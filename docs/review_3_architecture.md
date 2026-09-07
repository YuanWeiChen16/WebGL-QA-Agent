# Review：架構對比分析 (debate_3_architecture.md)

> 審閱日期：2025-07  
> 審閱範圍：10 個替代方案的描述是否準確反映 2024–2025 年實際能力  
> 判定標準：✅ 準確 / ⚠️ 部分過時 / ❌ 明顯錯誤  
> 注意：本次審閱基於 AI 訓練知識（截至 2025 年初），未能執行即時網路搜尋驗證。建議對標記 ⚠️ 的項目進行人工二次確認。

---

## 逐項判定

### 1. Lighthouse CI — ⚠️ 部分過時

**原文問題：**
- 原文描述 Lighthouse「只跑一次性 page load 審計，無法在遊戲進行中連續量測 FPS 變化」。

**2024–2025 實際狀態：**
- Lighthouse 自 v10（2022 年末）起正式支援 **User Flows**，包含三種模式：
  - **Navigation**（傳統 page load）
  - **Timespan**（測量一段時間內的效能，包含互動期間）
  - **Snapshot**（某一時刻的靜態審計）
- Timespan 模式允許在使用者互動期間收集 CLS、INP、Long Tasks 等指標，**已非純 page-load 工具**。
- Lighthouse 12.x（2024）持續強化 User Flow，INP 正式取代 FID 成為 Core Web Vital。
- 但 Timespan 模式仍**不直接量測 WebGL canvas FPS**，此點原文結論仍大致正確。

**判定理由：** 原文將 Lighthouse 完全定性為「一次性 page load 審計」已不完整。Timespan 模式補足了互動期間效能的能力，但對 WebGL FPS 的無力描述仍然準確。

---

### 2. WebPageTest — ⚠️ 部分過時

**原文問題：**
- 原文描述 WebPageTest 本質是「載入即結束」，不做互動操作。

**2024–2025 實際狀態：**
- WebPageTest 自 2023 年起強化了 **Custom Scripting** 功能，支援 `navigate`、`click`、`type`、`waitFor` 等互動指令。
- 2024 年 Catchpoint 收購 WebPageTest 後持續維護，增加了 **Custom Metrics** 與 **Custom Script** 進階功能。
- 可透過腳本執行多步互動測試（multi-step），不再僅限於 page load。
- 不過，其互動腳本功能的靈活度仍遠不及 Playwright/Puppeteer 的完整自動化能力。
- WebPageTest 的核心強項（多地區、filmstrip、waterfall）描述仍然準確。

**判定理由：** 「載入即結束」的描述已不完全準確，WebPageTest 現在支援有限的互動腳本。但其在持續遊戲 session 監控方面的限制描述仍然成立。

---

### 3. Chrome UX Report (CrUX) — ✅ 準確

**2024–2025 實際狀態：**
- CrUX 持續由 Google 維護，2024 年 3 月 INP 正式取代 FID 成為 Core Web Vital。
- 仍為被動收集 RUM 數據，無法主動觸發測試。
- 仍需足夠流量才有數據（origin 需有足夠 Chrome 使用者造訪）。
- BigQuery 查詢、API 存取、PageSpeed Insights 整合均持續可用。
- 無法收集 WebGL FPS、draw call 等遊戲特有指標。

**判定理由：** 原文描述完全準確，CrUX 的定位和限制在 2024–2025 未有本質變化。唯一可補充的是 INP 取代 FID，但不影響對比結論。

---

### 4. Playwright Built-in Tracing — ⚠️ 部分過時（低估了能力）

**原文問題：**
- 原文描述 Playwright tracing「不直接暴露 Performance.getMetrics 的 FrameCount、LayoutCount」。

**2024–2025 實際狀態：**
- Playwright 1.40+（2024）持續增強 tracing 功能：
  - Trace Viewer UI 持續改進，支援更豐富的 timeline 視圖
  - 新增 **附件（attachments）** 功能，可在 trace 中嵌入自定義數據
  - `page.context.newCDPSession()` 仍然完全可用，可在 tracing 同時使用 CDP
- Playwright 的 `tracing` 本身確實不直接暴露 CDP Performance domain 的細粒度指標，此點正確。
- 但 Playwright 現在提供 `page.metrics()`（靈感來自 Puppeteer）等便利 API，部分簡化了效能數據存取。
- 整合策略描述（加兩行 code 即可）仍然有效且是最佳實踐。

**判定理由：** 核心對比邏輯正確，但低估了 Playwright 2024 年的部分增強。tracing 不做 CPU profile 和 rAF FPS 的結論仍然成立。

---

### 5. Puppeteer Performance Recipes — ✅ 準確

