# Test Results Analyzer Agent — 架構審查建議

**審查角色**：Testing / Test Results Analyzer Challenger  
**審查日期**：2026-07-16  
**對應 Agent 定義檔**：`.opencode/agents/testing-test-results-analyzer.md`

---

## 摘要

Test Results Analyzer agent 的設計借鑑了傳統 CI/CD 測試結果分析的最佳實踐（coverage JSON、pass rate、defect density），但與本專案實際場景存在顯著落差。本專案是一個**黑箱 Vision-based 遊戲 QA 框架**，其測試產出為 session.json（操作紀錄）、oracle anomaly 摘要、HTML timeline 報告，而非傳統的 code coverage 或 unit test results。以下建議旨在讓 Analyzer agent 真正對齊專案實際資料結構與使用場景。

---

## 建議 1：重新定義「Test Results Schema」— 以 Session Summary 取代 Coverage JSON

### 問題

Agent 範例程式碼假設輸入為 `pd.read_json(test_results_path)` 且含 `coverage.lines.pct` 等欄位。本專案完全沒有此類資料 — 產出是 `session.json`（動作序列 + 截圖路徑 + anomaly events）和 `GameSession.finish()` 的 result dict。

### 建議

定義專屬的 **Session Results Schema**，參考業界 session-based test report 格式（如 CTRF 的 `insights` 擴展機制），但對齊本專案的實際欄位：

```yaml
session_result:
  session_id: str
  game_name: str
  timestamp: ISO8601
  duration_ms: int
  actions_count: int
  screens_visited: list[str]
  anomalies:
    - type: oracle_violation | freeze | black_screen | console_error | no_effect_loop
      severity: critical | high | medium | low
      details: str
      screenshot: path
  oracle_checks:
    total: int
    passed: int
    violations: int
    candidates: int  # min_occurrences 未達門檻
  coverage:
    screens_known: int
    screens_visited_this_session: int
    transitions_exercised: int
    transitions_total: int
```

這樣 Analyzer 才有明確的「測試結果」可消費，而非硬套不存在的 code coverage。

### 參考

- **CTRF (Common Test Report Format)** — 定義了 tool-agnostic 的 JSON test result schema，支援 `extra` 擴展機制與 `insights` 跨 run 分析  
  https://github.com/ctrf-io/ctrf/blob/main/spec/ctrf.md

- **DreamUp QA Agent** — 類似的 Vision-based 遊戲測試框架，其 QAReport JSON 包含 `playability_score`、`issues[]`、`metadata` 等欄位，結構可參考  
  https://github.com/karinje/dreamup

---

## 建議 2：早期階段改用 Checklist-Based 品質評估，而非統計建模

### 問題

Agent 宣稱用 `RandomForestClassifier` 做 defect prediction、用 confidence intervals 驗證結論。但本專案現實是：bug 樣本極少（DESIGN.md 範例只有 BUG-001），session 數量初期可能只有個位數。n < 30 時這些統計方法根本無法收斂，會產生虛假的「高信心」結論。

### 建議

採用 **Minimum Viable Eval (MVE)** 的分層成熟度模型：

| 成熟度 | 適用條件 | 分析方法 |
|--------|----------|----------|
| Level 0 | < 5 sessions | 人工 checklist（畫面有載入嗎？有崩潰嗎？flow 走得通嗎？） |
| Level 1 | 5-20 sessions | 簡單計數（anomaly rate per session、screens coverage %、bugs/session） |
| Level 2 | 20-50 sessions | 趨勢圖（bugs/session 隨時間遞減？哪些 screen 反覆出問題？） |
| Level 3 | 50+ sessions | 統計方法（defect clustering、transition failure probability） |

Agent 應根據累積 session 數量**自動選擇分析層級**，而非一律跑 ML pipeline。這借鑑了 "Eval Pyramid" 概念 — 底層簡單便宜、頂層複雜昂貴，逐步升級。

### 參考

- **Minimum Viable Evals — Start Here** — 50 個 test case 即可抓住 80% 回歸，不需要平台級基礎設施  
  https://heyclarity.dev/blog/minimum-viable-evals/

- **The Evals Playbook for Solo Founders** — Eval Pyramid 分層模型（Golden Set → LLM Judge → Production Traces），適合小樣本初期  
  https://vikasmalpani.com/evals-playbook-for-solo-founders/

