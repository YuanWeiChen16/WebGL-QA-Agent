# Technical Artist 審查建議 — Batch 6

> 審查角度：Shader 效能、Draw Call 監控、Texture Memory 追蹤、GPU Profiling
> 日期：2026-07-16

---

## 建議 1：注入 WebGL Context Loss 事件監聽器（取代純 console pattern match）

**現況問題**：`detector.py` 只靠 console log 字串比對 `CONTEXT_LOST` 來偵測 GPU context loss。若遊戲本身未將此事件印出 console，則完全漏偵測。此外缺乏「預警」機制——context loss 發生時已經太晚。

**建議做法**：
1. 透過 `page.addInitScript` 注入 `canvas.addEventListener('webglcontextlost', ...)` 與 `webglcontextrestored` 監聽器，將事件推入一個可被 Playwright 讀取的全域陣列。
2. 同時注入 `gl.isContextLost()` 定期輪詢（每 N 幀檢查一次），作為被動事件的補充主動偵測。
3. 利用 `WEBGL_lose_context` extension 在測試環境中模擬 context loss，驗證偵測機制本身的可靠性。

**預期效果**：將 context loss 偵測從「遊戲自行 log 才抓得到」提升為「100% 覆蓋率的 DOM 事件攔截」，且可在 CI 中用模擬觸發做回歸。

**參考資料**：
- MDN — webglcontextlost event：https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event
- Khronos — Handling Context Lost：https://wikis.khronos.org/webgl/HandlingContextLost
- WEBGL_lose_context 規格：https://registry.khronos.org/webgl/extensions/WEBGL_lose_context/

---

## 建議 2：注入輕量 WebGL Memory Tracker 估算 GPU VRAM 使用量

**現況問題**：系統完全沒有 GPU 記憶體估算。JS heap (`performance.memory`) 不含 VRAM。Texture thrashing、LOD streaming 故障、資源洩漏等 GPU 側問題是完全盲區。

**建議做法**：
1. 採用 `webgl-memory` 方案（或自建等效輕量版），在 `page.addInitScript` 階段 monkey-patch WebGL context 的 `texImage2D`、`texSubImage2D`、`bufferData`、`deleteTexture`、`deleteBuffer` 等方法。
2. 根據 `internalformat × width × height × mip levels` 估算每次 texture 分配的 bytes，維護 running total。
3. 設定門檻（例如 512MB），超過時推送警告到 anomaly 系統。
4. 區分 `texStorage2D`（不可變大小，記憶體較可預測）與 `texImage2D`（可能需要 2× 記憶體）。

**預期效果**：在 context loss 發生前就能偵測到記憶體壓力趨勢，區分「正常高負載」與「資源洩漏」。

**參考資料**：
- HIABRE/webgl-memory（完整 VRAM 追蹤實作）：https://github.com/HIABRE/webgl-memory
- lewisgoing/webgltools（含 Resource Tracking + memory estimation）：https://github.com/lewisgoing/webgltools

---

## 建議 3：注入 Draw Call / State Change 計數器做每幀效能 Profile

**現況問題**：系統完全沒有 draw call 監控。WebGL 遊戲效能瓶頸常來自過多的 draw calls、頻繁 shader program switch、大量 texture bind，但目前只有 FPS 和 SSIM 兩個指標，無法定位渲染管線的具體瓶頸。

**建議做法**：
1. 透過 `page.addInitScript` 注入 WebGL proxy，攔截 `gl.drawArrays`、`gl.drawElements`、`gl.drawArraysInstanced`、`gl.drawElementsInstanced`、`gl.useProgram`、`gl.bindTexture`。
2. 每幀統計：draw call 數量、vertices/triangles 數量、shader switches、texture binds。
3. 將統計結果暴露為 `window.__webgl_perf_stats`，由 Playwright 的 `page.evaluate` 定期讀取。
4. 設定門檻（如 draw calls > 500/frame → warning, > 1000 → critical）。

**這不違反黑箱原則**——只是「可觀測性注入」（observability instrumentation），不修改遊戲邏輯。等同在生產環境加 APM agent。

**預期效果**：能定位「FPS 低是因為 draw call 爆量還是 shader 太重」，為效能 bug 提供根因分類。

**參考資料**：
- ayamflow/webgl-spy（輕量 draw call monitor）：https://github.com/ayamflow/webgl-spy
- webgl-stats npm（完整統計 API）：https://registry.npmjs.org/webgl-stats
- eyworldwide/GLPerf（WebGL Performance Monitor）：https://github.com/eyworldwide/GLPerf

---

