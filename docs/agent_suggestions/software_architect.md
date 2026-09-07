# 知識庫架構優化建議（Software Architect）

> 產出日期：2026-07-16
> 角色：Software Architect（DDD / 可擴展性專家）
> 對口：kb-defender

---

## 提問摘要

向 kb-defender 提出 7 個核心問題：

1. **Schema Evolution** — YAML 無版本欄位，schema 演進策略為何？
2. **Conflict Resolution** — runtime 學習層 vs 靜態 YAML 衝突時的優先順序？
3. **Knowledge Validation** — `_load_yaml` 僅 safe_load，缺少 schema validation？
4. **Multi-Game Isolation** — module-level `_kb_cache` 的隔離與 race condition？
5. **YAML Migration** — hardcoded 座標遷移到 YAML 是否有工具？
6. **Coordinate Reliability** — 座標不可靠時的降級/fallback 機制？
7. **Knowledge Reuse** — 跨遊戲知識複用的機制？

---

## 建議清單

### 建議 1：引入 Schema Version + 自動遷移管線

**問題**：`systems/*.yaml`、`game_info.yaml` 均無 `schema_version` 欄位。一旦結構變更（如加入 relative coordinates 或重構 invariants 格式），舊檔案與新程式碼之間無相容保證，只能手動修復。

**建議**：
- 在每個 YAML 根層級加入 `schema_version: "1.0"` 欄位。
- 實作遷移引擎（參考 `fluxconf` 的 JSON Patch + Python function 混合模式），在 `_load_yaml` 時自動偵測版本、依序執行遷移、回寫檔案。
- 遷移腳本放 `knowledge/_migrations/` 目錄，按整數前綴排序。

