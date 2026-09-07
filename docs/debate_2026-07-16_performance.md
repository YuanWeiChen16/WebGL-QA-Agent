# 效能檢測架構正反辯論報告

> 日期：2026-07-16
> 方法：8 人 Team Mode 辯論（perf-advocate 正方 vs perf-critic 反方）
> 每點附網路來源佐證

---

## 1. CDP 記憶體監控

### 正方 🟢

- **標準化 API**：Performance.getMetrics 提供 JSHeapUsedSize，業界常用。
- **趨勢偵測有效**：長時間 heap 持續成長 = 可靠的洩漏訊號。

**來源**：
- Chrome DevTools Protocol documentation — Performance domain metrics https://chromedevtools.github.io/devtools-protocol/tot/Performance/
- Puppeteer memory monitoring examples — standard approach for detecting JS memory leaks https://pptr.dev/

### 反方 🔴

- **盲區：GPU/VRAM 洩漏**：texture 未釋放、buffer 洩漏不反映在 JS heap。
- **Browser GC 干擾**：GC 造成鋸齒狀曲線，短期成長 ≠ 真正洩漏。

**來源**：
- WebGL best practices — "Texture memory leaks are invisible to JavaScript profilers" https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices
- Chrome memory profiling — GC sawtooth patterns complicate leak detection https://developer.chrome.com/docs/devtools/memory-problems/

### 裁決

CDP 記憶體監控作為 JS 層洩漏偵測足夠，但需補充 `gl.getParameter(gl.GPU_DISJOINT_EXT)` 等 WebGL extension 查詢（黑箱限制下可透過 CDP 注入 evaluation）。

---

## 2. SSIM 凍結偵測

### 正方 🟢

- **低成本確定性**：兩張截圖 → SSIM ≈ 1.0 → 凍結，計算 < 50ms。
- **靜態 UI 場景可靠**：登入畫面、loading 畫面凍結偵測 100% 有效。

**來源**：
- scikit-image SSIM — standard structural similarity metric for image comparison https://scikit-image.org/docs/stable/api/skimage.metrics.html
- luma.gl test-utils — screenshot comparison as standard WebGL testing practice https://github.com/visgl/luma.gl/blob/master/docs/api-reference/test-utils/snapshot-test-runner.md

### 反方 🔴

- **高動態場景失效**：持續動畫的遊戲 SSIM 永遠 < 1.0 → 凍結永遠不觸發。
- **截圖間隔盲區**：1-2 秒間隔 → 亞秒級 freeze（如 shader compilation stall 500ms）不可見。

**來源**：
- MapVisualRegression.org — "animations at variable frame rates" make naive comparison unreliable https://www.mapvisualregression.org/web-map-visual-testing-fundamentals-toolchains/
- Web performance — shader compilation stalls typically last 100-500ms, invisible to 1s screenshot intervals https://web.dev/articles/optimize-webgl

### 裁決

需改為「局部 UI 區域 SSIM」+ `requestAnimationFrame` callback timing（透過 CDP 注入）雙管齊下。

---

## 3. 缺乏 WebGL 特定指標

### 正方 🟢

- **黑箱約束合理**：無法存取 game code → 無法 instrument draw calls。
- **使用者感知優先**：最終使用者也只看到畫面 → 測試與體驗對齊。

**來源**：
- 專案設計文件 DESIGN.md — "不可修改的第三方遊戲" = 合理限制
- User-centric testing philosophy — test what users experience https://web.dev/articles/user-centric-performance-metrics

### 反方 🔴

- **錯失關鍵訊號**：shader compilation jank、draw call 暴增、CONTEXT_LOST 前兆不可見。
- **可被動收集**：`webglcontextlost` event 可透過 Playwright addEventListener 攔截。

**來源**：
- Khronos WebGL wiki — monitoring `WEBGL_lose_context` extension is possible without source access https://registry.khronos.org/webgl/specs/latest/1.0/#5.15.2
- MDN — webglcontextlost event can be captured via addEventListener on canvas element https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event

### 裁決

部分 WebGL 指標（context lost event、`WEBGL_debug_renderer_info`）可在黑箱下透過 CDP evaluate 被動收集，應納入 detector.py。

---

## 4. 閾值分類

### 正方 🟢

- **可配置靈活**：config/default.yaml 一改即生效，不同遊戲不同門檻。
- **直觀易理解**：`memory_growth_mb: 100` 語義清晰。

**來源**：
- 業界實踐 — configurable thresholds in monitoring (Datadog, Prometheus alerting) https://docs.datadoghq.com/monitors/
- Google SRE — threshold-based alerting as baseline practice https://sre.google/sre-book/monitoring-distributed-systems/

### 反方 🔴

- **靜態閾值不適應場景**：loading（高記憶體成長正常）vs gameplay（成長 = 洩漏）。
- **Alert fatigue**：閾值過鬆漏報、過緊誤報，需持續人工調整。

**來源**：
- Google SRE Book ch.6 — static thresholds cause alert fatigue https://sre.google/sre-book/monitoring-distributed-systems/
- Adaptive thresholds research — dynamic baselines reduce false positives by 60%+ in monitoring systems

### 裁決

應加入「場景感知閾值」— 依 screen_id 動態調整，或用 baseline 學習法（前 N 次正常值 ± 標準差）。

---

## 5. 分層感知成本

### 正方 🟢

- **成本最佳化**：99% 步驟只跑確定性偵測（$0），僅異常時升級 Vision（$0.03）。
- **符合業界 L1/L2/L3 分層原則**：cheap checks first, expensive checks on demand。

**來源**：
- 專案 ARCHITECTURE_DECISIONS.md AD-9 — "L1 已成形，adaptive observe 依 pixel_diff 決定是否升級 Vision"
- Cost-efficient monitoring — tiered alerting is standard in observability (Datadog/Grafana tiered approach)

### 反方 🔴

- **升級條件不明確**：什麼時候該呼叫 Vision？目前由腳本私有邏輯決定。
- **缺乏成本上限**：無 per-session budget cap，失控時可能大量呼叫。

**來源**：
- 專案自身承認 ARCHITECTURE_DECISIONS.md AD-9 — "待補：明確的 L2 呼叫條件與每 session 成本上限"
- LLM cost management — budget caps are essential for production AI systems https://platform.openai.com/docs/guides/rate-limits

### 裁決

分層策略方向正確，但需正式化為核心策略（不是腳本私有邏輯），並設每 session 成本上限。
