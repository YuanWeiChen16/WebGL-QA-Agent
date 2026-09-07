# Review 4：知識庫策略設計評審

> 評審角色：資深遊戲 AI 工程師 / MLOps 架構師
> 評審對象：`docs/debate_4_kb_strategy.md`
> 評審框架：Prometheus/Grafana metrics 哲學、SRE SLO/SLI、Feature Store patterns、TSDB schema、Adaptive thresholds (Kayenta/Datadog)、Game Analytics 業界做法、Model-based testing、YAML best practices、Observability as Code

---

## 1. 效能基線編碼方式（§1）

### 判定：✅ 與主流一致 / 🌟 場景粒度設計優於許多遊戲 QA 工具的全局閾值

**與主流對齊之處：**

- **場景粒度（per-screen）** 完全對齊 SRE 的 SLI 設計原則——每個 user journey 有自己的 SLO，而非全系統單一指標。Prometheus 的 label-based metrics 本質上就是鼓勵 per-endpoint / per-service 的差異化閾值。
- **分層預設值 + 覆寫** 與 Grafana alerting 的 `defaults → folder-level → rule-level` 繼承模式一致。
- **measurement_window_s** 對應 Prometheus 的 `for` duration 概念——持續多久才觸發 alert。

**正面創新：**

- 將 SRE 的 SLO 概念移植到遊戲場景，每個 screen 相當於一個「服務端點」，這在遊戲 QA 領域並不常見（多數工具如 GameAnalytics 只提供全局 session 級統計）。
- `perf_envelope` 的 target/warning/critical 三級映射到 SRE 的 SLO target / burn rate alert / page，概念清晰。

**潛在問題：**

- `bundle` 基線混入了 runtime perf metrics，概念層級不同。Bundle size 是 build-time artifact，不應與 runtime FPS/memory 放在同一個 `perf_baselines.yaml`。建議拆成 `build_budget.yaml`（CI 時檢查）和 `runtime_baselines.yaml`（QA 時檢查）。

---

## 2. 適應性學習設計（§2）

### 判定：⚠️ 部分偏差——方向正確但實作細節有風險

**與主流對齊之處：**

- **雙層門檻（static floor + adaptive ceiling）** 與 Netflix Kayenta 的設計哲學一致：Kayenta 使用 canary baseline 做相對比較，但保留 absolute threshold 作為安全網。
- **IQR 去離群值** 是 Datadog anomaly detection 的標準做法。
- **min_samples 冷啟動退回** 對應 Feature Store 的 feature freshness / staleness handling。
- **baseline_version 重置** 類似 ML pipeline 的 model versioning——data schema 變更時清除舊 feature statistics。

**偏差與風險：**

| 問題 | 主流做法 | 文件做法 | 風險等級 |
|------|----------|----------|----------|
| **趨勢計算位置** | 獨立的 metrics pipeline（Prometheus recording rules / Feature Store batch job） | 嵌入 KB YAML runtime layer | ⚠️ 中 |
| **樣本儲存** | TSDB（InfluxDB/TimescaleDB）with retention policy | YAML 陣列無限增長 | ❌ 高 |
| **容許退化幅度硬編碼** | Kayenta 用統計 confidence interval，Datadog 用 EWMA | 固定 15% tolerance_pct | ⚠️ 中 |
| **單一 tolerance_pct** | 不同 metric 有不同 sensitivity（FPS 偏差 5% 可感知，heap 偏差 5% 不可感知） | 文件未區分 per-metric tolerance | ⚠️ 中 |

**建議改進：**

1. **樣本存儲必須有 retention policy**：YAML 陣列不能無限增長。建議最多保留 N=50 筆 per screen per env，或引入 ring buffer 語義，或乾脆將 raw samples 存 SQLite/JSON Lines 而非 YAML。
2. **tolerance 應 per-metric 配置**：FPS 用 10%，heap 用 20%，load_time 用 15%——反映用戶感知差異。
3. **趨勢計算應離線化**：當前設計讓 QA agent 同時負責採集、計算趨勢、做判定——職責過多。建議新增一個 `trend_updater` batch job（哪怕只是個 Python script 定期跑），將「趨勢計算」與「判定」解耦。

---

## 3. 視覺狀態 × 效能關聯（§3）

