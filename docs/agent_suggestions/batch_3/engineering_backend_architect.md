# Backend Architect 審查建議（Batch 3）

> 審查角色：Backend Architect（可擴展性、可靠性、可觀測性、API 契約、成本控制）
> 日期：2026-07-16

---

## 1. Persistence Layer：從 naive file write 升級為安全寫入

### 現況問題

`knowledge_base.py` 的 `save_runtime()` 是裸 `open() + yaml.dump()`，無 file lock、無 atomic rename。Perf-defender 確認：多 session 平行跑同一遊戲時有 race condition，runtime YAML 會互相覆蓋。1MB+ YAML parse time 約 200-400ms，若未來每步 reload 會成瓶頸。

### 建議方案

**短期（single-session 防護）**：採用 `portalocker` 做 exclusive file lock + atomic write（先寫 `.tmp` 再 `os.replace()`），確保即使程式 crash 也不會留下半寫檔案。

```python
import portalocker, os, tempfile

def safe_yaml_dump(data, filepath):
    dir_path = os.path.dirname(filepath)
    with tempfile.NamedTemporaryFile('w', dir=dir_path, delete=False, suffix='.tmp') as tmp:
        yaml.dump(data, tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, filepath)  # atomic on same filesystem
```

**中期（multi-session）**：改用 SQLite WAL mode 作為 knowledge 儲存後端，搭配 `PRAGMA busy_timeout=5000` 與 app-level lock。SQLite 在 WAL mode 下支援多 reader + 單 writer 且不會 corruption。

### 參考資料

- portalocker 文件與跨平台 file locking API：https://portalocker.readthedocs.io/en/latest/
- SQLite concurrent writes 深度分析（WAL mode、busy_timeout、app-level lock 最佳實踐）：https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/
- 實戰案例：SQLite + portalocker 做 process-safe resource pool：https://medium.com/@harshoo3009/still-managing-test-accounts-from-json-files-72d483c5b6dc

---

## 2. Vision API 可靠性：加入 Circuit Breaker + Jitter

### 現況問題

Perf-defender 確認已有 exponential backoff retry（3 次）+ graceful fallback，但缺少：
- **Circuit breaker** — gateway 持續 502 時每步仍嘗試 3 次 retry，浪費 ~14 秒/步
- **Jitter** — 確定性 backoff 在多 client 時會 thundering herd
- **Dead letter** — fallback 後分析結果就丟失

### 建議方案

採用 `pyresilience`（Python 版 Resilience4j）統一管理 retry + circuit breaker + timeout + fallback，一個 decorator 解決所有 pattern 且 pattern 間共享狀態：

```python
from pyresilience import resilient, RetryConfig, TimeoutConfig, CircuitBreakerConfig, FallbackConfig

@resilient(
    retry=RetryConfig(max_attempts=3, delay=2.0, backoff_factor=2.0, jitter=True),
    timeout=TimeoutConfig(seconds=60),
    circuit_breaker=CircuitBreakerConfig(
        failure_threshold=5,       # 5 次連續失敗 → open
        recovery_timeout=60,       # 60 秒後 half-open 試一次
    ),
    fallback=FallbackConfig(
        handler=lambda e: _structured_fallback(),
        fallback_on=[Exception],
    ),
)
async def call_vision_api(payload):
    ...
```

優勢：circuit breaker 狀態跨 retry 共享，open 時直接走 fallback 不浪費 14 秒；內建 Prometheus / OpenTelemetry 支援；async native；benchmark 顯示 overhead 僅 0.64μs/call。

### 參考資料

- pyresilience — 統一 7 種 resilience pattern 的 Python 庫（含 benchmark vs tenacity/pybreaker）：https://github.com/AhsanSheraz/pyresilience
- pybreaker — 經典 Python circuit breaker 實作（Redis backing 可選）：https://github.com/danielfm/pybreaker
- Python 社群討論：如何協調 retry + circuit breaker + timeout：https://discuss.python.org/t/how-are-you-coordinating-resilience-patterns-retry-circuit-breaker-timeout-in-python/106597

---

## 3. Observability：導入 structlog + session correlation ID

### 現況問題

Perf-defender 坦承這是「最大的 operational readiness gap」：
- 僅有 `logging.getLogger()` + f-string，無 structured logging
- 無 correlation ID / trace ID
- 無 API call duration metric
- Debug 僅靠 HTML report 事後人工回溯

### 建議方案

導入 `structlog`，在 session 入口 bind `session_id` 作為 correlation ID，所有下游 log 自動攜帶。每次 Vision 呼叫記錄 duration、token count、cost：

```python
import structlog
from uuid import uuid4

# 初始化（一次性）
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
)

# Session 入口
async def start(self):
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        session_id=str(uuid4()),
        game=self.game_name,
    )
    log = structlog.get_logger()
    log.info("session_started", game_url=self.game_url)
```

Vision 呼叫加計時：

```python
import time

async def analyze_screenshot_structured(self, ...):
    log = structlog.get_logger()
    t0 = time.perf_counter()
    try:
        result = await self._call_api(...)
        duration_ms = (time.perf_counter() - t0) * 1000
        log.info("vision_call_completed", duration_ms=duration_ms, tokens=result.get("usage"))
        return result
    except Exception as e:
        duration_ms = (time.perf_counter() - t0) * 1000
        log.error("vision_call_failed", duration_ms=duration_ms, error=str(e))
        raise
```

JSON log 可直接餵 Datadog/Loki/Elasticsearch 做查詢與告警。

