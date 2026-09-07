# Batch 7 — MCP Builder 審查建議

**審查角色**：Specialized MCP Builder（MCP 伺服器設計專家）
**審查日期**：2026-07-16
**對象文件**：DESIGN.md、ARCHITECTURE_DECISIONS.md

---

## 總結

從 MCP 協議整合觀點審查本專案架構。Arch-defender 的核心立場是「MCP 是服務邊界協議，不適合單進程模組內部通訊」，這個立場在**目前的單 agent 階段**是合理的。但以下建議著眼於（1）架構預備性、（2）被忽略的中間方案、（3）業界趨勢，提供可漸進採用的改進方向。

---

## 建議 1：Knowledge Base — 採用「MCP-Ready Interface」模式，為未來多 agent 存取預留接縫

**現況問題**：`KnowledgeBase` 的 API 是純 Python 內部呼叫，若未來需暴露給外部 agent（AD-7 roadmap 提到的 CI 層、多 agent 協作），需大幅重構。

**Defender 立場**：YAGNI — 目前只有一個 agent，多 agent 是遠期需求；且 AD-5/AD-6 未穩定前暴露資料無意義。

**我的建議**：不需要現在建 MCP Server，但應**現在就把 KnowledgeBase 的公開方法設計為符合 MCP tool/resource 語義的形狀**（verb_noun 命名、JSON-serializable 輸入輸出、stateless 語義）。這樣未來包 MCP 只是加一層薄 wrapper，不需重構核心邏輯。

業界稱此模式為「Domain Aggregate with MCP-ready surface」——先在模組內落實 bounded context 的語義邊界，外部協議只是日後接上的 transport。

**具體行動**：
- `add_runtime_transition()` → 確保參數與回傳值皆為 JSON-serializable dict（非 dataclass 實例）
- `get_flow_graph()` → 回傳標準 JSON 結構而非內部物件引用
- 為每個公開方法加 docstring 說明「何時該呼叫」（對應 MCP tool description 的 "when to use"）

**參考資源**：
- MCP 官方「Server Concepts」— Resources 與 Tools 的設計語義：https://modelcontextprotocol.io/docs/learn/server-concepts
- Knowledge Plane — 多 agent 共享知識圖的 MCP server 實作：https://github.com/camplight/knowledgeplane
- knowledge-mcp — 帶記憶衰減與關聯連結的共享知識 MCP server：https://github.com/cristinecula/knowledge-mcp
- Agent-MCP — 多 agent 透過 MCP 共享知識圖協作的完整框架：https://github.com/rinadelph/Agent-MCP

---

## 建議 2：Vision Gateway — 不包 MCP，但應加入成本治理的 Tool Orchestrator 模式

**現況問題**：`vision.py` 直接 HTTP 呼叫 gateway，成本控制散落在呼叫端（`qa_interactive.py` 的 adaptive observe 邏輯）。

**Defender 立場**：Vision 是感覺器官，暴露為 MCP tool 等於放棄成本治理。完全正確。

**我同意不包 MCP**，但建議從 MCP「Tool Orchestrator」模式借鏡：將 Vision 呼叫包裝為一個**內部的 orchestrator 函數**，集中管理（1）呼叫頻率上限、（2）cost budget per session、（3）fallback 到低成本方案（本地 OCR）。目前 adaptive observe 是腳本私有邏輯（AD-9 也指出這個問題），提升為核心模組就是 Tool Orchestrator 的精神——不用 MCP protocol，但採用其設計智慧。

**具體行動**：
- 新增 `vision_orchestrator.py`（或在 `vision.py` 內加 class）集中 rate control + budget tracking
- 將 `qa_interactive.py` 的 adaptive observe 邏輯遷入此 orchestrator
- 對齊 AD-9 「把 adaptive observe 從腳本私有邏輯提升為核心正式策略」

**參考資源**：
- MCP Architecture Patterns 論文 — Pattern 2: Tool Orchestrator（封裝多步驟呼叫為單一 workflow）：https://arxiv.org/html/2606.30317
- MCP Institute — Production Architecture Patterns（Layered Tool Server 含 rate limiting layer）：https://mcp.institute/research/mcp-architecture-patterns
- PADISO — AI Agents in Production: MCP Server Design Patterns（Pattern 2: Layered Tool Server）：https://www.padiso.co/blog/ai-agents-production-mcp-server-design-patterns/

---

## 建議 3：Playwright — 維持直接呼叫，但為 scale-out 場景預留 CDP endpoint 接口

**現況問題**：Playwright 直接 import 使用，效能最佳。但若未來需要「瀏覽器跑在遠端機器」（例如 CI farm、雲端瀏覽器池），現有架構無法支撐。

**Defender 立場**：MCP overhead 在 ms 級確定性操作上不可接受（pixel_diff 時序、500ms interval 被吃掉）。完全正確。

**我同意不走 MCP transport**，但注意：微軟自己也區分了兩個方案——

1. **@playwright/mcp**：給 LLM agent 用，走 accessibility tree，延遲可接受因為 LLM 決策本身是秒級
2. **playwright-cli**：給 coding agent 用，CLI 介面更 token-efficient

本專案的場景（確定性腳本 + 即時截圖）兩者都不適合。但建議在 `browser.py` 中預留一個 `connect_via_cdp(endpoint_url)` 的替代初始化路徑，讓未來需要遠端瀏覽器時無需重構。OpenQA 專案正在研究同樣的問題（in-process Playwright context 如何透過 CDP 分享給外部工具）。

