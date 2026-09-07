# 反方論述：WebGL QA Agent 方法論批評

## 立場聲明

本文從持懷疑態度的 QA 主管視角，對 `webgl-qa-agent` 的自動化測試方法論進行系統性批評。核心論點：**此工具在概念上有趣，但距離生產環境可靠的 QA 覆蓋率存在根本性鴻溝。**

---

## 1. 根本性局限

### 1.1 觀察者悖論：你測量的不是玩家體驗

CDP（Chrome DevTools Protocol）層級的測量本質上是**瀏覽器觀察者的視角**，而非玩家的視角。當 `PerfProfiler.measure_fps()`（第 165–214 行）透過 `Runtime.evaluate` 注入 `requestAnimationFrame` 迴圈時，它測量的是瀏覽器合成器的幀回呼頻率，**不是** GPU 實際渲染完成的時間。

具體問題：
- WebGL 遊戲的 draw call 可能在 rAF 回呼之後才由 GPU 完成——CDP 看不到 GPU pipeline stall
- 雙緩衝/三緩衝機制下，rAF 的 delta 不等於實際呈現延遲（present latency）
- 注入的測量腳本本身佔用主執行緒時間，造成 observer effect

### 1.2 黑盒外觀、白盒幻覺

這套工具給人「深度 profiling」的印象，但實際上：
- 它無法存取遊戲引擎內部狀態（ECS entity count、physics step time、AI tick cost）
- 它無法區分「引擎的 update loop 慢」和「渲染 pipeline 慢」
- `Performance.getMetrics` 回傳的 `ScriptDuration` 是所有 JS 的總和，不能歸因到特定遊戲系統

**這不是 QA——這是外部觀測。** 真正的遊戲 QA 需要引擎層級的 instrumentation hook。

---

## 2. 純視覺/CDP 方法的盲區

### 2.1 完全無法偵測的缺陷類別

| 缺陷類別 | 為什麼此工具抓不到 |
|----------|-------------------|
| 音效 bug（音效不播、延遲、爆音） | CDP 沒有 Audio domain 的播放狀態追蹤 |
| 遊戲邏輯錯誤（傷害計算錯、掉落率偏差） | 無法存取遊戲記憶體/變數 |
| 動畫 timing（攻擊動作取消窗口錯誤） | rAF 粒度無法抓到 sub-frame timing |
| 物理穿模（碰撞體積錯誤） | 需要物理引擎 debug draw |
| 網路同步問題（P2P desync） | CDP Network domain 只看 HTTP，不看 WebSocket 語意 |
| Shader 渲染錯誤（Z-fighting、mipmap 閃爍） | 需要 RenderDoc/GPU debugger |
| 觸控/手勢輸入問題（移動端） | Playwright 的 input 模擬不等於真實觸控 |

### 2.2 Pixel-Perfect 問題

`KnowledgeBase` 的視覺比對完全基於 keyword matching（第 230–260 行的 `find_system_for_task`），沒有任何像素級比對機制。對於：
- Anti-aliasing 品質退化
- HDR tone mapping 色彩偏移
- 文字渲染模糊（特別是 CJK 字型在不同 DPI）

這套系統完全盲目。

---

## 3. CDP Profiling vs 遊戲引擎 Instrumentation 的差距

### 3.1 資訊密度對比

| 指標 | CDP 能給的 | 引擎 Instrumentation 能給的 |
|------|-----------|---------------------------|
| FPS | 合成器幀率（含 OS 排程抖動） | 精確的 game loop iteration time |
| 記憶體 | JS Heap 總量 | 每個資源池的分配（texture pool、mesh pool、audio buffer） |
| CPU | 按 JS function 的 self-time | 按遊戲系統的 tick cost（Physics: 2ms, AI: 1.5ms, Render: 8ms） |
| GPU | **完全沒有** | Draw call count、overdraw、shader complexity、VRAM usage |
| 網路 | HTTP request/response 層級 | 遊戲狀態同步延遲、封包遺失率、預測回滾次數 |

### 3.2 `PerfProfiler` 的 GPU 盲點

`PerfProfiler` 類別（perf_profiler.py）沒有任何 GPU 相關測量。對 WebGL 遊戲而言，GPU bound 是最常見的效能瓶頸，但：
- 沒有 `EXT_disjoint_timer_query` 的使用
- 沒有 draw call 計數
- 沒有 texture memory 追蹤
- 沒有 shader compilation stall 偵測

這就像用心電圖來診斷骨折——工具類別根本不對。

---

## 4. 具體程式碼弱點

### 4.1 記憶體取樣太稀疏

**`PerfProfiler.get_memory_snapshot()`**（perf_profiler.py 第 146–163 行）：

```python
for _ in range(5):
    result = await self._cdp.send("Performance.getMetrics")
    samples.append(metrics.get("JSHeapUsedSize", 0) / (1024 * 1024))
    await asyncio.sleep(1.0)
```

