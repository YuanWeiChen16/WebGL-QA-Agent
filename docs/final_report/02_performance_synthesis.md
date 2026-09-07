# 效能領域綜合報告

> **產出日期**：2026-07-17  
> **整合來源**：Batch 1–9 全部效能相關建議（Performance Benchmarker、SRE/Performance、SRE Batch 4、Backend Architect、Autonomous Optimization、Technical Artist、Frontend Developer、API Tester、Automation Governance、Incident Response、Workflow Optimizer、DevOps Automator、Database Optimizer）  
> **範圍**：Vision LLM 成本控制、渲染效能監控、記憶體管理、影像處理效能、併發擴展、CI 效能門檻、資料層效能

---

## 一、Vision LLM 成本與延遲控制

### 1.1 Per-Session 成本預算（P0 — 最高優先）

**問題**：AD-9 承認缺乏 per-session cost cap。Agent 若卡在探索迴圈，Vision 呼叫無上限，數分鐘內可耗盡整月預算。業界已有 agent loop 從 $127/week 飆升至 $47,000 的案例。

**整合建議**：三層成本護欄

| 層級 | 機制 | 建議值 |
|------|------|--------|
| Layer 1 | Per-call token tracking | 記錄每次 input/output tokens |
| Layer 2 | Per-session hard cap | 最多 200 次 Vision 呼叫 或 500K tokens（~$2.5） |
| Layer 3 | Velocity circuit breaker | 5 分鐘內 >15 次且 pixel_diff 低 → trip |

**觸發後行為**：降級為純確定性模式（detector + perceiver + 知識庫已知路徑），不中斷 session。

**參考 URL**：
- Rate Limiting AI Agents（三層防護完整模式）：https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion
- token-fence（per-session budget enforcement）：https://github.com/SiluPanda/token-fence
- AssemblyZero 三層成本控制：https://github.com/martymcenroe/AssemblyZero/wiki/Cost-Management
- tokencap（warn → degrade → block 三階段策略）：https://github.com/pykul/tokencap
- token-throttle（multi-resource rate limiting）：https://github.com/Elijas/token-throttle

---

### 1.2 Circuit Breaker + Async 修正（P0）

**問題**：`vision.py` 有 3 次 retry + exponential backoff，但：
- 無 circuit breaker — gateway 持續故障時每步浪費 14-42 秒
- `time.sleep()` 在 async context 凍結整個 event loop（違反 Ruff ASYNC251）
- 無 jitter — 多 client 會 thundering herd

**整合建議**：
1. 引入 async circuit breaker（`aiobreaker` 或 `pyresilience`），設定 `fail_max=5, reset_timeout=60s`
2. 所有 `time.sleep()` 替換為 `await asyncio.sleep()`
3. Backoff 加入 jitter 防止 thundering herd
4. Circuit breaker open 時 fast-fail → 純確定性模式

**SLO 影響**：無 circuit breaker 時 gateway 故障將 p99 latency 從 ~5s 推高至 180-240s。

**參考 URL**：
- aiobreaker（asyncio 原生 circuit breaker）：https://pypi.org/project/aiobreaker/
- pyresilience（統一 7 種 resilience pattern，overhead 0.64μs/call）：https://github.com/AhsanSheraz/pyresilience
- interlock-cb（sliding window + slow-call detection）：https://github.com/bagowix/interlock
- Ruff ASYNC251（blocking sleep 檢測規則）：https://docs.astral.sh/ruff/rules/blocking-sleep-in-async-function/

---

### 1.3 Image Preprocessing — 降低 40-70% Vision Token（P0）

**問題**：每次送完整 1280×720 PNG = 1,196 visual tokens。多數任務不需要全圖。

**整合建議**：

| 場景 | 策略 | 現況 tokens | 優化後 tokens | 節省 |
|------|------|------------|--------------|------|
| game_state 讀數 | ROI crop（只送 UI 區域） | 1,196 | 368 | 69% |
| screen_id 辨識 | Resize 至 1092px | 1,196 | 780 | 35% |
| 探索全圖 | Resize 至 1568px + JPEG q85 | 1,196 | 1,196 | 傳輸時間減少 |
| Hash dedup | 同畫面 SSIM>0.98 不重複呼叫 | — | — | 額外 10-25% |

