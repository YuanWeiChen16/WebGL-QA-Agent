# 架構對比分析：WebGL QA Agent vs. 10 個替代方案

> 生成日期：2024-07  
> 對象：`webgl-qa-agent` — Python/Playwright/CDP 黑箱 WebGL 遊戲 QA 框架

---

## 本工具架構摘要

| 層 | 實作 | 核心能力 |
|---|---|---|
| **瀏覽器控制** | Playwright + `page.context.new_cdp_session()` | 3 層截圖 fallback、console/pageerror 攔截、滑鼠/鍵盤操作 |
| **效能剖析** | `PerfProfiler` — Performance.getMetrics、Tracing domain、Profiler domain、Runtime.evaluate rAF 注入 | FPS 量測（兩種方式）、CPU profile top-20、heap 成長偵測 |
| **網路分析** | `NetworkAnalyzer` — Network domain 事件、Profiler+CSS coverage | 資源分類/瀑布圖、JS/CSS 使用率覆蓋 |
| **知識庫** | YAML 靜態層 + runtime 學習層 | 跨 session 累積、遊戲特定座標/invariant |
| **核心限制** | 純黑箱 — 無遊戲源碼、無引擎 hook、無 GPU 指令層存取 | — |

---

## 逐一對比分析

### 1. Lighthouse CI

**它是什麼：** Google 的自動化網頁品質審計工具，輸出 Performance Score 及 Web Vitals（FCP、LCP、CLS、TBT、INP）。

**它比本工具強在哪：**
- **標準化評分體系** — Performance Score 0–100 是業界共通語言，便於跨專案比較與 CI 門檻設定
- **Web Vitals 語義** — FCP/LCP/CLS/INP 有明確定義與使用者體驗關聯，本工具僅有原始 metrics 數值
- **CI 整合成熟** — `lhci autorun` 一行搞定 GitHub Actions、budget assertion、歷史趨勢儲存
- **Accessibility/SEO/Best Practices** 附帶審計 — 本工具完全不觸碰這些維度
- **可重複的模擬環境** — 固定 CPU throttling 4x、模擬 3G，結果穩定可比

**本工具能做到它做不到的：**
- **持續性 session 內 FPS 追蹤** — Lighthouse 只跑一次性 page load 審計，無法在遊戲進行中連續量測 FPS 變化
- **互動式操作** — 本工具可在 FPS 量測期間同時做 click/drag/key 操作，測「操作中效能」
- **黑箱遊戲邏輯測試** — Lighthouse 不做功能正確性驗證
- **記憶體洩漏偵測（多點採樣）** — Lighthouse 只看單次 JSHeapUsedSize，本工具做 5 點趨勢判斷
- **WebGL 專屬情境** — Canvas 截圖 fallback、rAF-based FPS（Lighthouse 的 FPS 與 WebGL 幀率無直接對應）

**整合策略：**
- 用 Lighthouse CI 做「載入品質門檻」（LCP < 4s、CLS < 0.1），gate 在 CI pipeline 前端
- 通過後再觸發本工具做「遊戲中 runtime 效能 + 功能驗證」
- 將 Lighthouse 的 `performance.timing` 數據與本工具 NetworkAnalyzer 的瀑布圖互補對照
- 實作：`subprocess` 呼叫 `lhci collect --url=...` → 解析 JSON → 注入報告

---

### 2. WebPageTest

**它是什麼：** 開源的網頁載入效能測試平台，支援多地區節點、連線模擬、filmstrip 截圖比較。

**它比本工具強在哪：**
- **多地區真實節點** — 可從全球 30+ 地點測試，暴露 CDN/地理延遲問題
- **瀑布圖視覺化** — 成熟的 waterfall chart 與 connection view，比本工具的 JSON 列表直觀得多
- **Filmstrip/Visual Progress** — 每 100ms 截圖計算 Speed Index、Visually Complete
- **連線模擬精確** — 頻寬/延遲/封包遺失的 traffic shaping 在 OS 層實作，比 CDP 的 Network.emulateNetworkConditions 更真實
- **Repeat View** — 測快取後的第二次載入，本工具無此概念