### 判定：🌟 優於主流的創新

**為什麼這是好創新：**

- 主流遊戲 QA 工具（如 GameAnalytics、Unity Performance Reporting）將效能數據視為「全局事件流」，與遊戲狀態弱關聯。它們通常只用 session 和 scene name 做最粗粒度的分群。
- Model-based testing 領域（如 GraphWalker、Spec Explorer）用狀態機描述系統行為，但通常只驗證功能正確性，不延伸到效能。
- **本文將狀態機的 edge（轉場）也納入效能建模**，這超越了 SRE 的 multi-window alert（只看 steady state）和遊戲 QA 的場景標籤（只看節點）。

**轉場效能成本（transition_perf）的價值：**

- 真實對應了遊戲中「loading 不算 bug」的領域知識。
- `settle_time_s` 是 SRE 中「deployment grace period」的遊戲版本——新部署後暫時不告警，給系統穩定的時間。
- 在 Prometheus 中，這等同於 `for: 30s` 的 alerting rule，但本文將它語義化為「轉場後等待」，對遊戲 QA 更直覺。

**潛在問題：**

- 狀態機如何知道「目前在哪個 screen」？文件假設了一個完美的 screen detector，但實際上 WebGL 遊戲的場景辨識可能模糊（overlay 可能半透明、transition 可能漸進）。建議明確定義 `screen_id` 的判定來源（截圖 classifier？URL hash？遊戲內部 telemetry？）。

---

## 4. YAML Schema 設計（§4）

### 判定：⚠️ 部分偏差——結構合理但存在 maintainability 風險

**與主流對齊之處：**

- **分離 static vs runtime** 符合 GitOps 的 `desired state (versioned)` vs `observed state (ephemeral)` 分離。
- **version 欄位** 符合 schema evolution best practice。
- **environments 正規化** 類似 Prometheus 的 relabeling rules，用 regex match + multiplier 進行跨環境正規化。

**與 YAML Best Practices 的偏差：**

| 問題 | Best Practice | 文件做法 | 嚴重度 |
|------|--------------|----------|--------|
| **嵌套深度** | YAML 不超過 4 層嵌套 | `screens.lobby.perf_envelope.fps.target` = 5 層 | ⚠️ |
| **陣列中的複雜物件** | 避免 YAML 陣列套 dict 套 list | `temporal_patterns` 每項 6+ key | ⚠️ |
| **查詢友好度** | 可用 jsonpath/jq 快速查詢 | 跨 3 個檔案（baselines + flow_graph + knowledge）才能得到完整判定所需數據 | ⚠️ |
| **單檔案大小** | 每個 YAML 檔不超過 200 行 | `perf_baselines.yaml` 在 10+ screens 時輕鬆超過 500 行 | ❌ |

**建議改進：**

1. **每場景一個檔案**：改為 `perf_baselines/<screen_id>.yaml`，每個檔案 30-50 行，便於 PR review 和 team ownership。
2. **減少嵌套**：用 flat key convention 取代深層嵌套：
   ```yaml
   # 替代方案：flat keys
   lobby.fps.target: 60
   lobby.fps.warning: 55
   lobby.fps.critical: 40
   lobby.memory.heap_budget_mb: 120
   ```
   或至少用 JSON Schema validation（`$ref`）確保結構正確。
3. **合併查詢入口**：KB 的 Python API 是正確的抽象——用戶不應直接 parse 3 個 YAML。但建議加入 schema validation（如 JSON Schema for YAML）在 CI 中驗證。

**與 Observability as Code 的對齊：**

- SLO-as-code（如 OpenSLO、Sloth）鼓勵將 SLO 定義為 YAML 並 version control——本文的 `perf_baselines.yaml` 精確符合此趨勢。
- Monitoring-as-code（Terraform provider for Datadog）鼓勵 alert threshold 可審計——符合。
- 但 OpenSLO 的 schema 更扁平，且每個 SLO 是獨立文件——本文的「所有 screens 塞一個 YAML」偏離此最佳實踐。

---

## 5. 適應性 vs 靜態閾值（§5）

### 判定：✅ 與主流一致

**與主流對齊之處：**

