# 架構決策追蹤清單（Architecture Decisions）

理念/架構層的決策與長期追蹤項，**與每日 code-quality review 分開**。
每日 review 管「程式碼寫得好不好」；本文件管「方向對不對」——這些項目不該因為
「不在本週 code review 範圍」而被長期跳過。

狀態：✅ 已決策/已落地 ｜ 🔧 進行中 ｜ 🔲 待處理 ｜ 🧊 暫緩（roadmap）

最後更新：2026-07-08

---

## AD-1 ✅ 黑箱 vs. 遊戲內 hook — 採「純黑箱」

- **決策**：以純視覺黑箱測試，不注入遊戲內 hook / SDK。
- **理由**：測試對象「受測的第三方遊戲 (the game under test)」是**不可修改的第三方遊戲**，無原始碼、
  無法 instrument。業界（Microsoft Inspector）正是在「目標無法 instrument」時採純像素法。
- **後果**：ground truth 只能來自畫面 → 必須靠 Vision 讀數值（見 AD-2）；座標定位較脆弱，
  需靠知識庫累積 + 未來的 grounding（見 AD-4）。
- **重新評估條件**：若改測自家、可重建的 Unity 遊戲 → 應改用 in-engine hook（AltTester/
  GameDriver）取得狀態真值與毫秒級定位。

## AD-2 ✅ Test oracle — Vision 讀 game_state + 宣告式 invariant

- **決策**：功能正確性用 Vision 讀 `game_state`（score/currency/level/lives），由 `oracle.py`
  比對動作前後值；invariant 宣告於 `game_info.yaml`。
- **理由**：黑箱下無引擎真值，畫面數字是唯一可得的 ground truth；invariant 引擎保持確定性、
  可單元測試，把昂貴/非確定的 Vision 呼叫時機交給呼叫端控制。
- **已落地**：`oracle.py`、vision schema `game_state`、4 條 example_game invariants、
  `GameSession.check_invariants()`、`tests/test_oracle.py`（16 tests）。
- **感測器防護（2026-07-09 補）**：oracle 輸入是 Vision 讀數，本身會誤讀，兩道防線：
  (1) **二次確認** — `check_invariants(reread=...)` 發現違規時重截圖重讀，兩次都違規才算數
  （單次 OCR 誤讀極少在第二幀重複）；(2) **min_occurrences** — invariant 可宣告連續 N 次
  違規才確認為 bug（RNG/時序競態欄位建議 2-3），未達門檻記為 candidate，出現在報告
  timeline 但不進 bug 清單，pass 會重置連續計數。
- **後續**：擴充 invariants（下注額扣款、技能冷卻、任務進度單調遞增）；追蹤 oracle
  precision（報的 bug 幾成為真）；長期可用本地 OCR 交叉驗證數字。

## AD-3 ✅ 單一知識系統

- **決策**：`KnowledgeBase` 一套涵蓋靜態 YAML + runtime 學習層；移除 `KnowledgeStore`。
- **已落地**：`knowledge.py` 已刪除，無殘留呼叫者。

## AD-4 🔧 座標 grounding + 動作後斷言（理念 #3 核心）

- **問題**：Vision 的 `suggested_click` 座標直接點下，無點擊前驗證、無點擊後斷言，
  卡關循環（反覆點同一處無進度）在架構上會發生。
- **(2) 點擊後斷言 — ✅ 已落地（2026-07-09）**：`GameSession.execute_action` 每個動作後
  自動截圖比對 `pixel_diff_ratio`（`config: action_verify`），回傳
  `effect: {changed, pixel_diff, consecutive_noop, blocked}`；同一動作（10px 網格容差的
  signature）連續 `max_consecutive_noop`（預設 3）次無畫面反應 → 記 `no_effect_loop`
  candidate anomaly 並標 `blocked: True`，呼叫端據此停止重複。搭配 oracle 數值斷言
  （AD-2）構成雙訊號。
- **(1) 點擊前 grounding — 🔲 待處理**：模板比對/OCR 確認座標有目標，或 OmniParser 類
  偵測產生候選框讓 Vision「選 element_id」而非吐裸座標。
