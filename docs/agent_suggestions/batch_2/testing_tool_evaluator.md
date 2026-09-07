# Testing Tool Evaluator — 工具選擇建議

**審查角色**: Tool Evaluator（技術評估與策略工具選型專家）
**審查日期**: 2026-07-16
**對應架構決策**: AD-1, AD-2, AD-4, AD-5, AD-7, AD-9

---

## 建議 1: 引入 canvas-grid 或模板比對 locator 層，補強 Playwright 對 WebGL canvas 的定位能力

**現況問題**:
Playwright 官方已明確表示「locateOnScreen 功能超出 Playwright 範疇」（Issue #27729 已關閉為 out of scope）。目前專案以硬編碼絕對座標點擊 canvas，AD-4 也承認「點擊前 grounding」尚未實作。Playwright 對 canvas 內容的 trace 支援直到 v1.50 才加入螢幕截圖 toggle，WebGL readback 仍然昂貴且不穩定。

**具體建議**:
1. 評估 `canvas-grid`（https://dev.to/fonzi/testing-html5-canvas-with-canvasgrid-and-playwright-5h4c）作為 runtime grid overlay 方案，提供基於區域的點擊/拖曳/色彩取樣，無需逆向 canvas 內部。
2. 對於需要精確元素定位的場景，參考 Playwright 社群的 SwiftShader 軟體渲染 + screenshot assertion 模式（https://barthpaleologue.github.io/Blog/posts/webgl-webgpu-playwright-setup/），以 `--use-gl=swiftshader` 確保跨環境一致性。
3. 長期：評估 OpenCV `matchTemplate` 做子圖搜尋，取代裸座標。

**ROI 分析**:
- canvas-grid 為零成本開源方案，整合工時約 2-4 小時
- 可直接解決 AD-4(1)「點擊前 grounding」的部分需求
- 降低因解析度/視窗大小變動導致的點擊失敗率

**參考來源**:
- https://github.com/microsoft/playwright/issues/27729 （Playwright 官方拒絕 locateOnScreen）
- https://dev.to/fonzi/testing-html5-canvas-with-canvasgrid-and-playwright-5h4c （canvas-grid 方案）
- https://barthpaleologue.github.io/Blog/posts/webgl-webgpu-playwright-setup/ （WebGL + Playwright E2E 設定含 SwiftShader + Docker CI）

---

## 建議 2: 採用 perceptual hashing（pHash/dHash）+ 局部 ROI 取代全圖 SSIM，解決 screen_id 穩定化瓶頸

**現況問題**:
AD-5 明確指出 SSIM 對動態畫面（如魚群游動）無判別力，導致 screen_id 主鍵不穩定、confidence 累積失效。SSIM 是全圖統計量，對局部 UI 變化不敏感，對全局動態過度敏感。

**具體建議**:
1. 引入 `imagehash` 套件（Python，支援 pHash/dHash/wHash），對 UI 錨點區域（固定 HUD、按鈕列）計算 perceptual hash 作為 screen fingerprint。動態區域（魚群/粒子）以遮罩排除。
2. 組合策略：`screen_id = hash(UI_region_phash) + structural_anchor_positions`，而非單一全圖 SSIM 閾值。
3. 保留 SSIM 作為「畫面是否有任何變化」的 L0 快速篩選，但 screen_id 判定改用 hash 指紋。

**ROI 分析**:
- `imagehash` 為輕量純 Python 套件，無 GPU 依賴
- 直接解決 AD-5 的根本問題，為 confidence 升降（AD-6）建立穩定基礎
- 降低 Vision LLM 被呼叫來確認「這是哪個畫面」的頻率（節省成本）

**參考來源**:
- https://github.com/JohannesBuchner/imagehash （imagehash 套件，支援 pHash/dHash/wHash，3.5k+ stars）
- https://content-blockchain.org/research/testing-different-image-hash-functions/ （各 hash 演算法比較）
- https://pypi.org/project/ImageHash/ （PyPI 頁面，MIT 授權）

---

## 建議 3: 引入 PaddleOCR 作為 L1 本地數值讀取層，降低 Vision LLM 成本 80%+

**現況問題**:
AD-2 與 AD-9 承認完全依賴雲端 Vision LLM 讀取遊戲數值（分數/金幣/等級），每次呼叫約 $0.01-0.03，一個探索 session 可能呼叫數百次。DESIGN.md 提到「長期可用本地 OCR 交叉驗證」但未實作。

**具體建議**:
1. 整合 **PaddleOCR**（85.6k GitHub stars，Apache-2.0，支援 100+ 語言含中文數字）作為 L1 數值讀取。針對已知 HUD 區域（分數/金幣座標從 knowledge YAML 讀取）做局部裁切 → OCR。
2. 分層策略：
   - L0: pixel_diff 偵測變化（已有）
   - **L1: PaddleOCR 讀取已知區域數字**（新增，<50ms，零成本）
   - L2: Vision LLM（僅未知畫面/L1 低信心/斷言失敗時升級）
