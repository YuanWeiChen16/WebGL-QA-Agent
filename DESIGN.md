# WebGL Game QA Agent — 設計文件

## 概述

一個會**累積經驗、逐步學會遊戲**的自主 QA Agent，能夠：
- 對任意 WebGL 遊戲進行黑箱自動遊玩
- 每次 session 把學到的知識持久化
- 自動產出遊戲流程圖（screen flow graph）
- 每個步驟的策略可以人工微調
- 產出 QA 報告（bug、crash、效能問題）

---

## 專案位置

```
webgl-qa-agent/
```

可與受測遊戲的客戶端專案並列開發，Phase 2 再行整合。

---

## 分階段目標

### Phase 1 — 黑箱 Agent（目前實作）

對 WebGL 遊戲 URL，**不需也無法改遊戲程式碼**（測試對象為第三方遊戲）：
- 視覺感知（截圖 → Vision LLM，structured tool_use）
- 自主操作（click / keypress / drag / longpress）
- 崩潰級異常偵測（console error、凍結、黑白屏、記憶體）— `detector.py`
- **功能正確性 oracle**（Vision 從畫面讀 `game_state` 數值，依 invariant 比對前後狀態）— `oracle.py`
- 累積 knowledge 並產出報告

### 為什麼是黑箱：這是刻意的設計選擇，不是限制

測試對象「受測的第三方遊戲 (the game under test)」是**不可修改的第三方遊戲**，沒有原始碼、無法加入
`unityInstance.SendMessage` 或 export 狀態的橋接。這正是業界純像素黑箱方案（如 Microsoft
Inspector）的適用場景：**當目標無法被 instrument 時，唯一的 ground truth 就是畫面本身**。

因此本專案：
- 用 Vision 讀畫面數值（分數、金幣、砲倍階、進度）作為 test oracle 的 ground truth；
- 座標定位靠 Vision + 知識庫累積，而非 DOM/物件階層查詢。

> 對照：若測試對象是**自家、可重建**的遊戲（例如 Unity 專案），業界首選會是 in-engine
> hook（AltTester / GameDriver）以取得狀態真值與毫秒級定位。那不是本專案的場景——
> 這裡的黑箱是被測對象性質決定的正確選擇，不是退而求其次。

---

## 架構（Hermes Agent 串接）

Hermes Agent 本身就是 agent loop 的大腦，Playwright 模組是手腳：

```
使用者: "去探索 https://xxx.com"
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│  Hermes Agent（大腦 — 決策 + Vision LLM + 知識管理）         │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ webgl-qa skill（定義 agent loop + 工作流程）          │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                          │                                   │
│                          ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ webgl_qa Python 模組 (Playwright helper)              │   │
│  │                                                       │   │
│  │  browser.py ─────── 啟動/控制瀏覽器、截圖、執行動作   │   │
│  │  perceiver.py ───── 截圖分析（SSIM、dominant color）  │   │
│  │  knowledge_base.py ─ 單一知識庫（靜態 YAML + runtime）│   │
│  │  detector.py ────── console error、凍結、黑白屏偵測   │   │
│  │  oracle.py ──────── 功能正確性檢查（Vision 數值）     │   │
│  │  reporter.py ────── HTML timeline 報告                │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Knowledge 持久化:                                           │
│  • knowledge/<game>/knowledge.yaml — 遊戲知識               │
│  • screenshots/<game>/ — 參考截圖                            │
│  • reports/ — QA 報告                                        │
│  • sessions/ — session log (可重播)                          │
└─────────────────────────────────────────────────────────────┘
```

### 跟純獨立 CLI 比的優勢

- 不需另外設定 LLM API key — 直接用 Hermes 的 provider + Vision
- 可對話式微調 —「那個 screen 你點錯了，應該點右邊的按鈕」
- 可用 cron 排程 — 每天自動跑一輪 QA
- knowledge 可存為 skill — 每個遊戲的知識變成可載入的 skill
- 中途可介入 — 隨時插話修正 agent 的判斷

---

## 技術選擇

| 組件 | 選擇 | 原因 |
|------|------|------|
| 瀏覽器自動化 | **Playwright (Python)** | WebGL canvas 支援好、截圖快、能攔截 console log |
| 視覺分析 | **Claude Vision / GPT-4o** | 理解遊戲畫面 + 結構化輸出動作指令 |
| 語言 | **Python 3.11+** | 生態成熟、async 支援好 |
| 套件管理 | **uv** | 快速、lockfile |
| 報告 | **HTML + JSON** | 帶截圖的互動式 timeline |
| 知識儲存 | **YAML** | 人類可讀可編輯 |

