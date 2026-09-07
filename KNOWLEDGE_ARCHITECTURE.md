# WebGL QA Agent — 知識驅動架構設計

## 目標

將遊戲知識從 Python code 中抽離，建立結構化知識庫：
- 各系統獨立維護
- 新問題自動查詢相關知識
- 流程圖清楚描述系統間關係

> 註：本文件所有 YAML 範例中的**座標、任務文字、系統內容均為示意佔位**，
> 非任何真實遊戲的資料。請依你的受測遊戲填入實際值。以 `example_game` 泛指受測遊戲。

## 與實作的對齊（2026-07-07 更新）

- **單一知識系統**：由 `knowledge_base.py::KnowledgeBase` 一套涵蓋「靜態 YAML（systems/、
  flow_graph、problems/、game_info）」+「runtime 學習層（knowledge.yaml）」。舊的
  `KnowledgeStore` 已移除。
- **設定分層**：門檻/解析度/timing 等移到 `config/default.yaml`，遊戲特定值 override 於
  `game_info.yaml`（由 `config.py` 深層合併）。
- **功能正確性 oracle**：`game_info.yaml` 的 `oracle.invariants` 宣告不變量，由 `oracle.py`
  比對 Vision 讀到的 `game_state`（分數/金幣/等級/生命）前後值。
- **座標來源**：`actions.py` 一律從知識庫讀座標與操作序列（不再寫死於程式）。

## 目錄結構

```
knowledge/
└── example_game/
    ├── game_info.yaml           # 遊戲基本資訊（URL、解析度、帳號格式）
    ├── systems/                 # 各系統知識
    │   ├── login.yaml           # 登入系統
    │   ├── tutorial.yaml        # 新手教學系統
    │   ├── gameplay.yaml        # 遊戲主畫面
    │   ├── tasks.yaml           # 任務系統（新手任務序列、每日任務）
    │   ├── upgrade.yaml         # 升級系統
    │   ├── skills.yaml          # 技能系統
    │   ├── hall_switch.yaml     # 關卡/場景切換系統
    │   ├── lobby.yaml           # 大廳系統
    │   ├── shop.yaml            # 商城系統
    │   ├── player_info.yaml     # 個人介面系統
    │   └── events.yaml          # 特殊活動系統
    ├── flow_graph.yaml          # 系統間轉換流程圖
    ├── problems/                # 已知問題與解法
    │   ├── stuck_upgrade.md
    │   ├── element_not_found.md
    │   └── vision_parse_error.md
    └── sessions/                # QA session 累積紀錄（自動生成）
        └── ...
```

## 系統知識檔案格式（systems/*.yaml）

> 以下為一個「升級系統」的示意；座標請填入你的遊戲實際像素值。

```yaml
system_id: upgrade
name: 升級系統
description: 管理某項數值（等級/階級）升級的系統

# 如何進入此系統
entry_points:
  - from: gameplay
    trigger: "任務文字包含 提升/升級/等級"   # 依你的遊戲 UI 文字調整
    action:
      type: click
      x: 100          # 示意座標
      y: 200
      description: "點擊左側升級按鈕"

# 此系統的 UI 元素
elements:
  - id: upgrade_toggle_button
    label: 升級
    location: {x: 100, y: 200}          # 示意座標
    type: toggle
    note: "點擊開關升級面板"
  - id: upgrade_panel
    label: 升級面板
    bounds: {x: 40, y: 180, width: 320, height: 60}
    type: panel
    note: "點面板中間確認升級"
  - id: upgrade_confirm
    label: 升級確認位置
    location: {x: 200, y: 210}          # 示意座標
    type: button
    note: "面板中央，點擊執行升級"

# 操作序列
actions:
  do_upgrade:
    description: "升級一次"
    steps:
      - {type: click, x: 100, y: 200, wait: 1.5, note: "開啟升級面板"}
      - {type: click, x: 200, y: 210, wait: 1.0, note: "點擊升級"}
      - {type: click, x: 200, y: 210, wait: 2.0, note: "再點一次確認"}

# 如何離開此系統
exit_points:
  - to: gameplay
    action: "點擊面板外區域 或 升級完成自動關閉"

# 已知問題
known_issues:
  - id: stuck_at_confirm
    description: "某階段升級時確認座標可能無效"
    symptoms: ["進度卡住", "重複升級無效果"]
    solution: "需要先點擊開關顯示方框，再點方框中間"
    status: investigating

# 辨識關鍵字（Vision OCR 可能的文字變體；依你的遊戲填入）
recognition_keywords:
  - "提升"
  - "升級"
  - "升级"
  - "upgrade"
  - "等級"
  - "阶级"
```

## 流程圖格式（flow_graph.yaml）