**參考 URL**：
- Anthropic 官方 Vision 文件（token 計算公式 + resize 建議）：https://platform.claude.com/docs/en/build-with-claude/vision
- Claude Vision Production Guide（40-70% cost cut）：https://www.developersdigest.tech/blog/claude-vision-api-production-guide
- Claude Lab 按務類型調整 resize：https://claudelab.net/en/articles/api-sdk/claude-vision-pdf-ocr-implementation-patterns

---

### 1.4 Multi-Model Semantic Router（P2）

**問題**：所有 Vision 呼叫走同一模型，但 80% 是簡單任務（已知畫面讀數）。

**整合建議**：利用 perceiver 現有信號做 zero-cost routing：
- `screen_id` 已知 + confidence high → Cheap model（Haiku）
- `screen_id` 未知 OR pixel_diff > 0.3 → Premium model（Opus）
- `game_state` 純讀數 + ROI crop → Cheapest

**預估效益**：結合 ROI crop + multi-model，總成本削減 70-80%。

**參考 URL**：
- Multi-Model Routing — Cut LLM Bills 40-70%：https://akshayghalme.com/blogs/multi-model-routing-ai-gateway-pattern/
- RouteLLM Benchmarks（95% GPT-4 quality at 26% cost）：https://klymentiev.com/blog/llm-router
- A3M Router（96.77% routing accuracy）：https://github.com/Das-rebel/a3m-router

---

### 1.5 Vision Telemetry（P1）

**問題**：無記錄 Vision 呼叫的 latency、token count、cost、parse success rate，無法量化優化效果。

**整合建議**：每次呼叫記錄 structured telemetry → `runs/<game>/telemetry.jsonl`，每 session 結束在 report 中顯示 cost breakdown。Parse success rate 連續 10 次 < 80% 觸發 regression alert。

**參考 URL**：
- AI Agent Cost Governance System：https://letsbuildsolutions.com/blog/ai-ml/designing-an-ai-agent-cost-governance-system-token-budgets-spend-caps-and-automated-circuit-breakers-for-production-llm-deployments/

---

## 二、渲染效能監控（WebGL 專項）

### 2.1 Jank Score + Frame Drop 百分比（P0）

**問題**：rAF injection 只回傳 avg/min/max FPS，對 5-10 FPS 的嚴重掉幀但非凍結是盲區。

**整合建議**：
- 定義 long frame = frame_time > 1.5 × (1000 / target_fps)
- 計算 frame drop % = long_frames / total_frames × 100
- 計算 jank score = Σ(frame_time − budget) for all long frames
- 門檻：frame_drop > 10% = warning, > 25% = critical

**預期效果**：偵測「非凍結但嚴重卡頓」；frame drop % 直接作為 CI pass/fail 指標。

**參考 URL**：
- Google 官方 frame budget 與 jank 概念：https://web.dev/articles/speed-rendering
- stats-gl WebGL Performance Monitor：https://github.com/RenaudRohlinger/stats-gl

---

### 2.2 WebGL Context Loss 事件監聽（P0）

**問題**：只靠 console log 字串比對偵測 context loss，遊戲靜默處理時完全漏偵測。

**整合建議**：
1. 透過 `page.addInitScript` 注入 `webglcontextlost` / `webglcontextrestored` 監聽器
2. 區分「正常恢復」（5 秒內 restored）與「真正崩潰」（超時未恢復）
3. 同時注入 `gl.isContextLost()` 定期輪詢作為補充
4. 用 `WEBGL_lose_context` extension 在 CI 中模擬測試

**參考 URL**：
- Khronos 官方 WebGL Context Loss 處理指南：https://wikis.khronos.org/webgl/HandlingContextLost
- MDN webglcontextlost event：https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/webglcontextlost_event
- WebGL crash reporting 最佳實踐：https://bugnet.io/blog/crash-reporting-for-three-js-and-webgl-games

