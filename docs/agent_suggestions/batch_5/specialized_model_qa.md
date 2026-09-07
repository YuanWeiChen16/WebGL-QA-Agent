# Batch 5 — Model QA Specialist 建議

> 審查角色：Model QA Specialist（獨立模型審計專家）
> 審查日期：2026-07-16
> 焦點：感測器校準、統計可靠性、下游決策級聯失效

---

## 建議 1：為 Vision OCR 感測器建立精度基線（Precision Baseline）

### 問題

Oracle (AD-2) 的 ground truth 全來自 Vision LLM 讀畫面數值，但目前**沒有對 Vision 模型本身做過 precision/recall 量測**。「二次確認」防線的有效性建立在「兩次 OCR 都錯的機率很低」的假設上，但若遊戲 UI 使用低對比度、描邊字型、動態背景或非 ASCII 字元，這個假設可能不成立。

### 建議做法

1. **建立 ground-truth 標註集**：從已收集的截圖中標註 50-100 張含數值的畫面（score、currency、level），作為 calibration dataset。
2. **量測 per-field accuracy**：對每個數值欄位分別計算 Vision 的 precision/recall，找出系統性弱點（如小數點、逗號分隔符、動態背景上的白字）。
3. **導入 local OCR 交叉驗證**：用 EasyOCR / Tesseract 對同一截圖做 ensemble 讀數，兩個獨立 OCR source 同時錯的機率遠低於單一 Vision model。

### 參考

- **StructuredVision** — 專門用於遊戲介面的 OCR 結構化抽取工具，支援 Gemini + Tesseract + EasyOCR 多引擎對比驗證：
  https://github.com/ammahmoudi/StructuredVision
- **Lost-in-the-Interface benchmark** — 首個評估 LVLM 在複雜遊戲 UI 上表現的 benchmark（2048、Sudoku、Governor of Poker、Mahjong Soul），量測不同 UI 複雜度下的辨識正確率：
  https://github.com/XiangLiSky/Lost-in-the-interface
- **GGBench / Game-R1** — 大規模跨類型遊戲 grounding benchmark，含 OCR 能力評測（OCRBench 828-884 分），證明遊戲 UI OCR 仍有 10-15% 誤差空間：
  https://ojs.aaai.org/index.php/AAAI/article/download/37800/41762

### 預期效果

- 量化「二次確認」防線的真實有效性（目前是信念，不是數據）
- 找出需要特殊處理的 UI 區域（如動態背景上的數字需要 crop + 預處理）
- 為 oracle precision 追蹤（AD-2 後續）提供 baseline

---

## 建議 2：以 Beta-Bernoulli 後驗取代三級制 Confidence（AD-6）

### 問題

目前 transition confidence 只有 low/medium/high 三級單向遞增。「嘗試 100 次成功 95 次」和「嘗試 3 次成功 3 次」都是 "high"——前者有統計意義，後者只是樣本不足的假象。當知識圖超過 20+ screens 時，這會導致：
- 偽穩定路徑（低樣本被誤判為可靠）
- 真不穩定路徑無法被降級（只升不降）
- 探索策略無法區分「確定可走」與「還需要更多驗證」

### 建議做法

1. **每條 transition 維護 `(α, β)` 參數**：`α = 成功次數 + 1`、`β = 失敗次數 + 1`（Beta(1,1) 為均勻先驗）。
2. **confidence 由後驗下界決定**：用 95% credible interval 的下界 `Beta.ppf(0.05, α, β)` 作為 conservative trust score。
3. **加入時間衰減**：長期未驗證的 transition 應向先驗回歸（exponential decay on α, β toward prior）。
4. **決策整合**：routing 時用 Thompson sampling 從 Beta 後驗取樣，自然平衡 exploration vs. exploitation。

### 參考

- **BayesTruth** — 精確 Beta-Bernoulli 後驗的信任評分庫，含 credible interval、Thompson sampling routing、時間衰減、校準驗證：
  https://github.com/davccavalcante/bayestruth
- **Bayesian LangGraph (OpenReview)** — 將 Beta-Bernoulli 可靠性模型整合進 agent graph routing 的學術論文，提供完整的更新規則與收斂證明：
  https://openreview.net/pdf/fa95c2e33e65c349751de2ff9183cb917cc3fba3.pdf