```yaml
# 系統間轉換圖
# 每個節點是一個系統，邊描述如何從一個系統到另一個
# （座標均為示意佔位）

nodes:
  - id: login
    name: 登入系統
    type: entry
  - id: tutorial
    name: 新手教學
    type: transient
  - id: gameplay
    name: 遊戲主畫面（第一關卡）
    type: primary
  - id: tasks
    name: 任務系統
    type: overlay  # 疊加在 gameplay 上
  - id: upgrade
    name: 升級系統
    type: overlay
  - id: skills
    name: 技能系統
    type: overlay
  - id: hall_switch
    name: 關卡切換
    type: transition
  - id: gameplay_hall2
    name: 遊戲主畫面（第二關卡）
    type: primary
  - id: menu
    name: 菜單
    type: overlay
  - id: lobby
    name: 大廳
    type: goal

edges:
  - from: login
    to: tutorial
    trigger: "輸入帳號 + 確認 + 等待載入"
    auto: true

  - from: tutorial
    to: gameplay
    trigger: "點擊畫面數次跳過教學彈窗"
    auto: true

  - from: gameplay
    to: tasks
    trigger: "畫面頂部顯示任務文字"
    auto: true
    note: "任務系統疊加在遊戲上"

  - from: tasks
    to: upgrade
    trigger: "任務文字含 提升/升級"
    action: "點擊升級按鈕(<x>,<y>)"

  - from: tasks
    to: skills
    trigger: "任務文字含 使用/技能"
    action: "點擊技能按鈕(<x>,<y>)"

  - from: gameplay
    to: hall_switch
    trigger: "完成特定任務後自動觸發"
    auto: true
    note: "出現 loading screen"

  - from: hall_switch
    to: gameplay_hall2
    trigger: "loading 完成"
    auto: true

  - from: gameplay_hall2
    to: menu
    trigger: "點擊左上角菜單按鈕(<x>,<y>)"
    action: {type: click, x: 60, y: 160}   # 示意座標
    note: "菜單圖示，只在第二關卡以上才有"

  - from: menu
    to: lobby
    trigger: "點擊「回到大廳」按鈕"
    action: "待確認座標"
    status: investigating
```

## Agent 查詢邏輯

```python
class KnowledgeBase:
    def __init__(self, game_name):
        self.base_dir = f"knowledge/{game_name}"
        self.systems = self._load_systems()
        self.flow_graph = self._load_flow_graph()
        self.problems = self._load_problems()

    def find_system_for_task(self, task_text: str) -> dict | None:
        """根據任務文字找到對應的系統"""
        for sys in self.systems:
            for kw in sys.get("recognition_keywords", []):
                if kw in task_text.lower():
                    return sys
        return None

    def get_action_sequence(self, system_id: str, action_name: str) -> list:
        """取得某系統的操作序列"""
        sys = self.systems_by_id[system_id]
        return sys["actions"][action_name]["steps"]

    def find_solution(self, symptoms: list[str]) -> dict | None:
        """根據症狀查找已知問題的解法。
        實際實作用評分制（子字串完全命中 +3、詞命中 +1、標題命中 +2），
        分數 >= 2 才回傳最佳匹配——避免中文無空格導致 split() 比對失效。"""
        # scoring over self.problems; see knowledge_base.py::find_solution
        ...

    def get_path(self, from_system: str, to_system: str) -> list:
        """找到從一個系統到另一個的路徑"""
        # BFS on flow_graph edges
        ...
```

## 新手任務序列（tasks.yaml 部分）

> `text_patterns` 為 Vision OCR 讀到的任務文字；以下為**示意佔位**，
> 請替換為你的遊戲實際 UI 文字（含簡繁/字形變體）。

```yaml
newbie_task_sequence:
  description: "新帳號的固定任務序列，完成後觸發關卡切換"
  tasks:
    - id: task_action_1
      text_patterns: ["<任務文字: 例如 執行動作 N 次>"]
      system: gameplay
      action: primary_action
      repeat: true

    - id: task_collect_1
      text_patterns: ["<任務文字: 例如 收集 N 個道具>"]
      system: gameplay
      action: primary_action

    - id: task_earn_1
      text_patterns: ["<任務文字: 例如 獲得 N 金幣>"]
      system: gameplay
      action: primary_action

    - id: task_upgrade_1
      text_patterns: ["<任務文字: 例如 升級至 2 階>"]
      system: upgrade
      action: do_upgrade

    - id: task_use_skill_1
      text_patterns: ["<任務文字: 例如 使用技能 1 次>"]
      system: skills
      action: use_skill

    - id: task_upgrade_2
      text_patterns: ["<任務文字: 例如 升級至 3 階>"]
      system: upgrade
      action: do_upgrade
      note: "完成後觸發自動關卡切換"

  after_completion: hall_switch
```

## 實作計畫

### Phase 1: 知識結構建立
1. 建立 `systems/` 目錄和各系統 yaml
2. 建立 `flow_graph.yaml`
3. 將現有 knowledge.yaml 遷移到新結構

### Phase 2: Agent 整合
1. 實作 `KnowledgeBase` class
2. 修改主腳本從知識庫讀取操作序列
3. 任務匹配改為查詢 knowledge 而非 hardcode

