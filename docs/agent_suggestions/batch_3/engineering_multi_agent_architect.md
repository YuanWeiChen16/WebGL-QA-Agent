# Multi-Agent Systems Architect 審查建議

> 審查角色：Multi-Agent Systems Architect（專精 topology selection、failure-mode engineering、inter-agent trust、HITL gating、observability）
> 審查日期：2026-07-16
> 對象文件：DESIGN.md、ARCHITECTURE_DECISIONS.md
> 批次：Batch 3 — 架構工程組

---

## 總評

從多代理系統架構角度看，WebGL QA Agent 本質上是一條 **Sequential Chain Pipeline**：
截圖 → Vision LLM → 決策 → 動作 → 偵測/Oracle → 知識庫更新。
此 pipeline 在 happy path 運作良好，但缺乏 production-grade multi-agent 系統必備的
**failure recovery、observability、inter-agent contract、HITL gate、evaluation baseline**。

以下 5 項建議按優先度排序，每項附具體做法與業界參考 URL。

---

## 建議 1：Vision LLM Fallback Chain — 消除單點故障

**問題**：
Vision LLM（透過 gateway 呼叫 Claude Vision / GPT-4o）是整條 pipeline 唯一的感知通道。
Gateway timeout、rate limit (429)、malformed response 任一發生，pipeline 全面停擺。
目前架構無 fallback handler、無 circuit breaker、無 degraded mode。

**建議做法**：
實作三層 Fallback Chain：

```
Layer 1 (Primary):  Claude Vision via gateway（完整 structured tool_use）
Layer 2 (Fallback): 備用 Vision model 或備用 gateway（可用 GPT-4o / Gemini）
Layer 3 (Degraded): 純確定性感知（SSIM + perceiver.py pixel diff + 知識庫座標）
                     → 標記 degraded_mode=True，僅執行已知 scripted_sequence
Layer 4 (Halt):     停止 pipeline，保存 checkpoint，通知使用者
```

每層之間以 **Circuit Breaker** 控制：連續 3 次失敗 → 跳下一層；cooldown 60 秒後嘗試恢復。

**來源**：
- Agent Patterns Catalog — Fallback Chain Pattern：定義 ordered handlers + confidence signal + bounded cascade depth
  https://www.agentpatternscatalog.org/patterns/fallback-chain/
- Multi-Agent System Error Recovery (ECOA AI)：三層錯誤恢復（retry → fallback → compensation），12% → 0.2% failure rate
  https://ecoaai.com/multi-agent-system-error-recovery-guide/
- COCO: Cognitive Operating System with Continuous Oversight — Contextual Rollback Mechanism
  https://doi.org/10.48550/arxiv.2508.13815

**優先級**：高

**預期效果**：Vision 失敗時 pipeline 不全停，degraded mode 仍可執行 scripted 回歸測試。

---

## 建議 2：結構化 Observability — OpenTelemetry trace_id 貫穿 pipeline

**問題**：
整條 pipeline（截圖 → Vision 呼叫 → 決策 → 動作 → detector → oracle）沒有 shared trace_id。
`session.json` 記錄操作序列，但不是 distributed trace — 缺乏每步的 latency_ms、
input_tokens、output_tokens、cost_usd、confidence、model_version。

當 oracle 報出 false positive 或 detector 漏報時，無法做 root cause analysis：
是 Vision 誤讀？是 SSIM 門檻不對？是 invariant 定義有問題？只能人工逐步排查。

**建議做法**：
採用 OpenTelemetry 標準，每個 agent loop iteration = 1 trace，每步 = 1 span：

```json
{
  "trace_id": "run-session-uuid",
  "spans": [
    {"name": "screenshot", "latency_ms": 120},
    {"name": "vision_call", "model": "claude-4-vision", "input_tokens": 1820, "output_tokens": 412, "cost_usd": 0.008, "confidence": 0.85},
    {"name": "action_execute", "action_type": "click", "pixel_diff": 0.12},
    {"name": "detector_check", "anomalies_found": 0},
    {"name": "oracle_check", "violations": [], "reread_triggered": false}
  ]
}
```

