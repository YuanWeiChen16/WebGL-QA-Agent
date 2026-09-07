# Incident Response Commander — 架構建議

> 審查角色：Engineering Incident Response Commander
> 審查對象：WebGL QA Agent 整體架構（DESIGN.md / ARCHITECTURE_DECISIONS.md）
> 日期：2026-07-16

---

## 1. Vision Gateway 單點故障：導入 Circuit Breaker + Graceful Degradation

**問題**：`vision.py` 依賴單一 `VISION_GATEWAY_URL`，無任何 circuit breaker 或 fallback。若 gateway 掛掉或回應逾時，整個 agent loop 會無限等待或連續重試，耗盡錯誤預算並產生無意義的 session 資料。從事件回應角度，這是一個未被保護的 SEV1 級單點故障。

**建議**：
- 在 `vision.py` 外層包裝 circuit breaker（Python 生態推薦 `pybreaker` 或 async 用 `aiobreaker`）：連續 3 次失敗 → 斷路 60 秒 → half-open 試探。
- 斷路期間 agent loop 降級為「純確定性模式」：只跑 `detector.py` 崩潰偵測 + `perceiver.py` pixel diff，不呼叫 Vision，避免整個 session 浪費。
- 記錄 circuit state 變化到 session log，事後 post-mortem 可追蹤 gateway 健康狀況。

**參考**：
- https://oneuptime.com/blog/post/2026-01-23-python-circuit-breakers/view — Python circuit breaker 實作完整指南（pybreaker 用法、fallback 模式、FastAPI 整合）
- https://codingeasypeasy.com/blog/implement-circuit-breakers-for-api-calls-in-fastapi-with-aiobreaker/ — aiobreaker async circuit breaker，適合本專案的 async 架構

---

## 2. Session 中斷恢復（Crash Recovery）：Checkpoint + Partial Report

**問題**：`GameSession` 在 `start()` 之後若意外終止（OOM、Playwright crash、OS kill），`finish()` 未被呼叫，當次 session 的所有操作紀錄、anomaly 偵測結果、oracle 判定全部遺失。長時間 nightly run 在第 3 小時 crash 等於前 3 小時白跑。

**建議**：
- 每 N 步（建議 10 步或每 30 秒）做一次 checkpoint：將 `session_data`（timeline、anomalies、game_states）以 atomic write 寫入 `runs/<game>/<timestamp>/checkpoint.json`。
- `GameSession.__init__` 檢查是否存在未完成的 checkpoint，提供 `resume=True` 選項從中斷點繼續。
- 即使 `finish()` 未被呼叫，checkpoint 資料也足以讓 `reporter.py` 產出 partial report（標記 "incomplete session"）。
- 使用 `atexit` + signal handler 在收到 SIGTERM/SIGINT 時嘗試做最後一次 checkpoint + 關閉 browser。

**參考**：
- https://github.com/deepcausa/safeatomic — `safeatomic` 套件提供 atomic YAML/JSON write + crash durability + cooperative lock，完美適用 checkpoint 寫入
- https://gist.github.com/therightstuff/cbdcbef4010c20acc70d2175a91a321f — 最小化 atomic write 範例（temp file + fsync + os.replace）

---

## 3. 長時間運行資源洩漏：Context Recycling + Self-Health Check

**問題**：nightly cron 跑 24 小時，Playwright browser context 的記憶體會持續成長（DOM 節點殘留、event listener 累積、console log buffer 無上限）。`detector.py` 監控的是遊戲的記憶體成長，但 agent 自身的資源洩漏無人看管。

**建議**：
- 實作 **Context Recycling**：每 N 個 action（建議 100）或每 30 分鐘，關閉當前 browser context 並重新建立，釋放累積的 DOM/listener/cache 記憶體。
- `browser.py` 的 console log buffer 加上環形緩衝（ring buffer，上限 5000 條），超出則丟棄最舊的。
- 加入 agent self-health check：每 5 分鐘檢查 Python process RSS，若超過閾值（如 2GB）→ 寫 checkpoint → 重啟 session（或至少告警）。
- 截圖暫存改為 streaming 寫入磁碟 + 定期清理超過 1 小時的暫存檔。

