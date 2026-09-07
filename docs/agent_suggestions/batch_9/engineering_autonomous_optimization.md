# Autonomous Optimization Architect — 架構審查建議

> **角色**：Autonomous Optimization Architect（自主優化架構師）
> **審查範圍**：Vision LLM 成本控制、多模型路由、Circuit Breaker、Token 效率、Telemetry
> **日期**：2026-07-16

---

## 背景摘要

目前 WebGL QA Agent 的 Vision 呼叫走單一 gateway（Anthropic 相容），每次送完整 1280x720 截圖，無 per-session 成本上限、無 circuit breaker、無 telemetry 記錄。AD-9 提出「每 session 成本上限」但尚未實作。本文從 AI FinOps 視角提出具體可執行的優化建議。

---

## 建議 1：實作 Per-Session Token Budget + Circuit Breaker

### 問題

Agent 若卡在探索迴圈不斷截圖呼叫 Vision，token 消耗無上限。目前 `execute_action` 的 `consecutive_noop` 只防重複動作，但不防整體 session 的 Vision 呼叫次數或成本失控。

### 建議

在 `vision.py` 外層加入 token budget enforcement middleware：

1. **Per-session hard cap**：設定每 session 最多 N 次 Vision 呼叫（建議初始值 50 次）或最多 M input tokens（建議 200K tokens，約 $0.60 at Sonnet pricing）。
2. **Sliding window velocity check**：若 5 分鐘內 Vision 呼叫超過 15 次且 pixel_diff 均低於閾值（表示畫面沒變化），自動 trip circuit breaker。
3. **Graceful degradation**：circuit breaker 觸發後，agent 降級為純確定性模式（detector + perceiver + 知識庫已知路徑），不中斷 session。

### 參考實作

- **token-fence**（TypeScript middleware）：per-request / per-session / per-user / global 四層 sliding window budget enforcement，支援 `BudgetExceededError` 回傳剩餘額度。
  - URL: https://github.com/SiluPanda/token-fence
- **Loopers**（Go reverse proxy）：支援 500+ AI models 的 pre-call budget enforcement，atomic Redis Lua transaction，fail-closed guarantee，mid-stream SSE cutoff。
  - URL: https://github.com/CURSED-ME/loopers-oss
- **AssemblyZero 三層成本控制**：Layer 1 per-call tracking → Layer 2 session budget → Layer 3 iteration circuit breaker（估算下一次迭代成本，超過就 trip）。
  - URL: https://github.com/martymcenroe/AssemblyZero/wiki/Cost-Management
- **MonetiseBG/circuit-breaker**：專為 AI agent 設計的 budget-guard + loop-killer 雙模式，支援 LangChain / Vercel AI SDK / LangGraph 整合。
  - URL: https://github.com/MonetiseBG/circuit-breaker

### 預估效益

- 防止單次 session 失控花費超過 $1（目前無保護）
- 卡關迴圈從「直到 session 結束才停」縮短為「5 分鐘內自動降級」

---

## 建議 2：Image Preprocessing — Resize + ROI Crop 降低 40-70% Vision Token

### 問題

目前每次 Vision 呼叫送完整 1280x720 PNG。根據 Anthropic 官方公式，token cost = ⌈width/28⌉ × ⌈height/28⌉ = 46 × 26 = 1,196 visual tokens。若改為只送 UI 區域（如底部砲台 + 上方分數區，約 1280x200），token 降為 46 × 8 = 368 tokens，節省 69%。

### 建議

1. **Client-side resize**：送出前 resize 到 1568px long edge（Anthropic 推薦最大值），轉 JPEG quality 85。這是 Anthropic 官方文件明確建議的最佳實踐。
2. **Task-specific ROI crop**：
   - `game_state` 讀數任務：只送 UI 區域（分數/金幣/等級所在的固定位置），座標從 `game_info.yaml` 讀取。
   - `screen_id` 辨識任務：送全圖但 resize 到 1092px（分類任務 accuracy 幾乎不受影響）。
   - 探索/未知畫面：送完整 1568px 版本。
3. **Hash-based dedup**：對 preprocessed bytes 做 hash，同一畫面（SSIM > 0.98）不重複呼叫 Vision。

### 參考

- **Anthropic 官方 Vision 文件** — Resolution and token cost 段落，明確說明 visual token 計算公式與 resize 建議。
  - URL: https://platform.claude.com/docs/en/build-with-claude/vision
