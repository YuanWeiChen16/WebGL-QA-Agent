# Debate 4：統一視覺 QA 狀態與效能期望的知識庫策略

> 設計目標：將「遊戲目前在哪個畫面」與「這個畫面效能應該長什麼樣」統一在同一個知識系統中，
> 讓 QA agent 能同時判定「功能正確性」和「效能健康度」。

---

## 1. 效能基線如何編碼到 KB 中

### 1.1 設計原則

效能基線必須是**場景粒度**（per-screen / per-state），而非全局單一閾值。
理由：WebGL 遊戲的 lobby 可能穩定 60 FPS / 80 MB，但戰鬥畫面可能合理地降到 45 FPS / 200 MB。
全局閾值會產生大量誤報（lobby 超標）或漏報（戰鬥中洩漏被全局均值掩蓋）。

### 1.2 基線結構

每個「視覺狀態」（screen_id）擁有一個 `perf_envelope`，定義該狀態的效能預算：

```yaml
# knowledge/<game>/perf_baselines.yaml
version: 1
defaults:
  fps:
    target: 60
    warning_threshold: 45
    critical_threshold: 30
    measurement_window_s: 5
  memory:
    heap_budget_mb: 256
    growth_rate_mb_per_min: 2.0  # 超過即為洩漏嫌疑
    leak_confirm_duration_s: 60
  load_time:
    target_s: 5.0
    critical_s: 15.0
  bundle:
    max_total_mb: 20
    max_single_asset_mb: 5

screens:
  lobby:
    perf_envelope:
      fps: {target: 60, warning: 55, critical: 40}
      memory: {heap_budget_mb: 120, growth_rate_mb_per_min: 0.5}
      load_time: {target_s: 3.0, critical_s: 8.0}
    notes: "靜態 UI 為主，FPS 應穩定接近 vsync"

  gameplay_battle:
    perf_envelope:
      fps: {target: 60, warning: 40, critical: 25}
      memory: {heap_budget_mb: 300, growth_rate_mb_per_min: 5.0}
      load_time: {target_s: 2.0, critical_s: 5.0}
    notes: "高粒子、多物件，允許偶爾掉幀但不應持續低於 40"

  upgrade_overlay:
    perf_envelope:
      fps: {target: 60, warning: 50, critical: 35}
      memory: {heap_budget_mb: 150, growth_rate_mb_per_min: 1.0}
      load_time: {target_s: 1.0, critical_s: 3.0}
    notes: "覆蓋層不應拖垮底層 FPS"
```

### 1.3 歷史趨勢

歷史趨勢存放在 runtime layer（`knowledge.yaml` 的延伸），不混入靜態基線：

```yaml
# knowledge/<game>/knowledge.yaml 內的 perf_history 區段
perf_history:
  lobby:
    samples:
      - {timestamp: "2025-07-10T14:30:00", fps_avg: 59.2, heap_mb: 98, env: "chrome-126-win"}
      - {timestamp: "2025-07-11T09:15:00", fps_avg: 58.8, heap_mb: 102, env: "chrome-126-win"}
    trend:
      fps_7d_avg: 59.0
      heap_7d_avg_mb: 100
      heap_7d_growth_rate: 0.3  # MB/min 七日均值
  gameplay_battle:
    samples:
      - {timestamp: "2025-07-10T14:35:00", fps_avg: 48.1, heap_mb: 245, env: "chrome-126-win"}
    trend:
      fps_7d_avg: 47.5
      heap_7d_avg_mb: 240
      heap_7d_growth_rate: 3.2
```

---

## 2. 適應性學習：「此場景通常用 X MB 和 Y FPS」

### 2.1 方案概述

KB 可選擇性地從 runtime 採集累積統計，自動更新 `trend` 區段，
並在趨勢偏離靜態基線時產生 advisory（非強制 fail）。

### 2.2 優點

| 面向 | 效益 |
|------|------|
| 環境適應 | 不同硬體 / 瀏覽器版本的「正常 FPS」不同，學習後避免硬體差異誤報 |
| 漸進退化偵測 | 靜態閾值可能太寬鬆，但趨勢能捕捉「上週 58 FPS → 這週 52 FPS」的漸進滑坡 |
| 冷啟動輔助 | 新場景首次跑完後自動建立 baseline，省去人工填寫 |
| 版本回歸 | 比較 build N vs build N-1 的趨勢差異，偵測引入的退化 |

