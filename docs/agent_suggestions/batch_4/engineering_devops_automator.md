# DevOps Automator 審查建議 — Batch 4

**審查者**：DevOps Automator（CI/CD、基礎設施自動化、可觀測性專家）
**日期**：2026-07-16
**對象**：webgl-qa-agent 專案的 DevOps / 自動化 / 部署成熟度

---

## 摘要

與 arch-defender 對話後確認：專案目前處於「單人本地開發」階段，CI/CD 與自動化基礎設施刻意延後。但 defender 也承認 **unit test CI「沒有好的理由不做」**。以下建議按「現在就能做」→「nightly 就緒時做」→「長期演進」分層，每條附實作參考 URL。

---

## 建議 1：立即建立 Unit Test CI Pipeline（lint + pytest）

**問題**：專案有 60+ 純函數 pytest 測試，卻無任何 CI 守護。PR 可能引入回歸而無人知曉。

**建議**：建立 `.github/workflows/ci.yml`，使用 `astral-sh/setup-uv` + `uv sync --locked` + `uv run pytest` + `uv run ruff check .`。這是零風險、近零維護成本的改進，defender 已同意「可以今天就建」。

**具體方案**：
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
      - run: uv sync --locked --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest tests/
```

**參考 URL**：
- uv 官方 GitHub Actions 指南：https://docs.astral.sh/uv/guides/integration/github/
- astral-sh/setup-uv action：https://github.com/astral-sh/setup-uv
- 完整 Python CI 範例（uv + ruff + pytest）：https://pydevtools.com/handbook/tutorial/setting-up-github-actions-with-uv/

---

## 建議 2：Secrets 管理 — 採用 GitHub Actions Secrets + Environment 隔離

**問題**：ARCHITECTURE_DECISIONS.md 附錄明確標記「移除探索腳本中寫死的 Vision gateway 網址與明文金鑰」為待辦。當 nightly 自動化就緒時，需要安全的 secrets 注入機制。

**建議**：
1. **立即**：清除腳本中寫死的 gateway URL 與 API key（技術債）。
2. **nightly 就緒時**：使用 GitHub Actions repository secrets 注入 `VISION_GATEWAY_URL` 與 `VISION_API_KEY`。只有 2 個 secret，不需要 Vault/SOPS 級別工具。
3. **最佳實踐**：secrets 以 env var 傳入 step，不寫入 CLI args；pin 第三方 action 到 commit SHA 防供應鏈攻擊。

**具體做法**：
```yaml
steps:
  - name: Run nightly QA
    env:
      VISION_GATEWAY_URL: ${{ secrets.VISION_GATEWAY_URL }}
      VISION_API_KEY: ${{ secrets.VISION_API_KEY }}
    run: uv run python scripts/qa_interactive.py
```

**參考 URL**：
- GitHub 官方 secrets 文件：https://docs.github.com/actions/security-guides/using-secrets-in-github-actions
- Secrets 最佳實踐（scope/rotation/OIDC）：https://www.blacksmith.sh/blog/best-practices-for-managing-secrets-in-github-actions
- Secrets vs Environment Variables 指南：https://env.dev/guides/github-actions-secrets-env

---

## 建議 3：GPU Self-Hosted Runner 方案 — 視覺 QA 的硬約束

**問題**：WebGL QA agent 的 SSIM/pixel_diff 直接依賴截圖像素品質。SwiftShader 軟體渲染與真實 GPU 在 shader precision、anti-aliasing、texture filtering 上有顯著差異，會導致 perceiver.py 的閾值失效（defender 確認這是「考慮過後的硬約束」）。

**建議**：nightly E2E 視覺測試採用 GPU self-hosted runner。推薦方案：

| 方案 | 成本 | 複雜度 | 適用場景 |
|------|------|--------|----------|
| RunsOn (AWS g5.xlarge) | ~$1.06/hr spot | 低 | 推薦首選 |
| machulav/ec2-github-runner | AWS 按需啟停 | 中 | 完全自控 |
| 本地 Windows 機器 runner | 已有硬體 | 低 | 初期驗證 |

**Chromium GPU 加速配置**（在有 GPU 的 Linux runner 上）：
```python
browser = await playwright.chromium.launch(
    args=[
        '--use-angle=vulkan',
        '--enable-features=Vulkan',
        '--disable-vulkan-surface',
        '--no-sandbox',
    ]
)
```

**重要區分**：
- **Unit test CI**（parser、oracle、knowledge_base）→ 任何 runner 都能跑
- **E2E 視覺測試**（截圖 + SSIM + pixel_diff）→ 必須 GPU runner

**參考 URL**：
- RunsOn GPU runners（g4dn/g5 配置）：https://runs-on.com/docs/runners/platforms/
- Playwright + GPU Docker 實戰（Promaton 案例）：https://blog.promaton.com/testing-3d-applications-with-playwright-on-gpu-1e9cfc8b54a9
- Playwright WebGL hardware acceleration issue：https://github.com/microsoft/playwright/issues/11627
- machulav/ec2-github-runner 完整範例：https://github.com/neuronets/nobrainer/blob/a6683f5b5730b378f18a362fb58a11594d9d8bde/.github/workflows/guide-notebooks-ec2.yml

---

## 建議 4：報告持久化 + 失敗通知 — GitHub Pages + Slack Webhook

**問題**：報告目前產在本機 `runs/<game>/<timestamp>/`，nightly 自動化後需要持久化存取與失敗通知。

**建議**：採「GitHub Pages 發布報告 + webhook 通知」的低複雜度路線。報告已是 self-contained HTML（截圖 base64 inline），天然適合靜態託管。

**分階段實作**：

**Phase 1 — Artifact 保存（立即可做）**：
```yaml
- name: Upload QA report
  uses: actions/upload-artifact@v4
  with:
    name: qa-report-${{ github.run_number }}
    path: runs/
    retention-days: 30
