# Codebase Onboarding Engineer — 架構審查建議

> 審查日期：2026-07-16
> 角色：Codebase Onboarding Engineer（新進開發者快速理解 codebase 的專家）
> 審查對象：DESIGN.md、KNOWLEDGE_ARCHITECTURE.md、知識庫架構

---

## 摘要

以新進開發者視角審查本專案的文件與架構，發現 5 個影響 onboarding 效率的議題。KB Defender 回應確認其中 2 項為 documentation debt、2 項為已知取捨、1 項已有緩解機制。以下為具體改善建議，每項附業界參考資源。

---

## 建議 1：導入 Architecture Decision Records (ADR) 解決文件分裂

### 問題

DESIGN.md 的 `knowledge.yaml` schema（screens/flow_graph/bugs 扁平結構）與 KNOWLEDGE_ARCHITECTURE.md 的目錄結構（systems/*.yaml + flow_graph.yaml + problems/*.md）表面上是兩套知識表達。KB Defender 確認這是「靜態層 vs runtime 層」的刻意分層，但 DESIGN.md 未標記舊 schema 的適用範圍，新人容易混淆 source of truth。

### 建議

1. 在 DESIGN.md 第 144 行 Knowledge Schema 區段加入 `> ⚠️ Deprecated scope notice`，標明此 schema 僅描述 runtime 動態學習層，靜態層以 KNOWLEDGE_ARCHITECTURE.md 為準。
2. 建立 `docs/adrs/` 目錄，採用 ADR（Architecture Decision Record）格式記錄「為何分兩層」「為何 screen_id 由 Vision 自由命名」等關鍵決策，避免未來開發者重複追問相同問題。
3. 考慮導入 Truth Syncing 實踐——每次修改架構程式碼時，同步更新對應的設計文件，作為 PR 的 Definition of Done 之一。

### 參考資源

- Martin Fowler — Architecture Decision Records：https://martinfowler.com/bliki/ArchitectureDecisionRecord.html
- DeployIt — ADR from Git: Always Current（自動化 ADR 與 PR 綁定）：https://deployit.ai/blog/architecture-decision-records-from-git-always-current
- Cortex TMS — Truth Syncing（文件同步實踐）：https://cortex-tms.org/concepts/truth-syncing/
- CODITECT — ADR Single Source of Truth Consolidation（多 repo ADR 合併案例）：https://docs.coditect.ai/architecture/adrs/adr-150-adr-single-source-of-truth

---

## 建議 2：引入 Perceptual Hashing 解決 screen_id 主鍵穩定性

### 問題

Runtime screen_id 由 Vision LLM 自由命名，同一畫面可能被命名為 "gameplay_main" 或 "fishing_screen"，導致 runtime flow_graph 出現冗餘節點。KB Defender 確認靜態層 system_id 穩定，但 runtime 探索品質受影響。

### 建議

1. 對每張截圖計算 perceptual hash（如 64-bit average hash 或 pHash），作為 screen 的 canonical visual fingerprint。
2. 使用 Hamming distance 比對（閾值建議 8 bits / 12.5%），在 `add_runtime_screen()` 時自動偵測：若新截圖的 hash 與既有 screen 的 reference hash 距離 ≤ 閾值，則合併到同一 screen_id 而非創建新節點。
3. 此機制完全確定性（numpy + imagehash，零 LLM 成本），可作為 canonical registry 的第一步實作。
4. 進階：結合 SSIM（目前已有）+ perceptual hash 雙重確認，SSIM 處理像素級細節、pHash 處理整體結構相似度。

### 參考資源

- Firespawn Studios — Perceptual Hashing for Autonomous Agent Visual Memory（遊戲 AI agent 實際使用 pHash 做位置辨識）：https://firespawnstudios.net/blog/how-we-gave-an-ai-a-sense-of-place/
- Bugnet — Visual Snapshot Testing for Game UI Regressions（perceptual diff + CI 整合）：https://bugnet.io/blog/how-to-use-visual-snapshot-testing-for-game-ui-regressions
- AutoGameVisionTester — 使用 perceptual hashing 跳過重複幀節省 token：https://github.com/Sqeakzz/AutoGameVisionTester

---

## 建議 3：導入 Consensus Entropy 機制強化 Oracle 可靠性

### 問題

Oracle.py 的功能正確性依賴 Vision LLM 讀取畫面數值。雖然 KB Defender 確認 oracle 本身是純確定性比較器（不呼叫 Vision），且有 `min_occurrences` streak 機制過濾單次 hallucination，但上游 Vision 讀數的準確率仍無量化基準。

### 建議

1. **低成本方案（推薦）**：對關鍵數值（分數/金幣/等級）在同一幀做 2 次 Vision 呼叫（可用不同 crop region 或略微不同 prompt），比較結果是否一致。不一致時標記為 `uncertain`，oracle 跳過該次比對（與現有 None = skip 邏輯一致）。
2. **中成本方案**：引入 Consensus Entropy (CE) 概念——多個 VLM 獨立讀取同一截圖，correct predictions 在語義空間收斂、errors 則分散。CE 低 = 可信，CE 高 = 路由到更強模型或標記為 uncertain。
3. **零成本輔助**：對數值變化做 sanity check——如果 Vision 讀到的 delta 超過合理範圍（例如金幣一次增加 10000），自動標記為疑似 hallucination 並要求重讀。此規則可寫在 `game_info.yaml` 的 invariant 旁。
4. 建立 `oracle_accuracy_log.yaml`，記錄每次 Vision 讀數與後續 session 結果的對應，長期累積可計算該 gateway 在此遊戲上的 OCR 準確率基準。

### 參考資源

- Consensus Entropy: Multi-VLM Agreement for Self-Verifying OCR（CVPR 2026，F1 提升 42.1%）：https://arxiv.org/html/2504.11101v4
- Seeing is Believing? Mitigating OCR Hallucinations in MLLMs（GRPO 框架 + uncertainty awareness）：https://arxiv.org/html/2506.20168
- CE-OCR GitHub（開源實作）：https://github.com/Aslan-yulong/consensus-entropy

---

## 建議 4：建立明確的 Cost Boundary 分層圖

### 問題

KB Defender 確認 perceiver.py 是 100% 零成本（純 numpy/PIL），且 Vision 觸發的唯一入口是 `vision.py::analyze_screenshot_structured()`。但這個資訊分散在 README 架構圖和各模組 docstring 中，沒有一張單獨的 cost boundary diagram。新開發者（尤其是需要控制 API 預算的 PM/Tech Lead）需要一目了然的成本地圖。

### 建議

1. 在 DESIGN.md 或 README.md 加入明確的 Cost Boundary 表：

```markdown
## Cost Boundary（API 呼叫成本地圖）

| 模組 | 成本 | 觸發方式 | 備註 |
|------|------|----------|------|
| browser.py | 零 | 自動 | Playwright 本地操作 |
| perceiver.py | 零 | 自動 | numpy/PIL 影像分析 |
| detector.py | 零 | 自動 | 確定性異常偵測 |
| oracle.py | 零 | 顯式呼叫 | 純數值比較，不呼叫 Vision |
| vision.py | **有成本** | 顯式呼叫 | Claude Vision gateway |
| knowledge_base.py | 零 | 自動 | YAML 讀寫 |
| reporter.py | 零 | session 結束 | HTML 生成 |
```

2. 在 `vision.py` 的 docstring 頂部加入成本警告：`# ⚠️ 此模組的每次呼叫產生 LLM API 成本`。
3. 考慮在 session 報告中加入「本次 run 的 Vision 呼叫次數與估算成本」欄位。

### 參考資源

- AWS Game Tech — AI Game Testing Agent 成本追蹤（每個 test case 約 $0.20-$0.28，含 per-model token breakdown）：https://aws.amazon.com/blogs/gametech/building-an-ai-game-testing-agent-with-amazon-bedrock/
- Microsoft Inspector — Pixel-Based Game Testing（純像素輸入的成本優勢分析）：https://ar5iv.labs.arxiv.org/html/2207.08379

---

## 建議 5：實作 Incremental Persist 與 Write-Ahead Log 保障 Runtime 知識持久性

### 問題

KB Defender 確認 `save_runtime()` 是一次性全量寫入，session 中途 crash 會丟失本次 runtime 累積。這是已知取捨（頻繁寫入有 I/O 開銷 + partial write corruption 風險），但對長時間探索 session（30+ 分鐘）來說，丟失所有新發現的 screens/transitions 代價不低。

### 建議

1. **Atomic write pattern**：每次 `save_runtime()` 先寫入 `knowledge.yaml.tmp`，完成後 `os.replace()` 原子替換。這消除 partial write corruption 風險，成本極低。
2. **Periodic flush**：每 N 步（建議 N=10 或每 5 分鐘）呼叫一次 `save_runtime()`（配合 atomic write）。在 `config/default.yaml` 加入 `runtime_flush_interval_steps: 10` 可配置。
3. **WAL-lite 方案（進階）**：每次 `add_runtime_screen()` / `add_runtime_transition()` 時，append 一行 JSON 到 `knowledge.wal`（append-only，crash-safe）。啟動時若存在 WAL，replay 到記憶體再合併。這是 SQLite WAL 的簡化版，適合小型 YAML 知識庫。
4. 在 `session.json`（由 reporter 寫入 runs/ 目錄）中已有完整操作記錄，可作為 recovery source——加入一個 `recover_runtime_from_session(session_json_path)` 工具函數，從崩潰的 session.json 重建 runtime 知識。

### 參考資源

- Firespawn Studios — Agent Visual Memory 持久化（每次 action 後存入 database）：https://firespawnstudios.net/blog/how-we-gave-an-ai-a-sense-of-place/
- AWS Game Tech — Action trace + DynamoDB Streams 即時持久化：https://aws.amazon.com/blogs/gametech/building-an-ai-game-testing-agent-with-amazon-bedrock/

---

## 優先順序建議

| # | 建議 | 影響度 | 實作成本 | 推薦優先級 |
|---|------|--------|----------|-----------|
| 1 | ADR + 文件同步 | 中（onboarding 效率） | 低 | P2 |
| 2 | Perceptual Hash 去重 | 高（探索品質） | 低 | **P1** |
| 3 | Oracle 可靠性強化 | 中（減少 false positive） | 中 | P2 |
| 4 | Cost Boundary 表 | 低（文件改善） | 極低 | P3 |
| 5 | Incremental Persist | 中（長 session 容錯） | 低-中 | P2 |

**最高優先**：建議 2（Perceptual Hash）——成本極低（imagehash 套件 + ~30 行程式碼），立即解決 screen_id 穩定性這個 KB Defender 也承認的 Medium 嚴重度問題，且 Firespawn Studios 的實戰經驗證明在遊戲 AI agent 場景中效果穩定。
