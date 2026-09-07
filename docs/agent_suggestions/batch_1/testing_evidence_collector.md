# Evidence Collector 審查建議

> 角色：EvidenceQA — 截圖不會說謊、沒有證據等於幻想的懷疑論 QA 專家
> 日期：2026-07-16
> 對象：WebGL QA Agent 架構與設計

---

## 建議 1：建立 Vision OCR 精確度基線（Precision/Recall 量化）

**問題**：oracle.py 的 ground truth 完全依賴 Vision LLM 讀取畫面數值，但目前**零驗證數據**證明讀數精確度。根據 OCRBench v2 的評測，即使最強的閉源 LMM 在 text recognition 任務上也僅達約 76% 準確率（GPT-4o），且在「需要精確空間理解的任務」上表現顯著下降。

**證據**：
- OCRBench v2 顯示多數 LMM 總分低於 50/100，且在 fine-grained perception 與 text spotting 能力上嚴重不足
- video-db/ocr-benchmark 在動態影片環境中測試，Claude-3.5 Sonnet CER 為 0.3229、WER 為 0.4663（即約 1/3 字元會讀錯）
- 遊戲畫面的藝術字型、動態背景、粒子特效會比標準文字場景更難辨識

**具體建議**：
1. 建立「golden dataset」——手動標註 50-100 張遊戲截圖的真實數值（score/currency/level）
2. 跑 Vision 讀取 → 對比人工標註 → 計算 CER、field-level accuracy、false positive rate
3. 設定門檻：若 field accuracy < 95%，oracle 結論必須標記 confidence level
4. 長期方向：本地 OCR（如 PaddleOCR）交叉驗證數字欄位

**來源**：
- https://arxiv.org/html/2501.00321v2 （OCRBench v2：LMM OCR 能力全面評測）
- https://github.com/video-db/ocr-benchmark （動態影片環境 VLM OCR 基準測試）

---

## 建議 2：pixel_diff 動態場景可區分性驗證 — 採用 ROI 遮罩分離動態區

**問題**：execute_action 的點擊後斷言用 pixel_diff_ratio 判斷動作是否生效。但在持續動態的遊戲畫面（魚群游動、粒子效果），pixel_diff **永遠非零**，「有效點擊」與「無效點擊」的分佈可能完全重疊，使斷言形同虛設。qa-defender 承認目前靠「連續 3 次低變化才判 noop」但**無實際分佈數據**。

**證據**：
- Applitools 的 Regions Only 方法論明確指出：「當 90% 頁面持續變化時，全頁視覺斷言會過於寬泛」，必須用 targeted region 隔離有意義的變化
- ASE 2022 論文（Alberta 大學）證明傳統 snapshot testing 對遊戲動態場景準確率僅 44.6%，而用 isolated object comparison 達 100%
- StageMask / Playwright 的 mask 機制都是為了解決「動態內容導致 false positive」的業界標準做法

**具體建議**：
1. 收集 100 次「有效點擊」和 100 次「無效點擊」的 pixel_diff 值，畫分佈圖確認是否可分離
2. 引入 **ROI 遮罩**：將動態區（魚群區域）與 UI 靜態區（分數、按鈕）分開計算 diff
3. 對 UI 靜態區做嚴格 diff（threshold 低）、動態區僅監測結構性變化（SSIM 或忽略）
4. 參考 Applitools 的 Hybrid Validation：同一步驟內對不同區域套用不同敏感度

**來源**：
- https://applitools.com/blog/mastering-targeted-ui-validation-with-regions-only/ （Regions Only 精準視覺驗證）
- https://asgaard.ece.ualberta.ca/papers/Conference/ASE_2022_Macklon_Automatically_Detecting_Visual_Bugs_In_HTML5_Canvas_Games.pdf （Canvas 遊戲視覺 bug 自動偵測，snapshot testing 僅 44.6% vs. isolated object 100%）
- https://wopee.io/blog/screenshot-comparison-algorithms-visual-testing/ （SSIM/pixelmatch/pHash 完整比較與適用場景）

---

## 建議 3：screen_id 辨識改用 perceptual hash + UI 錨點，而非全圖 SSIM

**問題**：AD-5 承認全圖 SSIM 對動態畫面無判別力，但目前仍是唯一的 screen matching 機制。qa-defender 確認「同一 gameplay screen 因魚群位置不同被判為不同 screen」的問題確實存在，但**無頻率數據**。

**證據**：
- Wopee.io 的算法比較指出：SSIM window size 是需要 per-content-type tuning 的超參數，且「subtle localized changes inside a window 可能被平均掉而漏掉」
- VideoGameBench 使用 perceptual image hashing（pHash）做遊戲畫面 checkpoint 匹配，Hamming distance < 12 為匹配閾值，在遊戲場景下比 SSIM 更實用
- UIHASH（USENIX Security 2024）將 UI 分割為 grid，用 CNN-based Siamese network 計算相似度，達到 F1 0.984，遠超純圖像比對的 0.823
- ideamans/page-regression-tester 使用 ignore-regions 排除動態內容後再做 SSIM

**具體建議**：
1. 實作 AD-5 提案的 canonical screen registry：遮罩動態區後計算 perceptual hash
2. 定義 UI 錨點指紋（固定位置的 UI 元素如分數欄、按鈕列）作為 screen identity 的主鍵
3. SSIM 改為僅在 UI 靜態區計算，或改用降採樣後的 pHash 做快速預篩
4. 記錄實際的 screen misidentification rate 作為改進基線

