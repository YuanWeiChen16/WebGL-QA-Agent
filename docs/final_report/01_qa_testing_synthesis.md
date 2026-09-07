# QA 測試領域綜合建議報告

> **綜合來源**：test_automation_engineer.md、batch_1（testing_evidence_collector、testing_performance_benchmarker、testing_reality_checker、testing_test_automation_engineer）、batch_2（testing_api_tester、testing_test_results_analyzer、testing_tool_evaluator、testing_workflow_optimizer）、batch_5（specialized_model_qa）、batch_6（engineering_frontend_developer — QA 相關部分）、batch_7（engineering_minimal_change — QA 相關部分）、batch_4（engineering_code_reviewer — QA 相關部分）、batch_9（testing_accessibility_auditor）
>
> **產出日期**：2026-07-17

---

## 目錄

1. [Oracle 可靠性與精確度量化](#1-oracle-可靠性與精確度量化)
2. [Pass/Fail Verdict 與 CI 整合](#2-passfail-verdict-與-ci-整合)
3. [畫面感知穩定化（screen_id / SSIM / pixel_diff）](#3-畫面感知穩定化screen_id--ssim--pixel_diff)
4. [Vision API 韌性與成本控制](#4-vision-api-韌性與成本控制)
5. [測試框架與自動化基礎設施](#5-測試框架與自動化基礎設施)
6. [效能基線與記憶體管理](#6-效能基線與記憶體管理)
7. [WebGL 特有測試挑戰](#7-webgl-特有測試挑戰)
8. [跨 Session 趨勢分析與工作流程](#8-跨-session-趨勢分析與工作流程)
9. [無障礙測試能力擴展](#9-無障礙測試能力擴展)
10. [程式碼品質與可維護性](#10-程式碼品質與可維護性)

---

## 1. Oracle 可靠性與精確度量化

### 核心問題

Oracle（功能正確性驗證）是本框架最關鍵的判斷引擎，但目前**零量化數據**證明其可靠性。Vision LLM 的 OCR 能力在遊戲場景下存在系統性弱點（藝術字型、動態背景、非 ASCII 字元），而「二次確認」機制對系統性誤讀無效。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | 建立 Vision OCR 精確度基線（50-100 張 ground-truth 標註集，量測 per-field WER/CER/Accuracy） | Evidence Collector、Reality Checker、Model QA |
| **P0** | 量化 reread 機制的實際過濾率，記錄觸發案例中「第二次翻轉為 pass」的比率 | Evidence Collector |
| **P1** | 引入 PaddleOCR 作為 L1 本地數值讀取層，與 Vision LLM 做異源交叉驗證 | Tool Evaluator、Evidence Collector |
| **P1** | 建立 Oracle Feedback Loop：結構化 dismiss 記錄、per-invariant precision 追蹤、自動調整 min_occurrences | Workflow Optimizer |
| **P2** | 導入 Hypothesis property-based testing 對 oracle.py 做邊界探索 | Test Automation Engineer |
| **P2** | Oracle `required_flags` schema 驗證，防止 flags 缺失導致靜默誤判 | Code Reviewer |

### 關鍵參考

- OCRBench v2（LMM OCR 全面評測）：https://arxiv.org/html/2501.00321v2
- video-db/ocr-benchmark（Claude CER 0.3229、WER 0.4663）：https://github.com/video-db/ocr-benchmark
- PaddleOCR（85.6k stars，PP-OCRv6）：https://github.com/PaddlePaddle/PaddleOCR
- StructuredVision（遊戲介面 OCR 多引擎對比）：https://github.com/ammahmoudi/StructuredVision
- Hypothesis property-based testing：https://hypothesis.readthedocs.io/en/latest/stateful.html
- SmartOracle（agentic False Positive Critic）：https://arxiv.org/pdf/2601.15074
- OASIs（迭代式 oracle 改進，提升 48.6% 偵測率）：https://doi.org/10.1145/3213846.3229503

---

## 2. Pass/Fail Verdict 與 CI 整合

### 核心問題

框架目前**無法告訴你測試通過還是失敗**。無 exit code、無 verdict、run status 停在 "running"。無法 gate deployment，與「偶爾呼叫 LLM 的截圖腳本」無本質區別。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | 定義三級 verdict：PASS(0) / FAIL(1) / UNSTABLE(2)，`finish()` 回傳明確判定 + exit code | Reality Checker、Test Automation Engineer、Evidence Collector、Workflow Optimizer |
| **P0** | 立即實作 L1 崩潰偵測 Smoke Test CI（零 Vision 呼叫、零成本，detector + perceiver 確定性偵測） | Workflow Optimizer |
| **P1** | 建立 Flake Root-Cause Attribution Pipeline：每個 anomaly 附加 failure_mode_tag（ocr_misread / click_miss / timing_race / real_bug） | Test Automation Engineer |
| **P1** | 分層 CI 管線：PR Gate（unit tests + lint < 2min）→ Integration（Playwright mock < 10min）→ Nightly（真實 E2E + Vision） | Test Automation Engineer（頂層）|
| **P2** | 建立確定性回歸層（Zero-LLM Regression Gate）：scripted setup → bounded exploration → scripted checkpoint | Test Automation Engineer |
| **P2** | 端對端效果驗證：seeded-fault 驗證（植入 5-10 個已知 bug，量測 precision/recall） | Reality Checker |

### 關鍵參考

- iXie Gaming — AI Game Testing That Teams Trust：https://www.ixiegaming.com/blog/ai-game-testing-that-teams-actually-trust-how-to-design-signal-not-flake/
- Eidos-Montréal — Automated Game Testing（Initialize-Execute-Validate）：https://www.eidosmontreal.com/news/automated-game-testing/
- Bugnet — Setting Up Automated Regression Tests：https://bugnet.io/blog/setting-up-automated-regression-tests-for-game-builds
- GLIB（NetEase，53 bugs found，precision 100%）：https://dl.acm.org/doi/fullHtml/10.1145/3551349.3556913
- ButterStack — Game Dev Testing QA Pipeline：https://www.butterstack.com/blog/game-dev-testing-qa-pipeline/

---

## 3. 畫面感知穩定化（screen_id / SSIM / pixel_diff）

### 核心問題

三個感知機制存在系統性缺陷：
1. **screen_id**：全圖 SSIM 對動態畫面無判別力 → 同一邏輯畫面被分裂為多個 ID → 知識累積級聯失效
2. **pixel_diff**：動態場景永遠非零 → noop 偵測形同虛設
3. **confidence**：只升不降、無統計意義（3 次全成功 = 100 次 95% 成功）

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | screen_id 改用 perceptual hash（pHash/dHash）+ UI 錨點指紋，遮罩動態區域 | Tool Evaluator、Evidence Collector、Model QA、Reality Checker |
| **P0** | 引入 ROI 遮罩：將動態區（魚群）與 UI 靜態區（分數、按鈕）分開計算 diff | Evidence Collector、Minimal Change |
| **P1** | pixel_diff 加入 per-screen adaptive baseline（calibration phase 採集 idle 狀態分佈） | Code Reviewer、Model QA |
| **P1** | Per-game 異常偵測閾值自動校準（前 N 步作為 baseline，動態計算 threshold） | Model QA |
| **P1** | Confidence 改用 Beta-Bernoulli 後驗模型，加入時間衰減與雙向機制 | Model QA、Reality Checker |
| **P2** | 點擊後斷言增加語意層 Effect Signal（game_state diff + pixel_diff 雙訊號） | Model QA |
| **P2** | Oracle streak 加入 action-distance decay（TTL），避免 stale streak | Code Reviewer |

### 關鍵參考

- imagehash 套件（pHash/dHash/wHash）：https://github.com/JohannesBuchner/imagehash
- VideoGameBench（perceptual hash 做遊戲進度匹配）：https://arxiv.org/html/2505.18134
- UIHASH（grid-based UI 相似度 F1=0.984）：https://www.usenix.org/system/files/usenixsecurity24_slides-li-jiawei.pdf
- Applitools Regions Only 精準視覺驗證：https://applitools.com/blog/mastering-targeted-ui-validation-with-regions-only/
- ASE 2022（Canvas 遊戲：snapshot 44.6% vs isolated object 100%）：https://asgaard.ece.ualberta.ca/papers/Conference/ASE_2022_Macklon_Automatically_Detecting_Visual_Bugs_In_HTML5_Canvas_Games.pdf
- BayesTruth（Beta-Bernoulli 信任評分）：https://github.com/davccavalcante/bayestruth
- Gameplay-Anomaly-Detection-Agent（ResNet50 + KNN Memory Bank）：https://github.com/attarmau/Gameplay-Anomaly-Detection-Agent

---

## 4. Vision API 韌性與成本控制

### 核心問題

Vision 呼叫無 circuit breaker、無 per-session cost cap、無 rate limiter。Gateway 故障時每次呼叫燒 ~42 秒才放棄；高動態場景可能無限制呼叫 Vision；無降級模式。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | 引入 Circuit Breaker（連續 N 次失敗後開路，降級為純確定性偵測） | API Tester、Performance Benchmarker |
| **P0** | Per-session cost budget + rate limiter（requests/min + cost_cents/hour 雙維度限制） | API Tester、Performance Benchmarker |
| **P1** | 分層感知策略：L0 pixel_diff → L1 PaddleOCR（<50ms, 零成本）→ L2 Vision LLM（僅升級時呼叫） | Tool Evaluator |
| **P1** | Screenshot pipeline 整體超時（asyncio.wait_for 5s），加入 metrics counter 追蹤 fallback/timeout 頻率 | API Tester |
| **P2** | Vision 呼叫加入 slow-call detection + cost velocity 監控 | Performance Benchmarker |

### 關鍵參考

- interlock-cb（零依賴 Python circuit breaker）：https://github.com/bagowix/interlock
- token-throttle（多資源 LLM rate limiting）：https://github.com/Elijas/token-throttle
- TrueFoundry — Rate Limiting AI Agents：https://www.truefoundry.com/blog/rate-limiting-ai-agents-preventing-llm-api-exhaustion
- Balacode — Circuit Breakers for LLMs：https://balacode.io/blog/circuit-breakers-llms-architecture-fallback
- Backpressure Patterns for LLM Pipelines：https://tianpan.co/blog/2026-04-15-backpressure-llm-pipelines

---

## 5. 測試框架與自動化基礎設施

### 核心問題

現有 4 個測試檔案（~60 tests）覆蓋有限，`detector.py`（201 行）零測試覆蓋。無 coverage 報告、無 CI、無 property-based testing。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | 建立 Coverage 報告（fail_under=75），優先補齊 detector.py 測試 | Test Automation Engineer |
| **P1** | 導入 pytest-xdist 平行化（-n auto --dist loadscope） | Test Automation Engineer |
| **P1** | Knowledge Base 測試用 inline fixture（tmp_path）隔離，保留 1-2 個 filesystem smoke test | Test Automation Engineer |
| **P1** | Playwright E2E 雙層 retry（auto-wait + 選擇性 TimeoutError retry），WebGL context ready fixture | Test Automation Engineer |
| **P2** | Action-sequence fuzzer 模組：Hypothesis RuleBasedStateMachine + flow_graph 狀態機探索 | Tool Evaluator |
| **P2** | Perceiver 浮點斷言改用 pytest.approx 防止跨平台 flakiness | Test Automation Engineer |

### 關鍵參考

- pytest-xdist parallel testing：https://pytest-xdist.readthedocs.io/en/latest/distribution.html
- pytest-cov + xdist 整合：https://pytest-cov.readthedocs.io/en/stable/xdist.html
- Hypothesis stateful testing：https://hypothesis.readthedocs.io/en/latest/stateful.html
- Playwright Best Practices：https://playwright.dev/docs/best-practices
- Semaphore — Property-based testing with Hypothesis：https://semaphore.io/blog/property-based-testing-python-hypothesis-pytest
- pytest-benchmark：https://pytest-benchmark.readthedocs.io/en/stable/

---

## 6. 效能基線與記憶體管理

### 核心問題

「近零成本」偵測層宣稱無量化支撐。SSIM 在 1080p 下用 scikit-image 耗時 ~580ms（遠超操作間隔）。Playwright 長時間 session 有已知記憶體洩漏。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P1** | 建立 perceiver/detector 效能基線（pytest-benchmark），設定 20% 退化門檻 | Performance Benchmarker |
| **P1** | 評估 SSIM 替換為 Fast-SSIM（1080p 2.3ms vs scikit-image 580ms）或降採樣後比對 | Performance Benchmarker |
| **P1** | Playwright context recycling（每 200 動作或 10 分鐘回收，storageState 保存/恢復） | Performance Benchmarker |
| **P2** | 並行 session：Browser Pool（共享 Chromium process + context 隔離）+ Vision request queue | API Tester、Performance Benchmarker |
| **P2** | Knowledge YAML I/O 改用 asyncio.to_thread + dirty flag 批次寫入 | API Tester |
| **P2** | 並行知識庫隔離：ephemeral per-run + canonical merge 雙層模型 | Test Automation Engineer |

### 關鍵參考

- Fast-SSIM（1080p 2.3ms，251x 加速）：https://pypi.org/project/Fast-SSIM/
- Playwright Issue #15400（長 session 記憶體洩漏）：https://github.com/microsoft/playwright/issues/15400
- WebScraping.AI — Memory Management for Playwright：https://webscraping.ai/faq/playwright/what-are-the-memory-management-best-practices-when-running-long-playwright-sessions
- Playwright Parallelism：https://playwright.dev/docs/test-parallel
- Browser Pool Patterns：https://scrapingcentral.com/learn/dynamic-web/browser-pool-patterns

---

## 7. WebGL 特有測試挑戰

### 核心問題

WebGL canvas 對傳統測試工具是黑箱：Playwright 無法 locate canvas 內元素、截圖可能擷取到 GPU 中間狀態、context loss 被過度報告、跨瀏覽器渲染差異顯著、座標為絕對像素無法跨解析度。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P1** | WebGL context loss 偵測改為區分「正常恢復」與「遊戲崩潰」（注入事件監聽 + 超時機制） | Frontend Developer |
| **P1** | 截圖前插入雙重 rAF 同步，確保擷取完整渲染幀（消除 tearing） | Frontend Developer |
| **P1** | HiDPI 座標正規化：明確宣告 CSS pixel 座標系統、截圖用 `scale: 'css'` | Frontend Developer |
| **P1** | Canvas resize 動態更新座標基準（ResizeObserver + 相對比例座標） | Frontend Developer |
| **P2** | 引入 canvas-grid 或 template matching 作為 Playwright 對 canvas 的定位補強 | Tool Evaluator |
| **P2** | CI 環境使用 SwiftShader 軟體渲染確保跨環境一致性 | Tool Evaluator |
| **P2** | 跨瀏覽器 SSIM 比對需記錄 WebGL renderer info，套用不同閾值 | Frontend Developer |

### 關鍵參考

- Khronos — Handling Context Lost：https://wikis.khronos.org/webgl/HandlingContextLost
- WebGL Fundamentals — Resizing Canvas：https://webglfundamentals.org/webgl/lessons/webgl-resizing-the-canvas.html
- canvas-grid + Playwright 測試：https://dev.to/fonzi/testing-html5-canvas-with-canvasgrid-and-playwright-5h4c
- WebGL + Playwright E2E（SwiftShader + Docker）：https://barthpaleologue.github.io/Blog/posts/webgl-webgpu-playwright-setup/
- Playwright screenshot timing issue：https://github.com/microsoft/playwright/issues/18934
- WebGL fingerprinting 跨瀏覽器差異：https://blog.crawlex.net/blog/webgl-fingerprinting/

---

## 8. 跨 Session 趨勢分析與工作流程

### 核心問題

每次 session 獨立產出報告，缺乏跨 session 的 bug 重現率追蹤、anomaly 頻率趨勢、覆蓋率指標、階段轉換判定。測試結果分析仍沿用不適用的傳統 CI 指標。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P1** | 實作跨 session 趨勢聚合（bug_reproduction_rates、anomaly_frequency、new/resolved bugs、stability_score） | Workflow Optimizer |
| **P1** | 定義分層覆蓋率指標：screen_visit_rate（explore）、flow_edge_coverage（validate）、invariant_trigger_rate（test） | Workflow Optimizer |
| **P1** | 重新定義 Test Results Schema 為 Session Results Schema（對齊專案實際資料結構） | Test Results Analyzer |
| **P2** | 建立階段轉換的半自動提議機制（Phase Readiness Advisor） | Workflow Optimizer |
| **P2** | 引入 Session-Based Test Management (SBTM) 指標作為分析框架 | Test Results Analyzer |
| **P2** | 整合 Allure Report 取代自建 reporter.py（截圖附件、趨勢圖、CI 整合） | Tool Evaluator |
| **P2** | 報告受眾從 executive 改為 operator 導向（每日 Operator Summary + 週/月 Periodic Report） | Test Results Analyzer |
| **P3** | 分層成熟度分析（Level 0-3），根據累積 session 數量自動選擇分析層級 | Test Results Analyzer |

### 關鍵參考

- Fern Platform（Universal Test Aggregation + Flaky Test Detection）：https://github.com/guidewire-oss/fern-platform
- Flakiness.io：https://flakiness.io/
- CTRF（Common Test Report Format）：https://github.com/ctrf-io/ctrf/blob/main/spec/ctrf.md
- Allure Report + pytest：https://allurereport.org/docs/pytest/
- SBTM 完整指標體系：https://yrkan.com/blog/session-based-test-management/
- DreamUp QA Agent（類似 Vision-based 遊戲測試）：https://github.com/karinje/dreamup
- Piwi Dashboard（persistent test intelligence）：https://github.com/PhenX/piwi-dashboard

---

## 9. 無障礙測試能力擴展

### 核心問題

本專案有兩個無障礙維度需關注：(1) 工具本身的無障礙性（報告、CLI），(2) 偵測受測遊戲的無障礙問題（閃爍、鍵盤支援、色彩對比）。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P1** | 新增光敏性癲癇風險偵測模組（WCAG 2.3.1），整合 EA IRIS 開源引擎 | Accessibility Auditor |
| **P2** | HTML 報告符合 WCAG 2.2 AA（heading hierarchy、ARIA landmarks、img alt、鍵盤導航） | Accessibility Auditor |
| **P2** | Vision LLM 增加色彩無障礙分析 prompt（僅靠顏色傳達資訊、對比度不足） | Accessibility Auditor |
| **P3** | 偵測受測遊戲 canvas 是否提供 shadow DOM / ARIA 代理層 + 鍵盤回應 | Accessibility Auditor |
| **P3** | CLI 輸出支援 NO_COLOR 環境變數、非 TTY 停用動畫、結構化錯誤訊息 | Accessibility Auditor |

### 關鍵參考

- EA IRIS 光敏性癲癇分析（開源）：https://github.com/electronicarts/IRIS
- EPI-LENS 即時閃爍分析：https://github.com/Pi-0r-Tau/EPI-LENS
- WCAG 2.3.1 Three Flashes：https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold
- axe-html-reporter：https://www.npmjs.com/package/axe-html-reporter
- NO_COLOR 標準：https://no-color.org/
- Quorum Language — Accessible WebGL Canvas：https://quorumlanguage.com/tutorials/accessibility/accessibleGraphicsWebGL.html

---

## 10. 程式碼品質與可維護性

### 核心問題

存在影響測試可靠性的程式碼問題：bare except 靜默吞掉 reread 失敗、global singleton 阻礙並行與測試、convenience functions 無 deprecation 路徑。

### 統整建議

| 優先級 | 建議項目 | 來源 |
|--------|----------|------|
| **P0** | 修復 `check_invariants` 的 bare `except Exception: pass` — 加入 logging + `reread_failed` 回傳欄位 | Code Reviewer |
| **P1** | 移除 global mutable singleton（`_session`），改用 async context manager 模式 | Code Reviewer |
| **P1** | 強化故障可調試性：每個 anomaly 產 self-contained repro package（before/after.png、vision_response.json、oracle_trace.json） | Test Automation Engineer |
| **P2** | Convenience functions 加 DeprecationWarning 引導遷移 | Code Reviewer |
| **P2** | 文件整理：Hermes 整合段落隔離為 roadmap、四份文件考慮合併降低維護成本 | Minimal Change |

### 關鍵參考

- PEP 760（No More Bare Excepts）：https://peps.python.org/pep-0760/
- Python contextlib asynccontextmanager：https://docs.python.org/3/library/contextlib.html
- iXie Gaming — Hydrated State Replays（repro package gold standard）：https://www.ixiegaming.com/blog/ai-game-testing-that-teams-actually-trust-how-to-design-signal-not-flake/
- Playwright — Every failure debuggable from artifacts：https://playwright.dev/docs/best-practices
- Martin Fowler: Yagni：https://martinfowler.com/bliki/Yagni.html

---

## 全局優先級總覽

### P0 — 立即處理（系統核心可信度）

| # | 項目 | 主題 |
|---|------|------|
| 1 | 定義 Pass/Fail Verdict + exit code | CI 整合 |
| 2 | 建立 L1 崩潰偵測 Smoke Test CI | CI 整合 |
| 3 | 建立 Vision OCR 精確度基線 | Oracle 可靠性 |
| 4 | screen_id 改用 perceptual hash + UI 錨點 | 畫面感知 |
| 5 | Vision API Circuit Breaker + Cost Budget | 韌性 |
| 6 | 修復 bare except 靜默吞掉 reread 失敗 | 程式碼品質 |
| 7 | 引入 ROI 遮罩分離動態區域 | 畫面感知 |

### P1 — 短期改善（1-4 週）

| # | 項目 | 主題 |
|---|------|------|
| 8 | Flake Attribution Pipeline | CI 整合 |
| 9 | 分層 CI 管線 | 自動化基礎設施 |
| 10 | PaddleOCR L1 本地數值讀取 | Oracle / 成本 |
| 11 | Per-screen adaptive pixel_diff baseline | 畫面感知 |
| 12 | Beta-Bernoulli confidence 模型 | 知識累積 |
| 13 | WebGL context loss 區分恢復/崩潰 | WebGL |
| 14 | SSIM 效能基線 + Fast-SSIM 評估 | 效能 |
| 15 | Playwright context recycling | 效能 |
| 16 | 跨 session 趨勢聚合 | 工作流程 |
| 17 | Coverage 報告 + detector.py 補測試 | 測試基礎設施 |
| 18 | Global singleton → async context manager | 程式碼品質 |
| 19 | 截圖 rAF 同步 + HiDPI 座標正規化 | WebGL |
| 20 | 光敏性癲癇風險偵測模組 | 無障礙 |

### P2 — 中期建設（1-3 月）

| # | 項目 | 主題 |
|---|------|------|
| 21 | 確定性回歸層 + seeded-fault 驗證 | CI 整合 |
| 22 | Action-sequence fuzzer（Hypothesis RuleBasedStateMachine） | 測試基礎設施 |
| 23 | Per-game 閾值自動校準 | 畫面感知 |
| 24 | 語意層 Effect Signal（game_state diff） | 畫面感知 |
| 25 | Browser Pool + 並行知識庫隔離 | 效能 / 擴展 |
| 26 | Allure Report 整合 | 報告 |
| 27 | Oracle Feedback Loop | Oracle |
| 28 | Repro Package（self-contained debug artifacts） | 可調試性 |
| 29 | Canvas resize 動態座標 + canvas-grid | WebGL |
| 30 | HTML 報告 WCAG 2.2 AA | 無障礙 |

### P3 — 長期願景

| # | 項目 | 主題 |
|---|------|------|
| 31 | 分層成熟度分析模型 | 工作流程 |
| 32 | Canvas 無障礙偵測（shadow DOM / ARIA） | 無障礙 |
| 33 | 跨瀏覽器渲染差異處理 | WebGL |

---

## 跨主題共識觀察

以下觀點被**三個以上獨立來源**同時強調，代表高度共識：

1. **「衡量自身可靠性」是首要之務**：Vision 讀數沒有精確度數據、pixel_diff 沒有可區分性證據、SSIM 沒有失敗率統計、session 沒有 pass/fail。一個「證據驅動」的 QA 系統，首先需要對自身感測器的可靠性有證據。

2. **screen_id 穩定化是級聯失效的根源**：screen_id 不穩 → confidence 失效 → strategy 失效 → 探索效率崩潰 → 知識圖退化為 noise。解決此問題是所有知識累積功能的前提。

3. **分層感知（pixel → local OCR → Vision LLM）是成本與可靠性的最佳平衡**：零成本確定性層覆蓋 80% 場景，Vision 僅在必要時升級。

4. **Boot test / Smoke test 是 ROI 最高的自動化測試**：不需要等完美框架才開始 CI。現有的 detector + perceiver 已可支撐 per-commit smoke。

5. **pixel_diff 在動態遊戲場景下需要 ROI 遮罩才可用**：裸用 pixel_diff 對高動態畫面（魚群、粒子）形同虛設，這是多方一致指出的核心適用性問題。
