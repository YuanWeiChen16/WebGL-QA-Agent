# Minimal Change Engineer 審查建議 — Batch 7

角色：**Minimal Change Engineer**（最小變更工程師）
審查焦點：scope creep、不必要的複雜度、YAGNI 違規、投機性架構
日期：2026-07-16

---

## 建議 1：pixel_diff 機制對動態畫面遊戲的適用性問題

**現況**：AD-4 已落地「點擊後斷言」，用 `pixel_diff_ratio` 判斷動作是否生效。但主要測試目標是「魚群持續游動」的 WebGL 遊戲——pixel diff 永遠非零。

**問題**：這等於為一個「在主要使用場景下必定需要額外邏輯來過濾噪聲」的功能投入了實作成本。業界做法是：對高動態畫面，pixel diff 不應作為 primary signal，而應改用 ROI masking（遮罩動態區域）或 perceptual hashing 比對 UI 固定區域。

**建議**：
- 若 pixel_diff 在動態遊戲場景中確實無法裸用（需 ROI mask），應在文件中明確標註其適用範圍為「靜態 UI 畫面」
- 考慮是否應延後「點擊後斷言」的實作，直到有具體的 ROI masking 策略，而非先做一個對主場景無效的通用版
- 若已落地且有實際價值（如用於靜態 menu 畫面），則無需移除，但應停止在文件中宣稱它適用於所有場景