- **P5/P95 而非 avg** 完全對應 SRE 的「尾端延遲比平均延遲重要」——Google SRE Book 明確建議用 P99/P95 而非 mean 來設定 SLO。在遊戲中用 P5 FPS（最差 5%）和 P95 heap（最高 5%）是正確的映射。
- **max(static, adaptive)** 等同於 Datadog 的 composite monitor（anomaly detection + static threshold 聯合），兩者任一觸發即 alert。
- **環境 fingerprint 分群** 對應 Prometheus 的 label-based cardinality management——同一個 metric 用 labels 區分 env。

**做得好的地方：**

- 明確指出「用 P5 評估 FPS」而非 avg——這比 90% 的遊戲 QA 工具做得好（GameAnalytics 預設展示 mean FPS）。
- `confidence` level（none/low/medium/high）是 ML pipeline 中 data quality indicator 的標準做法。

**小問題：**

- `tolerance_pct` 用百分比比固定值好，但未考慮到 metric 的 variance。建議參考 Kayenta 的做法：用 Mann-Whitney U test 或 Kolmogorov-Smirnov 做統計假設檢定，而非簡單百分比比較。不過在 QA agent 的場景下，統計檢定可能 over-engineering——百分比法是合理的 pragmatic 選擇。

---

## 6. 時間模式處理（§6）

### 判定：🌟 優於主流的創新

**為什麼這是好創新：**

- **主流 observability 工具不具備「應用層時間語義」。** Prometheus 的 `for` duration 是固定的等待時間，不理解「遊戲戰鬥第 3 分鐘的粒子累積是正常的」。Datadog 的 anomaly detection 能學習 weekly/daily 周期，但無法編碼「場景內的時間模式」。
- **物件池預熱期建模** 在 JVM 監控中有類似概念（JIT warm-up 期的延遲不算 SLO violation），但在遊戲 QA 中將其形式化為 `temporal_patterns` with `window_s` 是新穎的。
- **FPS 降級允許 + floor** 是「error budget with hard limit」的遊戲版本：允許一定退化（consume budget），但有絕對底線（budget exhaustion = page）。

**做得好的地方：**

- 區分「物件池預熱」「正常遊戲進程」「真正洩漏」三種模式，並給出可執行的判定邏輯——這是 domain-specific observability 的典範。
- `max_degradation` 確保即使所有 temporal adjustment 都生效，也不會把閾值放寬到不合理的程度。

**潛在風險：**

| 風險 | 說明 | 建議 |
|------|------|------|
| **temporal_patterns 爆炸** | 複雜遊戲可能每場景 10+ patterns，YAML 變巨 | 設定上限（建議 ≤5 per screen），超過則重新思考場景拆分 |
| **patterns 互相衝突** | 如果兩個 pattern 的時間窗口重疊怎麼辦？ | 定義 priority / merge 策略（如：取最寬鬆者、取最嚴格者、報錯） |
| **判定邏輯與 KB 耦合** | evaluate 函數直接讀 YAML pattern 做 if/else | 建議用 Strategy Pattern 封裝，便於 unit test |

---

## 7. 整合架構（§7）

### 判定：✅ 與主流一致

**與主流對齊之處：**

- **數據流方向** 清楚：採集 → 評估 → 報告 → 累積。這是標準的 observability pipeline（collect → process → store → alert）。
- **KB 作為 config 層**（不是 data store）：效能數據的真正 store 是 `perf_runtime`，KB 只是 threshold config——對應 Prometheus 的 alerting rules 是 config 而非 data。
- **分離 Profiler（採集）、Evaluator（判定）、Reporter（呈現）** 符合 single-responsibility。

**建議改進：**

- 缺少 **feedback loop 的明確定義**：`record_perf_sample()` 之後如何觸發 `computed_trend` 的重算？同步？異步？batch？建議明確。
- 缺少 **數據 retention 策略**：`perf_runtime` 的 samples 如何 rotate？永久增長會導致 YAML parsing 越來越慢。

---

## 8. 總體評估

### 8.1 主流對齊度

