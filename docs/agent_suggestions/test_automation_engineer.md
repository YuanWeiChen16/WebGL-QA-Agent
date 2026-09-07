# Test Automation Engineer 優化建議

> 針對 webgl-qa-agent 測試架構的改善方案，基於對現有 4 個測試檔案 (test_oracle.py, test_knowledge_base.py, test_parser.py, test_perceiver.py) 的分析。

---

## 建議 1：導入 pytest-xdist 平行化測試執行

**提問**：目前 4 個測試檔案都是純 CPU-bound（numpy 運算 + YAML 讀取），適合用 pytest-xdist 平行化嗎？有沒有共享狀態的風險？

**優化建議**：

現有測試完全無共享狀態（無 DB、無檔案寫入、無網路），非常適合平行化。建議：

1. 安裝 `pytest-xdist>=3.6.0` 與 `pytest-cov>=6.0.0`
2. 在 `pyproject.toml` 中設定：
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   pythonpath = ["src"]
   addopts = "-n auto --dist loadscope"
   ```
3. 使用 `--dist loadscope` 確保同一模組的測試在同一 worker 執行，避免 class-level fixture 重複初始化（如 `KnowledgeBase` 載入）
4. CI 中明確指定 `-n 4` 避免容器化環境的 CPU count 誤報

**來源 URL**：
- https://pytest-xdist.readthedocs.io/en/latest/distribution.html
- https://qaskills.sh/blog/pytest-xdist-parallel-testing-guide
- https://danielnouri.org/notes/2025/11/03/modern-python-ci-with-coverage-in-2025/

**優先級**：Medium

**預期效果**：測試套件目前規模小（~60 tests），平行化效益有限，但建立正確基礎設施後，當測試數量成長到 200+ 時可節省 50-75% 執行時間。

---

## 建議 2：建立分層 CI 管線（PR Gate + Nightly）

**提問**：考慮到這是 Playwright + Vision LLM 的框架，CI 管線怎麼分層？哪些測試適合在每次 PR 跑，哪些適合 nightly？

**優化建議**：

建議三層分離架構：

**Layer 1 - PR Gate（每次 push/PR，< 2 分鐘）**：
- Unit tests（現有 4 個檔案）
- Linting（ruff）
- Type checking（若有 mypy/pyright）

**Layer 2 - Integration（PR merge 後，< 10 分鐘）**：
- Playwright headless browser 啟動/截圖測試（不需真實遊戲）
- Vision API mock 整合測試
- Reporter HTML 產出驗證

**Layer 3 - Nightly（每日排程）**：
- 真實 WebGL 遊戲 E2E（webglsamples.org/aquarium）
- Vision LLM 真實呼叫測試（成本控制）
- 效能回歸（memory leak detection over time）

GitHub Actions 配置範例：
```yaml
name: tests
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --dev
      - run: uv run pytest -n auto --cov --cov-report=xml --junitxml=results.xml
```

**來源 URL**：
- https://danielnouri.org/notes/2025/11/03/modern-python-ci-with-coverage-in-2025/
- https://playwright.dev/docs/best-practices
- https://docs.pytest.org/en/stable/explanation/flaky.html

**優先級**：High

**預期效果**：PR 合併前即攔截回歸，nightly 負責高成本的 E2E 驗證，團隊對測試結果的信任度提升。

---

## 建議 3：以 Hypothesis 對 Oracle invariant 邏輯做 Property-Based Testing

**提問**：oracle.py 的 invariant 檢查邏輯是核心，但目前只有 positive/negative path 測試。需要 property-based testing（如 Hypothesis）來找 edge case 嗎？

**優化建議**：

Oracle 模組是專案最核心的判斷邏輯，且其輸入空間（before/after state dicts、各種 kind 組合、flag 組合、min_occurrences streak）組合爆炸。強烈建議導入 Hypothesis：

```python
from hypothesis import given, strategies as st, assume

@given(
    before_val=st.one_of(st.integers(-1000, 1000), st.none(), st.booleans()),
    after_val=st.one_of(st.integers(-1000, 1000), st.none(), st.booleans()),
    delta=st.integers(1, 10),
)
def test_increment_invariant_properties(before_val, after_val, delta):
    """increment kind: skip on None/bool, pass iff after == before + delta."""
    oc = make_oracle([{"id": "t", "field": "x", "kind": "increment", "delta": delta}])
    result = oc.check_action("any", {"x": before_val}, {"x": after_val})
    
    # Property: None/bool inputs should always skip (no violation)
    if before_val is None or after_val is None or isinstance(before_val, bool) or isinstance(after_val, bool):
        assert result == []
    # Property: exact increment should pass
    elif after_val == before_val + delta:
        assert result == []
    # Property: anything else should violate
    else:
        assert len(result) == 1