**參考**：
- [Bugnet: How to Automate Screenshot Comparison Testing for Games](https://bugnet.io/blog/how-to-automate-screenshot-comparison-testing) — 明確指出「animated backgrounds with looping particles or shader animations are non-deterministic. Pause animations or capture from a fixed time step.」pixel diff 對動態畫面需特殊處理。
- [Microsoft Inspector (arXiv 2207.08379)](https://ar5iv.labs.arxiv.org/html/2207.08379) — 純像素輸入的遊戲測試 agent，用 curiosity-based reward（RND）而非 raw pixel diff 來判斷「新畫面」vs「舊畫面」。

---

## 建議 2：confidence 升降機制——無消費者的投機性架構

**現況**：AD-6 承認 confidence 只有遞增無遞減，且 DESIGN.md 宣稱的「失敗則降低」無對應程式。更關鍵的是：目前沒有任何 caller 依賴 confidence 值來做「選路」或「跳過低信心 transition」的決策。

**問題**：這是典型的 YAGNI 違規——為一個「未來也許有用」的特性預留了 schema 和部分實作，但沒有消費者。Kent Beck 的 YAGNI 論述明確指出：投機性結構即使免費產生，仍有兩張帳單（optionality cost + NPV cost）。

**建議**：
- 在有具體 caller 需要依據 confidence 做決策之前，不應投入時間實作「遞減 + 時間衰減」
- 若 confidence 欄位已存在但無人讀取，考慮簡化為 `visit_count: int`（純事實記錄），移除 low/medium/high 語義
- 把 AD-6 狀態從「🔲 待處理」改為「🧊 暫緩」，加註「等待具體消費者場景」

**參考**：
- [Martin Fowler: Yagni](https://martinfowler.com/bliki/Yagni.html) — 「any abstraction that makes it harder to understand the code for current requirements is presumed guilty」
- [Kent Beck: The Cost YAGNI Was Never About (2026)](https://newsletter.kentbeck.com/p/the-cost-yagni-was-never-about) — 「speculative structure sends you two bills... optionality says don't commit before the information arrives」

---

## 建議 3：Hermes Agent 整合架構——投機性設計段落

**現況**：DESIGN.md 花了大量篇幅描述「Hermes Agent 串接」架構（對話式微調、cron 排程、skill 化知識），但實際入口只有 `scripts/` + `GameSession` API。文件自己也承認「目前尚未實作」。

**問題**：這段描述的是一個「也許有一天會成真」的整合方案，但它在 DESIGN.md 中佔了相當份量，會誤導新人以為這是當前架構。這不是「思考未來」（thinking ahead is good），而是「把未來設計當成現況描述」。

**建議**：
- 將 Hermes 整合段落移到獨立的 `docs/future/hermes_integration.md`，或在 DESIGN.md 中用明確的 `## Future / Roadmap` 區塊隔離
- DESIGN.md 的「架構」章節應只描述目前可執行的架構
- YAGNI-C 原則：「thinking ahead is good, implementing ahead is bad」——但目前的問題是「描述 ahead 卻不標註為 speculative」，造成認知負擔

**參考**：
- [ACCU: YAGNI-C as a Practical Application of YAGNI](https://accu.org/journals/overload/21/117/ignatchenko_1837/) — 第一原則「thinking ahead is good, implementing ahead is bad」，但前提是「think」不要混入「current specification」
- [ArchMan: YAGNI Principle](https://archman.dev/docs/core-design-and-programming-principles/general-principles/yagni) — 「speculative code costs: cognitive load — team must understand unused paths」

---

## 建議 4：Oracle 二次確認 + min_occurrences——「核心尚未充分使用」階段的防禦性程式

**現況**：AD-2 補了兩道感測器防護：(1) reread 二次確認（截圖重讀），(2) min_occurrences 連續 N 次違規門檻。這是為了防 Vision OCR 誤讀。

**問題**：這些防護的前提是「oracle 已在生產場景中被頻繁觸發，且 false positive 是實際痛點」。但如果 oracle 本身的使用頻率還很低（research preview 階段），這就是「為尚未發生的問題預先建造的防禦工事」。

**建議**：
- 若這些防護是基於實際跑過的 session 中觀察到的 false positive 而加，則合理——但應在 AD-2 中記錄「觸發事件：在 X 次 session 中觀察到 Y% false positive rate」
- 若是「預防性地加入因為理論上會有誤讀」，則建議先用最簡單的單次判斷，等實際跑出 false positive 數據後再加防護
- 最小變更原則：先讓核心 loop 跑起來並收集數據，再根據數據加防護層

**參考**：
- [Meta Engineering: Automating Dead Code Cleanup (SCARF)](https://engineering.fb.com/2023/10/24/data-infrastructure/automating-dead-code-cleanup/) — Meta 的做法是「先以小量跑 + 監控正確性，確認問題存在後才加防護層和自動化」。類比：先確認 oracle 的 false positive 是真實問題，再加 reread/min_occurrences。
- [c2 wiki: YouArentGonnaNeedIt](http://xp.c2.com/YouArentGonnaNeedIt.html) — 「if a developer finds a method in the system that is not sent, she should remove it」——如果防護層的觸發條件在實際使用中從未被滿足，它就是 dead code。

---

## 建議 5：四份設計文件 + 每日自動複審——研究性專案的文件密度成本

**現況**：專案同時維護 DESIGN.md、ARCHITECTURE_DECISIONS.md、KNOWLEDGE_ARCHITECTURE.md、README.md，加上 AD-10 的每日自動複審產出 `reviews/` 報告。

**問題**：對一個自稱「Research preview / 實驗性專案」且「介面與行為可能變動」的專案，這種文件基礎設施的維護成本可能超過其價值。每次 pivot 都需要同步更新四份文件 + 確保自動複審的 prompt 仍然對齊現狀。這本身就是 scope creep 的一種形式——「文件基礎設施的 scope creep」。

**建議**：
- 合併為兩份：README.md（使用者導向）+ DESIGN.md（包含架構決策追蹤，以 `## Architecture Decisions` 區塊存在）
- 每日自動複審在專案穩定前暫停（或改為週頻），避免「每天產出需要人工 triage 的報告」造成的 review fatigue
- 最小變更原則應用於文件：文件的存在本身也需要「有具體消費者」。問：誰在讀 KNOWLEDGE_ARCHITECTURE.md？多久讀一次？

**參考**：
- [Martin Fowler: Yagni](https://martinfowler.com/bliki/Yagni.html) — 「the cost of carry: the code adds some complexity to the software, this complexity makes it harder to modify」——文件也有 cost of carry，每次改程式都要想「哪幾份文件需要同步」。
- [Kent Beck: The Cost YAGNI Was Never About (2026)](https://newsletter.kentbeck.com/p/the-cost-yagni-was-never-about) — 「YAGNI is a meditation on timing. Building structure too soon is as risky as building structure too late.」文件基礎設施也是結構。

---

## 總結

| # | 類型 | 嚴重度 | 核心訊息 |
|---|------|--------|----------|
| 1 | 適用性 | 中 | pixel_diff 對主場景（動態遊戲）無效，需 ROI mask 才能用 |
| 2 | YAGNI | 中 | confidence 機制無消費者，應暫緩或簡化 |
| 3 | 認知負擔 | 低 | Hermes 整合描述混入現況架構，應隔離為 roadmap |
| 4 | 防禦性程式 | 低 | oracle 防護層應基於實際 false positive 數據，而非預防性添加 |
| 5 | scope creep | 低 | 四份文件 + 每日複審對 research preview 過重，建議合併/降頻 |