### Phase 3: 自動學習
1. 每次 Vision 回傳新元素時，自動更新對應系統的 elements
2. 遇到新問題時，自動建立 `problems/` 條目
3. 解決問題後更新 solution

## 擴充欄位（2026-09-03 更新：Android 驅動與畫面錨點）

以下欄位在 `knowledge/com_shouxin_hwby/` 首次使用，語意與既有 schema 相容（缺省即忽略）。

### 目錄新增 `anchors/`
```
knowledge/<game>/
└── anchors/                 # 畫面辨識用的靜態 UI 裁切圖（由參考截圖裁出，隨 systems/*.yaml 版本控制）
    ├── title_start_game.png
    └── gameplay_skill_row.png
```

### systems/*.yaml：`detection.anchors` — 確定性畫面辨識
```yaml
detection:
  anchors:
    - {element: quick_start, image: anchors/lobby_quick_start.png,
       region: {x: 1440, y: 945, width: 390, height: 85}, min_ssim: 0.6}
```
- `KnowledgeBase.identify_system(frame)` 對每個宣告了 anchors 的系統計算「區域 SSIM 平均」，
  每個 anchor 都需達到自己的 `min_ssim` 才算候選；最高分與次高分差距小於 `min_margin`（預設 0.15）
  時回 `system_id: None`（寧可不知道，也不猜）。`GameSession.identify_screen()` 為呼叫入口。
- 這是給 `screen_id` 一個**不依賴 Vision 的正準主鍵**；Vision 的命名仍只作 display name。
- **不要用全圖動態程度判斷畫面**：實測標題頁立繪動畫的連續幀 pixel_diff ≈ 0.38，與遊玩畫面同量級。
- 區域與門檻應由「對全部已擷取畫面跑混淆矩陣」決定；跨廳仍相同的控件可放寬到 0.5。

### systems/*.yaml：`destructive: true` — 無人值守時禁止點擊
```yaml
elements:
  - id: shop
    label: 商城
    location: {x: 110, y: 690}
    type: button
    destructive: true        # 購買/商城/帳號切換/下載/離開遊戲
```
自動化腳本以**當前畫面**的 destructive 元素為硬性護欄（點擊落在 60px 內即拒絕）；
其他畫面的元素只作跨畫面重疊提示，畫面漂移由「動作後大幅重繪 → 重新辨識」處理。
不同畫面的座標空間不可混用。

### systems/gameplay.yaml：`fire_points`
```yaml
fire_points:            # 均勻分布於 fish_area 內；固定砲口角度會讓凍結畫面看起來像有反應
  - {x: 860, y: 340}
```
缺省時由 `fish_area.bounds` 均勻取樣推導。

### game_info.yaml 新欄位（Android / 原生 App）
```yaml
platform: android
package: com.shouxin.hwby
driver: adb
screen: {width: 1920, height: 1080}       # 與 adb screencap 一致；input tap 同一座標空間，不需 DPR 換算
coordinate_space: framebuffer_pixels
motion:
  gameplay_min_change: 0.15               # 僅作存活/凍結訊號，不作畫面辨識
layout_baseline:
  static_regions:                         # 版面回歸可比對的靜態區；高動態遊戲無法自動推導，必須明列
    - {x: 1440, y: 180, width: 240, height: 180}
```
`game_info.yaml` 會被合併進 session config（`config.get("motion.gameplay_min_change")`），
所以這些是遊戲層級的覆寫，不必動 `config/default.yaml`。

### flow_graph.yaml：節點 `type` 對導航的意義
| type | 導航行為（scripts/android_autoplay.py） |
|---|---|
| `entry` / `primary` / `goal` | 每一跳執行邊上的 `action`，之後**重新辨識**畫面必須等於目標節點 |
| `transition`（如 loading） | 抵達後辨識不到不算失敗；下一跳改為輪詢直到出現已知畫面（上限 `timing.title_to_lobby_load`） |
| `overlay`（如大廳彈窗） | 可作為路徑起點；`dismiss` 動作後重新辨識 |
| `transient`（如升級覆蓋層） | 只等待不點擊；`popup_dismiss.transient_wait` 先給它自行消失的時間 |

### game_info.yaml：`popup_dismiss` — 未知畫面的唯一允許動作
```yaml
popup_dismiss:
  transient_wait: 4        # 先等瞬時覆蓋層自行消失並重新辨識
  max_attempts: 4          # 之後最多點幾次「關閉」位置，每次點完重新辨識，一辨識出已知畫面立即停止
  close_positions:         # 只允許點這些已觀察過的關閉鈕位置
    - {x: 1832, y: 68}
  wait_between: 1.5
```
原則：辨識為 unknown 時**不做任何其他點擊**；後備用盡仍 unknown 就停手並存證（截圖進報告），交由人判斷。

### known_issues 欄位沿用既有 schema
`id / description / symptoms / solution / status`（`status` 建議：`confirmed | investigating | fixed`）。
