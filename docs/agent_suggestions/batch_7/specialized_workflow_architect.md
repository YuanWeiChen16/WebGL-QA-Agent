# Workflow Architect 審查建議 — Batch 7

> 日期：2026-07-16
> 審查角色：Specialized Workflow Architect（專精完整工作流樹映射、分支條件、失敗模式、恢復路徑、交接契約）
> 審查面向：工作流設計、狀態機、故障恢復、資料完整性
> 批次：Batch 7 — 特化組

---

## 建議 1：為 GameSession 生命週期建立正式 Async State Machine

**問題**：`GameSession` 的 `start() → observe() → execute_action() → finish()` 缺乏正式狀態定義。AD-7 已標記 `finish()` 的 status 停在 "running"，但根本原因是沒有明確的狀態機——當 Playwright 連線斷開、browser crash、或 Vision 超時時，session 處於未定義狀態，無法自動清理或恢復。

**建議**：引入 `python-statemachine` 或類似的 async state machine library，定義 GameSession 的正式狀態轉換：

```
[created] → start() → [running]
[running] → observe()/act() → [running]
[running] → finish() → [completed]
[running] → (error) → [failed] → cleanup() → [terminated]
[running] → (timeout) → [timed_out] → cleanup() → [terminated]
```

每個狀態轉換需定義：
- 進入條件與守衛（guards）
- 超時限制
- 失敗時的清理動作（關閉 browser、flush partial report）
- 對外可觀察的狀態（報告中的 session status）
- 非法 transition（如 COMPLETED → RUNNING）要 raise error

**參考**：
- python-statemachine async 支援（自動切換 AsyncEngine、concurrent event sending）：https://python-statemachine.readthedocs.io/en/latest/async.html
- XState Python 實作（含 invoke/service/timeout/delayed transitions）：https://github.com/basiltt/xstate-statemachine
- AsyncStateMachine（Moore machine + side effects 分離、testable in isolation）：https://github.com/sideeffect-io/AsyncStateMachine

**對應 AD**：AD-7（CI exit code）
**優先級**：高

---

## 建議 2：Vision LLM 呼叫加入 Circuit Breaker + Fallback 降級

**問題**：`vision.py` 呼叫外部 gateway 沒有定義 timeout、retry 策略、或 circuit breaker。AD-9 提到「每 session 成本上限」待補，但更根本的是 agent loop 的 liveness——Vision gateway 連續失敗時，整個 observe-act loop 會卡死或無限等待。

**建議**：在 `vision.py` 層實作三層防護：

1. **Per-call timeout**：每次 Vision 呼叫設 20s hard timeout（可配置於 `default.yaml`）
2. **Retry with jitter**：transient 錯誤（429/500/502/503/529）最多重試 3 次，exponential backoff + full jitter，cap 32s
3. **Circuit breaker**：5 次失敗在 60s 窗口內 → 開路 30s；開路期間 observe loop 自動降級為「純確定性偵測」（detector + perceiver，不呼叫 Vision），並在報告中標記降級區段
4. **Session cost cap**：累計 Vision token 達上限 → 強制降級為確定性模式直到 session 結束

Python 實作可用 `pybreaker` library 或手寫（狀態簡單）。關鍵是 circuit 狀態對 reporter 可見，讓操作者知道哪些區段是「Vision-assisted」vs「deterministic-only」。

**參考**：
- LLM Circuit Breaker 生產模式完整指南（含 config、alerting、adaptive threshold）：https://www.onaro.io/docs/guides/circuit-breaker
- Claude API Circuit Breaker 實作（Redis distributed state、Lua atomic transitions、per-provider isolation）：https://www.sitepoint.com/claude-api-circuit-breaker-pattern/
- Retry/Fallback/Circuit Breaker 在 LLM app 的分層策略（何時用哪個 pattern）：https://portkey.ai/blog/retries-fallbacks-and-circuit-breakers-in-llm-apps/
- Circuit Breaker for LLM（pybreaker + per-provider isolation、real-world outage case）：https://supergood.solutions/blog/systems-sunday-circuit-breakers-llm-calls-2026/
- LLM Retry/Fallback 生產指南（timeout budget tree、idempotency、cost control）：https://solana.garden/guides/llm-retry-fallback-resilience-explained/

**對應 AD**：AD-9（感知分層與成本）
**優先級**：高

---

## 建議 3：知識庫 YAML 寫入改用 Atomic Write 防止損壞

**問題**：`knowledge_base.py` 在 session 結束時寫回 YAML，使用普通 `open(path, "w")` + `yaml.dump()`。若寫入途中 process 被 kill、或（未來）兩個 session 平行跑同一 game，YAML 會被截斷或交錯損壞。這對「累積式學習」的核心價值是致命的——一次損壞就丟失所有歷史知識。

**建議**：

1. **Atomic write**：改用 temp file + fsync + `os.replace()` 模式（跨平台原子操作）：
   ```python
   import tempfile, os, yaml
   def atomic_yaml_write(path, data):
       fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
       try:
           with os.fdopen(fd, 'w', encoding='utf-8') as f:
               yaml.dump(data, f)
               f.flush()
               os.fsync(f.fileno())
           os.replace(tmp, path)  # atomic on both POSIX and Windows
       except BaseException:
           os.unlink(tmp)
           raise
   ```

2. **Backup rotation**：每次寫入前複製上一版為 `.bak`（或帶 timestamp），最多保留 3 份。

3. **（未來）File lock**：若需平行 session，加 `fasteners.InterProcessReaderWriterLock` 包裹讀寫。

