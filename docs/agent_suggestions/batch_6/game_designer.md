# Game Designer 對 webgl-qa-agent 整體架構的建議報告

> 日期：2026-07-16
> 審查角色：Game Designer（專精遊戲機制設計、玩家心理、系統平衡）
> 審查面向：遊戲設計視角的 QA 架構
> 批次：Batch 6 — 遊戲/前端組

---

## 建議 1：缺乏遊戲狀態機複雜性的建模

**提問**：遊戲的狀態遠比「screen A → screen B」的線性流程複雜。如何處理：條件分支（等級夠才能進副本）、隨機事件（掉落觸發特殊畫面）、時間限制（限時活動只在特定時段出現）？

**優化建議**：
- 在 flow_graph.yaml 加入 guard conditions：`{from: gameplay, to: dungeon, guard: "level >= 10"}`
- 加入 event triggers：`{type: random, probability: 0.1, target: bonus_screen}`
- 加入 time windows：`{available: "09:00-21:00", timezone: "Asia/Taipei"}`
- agent 探索時自動記錄「什麼條件下才出現這個 transition」

**來源**：
- Game State Machine design patterns http://www.gameaipro.com/
- Hierarchical State Machines for game AI https://gameprogrammingpatterns.com/state.html

**優先級**：中

**預期效果**：agent 能理解「為什麼某些路徑走不通」而非盲目重試。

---

## 建議 2：未考慮遊戲隨機性對測試的影響

**提問**：多數遊戲有 RNG（隨機數生成器）。同一操作可能產生不同結果（如：攻擊傷害 50-100 隨機）。invariant 如何處理這種非確定性？

**優化建議**：
- Invariant 支援 range 類型：`{field: damage, kind: range, min: 50, max: 100}`
- 統計型 invariant：`{field: win_rate, kind: statistical, expected: 0.5, tolerance: 0.1, sample_size: 20}`
- 區分「隨機但合理」vs「異常」：超出 3σ 才報告

**來源**：
- Statistical game testing — EA SEED approach https://www.ea.com/seed/news/automated-game-testing-using-deep-reinforcement-learning
- Property-based testing with randomness https://hypothesis.readthedocs.io/

**優先級**：高

**預期效果**：避免 RNG 合法變異被誤報為 bug。

---

## 建議 3：缺乏玩家行為模式模擬

**提問**：真正的 QA 需要模擬不同玩家類型（新手亂點、老手速通、掛機玩家）。目前的 explore mode 只有一種行為模式嗎？

**優化建議**：
- 定義 Player Persona profiles：
  - `newbie`：隨機點擊、不看教學、操作緩慢
  - `speedrunner`：最短路徑、快速點擊、跳過動畫
  - `afk_player`：登入後不操作（測試 timeout/idle handling）
  - `stress_tester`：瘋狂快速點擊、邊界操作
- 每種 persona 有不同的 action selection strategy

**來源**：
- Player taxonomy — Bartle's player types https://en.wikipedia.org/wiki/Bartle_taxonomy_of_player_types
- Behavioral testing patterns for games https://www.gamedeveloper.com/

**優先級**：中

**預期效果**：覆蓋更多玩家行為模式，發現不同類型玩家才會觸發的 bug。

---

## 建議 4：遊戲經濟系統的 invariant 不足

**提問**：遊戲經濟（金幣獲得/消耗、道具交易）是 bug 高發區。目前的 invariant 能表達「總資產守恆」（A 花了 100 金幣買道具 → 金幣 -100 且道具 +1）嗎？

**優化建議**：
- 支援 multi-field invariant：`{when: purchase, fields: [{coin: -price}, {item_count: +1}], atomic: true}`
- 支援 conservation law：`{type: conservation, fields: [coin, item_value_sum], tolerance: 0}`
- 支援 non-negative constraint：`{field: coin, kind: non_negative}`

**來源**：
- Game economy design and balance testing https://www.gamesindustry.biz/
- Virtual economy invariants — Eve Online case study https://www.eveonline.com/news/

**優先級**：高

**預期效果**：捕捉遊戲經濟 bug（複製金幣、免費購買、負數資產）。
