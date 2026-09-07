"""Robust Vision response parser with multiple fallback strategies.

Centralizes all JSON parsing logic that was previously duplicated across scripts.
"""

import json
import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VisionResponse:
    """Structured response from Vision API analysis."""
    screen_id: str = "unknown"
    description: str = ""
    current_task: str = ""
    task_progress: str = ""
    is_hall_switch: bool = False
    is_lobby: bool = False
    is_popup: bool = False
    has_reward_button: bool = False
    has_finger_indicator: bool = False
    finger_location: Optional[dict] = None
    elements: list = field(default_factory=list)
    suggested_click: Optional[dict] = None
    anomalies: list = field(default_factory=list)
    # Metadata
    raw_text: str = ""
    parse_success: bool = False
    has_menu_button: bool = False
    has_lobby_button: bool = False
    lobby_button_location: Optional[dict] = None
    menu_visible: bool = False

    def to_dict(self) -> dict:
        """Convert to dict (compatible with existing code)."""
        d = {
            "screen_id": self.screen_id,
            "description": self.description,
            "current_task": self.current_task,
            "task_progress": self.task_progress,
            "is_hall_switch": self.is_hall_switch,
            "is_lobby": self.is_lobby,
            "is_popup": self.is_popup,
            "has_reward_button": self.has_reward_button,
            "has_finger_indicator": self.has_finger_indicator,
            "finger_location": self.finger_location,
            "elements": self.elements,
            "suggested_click": self.suggested_click,
            "anomalies": self.anomalies,
            "has_menu_button": self.has_menu_button,
            "has_lobby_button": self.has_lobby_button,
            "lobby_button_location": self.lobby_button_location,
            "menu_visible": self.menu_visible,
        }
        return d


def parse_vision(raw_text: str) -> dict:
    """Parse Vision API response text into structured dict.

    Tries multiple strategies:
    1. Direct JSON parse
    2. Extract JSON from markdown code block
    3. Find JSON object with regex
    4. Return low-confidence fallback with raw description

    Args:
        raw_text: Raw text response from Claude Vision

    Returns:
        Dict compatible with existing code (screen_id, elements, etc.)
    """
    if not raw_text or not raw_text.strip():
        return _fallback("empty_response", "Empty Vision response", raw_text)

    text = raw_text.strip()

    # Strategy 1: Direct JSON parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return _normalize(result)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: Extract from markdown code block
    try:
        # Match ```json ... ``` or ``` ... ```
        code_block_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
        if code_block_match:
            json_str = code_block_match.group(1).strip()
            result = json.loads(json_str)
            if isinstance(result, dict):
                return _normalize(result)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 3: Find outermost JSON object with regex
    try:
        # Find the first { and match to its closing }
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            json_str = json_match.group(0)
            result = json.loads(json_str)
            if isinstance(result, dict):
                return _normalize(result)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 4: Try fixing common JSON issues
    try:
        # Remove trailing commas
        fixed = re.sub(r',\s*([}\]])', r'\1', text)
        # Try extracting JSON again
        json_match = re.search(r'\{[\s\S]*\}', fixed)
        if json_match:
            result = json.loads(json_match.group(0))
            if isinstance(result, dict):
                return _normalize(result)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 5: Fallback — use raw text as description
    logger.warning(f"Failed to parse Vision response as JSON (len={len(text)})")
    return _fallback("parse_error", text[:300], raw_text)


def _normalize(result: dict) -> dict:
    """Normalize a parsed JSON dict to ensure all expected keys exist."""
    defaults = {
        "screen_id": "unknown",
        "description": "",
        "current_task": "",
        "task_progress": "",
        "is_hall_switch": False,
        "is_lobby": False,
        "is_popup": False,
        "has_reward_button": False,
        "has_finger_indicator": False,
        "finger_location": None,
        "elements": [],
        "suggested_click": None,
        "anomalies": [],
        "has_menu_button": False,
        "has_lobby_button": False,
        "lobby_button_location": None,
        "menu_visible": False,
    }

    # Merge with defaults
    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val

    # Ensure elements is a list
    if not isinstance(result.get("elements"), list):
        result["elements"] = []

    # Ensure anomalies is a list
    if not isinstance(result.get("anomalies"), list):
        result["anomalies"] = []

    return result


def _fallback(screen_id: str, description: str, raw_text: str) -> dict:
    """Create a fallback response when parsing fails."""
    return {
        "screen_id": screen_id,
        "description": description,
        "current_task": "",
        "task_progress": "",
        "is_hall_switch": False,
        "is_lobby": False,
        "is_popup": False,
        "has_reward_button": False,
        "has_finger_indicator": False,
        "finger_location": None,
        "elements": [],
        "suggested_click": None,
        "anomalies": ["parse_error"],
        "has_menu_button": False,
        "has_lobby_button": False,
        "lobby_button_location": None,
        "menu_visible": False,
    }
