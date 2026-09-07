# Accessibility Auditor 審查建議

**審查角色**：Accessibility Auditor（無障礙稽核專家）
**審查對象**：WebGL QA Agent 設計文件（DESIGN.md）
**日期**：2026-07-16

---

## 建議 1：HTML 報告產出應符合 WCAG 2.2 AA 語意化標準

**問題**：`reporter.py` 產出的 HTML timeline 報告目前未明確規範無障礙需求。若 QA 團隊中有使用螢幕閱讀器的工程師需閱讀報告，缺乏語意化標記（heading hierarchy、landmark regions）、截圖替代文字（alt text）及鍵盤導航支援將導致報告完全不可用。

**建議**：
- 報告 HTML 應包含正確的 heading 層級結構（h1 → h2 → h3）、ARIA landmark regions（`<nav>`、`<main>`、`<section>`）
- 所有截圖 `<img>` 必須帶有描述性 `alt` 屬性（可由 Vision LLM 分析結果自動生成）
- Timeline 互動元素須支援鍵盤操作（Tab 導航、Enter/Space 啟動）
- 採用類似 `axe-html-reporter` 的模式產出符合無障礙標準的報告結構
- 可整合 axe-core 對產出報告本身做自動掃描驗證

**參考資源**：
- axe-html-reporter（從 axe 結果產出無障礙 HTML 報告）：https://www.npmjs.com/package/axe-html-reporter
- axe-playwright-report（Playwright + axe-core 儀表板報告）：https://github.com/mr-anton-t/axe-playwright-report
- WCAG 2.2 完整規範：https://www.w3.org/TR/WCAG22/

---

## 建議 2：新增光敏性癲癇風險偵測模組（WCAG 2.3.1）

**問題**：WebGL 遊戲常包含高速閃爍動畫（爆炸特效、場景切換、閃光提示），可能對光敏性癲癇患者造成癲癇發作風險。目前 `detector.py` 偵測崩潰級異常但未涵蓋此類無障礙安全議題。

**建議**：
- 在 `detector.py` 或新增 `a11y_detector.py` 中加入閃爍頻率分析：擷取連續幀，計算亮度變化（ΔB = |Bt - Bt-1|），偵測每秒超過 3 次閃爍的區段
- 參考 WCAG 2.3.1 標準：任一秒內不超過 3 次一般閃爍或紅色閃爍，或閃爍區域不超過螢幕 341×256 像素區塊的 25%
- 可整合 EA 開源的 IRIS 光敏性分析引擎，或參考 EPI-LENS 的即時分析演算法
- 將偵測結果納入 QA 報告，標記嚴重度為 Critical（可能導致身體傷害）

**參考資源**：
- WCAG 2.3.1 Understanding（三次閃爍或低於閾值）：https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold
- EA IRIS 光敏性癲癇分析工具（開源）：https://github.com/electronicarts/IRIS
- EPI-LENS 即時閃爍分析瀏覽器工具：https://github.com/Pi-0r-Tau/EPI-LENS
- PEAT（Photosensitive Epilepsy Analysis Tool）：https://trace.umd.edu/peat/

---

## 建議 3：為 WebGL Canvas 遊戲建立無障礙偵測能力（Shadow DOM 可存取性）

**問題**：WebGL canvas 對輔助技術是完全不透明的黑箱 —— 螢幕閱讀器無法讀取 canvas 內容、鍵盤使用者無法操作 canvas 內元素。目前 agent 能偵測遊戲「壞了」，但無法偵測遊戲「對身障使用者不可用」。

**建議**：
- 新增偵測維度：檢查受測遊戲是否提供 shadow DOM / ARIA 代理層（DOM proxy layer）來暴露 canvas 內容至無障礙樹
- Vision LLM 可辨識畫面上是否有純視覺（無文字標籤）的互動元素，標記為潛在無障礙障礙
- 檢測遊戲是否回應鍵盤事件（Tab/Enter/Arrow keys）—— 若所有互動僅限滑鼠/觸控，標記為 WCAG 2.1.1 Keyboard 違規風險
- 偵測色彩對比：Vision 分析可標記僅以顏色區分資訊的 UI 元素（違反 WCAG 1.4.1 Use of Color）

