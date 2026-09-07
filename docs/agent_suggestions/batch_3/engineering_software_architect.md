# 軟體架構師審查建議 — Batch 3

審查日期：2026-07-16
角色：Software Architect（系統設計、領域建模、架構模式、技術決策）

---

## 摘要

本次審查針對 DESIGN.md 與 ARCHITECTURE_DECISIONS.md 提出 5 項架構挑戰，經 kb-defender 逐題回應後，篩選出以下 3 項仍具改善空間的建議。其餘 2 項（Event-Driven 與 YAML 分離）defender 的防禦合理——程序式編排在目前規模是正確的 YAGNI 決策，靜態/動態 YAML 已物理分離。

---

## 建議 1：Oracle 感測器融合架構 — 從「重複取樣」走向「獨立通道投票」

### 問題

`oracle.py` 的功能正確性完全依賴 Vision LLM 讀數值。AD-2 的兩道防線（reread 二次確認、min_occurrences 連續計數）本質是「重複取樣同一個不可靠感測器」，不符合可靠性工程中「獨立通道冗餘」原則。defender 承認此為債務，但認為黑箱約束下獨立通道有限。

### 建議

引入**分層感測器融合架構**，即使在黑箱約束下仍有可用的獨立通道：

1. **L1: Pixel Template Matching（低成本、高精度、窄適用）** — 對已知 UI 位置（score/currency 顯示區域）做 ROI 裁切 + digit template matching。遊戲字型固定時精度極高，且零 API 成本。ROI 座標可從 `game_info.yaml` 的 `oracle.ui_regions` 宣告。

2. **L2: Local OCR（中成本、中精度）** — PaddleOCR/EasyOCR 對裁切後的小區域 ROI 做辨識。defender 提到「對藝術字型精度差」是全圖場景，但裁切後的數字區域（通常是標準字型 + 高對比背景）精度可接受。

3. **L3: Vision LLM（高成本、高通用性）** — 現有方案，作為仲裁者而非唯一來源。

**投票規則**：三通道中兩個一致即採信；全部不一致時標記為 `uncertain` 不計入 oracle 判定。

**實作路徑**：先量測現有 Vision 的 precision/recall（defender 建議的正確順序），確認瓶頸後再加入 L1/L2。建議先從最簡單的「digit ROI + template matching」開始——這在遊戲 UI 數字辨識領域已被驗證有效。

### 參考

- **FADE: Testing Fault-Tolerance of Multi-Sensor Fusion** (ACM SIGSOFT 2024) — 自駕系統的多感測器融合測試方法論，展示了「單一感測器故障如何級聯影響系統行為」及「獨立通道冗餘」的必要性。論文提出 feedback-guided differential fuzzer 來發現融合錯誤，概念可借用於 oracle precision 的自動化量測。
  https://dl.acm.org/doi/10.1145/3728910

- **FusED: Detecting Multi-sensor Fusion Errors in ADAS** (ISSTA 2022) — 提出「fusion fault = 選錯感測器輸出」的定義，並用因果分析做 root cause filtering。其 counterfactual intervention 概念（替換某通道觀察結果是否改變）可直接應用於 oracle 的「Vision 讀數 vs. template matching 讀數不一致時該信誰」。
  https://par.nsf.gov/servlets/purl/10397924

- **IRCA: Interventional Root Cause Analysis for MSF Perception** (NDSS 2025) — 階層式結構因果模型 (H-SCM) 定位多感測器融合中的故障根因。其「intervention oracle」概念（用已知正確輸出替換可疑模組）正是 template matching 作為 ground truth 校準 Vision 讀數的理論基礎。
  https://www.ndss-symposium.org/wp-content/uploads/2025-36-paper.pdf

### 優先級

P1 — 在 oracle precision 數據收集完成後立即排入。建議先實作最輕量的 digit ROI template matching 作為 Vision 的交叉驗證。

---

