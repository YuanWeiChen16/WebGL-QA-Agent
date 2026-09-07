"""Centralized Vision prompt templates for WebGL QA Agent.

All prompts are generated dynamically from knowledge base and config.
No game-specific content is hardcoded here.
"""

from typing import Optional


def build_screen_analysis_prompt(config: dict, known_elements: list = None) -> str:
    """Build the main screen analysis prompt from config.

    Args:
        config: Merged config dict (from Config.raw or Config.get_section)
        known_elements: Optional list of known UI element labels for this game
    """
    vision_ctx = config.get("vision_context", {})
    game_type = vision_ctx.get("game_type", "WebGL game")
    resolution = vision_ctx.get("resolution_hint", "1280x720")
    screen_types = vision_ctx.get("known_screen_types", ["gameplay", "popup", "loading", "login", "unknown"])
    language = vision_ctx.get("language", "en")

    screen_list = ", ".join(screen_types)
    lang_note = "in Chinese" if "zh" in language else "in English"

    elements_hint = ""
    if known_elements:
        labels = ", ".join(known_elements[:15])
        elements_hint = f"\nKnown UI labels in this game: {labels}"

    return f"""Analyze this {game_type} screenshot ({resolution} pixels).
Identify the screen state from: [{screen_list}]
Describe what's on screen ({lang_note}).
List interactive elements with their (x, y) coordinates.
Note any visual anomalies (glitches, missing textures, UI overlap).
Report any visible task/mission text and progress.
Read any visible numeric state into game_state: score, currency/coins/gold balance,
level/tier (e.g. cannon multiplier), and lives — copy the digits exactly, use null
when a value is not visible (do NOT guess). Set reward_detected if a win/payout is shown.{elements_hint}

Use the game_analysis tool to report your findings."""


def build_task_analysis_prompt(config: dict, known_elements: list = None) -> str:
    """Build a task-focused analysis prompt.

    Args:
        config: Merged config dict
        known_elements: Optional list of known UI element labels
    """
    vision_ctx = config.get("vision_context", {})
    game_type = vision_ctx.get("game_type", "WebGL game")
    resolution = vision_ctx.get("resolution_hint", "1280x720")
    screen_types = vision_ctx.get("known_screen_types", ["gameplay", "popup", "loading"])
    language = vision_ctx.get("language", "en")

    screen_list = ", ".join(screen_types)
    lang_note = "in Chinese" if "zh" in language else "in English"

    elements_hint = ""
    if known_elements:
        labels = ", ".join(known_elements[:15])
        elements_hint = f"\nKnown UI labels: {labels}"

    return f"""Look at this {game_type} screenshot ({resolution}).

Tell me:
1. What screen is this? ({screen_list})
2. Is there a TASK indicator? (mission text + progress like "3/10") — read the exact text
3. Is there a flashing finger/arrow indicator pointing somewhere?
4. Is there a reward/claim button?
5. Any popup overlaying the game?
6. Any navigation panel visible?

Describe {lang_note}.{elements_hint}

Respond ONLY in JSON:
{{
  "screen_id": "string",
  "description": "brief description",
  "current_task": "exact task text if visible, else empty string",
  "task_progress": "e.g. 3/10 or empty",
  "is_popup": false,
  "has_reward_button": false,
  "has_finger_indicator": false,
  "finger_location": null,
  "elements": [{{"id": "str", "type": "str", "label": "str", "location": {{"x": int, "y": int}}}}],
  "suggested_click": {{"x": int, "y": int, "reason": "str"}},
  "anomalies": []
}}"""


def build_menu_analysis_prompt(config: dict, navigation_labels: list = None) -> str:
    """Build a menu/navigation analysis prompt.

    Args:
        config: Merged config dict
        navigation_labels: Labels to look for (e.g., ["回到大廳", "Lobby", "Exit"])
    """
    vision_ctx = config.get("vision_context", {})
    resolution = vision_ctx.get("resolution_hint", "1280x720")

    if not navigation_labels:
        navigation_labels = ["Lobby", "Exit", "Back", "Menu"]

    labels_str = ", ".join(f'"{l}"' for l in navigation_labels)

    return f"""This game screenshot ({resolution}).
A menu button was just clicked. Look for any menu panel, sidebar, or popup that appeared.

Especially look for navigation buttons: {labels_str}

List ALL visible UI elements with EXACT (x,y) coordinates.

Respond in JSON:
{{
  "screen_id": "menu_open|gameplay|popup|lobby",
  "description": "description",
  "has_lobby_button": false,
  "lobby_button_location": null,
  "menu_visible": true,
  "elements": [{{"id": "str", "type": "str", "label": "str", "location": {{"x": int, "y": int}}}}],
  "suggested_click": {{"x": int, "y": int, "reason": "str"}},
  "anomalies": []
}}"""


