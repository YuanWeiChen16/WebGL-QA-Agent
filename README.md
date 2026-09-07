# WebGL QA Agent

> AI 驅動的 **WebGL 遊戲自動化 QA 框架** — 以 Playwright 控制瀏覽器、Vision LLM 分析畫面，對任意 WebGL 遊戲做黑箱自動遊玩、崩潰級異常偵測與功能正確性驗證。
>
> *An AI-driven, black-box QA framework for WebGL games: Playwright drives the browser, a vision LLM reads the screen, and the agent explores, detects crash-level anomalies, and checks functional invariants.*

> ⚠️ **Research preview / 實驗性專案。** 介面與行為可能變動。完整架構見 [DESIGN.md](DESIGN.md) 與 [KNOWLEDGE_ARCHITECTURE.md](KNOWLEDGE_ARCHITECTURE.md)。

---

## 特色

- **純黑箱** — 不需遊戲原始碼、不注入引擎 hook，適用於「不可修改的第三方 WebGL 遊戲」。
- **視覺感知** — 截圖 → Vision LLM（Anthropic 相容 gateway），走 `tool_use` 結構化 schema 保證 JSON 輸出。
- **崩潰級異常偵測** — 凍結、黑白屏、記憶體成長、console / page error 監控，確定性、近零成本。
- **功能正確性 oracle** — Vision 讀畫面數值（分數 / 金幣 / 等級 / 生命），依 `game_info.yaml` 宣告的 invariant 比對動作前後狀態。
- **知識庫** — 靜態 YAML（子系統座標、流程圖、已知問題）+ runtime 學習層，跨 session 累積。
- **報告** — 每次 run 產出 HTML timeline 報告與可重播的 `session.json`。

## 架構概覽

```
你的腳本 / GameSession (agent.py)  ── 生命週期 + observe / act / oracle
   ├── driver.py         驅動層介面：screenshot / click / drag / 能力宣告 + 中立效能 schema
   │   ├── browser.py    Playwright + Chromium：console/pageerror 攔截、CDP 效能
   │   └── adb_device.py adb：原生 Android App / 模擬器（screencap、input、dumpsys、SurfaceFlinger）
   ├── perceiver.py      SSIM / 凍結 / 黑白屏 / pixel-diff / 區域錨點比對
   ├── detector.py       崩潰級異常偵測
   ├── oracle.py         功能正確性 invariant（純確定性，不呼叫 Vision）
   ├── knowledge_base.py 單一知識庫（靜態 YAML + runtime）
   └── reporter.py       HTML 報告
vision.py + prompts.py + parser.py  ── Vision 呼叫與解析
```

## 安裝

需求：Python 3.11+、[uv](https://github.com/astral-sh/uv)

```bash
uv sync
uv run playwright install chromium
```

## 設定

複製環境變數範本並填入你的值：

```bash
cp .env.example .env
```

| 變數 | 說明 |
|------|------|
| `VISION_GATEWAY_URL` | Anthropic 相容的 Vision gateway 位址（必填） |
| `VISION_API_KEY` | gateway 金鑰（必填） |
| `GAME_URL` | 受測 WebGL 遊戲 URL |
| `LOGIN_ID` | 若遊戲需要登入帳號（選填） |

偵測門檻、解析度、timing、oracle invariants 等集中在 [`config/default.yaml`](config/default.yaml)，可用 `knowledge/<game>/game_info.yaml` 逐鍵覆寫。

> ⚠️ 腳本**不會**自動載入 `.env`；請先把變數載入 shell（`.env.example` 開頭附了 PowerShell / bash 指令），或自行引入 `python-dotenv`。

## 快速上手

以公開的 [WebGL Aquarium](https://webglsamples.org/aquarium/aquarium.html) 為例（`knowledge/webgl_aquarium_test/` 已附此範例知識）：

```python
import asyncio, os
from webgl_qa.agent import GameSession

async def main():
    session = GameSession(
        game_url=os.environ.get("GAME_URL", "https://webglsamples.org/aquarium/aquarium.html"),
        game_name="webgl_aquarium_test",
    )
    await session.start()
    obs = await session.observe()            # 截圖 + 崩潰級異常偵測（不呼叫 Vision）
    print("anomalies:", obs["anomalies"])
    await session.execute_action({"type": "click", "x": 640, "y": 360})
    result = await session.finish()          # 產出 runs/<game>/<timestamp>/report.html
    print("report:", result["report_path"])

asyncio.run(main())
```

Vision 分析、`record_game_state()` / `check_invariants()` 等 oracle 進階用法見 [DESIGN.md](DESIGN.md)。`scripts/` 內另有互動式與連續測試的範例腳本。

## 知識庫

每個遊戲一個 `knowledge/<game>/` 目錄：`systems/*.yaml`（座標與操作序列）、`flow_graph.yaml`（系統間轉換）、`problems/*.md`（已知問題與解法）、`game_info.yaml`（基本資訊 + oracle invariants），外加自動生成的 runtime `knowledge.yaml`。`actions.py` 一律從知識庫讀座標，改 YAML 即生效。詳見 [KNOWLEDGE_ARCHITECTURE.md](KNOWLEDGE_ARCHITECTURE.md)。

## 現況與限制（誠實對齊）

- 座標目前為**絕對像素**，尚未做解析度正規化 / 相對定位。
- 凍結偵測仍採全圖 SSIM，對高動態畫面判別力有限。畫面**辨識**則改用知識庫宣告的靜態 UI 錨點做區域 SSIM（`detection.anchors` → `GameSession.identify_screen()`），不依賴 Vision；尚未宣告錨點的遊戲仍由 Vision 命名 screen_id。
- Android（adb）路徑目前僅驗證於 BlueStacks（1920×1080）；原生 App 無 console/heap，效能改由 `dumpsys meminfo` 與 SurfaceFlinger frame timing 提供，`gfxinfo` 對自繪 SurfaceView 的遊戲不適用。
- 尚無「零 LLM 的確定性回歸層」與 CI 化的 pass/fail exit code。
- Vision 呼叫有成本與延遲；即時遊戲的時效操作應走確定性腳本，而非每步呼叫 Vision。

## 授權

[MIT](LICENSE)。
