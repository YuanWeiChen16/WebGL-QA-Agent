# 現有架構對比正反辯論報告

> 日期：2026-07-16
> 方法：8 人 Team Mode 辯論（arch-advocate 正方 vs arch-critic 反方）
> 每個競品附網路來源佐證

---

## 對比總覽

| 競品 | webgl-qa-agent 勝出之處 | 競品勝出之處 | 何時用誰 |
|------|------------------------|-------------|---------|
| glcheck | 能測 gameplay 行為 | 確定性/CI-native | glcheck=API test; 本專案=gameplay QA |
| Autify Aximo | 開源/知識累積 | 企業級穩定 | Aximo=企業; 本專案=客製化 |
| luma.gl | 不綁生態 | 成熟 pipeline | luma.gl=data viz; 本專案=遊戲 |
| Playwright | 語義理解 | 零成本/大社群 | Playwright=回歸; 本專案=智慧探索 |
| GameDriver | 不需原始碼 | 精準狀態存取 | GameDriver=自家遊戲; 本專案=第三方 |
| EA SEED | 實用可部署 | 真正 RL 探索 | EA SEED=研究; 本專案=可用工具 |
| Microsoft | 開源輕量 | 企業規模 | Microsoft=AAA; 本專案=中小團隊 |

---

## 1. vs glcheck

### webgl-qa-agent 勝出 🟢

- **能測真正的 gameplay**：glcheck 只能測 WebGL API conformance（pixelEqual、parameterEqual），無法測「升級後等級是否加 1」「點擊按鈕後畫面是否切換」等遊戲行為。
- **不需測試 harness**：glcheck 需要為每個 test case 寫渲染程式碼，本專案直接對線上遊戲操作。

**來源**：
- glcheck README — "A WebGL-focused testing framework" for unit and render tests https://github.com/tsherif/glcheck
- glcheck 設計 — 提供 `t.pixelEqual()`、`t.bufferEqual()` 等 WebGL API 層面斷言，非 gameplay 層面

### glcheck 勝出 🔴

- **確定性可重現**：每次 run 結果相同，CI pass/fail 明確。
- **零 LLM 成本**：純 JavaScript 斷言，毫秒級執行。
- **CI-native**：直接掛 GitHub Actions，exit code 即結果。

**來源**：
- glcheck — "allows it to run automated tests and generate coverage reports" https://github.com/tsherif/glcheck
- 本專案 ARCHITECTURE_DECISIONS.md AD-7 — 承認 "尚無 pass/fail verdict 與 exit code"

### 何時選誰

- glcheck：測試 WebGL shader/rendering API 的正確性（白箱 unit test）
- webgl-qa-agent：測試遊戲行為（黑箱 gameplay QA）

---

## 2. vs Autify Aximo

### webgl-qa-agent 勝出 🟢

- **開源免費**：MIT 授權，完全可自訂。
- **知識累積跨 session**：Aximo 每次從零開始，本專案累積學習。
- **宣告式 invariant**：可定義遊戲邏輯檢查，非僅視覺比對。

**來源**：
- Autify Aximo — "autonomous AI testing agent" using natural language https://autify.com/solutions/canvas-and-webgl-testing
- Autify 為 SaaS 商業產品，月費 $1,000+，無法自訂內部邏輯

### Autify Aximo 勝出 🔴

- **商業級穩定**：有專門團隊維護、客服支援、SLA 保證。
- **企業級規模**：雲端並行執行、自動排程、團隊協作。
- **即用性**：自然語言寫測試，5 分鐘上手。

**來源**：
- Autify — "Zero setup, fully cloud" with enterprise support https://autify.com/solutions/canvas-and-webgl-testing
- 本專案仍是 "Research preview / 實驗性專案"（README）

### 何時選誰

- Autify：企業預算充裕、需立即上線、不需深度客製化
- webgl-qa-agent：開源需求、需知識累積、需自訂 invariant 邏輯

---

## 3. vs luma.gl/test-utils

### webgl-qa-agent 勝出 🟢

