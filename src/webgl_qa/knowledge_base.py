"""KnowledgeBase — the single unified knowledge system for a game.

Combines two layers behind one interface:
- Static YAML knowledge: game_info.yaml, systems/*.yaml, flow_graph.yaml,
  problems/*.md (human-maintained, version-controlled).
- Dynamic runtime layer: screens/transitions/bugs discovered during a session,
  persisted to knowledge.yaml (the *_runtime methods below).

There is no separate KnowledgeStore anymore; this class replaces it.

Usage:
    kb = KnowledgeBase("example_game")
    system = kb.find_system_for_task("提升等級至 2")
    steps = kb.get_action_sequence("upgrade", "upgrade_cannon")
    path = kb.get_path("gameplay_hall1", "lobby")
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge"


class KnowledgeBase:
    """Structured knowledge base for a game, loaded from YAML files."""

    def __init__(self, game_name: str, base_dir: Path = None):
        self.game_name = game_name
        self.base_dir = base_dir or (KNOWLEDGE_DIR / game_name)
        self.game_info = {}
        self.systems = []
        self.systems_by_id = {}
        self.flow_graph = {"nodes": [], "edges": []}
        self.problems = []  # Parsed problem documents
        self._anchor_cache: dict = {}  # anchor image path -> decoded RGB array
        self._load()

    def _load(self):
        """Load all knowledge files."""
        # Game info
        game_info_path = self.base_dir / "game_info.yaml"
        if game_info_path.exists():
            self.game_info = self._load_yaml(game_info_path)

        # Systems
        systems_dir = self.base_dir / "systems"
        if systems_dir.exists():
            for yaml_file in sorted(systems_dir.glob("*.yaml")):
                system = self._load_yaml(yaml_file)
                if system:
                    self.systems.append(system)
                    sys_id = system.get("system_id", yaml_file.stem)
                    self.systems_by_id[sys_id] = system

        # Flow graph
        flow_path = self.base_dir / "flow_graph.yaml"
        if flow_path.exists():
            self.flow_graph = self._load_yaml(flow_path) or {"nodes": [], "edges": []}

        # Problems
        self._load_problems()

        # Runtime dynamic layer
        self._load_runtime()

        logger.info(f"Loaded knowledge for '{self.game_name}': {len(self.systems)} systems, "
                    f"{len(self.flow_graph.get('edges', []))} edges, {len(self.problems)} problems")

    def _load_yaml(self, path: Path) -> dict:
        """Load a YAML file safely."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return {}

    def _load_problems(self):
        """Load problems/*.md as structured problem database."""
        import re
        problems_dir = self.base_dir / "problems"
        if not problems_dir.exists():
            return

        for md_file in sorted(problems_dir.glob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
                problem = self._parse_problem_md(md_file.stem, content)
                if problem:
                    self.problems.append(problem)
            except Exception as e:
                logger.error(f"Failed to load problem {md_file}: {e}")

    def _parse_problem_md(self, file_id: str, content: str) -> Optional[dict]:
        """Parse a problem markdown file into structured dict.

        Expected sections: ## 症狀, ## 根本原因, ## 解法, ## 狀態
        """
        import re
        problem = {
            "id": file_id,
            "title": "",
            "symptoms": [],
            "root_cause": "",
            "solution": "",
            "status": "open",
            "notes": [],
        }

        # Extract title from first # heading
        title_match = re.search(r'^#\s+(?:問題[：:]?\s*)?(.+)$', content, re.MULTILINE)
        if title_match:
            problem["title"] = title_match.group(1).strip()

        # Extract symptoms section
        symptoms_match = re.search(
            r'##\s*症狀\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if symptoms_match:
            lines = symptoms_match.group(1).strip().split("\n")
            problem["symptoms"] = [
                line.lstrip("- ").strip() for line in lines
                if line.strip() and line.strip().startswith("-")
            ]

        # Extract root cause
        cause_match = re.search(
            r'##\s*根本原因\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if cause_match:
            problem["root_cause"] = cause_match.group(1).strip()

        # Extract solution
        solution_match = re.search(
            r'##\s*解法\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if solution_match:
            problem["solution"] = solution_match.group(1).strip()

        # Extract status
        status_match = re.search(
            r'##\s*狀態\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if status_match:
            status_text = status_match.group(1).strip()
            if "已修復" in status_text or "✅" in status_text:
                problem["status"] = "resolved"
            elif "進行中" in status_text:
                problem["status"] = "in_progress"

        # Extract notes
        notes_match = re.search(
            r'##\s*注意\s*\n(.*?)(?=\n##|\Z)', content, re.DOTALL
        )
        if notes_match:
            lines = notes_match.group(1).strip().split("\n")
            problem["notes"] = [
                line.lstrip("- ").strip() for line in lines
                if line.strip() and line.strip().startswith("-")
            ]

        return problem

    def find_solution(self, symptoms: list[str]) -> Optional[dict]:
        """Match symptoms to known problems and return the best match.

        Args:
            symptoms: List of symptom strings to match against

        Returns:
            Best matching problem dict, or None if no match found
        """
        if not symptoms or not self.problems:
            return None

        best_match = None
        best_score = 0

        symptoms_lower = [s.lower() for s in symptoms]
        symptoms_joined = " ".join(symptoms_lower)

        for problem in self.problems:
            score = 0
            problem_symptoms = problem.get("symptoms", [])

            for ps in problem_symptoms:
                ps_lower = ps.lower()
                # Check if any word from the problem symptom appears in input symptoms
                for word in ps_lower.split():
                    if len(word) >= 3 and word in symptoms_joined:
                        score += 1
                # Exact substring match gets higher score
                for input_symptom in symptoms_lower:
                    if ps_lower in input_symptom or input_symptom in ps_lower:
                        score += 3

            # Also match against title and root_cause
            title_lower = problem.get("title", "").lower()
            for input_symptom in symptoms_lower:
                if any(kw in title_lower for kw in input_symptom.split() if len(kw) >= 3):
                    score += 2

            if score > best_score:
                best_score = score
                best_match = problem

        # Only return if we have a meaningful match (score >= 2)
        if best_score >= 2:
            return best_match
        return None

    def get_all_problems(self, status: str = None) -> list[dict]:
        """Get all problems, optionally filtered by status.

        Args:
            status: Filter by status ('open', 'resolved', 'in_progress'). None for all.

        Returns:
            List of problem dicts
        """
        if status is None:
            return self.problems
        return [p for p in self.problems if p.get("status") == status]

    def find_system_for_task(self, task_text: str) -> Optional[dict]:
        """Find the system that handles a given task text.

        Args:
            task_text: The task description from Vision (e.g., "提升等級至 2")

        Returns:
            System dict or None
        """
        task_lower = task_text.lower()

        # Check task sequence first (tasks.yaml has specific patterns)
        tasks_system = self.systems_by_id.get("tasks")
        if tasks_system:
            for task_def in tasks_system.get("newbie_task_sequence", {}).get("tasks", []):
                for pattern in task_def.get("text_patterns", []):
                    if pattern.lower() in task_lower or any(
                        kw in task_lower for kw in pattern.lower().split()
                        if len(kw) >= 2
                    ):
                        target_system = task_def.get("system", "gameplay")
                        return self.systems_by_id.get(target_system)

        # Fallback: check each system's recognition_keywords
        for system in self.systems:
            keywords = system.get("recognition_keywords", [])
            for kw in keywords:
                if kw.lower() in task_lower:
                    return system

        return None

    def get_action_sequence(self, system_id: str, action_name: str) -> list:
        """Get the action steps for a specific system action.

        Args:
            system_id: e.g., "upgrade", "skills", "login"
            action_name: e.g., "upgrade_cannon", "use_lock_card"

        Returns:
            List of step dicts: [{"type": "click", "x": 65, "y": 235, "wait": 1.5}, ...]
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            logger.warning(f"System '{system_id}' not found")
            return []

        actions = system.get("actions", {})
        action = actions.get(action_name)
        if not action:
            logger.warning(f"Action '{action_name}' not found in system '{system_id}'")
            return []

        return action.get("steps", [])

    def get_action_for_task(self, task_text: str) -> tuple[Optional[str], Optional[str], list]:
        """Find the system and action for a task, return (system_id, action_name, steps).

        Args:
            task_text: The task description

        Returns:
            (system_id, action_name, steps) or (None, None, [])
        """
        task_lower = task_text.lower()

        # Check task sequence for specific action mapping
        tasks_system = self.systems_by_id.get("tasks")
        if tasks_system:
            for task_def in tasks_system.get("newbie_task_sequence", {}).get("tasks", []):
                for pattern in task_def.get("text_patterns", []):
                    if pattern.lower() in task_lower:
                        system_id = task_def.get("system", "gameplay")
                        action_name = task_def.get("action", "burst_shoot")
                        steps = self.get_action_sequence(system_id, action_name)
                        return system_id, action_name, steps

        # Data-driven keyword matching from YAML recognition_keywords + default_action
        for system in self.systems:
            sys_id = system.get("system_id", "")
            keywords = system.get("recognition_keywords", [])
            default_action = system.get("default_action")
            if not default_action:
                continue
            for kw in keywords:
                if kw.lower() in task_lower:
                    steps = self.get_action_sequence(sys_id, default_action)
                    return sys_id, default_action, steps

        return None, None, []

    def get_element(self, system_id: str, element_id: str) -> Optional[dict]:
        """Get a specific UI element definition.

        Args:
            system_id: System containing the element
            element_id: Element ID

        Returns:
            Element dict with location, type, etc.
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            return None

        for el in system.get("elements", []):
            if el.get("id") == element_id:
                return el

        return None

    def get_path(self, from_node: str, to_node: str) -> list:
        """Find shortest path between two systems in the flow graph.

        Args:
            from_node: Starting system ID
            to_node: Target system ID

        Returns:
            List of edge dicts representing the path
        """
        edges = self.flow_graph.get("edges", [])

        # Build adjacency list
        adj = {}
        edge_map = {}
        for edge in edges:
            src = edge.get("from", "")
            dst = edge.get("to", "")
            if src not in adj:
                adj[src] = []
            adj[src].append(dst)
            edge_map[(src, dst)] = edge

        # BFS
        queue = deque([(from_node, [from_node])])
        visited = {from_node}

        while queue:
            current, path = queue.popleft()
            if current == to_node:
                # Convert path to edges
                result = []
                for i in range(len(path) - 1):
                    edge = edge_map.get((path[i], path[i + 1]))
                    if edge:
                        result.append(edge)
                return result

            for neighbor in adj.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return []  # No path found

    def get_detection_indicators(self, system_id: str) -> list:
        """Get indicators for detecting a system state.

        Args:
            system_id: System to detect

        Returns:
            List of indicator strings
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            return []

        detection = system.get("detection", {})
        return detection.get("indicators", [])

    def get_detection_anchors(self, system_id: str) -> list:
        """Static UI anchors declared under ``detection.anchors`` for a system.

        Each anchor: ``{element, image, region: {x, y, width, height}, min_ssim}``
        with ``image`` relative to the knowledge directory.
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            return []
        return (system.get("detection") or {}).get("anchors", []) or []

    def _anchor_image(self, rel_path: str):
        """Load (and cache) an anchor template as an RGB array; None if missing."""
        if rel_path in self._anchor_cache:
            return self._anchor_cache[rel_path]
        path = self.base_dir / rel_path
        if not path.exists():
            logger.warning(f"anchor image missing: {path}")
            self._anchor_cache[rel_path] = None
            return None
        import numpy as np
        from PIL import Image
        with Image.open(path) as im:
            arr = np.array(im.convert("RGB"), dtype=np.uint8)
        self._anchor_cache[rel_path] = arr
        return arr

    def identify_system(self, frame, min_margin: float = 0.15) -> dict:
        """Deterministically identify which system a frame shows.

        Every system that declares ``detection.anchors`` is scored by the mean
        region-SSIM of its anchors against the frame; a system only qualifies
        when each anchor clears its own ``min_ssim``. The best qualifier wins
        unless the runner-up is within ``min_margin`` — then the answer is
        ambiguous and ``system_id`` is None rather than a guess.

        This is the canonical screen key the runtime layer lacks (screen_ids
        named by Vision are display names); it needs no Vision call and is
        stable across a game's animated backgrounds, which defeat whole-frame
        motion or SSIM heuristics.

        Returns:
            {"system_id": str | None, "best": str | None, "confidence": float,
             "ambiguous": bool, "scores": {system_id: mean_ssim}}
        """
        from .perceiver import match_region

        scored: dict[str, tuple[float, bool]] = {}
        for sid in self.systems_by_id:
            anchors = self.get_detection_anchors(sid)
            if not anchors:
                continue
            values, qualifies = [], True
            for a in anchors:
                tmpl = self._anchor_image(a["image"])
                if tmpl is None:
                    qualifies = False
                    continue
                s = match_region(frame, tmpl, a["region"])
                values.append(s)
                if s < float(a.get("min_ssim", 0.6)):
                    qualifies = False
            if values:
                scored[sid] = (sum(values) / len(values), qualifies)

        scores = {sid: round(v[0], 3) for sid, v in scored.items()}
        ranked = sorted(((sid, v[0]) for sid, v in scored.items() if v[1]),
                        key=lambda kv: -kv[1])
        if not ranked:
            return {"system_id": None, "best": None, "confidence": 0.0,
                    "ambiguous": False, "scores": scores}
        best_id, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else -1.0
        ambiguous = (best_score - second_score) < min_margin
        return {"system_id": None if ambiguous else best_id, "best": best_id,
                "confidence": round(best_score, 3), "ambiguous": ambiguous,
                "scores": scores}

    def get_known_issues(self, system_id: str) -> list:
        """Get known issues for a system.

        Args:
            system_id: System ID

        Returns:
            List of issue dicts
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            return []

        return system.get("known_issues", [])

    def update_element_location(self, system_id: str, element_id: str, x: int, y: int):
        """Update an element's location (auto-learning).

        Args:
            system_id: System containing the element
            element_id: Element to update
            x, y: New coordinates
        """
        system = self.systems_by_id.get(system_id)
        if not system:
            return

        for el in system.get("elements", []):
            if el.get("id") == element_id:
                el["location"] = {"x": x, "y": y}
                # Save back to YAML
                self._save_system(system_id)
                logger.info(f"Updated {system_id}/{element_id} location to ({x}, {y})")
                return

    def _save_system(self, system_id: str):
        """Save a system back to its YAML file."""
        system = self.systems_by_id.get(system_id)
        if not system:
            return

        path = self.base_dir / "systems" / f"{system_id}.yaml"
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(system, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            logger.error(f"Failed to save {path}: {e}")

    def summary(self) -> str:
        """Return a brief summary of loaded knowledge."""
        lines = [
            f"Game: {self.game_info.get('name', self.game_name)}",
            f"Systems: {len(self.systems)}",
            f"Flow edges: {len(self.flow_graph.get('edges', []))}",
            f"Problems: {len(self.problems)} ({len([p for p in self.problems if p['status'] == 'open'])} open)",
            f"Runtime screens: {len(self._runtime_data.get('screens', []))}",
            f"Runtime bugs: {len(self._runtime_data.get('bugs', []))}",
            "Systems loaded:",
        ]
        for sys in self.systems:
            sys_id = sys.get("system_id", "?")
            name = sys.get("name", "?")
            n_elements = len(sys.get("elements", []))
            n_actions = len(sys.get("actions", {}))
            lines.append(f"  - {sys_id}: {name} ({n_elements} elements, {n_actions} actions)")
        return "\n".join(lines)

    # --- Dynamic Runtime Layer ---
    # Runtime learning (screens, transitions, bugs) discovered during a session.
    # This is the single knowledge system: static YAML (systems/, flow_graph,
    # problems/) + this dynamic layer, unified in one class.

    def _load_runtime(self):
        """Load runtime knowledge.yaml for dynamic learning."""
        self._runtime_path = self.base_dir / "knowledge.yaml"
        if self._runtime_path.exists():
            try:
                with open(self._runtime_path, "r", encoding="utf-8") as f:
                    self._runtime_data = yaml.safe_load(f) or {}
            except Exception as e:
                logger.error(f"Failed to load runtime knowledge: {e}")
                self._runtime_data = {}
        else:
            self._runtime_data = {}

        # Ensure required keys
        self._runtime_data.setdefault("game", {"url": "", "title": "", "last_updated": ""})
        self._runtime_data.setdefault("screens", [])
        self._runtime_data.setdefault("flow_graph", [])
        self._runtime_data.setdefault("bugs", [])

    def save_runtime(self) -> None:
        """Save runtime knowledge to YAML."""
        from datetime import datetime
        self._runtime_data["game"]["last_updated"] = datetime.now().isoformat()
        with open(self._runtime_path, "w", encoding="utf-8") as f:
            yaml.dump(self._runtime_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def set_game_info(self, url: str, title: str = "") -> None:
        """Set game URL and title in runtime data."""
        self._runtime_data["game"]["url"] = url
        self._runtime_data["game"]["title"] = title

    def get_runtime_screen(self, screen_id: str) -> Optional[dict]:
        """Get a runtime-discovered screen by ID."""
        for s in self._runtime_data["screens"]:
            if s.get("id") == screen_id:
                return s
        return None

    def add_runtime_screen(self, screen_id: str, description: str, elements: list = None,
                           reference_screenshot: str = None) -> dict:
        """Add/update a runtime-discovered screen."""
        existing = self.get_runtime_screen(screen_id)
        if existing:
            existing["description"] = description
            if elements:
                existing["known_elements"] = elements
            if reference_screenshot:
                existing["reference_screenshot"] = reference_screenshot
            return existing

        screen = {
            "id": screen_id,
            "description": description,
            "known_elements": elements or [],
            "transitions": [],
            "strategy": {"mode": "explore"},
        }
        if reference_screenshot:
            screen["reference_screenshot"] = reference_screenshot
        self._runtime_data["screens"].append(screen)
        return screen

    def add_runtime_transition(self, from_screen: str, to_screen: str, action: str,
                               confidence: str = "low") -> None:
        """Add a transition between runtime screens."""
        screen = self.get_runtime_screen(from_screen)
        if screen:
            transitions = screen.setdefault("transitions", [])
            for t in transitions:
                if t.get("goes_to") == to_screen and t.get("action") == action:
                    if t.get("confidence") == "low":
                        t["confidence"] = "medium"
                    elif t.get("confidence") == "medium":
                        t["confidence"] = "high"
                    return
            transitions.append({
                "action": action,
                "goes_to": to_screen,
                "confidence": confidence,
            })

        # Add to flow_graph
        for edge in self._runtime_data["flow_graph"]:
            if edge.get("from") == from_screen and edge.get("to") == to_screen and edge.get("action") == action:
                edge["confidence"] = confidence
                return
        self._runtime_data["flow_graph"].append({
            "from": from_screen,
            "to": to_screen,
            "action": action,
            "stable": confidence == "high",
        })

    def add_bug(self, screen_id: str, description: str, severity: str = "medium",
                repro_steps: list = None, evidence: list = None) -> str:
        """Add a bug. Returns the bug ID."""
        from datetime import datetime
        bug_id = f"BUG-{len(self._runtime_data['bugs']) + 1:03d}"
        bug = {
            "id": bug_id,
            "screen": screen_id,
            "severity": severity,
            "description": description,
            "repro_steps": repro_steps or [],
            "evidence": evidence or [],
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "reproduced": 1,
        }
        self._runtime_data["bugs"].append(bug)
        return bug_id

    def get_runtime_flow_summary(self) -> str:
        """Get a human-readable flow summary from runtime data."""
        if not self._runtime_data["flow_graph"]:
            return "(no flow discovered yet)"
        lines = []
        for edge in self._runtime_data["flow_graph"]:
            stable = "✓" if edge.get("stable") else "?"
            lines.append(f"  {edge['from']} ──[{edge['action']}]──▶ {edge['to']} [{stable}]")
        return "\n".join(lines)

    def get_known_screen_ids(self) -> list[str]:
        """Get list of known screen IDs (runtime)."""
        return [s["id"] for s in self._runtime_data["screens"]]


# Convenience: singleton instance
_kb_cache = {}


def get_knowledge_base(game_name: str = "example_game") -> KnowledgeBase:
    """Get or create a KnowledgeBase instance (cached)."""
    if game_name not in _kb_cache:
        _kb_cache[game_name] = KnowledgeBase(game_name)
    return _kb_cache[game_name]