```

重點 properties 待驗證：
- **Skip-on-None 不變性**：任何 `None`/`bool` 輸入永遠不產生 violation
- **Streak 單調性**：consecutive violation count 永遠遞增直到 pass 重置
- **Range 對稱性**：`range` kind 只看 after，不受 before 影響
- **Record=False 無副作用**：呼叫前後 violations/candidates/streaks 不變

**來源 URL**：
- https://semaphore.io/blog/property-based-testing-python-hypothesis-pytest
- https://python-testing-debugging.com/property-based-fuzz-testing-strategies/
- https://mergify.com/blog/pytest-hypothesis-seed-non-determinism

**優先級**：High

**預期效果**：以 100 examples/test 可在 <1 秒內探索 oracle 的邊界條件，發現手動測試難以覆蓋的 edge case（如整數溢位、float vs int 比較）。

---

## 建議 4：Perceiver 浮點斷言改用 pytest.approx 防止跨平台 Flakiness

**提問**：perceiver 測試依賴 numpy 浮點運算和 SSIM 計算，目前用硬編碼 threshold（如 `0.4 < ratio < 0.6`）。這些 assertion 在不同平台上會有精度差異導致 flaky 嗎？

**優化建議**：

目前的 `test_perceiver.py` 使用範圍斷言（如 `0.4 < ratio < 0.6`）是正確做法，但有兩處風險：

1. **SSIM 計算**：`compute_ssim` 使用全局 mean/var，不同 numpy 版本的浮點精度可能導致 `ssim > 0.99` 在某些環境下變成 `0.9899...`
2. **pixel_diff_ratio**：涉及 `int16` 轉換和除法，在不同 CPU 架構上可能有微小差異

建議修改：
```python
# 將精確邊界改為 approx
def test_identical_images_ssim_1(self):
    frame = _make_rgb(128, 128, 128)
    ssim = compute_ssim(frame, frame.copy())
    assert ssim == pytest.approx(1.0, abs=0.01)  # 而非 ssim > 0.99

def test_partial_change(self):
    # ...
    ratio = pixel_diff_ratio(frame1, frame2)
    assert ratio == pytest.approx(0.5, abs=0.1)  # 而非 0.4 < ratio < 0.6
```

同時建議加入 `@pytest.mark.filterwarnings("ignore::RuntimeWarning")` 防止 numpy 除以零等 warning 干擾。

**來源 URL**：
- https://docs.pytest.org/en/stable/explanation/flaky.html
- https://qaskills.sh/blog/pytest-xdist-parallel-testing-guide

**優先級**：Low

**預期效果**：消除跨平台 CI（Windows/Linux/macOS matrix）的潛在 flaky failures，測試意圖更明確。

---

## 建議 5：Playwright E2E 測試採用多層 Retry 策略

**提問**：如果未來加入 Playwright E2E 測試（連真實 browser），建議怎麼設計 retry？用 pytest-rerunfailures 還是在 Playwright 層級做 auto-wait + retry？

**優化建議**：

建議**雙層 retry 策略**，避免單一層級的盲目重試：

**Layer 1 - Playwright 內建 auto-wait（首選）**：
- 使用 Locator-based API（自帶 actionability checks）
- 設定合理的 `expect` timeout（WebGL 載入較慢，建議 15-30 秒）
- 絕對不用 `page.wait_for_timeout()`（hard wait）

**Layer 2 - pytest-playwright-artifacts + 選擇性 retry**：
```toml
[tool.pytest.ini_options]
playwright_timeout_retries = 2  # 僅對 TimeoutError retry
```

使用 `pytest-playwright-artifacts` 而非通用的 `pytest-rerunfailures`，因為：
- 只對 Playwright `TimeoutError` retry（assertion failures 立即失敗）
- 失敗時自動保存 screenshot + console log + DOM snapshot
- 不會掩蓋真正的 bug

**WebGL 特殊考量**：
```python
# conftest.py for E2E
@pytest.fixture
def webgl_page(page):
    """Wait for WebGL context to be ready before tests."""
    page.goto(GAME_URL)
    # Wait for canvas to be present and WebGL context created
    page.wait_for_selector("canvas", state="attached", timeout=30000)
    page.wait_for_function("document.querySelector('canvas').getContext('webgl2') !== null")
    return page
