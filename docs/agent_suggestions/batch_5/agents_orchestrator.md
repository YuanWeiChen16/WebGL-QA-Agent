# Agents Orchestrator 架構審查建議

**審查日期**：2026-07-16  
**審查角色**：Agents Orchestrator 視角  
**審查對象**：`.opencode/agents/agents-orchestrator.md`

---

## 建議 1：通用軟體交付 Pipeline 與專案領域的根本錯配 — 應重構為領域專用 Orchestrator

**問題**：agents-orchestrator 定義了 PM → ArchitectUX → [Dev ↔ QA Loop] → Integration 的通用軟體交付 pipeline，但本專案的核心工作流程是 GameSession 的 explore → validate → test 循環。這是典型的「Agent Everywhere」反模式 — 將通用 agent 架構套用於不需要它的領域場景。

**業界觀點**：LindleyLabs 的研究指出：「Agent execution pipelines have become the new over-engineering magnet. Teams reach for multi-agent hierarchies before they've established whether a single agent with well-scoped tools could do the job.」同時 AgentPatterns.tech 明確將此歸類為反模式：「Agent Everywhere is an anti-pattern where agent logic is added to every task, even where a simple API call or deterministic workflow is enough.」

**建議**：
1. 將 orchestrator 重構為「WebGL QA Pipeline Orchestrator」，workflow 改為：Knowledge Setup → Explore Loop → Validate Paths → Stress Test → Report
2. 若仍需保留「開發本專案程式碼」的 orchestrator 功能，應明確分離為兩個 agent：一個管開發流程、一個管 QA 執行流程
3. 參考 Hintas 的垂直化觀點：「Platform is horizontal, knowledge is vertical. You don't rebuild the engine for each industry. You populate it with different knowledge.」

**參考 URL**：
- https://lindleylabs.com/blog/your-ai-agent-pipeline-is-a-rube-goldberg-machine
- https://www.agentpatterns.tech/en/anti-patterns/agent-everywhere-problem
- https://hintas.blog/vertical-saas-why-industry-specific-ai-wins

---

## 建議 2：50+ Agent 清單造成 Context Window 浪費 — 應改為動態載入或精簡

**問題**：orchestrator prompt 列出 50+ 個 specialist agents（行銷、社群、XR、金融、法務…），每次呼叫都注入 context window。Attention 成本為 O(n²)，這些不相關的 agent 描述不僅浪費 token，還會降低推理品質（lost-in-the-middle 效應）。

**業界觀點**：Shaped.ai 的研究量化了這個問題：「Attention cost scales quadratically with input length — doubling your context doesn't double your cost, it quadruples it. Every irrelevant chunk in your context window is actively harmful.」GenericAgent 論文（Fudan/SJTU 2026）進一步指出：「Long-horizon performance is determined not by context length, but by how much decision-relevant information is maintained within a finite context budget.」Ethos Agent 框架實測顯示，從 50K tokens 精簡到 2.5K ranked tokens 可節省 85% 成本且提升品質。

**建議**：
1. 將 agent 清單從 prompt 中移除，改為外部 registry（JSON/YAML），orchestrator 按需查詢
2. 保留在 prompt 中的只留與本專案直接相關的 5-8 個 agents（QA、Dev、DevOps、Performance）
3. 採用 GenericAgent 的「hierarchical on-demand memory」模式：預設只顯示高階摘要，需要時再展開細節

**參考 URL**：
- https://www.shaped.ai/blog/context-window-optimization-why-ranking-not-stuffing-is-the-scaling-law-for-agents
- https://arxiv.org/pdf/2604.17091 （GenericAgent: Token-Efficient Self-Evolving LLM Agent）
- https://ethosagent.ai/docs/building/explanation/context-cost-optimization.md

---

## 建議 3：雙重品質閘門語義衝突 — 需建立 Oracle 優先權階層

**問題**：orchestrator 的 quality gate（EvidenceQA screenshot + PASS/FAIL + retry 3 次）與專案既有的 oracle 系統（AD-2: Vision game_state + invariant, AD-4: pixel_diff 點擊後斷言）構成兩套平行的品質判定機制。當兩者結論衝突時（例如 EvidenceQA 判 PASS 但 oracle.py invariant FAIL），無明確仲裁規則。

**業界觀點**：Semantic Consensus Framework（Acharya 2026）研究了多 agent 系統中的語義衝突問題，發現「production deployments exhibit failure rates between 41% and 86.7%, with nearly 79% of failures originating from specification and coordination issues」。其解決方案是三層優先權：Policy Authority > Capability Authority > Temporal Priority。Oracle-Gate 專案則採用更簡單的分離原則：「No agent can say done. A separate reviewer agent independently tests the work.」

