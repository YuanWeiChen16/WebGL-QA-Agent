# Frontend Developer 架構審查建議 — Batch 6

> 審查角色：Frontend Developer（Canvas 渲染、瀏覽器相容性、Viewport 處理）
> 審查日期：2026-07-16

---

## 建議 1：截圖時機應與 requestAnimationFrame 同步

**問題**：目前 `browser.py` 的 `screenshot()` 直接呼叫 Playwright 的 `page.screenshot()`，無任何幀同步機制。WebGL 遊戲以 60fps 連續動畫運行（魚群游動、粒子特效），截圖可能擷取到 GPU 正在繪製的中間狀態（tearing），導致 SSIM 比對與 Vision 分析產生不穩定結果。

**建議**：在截圖前插入 rAF 同步，確保擷取完整渲染幀：

```python
# browser.py - screenshot() 改善
async def screenshot(self, path: Optional[str] = None) -> str:
    # 等待下一個 animation frame 完成，確保 GPU 已提交完整幀
    await self._page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    # 雙重 rAF 確保前一幀的 compositing 已完成
    screenshot_bytes = await self._page.screenshot(...)
```

此外，Playwright 原生支援 `animations: 'disabled'` 選項可暫停 CSS 動畫，但對 WebGL/JS 驅動的動畫無效。對於需要穩定截圖的場景（SSIM 參考圖、oracle 讀數），可考慮暫時覆寫 `requestAnimationFrame` 讓遊戲暫停一幀：

```python
await self._page.evaluate("window.__origRAF = window.requestAnimationFrame; window.requestAnimationFrame = () => 0")
# 截圖...
await self._page.evaluate("window.requestAnimationFrame = window.__origRAF")
```

**嚴重度**：Medium — 影響 perceiver SSIM 穩定度與 freeze detection 誤判率

**參考資料**：
- https://github.com/microsoft/playwright/blob/303901d7/packages/playwright-core/src/server/screenshotter.ts （Playwright 截圖內部實作，含 CSS animation disable 邏輯）
- https://github.com/currents-dev/playwright-best-practices-skill/blob/HEAD/testing-patterns/canvas-webgl.md （Canvas/WebGL 測試最佳實踐：暫停動畫、等待渲染完成）
- https://github.com/microsoft/playwright/issues/18934 （Playwright screenshot timing 與動畫觸發問題）

---

## 建議 2：HiDPI 座標空間不匹配需明確正規化

**問題**：目前 `browser.py` 硬編碼 `device_scale_factor=1`，暫時規避了 HiDPI 問題。但這意味著：
1. 在真實 HiDPI 設備上截圖解析度被人為降低，Vision LLM 看到的圖像品質較差
2. 若未來移除此限制或在不同環境運行，Vision 分析 2x 截圖回傳的座標將與 Playwright CSS-pixel 點擊座標不匹配
3. Playwright 的 `scale: 'device'`（預設值）會產生實際設備像素的截圖，但 `page.mouse.click(x, y)` 始終以 CSS 像素為單位

**建議**：
1. 在 `config/default.yaml` 中明確宣告座標系統為 CSS pixels，並記錄此設計決策
2. 截圖時使用 `scale: 'css'` 確保截圖像素與點擊座標 1:1 對應：

```python
screenshot_bytes = await self._page.screenshot(type="png", scale="css")
```

3. 若需要高品質截圖供 Vision 分析，則保留 `scale: 'device'` 但在座標轉換時除以 `device_scale_factor`：

```python
async def get_scale_factor(self) -> float:
    return await self._page.evaluate("window.devicePixelRatio")

def device_to_css_coords(self, x: int, y: int, dpr: float) -> tuple[float, float]:
    return x / dpr, y / dpr
```

4. 在 Vision prompt 中明確告知圖像的 DPI 與座標系統，避免 LLM 回傳錯誤像素座標

**嚴重度**：High — `device_scale_factor=1` 是隱性依賴，未文件化；跨環境部署會靜默產生座標錯位

**參考資料**：
- https://github.com/microsoft/playwright/pull/39233 （Playwright 修正 css-scale 截圖在高 DPI 環境的尺寸計算）
- https://github.com/microsoft/playwright/issues/17501 （deviceScaleFactor 與截圖品質的關係討論）
- https://github.com/microsoft/playwright/issues/6188 （Chromium deviceScaleFactor > 1 時截圖裁切 bug）

---

## 建議 3：WebGL context loss 偵測應區分「正常恢復」與「遊戲崩潰」

