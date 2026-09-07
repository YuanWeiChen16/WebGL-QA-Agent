"""Vision module — calls Claude Vision API to analyze game screenshots.

Features:
- Structured output via Anthropic tool_use (guaranteed JSON schema)
- Core schema (generic) + game-specific extensions loaded from config
- Lazy client initialization (no import-time env var requirement)
- Retry with exponential backoff
- Fallback to free-form text for custom prompts
"""

import base64
import os
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Retry configuration defaults (overridable via Config)
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BASE_BACKOFF = 2.0
_DEFAULT_TIMEOUT = 120.0
_DEFAULT_REQUEST_TIMEOUT = 60.0
_DEFAULT_MAX_TOKENS = 2000
_DEFAULT_MODEL = "claude-sonnet-4"

# Singleton client — lazy initialized
_client = None


def _get_client(timeout: float = None):
    """Get or create the singleton Anthropic client. Lazy init from env vars."""
    global _client
    if _client is None:
        from anthropic import Anthropic

        gateway_url = os.environ.get("VISION_GATEWAY_URL")
        api_key = os.environ.get("VISION_API_KEY")

        if not gateway_url or not api_key:
            raise EnvironmentError(
                "Missing required env vars: VISION_GATEWAY_URL and VISION_API_KEY. "
                "Set them before calling Vision API functions."
            )
        _client = Anthropic(
            base_url=gateway_url,
            api_key=api_key,
            timeout=timeout or _DEFAULT_TIMEOUT,
        )
    return _client


# --- Core tool schema (generic for any WebGL game) ---

CORE_SCHEMA_PROPERTIES = {
    "screen_id": {
        "type": "string",
        "description": "Screen state identifier (e.g., login, gameplay, loading, popup, lobby)"
    },
    "description": {
        "type": "string",
        "description": "Brief description of what's on screen"
    },
    "current_task": {
        "type": "string",
        "description": "Current task/objective shown on screen (exact text if visible, empty if none)"
    },
    "task_progress": {
        "type": "string",
        "description": "Progress indicator for current task (e.g., '1/3', '50%', empty if none)"
    },
    "is_popup": {
        "type": "boolean",
        "description": "True if there's a popup/dialog overlaying the main screen"
    },
    "has_reward_button": {
        "type": "boolean",
        "description": "True if there's a claimable reward button"
    },
    "has_finger_indicator": {
        "type": "boolean",
        "description": "True if there's a finger/arrow indicator pointing at something"
    },
    "finger_location": {
        "type": ["object", "null"],
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "description": "Location the finger indicator is pointing at, null if no indicator"
    },
    "elements": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "type": {"type": "string"},
                "label": {"type": "string"},
                "location": {
                    "type": "object",
                    "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                    "required": ["x", "y"]
                }
            },
            "required": ["id", "label", "location"]
        },
        "description": "Interactive UI elements visible on screen"
    },
    "suggested_click": {
        "type": ["object", "null"],
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "reason": {"type": "string"}
        },
        "description": "Recommended next click action with reason"
    },
    "anomalies": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Visual anomalies detected (glitches, missing textures, UI overlap)"
    },
    "game_state": {
        "type": "object",
        "description": (
            "Numeric game state read directly from the screen. This is the test "
            "oracle's ground truth for a black-box game — read the digits exactly "
            "as displayed. Use null for any value that is not visible or not legible; "
            "do NOT guess."
        ),
        "properties": {
            "score": {"type": ["integer", "null"], "description": "Current score, null if not shown"},
            "currency": {"type": ["integer", "null"], "description": "Player currency/coins/gold balance (integer, no commas), null if not shown"},
            "level": {"type": ["integer", "null"], "description": "Current level/tier, e.g. cannon multiplier level, null if not shown"},
            "lives": {"type": ["integer", "null"], "description": "Lives/HP remaining, null if not applicable"},
        },
    },
    "reward_detected": {
        "type": "boolean",
        "description": "True if a win/payout/catch animation or reward number is visible this frame (used by the oracle to explain currency increases)",
    },
}

