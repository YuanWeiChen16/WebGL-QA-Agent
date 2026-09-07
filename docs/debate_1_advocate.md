# 正方論述：Vision-Driven Black-Box + CDP Profiling 是 WebGL 遊戲的最強 QA 方法論

## 一、為什麼這套方法論對 WebGL 遊戲特別強大

### 1.1 WebGL 遊戲的根本測試困境

WebGL 遊戲有一個傳統 QA 無法迴避的結構性問題：**渲染結果只存在於 GPU → canvas → 像素**。不同於 DOM-based 應用可以透過 selector 查詢 UI 狀態，WebGL 遊戲的所有視覺輸出都是一片不可查詢的像素海洋。這代表：

- 沒有 DOM 元素可以 `querySelector`
- 沒有 accessibility tree 可以斷言
- 遊戲狀態封裝在 JavaScript heap 裡，外部無法直接讀取
- 第三方遊戲通常不提供原始碼或測試 hook

本框架的核心洞見是：**既然人類 QA 測試員是用眼睛看螢幕、用滑鼠鍵盤操作，那 AI agent 也可以**。`GameBrowser`（browser.py）提供了完整的人類操作模擬介面——`click`（第 115 行）、`drag`（第 127 行）、`key_press`（第 136 行）——而 `vision.py` 的 Claude Vision API 呼叫則扮演「眼睛」的角色，透過 `tool_use` 結構化 schema 保證每次分析都回傳可程式化處理的 JSON（第 54-80 行的 `CORE_SCHEMA_PROPERTIES`）。

### 1.2 CDP：比「看」更深的觀測層

純視覺方法的侷限在於看不到效能數據。本框架透過 Chrome DevTools Protocol (CDP) 補足了這個盲點：

- **`PerfProfiler`**（perf_profiler.py）直接透過 `Performance.getMetrics`（第 73 行）取得 FPS、JS heap、DOM nodes、layout count、script duration
- **`NetworkAnalyzer`**（network_analyzer.py）透過 `Network.enable`（第 42 行）攔截所有網路請求，分類資源類型（第 125-144 行的 `_classify_resource`）
- **CPU profiling** 透過 `Profiler.start` / `Profiler.stop`（第 100-143 行）取得 top 20 最耗時函式
- **記憶體洩漏偵測** 透過 5 次取樣比對 heap 成長（`get_memory_snapshot`，第 146-163 行）

這創造了一個「視覺 + 效能 + 網路」的三維觀測空間，遠超任何單一維度的測試方法。

### 1.3 零侵入性 = 適用於任何 WebGL 遊戲

關鍵設計決策：**不需要修改受測遊戲的任何一行程式碼**。`GameBrowser.launch()`（browser.py 第 26-60 行）只需要一個 URL。這意味著：

- 可以測試競品遊戲
- 可以測試已上線且不可修改的版本
- 可以測試第三方 SDK 嵌入的遊戲
- 不存在「測試 hook 引入了 observer effect」的問題

---

## 二、相較傳統 QA 的獨特優勢

### 2.1 vs 手動測試

| 面向 | 手動 QA | 本框架 |
|------|---------|--------|
| 一致性 | 測試員疲勞、遺漏 | 每次 observe cycle 完全一致 |
| 效能感知 | 「感覺有點卡」 | 精確到 `fps: round(fps, 1)`（perf_profiler.py 第 89 行） |
| 回歸能力 | 依賴記憶 | SSIM 比對 `compute_ssim`（perceiver.py 第 34-59 行）提供數學化的視覺回歸 |
| 凍結偵測 | 主觀判斷 | `is_frozen(prev, curr, threshold=0.995)`（perceiver.py 第 73 行）確定性判定 |
| 規模化 | 線性增加人力 | 同一套腳本跑 N 個遊戲 |

### 2.2 vs 單元測試

單元測試需要原始碼。對於：
- 混淆後的 production build
- 第三方遊戲引擎（Unity WebGL、Cocos）的輸出
- 只拿到部署 URL 的外包團隊

單元測試**根本不可行**。而本框架只要一個 URL 就能啟動完整 QA 流程。