最小可行實作：在 `GameSession` 加 `trace_context` dict，每步 append structured entry，
`finish()` 時寫入 `trace.jsonl`。進階可用 `opentelemetry-sdk` export 至 Jaeger/Tempo。

**來源**：
- OpenTelemetry for LLM Agents — 1 request = 1 trace, agent span model
  https://aivineet.com/llm-agent-tracing-distributed-context-opentelemetry/
- AgentTrace (arXiv 2602.10133) — 三層面 taxonomy（cognitive/operational/contextual），schema-based logging
  https://arxiv.org/pdf/2602.10133
- AI Agent Observability (Coverge) — GenAI semantic conventions, agent span attributes
  https://coverge.ai/blog/ai-agent-observability
- groundcover — AI Agent Observability Guide: treat evaluation as telemetry
  https://www.groundcover.com/learn/observability/ai-agent-observability

**優先級**：高

**預期效果**：任何 false positive/漏報可在 5 分鐘內 trace 回源頭，取代目前數小時的人工排查。

---

## 建議 3：Inter-Agent Contract — Vision ↔ GameSession Schema Validation

**問題**：
Hermes Agent（大腦）與 Python 模組（手腳）之間、Vision 回傳與 GameSession 消費之間，
沒有 formal schema contract。Vision 回傳的 `game_state`、`suggested_action`、`screen_id`
結構，與 `execute_action()` / `record_game_state()` / `check_invariants()` 的參數之間
沒有 runtime schema validation。

Silent failure 場景：Vision 漏回 `score` field → `record_game_state` 接受 partial dict →
oracle 比對時 KeyError 或 skip → 功能正確性檢查靜默跳過。

**建議做法**：

1. 定義 Pydantic schema：
```python
from pydantic import BaseModel, Field
from typing import Optional

class GameState(BaseModel):
    score: Optional[int] = None
    currency: Optional[int] = None
    level: Optional[int] = None
    lives: Optional[int] = None

class VisionResponse(BaseModel):
    screen_id: str
    game_state: GameState
    suggested_action: dict
    confidence: float = Field(ge=0.0, le=1.0)
```

2. Vision 回傳後立即驗證：schema 不合 → 記 structured warning → 觸發 reread 或 fallback。

3. 文件化 contract：每模組定義 RECEIVES / PRODUCES / NOT RESPONSIBLE FOR。

**來源**：
- Multi-Agent Pipeline Halt Protocol — semantic verification gate 捕捉 soft failure
  https://ranjankumar.in/ai-control-plane-multi-agent-pipeline-orchestration-failure-propagation
- Multi-Agent Failure Handling (AI Codex) — partial output 是最常被忽略的 failure mode
  https://www.aicodex.to/articles/multi-agent-failure-handling

**優先級**：中

**預期效果**：消除 Vision 回傳不完整時的 silent failure，所有 schema mismatch 立即可見。

---

## 建議 4：Formal HITL Gate — 取代 Ad-hoc 對話介入

**問題**：
DESIGN.md 宣稱「中途可介入」和「可對話式微調」，但這是 Hermes 平台的 ad-hoc chat 機制，
不是 formal Human-in-the-Loop gate：
- 沒有定義哪些動作需要 blocking approval（如 AD-4 提到的切廳/重登）
- 沒有 timeout behavior（使用者不回應怎麼辦？）
- 沒有 structured escalation interface（reasoning trace + alternatives + consequence）
- 自動排程（cron）跑時無人在線，ad-hoc 介入不存在

**建議做法**：
定義兩種 gate 類型：