- **Bayesian-Agent (DataArcTech)** — 用 Beta-Bernoulli 後驗管理 agent Skill 可靠性的實作，含 explore/retire/patch 策略閾值：
  https://github.com/DataArcTech/Bayesian-Agent
- **Safe Bayesian Exploration (AAAI 2024)** — Dirichlet-Categorical 後驗用於 MDP transition 不確定性建模，含安全邊界的信心量化：
  https://ojs.aaai.org/index.php/AAAI/article/download/30137/32013

### 預期效果

- Confidence 有統計意義：3 次全成功 ≠ 100 次 95% 成功
- 失敗自然降低後驗（不需額外邏輯）
- Thompson sampling 自動驅動探索不確定的路徑

---

## 建議 3：Per-Game 異常偵測閾值自動校準

### 問題

`detector.py` 的凍結（SSIM）、黑白屏（dominant color ratio）、記憶體成長閾值定在 `config/default.yaml`，對所有遊戲用同一組。但：
- **靜態棋牌遊戲**：正常 SSIM 極高（~0.99），freeze threshold 需要非常緊（如 0.999）
- **高動態射擊/捕魚遊戲**：正常 SSIM 可能只有 0.7-0.85，用預設 threshold 會 false positive 爆量
- 不同遊戲的「正常記憶體成長」差異也極大

### 建議做法

1. **Calibration Phase**：每個遊戲首次探索的前 N 步（如 30 步）作為 baseline 採集，計算各指標的分佈統計（mean, std, percentiles）。
2. **Dynamic Threshold**：freeze threshold = `baseline_ssim_mean - k * baseline_ssim_std`（k=3 對應 99.7% 正常範圍外）。
3. **Memory Bank Anomaly Scoring**：參考 PatchCore/SPADE 做法，建立正常狀態的 feature memory bank，新觀測離最近鄰的距離超過閾值即為異常。
4. **Persist per-game calibration**：存入 `knowledge/<game>/calibration.yaml`，後續 session 直接載入。

### 參考

- **Gameplay-Anomaly-Detection-Agent** — 用 ResNet50 embeddings + KNN Memory Bank 做遊戲影片異常偵測，以 clean gameplay 校準後自動偵測 bug：
  https://github.com/attarmau/Gameplay-Anomaly-Detection-Agent
- **State-aware hierarchical visual anomaly detection (Engineering Applications of AI, 2025)** — 整合 game state 資訊的自適應異常偵測框架，含 synthetic data generation 與 per-game 校準：
  https://doi.org/10.1016/j.engappai.2025.113497
- **RESP: Reference-guided Sequential Prompting** — 用同一影片中的 reference frame 作為 baseline 來判斷當前幀是否異常（glitch detection），解決跨遊戲閾值差異問題：
  https://arxiv.org/html/2604.11082v1

### 預期效果

- 消除「一組閾值適用所有遊戲」的 false positive/negative 問題
- 校準數據可重用，不需每次重新計算
- 對新遊戲自動適應，無需人工調參

---

## 建議 4：screen_id 穩定化——Canonical Registry + Perceptual Hash

### 問題

screen_id 由 Vision 自由命名、全圖 SSIM 做比對。高動態場景下同一邏輯畫面被分裂為多個 screen_id，造成：
- Transition 邊碎片化（本應是一條邊 split 成 N 條弱邊）
- Confidence 永遠達不到 high（每個別名只見過幾次）
- Strategy 無法匹配（知識庫裡的 strategy 掛在某個別名上，其他別名找不到）

這是一個**級聯失效模式**：screen_id 不穩 → confidence 失效 → strategy 失效 → 探索效率崩潰。

### 建議做法

1. **UI 錨點指紋**：對截圖的固定 UI 區域（頂部 status bar、底部 toolbar）做 perceptual hash（dHash/pHash），忽略動態內容區域。
2. **Canonical Screen Registry**：每個邏輯畫面有一個 canonical_id，由 UI 指紋 + 佈局特徵決定。Vision 命名只作 display_name。
3. **合併機制**：當兩個 screen_id 的 UI 指紋相似度超過閾值，自動 merge 為同一個 canonical screen，合併其 transitions 和 confidence。
4. **動態區域遮罩**：在 SSIM 比對前，遮罩已知的動態區域（如魚群游動區），只比對 UI 骨架。