CORE_REQUIRED_FIELDS = [
    "screen_id", "description", "current_task", "is_popup",
    "has_reward_button", "has_finger_indicator", "elements", "anomalies",
    "game_state",
]

# Game-specific extension fields (loaded from knowledge per game)
# These are added to the schema when a game defines them in game_info.yaml

_EXTENSION_REGISTRY = {
    "is_hall_switch": {
        "type": "boolean",
        "description": "True if this is a hall/room switching screen"
    },
    "is_lobby": {
        "type": "boolean",
        "description": "True if this is the main lobby with multiple game rooms"
    },
    "has_menu_button": {
        "type": "boolean",
        "description": "True if a hamburger/menu button is visible"
    },
    "has_lobby_button": {
        "type": "boolean",
        "description": "True if a lobby/return button is visible"
    },
    "lobby_button_location": {
        "type": ["object", "null"],
        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
        "description": "Location of lobby button, null if not visible"
    },
    "menu_visible": {
        "type": "boolean",
        "description": "True if a menu panel is currently open/visible"
    },
}


def build_tool_schema(game_extensions: list[str] = None) -> dict:
    """Build the game_analysis tool schema with optional game-specific extensions.

    Args:
        game_extensions: List of extension field names to include (from _EXTENSION_REGISTRY)

    Returns:
        Complete tool definition dict for Anthropic API
    """
    properties = dict(CORE_SCHEMA_PROPERTIES)
    required = list(CORE_REQUIRED_FIELDS)

    if game_extensions:
        for ext_name in game_extensions:
            if ext_name in _EXTENSION_REGISTRY:
                properties[ext_name] = _EXTENSION_REGISTRY[ext_name]
                required.append(ext_name)

    return {
        "name": "game_analysis",
        "description": "Report the analysis of a game screenshot in structured format.",
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    }


def _get_defaults(game_extensions: list[str] = None) -> dict:
    """Get the default values dict for normalizing tool_use results."""
    defaults = {
        "screen_id": "unknown",
        "description": "",
        "current_task": "",
        "task_progress": "",
        "is_popup": False,
        "has_reward_button": False,
        "has_finger_indicator": False,
        "finger_location": None,
        "elements": [],
        "suggested_click": None,
        "anomalies": [],
        "game_state": {"score": None, "currency": None, "level": None, "lives": None},
        "reward_detected": False,
    }
    # Add defaults for extensions
    if game_extensions:
        ext_defaults = {
            "is_hall_switch": False,
            "is_lobby": False,
            "has_menu_button": False,
            "has_lobby_button": False,
            "lobby_button_location": None,
            "menu_visible": False,
        }
        for ext_name in game_extensions:
            if ext_name in ext_defaults:
                defaults[ext_name] = ext_defaults[ext_name]
    return defaults


def _normalize_structured(result: dict, game_extensions: list[str] = None) -> dict:
    """Ensure all expected keys exist in a tool_use result."""
    defaults = _get_defaults(game_extensions)
    for key, default_val in defaults.items():
        if key not in result:
            result[key] = default_val
    return result


def _structured_fallback(screen_id: str, description: str, anomalies: list,
                         game_extensions: list[str] = None) -> dict:
    """Create a fallback dict when structured call fails."""
    result = _get_defaults(game_extensions)
    result["screen_id"] = screen_id
    result["description"] = description
    result["anomalies"] = anomalies
    return result