### 2.3 缺點與風險

| 風險 | 說明 | 緩解策略 |
|------|------|----------|
| **噪音數據** | 單次 GC spike、背景 tab、OS 排程都會汙染樣本 | 使用 P50/P95 而非 mean；丟棄極端離群值（IQR 法） |
| **環境差異** | CI 的 headless GPU 與開發者 RTX 4090 差距大 | 每筆樣本標記 `env` fingerprint，分群統計 |
| **冷啟動問題** | 前 N 次觀測不足以建立可靠基線 | 設定 `min_samples: 5`，不足時退回靜態 defaults |
| **基線漂移** | 如果遊戲版本升級確實改變效能特性，舊趨勢會誤導 | 引入 `baseline_version` 標記，版本跳號時重置趨勢 |
| **自我降級** | 如果 bug 持續存在，趨勢會「適應」壞的效能當新常態 | 趨勢永遠與靜態基線交叉驗證；靜態基線是 hard floor |

### 2.4 推薦策略：雙層門檻

```
判定 = max(靜態基線閾值, 趨勢基線 - 容許退化幅度)
```

- **靜態基線**（人工維護）= 「這個畫面絕對不能低於 X」的 hard floor
- **趨勢基線**（自動學習）= 「最近 7 天的 P50 是 Y，偏離 >15% 算異常」的 soft ceiling

兩者取嚴格者。這樣既不會因為學習到壞數據而放寬標準，也不會因為靜態閾值太寬鬆而漏掉漸進退化。

---

## 3. 視覺狀態 × 效能概況：狀態機 + 效能包絡線

### 3.1 概念模型

```
┌──────────────────────────────────────────────────────────┐
│                    Flow Graph (已有)                       │
│  login ──▶ lobby ──▶ gameplay_battle ──▶ upgrade_overlay  │
│                        ▲                       │          │
│                        └───────────────────────┘          │
└──────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              Perf Envelope (新增)                          │
│  每個 node 攜帶:                                          │
│    - expected_fps_range: [warning, target]                │
│    - expected_heap_range: [normal, budget]                │
│    - expected_load_time: [target, critical]               │
│    - transition_cost: 轉場時允許的暫態                     │
└──────────────────────────────────────────────────────────┘
```

### 3.2 轉場效能成本

狀態轉換（edge）本身也有效能特性：從 lobby → battle 的 loading 期間，FPS 可能暫時降到 10-15，
記憶體可能瞬間飆升 50 MB——這是「合理暫態」而非 bug。

```yaml
# flow_graph.yaml 的 edge 擴展
edges:
  - from: lobby
    to: gameplay_battle
    trigger: "點擊開始戰鬥"
    transition_perf:
      expected_duration_s: 3.0
      fps_during_transition: {min_acceptable: 5, note: "loading 畫面允許極低 FPS"}
      heap_spike_mb: 80  # 允許暫態增長
      settle_time_s: 2.0  # 轉場後多久才開始嚴格檢查目標 FPS
```

### 3.3 狀態機驅動的效能監控邏輯

```python
# 概念性虛擬碼
class PerfMonitor:
    def on_screen_change(self, old_screen: str, new_screen: str):
        """轉場時寬鬆，穩定後嚴格。"""
        edge = self.kb.get_edge(old_screen, new_screen)
        self.grace_period_until = now() + edge.transition_perf.settle_time_s
        self.current_envelope = self.kb.get_perf_envelope(new_screen)

    def evaluate(self, metrics: dict) -> list[Issue]:
        if now() < self.grace_period_until:
            # 轉場寬鬆模式：只檢查極端異常（完全凍結、heap 爆破）
            return self._check_catastrophic_only(metrics)
        else:
            # 穩態嚴格模式：用完整 perf_envelope 評估
            return self._check_full_envelope(metrics, self.current_envelope)
```

---

## 4. 統一 YAML Schema

