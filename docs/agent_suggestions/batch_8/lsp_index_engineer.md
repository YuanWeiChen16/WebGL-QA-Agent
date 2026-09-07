# LSP/Index Engineer 審查建議

> 審查角色：LSP/Index Engineer — 語意索引、結構化查詢、跨引用完整性、代碼智能  
> 審查對象：`KNOWLEDGE_ARCHITECTURE.md` 及相關知識庫實作  
> 日期：2026-07-16

---

## 建議 1：引入 YAML 跨文件引用完整性驗證（Referential Integrity）

**問題**：`flow_graph.yaml` 的 edges 以字串引用 `system_id`（如 `from: gameplay`、`to: upgrade`），但無任何機制驗證這些 ID 是否對應到 `systems/` 目錄下實際存在的 YAML 檔案。一個打字錯誤（如 `upgarde`）會讓 BFS 路徑查詢靜默失敗，與 LSP 規範中「所有 reference 必須解析到 definition」的原則相悖。

**建議**：
- 引入如 `cartulary` 的跨文件引用完整性驗證工具，在 CI 中宣告 `system_id` 為 primary key，`flow_graph.yaml` 的 `from`/`to` 為 foreign key reference，自動檢測懸空引用
- 或使用 `darig` 的 SQL-over-YAML 方案，對知識庫做 `SELECT * FROM edges WHERE from NOT IN (SELECT system_id FROM systems)` 式的完整性查詢
- 最低限度：在 `KnowledgeBase.__init__()` 加入啟動時驗證，確保所有 edge 節點在 `systems_by_id` 中存在

**參考**：
- cartulary（跨文件 referential integrity）：https://pypi.org/project/cartulary/0.3.0/
- darig（YAML schema + SQL query）：https://github.com/Vibe1NG/darig
- linkml-store referential integrity：https://linkml.io/linkml-store/how-to/Check-Referential-Integrity.html

---

## 建議 2：建立全局符號表與層級化 ID 命名空間

**問題**：各 system YAML 內的 `elements[].id` 和 `actions` 鍵名缺乏全局唯一性保證。若 `login.yaml` 和 `upgrade.yaml` 都定義 `id: confirm_button`，`KnowledgeBase` 無法無歧義地解析引用。這等同於 LSP 中兩個檔案定義同名 symbol 卻無 fully-qualified name 的問題。

**建議**：
- 採用層級化 ID 方案：`{system_id}.{element_id}`（如 `upgrade.confirm_button`、`login.confirm_button`）
- 在 `flow_graph.yaml` 的 action 中引用元素時使用完整路徑：`action: { element: "upgrade.upgrade_toggle_button" }`
- 建立類似 LSIF 的 symbol index（`.jsonl` 格式），記錄每個 symbol 的定義位置與所有引用位置，支援跨系統的 go-to-definition

**參考**：
- LSIF（Language Server Index Format）規範與實作：https://code.visualstudio.com/blogs/2019/02/19/lsif
- Sourcegraph LSIF 一年回顧（cross-repo navigation）：https://sourcegraph.com/blog/evolution-of-the-precise-code-intel-backend
- semnav（LSP 結果持久化為語意圖）：https://github.com/Yasu-umi/semnav

---

## 建議 3：實作增量更新與分層快取失效機制

**問題**：`KnowledgeBase.__init__()` 在建構時全量載入所有 systems、flow_graph、problems。對於一個持續運行的 QA agent（accumulating runtime knowledge），每次修改單一 YAML 就重建整個知識庫會造成：
1. 延遲高峰（大量 YAML 重新解析）
2. 潛在的狀態不一致（重建過程中的查詢可能讀到半成品）
3. 無法支援 hot-reload 場景

**建議**：
- 採用三層快取架構（類似 Probe 的 L1/L2/L3 設計）：
  - L1：記憶體內 Python dict（<1ms 存取）
  - L2：以 content hash（MD5/SHA256）為鍵的磁碟快取（跨 session 持久化）
  - L3：YAML 檔案重新解析（僅在 hash 變更時觸發）
