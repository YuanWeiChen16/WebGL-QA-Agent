"""Shared action sequences for WebGL QA Agent.

All game-specific coordinates and sequences are read from the knowledge base.
This module provides only generic execution engines.
"""

import asyncio
import random
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Pattern for random value placeholders in YAML: random(min-max)
_RANDOM_PATTERN = re.compile(r"random\((\d+)-(\d+)\)")


def _resolve_value(value):
    """Resolve a value that might contain 'random(min-max)' or be 'random'."""
    if value == "random":
        return None  # Caller decides
    if isinstance(value, str):
        match = _RANDOM_PATTERN.match(value)
        if match:
            lo, hi = int(match.group(1)), int(match.group(2))
            return random.randint(lo, hi)
    return value


def _interpolate_variables(text: str, variables: dict) -> str:
    """Replace ${VAR_NAME} placeholders with values from variables dict."""
    if not isinstance(text, str) or "${" not in text:
        return text
    for key, val in variables.items():
        text = text.replace(f"${{{key}}}", str(val))
    return text


async def long_press_shoot(session, x: int = None, y: int = None, duration: float = 0.8):
    """Long press to fire cannon at a position.

    Args:
        session: GameSession instance
        x, y: Target coordinates (random within shooting area if None)
        duration: Hold duration in seconds
    """
    if x is None or y is None:
        area = session.config.get_section("shooting.target_area")
        if area:
            x = x or random.randint(area.get("x_min", 300), area.get("x_max", 1000))
            y = y or random.randint(area.get("y_min", 150), area.get("y_max", 500))
        else:
            x = x or random.randint(300, 1000)
            y = y or random.randint(150, 500)

    page = session.browser._page
    await page.mouse.move(x, y)
    await page.mouse.down()
    await asyncio.sleep(duration)
    await page.mouse.up()


async def burst_shoot(session, count: int = None, duration: float = None, interval: float = None):
    """Fire multiple shots in sequence. Parameters from config if not specified."""
    cfg = session.config
    count = count or cfg.get("shooting.burst_count", 8)
    duration = duration or cfg.get("shooting.duration_min", 0.8)
    interval = interval or cfg.get("shooting.burst_interval", 0.3)

    for _ in range(count):
        await long_press_shoot(session, duration=duration)
        await asyncio.sleep(interval)


async def execute_steps(session, steps: list, variables: dict = None,
                        retry_on_fail: bool = True):
    """Execute a list of action steps from knowledge base.

    Args:
        session: GameSession instance
        steps: List of step dicts from KnowledgeBase.get_action_sequence()
            Each step: {"type": "click|wait|longpress|type|drag", "x": int, "y": int, ...}
        variables: Dict for ${VAR} interpolation in step values (e.g., {"LOGIN_ID": "..."})
        retry_on_fail: If True, retry failed steps once after a brief pause
    """
    variables = variables or {}

    for i, step in enumerate(steps):
        step_type = step.get("type", "")
        wait_after = step.get("wait", 0)

        try:
            if step_type == "click":
                x = _resolve_value(step.get("x", 640)) or 640
                y = _resolve_value(step.get("y", 360)) or 360
                await session.execute_action({"type": "click", "x": x, "y": y})

            elif step_type == "wait":
                seconds = step.get("seconds", wait_after or 1)
                await session.execute_action({"type": "wait", "seconds": seconds})

            elif step_type == "longpress":
                x = _resolve_value(step.get("x", 640))
                y = _resolve_value(step.get("y", 360))
                duration = step.get("duration", 0.8)
                repeat = step.get("repeat", 1)
                interval = step.get("interval", 0.3)
                for _ in range(repeat):
                    lx = x if x else None
                    ly = y if y else None
                    await long_press_shoot(session, x=lx, y=ly, duration=duration)
                    if repeat > 1:
                        await asyncio.sleep(interval)

            elif step_type == "type":
                text = _interpolate_variables(step.get("text", ""), variables)
                await session.execute_action({"type": "type", "text": text})

            elif step_type == "drag":
                await session.execute_action({
                    "type": "drag",
                    "from_x": step.get("from_x", 0),
                    "from_y": step.get("from_y", 0),
                    "to_x": step.get("to_x", 0),
                    "to_y": step.get("to_y", 0),
                })

            else:
                logger.warning(f"Unknown step type '{step_type}' in step {i+1}, skipping")
                continue

            # Wait after action if specified
            if wait_after and step_type != "wait":
                await session.execute_action({"type": "wait", "seconds": wait_after})

        except Exception as e:
            logger.warning(f"Step {i+1}/{len(steps)} failed ({step_type}): {e}")
            if retry_on_fail:
                await asyncio.sleep(1)
                try:
                    if step_type == "click":
                        await session.execute_action({"type": "click", "x": _resolve_value(step.get("x", 640)) or 640, "y": _resolve_value(step.get("y", 360)) or 360})
                    elif step_type == "longpress":
                        await long_press_shoot(session, x=_resolve_value(step.get("x")), y=_resolve_value(step.get("y")), duration=step.get("duration", 0.8))
                    elif step_type == "type":
                        await session.execute_action({"type": "type", "text": _interpolate_variables(step.get("text", ""), variables)})
                    elif step_type == "drag":
                        await session.execute_action({"type": "drag", "from_x": step.get("from_x", 0), "from_y": step.get("from_y", 0), "to_x": step.get("to_x", 0), "to_y": step.get("to_y", 0)})
                except Exception as retry_err:
                    logger.error(f"Step {i+1} retry also failed: {retry_err}. Aborting sequence.")
                    return
            else:
                return