## 建議 4：利用 EXT_disjoint_timer_query 做 GPU-side 時間量測

**現況問題**：FPS profiler 只在 CPU 側用 `requestAnimationFrame` 測幀率，無法區分「CPU-bound」與「GPU-bound」。更無法定位是哪個 draw call 最貴。系統也無法區分「GPU pipeline stalled（真凍結）」與「GPU-bound stuttering（只是慢）」。

**建議做法**：
1. 偵測 `gl.getExtension('EXT_disjoint_timer_query_webgl2')` 是否可用（Chrome 桌面版通常支援）。
2. 若可用，在 WebGL proxy 的每個 draw call 前後插入 `beginQuery`/`endQuery`，非阻塞地取得 GPU 耗時。
3. 將 per-draw-call GPU timing 聚合為每幀 GPU total time，與 CPU frame time 比對即可判斷瓶頸側。
4. 可選：產出 speedscope 格式的 profile 檔，用於深度分析。

**注意事項**：
- `TIMESTAMP_EXT` 已在 2016 年被 Chrome 移除，只能用 elapsed time query。
- 非 draw call 指令的 GPU time 通常回報為 0（已知限制）。
- 在 mobile 或某些環境下此 extension 不可用，需 graceful fallback。

**預期效果**：將效能分析從「猜測」提升為「量測」，能出具「此遊戲在 X 場景 GPU 耗時 16ms，瓶頸在第 N 個 draw call」的精確報告。

**參考資料**：
- Figma/webgl-profiler（EXT_disjoint_timer_query + speedscope 整合）：https://github.com/figma/webgl-profiler
- MDN — EXT_disjoint_timer_query：https://developer.mozilla.org/en-US/docs/Web/API/EXT_disjoint_timer_query
- Wonderland Engine — How We Profile WebXR/WebGL Apps：https://wonderlandengine.com/news/profiling-webxr-applications/

---

## 建議 5：量化 Screenshot Observer Effect 並加入自適應截圖策略

**現況問題**：`page.screenshot()` 會強制觸發 GPU `readPixels`，造成 GPU pipeline stall（CPU 等待所有 GPU 命令 flush）。在遊戲已處於高 GPU 壓力時，這個操作本身可能造成 frame drop 甚至觸發 context loss。目前完全未量測此 observer effect。

**建議做法**：
1. **量化**：在每次截圖前後記錄 `performance.now()` 差值，作為 `readPixels` 延遲的 proxy。延遲越長代表 GPU 壓力越大——這本身就是有價值的指標。
2. **自適應頻率**：若 screenshot 延遲 > 閾值（如 50ms），自動降低截圖頻率（從 1s 降到 3s），減少對被測遊戲的擾動。
3. **偵測 `preserveDrawingBuffer`**：注入腳本檢查 canvas context 建立時的 attributes（`gl.getContextAttributes().preserveDrawingBuffer`）。若為 false，`toDataURL`/screenshot 可能拿到空白——記錄此風險。
4. **替代方案**：在 GPU 壓力極高時改用 CDP `Page.captureScreenshot` 的 `fromSurface: true` 模式，它從合成器取圖而非從 WebGL context。

**預期效果**：避免觀測工具本身成為效能問題的來源；同時將 screenshot 延遲轉化為 GPU 壓力指標。

**參考資料**：
- Playwright PR #32009（canvas screenshot + preserveDrawingBuffer 問題討論）：https://github.com/microsoft/playwright/pull/32009
- Playwright Issue #23964（WebGL canvas 在 trace 中的限制）：https://github.com/microsoft/playwright/issues/23964
- Playwright Issue #17904（WebGL2 screenshot 在某些環境空白）：https://github.com/microsoft/playwright/issues/17904

---

## 總結優先級

| # | 建議 | ROI | 實作難度 | 前置依賴 |
|---|------|-----|---------|---------|
| 1 | Context Loss 事件監聽 | 高 | 低 | 無 |
| 2 | VRAM 估算 tracker | 高 | 中 | 無 |
| 3 | Draw Call 計數器 | 中 | 中 | 無 |
| 4 | GPU Timer Query | 中 | 高 | Extension 可用性 |
| 5 | Screenshot Observer Effect | 中 | 低 | 無 |

建議 1 和 5 可立即實作（幾乎只需加幾行 `addInitScript`）；建議 2 和 3 適合合併為一個「WebGL Observability Layer」統一注入；建議 4 則視目標瀏覽器支援度決定是否納入。

所有建議都遵循「不修改遊戲原始碼」的黑箱原則——純粹是觀測層注入，等同 APM/RUM agent 的做法。
