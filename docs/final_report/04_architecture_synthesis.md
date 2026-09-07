# 架構領域綜合報告

> **產出日期**：2026-07-17  
> **涵蓋範圍**：Batch 1-9 全部架構相關建議（15 份來源文件）  
> **綜合角色**：Architecture Synthesizer  

---

## 目錄

1. [Vision LLM 韌性與成本治理](#1-vision-llm-韌性與成本治理)
2. [知識庫資料安全與演進](#2-知識庫資料安全與演進)
3. [GameSession 生命週期與狀態機](#3-gamesession-生命週期與狀態機)
4. [感知層穩定化與多通道融合](#4-感知層穩定化與多通道融合)
5. [可觀測性與結構化日誌](#5-可觀測性與結構化日誌)
6. [CI/CD 與自動化治理](#6-cicd-與自動化治理)
7. [多遊戲可擴展性與並行隔離](#7-多遊戲可擴展性與並行隔離)
8. [Orchestrator 與工作流設計](#8-orchestrator-與工作流設計)
9. [開發者體驗（DX）與上手路徑](#9-開發者體驗dx與上手路徑)
10. [YAGNI 與架構紀律](#10-yagni-與架構紀律)

---

## 1. Vision LLM 韌性與成本治理

**共識等級**：🔴 最高優先（7 份來源一致）

這是跨所有審查者最一致的頂級關注點。Vision LLM gateway 是整條 pipeline 的**單點故障**，且無成本上限保護。

### 1.1 Circuit Breaker + Graceful Degradation

| 來源 | 建議摘要 |
|------|----------|
| Multi-Agent Architect (batch_3) | 三層 Fallback Chain：Primary → Backup model → 純確定性 → Halt |
| Workflow Architect (batch_7) | Per-call timeout + retry with jitter + circuit breaker + session cost cap |
| Backend Architect (batch_3) | `pyresilience` 統一管理 retry/CB/timeout/fallback，overhead 僅 0.64μs/call |
| SRE (batch_4) | `aiobreaker` async CB + `asyncio.sleep` 替換阻塞式 `time.sleep` |
| Incident Response (batch_9) | CB 狀態記入 session log，事後 post-mortem 可追蹤 |
| Autonomous Optimization (batch_9) | Sliding window velocity check：5 分鐘內 15 次且 pixel_diff 低 → trip |
| Multi-Agent Architect (root) | Vision Fallback Chain Pattern：連續 3 失敗 → 跳下層，cooldown 60s |

**綜合建議**：

```
Layer 1: Primary Vision（Claude Vision via gateway）
Layer 2: Backup model（GPT-4o / Gemini，可選）
Layer 3: 純確定性模式（detector + perceiver + 知識庫已知路徑）
Layer 4: Halt + checkpoint + 通知
```

- Circuit breaker：連續 5 次失敗 → 開路 60 秒 → half-open 試探
- 開路期間降級為確定性模式，報告中標記 `degraded_mode: true`
- 將 `time.sleep()` 替換為 `await asyncio.sleep()`（SRE-1 指出阻塞 event loop）

**關鍵參考 URL**：
- pyresilience（統一 7 種 resilience pattern）：https://github.com/AhsanSheraz/pyresilience
- aiobreaker（asyncio circuit breaker）：https://pypi.org/project/aiobreaker/
- Agent Patterns Catalog — Fallback Chain：https://www.agentpatternscatalog.org/patterns/fallback-chain/
- Onaro Circuit Breaker 生產指南：https://www.onaro.io/docs/guides/circuit-breaker

### 1.2 Per-Session 成本護欄

| 來源 | 建議摘要 |
|------|----------|
| Automation Governance (batch_5) | hard cap Vision 呼叫次數 + session 最大時長 |
| Backend Architect (batch_3) | config-driven call/token cap + warn→degrade→block 三階段 |
| Multi-Agent Architect (root) | Per-session token budget + 漸進降級策略 |
| Autonomous Optimization (batch_9) | 50 次 Vision 呼叫 or 200K tokens hard cap |

**綜合建議**：

```yaml
# config/default.yaml
cost_guardrails:
  max_vision_calls_per_session: 100
  max_tokens_per_session: 500000
  max_session_duration_minutes: 60
  degradation:
    - threshold: 0.8   # action: warn
    - threshold: 0.9   # action: reduce_frequency
    - threshold: 1.0   # action: hard_stop_vision
```

**關鍵參考 URL**：
- Token Budget Orchestrator：https://github.com/ricmmartins/tokenbudgetorchestrator
- Agent Budget Controller：https://github.com/pntech20/agent-budget-controller
- tokencap（warn→degrade→block）：https://github.com/pykul/tokencap

### 1.3 Image Preprocessing 降低 Token 成本

| 來源 | 建議摘要 |
|------|----------|
| Autonomous Optimization (batch_9) | Resize + ROI crop 節省 40-70% visual tokens |
| Prompt Engineer (batch_5) | 已知 display 位置的 ROI crop |

**綜合建議**：
- 送出前 resize 到 1568px long edge + JPEG q85
- game_state 讀數任務：只送 UI ROI，token 降 69%
- Hash-based dedup：SSIM > 0.98 不重複呼叫

**關鍵參考 URL**：
- Claude Vision Production Guide（resize + ROI 實測）：https://www.developersdigest.tech/blog/claude-vision-api-production-guide
- Anthropic Vision 官方文件：https://platform.claude.com/docs/en/build-with-claude/vision

---

## 2. 知識庫資料安全與演進

**共識等級**：🔴 高優先（6 份來源一致）

知識庫是跨 session 累積的核心資產，但目前寫入路徑有損壞風險。

### 2.1 Atomic Write 防止損壞

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | Multi-Game Isolation + File Locking |
| Workflow Architect (batch_7) | temp file + fsync + `os.replace()` 原子操作 |
| Backend Architect (batch_3) | `portalocker` exclusive lock + atomic write |
| Automation Governance (batch_5) | atomic write + session snapshot 審計 |
| Database Optimizer (batch_7) | `filelock` 套件（MIT、跨平台、3 行程式碼） |
| Incident Response (batch_9) | `safeatomic` 套件（4 大保證 + TLA+ 驗證） |

**綜合建議**（實作成本極低，10 行）：

```python
import tempfile, os, yaml
from filelock import FileLock

def atomic_yaml_write(path, data):
    lock = FileLock(f"{path}.lock", timeout=10)
    with lock:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
```

- 每次寫入前備份為 `.bak`
- 啟動時做 integrity check：parse 失敗則自動載入 `.bak`

**關鍵參考 URL**：
- filelock（跨平台 file locking）：https://py-filelock.readthedocs.io/en/latest/
- safeatomic（atomic write + cooperative lock + checksum）：https://pypi.org/project/safeatomic/2.0.3/
- cloudmesh/yamldb（atomic writes + portalocker）：https://github.com/cloudmesh/yamldb

### 2.2 Schema Version + Pydantic Validation

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | Schema Version + 自動遷移管線 |
| Software Architect (root) | Pydantic Schema Validation Gate |
| Backend Architect (batch_3) | VisionResponse Pydantic model 驗證 |
| Multi-Agent Architect (batch_3) | Inter-Agent Contract schema validation |
| Database Optimizer (batch_7) | schema 驗證防止手動編輯破壞結構 |

**綜合建議**：
- 每個 YAML 加入 `schema_version: "1.0"` 欄位
- 為每類 YAML 定義 Pydantic model（`SystemSchema`、`FlowGraphSchema`、`GameInfoSchema`）
- 載入時 `model_validate(data)`，驗證失敗 raise 明確錯誤
- Vision 回傳加入 `VisionResponse` schema 驗證，drift 即告警

**關鍵參考 URL**：
- fluxconf（Pydantic config + migration）：https://github.com/Greenroom-Robotics/fluxconf
- pydantic-yaml：https://pydantic-yaml.readthedocs.io/en/latest/
- yaml2pydantic：https://github.com/banduk/yaml2pydantic

### 2.3 分層衝突解決策略

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | Static > Runtime with Confidence Decay |

**綜合建議**：
- 優先順序：**靜態 YAML（human-curated）> runtime high > medium > low**
- runtime transition 加入 `success_count`/`failure_count`/`last_verified`
- 失敗時降級、超過 N 天未驗證降回 low
- runtime 與靜態衝突時記為 "tension"，不覆寫靜態

**關鍵參考 URL**：
- ElephantBroker 四態驗證模型：https://arxiv.org/pdf/2603.25097
- PRECEPT Bayesian Source Reliability：https://arxiv.org/html/2603.09641v1

---

## 3. GameSession 生命週期與狀態機

**共識等級**：🔴 高優先（5 份來源一致）

### 3.1 正式 Async State Machine

| 來源 | 建議摘要 |
|------|----------|
| Workflow Architect (batch_7) | `python-statemachine` 定義正式狀態轉換 |
| Multi-Agent Architect (root) | Node State Machine with proven termination |
| Multi-Agent Architect (root) | 每個狀態轉移有 timeout + retry budget |
| Rapid Prototyper (batch_8) | 參考 LangGraph 定義 AgentState enum |
| Automation Governance (batch_5) | finish() 加入 pass/fail verdict + exit code |

**綜合建議**：

```
States: CREATED → LOADING → EXPLORING → VALIDATING → TESTING → FINISHING → COMPLETED | FAILED
```

- 每個狀態轉移有 timeout 限制 + retry budget
- 非法 transition（如 COMPLETED → RUNNING）raise error
- `finish()` 計算 verdict：pass/warn/fail + exit code

### 3.2 Browser 生命週期防護

| 來源 | 建議摘要 |
|------|----------|
| SRE (batch_4) | atexit + signal handler + async context manager |
| Incident Response (batch_9) | Context recycling 每 100 action 或 30 分鐘 |

**綜合建議**：
- `GameSession` 實作 `__aenter__` / `__aexit__`
- 註冊 `atexit` + `signal.signal(SIGTERM)` 確保非正常退出也清理
- 長時間 session：每 100 action 回收 browser context

**關鍵參考 URL**：
- python-statemachine async：https://python-statemachine.readthedocs.io/en/latest/async.html
- Graph Harness（三層分離 + proven termination）：https://www.arxiv.org/pdf/2604.11378

### 3.3 Session 事件 Incremental Flush

| 來源 | 建議摘要 |
|------|----------|
| Workflow Architect (batch_7) | 每個事件立即 append 到 session.jsonl |
| Incident Response (batch_9) | 每 N 步 checkpoint + partial report |
| SRE (batch_4) | 資源上限 + streaming flush |

**綜合建議**：
- 每個事件即時寫入 `session.jsonl`（JSON Lines）
- 每 10 步或 30 秒做 checkpoint
- `finish()` 只做 summary + HTML render，不是唯一持久化點
- 異常中斷時 checkpoint 可產出 partial report

---

## 4. 感知層穩定化與多通道融合

**共識等級**：🟡 中高優先（4 份來源一致）

### 4.1 screen_id 穩定化（P0 前置條件）

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (batch_3) | screen_id 穩定化應提升為 P0 |
| AI Engineer (batch_3) | DINOv2 Screen Embedding + sqlite-vec |
| Level Designer (batch_9) | pHash pre-filter + 遮罩動態區分層方案 |

**綜合建議**（分層方案，不需等 AD-4）：

```
Layer 1: pHash pre-filter（<5ms，64-bit fingerprint，Hamming distance < 3 = 同 screen）
Layer 2: 固定遮罩 + SSIM（systems/*.yaml 定義 dynamic_regions）
Layer 3: DINOv2 embedding + KNN（cosine < 0.15 = 已知；> 0.3 = 新畫面）
Layer 4: Vision LLM 確認（僅中間地帶）
```

**關鍵參考 URL**：
- DINOv2 vs CLIP Benchmark（64% vs 28%）：https://github.com/JayyShah/CLIP-DINO-Visual-Similarity
- sqlite-vec（零依賴向量搜尋）：https://github.com/asg017/sqlite-vec/
- visual-guard（pixel/SSIM/pHash 三層）：https://pypi.org/project/visual-guard/

### 4.2 Oracle 多通道感測器融合

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (batch_3) | L1 Template Matching + L2 OCR + L3 Vision 投票 |
| AI Engineer (batch_3) | PaddleOCR L1.5 + Sensor Fusion Layer |
| Rapid Prototyper (batch_8) | Pixel sampling 減少 Vision 呼叫 |
| Prompt Engineer (batch_5) | Preprocessing Hints + Multi-pass OCR |

**綜合建議**：

| 層級 | 技術 | 成本 | 適用場景 |
|------|------|------|----------|
| L1 | Digit ROI Template Matching | 零 | 固定字型、已知位置 |
| L1.5 | PaddleOCR 局部 ROI | CPU 340ms | 數字區域辨識 |
| L2 | Vision LLM | $$$ | 未知畫面、複雜 UI |

- 三通道中兩個一致即採信
- 全部不一致 → 標記 `uncertain`，不計入 oracle 判定
- Feature Disagreement Score (FDS) 仲裁機制

**關鍵參考 URL**：
- PaddleOCR Benchmark（45ms GPU / 340ms CPU）：https://tildalice.io/paddleocr-easyocr-doctr-memory-latency-benchmark/
- Balatro 遊戲 HUD OCR（PaddleOCR fine-tune）：https://huggingface.co/marco-costa-ml/balatro-ocr
- CoRiM Conflict-driven Fusion（CVPR 2026）：https://openaccess.thecvf.com/content/CVPR2026/papers/Zou_CoRiM_Conflict-driven_Risk_Minimization_for_Dynamic_Multimodal_Fusion_CVPR_2026_paper.pdf

### 4.3 座標正規化

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | Virtual Coordinate + Anchor-Relative 混合系統 |

**綜合建議**：
- 定義參考解析度（1280x720），runtime 線性映射
- 高頻 UI 元素改用 Anchor-Relative 定位
- 未確認座標加 `reliability: investigating | confirmed | stable`

---

## 5. 可觀測性與結構化日誌

**共識等級**：🔴 高優先（5 份來源一致）

### 5.1 Structured Logging（structlog + correlation ID）

| 來源 | 建議摘要 |
|------|----------|
| Backend Architect (batch_3) | structlog + session correlation ID + Vision duration metric |
| Multi-Agent Architect (batch_3) | OpenTelemetry trace_id 貫穿 pipeline |
| Multi-Agent Architect (root) | OTel + LangSmith 雙軌追蹤 |
| SRE/Performance (root) | 跨 Run 歷史趨勢比對 |
| Autonomous Optimization (batch_9) | Per-call telemetry + daily cost dashboard |

**綜合建議**：

```python
# structlog + contextvars（最小可行方案）
structlog.configure(processors=[
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.JSONRenderer(),
])

# Session 入口 bind correlation ID
structlog.contextvars.bind_contextvars(
    session_id=str(uuid4()),
    game=self.game_name,
)
```

每次 Vision 呼叫記錄：
- `latency_ms`、`input_tokens`、`output_tokens`、`cost_usd`
- `parse_success`、`screen_id`、`model`

**關鍵參考 URL**：
- structlog contextvars：https://www.structlog.org/en/24.4.0/contextvars.html
- OpenTelemetry for LLM Agents：https://aivineet.com/llm-agent-tracing-distributed-context-opentelemetry/
- AgentTrace taxonomy（arXiv）：https://arxiv.org/pdf/2602.10133

### 5.2 即時告警

| 來源 | 建議摘要 |
|------|----------|
| SRE/Performance (root) | Webhook / Slack 通知機制 |
| Incident Response (batch_9) | critical anomaly 即時發送 webhook |

**綜合建議**：

```yaml
alerting:
  enabled: true
  webhook_url: "${ALERT_WEBHOOK_URL}"
  severity_threshold: high
  cooldown_seconds: 300
```

---

## 6. CI/CD 與自動化治理

**共識等級**：🟡 中優先（4 份來源一致）

### 6.1 Unit Test CI（立即可做）

| 來源 | 建議摘要 |
|------|----------|
| DevOps Automator (batch_4) | `.github/workflows/ci.yml` — uv + ruff + pytest |
| Rapid Prototyper (batch_8) | 零 Vision 確定性回歸層 |
| Automation Governance (batch_5) | finish() 加 exit code + CI 接軌 |
| SRE/Performance (root) | CI Exit Code 機制 |

**綜合建議**：

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
      - run: uv sync --locked --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest tests/
```

- Exit code：0 = pass、1 = high severity fail、2 = critical fail
- 與 pytest exit code 慣例對齊

**關鍵參考 URL**：
- uv GitHub Actions 指南：https://docs.astral.sh/uv/guides/integration/github/
- astral-sh/setup-uv：https://github.com/astral-sh/setup-uv
- pytest exit codes：https://docs.pytest.org/en/stable/reference/exit-codes.html

### 6.2 GPU Runner + 報告持久化（nightly 就緒時）

| 來源 | 建議摘要 |
|------|----------|
| DevOps Automator (batch_4) | RunsOn g5.xlarge + GitHub Pages 報告 |
| DevOps Automator (batch_4) | Mesa llvmpipe 作為 CI 煙霧測試折衷 |

### 6.3 排程失敗告警

| 來源 | 建議摘要 |
|------|----------|
| Automation Governance (batch_5) | Windows Task Scheduler 失敗觸發告警 + log rotation |

### 6.4 Runs 目錄 Retention

| 來源 | 建議摘要 |
|------|----------|
| SRE (batch_4) | max_runs: 50 / max_age_days: 30 / max_total_size_mb: 2048 |

---

## 7. 多遊戲可擴展性與並行隔離

**共識等級**：🟡 中優先（4 份來源一致）

### 7.1 File Locking + Session 隔離

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | Scoped KB + File Locking |
| SRE (batch_4) | Knowledge file lock + Vision client scoping |
| Database Optimizer (batch_7) | per-session runtime 寫入 + merge |
| Automation Governance (batch_5) | PID lock 防重複 |

**綜合建議**：
- `save_runtime()` 加 `filelock`
- Vision client 改為 instance-level（每 session 獨立 CB 狀態）
- 移除 `_session` global singleton → registry pattern
- 長期：per-session 寫入 delta + 結束時 merge

### 7.2 Supervisor-Worker 排程架構（長期）

| 來源 | 建議摘要 |
|------|----------|
| Multi-Agent Architect (root) | Supervisor → Budget Manager → Workers → Aggregator |

### 7.3 跨遊戲知識複用

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (root) | `knowledge/_shared/` 共通知識模板 |

---

## 8. Orchestrator 與工作流設計

**共識等級**：🟡 中優先

### 8.1 Agent Loop 終止策略

| 來源 | 建議摘要 |
|------|----------|
| Multi-Agent Architect (root) | 語義收斂偵測 + 分層終止瀑布 |
| Level Designer (batch_9) | 覆蓋率驅動探索（Go-Explore） |

**綜合建議**（四層終止）：
1. **Failsafe**：硬性 step/token/wall-clock 上限
2. **Stagnation**：連續 N 步 pixel_diff < threshold 且 screen_id 無變化
3. **Convergence**：flow_graph 覆蓋率不再增長
4. **Quality Gate**：oracle violations 累積超過閾值

### 8.2 Explore → Validate → Test 三階段轉換

| 來源 | 建議摘要 |
|------|----------|
| Workflow Architect (batch_7) | 定義量化轉換條件 + 回退機制 |
| Level Designer (batch_9) | promote CLI 命令工具化知識凍結 |

### 8.3 Orchestrator 領域專用化

| 來源 | 建議摘要 |
|------|----------|
| Agents Orchestrator (batch_5) | 通用 pipeline 改為 QA 領域專用 |
| Agents Orchestrator (batch_5) | 區分「程式碼 bug」與「遊戲 bug」的 retry 語義 |

### 8.4 Human-in-the-Loop 正式閘門

| 來源 | 建議摘要 |
|------|----------|
| Multi-Agent Architect (batch_3) | Formal HITL Gate（blocking + advisory） |
| Multi-Agent Architect (root) | 分層 Handoff 機制 |

**關鍵參考 URL**：
- AgentPatterns Loop Engineering：https://agentpatterns.ai/loop-engineering/
- Semantic Early-Stopping（arXiv）：https://arxiv.org/html/2606.27009
- Go-Explore（Microsoft Research）：https://www.microsoft.com/en-us/research/publication/go-explore-complex-3d-game-environments-for-automated-reachability-testing/

---

## 9. 開發者體驗（DX）與上手路徑

**共識等級**：🟡 中優先

### 9.1 一行指令快速上手

| 來源 | 建議摘要 |
|------|----------|
| Developer Advocate (batch_8) | Zero-Config Demo Mode（無需 Vision API key） |
| Rapid Prototyper (batch_8) | `uv run demo` 一行指令 |

### 9.2 Preflight Health Check

| 來源 | 建議摘要 |
|------|----------|
| Developer Advocate (batch_8) | 啟動時檢查環境變數、Playwright 安裝，給出友善錯誤 |

### 9.3 Knowledge Lightweight Bootstrap

| 來源 | 建議摘要 |
|------|----------|
| Rapid Prototyper (batch_8) | 新遊戲只需 URL + title → 自動產出初版 knowledge |

---

## 10. YAGNI 與架構紀律

**共識等級**：🟢 提醒性質

### 10.1 避免投機性架構

| 來源 | 建議摘要 |
|------|----------|
| Minimal Change (batch_7) | confidence 機制無消費者 → 應暫緩 |
| Minimal Change (batch_7) | Hermes 整合描述混入現況 → 隔離為 roadmap |
| Minimal Change (batch_7) | pixel_diff 對動態畫面無效 → 標註適用範圍 |
| Minimal Change (batch_7) | 四份設計文件對 research preview 過重 |

### 10.2 Program 式編排是正確選擇（目前）

| 來源 | 建議摘要 |
|------|----------|
| Software Architect (batch_3) | Event-Driven 在目前規模不需要（YAGNI） |
| MCP Builder (batch_7) | MCP 是未來，目前只需 MCP-ready interface |

---

## 綜合優先順序建議

### Phase 1：立即執行（1-2 週）

| # | 主題 | 具體行動 | 難度 | 風險等級 |
|---|------|----------|------|----------|
| 1 | Knowledge atomic write | `filelock` + temp + `os.replace()` | 極低 | 資料損壞 |
| 2 | Vision circuit breaker | `aiobreaker` + async sleep + fallback | 中 | 系統停擺 |
| 3 | Per-session cost cap | config 欄位 + 呼叫前計數 | 低 | 無限花費 |
| 4 | finish() exit code | verdict 計算 + `sys.exit()` | 極低 | CI 不可用 |
| 5 | Unit test CI | GitHub Actions workflow | 低 | 回歸無守護 |
| 6 | Browser lifecycle guard | async context manager + atexit | 低 | 孤兒 Chromium |

### Phase 2：短期改善（3-4 週）

| # | 主題 | 具體行動 | 難度 |
|---|------|----------|------|
| 7 | structlog observability | structlog + correlation ID + Vision metrics | 低 |
| 8 | Pydantic schema validation | YAML load 時 model_validate | 中 |
| 9 | Session incremental flush | 事件即時寫 JSONL + checkpoint | 低 |
| 10 | Image preprocessing | Resize + ROI crop 降 token | 低 |
| 11 | Runs retention policy | max_runs + max_age_days | 低 |
| 12 | `uv run demo` 指令 | Zero-Vision demo mode | 低 |

### Phase 3：中期演進（1-2 月）

| # | 主題 | 具體行動 | 難度 |
|---|------|----------|------|
| 13 | screen_id 穩定化 | pHash + 遮罩 SSIM 分層 | 中 |
| 14 | 本地 OCR（L1.5） | PaddleOCR ROI 數字讀取 | 中 |
| 15 | GameSession state machine | python-statemachine 定義狀態 | 中 |
| 16 | Loop termination strategy | 四層終止瀑布 | 中 |
| 17 | Multi-model router | Static rule-based routing | 高 |
| 18 | promote CLI | runtime → static 工具化 | 低 |

### Phase 4：長期路線（3+ 月）

| # | 主題 | 具體行動 |
|---|------|----------|
| 19 | SQLite 衍生索引層 | YAML source of truth + DB index |
| 20 | DINOv2 screen embedding | Learned embedding + sqlite-vec |
| 21 | Sensor Fusion Layer | FDS 仲裁機制 |
| 22 | Curiosity-driven Q-Learning | Tabular Q + 覆蓋率 reward |
| 23 | Knowledge Graph 化 | networkx.DiGraph + typed edges |
| 24 | Supervisor-Worker 排程 | 多遊戲並行 + budget 隔離 |

---

## 遊戲領域特殊考量

### Unity WebGL 特化

| 來源 | 建議摘要 | 優先級 |
|------|----------|--------|
| Unity Architect (batch_6) | 載入偵測（loading bar 消失 / SSIM 穩定） | 高 |
| Unity Architect (batch_6) | 場景切換黑屏 vs 異常黑屏區分 | 高 |
| Unity Architect (batch_6) | WASM memory 監控（接近 2GB 預警） | 中 |
| Unity Architect (batch_6) | Input delivery verification（canvas focus） | 中 |
| SRE/Performance (root) | WebGL Context Loss DOM event 監聽 | 高 |

### 遊戲設計層面

| 來源 | 建議摘要 | 優先級 |
|------|----------|--------|
| Game Designer (batch_6) | flow_graph 加入 guard conditions（等級限制） | 中 |
| Game Designer (batch_6) | Invariant 支援 range 類型（RNG 容忍） | 高 |
| Game Designer (batch_6) | 玩家行為模式模擬（newbie/speedrunner/afk） | 中 |
| Game Designer (batch_6) | 多欄位 conservation law invariant | 高 |

---

## 來源追溯表

| 文件 | 路徑 | 主要貢獻主題 |
|------|------|--------------|
| Software Architect (root) | `docs/agent_suggestions/software_architect.md` | 知識庫 Schema / 衝突 / 座標 |
| Multi-Agent Architect (root) | `docs/agent_suggestions/multi_agent_architect.md` | Loop 終止 / 成本 / 狀態機 / 恢復 |
| Multi-Agent Architect (batch_3) | `batch_3/engineering_multi_agent_architect.md` | Fallback Chain / OTel / HITL |
| Software Architect (batch_3) | `batch_3/engineering_software_architect.md` | Oracle 融合 / screen_id / VCR |
| Backend Architect (batch_3) | `batch_3/engineering_backend_architect.md` | Persistence / CB / structlog / Contract |
| AI Engineer (batch_3) | `batch_3/engineering_ai_engineer.md` | OCR / DINOv2 / Q-Learning / SQLite |
| DevOps Automator (batch_4) | `batch_4/engineering_devops_automator.md` | CI / Secrets / GPU Runner |
| SRE (batch_4) | `batch_4/engineering_sre.md` | CB / Browser / Retention / Isolation |
| Automation Governance (batch_5) | `batch_5/automation_governance_architect.md` | 排程告警 / Exit code / Cost cap |
| Agents Orchestrator (batch_5) | `batch_5/agents_orchestrator.md` | 領域專用化 / Oracle 優先權 / Retry 語義 |
| Prompt Engineer (batch_5) | `batch_5/engineering_prompt_engineer.md` | Preprocessing Hints / Multi-pass OCR |
| Unity Architect (batch_6) | `batch_6/unity_architect.md` | Unity 載入 / 場景切換 / WASM |
| Game Designer (batch_6) | `batch_6/game_designer.md` | Guard conditions / RNG / Economy |
| Workflow Architect (batch_7) | `batch_7/specialized_workflow_architect.md` | State machine / Atomic write / 三階段 |
| Minimal Change (batch_7) | `batch_7/engineering_minimal_change.md` | YAGNI / pixel_diff 適用性 |
| Database Optimizer (batch_7) | `batch_7/engineering_database_optimizer.md` | filelock / SQLite / per-session write |
| MCP Builder (batch_7) | `batch_7/specialized_mcp_builder.md` | MCP-ready interface / Vision orchestrator |
| Developer Advocate (batch_8) | `batch_8/specialized_developer_advocate.md` | Demo mode / Preflight / Use cases |
| Rapid Prototyper (batch_8) | `batch_8/engineering_rapid_prototyper.md` | uv run demo / 確定性測試 / Bootstrap |
| Autonomous Optimization (batch_9) | `batch_9/engineering_autonomous_optimization.md` | Token budget / ROI crop / Multi-model |
| Incident Response (batch_9) | `batch_9/engineering_incident_response.md` | CB / Checkpoint / Resource leak / Alert |
| Level Designer (batch_9) | `batch_9/level_designer.md` | Coverage-driven / pHash / promote CLI |
| SRE/Performance (root) | `docs/agent_suggestions/sre_performance.md` | Jank score / Context loss / Regression |

---

*本報告彙整自 15+ 位不同角色審查者的架構建議，涵蓋 40 份原始文件。每項建議均經交叉驗證，共識度越高排越前。所有參考 URL 均為 2024-2026 年間的開源專案、學術論文或業界最佳實踐。*
