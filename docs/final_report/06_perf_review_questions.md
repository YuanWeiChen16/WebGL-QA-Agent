# 效能領域綜合報告 — 審閱質疑與修正建議

> **審閱者**：Senior Performance Reviewer  
> **審閱對象**：`02_performance_synthesis.md`  
> **交叉參照**：`01_qa_testing_synthesis.md`、`03_knowledge_base_synthesis.md`、`04_architecture_synthesis.md`  
> **日期**：2026-07-17

---

## 質疑 1：SSIM 效能瓶頸的優先級與 screen_id 穩定化存在邏輯衝突

**問題**：02 報告將「SSIM 效能基線 + Fast-SSIM 評估」列為 P0（§4.1），但 01 和 03 報告均以最高共識認定 **screen_id 應改用 perceptual hash (pHash/dHash) 取代全圖 SSIM**（01 §3、03 §1）。若 screen_id 穩定化方案落地，SSIM 在主路徑上的角色將大幅縮減（僅用於遮罩後的局部比對），此時投入 Fast-SSIM 整合的 ROI 是否仍成立？

**修正建議**：將 §4.1 改為條件式優先級 —— 若 pHash 方案先行落地，SSIM 加速降為 P2；若 pHash 延後，才維持 P0。兩條路徑的依賴關係應在 §十 的依賴圖中明確標註。

---

## 質疑 2：Per-Session Budget 的建議值缺乏情境分化，可能過於保守

**問題**：§1.1 建議 Layer 2 為「最多 200 次 Vision 呼叫或 500K tokens（~$2.5）」。但 04 報告 §1.2 的 Autonomous Optimization 來源建議「50 次呼叫 or 200K tokens」，03 報告 §5 引用的數字是「100 次 + 500K tokens」。三份報告三套數字，無一提供推導依據（例如：典型 session 實際需要多少次 Vision 呼叫？explore phase vs test phase 需求差異多大？）。

**修正建議**：
1. 補充實證基線 — 至少跑 5 個 session 統計實際 Vision 呼叫分佈（p50/p95/max），再設定 cap。
2. Cap 應依 session phase 分化：explore（較高 budget）、validate/test（較低 budget）。
3. 統一跨報告的建議值，或明確說明不同場景適用不同 cap。

---

## 質疑 3：Fast-SSIM「251× 加速」宣稱未經驗證，存在誤導風險

**問題**：§4.1 引用 Fast-SSIM 宣稱「1080p 從 580ms → 2.3ms，251× 加速」，但：
- Fast-SSIM 在 PyPI 上最新版本為 1.3.1（2024），Stars 極少，無生產環境使用紀錄
- 251× 加速通常意味著 AVX2/SIMD intrinsics，但未說明是否相容所有 CI 環境（ARM runner、Docker 無 AVX2）
- 未與其他成熟方案（OpenCV `cv2.SSIM`、Pillow-SIMD、降採樣後 scikit-image）做對比 benchmark

**修正建議**：將 §4.1 建議改為「評估多方案」而非直接推薦 Fast-SSIM。新增 decision matrix：

| 方案 | 預估延遲 | 平台相容性 | 成熟度 | 風險 |
|------|----------|-----------|--------|------|
| Fast-SSIM (AVX2) | ~2.3ms | x86 only | 低 | 高 |
| 降採樣至 480p + scikit-image | ~50-80ms | 全平台 | 高 | 低 |
| OpenCV SSIM | ~30-50ms | 全平台 | 高 | 低 |
| Pillow-SIMD + 自算 SSIM | ~20ms | x86 | 中 | 中 |

---

## 質疑 4：Observe-Act-Learn Loop 效能預算（§八）的「<20ms 確定性 observe」與實際不符

**問題**：§八表格宣稱「observe()（確定性）< 20ms」，但 §4.2 同時列出各偵測項目的預期耗時總和已含 freeze_detection（pixel_diff）5-15ms。然而：
- `page.screenshot()` 本身在 Playwright 中通常需 50-200ms（取決於 GPU 壓力，§2.6 也承認此點）
- 截圖是 observe() 的前置步驟，未計入 20ms budget
- 若加上截圖 + rAF 同步（§4.3 建議的雙重 rAF 等待），observe 實際延遲可能在 100-300ms

**修正建議**：
1. 明確區分「截圖取得」與「確定性分析」兩個時段的 budget
2. 修正 §八 表格，將 `observe()` 拆為：`screenshot acquisition: <200ms` + `deterministic analysis: <20ms`
3. 總 loop budget 應調整為含截圖的現實數字，否則會誤導實作者低估 latency

---

## 質疑 5：跨 Run 歷史趨勢比對（§6.2）被標為 P0 但缺乏與 CI Exit Code（§6.3）的先後約束

**問題**：§6.2 跨 Run 趨勢比對被列為 P0（預估 4-6h），但其前提是每次 run 要有可比較的 metrics。而 §6.3 的 CI exit code 機制（P1, 2-3h）實際上是 metrics 可被收集的基礎設施。依賴圖 §十 已畫出 `6.1 → 6.3` 和 `6.2 → 6.3`，但 6.2 的 P0 等級暗示它應先於 6.3，這與依賴關係矛盾。