**參考資源**：
- Quorum Language — Accessible WebGL/Canvas（Shadow DOM 方法）：https://quorumlanguage.com/tutorials/accessibility/accessibleGraphicsWebGL.html
- Accessible Interactive Data Visualization（Canvas/WebGL DOM proxy 架構）：https://www.interactive-data-visualization.com/accessible-interactive-data-visualization/
- Autify Canvas/WebGL Testing（AI 視覺辨識測試方法）：https://autify.com/solutions/canvas-and-webgl-testing

---

## 建議 4：Vision LLM 增加色彩無障礙分析 prompt

**問題**：Vision LLM 目前用於讀取畫面數值與辨識互動元素，但未針對色彩無障礙進行分析。色盲使用者（約 8% 男性）可能無法區分僅以色相區分的遊戲元素（如紅/綠魚群、狀態指示燈）。

**建議**：
- 在 `prompts.py` 中新增無障礙分析 prompt 模板，要求 Vision LLM 辨識：
  - 是否有元素僅靠顏色傳達資訊（無形狀/文字/紋理冗餘）
  - 文字與背景的對比度是否明顯不足（WCAG 1.4.3 要求 4.5:1）
  - 動畫是否持續閃爍或快速循環
- 此分析可作為 `oracle.py` 的延伸 invariant：`{id: color_only_info, when: any_screen, kind: a11y_check, severity: medium}`
- 搭配 `perceiver.py` 的像素分析能力，可計算實際色彩對比度數值

**參考資源**：
- WCAG 2.2 axe-core + Playwright 測試指南（含色彩對比自動偵測）：https://www.goqa.ai/blog/wcag-2-2-audits-with-axe-core
- a11y-oracle（CDP 無障礙樹攔截 + 焦點指示器驗證）：https://github.com/a11y-oracle/a11y-oracle
- WCAG 1.4.1 Use of Color + 1.4.3 Contrast Minimum：https://www.w3.org/TR/WCAG22/#use-of-color

---

## 建議 5：CLI 腳本輸出應對螢幕閱讀器友善

**問題**：`scripts/qa_interactive.py` 與 `start_session.py` 的終端輸出若使用 ANSI 動畫（spinner、進度條、彩色文字），對使用螢幕閱讀器的開發者會造成困擾 —— 螢幕閱讀器會逐字讀出 escape sequence 或重複朗讀不斷更新的行。

**建議**：
- 偵測環境變數 `NO_COLOR`（https://no-color.org/）或終端是否為 TTY，非 TTY 時自動停用動畫與色彩
- 進度指示改用靜態文字行（如 `[3/10] Capturing screenshot...`）而非原地覆寫的 spinner
- 錯誤訊息格式化為結構清晰的文字：`[ERROR] <模組>: <描述>`，避免依賴顏色區分嚴重度
- 報告完成後輸出純文字摘要（不僅開啟 HTML），讓螢幕閱讀器使用者直接在終端取得結果

**參考資源**：
- NO_COLOR 標準（停用終端色彩的環境變數慣例）：https://no-color.org/
- Speakable（預測螢幕閱讀器如何詮釋輸出，含 CLI 整合）：https://getspeakable.dev/
- WCAG-toolkit CLI 範例（結構化終端輸出）：https://github.com/dar-kow/sdet-wcag-toolkit

---

## 總結

本專案作為一個「偵測遊戲問題」的 QA 工具，有兩個無障礙維度需要關注：

1. **工具本身的無障礙性**（報告、CLI）：確保身障 QA 工程師能使用此工具
2. **偵測受測遊戲的無障礙問題**（閃爍、鍵盤支援、色彩對比）：擴展 agent 偵測能力覆蓋 WCAG 相關議題

其中「光敏性癲癇風險偵測」（建議 2）優先級最高——這是唯一可能導致使用者身體傷害的無障礙問題，且有成熟的開源工具（EA IRIS）可直接整合。
