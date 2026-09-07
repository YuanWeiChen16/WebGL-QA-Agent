# Performance Benchmarker 審查建議

**角色**：Performance Benchmarker（效能測試與最佳化專家）
**審查日期**：2026-07-16
**審查對象**：WebGL QA Agent 整體效能架構

---

## 建議總覽

| # | 建議 | 優先級 | 對應架構決策 |
|---|------|--------|-------------|
| 1 | Vision LLM 呼叫需要 circuit breaker + 成本上限機制 | 高 | AD-9 |
| 2 | SSIM/pixel_diff 影像處理需建立效能基線與 benchmark | 高 | AD-4, AD-5 |
| 3 | Playwright 長時間 session 需要 context recycling 防記憶體洩漏 | 高 | — |
| 4 | 並行 session 擴展需要資源池化架構 | 中 | AD-7 |
| 5 | 確定性偵測層「近零成本」宣稱需量化 benchmark 支撐 | 中 | AD-9 |

---

## 建議 1：Vision LLM 呼叫需要 circuit breaker + per-session 成本上限

### 問題

AD-9 明確標註「待補每 session 成本上限」，目前 Vision 呼叫（截圖→Claude Vision 分析）沒有：
- p95 延遲 SLA 定義
- per-session token/cost budget cap
- gateway 超時或降級的 fallback 策略
- 防止 agent loop 失控重複呼叫的機制

在 agentic workflow 中，一個未受控的 Vision 呼叫 loop 可以在數分鐘內耗盡整月預算。業界已有多起案例（如 GetOnStack 事件：agent-to-agent infinite loop 11 天從 $127/week 飆升至 $47,000）。

### 建議實作

採用三層防護架構（Token Bucket + Circuit Breaker + Fallback Chain）：

```python
# 概念：per-session Vision 成本預算
class VisionBudget:
    max_calls_per_session: int = 20        # 單次 session 最多 Vision 呼叫次數
    max_cost_per_session_usd: float = 2.0  # 單次 session 成本上限
    latency_timeout_ms: int = 15000        # 單次呼叫 p95 超時
    circuit_breaker_threshold: int = 3     # 連續失敗 N 次後開路
    fallback: str = "skip_vision"          # 開路後降級為純確定性偵測
```

Circuit breaker 應區分 HTTP 429（rate limit → backoff retry）與 5xx（服務異常 → 開路），並監控：
- 連續 429 次數（超過 5 次/60s 開路）
- cost velocity（花費速率超過計畫 10x 開路）
- p95 latency 超過 baseline 3x（慢降級偵測）

### 參考來源

