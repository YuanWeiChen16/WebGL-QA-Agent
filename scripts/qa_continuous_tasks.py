"""QA Test: Login → Complete tasks continuously → Hall switch popup → Lobby
Keeps completing tasks (shooting, catching fish, etc.) until hall switch appears.
Account: 20260701244108 (fresh)
"""
import asyncio
import sys
import os
import json
import random
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.agent import GameSession
from webgl_qa.vision import analyze_screenshot

GAME_URL = os.environ.get("GAME_URL", "")
GAME_NAME = "example_game"
LOGIN_ID = os.environ.get("LOGIN_ID", "")

test_log = []
step_counter = 0


def log_step(action, screenshot_path, vision_result, file_size):
    global step_counter
    step_counter += 1
    entry = {
        "step": step_counter,
        "time": datetime.now().strftime("%H:%M:%S"),
        "action": action,
        "screenshot": screenshot_path,
        "file_size": file_size,
        "vision": vision_result,
    }
    test_log.append(entry)
    print(f"\n[Step {step_counter}] {action}", flush=True)
    print(f"  Screen: {vision_result.get('screen_id', '?')} | Size: {file_size}", flush=True)
    desc = vision_result.get('description', '')
    if desc:
        print(f"  Desc: {desc[:80]}", flush=True)
    task = vision_result.get('current_task', '')
    if task:
        print(f"  Task: {task}", flush=True)
    elements = vision_result.get('elements', [])
    if elements:
        for el in elements[:5]:
            loc = el.get('location', {})
            print(f"    - {el.get('label', el.get('id','?'))} @ ({loc.get('x','?')},{loc.get('y','?')})", flush=True)
    if vision_result.get('is_hall_switch'):
        print(f"  ★★★ HALL SWITCH DETECTED ★★★", flush=True)
    if vision_result.get('anomalies'):
        print(f"  Anomalies: {vision_result['anomalies']}", flush=True)


def parse_vision(raw_text):
    try:
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except:
        return {"screen_id": "parse_error", "description": raw_text[:200], "elements": [], "anomalies": []}


TASK_PROMPT = """Look at this game screenshot (1280x720). This is a fishing game (捕鱼/捕魚).

Tell me:
1. What screen is this? (gameplay, popup, hall_switch, lobby, reward, tutorial, loading)
2. Is there a TASK indicator? (e.g., "執行動作10次 3/10", "收集道具5個 2/5") — read the exact text
3. Is there a HALL SWITCH panel (切换厅/廳館選擇/room selection list)?
4. Is there a flashing finger/arrow indicator pointing somewhere?
5. Is there a reward/claim button?
6. Any popup overlaying the game?

IMPORTANT: "切换厅" or a panel showing multiple hall/room options = hall switch!

Respond ONLY in JSON:
{
  "screen_id": "gameplay|popup|hall_switch|lobby|reward|tutorial|loading|unknown",
  "description": "brief Chinese description",
  "current_task": "exact task text if visible, else empty string",
  "task_progress": "e.g. 3/10 or empty",
  "is_hall_switch": false,
  "is_popup": false,
  "has_reward_button": false,
  "has_finger_indicator": false,
  "finger_location": null,
  "elements": [{"id": "str", "type": "str", "label": "str", "location": {"x": int, "y": int}}],
  "suggested_click": {"x": int, "y": int, "reason": "str"},
  "anomalies": []
}"""


async def observe_and_analyze(session, action_desc, prompt=None):
    """Observe + Vision. Returns parsed dict."""
    obs = await session.observe()
    path = obs["screenshot_path"]
    size = os.path.getsize(path)
    raw = analyze_screenshot(path, prompt=prompt or TASK_PROMPT)
    parsed = parse_vision(raw)
    log_step(action_desc, path, parsed, size)
    return parsed


async def long_press_shoot(session, x=None, y=None, duration=1.0):
    """Long press to shoot. Random position in fish area if not specified."""
    if x is None:
        x = random.randint(300, 1000)
    if y is None:
        y = random.randint(150, 500)
    page = session.browser._page
    await page.mouse.move(x, y)
    await page.mouse.down()
    await asyncio.sleep(duration)
    await page.mouse.up()