**2024–2025 實際狀態：**
- Puppeteer 仍由 Google Chrome 團隊維護，2024 年持續發版（v21–v23）。
- `page.metrics()` 語法糖仍然可用。
- Puppeteer 社群 recipes 仍然活躍，GitHub 上有大量效能相關 snippet。
- Puppeteer 與 Playwright 的定位差異（Node.js vs 多語言、Chrome-only vs 多瀏覽器）描述準確。
- 原文的「同類技術不同語言」定位恰當。

**判定理由：** 描述準確反映現狀。Puppeteer 持續維護中，功能定位未變。

---

### 6. GameBench — ⚠️ 部分過時

**原文問題：**
- 原文描述 GameBench 為「商業遊戲效能 profiling 平台」，「GUI 工具/cloud service，不易嵌入 CI pipeline」。

**2024–2025 實際狀態：**
- GameBench 在 2024 年仍為商業產品，提供 SDK 和 cloud dashboard。
- GameBench 近年強化了 **API 存取** 和 **自動化整合**能力，提供 REST API 拉取 session 數據。
- GameBench 2024 版本增加了部分 CI 友善功能（API 觸發測試、webhook 通知）。
- 但核心定位仍為行動裝置（Android/iOS）效能 profiling，Web/WebGL 支援有限。
- 「不易嵌入 CI」的描述在 2024 年已稍顯過時，但仍非原生 CI 工具。
- GPU 利用率、溫度/電量追蹤等描述仍然準確。

**判定理由：** 核心能力描述準確，但 CI 整合能力的描述略顯過時。GameBench 已有更多自動化選項。

---

### 7. Unity WebGL Profiler — ⚠️ 部分過時

**原文問題：**
- 原文提及「Unity Profiler 需 Pro 以上 license 完整功能」。
- 描述基於 Unity 2022/2023 LTS 時期。

**2024–2025 實際狀態：**
- **Unity 6**（2024 年底正式發布）對 Profiler 進行了重大更新：
  - 新的 **Memory Profiler** 模組整合進主 Profiler 窗口
  - **WebGL profiling** 改善——支援更好的 managed memory 追蹤
  - Unity 6 的授權模式變更：Personal 版本收入門檻提高，Profiler 基礎功能更開放
- Unity 6 WebGL build 支援 **Profiler connection via WebSocket**，不再需要 Autoconnect 那麼嚴格的設定。
- 但核心限制（需要 Development Build、生產環境不可能開）仍然成立。
- 原文提到的 JS bridge 整合策略（`window.__UNITY_PROFILER_DATA`）仍然是可行方案。
- 註解「需 Pro 以上 license 完整功能」在 Unity 6 新授權下需要更新。

**判定理由：** 核心對比邏輯正確，但 Unity 6 的 Profiler 改進和授權變更使部分細節過時。

---

### 8. Spector.js — ⚠️ 部分過時（維護狀態存疑）

**原文問題：**
- 原文將 Spector.js 列為 P0 整合優先，描述其為活躍的 WebGL API 攔截工具。

**2024–2025 實際狀態：**
- Spector.js GitHub（BabylonJS/Spector.js）最近一次重大更新約在 **2022–2023 年**，之後提交頻率顯著下降。
- 截至 2025 年，Spector.js 仍然可用但**維護活躍度明顯降低**，主要是 bug fix 而非新功能。
- **WebGPU 時代來臨**：Spector.js 僅支援 WebGL/WebGL2，不支援 WebGPU。對於未來遷移到 WebGPU 的專案無法覆蓋。
- Chrome Extension 仍可在 Chrome Web Store 安裝使用。
- BabylonJS 團隊的重心已轉向 Babylon.js 引擎本身及 WebGPU 支援。
- 功能描述（API call 攔截、texture 檢視、shader 檢視、draw call 重播）仍然準確。
- 作為 UMD bundle 注入的整合方案仍然技術可行。

**判定理由：** 功能描述準確，但「P0 立即整合」的建議需考慮維護停滯風險。工具仍可用但未來可能缺乏 bug fix 和新 WebGL extension 支援。

---

### 9. WebGL Inspector — ✅ 準確（已確認停止維護）

**2024–2025 實際狀態：**
- WebGL Inspector（benvanik/WebGL-Inspector）**已停止維護多年**，最後實質更新在 2015–2016 年左右。
- GitHub repo 仍然存在但無活躍開發。
- 不支援 WebGL2，更不支援任何現代 extension。
- Chrome 擴充功能可能已無法在 Manifest V3 下正常運作。
- 原文描述「更老舊，不支援 WebGL2」和「不建議整合」的結論完全正確。

**判定理由：** 原文對 WebGL Inspector 的判斷（已過時、不建議整合、Spector.js 為其精神續作）完全準確。

