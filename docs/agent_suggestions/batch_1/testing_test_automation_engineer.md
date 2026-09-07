# 測試自動化工程師 — 架構建議

> 角色：Test Automation Engineer（端對端測試自動化、flake 消除、CI 整合、故障可調試性）
> 日期：2026-07-16

---

## 建議 1：建立確定性回歸層（Zero-LLM Regression Gate）

**問題**：目前每次 run 都依賴 Vision LLM 非確定性 + 伺服器端 RNG，無法區分「遊戲壞了」與「Agent flaked」。AD-7 標記此為 roadmap 但尚無具體實作計畫。

**建議**：採用業界「Hybrid Model」——scripted setup → bounded exploration → scripted checkpoint 的三層架構：

1. **Scripted Setup**：用確定性腳本（`actions.py` + `execute_steps`）到達已知狀態
2. **Bounded Agent Exploration**：在已知狀態內做 AI 探索（限定範圍 + 時間上限）
3. **Scripted Invariant Checkpoints**：回到確定性斷言（pixel diff + 已知座標 OCR）

具體落地步驟：
- 將穩定的 flow（如 main_menu → gameplay 路徑）固化為 `scripts/regression/` 下的純 Python 腳本，zero LLM 呼叫
- 這些腳本產出二進位 exit code（0=pass, non-zero=fail），可直接掛 CI gate
- Agent 探索只在回歸層 pass 後才觸發，失敗不 block merge

**來源**：
- iXie Gaming — *AI Game Testing That Teams Trust: Designing Signal Over Flake*：「Trusted testing programs increasingly use a hybrid model that combines deterministic setup with constrained exploration... Scripted bots are effective because they are deterministic, auditable, and fast.」
  https://www.ixiegaming.com/blog/ai-game-testing-that-teams-actually-trust-how-to-design-signal-not-flake/
- AWS GameTech — *Building an AI game testing agent with Amazon Bedrock*：反映出 perceive-reason-act-reflect 循環中，stuck detection（連續 3 次相同結果 → auto-fail）是防止無限迴圈的關鍵機制
  https://aws.amazon.com/blogs/gametech/building-an-ai-game-testing-agent-with-amazon-bedrock/

---

## 建議 2：系統化 Flake Root-Cause Attribution Pipeline

**問題**：Oracle 報告的「bug」有至少 4 種失敗模式（真 bug / OCR 誤讀 / 座標偏移 / 時序競態），目前只有 `reread` 處理 OCR 誤讀，缺乏系統性分類。

**建議**：為每個 anomaly 附加 `failure_mode_tag`，建立自動分類邏輯：

```python
# 建議的分類規則
ATTRIBUTION_RULES = {
    "ocr_misread": "reread 第二次通過 → 標記為 OCR 誤讀，不計入 bug",
    "click_miss": "pixel_diff_ratio < threshold after click → 動作未生效",
    "timing_race": "第一次失敗、延遲 500ms 後 reread 通過 → 渲染延遲",
    "real_bug": "兩次 reread 皆違規 + pixel_diff 確認動作有生效 → 真正 bug",
}
```

每次 run 結束統計各 tag 比例，作為 suite health metric：
- `precision = real_bug / (real_bug + ocr_misread + timing_race + click_miss)`
- 目標：precision ≥ 80% 才有 CI gating 的信賴度

**來源**：
- Bugnet — *How to Identify Flaky Tests in Your Game CI Pipeline*：「Track every test run in a database, calculate a flakiness score per test based on pass-fail transitions across consecutive runs, quarantine tests that cross a threshold... Never ship auto-retry as a permanent solution — it hides real regressions.」
  https://bugnet.io/blog/how-to-identify-flaky-tests-in-your-game-ci-pipeline
- Mergify — *Flaky tests in Playwright*：明確列出 8 種 flake pattern 及其根因修復（非 workaround），強調 retries 是 instrumentation 而非 treatment
  https://mergify.com/learn/flaky-tests/playwright

---

## 建議 3：並行 Session 的知識庫隔離模型

**問題**：`knowledge/<game>/knowledge.yaml` 是共享可變狀態。若 CI 跑多個 shard 或 nightly 多 session 並行，會 race condition 寫同一檔案。

**建議**：採用「ephemeral per-run + canonical merge」雙層模型：

```
knowledge/<game>/
├── knowledge.yaml          ← canonical (read-only during run)
├── runtime/
│   ├── run_<timestamp_1>/  ← per-session ephemeral state
│   └── run_<timestamp_2>/
└── merge_queue/            ← post-run delta files, merged by single-writer
```

實作要點：
1. `GameSession.start()` 時 snapshot canonical knowledge 為 read-only baseline
2. Runtime 學習寫入 `runtime/run_<id>/` 獨立目錄（無 race）
3. `GameSession.finish()` 產出 delta file 到 `merge_queue/`
4. 獨立的 merge 程序（單一 writer）按序合併 deltas 到 canonical

這與 Playwright 的 worker isolation 模型一致——每個 worker 擁有獨立狀態，不共享可變資料。

**來源**：
- Playwright 官方文件 — *Parallelism*：「All workers have identical environments... You can't communicate between the workers... Note that parallel tests are executed in separate worker processes and cannot share any state or global variables.」
  https://playwright.dev/docs/test-parallel
