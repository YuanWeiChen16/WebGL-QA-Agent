# Rapid Prototyper 架構審查建議

> **審查角色**：Engineering Rapid Prototyper（快速原型 / MVP 驗證專家）
> **審查對象**：DESIGN.md 整體架構
> **日期**：2026-07-16

---

## 審查摘要

從快速原型開發的角度審視本專案架構，向 Arch Defender 提出了五個挑戰：time-to-value、schema 過度設計、自建 vs 組合現有工具、三模式 scope creep、以及迭代速度。Defender 的回覆證明了架構是從可運行腳本有機演化而來，且核心模組各有具體使用者。以下建議聚焦於**仍有改善空間**的面向。

---

## 建議 1：新增 `uv run demo` 一行指令快速上手體驗

**現況問題**：目前從零到看到結果需要 4 步（cp .env → uv sync → playwright install → 跑腳本），且需要手動設定 Vision API 金鑰。對於想快速評估此工具的開發者來說，門檻過高。

**建議做法**：
- 在 `pyproject.toml` 加入 `[project.scripts]` entry，例如 `webgl-qa = "webgl_qa.demo:main"`
- 建立 `src/webgl_qa/demo.py`，內含一個不依賴 Vision API 的 demo 模式（僅展示截圖 + SSIM + 異常偵測，跳過 LLM 呼叫）
- 讓 `uv run webgl-qa demo` 一行即可對公開 WebGL Aquarium 執行基本 QA loop

**參考**：
- uv 官方文件 `[project.scripts]` 機制：https://docs.astral.sh/uv/guides/tools/
- Simon Willison 的 uv CLI 開發模式（展示如何用 `uv run` 直接執行 CLI）：https://til.simonwillison.net/python/uv-cli-apps
- 完整 uv CLI 教學（從 init 到 Docker）：https://www.danilchenko.dev/posts/uv-python-tutorial/

**預期效果**：新開發者 30 秒內看到系統運作，降低評估門檻，加速社群採用。

---

## 建議 2：參考 gameagent-ai 的 LangGraph 架構，考慮 agent loop 狀態機化

**現況問題**：目前 `GameSession` 的 agent loop（observe → act → learn）是程序式流程，缺乏明確的狀態轉移定義。當 loop 複雜化（加入 retry、fallback、timeout handling），程序式寫法容易變成 spaghetti code。

**建議做法**：
- 不需要立即重寫，但可參考 gameagent-ai 使用 LangGraph 定義 observe/think/act/learn 狀態機的模式
- 在現有 `agent.py` 中先定義明確的 `AgentState` enum（OBSERVING / ACTING / LEARNING / ERROR_RECOVERY）
- 為未來的 Validate/Test 模式預留狀態轉移接口

**參考**：
- gameagent-ai（GPT-4o Vision + Playwright + LangGraph，與本專案高度同構）：https://github.com/vineethsaivs/gameagent-ai
- ai-game-playtesting-agent（LangGraph orchestration + 結構化報告）：https://github.com/ysskrishna/ai-game-playtesting-agent

**預期效果**：讓 agent loop 的控制流更透明、更容易 debug，也為未來加入 Validate/Test 模式提供清楚的擴展點。

---

## 建議 3：加入「零 Vision 確定性回歸層」作為迭代加速器

**現況問題**：每次跑完一輪 QA 都需要 Vision LLM 呼叫（有成本、有延遲）。在快速迭代階段，開發者改了 detector.py 或 oracle.py 後想確認沒壞掉，但沒有不花錢的方式驗證。

**建議做法**：
- 建立 `tests/` 目錄，用 recorded session（現有的 `session.json`）作為 fixture
- 對 detector/oracle/perceiver 寫純確定性的 unit test（輸入固定截圖 + 固定 game_state，驗證輸出）
- 加入 `uv run pytest` 作為 CI gate

**參考**：
- Playwright canvas game 測試的確定性模式設計（seed RNG + freeze time + fixed viewport）：https://agentskills.so/skills/chongdashu-phaserjs-oakwoods-playwright-testing
- T-Rex Runner 的 Playwright + canvas 測試（page.evaluate 讀 game state、console error 即失敗）：https://github.com/CanarysAutomations/Testing-with-Agents-GHCP
- api4.ai 的 30 天 MVP sprint 中的 test harness 建議：https://api4.ai/blog/timeline-to-mvp-30-day-sprint-with-vision-microservices

