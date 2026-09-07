# Level Designer 架構審查建議 — Batch 9

審查角色：Level Designer（空間敘事與流程設計專家）
審查日期：2026-07-16

---

## 摘要

從關卡設計的「空間可讀性」、「節奏曲線」、「分階段紀律」角度審視 WebGL QA Agent 架構。Defender 回應了五個質疑，其中 Q5（screen_id 穩定性）被接受為最有力批評，Q1/Q3/Q4 有既有機制但文件/工具化不足，Q2 被以 YAGNI 駁回。以下為經研究佐證後的改善建議。

---

## 建議 1：引入覆蓋率驅動探索（Coverage-Driven Exploration）取代平坦循環

**對應質疑**：Q1（critical path 優先）+ Q4（多路徑驗證）

**問題**：Defender 承認目前沒有「探索 budget 按 critical/optional 分配」的量化機制。Explore loop 依賴知識庫的 `newbie_task_sequence` 走 critical path，但對 optional branch 的覆蓋完全無策略。

**建議**：參考 Microsoft Research 的 Go-Explore 演算法，引入 state-space coverage metric 作為探索終止條件與 budget 分配依據。具體做法：

1. 在 `flow_graph.yaml` 的 node 加入 `priority: critical | secondary | optional` 欄位
2. 實作 visit counter（類似 Go-Explore 的 discretized state visitation），探索時以 inverse visit count 加權選擇下一目標
3. Critical path 的覆蓋率達 100% 才開始探索 secondary/optional

**學術佐證**：Go-Explore 在 1.5km x 1.5km 遊戲世界中 10 小時內達成完整覆蓋，遠優於 curiosity-driven RL 和 random baseline，且不需要人工示範。

**參考 URL**：
- https://www.microsoft.com/en-us/research/publication/go-explore-complex-3d-game-environments-for-automated-reachability-testing/
- https://ar5iv.labs.arxiv.org/html/2103.13798

---

## 建議 2：為 Flow Graph 加入語意權重（Semantic Weight），非 Pacing 但可指導測試力度

**對應質疑**：Q2（節奏曲線）

**問題**：Defender 以 YAGNI 駁回 pacing annotation，理由是「bug density ≠ pacing tension」且黑箱下無法推斷遊戲設計意圖。

**修正後建議**：不再要求 pacing arc，但建議在 `flow_graph.yaml` edge 加入 `test_weight: float` 欄位，依據：
- 該 transition 涉及金流操作（下注、購買）→ weight 高
- 該 transition 涉及不可逆操作（升級、刪除）→ weight 高
- 純瀏覽/設定 → weight 低

這不是 pacing，而是 **risk-based testing** 的標準做法。SMART 框架（2024）證明了將程式碼變更的 functional intent 映射到測試力度分配可達 94% branch coverage，是純 RL 方法的兩倍。

**實作建議**：讓 `adaptive_observe` 策略讀取 edge weight，weight > threshold 時自動啟用 Vision + oracle 雙驗證，低 weight 只跑確定性偵測。

**參考 URL**：
- https://arxiv.org/html/2512.12706v1 （SMART: Coverage-Aware Game Playtesting with LLM-Guided RL）

---

## 建議 3：工具化「知識凍結」流程——實作 `promote` CLI 命令

**對應質疑**：Q3（分階段紀律）

**問題**：Defender 承認「目前靜態→runtime 的分界不夠工具化（沒有 CLI 做 `promote runtime → static`），依賴人工編輯 YAML」。AD-10 的人工閘門設計正確，但缺乏工具支援使得 phase gate 在實踐中容易被跳過。

**建議**：實作 `python -m webgl_qa promote` 命令，執行：

1. 讀取 runtime `knowledge.yaml` 中 confidence=high 的 transition
2. 差異比對 static `flow_graph.yaml`，產出 diff 預覽
3. 人工確認後寫入 static 層並 git commit
4. 清除已 promote 的 runtime entries（或標記 `promoted: true`）

這等同關卡設計的「grey box playtest sign-off」——在探索期結束前，有一個明確的 checkpoint 把學到的知識鎖定。PDDL-based regression testing 的工作流程（Balyo et al., 2024）也採用類似的「log → model synthesis → human validation → planning」閘門。

**參考 URL**：
- https://arxiv.org/pdf/2402.12393 （Automating Video Game Regression Testing by Planning and Learning）