async def main():
    print("="*60, flush=True)
    print(f"QA: Continuous Task Completion → Hall Switch → Lobby", flush=True)
    print(f"Account: {LOGIN_ID}", flush=True)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print("="*60, flush=True)

    session = GameSession(game_url=GAME_URL, game_name=GAME_NAME, headless=True)
    result = await session.start()
    print(f"Canvas: {result.get('canvas')}", flush=True)

    # === LOGIN ===
    await session.execute_action({"type": "wait", "seconds": 12})
    await observe_and_analyze(session, "Initial load")

    await session.execute_action({"type": "click", "x": 65, "y": 615})
    await session.execute_action({"type": "wait", "seconds": 2})
    await observe_and_analyze(session, "Click Debug登录")

    await session.execute_action({"type": "click", "x": 640, "y": 335})
    await session.execute_action({"type": "wait", "seconds": 0.5})
    await session.execute_action({"type": "type", "text": LOGIN_ID})
    await session.execute_action({"type": "wait", "seconds": 0.5})
    await observe_and_analyze(session, f"Type {LOGIN_ID}")

    await session.execute_action({"type": "click", "x": 640, "y": 490})
    await session.execute_action({"type": "wait", "seconds": 30})
    parsed = await observe_and_analyze(session, "Confirm + wait 30s")

    # === DISMISS INITIAL POPUPS ===
    print("\n--- Dismiss welcome popups ---", flush=True)
    for i in range(5):
        await session.execute_action({"type": "click", "x": 640, "y": 400})
        await session.execute_action({"type": "wait", "seconds": 2})
        parsed = await observe_and_analyze(session, f"Dismiss popup {i+1}")
        
        if parsed.get("screen_id") in ("gameplay", "fishing"):
            break
        if parsed.get("is_hall_switch"):
            break

    # === TASK COMPLETION LOOP ===
    print(f"\n{'#'*60}", flush=True)
    print(f"# TASK COMPLETION LOOP", flush=True)
    print(f"{'#'*60}", flush=True)

    found_hall_switch = False
    max_iterations = 60  # safety limit
    shoot_burst_count = 0

    for iteration in range(max_iterations):
        print(f"\n--- Iteration {iteration+1} ---", flush=True)

        # Determine action based on current state
        if parsed.get("is_hall_switch"):
            found_hall_switch = True
            print("\n★★★ HALL SWITCH APPEARED! ★★★", flush=True)
            break

        # === TASK-SPECIFIC HANDLERS FIRST (before generic popup dismiss) ===
        task_text = parsed.get("current_task", "").lower()
        
        # Lock card task — highest priority (its tutorial popup tricks generic dismiss)
        is_lock_task = any(kw in task_text for kw in ["锁定", "鎖定", "lock", "銀定"])
        if is_lock_task:
            print(f"  Lock card task detected! Activating lock...", flush=True)
            # Lock button is typically in skill bar or right side
            # Try clicking the lock/skill area — ask Vision for exact position
            obs_lock = await session.observe()
            raw_lock = analyze_screenshot(obs_lock["screenshot_path"], prompt="""This fishing game has a task "使用技能1次" (use a skill once).
I need to find and click the LOCK button (鎖定). It's usually:
- In the bottom skill bar area
- Or on the right side of the weapon controls
- Could be labeled 鎖定/锁定/Lock or have a crosshair/target icon
- The hint says "使用「鎖定」，可以持續瞄準目標開炮"

Find the lock button. Where should I click?
Respond in JSON:
{
  "screen_id": "gameplay",
  "lock_button_location": {"x": int, "y": int},
  "description": "Chinese desc",
  "elements": [{"id": "str", "type": "str", "label": "str", "location": {"x": int, "y": int}}],
  "anomalies": []
}""")
            parsed_lock = parse_vision(raw_lock)
            log_step("Analyze lock button position", obs_lock["screenshot_path"], parsed_lock, os.path.getsize(obs_lock["screenshot_path"]))
            
            lock_loc = parsed_lock.get("lock_button_location")
            if lock_loc:
                await session.execute_action({"type": "click", "x": lock_loc["x"], "y": lock_loc["y"]})
                await session.execute_action({"type": "wait", "seconds": 1})
                # After activating lock, shoot a fish
                await long_press_shoot(session, x=640, y=350, duration=1.5)
                await session.execute_action({"type": "wait", "seconds": 2})
            else:
                # Try common lock positions: right side skill area
                for lock_pos in [(1200, 570), (1210, 230), (760, 695), (525, 695)]:
                    await session.execute_action({"type": "click", "x": lock_pos[0], "y": lock_pos[1]})
                    await session.execute_action({"type": "wait", "seconds": 1})
                await long_press_shoot(session, x=640, y=350, duration=1.5)
                await session.execute_action({"type": "wait", "seconds": 2})
            
            parsed = await observe_and_analyze(session, "After lock card attempt")
            continue

        # Upgrade cannon task — progress comes from SHOOTING, not clicking the button
        is_upgrade_task = any(kw in task_text for kw in ["提升", "升级", "upgrade", "阶级", "階級"])
        if is_upgrade_task:
            # Just shoot fish — upgrade progress accumulates from shooting
            print(f"  Upgrade task — shooting to accumulate progress...", flush=True)
            for _ in range(8):
                await long_press_shoot(session, duration=1.0)
                await asyncio.sleep(0.2)
            shoot_burst_count += 8
            await session.execute_action({"type": "wait", "seconds": 1})
            parsed = await observe_and_analyze(session, f"Upgrade: shooting ({shoot_burst_count} total)")
            continue

        is_shooting_task = any(kw in task_text for kw in [
            "射击", "shoot", "射擊", "fire", "开火", "開火",
            "捕获", "catch", "捕獲", "捕鱼", "捕魚",
            "金币", "金幣", "coin",
        ])

        # === GENERIC UI HANDLERS (finger, reward, popup) ===
        if parsed.get("has_finger_indicator") and parsed.get("finger_location"):
            loc = parsed["finger_location"]
            await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
            await session.execute_action({"type": "wait", "seconds": 2})
            parsed = await observe_and_analyze(session, f"Click finger ({loc['x']},{loc['y']})")
            continue

        if parsed.get("has_reward_button"):
            suggested = parsed.get("suggested_click", {})
            x = suggested.get("x", 640)
            y = suggested.get("y", 400)
            await session.execute_action({"type": "click", "x": x, "y": y})
            await session.execute_action({"type": "wait", "seconds": 2})
            parsed = await observe_and_analyze(session, f"Claim reward ({x},{y})")
            continue

        if parsed.get("is_popup") and not is_shooting_task:
            suggested = parsed.get("suggested_click", {})
            x = suggested.get("x", 640)
            y = suggested.get("y", 400)
            await session.execute_action({"type": "click", "x": x, "y": y})
            await session.execute_action({"type": "wait", "seconds": 2})
            parsed = await observe_and_analyze(session, f"Dismiss popup ({x},{y})")
            continue

        # === SHOOTING / DEFAULT ===
        if is_shooting_task or parsed.get("screen_id") in ("gameplay", "fishing", "fishing_game_active", "fish_shooting_game_active", "gameplay_fishing", "gameplay_tutorial", "fishing_game_room", "fishing_game_waiting_room"):
            # Shoot in bursts then check
            print(f"  Shooting burst (5 shots)...", flush=True)
            for _ in range(5):
                await long_press_shoot(session, duration=0.8)
                await asyncio.sleep(0.3)
            shoot_burst_count += 5
            
            # Check state every 5 shots
            await session.execute_action({"type": "wait", "seconds": 1})
            parsed = await observe_and_analyze(session, f"After {shoot_burst_count} total shots")
        else:
            # Unknown state — try suggested click
            suggested = parsed.get("suggested_click", {})
            x = suggested.get("x", 640)
            y = suggested.get("y", 400)
            reason = suggested.get("reason", "unknown state")
            await session.execute_action({"type": "click", "x": x, "y": y})
            await session.execute_action({"type": "wait", "seconds": 2})
            parsed = await observe_and_analyze(session, f"Suggested: ({x},{y}) - {reason}")

    # === HALL SWITCH PHASE ===
    if found_hall_switch:
        print(f"\n{'#'*60}", flush=True)
        print(f"# HALL SWITCH → LOBBY", flush=True)
        print(f"{'#'*60}", flush=True)

        # Analyze hall switch panel and select a hall
        HALL_PROMPT = """This is a hall/room selection panel (切换厅/廳館選擇).
I need to:
1. Select/switch to a different hall
2. After switching, find the "回到大厅" (Return to Lobby) button on the left side

What halls/rooms are available? Which should I click to switch?
Look for: hall list, room buttons, switch/enter buttons.

Respond in JSON:
{
  "screen_id": "hall_switch",
  "description": "Chinese description of what you see",
  "halls": [{"name": "str", "location": {"x": int, "y": int}}],
  "elements": [{"id": "str", "type": "str", "label": "str", "location": {"x": int, "y": int}}],
  "suggested_click": {"x": int, "y": int, "reason": "str"},
  "anomalies": []
}"""

        parsed = await observe_and_analyze(session, "Analyze hall switch panel", prompt=HALL_PROMPT)

        # Click to switch hall
        for hall_step in range(10):
            suggested = parsed.get("suggested_click", {})
            x = suggested.get("x", 640)
            y = suggested.get("y", 400)
            reason = suggested.get("reason", "")

            await session.execute_action({"type": "click", "x": x, "y": y})
            await session.execute_action({"type": "wait", "seconds": 3})

            LOBBY_PROMPT = """Look at this game screenshot (1280x720).
After switching halls, the LEFT SIDE should show new navigation buttons.
One of them should be "回到大厅" (Return to Lobby).

Is there:
- A "回到大厅" button? Where?
- Left-side navigation buttons?
- Any lobby/hall navigation?

Respond in JSON:
{
  "screen_id": "string",
  "description": "Chinese",
  "has_lobby_button": true/false,
  "lobby_button_location": {"x": int, "y": int} or null,
  "elements": [{"id": "str", "type": "str", "label": "str", "location": {"x": int, "y": int}}],
  "suggested_click": {"x": int, "y": int, "reason": "str"},
  "anomalies": []
}"""
            parsed = await observe_and_analyze(session, f"Hall step {hall_step+1}: ({x},{y}) {reason}", prompt=LOBBY_PROMPT)

            if parsed.get("has_lobby_button") and parsed.get("lobby_button_location"):
                loc = parsed["lobby_button_location"]
                print(f"\n★★★ CLICKING LOBBY at ({loc['x']},{loc['y']}) ★★★", flush=True)
                await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
                await session.execute_action({"type": "wait", "seconds": 5})
                parsed = await observe_and_analyze(session, "Entered Lobby!")
                break

            # Also scan elements
            for el in parsed.get("elements", []):
                label = el.get("label", "")
                if any(kw in label for kw in ["大厅", "大廳", "lobby", "回到"]):
                    loc = el["location"]
                    print(f"\n★ Found lobby in elements: {label} @ ({loc['x']},{loc['y']})", flush=True)
                    await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
                    await session.execute_action({"type": "wait", "seconds": 5})
                    parsed = await observe_and_analyze(session, f"Click {label}")
                    break

    # === SUMMARY ===
    print(f"\n\n{'='*60}", flush=True)
    print(f"TEST COMPLETE", flush=True)
    print(f"{'='*60}", flush=True)
    print(f"Total steps: {step_counter}", flush=True)
    print(f"Total shots fired: {shoot_burst_count}", flush=True)
    print(f"Hall switch found: {found_hall_switch}", flush=True)
    print(f"Run dir: {session.run_dir}", flush=True)

    log_path = session.run_dir / "qa_continuous_test_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(test_log, f, ensure_ascii=False, indent=2)
    print(f"Log: {log_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
