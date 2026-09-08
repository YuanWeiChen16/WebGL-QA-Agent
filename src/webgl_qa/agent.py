"""Agent — the core session loop for WebGL QA.

This module provides the GameSession class which manages:
- Driver lifecycle (browser, device, ...)
- Step-by-step screenshot → action → observe cycle
- Knowledge accumulation
- Bug detection
- Report generation

The session talks to the target only through a Driver, so the perception,
oracle, knowledge and reporting layers below are platform-independent.
"""

import asyncio
import atexit
import json
import weakref
from pathlib import Path
from datetime import datetime
from typing import Optional

from .browser import GameBrowser
from .driver import CAP_CONSOLE, CAP_PERFORMANCE, CAP_SCROLL, Driver
from .knowledge_base import KnowledgeBase
from .config import get_config, Config
from .detector import BugDetector
from .oracle import Oracle
from .reporter import Reporter
from .perceiver import is_frozen, is_blank_screen, pixel_diff_ratio, decode_to_array


class GameSession:
    """Manages a single QA session against a WebGL game.

    Designed to be driven externally (Hermes Agent or script).
    Each method returns structured data for the caller to reason about.
    """

    def __init__(self, game_url: str, project_dir: str = None,
                 game_name: str = None, headless: bool = None,
                 driver: Optional[Driver] = None):
        """Start a QA session against ``game_url``.

        Args:
            driver: Drives the target. Defaults to a Chromium GameBrowser;
                pass an AdbDevice (or any other Driver) to run the same
                session against a different platform. ``headless`` and the
                browser viewport config apply only to the default driver.
        """
        self.game_url = game_url
        self.project_dir = Path(project_dir) if project_dir else Path(__file__).resolve().parent.parent.parent
        self.game_name = game_name or self._url_to_name(game_url)

        # Load config (default.yaml merged with game_info.yaml)
        self.config: Config = get_config(self.game_name)

        # Session timestamp (used as run folder name)
        self._session_start = datetime.now()
        self._run_timestamp = self._session_start.strftime("%Y%m%d_%H%M%S")

        # Paths — all outputs go under runs/<game>/<timestamp>/
        self.run_dir = self.project_dir / "runs" / self.game_name / self._run_timestamp
        self.screenshots_dir = self.run_dir / "screenshots"
        self.knowledge_dir = self.project_dir / "knowledge" / self.game_name

        # Create dirs
        for d in [self.screenshots_dir, self.knowledge_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # Components
        if driver is not None:
            self.driver: Driver = driver
        else:
            if headless is None:
                headless = self.config.get("browser.headless", True)
            self.driver = GameBrowser(
                headless=headless,
                viewport_width=self.config.get("browser.viewport_width", 1280),
                viewport_height=self.config.get("browser.viewport_height", 720),
            )
        # Kept for callers written against the browser-only API.
        self.browser = self.driver
        self.knowledge = KnowledgeBase(self.game_name, base_dir=self.knowledge_dir)
        self.detector = BugDetector(config=self.config)
        self.oracle = Oracle(config=self.config)
        self.reporter = Reporter(self.run_dir)

        # Session state
        self.step_count = 0
        self.current_screen_id: Optional[str] = None
        self._last_screenshot_b64: Optional[str] = None
        self._last_frame_array = None  # cached decoded numpy array
        self._action_history: list[dict] = []
        self._last_game_state: dict = {}  # most recent Vision-read numeric state
        self._noop_streaks: dict = {}     # action signature -> consecutive no-effect count

        # A run directory with screenshots but no session.json is useless to
        # every downstream tool, and that is exactly what a crash or Ctrl+C
        # leaves behind. Track live sessions so the process-exit hook can
        # still write an "aborted" session.json and report for them.
        self._finished = False
        _live_sessions.add(self)

    def abort(self, reason: str = "aborted") -> Optional[dict]:
        """Persist what this session has so far without a clean ``finish()``.

        Synchronous on purpose: it must work from an ``except`` block, from a
        ``finally`` after the event loop is gone, and from the interpreter's
        exit hook. It writes ``session.json`` with ``status: "aborted"``,
        renders the report, saves runtime knowledge, and never raises. The
        driver is not closed here (that needs the event loop); the process is
        ending or the caller is about to do it. Returns the session log, or
        None if the session already finished.
        """
        if self._finished:
            return None
        self._finished = True
        _live_sessions.discard(self)

        session_log: dict = {}
        try:
            self.reporter.add_step(action="aborted", description=f"Session aborted: {reason}",
                                   screen_id=self.current_screen_id)
            self.reporter.generate(game_url=self.game_url,
                                   flow_summary=self.knowledge.get_runtime_flow_summary())
        except Exception:
            pass  # a partial report is better than none; keep going to the log
        try:
            session_log = self.reporter.generate_session_log()
            session_log.update({
                "status": "aborted",
                "abort_reason": reason,
                "game_url": self.game_url,
                "game_name": self.game_name,
                "duration_seconds": (datetime.now() - self._session_start).total_seconds(),
                "total_steps": self.step_count,
                "action_history": self._action_history,
            })
            (self.run_dir / "session.json").write_text(
                json.dumps(session_log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            self.knowledge.save_runtime()
        except Exception:
            pass
        return session_log

    @staticmethod
    def _url_to_name(url: str) -> str:
        """Convert URL to a safe directory name."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        name = parsed.netloc.replace(".", "_").replace(":", "_")
        if parsed.path and parsed.path != "/":
            name += parsed.path.replace("/", "_").rstrip("_")
        return name[:60]

    async def start(self) -> dict:
        """Launch browser and navigate to game. Returns initial state."""
        await self.driver.launch(self.game_url)
        self.knowledge.set_game_info(self.game_url, self.game_name)

        # Wait for WebGL to initialize (from config)
        init_wait = self.config.get("timing.webgl_init_wait", 5)
        await asyncio.sleep(init_wait)

        # Take initial screenshot
        screenshot_path = str(self.screenshots_dir / "initial.png")
        b64 = await self.driver.screenshot(screenshot_path)
        self._last_screenshot_b64 = b64
        self._last_frame_array = decode_to_array(b64)

        # Get canvas info
        canvas = await self.driver.get_viewport_size()

        # Check for immediate issues
        blank = is_blank_screen(self._last_frame_array)

        self.reporter.add_step(
            action="launch",
            description=f"Opened {self.game_url}",
            screenshot_path=screenshot_path,
        )

        return {
            "status": "launched",
            "screenshot_path": screenshot_path,
            "canvas": canvas,
            "blank_screen": blank,
            "console_errors": len(self.driver.get_errors()),
            "known_screens": self.knowledge.get_known_screen_ids(),
            "flow_summary": self.knowledge.get_runtime_flow_summary(),
        }

    async def observe(self) -> dict:
        """Take a screenshot and run anomaly checks. Returns observation data."""
        self.step_count += 1
        timestamp = datetime.now().strftime("%H%M%S")
        screenshot_path = str(self.screenshots_dir / f"step_{self.step_count:04d}_{timestamp}.png")
        b64 = await self.driver.screenshot(screenshot_path)

        # Decode once, reuse everywhere
        current_array = decode_to_array(b64)

        # Instrumentation is capability-gated: a driver whose platform cannot
        # observe console output or heap usage contributes nothing here, and
        # the frame-based checks below still run.
        console_logs: list[dict] = []
        errors: list[dict] = []
        if CAP_CONSOLE in self.driver.capabilities:
            console_logs = self.driver.get_console_logs(clear=True)
            errors = self.driver.get_errors(clear=True)

        perf_metrics: dict = {}
        if CAP_PERFORMANCE in self.driver.capabilities:
            try:
                perf_metrics = await self.driver.get_performance_metrics()
            except Exception:
                perf_metrics = {}

        anomalies = self.detector.run_all_checks(current_array, errors, perf_metrics)

        # Check pixel diff from last frame (using cached arrays)
        diff_ratio = 0.0
        if self._last_frame_array is not None:
            diff_ratio = pixel_diff_ratio(self._last_frame_array, current_array)

        self._last_screenshot_b64 = b64
        self._last_frame_array = current_array

        result = {
            "step": self.step_count,
            "screenshot_path": screenshot_path,
            "pixel_change_ratio": round(diff_ratio, 4),
            "anomalies": [{"type": a.type, "severity": a.severity, "description": a.description} for a in anomalies],
            "console_logs": console_logs[-10:],  # Last 10 logs
            "console_errors": [{"message": e["message"]} for e in errors],
            "current_screen": self.current_screen_id,
        }

        # Record in reporter
        self.reporter.add_step(
            action="observe",
            screen_id=self.current_screen_id,
            screenshot_path=screenshot_path,
            anomalies=[a.description for a in anomalies],
        )
        if errors:
            self.reporter.add_console_errors(len(errors))

        return result

    async def execute_action(self, action: dict) -> dict:
        """Execute an action decided by Hermes.
        
        Supported actions:
        - {"type": "click", "x": int, "y": int}
        - {"type": "double_click", "x": int, "y": int}
        - {"type": "drag", "from_x": int, "from_y": int, "to_x": int, "to_y": int}
        - {"type": "key", "key": str}
        - {"type": "type", "text": str}
        - {"type": "wait", "seconds": float}
        - {"type": "scroll", "x": int, "y": int, "delta_y": int}
        """
        action_type = action.get("type")
        description = ""

        try:
            if action_type == "click":
                await self.driver.click(action["x"], action["y"])
                description = f"Click at ({action['x']}, {action['y']})"
            elif action_type == "double_click":
                await self.driver.double_click(action["x"], action["y"])
                description = f"Double-click at ({action['x']}, {action['y']})"
            elif action_type == "drag":
                await self.driver.drag(action["from_x"], action["from_y"], action["to_x"], action["to_y"])
                description = f"Drag from ({action['from_x']},{action['from_y']}) to ({action['to_x']},{action['to_y']})"
            elif action_type == "key":
                await self.driver.key_press(action["key"])
                description = f"Press key: {action['key']}"
            elif action_type == "type":
                await self.driver.type_text(action["text"])
                description = f"Type: {action['text']}"
            elif action_type == "wait":
                await self.driver.wait(action.get("seconds", 1))
                description = f"Wait {action.get('seconds', 1)}s"
            elif action_type == "scroll":
                x, y = action.get("x", 640), action.get("y", 360)
                if CAP_SCROLL not in self.driver.capabilities:
                    return {"status": "error",
                            "message": f"{self.driver.name} driver does not support scroll"}
                await self.driver.scroll(x, y, action.get("delta_y", -100))
                description = f"Scroll at ({x},{y})"
            else:
                return {"status": "error", "message": f"Unknown action type: {action_type}"}

            # Configurable cooldown after action
            cooldown = self.config.get("timing.action_cooldown", 0.5)
            await asyncio.sleep(cooldown)

            self._action_history.append({
                "step": self.step_count,
                "action": action,
                "description": description,
                "timestamp": datetime.now().isoformat(),
            })

            self.reporter.add_step(
                action=description,
                screen_id=self.current_screen_id,
            )

            result = {"status": "ok", "description": description}

            # Post-action assertion (AD-4): verify the screen actually reacted.
            # Deterministic, no Vision — a screenshot + pixel diff against the
            # pre-action frame. Repeatedly ineffective identical actions are the
            # classic stuck-loop signature (e.g. clicking the same button while
            # progress stays 2/3) and get flagged so the caller can stop.
            if action_type != "wait":
                effect = await self._verify_action_effect(action_type, action, description)
                if effect is not None:
                    result["effect"] = effect

            return result

        except Exception as e:
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _action_signature(action_type: str, action: dict) -> str:
        """Stable signature for 'the same action repeated' (10px position grid)."""
        def grid(v):
            try:
                return int(v) // 10 * 10
            except (TypeError, ValueError):
                return v
        if action_type in ("click", "double_click", "scroll"):
            return f"{action_type}@{grid(action.get('x'))},{grid(action.get('y'))}"
        if action_type == "drag":
            return (f"drag@{grid(action.get('from_x'))},{grid(action.get('from_y'))}"
                    f"->{grid(action.get('to_x'))},{grid(action.get('to_y'))}")
        if action_type == "key":
            return f"key@{action.get('key')}"
        return action_type

    async def _verify_action_effect(self, action_type: str, action: dict,
                                    description: str) -> Optional[dict]:
        """Screenshot after an action and check the screen visibly changed.

        Returns {"changed", "pixel_diff", "consecutive_noop", "blocked"} or None
        when verification is disabled / not possible (no pre-action frame).
        Tracks consecutive no-effect repeats per action signature; at
        max_consecutive_noop the loop is flagged as a candidate anomaly and
        "blocked": True tells the caller to stop repeating this action.
        """
        cfg = self.config.get_section("action_verify")
        if not cfg.get("enabled", True):
            return None
        if self._last_frame_array is None:
            return None

        min_diff = cfg.get("min_pixel_diff", 0.005)
        max_noop = cfg.get("max_consecutive_noop", 3)

        try:
            b64 = await self.driver.screenshot()
        except Exception:
            return None   # verification is best-effort; never fail the action

        new_frame = decode_to_array(b64)
        diff = pixel_diff_ratio(self._last_frame_array, new_frame)
        changed = diff >= min_diff

        # Keep the freshest frame so observe()'s own diff stays meaningful.
        self._last_screenshot_b64 = b64
        self._last_frame_array = new_frame

        sig = self._action_signature(action_type, action)
        if changed:
            self._noop_streaks.pop(sig, None)
            noop = 0
        else:
            noop = self._noop_streaks.get(sig, 0) + 1
            self._noop_streaks[sig] = noop

        blocked = (not changed) and noop >= max_noop
        if blocked and noop == max_noop:   # flag once per streak, at the threshold
            from .detector import Anomaly
            anomaly = Anomaly(
                type="no_effect_loop",
                severity="medium",
                description=(f"動作連續 {noop} 次無畫面反應（疑似卡關循環）: {description} "
                             f"(pixel_diff={diff:.4f} < {min_diff})"),
                evidence={"action_signature": sig, "consecutive_noop": noop,
                          "pixel_diff": round(diff, 4)},
            )
            self.detector.anomalies.append(anomaly)
            self.reporter.add_step(
                action="no_effect_loop",
                description=anomaly.description,
                screen_id=self.current_screen_id,
            )

        return {
            "changed": changed,
            "pixel_diff": round(diff, 4),
            "consecutive_noop": noop,
            "blocked": blocked,
        }

    def identify_screen(self, commit: bool = True) -> dict:
        """Identify the current screen from knowledge-base anchors, without Vision.

        Uses the last captured frame (call ``observe()`` first). A confident
        match becomes ``current_screen_id`` when ``commit`` is True, giving the
        session a canonical, deterministic screen key; an ambiguous or unknown
        frame leaves it untouched and returns ``system_id: None``.
        """
        if self._last_frame_array is None:
            return {"system_id": None, "best": None, "confidence": 0.0,
                    "ambiguous": False, "scores": {}, "reason": "no frame captured yet"}
        result = self.knowledge.identify_system(self._last_frame_array)
        if commit and result.get("system_id"):
            self.current_screen_id = result["system_id"]
        return result

    def update_screen(self, screen_id: str, description: str, elements: list = None) -> dict:
        """Update knowledge about the current screen (called after analysis)."""
        prev_screen = self.current_screen_id

        # Save reference screenshot into screenshots dir
        ref_path = str(self.screenshots_dir / f"{screen_id}_ref.png")
        if self._last_screenshot_b64:
            import base64
            Path(ref_path).parent.mkdir(parents=True, exist_ok=True)
            Path(ref_path).write_bytes(base64.b64decode(self._last_screenshot_b64))

        # Update knowledge (store relative path for portability)
        knowledge_ref = f"screenshots/{screen_id}_ref.png"
        self.knowledge.add_runtime_screen(screen_id, description, elements, knowledge_ref)

        # Record transition if screen changed
        if prev_screen and prev_screen != screen_id and self._action_history:
            last_action = self._action_history[-1]
            self.knowledge.add_runtime_transition(prev_screen, screen_id, last_action["description"])

        self.current_screen_id = screen_id
        self.knowledge.save_runtime()

        return {
            "status": "ok",
            "screen_id": screen_id,
            "is_new": prev_screen != screen_id,
            "transition_from": prev_screen,
        }

    def report_bug(self, description: str, severity: str = "medium") -> dict:
        """Report a bug found during this session."""
        repro = [a["description"] for a in self._action_history[-5:]]
        evidence = []
        if self._last_screenshot_b64:
            bug_count = len(self.knowledge._runtime_data.get("bugs", []))
            bug_screenshot = str(self.screenshots_dir / f"bug_{bug_count + 1:03d}.png")
            import base64
            Path(bug_screenshot).write_bytes(base64.b64decode(self._last_screenshot_b64))
            evidence.append(bug_screenshot)

        bug_id = self.knowledge.add_bug(
            screen_id=self.current_screen_id or "unknown",
            description=description,
            severity=severity,
            repro_steps=repro,
            evidence=evidence,
        )
        self.knowledge.save_runtime()
        self.reporter.add_bug({"id": bug_id, "description": description, "severity": severity, "repro_steps": repro})

        return {"bug_id": bug_id, "severity": severity}

    def record_game_state(self, game_state: dict) -> dict:
        """Store the numeric game state read by Vision (score/currency/level/lives).

        Call this after each structured Vision analysis so that
        check_invariants() can compare before/after around an action.
        """
        self._last_game_state = dict(game_state) if isinstance(game_state, dict) else {}
        return {"status": "ok", "game_state": self._last_game_state}

    @property
    def last_game_state(self) -> dict:
        """Most recent Vision-read numeric state (for before/after oracle checks)."""
        return dict(self._last_game_state)

    async def check_invariants(self, action_tag: str, before_state: dict,
                               after_state: dict, flags: dict = None,
                               reread=None) -> dict:
        """Run functional-correctness invariants for an action (Vision-based oracle).

        The caller reads game_state (via Vision) before and after an action, then
        calls this. Two guards keep Vision misreads / live-server randomness from
        becoming fake bugs:

        1. Double-check (sensor guard): if ``reread`` is given and the first pass
           finds violations, ``reread`` is awaited to obtain a FRESH
           (after_state, flags) — i.e. re-screenshot + re-analyze. Only invariants
           violated on BOTH reads survive; a Vision digit-misread rarely repeats
           identically on a second frame.
        2. min_occurrences (race guard): each invariant may require N consecutive
           violation observations (declared in game_info.yaml) before it is
           confirmed. Below N it is recorded as a *candidate*, not a bug.

        Args:
            action_tag: Label of the action just performed, e.g. "upgrade", "shoot".
            before_state: game_state dict read before the action.
            after_state: game_state dict read after the action.
            flags: Optional context flags, e.g. {"reward_detected": True}.
            reread: Optional async callable () -> (after_state2: dict, flags2: dict).
                Typically: screenshot + analyze_screenshot_structured, returning
                (result["game_state"], {"reward_detected": result["reward_detected"]}).

        Returns:
            {"action_tag", "checked", "double_checked",
             "violations":  [ {invariant, bug_id, severity, description, occurrence} ],
             "candidates":  [ {invariant, severity, description, occurrence, min_occurrences} ]}
        """
        before_state = before_state or {}
        after_state = after_state or {}
        flags = flags or {}

        # Pass 1 — pure evaluation (no streak/list side effects yet).
        raw = self.oracle.check_action(action_tag, before_state, after_state,
                                       flags, record=False)

        double_checked = False
        final_after, final_flags = after_state, flags
        surviving_ids = None   # None = no filter (no reread performed)

        if raw and callable(reread):
            # Pass 2 — fresh read; keep only invariants violated on BOTH reads.
            try:
                after2, flags2 = await reread()
                after2, flags2 = after2 or {}, flags2 or {}
                double_checked = True
                final_after, final_flags = after2, flags2
                recheck = self.oracle.check_action(action_tag, before_state,
                                                   after2, flags2, record=False)
                ids1 = {v.evidence.get("invariant") for v in raw}
                ids2 = {v.evidence.get("invariant") for v in recheck}
                surviving_ids = ids1 & ids2
            except Exception:
                # reread failed (screenshot/Vision error) — fall back to single read.
                pass

        # Pass 3 — recorded evaluation on the freshest state: updates streaks,
        # classifies each violation as confirmed (>= min_occurrences) or candidate.
        recorded = self.oracle.check_action(action_tag, before_state,
                                            final_after, final_flags, record=True)

        reported, candidates = [], []
        for v in recorded:
            inv_id = v.evidence.get("invariant")
            if surviving_ids is not None and inv_id not in surviving_ids:
                continue   # failed the double-check → discard as sensor noise
            entry = {
                "invariant": inv_id,
                "severity": v.severity,
                "description": v.description,
                "occurrence": v.evidence.get("occurrence"),
                "min_occurrences": v.evidence.get("min_occurrences"),
            }
            if v.evidence.get("confirmed"):
                # Surface in the anomaly summary produced at finish()
                self.detector.anomalies.append(v)
                bug = self.report_bug(v.description, v.severity)
                entry["bug_id"] = bug["bug_id"]
                reported.append(entry)
            else:
                # Candidate: visible in the report timeline, not filed as a bug.
                self.reporter.add_step(
                    action="oracle_candidate",
                    description=f"{v.description} (occurrence "
                                f"{entry['occurrence']}/{entry['min_occurrences']})",
                    screen_id=self.current_screen_id,
                )
                candidates.append(entry)

        return {
            "action_tag": action_tag,
            "checked": self.oracle.applicable_count(action_tag),
            "double_checked": double_checked,
            "violations": reported,
            "candidates": candidates,
        }

    async def finish(self) -> dict:
        """End the session, generate report, save everything."""
        # Generate report (saved as report.html in run_dir)
        report_path = self.reporter.generate(
            game_url=self.game_url,
            flow_summary=self.knowledge.get_runtime_flow_summary(),
        )

        # Save session log (saved as session.json in run_dir)
        session_log = self.reporter.generate_session_log()
        session_log["status"] = "completed"
        session_log["game_url"] = self.game_url
        session_log["game_name"] = self.game_name
        session_log["duration_seconds"] = (datetime.now() - self._session_start).total_seconds()
        session_log["total_steps"] = self.step_count
        session_log["action_history"] = self._action_history

        session_path = self.run_dir / "session.json"
        session_path.write_text(json.dumps(session_log, ensure_ascii=False, indent=2), encoding="utf-8")

        # Save final knowledge
        self.knowledge.save_runtime()

        # This session no longer needs the exit hook.
        self._finished = True
        _live_sessions.discard(self)

        # Close browser
        await self.driver.close()

        anomaly_summary = self.detector.get_summary()

        return {
            "run_dir": str(self.run_dir),
            "report_path": report_path,
            "session_log_path": str(session_path),
            "total_steps": self.step_count,
            "screens_found": list(self.reporter.screens_found),
            "bugs_found": len(self.reporter.bugs),
            "anomalies": anomaly_summary,
            "oracle": self.oracle.get_summary(),
            "flow_summary": self.knowledge.get_runtime_flow_summary(),
        }


# --- Process-exit safety net -------------------------------------------------

#: Sessions that have been created but not yet finished or aborted. Weak so
#: that a session dropped by its owner is not kept alive just for the hook.
_live_sessions: "weakref.WeakSet[GameSession]" = weakref.WeakSet()


def _flush_live_sessions_at_exit() -> None:
    """Write an aborted session.json for any session the process left open.

    Runs at interpreter shutdown (normal exit, unhandled exception, Ctrl+C
    reaching the top level). Not on a hard kill — nothing can help there.
    """
    for session in list(_live_sessions):
        try:
            session.abort("process exited before finish() was called")
        except Exception:
            pass


atexit.register(_flush_live_sessions_at_exit)


# --- Convenience functions for Hermes to call via execute_code ---

_session: Optional[GameSession] = None


def get_session() -> GameSession:
    """Get the current active session."""
    if _session is None:
        raise RuntimeError("No active session. Call start_session() first.")
    return _session


async def start_session(game_url: str, game_name: str = None, headless: bool = None) -> dict:
    """Start a new QA session. Returns initial state."""
    global _session
    _session = GameSession(game_url=game_url, game_name=game_name, headless=headless)
    return await _session.start()


async def observe() -> dict:
    """Take a screenshot and check for anomalies."""
    return await get_session().observe()


async def act(action: dict) -> dict:
    """Execute an action."""
    return await get_session().execute_action(action)


async def identify_screen(commit: bool = True) -> dict:
    """Identify the current screen from knowledge-base anchors (no Vision)."""
    return get_session().identify_screen(commit=commit)


async def update_screen(screen_id: str, description: str, elements: list = None) -> dict:
    """Update knowledge about current screen."""
    return get_session().update_screen(screen_id, description, elements)


async def report_bug(description: str, severity: str = "medium") -> dict:
    """Report a bug."""
    return get_session().report_bug(description, severity)


async def record_game_state(game_state: dict) -> dict:
    """Store the numeric game state read by Vision (for the oracle)."""
    return get_session().record_game_state(game_state)


async def check_invariants(action_tag: str, before_state: dict,
                           after_state: dict, flags: dict = None,
                           reread=None) -> dict:
    """Run the Vision-based functional oracle for an action."""
    return await get_session().check_invariants(action_tag, before_state,
                                                after_state, flags, reread=reread)


async def finish_session() -> dict:
    """End session and generate report."""
    global _session
    result = await get_session().finish()
    _session = None
    return result
