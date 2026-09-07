# 知識庫綜合報告審查意見與修正建議

> **審查者**：KB Architecture Reviewer  
> **審查對象**：`03_knowledge_base_synthesis.md`  
> **交叉參考**：`01_qa_testing_synthesis.md`、`02_performance_synthesis.md`、`04_architecture_synthesis.md`  
> **日期**：2026-07-17

---

## 問題 1：Golden Dataset 優先級與 QA 報告存在嚴重矛盾

**矛盾點**：知識庫報告將「Golden Dataset + Oracle precision 量化」列為 **P2 #12**（中期 1-2 月），但 QA 測試報告（01）將「建立 Vision OCR 精確度基線」列為 **P0 #3**（立即處理）。

**質疑**：如果 Oracle 的 ground truth 完全依賴 Vision LLM OCR，且 WER 可能高達 46%，那麼在沒有量化基線的情況下，報告中所有依賴 Oracle 判定的改善方案（Confidence 機制、Feedback Loop、趨勢分析）的效益都無法被驗證。這不是「中期」才需要的東西——它是衡量其他改善是否有效的**前置條件**。

**修正建議**：Golden Dataset 應提升至 P0 或 P1 初期。至少需要一個 minimal viable 版本（20-30 張標註截圖）來建立 baseline，否則後續所有「precision 提升 X%」的宣稱都是無根據的。

---

## 問題 2：screen_id 穩定化的優先級跨報告不一致，且缺乏遷移策略

**矛盾點**：
- 知識庫報告：P0 #4（1-3 天）
- 架構報告（04）：Phase 3 #13（1-2 月，難度「中」）
- QA 報告（01）：P0 #4

**缺失**：三份報告都未提及一個關鍵問題——**如果改變 screen_id 生成邏輯，所有現有 runtime knowledge（transitions、confidence scores、strategies）都會因為主鍵變更而成為孤兒資料**。報告中完全沒有遷移策略。

**質疑**：聲稱 pHash pre-filter 只需「30 行 + imagehash」就能完成，但實際上還需要：
1. 舊 screen_id → 新 screen_id 的映射表/遷移腳本
2. Hamming distance 閾值的 per-game 校準（< 8 是否對所有遊戲通用？）
3. 與現有 `flow_graph.yaml` 中 screen 節點名稱的同步

**修正建議**：在 P0 列表中明確加入「screen_id 遷移計畫」，且將工作量估算從「30 行」修正為包含遷移與校準的實際範圍（預估 2-3 天而非半天）。

---

## 問題 3：PaddleOCR L1.5 的延遲與「近零成本偵測層」承諾衝突

**矛盾點**：知識庫報告在 §2 建議 PaddleOCR 作為 P1 本地 OCR 層（標記為 `<50ms/zero API`），但效能報告（02）明確指出 PaddleOCR CPU 延遲為 **340ms**，且確定性偵測層的整體預算是 **<20ms**。

**質疑**：
- 如果 PaddleOCR 在 CPU 上需要 340ms，它根本不能被放在每個 `observe()` 迴圈中
- 若改用 GPU 加速（45ms），則違反「零額外硬體需求」的黑箱原則
- 報告中標記的 `<50ms` 是否有來源支撐？還是從 GPU benchmark 誤植？

**修正建議**：明確定位 PaddleOCR 為「按需觸發」而非「每步執行」，並在效能預算表中標註其實際延遲。建議的呼叫策略應為：`pixel_diff 偵測到 UI 區域變化 → 觸發 PaddleOCR ROI crop`，而非持續輪詢。

---

## 問題 4：Confidence 機制（Beta-Bernoulli）是否為投機性架構？

**背景**：架構報告 §10.1 引述 Minimal Change 審查者明確警告：「confidence 機制無消費者 → 應暫緩」。知識庫報告仍將 Beta-Bernoulli 後驗列為 P2 #13。

**質疑**：
1. 目前哪個模組會**消費** confidence 分數來做決策？報告未列出具體消費者。
2. 如果 screen_id 本身不穩定（P0 問題），那麼在不穩定主鍵上累積的 success/failure count 有統計意義嗎？
3. Beta-Bernoulli 需要多少樣本才能產生有意義的 95% credible interval？若 session 平均只跑 50-100 步，per-transition 樣本數可能永遠不足。

**修正建議**：
- 將 Confidence 改善標記為「blocked by screen_id stabilization」
- 在實作前先定義消費者介面（哪些模組讀取 confidence、在什麼閾值下做什麼決策）
- 考慮先用簡單的 `success_count / total_count` 替代 Beta-Bernoulli，降低認知負擔

---

## 問題 5：YAML 作為 Source of Truth 的規模天花板未被正視

**問題**：知識庫報告 §7.4 堅持「YAML 為 source of truth + SQLite 為可重建的衍生索引」，但效能報告（02）§5.3 指出 500KB+ 的 knowledge.yaml 每次寫入需 100-200ms 且阻塞 event loop。

**質疑**：
1. 如果一個遊戲的 runtime knowledge 持續累積，YAML 檔案會無限增長。報告未定義任何**上限**或**淘汰策略**。
2. 「人類可讀」的 YAML source of truth 在 500KB 時已經不可能手動閱讀/編輯——此時它與 SQLite 的「人類可讀性」差異幾乎為零。
3. 併發場景下的 file lock + atomic write 在大檔案上的延遲會更嚴重。