---

### 2.3 Draw Call / State Change 計數器（P1）

**問題**：只有 FPS 和 SSIM 兩個指標，無法定位渲染管線具體瓶頸。

**整合建議**：注入 WebGL proxy 攔截 `drawArrays`/`drawElements`/`useProgram`/`bindTexture`，每幀統計 draw calls、vertices、shader switches。門檻：draw calls > 500/frame → warning, > 1000 → critical。

**參考 URL**：
- webgl-spy（輕量 draw call monitor）：https://github.com/ayamflow/webgl-spy
- GLPerf（WebGL Performance Monitor）：https://github.com/eyworldwide/GLPerf

---

### 2.4 GPU Timer Query（P2）

**問題**：FPS profiler 只在 CPU 側量測，無法區分 CPU-bound 與 GPU-bound。

**整合建議**：偵測 `EXT_disjoint_timer_query_webgl2` 可用性，在 draw call 前後插入 query，聚合為每幀 GPU total time。可選產出 speedscope 格式 profile。

**參考 URL**：
- Figma/webgl-profiler（EXT_disjoint_timer_query + speedscope）：https://github.com/figma/webgl-profiler
- Wonderland Engine Profiling Guide：https://wonderlandengine.com/news/profiling-webxr-applications/

---

### 2.5 間接 GPU 記憶體壓力偵測（P1）

**問題**：無法直接追蹤 VRAM（黑箱限制），但完全沒有 GPU 記憶體壓力的間接指標。

**整合建議**：
1. **VRAM 估算 tracker**：monkey-patch `texImage2D`/`bufferData`/`deleteTexture` 等，按 `internalformat × width × height × mip levels` 估算 bytes
2. **Context loss 頻率作為 OOM 信號**
3. **FPS 階梯式下降模式識別**（step change detection）
4. **Resource entry 紋理資產追蹤**：`performance.getEntriesByType('resource')` 過濾圖片

**參考 URL**：
- webgl-memory（完整 VRAM 追蹤）：https://github.com/HIABRE/webgl-memory
- webgltools（Resource Tracking + memory estimation）：https://github.com/lewisgoing/webgltools
- MDN WebGL best practices（per-pixel VRAM budget）：https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API/WebGL_best_practices

---

### 2.6 Screenshot Observer Effect 量化（P1）

**問題**：`page.screenshot()` 強制觸發 GPU `readPixels`，造成 pipeline stall。高 GPU 壓力時可能導致 frame drop 甚至 context loss。

**整合建議**：
1. 截圖前後記錄 `performance.now()` 差值作為 GPU 壓力 proxy
2. 若 screenshot 延遲 > 50ms，自動降低截圖頻率
3. 偵測 `preserveDrawingBuffer` 屬性，避免空白截圖
4. GPU 壓力極高時改用 CDP `Page.captureScreenshot` 的 `fromSurface: true`

**參考 URL**：
- Playwright PR #32009（canvas screenshot + preserveDrawingBuffer）：https://github.com/microsoft/playwright/pull/32009

---

## 三、記憶體管理與資源生命週期

### 3.1 Playwright Context Recycling（P0）

**問題**：Playwright 長時間 session 有已知記憶體洩漏（#15400），20 分鐘內 RSS 可超過 400MB。本專案 endurance testing 場景（30 分鐘+）會直接觸發。

**整合建議**：
- 每 200 個動作 或 每 10 分鐘 回收一次 context
- 使用 `browserContext.storageState()` 保存/恢復狀態
- 監控 Python process + Chromium 子程序 RSS
- session 級記憶體上限（512MB），超過優雅終止並產報告

**參考 URL**：
- Playwright #15400 Memory Leaks：https://github.com/microsoft/playwright/issues/15400
- Memory Management Best Practices for Long Sessions：https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions
- Aethyn Run Playwright at Scale：https://www.aethyn.io/solutions/run-playwright-at-scale

---