- **不綁生態**：luma.gl 強綁 vis.gl（deck.gl/kepler.gl），只適用 data visualization。
- **適用遊戲**：luma.gl 的 AnimationLoop + SnapshotTestRunner 是為地圖/圖表設計，非互動式遊戲。
- **智慧探索**：能發現未知 UI，不只做已知場景回歸。

**來源**：
- luma.gl SnapshotTestRunner — designed for "Browser-based WebGL render tests" in vis.gl context https://github.com/visgl/luma.gl/blob/master/docs/api-reference/test-utils/snapshot-test-runner.md
- deck.gl testing — test cases are predefined layer configurations, not gameplay exploration https://github.com/uber/deck.gl/blob/master/docs/developer-guide/testing.md

### luma.gl 勝出 🔴

- **成熟穩定**：在 deck.gl（40k+ GitHub stars）中經歷數年生產驗證。
- **完善的 golden image pipeline**：tolerance / threshold / per-pixel 差異全配置化。
- **Puppeteer + BrowserTestDriver 整合完善**：headless / non-headless 自動切換。

**來源**：
- luma.gl test-utils — battle-tested with configurable imageDiffOptions https://github.com/visgl/luma.gl/blob/master/docs/api-reference/test-utils/snapshot-test-runner.md
- @luma.gl/test-utils npm — "Automated WebGL testing utilities with Puppeteer and image diffing" https://npmx.dev/package/@luma.gl/test-utils

### 何時選誰

- luma.gl：vis.gl 生態的 data visualization 回歸測試
- webgl-qa-agent：互動式 WebGL 遊戲的行為 QA

---

## 4. vs Playwright toHaveScreenshot()

### webgl-qa-agent 勝出 🟢

- **語義理解**：能理解「分數增加了」「等級升了」，而非僅判斷像素差異。
- **智慧探索**：能自主發現未知畫面，不需預先定義所有 test case。
- **功能正確性**：Playwright 只能判斷「畫面變了 vs 沒變」，無法判斷「變對了」。

**來源**：
- Playwright toHaveScreenshot — "Produces and visually compares screenshots" https://playwright.dev/docs/test-snapshots
- 本專案 oracle.py — 可斷言 "upgrade action should increment level by 1"，Playwright 做不到

### Playwright 勝出 🔴

- **零 LLM 成本**：純像素比對，無任何 API 費用。
- **巨大社群**：npm 週下載量 5M+，問題必有解答。
- **內建 CI 整合**：`npx playwright test` 即可，exit code 直接表達 pass/fail。
- **穩定可靠**：確定性比對，不受 LLM 隨機性影響。

**來源**：
- Playwright test — built-in visual comparison with CI integration https://playwright.dev/docs/test-snapshots
- threejs-visual-qa — demonstrates Playwright as "preferred standard over WebdriverIO for WebGL testing" https://github.com/yomero243/threejs-visual-qa

### 何時選誰

- Playwright toHaveScreenshot：已知 baseline 的視覺回歸（確認「沒壞」）
- webgl-qa-agent：未知遊戲的智慧探索 + 功能正確性驗證（確認「做對了」）

---

## 5. vs GameDriver / AltTester

### webgl-qa-agent 勝出 🟢

- **不需遊戲原始碼**：GameDriver/AltTester 必須在遊戲中注入 SDK，第三方遊戲不可能。
- **跨引擎通用**：不限 Unity/Unreal，任何 WebGL 遊戲皆可。
- **零部署成本**：不需修改 build pipeline。

**來源**：
- AltTester — "requires adding AltDriver to your app" https://alttester.com/docs/
- GameDriver — "connects to your running game" requiring integration SDK https://gamedriver.io/

### GameDriver/AltTester 勝出 🔴

- **Ground truth 狀態存取**：直接讀取遊戲內部變數（生命值、金幣、等級），不靠 OCR。
- **毫秒級精準**：直接操作 UI element by reference，無座標偏移問題。
- **業界標準**：AAA 工作室採用，經過大規模驗證。
- **確定性**：操作和斷言都是確定性的，無 Vision 隨機性。

