# Testing Workflow Optimizer 審查建議

**審查角色**：Workflow Optimizer（流程改善與自動化專家）
**審查日期**：2026-07-16
**審查範圍**：測試工作流程的階段轉換、覆蓋率定義、CI 整合、Oracle feedback loop、跨 session 聚合

---

## 建議一：立即實作 L1 崩潰偵測 Smoke Test CI（不等 AD-4/AD-5）

### 問題

AD-7 將 CI 整合標為「依賴 AD-4/AD-5 先穩定」，但這指的是 L3 確定性回歸層。目前已有的 `detector.py`（console error、凍結、黑白屏、記憶體）和 `perceiver.py`（pixel_diff/SSIM）是純確定性的、零 Vision 呼叫、零成本，完全可以先跑起來。唯一缺的是 `finish()` 沒有 exit code。

### 建議

採用遊戲業界標準的**分層 CI 架構**：

| 層級 | 觸發時機 | 內容 | 目標時間 |
|------|----------|------|----------|
| Per-commit smoke | 每次 push | 啟動遊戲 + 偵測崩潰 + 基本操作 | < 10 分鐘 |
| Nightly regression | 每晚 | 完整 systems/*.yaml 操作序列 + anomaly 統計 | < 30 分鐘 |
| Release candidate | 手動觸發 | 全路徑 + Oracle invariant + 人工探索 | < 2 小時 |

具體實作：
1. `GameSession.finish()` 加入 `sys.exit(1 if anomalies else 0)` 的 verdict
2. 寫一個 `scripts/ci_smoke.py`，從 `systems/*.yaml` 讀確定性操作序列
3. GitHub Actions / 排程任務掛上，失敗自動建 issue

### 依據

業界共識是 **boot test 是 ROI 最高的自動化測試**，不需要等完美框架才開始：

- iXie Gaming：「Per-Commit Smoke: Quick startup and gameplay validation under 10 minutes」
  - URL: https://www.ixiegaming.com/blog/automated-game-testing-that-delivers-bots-toolchains-and-ci-cd/
- Bugnet：「Start with smoke tests that verify your game boots and loads every scene without crashing」
  - URL: https://bugnet.io/blog/setting-up-automated-regression-tests-for-game-builds
- ButterStack：「A boot test that runs on every build catches more issues than you'd expect... It's the highest-ROI test you'll ever write」
  - URL: https://www.butterstack.com/blog/game-dev-testing-qa-pipeline/
- Beefed.ai：「Gate 1 — BVT / Per-PR smoke: binary launches, main menu, primary scene load... Make the BVT a true gate」
  - URL: https://beefed.ai/en/regression-testing-game-development

### 預期效益

- **週期時間**：從「手動確認遊戲能跑」→ 自動 10 分鐘內回饋
- **錯誤率**：崩潰級問題的漏檢率降至接近零
- **實作成本**：極低（1-2 天工作量），不需改動核心架構

---

## 建議二：定義分層覆蓋率指標，對齊三階段模式

### 問題

目前終止條件只有 `--duration`/`--runs`，沒有語義化的覆蓋率定義。探索可能重複造訪相同 screen 而不自知，無法判斷「何時已經探索夠了」。

### 建議

建立三層覆蓋率指標，自然對應 Explore → Validate → Test 三階段：

```yaml
# config/coverage_targets.yaml
coverage:
  explore:
    metric: screen_visit_rate          # visited_screens / total_known_screens
    target: 0.9                         # 90% screen 造訪率
    termination: true                   # 達標即可考慮升級到 Validate
    
  validate:
    metric: flow_edge_coverage          # traversed_edges / total_known_edges
    target: 0.85                        # 85% flow edge 覆蓋率
    min_confidence: medium              # 只計 confidence >= medium 的 edge
    
  test:
    metric: invariant_trigger_rate      # triggered_invariants / total_invariants
    target: 0.8                         # 80% invariant 觸發率
    additional: systems_action_coverage # executed_actions / total_defined_actions
```

**為什麼不用像素覆蓋率**：黑箱 + 動態魚群畫面下，像素級覆蓋率沒有語義意義，只會被 RNG 動畫灌水。

### 依據

- iXie Gaming 的「Coverage Minutes」概念：「How many minutes of real gameplay does your automation simulate daily? A single scenario graph can cover more ground than 20 isolated tests」
  - URL: https://www.ixiegaming.com/blog/automated-game-testing-that-delivers-bots-toolchains-and-ci-cd/
- Beefed.ai：「Use coverage signals to expose blind spots: code coverage for logic-heavy assemblies and telemetry/event coverage for runtime systems where code coverage can't reach」
  - URL: https://beefed.ai/en/regression-testing-game-development
- Bugnet：「Track how many tests pass and fail per build... which systems produce the most regressions」
  - URL: https://bugnet.io/blog/setting-up-automated-regression-tests-for-game-builds

### 預期效益

- 探索有明確停止條件，不再「盲跑 N 分鐘」
- 階段升級有數據支撐（搭配 AD-10 人工確認閘門）
- 可衡量每次 session 的邊際貢獻

---

## 建議三：建立 Oracle 誤報的結構化 Feedback Loop

### 問題

目前 oracle 的二次確認（reread）和 min_occurrences 機制已落地，但人工確認/否決後的回饋是非結構化的手動改 YAML）。缺乏：
- 結構化的 dismiss 記錄（為什麼誤報？）
- 自動提議調整門檻的機制
- 誤報歷史追蹤（同一條 invariant 的 precision 隨時間變化）

### 建議

參考 OASIs 的迭代改進流程和 SmartOracle 的 False Positive Critic 架構：

```python
# oracle_feedback.py
@dataclass
class OracleFeedback:
    invariant_id: str
    session_id: str
    timestamp: str
    verdict: Literal["confirmed_bug", "false_positive", "deferred"]
    reason: str  # e.g. "OCR misread during animation", "RNG timing"
    suggested_adjustment: Optional[dict]  # e.g. {"min_occurrences": 3}

class OracleFeedbackLoop:
    def record_feedback(self, feedback: OracleFeedback): ...
    def compute_precision(self, invariant_id: str, last_n: int = 20) -> float: ...
    def suggest_adjustments(self) -> List[dict]: ...
```

工作流程：
1. `report.html` 的每個 candidate 旁加 `[Confirm] [Dismiss]` 按鈕
2. Dismiss 時記錄原因分類（OCR 誤讀 / RNG 時序 / 動畫干擾 / invariant 定義錯誤）
3. 累積 N 筆後自動計算該 invariant 的 precision，低於閾值（如 50%）自動提議調高 min_occurrences
4. 所有 feedback 存入 `knowledge/<game>/oracle_feedback.yaml`，跨 session 累積

### 依據

- OASIs (ISSTA 2018)：迭代式 oracle 改進流程，人在迴路中修正 false positive/negative，平均提升 48.6% 錯誤偵測率
  - URL: https://doi.org/10.1145/3213846.3229503
- SmartOracle (2026)：agentic 架構中的 False Positive Critic sub-agent，達成 18% false positive rate + 0.84 recall
  - URL: https://arxiv.org/pdf/2601.15074
- ISONOISE (2025)：human-in-the-loop oracle learning 中的 mislabel 偵測，以 disagreement score 識別錯誤標籤
  - URL: https://arxiv.org/pdf/2506.13273
- TOGLL (2024)：LLM-based oracle generation 研究指出，超過 10% false positive rate 會讓開發者放棄工具
  - URL: https://arxiv.org/html/2405.03786v2

### 預期效益

- Oracle precision 可追蹤、可改善（目標：< 10% 誤報率）
- 減少人工重複判斷相同類型的誤報
- 長期建立每條 invariant 的信賴度數據

---

## 建議四：實作跨 Session 趨勢聚合（aggregate_runs）

### 問題

每個 session 獨立產出 report，但跨 session 的 bug 重現率、anomaly 頻率、新增/消失的問題沒有追蹤機制。一旦進入定期回歸測試，這是必要的基礎設施。

### 建議

參考 Fern Platform、Flakiness.io、Piwi Dashboard 等測試智能平台的架構，在 `session_manager.py` 加入聚合功能：

```python
# session_manager.py 擴充
class RunAggregator:
    def aggregate_runs(self, game: str, last_n: int = 10) -> AggregateReport:
        """掃描 runs/<game>/*/metadata.json，產出跨 run 統計"""
        return AggregateReport(
            bug_reproduction_rates={},    # bug_id → 最近 N 次出現率
            anomaly_frequency={},         # anomaly_type → 每 run 平均次數
            new_bugs=[],                  # 本期新增
            resolved_bugs=[],             # 本期消失（連續 M 次未出現）
            coverage_trend=[],            # 每次 run 的覆蓋率
            stability_score=0.0,          # 綜合穩定度（0-1）
        )
    
    def detect_flaky_anomalies(self, game: str) -> List[str]:
        """識別間歇性出現的 anomaly（類似 flaky test 偵測）"""
        ...
```

輸出格式參考 Piwi Dashboard 的 heat-map 概念：每天一格，顏色代表狀態（綠=無異常、黃=candidate、紅=confirmed bug）。

### 依據

- Fern Platform：「Universal Test Aggregation — REST API accepts test results from any framework... Flaky Test Detection — Automatically identifies tests that pass/fail intermittently」
  - URL: https://github.com/guidewire-oss/fern-platform
- Flakiness.io：「Track each test's performance across commits to detect regressions... A test that flips between pass and fail on the same commit is classified as a flake; a test whose outcome changes at a specific commit and stays that way is a regression」
  - URL: https://flakiness.io/
- Piwi Dashboard：「Persistent test intelligence — every run, trace, and report is stored permanently and browsable across history. Compare runs side by side, track flakiness over time」
  - URL: https://github.com/PhenX/piwi-dashboard
- Semaphore Flaky Tests：「Spot trends and track issues over time with visualizations that highlight flaky tests and review test performance history」
  - URL: https://semaphore.io/product/flaky-tests-dashboard

### 預期效益

- 回歸測試有「趨勢」可看，不只是單次 pass/fail
- 間歇性問題（flaky anomaly）可被識別並量化
- 為未來 CI 的 pass/fail 判定提供歷史基線

---

## 建議五：建立階段轉換的半自動提議機制

### 問題

Explore → Validate → Test 的三階段轉換目前完全由人工決定。這在 AD-5/AD-6 未穩定前是合理的（自動升級會產生錯誤判定），但長期需要一個「系統提議、人工確認」的機制，否則隨著 session 數量增加，人無法判斷何時該切換。

### 建議

設計一個 **Phase Readiness Advisor**，每次 session 結束時評估是否建議升級：

```python
class PhaseReadinessAdvisor:
    def evaluate_after_session(self, game: str, current_phase: str) -> PhaseAdvice:
        """基於覆蓋率指標和 knowledge 穩定度，提議是否升級"""
        if current_phase == "explore":
            screen_coverage = self.calc_screen_coverage(game)
            edge_stability = self.calc_edge_stability(game)  # 連續 N session 無新 edge
            if screen_coverage >= 0.9 and edge_stability >= 3:
                return PhaseAdvice(
                    recommend="upgrade_to_validate",
                    confidence=0.8,
                    reason=f"Screen coverage {screen_coverage:.0%}, no new edges in last {edge_stability} sessions",
                    blockers=self.check_blockers(game)  # e.g. AD-5 screen_id 不穩定
                )
        ...
```

**關鍵設計原則**（對齊 AD-10）：
- 系統只「提議」，不自動執行
- 提議附帶 confidence 和 blockers
- 輸出到 `reviews/` 或 report，由人決定是否採納
- 依賴的指標（覆蓋率、edge stability）來自建議二的實作

### 依據

- ButterStack 的分層門控：「Per-Commit Smoke → Nightly → Release Candidate... Make the BVT a true gate; a green BVT must be required to merge or promote to next stage」
  - URL: https://www.butterstack.com/blog/game-dev-testing-qa-pipeline/
- Beefed.ai 的 Gate 哲學：「Gate 1 (BVT) → Gate 2 (Nightly) → Gate 3 (Release-candidate full regression)」
  - URL: https://beefed.ai/en/regression-testing-game-development
- Bugnet 的漸進式策略：「Start with smoke tests... Add screenshot comparison... Add gameplay bots... integrate into CI/CD」
  - URL: https://bugnet.io/blog/setting-up-automated-regression-tests-for-game-builds

### 預期效益

- 避免過早升級（AD-5/AD-6 未穩定時系統會列為 blocker）
- 避免過晚升級（覆蓋率已飽和仍在無效探索）
- 保持「人是決策閘門」的原則，同時減輕人工判斷負擔

---

## 實施優先級

| 優先級 | 建議 | 理由 | 預估工作量 |
|--------|------|------|-----------|
| P0 | 建議一（L1 CI smoke） | 零依賴、極低成本、最高 ROI | 1-2 天 |
| P1 | 建議四（跨 session 聚合） | CI 上線後立即需要趨勢數據 | 3-5 天 |
| P1 | 建議二（覆蓋率指標） | 為階段轉換和終止條件提供基礎 | 2-3 天 |
| P2 | 建議三（Oracle feedback） | 需要累積足夠 session 後才有意義 | 5-7 天 |
| P2 | 建議五（階段轉換提議） | 依賴建議二的覆蓋率指標先就位 | 3-5 天 |

---

## KB Defender 回覆摘要

KB Defender 確認：
1. Validate/Test 模式確實尚未實作，三階段轉換目前是人工決定（非遺漏，是 AD-5/AD-6 未穩定前的合理選擇）
2. 覆蓋率應分層組合：screen 造訪率（explore）、flow edge 覆蓋率（validate）、invariant 觸發率（test）
3. L1 崩潰偵測 smoke test 完全不依賴 AD-4/AD-5，可以先上
4. Oracle feedback loop 目前缺乏結構化機制，只能手動改 YAML
5. 跨 session 趨勢追蹤完全缺失，但 `bugs` 區塊的 `reproduced` 計數是可用的基礎
