# 多代理系統架構優化建議（Multi-Agent Architecture Suggestions）

> 角色：Multi-Agent Systems Architect
> 日期：2026-07-16
> 對象：WebGL QA Agent (`webgl-qa-agent`)
> 方法：深入分析 codebase + 最新研究文獻 + 向 arch-defender 提問

---

## 提問摘要（Questions to arch-defender）

1. `no_effect_loop` 標記 `blocked=True` 但不強制終止——framework 層是否需要 failsafe？
2. `adaptive_observe` 完全不感知 API 預算，cost control 應該留在腳本層還是 framework 內建？
3. `GameSession` 刻意保持無狀態機設計（caller 驅動），是否有理由不內建 lifecycle state machine？
4. WebGL CONTEXT_LOST 後的預期行為是什麼？
5. OTel 整合的投入產出比——目前規模是否值得引入額外 infra？
6. AD-4 #3 的「高風險轉換雙訊號」傾向同步 block 還是異步 skip+review？

---

## 建議 1：Agent Loop 終止策略（Loop Termination）

### 問題

目前 `GameSession` 的 explore loop 沒有形式化的終止條件——只靠外部腳本的 `--duration`/`--runs` 控制。`max_consecutive_noop=3` 只標記 blocked 但不強制終止 session。如果 Vision LLM 持續建議無效動作，agent 可能無限消耗 token。

### 建議

引入 **語義收斂偵測（Semantic Early-Stopping）** + **分層終止瀑布（Termination Cascade）**。四層優先級終止條件：

1. **Failsafe**：硬性 step/token/wall-clock 上限（保證終止）
2. **Stagnation**：連續 N 步 pixel_diff < threshold 且 screen_id 無變化
3. **Convergence**：flow_graph 覆蓋率不再增長（連續 K 步無新 screen/transition）
4. **Quality Gate**：oracle violations 累積超過容許閾值

```python
class ExitReason(Enum):
    SUCCESS = "coverage_target_met"
    CONVERGENCE = "no_new_discovery"
    STAGNATION = "stuck_loop"
    BUDGET = "budget_exhausted"
    FAILSAFE = "max_steps_reached"
```

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| AgentPatterns.ai | https://agentpatterns.ai/loop-engineering/ | Loop Engineering patterns：convergence detection、go/no-go gates、runaway guardrails |
| SHP (arxiv) | https://arxiv.org/html/2606.27009 | Semantic Early-Stopping：cosine-distance patience window + quality gate，judge-free 版節省 38% token |
| Engineering Playbook | https://engineering-playbook.vercel.app/agentic/loop-control-and-exit-conditions | Exit conditions：tagged predicates + stagnation detector (window=4+) + handoff |
| IAL-Scan (arxiv) | https://arxiv.org/html/2607.01641 | 靜態分析偵測無限 agent loop；bound coverage verification；每個 feedback path 需 effective bound |

### 優先級：🔴 高

### 預期效果

- 避免 runaway session 燒 token
- 每次 run 有明確結束原因（tagged ExitReason）
- 支援 CI pass/fail verdict（對應 AD-7）

---

## 建議 2：成本治理（Cost Governance）

### 問題

Vision 呼叫（Claude Sonnet）每次約 $0.003-0.01，一個 explore session 可能產生上百次呼叫。`adaptive_observe` 的門檻是純 pixel-based，沒有預算感知的降級機制。多遊戲並行時無法防止單一卡關遊戲吃掉所有 API 預算。

### 建議

引入 **Per-Session Token Budget + 漸進降級策略**：

```yaml
# config/default.yaml 新增
budget:
  per_session:
    max_vision_calls: 50
    max_cost_usd: 2.00
    soft_cap_ratio: 0.8
  degradation:
    - threshold: 0.8
      action: reduce_vision_frequency  # 每 3 步才呼叫一次
    - threshold: 0.9
      action: skip_non_critical_vision # 只在未知畫面呼叫
    - threshold: 1.0
      action: hard_stop
  model_routing:
    default: claude-sonnet-4
    degraded: claude-haiku-3-5  # 接近上限時降級
```

狀態機：`active → warned → degraded → stopped`

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| Token Budget Orchestrator | https://github.com/ricmmartins/tokenbudgetorchestrator | Per-agent budget + auto-downgrade routing；SDK runs in-process，prompts never leave infra |
| Agent Budget Controller | https://github.com/pntech20/agent-budget-controller | soft cap → warn → degrade → hard-stop 狀態機；O(1) spend lookup；multi-scope budgets |
| BAMAS (arxiv) | https://arxiv.org/html/2511.21572v1 | Budget-aware multi-agent structuring；ILP 選最佳 model 組合；減少 86% 成本 |
| Joule | https://github.com/Aagam-Bothara/Joule | 7 維預算執行：token/cost/time/tool-call/energy/carbon/depth |
| Guild.ai Govern | https://www.guild.ai/platform/govern | Per-agent per-model spend thresholds + centralized mediation |

### 優先級：🔴 高

### 預期效果

- 單 session 成本可控 <$2
- 接近上限時平滑降級而非突然中斷
- 多遊戲並行時預算隔離