def build_find_element_prompt(config: dict, element_description: str,
                              hints: list = None) -> str:
    """Build a prompt to locate a specific UI element.

    Args:
        config: Merged config dict
        element_description: What to find (e.g., "lock button (鎖定)")
        hints: Optional position hints or labels to help Vision
    """
    vision_ctx = config.get("vision_context", {})
    game_type = vision_ctx.get("game_type", "WebGL game")
    resolution = vision_ctx.get("resolution_hint", "1280x720")

    hints_str = ""
    if hints:
        hints_str = "\nHints: " + ", ".join(hints)

    return f"""This {game_type} screenshot ({resolution}).
Find the {element_description}.{hints_str}

Report its exact (x, y) center coordinates.
Respond in JSON:
{{
  "screen_id": "gameplay",
  "target_location": {{"x": int, "y": int}},
  "description": "description",
  "elements": [{{"id": "str", "type": "str", "label": "str", "location": {{"x": int, "y": int}}}}],
  "anomalies": []
}}"""


def build_region_analysis_prompt(config: dict, region: str,
                                 look_for: list = None) -> str:
    """Build a prompt to analyze a specific region of the screen.

    Args:
        config: Merged config dict
        region: Region description (e.g., "left side", "bottom bar")
        look_for: Specific things to identify
    """
    vision_ctx = config.get("vision_context", {})
    game_type = vision_ctx.get("game_type", "WebGL game")
    resolution = vision_ctx.get("resolution_hint", "1280x720")

    look_for_str = ""
    if look_for:
        items = "\n".join(f"- {item}" for item in look_for)
        look_for_str = f"\n\nSpecifically look for:\n{items}"

    return f"""This {game_type} screenshot ({resolution}). Focus on the {region}.
List ALL buttons/icons in that region with exact (x,y) coordinates.{look_for_str}

Respond in JSON:
{{
  "region_elements": [{{"label": "str", "location": {{"x": int, "y": int}}, "description": "str"}}],
  "current_task": "str",
  "description": "str"
}}"""


# --- Helper to build prompts from KnowledgeBase context ---

def get_navigation_labels(knowledge_base) -> list[str]:
    """Extract navigation-related labels from knowledge base systems."""
    labels = []
    for sys_id in ("lobby", "hall_switch"):
        system = knowledge_base.systems_by_id.get(sys_id)
        if system:
            # Pull labels from elements
            for el in system.get("elements", []):
                label = el.get("label", "")
                if label:
                    labels.append(label)
            # Pull from vision_hints if defined
            hints = system.get("vision_hints", {})
            labels.extend(hints.get("navigation_labels", []))
    return labels


def get_known_ui_labels(knowledge_base, system_id: str = None) -> list[str]:
    """Extract known UI element labels from knowledge base."""
    labels = []
    systems = [knowledge_base.systems_by_id[system_id]] if system_id and system_id in knowledge_base.systems_by_id else knowledge_base.systems
    for system in systems:
        for el in system.get("elements", []):
            label = el.get("label", "")
            if label and label not in labels:
                labels.append(label)
    return labels


# Legacy compatibility aliases — eagerly built from default config.
TASK_ANALYSIS_PROMPT = None
MENU_ANALYSIS_PROMPT = None


def _ensure_legacy_prompts():
    """Build legacy prompts from default config."""
    global TASK_ANALYSIS_PROMPT, MENU_ANALYSIS_PROMPT
    if TASK_ANALYSIS_PROMPT is None:
        from .config import get_config
        try:
            cfg = get_config("example_game")
        except Exception:
            cfg = get_config()
        TASK_ANALYSIS_PROMPT = build_task_analysis_prompt(cfg.raw)
        MENU_ANALYSIS_PROMPT = build_menu_analysis_prompt(cfg.raw)


# Auto-populate on import so existing scripts work unchanged
_ensure_legacy_prompts()