**參考**：
- https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions — Playwright 長時間運行記憶體管理最佳實踐（context recycling pattern、memory monitoring、browser pool）
- https://www.firecrawl.dev/glossary/web-scraping-apis/prevent-memory-leaks-web-scrapers — 長時間 headless browser 記憶體洩漏成因表與修復策略
- https://qaskills.sh/blog/playwright-await-using-automatic-cleanup-guide — 資源自動清理模式（await using / AsyncDisposableStack），防止 zombie process

---

## 4. Knowledge 寫入衝突與資料完整性：Atomic Write + File Locking

**問題**：`knowledge_base.py` 寫入 `knowledge.yaml` 時若中途 crash（電源中斷、OOM kill），YAML 可能留在半寫狀態（truncated/corrupt），下次啟動時 `yaml.safe_load` 會拋 parse error，整個知識庫不可用。若多個 session 同時跑不同遊戲倒是各自目錄不衝突，但同遊戲多實例（如平行壓測）則會互相覆蓋。

**建議**：
- 所有 knowledge YAML 寫入改用 atomic write 模式：先寫 temp file → fsync → `os.replace` 到目標路徑。推薦直接用 `safeatomic` 套件的 `atomic_yaml_dump`。
- 加上 cooperative file lock（`fcntl.flock` on Linux / `msvcrt.locking` on Windows），防止同遊戲多實例同時寫入。
- 每次寫入前保留上一版本為 `.bak`（或 `.knowledge.yaml.bak`），corrupt 時可自動回退。
- 啟動時做 YAML integrity check：若 parse 失敗，嘗試載入 `.bak`，並記錄 recovery event 到 session log。

**參考**：
- https://pypi.org/project/safeatomic/2.0.3/ — safeatomic v2.0.3：atomic write + cooperative lock + checksum sidecar，四大保證（AtomicVisibility / CrashDurability / WriterExclusion / IntegrityDetection）
- https://github.com/deepcausa/safeatomic — 完整文檔含 TLA+ 正式驗證模型、safety policy、doctor 診斷工具

---

## 5. 即時告警與可觀測性：Webhook 通知 + Structured Metrics

**問題**：目前所有偵測結果（anomalies、oracle violations、WebGL context lost）只寫進 report HTML/JSON，是事後靜態產物。nightly run 凌晨 2 點發現遊戲完全黑屏（SEV1），要等到隔天早上人工看報告才知道。無即時告警 = 無法做 incident response。

**建議**：
- 在 `detector.py` / `oracle.py` 偵測到 high severity anomaly 時，即時發送 webhook 通知（Slack Incoming Webhook / PagerDuty Events API v2 / Discord webhook）。可在 `config/default.yaml` 新增：
  ```yaml
  alerting:
    enabled: true
    webhook_url: "${ALERT_WEBHOOK_URL}"
    severity_threshold: high  # 只有 high/critical 才即時通知
    cooldown_seconds: 300     # 同類告警 5 分鐘內不重複
  ```
- 每個 session 結束時推送 structured metrics（JSON）到可選的 metrics endpoint：run duration、anomaly count by severity、oracle violation count、Vision call count/latency/error rate、memory peak。
- 長期目標：接入 Prometheus（push gateway）或 Datadog，建立 dashboard 追蹤跨 session 的趨勢（MTTD、anomaly rate、Vision reliability）。

**參考**：
- https://developer.pagerduty.com/docs/events-api-v2/overview/ — PagerDuty Events API v2，適合自動化系統發送 SEV1/SEV2 告警
- https://api.slack.com/messaging/webhooks — Slack Incoming Webhooks，最低成本的即時通知管道

---

## 總結優先級

| # | 建議 | 嚴重度 | 實作難度 | 建議優先序 |
|---|------|--------|----------|-----------|
| 1 | Circuit Breaker for Vision Gateway | SEV2 | 中 | P1 |
| 2 | Crash Recovery / Checkpoint | SEV2 | 中 | P1 |
| 4 | Atomic Write for Knowledge | SEV3 | 低 | P2 |
| 3 | Long-run Resource Management | SEV3 | 中 | P2 |
| 5 | Real-time Alerting | SEV3 | 低 | P2 |

建議 #1 和 #2 為最高優先：它們直接影響 nightly run 的可靠性與可恢復性，是從「跑完卻不知道壞了」到「壞了能自癒、能即時知道」的關鍵差距。