### 參考資料

- structlog contextvars 文件（async-safe correlation ID propagation）：https://www.structlog.org/en/24.4.0/contextvars.html
- AI 應用 structured logging 最佳實踐（structlog + cost tracking）：https://callsphere.ai/blog/python-logging-ai-applications-structured-logs-structlog-loguru
- 完整範例：structlog + OpenTelemetry + correlation ID 整合：https://github.com/bossjones/logging-lab/blob/main/src/logging_lab/logging_config.py

---

## 4. API Contract：Vision Gateway Schema Drift 偵測

### 現況問題

`vision.py` 透過 Anthropic SDK 呼叫 gateway，無正式 OpenAPI spec、無 contract test。Schema 變更只在 runtime parse 失敗時才被發現（靜默走 fallback）——可能數天不被察覺。

### 建議方案

**方案 A（推薦）— Response schema 驗證 + 告警**：

在 `_parse_vision_response()` 中加入 Pydantic model 驗證。Schema 不符時不只 fallback，還要結構化 log 告警：

```python
from pydantic import BaseModel, ValidationError

class VisionResponse(BaseModel):
    screen_id: str
    elements: list[dict] = []
    game_state: dict = {}
    suggested_action: dict | None = None

def _parse_vision_response(self, raw):
    try:
        validated = VisionResponse.model_validate(raw)
        return validated.model_dump()
    except ValidationError as e:
        log.warning("vision_schema_drift_detected", errors=e.errors())
        # 仍走 fallback，但現在有明確告警
        return self._structured_fallback()
```

**方案 B — Schemathesis contract test（CI 級）**：

若 gateway 有 OpenAPI spec，用 `schemathesis` 做 property-based contract testing，自動生成邊界情境驗證 response schema：

```python
import schemathesis
schema = schemathesis.openapi.from_url("http://gateway/openapi.json")

@schema.parametrize()
def test_vision_api(case):
    case.call_and_validate()
```

### 參考資料

- Schemathesis — 從 OpenAPI spec 自動產生 property-based API test：https://schemathesis.io/
- Schemathesis GitHub（stateful testing、schema violation detection）：https://github.com/schemathesis/schemathesis
- Dredd — 語言無關的 API description 驗證框架：https://dredd.org/en/latest/

---

## 5. Cost Budget Enforcement：Per-Session 硬性花費上限

### 現況問題

AD-9 自己承認「待補」。目前 Vision 呼叫頻率僅由架構性緩解控制（adaptive observe skip_threshold），無 per-session call counter、token accumulator、或任何硬性上限。高動態遊戲畫面可能觸發數百次 Vision 呼叫。

### 建議方案

**方案 A（輕量自建）— config-driven call/token cap**：

在 `config/default.yaml` 加入：

```yaml
vision:
  budget:
    max_calls_per_session: 100
    max_tokens_per_session: 500000  # ~$2.5 at Claude pricing
    action_on_exceed: "degrade"     # degrade | warn | block
```

在 `vision.py` 加 counter：

```python
class VisionClient:
    def __init__(self, config):
        self._call_count = 0
        self._token_count = 0
        self._budget = config.get("vision.budget", {})

    async def analyze(self, ...):
        max_calls = self._budget.get("max_calls_per_session", float("inf"))
        if self._call_count >= max_calls:
            log.warning("vision_budget_exceeded", calls=self._call_count)
            return self._structured_fallback()
        ...
        self._call_count += 1
        self._token_count += response_tokens
```

**方案 B（成熟方案）— 採用 `tokencap` 或 `llm-token-guardian`**：

```python
import tokencap

# Wrap Anthropic client with 50K token session budget
client = tokencap.wrap(
    anthropic.Anthropic(),
    policy=tokencap.Policy(dimensions={
        "session": tokencap.DimensionPolicy(
            limit=500_000,
            thresholds=[
                tokencap.Threshold(at_pct=0.8, actions=[tokencap.Action(kind=tokencap.ActionKind.WARN)]),
                tokencap.Threshold(at_pct=0.95, actions=[tokencap.Action(kind=tokencap.ActionKind.DEGRADE, degrade_to="claude-haiku-4-5")]),
                tokencap.Threshold(at_pct=1.0, actions=[tokencap.Action(kind=tokencap.ActionKind.BLOCK)]),
            ],
        ),
    }),
)
```

優勢：80% 時警告、95% 時自動降級到便宜模型、100% 時 block；token 精確計量來自 API response；SQLite backend 持久化。

### 參考資料

- tokencap — per-session token budget enforcement（warn → degrade → block 三階段策略）：https://github.com/pykul/tokencap
- llm-token-guardian — pre-call cost estimation + session budget tracking：https://github.com/iamsaugatpandey/llm-token-guardian
- LiteLLM Agent Gateway — per-session budget cap + rate limits 設計參考：https://docs.litellm.ai/docs/proxy/users

---

## 總結優先序

| # | 建議 | 影響 | 複雜度 | 建議優先 |
|---|------|------|--------|----------|
| 3 | Observability（structlog） | 解鎖所有 debug/監控能力 | 低 | P0 |
| 5 | Cost budget enforcement | 防止不可控花費 | 低-中 | P0 |
| 2 | Circuit breaker（pyresilience） | 減少 gateway 故障時的延遲浪費 | 中 | P1 |
| 4 | Schema drift detection | 防止靜默降級被忽視 | 低 | P1 |
| 1 | Persistence safety | 多 session 場景才觸發 | 中 | P2 |