**問題**：`detector.py` 目前將 `CONTEXT_LOST_WEBGL` console message 視為崩潰級異常。但根據 WebGL 規範，context loss 是瀏覽器正常行為（GPU 資源壓力、Tab 背景化、驅動重設），遊戲**應該**正確處理 `webglcontextlost` + `webglcontextrestored` 事件。偵測器需要區分：
- **遊戲正確恢復**（context lost → 3 秒內 restored → 畫面正常）= 正常行為
- **遊戲未能恢復**（context lost → 超時無 restored、或恢復後畫面異常）= 真正的 bug

**建議**：注入事件監聽器追蹤 context 生命週期：

```python
# browser.py - launch() 後注入
await self._page.evaluate("""
() => {
    window.__webgl_context_events = [];
    const canvas = document.querySelector('canvas');
    if (!canvas) return;
    canvas.addEventListener('webglcontextlost', (e) => {
        window.__webgl_context_events.push({
            type: 'lost', time: Date.now(), prevented: e.defaultPrevented
        });
    });
    canvas.addEventListener('webglcontextrestored', (e) => {
        window.__webgl_context_events.push({
            type: 'restored', time: Date.now()
        });
    });
}
""")
```

偵測邏輯改為：
1. 偵測到 context lost → 開始計時，**不立即報告異常**
2. 若 `context_recovery_timeout`（建議 5 秒，可設定）內收到 `webglcontextrestored` → 記錄為 info 事件
3. 若超時未恢復，或恢復後 pixel_diff 顯示畫面凍結/黑屏 → 報告為 anomaly
4. 額外檢查：`gl.isContextLost()` 可作為確認信號

**嚴重度**：High — 誤報率直接影響 QA 報告可信度；測試長時間運行時 context loss 必然發生

**參考資料**：
- https://wikis.khronos.org/webgl/HandlingContextLost （Khronos 官方 Context Loss 處理指南，含 simulator）
- https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event （MDN webglcontextlost 事件規範）
- https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextrestored_event （MDN webglcontextrestored 事件規範）
- https://developer.mozilla.org/en-US/docs/Web/API/WebGLRenderingContext/isContextLost （isContextLost() API）
- https://registry.khronos.org/webgl/extensions/WEBGL_lose_context/ （WEBGL_lose_context 擴充，可用於測試恢復邏輯）

---

## 建議 4：跨瀏覽器 SSIM 比對需考慮 ANGLE/OpenGL 渲染差異

**問題**：不同瀏覽器的 WebGL 後端差異顯著：
- Chrome/Edge（Windows）：ANGLE → Direct3D 11
- Chrome/Edge（macOS）：ANGLE → Metal
- Firefox（Windows）：也走 ANGLE，但版本/設定可能不同
- Safari：WebKit 原生 Metal

這導致相同 WebGL 遊戲在不同瀏覽器產生**像素級不同**的渲染結果（anti-aliasing 演算法、紋理過濾、浮點精度、色彩空間）。目前 `perceiver.py` 的全圖 SSIM 使用單一閾值，跨瀏覽器的參考截圖將產生系統性偏差。

**建議**：
1. 參考截圖應**按瀏覽器/後端分別儲存**，或使用更寬容的比對策略：

```yaml
# config/default.yaml
perceiver:
  ssim_threshold: 0.85          # 同瀏覽器
  ssim_cross_browser_threshold: 0.70  # 跨瀏覽器（降低要求）
```

2. 在 session metadata 中記錄 WebGL renderer 資訊作為比對上下文：

```python
renderer_info = await self._page.evaluate("""
() => {
    const canvas = document.querySelector('canvas');
    const gl = canvas?.getContext('webgl2') || canvas?.getContext('webgl');
    if (!gl) return null;
    const ext = gl.getExtension('WEBGL_debug_renderer_info');
    return {
        vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
        renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
        version: gl.getParameter(gl.VERSION),
    };
}
""")
```

3. SSIM 比對時忽略已知的 anti-aliasing 差異區域（邊緣像素），或改用感知哈希（pHash）作為跨瀏覽器的 screen_id 主鍵

**嚴重度**：Medium — 目前專案僅使用 Chromium，但 DESIGN.md 未限制瀏覽器；未來擴展時會系統性破壞 screen_id 匹配

