# Automation Governance Architect — 架構審查建議

**審查日期**：2026-07-16
**審查角色**：Automation Governance Architect
**審查範圍**：自動化治理面 — 失敗恢復、成本護欄、審計回滾、冪等性、CI 終止狀態

---

## 建議 1：為每日複審排程 (AD-10) 加入失敗告警與 watchdog

### 問題

`scripts/daily_review.ps1` 經由 Windows Task Scheduler 每天 09:00 執行，但失敗時**完全靜默**——無 Event Log 寫入、無 email/webhook 告警、無 retention rotation。連續 N 天失敗等於「治理盲區」。

### 建議

1. 在排程任務的 Action 設定「失敗觸發第二排程」——利用 TaskScheduler Operational Event Log（Event ID 201 = 任務完成、203 = Action 啟動失敗）觸發告警腳本。
2. 加入 PowerShell watchdog：每天 10:00 檢查 `reviews/.logs/` 是否有當天 log，若無則發 webhook/email。
3. Log 加入 7 天 rotation（`Get-ChildItem | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } | Remove-Item`）。

### 參考實作

- Windows Event Log 觸發排程告警模式：https://superuser.com/questions/249103/make-windows-task-scheduler-alert-me-on-fail
- NXLog TaskScheduler Operational 監控：https://docs.nxlog.co/integrate/windows-task-scheduler.html
- Microsoft Q&A PowerShell TaskMonitor 範例：https://learn.microsoft.com/en-us/answers/questions/919978/for-dummies-steps-to-setup-ntevt-to-alert-on-faile

### 治理判定

**APPROVE AS PILOT** — 低修復難度、低風險，但需先在單機驗證告警觸發率再推廣。

---

## 建議 2：`finish()` 加入 pass/fail verdict + exit code 以接軌 CI

### 問題

`GameSession.finish()` 回傳 dict 但不設定 process exit code，且 `SessionManager.metadata.json` 只寫 "complete" 無 pass/fail。多個 run 異常退出時 metadata 停在 "running"。一個沒有終止狀態的自動化流程等於「永遠成功」——無法掛進 CI pipeline、無法觸發退化告警。

### 建議

1. `finish()` 末尾加 verdict 邏輯：

```python
import sys

verdict = "pass"
if any(a["severity"] == "critical" for a in anomalies):
    verdict = "fail"
    exit_code = 2
elif any(a["severity"] == "high" for a in anomalies):
    verdict = "fail"
    exit_code = 1
else:
    exit_code = 0

metadata["verdict"] = verdict
metadata["exit_code"] = exit_code
```

2. 腳本入口（`qa_interactive.py`）呼叫 `sys.exit(result["exit_code"])`。
3. CI 整合：exit code 0 = pass、1 = high severity fail、2 = critical fail，與 pytest 慣例對齊。

### 參考實作

- pytest exit code 公約（0-6）：https://docs.pytest.org/en/stable/reference/exit-codes.html
- CI pipeline 如何依 exit code 判定 pass/fail：https://dojofive.com/blog/how-ci-pipeline-scripts-and-exit-codes-interact/
- 自訂 test runner exit code 最佳實踐：https://www.happyassassin.net/posts/2016/12/31/qa-protip-of-the-day-make-sure-your-test-runner-fails-properly/

### 治理判定

**APPROVE** — 修復量極低（2-5 行），價值極高（解鎖 CI 化與退化偵測）。應為最高優先。

---

## 建議 3：Vision LLM 呼叫加入 per-session hard cap 成本護欄

### 問題

目前有 adaptive observe（pixel_diff < 0.02 跳過 Vision）和 retry cap = 3 的「軟」節流，但**無 per-session 最大 Vision 呼叫次數、無 token budget、無 session 最大時長**。若腳本因 bug 進入迴圈，成本無上限。

### 建議

1. 在 `config/default.yaml` 加入：

```yaml
cost_guardrails:
  max_vision_calls_per_session: 200
  max_session_duration_minutes: 60
  warn_at_percentage: 80
```

2. `vision.py` 呼叫前檢查計數器，達 hard cap 則 raise `BudgetExceededError` 並觸發 `finish()`。
3. 長期考慮引入 `llm-token-guardian` 或類似 Python 庫做 pre-call cost estimation + session budget tracking。

### 參考實作

- token-fence（per-session token budget enforcement middleware）：https://github.com/SiluPanda/token-fence
- llm-token-guardian（Python pre-call cost estimation + session budget）：https://github.com/iamsaugatpandey/llm-token-guardian
- AgentGateway budget limits 模式（per-session/per-user/global）：https://agentgateway.dev/docs/kubernetes/main/llm/budget-limits/
- SupraWall 三層成本護欄（per-call / per-session / per-day）：https://www.supra-wall.com/learn/how-to-set-token-limits-ai-agents