更重要的是，單元測試驗證的是「程式碼邏輯是否正確」，但無法驗證「玩家看到的畫面是否正確」。一個通過所有單元測試的遊戲，仍然可能出現：渲染異常、shader 錯誤、UI 元素遮擋、動畫凍結——這些只有視覺層才能捕捉。

### 2.3 vs 引擎內嵌監控

Unity/Unreal 的內建 profiler 功能強大，但：

1. **只在開發環境可用**——production build 通常移除了 profiler
2. **不是黑箱**——需要引擎存取權限
3. **看不到瀏覽器層**——WebGL 特有的問題（WebAssembly 記憶體限制、SharedArrayBuffer 限制、瀏覽器 GC 干擾）在引擎 profiler 裡是盲區

本框架的 CDP 層觀測的是**瀏覽器實際行為**，而非引擎的理想模型。`NetworkAnalyzer.get_js_css_coverage()`（network_analyzer.py 第 146-246 行）能發現引擎完全不知道的問題：例如載入了 2MB 的 JavaScript 但只用了 30%。

---

## 三、視覺回歸 + 效能指標結合如何創造更完整的 QA 視野

### 3.1 因果鏈追蹤

單看 FPS 下降，你不知道為什麼。單看畫面變化，你不知道代價多大。結合兩者：

```
畫面切換（Vision 偵測 screen_id 變化）
  → FPS 從 60 降到 30（PerfProfiler.measure_fps，第 165-214 行）
  → CPU profile 顯示 renderParticles 佔 40% self-time（stop_cpu_profile，第 104-144 行）
  → 同時 heap 成長 15MB（get_memory_snapshot，第 146-163 行）
  → 結論：粒子系統在新場景有效能問題且疑似記憶體洩漏
```

這種因果推理在任何單一維度的工具中都無法完成。

### 3.2 視覺回歸作為效能異常的早期信號

`perceiver.py` 的 `is_frozen()` 函式（第 73-74 行）使用 SSIM > 0.995 作為凍結判定。這比 FPS 監控更快：

- FPS 指標需要至少 1 秒的取樣窗口（`asyncio.sleep(1.0)`，perf_profiler.py 第 77 行）
- SSIM 比對是即時的——兩幀之間就能判定

當 `is_frozen()` 觸發但 FPS 仍顯示 60 時，代表遊戲仍在跑 render loop 但畫面沒有變化——這是邏輯凍結（game logic frozen）而非渲染凍結（render frozen），是一種只有視覺+效能結合才能鑑別的 bug 類型。

### 3.3 知識累積形成複合價值

`KnowledgeBase`（knowledge_base.py）統一了靜態知識（systems YAML、flow_graph、problems）和動態 runtime 學習（`add_runtime_screen`，第 512 行；`add_runtime_transition`，第 536 行；`add_bug`，第 567 行）。這意味著：

- 第一次跑發現的 bug 會記錄到 `_runtime_data["bugs"]`
- 第二次跑可以透過 `find_solution(symptoms)` （第 169-215 行）比對已知問題
- 跨 session 累積的 flow graph 讓 agent 對遊戲結構的理解越來越完整
- `get_path(from_node, to_node)`（第 341-384 行）的 BFS 導航越來越準確

這是一種**學習型 QA**——越跑越強，而非每次從零開始。

---

## 四、為常見批評辯護

### 4.1「速度慢」

**事實澄清**：慢的是 Vision LLM 呼叫，而非整個系統。

框架已經做了明確的分層設計：
- **確定性快速層**（零 LLM 成本）：`is_frozen()`、`is_blank_screen()`、`pixel_diff_ratio()`、所有 CDP 指標——這些在毫秒內完成
- **Vision 層**（慢但智慧）：只在需要理解畫面語義時呼叫

`GameSession`（agent.py）的 `observe()` 方法先跑確定性偵測，只在必要時才觸發 Vision。這不是「每幀都呼叫 LLM」——這是事件驅動的智慧觀測。

而且，WebGL 遊戲的 QA 目標不是「即時反應」——是「發現 bug」。即使一個完整 session 需要 10 分鐘，它能在無人值守的情況下持續運行，比一個 8 小時工作日但需要人全程看著的手動 QA 高效得多。