```

**Phase 2 — GitHub Pages 發布（nightly 就緒時）**：
```yaml
- name: Deploy report to GitHub Pages
  uses: peaceiris/actions-gh-pages@v3
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    publish_branch: gh-pages
    publish_dir: runs/
```

**Phase 3 — Slack/Discord 通知**：
```yaml
- name: Notify on failure
  if: failure()
  run: |
    curl -X POST -H 'Content-type: application/json' \
      --data '{"text":"❌ Nightly QA failed: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}"}' \
      ${{ secrets.SLACK_WEBHOOK_URL }}
```

**參考 URL**：
- actions/upload-pages-artifact：https://github.com/actions/upload-pages-artifact
- actions/deploy-pages：https://github.com/actions/deploy-pages/
- HTML 報告 GitHub Pages 自動部署 action：https://github.com/pavanmudigonda/html-reporter-github-pages
- Nightly CI dashboard 部署範例：https://github.com/DUNE-DAQ/daq-release/blob/618cb6d619d3c36045c93bf00e249a0b5d9f8534/.github/workflows/nightly-ci-dashboard.yml

---

## 建議 5：軟體渲染替代方案 — Mesa llvmpipe 作為 CI 折衷

**問題**：如果短期無法取得 GPU runner，是否有中間方案讓 CI 至少能跑「煙霧測試級」的 WebGL 驗證？

**建議**：使用 Mesa llvmpipe（`--use-angle=gl`）替代已棄用的 SwiftShader，CPU 降 49%，且保有完整 WebGL1/WebGL2 支援。但需注意：

**適用場景**：
- 驗證「遊戲能正常載入、不 crash」（功能性煙霧測試）
- 驗證 detector.py 的 console error / page error 捕捉
- **不適合**精確的 SSIM 比對或像素級 oracle 斷言

**配置**：
```python
# 在無 GPU 的 CI 環境中，使用 Mesa llvmpipe
browser = await playwright.chromium.launch(
    args=[
        '--use-angle=gl',       # 走 Mesa llvmpipe
        '--no-sandbox',
    ]
)
# 同時需要 xvfb：xvfb-run uv run python scripts/smoke_test.py
```

**重要**：需在 perceiver.py 中為 CI 環境設置**不同的 SSIM 閾值**，或直接跳過像素級斷言——這應透過 `config/default.yaml` 的 environment overlay 實現。

**參考 URL**：
- Mesa llvmpipe vs SwiftShader 深度比較（CPU 降 49%）：https://botbrowser.io/en/blog/mesa-llvmpipe-vs-swiftshader-chromium-linux/
- Playwright headless GPU acceleration feature request：https://github.com/microsoft/playwright/issues/15533
- Playwright Docker WebGL 問題追蹤：https://github.com/microsoft/playwright/issues/18810

---

## 優先序總結

| # | 建議 | 時機 | 風險 | 工程量 |
|---|------|------|------|--------|
| 1 | Unit test CI | **今天** | 近零 | 半天 |
| 2 | 清除寫死 secrets | **本週** | 低 | 2hr |
| 3 | GPU runner 方案設計 | AD-7 就緒時 | 中（成本） | 2-3 天 |
| 4 | 報告持久化 Phase 1 | 跟 CI 一起 | 零 | 1hr |
| 5 | Mesa llvmpipe 煙霧測試 | 選配 | 低 | 半天 |

---

## 與架構決策的對齊

- **AD-7（L3 確定性回歸 + CI）**：建議 1 解鎖 unit test 部分；E2E CI 待 AD-4/AD-5 穩定後再建。
- **AD-10（每日自動化複審）**：已有 Windows 排程，但 nightly QA 是獨立需求，建議 3+4 為其鋪路。
- **附錄待辦（移除寫死金鑰）**：建議 2 直接對應。