### 3.2 Browser 孤兒化防護（P0）

**問題**：`browser.close()` 只在 `finish()` 呼叫，無 atexit/signal handler/context manager。Process 被 kill 時 Chromium 子程序 100% 孤兒化，佔 200-500MB。

**整合建議**：
1. `GameSession` 實作 `__aenter__` / `__aexit__` async context manager
2. 註冊 `atexit.register()` + `signal.signal(SIGTERM, handler)`
3. 所有腳本改用 `async with GameSession(...) as session:` pattern

**參考 URL**：
- Python atexit 模組：https://docs.python.org/3/library/atexit.html
- Playwright Browser.close() 文件：https://playwright.dev/python/docs/api/class-browser#browser-close

---

### 3.3 Session 資源上限（P1）

**問題**：`self.steps: list[dict]` 只增不減，1000+ steps 約 10-50MB。8 小時 nightly 約 960 張 PNG（192MB disk）。

**整合建議**：
```yaml
session:
  max_steps: 2000
  max_duration_hours: 4
  max_screenshots_mb: 500
```
超限觸發 graceful `finish()`，而非 OOM crash。Reporter 支援 streaming flush（每 100 steps 寫中間報告）。

---

### 3.4 runs/ 目錄 Retention Policy（P1）

**問題**：零清理機制。每次 run ~5MB，nightly 每天 10 次 = 50MB/day，一年 ~18GB。

**整合建議**：
```yaml
retention:
  max_runs: 50
  max_age_days: 30
  max_total_size_mb: 2048
```
每次 `create_run()` 後以 LRU 策略清理。

---

## 四、影像處理效能（確定性偵測層）

### 4.1 SSIM 效能基線與加速（P0）

**問題**：scikit-image SSIM 在 1080p 約 580ms/次，若 observe 間隔 50ms，單次 SSIM 就遠超操作間隔。

**整合建議**：
1. 用 `pytest-benchmark` 建立 perceiver 核心函數效能基線
2. 評估替換為 `Fast-SSIM`（AVX2 加速，1080p 從 580ms → 2.3ms，251× 加速）
3. 或改用降採樣後比對（resize 到 480p 再算 SSIM）
4. CI 整合 `--benchmark-compare-fail` 設定 20% 退化門檻

**參考 URL**：
- Fast-SSIM v1.3.1（251× 加速）：https://pypi.org/project/Fast-SSIM/
- pytest-benchmark 官方文件：https://pytest-benchmark.readthedocs.io/en/stable/
- Pillow-SIMD（AVX2 比原版快 4-6×）：https://python-pillow.github.io/pillow-perf/

---

### 4.2 確定性偵測層量化 Benchmark（P1）

**問題**：AD-9 宣稱「近零成本」但無量化定義。若 observe() 在 500ms 間隔下佔用 >50ms 就不算「近零」。

**整合建議**：為每個偵測項目獨立計時並建立 budget：

| 偵測項目 | 預期耗時 |
|----------|----------|
| console_error_check | <1ms |
| freeze_detection（pixel_diff） | ~5-15ms |
| blank_screen_detection | ~2-5ms |
| memory_growth_check | <1ms |
| **total observe overhead** | **<20ms（間隔的 <4%）** |

---

### 4.3 截圖時機 rAF 同步（P1）

**問題**：`page.screenshot()` 無幀同步，可能擷取 GPU 繪製中間狀態（tearing），導致 SSIM 不穩定。

**整合建議**：截圖前插入雙重 rAF 等待：
```python
await page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
```

**參考 URL**：
- Canvas/WebGL 測試最佳實踐：https://github.com/currents-dev/playwright-best-practices-skill/blob/HEAD/testing-patterns/canvas-webgl.md

---

## 五、併發擴展與資源池化

### 5.1 Browser Pool 架構（P2）

**問題**：單 session = 獨立 Playwright browser instance（~200MB RAM）。5 個並行 session = 1GB+ 基礎消耗。