- **Claude Vision API Production Guide**（Developers Digest）— 完整 preprocessing pipeline：orient → resize 1568px → JPEG q85 → hash dedup，實測「cuts image costs 40-70% with no measurable accuracy loss on text-heavy imagery」。
  - URL: https://www.developersdigest.tech/blog/claude-vision-api-production-guide
- **Claude Vision Coordinates 文件** — `resized_size()` reference implementation，確保 resize 後座標對齊。
  - URL: https://platform.claude.com/docs/en/build-with-claude/vision-coordinates
- **Claude Lab 實作指南** — 按任務類型調整 resize target：OCR 任務 1568px、分類任務 1092px（nearly halves token count）。
  - URL: https://claudelab.net/en/articles/api-sdk/claude-vision-pdf-ocr-implementation-patterns

### 預估效益

| 場景 | 現況 tokens | 優化後 tokens | 節省 |
|------|------------|--------------|------|
| game_state 讀數（ROI crop） | 1,196 | 368 | 69% |
| screen_id 辨識（resize 1092） | 1,196 | 780 | 35% |
| 探索全圖（resize 1568 + JPEG） | 1,196 | 1,196（已在限內） | 傳輸時間減少 |
| Hash dedup 命中率 | — | — | 額外 10-25% 呼叫省略 |

---

## 建議 3：Multi-Model Semantic Router — 用 pixel_diff + screen_id 做 Complexity Classifier

### 問題

所有 Vision 呼叫走同一模型（推測為 Claude Sonnet 等級），但 80% 的呼叫是簡單任務（已知畫面的 game_state 讀數），只有 20% 是真正需要高能力模型的（未知畫面探索、複雜 UI 判斷）。

### 建議

利用 perceiver 現有信號做 zero-cost complexity routing：

| 信號 | 路由決策 |
|------|----------|
| `screen_id` 已知 + confidence high | → Cheap model（Gemini Flash / Haiku） |
| `screen_id` 已知 + confidence medium | → Mid model（Sonnet） |
| `screen_id` 未知 OR pixel_diff > 0.3 | → Premium model（Opus） |
| `game_state` 純讀數（已知 ROI） | → Cheapest（Haiku + ROI crop） |

實作路徑：
1. 先用 static rule-based routing（30 行程式碼），不需 ML。
2. 記錄每次路由的 accuracy（parser 是否成功解析），累積 1000 次後評估是否需要 learned router。
3. Fallback chain：若 cheap model 回傳 parse failure，自動 escalate 到 premium。

### 參考

- **Multi-Model Routing — Cut LLM Bills 40-70%**（Akshay Ghalme）— 完整的 gateway 選型比較（LiteLLM / Portkey / OpenRouter / Cloudflare AI Gateway）、cascade vs fallback patterns、58% cost reduction case study。
  - URL: https://akshayghalme.com/blogs/multi-model-routing-ai-gateway-pattern/
- **LLM Router 2026: RouteLLM Benchmarks**（Klymentiev）— Static routing 即可捕獲 60-70% 可用節省，RouteLLM benchmark 達 95% GPT-4 quality at 26% cost。
  - URL: https://klymentiev.com/blog/llm-router
- **A3M Router**（Das-rebel）— 開源 multi-signal heuristic router，complexity score 0.0-1.0 對應 free/cheap/mid/premium tier，96.77% routing accuracy，$0.0768/1K cost。
  - URL: https://github.com/Das-rebel/a3m-router
- **MAST LLM Router**（m4stanuj）— Task-aware fallback router，6 models per chain auto-failover，semantic cache 0.82 threshold，$0/month 全走 free tier。
  - URL: https://github.com/m4stanuj/mast-llm-router
- **LLM Semantic Router**（ReadTheDocs）— BERT-based semantic classifier + Envoy ExtProc 整合，production-ready with monitoring。
  - URL: https://llm-semantic-router.readthedocs.io/en/latest/

### 預估效益

- 假設 80% 呼叫路由到 cheap tier（Haiku $1/M vs Sonnet $3/M），整體 Vision 成本降低 50-60%。
- 結合建議 2 的 ROI crop，疊加效果可達 70-80% 總成本削減。

---

## 建議 4：Vision Telemetry + LLM-as-a-Judge 自動化品質評估

### 問題