---

## 運作模式

### 1. Explore（探索）

第一次跑，agent 不知道任何東西：

```
loop:
  1. 截圖
  2. → Vision LLM: "這是什麼畫面？看到哪些可互動元素？"
  3. LLM 回覆: {screen_id, elements[], suggested_action}
  4. 執行 suggested_action
  5. 截圖（動作後）
  6. → Vision LLM: "畫面變了嗎？現在在哪個 screen？"
  7. 記錄 transition: screen_A --[action]--> screen_B
  8. 更新 knowledge.yaml
```

### 2. Validate（驗證）

有了基本 knowledge 之後：
- 照著已知 flow 走一遍，確認路徑沒壞
- 遇到新畫面 → 標記 unknown → 探索補充
- 發現走不通 → 標記斷點，嘗試替代路徑

### 3. Test（測試 / QA）

flow 穩定後：
- 按流程跑完整 happy path
- 每個 screen 做異常操作（亂按、快速切換、邊界值）
- 特定 screen 跑壓力測試（重複操作 N 次）
- 記錄所有 bug + 自動歸檔

---

## Knowledge Schema

```yaml
# knowledge.yaml
game:
  url: "https://example.com/game"
  title: "Example Game"
  last_updated: "2026-06-30T10:00:00"

screens:
  - id: main_menu
    description: "主選單，有 Play、Settings、Shop 三個按鈕"
    reference_screenshot: screenshots/main_menu.png
    known_elements:
      - {id: btn_play, type: button, label: "Play", location: {x: 512, y: 400}}
      - {id: btn_settings, type: button, label: "Settings", location: {x: 512, y: 500}}
      - {id: btn_shop, type: button, label: "Shop", location: {x: 512, y: 600}}
    transitions:
      - {action: "click btn_play", goes_to: level_select, confidence: high}
      - {action: "click btn_settings", goes_to: settings, confidence: high}
    strategy:
      mode: scripted  # scripted | systematic | random
      scripted_sequence:
        - {action: click, target: btn_play}
        - {action: wait_for_screen, expect: level_select, timeout: 5s}

  - id: gameplay
    description: "捕魚主畫面，底部有砲台，魚在水中游動"
    reference_screenshot: screenshots/gameplay.png
    known_elements:
      - {id: cannon, type: interactive, label: "砲台", location: {x: 512, y: 700}}
      - {id: fish_area, type: dynamic_region, label: "魚群區域", location: {x: 512, y: 350, w: 900, h: 500}}
      - {id: score, type: display, label: "分數", location: {x: 100, y: 50}}
    strategy:
      mode: systematic
      actions:
        - {type: click, target: fish_area, interval: 500ms, description: "射擊魚群"}
        - {type: observe, check: score, every: 5s, description: "監控分數變化"}
      fallback: random_click_in_fish_area
      duration: 60s

flow_graph:
  - {from: main_menu, to: level_select, action: "click Play", stable: true}
  - {from: level_select, to: loading, action: "click Level 1", stable: true}
  - {from: loading, to: gameplay, action: "wait", stable: true}
  - {from: gameplay, to: result_screen, action: "timeout/game_over", stable: true}
  - {from: result_screen, to: main_menu, action: "click OK", stable: true}

bugs:
  - id: BUG-001
    screen: gameplay
    severity: medium
    description: "連續快速點擊砲台 20 次後畫面凍結 2 秒"
    repro_steps:
      - {action: click, target: cannon, repeat: 20, interval: 50ms}
    evidence:
      - screenshots/bug001_frozen.png
      - console_log: "WebGL: CONTEXT_LOST_WEBGL"
    first_seen: "2026-06-30"
    last_seen: "2026-06-30"
    reproduced: 3  # 重現次數
```

---

## 微調方式

### 方法 1：直接編輯 knowledge.yaml

最直接。你可以：
- 修改任何 screen 的 `strategy` 區塊
- 加入 `scripted_sequence` 指定精確操作
- 調整 `interval`、`duration`、`timeout`
- 標記某些 transition 為 `skip: true`（不要走這條路）