## 建議 2：screen_id 穩定化應提升為 P0 前置條件

### 問題

AD-5 承認 screen_id 由 Vision 自由命名且 SSIM 對動態畫面無判別力。defender 辯護稱「核心 QA path 走靜態層 system_id 不受影響」、「runtime layer 是可再生的副產物」。

但這個辯護暴露了更深層的架構問題：**如果 runtime learning 產出的知識「可拋棄」，那 DESIGN.md 宣稱的「累積經驗、逐步學會遊戲」的核心價值主張就是空的**。系統的差異化優勢（自主學習 + 知識累積）建立在一個不穩定的主鍵上。

### 建議

將 screen_id 穩定化從 🔲 待處理提升為 AD-4 (grounding) 的並行工作，而非其後續：

1. **UI 錨點指紋**（AD-5 已提案的方向）：遮罩動態區域後，對 UI 固定元素（按鈕、面板邊框、HUD 佈局）做 perceptual hash。這不依賴 AD-4 的 grounding 完成。

2. **Canonical Screen Registry**：定義有限的 canonical screen 集合（可從靜態 `systems/*.yaml` 的 system_id 衍生），Vision 命名只作 display name alias。

3. **漸進式穩定化**：新 session 開始時，先嘗試用 registry 匹配；匹配失敗才走 Vision 命名路徑（標記為 `unregistered`），人工審核後歸入 registry。

**關鍵論點**：defender 說「runtime 資料可再生（重跑幾個 session 就能重建）」——但如果每次重建的結果不一致（因為 screen_id 不穩），那「可再生」等於「不可用」。穩定化是讓 runtime learning 從「demo feature」變成「production asset」的門檻。

### 參考

- **Probar: Deterministic WASM Game Testing Framework** — 展示了遊戲測試中 deterministic replay 的架構：用 perceptual hash + state fingerprint 作為遊戲狀態的穩定標識，而非依賴視覺模型的自由命名。其「recording → replay → hash 比對」流程可作為 screen registry 穩定化的參考模型。
  https://docs.rs/crate/jugar-probar/0.3.0

- **Frontend Testing Skill (PhaserJS)** — 業界對 HTML5/WebGL 遊戲測試的最佳實踐：「Stabilize: seed RNG, freeze time, fix viewport/DPR, disable animations」。其中「add a ready signal + deterministic mode」的概念可應用於 screen fingerprint 的穩定採樣時機（等動畫穩定後才取指紋）。
  https://playbooks.com/skills/chongdashu/phaserjs-tinyswords/frontend-testing

### 優先級

P0 — 這是 runtime learning 價值主張的前置條件。無穩定 screen_id，所有知識累積機制（confidence、flow_graph、strategy evolution）都是建立在沙上。

---

## 建議 3：Game Simulator Adapter — 讓 QA 框架本身可做確定性回歸

### 問題

整合測試（`GameSession` 的 observe → act → oracle 完整迴路）需要真實瀏覽器 + 真實遊戲 + 真實 Vision API。defender 承認缺乏 `MockBrowser` + 預錄截圖的 integration test harness，但認為實作代價高（「模擬器需要回應點擊座標後下一幀是什麼，本質上是重建遊戲邏輯」）。

### 建議

不需要重建遊戲邏輯。採用 **Record-Replay Adapter** 模式（業界已有成熟方案）：

1. **Recording Phase**：正常跑一次 session，`GameSession` 的每個 browser 互動（screenshot 回傳、console log、page error）全部序列化存檔，附帶 action input 作為 key。

2. **Replay Phase**：`MockBrowser` 實作 `BrowserProtocol` 介面，根據 action sequence 依序回放預錄的截圖。不需要「理解座標」——只需要「第 N 個動作後回傳第 N 張截圖」。

3. **差異容忍**：replay 時若 action sequence 與錄製時不同（因為 agent 決策改變），則標記為 `diverged` 並 fallback 到最近的匹配點或宣告 test inconclusive。