---

## 建議 3：狀態機形式化（State Machine Formalization）

### 問題

`GameSession` 的 lifecycle 是隱式的（start→observe/act loop→finish），沒有正式狀態圖。Session 可能在任何狀態下因異常中斷但沒有 recovery 協議。連續 QA（`qa_continuous_tasks.py`）或多 session 並行時，缺乏形式保證可能導致 zombie session。

### 建議

定義 **GameSession Node State Machine** with proven termination：

```
States: INIT → LOADING → EXPLORING → VALIDATING → TESTING → FINISHING → COMPLETED | FAILED

Transitions:
  INIT       →(launch)→       LOADING
  LOADING    →(webgl_ready)→  EXPLORING
  LOADING    →(timeout)→      FAILED
  EXPLORING  →(coverage_met)→ VALIDATING
  EXPLORING  →(budget/stagnation)→ FINISHING
  VALIDATING →(all_pass)→     TESTING
  VALIDATING →(regression)→   EXPLORING  (bounded: max 2 retries)
  TESTING    →(complete)→     FINISHING
  FINISHING  →(report_saved)→ COMPLETED
  *          →(unrecoverable)→ FAILED
```

每個狀態轉移都有 timeout `τ_v` + retry budget `b_v`，保證有限時間內必然到達 terminal state。

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| Graph Harness (arxiv) | https://www.arxiv.org/pdf/2604.11378 | 三層分離 planning/execution/recovery + node state machine with proven termination + bounded recovery |
| IAL-Scan (arxiv) | https://arxiv.org/html/2607.01641 | Agentic Loop Dependence Graph；bound coverage verification |
| Engineering Playbook | https://engineering-playbook.vercel.app/agentic/loop-control-and-exit-conditions | Tagged exit reasons + structured AgentResult |

### 優先級：🟡 中

### 預期效果

- 消除 zombie session
- 保證 `finish()` 必然被呼叫產出報告
- 支援 AD-7 CI exit code

---

## 建議 4：錯誤恢復（Error Recovery）

### 問題

`execute_action` 的 try/except 直接回傳 `{"status": "error"}`，呼叫端沒有標準化 recovery 協議。Playwright page crash（WebGL CONTEXT_LOST）發生在 action 中間時缺乏 relaunch 邏輯。`vision.py` 有 retry 但 `browser.py` 沒有。

### 建議

實作 **三層升級式恢復（Bounded Recovery Escalation）**：

```
Level 1 (Retry):     同一動作重試 1 次（transient error）
Level 2 (Workaround): 換替代動作或重新截圖（tool failure）
Level 3 (Relaunch):  關閉 browser 重新啟動（page crash / context lost）
Level 4 (Abort):     標記 FAILED + 保存 partial report（unrecoverable）
```

規則：
- 每層都有明確的 retry budget 和 timeout
- 不允許跳級（必須逐層升級）
- 防止 LLM 自行決定 recovery 策略導致無界重試

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| Graph Harness (arxiv) | https://www.arxiv.org/pdf/2604.11378 | Recovery escalation ladder：retry → patch → replan；不允許跳級；bounded prevents infinite retry |
| Engineering Playbook | https://engineering-playbook.vercel.app/agentic/loop-control-and-exit-conditions | Structured failure results + handoff pattern |
| AgentPatterns.ai | https://agentpatterns.ai/loop-engineering/ | Stuck-Loop Recovery：nudge → replan → escalate → reset → hand off → abort |

### 優先級：🟡 中

### 預期效果

- WebGL CONTEXT_LOST 後自動恢復
- Partial report 保存避免長時間 run 白費
- 明確的 recovery audit trail

---

## 建議 5：可觀測性與追蹤（Observability / Tracing）

### 問題

可觀測性僅限於事後的 HTML timeline + session.json。Production QA 場景（夜間排程多遊戲）無法即時知道 session 卡住。Vision 呼叫的 latency/cost 沒有被追蹤到可聚合的後端。

### 建議

整合 **OpenTelemetry + LangSmith 雙軌追蹤**：

- 每個 `GameSession` 產生一個 root trace
- 每個 `observe()` / `execute_action()` / Vision call 是 child span
- Span attributes：`game_name`、`step_count`、`screen_id`、`pixel_diff`、`anomaly_count`、`vision_cost`
- OTel Collector fan-out → LangSmith（agent debugging）+ Grafana/Prometheus（dashboard + alerting）

```python
from opentelemetry import trace
tracer = trace.get_tracer("webgl-qa-agent")

class GameSession:
    async def observe(self):
        with tracer.start_as_current_span("observe", attributes={
            "game.name": self.game_name,
            "game.step": self.step_count,
            "game.screen_id": self.current_screen_id or "unknown",
        }) as span:
            # ... existing logic ...
            span.set_attribute("observe.pixel_diff", diff_ratio)
            span.set_attribute("observe.anomaly_count", len(anomalies))
```

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| OpenTelemetry Blog | https://opentelemetry.io/blog/2025/ai-agent-observability/ | OTel AI Agent Semantic Convention；GenAI SIG 定義 agent span conventions |
| LangChain Blog | https://www.langchain.com/blog/end-to-end-opentelemetry-langsmith | LangSmith + OTel 整合；fan-out via OTel Collector |
| CallSphere Blog | https://callsphere.ai/blog/ai-agent-observability-opentelemetry-langsmith-tracing | AI Agent Observability best practices：token usage per step、tool success rate、loop count |
| LangSmith Production | https://alatirok.com/langsmith-production-setup-multi-agent-observability/ | Multi-agent tracing + regression monitoring + automated alerting |

