"""Fast menu→lobby: login with same account, click menu then immediately click 回大廳."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Vision gateway credentials are read from the environment (see .env.example)

from webgl_qa.agent import GameSession
from webgl_qa.vision import analyze_screenshot_structured
from webgl_qa.actions import login_sequence, dismiss_popups

GAME_URL = os.environ.get("GAME_URL", "")
LOGIN_ID = os.environ.get("LOGIN_ID", "")


async def main():
    print("=== Fast Menu → Lobby Script ===", flush=True)

    session = GameSession(
        game_url=GAME_URL,
        game_name="example_game",
        headless=False,
    )
    result = await session.start()
    print(f"Canvas: {result['canvas']}", flush=True)

    # Login
    print("Logging in...", flush=True)
    await login_sequence(session, LOGIN_ID, mode="debug")
    print("Login done, waiting 30s for game load...", flush=True)
    await asyncio.sleep(30)

    # Dismiss initial popups (3 rounds)
    print("Dismissing popups...", flush=True)
    for i in range(3):
        obs = await session.observe()
        path = obs["screenshot_path"]
        parsed = analyze_screenshot_structured(path)
        print(f"  Popup {i+1}: {parsed.get('screen_id')} - {parsed.get('description', '')[:60]}", flush=True)
        if parsed.get("is_popup") or parsed.get("screen_id") in ("popup", "welcome"):
            click_pos = parsed.get("suggested_click", {"x": 640, "y": 400})
            await session.execute_action({"type": "click", "x": click_pos["x"], "y": click_pos["y"]})
            await asyncio.sleep(2)
        else:
            break

    # Wait a bit for gameplay to settle
    await asyncio.sleep(3)

    # Take a screenshot to see current state
    obs = await session.observe()
    parsed = analyze_screenshot_structured(obs["screenshot_path"])
    print(f"\nCurrent state: {parsed.get('screen_id')}", flush=True)
    print(f"  Desc: {parsed.get('description', '')[:80]}", flush=True)

    # Now do the FAST menu → lobby sequence
    # Key: no Vision between menu click and lobby click!
    print("\n=== FAST MENU → LOBBY ===", flush=True)
    
    for attempt in range(5):
        print(f"\nAttempt {attempt+1}: clicking menu (60, 160)...", flush=True)
        await session.execute_action({"type": "click", "x": 60, "y": 160})
        
        # Wait just 300ms for menu to appear, then immediately click 回大廳
        await asyncio.sleep(0.3)
        
        print(f"  Immediately clicking 回大廳 (350, 165)...", flush=True)
        await session.execute_action({"type": "click", "x": 350, "y": 165})
        
        # Wait 3s to see if it worked
        await asyncio.sleep(3)
        
        # Now check with Vision
        obs = await session.observe()
        parsed = analyze_screenshot_structured(obs["screenshot_path"])
        screen_id = parsed.get("screen_id", "")
        desc = parsed.get("description", "")
        print(f"  Result: {screen_id} - {desc[:80]}", flush=True)
        
        # Check if we're in lobby or loading to lobby
        if "lobby" in screen_id.lower() or "大廳" in desc or "大厅" in desc or "lobby" in desc.lower():
            print("\n★★★ SUCCESS! Reached lobby! ★★★", flush=True)
            # Take final screenshot
            obs = await session.observe()
            print(f"Final screenshot: {obs['screenshot_path']}", flush=True)
            return
        
        # Check for confirmation dialog
        if "confirm" in screen_id.lower() or "確認" in desc or "确认" in desc:
            print("  Found confirmation dialog, clicking confirm...", flush=True)
            click_pos = parsed.get("suggested_click", {"x": 640, "y": 400})
            await session.execute_action({"type": "click", "x": click_pos["x"], "y": click_pos["y"]})
            await asyncio.sleep(3)
            obs = await session.observe()
            parsed = analyze_screenshot_structured(obs["screenshot_path"])
            print(f"  After confirm: {parsed.get('screen_id')} - {parsed.get('description', '')[:60]}", flush=True)
            if "lobby" in parsed.get("screen_id", "").lower() or "大廳" in parsed.get("description", ""):
                print("\n★★★ SUCCESS! Reached lobby! ★★★", flush=True)
                return
        
        # If still in gameplay, maybe menu didn't open or closed too fast
        # Try with slightly longer delay
        await asyncio.sleep(2)
    
    print("\n[FAILED] Could not reach lobby after 5 attempts.", flush=True)
    # Final screenshot for debugging
    obs = await session.observe()
    final_parsed = analyze_screenshot_structured(obs["screenshot_path"])
    print(f"Final state: {final_parsed.get('screen_id')} - {final_parsed.get('description', '')[:100]}", flush=True)
    print(f"Screenshot: {obs['screenshot_path']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
