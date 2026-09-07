"""Interactive WebGL QA Agent — uses KnowledgeBase + shared modules.

Usage:
  - Runs autonomously (login → tasks → lobby)
  - When stuck or needs help, pauses and watches cmd.txt for commands
  - Commands:
      click X Y        — click at coordinates
      type TEXT        — type text
      wait N           — wait N seconds
      drag X1 Y1 X2 Y2 — drag
      longpress X Y D  — long press at (X,Y) for D seconds
      screenshot       — take screenshot + Vision analysis
      vision PROMPT    — take screenshot + custom Vision prompt
      menu             — click menu (60,160) + screenshot
      upgrade          — run upgrade sequence from knowledge
      lock             — run lock card sequence from knowledge
      state            — print current parsed state
      continue         — resume auto mode
      quit             — exit
"""
import asyncio
import sys
import os
import json
from datetime import datetime
from pathlib import Path
from playwright._impl._errors import TargetClosedError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.agent import GameSession
from webgl_qa.vision import analyze_screenshot, analyze_screenshot_structured
from webgl_qa.parser import parse_vision
from webgl_qa.prompts import TASK_ANALYSIS_PROMPT, MENU_ANALYSIS_PROMPT
from webgl_qa.actions import (
    login_sequence, dismiss_popups, long_press_shoot, burst_shoot,
    upgrade_cannon, use_lock_card, click_menu, execute_steps,
)
from webgl_qa.knowledge_base import get_knowledge_base
from webgl_qa.perceiver import pixel_diff_ratio


# Adaptive observe thresholds
DIFF_SKIP_THRESHOLD = 0.02    # Below this: skip Vision entirely (screen unchanged)
DIFF_LIGHT_THRESHOLD = 0.15   # Below this: lightweight Vision (screen_id + task only)

# Default config
CMD_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cmd.txt")