**整合建議**：
- 固定 N 個 browser instance，每 session 用 context 隔離
- workers = (available_RAM × 0.7) / per_context_RAM
- Browser contexts 比 browser instances 輕量且初始化更快

**參考 URL**：
- Playwright #21205（Browsers vs Contexts Performance）：https://github.com/microsoft/playwright/issues/21205
- Browser Pool Patterns：https://scrapingcentral.com/learn/dynamic-web/browser-pool-patterns
- Pooling Playwright Browsers（FastAPI 案例）：https://danieljoffe.com/blog/pooling-playwright-browsers-fastapi

---

### 5.2 Knowledge 併發安全（P1）

**問題**：`save_runtime()` 無 file lock，多 session 同遊戲會 race condition。

**整合建議**：
1. **短期**：`filelock` 套件 + atomic write（先寫 .tmp 再 `os.replace()`）
2. **中期**：改為 per-session 寫入，session 結束時 merge
3. **長期**：SQLite WAL mode 作為 knowledge 儲存後端

**參考 URL**：
- filelock 官方文件：https://py-filelock.readthedocs.io/en/latest/
- portalocker（跨平台 file locking）：https://portalocker.readthedocs.io/en/latest/
- SQLite concurrent writes（WAL mode 最佳實踐）：https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/

---

### 5.3 YAML I/O 非阻塞化（P1）

**問題**：`save_runtime()` 是同步 YAML dump，500KB+ 的 knowledge.yaml 每次寫入 100-200ms 且 block event loop。

**整合建議**：
1. `asyncio.to_thread()` 包裝寫入
2. Dirty flag + 批次寫入（每 10 次更新合併一次）
3. 多 session 時加 `AsyncFileLock`

**參考 URL**：
- Python asyncio.to_thread：https://docs.python.org/3/library/asyncio-task.html

---

## 六、CI 效能門檻與迴歸偵測

### 6.1 效能門檻 Config 化（P1）

**問題**：`perf_report.py` 門檻硬編碼，與 `detector.py` 從 YAML 讀取的做法不一致。

**整合建議**：在 `config/default.yaml` 新增 `performance_budgets` 區塊：
```yaml
performance_budgets:
  fps:
    critical: 30
    warning: 50
  heap_mb:
    critical: 512
    warning: 256
  frame_drop_percent:
    critical: 25
    warning: 10
```
遊戲特定 `game_info.yaml` 可覆寫。

---

### 6.2 跨 Run 歷史趨勢比對（P0）

**問題**：每次 run 獨立，gradual degradation（如每版 2%）不會被偵測，只有跌破絕對門檻才觸發。

**整合建議**：
1. 每次 run 完成寫 key metrics 到 `runs/<game>/metrics_history.jsonl`
2. 計算 moving average（最近 10 次），當前 run 比 MA 低 > 10% → regression
3. HTML report 加 sparkline 趨勢圖
4. CI 偵測到 regression 時 exit code = 1

**參考 URL**：
- Flakiness.io（跨 commit 趨勢追蹤）：https://flakiness.io/
- Lighthouse CI（performance budget assertion + 歷史比對）：https://github.com/nicedoc/lighthouse-ci

---

### 6.3 CI Exit Code 機制（P1）

**問題**：`finish()` 無 exit code，無法掛 CI pipeline。

**整合建議**：
- pass（exit 0）：無 critical/high anomaly，所有 budget 在 warning 以下
- fail（exit 1）：有 critical anomaly 或 budget exceeded
- warn（exit 0）：有 warning 但無 critical

**參考 URL**：
- pytest exit code 公約：https://docs.pytest.org/en/stable/reference/exit-codes.html

---

### 6.4 GPU Runner 方案（P2）

**問題**：SwiftShader 軟體渲染與真實 GPU 在 shader precision、anti-aliasing 上差異顯著，會導致 perceiver 閾值失效。

**整合建議**：
- E2E 視覺測試必須 GPU runner（RunsOn g5.xlarge ~$1.06/hr spot）
- Unit test CI 任何 runner 即可
- 折衷方案：Mesa llvmpipe 做煙霧測試（功能性驗證，不做精確 SSIM）

