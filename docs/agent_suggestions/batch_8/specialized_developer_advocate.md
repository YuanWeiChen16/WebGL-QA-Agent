# Developer Advocate 對 webgl-qa-agent 的建議報告

> 日期：2026-07-16
> 審查角色：Specialized Developer Advocate（專精開發者社群、DX 體驗、技術內容、平台推廣）
> 審查面向：開發者體驗（DX）與上手摩擦
> 批次：Batch 8 — 知識/可觀測組

---

## 建議 1：Getting Started 路徑過長

**提問**：一個新開發者從 clone repo 到「看到第一個有意義的輸出」需要幾步？目前的 README 快速上手需要：設定 .env（找 Vision gateway）、uv sync、playwright install、寫 Python script。能否縮短到 1 條指令？

**優化建議**：
提供 Zero-Config Demo Mode：
- `uv run demo` → 用 WebGL Aquarium 做簡短 demo（無需 Vision API key）
- Demo 模式只跑確定性偵測層（freeze/blank/console error）
- 產出一份 sample report.html 讓使用者看到「這個工具能做什麼」
- Vision 功能標記為 optional tier（有 key 才啟用）

**來源**：
- Developer Experience best practices — time-to-first-value https://dx.tips/
- Stripe's "5 minutes to first API call" philosophy https://stripe.com/docs/development

**優先級**：高

**預期效果**：新使用者 2 分鐘內看到價值，而非卡在「沒有 Vision API key」而無法體驗。

---

## 建議 2：缺乏 Interactive Playground

**提問**：有沒有一個方式讓開發者「不寫程式就能試用」？如 CLI interactive mode 或 web dashboard？

**優化建議**：
- 實作 `scripts/playground.py`：互動式 REPL
  - 輸入 URL → 自動啟動 browser → 顯示截圖 → 手動下指令（click/screenshot/observe）
  - 類似 `start_session.py` 但加上 rich terminal UI（用 rich/textual）
- 或提供 Jupyter Notebook template：step-by-step 展示完整工作流
- 每一步都有即時 feedback（截圖顯示在 terminal 或 notebook）

**來源**：
- Interactive CLI tools improve developer adoption — Ink/Blessed https://github.com/Textualize/textual
- Jupyter as documentation tool — executable docs https://jupyter.org/

**優先級**：中

**預期效果**：降低「寫 Python script」的門檻，讓非 Python 開發者也能試用。

---

## 建議 3：錯誤訊息不友善

**提問**：如果 Vision API key 無效、或 game URL 無法載入、或 Playwright 未安裝，使用者會看到什麼錯誤訊息？是 Python traceback 還是友善的提示？

**優化建議**：
加入 Startup Health Check：
```python
async def preflight_check():
    errors = []
    if not os.environ.get("VISION_GATEWAY_URL"):
        errors.append("❌ VISION_GATEWAY_URL not set. Copy .env.example to .env and fill in your gateway URL.")
    if not shutil.which("playwright"):
        errors.append("❌ Playwright not installed. Run: uv run playwright install chromium")
    # ... more checks
    if errors:
        print("\n".join(errors))
        sys.exit(1)
```
- 在 GameSession.start() 最前面跑 preflight
- 每個錯誤給出具體的修復指令（不只是說「失敗了」）

**來源**：
- Preflight checks in CLI tools — best practice https://clig.dev/#errors
- Friendly error messages — Elm compiler as gold standard https://elm-lang.org/news/compiler-errors-for-humans

**優先級**：高

**預期效果**：新使用者不會因為一個未設定的環境變數而面對 50 行 traceback。

---

## 建議 4：缺乏使用案例文件

**提問**：README 說「適用於不可修改的第三方 WebGL 遊戲」，但沒有具體的使用案例。什麼類型的遊戲？什麼規模的團隊？解決什麼痛點？

**優化建議**：
加入 Use Cases 段落或獨立的 `docs/use-cases.md`：
- **案例 1**：遊戲發行商需要定期回歸測試代理的 H5 遊戲（無原始碼）
- **案例 2**：QA 團隊想自動化夜間巡檢（crash detection）
- **案例 3**：獨立開發者想對自己的 WebGL 遊戲做長時間壓力測試
- 每個案例包含：痛點、如何使用本工具解決、預期產出

**來源**：
- Use-case driven documentation — Divio documentation system https://documentation.divio.com/
- Stripe use cases page as reference https://stripe.com/use-cases

**優先級**：中

**預期效果**：讓潛在使用者快速判斷「這個工具適不適合我的場景」。

---

## 建議 5：缺乏 Contributing Guide

**提問**：如果外部開發者想貢獻，目前有 CONTRIBUTING.md 嗎？程式碼風格、PR 流程、測試要求是什麼？

**優化建議**：
加入基本 Contributing 指引：
- 開發環境設定（uv sync + pre-commit hooks）
- 程式碼風格（ruff format + ruff check）
- 測試要求（新功能必須有 unit test）
- PR template（描述變更 + 測試方式）
- Issue template（bug report / feature request）

**來源**：
- GitHub CONTRIBUTING.md best practices https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions
- Open source contribution guidelines — Mozilla https://mozilla.github.io/open-leadership-training-series/

**優先級**：低（目前是單人專案）

**預期效果**：為未來開源社群參與做準備。
