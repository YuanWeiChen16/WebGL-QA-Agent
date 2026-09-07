"""Minimal session starter - just opens browser, logs in, waits. AI drives from there."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.agent import GameSession
from webgl_qa.actions import login_sequence

GAME_URL = os.environ.get("GAME_URL", "")
LOGIN_ID = os.environ.get("LOGIN_ID", "")  # Existing account that completed tasks
SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lobby_exploration")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

async def main():
    session = GameSession(
        game_url=GAME_URL,
        game_name="example_game",
        headless=False,
    )
    
    print("Starting session...", flush=True)
    result = await session.start()
    print(f"Session started. Canvas: {result.get('canvas')}", flush=True)
    
    # Login
    print("Logging in...", flush=True)
    await login_sequence(session, LOGIN_ID, mode="debug")
    print("Login done, waiting 30s for load...", flush=True)
    await asyncio.sleep(30)
    
    # Take screenshot
    obs = await session.observe()
    ss_path = obs.get("screenshot_path", "")
    print(f"SCREENSHOT: {ss_path}", flush=True)
    
    # Keep browser alive, poll cmd.txt for commands
    CMD_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cmd.txt")
    print("Ready. Watching cmd.txt for commands...", flush=True)
    
    while True:
        try:
            if os.path.exists(CMD_FILE):
                with open(CMD_FILE, "r", encoding="utf-8") as f:
                    line = f.read().strip()
                if line:
                    with open(CMD_FILE, "w") as f:
                        f.write("")
                    
                    if line == "quit":
                        print("Quitting.", flush=True)
                        break
                    elif line == "screenshot":
                        obs = await session.observe()
                        print(f"SCREENSHOT: {obs.get('screenshot_path', '')}", flush=True)
                    elif line.startswith("click "):
                        parts = line.split()
                        x, y = int(parts[1]), int(parts[2])
                        await session.execute_action({"type": "click", "x": x, "y": y})
                        print(f"Clicked ({x},{y})", flush=True)
                        await asyncio.sleep(1.5)
                        obs = await session.observe()
                        print(f"SCREENSHOT: {obs.get('screenshot_path', '')}", flush=True)
                    elif line.startswith("wait "):
                        secs = int(line.split()[1])
                        await asyncio.sleep(secs)
                        obs = await session.observe()
                        print(f"SCREENSHOT: {obs.get('screenshot_path', '')}", flush=True)
                    elif line.startswith("scroll "):
                        parts = line.split()
                        x, y, dy = int(parts[1]), int(parts[2]), int(parts[3])
                        await session.execute_action({"type": "scroll", "x": x, "y": y, "delta_y": dy})
                        print(f"Scrolled at ({x},{y}) delta={dy}", flush=True)
                        await asyncio.sleep(1.5)
                        obs = await session.observe()
                        print(f"SCREENSHOT: {obs.get('screenshot_path', '')}", flush=True)
                    else:
                        print(f"Unknown command: {line}", flush=True)
            
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Error: {e}", flush=True)
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