**本工具能做到它做不到的：**
- **互動操作** — WebPageTest 本質是「載入即結束」，不做遊戲中操作
- **持續效能監控** — 本工具可在遊戲跑 5 分鐘時量 FPS，WebPageTest 跑到 onLoad 就停
- **功能正確性 + 異常偵測** — 凍結/黑屏/console error 追蹤
- **自動化遊戲流程** — WebPageTest 無法模擬玩家操作序列

**整合策略：**
- WebPageTest 負責「遊戲首頁載入品質 + CDN 效能基線」
- 本工具負責「進入遊戲後的 runtime 行為」
- 可透過 WebPageTest API（`/runtest`）自動觸發測試並拉回 waterfall JSON
- 將 WebPageTest 的 filmstrip 與本工具的截圖 timeline 在同一 HTML 報告中並列

---

### 3. Chrome UX Report (CrUX)

**它是什麼：** Google 收集的真實 Chrome 使用者體驗數據集，可透過 BigQuery 查 origin-level 的 Web Vitals 75th percentile。

**它比本工具強在哪：**
- **真實使用者數據（RUM）** — 反映玩家實際裝置/網路/地理分佈的真實體驗，非合成測試
- **75th percentile 語義** — 知道「75% 的真實使用者 LCP < Xms」，本工具只知道「你的測試機上 FPS = Y」
- **長期趨勢** — 按月/週追蹤，可看版本發佈對真實體驗的影響
- **裝置/連線/國家分段** — 可拆分 mobile/desktop、4G/3G 等 cohort

**本工具能做到它做不到的：**
- **WebGL 遊戲特有指標** — CrUX 沒有 FPS、draw call、heap growth 等遊戲指標
- **功能驗證** — CrUX 純粹是指標收集，無 pass/fail 判定
- **主動探索式測試** — CrUX 是被動收集，無法「觸發特定操作後看效能變化」
- **私有/未上線遊戲** — CrUX 需要足夠流量才有數據

**整合策略：**
- CrUX 做「上線後監控」——BigQuery 排程查詢，當 p75 LCP 惡化時自動觸發本工具跑深度診斷
- 本工具做「上線前/CI 驗證」——合成環境確保基線不退化
- 將 CrUX 的 formFactor 分段反映在本工具的 viewport/device_scale_factor 配置中

---

### 4. Playwright Built-in Tracing

**它是什麼：** Playwright 內建的 `tracing.start()` / `tracing.stop()`，產出 `trace.zip`，可在 trace.playwright.dev 開啟查看 timeline、network、screenshots、HAR。

**它比本工具強在哪：**
- **操作-截圖-時間軸一體化** — 每個 action 自動配對 before/after screenshot + network + console
- **Trace Viewer UI** — 互動式時間軸，可 step-by-step 回放操作序列
- **HAR 匯出** — 標準格式，可匯入其他工具分析
- **零額外 CDP 管理** — 不需手動建 CDP session，Playwright 內建管理

**本工具能做到它做不到的：**
- **CDP 層級細粒度** — Performance.getMetrics 的 FrameCount、LayoutCount、ScriptDuration 等 Playwright tracing 不直接暴露
- **CPU profile top functions** — Playwright tracing 不做 Profiler.start/stop 的函數級 self-time 分析
- **rAF FPS 量測** — 注入 JavaScript 的幀時間追蹤是本工具獨有
- **記憶體洩漏偵測** — 多點 heap 採樣 + 趨勢判斷
- **遊戲知識庫整合** — invariant 驗證、異常偵測

**整合策略：**
- **最適合直接整合** — 在 `GameBrowser.launch()` 加 `await context.tracing.start(screenshots=True, snapshots=True)`
- 每個 test session 結束時 `tracing.stop(path="runs/.../trace.zip")`
- HTML 報告中加入 trace.zip 下載連結 → 讓使用者在 Trace Viewer 中互動式回放
- 兩者完全互補：Playwright tracing 提供操作級回放，本工具提供效能/異常級分析

---

### 5. Puppeteer Performance Recipes

**它是什麼：** Puppeteer 社群累積的 CDP 效能腳本集（tracing、coverage、metrics、timeline 等）。