**參考 URL**：
- Playwright + GPU Docker（Promaton 案例）：https://blog.promaton.com/testing-3d-applications-with-playwright-on-gpu-1e9cfc8b54a9
- Mesa llvmpipe vs SwiftShader（CPU 降 49%）：https://botbrowser.io/en/blog/mesa-llvmpipe-vs-swiftshader-chromium-linux/

---

## 七、可觀測性與即時告警

### 7.1 Structured Logging（P0）

**問題**：僅有 `logging.getLogger()` + f-string，無 structured logging、無 correlation ID、無 API call duration metric。

**整合建議**：導入 `structlog`，session 入口 bind `session_id`，所有 Vision 呼叫記錄 duration + token count + cost。JSON log 可直接餵 Datadog/Loki。

**參考 URL**：
- structlog contextvars：https://www.structlog.org/en/24.4.0/contextvars.html
- AI 應用 structured logging 最佳實踐：https://callsphere.ai/blog/python-logging-ai-applications-structured-logs-structlog-loguru

---

### 7.2 即時告警 Webhook（P2）

**問題**：所有結果只寫 report HTML，nightly run 凌晨異常要等隔天才知。

**整合建議**：critical anomaly 即時發送 Slack/PagerDuty webhook，同類告警 5 分鐘 cooldown。

---

## 八、效能預算總覽

### Observe-Act-Learn Loop 效能預算

| 階段 | 預算 | 備註 |
|------|------|------|
| observe()（確定性） | <20ms | detector + pixel_diff |
| execute_action() + 驗證 | <100ms | 含動作後截圖 + pixel_diff |
| Vision 呼叫（若觸發） | <15s (p95) | 含網路 + 推理 |
| knowledge 更新 | <10ms | YAML write（async） |
| **單步 loop（無 Vision）** | **<150ms** | 可支撐 interval: 200ms+ |
| **單步 loop（含 Vision）** | **<16s** | Vision 為主要瓶頸 |

---

## 九、實施優先級總表

| 優先級 | 主題 | 建議項目 | 預估工時 | 風險等級 |
|--------|------|----------|----------|----------|
| **P0** | Vision 成本 | Per-session budget cap + circuit breaker | 3-4h | 🔴 高 |
| **P0** | Vision 成本 | Image resize + ROI crop preprocessing | 2-3h | 🔴 高 |
| **P0** | 記憶體 | Browser 孤兒化防護（context manager + atexit） | 2-3h | 🔴 高 |
| **P0** | 記憶體 | Playwright context recycling | 3-4h | 🔴 高 |
| **P0** | 影像處理 | SSIM 效能基線 + Fast-SSIM 評估 | 2-4h | 🔴 高 |
| **P0** | 渲染監控 | Jank Score + Frame Drop % | 2-4h | 🔴 高 |
| **P0** | 渲染監控 | WebGL Context Loss 事件監聽 | 1-2h | 🔴 高 |
| **P0** | CI | 跨 Run 歷史趨勢比對（regression detection） | 4-6h | 🟡 中 |
| **P0** | 可觀測性 | Structured logging（structlog） | 2-3h | 🟡 中 |
| **P1** | Vision 成本 | Vision telemetry | 2-3h | 🟡 中 |
| **P1** | 渲染監控 | Draw call / state change 計數器 | 3-4h | 🟡 中 |
| **P1** | 渲染監控 | 間接 GPU 記憶體壓力偵測 | 3-4h | 🟡 中 |
| **P1** | 渲染監控 | Screenshot observer effect 量化 | 2-3h | 🟡 中 |
| **P1** | 影像處理 | 確定性偵測層量化 benchmark | 2-3h | 🟡 中 |
| **P1** | 影像處理 | 截圖 rAF 同步 | 1-2h | 🟡 中 |
| **P1** | 併發 | Knowledge filelock + atomic write | 1-2h | 🟡 中 |
| **P1** | 併發 | YAML I/O 非阻塞化 | 1-2h | 🟡 中 |
| **P1** | CI | 效能門檻 config 化 | 2-3h | 🟡 中 |
| **P1** | CI | CI exit code 機制 | 2-3h | 🟡 中 |
| **P1** | 記憶體 | Session 資源上限 + graceful degradation | 3-4h | 🟡 中 |
| **P1** | 記憶體 | runs/ retention policy | 2-3h | 🟡 中 |
| **P2** | Vision 成本 | Multi-model semantic router | 5-8h | 🟢 低 |
| **P2** | 渲染監控 | GPU timer query（EXT_disjoint_timer_query） | 4-6h | 🟢 低 |
| **P2** | 併發 | Browser pool 架構 | 6-8h | 🟢 低 |
| **P2** | CI | GPU runner 方案 | 2-3d | 🟢 低 |
| **P2** | 可觀測性 | 即時告警 webhook | 2-3h | 🟢 低 |