| 面向 | 判定 | 說明 |
|------|------|------|
| 效能基線編碼方式 | ✅🌟 | 場景粒度 = SRE per-endpoint SLO 的正確映射 |
| 適應性學習設計 | ⚠️ | 方向正確，但樣本存儲和趨勢計算的實作需要改進 |
| 視覺狀態 × 效能關聯 | 🌟 | 狀態機 + 轉場成本是遊戲 QA 的優秀創新 |
| YAML Schema 設計 | ⚠️ | 結構合理但嵌套過深、單檔過大 |
| 適應性 vs 靜態閾值 | ✅ | P5/P95 + max(static, adaptive) 完全對齊主流 |
| 時間模式處理 | 🌟 | 形式化遊戲領域的時間語義，超越通用 observability |
| 整合架構 | ✅ | 標準 pipeline 架構，職責分離清晰 |

### 8.2 關鍵強項

1. **SRE 概念的遊戲化映射**：將 SLO/SLI/error budget 自然地翻譯到遊戲場景，不是生硬套用而是領域適配。
2. **雙層門檻避免兩難**：不用在「太敏感（誤報多）」和「太遲鈍（漏報多）」之間二選一。
3. **轉場 grace period**：真正理解遊戲的 temporal 特性，避免 loading screen 觸發效能告警。
4. **環境正規化**：承認「不同硬體的正常不同」，用 multiplier 而非 one-size-fits-all。

### 8.3 關鍵風險

1. **YAML 膨脹**：10+ screens × temporal_patterns × environments × known_issues → 單檔可能超過 1000 行。
   - **建議**：per-screen 拆檔，或至少引入 `$ref` / YAML anchors 減少重複。
2. **Runtime YAML 無限增長**：samples 陣列沒有 cap。
   - **建議**：硬性限制 max 50 samples per screen per env；超過時用 sliding window 替換最舊。
3. **缺乏 Schema Validation**：YAML 沒有 runtime type checking，打錯欄位名不會 fail fast。
   - **建議**：新增 JSON Schema 定義，在 CI 中驗證所有 `perf_baselines.yaml`。
4. **Temporal patterns 複雜度**：多個 pattern 重疊時行為未定義。
   - **建議**：定義明確的 priority / merge 規則並加入 unit test 覆蓋。

### 8.4 實作優先級建議

若要將此設計落地，建議按以下順序：

| Phase | 內容 | 理由 |
|-------|------|------|
| P0 | 靜態基線 + per-screen envelope（無 adaptive） | 最小可用版本，已能解決 80% 誤報 |
| P1 | 轉場 grace period（settle_time） | 成本低、效益高，消除 loading 期間的噪音 |
| P2 | Schema validation（JSON Schema in CI） | 防止 YAML 腐敗，越早引入越好 |
| P3 | 適應性學習（trend 計算 + dual threshold） | 需要累積足夠樣本後才有意義 |
| P4 | Temporal patterns | 最複雜，等其他層穩定後再加入 |
| P5 | 環境正規化 | 需要跨多環境測試資料驗證 multiplier 是否準確 |

### 8.5 與主流框架的具體差距清單

| 主流框架 | 本文做法 | 差距 | 建議 |
|----------|----------|------|------|
| Prometheus recording rules | 趨勢計算嵌入 KB | 無離線預計算 | 新增 batch trend updater |
| InfluxDB retention policies | YAML samples 無限增長 | 無 TTL / rotation | 加入 max_samples + sliding window |
| OpenSLO spec | 所有 SLO 塞一個檔 | 非 per-SLO file | 改為 per-screen file |
| Kayenta canary analysis | 固定 % tolerance | 無統計檢定 | 可接受——pragmatic choice |
| Feature Store freshness | min_samples fallback | 一致 | ✅ |
| Grafana alert groups | 分層 defaults → override | 一致 | ✅ |
| Game Analytics session tags | 全局 session metrics | 本文優於主流（per-screen） | 🌟 |

---

## 9. 結語

這份 KB 策略在**概念層面**是優秀的——正確地將 SRE observability 思維移植到遊戲 QA 領域，並加入了遊戲特有的時間語義和狀態機建模。

**實作層面**的主要風險在於 YAML 作為 runtime data store 的可擴展性。建議明確劃定「YAML 只存配置和靜態基線」、「runtime 數據用更適合的 storage（SQLite / JSON Lines / 簡單的 append-only file）」的邊界。

核心設計決策（場景粒度、雙層門檻、轉場 grace period、temporal patterns）都是值得保留的好設計，在遊戲 QA 領域屬於創新而非反模式。