```

**來源 URL**：
- https://playwright.dev/docs/best-practices
- https://semaphore.io/blog/flaky-tests-playwright
- https://playwright.dev/docs/test-retries
- https://github.com/iloveitaly/pytest-playwright-artifacts

**優先級**：Medium（未來導入 E2E 時實施）

**預期效果**：E2E 測試穩定度達到 >98% pass rate on first run，失敗時有完整 debug artifacts，不會因 retry 掩蓋真正問題。

---

## 建議 6：建立 Coverage 報告與合理 Target

**提問**：目前沒有 coverage 報告。對這種 QA framework 專案，coverage target 應該設多少？哪些模組最需要優先覆蓋？

**優化建議**：

建議分模組設定 coverage 目標：

| 模組 | 目標覆蓋率 | 理由 |
|------|-----------|------|
| oracle.py | 95%+ | 核心判斷邏輯，錯誤直接導致 false positive/negative |
| parser.py | 90%+ | Vision 回應解析，robustness 關鍵 |
| perceiver.py | 85%+ | 數值計算，已有良好測試 |
| detector.py | 85%+ | 異常偵測，目前**零測試**，最需補齊 |
| knowledge_base.py | 80%+ | 資料讀取，已有測試 |
| agent.py / browser.py | 60%+ | 整合層，部分需 mock |

配置：
```toml
[tool.coverage.run]
source = ["webgl_qa"]
relative_files = true
parallel = true

[tool.coverage.report]
show_missing = true
fail_under = 75
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

**最急迫缺口**：`detector.py`（201 行，零測試覆蓋）是最需要優先補測試的模組。

**來源 URL**：
- https://danielnouri.org/notes/2025/11/03/modern-python-ci-with-coverage-in-2025/
- https://pytest-cov.readthedocs.io/en/stable/xdist.html

**優先級**：High

**預期效果**：建立可量化的品質基線，PR 中即可看到 coverage diff，防止新代碼無測試合併。

---

## 建議 7：Knowledge Base 測試用 Inline Fixture 隔離

**提問**：test_knowledge_base.py 依賴 `knowledge/example_game/` 的實際 YAML 檔案。如果未來多人開發時有人改了 YAML 結構，這些測試會連帶壞掉。應該用 snapshot 或 inline fixture 來隔離嗎？

**優化建議**：

建議**混合策略**：保留現有的 filesystem fixture 作為 integration smoke test，同時新增 inline fixture 做隔離的 unit test：

```python
# tests/conftest.py
@pytest.fixture
def minimal_kb(tmp_path):
    """Inline YAML fixture — isolated from real knowledge/ changes."""
    systems_dir = tmp_path / "systems"
    systems_dir.mkdir()
    (systems_dir / "combat.yaml").write_text("""
system_id: combat
name: Combat
recognition_keywords: ["攻擊", "射擊", "戰鬥"]
default_action: attack
actions:
  attack:
    steps:
      - {type: click, x: 500, y: 300}
""")
    (tmp_path / "flow_graph.yaml").write_text("""
edges:
  - {from: lobby, to: combat, trigger: start_button}
""")
    (tmp_path / "game_info.yaml").write_text("{}")
    return KnowledgeBase("test_game", base_dir=tmp_path)
```

這樣：
- **Inline fixture tests**：驗證 KnowledgeBase 的邏輯行為，不受 YAML 結構演進影響
- **Filesystem fixture test**：保留 1-2 個 smoke test 確保 `knowledge/example_game/` 結構仍然有效（作為 documentation test）
- 使用 `tmp_path` fixture 確保平行執行時不衝突

**來源 URL**：
- https://docs.pytest.org/en/stable/explanation/flaky.html
- https://qaskills.sh/blog/pytest-xdist-parallel-testing-guide

**優先級**：Medium

**預期效果**：測試穩定性提升，多人協作時 YAML schema 變更不會造成非相關測試失敗，同時保留對真實知識庫格式的 smoke test 覆蓋。

---

## 總結優先順序

| # | 建議 | 優先級 | 投入/產出比 |
|---|------|--------|------------|
| 2 | 分層 CI 管線 | High | 一次設定，長期受益 |
| 6 | Coverage 報告 + detector.py 補測試 | High | 填補最大覆蓋缺口 |
| 3 | Hypothesis property-based testing | High | 核心邏輯的邊界安全網 |
| 1 | pytest-xdist 平行化 | Medium | 基礎設施，測試量大時回報 |
| 7 | Inline fixture 隔離 | Medium | 團隊擴展時必要 |
| 5 | Playwright E2E retry 策略 | Medium | 未來 E2E 時實施 |
| 4 | 浮點斷言改進 | Low | 風險低但值得做 |