- **5 個樣本、5 秒窗口**——這對偵測 memory leak 完全不夠
- 真正的 leak 可能需要 5–30 分鐘才能顯現
- GC 週期（通常 10–60 秒一次 major GC）可能完全包含在這 5 秒內，造成假陰性
- `heap_growth > 10.0 MB` 的閾值（第 162 行）完全沒有科學依據——Unity WebGL build 的 heap 在載入資源時正常增長就超過 10MB

### 4.2 Coverage 等待時間太短

**`NetworkAnalyzer.get_js_css_coverage()`**（network_analyzer.py 第 146–246 行）：

```python
# Let code execute
await asyncio.sleep(2)
```

- **只等 2 秒**（第 167 行）就收集 coverage
- WebGL 遊戲的核心 gameplay loop 通常需要玩家互動才會執行到（戰鬥系統、UI 系統、結算邏輯）
- 2 秒內只能覆蓋 initialization code，完全無法代表真實 dead code 比例
- 結果：會大幅高估 dead code percentage（因為 gameplay code 還沒被觸發）

### 4.3 閾值全部寫死

**`PerfReporter._detect_issues()`**（perf_report.py 第 223–294 行）：

```python
if fps["avg"] > 0 and fps["avg"] < 30:        # 第 232 行
if fps["avg"] > 0 and fps["avg"] < 50:        # 第 239 行
if mem["heap_used_mb"] > 512:                   # 第 248 行
if mem.get("heap_growth_mb") ... > 50:          # 第 256 行
if dead_pct > 30:                               # 第 265 行
if size_mb > 5:                                 # 第 276 行
if total_bundle_mb > 20:                        # 第 286 行
```

問題：
- 30 FPS 對手遊可接受，對 FPS 射擊遊戲不可接受——沒有遊戲類型適配
- 512 MB heap 對大型 3D 遊戲完全正常
- 5 MB 單一資源閾值——一個 4K 紋理壓縮後就超過這個數字
- 所有閾值無法通過配置覆蓋，必須改程式碼

### 4.4 Keyword Matching 太簡單

**`KnowledgeBase.find_system_for_task()`**（knowledge_base.py 第 230–260 行）：

```python
for kw in keywords:
    if kw.lower() in task_lower:
        return system
```

- 純字串包含比對，沒有：
  - 分詞（中文「提升等級」vs「等級提升」就可能不匹配）
  - 同義詞擴展（「升級」=「提升等級」=「level up」）
  - 模糊匹配（typo tolerance）
  - 語意距離計算

**`KnowledgeBase.find_solution()`**（第 169–215 行）同樣脆弱：

```python
for word in ps_lower.split():
    if len(word) >= 3 and word in symptoms_joined:
        score += 1
```

- 用空格 split 中文字串基本無效（中文沒有空格分隔詞）
- `len(word) >= 3` 對中文字元意味著至少 3 個字——過度嚴格
- 分數閾值 `best_score >= 2` 沒有正規化，問題庫越大越容易誤判

### 4.5 CPU Profile 分析過度簡化

**`PerfProfiler.stop_cpu_profile()`**（perf_profiler.py 第 104–144 行）：

- 只回傳 top 20 functions by self-time
- 沒有 call tree 關係——無法知道「誰呼叫了這個 hot function」
- 沒有 flame chart 輸出——QA 人員無法用視覺化方式分析
- `timeDeltas` 的索引對齊假設（第 125 行 `time_deltas[i] if i < len(time_deltas) else 0`）在 CDP 實作中不保證對齊

---

## 5. 一個持懷疑態度的 QA 主管會怎麼說

> 「你給我的是一個花了三天做的 demo，不是 production QA pipeline。」

具體質疑：

1. **「這個能抓到我們上週的 P0 bug 嗎？」**——如果 P0 是音效不播放、戰鬥平衡崩壞、或特定機型 GPU 閃退，答案是「不能」。

2. **「誤報率多少？」**——`perf_report.py` 的寫死閾值會對正常的大型遊戲瘋狂報警。QA 團隊會很快學會忽略這些告警。

3. **「coverage 只跑 2 秒，你告訴我 70% dead code，但那些 code 是戰鬥系統的——玩家還沒進戰鬥而已。」**——Coverage 數字完全不可信。

4. **「memory leak 取樣 5 秒就下結論？我們的 leak 是玩 20 分鐘後才 OOM 的。」**——工具在設計層面就無法偵測真實世界的 memory leak。

5. **「你沒有 regression baseline。每次跑出的數字沒有比較基準，怎麼知道是退化還是正常波動？」**——沒有歷史數據存儲、沒有統計顯著性檢定、沒有 A/B 比較。

6. **「CI/CD 整合在哪？閾值突破自動擋 merge 在哪？」**——這是一個手動跑的腳本，不是自動化管線。