---

## 十、關鍵依賴關係

```
Image Preprocessing (1.3) ──┐
                            ├──→ Vision Telemetry (1.5) ──→ Multi-Model Router (1.4)
Per-Session Budget (1.1) ───┘

Context Loss 監聽 (2.2) ──→ 間接 GPU 壓力偵測 (2.5)

效能門檻 Config 化 (6.1) ──→ CI Exit Code (6.3)
                                    │
跨 Run 趨勢比對 (6.2) ─────────────┘

Browser 孤兒化防護 (3.2) ──→ Context Recycling (3.1) ──→ Browser Pool (5.1)

Structured Logging (7.1) ──→ 即時告警 (7.2)
```

---

## 十一、共識性問題（多方審查者重複提出）

以下問題被 **3 個以上獨立審查角色** 同時標記，代表高度共識：

| 共識問題 | 提出者（≥3） | 共識優先級 |
|----------|-------------|-----------|
| **Vision API 無 circuit breaker，gateway 故障時整個 session 癱瘓** | Performance Benchmarker、SRE Batch 4、Backend Architect、API Tester、Incident Response、Autonomous Optimization | P0 |
| **Vision API 無 per-session 成本上限，loop 失控可災難性花費** | Performance Benchmarker、Backend Architect、API Tester、Automation Governance、Autonomous Optimization、Incident Response | P0 |
| **Playwright 長時間 session 記憶體洩漏 + browser 孤兒化** | Performance Benchmarker、SRE Batch 4、Incident Response、API Tester | P0 |
| **Knowledge YAML 併發寫入無 file lock，race condition 損毀** | Database Optimizer、Backend Architect、SRE Batch 4、Automation Governance、API Tester、Incident Response | P1 |
| **WebGL Context Loss 只靠 console 字串比對，漏偵測率高** | SRE/Performance、Technical Artist、Frontend Developer | P0 |
| **SSIM 影像處理未經 profiling，可能成為高頻 observe 瓶頸** | Performance Benchmarker、SRE/Performance、Frontend Developer | P0 |
| **缺乏 CI exit code，無法掛 pipeline** | SRE/Performance、Workflow Optimizer、Automation Governance | P1 |
| **缺乏跨 Run 歷史趨勢比對（gradual degradation 不可偵測）** | SRE/Performance、Workflow Optimizer | P0 |
| **缺乏 structured logging / observability** | Backend Architect、SRE Batch 4、Incident Response | P0 |

**核心結論**：9 項共識問題中有 6 項被判為 P0，集中在 Vision API 韌性、記憶體安全、渲染監控三大領域。這些問題若不在 nightly run 上線前解決，系統會在 production 中靜默惡化。

---

**結論**：本專案效能面的最大風險集中在三個領域：（1）Vision LLM 無成本上限可能導致災難性花費；（2）長時間 Playwright session 記憶體洩漏會導致 nightly run 靜默失敗；（3）影像處理（SSIM）在高頻 observe 下可能成為嚴重瓶頸。建議立即處理所有 P0 項目（約 2-3 天工作量），這些改善不需修改核心架構，且每項都有明確的量化效益。
