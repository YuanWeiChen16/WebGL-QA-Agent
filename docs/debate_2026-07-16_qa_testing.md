# QA 測試架構正反辯論報告

> 日期：2026-07-16
> 方法：8 人 Team Mode 辯論（qa-advocate 正方 vs qa-critic 反方）
> 每點附網路來源佐證

---

## 1. 黑箱視覺測試方法

### 正方 🟢

- **通用性極高**：不需遊戲原始碼，適用任何第三方 WebGL 遊戲。Microsoft Inspector 正是在「目標無法 instrument」時採純像素法。
- **零侵入**：不改遊戲程式碼 = 不影響產品行為、不引入 observer effect。

**來源**：
- Autify — "Canvas and WebGL apps break traditional automation. No DOM, no selectors" https://autify.com/solutions/canvas-and-webgl-testing
- MapVisualRegression.org — deterministic rendering + visual comparison is standard for opaque rendering engines https://www.mapvisualregression.org/web-map-visual-testing-fundamentals-toolchains/

### 反方 🔴

- **座標脆弱**：絕對像素定位在 UI 變動時即失效，維護成本高。
- **無 ground truth**：畫面數字是唯一真值來源，OCR 誤讀無法交叉驗證。

**來源**：
- Three.js Forum — visual testing for dynamic 3D content generates false positives from minor camera shifts https://discourse.threejs.org/t/best-practices-for-qa-automation/89191
- deck.gl testing docs — "Testing WebGL code is much harder...rendering behavior differs cross platforms" https://github.com/uber/deck.gl/blob/master/docs/developer-guide/testing.md

### 裁決

對不可修改的第三方遊戲，黑箱是唯一選擇（非退而求其次）。但需投資座標 grounding 與多訊號交叉驗證降低脆弱性。

---

## 2. Vision LLM 作為 Test Oracle

### 正方 🟢

- **語義理解**：能讀懂「等級 5」「金幣 1200」等畫面數值，超越純像素比對。
- **結構化輸出**：tool_use schema 保證 JSON 格式，可程式化處理。

**來源**：
- GPT-4V/Claude Vision 在 OCR benchmark 達 90%+ 準確率 — OpenAI GPT-4V technical report https://openai.com/research/gpt-4v-system-card
- threejs-visual-qa PoC — "Solves the fundamental problem of testing WebGL content inside an opaque canvas element" https://github.com/yomero243/threejs-visual-qa

### 反方 🔴

- **幻覺風險**：LLM 可能「看到」不存在的數字，單次讀數不可信。
- **成本與延遲**：每次呼叫 $0.01-0.05，延遲 2-5 秒，不適合即時測試。

**來源**：
- Anthropic — Vision models may hallucinate text in complex scenes https://docs.anthropic.com/en/docs/build-with-claude/vision
- 業界共識 — Vision API calls at $0.01-0.05/image make high-frequency testing prohibitive

### 裁決

Vision LLM 作為 oracle 在黑箱場景下是創新且有效的，但必須搭配「二次確認」機制（專案已實作 reread）和成本上限控制。

---

## 3. 確定性異常偵測層

### 正方 🟢

- **零成本、零延遲**：SSIM + pixel diff + console error 不需 LLM，可每步執行。
- **崩潰級偵測可靠**：黑白屏 (dominant color)、console CONTEXT_LOST 是確定性訊號。

**來源**：
- luma.gl SnapshotTestRunner — pixel-diffing as standard practice for WebGL render tests https://github.com/visgl/luma.gl/blob/master/docs/api-reference/test-utils/snapshot-test-runner.md
- WebGL spec — CONTEXT_LOST_WEBGL event is deterministic signal of GPU failure https://registry.khronos.org/webgl/specs/latest/1.0/#5.15.2

### 反方 🔴

- **動態內容盲區**：魚群游動 = SSIM 永遠變化 → 凍結偵測失效。
- **全圖 SSIM 粗糙**：UI 區變化被動態背景稀釋，細微 UI bug 偵測不到。

**來源**：
- MapVisualRegression.org — "Pixel-perfect diffing is fundamentally misaligned with...continuous animation loops" https://www.mapvisualregression.org/web-map-visual-testing-fundamentals-toolchains/
- Wonderland Engine testing — uses per-pixel RMSE tolerance + event-based capture for precision https://github.com/hugoam/wonderland-screenshot-testing

### 裁決

確定性層作為 L1 篩選器正確，但需改進：遮罩動態區的局部 SSIM、UI 錨點指紋比對。

---

## 4. Invariant 宣告式功能正確性

### 正方 🟢

- **可測試、可維護**：YAML 宣告 `{field: level, kind: increment, delta: 1}` 清晰明確。
- **確定性引擎**：oracle.py 比對純數學，可 100% 單元測試。

**來源**：
- Property-based testing (QuickCheck/Hypothesis) — declarative invariants catch edge cases https://hypothesis.readthedocs.io/
- oracle.py 已有 16 個 unit tests 全覆蓋

### 反方 🔴

- **表達力有限**：無法描述複雜狀態機（如：使用技能→冷卻→再次可用的時序邏輯）。
- **sensor 依賴**：輸入來自 Vision OCR，garbage in = garbage out。

**來源**：
- Game state machines are inherently complex — simple invariants miss emergent behavior https://www.gamedeveloper.com/
- 專案自身 ARCHITECTURE_DECISIONS.md 承認 "oracle 輸入是 Vision 讀數，本身會誤讀"

### 裁決

Invariant 引擎設計正確，但需擴展為 temporal logic（`after N steps`、`within T seconds`）以覆蓋時序行為。

---

## 5. 純 Canvas 測試（無 DOM）

### 正方 🟢

- **適用任何 WebGL 遊戲**：Unity WebGL、Cocos、Pixi.js、原生 WebGL 全通用。
- **不受框架綁定**：不依賴 Unity/Cocos 特定 SDK。

**來源**：
- Autify — "Most testing tools were built for the DOM...Canvas applications bypass all of that" https://autify.com/solutions/canvas-and-webgl-testing
- GameDriver/AltTester require source code access — limits to owned games only

### 反方 🔴

- **喪失豐富資訊**：DOM overlay（loading bar、error dialog）無法區分來源。
- **效能指標盲區**：WebGL context 內部狀態（draw calls, GPU memory）完全不可見。

**來源**：
- Playwright docs — toHaveScreenshot captures full page including non-canvas DOM elements https://playwright.dev/docs/test-snapshots
- Chrome DevTools WebGL Inspector 能即時監控 draw calls 和 texture memory — 但需 extension 注入

### 裁決

純 canvas 方法在「第三方遊戲」約束下正確。但對 DOM overlay 元素（如錯誤彈窗）建議額外攔截 DOM mutation。
