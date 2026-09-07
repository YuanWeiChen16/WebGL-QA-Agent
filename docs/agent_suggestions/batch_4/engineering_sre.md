# SRE 工程建議 — Batch 4

> 審查角色：Site Reliability Engineer
> 審查日期：2026-07-16
> 審查範圍：DESIGN.md、ARCHITECTURE_DECISIONS.md、perf-defender 效能驗證回覆

---

## SRE-1 🔴 Vision API 加入 Circuit Breaker + 改用 asyncio.sleep

**現況問題：**
- `vision.py` 有 retry/backoff（`max_retries=3`、`backoff_base=2.0`），但**無 circuit breaker** — 連續失敗不會 trip，每次呼叫都重新嘗試 3 次，gateway 持續不健康時每個 session step 被迫等 3-4 分鐘才 fail。
- Backoff 使用阻塞式 `time.sleep()`，在 async context 中**凍結整個 event loop**，不只當前 session hang，同 process 所有 coroutine 都停擺。

**建議：**
1. 引入 `aiobreaker`（asyncio 原生 circuit breaker），設定 `fail_max=5, reset_timeout=60s`，gateway 連續 5 次失敗後 trip，後續呼叫 fast-fail 不浪費時間。
2. 將所有 `time.sleep()` 替換為 `await asyncio.sleep()`，讓 event loop 在等待期間仍可處理其他任務。
3. 加入 circuit breaker 狀態 metric（open/half-open/closed），供 observability 使用。

**SLO 影響：** 若定義「每步驟 < 10s 完成 observe+act」為 latency SLI，無 circuit breaker 時 gateway 故障會將 p99 從正常 ~5s 推高至 180-240s，burn rate 瞬間爆表。

**參考資料：**
- aiobreaker — asyncio circuit breaker 實作：https://pypi.org/project/aiobreaker/
- Ruff ASYNC251 — blocking sleep in async function 檢測規則：https://docs.astral.sh/ruff/rules/blocking-sleep-in-async-function/
- Python asyncio.sleep 官方文件：https://docs.python.org/3/library/asyncio-task.html#sleeping
- circuit-breaker-box（含 tenacity 整合）：https://github.com/community-of-python/circuit-breaker-box

---

## SRE-2 🔴 Playwright Browser 生命週期防護 — atexit + signal + context manager

**現況問題：**
- `browser.close()` 只在 `session.finish()` 呼叫，**無 atexit handler、無 signal handler、無 try/finally、無 context manager**。
- Python process 被 OOM killer、SIGTERM、或未 catch 的 exception 中斷時，Chromium child process **100% 孤兒化**，佔 200-500MB RSS + GPU memory。
- CI/nightly 環境反覆 leak 會快速耗盡資源。

**建議：**
1. `GameSession` 實作 `__aenter__` / `__aexit__` async context manager，`__aexit__` 中確保 `browser.close()` 被呼叫。
2. 在 `start()` 中註冊 `atexit.register(self._sync_cleanup)` 與 `signal.signal(SIGTERM, handler)`，確保非正常退出也能清理。
3. 所有公開腳本（`qa_interactive.py`、`start_session.py`）改用 `async with GameSession(...) as session:` pattern。
4. 考慮 Playwright `handle_sighup=True`（預設已啟用）確認其作用，並加入 health check：若 browser process 不存在則 skip close。

**參考資料：**
- Python atexit 模組（正常退出時自動執行清理）：https://docs.python.org/3/library/atexit.html
- Playwright Python Browser.close() 文件：https://playwright.dev/python/docs/api/class-browser#browser-close
- Playwright BrowserType launch — `handle_sighup` 參數：https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch
- playwright-python issue #2254 — context manager 討論：https://github.com/microsoft/playwright-python/issues/2254
- contextlib.closing 用於非 CM 物件：https://docs.python.org/3/library/contextlib.html#contextlib.closing

---

## SRE-3 🟡 runs/ 目錄加入 Retention Policy

**現況問題：**
- `session_manager.py` 只有 `create_run()` 邏輯，**零清理機制**。
- 每次 run 約 5MB（screenshots + HTML + JSON），nightly 每天 10 次 = 50MB/day，一年 ~18GB。
- CI 環境更快爆（容器 ephemeral storage 常限 10-20GB）。

**建議：**
1. 在 `config/default.yaml` 加入 retention 設定：
   ```yaml
   retention:
     max_runs: 50          # 每個 game 最多保留 50 次 run
     max_age_days: 30      # 超過 30 天自動刪除
     max_total_size_mb: 2048  # 總量上限
   ```
2. 在 `session_manager.py` 加入 `cleanup_old_runs()` 函式，每次 `create_run()` 後觸發，以 LRU 策略刪除超齡/超量 run。
3. 保留 latest symlink 或 `runs/<game>/latest → <timestamp>` 讓腳本永遠能找到最新 run。
4. 長期：考慮 S3/GCS 歸檔，local 只保留 N 份。