- **Running Experiments with Small Sample Size** — 小樣本下統計檢定的限制與替代策略  
  https://varunprajan.github.io/blog/running-experiments-with-small-sample-size/

---

## 建議 3：將「Release Readiness」重新定義為「知識庫成熟度評估」

### 問題

Agent 核心功能之一是 `assess_release_readiness()` — GO/NO-GO 決策。但本專案測試的是**第三方不可修改的遊戲**（AD-1），我們無法控制其 release。因此傳統的 "release readiness" 語義在這裡不適用。

### 建議

將 release readiness 改為 **Knowledge Maturity Assessment**，回答的問題是：「知識庫是否成熟到可以進入確定性回歸模式（AD-7）？」

評估維度：

1. **Flow 覆蓋率** — `screens_visited / screens_known`、`transitions_exercised / transitions_total`
2. **Confidence 穩定度** — 多少 transitions 達到 high confidence？有多少 low/unverified？
3. **Oracle 可靠度** — invariant violation 的 false positive rate（reread 通過但首次失敗的比例）
4. **異常基線** — 是否已建立「正常 anomaly 背景噪音」？新 anomaly 是否超出基線？
5. **Session 一致性** — 最近 N 個 session 的 flow 成功率是否穩定？

這直接對應 AD-7（確定性回歸層 + CI）的前置條件：只有知識庫夠成熟，才值得固化為零 LLM 的回歸腳本。

### 參考

- **Session-Based Test Management (SBTM) Guide** — 以 session 為單位測量覆蓋率、bugs/session、charter completion 的方法論  
  https://helpmetest.com/blog/session-based-test-management/

- **The MaLET Model — Maturity Levels for Exploratory Testing** — 探索式測試的成熟度模型，定義從 freestyle 到 fully scripted 的演進路徑  
  https://doi.org/10.1109/seaa53835.2021.00019

---

## 建議 4：明確與 oracle.py / detector.py 的職責界線 — Analyzer 是「跨 session 趨勢層」

### 問題

oracle.py 已做 per-action 的 invariant violation 判斷，detector.py 做 per-frame 的崩潰級偵測。若 Analyzer 只是把這些 per-event 結果重新包裝成報表，其獨立價值不明。

### 建議

明確定位 Analyzer 為 **Cross-Session Longitudinal Analysis Layer**：

```
detector.py  → per-frame（凍結？黑屏？console error？）
oracle.py    → per-action（invariant 違規？）
reporter.py  → per-session（timeline + 摘要）
analyzer     → cross-session（趨勢 + 退化偵測 + 熱區識別）
```

Analyzer 的獨特價值：

- **退化偵測**：同一 screen/transition 的 anomaly rate 是否隨版本/時間上升？
- **熱區識別**：哪些 screen 是 bug 密集區（bugs/session-hour 最高）？
- **Pattern clustering**：不同 session 中重複出現的 anomaly sequence → 穩定 repro_steps
- **Knowledge gap alerting**：哪些 screen 從未被 visit？哪些 transition 只有 low confidence？

這借鑑了 rsn-game-qa 的 12 oracle 架構 — 每個 oracle 管單一維度偵測，上層做跨維度/跨 episode 的聚合分析。

### 參考

- **rsn-game-qa** — RL-driven 遊戲測試平台，12 bug-detection oracles + session/episode 分層報告架構  
  https://github.com/Roboter-Schlafen-Nicht/rsn-game-qa

- **Cross-Version Software Defect Prediction Considering Concept Drift** — 跨版本/跨時間的 defect trend 分析，含 concept drift 偵測  
  https://www.mdpi.com/2073-8994/15/10/1934

- **Evaluating Testing Effectiveness During Software Evolution: A Time-Series Cross-Section Approach** — 用時間序列分析測試活動效果，跨專案/跨時段  
  https://doi.org/10.1002/smr.531

---

## 建議 5：報告受眾調整 — 從 Executive Dashboard 改為 Developer/QA Operator 導向

### 問題

Agent 設計了 `create_executive_report()` 與「stakeholder communication」。但本專案的使用場景是單人/小團隊用 Hermes Agent 對話式操作，可中途插話修正。Executive dashboard 在此場景屬過度設計。

### 建議

報告體系應分為兩層：

**1. Operator Summary（主力）** — 給每天跑 QA session 的人看：