- **(3) 高風險轉換雙訊號 — 🔲 待處理**：切廳/重登需兩個獨立訊號一致才放行。

## AD-5 🔲 screen_id 主鍵穩定化

- **問題**：screen_id 由 Vision 自由命名，第一道比對 SSIM 為全圖統計，對魚群游動畫面無判別力
  → confidence 累積失效、同畫面被別名拆成多條 low 邊。
- **提案**：canonical screen registry（遮罩動態區後的 perceptual hash + UI 錨點指紋）作主鍵，
  Vision 命名只作 display name；`compute_ssim` 改逐窗或降採樣。

## AD-6 🔲 confidence 升降 + 時間衰減

- **問題**：`add_runtime_transition` 只有 low→medium→high 遞增，DESIGN 宣稱的「失敗則降低」
  無對應程式。
- **提案**：記成功/失敗次數與 `last_verified`，實作遞減與時間衰減；`stable` 由比率決定。

## AD-7 🧊 L3 確定性回歸層 + CI（roadmap）

- **問題**：探索學到的 flow 未固化為零 LLM 的回歸腳本；`finish()` 無 pass/fail verdict 與
  exit code，無法掛 CI（多個 run 的 status 停在 "running"）。
- **提案**：flow 穩定後產生確定性腳本；`run` 以明確 status + exit code 結束 + JSON summary；
  先掛 nightly cron + 失敗通知。依賴 AD-4/AD-5 先穩。

## AD-8 🧊 replay / 覆蓋率（roadmap）

- **replay**：黑箱 + server-side RNG（魚群/掉落/帳號進度皆伺服器狀態）下，單次點擊序列重播
  無法保證重現。應改為「統計化重複執行」判定（EA SEED 做法），而非承諾精確 replay。
- **覆蓋率**：目前終止條件只有 `--duration`/`--runs`，無覆蓋率定義。先定義覆蓋單位（造訪
  screen 數 / 完成任務數 / 觸發系統數），再以覆蓋率驅動探索與終止。

## AD-9 🔧 感知分層與成本（部分）

- **現況**：`observe()` 每步跑確定性偵測（detector + pixel_diff）不呼叫 Vision，
  adaptive observe 依 pixel_diff 決定是否升級 Vision — L1 已成形。
- **待補**：明確的 L2 呼叫條件（僅未知畫面/斷言失敗時）與每 session 成本上限；把
  `qa_interactive.py` 的 adaptive observe 從腳本私有邏輯提升為核心正式策略。

## AD-10 ✅ 每日自動化複審 + 人工決策閘門

- **決策**：本清單所依據的「理念/架構複審」改為每日自動執行，但**只提建議、不自動改動**，
  是否處理由使用者逐項決定。
- **機制**：Windows 工作排程 `WebGL-QA-DailyReview` 每天 09:00 呼叫 `scripts/daily_review.ps1`
  → 以 headless Claude Code（`claude.exe -p`，動態解析最新版）執行 `.claude/commands/daily-review.md`。
- **交付**：每日產出 `reviews/<date>_design_recheck.md`，內含「待辦建議清單」（逐項對齊 AD 編號、
  可 approve/skip、延續未處理項目）。log 於 `reviews/.logs/`。
- **安全界線**：複審過程**唯讀程式碼**，只寫 `reviews/`；**不編輯本檔**——AD 狀態由使用者決定後
  自行更新，維持人是決策閘門。
- **操作**：
  - 立即測試：`schtasks /Run /TN WebGL-QA-DailyReview`
  - 改時間/模型：重跑 `scripts/register_daily_review.ps1 -Time 08:30 -Model claude-sonnet-5`
  - 反安裝：`scripts/register_daily_review.ps1 -Remove`
- **用量備註**：每日深審用 opus 會持續消耗 Claude 用量；若常撞上限，改 `-Model claude-sonnet-5`
  或降頻。互動時亦可用 `/daily-review` slash command 手動觸發同一套複審。

---

## 附：非架構但已列待辦

- 移除探索腳本中寫死的 Vision gateway 網址與明文金鑰（改讀環境變數）。
- 為純函數補 pytest（parser、perceiver、knowledge_base、oracle）。