**SLO 影響：** Disk exhaustion 會導致 `session.finish()` 寫報告失敗 → 整個 session 結果丟失，屬 availability SLI 事件。

**參考資料：**
- Python pathlib + shutil 刪除舊目錄的慣例做法：https://docs.python.org/3/library/shutil.html#shutil.rmtree
- logrotate 設計理念（retention = count + age + size 三軸）：https://man7.org/linux/man-pages/man8/logrotate.8.html
- GitHub Actions ephemeral storage 限制：https://docs.github.com/en/actions/using-github-hosted-runners/using-github-hosted-runners/about-github-hosted-runners#standard-github-hosted-runners-for-public-repositories

---

## SRE-4 🟡 並行 Session 隔離 — Knowledge File Lock + Vision Client Scoping

**現況問題：**
- `KnowledgeBase` 同 game_name 共享實例，`save_runtime()` 無 file lock，併發寫入會 corrupt YAML。
- `_client` 是 module-level singleton，多 session 共享 rate limit 互相影響。
- `_session` global singleton 讓多 session 在 API 層根本不可能。

**建議：**
1. `save_runtime()` 加入 file lock（`filelock` 套件或 `fcntl.flock`），防止併發寫入 corruption。
2. Vision client 改為 instance-level（注入 `GameSession`），每個 session 可有獨立 rate limit bucket 或至少獨立 circuit breaker 狀態。
3. 移除 `_session` global singleton，改為 registry pattern（`SessionRegistry[game_name]`），支援多 session 共存。
4. Run output 目錄加入 session_id（UUID）而非僅 timestamp，避免同秒碰撞。

**SLO 影響：** Knowledge YAML corruption 是 data integrity 問題，會導致後續所有 session 讀到損壞資料 → 連鎖失敗。

**參考資料：**
- filelock — cross-platform file locking：https://pypi.org/project/filelock/
- Python fcntl.flock（Unix file lock）：https://docs.python.org/3/library/fcntl.html#fcntl.flock
- httpx AsyncClient instance management best practices：https://www.python-httpx.org/async/#opening-and-closing-clients

---

## SRE-5 🟡 Session Resource Ceiling + Graceful Degradation

**現況問題：**
- `self.steps: list[dict]` 在整個 session 生命週期只增不減，最後一次性渲染 HTML。1000+ steps 約 10-50MB。
- `_runtime_data` 的 screens/flow_graph 無 eviction，`save_runtime()` 每次重寫整份 YAML，隨時間線性增長。
- 8 小時 nightly session 約 960 張 PNG（192MB disk），knowledge YAML 重寫成本隨 screen 數量增加。

**建議：**
1. 設定 session 資源上限（config 可調）：
   ```yaml
   session:
     max_steps: 2000        # 超過後 graceful finish
     max_duration_hours: 4  # 硬性時間上限
     max_screenshots_mb: 500
   ```
2. Steps 超過上限時觸發 `session.finish()` 而非 OOM crash，確保報告正常產出。
3. Knowledge runtime 加入 LRU eviction — 低 confidence 且超過 N 天未驗證的 screen 可被清出記憶體。
4. Reporter 支援 streaming flush（每 100 steps 寫一次中間報告），避免 crash 時全部資料丟失。

**SLO 影響：** 定義「每個 nightly run 成功產出報告」為 availability SLI，OOM crash 或 disk full 都是 incident。resource ceiling 讓系統 graceful degrade 而非 hard fail。

**參考資料：**
- Python resource 模組（設定 process memory limit）：https://docs.python.org/3/library/resource.html
- Streaming HTML 寫法（避免大量 DOM 一次渲染）：https://developer.mozilla.org/en-US/docs/Web/API/Streams_API
- Google SRE Book — Managing Critical State（graceful degradation）：https://sre.google/sre-book/managing-critical-state/

---

## 總結：風險排序與行動優先級

| 優先級 | 項目 | 風險等級 | 預估工時 |
|--------|------|----------|----------|
| P0 | SRE-2 Browser 孤兒化防護 | 🔴 高 | 2-3h |
| P0 | SRE-1 Circuit breaker + async sleep | 🔴 高 | 3-4h |
| P1 | SRE-4 並行隔離 | 🟡 中高 | 4-6h |
| P1 | SRE-3 Retention policy | 🟡 中 | 2-3h |
| P2 | SRE-5 Resource ceiling | 🟡 中 | 3-4h |

**建議導入順序：** SRE-2 → SRE-1 → SRE-3 → SRE-4 → SRE-5。前兩項為「系統會在 production 中靜默惡化」的隱藏債務，應在 nightly run 上線前解決。