### 4.1 完整 `perf_baselines.yaml` Schema

```yaml
# knowledge/<game>/perf_baselines.yaml
# 靜態效能基線，人工維護，版本控制

version: 1  # schema 版本

# 全局預設值（任何 screen 未指定欄位時回退此處）
defaults:
  fps:
    target: 60                    # int, 目標 FPS
    warning_threshold: 45         # int, 低於此產生 warning
    critical_threshold: 30        # int, 低於此產生 critical
    measurement_window_s: 5       # float, 每次取樣窗口
    percentile: 5                 # int, 用第 N 百分位（P5）評估 worst-case
  memory:
    heap_budget_mb: 256           # float, 最大允許堆積
    growth_rate_mb_per_min: 2.0   # float, 超過即為洩漏嫌疑
    leak_confirm_duration_s: 60   # float, 需持續多久才確認洩漏
    gc_spike_tolerance_mb: 20     # float, GC 回收後的暫態允許
  load_time:
    target_s: 5.0                 # float
    critical_s: 15.0              # float
  bundle:
    max_total_mb: 20              # float
    max_single_asset_mb: 5        # float
    dead_code_warning_pct: 30     # float

# 環境正規化：定義已知環境 fingerprint 的修正係數
environments:
  ci_headless:
    fingerprint_match: "headless.*chrome"
    fps_multiplier: 0.7           # CI headless 通常比有頭慢 30%
    memory_multiplier: 1.0
  dev_desktop:
    fingerprint_match: "chrome.*gpu"
    fps_multiplier: 1.0
    memory_multiplier: 1.0

# 每場景效能包絡線
screens:
  # key = flow_graph.yaml 中的 node id
  lobby:
    perf_envelope:
      fps:
        target: 60
        warning: 55
        critical: 40
      memory:
        heap_budget_mb: 120
        growth_rate_mb_per_min: 0.5
      load_time:
        target_s: 3.0
        critical_s: 8.0
      gpu:
        draw_calls_budget: 100
        texture_memory_mb: 64
    visual_indicators:
      # 連結視覺 QA：這些是此畫面應有的視覺特徵
      - "背景動畫平滑"
      - "UI 按鈕可見且未重疊"
    known_perf_issues:
      - id: lobby_particle_leak
        description: "粒子系統在 lobby 閒置 5 分鐘後不回收"
        status: investigating
        workaround: "定期切換場景觸發 GC"

  gameplay_battle:
    perf_envelope:
      fps:
        target: 60
        warning: 40
        critical: 25
      memory:
        heap_budget_mb: 300
        growth_rate_mb_per_min: 5.0
      load_time:
        target_s: 2.0
        critical_s: 5.0
      gpu:
        draw_calls_budget: 500
        texture_memory_mb: 256
    # 時間模式：此場景已知的效能隨時間變化
    temporal_patterns:
      - type: expected_degradation
        description: "戰鬥持續 > 3 分鐘後粒子累積導致 FPS 微降"
        after_s: 180
        fps_adjustment: -5      # 允許額外 -5 FPS
        memory_adjustment_mb: 30  # 允許額外 +30 MB
      - type: known_growth
        description: "物件池預熱期前 30 秒記憶體快速增長是正常的"
        window_s: [0, 30]
        growth_rate_override_mb_per_min: 15.0

  upgrade_overlay:
    perf_envelope:
      fps:
        target: 60
        warning: 50
        critical: 35
      memory:
        heap_budget_mb: 150
        growth_rate_mb_per_min: 1.0
      load_time:
        target_s: 1.0
        critical_s: 3.0
```

### 4.2 `flow_graph.yaml` 擴展（轉場效能）

```yaml
# 在既有 edges 上增加 transition_perf 欄位
edges:
  - from: login
    to: lobby
    trigger: "輸入帳號 + 確認"
    transition_perf:
      expected_duration_s: 5.0
      fps_during_transition: {min_acceptable: 0, note: "loading screen"}
      heap_spike_mb: 100
      settle_time_s: 3.0

  - from: lobby
    to: gameplay_battle
    trigger: "點擊開始"
    transition_perf:
      expected_duration_s: 3.0
      fps_during_transition: {min_acceptable: 5}
      heap_spike_mb: 80
      settle_time_s: 2.0

  - from: gameplay_battle
    to: upgrade_overlay
    trigger: "任務文字含 升級"
    transition_perf:
      expected_duration_s: 0.5
      fps_during_transition: {min_acceptable: 30}
      heap_spike_mb: 10
      settle_time_s: 0.5
```