```yaml
# Blocking Gate（高風險動作）
hitl_gates:
  - trigger: "action targets known_risky_transition"  # 切廳、重登、大額下注
    type: blocking
    timeout_seconds: 300
    timeout_action: skip_and_log  # 不執行，記入 report
    interface:
      show: [reasoning, alternatives, consequence, confidence]

# Advisory Gate（品質監控）
  - trigger: "oracle_violation AND severity >= high"
    type: advisory
    action: flag_for_review  # pipeline 繼續但標記
```

Cron 模式下 blocking gate 自動 timeout → skip，確保無人時不卡死。

**來源**：
- COCO Framework — Bidirectional Reflection Protocol：monitor/execution 互相驗證，human gate 僅 cascade failure 觸發
  https://doi.org/10.48550/arxiv.2508.13815
- Multi-Agent Pipeline Orchestration — pipeline halt protocol with propagation boundary
  https://ranjankumar.in/ai-control-plane-multi-agent-pipeline-orchestration-failure-propagation

**優先級**：中

**預期效果**：高風險動作有正式閘門、cron 模式不卡死、事後可追溯「為何放行/攔截」。

---

## 建議 5：Evaluation Baseline — Vision 準確率 + Oracle Precision/Recall

**問題**：
AD-2 承認「追蹤 oracle precision（報的 bug 幾成為真）」尚無實作。目前無 quantitative baseline：
- Vision 畫面辨識/數值讀取準確率？
- Oracle precision（報的 violation 多少是真 bug）？recall（實際 bug 漏報率）？
- 改 Vision prompt 後品質是否退化？無 regression detection。

沒有 eval baseline = 無法安全迭代。每次改 prompt/model 都可能靜默退化。

**建議做法**：

1. 建立 golden dataset（≥20 cases）：
   - 10+ 張已知畫面 + 正確 game_state（測 Vision 數值讀取 accuracy）
   - 10+ 對 before/after state + 預期 oracle verdict（測 invariant 引擎 precision/recall）

2. 自動化 eval script：
   ```bash
   python -m pytest tests/test_eval_vision.py   # Vision accuracy
   python -m pytest tests/test_eval_oracle.py   # Oracle precision/recall
   ```

3. Gate rule：prompt/model 修改前後必須跑 eval，score 不得低於 baseline。

4. Production precision 追蹤：每個 oracle violation 標記 `confirmed: true/false`，累計 precision rate。

**來源**：
- MLflow Tracing — Evaluation as telemetry，eval score 附加到每次 run
  https://mlflow.org/docs/latest/genai/tracing/
- AI Agent Observability (groundcover) — treat evaluation as telemetry, attach correctness scores to runs
  https://www.groundcover.com/learn/observability/ai-agent-observability

**優先級**：中

**預期效果**：每次 prompt/model 變更有量化品質門檻，regression 可自動偵測。

---

## 優先度總覽

| # | 建議 | 優先度 | 理由 |
|---|------|--------|------|
| 1 | Vision Fallback Chain | **高** | 單點故障，production 不可接受 |
| 2 | OpenTelemetry Observability | **高** | 無法 debug = 無法維運 |
| 3 | Schema Validation Contract | **中** | silent failure 預防 |
| 4 | Formal HITL Gate | **中** | cron 模式必備，短期人工在線可緩解 |
| 5 | Eval Baseline | **中** | 安全迭代前提，初期可先建 minimal set |

---

## 與現有 Architecture Decisions 對應

| 建議 | 相關 AD | 備註 |
|------|---------|------|
| Fallback Chain | AD-9（感知分層與成本） | 整合到 L1/L2/L3 分層 |
| Observability | 無對應 AD | 建議新增 AD-11 |
| Schema Contract | AD-2（Vision game_state） | 強化輸入驗證 |
| HITL Gate | AD-4（高風險轉換雙訊號） | 補齊人工閘門 |
| Eval Baseline | AD-2（追蹤 precision） | 落實已規劃但未實作項 |