**修正建議**：
- 定義 knowledge.yaml 的**規模閾值**（例如 200KB），超過後自動分片或遷移至 SQLite
- 在 §3 的 atomic write 方案中加入 size-aware 策略（小檔案 atomic YAML、大檔案 SQLite WAL）
- 將「YAML 為永遠的 source of truth」改為「YAML 為初期 source of truth，達到規模閾值後平滑遷移至 SQLite」

---

## 問題 6：跨遊戲知識複用（§13）缺乏驗證機制與失敗案例分析

**問題**：§13 提出 `knowledge/_shared/` 共通模板（login/popup/loading），但：

**質疑**：
1. 登入流程在不同遊戲間的差異極大（OAuth vs 帳密 vs 手機驗證 vs 免登入），「共通模板」能抽象到什麼程度？報告未定義抽象層級。
2. 無**驗證機制**：shared knowledge 套用到新遊戲後，如何判斷它是否有效？錯誤的 shared knowledge 會不會比沒有 knowledge 更糟糕（引導 agent 走錯路）？
3. 引用的 AWS Game Testing Agent 案例是**有原始碼存取權**的白箱測試，與本專案的純黑箱假設根本不同。
4. 無失敗案例分析：什麼情況下 shared knowledge 會**主動有害**？

**修正建議**：
- 加入「shared knowledge applicability check」機制：套用前先驗證（例如 pHash 比對確認 login 畫面相似度 > 0.7）
- 將 §13 的優先級從 ★★★☆☆ 降至長期探索性研究
- 移除 AWS 案例引用或加入注記說明其白箱假設不適用

---

## 問題 7：全域優先級表的「工作量」估算系統性偏低

**問題**：P0 列表聲稱 5 項共需「1-3 天」，但：

| 項目 | 報告估算 | 實際考量 |
|------|----------|----------|
| finish() verdict | 2-5 行 | 需定義 verdict 計算邏輯、edge cases（partial success?）、與 reporter 整合 |
| atomic write | 10 行 | 需加測試、處理 Windows 跨磁碟 os.replace 限制、.bak rotation |
| Vision per-session cap | 20 行 | 需定義降級行為、config schema、telemetry 記錄、與 circuit breaker 互動 |
| pHash pre-filter | 30 行 | 需校準閾值、遷移舊資料、處理 edge cases（見問題 2） |
| Image resize/ROI | 30 行 | 需定義 per-task ROI 策略、修改 Vision 呼叫鏈、驗證不影響 LLM 判讀品質 |

**質疑**：「行數」不等於「工作量」。每項都還需要：測試、文件更新、config 欄位設計、edge case 處理。實際工時可能是聲稱的 2-3 倍。

**修正建議**：改用「人天」而非「行數」作為估算單位，並將 P0 的期望時程從「1-3 天」修正為「1-2 週」（含測試與整合），避免設定不切實際的預期。

---

## 問題 8：可觀測性（§10）與其他改善項目的依賴關係被低估

**問題**：structlog + correlation ID 被列為 P1 #9，但幾乎所有 P0 改善（circuit breaker、cost cap、screen_id 穩定化）的**效果驗證**都依賴可觀測性基礎設施。

**質疑**：
1. 沒有 structured logging，如何量化 circuit breaker 的觸發頻率？
2. 沒有 per-call telemetry，如何驗證 image preprocessing 真的節省了 40-70% token？
3. 沒有 correlation ID，如何在 multi-session 場景下追蹤特定 failure 的根因？

**矛盾**：效能報告（02）將 Structured Logging 列為 **P0**，架構報告（04）也列為 Phase 1 #7（1-2 週），但知識庫報告將其降為 P1。

**修正建議**：將 structlog + Vision telemetry 提升至 P0，作為所有其他改善的**可觀測性前置條件**。建議順序應為：`observability → cost cap → circuit breaker → screen_id`，而非報告目前的排列。

---

## 總結：建議的修正優先級排序

基於以上 8 點審查，建議將知識庫報告的 P0 列表修正為：

| 原排序 | 修正排序 | 項目 | 理由 |
|--------|----------|------|------|
| — | **新增 P0** | structlog + Vision telemetry | 驗證其他改善的前置條件 |
| P2 #12 | **提升至 P0** | Golden Dataset minimal（20-30 張） | Oracle 可靠性的量化基礎 |
| P0 #1 | 維持 P0 | finish() verdict + exit code | CI 前置 |
| P0 #2 | 維持 P0 | atomic write + .bak | 資料安全 |
| P0 #3 | 維持 P0 | Vision per-session hard cap | 防災難花費 |
| P0 #4 | 維持 P0 但修正估算 | screen_id pHash（含遷移計畫） | 改為 3-5 天估算 |
| P0 #5 | 維持 P0 | Image resize/ROI | token 節省 |

---

*本審查基於跨報告交叉分析。每個問題都指向具體的矛盾或缺失，而非方向性異議。知識庫報告的整體架構與主題分類品質優良，上述修正旨在提升其可執行性與一致性。*