### 4.3 Runtime 學習層（`knowledge.yaml` 擴展）

```yaml
# knowledge/<game>/knowledge.yaml — 自動維護，不 commit（或 .gitignore）
perf_runtime:
  config:
    min_samples_for_trend: 5      # 不足時退回靜態 defaults
    trend_window_days: 7
    outlier_iqr_multiplier: 1.5   # IQR 法去極端值
    baseline_version: "1.2.0"     # 遊戲版本跳號時重置

  screens:
    lobby:
      samples:
        - timestamp: "2025-07-10T14:30:00+08:00"
          env: "chrome-127-win-rtx3060"
          fps: {avg: 59.2, p5: 55.1, p95: 60.0}
          memory: {heap_mb: 98, growth_rate: 0.3}
          duration_s: 30
        - timestamp: "2025-07-11T09:15:00+08:00"
          env: "chrome-127-win-rtx3060"
          fps: {avg: 58.8, p5: 54.2, p95: 59.8}
          memory: {heap_mb: 102, growth_rate: 0.4}
          duration_s: 45
      computed_trend:  # 由系統自動計算
        fps_p50: 59.0
        fps_p5: 54.6
        heap_p50_mb: 100
        growth_rate_p50: 0.35
        last_updated: "2025-07-11T09:15:00+08:00"
        sample_count: 2
        confidence: low  # < min_samples

    gameplay_battle:
      samples:
        - timestamp: "2025-07-10T14:35:00+08:00"
          env: "chrome-127-win-rtx3060"
          fps: {avg: 48.1, p5: 32.0, p95: 58.2}
          memory: {heap_mb: 245, growth_rate: 3.2}
          duration_s: 120
      computed_trend:
        fps_p50: 48.1
        fps_p5: 32.0
        heap_p50_mb: 245
        growth_rate_p50: 3.2
        last_updated: "2025-07-10T14:35:00+08:00"
        sample_count: 1
        confidence: none  # < min_samples，退回 defaults
```

### 4.4 查詢介面設計

```python
class KnowledgeBase:
    # --- 新增的效能查詢 API ---

    def get_perf_envelope(self, screen_id: str, env: str = None) -> dict:
        """取得指定場景的效能包絡線。
        
        優先順序：
        1. perf_baselines.yaml 中 screens[screen_id].perf_envelope
        2. 若有 env 修正，套用 environments[env].multiplier
        3. 若未指定場景，回退 defaults
        
        Returns:
            {fps: {target, warning, critical},
             memory: {heap_budget_mb, growth_rate_mb_per_min},
             load_time: {target_s, critical_s}}
        """
        ...

    def get_adaptive_threshold(self, screen_id: str, metric: str, env: str = None) -> float:
        """取得適應性閾值 = max(靜態閾值, 趨勢 - 容許退化)。
        
        Args:
            metric: "fps_warning" | "fps_critical" | "heap_budget" | ...
        """
        ...

    def get_transition_perf(self, from_screen: str, to_screen: str) -> dict:
        """取得轉場效能預期（settle_time, spike 容許等）。"""
        ...

    def get_temporal_patterns(self, screen_id: str) -> list[dict]:
        """取得時間模式（已知退化、預熱期等）。"""
        ...

    def record_perf_sample(self, screen_id: str, metrics: dict, env: str) -> None:
        """記錄一筆效能樣本到 runtime layer，觸發趨勢重算。"""
        ...

    def evaluate_perf(self, screen_id: str, metrics: dict, 
                      elapsed_s: float = 0, env: str = None) -> list[dict]:
        """綜合評估：靜態 + 適應性 + 時間模式 + 轉場寬限。
        
        Returns:
            [{severity: "critical"|"warning"|"info",
              category: "fps"|"memory"|"load_time",
              message: str,
              value: float,
              threshold: float}]
        """
        ...
```