此外，01 報告 §2 將 Pass/Fail Verdict + exit code 列為 **P0 #1**（最高優先中的第一項），而 02 報告卻將其降為 P1。跨報告優先級不一致。

**修正建議**：
1. CI Exit Code 機制應升為 P0（與 01、04 報告對齊）
2. 跨 Run 趨勢比對維持 P0，但在依賴圖中明確標註為「Phase 2 P0」（依賴 exit code 先完成）
3. 建議加入 implementation order 欄位，區分「優先級」與「執行順序」

---

## 質疑 6：Browser Pool 架構（§5.1）的 RAM 估算過於樂觀

**問題**：§5.1 聲稱「Browser contexts 比 browser instances 輕量且初始化更快」，但未量化 context 的實際記憶體開銷。根據 Playwright #21205 的討論：
- 每個 context 仍佔 30-80MB（含 renderer process）
- WebGL 遊戲的 context 記憶體遠高於普通網頁（GPU buffer + texture 記憶體）
- 公式 `workers = (available_RAM × 0.7) / per_context_RAM` 中的 `per_context_RAM` 未給出建議值

同時，04 報告 §7.1 將此項歸為「長期」Phase 4，而 02 報告標為 P2。兩者一致但與實際需求（nightly 已有多 session 場景）可能不匹配。

**修正建議**：
1. 補充 WebGL 遊戲 context 的實測記憶體數據（至少跑一個 session 量測 RSS 增長曲線）
2. 明確標註 per_context_RAM 建議值（WebGL 場景估 150-300MB）
3. 若 nightly 需要 5+ 並行 session，此項應升為 P1

---

## 質疑 7：缺少「效能優化對 QA 準確度的負面影響」風險評估

**問題**：整份報告專注於「更快、更省」，但未討論效能優化可能犧牲 QA 準確度的 trade-off：
- ROI crop（§1.3）：裁切區域外的異常將完全漏偵測（例如：UI 區域外的渲染 artifact）
- 降採樣 SSIM（§4.1）：降低解析度會犧牲細粒度異常偵測（1px 渲染錯誤在 480p 下不可見）
- Hash dedup（§1.3 表格最後行）：SSIM > 0.98 不呼叫 Vision，但遊戲內微小但有意義的 UI 變化（如 HP 從 100→99）可能被 skip
- Multi-model router（§1.4）：cheap model 用於「已知畫面讀數」可能錯過新出現的 anomaly

01 報告 §1 明確指出「Oracle 可靠性是系統可信度基礎」，03 報告 §2 也強調「多通道感測器融合」。效能報告的優化建議若未附帶準確度影響評估，可能導致「系統變快但變瞎」。

**修正建議**：
1. 每個優化建議增加「準確度影響」欄位（無影響 / 可接受降級 / 需 fallback 保護）
2. ROI crop 建議加入「全圖 fallback 頻率」（例如每 10 步做一次全圖 Vision 掃描）
3. Hash dedup 閾值應由 Oracle 精確度基線實驗決定，而非硬編碼 0.98
4. 新增一節「效能-準確度 Pareto 前沿」，明確表達每項優化的 trade-off 曲線

---

## 質疑 8：Structured Logging（§7.1）的 P0 定位與其他 P0 項目的依賴關係未釐清

**問題**：§7.1 被標為 P0，但 structured logging 本質上是「可觀測性基礎設施」，其價值在於支撐其他優化的量化驗證。04 報告 §5.1 也標為高優先但列在 Phase 2（短期 3-4 週）而非 Phase 1。

更關鍵的問題是：§7.1 應該是**所有效能優化的前置條件**，因為沒有 telemetry 就無法量化任何優化的效果。但 §十 的依賴圖只畫了 `7.1 → 7.2`（logging → alerting），未畫出 `7.1 → 1.5`（logging → Vision telemetry）、`7.1 → 6.2`（logging → 趨勢比對）等關鍵依賴。

**修正建議**：
1. 將 structured logging 定位為「Phase 0.5」— 其他所有 P0 優化開始前的前置條件
2. 在依賴圖中加入從 7.1 到 1.5、4.2、6.2 的虛線（「建議先行」而非「硬性阻塞」）
3. 與 04 報告對齊：Phase 1 而非 Phase 2，因為沒有 logging 就無法驗證其他改善是否真的有效

---

## 總結性修正建議

| # | 類型 | 建議 |
|---|------|------|
| A | 依賴圖補充 | 加入 pHash ↔ SSIM 的條件分支、7.1 → 所有量化驗證項目的前置關係 |
| B | 跨報告對齊 | CI Exit Code 升為 P0；Per-session budget 統一數值或明確場景區分 |
| C | 風險欄位 | 每項優化增加「準確度影響」與「平台相容性」欄位 |
| D | 實證缺口 | 補充實際 session Vision 呼叫統計、context 記憶體實測、Fast-SSIM 跨平台驗證 |
| E | 預算修正 | §八 表格拆分截圖取得與確定性分析，給出現實總 latency |

---

*本審閱基於跨四份報告的交叉分析。核心觀點：效能報告技術深度足夠，但在「優化 vs 準確度 trade-off」、「跨報告數值一致性」、「依賴關係完整性」三個面向存在顯著盲區。*