async def run_action_sequence(session, system_id: str, action_name: str,
                              variables: dict = None) -> bool:
    """Run a named action sequence from the knowledge base.

    Args:
        session: GameSession instance
        system_id: System ID (e.g., "login", "upgrade", "skills")
        action_name: Action name (e.g., "debug_login", "upgrade_cannon")
        variables: Dict for ${VAR} interpolation

    Returns:
        True if steps were found and executed, False if action not found.
    """
    steps = session.knowledge.get_action_sequence(system_id, action_name)
    if not steps:
        logger.warning(f"Action '{action_name}' not found in system '{system_id}'")
        return False
    await execute_steps(session, steps, variables=variables)
    return True


async def login_sequence(session, login_id: str, mode: str = "debug"):
    """Execute login flow from knowledge base.

    Args:
        session: GameSession instance
        login_id: Account ID to use
        mode: "debug" or "game" — maps to action names in systems/login.yaml
    """
    action_map = {
        "debug": "debug_login",
        "game": "game_login",
    }
    action_name = action_map.get(mode, "debug_login")
    variables = {"LOGIN_ID": login_id}

    success = await run_action_sequence(session, "login", action_name, variables=variables)
    if not success:
        logger.error(f"Login action '{action_name}' not found in knowledge base")


async def dismiss_popups(session, max_clicks: int = None, wait_between: float = None):
    """Click to dismiss welcome/tutorial popups using config values.

    Args:
        session: GameSession instance
        max_clicks: Override max click count (default from config)
        wait_between: Override wait between clicks (default from config)
    """
    cfg = session.config
    popup_cfg = cfg.get_section("popup_dismiss")
    max_clicks = max_clicks if max_clicks is not None else popup_cfg.get("max_clicks", 5)
    pos = popup_cfg.get("click_position", {"x": 640, "y": 400})
    wait_between = wait_between if wait_between is not None else popup_cfg.get("wait_between", 2.0)

    for _ in range(max_clicks):
        await session.execute_action({"type": "click", "x": pos["x"], "y": pos["y"]})
        await session.execute_action({"type": "wait", "seconds": wait_between})


async def upgrade_cannon(session):
    """Execute upgrade cannon sequence from knowledge."""
    await run_action_sequence(session, "upgrade", "upgrade_cannon")


async def use_lock_card(session):
    """Execute lock card sequence from knowledge."""
    await run_action_sequence(session, "skills", "use_lock_card")


async def click_menu(session):
    """Click the menu button from knowledge."""
    element = session.knowledge.get_element("gameplay", "menu_button")
    if element:
        loc = element.get("location", {})
        await session.execute_action({"type": "click", "x": loc.get("x", 60), "y": loc.get("y", 160)})
    else:
        # Fallback: try gameplay system elements
        steps = session.knowledge.get_action_sequence("gameplay", "open_menu")
        if steps:
            await execute_steps(session, steps)
        else:
            logger.warning("Menu button location not found in knowledge")
    await session.execute_action({"type": "wait", "seconds": 3})