目前無記錄 Vision 呼叫的 latency、token count、cost、parse success rate。無法量化優化效果，也無法偵測品質退化（例如模型更新後 game_state 讀數準確率下降）。

### 建議

1. **Per-call telemetry**：在 `vision.py` 每次呼叫記錄：
   ```python
   {
       "timestamp": ...,
       "session_id": ...,
       "call_type": "game_state" | "screen_id" | "explore",
       "model": "claude-sonnet-4",
       "input_tokens": 1196,
       "output_tokens": 350,
       "cost_usd": 0.0052,
       "latency_ms": 2340,
       "parse_success": True,
       "screen_id": "gameplay",
       "image_dimensions": [1280, 720],
   }
   ```
2. **Daily cost dashboard**：累積寫入 `runs/<game>/telemetry.jsonl`，每 session 結束時在 report 中顯示 Vision cost breakdown。
3. **Shadow testing for model comparison**：每 20 次呼叫抽 1 次（5%），同時送 cheap model，比較 parse 結果。若 cheap model 的 game_state 數值與 premium model 一致率 > 95%，自動提升 router weight。
4. **Regression alert**：若 parse_success_rate 連續 10 次低於 80%，觸發 alert（寫入 report + 記為 anomaly）。

### 參考

- **AI Agent Cost Governance System**（Let's Build Solutions）— 完整的 per-call tracking + spend velocity anomaly detection + circuit breaker state machine 架構設計。
  - URL: https://letsbuildsolutions.com/blog/ai-ml/designing-an-ai-agent-cost-governance-system-token-budgets-spend-caps-and-automated-circuit-breakers-for-production-llm-deployments/
- **Claude Vision Production Guide**（Developers Digest）— 「log token usage on every call. Record `message.usage` and watch the daily average input tokens per image. A regression in your resize step shows up first as a jump in that number.」
  - URL: https://www.developersdigest.tech/blog/claude-vision-api-production-guide

---

## 建議 5：Vision API Graceful Degradation — 純確定性 Fallback Mode

### 問題

若 Vision gateway 連續失敗（rate limit / 500 / timeout），目前行為是拋 exception，session 中斷。Agent 已有足夠的確定性能力（detector + perceiver + 知識庫已知路徑 + oracle）可在無 Vision 時繼續有限運作。

### 建議

1. **Retry with exponential backoff**：最多 3 次，timeout 5s → 10s → 20s。
2. **Circuit breaker trigger**：3 次連續失敗 → trip，cooldown 60s。
3. **Fallback mode**：circuit breaker open 期間，agent 自動切換為：
   - 只走知識庫已知路徑（high confidence transitions）
   - 只用 perceiver 的 SSIM + pixel_diff 做畫面辨識
   - 只執行 detector 崩潰偵測
   - 不嘗試探索未知畫面
   - 報告中標記 `degraded_mode: true`
4. **Half-open probe**：cooldown 後下一次需要 Vision 時送一次 probe call，成功則恢復正常。

### 參考

- **Multi-Model Routing 文章**（Akshay Ghalme）— 「Fallback handles availability, not cost. If primary is down or rate-limited, try secondary. Production systems run primary on Anthropic Sonnet, fallback to OpenAI GPT-4o, second fallback to Gemini 2.5 Pro. A single-provider outage no longer brings down your AI features.」
  - URL: https://akshayghalme.com/blogs/multi-model-routing-ai-gateway-pattern/
- **Loopers OSS** — Fail-closed guarantee + circuit breaker 設計，可作為 Vision gateway 前的 proxy。
  - URL: https://github.com/CURSED-ME/loopers-oss

---

## 優先順序建議

| 優先級 | 建議 | 實作難度 | 預估節省 | 與現有 AD 對應 |
|--------|------|----------|----------|----------------|
| P0 | 建議 2：Image resize + ROI crop | 低（純 preprocessing） | 40-70% token | AD-9 |
| P0 | 建議 1：Per-session budget cap | 中 | 防災難性花費 | AD-9 |
| P1 | 建議 5：Graceful degradation | 中 | 99.9% uptime | — |
| P1 | 建議 4：Telemetry | 低 | 可量化所有優化 | — |
| P2 | 建議 3：Multi-model router | 高 | 額外 50-60% | — |

建議 2 和 1 為 P0，因為它們是「做了立刻有效果」且「不做有風險」的項目。建議 3 依賴建議 4 的 telemetry 數據來驗證路由準確性，因此排在後面。