```
=== Session Trend (last 7 runs) ===
anomaly_rate:  0.12 → 0.08 → 0.15 → 0.05 (↓ trending)
screens_coverage: 8/12 (67%) — missing: shop, settings, result_screen
oracle_violations: 2 confirmed, 1 candidate
hotspot: gameplay screen (3 freeze events in 7 sessions)
knowledge_maturity: Level 2 (20+ sessions, trend analysis available)

Action items:
- [ ] Explore shop/settings screens (0 sessions)
- [ ] Investigate gameplay freeze pattern (BUG-001 reproduction rate: 43%)
```

**2. Periodic Report（輔助）** — 週/月頻率，給需要決策「是否投資固化回歸腳本」的人：

- 知識庫成熟度分數
- 本週期新發現 vs 已知問題
- 建議下一步（繼續探索 / 開始寫確定性腳本 / 調整 oracle invariant）

這借鑑了 GameEval 與 ManaMind 的報告設計 — 即時 dashboard 給操作者，定期報告給決策者。

### 參考

- **GameEval** — 自主遊戲測試平台，即時 WebSocket dashboard + D1 結構化 metadata 儲存，報告設計面向操作者  
  https://github.com/adam0white/GameEval

- **ManaMind Product** — 商業級遊戲 QA 平台的 Command Centre 設計，分「即時監控」與「結構化 bug report」兩層  
  https://manamind.ai/product

- **MVE Regression Gates** — 用 severity-weighted failure count 做 pass/fail 門檻，適合小規模但需要決策的場景  
  https://optyxstack.com/llm-evaluation/minimum-viable-eval-starter-kit-50-tests

---

## 建議 6：引入 Session-Based Test Management (SBTM) 指標作為分析框架

### 問題

Agent 的 metrics 框架（pass rate、defect density per KLOC、coverage %）全部來自傳統 CI 測試語境。本專案的「測試」是探索式的 session-based 活動，需要不同的度量體系。

### 建議

採用 SBTM 的核心指標並自動化：

| SBTM 指標 | 本專案對應 | 自動化來源 |
|-----------|-----------|-----------|
| Sessions completed | `len(runs/<game>/*)` | session_manager.py |
| Bugs/session-hour | `anomalies_confirmed / session_duration_hours` | session.json |
| Charter coverage | `screens_visited / screens_in_knowledge` | knowledge_base.py |
| TBS ratio (Test/Bug/Setup) | `action_time / investigation_time / startup_time` | session timeline |
| Bug discovery trend | bugs/session 隨時間的移動平均 | cross-session aggregation |
| Diminishing returns signal | 連續 N 個 session bugs/session < threshold | analyzer trigger |

當 bug discovery rate 持續下降（如連續 5 個 session < 0.5 bugs/hour），Analyzer 應自動建議：「此區域探索已趨飽和，建議固化為確定性回歸腳本（AD-7）」。

### 參考

- **Session-Based Test Management: Structured Approach to Exploratory Testing** — SBTM 完整指標體系與 debrief 流程  
  https://yrkan.com/blog/session-based-test-management/

- **How to Manage and Measure Exploratory Testing using SBTM** — TBS metrics、defects/session、charter completion 的實務應用  
  https://medium.com/globant/how-to-manage-and-measure-exploratory-testing-using-session-based-test-management-f0f62bd8363e

- **Exploratory Test Management: The Complete Guide** — SBTM 與 CI/CD 整合、ROI 度量、覆蓋率追蹤  
  https://testquality.com/exploratory-test-management-the-complete-guide-for-modern-qa-teams/

---

## 總結

| # | 建議主題 | 優先級 | 影響範圍 |
|---|---------|--------|----------|
| 1 | 重新定義 Test Results Schema | High | Agent 定義 + session_manager.py |
| 2 | 分層成熟度分析（非一律 ML） | High | Agent 核心邏輯 |
| 3 | Release Readiness → Knowledge Maturity | Medium | Agent 定義 + 與 AD-7 對齊 |
| 4 | 明確職責界線：cross-session 趨勢層 | High | Agent 定義 + 架構文件 |
| 5 | 報告受眾從 executive 改為 operator | Medium | Agent deliverable template |
| 6 | 引入 SBTM 指標框架 | Medium | Agent metrics 定義 |

核心觀點：Test Results Analyzer 不應是通用 CI 測試分析工具的翻版，而應成為**黑箱探索式遊戲測試的跨 session 趨勢分析引擎**，其價值在於「從多次 session 的累積資料中發現 single-session 看不到的 pattern」。
