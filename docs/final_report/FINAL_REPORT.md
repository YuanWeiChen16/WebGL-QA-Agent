# WebGL QA Agent — 最終綜合改善報告

> **產出日期**：2026-07-17  
> **整合來源**：4 份領域綜合報告 + 3 份交叉審閱修正  
> **涵蓋範圍**：QA 測試、效能、知識庫、架構（40+ 份原始審查文件、15+ 位角色審查者）  
> **版本**：FINAL v1.0

---

## 目錄

1. [執行摘要](#執行摘要)
2. [Top-10 最關鍵改善項目](#top-10-最關鍵改善項目)
3. [統一優先級框架](#統一優先級框架)
4. [Phase 1：立即執行（Week 1-2）](#phase-1立即執行week-1-2)
5. [Phase 2：短期改善（Week 3-6）](#phase-2短期改善week-3-6)
6. [Phase 3：中期建設（Month 2-3）](#phase-3中期建設month-2-3)
7. [Phase 4：長期路線（Month 4+）](#phase-4長期路線month-4)
8. [領域一：QA 測試與 Oracle 可靠性](#領域一qa-測試與-oracle-可靠性)
9. [領域二：效能與資源管理](#領域二效能與資源管理)
10. [領域三：知識庫與資料演進](#領域三知識庫與資料演進)
11. [領域四：架構與基礎設施](#領域四架構與基礎設施)
12. [審閱者修正整合](#審閱者修正整合)
13. [關鍵依賴關係圖](#關鍵依賴關係圖)
14. [風險與 Trade-off 矩陣](#風險與-trade-off-矩陣)
15. [明確不做清單](#明確不做清單)
16. [附錄：跨報告共識觀察](#附錄跨報告共識觀察)

---

## 執行摘要

本專案是一個 AI 驅動的 WebGL 遊戲黑箱 QA 框架，以 Playwright 控制瀏覽器、Vision LLM 分析畫面，對任意 WebGL 遊戲做自動探索、崩潰偵測與功能正確性驗證。

經 40+ 份跨角色審查與 3 輪交叉審閱，系統核心問題歸結為 **5 大風險領域**：

| # | 風險領域 | 核心問題 | 影響 |
|---|----------|----------|------|
| 1 | **Vision API 韌性** | 無 circuit breaker、無成本上限 | Session 癱瘓、災難性花費 |
| 2 | **系統可信度** | Oracle 精確度未量化、無 pass/fail verdict | 無法判斷測試是否通過 |
| 3 | **畫面辨識穩定性** | screen_id 全圖 SSIM 在動態畫面失效 | 知識累積級聯失效 |
| 4 | **記憶體安全** | Browser 孤兒化、知識庫寫入無保護 | 靜默故障、資料損壞 |
| 5 | **可觀測性缺失** | 無 structured logging、無 telemetry | 無法驗證任何改善效果 |

### 審閱者關鍵修正

三位審閱者的交叉審閱揭示以下系統性問題：

1. **P0 項目過多**：四份報告合計 15+ 項 P0，需精簡至可執行範圍
2. **工時估算偏低**：「行數」不等於工作量，需加 1.5-2× 安全係數
3. **循環依賴**：screen_id 穩定化 ↔ Golden Dataset 存在雞生蛋問題
4. **可觀測性是前置條件**：沒有 logging/telemetry 就無法驗證其他改善
5. **效能優化可能犧牲準確度**：ROI crop、降採樣等需附帶準確度影響評估
6. **回歸保護缺失**：在 60 個測試、detector.py 零覆蓋的狀態下修改核心模組風險極高

---

## Top-10 最關鍵改善項目

以下為整合四份報告 + 三份審閱後，按**影響力 × 緊迫性 × 可行性**排序的 Top-10：

| 排名 | 項目 | 領域 | 影響 | 預估工時 | 理由 |
|------|------|------|------|----------|------|
| **1** | Structured Logging + Vision Telemetry | 可觀測性 | 🔴 極高 | 3-5 人天 | 所有其他改善的驗證前置條件（審閱者一致提升至 P0） |
| **2** | `finish()` Pass/Fail Verdict + Exit Code | CI | 🔴 極高 | 2-3 人天 | 框架與「截圖腳本」的本質區別；CI 化最低門檻 |
| **3** | Vision API Circuit Breaker + Per-Session Cost Cap | 韌性 | 🔴 極高 | 4-6 人天 | 防止 gateway 故障癱瘓 session + 防止災難性花費 |
| **4** | Knowledge YAML Atomic Write + .bak | 資料安全 | 🔴 高 | 2-3 人天 | 修復成本極低、風險消除明確（10 行核心邏輯） |
| **5** | Browser 孤兒化防護（async context manager） | 記憶體 | 🔴 高 | 2-3 人天 | Process kill 時 100% 孤兒化 Chromium（200-500MB） |
| **6** | screen_id pHash 穩定化（含遷移計畫） | 知識累積 | 🔴 高 | 5-8 人天 | 知識庫所有功能的前提；需含閾值校準與遷移 |
| **7** | Oracle Golden Dataset Minimal（20-30 張標註） | 可信度 | 🟡 高 | 3-5 人天 | Oracle WER 可能 46%，無基線則所有改善無法量化 |
| **8** | Image Preprocessing（Resize + ROI Crop） | 成本 | 🟡 高 | 3-4 人天 | Token 節省 40-70%，直接降低 Vision 呼叫成本 |
| **9** | 待修改模組 Characterization Tests | 回歸保護 | 🟡 高 | 3-5 人天 | 在 60 tests / detector 零覆蓋下修改核心模組前必備 |
| **10** | L1 崩潰偵測 Smoke Test CI | CI | 🟡 中 | 2-3 人天 | 零 Vision 成本、今天就能做的 per-commit 回歸守護 |

**總計預估**：30-45 人天（Phase 1-2 全部完成）

---

## 統一優先級框架

### P0 定義（審閱者修正後）

> **P0 標準**：不修復則 nightly run 會靜默失敗、造成不可逆損害（資料損壞/無限花費），或使系統完全無法產出可信結果。

精簡至 **7 項真正的 Day-1 阻擋項**（依執行順序）：

| 順序 | 項目 | 理由 |
|------|------|------|
| 0.5 | Structured Logging + Telemetry | 驗證後續所有改善的前置條件 |
| 1 | finish() verdict + exit code | CI 化最低門檻 |
| 2 | Knowledge atomic write + .bak | 資料安全，10 行修復 |
| 3 | Browser 孤兒化防護 | 非正常退出必 leak |
| 4 | Vision circuit breaker + cost cap | 防癱瘓 + 防破產 |
| 5 | Image preprocessing（resize + ROI） | 成本直接砍半 |
| 6 | screen_id pHash pre-filter（含遷移） | 知識累積地基 |

### 跨報告優先級仲裁結果

| 項目 | 01(QA) | 02(效能) | 03(知識庫) | 04(架構) | 最終判定 |
|------|--------|----------|-----------|----------|----------|
| screen_id 穩定化 | P0 | — | P0 | Phase 3 | **P0**（但工時修正為 5-8 天） |
| Oracle Golden Dataset | P0 | — | P2 | — | **P1 初期**（minimal 20-30 張先行） |
| Circuit Breaker | P0 | P0 | P1 | Phase 1 | **P0** |
| Structured Logging | 未標 | P0 | P1 | Phase 2 | **P0**（升級為前置條件） |
| CI Exit Code | P0 | P1 | P0 | Phase 1 | **P0** |
| SSIM 加速 | P1 | P0 | — | — | **P1**（條件式：若 pHash 先行則降為 P2） |

---

## Phase 1：立即執行（Week 1-2）

> 目標：建立可觀測性基礎、防止資料損壞與無限花費、解鎖 CI 化

| # | 項目 | 具體行動 | 工時 | 風險等級 | 驗收標準 |
|---|------|----------|------|----------|----------|
| 1 | Structured Logging | `structlog` + session correlation ID + Vision per-call metrics（latency_ms, tokens, cost_usd） | 3-5d | 🟡 中 | JSON log 含 session_id，Vision 呼叫有 cost breakdown |
| 2 | finish() Verdict | 三級判定 PASS(0)/FAIL(1)/UNSTABLE(2) + `sys.exit()` | 2-3d | 🟡 中 | `finish()` 回傳 verdict，script exit code 正確 |
| 3 | Knowledge Atomic Write | `filelock` + temp + `os.replace()` + `.bak` 備份 | 2-3d | 🔴 高 | 併發寫入不損壞，crash 後可從 .bak 恢復 |
| 4 | Browser Lifecycle Guard | `__aenter__`/`__aexit__` + `atexit` + `signal.signal(SIGTERM)` | 2-3d | 🔴 高 | kill -9 後無孤兒 Chromium process |
| 5 | Vision Circuit Breaker | `aiobreaker`（fail_max=5, reset=60s）+ `asyncio.sleep` 替換 | 3-4d | 🔴 高 | Gateway 故障 5 次後 fast-fail，降級為確定性模式 |
| 6 | Per-Session Cost Cap | config-driven max_calls/max_tokens + 三階段降級（warn→reduce→block） | 2-3d | 🔴 高 | 超出 cap 後自動降級，telemetry 記錄觸發事件 |

**Phase 1 總計**：15-21 人天

---

## Phase 2：短期改善（Week 3-6）

> 目標：穩定化 screen_id、建立回歸保護、降低 Vision 成本、解鎖 CI pipeline

| # | 項目 | 具體行動 | 工時 | 驗收標準 |
|---|------|----------|------|----------|
| 7 | Characterization Tests | 為 perceiver/detector/oracle/vision 補充快照測試，coverage > 60% | 3-5d | pytest --cov 通過 60% 門檻 |
| 8 | screen_id pHash 穩定化 | imagehash + UI 區域遮罩 + Hamming < 8 合併 + 舊 ID 遷移腳本 | 5-8d | 同一邏輯畫面 10 次截圖產出相同 screen_id |
| 9 | Image Preprocessing | Resize 1568px + ROI crop（UI 區域）+ JPEG q85 | 3-4d | Vision token 減少 ≥ 35%（telemetry 驗證） |
| 10 | Oracle Golden Dataset (Minimal) | 20-30 張人工標註截圖 + per-field WER/CER 計算 | 3-5d | 有量化的 Vision OCR baseline 數字 |
| 11 | Unit Test CI Pipeline | GitHub Actions（uv + ruff + pytest） | 1-2d | PR 自動跑 lint + test，fail 則 block merge |
| 12 | L1 Smoke Test Script | 零 Vision 確定性崩潰偵測 CI script | 2-3d | per-commit 跑 detector + perceiver smoke |
| 13 | Pydantic Schema Validation | 為每類 YAML 定義 Pydantic model，載入時 fail-fast | 3-4d | 格式錯誤的 YAML 立即報錯 |
| 14 | Playwright Context Recycling | 每 200 action 或 10 分鐘回收 context + storageState 保存 | 3-4d | 30 分鐘 session RSS 不超過 512MB |

**Phase 2 總計**：24-35 人天

---

## Phase 3：中期建設（Month 2-3）

> 目標：多通道感測、探索策略、跨 session 趨勢、WebGL 專用強化

| # | 項目 | 具體行動 | 工時 |
|---|------|----------|------|
| 15 | PaddleOCR L1.5 層 | ROI crop + 按需觸發（pixel_diff 偵測 UI 變化時）| 5-7d |
| 16 | WebGL Context Loss 事件監聽 | 注入 webglcontextlost/restored + 區分恢復/崩潰 | 2-3d |
| 17 | Confidence 雙向機制 | success_count/failure_count + 時間衰減（先用簡單比率，暫緩 Beta-Bernoulli） | 3-4d |
| 18 | 跨 Session 趨勢聚合 | RunAggregator 掃描 runs/ 產出 metrics_history.jsonl + sparkline | 4-6d |
| 19 | GameSession State Machine | `python-statemachine` 定義正式狀態轉換 + timeout | 4-5d |
| 20 | 效能門檻 Config 化 | `performance_budgets` 區塊 in default.yaml + per-game 覆寫 | 2-3d |
| 21 | Jank Score + Frame Drop % | rAF injection 擴展為 long frame 偵測 + CI 門檻 | 3-4d |
| 22 | 座標正規化 | Virtual Coordinate（參考 1280x720）+ Anchor-Relative 混合 | 4-6d |
| 23 | Oracle Feedback Loop | 結構化 dismiss 記錄 + per-invariant precision 追蹤 | 3-4d |
| 24 | 光敏性癲癇風險偵測 | EA IRIS 整合，WCAG 2.3.1 三次閃爍偵測 | 3-4d |

**Phase 3 總計**：34-46 人天

---

## Phase 4：長期路線（Month 4+）

> 目標：智慧化感知、多遊戲擴展、自主探索

| # | 項目 | 描述 |
|---|------|------|
| 25 | DINOv2 Screen Embedding | ONNX 推理 + sqlite-vec KNN 取代 pHash 長期方案 |
| 26 | Multi-Model Semantic Router | 已知畫面 → Haiku、未知畫面 → Opus |
| 27 | Sensor Fusion Layer | Template + OCR + Vision 三通道投票 + FDS 仲裁 |
| 28 | Browser Pool 架構 | 固定 N 個 browser instance + context 隔離 |
| 29 | Curiosity-Driven Q-Learning | Tabular Q（state=screen_id）+ inverse visit count reward |
| 30 | Knowledge Graph 化 | networkx.DiGraph + typed edges（triggers/blocks/requires） |
| 31 | Supervisor-Worker 排程 | 多遊戲並行 + per-game budget 隔離 |
| 32 | SQLite 衍生索引層 | YAML source of truth + DB 可重建索引 |

---

## 領域一：QA 測試與 Oracle 可靠性

### 核心問題

Oracle（功能正確性驗證）是框架最關鍵的判斷引擎，但：
- **零量化數據**證明其可靠性（Vision LLM OCR WER 可能達 46%）
- 框架目前**無法告訴你測試通過還是失敗**（無 exit code、無 verdict）
- screen_id 不穩定導致知識累積級聯失效
- pixel_diff 在動態遊戲場景下形同虛設

### 統整建議（含審閱修正）

| 主題 | 建議 | 審閱修正 |
|------|------|----------|
| Oracle 精確度 | 建立 Golden Dataset 量化 WER/CER | 提升至 P1 初期（20-30 張 minimal 版本）；與 screen_id 穩定化有循環依賴，需漸進打破 |
| Pass/Fail Verdict | PASS(0)/FAIL(1)/UNSTABLE(2) + exit code | 需定義 verdict 計算邏輯（哪些 anomaly 組合算 FAIL） |
| screen_id 穩定化 | pHash/dHash + UI 錨點遮罩 | 工時從「30 行」修正為 5-8 天（含遷移計畫與閾值校準） |
| 分層感知 | L0 pixel → L1 OCR → L2 Vision | 升級閾值需 PoC 驗證；PaddleOCR 340ms CPU 不可放在每步 observe |
| ROI 遮罩 | 動態區（魚群）與 UI 靜態區分開 | 需附帶全圖 fallback 頻率（每 10 步一次全圖掃描） |
| bare except 修復 | `check_invariants` 加 logging + reread_failed 欄位 | 含回歸測試 |

### 跨主題共識（3+ 來源一致）

1. 「衡量自身可靠性」是首要之務
2. screen_id 穩定化是級聯失效的根源
3. 分層感知是成本與可靠性的最佳平衡
4. Boot test / Smoke test 是 ROI 最高的自動化測試
5. pixel_diff 在動態遊戲場景下需要 ROI 遮罩才可用

---

## 領域二：效能與資源管理

### 核心問題

- Vision 呼叫無 circuit breaker → gateway 故障時每步浪費 14-42 秒
- 無 per-session cost cap → agent loop 失控可災難性花費
- SSIM 在 1080p 下用 scikit-image 耗時 ~580ms
- Playwright 長時間 session 有已知記憶體洩漏

### 統整建議（含審閱修正）

| 主題 | 建議 | 審閱修正 |
|------|------|----------|
| SSIM 加速 | 評估 Fast-SSIM / 降採樣 / OpenCV | **條件式優先級**：若 pHash 方案先行，SSIM 加速降為 P2 |
| Per-Session Budget | 三層成本護欄 | 需**實證基線**（跑 5 session 統計實際 Vision 呼叫分佈），依 phase 分化 cap |
| 效能預算表 | observe() < 20ms | **修正**：拆為 `screenshot: <200ms` + `deterministic analysis: <20ms` |
| Browser Pool | context 隔離 | WebGL context 估 150-300MB RAM（非普通網頁的 30-80MB） |
| 跨 Run 趨勢 | P0 regression detection | 依賴 CI exit code 先完成，標為「Phase 2 P0」 |
| Structured Logging | structlog + correlation ID | **升為 Phase 0.5**：所有效能優化開始前的前置條件 |

### 效能-準確度 Trade-off（審閱者新增要求）

| 優化項目 | 準確度影響 | 緩解措施 |
|----------|-----------|----------|
| ROI Crop | 區域外異常漏偵測 | 每 10 步全圖 fallback |
| 降採樣 SSIM | 1px 渲染錯誤在 480p 不可見 | 僅用於 screen_id 粗篩，精確比對用原圖 |
| Hash Dedup（SSIM > 0.98） | 微小 UI 變化（HP 100→99）可能被 skip | 閾值由 Oracle 精確度實驗決定，非硬編碼 |
| Multi-Model Router | cheap model 可能漏 anomaly | 已知畫面才 route to cheap，未知一律 premium |

---

## 領域三：知識庫與資料進

### 核心問題

- `save_runtime()` 為裸 `open() + yaml.dump()` — 無 atomic write、無 lock、無 backup
- Confidence 只升不降、無統計意義
- YAML 在 500KB+ 時每次寫入 100-200ms 且阻塞 event loop
- 無跨 session 趨勢追蹤

### 統整建議（含審閱修正）

| 主題 | 建議 | 審閱修正 |
|------|------|----------|
| Atomic Write | filelock + temp + os.replace + .bak | 需處理 Windows 跨磁碟限制、加回歸測試 |
| Confidence | Beta-Bernoulli 後驗模型 | **Blocked by screen_id**；先用簡單 success/failure count；需先定義消費者介面 |
| YAML 規模 | YAML 為永遠的 source of truth | **修正**：定義 200KB 閾值，超過後平滑遷移至 SQLite |
| 跨遊戲知識複用 | `knowledge/_shared/` 共通模板 | 降優先級至長期探索；需 applicability check + 失敗案例分析 |
| Schema Validation | Pydantic model + schema_version | 含跨文件 referential integrity 檢查 |

### screen_id ↔ Golden Dataset 循環依賴解法

（審閱者 Q3 提出的漸進路徑）：

```
Step 1: 人工標註 30 張固定畫面 → 建立 screen_id ground truth
Step 2: 用 ground truth 驗證 pHash 方案（Hamming 閾值校準）
Step 3: pHash 穩定後 → 擴展為完整 Golden Dataset（50-100 張）
Step 4: 完整 Dataset 驗證 Oracle OCR 精確度
```

---

## 領域四：架構與基礎設施

### 核心問題

- Vision LLM gateway 是單點故障且無成本上限
- GameSession 無正式狀態機、無 async context manager
- 無 CI pipeline（lint + test + E2E）
- 開發者上手需要 Vision API key（門檻高）

### 統整建議（含審閱修正）

| 主題 | 建議 | 審閱修正 |
|------|------|----------|
| Vision Fallback Chain | Primary → Backup → 確定性 → Halt | 每層的降級行為需在 report 中標記 `degraded_mode: true` |
| GameSession 生命週期 | python-statemachine + async context manager | 移至 Phase 3（Phase 1 先做 context manager 防護） |
| CI Pipeline | GitHub Actions（uv + ruff + pytest） | 分層：PR Gate < 2min → Integration < 10min → Nightly E2E |
| DX 上手 | `uv run demo` 零 Vision 模式 | Phase 2 低成本高回報 |
| YAGNI 紀律 | Event-Driven / MCP 在目前規模不需要 | 維持 program 式編排，只做 MCP-ready interface |

### Unity WebGL 特化考量

| 項目 | 優先級 | 描述 |
|------|--------|------|
| 載入偵測 | 高 | loading bar 消失 / SSIM 穩定判定載入完成 |
| 場景切換黑屏 | 高 | 區分已知 transition 期 vs 異常黑屏 |
| WASM 記憶體監控 | 中 | 接近 2GB 限制預警 |
| Input Delivery | 中 | canvas focus 驗證 |

---

## 審閱者修正整合

### QA 審閱者（05）核心修正

| 編號 | 修正 | 整合方式 |
|------|------|----------|
| A1 | P0 精簡至 5 項、明確執行順序 | ✅ 已精簡至 7 項含前置條件 |
| A2 | screen_id ↔ Golden Dataset 循環依賴解法 | ✅ 漸進路徑已定義 |
| A3 | 回歸保護前置條件（characterization tests） | ✅ 納入 Phase 2 #7 |
| A4 | 效能預算基於實測，計入截圖時間 | ✅ 拆分 screenshot + analysis |
| A5 | 新依賴評估表 | ✅ 見下方依賴評估 |
| A6 | 分層感知升級閾值 + PoC 驗證 | ✅ PaddleOCR 定位為按需觸發 |
| A7 | 工時加安全係數 | ✅ 已改用人天估算 |
| A8 | 按團隊規模差異化路線圖 | ✅ 見下方 |

### 效能審閱者（06）核心修正

| 編號 | 修正 | 整合方式 |
|------|------|----------|
| Q1 | SSIM 加速與 pHash 的條件依賴 | ✅ 條件式優先級已標註 |
| Q2 | Per-Session Budget 需實證基線 | ✅ 要求跑 5 session 統計後設 cap |
| Q3 | Fast-SSIM 251× 宣稱未驗證 | ✅ 改為多方案 decision matrix |
| Q4 | observe < 20ms 與實際不符 | ✅ 拆分為截圖取得 + 確定性分析 |
| Q5 | 跨 Run 趨勢依賴 CI exit code | ✅ 標為 Phase 2 P0 |
| Q6 | Browser Pool RAM 估算過樂觀 | ✅ 修正為 WebGL context 150-300MB |
| Q7 | 缺少效能-準確度 trade-off | ✅ 新增 trade-off 矩陣 |
| Q8 | Structured Logging 為前置條件 | ✅ 升為 Phase 0.5 |

### 知識庫審閱者（07）核心修正

| 編號 | 修正 | 整合方式 |
|------|------|----------|
| Q1 | Golden Dataset 應提升優先級 | ✅ 提升至 P1 初期（minimal 版本） |
| Q2 | screen_id 遷移策略缺失 | ✅ 工時含遷移，Phase 2 明確列出 |
| Q3 | PaddleOCR 340ms 與 20ms 預算衝突 | ✅ 定位為按需觸發，非每步執行 |
| Q4 | Confidence Beta-Bernoulli 可能為投機性架構 | ✅ Blocked by screen_id；先用簡單比率 |
| Q5 | YAML 規模天花板 | ✅ 定義 200KB 閾值 + 平滑遷移策略 |
| Q6 | 跨遊戲知識複用缺驗證 | ✅ 降優先級至長期探索 |
| Q7 | 工時估算系統性偏低 | ✅ 已改用人天 + 含測試整合 |
| Q8 | 可觀測性為前置條件 | ✅ 升為 Phase 1 第一項 |

---

## 關鍵依賴關係圖

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 0.5: Structured Logging + Telemetry                       │
│ (所有改善的量化驗證基礎)                                          │
└──────────┬─────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────┐     ┌──────────────────────────────┐
│ finish() verdict + exit  │     │ Knowledge atomic write + .bak│
│ code (CI 最低門檻)        │     │ (資料安全)                    │
└──────────┬───────────────┘     └──────────────────────────────┘
           │
           ▼
┌──────────────────────────┐     ┌──────────────────────────────┐
│ Circuit Breaker +        │     │ Browser lifecycle guard       │
│ Per-Session Cost Cap     │     │ (async context manager)       │
└──────────┬───────────────┘     └──────────────────────────────┘
           │
           ▼
┌──────────────────────────┐     ┌──────────────────────────────┐
│ Image Preprocessing      │────▶│ Vision Telemetry 驗證節省     │
│ (resize + ROI)           │     │ (依賴 logging)                │
└──────────────────────────┘     └──────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────────┐
│ screen_id pHash (含遷移) ──→ Golden Dataset ──→ Oracle 精確度量化│
│ (循環依賴以漸進路徑打破)                                           │
└──────────┬───────────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────┐     ┌──────────────────────────────┐
│ Confidence 雙向機制       │     │ 跨 Session 趨勢聚合           │
│ (blocked by screen_id)   │     │ (依賴 exit code + telemetry)  │
└──────────────────────────┘     └──────────────────────────────┘

條件分支：
  pHash 先行落地 → SSIM 加速降為 P2
  pHash 延後     → SSIM 加速維持 P1
```

---

## 風險與 Trade-off 矩陣

### 新依賴評估（審閱者 A5 要求）

| 依賴 | 用途 | Stars/活躍度 | 安裝大小 | 平台限制 | 替代方案 |
|------|------|-------------|----------|----------|----------|
| `structlog` | Structured logging | 7k+ / 活躍 | 輕量 | 全平台 | 標準庫 logging + JSON formatter |
| `filelock` | 併發寫入保護 | 2k+ / 活躍 | 極輕量 | 全平台 | `fcntl`（Unix only） |
| `imagehash` | pHash/dHash | 5k+ / 中 | 輕量 | 全平台 | 自行實作 DCT hash |
| `aiobreaker` | Async circuit breaker | <500 / 低 | 極輕量 | 全平台 | **30 行自行實作**（推薦） |
| `PaddleOCR` | 本地 OCR | 85k+ / 活躍 | **1.5GB+** | GPU 需 CUDA | Tesseract(100MB)、EasyOCR(500MB)、Template Matching(0) |
| `Fast-SSIM` | SSIM 加速 | <100 / 低 | 輕量 | **x86 AVX2 only** | 降採樣 scikit-image(全平台)、OpenCV SSIM |
| `python-statemachine` | 狀態機 | 1k+ / 中 | 輕量 | 全平台 | Enum + 手動 transition |

**建議**：
- `aiobreaker` → 自行實作 30 行 circuit breaker（降低供應鏈風險）
- `PaddleOCR` → 先用 Template Matching（零依賴），效果不足再升級
- `Fast-SSIM` → 先用降採樣 scikit-image（全平台），確認 pHash 方案再決定

### 按團隊規模差異化路線（審閱者 A8 要求）

#### 單人維護者路線（精簡版）

| Phase | 重點 | 時程 |
|-------|------|------|
| 1 | logging + verdict + atomic write + context manager | 2 週 |
| 2 | circuit breaker（自行實作）+ cost cap + pHash | 3 週 |
| 3 | CI pipeline + smoke test + Golden Dataset minimal | 2 週 |
| 暫緩 | PaddleOCR、DINOv2、State Machine、Browser Pool | 待人力充裕 |

#### 小團隊（3-5 人）路線（完整版）

| Phase | 時程 | 並行軌道 |
|-------|------|----------|
| 1 | 2 週 | 軌道 A：logging + verdict + CI / 軌道 B：atomic write + lifecycle guard |
| 2 | 4 週 | 軌道 A：screen_id + Golden Dataset / 軌道 B：circuit breaker + cost cap + preprocessing |
| 3 | 6 週 | 軌道 A：PaddleOCR + Oracle feedback / 軌道 B：趨勢聚合 + WebGL 強化 |
| 4 | 持續 | DINOv2、Multi-model、Q-Learning |

---

## 明確不做清單

（審閱者建議：比無限降級的 P3 更誠實）

| 項目 | 不做原因 |
|------|----------|
| Event-Driven 架構（Pub/Sub） | YAGNI — 目前單 session 規模不需要 |
| 完整 OpenTelemetry + Jaeger | 過重 — structlog JSON 已足夠當前規模 |
| MCP Protocol 實作 | 只做 MCP-ready interface，等生態成熟再投入 |
| GPU Timer Query（EXT_disjoint_timer_query） | 黑箱限制 — 多數遊戲不暴露此 extension |
| 跨瀏覽器 SSIM 比對（Firefox/Safari） | 投入不符效益 — 統一 Chromium CI 即可 |
| 完整 Knowledge Graph（Neo4j/networkx） | 過早優化 — YAML + SQLite 足以支撐 100+ 節點 |
| 多 Agent 協作探索（cMarlTest） | 研究性質 — 離 production 太遠 |
| VCR Record-Replay Simulator | 高成本低回報 — 純黑箱假設下不實際 |

---

## 附錄：跨報告共識觀察

以下觀點被 **5 個以上獨立來源** 同時強調，代表最高共識：

### 共識 1：Vision API 韌性是生存問題

> 無 circuit breaker + 無成本上限 = 系統在 production 中靜默惡化或破產

- 提出者：Performance Benchmarker、SRE、Backend Architect、API Tester、Incident Response、Autonomous Optimization、Multi-Agent Architect、Workflow Architect
- 共識強度：8 個獨立角色

### 共識 2：screen_id 穩定化是一切知識功能的地基

> screen_id 不穩 → confidence 失效 → strategy 失效 → 探索效率崩潰 → 知識圖退化為 noise

- 提出者：Evidence Collector、AI Engineer、Model QA、Software Architect、Level Designer、Tool Evaluator、Frontend Developer、Reality Checker、ZK Steward
- 共識強度：9+ 個獨立角色

### 共識 3：分層感知是成本與可靠性的最佳平衡

> 零成本確定性層覆蓋 80% 場景，Vision 僅在必要時升級

- 提出者：Tool Evaluator、Evidence Collector、AI Engineer、Software Architect、Autonomous Optimization、Prompt Engineer
- 共識強度：6 個獨立角色

### 共識 4：沒有 Pass/Fail 的測試框架不是測試框架

> 無 exit code、無 verdict、run status 停在 "running" — 與截圖腳本無本質區別

- 提出者：Reality Checker、Test Automation Engineer、Workflow Optimizer、DevOps Automator、Governance Architect
- 共識強度：5+ 個獨立角色

### 共識 5：可觀測性是所有改善的前置條件

> 沒有 structured logging 和 telemetry，就無法量化任何優化是否真正有效

- 提出者：Backend Architect、SRE、Incident Response、Autonomous Optimization、Multi-Agent Architect
- 共識強度：5 個獨立角色（且被三位審閱者一致強調）

---

## 結論

本專案在技術方向上已有清晰的架構與功能設計，核心缺口集中在**可信度基礎設施**（可觀測性、verdict、Oracle 量化）與**防護性工程**（circuit breaker、atomic write、lifecycle guard）。

建議的執行策略：

1. **先建觀測、再做改善** — Structured Logging 是 Day 1 工作
2. **先防損壞、再求優化** — Atomic write + lifecycle guard 在任何效能優化之前
3. **漸進打破循環依賴** — 30 張標註 → pHash 驗證 → 完整 Dataset
4. **每個改善附帶驗證** — 沒有 telemetry 數據支撐的「改善」不算完成
5. **接受 good enough** — 30 行 circuit breaker > 完美的 pyresilience 整合

---

*本報告整合自 4 份領域綜合報告（01-04）與 3 份交叉審閱修正（05-07），涵蓋 40+ 份原始審查文件、15+ 位角色審查者的建議。最終判定以跨報告共識度、審閱者修正、實際可執行性為依據。*