### 方法 2：調整設定與 oracle（config / game_info.yaml）

- 偵測門檻、解析度、timing、adaptive observe → `config/default.yaml`
- 遊戲特定 override、oracle invariants → `knowledge/<game>/game_info.yaml`

```yaml
# game_info.yaml — 新增一條功能正確性檢查
oracle:
  invariants:
    - {id: level_up_on_upgrade, when: upgrade, field: level, kind: increment, delta: 1, severity: high}
```

### 方法 3：CLI 策略覆寫（尚未實作，roadmap）

> 早期設計過 `python -m webgl_qa tune/stress/test --strategy aggressive.yaml` 與
> `strategies/*.yaml` 覆寫機制，**目前尚未實作**。在此之前，壓力/激進測試請直接寫成
> `scripts/` 下的腳本，或在 `systems/*.yaml` 的 `actions` 定義操作序列由 `execute_steps` 執行。

---

## 學習與累積機制

| 機制 | 實作方式 | 何時觸發 |
|------|----------|----------|
| **Screen 辨識** | reference screenshot + LLM description；下次用 structural similarity (SSIM) + LLM 確認 | 每次截圖時比對 |
| **元素記憶** | 記住 bounding box + 視覺特徵；允許位置浮動（relative positioning） | 探索時發現新元素 |
| **Flow 累積** | 每次成功 transition 增加 confidence；失敗則降低 | 每次 screen 變化 |
| **策略進化** | 記錄 action → outcome（分數變化、畫面變化）；下次優先選有效動作 | 每次動作後 |
| **異常記憶** | 觸發 crash 的操作序列存為 repro_steps；後續可重播驗證 | 偵測到 bug 時 |
| **Session 累積** | 每次 run 結束更新 knowledge.yaml，下次從上次學到的開始 | session 結束時 |

> **實作狀態（誠實對齊）**：
> - ✅ 已實作：Screen 辨識（SSIM + Vision）、Flow transition 累積、異常 repro_steps、Session 累積。
> - ⚠️ 部分/未實作：
>   - **confidence 只升不降** — 目前 transition 重複出現會 low→medium→high，但「失敗則降低」尚無對應程式（見 `knowledge_base.py::add_runtime_transition`）。
>   - **relative positioning** — 座標仍是絕對像素，尚未做解析度正規化/浮動定位。
>   - **策略進化（action→outcome）** — schema 無 outcome 欄位，尚未實作「優先選有效動作」。
>   - **screen_id 主鍵** — 對已宣告 `detection.anchors` 的系統，`identify_screen()` 以區域 SSIM 給出確定性的系統 id（2026-09-03 起，先落地於 Android 知識庫）；未宣告者仍由 Vision 自由命名，全圖 SSIM 只用於凍結偵測。完整的 canonical registry（遮罩動態區的 perceptual hash）仍未建立（見架構決策追蹤清單）。

---

## 產出物

每次 session 產出一個獨立資料夾 `runs/<game>/<YYYYMMDD_HHMMSS>/`：

| 檔案 | 說明 |
|------|------|
| `report.html` | 本次 session 的完整 timeline 報告 |
| `session.json` | 原始操作紀錄；`status` 為 `completed`（正常 `finish()`）或 `aborted`（含 `abort_reason`） |
| `screenshots/` | 本次 session 的所有截圖 |
| `exploration/`、`lobby_exploration.json` | 探索類腳本的附加產物（同樣放在 run 資料夾內） |
| `knowledge/<game>/knowledge.yaml` | 更新後的 runtime 知識（累積式，不在 run 資料夾） |

**中斷保證**：`GameSession` 在程序結束時（Ctrl+C、未捕捉例外、正常退出）會為尚未 `finish()` 的 session
自動寫出 `status: aborted` 的 `session.json` 與 report；腳本也可在 `except` 中主動呼叫 `session.abort(reason)`。
這消除了過去「只剩 `screenshots/`、無法分析」的孤兒 run（清理時一次找出 78 個）。
根目錄的 `reports/`、`sessions/`、`screenshots/` 為 2026-06/07 的舊版佈局，已於 2026-09-07 搬離 repo。

---

## 執行介面（實際現況）

