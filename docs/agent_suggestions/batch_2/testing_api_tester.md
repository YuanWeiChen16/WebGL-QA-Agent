# API Tester 審查建議 — Batch 2

> 審查角色：API Testing & Resilience Specialist  
> 審查日期：2026-07-16  
> 對應架構決策：AD-4, AD-9  

---

## 建議 1：加入 Vision API Circuit Breaker 防護

**問題**：`vision.py` 有 3 次重試 + 指數退避，但缺乏跨呼叫的全域 circuit breaker。當 gateway 持續故障時，每次 Vision 呼叫會燒掉 ~42 秒才放棄，無任何降級模式。連續 N 次失敗不會觸發「暫停 Vision、僅用確定性偵測器」的 fallback。

**建議**：引入 `interlock-cb` 套件（零依賴核心、同時支援 sync/async、支援 failure-rate sliding window + slow-call detection），在 `vision.py` 的呼叫點加上 circuit breaker：

```python
from interlock import CircuitBreaker, Config

vision_breaker = CircuitBreaker(
    name="vision-gateway",
    config=Config(
        failure_rate_threshold=0.6,
        minimum_number_of_calls=5,
        wait_duration_in_open_state=60,  # 60s 後進 half-open
        slow_call_duration_threshold=30.0,
        slow_call_rate_threshold=0.5,
    ),
)
```

當 circuit open 時，`observe()` 自動降級為純確定性偵測（detector + pixel_diff），不呼叫 Vision，避免長時間 block。

**參考資料**：
- interlock-cb GitHub（現代 Python circuit breaker，支援 sliding window + slow-call）：https://github.com/bagowix/interlock
- resilient-http 範例（circuit breaker + retry + backoff 組合模式）：https://github.com/pgnikolov/resilient-http
- hyx circuit breaker 文件（consecutive breaker 基本實作參考）：https://hyx.readthedocs.io/en/latest/components/circuit_breakers/

---

## 建議 2：加入 Per-Session Vision API Cost Budget 與 Rate Limiter

**問題**：AD-9 承認缺乏 per-session cost cap。adaptive_observe 的 `skip_threshold=0.02` 是節流第一道防線，但不是 rate limiter。高動態場景（持續動畫遊戲）中每步都超過 2% threshold，會無限制呼叫 Vision API，無 429 graceful degradation。

**建議**：使用 `token-throttle` 套件建立 per-session rate limiter，支援「reserve → call → refund」模式與多維度限制（requests/min + tokens/min）：

```python
from token_throttle import MemoryBackendBuilder, PerModelConfig, Quota, RateLimiter, UsageQuotas

vision_limiter = RateLimiter(
    PerModelConfig(
        quotas=UsageQuotas([
            Quota(metric="requests", limit=30, per_seconds=60),      # 30 calls/min
            Quota(metric="cost_cents", limit=500, per_seconds=3600),  # $5/hr hard cap
        ])
    ),
    backend=MemoryBackendBuilder(),
)
```

當 budget 耗盡時，`acquire_capacity` 會 block 或 timeout，呼叫端可 fallback 到確定性觀察。搭配 `timeout` 參數可實現 fail-fast：

```python
reservation = await vision_limiter.acquire_capacity(
    model="claude-vision",
    usage={"requests": 1, "cost_cents": 1},
    timeout=2.0,  # 2s 內拿不到配額就放棄
)
```

**參考資料**：
- token-throttle（多資源 LLM rate limiting，reserve & refund 模式）：https://github.com/Elijas/token-throttle
- ratebucket（multi-resource arbiter + pool-wide 429 gate）：https://pypi.org/project/ratebucket/
- steindamm（async token bucket，支援 non-refilling fixed quota）：https://github.com/feuerstein-org/steindamm

---

## 建議 3：Knowledge YAML I/O 改用 `asyncio.to_thread` + 批次寫入

**問題**：`save_runtime()` 是同步 YAML dump，每次 `update_screen()` / `report_bug()` 都觸發整份重寫。在 async event loop 上這是 blocking I/O。長 session（200+ screens）下，knowledge.yaml 可達 500KB+，每次寫入 100-200ms 且 block 整個 loop，影響 action pipeline 的即時性。

**建議**：

1. **短期**：用 `asyncio.to_thread()` 包裝 YAML 寫入，避免 block event loop：

```python
import asyncio

async def save_runtime_async(self):
    await asyncio.to_thread(self._save_runtime_sync)
```

2. **中期**：實作 dirty flag + 批次寫入（每 N 次更新或每 T 秒合併寫一次）：

```python
class KnowledgeBase:
    _dirty_count = 0
    _BATCH_THRESHOLD = 10

    def mark_dirty(self):
        self._dirty_count += 1
        if self._dirty_count >= self._BATCH_THRESHOLD:
            asyncio.create_task(self.save_runtime_async())
            self._dirty_count = 0
```

3. **併發安全**：若未來要跑多 session 同 game，加入 `filelock` 的 `AsyncFileLock` 保護寫入：

```python
from filelock import AsyncFileLock

lock = AsyncFileLock("knowledge.yaml.lock")
async with lock:
    await asyncio.to_thread(self._save_runtime_sync)
```