**具體行動**：
- `browser.py` 的 `launch()` 加一個 `cdp_endpoint` 可選參數，若提供則用 `browser.connect_over_cdp()` 而非 `browser.launch()`
- 不改變預設行為，不引入 MCP overhead

**參考資源**：
- Microsoft Playwright MCP — 官方明確區分 MCP vs CLI 的適用場景：https://github.com/microsoft/Playwright-MCP
- Playwright MCP 官方文件 — transport 選擇與 CDP 連接：https://playwright.dev/docs/getting-started-mcp
- OpenQA Issue #13 — 研究 MCP vs CLI overhead，含 CDP endpoint 共享方案：https://github.com/openqa-labs/openqa/issues/13
- MCP Rated — Playwright MCP 延遲實測（screenshot 57ms、click 3764ms）：https://mcprated.com/mcpserver/playwright

---

## 建議 4：採用「一 Server 一 Bounded Context」原則規劃未來 MCP 化路徑

**現況問題**：DESIGN.md 與 ARCHITECTURE_DECISIONS.md 無任何關於「若未來需要 MCP 化，邊界在哪」的前瞻規劃。

**Defender 立場**：目前是單進程，MCP 化 premature。

**我同意 premature implementation 不可取**，但 premature planning 是免費的。業界共識（DDD + MCP 文獻）是：MCP Server 應對齊 Bounded Context，而非對齊模組。若用這個透鏡看本專案，自然的 context 邊界是：

| Bounded Context | 未來 MCP Server | 核心職責 |
|---|---|---|
| 感知（Perception） | `perception-mcp` | 截圖、SSIM、pixel diff、Vision 呼叫 |
| 知識（Knowledge） | `knowledge-mcp` | 知識讀寫、flow graph、screen registry |
| 判定（Oracle） | 不需要 MCP（純函數直接 import） | invariant 檢查 |
| 操作（Browser） | 不需要 MCP（延遲敏感） | Playwright 瀏覽器控制 |
| 報告（Reporting） | `reports-mcp`（低優先） | 報告產生與查詢 |

這個規劃不需要寫任何程式，只需記錄在 ARCHITECTURE_DECISIONS.md 作為未來參考。

**具體行動**：
- 在 ARCHITECTURE_DECISIONS.md 新增 `AD-11 🧊 MCP 化路徑規劃（roadmap）`，記錄上述邊界劃分與「觸發條件」（何時才該真正實作）

**參考資源**：
- 「MCP Server as Bounded Context」— DDD 則應用於 MCP 設計：https://amgres.com/blog/mcp-server-as-a-bounded-context
- 「DDD and MCP: Executable Bounded Context」— 完整的 DDD-MCP 對應：https://levelup.gitconnected.com/ddd-didnt-die-in-microservices-it-was-waiting-for-mcp-2bcc6ddffbd4
- MCP 官方架構文件 — client-host-server 模型與 capability negotiation：https://modelcontextprotocol.io/specification/2025-11-25/architecture
- MCP Institute — 從 Single-Purpose 到 Gateway 的漸進路徑：https://mcp.institute/research/mcp-architecture-patterns

---

## 建議 5：Oracle — 不包 MCP，但提供 CLI wrapper 供 CI 使用

**現況問題**：`oracle.py` 是純函數、零 I/O，直接 import 是最佳方案。但 AD-7 提到未來要掛 CI，CI 環境可能不想安裝完整 Python 依賴。

**Defender 立場**：直接 import 比 MCP 輕量；CI 需要的是 exit code 不是雙向協議。完全正確。

**我完全同意不用 MCP**。但建議現在就加一個極簡的 CLI entry point（`python -m webgl_qa.oracle check ...`），回傳結構化 JSON + exit code。這正是 MCP 文獻中 Domain-Specific Adapter 模式的最小化版本——不用 MCP protocol，但維持 boundary 的語義（typed input → typed output → deterministic exit code）。

**具體行動**：
- 新增 `src/webgl_qa/oracle_cli.py`（或在 oracle.py 加 `if __name__` block）
- 接受 `--before`、`--after`、`--action`、`--game-info` 參數
- 輸出 JSON（violations list）+ exit code（0 = pass、1 = violation、2 = error）
- 這直接服務 AD-7 的 CI 需求

**參考資源**：
- MCP Architecture Patterns 論文 — Pattern 5: Domain-Specific Adapter（驗證 + 結構化輸出）：https://arxiv.org/html/2606.30317
- PADISO Production Patterns — Transport Decision Matrix（stdio 適合 single-machine / dev）：https://www.padiso.co/blog/ai-agents-production-mcp-server-design-patterns/
- MCP 官方規範 — Servers focus on specific, well-defined capabilities：https://modelcontextprotocol.io/specification/2025-11-25/architecture

---

## 與 Defender 的共識與分歧

| 議題 | Defender | 我的最終立場 | 差異 |
|---|---|---|---|
| Vision → MCP | ❌ 反對 | ❌ 同意不包 MCP，但建議加 orchestrator 集中成本治理 | 手段不同，目標一致 |
| KB → MCP | ⏳ 未來 | ⏳ 同意未來，但建議現在就 MCP-ready interface | 時間差：現在設計 vs 未來再說 |
| Oracle → MCP | ❌ 反對 | ❌ 同意，改建議 CLI wrapper | 完全一致 |
| Playwright → MCP | ❌ 反對 | ❌ 同意，建議預留 CDP endpoint | 幾乎一致 |
| Reporter → MCP | 🤷 無意見 | 🧊 低優先可做可不做 | 一致 |
| 整體 MCP 路徑規劃 | （未討論） | 建議記錄 bounded context 劃分 | 新增建議 |