**參考**：
- `safeatomic`（atomic write + cooperative lock + checksum sidecar，完整 4 保證矩陣）：https://pypi.org/project/safeatomic/2.0.3/
- 真實案例：YAML 併發寫入損壞（nah 專案 issue #66，含 reproducer 數據）：https://github.com/manuelschipper/nah/issues/66
- atomic-hermes 的 `atomic_yaml_write` 實作（BaseException cleanup、preserve mode）：https://github.com/AtomicBot-ai/atomic-hermes/blob/dab36d9511cef5eef12849a57661e8f64e2e16dc/utils.py
- python-atomicwrites（POSIX + Windows MoveFileEx）：https://python-atomicwrites.readthedocs.io/en/latest/
- StackOverflow：多 process 存取 YAML 損壞解法（fasteners InterProcessReaderWriterLock）：https://stackoverflow.com/questions/72275028/characters-added-to-the-bottom-of-yaml-files-accessed-by-multiple-processes

**對應 AD**：AD-3（單一知識系統）
**優先級**：中高（實作成本極低，10 行 code）

---

## 建議 4：定義 Explore → Validate → Test 三階段的正式轉換條件

**問題**：DESIGN.md 列出三個運作模式但沒有定義轉換觸發條件。目前完全依賴人工選擇不同腳本，這意味：(a) 無法自動化端到端流程，(b) 沒有「何時算探索完成」的客觀指標，(c) Test 模式遇到新畫面時沒有自動回退機制。

**建議**：定義 workflow-level 狀態機（與 session-level 分開）：

```
[Explore] → coverage_threshold_met → [Validate]
[Validate] → all_paths_pass → [Test]
[Validate] → new_screen_discovered → [Explore]  (回退)
[Test] → unknown_screen_encountered → [Explore]  (局部回退)
```

轉換條件需量化（對應 AD-8 的覆蓋率定義）：
- **Explore → Validate**：已知 screen 數 ≥ `game_info.yaml` 宣告的 `expected_screens`，或連續 N 步無新 screen 發現
- **Validate → Test**：所有 `flow_graph` 中 `stable: true` 的路徑成功走過 ≥ 2 次
- **回退觸發**：Vision 回報 screen_id 不在已知清單中

即使短期保持人工觸發，也應在 `GameSession` 或上層 orchestrator 中記錄當前 phase 與轉換 metrics，讓操作者有客觀依據判斷「該切模式了」。

**參考**：
- Godot AI Playtest（外部 process 控制遊戲 + session lifecycle management）：https://github.com/marcushale/godot-ai-playtest
- AI Game Framework（state-driven game loop + GameState enum 控制探索/測試模式切換）：https://github.com/mariolpantunes/ai-game-framework
- Choreo async test framework（Scenario DSL 的三態 setup/expect/await + deadline-bounded scope）：https://github.com/clear-route/choreo

**對應 AD**：AD-7、AD-8（覆蓋率驅動終止）
**優先級**：中

---

## 建議 5：Session 事件 Incremental Flush 防止異常中斷資料遺失

**問題**：目前 session timeline 的事件（截圖、anomalies、actions、oracle results）只在 `finish()` 時一次性寫入 `session.json` 和報告。如果 browser crash 或 process kill 導致 `finish()` 未執行，整個 session 的資料全部遺失——包括可能已經發現的 bug evidence。

**建議**：

1. **Incremental append**：每個事件（observe / action / anomaly）發生時立即 append 到 `session.jsonl`（JSON Lines 格式，每行一個 event），而非記憶體累積。即使 process 中斷，已記錄的事件都保存。

2. **Checkpoint mechanism**：每 N 個事件（或每 30s）flush 一次 partial report HTML（或至少 JSON summary），讓操作者即使在 session 進行中也能查看進度。

3. **Recovery on restart**：下次啟動同 game 的 session 時，偵測到 `.jsonl` 存在但無對應 `report.html` → 提示上次異常中斷，可選擇生成部分報告或從斷點繼續。

4. **`finish()` 改為 finalize**：`finish()` 只做最終 summary 計算 + HTML render，不是唯一的持久化點。

**參考**：
- Game Loop Manager 的 tick-level state broadcast 模式（每 tick authoritative snapshot）：https://github.com/deepgram/stick-fighter/blob/main/game_loop.py
- Godot E2E enhance（out-of-process、crash isolated、screenshot on test failure）：https://github.com/2640735332/godot-e2e-enhance
- Choreo test framework 的 timeline event 即時記錄（per-scenario timeline with PUBLISHED/RECEIVED/MATCHED events）：https://github.com/clear-route/choreo

**對應 AD**：AD-7（run status + exit code）
**優先級**：中

---

## 總結

| # | 建議 | 對應 AD | 優先級 | 實作成本 |
|---|------|---------|--------|----------|
| 1 | GameSession 正式 state machine | AD-7 | 高 | 中 |
| 2 | Vision 呼叫 circuit breaker + fallback | AD-9 | 高 | 中 |
| 3 | 知識庫 atomic write | AD-3 | 中高 | 極低（10 行） |
| 4 | 三階段轉換條件量化 | AD-7, AD-8 | 中 | 中（設計為主） |
| 5 | Session 事件 incremental flush | AD-7 | 中 | 低 |

建議 1 與 2 是最高優先——它們直接影響 agent loop 在生產環境的可靠性，也是 AD-7（CI 化）的前置條件。建議 3 實作成本極低且後果嚴重，建議立即處理。