class InteractiveAgent:
    """Encapsulates the interactive QA agent state and logic.

    All state that was previously in module globals is now instance attributes,
    enabling multiple concurrent sessions and unit testing.
    """

    def __init__(self, game_url: str, game_name: str, login_id: str,
                 headless: bool = True, cmd_file: str = CMD_FILE):
        self.game_url = game_url
        self.game_name = game_name
        self.login_id = login_id
        self.headless = headless
        self.cmd_file = cmd_file

        # Session state
        self.session: GameSession = None
        self.kb = None
        self.step_counter = 0
        self.shoot_burst_count = 0
        self.last_parsed: dict = {}
        self.last_screenshot_path: str = None
        self.consecutive_skips = 0

    async def observe_and_analyze(self, action_desc, prompt=None, force_vision=False):
        """Take screenshot + Vision analysis with adaptive observe.

        Adaptive strategy (only when in gameplay/shooting and no custom prompt):
        - diff < 0.02: skip Vision entirely (screen unchanged)
        - diff 0.02-0.15: lightweight Vision (screen_id + task only)
        - diff > 0.15 or force_vision: full Vision analysis

        Always calls Vision when: custom prompt, force_vision=True, or consecutive_skips >= 5.
        """
        self.step_counter += 1
        obs = await self.session.observe()
        path = obs["screenshot_path"]
        size = os.path.getsize(path)

        # Adaptive observe: compare with previous screenshot
        use_adaptive = (
            not force_vision
            and prompt is None
            and self.last_screenshot_path is not None
            and self.last_parsed.get("screen_id") in ("gameplay", "fishing", "fishing_game_active", "gameplay_fishing", "tutorial")
            and self.consecutive_skips < 5  # Force Vision after 5 consecutive skips
        )

        if use_adaptive:
            # Use session's cached numpy arrays instead of re-reading from disk
            curr_img = self.session._last_frame_array
            prev_img = getattr(self.session, '_prev_frame_for_adaptive', None)
            if curr_img is None or prev_img is None:
                # First frame or missing cache — skip adaptive, do full Vision
                use_adaptive = False
                diff = 1.0
            else:
                diff = pixel_diff_ratio(prev_img, curr_img)

            if diff < DIFF_SKIP_THRESHOLD:
                # Screen barely changed — skip Vision entirely
                self.consecutive_skips += 1
                self.last_screenshot_path = path
                self.session._prev_frame_for_adaptive = curr_img
                print(f"\n[Step {self.step_counter}] {action_desc} (skip Vision, diff={diff:.4f}, skips={self.consecutive_skips})", flush=True)
                return self.last_parsed

            elif diff < DIFF_LIGHT_THRESHOLD:
                # Minor change — use lightweight prompt
                prompt = (
                    "Quick check: what is the screen_id and current_task? "
                    "Respond in JSON: {\"screen_id\": \"...\", \"current_task\": \"...\", \"has_finger_indicator\": bool, \"has_reward_button\": bool}"
                )
                print(f"\n[Step {self.step_counter}] {action_desc} (light Vision, diff={diff:.4f})", flush=True)
            else:
                print(f"\n[Step {self.step_counter}] {action_desc} (full Vision, diff={diff:.4f})", flush=True)
        else:
            print(f"\n[Step {self.step_counter}] {action_desc}", flush=True)

        # Reset skip counter when we actually call Vision
        self.consecutive_skips = 0
        self.last_screenshot_path = path

        # Cache current frame for next adaptive comparison
        self.session._prev_frame_for_adaptive = self.session._last_frame_array

        # Use structured tool_use for default analysis, free-form for custom prompts
        if prompt is None:
            # Structured output — guaranteed JSON schema, no parsing fallback needed
            parsed = analyze_screenshot_structured(path)
        else:
            # Custom prompt — use free-form text + parser fallback
            raw = analyze_screenshot(path, prompt=prompt)
            parsed = parse_vision(raw)

        self.last_parsed = parsed

        print(f"  Screen: {parsed.get('screen_id', '?')} | Size: {size}", flush=True)
        desc = parsed.get('description', '')
        if desc:
            print(f"  Desc: {desc[:100]}", flush=True)
        task = parsed.get('current_task', '')
        if task:
            print(f"  Task: {task}", flush=True)
        progress = parsed.get('task_progress', '')
        if progress:
            print(f"  Progress: {progress}", flush=True)
        elements = parsed.get('elements', [])
        if elements:
            for el in elements[:6]:
                if not isinstance(el, dict):
                    continue
                loc = el.get('location', {})
                if not isinstance(loc, dict):
                    loc = {}
                print(f"    - {el.get('label', el.get('id','?'))} @ ({loc.get('x','?')},{loc.get('y','?')})", flush=True)
        if parsed.get('is_hall_switch'):
            print(f"  ★★★ HALL SWITCH ★★★", flush=True)
        if parsed.get('is_lobby'):
            print(f"  ★★★ LOBBY ★★★", flush=True)
        if parsed.get('anomalies'):
            print(f"  Anomalies: {parsed['anomalies']}", flush=True)

        return parsed

    async def do_login(self):
        """Login and dismiss popups. Returns parsed state."""
        print("=== LOGIN (debug mode) ===", flush=True)
        await login_sequence(self.session, self.login_id, mode="debug")
        print("Login submitted, dismissing popups...", flush=True)

        for i in range(8):
            parsed = await self.observe_and_analyze(f"Dismiss popup {i+1}")
            if parsed.get("screen_id") in ("gameplay", "fishing", "fishing_game_active"):
                break
            if parsed.get("is_hall_switch") or parsed.get("is_lobby"):
                break

            # Use KB-driven popup dismiss
            dismissed = await self._dismiss_popup_by_kb(parsed)
            if not dismissed:
                # Generic click center to dismiss any overlay
                await self.session.execute_action({"type": "click", "x": 640, "y": 400})
                await self.session.execute_action({"type": "wait", "seconds": 2})

        return self.last_parsed

    def _match_popup_type(self, parsed):
        """Match current screen against KB popup_types. Returns matching popup dict or None."""
        popups_system = self.kb.systems_by_id.get("popups") if self.kb else None
        if not popups_system:
            return None
        desc = (parsed.get("description", "") + " " + parsed.get("current_task", "")).lower()
        for popup_def in popups_system.get("popup_types", []):
            keywords = popup_def.get("keywords", [])
            if any(kw.lower() in desc for kw in keywords):
                return popup_def
        return None

    async def _dismiss_popup_by_kb(self, parsed):
        """Try to dismiss popup using KB popup_types. Returns True if handled."""
        popup_def = self._match_popup_type(parsed)
        if popup_def:
            steps = popup_def.get("dismiss", {}).get("steps", [])
            popup_name = popup_def.get("name", popup_def.get("id", "unknown"))
            print(f"  → KB popup match: {popup_name}", flush=True)
            for step in steps:
                await self.session.execute_action(step)
            return True

        # Fallback: look for close/X button in Vision elements
        if parsed.get("is_popup"):
            x, y = self._find_close_button(parsed)
            print(f"  → Popup dismiss click ({x},{y})", flush=True)
            await self.session.execute_action({"type": "click", "x": x, "y": y})
            await self.session.execute_action({"type": "wait", "seconds": 2})
            return True

        return False

    def _find_close_button(self, parsed):
        """Find close/X button in parsed elements. Returns (x, y)."""
        elements = parsed.get("elements", [])
        for el in elements:
            if not isinstance(el, dict):
                continue
            label = (el.get("label") or "").lower()
            el_id = (el.get("id") or "").lower()
            if any(kw in label or kw in el_id for kw in ["关闭", "關閉", "close", "x", "×"]):
                loc = el.get("location")
                if loc and isinstance(loc, dict):
                    return (loc.get("x", 640), loc.get("y", 400))
        # Fallback: suggested_click
        suggested = parsed.get("suggested_click", {})
        return (suggested.get("x", 640), suggested.get("y", 400))

    async def handle_command(self, cmd_line):
        """Process a command from cmd.txt. Returns True to resume auto."""
        parts = cmd_line.strip().split()
        if not parts:
            return False

        cmd = parts[0].lower()

        if cmd == "continue":
            print(">>> Resuming auto mode", flush=True)
            return True

        elif cmd == "quit":
            print(">>> Quitting", flush=True)
            sys.exit(0)

        elif cmd == "click" and len(parts) >= 3:
            x, y = int(parts[1]), int(parts[2])
            await self.session.execute_action({"type": "click", "x": x, "y": y})
            await self.session.execute_action({"type": "wait", "seconds": 1})
            await self.observe_and_analyze(f"Manual click ({x},{y})")

        elif cmd == "type" and len(parts) >= 2:
            text = " ".join(parts[1:])
            await self.session.execute_action({"type": "type", "text": text})
            await self.observe_and_analyze(f"Manual type: {text}")

        elif cmd == "wait" and len(parts) >= 2:
            secs = float(parts[1])
            await self.session.execute_action({"type": "wait", "seconds": secs})
            await self.observe_and_analyze(f"Wait {secs}s")

        elif cmd == "longpress" and len(parts) >= 4:
            x, y = int(parts[1]), int(parts[2])
            d = float(parts[3]) if len(parts) > 3 else 1.0
            await long_press_shoot(self.session, x, y, d)
            await self.session.execute_action({"type": "wait", "seconds": 1})
            await self.observe_and_analyze(f"Long press ({x},{y}) {d}s")

        elif cmd == "drag" and len(parts) >= 5:
            x1, y1, x2, y2 = int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])
            await self.session.execute_action({"type": "drag", "from_x": x1, "from_y": y1, "to_x": x2, "to_y": y2})
            await self.session.execute_action({"type": "wait", "seconds": 1})
            await self.observe_and_analyze(f"Drag ({x1},{y1})→({x2},{y2})")

        elif cmd == "screenshot" or cmd == "ss":
            await self.observe_and_analyze("Manual screenshot")

        elif cmd == "vision" and len(parts) >= 2:
            prompt = " ".join(parts[1:])
            await self.observe_and_analyze("Custom vision", prompt=prompt)

        elif cmd == "menu":
            await click_menu(self.session)
            await self.observe_and_analyze("Click menu (60,160)", prompt=MENU_ANALYSIS_PROMPT)

        elif cmd == "upgrade":
            print(">>> Running upgrade sequence (from knowledge)", flush=True)
            await upgrade_cannon(self.session)
            await self.observe_and_analyze("After upgrade sequence")

        elif cmd == "lock":
            print(">>> Running lock card sequence (from knowledge)", flush=True)
            await use_lock_card(self.session)
            await self.observe_and_analyze("After lock card sequence")

        elif cmd == "state":
            print(f">>> Last state: {json.dumps(self.last_parsed, ensure_ascii=False, indent=2)[:500]}", flush=True)

        elif cmd == "kb":
            print(f">>> {self.kb.summary()}", flush=True)

        else:
            print(f">>> Unknown command: {cmd_line.strip()}", flush=True)
            print(">>> Commands: click X Y | type TEXT | wait N | longpress X Y D | drag X1 Y1 X2 Y2", flush=True)
            print(">>>           screenshot | vision PROMPT | menu | upgrade | lock | state | kb | continue | quit", flush=True)

        return False

    async def wait_for_command(self):
        """Watch cmd.txt for commands. Returns when 'continue' is received."""
        print(f"\nWAITING> Write command to: {self.cmd_file}", flush=True)
        print(f"WAITING> (or 'continue' to resume auto)", flush=True)
        while True:
            if os.path.exists(self.cmd_file):
                try:
                    with open(self.cmd_file, "r", encoding="utf-8") as f:
                        line = f.read().strip()
                    if line:
                        with open(self.cmd_file, "w", encoding="utf-8") as f:
                            f.write("")
                        print(f">>> CMD: {line}", flush=True)
                        resume = await self.handle_command(line)
                        if resume:
                            return
                        print(f"WAITING> ", flush=True)
                except Exception:
                    pass
            await asyncio.sleep(0.5)

    async def try_menu_to_lobby(self):
        """KB-driven fast menu → lobby.

        Reads steps from knowledge/example_game/systems/lobby.yaml (enter_lobby action).
        Respects timing_critical + max_gap_ms + retry_attempts from YAML.
        """
        action_data = self.kb.systems_by_id.get("lobby", {}).get("actions", {}).get("enter_lobby", {})
        if not action_data:
            print("  [ERROR] KB has no lobby/enter_lobby action!", flush=True)
            await self.wait_for_command()
            return self.last_parsed

        steps = action_data.get("steps", [])
        attempts = action_data.get("retry_attempts", 5)
        verify_keywords = action_data.get("verify_keywords", ["lobby", "大廳", "大厅"])

        print(f"  Using KB enter_lobby ({attempts} attempts, {len(steps)} steps)...", flush=True)

        for i in range(attempts):
            # Execute steps (timing-critical: no Vision between them)
            for step in steps:
                step_type = step.get("type", "")
                if step_type == "click":
                    await self.session.execute_action({"type": "click", "x": step["x"], "y": step["y"]})
                elif step_type == "wait":
                    await asyncio.sleep(step.get("seconds", 1))

            # Verify with Vision
            obs = await self.session.observe()
            parsed = analyze_screenshot_structured(obs["screenshot_path"])
            screen_id = parsed.get("screen_id", "")
            desc = parsed.get("description", "")

            if any(kw in screen_id.lower() or kw in desc for kw in verify_keywords):
                print(f"\n★★★ LOBBY REACHED! (attempt {i+1}) ★★★", flush=True)
                self.last_parsed = parsed
                return parsed

            await asyncio.sleep(1)

        print("  go_to_lobby failed after all attempts. Entering manual mode.", flush=True)
        await self.wait_for_command()
        return self.last_parsed

    async def auto_iteration(self, parsed):
        """One iteration of auto mode. Uses KnowledgeBase for task routing."""

        # === Goal checks ===
        if parsed.get("is_hall_switch"):
            print("\n★★★ HALL SWITCH! Entering manual mode. ★★★", flush=True)
            await self.wait_for_command()
            return self.last_parsed

        if parsed.get("is_lobby"):
            print("\n★★★ LOBBY REACHED! ★★★", flush=True)
            await self.wait_for_command()
            return self.last_parsed

        # === Detect loading screen → hall transition ===
        # Read exclude keywords from KB (hall_switch.yaml detection.exclude_keywords)
        desc = parsed.get("description", "")
        screen_id = parsed.get("screen_id", "")
        hall_switch_sys = self.kb.systems_by_id.get("hall_switch", {})
        exclude_kws = hall_switch_sys.get("detection", {}).get("exclude_keywords", [])
        is_excluded = any(kw in desc or kw in screen_id for kw in exclude_kws)
        is_loading = (
            screen_id == "loading"
            or "載入" in desc
            or "加载" in desc
            or "歡迎來到" in desc
        )
        if is_loading and not is_excluded:
            print("\n★★★ LOADING SCREEN — Hall transition! ★★★", flush=True)
            print("  Waiting 15s for new scene to load...", flush=True)
            await self.session.execute_action({"type": "wait", "seconds": 15})
            await dismiss_popups(self.session, max_clicks=3)
            print("  Looking for menu button...", flush=True)
            return await self.try_menu_to_lobby()

        # === Detect menu button in new hall ===
        elements = parsed.get("elements", [])
        task_text = parsed.get("current_task", "")
        has_menu = any(
            isinstance(el, dict) and el.get("label", "") in ["菜单", "三", "menu", "☰", "菜單"]
            for el in elements
        )
        if has_menu and self.shoot_burst_count > 40 and not task_text:
            print("\n★ Menu button detected, no active task! Trying to find lobby...", flush=True)
            return await self.try_menu_to_lobby()

        # === Priority 1: Finger indicator ===
        if parsed.get("has_finger_indicator") and parsed.get("finger_location"):
            loc = parsed["finger_location"]
            await self.session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
            await self.session.execute_action({"type": "wait", "seconds": 2})
            return await self.observe_and_analyze(f"Click finger ({loc['x']},{loc['y']})")

        # === Priority 2: Reward button (skip if popup with close button — let popup dismiss handle it) ===
        if parsed.get("has_reward_button") and not parsed.get("is_popup"):
            suggested = parsed.get("suggested_click", {})
            x = suggested.get("x", 640)
            y = suggested.get("y", 400)
            await self.session.execute_action({"type": "click", "x": x, "y": y})
            await self.session.execute_action({"type": "wait", "seconds": 2})
            return await self.observe_and_analyze(f"Claim reward ({x},{y})")

        # === Priority 3: Task-specific (KnowledgeBase driven) ===
        task_text = parsed.get("current_task", "")

        if task_text:
            system_id, action_name, steps = self.kb.get_action_for_task(task_text)

            if system_id and action_name:
                print(f"  KB matched: {system_id}/{action_name}", flush=True)

                if action_name == "upgrade_cannon":
                    await upgrade_cannon(self.session)
                    return await self.observe_and_analyze("After upgrade")

                elif action_name == "use_lock_card":
                    print("  Lock card task!", flush=True)
                    await use_lock_card(self.session)
                    return await self.observe_and_analyze("After lock card")

                elif action_name == "burst_shoot":
                    burst = 8
                    print(f"  Shooting burst ({burst})...", flush=True)
                    await burst_shoot(self.session, count=burst, duration=0.8, interval=0.3)
                    self.shoot_burst_count += burst
                    await self.session.execute_action({"type": "wait", "seconds": 1})
                    return await self.observe_and_analyze(f"After {self.shoot_burst_count} total shots")

                elif steps:
                    # Execute steps from knowledge base
                    print(f"  Executing {len(steps)} steps from KB...", flush=True)
                    await execute_steps(self.session, steps)
                    return await self.observe_and_analyze(f"After KB steps ({system_id}/{action_name})")

        # === Priority 4: Gameplay — shoot ===
        if parsed.get("screen_id") in ("gameplay", "fishing", "fishing_game_active", "gameplay_fishing", "tutorial"):
            burst = 8
            print(f"  Shooting burst ({burst})...", flush=True)
            await burst_shoot(self.session, count=burst, duration=0.8, interval=0.3)
            self.shoot_burst_count += burst
            await self.session.execute_action({"type": "wait", "seconds": 1})
            return await self.observe_and_analyze(f"After {self.shoot_burst_count} total shots")

        # === Priority 5: Popup dismiss (KB-driven) ===
        if parsed.get("is_popup"):
            await self._dismiss_popup_by_kb(parsed)
            return await self.observe_and_analyze("After popup dismiss")

        # === Unknown — manual mode ===
        print(f"\n??? STUCK: unknown state. screen={parsed.get('screen_id')} task={task_text}", flush=True)
        print(f"    Entering manual mode.", flush=True)
        await self.wait_for_command()
        return self.last_parsed

    async def run(self):
        """Main entry point — launches browser, logs in, runs auto loop."""
        print("=" * 60, flush=True)
        print(f"Interactive WebGL QA Agent (Knowledge-Driven)", flush=True)
        print(f"Account: {self.login_id}", flush=True)
        print(f"URL: {self.game_url}", flush=True)
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        print("=" * 60, flush=True)

        # Load knowledge base
        self.kb = get_knowledge_base(self.game_name)
        print(f"\n{self.kb.summary()}", flush=True)
        print("=" * 60, flush=True)
        print("Commands (at WAITING> prompt):", flush=True)
        print("  click X Y | type TEXT | wait N | longpress X Y D", flush=True)
        print("  screenshot | vision PROMPT | menu | upgrade | lock", flush=True)
        print("  state | kb | continue | quit", flush=True)
        print("=" * 60, flush=True)

        self.session = GameSession(game_url=self.game_url, game_name=self.game_name, headless=self.headless)

        try:
            result = await self.session.start()
            print(f"Canvas: {result.get('canvas')}", flush=True)

            # Login
            parsed = await self.do_login()

            # Auto loop
            print(f"\n{'#'*60}", flush=True)
            print(f"# AUTO MODE — knowledge-driven, pauses when stuck", flush=True)
            print(f"{'#'*60}", flush=True)

            max_iterations = 200
            stuck_count = 0
            last_task = ""

            for iteration in range(max_iterations):
                # Check cmd.txt mid-auto (allows AI to interrupt auto mode)
                if os.path.exists(self.cmd_file):
                    try:
                        with open(self.cmd_file, "r", encoding="utf-8") as f:
                            cmd_line = f.read().strip()
                        if cmd_line:
                            with open(self.cmd_file, "w", encoding="utf-8") as f:
                                f.write("")
                            print(f">>> CMD (mid-auto): {cmd_line}", flush=True)
                            resume = await self.handle_command(cmd_line)
                            if not resume:
                                # Command handled, stay in manual mode
                                await self.wait_for_command()
                            parsed = self.last_parsed
                    except Exception:
                        pass

                print(f"\n--- Auto iteration {iteration+1} ---", flush=True)

                # Stuck detection
                current_task = parsed.get("current_task", "")
                if current_task == last_task and current_task:
                    stuck_count += 1
                else:
                    stuck_count = 0
                    last_task = current_task

                if stuck_count >= 5:
                    print(f"\n!!! STUCK on same task for 5 iterations: {current_task}", flush=True)
                    # Check known issues from KB
                    system_id, _, _ = self.kb.get_action_for_task(current_task)
                    if system_id:
                        issues = self.kb.get_known_issues(system_id)
                        if issues:
                            print(f"  Known issues for {system_id}:", flush=True)
                            for issue in issues:
                                print(f"    - {issue.get('id')}: {issue.get('description', '')[:80]}", flush=True)
                    # Try find_solution from problems/
                    solution = self.kb.find_solution([current_task, parsed.get("description", "")])
                    if solution:
                        print(f"  Matched problem: {solution.get('title', '')}", flush=True)
                        print(f"  Solution: {solution.get('solution', '')[:120]}", flush=True)
                    print(f"    Entering manual mode.", flush=True)
                    await self.wait_for_command()
                    parsed = self.last_parsed
                    stuck_count = 0
                    continue

                try:
                    parsed = await self.auto_iteration(parsed)
                except TargetClosedError:
                    print("\n!!! BROWSER CLOSED — attempting recovery...", flush=True)
                    try:
                        # Restart browser and re-login
                        self.session = GameSession(game_url=self.game_url, game_name=self.game_name, headless=self.headless)
                        result = await self.session.start()
                        print(f"  Browser restarted. Canvas: {result.get('canvas')}", flush=True)
                        print("  Re-logging in...", flush=True)
                        await login_sequence(self.session, self.login_id, mode="debug")
                        await dismiss_popups(self.session, max_clicks=5)
                        parsed = await self.observe_and_analyze("After browser recovery")
                        print("  ★ Recovery successful!", flush=True)
                    except Exception as recovery_err:
                        print(f"  ✗ Recovery failed: {recovery_err}", flush=True)
                        print(f"    Entering manual mode.", flush=True)
                        await self.wait_for_command()
                        parsed = self.last_parsed
                    continue
                except Exception as e:
                    print(f"\n!!! UNEXPECTED ERROR: {e}", flush=True)
                    print(f"    Entering manual mode.", flush=True)
                    await self.wait_for_command()
                    parsed = self.last_parsed
                    continue

                # Check if we reached lobby
                if parsed.get("is_lobby"):
                    print("\n★★★ LOBBY REACHED! Goal complete! ★★★", flush=True)
                    break

            print(f"\n{'='*60}", flush=True)
            print(f"SESSION ENDED", flush=True)
            print(f"Steps: {self.step_counter} | Shots: {self.shoot_burst_count}", flush=True)
            print(f"Run dir: {self.session.run_dir}", flush=True)
            print(f"{'='*60}", flush=True)

            # Keep alive for manual exploration
            print("\nSession still alive. Enter commands or 'quit':", flush=True)
            await self.wait_for_command()

        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n\nShutting down gracefully...", flush=True)
        except Exception as e:
            print(f"\n\nFATAL ERROR: {e}", flush=True)
        finally:
            if self.session:
                try:
                    result = await self.session.finish()
                    print(f"Report saved: {result.get('report_path', 'N/A')}", flush=True)
                except Exception:
                    print("Failed to generate final report.", flush=True)
                # Ensure browser is closed even if finish() fails
                try:
                    await self.session.browser.close()
                except Exception:
                    pass


async def main():
    """Entry point — creates and runs an InteractiveAgent."""
    agent = InteractiveAgent(
        game_url=os.environ.get("GAME_URL", ""),
        game_name="example_game",
        login_id=os.environ.get("LOGIN_ID", ""),
        headless=True,
    )
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