---

## 建議 4：Screen Fingerprint 採用 pHash pre-filter + 遮罩動態區的分層方案

**對應質疑**：Q5（screen_id 不穩定）

**問題**：Defender 接受此為最有力質疑，同意可從 🔲 提升為 🔧 並行工作。但表示「正確的 screen fingerprint 需要遮罩動態區」且依賴 AD-4 grounding。

**建議**：採用 visual regression testing 業界的標準分層方案，不需等 AD-4：

1. **Layer 1 — pHash pre-filter**（< 5ms）：將截圖降至 32x32 灰階做 DCT，產出 64-bit fingerprint。Hamming distance < 3 = 同一 screen，直接跳過後續比對。
2. **Layer 2 — 固定遮罩 + SSIM**：在 `systems/*.yaml` 為每個 system 定義 `dynamic_regions` 矩形遮罩（魚群區、計時器、動畫區），遮罩後做 SSIM。
3. **Layer 3 — UI anchor extraction**（roadmap）：用 edge detection 提取 UI 固定元素輪廓作為 structural fingerprint。

此方案的 Layer 1+2 完全不依賴 AD-4 grounding，且 pHash 在業界被驗證為「pre-filter 角色下可將 diff 時間降低 60-80%」（Wopee.io benchmark）。`visual-guard` 套件已提供 pixel/SSIM/pHash 三層比對的 Python 實作可參考。

**參考 URL**：
- https://wopee.io/blog/screenshot-comparison-algorithms-visual-testing/
- https://pypi.org/project/visual-guard/
- https://registry.npmjs.org/@vizzly-testing/honeydiff （Rust-native 的 fingerprint + SSIM + cluster 實作）

---

## 建議 5：引入多 Agent 協作探索以加速覆蓋——參考 cMarlTest 架構

**對應質疑**：Q4（多路徑驗證）+ Q1（探索效率）

**問題**：Defender 承認「目前確實沒有 enumerate all viable paths per screen 的系統性機制」，且在黑箱 + Vision 下窮舉路徑成本太高。

**建議**：不需窮舉，但可用 TITAN 框架的「主動優先排序」思路：

1. **Action prioritization**：每個 screen 的 `known_elements` 按「未測試次數」排序，Vision 回傳 `suggested_action` 時與排序交叉驗證，優先點擊測試次數最少的元素
2. **Divergent session**：在 critical path 走通後，啟動「divergent mode」——每個 junction 刻意走非預設路徑，記錄結果
3. **多 session 並行**（長期 roadmap）：cMarlTest 證明多 agent 協作（active + passive observer）可顯著提升覆蓋率和效率

TITAN 框架（2025）已在商業 MMORPG 中達成 95% 任務完成率且偵測到 4 個既有方法遺漏的 bug，其核心思路（LLM oracle + action prioritization + trace memory）與本專案架構高度相容。

**參考 URL**：
- https://arxiv.org/html/2509.22170 （TITAN: LLM-driven MMORPG Testing）
- https://arxiv.org/html/2502.14606 （cMarlTest: Curiosity Driven Multi-agent RL for 3D Game Testing）
- https://ar5iv.labs.arxiv.org/html/2202.10057 （CCPT: Curiosity-Conditioned Proximal Trajectories）

---

## 優先序建議

| 優先度 | 建議 | 理由 |
|--------|------|------|
| P0 | #4 Screen Fingerprint 分層方案 | Defender 已接受，且是其他改進的地基 |
| P1 | #3 promote CLI 工具化 | 低成本高收益，直接解決 phase gate 實踐問題 |
| P1 | #1 Coverage-driven exploration | 解決探索效率和終止條件問題 |
| P2 | #2 Edge test_weight | 需先有穩定 flow_graph（依賴 #4） |
| P3 | #5 多路徑/多 Agent | 長期 roadmap，依賴 #1 和 #4 的基礎 |

---

## Defender 防禦有效的觀點（不再追究）

- **Q2 的 YAGNI 論點**：同意不加 pacing arc metadata，改為 risk-based `test_weight`（見建議 #2）
- **Q3 的靜態/runtime 雙層設計**：承認這確實是一種 freeze 機制，問題在工具化而非設計
- **Q1 的 task sequence 機制**：承認 `newbie_task_sequence` 確實提供了 critical path 引導，但建議文件應更明確描述此機制
