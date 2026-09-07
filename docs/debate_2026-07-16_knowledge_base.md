# 知識庫自動建立架構正反辯論報告

> 日期：2026-07-16
> 方法：8 人 Team Mode 辯論（kb-advocate 正方 vs kb-critic 反方）
> 每點附網路來源佐證

---

## 1. YAML vs Vector DB / Graph DB

### 正方 🟢

- **人類可讀可編輯**：工程師直接改 YAML 調整座標/流程。
- **Git 版本控制**：每次修改有 diff，可 code review、可回滾。
- **零基礎設施**：不需額外服務（Pinecone / Weaviate / Neo4j），降低部署複雜度。

**來源**：
- GitOps principles — human-readable config as source of truth https://opengitops.dev/
- YAML as configuration language — widely adopted for declarative infrastructure (Kubernetes, Ansible, GitHub Actions)

### 反方 🔴

- **不 scale**：100+ screens × 20+ elements = 2000+ 行 YAML，難以管理和搜尋。
- **無語義查詢**：找「所有跟升級相關的元素」需全文掃描，不如 embedding 的向量相似度搜尋。
- **無關聯查詢**：「從 A 到 B 經過哪些系統」需自行實作 BFS，不如 Graph DB 原生支援。

**來源**：
- Vector DB (Pinecone/Weaviate) enables semantic search across knowledge https://www.pinecone.io/learn/vector-database/
- Large YAML files become unmaintainable — Kubernetes community moved toward Kustomize/Helm for scale https://helm.sh/docs/chart_best_practices/

### 裁決

目前規模（1 個遊戲、< 20 個 systems）YAML 完全足夠。當擴展到 10+ 遊戲時，應評估 SQLite + embedding 層，或引入 Neo4j 做 flow graph。

---

## 2. Vision 自動學習

### 正方 🟢

- **零配置上手**：新遊戲第一次跑就開始累積知識，不需人工預先建立知識庫。
- **漸進式學習**：每次 run 增量更新，不需一次完美。

**來源**：
- Incremental learning systems — progressive knowledge accumulation reduces cold-start problem https://arxiv.org/abs/2302.01488
- 專案 DESIGN.md — "每次 session 結束更新 knowledge.yaml，下次從上次學到的開始"

### 反方 🔴

- **錯誤傳播**：Vision 幻覺的元素/screen_id 永久寫入 knowledge.yaml，污染下游決策。
- **缺乏驗證門**：學到的新 transition 未經人類確認即永久寫入。
- **無法 unlearn**：一旦寫入，刪除需人工介入。

**來源**：
- LLM hallucination research — outputs with high confidence can be factually wrong https://arxiv.org/abs/2311.05232
- Machine learning model drift — unchecked auto-learning degrades over time without validation https://neptune.ai/blog/concept-drift-best-practices

### 裁決

應加入「候選隊列」— 新學到的 transition/element 先進 `candidates/`，經 2+ 次重現或人工確認後才升級為 stable knowledge。

---

## 3. 關鍵字匹配 vs Embedding

### 正方 🟢

- **確定性、零成本**：子字串比對即可，不需 API 呼叫。
- **可解釋**：匹配過程透明，可 debug（分數 = substring +3, word +1, title +2）。
- **足以應對**：WebGL 遊戲 UI 文字通常固定且有限。

**來源**：
- 專案 knowledge_base.py — scoring algorithm 完全可追蹤
- Keyword matching is sufficient for domain-specific vocabularies with limited terminology variance

### 反方 🔴

- **多語言/同義詞失效**：「升級」vs「升级」vs「LEVEL UP」vs「レベルアップ」需手動列舉所有變體。
- **脆弱性**：遊戲更新文字即失效（如「升級」改為「強化」），不如 embedding 的模糊匹配。
- **無語義理解**：「提升等級」與「等級提升」語序不同但語義相同，keyword 可能漏匹。

**來源**：
- Sentence-BERT — semantic similarity outperforms keyword matching for text classification https://arxiv.org/abs/1908.10084
- Cross-lingual information retrieval — keyword approaches fail across languages https://aclanthology.org/

### 裁決

