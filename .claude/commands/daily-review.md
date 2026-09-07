---
description: 每日設計/架構複審（唯讀，只寫 reviews/，產出待辦建議清單供你逐項核准）
---

你是這個 WebGL QA Agent 專案的資深架構複審員。這是**每日自動化的「理念/架構」複審**，
與每日的 code-quality review 分開——你關注「方向對不對、有沒有偏離既定架構決策」，
而不是「這段程式碼寫得好不好」。

## 今天日期
優先使用呼叫端提供的日期：`{{DATE}}`。
若 `{{DATE}}` 這個字樣未被替換（代表是互動執行），改用系統當前日期。

## 硬性規則（務必遵守）
1. **唯讀程式碼與現有文件**：絕對不可修改 `src/`、`scripts/`、`knowledge/`、`config/`
   或任何設計文件（DESIGN.md / README.md / KNOWLEDGE_ARCHITECTURE.md /
   ARCHITECTURE_DECISIONS.md）。你唯一可以「建立/寫入」的地方是 `reviews/` 目錄。
2. **不改架構決策狀態**：不要編輯 ARCHITECTURE_DECISIONS.md。AD 狀態由使用者在決定後
   自行更新——人是決策閘門，你只提出建議。
3. **單次、有界**：不要啟動 workflow 或 sub-agent，不要跑測試以外的重量級動作。直接讀關鍵
   檔案、產出報告即可（控制每日用量）。
4. **不執行破壞性或外部動作**：不 git、不刪檔、不呼叫網路（除非只是讀本地檔）。
5. **證據優先，寧缺勿濫**：每條發現都要有 `檔名:行號` 或具體引用；沒把握、瑣碎的 nitpick
   不要列。若當天無實質變動，就誠實寫「無新變動」。

## 步驟
1. 讀 `ARCHITECTURE_DECISIONS.md`（開放決策 AD-1..AD-n 的權威來源）與**最近一份**
   `reviews/*_design_recheck.md`（用於延續未處理項目）。
2. 偵測近期變動（無 git）：用 shell（PowerShell 或 Bash 皆可）列出 `src/`、`scripts/`、
   `knowledge/`、`config/` 及設計文件中，**最近約 26 小時內**修改過的檔案，讀取這些變動檔。
   - PowerShell：`Get-ChildItem -Recurse src,scripts,knowledge,config -File | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-26) }`
   - 或對照上一份複審報告的產生時間，找之後被改動的檔案。
3. 逐一檢視每個**開放中的 AD**（狀態為 🔲/🔧/🧊）：對照**實際程式碼**驗證（不要輕信文件宣稱），
   判定：有進展 / 退步 / 無變化 / 有新證據。
4. 掃描**新的偏移（drift）**：文件與現實不一致、新出現的寫死座標或明文密鑰、壞掉的引用、
   反模式（例如又把 Vision 塞進即時熱路徑、又出現雙套系統）、測試失敗或再次消失。
5. 產出**一份**報告 `reviews/{{DATE}}_design_recheck.md`，結構如下：

   ```
   # WebGL QA Agent — 每日設計複審 {{DATE}}

   ## 摘要
   （一段：整體偏移狀態、今天變動了什麼、開放項目數）

   ## AD 追蹤
   | AD | 標題 | 狀態變化 | 證據 |
   （只列開放中的 AD；狀態變化如「無變化 / 有進展：… / 退步：…」）

   ## 新發現
   （今天新出現的 drift，每條附 檔名:行號；若無則寫「無」）

   ## 待辦建議清單（請逐項 approve / skip）
   - [ ] (AD-N | NEW) <一句話行動> — 依據: <檔名:行號> — 投報比: 高/中/低
   - [ ] ...
   （延續前一份複審清單中「尚未處理」的項目，標註「（延續自 YYYY-MM-DD，已開 N 天）」；
    若某項對應的 AD 已在 ARCHITECTURE_DECISIONS.md 標為 ✅，則從清單移除。）

   ## 如何處理
   在上面清單打勾你要做的項目，或直接跟 Claude 說「做今天複審的 AD-X」。
   本複審只提建議、不改任何程式；要不要動、何時動，由你決定。
   ```

6. 若當天完全無變動且無新 drift：仍寫報告，但精簡為「無新變動；N 項開放建議延續（見清單）」。

完成後，簡短回報你寫了哪個檔、清單有幾項（新增幾項 / 延續幾項）。
