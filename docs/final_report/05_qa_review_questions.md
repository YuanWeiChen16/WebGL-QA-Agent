# QA 審查問題與修訂建議

> **審查者**：Senior QA Reviewer  
> **審查範圍**：01_qa_testing_synthesis.md、02_performance_synthesis.md、03_knowledge_base_synthesis.md、04_architecture_synthesis.md  
> **產出日期**：2026-07-17

---

## 一、跨報告優先級矛盾

### Q1：P0 項目總量是否超出實際可執行範圍？四份報告的 P0 定義不一致如何仲裁？

**矛盾事實**：

| 報告 | P0 項目數 | 預估總工時 |
|------|-----------|-----------|
| 01（QA） | 7 項 | 未標註 |
| 02（效能） | 9 項 | 20-30h（宣稱 2-3 天） |
| 03（知識庫） | 5 項 | 極低（宣稱 1-3 天） |
| 04（架構） | 6 項 | 1-2 週 |

合併去重後仍有 **15+ 項 P0**，即使每項只需 2-3 小時，也需要 30-45 小時的 focused work。報告 02 宣稱「約 2-3 天工作量」明顯低估（9 項 P0 × 平均 3h = 27h 純開發，不含 review/testing）。

**同一項目在不同報告中優先級不同**：
- `screen_id 穩定化`：報告 01/03 標 P0，報告 04 放在 Phase 3（1-2 月）
- `Oracle Golden Dataset`：報告 01 標 P0，報告 03 放 P2
- `Circuit Breaker`：報告 03 標 P1，報告 01/02/04 標 P0
- `Structured Logging`：報告 02/04 標 P0，報告 01 未明確標級

**建議修訂**：
1. 建立統一的 P0 定義標準（例：「不修復則 nightly run 會靜默失敗或造成不可逆損害」）
2. 將 P0 精簡為 **5 項以內**真正的 Day-1 阻擋項，其餘降為 P1
3. 明確排序：P0 之間也需要 1st / 2nd / 3rd 的執行順序

---

### Q2：「立即可做」的工時估算是否經過實際驗證？是否低估了整合測試與邊界情況的成本？

**具體疑慮**：

- 報告 03 宣稱 `atomic_yaml_write` 只需「10 行」— 但這不含 Windows 平台的 `os.replace()` 原子性限制（跨磁碟不原子）、`filelock` 在 NFS 上的行為、以及既有測試的適配
- 報告 04 宣稱 `finish() exit code` 只需「2-5 行」— 但 verdict 的判定邏輯（哪些 anomaly 組合算 FAIL？UNSTABLE 的語義是什麼？）需要設計決策，不是純粹的程式碼量問題
- `aiobreaker` / `pyresilience` 引入後需要對整個 async 呼叫鏈做回歸驗證

**建議修訂**：所有工時估算加上 1.5-2× 安全係數，並標註「不含測試與整合驗證」。

---

## 二、邏輯缺口與未回答的前置問題

### Q3：Oracle 精確度量化（Golden Dataset）與 screen_id 穩定化之間的依賴關係為何？先做哪個？

**問題**：
- 報告 01 說「建立 Golden Dataset 量化 Vision OCR 精確度」是 P0
- 報告 03 說「screen_id pHash pre-filter」是 P0
- 但 Golden Dataset 的標註需要穩定的 screen_id 才能有意義地歸類（否則同一畫面的不同 ID 會混淆標註）
- 反過來，screen_id 穩定化效果的量化又需要 ground truth 來評估

這是一個**雞生蛋問題**。四份報告都沒有討論如何打破這個循環依賴。

**建議修訂**：明確建議「先用人工標註 30 張固定畫面建立 screen_id ground truth → 驗證 pHash 方案 → 再擴展為完整 Golden Dataset」的漸進路徑。

---

### Q4：報告大量建議引入新依賴（PaddleOCR、DINOv2、structlog、filelock、aiobreaker、python-statemachine、imagehash、Fast-SSIM），但未評估依賴膨脹的維護成本與供應鏈風險？

**具體疑慮**：

- PaddleOCR（85.6k stars）是大型套件（安裝約 1.5GB+），在 CI 環境啟動慢、GPU 依賴複雜
- DINOv2 推理需要 GPU 或大量 CPU 時間，與「近零成本確定性層」的哲學矛盾
- 報告 02 建議 `Fast-SSIM`（AVX2 加速）但未提及：該套件最後更新時間、Windows 相容性、ARM 平台（M-series Mac）支援
- 多個報告建議 `pyresilience` 但其 GitHub stars 極少（<100?），長期維護性存疑

**建議修訂**：
1. 每個建議的新依賴附加「維護活躍度 / 安裝大小 / 平台限制」評估
2. 區分「必須引入」vs「可用標準庫替代」（例：circuit breaker 可用 30 行自行實作 vs 引入套件）
3. 對 PaddleOCR 給出輕量替代方案（如 Tesseract、EasyOCR、或純 template matching）

---

### Q5：四份報告均未討論「現有功能的回歸保護」— 在大規模重構 perceiver/detector/oracle 之前，如何確保不破壞已有能力？

**問題**：

報告 01 承認目前只有 ~60 個測試，`detector.py` 零覆蓋。但所有 P0 建議都涉及修改核心模組：
- `perceiver.py`（screen_id 改 pHash、SSIM 改 Fast-SSIM、加 ROI 遮罩）
- `oracle.py`（bare except 修復、confidence 模型更換）
- `vision.py`（circuit breaker、cost cap、image preprocessing）
- `knowledge_base.py`（atomic write、filelock）