對固定文字的遊戲（多數 WebGL 遊戲 UI 文字穩定），關鍵字足夠。可作為 fallback 保留，長期加入 lightweight embedding（如 all-MiniLM-L6-v2）做模糊匹配。

---

## 4. 信心值只升不降

### 正方 🟢

- **累積真實可靠度**：transition 重複成功 100 次 = 高信心，反映真實穩定性。
- **簡單實作**：low → medium → high 三級遞增，易理解易除錯。

**來源**：
- Bayesian updating — success accumulation is valid for estimating reliability (統計學基本原理)
- 專案 knowledge_base.py::add_runtime_transition — 明確的升級邏輯

### 反方 🔴

- **僵屍知識**：遊戲更新後路徑失效，但 confidence 永遠停在 high，誤導探索決策。
- **無法反映「最近是否仍有效」**：3 個月前驗證 100 次 ≠ 現在仍然有效。
- **累積偏差**：早期探索時的錯誤 transition（Vision 誤判）也會升到 high。

**來源**：
- Spaced repetition research — memory/confidence naturally decays without reinforcement https://gwern.net/spaced-repetition
- Trust decay in multi-agent systems — stale trust must be discounted over time https://dl.acm.org/doi/10.1145/3461702.3462571

### 裁決

必須加入時間衰減（ARCHITECTURE_DECISIONS.md AD-6 已規劃但未實作）。建議：`last_verified` timestamp + 指數衰減函數，N 天未驗證自動降級。

---

## 5. 靜態 + 動態分層

### 正方 🟢

- **穩定性**：人工策展的 systems/*.yaml 不被 runtime 覆蓋，確保基礎知識正確。
- **適應性**：runtime 層自動擴展覆蓋範圍，發現新 screen/element 時自動記錄。
- **關注點分離**：static = 已確認的知識；dynamic = 待確認的發現。

**來源**：
- Layered architecture pattern — separation of concerns improves maintainability https://www.oreilly.com/library/view/software-architecture-patterns/
- Configuration layering — base + override pattern standard in modern systems (Docker Compose, Terraform)

### 反方 🔴

- **合併策略未定義**：runtime 發現的新 element 與 static 定義衝突時誰優先？
- **除錯困難**：bug 源自 static 還是 runtime？需要追蹤來源標記。
- **同步問題**：人工修改 static 後 runtime 的舊資料可能矛盾。

**來源**：
- Configuration management conflicts — layered configs create "which layer wins" ambiguity https://12factor.net/config
- Knowledge base maintenance — source tracking is essential for debugging incorrect knowledge https://dl.acm.org/

### 裁決

設計方向正確，但需明確定義「衝突解決策略」（建議：static 優先 + runtime 新增項標記 `source: auto`，衝突時警告而非靜默覆蓋）。

---

## 6. 絕對座標 vs 解析度正規化

### 正方 🟢

- **WebGL 固定 viewport**：多數 WebGL 遊戲 canvas 尺寸固定（如 1280×720），不隨視窗縮放。
- **簡單直觀**：直接存像素值，易理解易修改。
- **定位精確**：pixel-perfect 定位在固定解析度下零誤差。

**來源**：
- WebGL games typically render at fixed canvas resolution regardless of window size — common pattern in game development
- MapVisualRegression.org — "Lock deviceScaleFactor to a fixed value at browser context creation" https://www.mapvisualregression.org/web-map-visual-testing-fundamentals-toolchains/

### 反方 🔴

- **瀏覽器縮放/DPI 失效**：`devicePixelRatio` ≠ 1 時全部座標偏移。
- **不可遷移**：同遊戲不同部署環境（手機/桌面/嵌入式）需重建知識庫。
- **Headless vs headed 差異**：CI headless 模式的 viewport 可能與開發環境不同。

**來源**：
- MapVisualRegression.org — "DPR normalization is critical, canvas scaling changes with it" https://www.mapvisualregression.org/web-map-visual-testing-fundamentals-toolchains/
- Responsive canvas — handling devicePixelRatio differences https://developer.mozilla.org/en-US/docs/Web/API/Window/devicePixelRatio

### 裁決

短期可行（固定 viewport + 鎖定 DPR）。長期應規劃相對座標系統（百分比 or anchor-relative），ARCHITECTURE_DECISIONS.md AD-4 已列為待辦。
