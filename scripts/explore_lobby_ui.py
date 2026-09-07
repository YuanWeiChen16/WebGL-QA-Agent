"""Explore lobby UI: login → fast menu→lobby → systematically screenshot and analyze all elements."""
import asyncio
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Vision gateway credentials are read from the environment (see .env.example)

from webgl_qa.agent import GameSession
from webgl_qa.vision import analyze_screenshot_structured, analyze_screenshot
from webgl_qa.actions import login_sequence

GAME_URL = os.environ.get("GAME_URL", "")
LOGIN_ID = os.environ.get("LOGIN_ID", "")


async def main():
    print("=== Lobby UI Exploration ===", flush=True)
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}", flush=True)

    session = GameSession(
        game_url=GAME_URL,
        game_name="example_game",
        headless=False,
    )
    result = await session.start()
    print(f"Canvas: {result['canvas']}", flush=True)

    # Login
    print("\n[1] Logging in...", flush=True)
    await login_sequence(session, LOGIN_ID, mode="debug")
    print("Login done, waiting 30s for game load...", flush=True)
    await asyncio.sleep(30)

    # Dismiss initial popups
    print("\n[2] Dismissing popups...", flush=True)
    for i in range(5):
        obs = await session.observe()
        parsed = analyze_screenshot_structured(obs["screenshot_path"])
        screen_id = parsed.get("screen_id", "")
        desc = parsed.get("description", "")[:80]
        print(f"  Round {i+1}: {screen_id} - {desc}", flush=True)

        if parsed.get("is_popup") or screen_id in ("popup", "welcome", "tutorial"):
            click_pos = parsed.get("suggested_click", {"x": 640, "y": 400})
            if isinstance(click_pos, dict):
                await session.execute_action({"type": "click", "x": click_pos.get("x", 640), "y": click_pos.get("y", 400)})
            else:
                await session.execute_action({"type": "click", "x": 640, "y": 400})
            await asyncio.sleep(2)
        elif "gameplay" in screen_id or "fishing" in screen_id:
            print("  → Reached gameplay, breaking.", flush=True)
            break
        else:
            await session.execute_action({"type": "click", "x": 640, "y": 400})
            await asyncio.sleep(2)

    await asyncio.sleep(3)

    # Verify we're in gameplay with menu button
    obs = await session.observe()
    parsed = analyze_screenshot_structured(obs["screenshot_path"])
    print(f"\n[3] Current state: {parsed.get('screen_id')} - {parsed.get('description', '')[:80]}", flush=True)

    # Fast menu → lobby (timing critical, no Vision between clicks)
    print("\n[4] === FAST MENU → LOBBY ===", flush=True)
    lobby_reached = False

    for attempt in range(5):
        print(f"\n  Attempt {attempt+1}:", flush=True)
        # Click menu
        await session.execute_action({"type": "click", "x": 60, "y": 160})
        await asyncio.sleep(0.3)
        # Click 回大廳
        await session.execute_action({"type": "click", "x": 350, "y": 165})
        await asyncio.sleep(3)

        # Check result
        obs = await session.observe()
        parsed = analyze_screenshot_structured(obs["screenshot_path"])
        screen_id = parsed.get("screen_id", "")
        desc = parsed.get("description", "")
        print(f"    Result: {screen_id} - {desc[:80]}", flush=True)

        # Check for confirmation dialog
        if "confirm" in screen_id.lower() or "確認" in desc or "确认" in desc:
            print("    → Confirmation dialog, clicking confirm...", flush=True)
            click_pos = parsed.get("suggested_click", {"x": 640, "y": 400})
            if isinstance(click_pos, dict):
                await session.execute_action({"type": "click", "x": click_pos.get("x", 640), "y": click_pos.get("y", 400)})
            else:
                await session.execute_action({"type": "click", "x": 640, "y": 400})
            await asyncio.sleep(5)

        # Recheck
        obs = await session.observe()
        parsed = analyze_screenshot_structured(obs["screenshot_path"])
        screen_id = parsed.get("screen_id", "")
        desc = parsed.get("description", "")

        if "lobby" in screen_id.lower() or "大廳" in desc or "大厅" in desc or "lobby" in desc.lower():
            print("\n  ★★★ SUCCESS! Reached lobby! ★★★", flush=True)
            lobby_reached = True
            break

        await asyncio.sleep(2)

    if not lobby_reached:
        print("\n[FAILED] Could not reach lobby. Final state screenshot saved.", flush=True)
        obs = await session.observe()
        print(f"Final screenshot: {obs['screenshot_path']}", flush=True)
        return

    # ========== LOBBY EXPLORATION ==========
    print("\n\n" + "="*60, flush=True)
    print("=== LOBBY UI EXPLORATION ===", flush=True)
    print("="*60, flush=True)

    lobby_data = {
        "timestamp": datetime.now().isoformat(),
        "screens": [],
    }

    # Phase 1: Overall lobby screenshot with detailed analysis
    print("\n[5] Phase 1: Overall lobby analysis", flush=True)
    obs = await session.observe()
    lobby_ss = obs["screenshot_path"]
    print(f"  Screenshot: {lobby_ss}", flush=True)

    # Use free-form Vision for more detailed analysis
    detail_prompt = """This is a game lobby/main menu screen. Please provide an extremely detailed analysis:

1. List ALL visible UI elements (buttons, icons, labels, panels, tabs, navigation items)
2. For each element, provide:
   - Exact position (x, y) in the 1280x720 viewport
   - Size estimate (width x height)
   - Text label (if any, in original language)
   - Type (button, icon, label, panel, tab, image, counter)
   - Visual description (color, shape, style)
3. Describe the overall layout structure (top bar, bottom bar, center content, sidebars)
4. Note any scrollable areas or pagination indicators
5. Identify which elements appear clickable/interactive vs decorative

Be as thorough as possible. This is for QA documentation purposes."""

    lobby_detail = analyze_screenshot(lobby_ss, prompt=detail_prompt)
    print(f"\n  Vision analysis (overall):\n{lobby_detail[:3000]}", flush=True)
    lobby_data["screens"].append({
        "name": "lobby_main",
        "screenshot": lobby_ss,
        "analysis": lobby_detail,
    })

    # Phase 2: Structured analysis for element positions
    print("\n[6] Phase 2: Structured element positions", flush=True)
    parsed = analyze_screenshot_structured(lobby_ss)
    print(f"  screen_id: {parsed.get('screen_id')}", flush=True)
    print(f"  description: {parsed.get('description', '')[:120]}", flush=True)
    elements = parsed.get("elements", [])
    print(f"  elements ({len(elements)}):", flush=True)
    for el in elements:
        if isinstance(el, dict):
            print(f"    - {el.get('label', '?')} @ ({el.get('location', {}).get('x', '?')}, {el.get('location', {}).get('y', '?')}) [{el.get('type', '?')}]", flush=True)
        else:
            print(f"    - (string) {el}", flush=True)
    lobby_data["screens"].append({
        "name": "lobby_structured",
        "parsed": parsed,
    })

    # Phase 3: Click on different areas to discover sub-menus/panels
    # Try clicking on various UI areas and document what happens
    exploration_targets = [
        {"name": "top_left_area", "x": 100, "y": 50, "desc": "Top-left (possibly back/home)"},
        {"name": "top_right_area", "x": 1200, "y": 50, "desc": "Top-right (possibly settings/profile)"},
        {"name": "bottom_center", "x": 640, "y": 680, "desc": "Bottom center (possibly navigation bar)"},
        {"name": "bottom_left", "x": 100, "y": 680, "desc": "Bottom left area"},
        {"name": "bottom_right", "x": 1180, "y": 680, "desc": "Bottom right area"},
        {"name": "center_left", "x": 200, "y": 360, "desc": "Center left (possible game category)"},
        {"name": "center_right", "x": 1080, "y": 360, "desc": "Center right (possible game category)"},
    ]

    print("\n[7] Phase 3: Exploring clickable areas", flush=True)
    for target in exploration_targets:
        print(f"\n  --- Clicking: {target['desc']} ({target['x']}, {target['y']}) ---", flush=True)
        await session.execute_action({"type": "click", "x": target["x"], "y": target["y"]})
        await asyncio.sleep(2)

        obs = await session.observe()
        ss_path = obs["screenshot_path"]
        parsed = analyze_screenshot_structured(ss_path)
        screen_id = parsed.get("screen_id", "")
        desc = parsed.get("description", "")[:120]
        is_popup = parsed.get("is_popup", False)
        print(f"    → {screen_id} | popup={is_popup} | {desc}", flush=True)

        # If something opened, document it and close
        if is_popup or screen_id != lobby_data["screens"][1].get("parsed", {}).get("screen_id", ""):
            # New screen/panel opened - do detailed analysis
            detail = analyze_screenshot(ss_path, prompt="Describe all UI elements visible in this panel/dialog. List positions (x,y), labels, and types.")
            print(f"    Detail: {detail[:500]}", flush=True)
            lobby_data["screens"].append({
                "name": target["name"],
                "click_pos": {"x": target["x"], "y": target["y"]},
                "screenshot": ss_path,
                "screen_id": screen_id,
                "description": desc,
                "analysis": detail[:2000],
            })

            # Close it - try common close positions
            # Press ESC or click X or click outside
            await session.execute_action({"type": "key", "key": "Escape"})
            await asyncio.sleep(1)
            # If still open, try clicking a close button area
            obs2 = await session.observe()
            parsed2 = analyze_screenshot_structured(obs2["screenshot_path"])
            if parsed2.get("is_popup") or parsed2.get("screen_id") == screen_id:
                # Try clicking top-right X
                await session.execute_action({"type": "click", "x": 1240, "y": 40})
                await asyncio.sleep(1)

        await asyncio.sleep(1)

    # Phase 4: Check for scrollable content
    print("\n[8] Phase 4: Checking for scrollable content", flush=True)
    obs = await session.observe()
    parsed = analyze_screenshot_structured(obs["screenshot_path"])
    # Try scrolling in center area
    await session.execute_action({"type": "scroll", "x": 640, "y": 360, "delta_y": -200})
    await asyncio.sleep(2)
    obs_after = await session.observe()
    parsed_after = analyze_screenshot_structured(obs_after["screenshot_path"])
    print(f"  Before scroll: {parsed.get('screen_id')}", flush=True)
    print(f"  After scroll: {parsed_after.get('screen_id')}", flush=True)
    print(f"  Scroll description: {parsed_after.get('description', '')[:120]}", flush=True)

    # Save results
    output_path = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}/runs/example_game/{datetime.now().strftime('%Y%m%d_%H%M%S')}_lobby_exploration.json"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(lobby_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[9] Results saved: {output_path}", flush=True)

    print("\n=== LOBBY EXPLORATION COMPLETE ===", flush=True)
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}", flush=True)
    print(f"Total screens documented: {len(lobby_data['screens'])}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