**建議**：
1. 明確定義優先權：oracle.py 的 invariant 結果 > EvidenceQA 的主觀判定（因前者是確定性檢查）
2. 採用 K11tech 論文的 Multi-LLM Consensus Gate 思路：當兩套 oracle 不一致時，強制升級為人工介入
3. 在 orchestrator prompt 中加入明確的仲裁規則：「若 `oracle.py` 報告 invariant violation，即使 EvidenceQA 視覺上判 PASS，仍視為 FAIL」

**參考 URL**：
- https://arxiv.org/pdf/2604.16339 （Semantic Consensus Framework）
- https://github.com/gabrieljtao-tech/oracle-gate
- https://doi.org/10.5281/zenodo.20551586 （K11tech Multi-LLM Consensus Gate）

---

## 建議 4：「自主運作」宣稱與 AD-10 人工閘門原則衝突 — 需明確界線

**問題**：orchestrator 宣稱「Run entire pipeline with single initial command」和「Autonomous Operation — Handle errors without manual intervention」。但 AD-10 明確規定「只提建議、不自動改動，是否處理由使用者逐項決定」。兩者存在根本性的治理衝突。

**業界觀點**：「Beyond Static Gates」論文（Jadhav 2026）提出的 Adaptive HITL Threshold Learner 展示了正確做法：自動化可以漸進式地「earn autonomy」，但有明確的安全邊界（bounded [0.70, 0.95]）和 escape rate = 0% 的硬約束。AI Workflows vs Agents 的實務建議是：「Implement it as a bounded function within a workflow. Never let agents control your entire application architecture.」

**建議**：
1. 在 orchestrator 中明確區分「可自主執行」vs「需人工確認」的動作類別
2. 「可自主」：spawn 探索 agent、執行測試、產生報告
3. 「需確認」：修改 ARCHITECTURE_DECISIONS.md、變更 knowledge schema、修改 oracle invariants
4. 參考 Oracle-Gate 的 circuit breaker 模式：3 次 retry 後不是繼續自主處理，而是升級給人
5. 將 AD-10 的約束直接寫入 orchestrator 的 Critical Rules 區段

**參考 URL**：
- https://doi.org/10.5281/zenodo.20551586 （Adaptive HITL Threshold）
- https://paulserban.eu/blog/post/ai-workflows-vs-ai-agents-stop-overengineering-your-ai-systems/
- https://github.com/gabrieljtao-tech/oracle-gate

---

## 建議 5：Retry 語義在黑箱 QA 場景中不適用 — 應區分「程式碼 bug」與「遊戲 bug」

**問題**：orchestrator 的 retry 邏輯假設「QA FAIL → 修我們的程式碼 → 重測」。但在黑箱 QA 場景中，大部分的 FAIL 代表「受測第三方遊戲有 bug」（這正是我們想發現的），而非「我們的 agent 程式碼需要修」。當前 retry 語義會導致：發現遊戲 bug → 判定自身失敗 → 無意義地修改 agent 程式碼 → 遊戲 bug 依然存在。

**業界觀點**：Orchestration Gap 論文（Stanford/CMU 2026）指出：「The value in these settings does not come from a single capable model invocation; it comes from orchestration — the runtime that coordinates multi-step workflows, enforces hard domain constraints.」關鍵在於 orchestrator 必須理解其領域的「hard domain constraints」。Agent Capsules 論文則展示了品質閘門需要「quality-gated granularity control」— 不同類型的失敗需要不同的處理路徑。

**建議**：
1. 將 QA 結果分類為三種：
   - **Agent Bug**（我們的程式碼問題）→ retry dev 修正
   - **Game Bug**（受測遊戲的問題）→ 記錄到 bug report，標記為發現，繼續測試
   - **Flaky/Inconclusive**（Vision 誤讀、時序競態）→ 重測但不修程式碼（AD-2 的 min_occurrences 機制）
2. 修改 retry 決策邏輯：只有 Agent Bug 才進入 dev-QA 迴圈
3. Game Bug 的正確響應是「歸檔 + 繼續探索」而非「retry 直到 pass」

**參考 URL**：
- https://arxiv.org/html/2606.19790 （The Orchestration Gap）
- https://pith.science/paper/2605.00410 （Agent Capsules: Quality-Gated Granularity Control）
- https://arxiv.org/html/2510.00615v3 （Acon: Optimizing Context Compression for Long-horizon Agents）

---

## 總結

| # | 建議摘要 | 優先級 | 影響範圍 |
|---|---------|--------|---------|
| 1 | 通用 pipeline 改為領域專用 orchestrator | 高 | 整體架構方向 |
| 2 | Agent 清單精簡或動態載入 | 高 | 每次呼叫的 token 成本 |
| 3 | 建立 oracle 優先權階層解決雙重閘門衝突 | 中 | 品質判定一致性 |
| 4 | 明確自主 vs 人工確認的動作邊界 | 中 | 治理合規 |
| 5 | 區分「程式碼 bug」與「遊戲 bug」的 retry 語義 | 高 | 核心 QA 邏輯正確性 |