**它比本工具強在哪：**
- **社群成熟度** — 大量現成 snippet 可抄，edge case 處理經過千人踩坑
- **Node.js 生態** — 若團隊是 JS stack，Puppeteer 的 typing 與 ecosystem（lighthouse-ci、web-vitals 等）整合更自然
- **`page.metrics()` 語法糖** — 不需手動 `Performance.getMetrics` 再解析

**本工具能做到它做不到的：**
- **架構封裝** — 本工具已將 CDP 操作封裝為語義化方法（`measure_fps`、`get_memory_snapshot`），Puppeteer recipes 是散裝 snippet
- **遊戲 QA 流程** — observe/act/oracle 迴圈、知識庫、異常偵測、HTML 報告——Puppeteer recipes 不涵蓋
- **Python 整合** — 與 ML/Vision 生態（OpenCV、Anthropic SDK）同語言，無需跨 process 通訊
- **多層截圖 fallback** — 處理 WebGL font-blocking 場景的 3 段 fallback

**整合策略：**
- 更像「同類技術不同語言」而非互補工具
- 可參考 Puppeteer recipes 中的 edge case 處理（如 Tracing.dataCollected 的 chunked data、coverage 的 source map 反向映射）移植到本工具
- 若需 JS 端工具鏈：可用 Puppeteer 做輕量 CI smoke test，本工具做深度 session

---

### 6. GameBench

**它是什麼：** 商業遊戲效能 profiling 平台，支援手機/PC 遊戲的 FPS overlay、CPU/GPU 利用率、電池/溫度追蹤。

**它比本工具強在哪：**
- **GPU 利用率** — 直接讀取 GPU driver counter（Mali/Adreno/Apple GPU），本工具完全無法觸及 GPU 層
- **每幀 CPU/GPU 分拆** — 知道每幀卡在 CPU 還是 GPU bound
- **行動裝置真實 profiling** — 溫度/電量/記憶體壓力/thermal throttling，Web 層不可見
- **商業級報告** — 自動生成可交付客戶的 PDF 報告
- **多平台** — Android/iOS/PC 原生 app + WebGL in mobile browser

**本工具能做到它做不到的：**
- **自動化測試流程** — GameBench 需人工遊玩或外接自動化；本工具 observe/act/oracle 全自動
- **功能正確性驗證** — GameBench 只看效能，不判「遊戲邏輯對不對」
- **CI 整合** — GameBench 是 GUI 工具/cloud service，不易嵌入 CI pipeline
- **黑箱 Web 專屬** — 不需安裝 APK、不需 USB debug、不需 root
- **知識庫累積** — 跨 session 學習

**整合策略：**
- GameBench 用於「行動裝置真實效能基線」——特別是 GPU bound 判定
- 本工具用於「CI 自動化 + 功能驗證」
- 可透過 GameBench API 拉取 session metrics → 與本工具報告合併
- 本工具可加入 `navigator.deviceMemory` / `navigator.hardwareConcurrency` 查詢補充裝置資訊

---

### 7. Unity WebGL Profiler

**它是什麼：** Unity 引擎內建的 Profiler 連接 WebGL build，可看 draw call、shader timing、managed memory allocation 來源、Mono/IL2CPP GC。

**它比本工具強在哪：**
- **引擎級粒度** — 知道哪個 GameObject 的哪個 Component 花了多少 ms，哪個 shader pass 最貴
- **Draw call 細節** — 每個 draw call 的 vertex count、material、batch 狀態
- **記憶體歸因** — 知道是哪個 Texture2D / AudioClip / ScriptableObject 佔了多少 MB
- **GC Allocation** — 每幀哪一行 C# 產生了 GC alloc
- **Frame Debugger** — 逐步重建單幀的 render pipeline

**本工具能做到它做不到的：**
- **不需源碼/引擎存取** — Unity Profiler 需要 Development Build + Autoconnect Profiler，生產環境不可能開
- **跨引擎** — 本工具對 Unity/Cocos/Phaser/Three.js/自研引擎一視同仁
- **自動化 QA 流程** — Unity Profiler 是手動開發工具，無法串 CI
- **異常偵測** — 凍結/黑屏/console error 的自動判定
- **Vision + 知識庫** — 畫面語義理解，引擎 profiler 不做