---

## 5. 適應性閾值 vs 靜態閾值

### 5.1 比較表

| 面向 | 靜態閾值 | 適應性閾值 |
|------|----------|------------|
| 定義 | 人工在 YAML 中硬編碼 | 從歷史 P50/P5 自動計算 |
| 優點 | 穩定、可預測、不會自我降級 | 環境自適應、捕捉漸進退化 |
| 缺點 | 跨環境誤報、需頻繁人工調整 | 噪音汙染、冷啟動無效、可能適應壞數據 |
| 適用場景 | 「絕對不能低於 X」的 hard floor | 「相比上週是否退化」的 drift detection |

### 5.2 百分位 vs 絕對值

- **FPS**：用 P5（最差 5% 的幀）評估 worst-case，而非 avg。
  - 原因：avg 60 FPS 但 P5 = 15 FPS 代表嚴重卡頓，用戶可感知。
- **Memory**：用 P95（最高 5% 的峰值）評估 heap 壓力。
  - 原因：GC 回收後 heap 會降低，取峰值才能抓到壓力點。
- **Load time**：用絕對值（秒），因為用戶感知是絕對的。

### 5.3 首次執行處理（Cold Start）

```
if sample_count < min_samples_for_trend:
    # 退回靜態基線
    threshold = static_baseline[metric]
    confidence = "low"
    advisory = "尚未累積足夠數據，使用靜態預設值"
else:
    # 使用適應性閾值
    threshold = max(static_floor, trend_p50 * (1 - tolerance_pct))
    confidence = "high" if sample_count >= 20 else "medium"
```

### 5.4 環境正規化

不同環境的「正常 FPS」天差地遠。解法：

1. **每筆樣本附帶 env fingerprint**：`chrome-127-win-rtx3060`
2. **趨勢分群計算**：同 env 的樣本一起統計
3. **跨 env 時套用 multiplier**：CI headless 的 FPS × 0.7 才能與 dev desktop 比較
4. **首次遇到新 env**：前 5 筆當冷啟動，退回靜態基線 × env multiplier（若已知）

```yaml
# 查詢邏輯虛擬碼
effective_threshold = static_threshold * env_multiplier
if has_enough_samples(screen, env):
    adaptive = trend_p50[screen][env] * (1 - tolerance)
    effective_threshold = max(effective_threshold, adaptive)
```

---

## 6. 時間模式處理

### 6.1 已知記憶體成長率 vs 洩漏

並非所有記憶體增長都是洩漏。需要區分：

| 模式 | 特徵 | 處理方式 |
|------|------|----------|
| **物件池預熱** | 前 30 秒快速增長 → 穩定 | `temporal_patterns.window_s` 覆蓋 growth_rate |
| **正常遊戲進程** | 隨遊戲時間線性微增（新資源載入） | 較高的 `growth_rate_mb_per_min` 允許 |
| **真正洩漏** | 持續線性/超線性增長，無上界 | 超過 `leak_confirm_duration_s` 且超過調整後的 rate → alert |

### 6.2 判定邏輯

```python
def evaluate_memory_growth(self, screen_id: str, samples_mb: list[float], 
                           elapsed_s: float, env: str = None) -> dict:
    """
    1. 取得 temporal_patterns 中的活躍模式
    2. 根據 elapsed_s 判斷目前處於哪個時間窗口
    3. 套用該窗口的 growth_rate_override
    4. 計算實際 growth_rate = (samples[-1] - samples[0]) / elapsed_minutes
    5. 比較 actual vs allowed（含 temporal adjustment）
    """
    envelope = self.get_perf_envelope(screen_id, env)
    base_rate = envelope["memory"]["growth_rate_mb_per_min"]
    
    # 檢查是否在特殊時間窗口
    patterns = self.get_temporal_patterns(screen_id)
    for pattern in patterns:
        if pattern["type"] == "known_growth":
            window = pattern["window_s"]
            if window[0] <= elapsed_s <= window[1]:
                base_rate = pattern["growth_rate_override_mb_per_min"]
                break
    
    actual_rate = calculate_rate(samples_mb, elapsed_s)
    
    if actual_rate > base_rate:
        if elapsed_s > envelope["memory"]["leak_confirm_duration_s"]:
            return {"verdict": "leak_confirmed", "rate": actual_rate, "allowed": base_rate}
        else:
            return {"verdict": "leak_suspected", "rate": actual_rate, "allowed": base_rate}
    return {"verdict": "healthy", "rate": actual_rate, "allowed": base_rate}
```

