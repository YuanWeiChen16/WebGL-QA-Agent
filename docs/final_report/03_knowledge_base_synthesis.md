# 知識庫（Knowledge Base）領域綜合報告

> **產出日期**：2026-07-17  
> **資料來源**：`docs/agent_suggestions/` 全部 9 批次 + 頂層專家報告（共 40+ 份審查文件）  
> **報告性質**：跨角色主題綜合，按優先級排序

---

## 目錄

1. [screen_id 穩定化與畫面辨識](#1-screen_id-穩定化與畫面辨識)
2. [Oracle 可靠性與感測器融合](#2-oracle-可靠性與感測器融合)
3. [知識庫儲存安全與併發](#3-知識庫儲存安全與併發)
4. [Confidence 機制與知識品質閘門](#4-confidence-機制與知識品質閘門)
5. [Vision LLM 成本控制與韌性](#5-vision-llm-成本控制與韌性)
6. [CI 整合與 Pass/Fail 判定](#6-ci-整合與-passfail-判定)
7. [知識庫結構演進（Schema / Graph / 搜尋）](#7-知識庫結構演進)
8. [跨 Session 趨勢分析與回饋迴圈](#8-跨-session-趨勢分析與回饋迴圈)
9. [座標正規化與 Grounding](#9-座標正規化與-grounding)
10. [可觀測性與除錯能力](#10-可觀測性與除錯能力)
11. [WebGL 專用偵測強化](#11-webgl-專用偵測強化)
12. [探索策略與覆蓋率](#12-探索策略與覆蓋率)
13. [跨遊戲知識複用與 Onboarding](#13-跨遊戲知識複用與-onboarding)

---

## 1. screen_id 穩定化與畫面辨識

**共識程度**：★★★★★（幾乎所有角色一致認定為最高優先）

### 問題摘要

screen_id 由 Vision LLM 自由命名 + 全圖 SSIM 比對，在動態畫面（魚群游動、粒子效果）下完全失效。同一邏輯畫面被拆成多個別名，導致：
- Transition 邊碎片化（confidence 永遠達不到 high）
- Strategy/knowledge 跨 session 不可用
- Runtime learning 的核心價值主張被掏空

### 建議方案（多角色交集）

| 層級 | 方案 | 延遲 | 來源角色 |
|------|------|------|----------|
| L1 | Perceptual Hash (pHash/dHash) pre-filter | <5ms | Evidence Collector, Tool Evaluator, Codebase Onboarding, Level Designer, Model QA |
| L2 | UI 錨點遮罩 + 局部 SSIM | ~10ms | Evidence Collector, Software Architect (B3), Frontend Developer |
| L3 | DINOv2 Screen Embedding + sqlite-vec KNN | ~50ms | AI Engineer |
| Registry | Canonical Screen Registry（Vision 命名降為 display name） | — | Software Architect (B3), ZK Steward |

### 推薦實作路徑

1. **立即**（P0）：用 `imagehash` 套件對 UI 固定區域計算 pHash，Hamming distance < 8 → 合併為同一 screen
2. **短期**：在 `systems/*.yaml` 定義 `dynamic_regions` 遮罩，遮罩後做 SSIM
3. **中期**：評估 DINOv2 ONNX embedding 作為長期方案

### 參考 URL

- imagehash 套件：https://github.com/JohannesBuchner/imagehash
- Firespawn Studios — pHash 用於遊戲 AI 位置辨識：https://firespawnstudios.net/blog/how-we-gave-an-ai-a-sense-of-place/
- DINOv2 vs CLIP Visual Similarity：https://github.com/JayyShah/CLIP-DINO-Visual-Similarity
- sqlite-vec 向量搜尋：https://github.com/asg017/sqlite-vec/
- VideoGameBench pHash checkpoint matching：https://arxiv.org/html/2505.18134
- visual-guard（pixel/SSIM/pHash 三層比對）：https://pypi.org/project/visual-guard/

---

## 2. Oracle 可靠性與感測器融合

**共識程度**：★★★★★（Critical — 多角色標記為系統可信度基礎）

### 問題摘要

Oracle 的 ground truth 完全依賴 Vision LLM OCR，但：
- OCR 準確率從未量化（OCRBench 顯示 VLM 在遊戲字型上 WER 可達 46%）
- 「reread 二次確認」只是重複同一個不可靠感測器
- 無獨立交叉驗證通道

### 建議方案

| 優先級 | 方案 | 成本 | 來源 |
|--------|------|------|------|
| P0 | 建立 Golden Dataset（50-100 張標註截圖）量化 Vision precision/recall | 人工標註 | Reality Checker, Evidence Collector, Multi-Agent Architect, Model QA |
| P1 | PaddleOCR 本地 L1.5 層（已知 HUD 區域 ROI crop） | <50ms/zero API | AI Engineer, Tool Evaluator, Rapid Prototyper |
| P1 | Digit ROI Template Matching（遊戲固定字型） | <5ms | Software Architect (B3) |
| P2 | 多通道投票機制（Local OCR + Vision + Template → 2/3 一致採信） | — | Software Architect (B3), AI Engineer |
| P2 | Consensus Entropy（多 VLM 獨立讀取 → 收斂判定） | 2x Vision cost | Codebase Onboarding |

### Prompt 層面改進

| 方案 | 效果 | 來源 |
|------|------|------|
| Preprocessing Hints（告知數字位置/字型特徵） | 定位誤差 23% → 4% | Prompt Engineer |
| Multi-pass OCR（第二次帶入第一次結果做 verify） | 精準 reread | Prompt Engineer |
| 3 級 Uncertainty Policy（clear/ambiguous/not_visible） | 智慧觸發 reread | Prompt Engineer |

### 參考 URL

- PaddleOCR（85.6k stars）：https://github.com/PaddlePaddle/PaddleOCR
- OCRBench v2：https://arxiv.org/html/2501.00321v2
- Balatro OCR（PaddleOCR fine-tune 遊戲 HUD）：https://huggingface.co/marco-costa-ml/balatro-ocr
- Consensus Entropy（CVPR 2026, F1 +42.1%）：https://arxiv.org/html/2504.11101v4
- StructuredVision（多引擎對比）：https://github.com/ammahmoudi/StructuredVision
- FADE（多感測器融合測試）：https://dl.acm.org/doi/10.1145/3728910

---

## 3. 知識庫儲存安全與併發

**共識程度**：★★★★☆（所有工程角色一致指出，且修復成本極低）

### 問題摘要

`save_runtime()` 為裸 `open() + yaml.dump()`：
- 無 atomic write → crash 時半寫損毀
- 無 file lock → 多 session 併發覆寫
- 無 backup → 損壞後無法還原

### 建議方案（全角色一致）

```python
# Atomic write（10 行，立即可做）
import tempfile, os
def atomic_yaml_write(data, filepath):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(filepath), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, allow_unicode=True)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, filepath)
    except BaseException:
        os.unlink(tmp); raise
```

| 層級 | 措施 | 工具 | 來源 |
|------|------|------|------|
| 立即 | Atomic write（temp + fsync + os.replace） | 內建 | 全部工程角色 |
| 立即 | .bak 備份前一版 | shutil.copy2 | Database Optimizer, Governance Architect, Incident Response |
| 短期 | filelock 排他寫入 | `filelock` 套件 | Database Optimizer, SRE, Backend Architect |
| 中期 | Per-session delta 寫入 + session 結束 merge | — | Test Automation Engineer, Database Optimizer |

### 參考 URL

- filelock（跨平台 file lock）：https://pypi.org/project/filelock/
- safeatomic（atomic write + lock + checksum）：https://pypi.org/project/safeatomic/2.0.3/
- portalocker：https://portalocker.readthedocs.io/en/latest/

---

## 4. Confidence 機制與知識品質閘門

**共識程度**：★★★★☆

### 問題摘要

- AD-6：confidence 只升不降，失敗不會降級
- 「3 次全成功」與「100 次 95% 成功」都是 high — 無統計意義
- 座標更新（`update_element_location`）無品質閘門直接寫入 static YAML
- 知識無新鮮度偵測，過時 entries 永不清除

### 建議方案

| 方案 | 描述 | 來源 |
|------|------|------|
| Beta-Bernoulli 後驗 | α=成功+1, β=失敗+1，用 95% credible interval 下界作 trust score | Model QA |
| 分層衝突解決 | Static YAML > runtime high > medium > low | Software Architect (top) |
| Staleness 偵測 | last_verified_date + 30/90 天分級 | ZK Steward |
| 座標更新 confidence 閘門 | 連續 3 次 Vision 回報相近座標（<10px）才寫入 | ZK Steward |
| 解法信心分數 | find_solution() 回傳附帶 success_rate | ZK Steward |

### 參考 URL

- BayesTruth（Beta-Bernoulli 信任評分）：https://github.com/davccavalcante/bayestruth
- COMPASS KB Validation（HARD/WARN 閘門）：https://pypi.org/project/compass-kb-validation/1.30.0/
- ElephantBroker 四態驗證模型：https://arxiv.org/pdf/2603.25097
- Knowledge-as-Code staleness model：https://snapsynapse.com/tools/knowledge-as-code/

---

## 5. Vision LLM 成本控制與韌性

**共識程度**：★★★★★（AD-9 明確標記「待補」，所有角色追蹤

### 問題摘要

- 無 per-session 成本上限 → agent loop 失控可耗盡預算
- 無 circuit breaker → gateway 故障時每步浪費 14-42 秒
- `time.sleep()` 在 async 環境凍結 event loop
- 未做 image preprocessing → 每次送完整 1280x720 浪費 token

### 建議方案

| 優先級 | 方案 | 預估效益 | 來源 |
|--------|------|----------|------|
| P0 | Per-session hard cap（max_calls + max_tokens） | 防災難性花費 | 全部 |
| P0 | Image resize 1568px + ROI crop | token -40~70% | Autonomous Optimization |
| P0 | Circuit breaker（連續 3-5 失敗 → open → 確定性降級） | latency 恢復 | SRE, API Tester, Backend Architect, Multi-Agent, Workflow, Incident Response |
| P1 | 將 `time.sleep()` → `asyncio.sleep()` | event loop 不凍結 | SRE |
| P1 | Multi-model semantic router（已知畫面 → cheap model） | 成本 -50~60% | Autonomous Optimization |
| P2 | Hash dedup（SSIM > 0.98 不重複呼叫） | 呼叫量 -10~25% | Autonomous Optimization |

### 參考 URL

- pyresilience（retry + circuit breaker + timeout 統一）：https://github.com/AhsanSheraz/pyresilience
- interlock-cb：https://github.com/bagowix/interlock
- token-throttle（多維 rate limiting）：https://github.com/Elijas/token-throttle
- Anthropic Vision 文件（resize 建議）：https://platform.claude.com/docs/en/build-with-claude/vision
- Claude Vision Production Guide（preprocessing pipeline）：https://www.developersdigest.tech/blog/claude-vision-api-production-guide

---

## 6. CI 整合與 Pass/Fail 判定

**共識程度**：★★★★★（AD-7 公認最高優先缺口）

### 問題摘要

- `finish()` 無 verdict / exit code
- metadata.json 停在 "running"
- 無法掛 CI pipeline — 框架與「截圖腳本」無本質區別

### 建議方案

| 方案 | 描述 | 來源 |
|------|------|------|
| 三級 Verdict | PASS(0) / FAIL(1) / UNSTABLE(2) | Test Automation Engineer, Governance Architect, Reality Checker |
| L1 Smoke Test CI | 零 Vision、只跑 detector — 今天就能做 | Workflow Optimizer, DevOps Automator |
| Flake Attribution | real_bug / ocr_misread / timing_race / click_miss 分類 | Test Automation Engineer |
| CI Pipeline（lint + pytest） | `.github/workflows/ci.yml` + `astral-sh/setup-uv` | DevOps Automator |
| GPU Self-hosted Runner | nightly E2E 視覺測試需真實 GPU | DevOps Automator |

### 建議落地順序

```
1. finish() 加 verdict + exit code（2-5 行，P0）
2. scripts/ci_smoke.py — 確定性崩潰偵測（1-2 天）
3. GitHub Actions unit test CI（半天）
4. Nightly regression（待 AD-4/AD-5 穩定）
```

### 參考 URL

- iXie Gaming 分層 CI：https://www.ixiegaming.com/blog/automated-game-testing-that-delivers-bots-toolchains-and-ci-cd/
- pytest exit code 公約：https://docs.pytest.org/en/stable/reference/exit-codes.html
- astral-sh/setup-uv action：https://github.com/astral-sh/setup-uv
- Bugnet 回歸測試設定：https://bugnet.io/blog/setting-up-automated-regression-tests-for-game-builds

---

## 7. 知識庫結構演進

**共識程度**：★★★☆☆（方向一致，時間點有分歧）

### 7.1 Schema Validation（高優先）

| 方案 | 來源 |
|------|------|
| Pydantic model 驗證每類 YAML（fail-fast） | Software Architect (top), Database Optimizer |
| Schema version + 自動遷移管線 | Software Architect (top) |
| 跨文件 referential integrity（flow_graph edges → systems） | LSP Index Engineer |

### 7.2 搜尋改進（中優先）

| 方案 | 來源 |
|------|------|
| 全局符號表（`system.element` fully-qualified name） | LSP Index Engineer |
| 語意向量搜尋（bge-m3 embedding 或 vibe-finder fuzzy） | LSP Index Engineer |
| SQLite FTS5 索引（中文 + 英文） | Database Optimizer |

### 7.3 Knowledge Graph 化（低優先/長期）

| 方案 | 來源 |
|------|------|
| networkx.DiGraph 多跳推理 | Software Architect (top) |
| Typed edges（triggers/blocks/requires） | Software Architect (top) |
| KLPEG 式 KG + LLM 推理 | Software Architect (top) |

### 7.4 SQLite 衍生索引層（中優先）

YAML 為 source of truth + SQLite 為可重建的衍生索引，支援跨 session 查詢。

### 參考 URL

- yaml2pydantic：https://github.com/banduk/yaml2pydantic
- fluxconf（migration support）：https://github.com/Greenroom-Robotics/fluxconf
- cartulary（referential integrity）：https://pypi.org/project/cartulary/0.3.0/
- Pyrite（YAML + SQLite FTS5）：https://github.com/markramm/pyrite
- KLPEG（KG for game testing）：https://doi.org/10.48550/arxiv.2511.02534

---

## 8. 跨 Session 趨勢分析與回饋迴圈

**共識程度**：★★★★☆

### 問題摘要

- 每個 session 獨立產出報告，無跨 session 趨勢追蹤
- Oracle 誤報無結構化 feedback loop
- Bug 重現率無自動統計

### 建議方案

| 方案 | 描述 | 來源 |
|------|------|------|
| RunAggregator | 掃描 runs/ 目錄，產出 bug reproduction rate、anomaly frequency、stability score | Workflow Optimizer |
| Oracle Feedback Loop | 每個 candidate 記錄 confirmed/false_positive + 原因分類 | Workflow Optimizer |
| SBTM 指標 | bugs/session-hour、charter coverage、diminishing returns signal | Test Results Analyzer |
| Knowledge Maturity Assessment | flow 覆蓋率 + confidence 穩定度 + oracle 可靠度 → 是否可進入確定性回歸 | Test Results Analyzer |

### 參考 URL

- OASIs（ISSTA 2018，迭代式 oracle 改進）：https://doi.org/10.1145/3213846.3229503
- SmartOracle（False Positive Critic）：https://arxiv.org/pdf/2601.15074
- Fern Platform（Universal Test Aggregation）：https://github.com/guidewire-oss/fern-platform
- Flakiness.io：https://flakiness.io/

---

## 9. 座標正規化與 Grounding

**共識程度**：★★★★☆（AD-4 公認待處理）

### 問題摘要

- 座標為絕對像素，解析度變更即失效
- 無 pre-click grounding（可能大量點擊空氣）
- pixel_diff 在高動態場景作為 action effect signal 失效

### 建議方案

| 方案 | 來源 |
|------|------|
| Virtual Coordinate 系統（參考解析度 + 線性映射） | Software Architect (top) |
| Anchor-Relative 定位（top-right, offset） | Software Architect (top) |
| Canvas ResizeObserver 監控尺寸變化 | Frontend Developer |
| HiDPI 座標空間正規化（CSS px vs device px） | Frontend Developer |
| Per-screen adaptive pixel_diff baseline（idle 分佈 + 2σ） | Code Reviewer |
| 語意層 Effect Signal（game_state diff 而非純 pixel diff） | Model QA, Minimal Change |
| rAF 截圖同步（避免 tearing） | Frontend Developer |

### 參考 URL

- WebGL canvas resize guide：https://webglfundamentals.org/webgl/lessons/webgl-resizing-the-canvas.html
- Unity Agent Workflows Coordinate Conversion：https://github.com/AUN-PN/unity-agent-workflows/blob/main/references/coordinate-space-conversion.md
- Canvas visual bug detection（Alberta, ASE 2022）：https://asgaard.ece.ualberta.ca/papers/Conference/ASE_2022_Macklon_Automatically_Detecting_Visual_Bugs_In_HTML5_Canvas_Games.pdf

---

## 10. 可觀測性與除錯能力

**共識程度**：★★★★☆（Backend Architect 標為 P0 gap）

### 問題摘要

- 僅有 `logging.getLogger()` + f-string，無 structured logging
- 無 correlation ID / trace_id
- Vision 呼叫無 latency/token/cost metric
- Debug 僅靠事後 HTML report

### 建議方案

| 方案 | 來源 |
|------|------|
| structlog + session correlation ID | Backend Architect |
| OpenTelemetry trace（每步 = 1 span） | Multi-Agent Architect |
| Per-call Vision telemetry（latency_ms, tokens, cost_usd） | Backend Architect, Autonomous Optimization |
| Webhook 即時告警（high severity → Slack/PagerDuty） | Incident Response |
| Allure Report 整合（趨勢 + CI 原生） | Tool Evaluator |

### 參考 URL

- structlog contextvars：https://www.structlog.org/en/24.4.0/contextvars.html
- AgentTrace 三層 taxonomy：https://arxiv.org/pdf/2602.10133
- Allure + Playwright：https://allurereport.org/docs/playwright/
- PagerDuty Events API v2：https://developer.pagerduty.com/docs/events-api-v2/overview/

---

## 11. WebGL 專用偵測強化

**共識程度**：★★★☆☆（專業角色強烈建議）

### 問題摘要

- Context loss 偵測靠 console pattern match（遊戲不印就漏）
- 無 VRAM 估算、無 draw call 監控
- 未區分「正常場景切換黑屏」vs「異常黑屏」
- Unity WebGL 特殊載入行為未處理

### 建議方案

| 方案 | 來源 |
|------|------|
| 注入 webglcontextlost/restored 事件監聽器 | Technical Artist, Frontend Developer |
| WebGL memory tracker（monkey-patch texImage2D） | Technical Artist |
| Draw call / state change 計數器 | Technical Artist |
| Context loss 區分恢復 vs 崩潰（5s timeout） | Frontend Developer |
| Unity WebGL 載入偵測（loading bar 消失 / SSIM 穩定） | Unity Architect |
| Unity 場景切換黑屏期 ≠ 異常（已知 transition 容忍） | Unity Architect |
| Screenshot observer effect 量化 + 自適應頻率 | Technical Artist |

### 參考 URL

- Khronos Handling Context Lost：https://wikis.khronos.org/webgl/HandlingContextLost
- WEBGL_lose_context extension：https://registry.khronos.org/webgl/extensions/WEBGL_lose_context/
- webgl-memory（VRAM tracking）：https://github.com/HIABRE/webgl-memory
- Figma webgl-profiler：https://github.com/figma/webgl-profiler

---

## 12. 探索策略與覆蓋率

**共識程度**：★★★☆☆

### 問題摘要

- 探索無明確停止條件（盲跑 N 分鐘）
- 無覆蓋率指標定義
- 無 exploration/exploitation balance
- 三階段（Explore → Validate → Test）轉換無量化條件

### 建議方案

| 方案 | 來源 |
|------|------|
| 分層覆蓋率：screen_visit_rate / flow_edge_coverage / invariant_trigger_rate | Workflow Optimizer |
| Curiosity-Driven Q-Learning（tabular，state=screen_id） | AI Engineer |
| Coverage-Driven Exploration（Go-Explore 式 inverse visit count） | Level Designer |
| Phase Readiness Advisor（系統提議、人工確認） | Workflow Optimizer |
| Player Persona profiles（newbie/speedrunner/afk/stress） | Game Designer |
| Action prioritization（未測試元素優先） | Level Designer |

### 參考 URL

- WebExplor（Curiosity Q-learning, 3466 failures）：https://arxiv.org/pdf/2103.06018
- Go-Explore for 3D Game Environments：https://www.microsoft.com/en-us/research/publication/go-explore-complex-3d-game-environments-for-automated-reachability-testing/
- SMART（Coverage-Aware Game Playtesting）：https://arxiv.org/html/2512.12706v1
- TITAN（LLM-driven MMORPG Testing, 95% 完成率）：https://arxiv.org/html/2509.22170

---

## 13. 跨遊戲知識複用與 Onboarding

**共識程度**：★★★☆☆

### 建議方案

| 方案 | 來源 |
|------|------|
| `knowledge/_shared/` 共通模板（login/popup/loading） | Software Architect (top) |
| Lightweight bootstrap（只填 url+title → 自動探索產出初版 YAML） | Rapid Prototyper |
| `uv run demo` 一行指令體驗（零 Vision 模式） | Rapid Prototyper |
| ADR（Architecture Decision Records）解決文件分裂 | Codebase Onboarding |
| Cost Boundary 表（哪些模組有 API 成本） | Codebase Onboarding |
| Game-agnostic patterns 複用 | Software Architect (top) |

### 參考 URL

- AWS Game Testing Agent（game-agnostic KB）：https://aws.amazon.com/blogs/gametech/building-an-ai-game-testing-agent-with-amazon-bedrock/
- KLPEG（跨版本知識複用）：https://doi.org/10.48550/arxiv.2511.02534
- uv CLI 開發模式：https://docs.astral.sh/uv/guides/tools/

---

## 全域優先級總覽

### P0 — 立即執行（1-3 天，極高 ROI）

| # | 項目 | 工作量 | 理由 |
|---|------|--------|------|
| 1 | `finish()` 加 verdict + exit code | 2-5 行 | CI 化前置條件 |
| 2 | Knowledge YAML atomic write + .bak | 10 行 | 資料安全，修復成本極低 |
| 3 | Vision per-session hard cap | 20 行 | 防災難性花費 |
| 4 | screen_id pHash pre-filter | 30 行 + imagehash | 知識累積的地基 |
| 5 | Image resize/ROI crop preprocessing | 30 行 | token -40~70% |

### P1 — 短期（1-2 週）

| # | 項目 | 理由 |
|---|------|------|
| 6 | Circuit breaker for Vision gateway | 故障時 session 不卡死 |
| 7 | PaddleOCR L1.5 確定性數值讀取 | Oracle 可靠性、成本降低 |
| 8 | Unit test CI pipeline（GitHub Actions） | 回歸防護 |
| 9 | structlog + session correlation ID | 解鎖除錯能力 |
| 10 | filelock 併發寫入保護 | 多 session 場景安全 |
| 11 | L1 崩潰偵測 Smoke Test script | 最高 ROI 自動化測試 |

### P2 — 中期（1-2 月）

| # | 項目 | 理由 |
|---|------|------|
| 12 | Golden Dataset + Oracle precision 量化 | 證明系統有效的最低要求 |
| 13 | Confidence 雙向機制（Beta-Bernoulli 或 success/failure count） | 知識品質 |
| 14 | 跨 session 趨勢聚合（RunAggregator） | 回歸測試有趨勢可看 |
| 15 | Pydantic schema validation | YAML 格式錯誤 fail-fast |
| 16 | 覆蓋率指標 + 階段轉換條件 | 探索有停止條件 |
| 17 | WebGL context loss 事件注入偵測 | 偵測覆蓋率 100% |
| 18 | Oracle Feedback Loop（結構化 dismiss） | Oracle precision 持續改善 |

### P3 — 長期路線圖

| # | 項目 |
|---|------|
| 19 | DINOv2 screen embedding + sqlite-vec |
| 20 | Multi-model semantic router |
| 21 | Curiosity-driven Q-Learning 探索 |
| 22 | Knowledge Graph 化（networkx + typed edges） |
| 23 | 跨遊戲 shared knowledge layer |
| 24 | Game Simulator Adapter（VCR record-replay） |
| 25 | 多 Agent 協作探索（cMarlTest 架構） |

---

## 附錄：角色 × 主題交叉索引

| 主題 | 提及角色數 | 核心角色 |
|------|-----------|----------|
| screen_id 穩定化 | 12+ | Evidence Collector, AI Engineer, Model QA, Software Architect, Level Designer |
| Oracle/Vision 可靠性 | 10+ | Reality Checker, Evidence Collector, Prompt Engineer, Model QA, Multi-Agent |
| 儲存安全（atomic/lock） | 8+ | Database Optimizer, Backend Architect, SRE, Governance, Incident Response, Workflow |
| Vision 成本/韌性 | 10+ | Performance Benchmarker, API Tester, Backend Architect, SRE, Autonomous Optimization |
| CI / Pass-Fail | 8+ | Test Automation, Workflow Optimizer, DevOps, Governance, Reality Checker |
| 可觀測性 | 5+ | Backend Architect, Multi-Agent, SRE, Incident Response, Autonomous Optimization |
| 座標/Grounding | 6+ | Software Architect, Frontend Developer, Code Reviewer, Model QA, Tool Evaluator |
| 知識品質閘門 | 5+ | ZK Steward, Software Architect, Model QA, Minimal Change |
| 探索策略 | 5+ | AI Engineer, Level Designer, Workflow Optimizer, Game Designer |
| WebGL 專用 | 4 | Technical Artist, Frontend Developer, Unity Architect |

---

*本報告綜合 40+ 份跨角色審查建議，以主題聚合、優先級排序、參考 URL 保留的方式呈現。每項建議的原始細節請參閱 `docs/agent_suggestions/` 對應批次文件。*