**整合策略：**
- **開發階段**用 Unity Profiler 做精確 draw call/memory 歸因
- **CI/QA 階段**用本工具做自動化回歸 + 效能 gate
- 可讓 Unity build 注入一個輕量 JS bridge：`window.__UNITY_PROFILER_DATA = {...}`，本工具透過 `Runtime.evaluate` 讀取
- 或用 Unity 的 Custom Profiler Counters → 寫到 `console.log('[PERF]...')` → 本工具 console 攔截解析

---

### 8. Spector.js

**它是什麼：** 開源 WebGL API 攔截器，逐幀記錄所有 WebGL/WebGL2 呼叫，檢視 texture/shader/state。

**它比本工具強在哪：**
- **WebGL API call 層級可見性** — 看到每一個 `gl.bindTexture`、`gl.drawArrays`、`gl.uniformMatrix4fv`
- **逐幀狀態快照** — 某一幀的完整 GL state：bound buffers、active texture units、blend mode、depth test
- **Shader 原始碼檢視** — vertex/fragment shader GLSL 內容
- **Texture 內容檢視** — 每個 texture unit 綁定的圖片內容
- **Draw call 重播** — 可 step-through 單幀的 draw call 序列

**本工具能做到它做不到的：**
- **無需注入** — Spector.js 需要在頁面載入前注入 interception script 或用 browser extension；本工具純外部 CDP
- **效能量化** — Spector.js 主要看「API 呼叫正確性」而非「FPS / 記憶體 / CPU 時間」
- **自動化 + CI** — Spector.js 是互動式 debug 工具，非自動化 pipeline 工具
- **網路 + 資源分析** — Spector.js 不看 HTTP 層
- **異常偵測 + 功能驗證** — Spector.js 不做

**整合策略：**
- **最具互補性的 WebGL 專屬工具**
- 方案 A（自動注入）：在 `GameBrowser.launch()` 時透過 `page.add_init_script()` 注入 Spector.js UMD bundle → 用 `Runtime.evaluate` 呼叫 `spector.captureNextFrame()` → 拿回 JSON
- 方案 B（按需觸發）：當本工具偵測到 FPS 異常下降時，自動觸發 Spector capture 一幀做 root cause 分析
- 將 Spector 的 draw call count、state errors 加入報告的「WebGL Health」區塊

---

### 9. WebGL Inspector

**它是什麼：** 類似 Spector.js 的早期 WebGL debugging 工具，提供 draw call 分析、GL state 追蹤、resource 監控。

**它比本工具強在哪：**
- **Draw call timeline** — 視覺化單幀內每個 draw call 的時序排列
- **Resource 生命週期追蹤** — Buffer/Texture/Program 的 create/update/delete 全記錄
- **State 差異比較** — 兩個 draw call 間的 GL state diff
- **Redundant call 偵測** — 找出無效的重複 state 設定

**本工具能做到它做不到的：**
- 與 Spector.js 對比相似：無需注入、自動化、效能量化、網路分析、異常偵測
- WebGL Inspector 更老舊，不支援 WebGL2 / 部分現代 extension
- 本工具的 Python 生態整合更好

**整合策略：**
- **不建議整合** — Spector.js 是其精神續作且更完整
- 若有特殊需求（如 WebGL1-only legacy game），可做類似 Spector.js 的注入方案
- 優先選擇 Spector.js 做為 WebGL API 層的整合對象

---

### 10. PIX / RenderDoc

**它是什麼：** GPU 層級的圖形 debugger（PIX for Windows/Xbox、RenderDoc 跨平台），可做逐 draw call GPU timing、shader debugging、pixel history。

**它比本工具強在哪：**
- **GPU 硬體計時** — 每個 draw call 實際在 GPU 花了多少 ns
- **Shader Debugging** — 逐像素 step-through fragment shader
- **Pixel History** — 某像素被哪些 draw call 影響、最終值怎麼來的
- **GPU Memory 歸因** — 哪個 resource 佔多少 VRAM
- **Pipeline State** — 完整的 graphics pipeline 每個 stage 狀態
- **Mesh Viewer** — 視覺化頂點/索引資料