### 治理判定

**APPROVE** — layered config 架構已就位，加一個欄位 + 呼叫前檢查即可。風險 = 中高（無限成本），修復難度 = 低。

---

## 建議 4：knowledge YAML 寫入加入 atomic write + snapshot 審計

### 問題

`save_runtime()` 直接 `yaml.dump()` 覆寫整個 knowledge.yaml——無 diff 審計、無 schema validation、無「壞寫入」回滾。Vision 誤判寫入錯誤 transition 後，唯一防線是 Git history。平行 session 寫入同一檔案有 last-write-wins race condition。

### 建議

1. **Atomic write**：寫入 temp file 後 `os.replace()` 確保不會半寫損毀。
2. **Session snapshot**：`GameSession.start()` 時複製 knowledge.yaml 到 `runs/<game>/<timestamp>/knowledge_snapshot.yaml`，可做 diff 還原。
3. **File lock**：使用 `portalocker` 或 `filelock` 套件，在 `save_runtime()` 前取得排他鎖（timeout 10s）。
4. **Schema validation**：寫入前用 jsonschema/pydantic 驗證結構完整性。

### 參考實作

- cloudmesh/yamldb（atomic writes + portalocker concurrency locking for YAML）：https://github.com/cloudmesh/yamldb
- yacman（YAML config manager with file locking + write_lock context manager）：http://pep.databio.org/yacman/code/python-api/
- ConcurrentFileStore 模式（portalocker + atomic temp file + thread lock registry）：https://github.com/muellerberndt/hound/blob/c2989018/analysis/concurrent_knowledge.py
- Atomic YAML writer with PID lockfile pattern：https://gist.github.com/robertoberto/2c36dd863dd753d5d61f738e7f81ae5e

### 治理判定

**APPROVE AS PILOT** — 短期 knowledge 檔案很小（race 概率低），但架構上應及早補上。先實作 atomic write + snapshot，lock 待多 session 平行化時再加。

---

## 建議 5：執行入口加入 PID lock 防重複 + 標準化命名

### 問題

`qa_interactive.py` 和 `start_session.py` 無 duplicate protection——重複觸發建立多個平行 session，且 `save_runtime()` 有 race condition。腳本命名未遵循任何治理標準（環境-系統-流程-動作-版本）。

### 建議

1. **PID lock**：`GameSession.start()` 時寫入 `runs/<game>/.lock`（含 PID + timestamp），`finish()` 時刪除。啟動時檢查 lock 是否存在且 process 仍活著（`psutil.pid_exists`）。

```python
from filelock import FileLock, Timeout

lock_path = self.run_base / ".session.lock"
try:
    self._file_lock = FileLock(lock_path, timeout=0)
    self._file_lock.acquire()
except Timeout:
    raise RuntimeError(f"Another session is already running for {self.game_name}")
```

2. **命名治理**：腳本重新命名為包含意圖的格式：
   - `qa_interactive.py` → `run-qa-explore-interactive-v1.py`
   - `start_session.py` → `run-session-manual-v1.py`
3. **Input validation**：入口腳本加 `GAME_URL` / `VISION_GATEWAY_URL` 存在性檢查，缺失則 early exit（exit code 4 = usage error）。

### 參考實作

- filelock 套件（跨平台 file-based lock）：https://py-filelock.readthedocs.io/en/latest/
- pytest-xdist FileLock 防重複執行模式：https://pytest-xdist.readthedocs.io/en/stable/how-to.html
- pytest-once（file lock + marker file 保證 exactly-once）：https://pypi.org/project/pytest-once/
- tg-note KB Synchronization（async + file lock 雙層）：https://artyomzemlyak.github.io/tg-note/architecture/kb-synchronization/

### 治理判定

**APPROVE** — `filelock` 是成熟套件（零外部依賴），加入成本極低。命名重構可漸進執行。

---

## 總結優先級

| # | 建議 | 治理風險 | 修復難度 | 判定 |
|---|------|---------|---------|------|
| 2 | exit code + CI 接軌 | 高 | 極低 | APPROVE（最高優先） |
| 3 | Vision 成本 hard cap | 高 | 低 | APPROVE |
| 5 | PID lock 防重複 | 中 | 低 | APPROVE |
| 4 | knowledge atomic write | 中 | 低 | APPROVE AS PILOT |
| 1 | 排程失敗告警 | 中 | 低 | APPROVE AS PILOT |

所有建議皆為**非侵入式增補**，不需修改核心架構，可逐項獨立實作。
