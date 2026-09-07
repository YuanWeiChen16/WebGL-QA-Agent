# SRE/Performance 優化建議報告

> 產出日期：2026-07-16
> 角色：SRE/Performance Specialist
> 對象：WebGL QA Agent 效能檢測架構

---

## 建議一：加入 Jank Score 與 Frame Drop 百分比計算

### 問題

目前 rAF injection 只回傳 avg/min/max FPS，沒有 jank score 或 frame drop percentage。SSIM freeze detection 只抓 SSIM > 0.995 的完全凍結，對 5-10 FPS 的嚴重掉幀但非凍結情況完全是盲區。

### 優化建議

在現有 `perf_profiler.py` 的 `measure_fps()` rAF loop 中，加入 frame drop 計算邏輯：

1. 定義 **long frame** = frame_time > 1.5 × (1000 / target_fps)（如 60fps 目標則 > 25ms）
2. 計算 **frame drop %** = long_frames / total_frames × 100
3. 計算 **jank score** = Σ(frame_time - budget) for all long frames（類似 Chrome 的 Total Blocking Time 概念）
4. 在 `perf_report.py` 加入門檻：frame_drop > 10% = warning, > 25% = critical

這不違反黑箱原則，因為 rAF injection 本來就在做了，只是沒算 jank 指標。

### 網路來源 URL

- https://web.dev/articles/speed-rendering — Google 官方 frame budget 與 jank 概念說明
- https://github.com/RenaudRohlinger/stats-gl — stats-gl: WebGL/WebGPU Performance Monitor，展示 real-time FPS sliding window 與 frame timing 最佳實踐
- https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame — MDN rAF API，含 DOMHighResTimeStamp 精確度說明

### 優先級

**高** — 這是目前最大的感知盲區，實作成本低（只需修改已注入的 JS snippet）

### 預期效果

- 能偵測到「非凍結但嚴重卡頓」的情況（如 15 FPS 持續 5 秒）
- frame drop % 可直接作為 CI pass/fail 指標
- 與 SSIM freeze detection 形成互補雙訊號

---

## 建議二：透過 CDP 注入 WebGL Context Loss 事件監聽

### 問題

目前只靠 console log 字串比對 `"CONTEXT_LOST"` 偵測 context loss。如果遊戲靜默處理了 context loss 不印 log，完全偵測不到。也沒有監聽 `webglcontextlost` / `webglcontextrestored` DOM events。

### 優化建議

在 `browser.py` 的 `launch()` 方法中，於頁面載入後注入 context loss 監聽器：

```python
await self._page.evaluate("""() => {
    const canvases = document.querySelectorAll('canvas');
    canvases.forEach((canvas, i) => {
        canvas.addEventListener('webglcontextlost', (e) => {
            console.error(`[WEBGL_QA] CONTEXT_LOST canvas_${i} timestamp=${Date.now()}`);
        });
        canvas.addEventListener('webglcontextrestored', (e) => {
            console.warn(`[WEBGL_QA] CONTEXT_RESTORED canvas_${i} timestamp=${Date.now()}`);
        });
    });
}""")
```

然後在 `detector.py` 的 `critical_patterns` 中加入 `"[WEBGL_QA] CONTEXT_LOST"` 做 critical severity 匹配。同時記錄 context loss 頻率與恢復時間差。

### 網路來源 URL

- https://wikis.khronos.org/webgl/HandlingContextLost — Khronos 官方 WebGL Context Loss 處理指南
- https://bugnet.io/blog/fix-webgl-context-lost-on-tab-switch-restoration — Context loss 偵測與恢復的實戰模式
- https://developer.mozilla.org/en-US/docs/Web/API/WebGLRenderingContext/isContextLost — MDN isContextLost() API
- https://bugnet.io/blog/crash-reporting-for-three-js-and-webgl-games — WebGL crash reporting 最佳實踐，含 context loss 頻率作為健康指標

### 優先級

**高** — 不違反黑箱原則（DOM event 監聽是瀏覽器標準 API），且 context loss 是 WebGL 最常見的致命故障

### 預期效果

- 100% 偵測率的 context loss（無論遊戲自身是否印 log）
- 可統計 context loss 頻率作為穩定性指標
- 可計算 loss-to-restore 時間差，評估遊戲的恢復能力

---

## 建議三：效能門檻從硬編碼移至 config/default.yaml

### 問題

`perf_report.py` 的效能門檻（FPS < 30 critical, heap > 512 MB 等）硬編碼在 Python 中，無法通過 config 調整。而 `detector.py` 的門檻已在 YAML 中，形成不一致。

### 優化建議

1. 在 `config/default.yaml` 新增 `performance_budgets` 區塊：

```yaml
performance_budgets:
  fps:
    critical: 30
    warning: 50
  heap_mb:
    critical: 512
    warning: 256
  heap_growth_mb:
    warning: 50
  dead_code_percent:
    warning: 30
  single_asset_mb:
    warning: 5
  total_bundle_mb:
    warning: 20
```

