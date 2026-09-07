"""QA Runner — fast execution, stops when stuck for Hermes to decide.

Usage:
  # First run (login + auto tasks):
  python qa_runner.py start
  
  # Continue from where it stopped (with specific action):
  python qa_runner.py continue click 65 240
  python qa_runner.py continue shoot 10
  python qa_runner.py continue wait 5
  
  # Just observe current state:
  python qa_runner.py observe
"""
import asyncio
import sys
import os
import json
import random
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.agent import GameSession

GAME_URL = os.environ.get("GAME_URL", "")
GAME_NAME = "example_game"
STATE_FILE = (Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "runs" / "qa_state.json")


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


async def long_press(page, x, y, duration=1.0):
    await page.mouse.move(x, y)
    await page.mouse.down()
    await asyncio.sleep(duration)
    await page.mouse.up()


async def observe_state(session) -> dict:
    """Take screenshot + basic state info. No Vision — just raw data."""
    obs = await session.observe()
    path = obs["screenshot_path"]
    size = os.path.getsize(path)
    console = obs.get("console_logs", [])
    errors = obs.get("console_errors", [])
    return {
        "screenshot": path,
        "size": size,
        "step": obs.get("step", 0),
        "console_errors": errors,
        "pixel_change": obs.get("pixel_change_ratio", 0),
    }


async def do_login(session, login_id):
    """Fast login sequence — no Vision needed."""
    print(f"Logging in with {login_id}...", flush=True)
    
    await session.execute_action({"type": "wait", "seconds": 12})
    await session.execute_action({"type": "click", "x": 65, "y": 615})  # Debug登录
    await session.execute_action({"type": "wait", "seconds": 2})
    await session.execute_action({"type": "click", "x": 640, "y": 335})  # Input
    await session.execute_action({"type": "wait", "seconds": 0.5})
    await session.execute_action({"type": "type", "text": login_id})
    await session.execute_action({"type": "wait", "seconds": 0.5})
    await session.execute_action({"type": "click", "x": 640, "y": 490})  # 确认
    await session.execute_action({"type": "wait", "seconds": 30})
    
    # Dismiss welcome popups (click center x5)
    for i in range(5):
        await session.execute_action({"type": "click", "x": 640, "y": 400})
        await session.execute_action({"type": "wait", "seconds": 2})
    
    print("Login complete.", flush=True)


async def shoot_burst(session, count=5, duration=0.8):
    """Shoot fish rapidly."""
    page = session.browser._page
    for _ in range(count):
        x = random.randint(300, 1000)
        y = random.randint(150, 500)
        await long_press(page, x, y, duration)
        await asyncio.sleep(0.2)


async def auto_tasks(session, max_iterations=30):
    """Run tasks automatically. Returns when stuck or hall switch detected.
    
    Stuck = same screenshot size (±5%) for 3 consecutive observations.
    """
    prev_sizes = []
    stuck_count = 0
    shoot_total = 0
    
    for i in range(max_iterations):
        # Shoot burst
        print(f"  [{i+1}/{max_iterations}] Shooting 8...", flush=True)
        await shoot_burst(session, count=8, duration=0.8)
        shoot_total += 8
        await session.execute_action({"type": "wait", "seconds": 1})
        
        # Click task bar area (claim rewards if available)
        await session.execute_action({"type": "click", "x": 640, "y": 140})
        await session.execute_action({"type": "wait", "seconds": 1.5})
        
        # Click center (dismiss any popup)
        await session.execute_action({"type": "click", "x": 640, "y": 400})
        await session.execute_action({"type": "wait", "seconds": 1})
        
        # Click 升炮 button area (multiple nearby positions to ensure hit)
        for ux, uy in [(65, 240), (60, 235), (70, 245), (55, 240)]:
            await session.execute_action({"type": "click", "x": ux, "y": uy})
            await session.execute_action({"type": "wait", "seconds": 0.5})
        await session.execute_action({"type": "wait", "seconds": 1})
        
        # Dismiss any upgrade popup that appeared
        await session.execute_action({"type": "click", "x": 640, "y": 400})
        await session.execute_action({"type": "wait", "seconds": 0.5})
        
        # Observe
        obs = await observe_state(session)
        size = obs["size"]
        print(f"    Size: {size}, Shots: {shoot_total}", flush=True)
        
        # Stuck detection: if size is very small or hasn't changed category
        # Small size (<200KB) usually means overlay/modal blocking gameplay
        if size < 200000:
            print(f"  ⚠ Small screenshot ({size}B) — possible blocking popup!", flush=True)
            stuck_count += 1
        else:
            stuck_count = 0
        
        if stuck_count >= 3:
            print(f"  STUCK detected after {stuck_count} small screenshots.", flush=True)
            return {"status": "stuck", "screenshot": obs["screenshot"], "shots": shoot_total, "reason": "blocking_popup"}
        
        prev_sizes.append(size)
    
    # Finished max iterations
    obs = await observe_state(session)
    return {"status": "max_iterations", "screenshot": obs["screenshot"], "shots": shoot_total}