**來源**：
- https://arxiv.org/html/2505.18134 （VideoGameBench：用 perceptual hash 做遊戲進度 checkpoint 匹配）
- https://www.usenix.org/system/files/usenixsecurity24_slides-li-jiawei.pdf （UIHASH：grid-based UI 相似度，F1=0.984）
- https://wopee.io/blog/screenshot-comparison-algorithms-visual-testing/ （pHash 作為預篩器，SSIM 的侷限性）

---

## 建議 4：為 reread 機制補充「系統性誤讀」防護與量化過濾率

**問題**：AD-2 的二次確認假設「OCR 誤讀是隨機的，第二次不會重複」。但 Vision LLM 的誤讀往往是**系統性的**（特定字型/背景/光效下一致性誤讀），此時 reread 兩次都會犯同樣錯，形同虛設。qa-defender 承認**無實測過濾率數據**。

**證據**：
- OCRBench v2 發現 LMM 在 fine-grained perception 上系統性不足，不是隨機錯誤
- V-MAGE 論文指出 VLM 存在 anchoring bias：「處理相似連續幀時，先前推論對當前推理產生不當影響」——第二次讀同一畫面可能因 anchoring 而重複同樣錯誤
- video-db benchmark 顯示 Claude 的 WER 為 46.63%，這不是偶爾誤讀而是系統性能力不足

**具體建議**：
1. 量化 reread 實際過濾率：記錄所有觸發 reread 的案例，統計「第二次翻轉為 pass」的比率
2. 引入**異源交叉驗證**：對關鍵數字欄位同時用本地 OCR（Tesseract/PaddleOCR）讀取，兩個系統一致才確認
3. 建立「已知系統性誤讀」資料庫：記錄特定遊戲中 Vision 反覆讀錯的數字/字型組合
4. 對 min_occurrences 參數做 calibration：不同遊戲/欄位的最佳值應由歷史 false positive 率決定

**來源**：
- https://arxiv.org/html/2501.00321v2 （OCRBench v2：LMM 系統性能力不足的五類限制）
- https://aclanthology.org/2026.findings-acl.878.pdf （V-MAGE：VLM 的 anchoring bias 導致重複錯誤）
- https://github.com/video-db/ocr-benchmark （Claude OCR WER 46.63%——非隨機誤差）

---

## 建議 5：定義明確的 session pass/fail verdict 與 false alarm 追蹤機制

**問題**：目前 QA session 無 pass/fail 判定標準、無 exit code、無歷史統計。qa-defender 承認「目前全靠人工看報告判斷」，這使得自動化 QA 的核心價值（無人值守回歸測試）無法實現。

**證據**：
- Eidos-Montréal 的 Automated Game Testing 框架明確將測試分為 Initialize → Execute → Validate 三階段，每個 action validation 都有明確的 pass/fail 判定，且「any action validation yields unexpected results or times out → test fails」
- Wuji（NetEase）定義了四類 oracle（Crash / Stuck / Logical / Balance），每類有明確的自動判定條件與閾值，且承認「false alarms 是潛在威脅」故記錄完整 replay 資訊供人工確認
- iv4XR 框架的 programmed playtests 使用 differential invariants（「score 不應遞減」）作為持續斷言，任何違反即標記 fail
- 業界共識：自動化測試的價值來自「明確的 pass/fail + 低 false positive 率」，否則人工成本不會真正降低

**具體建議**：
1. 定義三級 verdict：`PASS`（無 anomaly + oracle 全 pass）/ `WARN`（有 candidate 但未確認）/ `FAIL`（confirmed bug）
2. 實作 exit code：0=PASS, 1=FAIL, 2=WARN, 非零觸發通知
3. 建立 false alarm 追蹤：每個報告的 bug 需人工確認 true/false，累積計算 oracle precision
4. 設定目標：oracle precision > 80% 才算可用；低於此值代表 reread/threshold 需要校準
5. 每月產出 metrics dashboard：total sessions / bugs found / confirmed bugs / false alarm rate

**來源**：
- https://www.eidosmontreal.com/news/automated-game-testing/ （Eidos-Montréal AGT：Initialize-Execute-Validate + action validation pass/fail）
- https://nos.netease.com/mg-file/mg/neteasegamecampus/art_works/20200812/202008122020238586.pdf （Wuji：四類 oracle + false alarm 處理 + replay 記錄）
- https://dl.acm.org/doi/10.1145/3742473 （iv4XR Smart Playtesting：differential invariants + programmed playtests 100% bug detection rate）

---

## 總結

以上五項建議的共同主題：**目前系統缺乏「衡量自身可靠性」的機制**。Vision 讀數沒有精確度數據、pixel_diff 沒有可區分性證據、SSIM 沒有失敗率統計、reread 沒有過濾率、session 沒有 pass/fail。一個「證據驅動」的 QA 系統，首先需要對自身感測器的可靠性有證據。建議優先順序：

1. **P0**：建議 5（pass/fail verdict）— 沒有這個，其他改進無法衡量效果
2. **P0**：建議 1（Vision 精確度基線）— oracle 的可信度是整個系統的基礎
3. **P1**：建議 2（pixel_diff ROI 遮罩）— 動態遊戲場景下的核心可用性問題
4. **P1**：建議 3（screen_id perceptual hash）— 知識累積的前提
5. **P2**：建議 4（reread 系統性誤讀防護）— 在建議 1 的數據出來後再決定方向