> ⚠️ 早期版本設計過一套 `python -m webgl_qa explore/validate/test/replay/tune/stress`
> 統一 CLI，**目前尚未實作**（無 `__main__.py`）。實際入口是 `scripts/` 下的腳本 +
> `GameSession` API。下方為目前真正可用的方式；上述 CLI 列為未來 roadmap。

**主要方式：腳本**
```bash
# 先設定 gateway（環境變數）
export VISION_GATEWAY_URL="http://<gateway>:8000"
export VISION_API_KEY="<key>"

# 主力：自動跑新手任務序列並產報告
.venv/Scripts/python -I -X utf8 scripts/qa_interactive.py

# 最小啟動器：登入後由 cmd.txt 手動下指令（click/screenshot/wait）
.venv/Scripts/python -I -X utf8 scripts/start_session.py
```

**程式化方式：`GameSession` API**（供 Hermes 或自訂腳本呼叫）
```python
from webgl_qa.agent import GameSession

session = GameSession(game_url=URL, game_name="example_game")
await session.start()
obs = await session.observe()                       # 截圖 + 崩潰級異常偵測（不呼叫 Vision）
await session.execute_action({"type": "click", "x": 65, "y": 235})
session.record_game_state(vision_result["game_state"])   # 存入 Vision 讀到的數值
session.check_invariants("upgrade", before, after)       # 功能正確性 oracle
result = await session.finish()                     # 產報告 + oracle/anomaly 摘要
```

**Roadmap（尚未實作）**：統一 CLI、`validate`/`test --runs N` 回歸模式、`replay --bug-id`、
strategy override 檔。這些在 flow 穩定、且知識庫固化為確定性腳本後才有意義（見下方運作模式）。

---

## 專案結構

```
webgl-qa-agent/
├── DESIGN.md                  ← 本文件
├── pyproject.toml             ← uv 專案定義
├── src/
│   └── webgl_qa/
│       ├── __init__.py
│       ├── agent.py           ← GameSession 生命週期 + observe/act/oracle（無 __main__，driver 可注入）
│       ├── driver.py          ← 驅動層抽象介面（動詞 + capabilities + 中立效能 schema）
│       ├── browser.py         ← Playwright 瀏覽器控制（Driver 實作）
│       ├── adb_device.py      ← adb 驅動：原生 Android / 模擬器（Driver 實作）
│       ├── config.py          ← 分層設定（default.yaml + game_info.yaml）
│       ├── perceiver.py       ← SSIM/凍結/黑白屏/pixel diff
│       ├── detector.py        ← 崩潰級異常偵測
│       ├── oracle.py          ← 功能正確性 oracle（Vision 數值 + invariant）
│       ├── knowledge_base.py  ← 單一知識庫（靜態 YAML + runtime）
│       ├── vision.py          ← Claude Vision 呼叫（structured tool_use）
│       ├── prompts.py         ← Vision prompt 模板（由 config 生成）
│       ├── parser.py          ← Vision free-form JSON 解析（僅 custom prompt）
│       ├── actions.py         ← 共用 action 引擎（座標從知識庫讀）
│       ├── reporter.py        ← HTML 報告產生器
│       └── annotator.py       ← 截圖標註
├── config/
│   └── default.yaml           ← 全域預設設定
├── knowledge/<game>/          ← 每個遊戲的知識庫（systems/、flow_graph、problems/、game_info）
├── scripts/                   ← 執行腳本（qa_interactive、start_session、perf_runner、
│                                 android_monitor、android_autoplay…；以 python -X utf8 執行）
├── runs/<game>/               ← 每次測試獨立資料夾（report.html、session.json、screenshots）
├── reports/                   ← 舊版共用報告
└── screenshots/               ← 共用截圖
```

---

## 下一步

1. 建立專案骨架（pyproject.toml + 目錄結構）
2. 安裝依賴（playwright, httpx, pyyaml, pillow）
3. 實作 browser.py — 啟動 Chromium + 載入 URL + 截圖
4. 實作 perceiver.py — 截圖送 Vision LLM 取得分析
5. 實作 agent.py — explore loop（感知 → 決策 → 操作 → 學習）
6. 實作 knowledge.py — 讀寫 + 更新 knowledge.yaml
7. 實作 detector.py — console error / freeze / blank screen
8. 實作 reporter.py — 產出 HTML timeline
9. CLI 整合 — `__main__.py` 串接所有模組
10. 對一個公開 WebGL 遊戲做第一次 explore 驗證