- 使用 file watcher（watchdog）監控 `knowledge/` 目錄變更，僅重載變更的檔案
- flow_graph 的 BFS 路徑快取在任何節點/邊變更時選擇性失效（而非全量清除）

**參考**：
- Probe LSP indexing 三層快取架構：https://github.com/probelabs/probe/blob/main/docs/indexing-overview.md
- semnav 增量快取與失效策略：https://github.com/Yasu-umi/semnav

---

## 建議 4：以 Graph Shape Contract 驗證知識庫結構品質

**問題**：目前知識庫缺乏「結構品質閘門」——沒有機制確保新增的 system YAML 符合預期 schema（必填欄位、座標範圍、action steps 格式）。這類似於 property graph 缺少 SHACL-style constraint 的問題。

**建議**：
- 定義 PG Shape Contract（YAML 格式），宣告每個 system node 必須具備的 properties（`system_id` required、`entry_points[].action.x/y` 必須為正整數、`actions` 至少一個 step）
- 在 CI pipeline 中執行 shape validation，產出 violation report
- 對 `flow_graph.yaml` 的 edge 加入 cardinality constraint（每個 system 至少有一個 entry_point 或 exit_point）
- 可參考 Graphora Ontology Editor 的品質評分系統（0-100 分）做知識庫健康度指標

**參考**：
- PGSC（SHACL-style property graph validator）：https://github.com/Kineviz/pgsc
- Graphora Ontology Editor（YAML 知識圖譜品質驗證）：https://docs.graphora.io/client/ontology-editor/introduction

---

## 建議 5：引入語意向量搜尋取代手工評分式 keyword matching

**問題**：`find_solution()` 的評分機制（子字串 +3、詞 +1、標題 +2）本質上是手寫的 TF-IDF 近似。面對 Vision OCR 的常見問題：
- 繁簡混用（「升級」vs「升级」）
- OCR 錯字（「提昇」誤讀為「提升」或「提早」）
- 同義詞（「卡住」=「stuck」=「凍結」=「無反應」）

手工評分無法擴展，且新增語言/變體需不斷維護 `recognition_keywords`。

**建議**：
- 導入多語言 embedding 模型（如 `BAAI/bge-m3`，支援 100+ 語言，含中文繁簡）做語意向量索引
- 對所有 `recognition_keywords`、`known_issues[].symptoms`、`problems/*.md` 建立向量索引
- 查詢時將 OCR 文字 embed 後做 cosine similarity，自動處理 typo 容忍與跨語言匹配
- 輕量替代方案：使用 `vibe-finder`（純 Python、零依賴）做 gap-tolerant fuzzy phrase matching，專為 OCR 錯誤設計
- 混合架構：keyword exact match（快、確定性）+ semantic fallback（OCR 文字匹配不到時）

**參考**：
- DeepTextSearch（多語言 hybrid search + reranking）：https://github.com/TechyNilesh/DeepTextSearch
- vibe-finder（OCR typo-tolerant fuzzy matching）：https://pypi.org/project/vibe-finder/
- HybridRAG（Knowledge Graph + Vector + Fuzzy Search）：https://github.com/TrongNV2003/HybridRAG
- FoxNose Hybrid Search API（multilingual semantic + typo tolerance）：https://foxnose.net/product/search

---

## 總結

從語意索引與代碼智能的角度，本知識架構的核心缺陷是**缺乏 LSP 世界中視為理所當然的基礎設施**：

| LSP 世界的標準 | 本專案現狀 | 建議方向 |
|---|---|---|
| Referential integrity（reference → definition） | 字串引用無驗證 | cartulary / 啟動時驗證 |
| Fully-qualified symbol names | 平坦 ID 可衝突 | 層級化 `system.element` |
| Incremental indexing + cache | 全量重建 | 三層快取 + file watcher |
| Schema validation（LSP capabilities） | 無 schema 約束 | PGSC / JSON Schema |
| Fuzzy symbol search | 手工評分 | 向量語意搜尋 |

這些改善不需要一次到位，建議優先順序：**建議 1 > 建議 2 > 建議 5 > 建議 3 > 建議 4**（前兩者是正確性問題，後三者是效能與體驗問題）。