**預期效果**：改 code → 跑 test → 3 秒知道有沒有壞。迭代 cycle 從「分鐘級」降到「秒級」。

---

## 建議 4：Knowledge Schema 加入 lightweight 模式，降低新遊戲 onboarding 成本

**現況問題**：Arch Defender 正確指出 knowledge.yaml 的複雜度有具體 ROI（人類可編輯、actions.py 直接讀座標）。但對於**第一次對新遊戲跑 explore** 的場景，要求一開始就填寫完整 schema 會拖慢上手速度。

**建議做法**：
- 支援一個 minimal bootstrap：只需 `game_info.yaml` 中填 `url` 和 `title`，其餘全部由 explore 自動生成
- 第一次 explore 結束後，自動從 session.json 歸納出初版 knowledge.yaml（screen list + observed transitions）
- 人工微調是 optional 的第二步，不是 prerequisite

**參考**：
- MVP 測試方法論（從低保真到高保真漸進）：https://www.figma.com/resource-library/mvp-testing-methods/
- AI 原型開發指南（先 hypothesis → 最小可測試物 → 再加結構）：https://bubble.io/blog/ai-prototyping-for-product-managers/

**預期效果**：新遊戲從「填 YAML → 才能跑」變成「給 URL → 自動跑 → 自動產出初版 YAML」，time-to-first-result 降低 80%。

---

## 建議 5：借鏡 Browser-Operating-Agent 的 pixel sampling 技術，減少 Vision 呼叫

**現況問題**：目前每次 observe 都依賴 Vision LLM 才能理解畫面。但對於「分數是否改變」「砲倍階是否正確」這類**局部數值讀取**，Vision LLM 是 overkill（慢且貴）。

**建議做法**：
- 對已知 knowledge 中標記了 `type: display`（如分數、金幣）的元素，用 OCR 或 pixel sampling 做確定性讀取
- Vision LLM 只在「不確定當前是什麼 screen」或「發現新元素」時才呼叫
- 分層策略：確定性快速讀取 → 不確定時才升級到 Vision

**參考**：
- Browser-Operating-Agent（純 PIL pixel sampling 讀取 canvas 狀態，無需 LLM）：https://github.com/Hassan-Naeem-code/Browser-Operating-Agent
- gameagent-ai 的 observe 層設計（screenshot → GPT-4o，但可以被更輕量的方案替代局部讀取）：https://github.com/vineethsaivs/gameagent-ai
- api4.ai 的分層 Vision 架構（先用輕量 API，複雜情況才用重模型）：https://api4.ai/blog/timeline-to-mvp-30-day-sprint-with-vision-microservices

**預期效果**：已知元素的讀取成本降為 0（純 PIL），Vision 呼叫量減少 60-80%，迭代速度與運行成本同時改善。

---

## Defender 回覆中的有效論點（已納入考量）

| 挑戰 | Defender 論點 | 我的結論 |
|-------|--------------|----------|
| Q1 POC | 架構確實從腳本有機長出 | 同意。不建議推倒重來 |
| Q2 Schema | YAML 結構各有具體消費者 | 同意。建議加 lightweight bootstrap 模式而非簡化 schema |
| Q3 自建 | 核心差異化（語義 oracle）無法用 Applitools 替代 | 同意。建議維持自建但借鏡外部工具的局部技術 |
| Q4 三模式 | 事實上只做了 Explore | 同意。設計願景寫出來是對的 |
| Q5 迭代速度 | 4 步 5 分鐘 | 部分同意。建議再壓到 1 行 30 秒 |

---

## 總結優先級

| # | 建議 | 投入 | 影響 | 建議優先度 |
|---|------|------|------|-----------|
| 1 | `uv run demo` 一行指令 | 小（半天） | DX 大幅改善 | **高** |
| 3 | 零 Vision 確定性測試 | 中（1-2 天） | 迭代速度根本改善 | **高** |
| 4 | Knowledge lightweight bootstrap | 中（1 天） | 新遊戲 onboarding 加速 | **中** |
| 5 | Pixel sampling 減少 Vision 呼叫 | 中（2 天） | 成本與速度改善 | **中** |
| 2 | Agent loop 狀態機化 | 大（3-5 天） | 架構可維護性 | **低**（現階段不急） |