### 優先級：🟡 中

### 預期效果

- 即時偵測卡住的 session（alert on stagnation）
- Vision cost 即時追蹤
- Cross-session 聚合分析每個遊戲的 QA 效率

---

## 建議 6：人在迴路（Human-in-the-Loop）

### 問題

DESIGN.md 提到「中途可介入」但實際只有 `cmd.txt` 手動模式。`qa_interactive.py` 完全自主無 escalation。連續 `no_effect_loop` + recovery 失敗時沒有通知人類的機制。AD-4 #3 的高風險轉換也需要人工確認。

### 建議

實作 **分層 Handoff 機制**：

```python
class HumanHandoff(Exception):
    def __init__(self, reason: str, state: dict, suggested_action: str | None = None):
        self.reason = reason
        self.state = state
        self.suggested_action = suggested_action
```

觸發條件：
1. **Stagnation**：連續 N 步無進展 + recovery 失敗
2. **High-risk**：切廳/充值等不可逆動作前
3. **Ambiguity**：Vision confidence 過低 + 未知畫面
4. **Budget**：接近 hard cap 時詢問是否繼續

兩種模式：
- **同步**（互動式）：block 等待人類回應（適合 Hermes 對話模式）
- **異步**（排程式）：寫入 `needs_review` 記錄 + 發通知，session pause

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| Engineering Playbook | https://engineering-playbook.vercel.app/agentic/loop-control-and-exit-conditions | Human handoff pattern：interrupt by infrastructure not agent；sync/async/tiered |
| Guild.ai Govern | https://www.guild.ai/platform/govern | High-risk → pause → generate proposal → human approval required |
| Joule | https://github.com/Aagam-Bothara/Joule | requireApproval for specific actions + constitutional AI tiers |

### 優先級：🟢 低（但 AD-4 #3 依賴此功能）

### 預期效果

- 防止 agent 在不可逆操作上誤操作
- Stagnation 時及時介入而非白跑

---

## 建議 7：多遊戲可擴展性（Multi-Game Scalability）

### 問題

架構是 one session = one game = one process。`_session` 全域變數是單例設計不支援並行。夜間排程跑多遊戲時缺乏資源隔離和統一調度。

### 建議

引入 **Supervisor-Worker 排程架構**：

```
Supervisor（調度器）
├── Budget Manager（全域預算分配）
├── Worker-1: Game A session（獨立 process）
├── Worker-2: Game B session
├── Worker-3: Game C session
└── Aggregator: 彙整所有遊戲的 report + anomalies
```

- Supervisor 依覆蓋率 + 歷史異常率動態分配 budget
- Worker 之間預算隔離（per-agent scope）
- 高覆蓋率遊戲分配少預算（邊際收益遞減）
- 統一 exit reason aggregation → CI verdict

### 參考資料

| 來源 | URL | 重點 |
|------|-----|------|
| Token Budget Orchestrator | https://github.com/ricmmartins/tokenbudgetorchestrator | Per-agent budget isolation；runaway agent 無法吃掉整個 project 預算 |
| BAMAS (arxiv) | https://arxiv.org/html/2511.21572v1 | 根據 task 難度動態選 model 組合 + collaboration topology |
| Joule | https://github.com/Aagam-Bothara/Joule | Crew hierarchical strategy + per-agent budget slice |
| Guild.ai Govern | https://www.guild.ai/platform/govern | Track usage across agents/models/teams |

### 優先級：🟢 低（roadmap，依賴 #1-#4 先穩定）

### 預期效果

- 支援 nightly QA 跑多遊戲
- 預算公平分配
- 不因單遊戲卡關影響其他

---

## 總結：實施路線圖

| 階段 | 建議 | 優先級 | 依賴 | 預估工期 |
|------|------|--------|------|----------|
| Phase 1 | #1 Loop Termination | 🔴 高 | — | 2-3 天 |
| Phase 1 | #2 Cost Governance | 🔴 高 | — | 2-3 天 |
| Phase 2 | #3 State Machine | 🟡 中 | #1 | 3-4 天 |
| Phase 2 | #4 Error Recovery | 🟡 中 | #3 | 2-3 天 |
| Phase 2 | #5 Observability | 🟡 中 | — | 2-3 天 |
| Phase 3 | #6 Human-in-the-Loop | 🟢 低 | #3, #4 | 2 天 |
| Phase 3 | #7 Multi-Game Scalability | 🟢 低 | #1-#4 | 5-7 天 |

**建議先做 Phase 1（#1 + #2）**：直接防止 runaway cost，且不需要重構現有 API。再做 #3 形式化狀態機作為 Phase 2/3 的基礎。