**參考 URL**：
- [fluxconf — File-backed Pydantic configuration with migration support](https://github.com/Greenroom-Robotics/fluxconf)
- [pydantic-migrator — Strict versioned Pydantic model migrations](https://github.com/robGetsTheJobDone/pydantic-migrator)
- [SUEWS YAML Schema Versioning](https://suews.readthedocs.io/latest/contributing/schema/schema_versioning.html)
- [Metaplay Entity Schema Versions and Migrations](https://docs.metaplay.dev/game-server-programming/how-to-guides/entity-schema-versions-and-migrations)

**優先級**：高
**預期效果**：schema 變更不再需要人工逐檔修改；新增欄位時舊知識庫自動向前相容；可在 CI 中驗證遷移路徑完整性。

---

### 建議 2：分層衝突解決策略（Static > Runtime with Confidence Decay）

**問題**：`add_runtime_transition` 只有 low→medium→high 遞增（AD-6 已指出），靜態 YAML 與 runtime `knowledge.yaml` 描述同一 transition 時無明確優先規則。可能發生 runtime 學到錯誤座標後覆蓋正確的靜態定義。

**建議**：
- 明確定義分層優先順序：**靜態 YAML（human-curated）> runtime high confidence > runtime medium > runtime low**。
- 為 runtime transition 加入 `success_count`/`failure_count`/`last_verified` 欄位，實作 confidence 遞減（失敗時降級）與時間衰減（超過 N 天未驗證則降回 low）。
- 當 runtime 與靜態衝突時，記錄為 "tension"（不覆寫靜態），需人工審閱後合併。
- 參考 ElephantBroker 的四態驗證模型（unverified → low → medium → high），以及 PRECEPT 的 Bayesian source reliability。

**參考 URL**：
- [ElephantBroker: Knowledge-Grounded Cognitive Runtime — 4-state evidence verification](https://arxiv.org/pdf/2603.25097)
- [PRECEPT: Conflict-Aware Memory with Bayesian Source Reliability](https://arxiv.org/html/2603.09641v1)
- [SRIP-19: Recursive Contradiction Buffering for multi-agent runtimes](https://github.com/sigmastratum/documentation/blob/main/srs/registry/SRIP-19-RCB.md)
- [Conflict-Aware Memory for Embodied Agents (ACL 2026)](https://aclanthology.org/2026.acl-long.1306.pdf)

**優先級**：高
**預期效果**：消除 runtime 錯誤學習覆蓋 human-curated 知識的風險；AD-6 的 confidence 升降需求直接落地；衝突可追蹤、可審計。

---

### 建議 3：Pydantic Schema Validation Gate

**問題**：`_load_yaml` 使用 `yaml.safe_load` 後直接存為 dict，無型別檢查。缺少 `system_id` 的 YAML 會靜默被忽略（`sys_id = system.get("system_id", yaml_file.stem)`），座標為字串等格式錯誤只在執行期 crash。

**建議**：
- 為每類 YAML 定義 Pydantic model（`SystemSchema`、`FlowGraphSchema`、`GameInfoSchema`、`InvariantSchema`）。
- 在 `_load` 階段用 Pydantic `model_validate(data)` 取代裸 dict 存取；驗證失敗時 raise 明確錯誤而非靜默忽略。
- 可用 `yaml2pydantic` 風格讓 schema 本身也以 YAML 宣告，降低 schema 維護成本。

**參考 URL**：
- [yaml2pydantic — YAML schema to dynamic Pydantic models](https://github.com/banduk/yaml2pydantic)
- [G-KMS: Schema-Governed LLM Pipeline — normalization & validation gates](https://www.mdpi.com/2079-8954/14/2/175)
- [pydantic-yaml — YAML capabilities for Pydantic](https://pydantic-yaml.readthedocs.io/en/latest/)

**優先級**：高
**預期效果**：YAML 格式錯誤在載入時立即暴露（fail-fast）；IDE 可從 Pydantic model 產生 JSON Schema 用於 YAML 編輯器自動補全；消除 runtime KeyError / TypeError 類 bug。

---

### 建議 4：座標正規化 — Virtual Coordinate + Anchor-Relative 混合系統

**問題**：AD-4 明確指出座標為絕對像素、解析度變更即失效。`flow_graph.yaml` 有 `<x>,<y>` 佔位符，代表座標可靠性不足是常態。目前無 fallback。

**建議**：
- 採用 **Virtual Coordinate** 系統：定義參考解析度（如 1280x720），所有 YAML 座標以此為基準。runtime 依實際解析度做線性映射。
- 高頻 UI 元素改用 **Anchor-Relative** 定位（如 `anchor: top-right, offset: {x: -50, y: 30}`），參考 CEGUI UDim 設計。
- 為尚未確認的座標加入 `reliability: investigating | confirmed | stable` 欄位；`investigating` 座標不直接使用，改走 Vision re-detection fallback。
- 長期目標：OmniParser 風格的 element-id 選取取代裸座標（AD-4 已規劃）。

**參考 URL**：
- [GameDev StackExchange: Virtual coordinates for resolution independence](https://gamedev.stackexchange.com/questions/2159/what-coordinate-system-to-use-to-handle-2d-ui)
- [Resolution Independence Strategies](https://gamedev.stackexchange.com/questions/15553/how-do-i-make-a-resolution-independent-system)
- [Unity Agent Workflows: Coordinate Space Conversion](https://github.com/AUN-PN/unity-agent-workflows/blob/main/references/coordinate-space-conversion.md)

**優先級**：中（依賴 AD-4 roadmap）
**預期效果**：解析度變更不再需要逐一修改座標 YAML；`investigating` 座標有明確降級路徑而非盲目點擊；為未來 grounding 層鋪路。

---

### 建議 5：Multi-Game Isolation — Scoped KB + File Locking

**問題**：`_kb_cache` 是 module-level global dict，同 process 多遊戲共用無問題，但並行 session 寫入同一 `knowledge.yaml` 有 race condition（`save_runtime()` 為 read-modify-write 無鎖）。

**建議**：
- 為 `save_runtime()` 加入 file-level advisory lock（`fcntl.flock` on Linux / `msvcrt.locking` on Windows），或改用 atomic write（寫 temp file + rename）。
- 若未來需要多 process 並行，升級 runtime layer 為 SQLite（單檔、內建並發控制、支援 WAL mode），保留 YAML 作為 human-readable export。
- `_kb_cache` 加入 cache invalidation（基於 file mtime），避免長時間 process 中快取過期。

**參考 URL**：
- [KGN: PostgreSQL-backed knowledge graph with advisory locking](https://github.com/baobab00/kgn)
- [Ninai: Multi-tenant isolation via PostgreSQL RLS](https://github.com/sansten/ninai)
- [MemoryMesh: JSON file storage with schema-based isolation](https://github.com/chemiguel23/memorymesh)

**優先級**：中
**預期效果**：並行 session 不再互相覆蓋 runtime 知識；為 CI 跑多遊戲測試掃除障礙；長期可平滑過渡到 DB-backed storage。

---

### 建議 6：跨遊戲知識複用 — Shared Knowledge Layer

**問題**：每個遊戲完全獨立一套 `knowledge/<game>/`，但 WebGL 遊戲有大量共通 pattern（登入 flow、loading screen 偵測、通用 popup dismiss、常見 UI layout）。每加一個遊戲就要從零撰寫。

**建議**：
- 建立 `knowledge/_shared/` 目錄，放置跨遊戲的共通知識模板：
  - `patterns/login.yaml`（通用登入 flow 骨架）
  - `patterns/popup_dismiss.yaml`（常見彈窗關閉策略）
  - `patterns/loading_detection.yaml`（loading screen 判斷）
- `KnowledgeBase._load()` 先載入 `_shared/`，再用遊戲特定的 YAML overlay（深層合併）。
- 參考 KLPEG 的知識圖譜跨版本複用、AWS Game Testing Agent 的 game-agnostic Knowledge Base 設計。

**參考 URL**：
- [KLPEG: Knowledge Graph for cross-version reuse in game testing](https://doi.org/10.48550/arxiv.2511.02534)
- [AWS Game Testing Agent: Game-agnostic Knowledge Base + discovery module](https://aws.amazon.com/blogs/gametech/building-an-ai-game-testing-agent-with-amazon-bedrock/)
- [KG Test Agent: Knowledge graph as single source of truth with delta engine](https://github.com/joyboseroy/kg_test_agent)

**優先級**：中
**預期效果**：新遊戲 onboarding 時間大幅縮短；共通 pattern 只需維護一份、升級自動惠及所有遊戲；建立組織級的 QA 知識資產。

---

### 建議 7：Knowledge Graph 化 — 從扁平 YAML 演進為結構化圖

**問題**：目前知識以扁平 YAML + BFS over edges list 實作，隨遊戲複雜度增長（系統 > 20、edge > 50），查詢效率與表達力將受限。無法表達「間接影響」（如 A 升級影響 B 技能冷卻影響 C 任務進度）。

**建議**：
- 短期：將 `flow_graph` 的 edges 建為 `networkx.DiGraph`，支援多跳推理（找影響範圍）、cycle detection、weighted shortest path。
- 中期：引入 Knowledge Triple 結構 `(System, Relation, System)` 搭配 typed edges（`triggers`, `blocks`, `requires`, `conflicts_with`），支援因果推理。
- 長期：參考 KLPEG 的 KG + LLM 多跳推理，在遊戲更新時自動推斷影響範圍並生成測試目標。

**參考 URL**：
- [KLPEG: KG-enhanced LLM for incremental game playtesting — multi-hop reasoning](https://doi.org/10.48550/arxiv.2511.02534)
- [KG Test Agent: AST → Knowledge Graph → Delta Engine → Test Generation](https://github.com/joyboseroy/kg_test_agent)
- [Multi-Agent Game Factory: Vector RAG + Knowledge Graph pipeline](https://github.com/aaron-ywl/multi-agent-game-factory)
- [Director-AI: Conflict-Aware Knowledge Checks](https://anulum.github.io/director-ai/api/conflict-aware-knowledge/)

**優先級**：低（roadmap / 長期演進）
**預期效果**：支援「遊戲更新時哪些測試需要重跑」的自動推理；系統間隱性依賴可被發現；為 L3 確定性回歸層（AD-7）提供結構化基礎。

---

## 總結優先級排序

| # | 建議 | 優先級 | 對應 AD |
|---|------|--------|---------|
| 1 | Schema Version + 遷移管線 | 高 | — |
| 2 | 分層衝突解決策略 | 高 | AD-6 |
| 3 | Pydantic Schema Validation | 高 | AD-3 |
| 4 | 座標正規化（Virtual + Anchor） | 中 | AD-4 |
| 5 | Multi-Game Isolation + File Locking | 中 | — |
| 6 | 跨遊戲知識複用層 | 中 | — |
| 7 | Knowledge Graph 演進 | 低 | AD-7 |

---

*建議由 software-architect 基於程式碼分析與業界最佳實踐研究產出。每條建議的 URL 均為 2024-2026 年間的相關開源專案或學術論文。*
