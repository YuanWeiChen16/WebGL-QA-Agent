# Testing Reality Checker — 架構審查建議

**角色**：TestingRealityChecker（整合驗證 / 現實檢核）  
**審查對象**：DESIGN.md、ARCHITECTURE_DECISIONS.md  
**預設立場**：NEEDS WORK — 需壓倒性證據才能認定 production ready  
**日期**：2026-07-16

---

## 總體評定：NEEDS WORK

本框架在概念設計上具備原創性（黑箱 Vision + 宣告式 invariant），但在「能否證明自身有效」這個 QA 工具最基本的要求上，存在系統性缺口。一個無法量化自身準確率的測試工具，本身就是未經測試的。

---

## 建議 1：建立 Oracle Precision/Recall 量化基線

**問題**：AD-2 的功能正確性 oracle 完全依賴 Vision LLM 讀取遊戲畫面數值，但從未量化過這個 oracle 的 false positive / false negative 率。「二次確認」機制只是讓同一個模型讀兩次——相同的系統性偏差（如語義依賴、非語義文字辨識困難）不會因重複而消失。

**證據**：
- OCRBench 研究顯示，即使是 GPT-4V/Gemini 等頂級 VLM，在手寫文字上比 SOTA 監督式方法低 51.9%，在非語義文字（如亂序字母）上準確率下降平均 57%。遊戲 HUD 中的特殊字型、動態背景、藝術化數字正屬此類高難度場景。
  - 來源：https://arxiv.org/html/2305.07895
- 2025 年 Video OCR benchmark 顯示 Claude-3 在動態環境中 accuracy 僅約 65-70%，GPT-4o 約 76%，且所有 VLM 對遮擋/風格化文字仍有顯著困難。
  - 來源：https://www.emergentmind.com/papers/2502.06445
- OCR-Robust benchmark（2026）指出：higher clean accuracy 不保證 robustness，結構化視覺內容（圖表/表格）worst-case retention 僅 0.676，比文件類的 0.826 低 18%。
  - 來源：https://arxiv.org/html/2606.26041v1

**建議行動**：
1. 建立 ground-truth 標註集（50-100 張遊戲截圖，人工標註 score/currency/level 真值）
2. 跑 Vision 讀取 → 計算 WER/CER/Accuracy
3. 設定可接受門檻（如 WER < 5% 才可作為 oracle 輸入）
4. 在 `oracle.py` 加入 confidence score 回傳，低信心時標記為 uncertain 而非直接判定違規

---

## 建議 2：實作 Pass/Fail 判定與 CI 整合（AD-7 不能永遠是 roadmap）

**問題**：AD-7 明確承認：無確定性回歸層、無 exit code、run status 停在 "running"。DESIGN.md 將 CLI 列為步驟 9/10 但標「尚未實作」。如果一個 QA 框架無法告訴你測試通過還是失敗、無法 gate deployment，它與「偶爾呼叫 LLM 的截圖腳本」無本質區別。

**證據**：
- Microsoft Inspector（同為像素級黑箱測試）明確定義了 coverage metric 並以「是否發現 bug」作為效果衡量，而非僅產出報告。
  - 來源：https://ar5iv.labs.arxiv.org/html/2207.08379
- 學術研究（iv4XR on NetHack）雖然 agent 效果不佳（code coverage 14.2%），但至少定義了 mutation score (56.8%) 作為效果量化。沒有定義效果指標的測試工具無法被評估。
  - 來源：https://studenttheses.uu.nl/bitstream/handle/20.500.12932/48467/Corrected_version_Gerard_van_Schie.pdf
- TOGA（neural test oracle）的教訓：宣稱 FPR 25%，實際 precision 僅 0.38%，開發者需檢查 260 個失敗案例才能找到一個真 bug。不量化 precision 會導致工具無法使用。
  - 來源：http://arxiv.org/pdf/2305.17047v1

**建議行動**：
1. `GameSession.finish()` 必須回傳明確的 `verdict: pass | fail | inconclusive` + exit code
2. 定義 fail 條件：任何 confirmed anomaly（非 candidate）= fail；oracle violation confirmed = fail
3. 產出 JSON summary（anomaly count, invariant violations, verdict）供 CI 消費
4. 先實作最簡單的 nightly cron：跑一次 → 有無 crash-level anomaly → pass/fail → 通知

---

## 建議 3：修復知識累積的雙重失效（screen_id + confidence 只升不降）

**問題**：
- AD-5：screen_id 由 Vision 自由命名，SSIM 全圖統計對動態場景「無判別力」→ 同一畫面可能被拆成多個 alias，不同畫面可能被誤認為同一個。
- AD-6：confidence 只升不降，DESIGN.md 宣稱的「失敗則降低」完全未實作。

這代表知識圖：(a) 以不穩定標識為主鍵、(b) 永遠無法自我修正。N 個 session 後，flow graph 必然退化為 noise。