**來源**：
- GameDriver — "automate functional, performance, regression testing" with object-level access https://gamedriver.io/
- AltTester — "find objects, interact using object references, not coordinates" https://alttester.com/

### 何時選誰

- GameDriver/AltTester：自家 Unity/Unreal 遊戲（可修改原始碼）
- webgl-qa-agent：第三方不可修改的 WebGL 遊戲

---

## 6. vs EA SEED 自動化遊戲測試

### webgl-qa-agent 勝出 🟢

- **立即可用**：不需百萬步 RL 訓練，第一次 run 就能做 QA。
- **人類知識整合**：YAML 知識庫讓人工經驗直接注入，不靠 agent 自己摸索。
- **成本可控**：每次 run 成本明確（截圖 + 偶爾 Vision call），不像 RL 需要大量 GPU 訓練。

**來源**：
- EA SEED — "Augmenting Game Testing with AI" uses RL requiring millions of training steps https://www.ea.com/seed/news/automated-game-testing-using-deep-reinforcement-learning
- RL training costs — millions of environment interactions before usable policy

### EA SEED 勝出 🔴

- **真正自主探索**：RL agent 發現的 bug 是人類想不到的（novel failure modes）。
- **不依賴 Vision LLM**：直接在遊戲環境內學習，無 API 成本瓶頸。
- **覆蓋率保證**：RL 的 exploration bonus 確保系統性覆蓋狀態空間。
- **學術嚴謹**：有正式 paper 和實驗驗證。

**來源**：
- EA SEED research — RL agents found bugs that manual QA missed in production games https://www.ea.com/seed/news/automated-game-testing-using-deep-reinforcement-learning
- DeepMind game testing — RL exploration discovers edge cases beyond human intuition https://deepmind.google/discover/blog/

### 何時選誰

- EA SEED 方法：研究級探索、有 GPU 資源和訓練時間、追求最高覆蓋率
- webgl-qa-agent：需要立即可用的 QA 工具、人工知識整合、成本可控

---

## 7. vs Microsoft 遊戲測試工具

### webgl-qa-agent 勝出 🟢

- **開源透明**：MIT 授權，完全可自訂和擴展。
- **輕量部署**：Python + Playwright，不需企業基礎設施。
- **WebGL 專注**：針對 browser-based 遊戲最佳化，非泛用 native game 工具。

**來源**：
- Microsoft Game Testing — primarily targets Xbox/PC native games, not web-based games
- 本專案 — MIT license, single pip install, no infrastructure needed

### Microsoft 勝出 🔴

- **業界驗證**：Xbox 認證流程背書，AAA 大廠信賴。
- **企業規模**：支援數千台設備並行測試、完整 dashboard、團隊管理。
- **合規性**：Xbox certification requirements compliance built-in。
- **完整生態**：與 Azure DevOps、PlayFab 等整合。

**來源**：
- Microsoft Game Dev tools — enterprise-scale testing infrastructure https://developer.microsoft.com/en-us/games/
- Xbox certification requirements — automated compliance testing https://learn.microsoft.com/en-us/gaming/gdk/

### 何時選誰

- Microsoft：AAA 大廠、Xbox/PC native games、需要認證合規
- webgl-qa-agent：獨立/中小團隊、WebGL browser games、開源需求

---

## 綜合結論

**webgl-qa-agent 的獨特定位**：在「第三方不可修改 WebGL 遊戲的智慧黑箱 QA」這個 niche 中，目前沒有直接競品。

**最需從競品借鏡的 3 點**：
1. **從 Playwright 學**：CI 整合 + pass/fail exit code（AD-7 已規劃）
2. **從 EA SEED 學**：exploration bonus / coverage-driven 終止策略（AD-8 已規劃）
3. **從 GameDriver 學**：精確 assertion 模式（在可透過 CDP 注入的有限程度下模擬）

**長期願景**：結合 Vision LLM 語義理解 + RL exploration + 確定性回歸層，成為 WebGL 遊戲 QA 的完整解決方案。