**參考資料**：
- https://blog.crawlex.net/blog/webgl-fingerprinting/ （WebGL 跨瀏覽器渲染差異深度分析：ANGLE 後端、shader 精度、pow() 計算差異）
- https://groups.google.com/g/webgl-dev-list/c/-qnV-wUknf4 （ANGLE vs 原生 OpenGL 後端辨識方式）
- https://issues.angleproject.org/issues/40096900 （ANGLE D3D 後端渲染不正確的實例 — 相同 shader 不同結果）
- https://groups.google.com/g/angleproject-review/c/rrgm_mjRGhw （ANGLE DirectX 後端 depth buffer 初始值 bug，導致跨平台渲染差異）

---

## 建議 5：Canvas resize / Fullscreen 轉換應動態更新座標基準

**問題**：WebGL 遊戲經常支援視窗縮放與全螢幕切換。當 canvas 尺寸改變時：
1. 知識庫中所有絕對像素座標**立即失效**
2. WebGL framebuffer 需重建（`gl.viewport` 不會自動更新）
3. 遊戲 UI 元素可能重新佈局

目前 `browser.py` 在 `launch()` 時設定固定 viewport（1280×720），但未監控後續的 canvas 尺寸變化。若遊戲自動全螢幕或響應式縮放，系統不會察覺。

**建議**：
1. 使用 `ResizeObserver` 監控 canvas 實際渲染尺寸（考慮 `devicePixelContentBoxSize` 取得精確設備像素）：

```python
await self._page.evaluate("""
() => {
    window.__canvas_size_log = [];
    const canvas = document.querySelector('canvas');
    if (!canvas) return;
    const observer = new ResizeObserver(entries => {
        for (const entry of entries) {
            const dpr = window.devicePixelRatio;
            let width, height;
            if (entry.devicePixelContentBoxSize) {
                width = entry.devicePixelContentBoxSize[0].inlineSize;
                height = entry.devicePixelContentBoxSize[0].blockSize;
            } else {
                width = Math.round(entry.contentRect.width * dpr);
                height = Math.round(entry.contentRect.height * dpr);
            }
            window.__canvas_size_log.push({
                width, height, dpr, time: Date.now()
            });
            window.__canvas_current_size = { width, height, dpr };
        }
    });
    observer.observe(canvas, { box: 'content-box' });
}
""")
```

2. 每次 `observe()` / `execute_action()` 前檢查 canvas 尺寸是否改變：
   - 若改變 → 重新校準座標（按比例縮放知識庫座標）或標記需要重新探索
   - 記錄 resize 事件到 session timeline

3. 座標存儲應從絕對像素轉為**相對比例**（0.0-1.0），或同時存儲 `{x, y, ref_width, ref_height}` 以支援跨解析度轉換：

```python
def normalize_coords(x: int, y: int, canvas_w: int, canvas_h: int) -> tuple[float, float]:
    return x / canvas_w, y / canvas_h

def denormalize_coords(rx: float, ry: float, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    return round(rx * canvas_w), round(ry * canvas_h)
```

這也解決了 AD-4 提到的「座標目前為絕對像素，尚未做解析度正規化」問題。

**嚴重度**：High — 直接對應 ARCHITECTURE_DECISIONS.md AD-4 待處理項目；任何非固定 viewport 場景都會導致點擊失效

**參考資料**：
- https://webglfundamentals.org/webgl/lessons/webgl-resizing-the-canvas.html （WebGL canvas resize 完整指南：ResizeObserver + devicePixelContentBoxSize + gl.viewport）
- https://webgl2fundamentals.org/webgl/webgl-resize-the-canvas-comparison-fullwindow.html （三種 resize 方法比較）
- https://threejs.org/manual/en/responsive.html （Three.js 響應式設計：clientWidth/Height vs devicePixelRatio、HD-DPI 處理）
- https://github.com/KhronosGroup/WebGL/pull/3613 （WebGL 規範討論：canvas resize 時內容重設行為）
- https://github.com/emilk/egui/pull/4536 （ResizeObserver 取代 resize event 的實戰案例，解決非視窗觸發的 canvas resize）

---

## 總結

| # | 建議 | 嚴重度 | 對應架構決策 |
|---|------|--------|-------------|
| 1 | rAF 截圖同步 | Medium | AD-5（screen_id 穩定化） |
| 2 | HiDPI 座標正規化 | High | AD-4（座標 grounding） |
| 3 | Context loss 區分恢復/崩潰 | High | — （偵測器精確度） |
| 4 | 跨瀏覽器 SSIM 閾值 | Medium | AD-5（screen_id 主鍵） |
| 5 | Canvas resize 動態座標 | High | AD-4（相對定位） |
