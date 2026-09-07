"""Lobby exploration v5 — mimic qa_interactive's Vision-guided popup dismiss, then batch explore."""
import asyncio
import sys
import os
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.agent import GameSession
from webgl_qa.vision import analyze_screenshot_structured
from webgl_qa.actions import login_sequence

SCREENSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs", "lobby_explore_v5")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


async def vision_guided_dismiss(session, step):
    """Mimic qa_interactive's popup dismiss logic."""
    obs = await session.observe()
    if not obs.get("screenshot_path"):
        return "no_screenshot", ""
    
    parsed = analyze_screenshot_structured(obs["screenshot_path"])
    if not isinstance(parsed, dict):
        return "parse_error", ""
    
    screen_id = parsed.get("screen_id", "")
    desc = parsed.get("description", "")
    elements = parsed.get("elements", [])
    
    print(f"  [{step}] screen: {screen_id} | {desc[:80]}", flush=True)
    
    if "lobby" in screen_id or "大厅" in desc or "大廳" in desc:
        return "lobby", desc
    
    # Find close button
    for el in elements:
        if not isinstance(el, dict):
            continue
        label = str(el.get("label", "")).lower()
        loc = el.get("location", {})
        if not isinstance(loc, dict):
            continue
        if any(kw in label for kw in ["关闭", "關閉", "close", "×", "x"]):
            x, y = loc.get("x", 0), loc.get("y", 0)
            if x > 0:
                print(f"    Close btn: '{el.get('label')}' @ ({x},{y})", flush=True)
                await session.execute_action({"type": "click", "x": x, "y": y})
                await asyncio.sleep(2)
                return "dismissed", desc
    
    # Known patterns
    if any(k in desc for k in ["3日", "金喜", "金享", "金章", "金寶"]):
        print(f"    VIP popup → (1130,105)", flush=True)
        await session.execute_action({"type": "click", "x": 1130, "y": 105})
        await asyncio.sleep(2)
        return "dismissed", desc
    
    if any(k in desc for k in ["簽到", "签到"]):
        print(f"    签到 → (1226,46)", flush=True)
        await session.execute_action({"type": "click", "x": 1226, "y": 46})
        await asyncio.sleep(2)
        return "dismissed", desc
    
    # Fallback: top-right close
    print(f"    Fallback → (1226,46)", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(2)
    return "dismissed", desc


async def main():
    session = GameSession(
        game_url=os.environ.get("GAME_URL", ""),
        game_name="example_game",
        headless=True,
    )
    
    print("=== Starting browser ===", flush=True)
    result = await session.start()
    print(f"Canvas: {result.get('canvas')}", flush=True)
    
    # Login
    print("\n=== Login (debug) ===", flush=True)
    await login_sequence(session, os.environ.get("LOGIN_ID", ""), mode="debug")
    print("Login done, waiting...", flush=True)
    await asyncio.sleep(5)
    
    # Vision-guided popup dismiss (same as qa_interactive)
    print("\n=== Dismissing popups (Vision-guided) ===", flush=True)
    for i in range(6):
        status, desc = await vision_guided_dismiss(session, i + 1)
        if status == "lobby":
            print(f"\n✓ LOBBY REACHED after {i+1} step(s)!", flush=True)
            break
    else:
        print("WARNING: May not have reached lobby", flush=True)
    
    await asyncio.sleep(2)
    
    # === BATCH SCREENSHOT COLLECTION (no Vision between clicks) ===
    print("\n=== BATCH SCREENSHOT COLLECTION ===", flush=True)
    
    screenshots = []
    
    async def click_screenshot_close(name, x, y, close_x=1226, close_y=46, wait=1.5):
        """Click, wait, screenshot, close. No Vision."""
        await session.execute_action({"type": "click", "x": x, "y": y})
        await asyncio.sleep(wait)
        obs = await session.observe()
        path = f"{SCREENSHOT_DIR}/{name}.png"
        if obs.get("screenshot_path"):
            shutil.copy2(obs["screenshot_path"], path)
            size = os.path.getsize(path)
            print(f"  {name}: {size} bytes", flush=True)
            screenshots.append((name, path, size))
        if close_x:
            await session.execute_action({"type": "click", "x": close_x, "y": close_y})
            await asyncio.sleep(1)
    
    async def click_toggle_screenshot(name, x, y, wait=1.0):
        """Toggle popup, screenshot, toggle off."""
        await session.execute_action({"type": "click", "x": x, "y": y})
        await asyncio.sleep(wait)
        obs = await session.observe()
        path = f"{SCREENSHOT_DIR}/{name}.png"
        if obs.get("screenshot_path"):
            shutil.copy2(obs["screenshot_path"], path)
            size = os.path.getsize(path)
            print(f"  {name}: {size} bytes", flush=True)
            screenshots.append((name, path, size))
        # Toggle off
        await session.execute_action({"type": "click", "x": x, "y": y})
        await asyncio.sleep(0.5)
    
    async def fast_menu_item(name, item_x, item_y, close_x=1226, close_y=46):
        """Open menu (1220,45), immediately click item, screenshot, close."""
        await session.execute_action({"type": "click", "x": 1220, "y": 45})
        await asyncio.sleep(0.3)
        await session.execute_action({"type": "click", "x": item_x, "y": item_y})
        await asyncio.sleep(1.5)
        obs = await session.observe()
        path = f"{SCREENSHOT_DIR}/{name}.png"
        if obs.get("screenshot_path"):
            shutil.copy2(obs["screenshot_path"], path)
            size = os.path.getsize(path)
            print(f"  {name}: {size} bytes", flush=True)
            screenshots.append((name, path, size))
        if close_x:
            await session.execute_action({"type": "click", "x": close_x, "y": close_y})
            await asyncio.sleep(1)
    
    async def mini_popup_item(name, btn_x, btn_y, item_x, item_y, close_x=1226, close_y=46):
        """Open mini-popup, click sub-item, screenshot, close."""
        await session.execute_action({"type": "click", "x": btn_x, "y": btn_y})
        await asyncio.sleep(0.3)
        await session.execute_action({"type": "click", "x": item_x, "y": item_y})
        await asyncio.sleep(1.5)
        obs = await session.observe()
        path = f"{SCREENSHOT_DIR}/{name}.png"
        if obs.get("screenshot_path"):
            shutil.copy2(obs["screenshot_path"], path)
            size = os.path.getsize(path)
            print(f"  {name}: {size} bytes", flush=True)
            screenshots.append((name, path, size))
        if close_x:
            await session.execute_action({"type": "click", "x": close_x, "y": close_y})
            await asyncio.sleep(1)
    
    # Baseline
    obs = await session.observe()
    path = f"{SCREENSHOT_DIR}/00_lobby_baseline.png"
    if obs.get("screenshot_path"):
        shutil.copy2(obs["screenshot_path"], path)
        screenshots.append(("lobby_baseline", path, os.path.getsize(path)))
    
    # --- TOP BAR ---
    print("\n[Top bar]", flush=True)
    await click_screenshot_close("01_玩家頭像", 65, 45)
    await click_screenshot_close("02_金幣充值", 600, 38)
    await click_screenshot_close("03_鑽石充值", 780, 38)
    await click_screenshot_close("04_紫寶石充值", 950, 38)
    await click_screenshot_close("05_郵件", 1150, 45)
    
    # --- RIGHT SIDE ---
    print("\n[Right side]", flush=True)
    await click_screenshot_close("06_商城", 1220, 180)
    await click_screenshot_close("07_歡樂爭霸", 1220, 280)
    
    # --- MENU DROPDOWN ---
    print("\n[Menu dropdown]", flush=True)
    # Just open menu to see it
    await session.execute_action({"type": "click", "x": 1220, "y": 45})
    await asyncio.sleep(0.5)
    obs = await session.observe()
    path = f"{SCREENSHOT_DIR}/08_菜單展開.png"
    if obs.get("screenshot_path"):
        shutil.copy2(obs["screenshot_path"], path)
        screenshots.append(("菜單展開", path, os.path.getsize(path)))
        print(f"  菜單展開: {os.path.getsize(path)} bytes", flush=True)
    await asyncio.sleep(2)  # let auto-close
    
    await fast_menu_item("09_菜單-設定", 1222, 131, close_x=990, close_y=195)
    await fast_menu_item("10_菜單-公告", 1222, 198)
    await fast_menu_item("11_菜單-兌換", 1222, 264)
    
    # --- BOTTOM NAV ---
    print("\n[Bottom nav]", flush=True)
    await click_toggle_screenshot("12_我的-popup", 80, 670)
    await click_screenshot_close("13_炮台", 180, 670)
    await click_toggle_screenshot("14_藏品-popup", 280, 670)
    await click_screenshot_close("15_福利", 380, 670)
    
    # --- MINI-POPUP SUB-ITEMS ---
    print("\n[Mini-popup sub-items]", flush=True)
    await mini_popup_item("16_我的-背包", 80, 670, 80, 540)
    await mini_popup_item("17_我的-任務", 80, 670, 170, 540)
    await mini_popup_item("18_我的-VIP特權", 80, 670, 260, 540)
    await mini_popup_item("19_藏品-item1", 280, 670, 125, 540)
    await mini_popup_item("20_藏品-item2", 280, 670, 185, 540)
    await mini_popup_item("21_藏品-item3", 280, 670, 245, 540)
    
    # --- PLAYER PROFILE TABS ---
    print("\n[Player profile tabs]", flush=True)
    # Open profile
    await session.execute_action({"type": "click", "x": 65, "y": 45})
    await asyncio.sleep(1.5)
    # Tab: 資訊 (default)
    obs = await session.observe()
    path = f"{SCREENSHOT_DIR}/22_個人-資訊.png"
    if obs.get("screenshot_path"):
        shutil.copy2(obs["screenshot_path"], path)
        screenshots.append(("個人-資訊", path, os.path.getsize(path)))
        print(f"  個人-資訊: {os.path.getsize(path)} bytes", flush=True)
    # Tab: 炮臺
    await session.execute_action({"type": "click", "x": 74, "y": 260})
    await asyncio.sleep(1)
    obs = await session.observe()
    path = f"{SCREENSHOT_DIR}/23_個人-炮臺.png"
    if obs.get("screenshot_path"):
        shutil.copy2(obs["screenshot_path"], path)
        screenshots.append(("個人-炮臺", path, os.path.getsize(path)))
        print(f"  個人-炮臺: {os.path.getsize(path)} bytes", flush=True)
    # Tab: 神器
    await session.execute_action({"type": "click", "x": 74, "y": 365})
    await asyncio.sleep(1)
    obs = await session.observe()
    path = f"{SCREENSHOT_DIR}/24_個人-神器.png"
    if obs.get("screenshot_path"):
        shutil.copy2(obs["screenshot_path"], path)
        screenshots.append(("個人-神器", path, os.path.getsize(path)))
        print(f"  個人-神器: {os.path.getsize(path)} bytes", flush=True)
    # Close profile
    await session.execute_action({"type": "click", "x": 1234, "y": 38})
    await asyncio.sleep(1)
    
    print(f"\n\n=== SCREENSHOTS COMPLETE: {len(screenshots)} files ===", flush=True)
    print(f"Directory: {SCREENSHOT_DIR}/", flush=True)
    for name, path, size in screenshots:
        print(f"  {name}: {size:,} bytes", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