- [Rate Limiting AI Agents: Preventing LLM API Exhaustion with a 3-Layer Gateway](https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion) — TrueFoundry (2026-05)：三層防護（token bucket per identity、circuit breaker per pattern、fallback chain per route）的完整實作模式
- [Circuit Breakers for LLMs: Architecture & Fallback](https://balacode.io/blog/circuit-breakers-llms-architecture-fallback) — Balacode (2026-06)：per-model dynamic latency budget（expected latency = 2× TTFT + tokens × per-token latency）、cost-aware fallback chain
- [LLM Rate Limiting and Cost Controls](https://pristren.com/blog/llm-rate-limiting-cost-control/) — Pristren (2026-05)：LiteLLM proxy 做 per-user limits + global budget + circuit breaker 的實務方案
- [Backpressure Patterns for LLM Pipelines](https://tianpan.co/blog/2026-04-15-backpressure-llm-pipelines) — Tian Pan (2026-04)：session-level token budget cap 作為結構性防護，Shopify 實測 tool call output 消耗 ~100× user message tokens
- [rate-limit-shield](https://github.com/mizcausevic-dev/rate-limit-shield) — 開源 Python 套件：TokenBucket + CircuitBreaker + RetryPolicy 可直接整合

---

## 建議 2：SSIM/pixel_diff 影像處理需建立效能基線與 pytest-benchmark 迴歸

### 問題

`perceiver.py` 的全圖 SSIM 比對與 `execute_action` 每次動作後的 pixel_diff，在 1920×1080 解析度下的實際耗時未經 profiling。根據公開 benchmark 數據：

- **scikit-image SSIM 在 1080p：~580ms/次**（單核、無加速）
- **Fast-SSIM（AVX2 多線程）在 1080p：~2.3ms/次**（251x 加速）

若目前使用 scikit-image 的 `structural_similarity`，在壓力測試（interval: 50ms）場景下，單次 SSIM 計算就需要 580ms，**遠超操作間隔本身**，會成為嚴重瓶頸。

### 建議實作

1. **立即**：用 `pytest-benchmark` 建立 perceiver 核心函數的效能基線
2. **短期**：評估替換為 `Fast-SSIM`（PyPI 套件，AVX2/FMA 加速，1080p SSIM 2.3ms）或改用降採樣後比對（resize 到 480p 再算 SSIM）
3. **CI 整合**：`--benchmark-compare-fail` 設定 20% 退化門檻作為迴歸警報

```python
# pytest-benchmark 範例
def test_ssim_performance(benchmark):
    img1 = load_test_screenshot("1080p_gameplay.png")
    img2 = load_test_screenshot("1080p_gameplay_after.png")
    result = benchmark(compute_ssim, img1, img2)
    assert result >= 0.0  # 正確性驗證
```

### 參考來源

- [Fast-SSIM v1.3.1](https://pypi.org/project/Fast-SSIM/) — PyPI：1080p SSIM 從 scikit-image 的 580ms 加速至 2.3ms（251x），4K 從 2.6s 到 7.1ms（367x）
- [pytest-benchmark](https://pytest-benchmark.readthedocs.io/en/stable/) — 官方文件：`--benchmark-compare-fail` 支援效能迴歸偵測，`--benchmark-histogram` 產出趨勢圖
- [scikit-image vs ImageSharp: Processing 10,000 Images](https://milliseconds.dev/blog/12-imageops) — Milliseconds.dev：scikit-image per-image ~47ms（resize pipeline），Pillow 與 native 實作效能差距分析
- [Pillow Performance Benchmarks](https://python-pillow.github.io/pillow-perf/) — 官方：Pillow-SIMD (AVX2) 比原版快 4-6x，比 PIL 快 12-35x

---

## 建議 3：Playwright 長時間 session 需要 context recycling 機制

### 問題

Playwright 在長時間 session 有**已知的記憶體洩漏問題**（microsoft/playwright#15400，2022 年開啟，至今仍有使用者回報）：

- 不關閉 context 的情況下，每秒刷新頁面 → 20 分鐘內 RSS 超過 400MB
- Python 同步 API 的 `__pw_stack__` / `__pw_stack_trace__` 屬性阻止 task GC（已有社群 patch）
- 長時間運行後 Chromium 子程序不被完全清理，即使 close context 也會殘留 10+ 程序

本專案的 endurance testing 場景（30 分鐘+）會直接觸發這些問題。

### 建議實作

```python
class SessionMemoryManager:
    """Context recycling for long-running QA sessions."""
    
    MAX_ACTIONS_PER_CONTEXT = 200      # 每 200 個動作回收一次 context
    MEMORY_THRESHOLD_MB = 512          # RSS 超過 512MB 強制回收
    RECYCLE_INTERVAL_MINUTES = 10      # 最長 10 分鐘回收一次
    
    async def maybe_recycle(self):
        if self._should_recycle():
            state = await self.context.storage_state()  # 保存狀態
            await self.context.close()
            self.context = await self.browser.new_context(storage_state=state)
            self._reset_counters()
```

關鍵措施：
- 定期 context recycling（每 N 個動作或 M 分鐘）
- 使用 `browserContext.storageState()` 保存/恢復登入狀態
- 監控 Python process + Chromium 子程序的 RSS
- 設定 session 級別記憶體上限，超過時優雅終止並產出報告

### 參考來源

- [Playwright Issue #15400: Memory Leaks in Long Sessions](https://github.com/microsoft/playwright/issues/15400) — Microsoft/Playwright：官方確認「Playwright 專注於 testing 場景，metadata 在 context 關閉時才釋放」，建議定期 close & recreate context
- [Memory Management Best Practices for Long Playwright Sessions](https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions) — WebScraping.AI：Context Recycling Pattern + Memory Monitoring + Resource Blocking 完整指南
- [Scaling Playwright Tests: Solving CI Memory Leaks](https://hoangtaiki.com/blog/scaling-playwright-tests-solving-ci-memory-leaks) — Harry Tran (2026-02)：800+ leaked pages 案例、Playwright PageMan 自動化 page lifecycle 管理
- [Run Playwright at Scale](https://www.aethyn.io/solutions/run-playwright-at-scale) — Aethyn (2026-06)：「每幾百個 context 回收一次 browser」、per-context RAM 測量決定併發上限

---

## 建議 4：並行 session 擴展需要 browser pool + Vision gateway rate limit 規劃

### 問題

目前架構為單一 session 運作。若要擴展到多遊戲/多帳號並行 QA（例如 5 個並行 session），瓶頸依序為：

1. **Playwright browser instance**：每個 Chromium context ~200MB RAM，5 個 session = 1GB+ 基礎消耗
2. **Vision gateway rate limit**：多 session 共用同一 API key，併發 Vision 呼叫可能撞 TPM/RPM 上限
3. **知識庫併發讀寫**：多 session 同時更新同一 `knowledge.yaml` 會有 race condition

### 建議實作

```
┌─────────────────────────────┐
│  Session Orchestrator        │
│  • browser pool (N=3)        │
│  • Vision request queue      │
│  • knowledge write lock      │
└─────────────┬───────────────┘
              │
   ┌──────────┼──────────┐
   ▼          ▼          ▼
Session 1  Session 2  Session 3
(context)  (context)  (context)
```

- **Browser pool**：固定 N 個 browser instance，每個 session 用 context 隔離，測量 per-context RAM 設定 workers = (available_RAM × 0.7) / per_context_RAM
- **Vision request queue**：集中式 token bucket，per-session 公平分配 RPM 額度
- **知識庫**：寫入走 file lock 或改用 SQLite（WAL mode 支援併發讀）

### 參考來源

- [Playwright Issue #38683: High Concurrency Memory Usage](https://github.com/microsoft/playwright/issues/38683) — 100-200 workers 場景下 client 記憶體成為瓶頸，每 worker ~200MB
- [Playwright Parallelism Documentation](https://playwright.dev/docs/test-parallel) — 官方：worker 數受限於 CPU cores，context 比 browser 更輕量
- [Playwright Issue #21205: Browsers vs Contexts Performance](https://github.com/microsoft/playwright/issues/21205) — 官方確認「Browser contexts consume less resources and are faster to initialize. It gives you isolation at no cost.」
- [Optimal Test Suite Configuration - Playwright Workspaces](https://learn.microsoft.com/en-us/azure/app-testing/playwright-workspaces/concept-determine-optimal-configuration) — Microsoft Learn：client machine 仍是瓶頸、workers 數量需實驗決定最佳值

---

## 建議 5：確定性偵測層「近零成本」需要量化 benchmark 驗證

### 問題

AD-9 與 README 宣稱確定性偵測（detector + perceiver）為「近零成本」，但缺乏：
- 量化定義（「近零」= <1ms? <10ms? <1% CPU?）
- 在高頻 observe（每 500ms）下的實測 CPU 佔用率
- 不同偵測項目的個別耗時分布

如果 observe() 的確定性偵測在 500ms 間隔下佔用超過 10% 的可用時間（即 >50ms），就不能算「近零」。

### 建議實作

1. 為 detector.py 的每個偵測項目（console error check、freeze detection、blank screen detection、memory growth check）獨立計時
2. 為 perceiver.py 的 pixel_diff 計時（不含 SSIM，SSIM 已在建議 2 處理）
3. 建立 benchmark baseline 並寫入文件：

```python
# 預期 benchmark 結果格式
DETERMINISTIC_DETECTION_BUDGET = {
    "console_error_check": "<1ms",      # 只是檢查 list length
    "freeze_detection": "~5-15ms",       # pixel_diff on 1080p
    "blank_screen_detection": "~2-5ms",  # dominant color + threshold
    "memory_growth_check": "<1ms",       # 讀 JS heap metric
    "total_observe_overhead": "<20ms",   # 目標：observe 間隔的 <4%
}
```

4. CI 中加入 `pytest-benchmark` 迴歸門檻，確保新功能不會讓「近零」變成「有感」

### 參考來源

- [pytest-benchmark Documentation](https://pytest-benchmark.readthedocs.io/en/stable/usage.html) — `--benchmark-compare-fail` 設定迴歸門檻（如 `mean:5%`），`--benchmark-cprofile` 做 function-level profiling
- [pytest-benchmark GitHub](https://github.com/ionelmc/pytest-benchmark) — JSON export + histogram SVG + compare CLI，適合建立長期效能追蹤
- [Pillow Performance Benchmarks](https://python-pillow.github.io/pillow-perf/) — 影像操作 throughput 測量方法論：每個操作跑 11 次取 mean，量化為 Megapixels/s

---

## 整體架構建議

### 效能預算制度

建議為整個 observe-act-learn loop 建立效能預算：

| 階段 | 預算 | 備註 |
|------|------|------|
| observe()（確定性） | <20ms | detector + pixel_diff |
| execute_action() + 驗證 | <100ms | 含動作後截圖 + pixel_diff |
| Vision 呼叫（若觸發） | <15s (p95) | 含網路 + 推理 |
| knowledge 更新 | <10ms | YAML write |
| **單步 loop（無 Vision）** | **<150ms** | 可支撐 interval: 200ms+ |
| **單步 loop（含 Vision）** | **<16s** | Vision 為主要瓶頸 |

### 監控指標建議

在 session 報告中加入效能 section：
- per-action latency distribution（p50/p95/p99）
- Vision 呼叫次數與成本
- 記憶體成長曲線（session start → end）
- observe() overhead 佔比

---

**Performance Benchmarker**
**分析日期**：2026-07-16
**效能狀態**：⚠️ 需要建立基線（目前無 benchmark 數據支撐效能宣稱）
**可擴展性評估**：需要 browser pool + Vision rate limiting 才能支撐並行場景