2. `perf_report.py` 從 Config 讀取這些值，fallback 到現有硬編碼值
3. 遊戲特定的 `game_info.yaml` 可覆寫（如某遊戲本身就是高記憶體需求）

### 網路來源 URL

- https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices — MDN WebGL 最佳實踐：per-pixel VRAM budget 概念
- https://www.dotcom-monitor.com/blog/webgl-application-monitoring/ — WebGL 應用監控：效能預算與門檻設定最佳實踐
- https://www.intelligentgraphicandcode.com/development/threejs-interfaces/performance — Three.js 效能優化：frame budget 16.67ms 概念與自適應降級

### 優先級

**中** — 架構改善，降低維護成本，為 CI 化鋪路

### 預期效果

- 一處修改即可調整所有門檻，不需改 Python 程式碼
- 不同遊戲可有不同 budget（如 3A 大作 vs 休閒遊戲）
- 為 AD-7（CI exit code）提供基礎設施

---

## 建議四：加入跨 Run 歷史趨勢比對（Regression Detection）

### 問題

每次 run 產出獨立的 `runs/<game>/<timestamp>/` 目錄但完全沒有跨 run 比對。Gradual degradation（如 shader 每版慢 2%）不會被偵測到，只有跌破絕對門檻才會觸發。

### 優化建議

新增 `trend_analyzer.py` 模組：

1. **資料收集**：每次 run 完成時，將 key metrics（avg_fps, min_fps, heap_peak, frame_drop_pct）寫入 `runs/<game>/metrics_history.jsonl`（一行一筆，含 timestamp + commit SHA）
2. **趨勢比對**：讀取最近 N 次（預設 10）的 metrics，計算 moving average；若當前 run 的 avg_fps 比 MA 低 > 10%，標記 `regression_detected`
3. **報告整合**：在 HTML report 中加入 sparkline 圖表顯示歷史趨勢
4. **CI 整合**：若偵測到 regression，exit code = 1

```python
# 概念 pseudocode
def check_regression(current: dict, history: list[dict], threshold_pct: float = 10.0) -> bool:
    if len(history) < 3:
        return False  # 資料不足
    ma_fps = mean([h["avg_fps"] for h in history[-10:]])
    return current["avg_fps"] < ma_fps * (1 - threshold_pct / 100)
```

### 網路來源 URL

- https://www.dotcom-monitor.com/blog/webgl-application-monitoring/ — 合成監控 + 定期 benchmark 偵測 gradual degradation 的方法論
- https://www.intelligentgraphicandcode.com/development/threejs-interfaces/performance — 效能指標歷史追蹤與回歸偵測模式
- https://github.com/nicedoc/lighthouse-ci — Lighthouse CI 的 performance budget assertion 與歷史比對機制（可借鑑其 JSONL 存儲 + 門檻比對模式）

### 優先級

**高** — 直接解決 AD-7 的核心問題之一，且實作不複雜（JSONL append + 簡單統計）

### 預期效果

- 偵測到 2-5% 的漸進式效能衰退（目前完全看不到）
- 為 CI pipeline 提供 regression gate
- 長期累積的資料可用於 git bisect 定位效能退化的 commit

---

## 建議五：加入 CI Exit Code 機制

### 問題

README 自己承認「尚無 CI 化的 pass/fail exit code」。目前 `finish()` 無明確的 status + exit code，無法掛 CI pipeline。

### 優化建議

1. 在 `GameSession.finish()` 中根據 anomalies 和 performance budgets 計算 verdict：
   - `pass`：無 critical/high anomaly，所有 budget 在 warning 以下
   - `warn`：有 warning 但無 critical
   - `fail`：有 critical anomaly 或 budget exceeded

2. 回傳 exit code：pass=0, warn=0, fail=1

3. 在 `session.json` 中記錄 `{"verdict": "pass|warn|fail", "reasons": [...]}`

4. CLI wrapper（如 `scripts/run_qa.py`）以 `sys.exit(verdict_code)` 結束

```python
# agent.py finish() 擴充
def _compute_verdict(self) -> tuple[str, int]:
    critical = [a for a in self.detector.anomalies if a.severity == "critical"]
    high = [a for a in self.detector.anomalies if a.severity == "high"]
    if critical:
        return "fail", 1
    if high:
        return "warn", 0  # 或根據配置也可以 fail
    return "pass", 0
```

### 網路來源 URL

- https://www.dotcom-monitor.com/blog/webgl-application-monitoring/ — 合成監控的 pre-deployment validation 與 pass/fail 概念
- https://github.com/nicedoc/lighthouse-ci — Lighthouse CI 的 assertion + exit code 機制（業界標準參考）
- https://web.dev/articles/speed-rendering — Frame budget 概念：超過 16ms = 掉幀 = 品質降級的量化判定

### 優先級

**中** — 依賴建議三（可配置門檻）和建議四（regression detection），但可先用硬編碼門檻實作 MVP

### 預期效果

- 可直接掛 GitHub Actions / Jenkins pipeline
- 每次 deploy 前自動 gate check
- 與 AD-7 目標完全對齊