---

## 6. 達到生產環境品質還缺什麼

### 6.1 必要缺失（Must-Have）

| 缺失項目 | 影響 |
|----------|------|
| GPU profiling（WebGL extension 或 external GPU debugger 整合） | 無法診斷 GPU bound 問題 |
| 長時間壓力測試（30min+ soak test） | Memory leak 偵測無效 |
| Regression baseline + 統計比較 | 無法區分噪音和真實退化 |
| 可配置閾值（per-game, per-platform） | 誤報率失控 |
| 真實輸入模擬（touch、gamepad、多點觸控） | 僅覆蓋 desktop 滑鼠場景 |
| 多平台/多裝置矩陣 | 只測 Chrome desktop |
| CI/CD pipeline 整合 + gate mechanism | 不能自動擋 regression |
| 遊戲引擎 hook（Unity/Unreal WebGL 的 performance overlay） | CDP 資訊密度不足 |

### 6.2 重要缺失（Should-Have）

| 缺失項目 | 影響 |
|----------|------|
| Audio 測試自動化 | 音效 bug 完全盲區 |
| Visual regression（screenshot diff） | UI 視覺退化無法偵測 |
| Network condition simulation（3G、高延遲） | 未測試弱網環境 |
| Crash recovery + 自動重跑 | 單次失敗就丟失整個 session |
| Report 歷史趨勢圖 | 無法看到效能趨勢 |
| 支援 WebGPU | 只支援 WebGL，新標準無覆蓋 |

### 6.3 Nice-to-Have

- A/B 測試整合（新版 vs 舊版自動比較）
- 玩家行為模擬（不只是靜態等待，而是模擬真實操作路徑）
- 自動 bisect（哪個 commit 引入了效能退化）
- 多語言 keyword matching（NLP-based intent recognition）

---

## 7. 回應正方可能的辯護

### 辯護 1：「這是 MVP，先有再好」

**反駁**：MVP 可以接受功能不完整，但不能接受**測量結果不可信**。5 秒 memory sampling 和 2 秒 coverage 窗口產出的數字會誤導決策。錯誤的數字比沒有數字更危險——它給人虛假的信心。

### 辯護 2：「CDP 是唯一不需要修改遊戲原始碼的方法」

**反駁**：這是 trade-off 的選擇，但工具應該**明確標示測量限制**而非假裝全面。`PerfReporter` 的報告（包含 HTML 報告）沒有任何 caveat 說明 FPS 數字不含 GPU pipeline time、coverage 只代表前 2 秒的執行路徑。使用者會把這些數字當作真理。

### 辯護 3：「KnowledgeBase 的 keyword matching 夠用了」

**反駁**：對英文可能勉強可用，但 `find_solution()` 第 194 行的 `ps_lower.split()` 在中文語境下直接失效。這個工具明確使用繁體中文（`## 症狀`、`## 根本原因`），所以中文支援不是 nice-to-have——是基本需求。用 jieba 或 regex 詞彙表做基本分詞是最低要求。

### 辯護 4：「PerfProfiler 可以跑長時間測量」

**反駁**：`measure_fps()` 確實接受 `duration_seconds` 參數，但 `get_memory_snapshot()` 寫死 5 次取樣、`get_js_css_coverage()` 寫死 2 秒等待。這些不是「可以延長」——是**架構設計就固定了取樣策略**。要改需要重構 API。

### 辯護 5：「Network 分析很完整」

**反駁**：`NetworkAnalyzer` 確實是這套工具中最成熟的部分，但它只覆蓋 HTTP(S) 層。WebGL 遊戲大量使用 WebSocket 進行即時通訊，CDP 的 `Network.webSocketFrameSent/Received` 事件完全沒有被監聽（network_analyzer.py 中沒有任何 WebSocket 相關的 handler）。

### 辯護 6：「閾值可以之後改成可配置的」

**反駁**：技術上可以，但這暴露了更深的設計問題——`_detect_issues()` 把**領域知識**（什麼算「好」）寫進了程式碼。正確的做法是 threshold profile 作為外部 YAML 配置，per-game 可覆蓋。目前的設計讓每加一個遊戲就要 review 所有閾值。

---

## 結論

這套工具適合作為**開發者個人的快速檢查腳本**——「我改了 shader，FPS 有沒有明顯掉」。但它被包裝成「QA Agent」的定位過度承諾了。

真正的 WebGL 遊戲 QA 需要：
1. 引擎層級的 telemetry hook（不只是外部觀測）
2. 長時間 soak test（不是 5 秒取樣）
3. 統計嚴謹的 regression detection（不是單次閾值比較）
4. 多維度覆蓋（視覺 + 音效 + 邏輯 + 效能 + 網路）

在這些前提達成之前，這是一個**效能觀測腳本**，不是**QA Agent**。命名本身就是過度承諾。