3. 替代方案：EasyOCR（較輕量但精度略低）或 Tesseract（經典但對遊戲字體表現差）。PaddleOCR PP-OCRv6 在數位顯示器/點陣字體場景有專門優化，最適合遊戲 HUD。

**ROI 分析**:
- PaddleOCR 推理 <50ms/frame（CPU），零 API 成本
- 假設每 session 500 步中 80% 的數值讀取可由 L1 處理，每 session 省 $4-12
- 同時提供 Vision LLM 的交叉驗證來源（AD-2 待補項目）

**參考來源**:
- https://github.com/PaddlePaddle/PaddleOCR （官方 repo，85.6k stars，PP-OCRv6 2026.06 發布）
- https://paddleocr.com （官方網站，含線上 demo）
- https://arxiv.org/abs/2507.05595 （PaddleOCR 3.0 技術報告）

---

## 建議 4: 整合 Allure Report 取代自建 reporter.py，獲得截圖附件、趨勢圖、CI 整合能力

**現況問題**:
AD-7 承認目前無 pass/fail verdict、無 exit code、無法掛 CI。自建的 `reporter.py` 產出 HTML timeline，但缺乏：趨勢分析（跨 run 比較）、失敗分類、CI pipeline 整合、截圖自動附件管理。

**具體建議**:
1. 整合 **Allure Report**（`allure-pytest` 或 `allure-playwright`），將每個 anomaly/invariant violation 映射為 Allure test case，截圖作為 attachment。
2. 利用 Allure 內建功能：
   - **Categories**: 將 crash/freeze/invariant_violation/no_effect_loop 分類為不同 defect category
   - **History & Retries**: 跨 session 追蹤同一 bug 的重現率
   - **Timeline view**: 已內建，取代自建 timeline
   - **Environment info**: 記錄 game_url, resolution, session_duration
3. 保留 `session.json` 作為可重播的原始資料，Allure 負責人類可讀報告。
4. CI 整合：Allure 原生支援 GitHub Actions artifact upload + 趨勢圖。

**ROI 分析**:
- Allure 為免費開源（Apache-2.0），`allure-pytest` 套件成熟穩定
- 省去自建趨勢分析/CI 整合的工時（估計 20-40 小時）
- 直接解決 AD-7 的 pass/fail verdict 需求（Allure 的 Quality Gate 功能）

**參考來源**:
- https://allurereport.org/docs/playwright/ （Allure + Playwright 整合指南）
- https://allurereport.org/docs/pytest/ （Allure + pytest 整合）
- https://github.com/allure-framework/allure2 （Allure 2 主 repo，支援 30+ 框架）

---

## 建議 5: 引入 action-sequence fuzzer 與 Hypothesis 做系統性邊界測試

**現況問題**:
目前測試策略依賴 scripted sequence（人工定義）+ Vision 驅動探索（隨機性有限）。DESIGN.md 提到「異常操作（亂按、快速切換、邊界值）」但缺乏系統性 fuzzing 工具。AD-4(2) 的 `no_effect_loop` 偵測是被動的，不是主動探索邊界。

**具體建議**:
1. 建立 **action-sequence fuzzer** 模組：
   - 定義 action alphabet: `{click(x,y), drag(x1,y1,x2,y2), keypress(key), wait(ms), rapid_click(x,y,n)}`
   - 以 property-based 方式生成隨機序列，約束條件從 knowledge YAML 的 screen elements 推導
   - 每序列後跑 detector（crash/freeze/black_screen）+ oracle（invariant check）
2. 整合 **Hypothesis**（Python property-based testing 框架）的 stateful testing 模式（`RuleBasedStateMachine`），將 game state 建模為狀態機，讓 Hypothesis 自動探索轉換路徑。
3. 優先實作「壓力模式」：對當前畫面的所有已知元素做 rapid interaction（50ms 間隔 × 20 次），重現 BUG-001 類型的 context lost 問題。

**ROI 分析**:
- Hypothesis 為 Python 生態標準 property-based testing 工具，零成本
- 可系統性發現 DESIGN.md 提到但未自動化的邊界 bug 類別
- `RuleBasedStateMachine` 與現有 flow_graph 自然對應

**參考來源**:
- https://hypothesis.readthedocs.io/en/latest/stateful.html （Hypothesis stateful testing 文件）
- https://hypothesis.readthedocs.io/en/latest/ （Hypothesis 官方文件）
- https://github.com/HypothesisWorks/hypothesis （Hypothesis repo，7k+ stars）

---

## 總結優先順序

| 優先級 | 建議 | 解決的 AD | 預估工時 | 成本節省 |
|--------|------|-----------|----------|----------|
| P1 | PaddleOCR L1 數值讀取 | AD-2, AD-9 | 8-12h | $4-12/session |
| P1 | pHash screen fingerprint | AD-5, AD-6 | 6-8h | 減少 Vision 呼叫 |
| P2 | Allure Report 整合 | AD-7 | 12-16h | 省 20-40h 自建 |
| P2 | canvas-grid / template matching | AD-4(1) | 4-8h | 降低座標脆弱性 |
| P3 | Action-sequence fuzzer | — | 16-20h | 系統性找邊界 bug |