---

## 建議六：加入 Webhook / Slack 通知機制

### 問題

完全沒有即時告警。偵測到異常只寫入 anomalies list 最終輸出到 HTML 報告。是「事後檢閱」模式，不是即時告警。

### 優化建議

新增 `notifier.py` 模組，支援：

1. **Webhook（通用）**：POST JSON payload 到可配置的 URL
2. **Slack Incoming Webhook**：格式化為 Slack Block Kit 訊息
3. **觸發條件**：critical anomaly 即時發送；run 結束時發送 summary

```yaml
# config/default.yaml 新增
notifications:
  enabled: false
  webhook_url: ""  # 通用 webhook
  slack_webhook_url: ""  # Slack
  notify_on:
    - critical_anomaly
    - run_complete
    - regression_detected
```

Payload 範例：
```json
{
  "game": "example_game",
  "timestamp": "2026-07-16T10:00:00Z",
  "event": "critical_anomaly",
  "details": {"type": "context_lost", "severity": "critical"},
  "report_url": "file:///runs/example_game/20260716_100000/report.html"
}
```

### 網路來源 URL

- https://www.dotcom-monitor.com/blog/webgl-application-monitoring/ — WebGL 監控的 alerting 整合：即時通知 vs 事後報告的差異
- https://bugnet.io/blog/crash-reporting-for-three-js-and-webgl-games — WebGL crash reporting 的 dashboard + alerting 模式
- https://svilenkovic.com/3d/webgl-context-lost-fix — context loss 即時偵測與通知的重要性

### 優先級

**低** — 功能性增強，非核心缺口。建議在 CI exit code 穩定後再加

### 預期效果

- 夜間 nightly run 出問題時即時通知
- 與 AD-10 的每日複審機制互補
- 降低問題發現到修復的時間（MTTD）

---

## 建議七：間接 GPU 記憶體壓力偵測（不違反黑箱原則）

### 問題

無法直接追蹤 GPU VRAM（黑箱限制），但完全沒有任何 GPU 記憶體壓力的間接指標。

### 優化建議

雖然無法 instrument 第三方遊戲的 GL calls，但可透過以下間接方式偵測 GPU 記憶體壓力：

1. **JS Heap 中的 ArrayBuffer 追蹤**：大紋理在 upload 前以 ArrayBuffer 形式存在於 JS heap，監控 ArrayBuffer 總大小可間接反映紋理加載量

```javascript
// 注入到頁面中
(() => {
  const entries = performance.getEntriesByType('resource');
  const imageAssets = entries.filter(e => /\.(png|jpg|ktx2|basis)$/i.test(e.name));
  const totalBytes = imageAssets.reduce((sum, e) => sum + (e.transferSize || 0), 0);
  return { texture_assets_mb: totalBytes / 1024 / 1024, count: imageAssets.length };
})()
```

2. **Context loss 頻率作為 OOM 信號**：GPU OOM 通常表現為 context loss，結合建議二的 context loss 監聽，高頻率 loss = 可能的 VRAM 壓力

3. **FPS 階梯式下降模式識別**：GPU 記憶體不足時常表現為 FPS 突然階梯式下降（而非漸進），在 frame_times 中偵測 step change

### 網路來源 URL

- https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices — MDN：per-pixel VRAM budget 估算法、texture memory 管理
- https://github.com/ihc523/webgl-memory — webgl-memory: WebGL 記憶體追蹤器原理（雖然需 instrument GL context，但其估算方法可借鑑）
- https://www.mysimulator.uk/blog/tip-three-js-memory.html — GPU memory leak 偵測模式：context limits, renderer.info, heap tracking
- https://github.com/lewisgoing/webgltools — WebGLTools: Resource Tracking 與 estimated memory usage 的實作參考

### 優先級

**中** — 是間接指標，準確度有限，但比完全沒有好

### 預期效果

- 在 VRAM 耗盡導致 context loss 之前提供早期警告
- 結合 context loss 頻率建立「GPU 健康度」複合指標
- 為未來可能的 instrumented 測試（自家遊戲）提供 metric 框架

---

## 總結：優先實施順序

| 順序 | 建議 | 優先級 | 預估工時 | 依賴 |
|------|------|--------|----------|------|
| 1 | 建議一：Jank Score + Frame Drop % | 高 | 2-4h | 無 |
| 2 | 建議二：Context Loss 事件監聽 | 高 | 1-2h | 無 |
| 3 | 建議四：歷史趨勢比對 | 高 | 4-6h | 無 |
| 4 | 建議三：門檻移至 YAML | 中 | 2-3h | 無 |
| 5 | 建議五：CI Exit Code | 中 | 2-3h | 建議三 |
| 6 | 建議七：間接 GPU 壓力偵測 | 中 | 3-4h | 建議二 |
| 7 | 建議六：Webhook 通知 | 低 | 2-3h | 建議五 |

建議一、二、四可平行實施，且都不違反黑箱原則（AD-1）。完成後即可串接建議五做 CI 化，達成 AD-7 的目標。