### 6.3 預期 FPS 降級

某些場景的 FPS 會隨時間合理下降（如粒子累積、物件增多）：

```yaml
temporal_patterns:
  - type: expected_degradation
    description: "30 波敵人後場景物件數增加"
    after_s: 180
    fps_adjustment: -10        # 3 分鐘後允許目標 FPS 降低 10
    memory_adjustment_mb: 50   # 允許多用 50 MB
    max_degradation:           # 但有底線
      fps_floor: 30
      memory_ceiling_mb: 400
```

判定邏輯：

```python
def get_adjusted_fps_target(self, screen_id: str, elapsed_s: float) -> int:
    envelope = self.get_perf_envelope(screen_id)
    target = envelope["fps"]["target"]
    
    for pattern in self.get_temporal_patterns(screen_id):
        if pattern["type"] == "expected_degradation" and elapsed_s > pattern["after_s"]:
            adjustment = pattern["fps_adjustment"]
            floor = pattern.get("max_degradation", {}).get("fps_floor", 
                                                           envelope["fps"]["critical"])
            target = max(target + adjustment, floor)
    
    return target
```

---

## 7. 整合架構總覽

```
knowledge/<game>/
├── game_info.yaml              # 基本資訊 + oracle invariants（已有）
├── systems/*.yaml              # UI 元素 + 操作序列（已有）
├── flow_graph.yaml             # 狀態轉換圖 + transition_perf（擴展）
├── problems/*.md               # 已知問題（已有）
├── perf_baselines.yaml         # [新增] 靜態效能基線（per-screen）
└── knowledge.yaml              # [擴展] runtime 學習：screens + perf_runtime

src/webgl_qa/
├── knowledge_base.py           # [擴展] 新增 perf 查詢 API
├── perf_profiler.py            # 採集原始數據（已有）
├── perf_report.py              # 報告生成（已有）
└── perf_evaluator.py           # [新增] 結合 KB 的效能判定引擎
```

### 7.1 數據流

```
PerfProfiler.measure_fps()  ──▶  raw metrics
NetworkAnalyzer.get_*()     ──▶  raw network data
                                      │
                                      ▼
                            PerfEvaluator.evaluate()
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                  ▼
         KB.get_perf_envelope()   KB.get_temporal()   KB.get_adaptive_threshold()
                    │                 │                  │
                    └────────┬────────┘                  │
                             ▼                          ▼
                     adjusted thresholds ◄────── trend-based floor
                             │
                             ▼
                      Issue[] (with severity)
                             │
                             ▼
                    PerfReporter.generate_*()
                             │
                             ▼
                    KB.record_perf_sample()  ──▶  runtime layer 累積
```

---

## 8. 結論與建議

1. **分離靜態 / 動態**：`perf_baselines.yaml`（人工維護，commit）vs `knowledge.yaml` 中的 `perf_runtime`（自動累積，可 gitignore）。
2. **雙層門檻**：靜態基線是 hard floor，趨勢是 drift detector。兩者取嚴格者。
3. **場景粒度**：每個 flow_graph node 都有自己的 perf_envelope，而非全局單一閾值。
4. **轉場寬限**：edge 定義 settle_time，轉場期間只查致命異常。
5. **時間模式**：用 temporal_patterns 編碼「已知的合理退化」，避免誤報。
6. **環境正規化**：env fingerprint 分群 + multiplier，跨環境可比較。
7. **冷啟動安全**：不足 min_samples 時一律退回靜態基線，不猜測。

此方案的核心哲學：**靜態基線保底，適應性學習加嚴，時間模式抵銷已知行為，環境正規化消除硬體差異。**