在測試覆蓋率極低的情況下同時修改 4 個核心模組，回歸風險極高。

**建議修訂**：
1. 在所有 P0 項目之前，插入一個 **P0-prerequisite**：「為待修改模組補充 characterization tests（記錄現有行為的快照測試）」
2. 明確要求每個 P0 修改必須附帶對應的測試案例
3. 建立「改動前 → 改動後」的 A/B 比對機制

---

## 三、現實可行性質疑

### Q6：報告 02 的「效能預算」（observe <20ms、單步無 Vision <150ms）是否基於實測數據？還是理想估算？

**疑慮**：

- 報告 02 承認 SSIM 目前在 1080p 耗時 ~580ms，但效能預算表列 `observe() < 20ms`
- 即使換用 Fast-SSIM（2.3ms），加上 pixel_diff（~5-15ms）+ screenshot 擷取（未計入），20ms 的總預算極其緊張
- `page.screenshot()` 本身在 Playwright 中通常需要 50-200ms（取決於畫面複雜度），但效能預算表完全未計入截圖時間
- 報告建議「截圖前插入雙重 rAF 同步」，這本身就增加 ~33ms（2 frames at 60fps）

**建議修訂**：
1. 明確區分「截圖間隔」與「後處理時間」— screenshot 擷取不應包含在 observe() 預算內
2. 提供基於目前程式碼的**實測數據**而非理論估算
3. 定義不同 tier 的效能預算（high-frequency monitoring vs periodic check）

---

### Q7：「分層感知策略」（L0 pixel → L1 OCR → L2 Vision）在實務上如何處理升級判斷的邊界情況？

**問題**：

四份報告一致推薦分層感知，但沒有一份討論：
- L1 OCR 信心不足時的**升級閾值**如何設定？過低則 Vision 呼叫量無節省，過高則漏偵測
- 升級判斷本身是否需要 Vision？（元循環問題）
- 當 L1 和 L2 結果不一致時，投票機制中「2/3 一致」的第三票從何而來？
- PaddleOCR 在遊戲藝術字型上的實際準確率為何？（報告引用的 benchmark 都是文件/自然場景 OCR，非遊戲字型）

**建議修訂**：
1. 要求在引入 PaddleOCR 前，先用目標遊戲的 10-20 張截圖做 PoC 測試
2. 明確定義升級閾值的初始值與校準方法
3. 「2/3 投票」改為「L1 + L2 一致即採信，不一致標 uncertain 交人工確認」

---

## 四、缺失的關鍵維度

### Q8：四份報告均未討論「人力與技能前提」— 誰來執行這些建議？團隊是否具備所需的 ML / 效能工程 / DevOps 能力？

**問題**：

建議中涉及的技術棧跨度極大：
- **ML/CV**：PaddleOCR 部署與 fine-tune、DINOv2 embedding、Beta-Bernoulli 統計模型
- **效能工程**：WebGL profiling、GPU timer query、VRAM estimation、AVX2 SIMD
- **基礎設施**：GitHub Actions CI/CD、GPU runner、Docker 容器化
- **可觀測性**：structlog、OpenTelemetry、告警系統

對一個 research preview 階段的專案，這些建議隱含假設有一個 5-8 人的全棧團隊。如果實際只有 1-2 人維護，需要完全不同的優先級排列。

**建議修訂**：
1. 根據「單人維護」與「小團隊（3-5 人）」兩種場景分別給出精簡路線圖
2. 標記哪些項目可以用「good enough」的簡化版替代（例：circuit breaker 用 try/except + counter 替代完整 library）
3. 區分「必須自行實作」vs「可外部化」（例：CI 可用 GitHub Actions 模板、OCR 可用 API 而非本地部署）

---

## 五、修訂建議總結

| # | 修訂項目 | 影響報告 | 優先級 |
|---|----------|----------|--------|
| A1 | 統一 P0 定義、精簡至 5 項、明確執行順序 | 全部 | 高 |
| A2 | 解決 screen_id ↔ Golden Dataset 循環依賴，給出漸進路徑 | 01, 03 | 高 |
| A3 | 補充「回歸保護前置條件」（characterization tests） | 01, 04 | 高 |
| A4 | 效能預算基於實測而非理論，計入截圖時間 | 02 | 中 |
| A5 | 新依賴評估表（維護度 / 大小 / 平台 / 替代方案） | 全部 | 中 |
| A6 | 分層感知升級閾值設計 + PoC 驗證要求 | 01, 03, 04 | 中 |
| A7 | 工時估算加安全係數 + 標註測試成本 | 全部 | 中 |
| A8 | 按團隊規模給出差異化路線圖 | 全部 | 高 |

---

## 六、整體評價

四份報告的**研究深度**令人印象深刻：參考文獻豐富、跨角色共識分析有價值、技術方案具體可行。

但作為 QA 審查，必須指出：**這些報告本身缺乏「測試思維」的自我審視**。它們建議了大量改善測試框架的方案，卻沒有回答：
1. 如何驗證這些改善本身是有效的？（meta-testing）
2. 改善的順序錯誤是否會引入新問題？（依賴鏈）
3. 在資源有限的現實下，哪些建議應該被**明確放棄**而非降級？（kill list）

建議在最終報告中增加一個「明確不做」清單，比無限降級的 P3 更誠實。

---

*本審查文件旨在確保最終報告的建議具有可執行性與內部一致性，而非否定各領域報告的技術價值。*