**證據**：
- Automated Game Testing with Online Search（2025, Shirzadehhajimahmood et al.）明確展示：on-the-fly model construction 的品質直接決定測試效果——model completeness 與 precision 是獨立研究問題，不能假設累積就正確。
  - 來源：https://doi.org/10.1002/stvr.70002
- 同研究中，沒有 model 輔助的 Search⁻ 在多個 level 因「路徑信念錯誤」而卡住（相信路暢通但實際被擋），證明錯誤的累積知識比沒有知識更危險。

**建議行動**：
1. **screen_id 穩定化**：遮罩動態區域後取 perceptual hash 作主鍵，Vision 命名降級為 display name
2. **confidence 雙向機制**：記錄 success/failure 次數，實作 `decay_confidence()` 於 transition 失敗時呼叫
3. **garbage collection**：連續 N 次 session 未被驗證的 edge 自動降為 `unverified`，避免過時知識堆積
4. **model precision metric**：每次 session 結束計算「走過的 transition 中，幾成符合預期」

---

## 建議 4：進行端對端效果驗證（用已知有 bug 的軟體測試測試工具）

**問題**：目前只有 16 個 `oracle.py` 的單元測試。零端對端證據表明此框架能在真實 WebGL 遊戲中發現真實 bug。README 的 WebGL Aquarium demo 只截一張圖點一下。一個未經 validation 的測試工具是「未測試的測試工具」。

**證據**：
- Microsoft Inspector 明確報告：在兩款 UE4 遊戲中發現 2 個「人類測試者未發現的」潛在 bug，並提供了重現證據。這是效果驗證的最低標準。
  - 來源：https://ar5iv.labs.arxiv.org/html/2207.08379
- GLIB（NetEase，遊戲 UI 測試 oracle）在 14 款真實遊戲中報告 53 個 bug、48 個被確認並修復，precision 100%、recall 99.5%。這才是「QA 工具有效」的證明。
  - 來源：https://dl.acm.org/doi/fullHtml/10.1145/3551349.3556913
- Canvas visual bug detection 研究在自訂遊戲中注入 24 個 bug，測量 detection accuracy（100% vs baseline 44.6%），並明確報告 false positive rate 為 0。
  - 來源：https://dl.acm.org/doi/fullHtml/10.1145/3551349.3556913

**建議行動**：
1. 建立 seeded-fault 驗證：在測試用 WebGL 遊戲中刻意植入 5-10 個已知 bug（分數不扣、畫面凍結、按鈕失效）
2. 跑框架 → 記錄：發現幾個？漏掉幾個？誤報幾個？
3. 計算 precision = TP/(TP+FP)、recall = TP/(TP+FN)
4. 這是任何 QA 工具上線前的最低要求，不是 nice-to-have

---

## 建議 5：補齊 Click-Before Grounding 或量化 miss rate

**問題**：AD-4 承認 click-before grounding 是「待處理」。Post-click assertion（pixel_diff）能告訴你「沒變化」但不能告訴你為什麼——目標不存在？座標錯誤？元素不可互動？沒有 pre-click 驗證，agent 可能大量點擊空氣而不自知。

**證據**：
- Inspector 的做法是先用 few-shot object detector 確認目標存在再互動（7/9 cases 正確偵測），而非盲目點座標。
  - 來源：https://ar5iv.labs.arxiv.org/html/2207.08379
- Automated Game Testing（2025）中 agent 因「相信目標在某處但實際不在」而卡住的案例，正是缺乏 pre-action grounding 的後果。
  - 來源：https://doi.org/10.1002/stvr.70002

**建議行動**：
1. **短期**：在 `execute_action` 前加入 pixel sampling——目標座標周圍 NxN patch 的 histogram 是否符合「有 UI 元素」的 heuristic（非空白/非純背景）
2. **中期**：用 template matching 或小型 detector 確認座標區域確實有可點擊元素
3. **量化 miss rate**：統計過去 session 中 `consecutive_noop` / total_actions 的比率，作為 grounding 品質的 proxy metric
4. **長期**：如 AD-4 所述，OmniParser 式的 element detection → Vision 選 element_id 而非吐裸座標

---

## 總結

| 項目 | 嚴重度 | 狀態 |
|------|--------|------|
| Oracle precision 未量化 | Critical | 無數據 |
| 無 pass/fail 判定 | Critical | 未實作 |
| 知識累積基礎不穩 | High | 部分承認 |
| 零端對端效果驗證 | Critical | 無數據 |
| Click grounding 缺失 | Medium | 已知待處理 |

**結論**：概念設計合理，但三個 Critical 缺口（oracle 準確率未知、無法判定 pass/fail、未證明能抓 bug）使得此框架目前無法被稱為「QA 工具」——它更接近「一個有潛力但未驗證的探索性原型」。建議優先處理建議 4（seeded-fault 驗證）→ 建議 1（oracle 量化）→ 建議 2（pass/fail），這三項完成後才有資格討論 production readiness。