### 4.2「不精確」

**反駁**：精確度取決於你問的問題。

- 「FPS 是否低於 30？」—— `PerfProfiler.get_performance_metrics()` 回傳 `round(fps, 1)`（第 89 行），這比任何人類感知都精確
- 「是否有記憶體洩漏？」—— `heap_growth_mb > 10.0`（第 162 行）是一個明確的數學判定
- 「畫面是否凍結？」—— SSIM > 0.995 是確定性的

Vision 層確實有非確定性，但它處理的是**本質非確定性的問題**——「畫面上是什麼？」這個問題本身就沒有確定性的答案（不同人看同一畫面也會有不同描述）。用 LLM 處理本質模糊的問題，用確定性邏輯處理精確問題——這是正確的分層。

### 4.3「Token 昂貴」

**成本分析**：

一次 Vision 呼叫（截圖分析）≈ 2000-3000 tokens。假設一個 session 100 步，其中 20% 觸發 Vision = 20 次呼叫 ≈ 50K tokens ≈ US$0.15（以 Claude Sonnet 計）。

對比：
- 一個 QA 測試員一小時的薪資
- 一次 production bug 造成的玩家流失
- 部署一套引擎內嵌監控系統的工程成本

US$0.15 / session 是極其便宜的。

### 4.4「非確定性」

**這是特性，不是缺陷。**

真正的遊戲 bug 往往是非確定性的——race condition、記憶體相關的偶發崩潰、特定操作序列才觸發的異常。一個完全確定性的測試系統只能驗證「已知的已知」，而 Vision-driven agent 能透過探索性行為發現「未知的未知」。

`KnowledgeBase.add_runtime_transition()`（第 536-565 行）的 confidence 系統就是為此設計的——重複觀測到的 transition 會從 "low" 升到 "medium" 再到 "high"，讓系統自然地從非確定性觀測中萃取出確定性知識。

---

## 五、預先回應：「這套方法無法驗證遊戲玩法的正確性」

反方可能會說：「Vision 只能看到畫面表象，無法真正理解遊戲邏輯是否正確——例如傷害計算是否準確、掉落機率是否符合設計。」

**我的回應**：

1. **框架已經有 Oracle 機制**。`oracle.py` 模組（由 agent.py 第 65 行 `self.oracle = Oracle(config=self.config)` 引入）負責功能正確性驗證。它讀取 `game_info.yaml` 宣告的 invariants，比對 Vision 讀到的畫面數值（分數、金幣、等級），確認動作前後狀態是否符合預期。這是確定性的——不呼叫 Vision，只做數學比對。

2. **Knowledge base 的 `find_system_for_task`（第 230-260 行）和 `get_action_for_task`（第 285-319 行）** 提供了結構化的動作序列驗證——系統知道「升級」動作應該讓等級 +1，如果 Vision 讀到等級沒變，就是 bug。

3. **更根本的反駁**：沒有任何 QA 方法能從外部驗證內部機率表是否正確——這需要白箱存取。但我們能驗證的是「執行升級後等級確實提升了」「扣血後生命確實減少了」這類可觀測的因果關係。這已經比「看了一眼好像沒問題」的手動 QA 強得多。

框架的定位從來不是「取代所有測試方法」——而是填補一個其他方法無法觸及的空白：**對不可修改的 WebGL 遊戲進行自動化、可重複、持續學習的黑箱 QA**。在這個特定問題空間中，它是目前最有效的方法論。

---

## 結語

Vision-driven black-box + CDP profiling 不是一個折衷方案——它是對 WebGL 遊戲這個特殊問題域的**正確設計回應**。當你面對的是一個只輸出像素的黑箱、沒有原始碼、無法注入 hook，而你需要驗證它的視覺正確性和效能健康度時，這套方法論提供了：

1. 唯一可行的自動化路徑（純黑箱）
2. 多維度觀測（視覺 + 效能 + 網路）
3. 累積學習能力（KnowledgeBase）
4. 成本效益極高的確定性/智慧分層

代價是 Vision 呼叫的延遲和少量 token 成本。這是一個極其划算的 trade-off。
