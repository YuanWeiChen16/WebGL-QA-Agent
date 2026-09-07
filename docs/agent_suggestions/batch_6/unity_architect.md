# Unity Architect 對 webgl-qa-agent 整體架構的建議報告

> 日期：2026-07-16
> 審查角色：Unity Architect（專精 Unity 模組化設計、ScriptableObjects、WebGL Build）
> 審查面向：Unity WebGL 遊戲的特殊挑戰
> 批次：Batch 6 — 遊戲/前端組

---

## 建議 1：Unity WebGL Build 的特殊載入行為

**提問**：Unity WebGL 遊戲有獨特的載入模式：先顯示 Unity loading bar → 下載 .data/.wasm → 初始化 → 才顯示遊戲。目前的框架如何判斷「遊戲已完全載入」而非「還在 loading」？

**優化建議**：
加入 Unity-specific 載入偵測：
- 偵測 Unity loading bar DOM 元素（`#unity-progress-bar-full`）消失
- 或監聽 Unity 的 `unityInstance.Module.onRuntimeInitialized` callback（如果可注入）
- 或用 SSIM + 穩定性判斷：連續 3 秒畫面不同（動畫開始）= 遊戲已載入
- 設定 loading timeout：> 60 秒未完成 = loading failure anomaly

**來源**：
- Unity WebGL Loading — official docs https://docs.unity3d.com/Manual/webgl-building.html
- Unity WebGL template customization https://docs.unity3d.com/Manual/webgl-templates.html

**優先級**：高

**預期效果**：避免在遊戲仍在載入時就開始操作（導致全部 action 無效）。

---

## 建議 2：Unity WebGL 記憶體限制未處理

**提問**：Unity WebGL 使用 WASM linear memory，有硬上限（通常 2GB）。超過時直接 crash 無 graceful error。你的 JS heap 監控能看到 WASM memory 嗎？

**優化建議**：
監控 WASM memory：
```javascript
// Unity WebGL exposes WASM memory via Module.HEAPU8
const wasmMemory = Module.HEAPU8.byteLength; // bytes
window.__wasm_memory_mb = wasmMemory / 1024 / 1024;
```
- 如果能注入（黑箱限制）：透過 CDP evaluate 嘗試讀取 `Module.HEAPU8`
- 如果不能注入：監控 `Performance.memory.totalJSHeapSize`（間接指標）
- 接近 2GB 時預警（> 1.5GB = critical warning）

**來源**：
- Unity WebGL memory management https://docs.unity3d.com/Manual/webgl-memory.html
- WebAssembly memory limits — browser implementations https://webassembly.org/docs/web/

**優先級**：中

**預期效果**：在 WASM OOM crash 前預警，避免長 session 最後幾分鐘才 crash 但原因不明。

---

## 建議 3：Unity 場景切換的黑屏期處理

**提問**：Unity 場景切換（SceneManager.LoadScene）通常有 1-5 秒黑屏。目前的 blank screen detection 會把這當作 bug 嗎？

**優化建議**：
區分「正常場景切換黑屏」vs「異常黑屏」：
- 正常：黑屏 < 10 秒 + 之後恢復正常渲染
- 異常：黑屏 > 10 秒 + 無恢復跡象
- 在 knowledge 中記錄已知的 scene transition points 和預期 loading duration
- 如果在已知 transition 發生黑屏 → 正常，等待恢復
- 如果在非 transition 時發生黑屏 → anomaly

**來源**：
- Unity Scene Management — loading screens https://docs.unity3d.com/ScriptReference/SceneManagement.SceneManager.html
- Best practices for Unity WebGL loading https://blog.unity.com/engine-platform/webgl-build-optimization

**優先級**：高

**預期效果**：大幅降低 false positive（場景切換被誤報為 crash）。

---

## 建議 4：Unity WebGL Input 層的特殊性

**提問**：Unity WebGL 的 input handling 有特殊性：keyboard focus 必須在 canvas 上、mobile touch 需要特殊處理、某些瀏覽器的 pointer lock 行為不同。你的 Playwright click 能確保 input 真的送到 Unity 了嗎？

**優化建議**：
加入 input delivery verification：
- Click 前確保 canvas 有 focus：`await page.evaluate(() => document.querySelector('canvas').focus())`
- 使用 `dispatchEvent` 而非 Playwright 的高層 click（更接近真實 input）
- 驗證 input 生效：click 後檢查是否有 Unity 的 visual feedback（如 button highlight）
- 記錄 input rejection：如果 Unity 正在 loading/transition，input 會被 swallow

**來源**：
- Unity WebGL input handling https://docs.unity3d.com/Manual/webgl-input.html
- Playwright input dispatch vs native events https://playwright.dev/docs/input

**優先級**：中

**預期效果**：確保每次操作真的被遊戲接收，而非被 browser/Unity 層吞掉。