- Playwright 官方文件 — *Best Practices*：「Each test should be completely isolated from another test and should run independently with its own local storage, session storage, data, cookies etc. Test isolation improves reproducibility, makes debugging easier and prevents cascading test failures.」
  https://playwright.dev/docs/best-practices

---

## 建議 4：定義 Pass/Fail Verdict 的明確判定標準

**問題**：AD-7 明確指出 `finish()` 無 pass/fail verdict 與 exit code，多個 run 停在 "running" 狀態。任何 CI 整合都需要二進位信號。

**建議**：定義三層 verdict 邏輯，將非確定性 oracle 的假陽率納入考量：

```python
class RunVerdict(Enum):
    PASS = 0      # exit code 0
    FAIL = 1      # exit code 1 — confirmed bugs found
    UNSTABLE = 2  # exit code 2 — anomalies found but confidence < threshold

def compute_verdict(session_result) -> RunVerdict:
    confirmed_bugs = [a for a in session_result.anomalies 
                      if a.attribution == "real_bug"]
    candidates = [a for a in session_result.anomalies 
                  if a.attribution in ("timing_race", "ocr_misread")]
    
    if confirmed_bugs:
        return RunVerdict.FAIL
    if candidates and len(candidates) > MAX_CANDIDATE_THRESHOLD:
        return RunVerdict.UNSTABLE  # 不 block merge，但觸發 triage
    return RunVerdict.PASS
```

CI 整合規則：
- `PASS (0)` → 綠燈
- `FAIL (1)` → 紅燈，block merge
- `UNSTABLE (2)` → 黃燈，不 block 但開 triage ticket

只有 `FAIL` gate merge，避免假陽率過高時癱瘓 pipeline。同時追蹤 `UNSTABLE` 比率作為 suite health metric。

**來源**：
- iXie Gaming：「Gates should block only when failures meet clear criteria: High player impact... Confirmed reproducibility (seed/state replay exists)... Evidence attached (artifacts sufficient for immediate triage)」
  https://www.ixiegaming.com/blog/ai-game-testing-that-teams-actually-trust-how-to-design-signal-not-flake/
- visual-differ (npm)：展示簡潔的 exit code 設計——`0` = all match, `1` = differences detected，適合 CI pipeline 整合
  https://registry.npmjs.org/visual-differ
- lookout (GitHub)：「`lookout run` exits non-zero if any test fails, so it slots straight into CI」+ JUnit XML 報告
  https://github.com/alexmchughdev/lookout

---

## 建議 5：強化故障可調試性——「One-Click Repro Package」

**問題**：目前 `session.json` 有動作序列 + 截圖，但缺乏足夠上下文讓人「只看 artifacts 就能判斷 bug 真假」，尤其缺少：動作前後截圖配對、Vision 原始回應、oracle 判定過程。

**建議**：每個 anomaly 產出 self-contained 的 repro package：

```
runs/<game>/<timestamp>/anomalies/
├── ANO-001/
│   ├── before.png           ← 動作前截圖
│   ├── after.png            ← 動作後截圖  
│   ├── diff.png             ← pixel diff 視覺化
│   ├── vision_response.json ← Vision LLM 原始回應（含 game_state 讀數）
│   ├── oracle_trace.json    ← invariant 評估過程（哪條規則、前後值、判定）
│   ├── attribution.json     ← failure mode 分類結果與理由
│   └── context.json         ← 前 3 步動作 + 後 2 步動作的 timeline slice
```

目標：任何 anomaly 都能在**不重跑**的情況下，由人類在 30 秒內判定真假。這是 E2E 自動化的黃金標準——「Every failure must be debuggable from artifacts alone」。

**來源**：
- iXie Gaming — *Hydrated State Replays (The Gold Standard)*：「The most trusted systems produce a repro package that can be loaded to recreate the failure at or near the frame before it occurs: Save file or world snapshot, Engine state dump, Deterministic seed(s), Build hash + configuration...」
  https://www.ixiegaming.com/blog/ai-game-testing-that-teams-actually-trust-how-to-design-signal-not-flake/
- Playwright — *Best Practices*：「Every failure must be debuggable from artifacts. Trace, screenshot, video, console, and network log attach to every CI failure. 'Works on my machine, can't repro' is a tooling failure, not an excuse.」
  https://playwright.dev/docs/best-practices
- Mergify — *Flaky tests in Playwright*：強調 trace-on-first-retry 策略——green run 零開銷、red run 完整取證
  https://mergify.com/learn/flaky-tests/playwright

---

## 總結優先順序

| # | 建議 | 優先級 | 依賴 |
|---|------|--------|------|
| 1 | 確定性回歸層 | 高 | AD-4 座標穩定化（部分） |
| 2 | Flake Attribution Pipeline | 高 | 無（可立即開始） |
| 3 | 並行知識庫隔離 | 中 | 無（架構變更） |
| 4 | Pass/Fail Verdict | 高 | 建議 2（attribution 結果） |
| 5 | Repro Package | 中 | 建議 2（attribution metadata） |

建議 2 → 4 → 1 的順序落地：先能分類失敗模式、再能出 verdict、最後有確定性層可 gate CI。