### 參考

- **RESP (Reference-guided Sequential Prompting)** — 在同一影片中自動選擇 reference frame 作為 baseline，用 within-video comparison 取代 isolated classification，解決動態場景的判斷問題：
  https://arxiv.org/html/2604.11082v1
- **AutoGameUI** — 遊戲 UI 的多模態對應匹配，透過 hierarchy + geometry + semantics 建立 UI element 的 canonical mapping（F1=88.1%），可借鑑其「佈局指紋」概念：
  https://arxiv.org/pdf/2411.03709
- **GGBench** — 跨類型遊戲 grounding benchmark，驗證基於 bounding box + IoU 的 UI element 定位方法在不同遊戲類型的泛化性：
  https://ojs.aaai.org/index.php/AAAI/article/download/37800/41762

### 預期效果

- 同一邏輯畫面不再被 split 為多個 ID
- Confidence 累積正確反映真實嘗試次數
- Strategy / knowledge 跨 session 穩定可用

---

## 建議 5：點擊後斷言需要語意層 Effect Signal（AD-4 補強）

### 問題

`execute_action` 用 `pixel_diff_ratio` 判斷動作「有沒有效果」。但這個指標有兩個盲點：
- **高動態場景 false negative**：魚群持續游動 → pixel_diff 永遠 > 0 → 即使點擊無效（魚沒死、分數沒變）也被判定為「有效果」→ 不會觸發 `no_effect_loop` blocking
- **靜態場景 false positive**：hover effect 極微 → pixel_diff ≈ 0 → 有效操作被誤判為無效

本質問題是：pixel_diff 量測的是「畫面有沒有變化」，不是「操作有沒有達到預期效果」。

### 建議做法

1. **雙訊號架構**：pixel_diff（感知層）+ game_state diff（語意層）必須同時考慮。
2. **Lightweight game_state diff**：動作前後各讀一次 game_state（score、currency 等），若關鍵欄位無變化，即使 pixel_diff > 0 也視為「語意無效」。
3. **Action-outcome typing**：在 knowledge 中為每種 action 定義 expected_effect（如 "click fish → score should increase"），post-action assertion 按此驗證。
4. **Fallback to Vision only when needed**：pixel_diff=0（靜態無變化）時再呼叫 Vision 做語意確認，避免每步都 call Vision 的成本。

### 參考

- **DRL for Automated Game Testing (Bergdahl et al. 2021)** — 用 RL agent 偵測遊戲 exploit 和 stuck 狀態，透過 reward signal（非像素）判斷操作是否有效，證明語意訊號優於純視覺判斷：
  https://arxiv.org/pdf/2103.15819
- **Autonomous Game Balance Testing (Politowski et al. 2023)** — 用 autonomous agent 的 score-based metrics 作為 action effectiveness proxy，而非像素變化：
  https://doi.org/10.48550/arxiv.2304.08699
- **BayesTruth — observe/wrap pattern** — 提供 action → binary outcome observation 的標準化介面，可用於包裝 game_state diff 作為 success indicator：
  https://github.com/davccavalcante/bayestruth

### 預期效果

- 高動態場景中的無效操作不再被 pixel_diff 掩蓋
- `no_effect_loop` 偵測在所有場景類型中都可靠
- 與 oracle (AD-2) 形成閉環：oracle 判定 invariant violation → action was ineffective or harmful

---

## 總結優先級

| # | 建議 | 嚴重度 | 理由 |
|---|------|--------|------|
| 4 | screen_id 穩定化 | **High** | 級聯失效影響整個知識圖 |
| 2 | Beta-Bernoulli confidence | **High** | 決策基礎無統計意義 |
| 5 | 語意層 effect signal | **Medium** | pixel_diff 在高動態場景盲目 |
| 3 | Per-game 閾值自動校準 | **Medium** | 一組閾值無法適用所有遊戲 |
| 1 | Vision OCR 精度基線 | **Medium** | oracle 可靠性無量化證據 |

> 建議 4 和 2 為 **High** 是因為它們構成系統性 failure mode：screen_id 不穩讓 confidence 無法累積、confidence 無統計基礎讓 routing 不可靠——兩者疊加使整個探索-學習-驗證迴圈在中等規模遊戲上不可信賴。
