"""Lobby exploration pass 2 — fix the missing items (bottom nav, sub-items, profile tabs)."""
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
    """Use Vision to identify and dismiss a popup properly."""
    obs = await session.observe()
    if not obs.get("screenshot_path"):
        return "no_screenshot"
    parsed = analyze_screenshot_structured(obs["screenshot_path"])
    if not isinstance(parsed, dict):
        return "parse_error"
    screen_id = parsed.get("screen_id", "")
    desc = parsed.get("description", "")
    elements = parsed.get("elements", [])
    print(f"  [{step}] screen: {screen_id} | {desc[:80]}", flush=True)
    if "lobby" in screen_id or "大厅" in desc or "大廳" in desc:
        return "lobby"
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
                print(f"    Close: '{el.get('label')}' @ ({x},{y})", flush=True)
                await session.execute_action({"type": "click", "x": x, "y": y})
                await asyncio.sleep(2)
                return "dismissed"
    if any(k in desc for k in ["3日", "金喜", "金享", "金章", "金寶"]):
        await session.execute_action({"type": "click", "x": 1130, "y": 105})
        await asyncio.sleep(2)
        return "dismissed"
    if any(k in desc for k in ["簽到", "签到"]):
        await session.execute_action({"type": "click", "x": 1226, "y": 46})
        await asyncio.sleep(2)
        return "dismissed"
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(2)
    return "dismissed"


async def main():
    session = GameSession(
        game_url=os.environ.get("GAME_URL", ""),
        game_name="example_game", headless=True)
    
    print("=== Starting browser ===", flush=True)
    await session.start()
    print("=== Login ===", flush=True)
    await login_sequence(session, os.environ.get("LOGIN_ID", ""), mode="debug")
    await asyncio.sleep(5)
    
    print("\n=== Dismissing popups ===", flush=True)
    for i in range(6):
        status = await vision_guided_dismiss(session, i + 1)
        if status == "lobby":
            break
    
    print("\n✓ LOBBY — Starting pass 2\n", flush=True)
    await asyncio.sleep(2)
    
    # --- BOTTOM NAV ---
    print("[Bottom nav]", flush=True)
    
    # 我的 toggle popup
    await session.execute_action({"type": "click", "x": 80, "y": 670})
    await asyncio.sleep(1.5)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/30_我的-popup.png")
    print(f"  30_我的-popup: {os.path.getsize(f'{SCREENSHOT_DIR}/30_我的-popup.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 80, "y": 670})  # toggle off
    await asyncio.sleep(1)
    
    # 炮台
    await session.execute_action({"type": "click", "x": 180, "y": 670})
    await asyncio.sleep(2)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/31_炮台.png")
    print(f"  31_炮台: {os.path.getsize(f'{SCREENSHOT_DIR}/31_炮台.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(1)
    
    # 藏品 toggle popup
    await session.execute_action({"type": "click", "x": 280, "y": 670})
    await asyncio.sleep(1.5)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/32_藏品-popup.png")
    print(f"  32_藏品-popup: {os.path.getsize(f'{SCREENSHOT_DIR}/32_藏品-popup.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 280, "y": 670})  # toggle off
    await asyncio.sleep(1)
    
    # 福利
    await session.execute_action({"type": "click", "x": 380, "y": 670})
    await asyncio.sleep(2)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/33_福利.png")
    print(f"  33_福利: {os.path.getsize(f'{SCREENSHOT_DIR}/33_福利.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(1)
    
    # --- SUB ITEMS ---
    print("\n[Sub-items]", flush=True)
    
    # 我的 → 背包
    await session.execute_action({"type": "click", "x": 80, "y": 670})
    await asyncio.sleep(0.3)
    await session.execute_action({"type": "click", "x": 80, "y": 540})
    await asyncio.sleep(2)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/34_我的-背包.png")
    print(f"  34_我的-背包: {os.path.getsize(f'{SCREENSHOT_DIR}/34_我的-背包.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(1)
    
    # 我的 → 任務
    await session.execute_action({"type": "click", "x": 80, "y": 670})
    await asyncio.sleep(0.3)
    await session.execute_action({"type": "click", "x": 170, "y": 540})
    await asyncio.sleep(2)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/35_我的-任務.png")
    print(f"  35_我的-任務: {os.path.getsize(f'{SCREENSHOT_DIR}/35_我的-任務.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(1)
    
    # 我的 → VIP特權
    await session.execute_action({"type": "click", "x": 80, "y": 670})
    await asyncio.sleep(0.3)
    await session.execute_action({"type": "click", "x": 260, "y": 540})
    await asyncio.sleep(2)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/36_我的-VIP特權.png")
    print(f"  36_我的-VIP特權: {os.path.getsize(f'{SCREENSHOT_DIR}/36_我的-VIP特權.png')}", flush=True)
    await session.execute_action({"type": "click", "x": 1226, "y": 46})
    await asyncio.sleep(1)
    
    # 藏品 → item1, item2, item3
    for i, (item_x, name) in enumerate([(125, "炮臺"), (185, "炮臺網格"), (245, "炮座")], 1):
        await session.execute_action({"type": "click", "x": 280, "y": 670})
        await asyncio.sleep(0.3)
        await session.execute_action({"type": "click", "x": item_x, "y": 540})
        await asyncio.sleep(2)
        obs = await session.observe()
        fname = f"{SCREENSHOT_DIR}/3{6+i}_藏品-{name}.png"
        shutil.copy2(obs["screenshot_path"], fname)
        print(f"  3{6+i}_藏品-{name}: {os.path.getsize(fname)}", flush=True)
        await session.execute_action({"type": "click", "x": 1226, "y": 46})
        await asyncio.sleep(1)
    
    # --- PLAYER PROFILE TABS ---
    print("\n[Player profile tabs]", flush=True)
    await session.execute_action({"type": "click", "x": 65, "y": 45})
    await asyncio.sleep(2)
    
    # 資訊 (default)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/40_個人-資訊.png")
    print(f"  40_個人-資訊: {os.path.getsize(f'{SCREENSHOT_DIR}/40_個人-資訊.png')}", flush=True)
    
    # 炮臺
    await session.execute_action({"type": "click", "x": 74, "y": 260})
    await asyncio.sleep(1.5)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/41_個人-炮臺.png")
    print(f"  41_個人-炮臺: {os.path.getsize(f'{SCREENSHOT_DIR}/41_個人-炮臺.png')}", flush=True)
    
    # 神器
    await session.execute_action({"type": "click", "x": 74, "y": 365})
    await asyncio.sleep(1.5)
    obs = await session.observe()
    shutil.copy2(obs["screenshot_path"], f"{SCREENSHOT_DIR}/42_個人-神器.png")
    print(f"  42_個人-神器: {os.path.getsize(f'{SCREENSHOT_DIR}/42_個人-神器.png')}", flush=True)
    
    # Close profile
    await session.execute_action({"type": "click", "x": 1234, "y": 38})
    await asyncio.sleep(1)
    
    print("\n=== PASS 2 COMPLETE ===", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