def analyze_screenshot_structured(screenshot_path: str, model: str = None,
                                  prompt: str = None, config=None,
                                  game_extensions: list[str] = None) -> dict:
    """Analyze a screenshot using Claude Vision with tool_use for guaranteed structured output.

    Args:
        screenshot_path: Path to the screenshot file
        model: Model to use (default from config or claude-sonnet-4)
        prompt: Custom prompt (default: generic structured analysis prompt)
        config: Optional Config instance for settings override
        game_extensions: Extension fields to include in schema

    Returns:
        Dict with guaranteed schema (screen_id, elements, anomalies, etc.)
    """
    from anthropic import APIError, APITimeoutError, APIConnectionError, RateLimitError

    # Read settings from config if provided
    if config:
        model = model or config.get("vision.model", _DEFAULT_MODEL)
        max_retries = config.get("vision.max_retries", _DEFAULT_MAX_RETRIES)
        backoff_base = config.get("vision.backoff_base", _DEFAULT_BASE_BACKOFF)
        request_timeout = config.get("vision.request_timeout_seconds", _DEFAULT_REQUEST_TIMEOUT)
        max_tokens = config.get("vision.max_tokens", _DEFAULT_MAX_TOKENS)
    else:
        model = model or _DEFAULT_MODEL
        max_retries = _DEFAULT_MAX_RETRIES
        backoff_base = _DEFAULT_BASE_BACKOFF
        request_timeout = _DEFAULT_REQUEST_TIMEOUT
        max_tokens = _DEFAULT_MAX_TOKENS

    img_path = Path(screenshot_path)
    if not img_path.exists():
        logger.error(f"Screenshot not found: {screenshot_path}")
        return _structured_fallback("error", "Screenshot file not found", ["file_not_found"], game_extensions)

    img_bytes = img_path.read_bytes()
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

    suffix = img_path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"

    # Build tool schema
    tool_schema = build_tool_schema(game_extensions)

    # Default prompt
    if not prompt:
        prompt = "Analyze this WebGL game screenshot. Identify the screen state, interactive elements with their coordinates, any active tasks, and visual anomalies. Use the game_analysis tool to report your findings."

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            client = _get_client()

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                timeout=request_timeout,
                tools=[tool_schema],
                tool_choice={"type": "tool", "name": "game_analysis"},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            # Extract tool_use block
            for block in response.content:
                if block.type == "tool_use" and block.name == "game_analysis":
                    result = block.input
                    return _normalize_structured(result, game_extensions)

            # No tool_use block found
            logger.warning(f"No tool_use block in response: {response.content}")
            return _structured_fallback("api_error", "No tool_use in response", ["missing_tool_use"], game_extensions)

        except RateLimitError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1)) * 2
            logger.warning(f"Rate limited (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
            print(f"  [Vision] Rate limited, waiting {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APITimeoutError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1))
            logger.warning(f"Timeout (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
            print(f"  [Vision] Timeout, retrying in {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APIConnectionError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1))
            logger.warning(f"Connection error (attempt {attempt}/{max_retries}): {e}. Waiting {wait_time}s...")
            print(f"  [Vision] Connection error, retrying in {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APIError as e:
            last_error = e
            if e.status_code and e.status_code >= 500:
                wait_time = backoff_base * (2 ** (attempt - 1))
                logger.warning(f"Server error {e.status_code} (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
                print(f"  [Vision] Server error {e.status_code}, retrying in {wait_time}s...", flush=True)
                time.sleep(wait_time)
            else:
                logger.error(f"API client error: {e}")
                print(f"  [Vision] API error (no retry): {e}", flush=True)
                break

        except Exception as e:
            last_error = e
            logger.error(f"Unexpected error in Vision API (attempt {attempt}/{max_retries}): {e}")
            print(f"  [Vision] Unexpected error: {e}", flush=True)
            if attempt < max_retries:
                time.sleep(backoff_base)
            else:
                break

    error_msg = str(last_error) if last_error else "Unknown error"
    logger.error(f"Vision API failed after {max_retries} attempts: {error_msg}")
    print(f"  [Vision] FAILED after {max_retries} attempts: {error_msg[:100]}", flush=True)
    return _structured_fallback("api_error", f"Vision API failed: {error_msg[:100]}", ["vision_api_failure"], game_extensions)


def analyze_screenshot(screenshot_path: str, prompt: str = None, model: str = None,
                       config=None) -> str:
    """Analyze a screenshot using Claude Vision via gateway (free-form text response).

    Features:
    - Retries with exponential backoff
    - Handles API timeout, connection errors, rate limits
    - Returns raw response text from Claude

    Args:
        screenshot_path: Path to the screenshot file
        prompt: Custom prompt (defaults to generic analysis)
        model: Model to use
        config: Optional Config instance for settings override

    Returns:
        Raw text response from Claude Vision
    """
    from anthropic import APIError, APITimeoutError, APIConnectionError, RateLimitError

    # Read settings
    if config:
        model = model or config.get("vision.model", _DEFAULT_MODEL)
        max_retries = config.get("vision.max_retries", _DEFAULT_MAX_RETRIES)
        backoff_base = config.get("vision.backoff_base", _DEFAULT_BASE_BACKOFF)
        request_timeout = config.get("vision.request_timeout_seconds", _DEFAULT_REQUEST_TIMEOUT)
        max_tokens = config.get("vision.max_tokens", _DEFAULT_MAX_TOKENS)
    else:
        model = model or _DEFAULT_MODEL
        max_retries = _DEFAULT_MAX_RETRIES
        backoff_base = _DEFAULT_BASE_BACKOFF
        request_timeout = _DEFAULT_REQUEST_TIMEOUT
        max_tokens = _DEFAULT_MAX_TOKENS

    if not prompt:
        prompt = """Look at this WebGL game screenshot. Tell me:
1. What screen/state is this?
2. What interactive elements do you see?
3. For each element, estimate its location as {x, y} coordinates
4. What action should I take next to explore/test the game?
5. Any visual anomalies?

Respond in JSON:
{
  "screen_id": "string",
  "description": "string",
  "elements": [{"id": "string", "type": "string", "label": "string", "location": {"x": int, "y": int}}],
  "suggested_action": {"type": "click|key|drag|wait|type", "x": int, "y": int},
  "anomalies": []
}"""

    img_path = Path(screenshot_path)
    if not img_path.exists():
        logger.error(f"Screenshot not found: {screenshot_path}")
        return '{"screen_id": "error", "description": "Screenshot file not found", "elements": [], "anomalies": ["file_not_found"]}'

    img_bytes = img_path.read_bytes()
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")

    suffix = img_path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            client = _get_client()

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                timeout=request_timeout,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": img_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    }
                ],
            )

            for block in response.content:
                if hasattr(block, 'text'):
                    return block.text

            logger.warning(f"No text block in response: {response.content}")
            return str(response.content)

        except RateLimitError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1)) * 2
            logger.warning(f"Rate limited (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
            print(f"  [Vision] Rate limited, waiting {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APITimeoutError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1))
            logger.warning(f"Timeout (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
            print(f"  [Vision] Timeout, retrying in {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APIConnectionError as e:
            last_error = e
            wait_time = backoff_base * (2 ** (attempt - 1))
            logger.warning(f"Connection error (attempt {attempt}/{max_retries}): {e}. Waiting {wait_time}s...")
            print(f"  [Vision] Connection error, retrying in {wait_time}s... (attempt {attempt}/{max_retries})", flush=True)
            time.sleep(wait_time)

        except APIError as e:
            last_error = e
            if e.status_code and e.status_code >= 500:
                wait_time = backoff_base * (2 ** (attempt - 1))
                logger.warning(f"Server error {e.status_code} (attempt {attempt}/{max_retries}). Waiting {wait_time}s...")
                print(f"  [Vision] Server error {e.status_code}, retrying in {wait_time}s...", flush=True)
                time.sleep(wait_time)
            else:
                logger.error(f"API client error: {e}")
                print(f"  [Vision] API error (no retry): {e}", flush=True)
                break

        except Exception as e:
            last_error = e
            logger.error(f"Unexpected error in Vision API (attempt {attempt}/{max_retries}): {e}")
            print(f"  [Vision] Unexpected error: {e}", flush=True)
            if attempt < max_retries:
                time.sleep(backoff_base)
            else:
                break

    error_msg = str(last_error) if last_error else "Unknown error"
    logger.error(f"Vision API failed after {max_retries} attempts: {error_msg}")
    print(f"  [Vision] FAILED after {max_retries} attempts: {error_msg[:100]}", flush=True)

    return f'{{"screen_id": "api_error", "description": "Vision API failed: {error_msg[:100]}", "elements": [], "anomalies": ["vision_api_failure"]}}'


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python vision.py <screenshot_path> [prompt]")
        sys.exit(1)

    path = sys.argv[1]
    custom_prompt = sys.argv[2] if len(sys.argv) > 2 else None
    result = analyze_screenshot(path, custom_prompt)
    print(result)