async def run_start(login_id):
    """Full fresh start: login + auto tasks."""
    session = GameSession(game_url=GAME_URL, game_name=GAME_NAME, headless=True)
    result = await session.start()
    print(f"Canvas: {result.get('canvas')}", flush=True)
    
    await do_login(session, login_id)
    
    # Take initial gameplay screenshot
    obs = await observe_state(session)
    print(f"Gameplay screenshot: {obs['screenshot']} ({obs['size']}B)", flush=True)
    
    # Save state for continue
    save_state({
        "login_id": login_id,
        "run_dir": str(session.run_dir),
        "last_screenshot": obs["screenshot"],
        "phase": "tasks",
    })
    
    # Run auto task loop
    result = await auto_tasks(session, max_iterations=40)
    
    # Final screenshot
    obs = await observe_state(session)
    save_state({
        "login_id": login_id,
        "run_dir": str(session.run_dir),
        "last_screenshot": obs["screenshot"],
        "phase": "stopped",
        "stop_reason": result["status"],
        "total_shots": result["shots"],
    })
    
    print(f"\n=== STOPPED ===", flush=True)
    print(f"Reason: {result['status']}", flush=True)
    print(f"Screenshot: {obs['screenshot']}", flush=True)
    print(f"Total shots: {result['shots']}", flush=True)
    print(f"Run dir: {session.run_dir}", flush=True)
    print(f"\n→ Use vision to check screenshot and decide next action.", flush=True)


async def run_continue(actions):
    """Continue from saved state with specific actions."""
    state = load_state()
    if not state:
        print("ERROR: No saved state. Run 'start' first.", flush=True)
        return
    
    login_id = state["login_id"]
    
    # Reconnect (new session, same account)
    session = GameSession(game_url=GAME_URL, game_name=GAME_NAME, headless=True)
    result = await session.start()
    await do_login(session, login_id)
    
    # Execute requested actions
    page = session.browser._page
    for action in actions:
        parts = action.split()
        cmd = parts[0]
        
        if cmd == "click":
            x, y = int(parts[1]), int(parts[2])
            print(f"Click ({x}, {y})", flush=True)
            await session.execute_action({"type": "click", "x": x, "y": y})
            await session.execute_action({"type": "wait", "seconds": 2})
            
        elif cmd == "shoot":
            count = int(parts[1]) if len(parts) > 1 else 10
            print(f"Shooting {count}x...", flush=True)
            await shoot_burst(session, count=count)
            
        elif cmd == "wait":
            secs = float(parts[1]) if len(parts) > 1 else 3
            print(f"Wait {secs}s", flush=True)
            await session.execute_action({"type": "wait", "seconds": secs})
            
        elif cmd == "longpress":
            x, y = int(parts[1]), int(parts[2])
            dur = float(parts[3]) if len(parts) > 3 else 1.0
            print(f"Long press ({x},{y}) for {dur}s", flush=True)
            await long_press(page, x, y, dur)
            
        elif cmd == "type":
            text = " ".join(parts[1:])
            print(f"Type: {text}", flush=True)
            await session.execute_action({"type": "type", "text": text})
            
        elif cmd == "tasks":
            max_iter = int(parts[1]) if len(parts) > 1 else 30
            print(f"Auto tasks ({max_iter} iterations)...", flush=True)
            result = await auto_tasks(session, max_iterations=max_iter)
            print(f"  Result: {result['status']}", flush=True)
    
    # Final observe
    obs = await observe_state(session)
    save_state({
        "login_id": login_id,
        "run_dir": str(session.run_dir),
        "last_screenshot": obs["screenshot"],
        "phase": "continued",
    })
    print(f"\nScreenshot: {obs['screenshot']}", flush=True)
    print(f"Size: {obs['size']}B", flush=True)


async def run_observe_only():
    """Just login and take a screenshot to check current state."""
    state = load_state()
    login_id = state.get("login_id", os.environ.get("LOGIN_ID", ""))
    
    session = GameSession(game_url=GAME_URL, game_name=GAME_NAME, headless=True)
    result = await session.start()
    await do_login(session, login_id)
    
    obs = await observe_state(session)
    print(f"Screenshot: {obs['screenshot']}", flush=True)
    print(f"Size: {obs['size']}B", flush=True)


def main():
    if len(sys.argv) < 2:
        print("Usage: qa_runner.py start|continue|observe [args...]")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "start":
        login_id = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("LOGIN_ID", "")
        asyncio.run(run_start(login_id))
    elif cmd == "continue":
        actions = sys.argv[2:]  # e.g. ["click 65 240", "shoot 10"]
        asyncio.run(run_continue(actions))
    elif cmd == "observe":
        asyncio.run(run_observe_only())
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