**這不是模擬遊戲邏輯，而是 VCR pattern（錄影帶回放）**。業界已有 `test-proxy-recorder`（Playwright 的 record/replay API responses）、`routeFromHAR`（Playwright 內建的 HAR 回放）等成熟工具做完全相同的事。

**關鍵價值**：
- 讓 `oracle.py` 的 invariant 邏輯變更後可以跑 integration regression（不需連真實遊戲）
- 讓 CI 可以驗證 `GameSession` 的完整流程不會因重構而壞
- Vision API 可以用預錄的 response 替代（省成本 + 確定性）

### 參考

- **test-proxy-recorder** — Record & replay API responses for Playwright E2E tests（SSR proxy + browser HAR + WebSockets）。「Every flaky e2e run has the same root cause: the network. This records real traffic once, then replays it byte-for-byte on CI.」完全相同的概念可應用於 Vision API 回應的錄放。
  https://github.com/asmyshlyaev177/test-proxy-recorder

- **playwright-browser-harness** — 在 Playwright 下跑 bundled TypeScript 的 test harness，支援 COOP/COEP、Web Workers、persistence across reloads。展示了「真實瀏覽器 harness + 可控環境」的架構模式。
  https://github.com/wighawag/playwright-browser-harness

- **Playwright for HTML5 Game Testing (Reddit/r/gamedev)** — 實務經驗分享：HTML5 遊戲測試用 Playwright 的挑戰（canvas 元素不在 DOM）與解法（expose window test API + screenshot assertion）。驗證了 record-replay + screenshot comparison 在 WebGL 遊戲測試中的可行性。
  https://www.reddit.com/r/gamedev/comments/1p3d5ze/how_i_use_playwright_for_automated_inbrowser/

### 優先級

P2 — 在 AD-7（CI 回歸層）之前實作。建議先從最小的 `MockBrowser`（依序回放預錄截圖 + 預錄 Vision response）開始，不需要完整的 traffic proxy。

---

## 未列為建議的項目（defender 防禦成立）

### Event-Driven Architecture

defender 的防禦合理且有充分業界支持。目前 3-5 個模組、單 session 序列化執行、一個 consumer 的場景，程序式編排是正確選擇。業界共識明確：

> 「Events are a powerful tool and a terrible default. Reach for them deliberately... The system is small and the team is small. EDA buys you decoupling. If you don't have multiple teams or multiple consumers, you're paying complexity tax for benefits you won't use.」— [Event-Driven Architecture Without the Hype](https://ruchitsuthar.com/blog/software-architecture/event-driven-architecture-without-the-hype/)

> 「When your entire engineering team fits in a single conference room, the debugging challenges in decoupled systems can paralyze your development velocity.」— [Resisting the Event-Driven Architecture Trap](https://www.banandre.com/blog/resisting-the-event-driven-architecture-trap)

**演化觸發條件**：當模組數 >10、需要插件生態（第三方 anomaly handler）、或跨 session 事件串流（趨勢分析）時再考慮。

### YAML Configuration/State 分離

defender 正確指出靜態層與動態層已物理分離為不同檔案。唯一的交叉點 `update_element_location()` 是 dead code path。建議的唯一微調：未來若啟用該方法，應改為寫入 runtime override 層而非直接修改靜態 YAML。

---

## 行動項目摘要

| # | 建議 | 優先級 | 前置條件 | 預估影響 |
|---|------|--------|----------|----------|
| 1 | Oracle 多通道感測器融合 | P1 | oracle precision 數據收集 | 降低 false positive/negative，提升 oracle 可信度 |
| 2 | screen_id 穩定化提升為 P0 | P0 | 無（可與 AD-4 並行） | runtime learning 從 demo 變 production asset |
| 3 | Game Simulator Adapter (VCR pattern) | P2 | 無 | 啟用 CI integration regression，降低開發反饋循環 |