**參考資料**：
- Python asyncio.to_thread 官方文件：https://docs.python.org/3/library/asyncio-task.html
- py-filelock AsyncFileLock 使用指南：https://py-filelock.readthedocs.io/en/latest/how-to.html
- AnyIO to_thread.run_sync（更進階的 thread dispatch）：https://anyio.readthedocs.io/en/latest/threads.html?highlight=synchronous

---

## 建議 4：引入 Browser Pool 支援併發 Session 測試

**問題**：目前一個 `GameSession` = 一個獨立 Playwright browser instance。若要 nightly CI 平行測試 5 個遊戲，每個 instance 200-400MB RAM，且 knowledge_base 的 `_kb_cache` 是 module-level dict，多 session 同 game 會有 race condition。

**建議**：參考 `BrowserPool` pattern（一個 Chromium process + 多個 isolated context），改為：

```python
class BrowserPool:
    def __init__(self, max_contexts: int = 5, max_age_seconds: int = 300):
        self._browser = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_contexts)

    async def acquire(self) -> BrowserContext:
        await self._semaphore.acquire()
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(
                    args=["--disable-dev-shm-usage", "--no-sandbox", "--use-gl=angle"]
                )
        return await self._browser.new_context()

    async def release(self, context: BrowserContext):
        await context.close()
        self._semaphore.release()
```

每個 GameSession 透過 pool 取得 context 而非獨立 browser，共享一個 Chromium process 可節省 60-70% RAM。搭配 memory monitor（psutil 追蹤 Chromium PID RSS），超過閾值自動 recycle。

Knowledge 層需要 per-instance 的 `_kb_cache`（改為 instance attribute 而非 module-level），或加 file lock。

**參考資料**：
- Browser Pool 設計模式（bounded context pool + memory monitoring）：https://scrapingcentral.com/learn/dynamic-web/browser-pool-patterns
- Pooling Playwright browsers（FastAPI 實際案例，idle shutdown + context isolation）：https://danieljoffe.com/blog/pooling-playwright-browsers-fastapi
- playwright-pool 套件（async page pool 管理）：https://github.com/tgscan-dev/playwright-pool
- DEV.to Browser Pool 管理（memory monitoring + crash recovery + Docker shm）：https://dev.to/scraping_eng/managing-browser-pools-for-large-scale-scraping-memory-crashes-and-captcha-handling-19k7

---

## 建議 5：Screenshot Fallback Chain 設定超時上限與監控

**問題**：`execute_action` 的驗證截圖有 fallback chain（primary → CDP → canvas），worst-case 可達 27 秒（15s timeout + 2s sleep + retry + CDP + canvas fallback）。在 WebGL context lost 等異常下會嚴重拖慢整個 action loop，且無指標追蹤發生頻率。

**建議**：

1. **設定 pipeline 整體超時**：用 `asyncio.wait_for` 包裝整個截圖 + 驗證流程，給一個合理的總時間預算（如 5 秒）：

```python
try:
    verify_result = await asyncio.wait_for(
        self._verify_action_effect(before_screenshot),
        timeout=5.0,
    )
except asyncio.TimeoutError:
    verify_result = {"changed": None, "pixel_diff": None, "timeout": True}
    self._metrics["screenshot_timeouts"] += 1
```

2. **加入 metrics counter**：追蹤 screenshot fallback 觸發次數、平均耗時、timeout 次數，寫入 session summary：

```python
@dataclass
class ActionMetrics:
    total_actions: int = 0
    screenshot_fallbacks: int = 0
    screenshot_timeouts: int = 0
    avg_verify_ms: float = 0.0
```

3. **Adaptive cooldown**：若連續 N 次截圖超時（代表 WebGL context 不穩定），自動延長 `action_cooldown` 讓 GPU 恢復，而非固定 500ms。

**參考資料**：
- Python asyncio.wait_for 官方文件：https://docs.python.org/3/library/asyncio-task.html#asyncio.wait_for
- Playwright timeout 最佳實踐（per-action timeout vs global timeout）：https://playwright.dev/python/docs/browser-contexts
- resilient-api-client（per-endpoint timeout + structured metrics）：https://github.com/jensonjose/resilient-api-client

---

## 風險優先級摘要

| # | 建議 | 嚴重度 | 對應 AD | 實作複雜度 |
|---|------|--------|---------|-----------|
| 1 | Vision circuit breaker | 🔴 高 | AD-9 | 中（引入套件 + 裝飾器） |
| 2 | Per-session cost budget | 🔴 高 | AD-9 | 中（limiter 整合進 vision.py） |
| 3 | YAML async I/O + 批次 | 🟡 中 | — | 低（to_thread 一行） |
| 4 | Browser pool 併發 | 🟡 中 | — | 高（架構改動） |
| 5 | Screenshot timeout cap | 🟡 中 | AD-4 | 低（wait_for 包裝） |

建議優先處理 #1 和 #2（Vision API 韌性），這是目前測試可靠性的最大風險點。#3 和 #5 是低成本快速改善。#4 待 CI 平行化需求明確後再投入。