---

### 10. PIX / RenderDoc — ⚠️ 部分過時

**原文問題：**
- 原文描述 RenderDoc「無法直接 attach 到 Chrome 的 WebGL context」，需特殊 build。
- 描述「無 headless/CLI 模式可嵌入 pipeline」。

**2024–2025 實際狀態：**
- **RenderDoc** 持續活躍開發（2024–2025 多次發版），是 GPU debugging 的業界標準開源工具。
- RenderDoc 對 Chrome/WebGL 的支援在 2024 年有改善：
  - 透過 `--use-angle=vulkan` 啟動 Chrome，RenderDoc 可以 capture Vulkan backend 的 calls
  - 仍需 `--disable-gpu-sandbox` 等特殊旗標
  - 實務上仍然**非常不便**，不適合自動化
- RenderDoc **有 CLI（renderdoccmd）**，可做 headless capture 和 replay，技術上可嵌入 pipeline（但對 WebGL 場景仍極為困難）。
- **PIX** 2024 版持續更新，支援 DirectX 12 和 Xbox，免費使用。
- 原文「幾乎無法直接整合到 Web QA pipeline」的結論仍然正確。
- 原文描述的「GPU bound 時建議使用 RenderDoc」策略合理。

**判定理由：** 核心結論正確，但「無 CLI 模式」的描述不完全準確——RenderDoc 有 renderdoccmd。不過對 WebGL 場景的實用性限制描述仍然成立。

---

## 比較矩陣審閱

| 矩陣項目 | 判定 | 備註 |
|----------|------|------|
| Lighthouse CI 行「互動操作中效能 = ❌」 | ⚠️ | Timespan 模式已可做互動期間量測，應為 ⚠️ |
| WebPageTest 行「互動操作中效能 = ❌」 | ⚠️ | Custom Script 已支援有限互動 |
| Playwright Tracing 行「記憶體洩漏偵測 = ❌」 | ✅ | 仍然正確，tracing 不做 heap 分析 |
| GameBench 行「CI 自動化 = ❌」 | ⚠️ | 2024 年已有 API/自動化選項，但仍非原生 CI 工具 |
| 註解 ⚠️⁶「Unity Profiler 需 Pro 以上 license」 | ⚠️ | Unity 6 授權模式已變更 |
| 註解 ⚠️⁷「RenderDoc 開源免費，PIX 免費但限 Windows/Xbox」 | ✅ | 仍然準確 |

---

## 維護狀態總結

| 工具 | 2024–2025 維護狀態 |
|------|-------------------|
| Lighthouse | 🟢 活躍（Google 主導，持續更新） |
| WebPageTest | 🟢 活躍（Catchpoint 收購後持續維護） |
| CrUX | 🟢 活躍（Google 持續維護） |
| Playwright | 🟢 活躍（Microsoft 主導，頻繁發版） |
| Puppeteer | 🟢 活躍（Google Chrome 團隊維護） |
| GameBench | 🟡 商業運營中（產品持續但非開源社群驅動） |
| Unity Profiler | 🟢 活躍（Unity 6 重大更新） |
| Spector.js | 🟡 維護停滯（可用但新開發極少） |
| WebGL Inspector | 🔴 已停止維護（2015–2016 後無實質更新） |
| RenderDoc | 🟢 活躍（持續發版，GPU debugging 標準工具） |
| PIX | 🟢 活躍（Microsoft 持續更新） |

---

## 整體評估

原文 debate_3_architecture.md 的架構對比分析**整體品質良好**，核心對比邏輯和整合策略建議在 2024–2025 年仍然成立。主要需要更新的點：

1. **Lighthouse User Flows（Timespan 模式）**——原文未提及此重要功能，低估了 Lighthouse 在互動場景的能力
2. **WebPageTest Custom Scripts**——互動能力描述需更新
3. **Spector.js 維護風險**——作為 P0 整合建議，需要註明維護停滯的風險因子
4. **Unity 6 變更**——Profiler 功能和授權模式均有更新
5. **RenderDoc CLI 存在**——renderdoccmd 可做自動化 capture（雖對 WebGL 仍不實用）

**建議行動：**
- 在 Lighthouse 章節補充 Timespan 模式說明，並更新比較矩陣
- 在 Spector.js 章節加入維護狀態警告，考慮是否仍為 P0
- 考慮新增 WebGPU 遷移趨勢的前瞻性說明
- 更新 Unity Profiler 相關資訊至 Unity 6 版本

---

*審閱完成。因無法執行即時網路搜尋，上述判定基於 AI 訓練知識（截至 2025 年初）。標記 ⚠️ 的項目建議進一步以即時搜尋驗證。*