**本工具能做到它做不到的：**
- **Web 環境** — PIX/RenderDoc 無法直接 attach 到 Chrome 的 WebGL context（需特殊 build 或 ANGLE 橋接）
- **自動化** — 這些是互動式 IDE 級工具
- **CI 整合** — 無 headless/CLI 模式可嵌入 pipeline
- **功能/異常/知識庫** — 完全不同維度

**整合策略：**
- **幾乎無法直接整合**到 Web QA pipeline
- 間接路徑：Chrome 使用 ANGLE 做 WebGL → DirectX/Vulkan/Metal backend → 理論上可用 RenderDoc attach 到 Chrome GPU process（需 `--disable-gpu-sandbox` + `--gpu-startup-dialog`）
- 實際價值：當本工具偵測到「FPS 異常但 CPU profile 正常」（GPU bound），報告中建議「使用 RenderDoc 做 GPU 層 root cause 分析」
- 可在報告中自動產生 RenderDoc 的 attachment 指令

---

## 比較矩陣

| 維度 | 本工具 | Lighthouse CI | WebPageTest | CrUX | PW Tracing | Puppeteer | GameBench | Unity Profiler | Spector.js | WebGL Inspector | PIX/RenderDoc |
|------|--------|--------------|-------------|------|------------|-----------|-----------|----------------|------------|-----------------|---------------|
| **黑箱（無需源碼）** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ⚠️¹ | ⚠️¹ | ❌ |
| **CI 自動化** | ✅ | ✅ | ✅ | ⚠️² | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **WebGL FPS 量測** | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️³ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **互動操作中效能** | ✅ | ❌ | ❌ | ❌ | ✅ | ✅ | ⚠️⁴ | ✅ | ❌ | ❌ | ❌ |
| **記憶體洩漏偵測** | ✅ | ❌ | ❌ | ❌ | ❌ | ⚠️³ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **CPU Profile（函數級）** | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ |
| **GPU 層級分析** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ⚠️⁵ | ⚠️⁵ | ✅ |
| **Draw Call / GL State** | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| **Web Vitals 標準分數** | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **真實使用者數據** | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **多地區/多裝置** | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **異常自動偵測** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **功能正確性驗證** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **知識庫 + 跨session學習** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Vision LLM 整合** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **網路資源分析** | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **JS/CSS Coverage** | ✅ | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **操作回放 UI** | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **開源/免費** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ⚠️⁶ | ✅ | ✅ | ⚠️⁷ |
| **整合難度** | — | 低 | 中 | 低 | 極低 | 中 | 高 | 高 | 中 | 低 | 極高 |
| **整合優先序** | — | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ |

**註解：**
1. ⚠️¹ — 需注入 script，但不需遊戲源碼
2. ⚠️² — CrUX 是被動收集，需有流量
3. ⚠️³ — Puppeteer 可以做，但需自己寫，無封裝
4. ⚠️⁴ — GameBench 需外接自動化或人工操作
5. ⚠️⁵ — 看 API call 但無 GPU timing
6. ⚠️⁶ — Unity Profiler 需 Pro 以上 license 完整功能
7. ⚠️⁷ — RenderDoc 開源免費，PIX 免費但限 Windows/Xbox

---

## 結論：整合優先序建議

| 優先級 | 工具 | 理由 |
|--------|------|------|
| **P0（立即整合）** | Playwright Tracing | 幾乎零成本，加兩行 code 即得操作回放 + HAR |
| **P0（立即整合）** | Spector.js | 填補 WebGL API 層盲區，可自動注入 |
| **P1（CI 階段）** | Lighthouse CI | 標準化載入品質門檻 |
| **P2（增值）** | CrUX | 上線後真實用戶監控 |
| **P2（增值）** | WebPageTest | 多地區載入基線 |
| **P3（特定場景）** | Unity Profiler bridge | 若受測遊戲為 Unity 且可出 dev build |
| **P3（特定場景）** | GameBench | 行動裝置 GPU bound 判定 |
| **Skip** | Puppeteer recipes | 同層級技術，Python 已覆蓋 |
| **Skip** | WebGL Inspector | Spector.js 更完整 |
| **Reference only** | PIX/RenderDoc | Web 環境幾乎無法直接使用 |
