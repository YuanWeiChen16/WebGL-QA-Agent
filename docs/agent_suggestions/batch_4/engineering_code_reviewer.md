# Code Reviewer 工程審查建議 — Batch 4

> 審查對象：`src/webgl_qa/agent.py`、`src/webgl_qa/oracle.py`
> 角色：Code Reviewer（正確性、安全性、可維護性、效能、測試）
> 日期：2026-07-16

---

## 🔴 Blocker 1：`check_invariants` 的 bare `except Exception: pass` 靜默吞掉 reread 失敗

**位置**：`agent.py` L456-458

```python
except Exception:
    # reread failed (screenshot/Vision error) — fall back to single read.
    pass
```

**問題**：當 Vision gateway timeout 或網路異常時，double-check（二次確認）機制被完全跳過，但回傳結果中沒有任何降級警告。Caller 會收到看似正常的 violation 列表，卻不知道 false-positive 抑制機制已失效。

**Defender 確認**：「這是 bug，不是設計。正確做法：catch timeout → 標記 `confidence: degraded` 或 `reread_failed: true`。」

**建議修法**：

```python
except Exception as exc:
    import logging
    logging.getLogger(__name__).warning(
        "Oracle reread failed, double-check degraded: %s", exc
    )
    # Mark that surviving_ids filter is not trustworthy
    double_checked = False  # already False, but make intent explicit
    # Optionally: result["reread_failed"] = True
```

回傳結果加入 `reread_failed: bool` 欄位，讓報告與呼叫者能顯示「此 violation 未經二次確認」的警告。

**為什麼重要**：
- PEP 760 已提議禁止 bare except，PEP 8 明確反對靜默吞掉例外
- 在 async 環境下，靜默的 `except Exception: pass` 會掩蓋 `CancelledError` 以外的所有錯誤，包含 OOM、連線池耗盡等系統級問題
- 業界共識：「Log at the point of richest context」— except block 是最有上下文的地方

**參考資料**：
- https://peps.python.org/pep-0760/ — PEP 760: No More Bare Excepts
- https://www.flake8rules.com/rules/E722.html — flake8 E722: bare except anti-pattern
- https://engineersofai.com/docs/python/python-foundation/error-handling-and-defensive-engineering/common-error-anti-patterns — Common Error Anti-Patterns: Silent Failures
- https://dev.to/theauroraai/the-async-error-handling-patterns-that-actually-work-in-production-13cc — Async Error Handling Patterns（`except Exception: pass` in async task 列為 anti-pattern）

---

## 🔴 Blocker 2：Global mutable singleton 阻礙並行與測試

**位置**：`agent.py` L542-596

```python
_session: Optional[GameSession] = None

async def start_session(game_url: str, ...) -> dict:
    global _session
    _session = GameSession(...)
    return await _session.start()
```

**問題**：
1. 同一 process 無法同時跑兩個 GameSession（例如 A/B 測試兩個遊戲版本）
2. pytest 並行時若共用同一 module state 會互相踩踏
3. 無法做 dependency injection，mock 測試困難
4. 模組載入時期的全域狀態在 async 環境中是已知的 footgun

**Defender 確認**：「你完全正確，這是技術債。async with GameSession(...) as session: 是正確方向。」

**建議修法**：

```python
class GameSession:
    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.finish()
        return False

# 使用方式
async with GameSession(game_url=url, game_name=name) as session:
    obs = await session.observe()
    await session.execute_action({"type": "click", "x": 640, "y": 360})
```

保留舊的 convenience functions 作為 deprecated wrapper（加 `warnings.warn`），逐步遷移。

**參考資料**：
- https://docs.python.org/3/library/contextlib.html — Python contextlib: asynccontextmanager 官方文件
- https://www.learnwithparam.com/blog/async-context-management-python-ai-services — Async Context Management for Python AI Services（「Never store resources in module globals」）
- https://uguraslim.com/blog/fastapi-lifespan-events-for-multi-tenant-resource-initializa/ — Avoiding Singleton Hell: Lifespan Context Manager Pattern
- https://abhi.rodeo/posts/programming/languages/python/fastapi/globals-in-fastapi/ — Global Dependencies Done Right: Why module-level state is wrong

---

## 🟡 Suggestion 1：Oracle `_streaks` 加入 action-distance decay

**位置**：`oracle.py` L85 `self._streaks: dict`

**問題**：streak 只在同一 invariant pass 時歸零。如果 session 中間很長一段時間都沒觸發某個 action_tag（例如 "upgrade"），過時的 streak 會在下次觸發時立即計為「連續第 N 次失敗」，即使中間已過了幾百步完全無關的操作。

**Defender 回應**：「意圖是捕捉『每次升級都失敗』的模式。但你說得對，長時間不觸發的 streak 是 stale data。可以加 TTL。」

**建議修法**：

```python
@dataclass
class StreakEntry:
    count: int = 0
    last_step: int = 0  # 記錄最後觸發的 step

class Oracle:
    def __init__(self, config=None):
        self._streaks: dict[str, StreakEntry] = {}
        self._global_step = 0
        # 從 config 讀取 decay distance，預設 50 步
        self._streak_decay_distance = config.get("oracle.streak_decay_distance", 50) if config else 50

    def check(self, invariant, before, after, flags=None, record=True):
        if record:
            self._global_step += 1
            entry = self._streaks.get(invariant.id, StreakEntry())
            # Decay: 如果距離上次觸發超過 N 步，reset
            if self._global_step - entry.last_step > self._streak_decay_distance:
                entry.count = 0
            entry.last_step = self._global_step
            # ... 後續邏輯
```

**參考資料**：
- https://ar5iv.labs.arxiv.org/html/2207.08379 — Microsoft Inspector: Pixel-Based Game Testing（curiosity-based exploration 中使用 step-distance 衰減來判斷「新穎性」是否過期）
- https://arxiv.org/html/2604.11082v1 — RESP: Reference-guided Sequential Prompting（LastCleanFrame 策略：以「時序距離」決定 reference 是否仍有效）

---

## 🟡 Suggestion 2：`_verify_action_effect` 加入 per-screen adaptive pixel_diff 門檻

**位置**：`agent.py` L284-286

```python
min_diff = cfg.get("min_pixel_diff", 0.005)
```

**問題**：
- 高動態場景（魚群游動、粒子特效）：idle 狀態的 pixel_diff 已遠超 0.005 → noop 偵測永遠判為 "changed" → 失效
- 靜態 UI 畫面：anti-aliasing 抖動 < 0.005 但可能是 0.003 → 真正的 UI 反應（例如按鈕高亮）也被判為 "no change"

**Defender 確認**：「目前沒有 adaptive mechanism。計畫方向：per-screen baseline + ROI-based diff。」

**建議修法（per-screen baseline）**：

```python
class GameSession:
    _screen_baselines: dict[str, float] = {}  # screen_id -> idle pixel_diff mean

    async def _calibrate_screen_baseline(self, screen_id: str, samples: int = 3):
        """Take N idle screenshots and compute the natural pixel_diff distribution."""
        diffs = []
        for _ in range(samples):
            await asyncio.sleep(0.3)
            b64 = await self.browser.screenshot()
            frame = decode_to_array(b64)
            if self._last_frame_array is not None:
                diffs.append(pixel_diff_ratio(self._last_frame_array, frame))
            self._last_frame_array = frame
        if diffs:
            mean = sum(diffs) / len(diffs)
            std = (sum((d - mean)**2 for d in diffs) / len(diffs)) ** 0.5
            self._screen_baselines[screen_id] = mean + 2 * std  # 2σ above idle
```

在 `_verify_action_effect` 中：
```python
adaptive_min = self._screen_baselines.get(self.current_screen_id, min_diff)
changed = diff >= max(min_diff, adaptive_min)
```

**參考資料**：
- https://ar5iv.labs.arxiv.org/html/2208.02335 — Automatically Detecting Visual Bugs in HTML5 Canvas Games（「threshold should be defined empirically and for each game, as different games may have different levels of in-game randomness」）
- https://bugnet.io/blog/how-to-automate-screenshot-comparison-testing — Automating Screenshot Comparison for Games（「pixel art games can use very tight thresholds, while 3D games with complex lighting need more room」）
- https://doi.org/10.1145/3047407 — Automatic Detection of Game Engine Artifacts Using Full Reference IQMs（SSIM + perceptual metric 用於動態場景，per-scene threshold tuning）
- https://pdiff.sourceforge.net/metric.html — Perceptual Diff: 為什麼固定 pixel threshold 在動態場景中產生大量 false positive

---

## 🟡 Suggestion 3：Oracle `decrease_or_flag` 加入 `required_flags` schema 驗證

**位置**：`oracle.py` L47-64（Invariant dataclass）、L165-167（check 邏輯）

**問題**：`unless_flag` 欄位依賴 caller 傳入的 `flags` dict，但：
1. 沒有 schema 驗證 — caller 忘記傳 `reward_detected` 不會有任何警告
2. 沒有文件化約束 — 哪些 invariant 需要哪些 flags 只能讀 YAML 推斷
3. 靜默誤判 — flags 缺失時 `flags.get(unless_flag)` 回傳 None → 被當成 falsy → invariant 判為 violated

**Defender 確認**：「Low-effort high-impact fix。應在 Invariant dataclass 加 required_flags，check 時做 assertion。」

**建議修法**：

```python
@dataclass
class Invariant:
    # ... existing fields ...
    required_flags: list[str] = field(default_factory=list)

class Oracle:
    def check(self, invariant, before, after, flags=None, record=True):
        flags = flags or {}
        # Schema validation: warn on missing required flags
        if invariant.required_flags:
            missing = set(invariant.required_flags) - set(flags.keys())
            if missing:
                import logging
                logging.getLogger(__name__).warning(
                    "Invariant [%s] requires flags %s but received %s — "
                    "check may produce false positives",
                    invariant.id, invariant.required_flags, list(flags.keys())
                )
        # ... rest of check logic
```

在 `game_info.yaml` 中宣告：
```yaml
oracle:
  invariants:
    - id: currency_decrease_on_shoot
      when: shoot
      field: currency
      kind: decrease_or_flag
      unless_flag: reward_detected
      required_flags: [reward_detected]  # 新增
      severity: medium
```

**參考資料**：
- https://debuglab.net/2026/05/15/stop-using-try-except-as-control-flow-in-python-services/ — Typed Result Patterns: 為什麼 stringly-typed loose contracts 在跨邊界時需要 schema enforcement
- https://docs.python.org/3/library/dataclasses.html — Python dataclasses: field(default_factory=list) 標準做法
- https://fastapi-patterns.com/core-architecture-routing-patterns/dependency-injection-strategies/ — Dependency Injection: 為什麼 implicit contracts 應該被 explicit validation 取代

---

## 💭 Nit：convenience functions 加 deprecation warning

**位置**：`agent.py` L540-597

即使短期內保留 `start_session()` / `finish_session()` 等模組層級 convenience functions，建議加入 `DeprecationWarning` 引導使用者遷移：

```python
import warnings

async def start_session(game_url: str, game_name: str = None, headless: bool = None) -> dict:
    """Start a new QA session. Returns initial state.

    .. deprecated::
        Use ``async with GameSession(...) as session:`` instead.
    """
    warnings.warn(
        "start_session() is deprecated. Use 'async with GameSession(...) as session:' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    global _session
    _session = GameSession(game_url=game_url, game_name=game_name, headless=headless)
    return await _session.start()
```

**參考資料**：
- https://docs.python.org/3/library/warnings.html — Python warnings module: DeprecationWarning 標準用法

---

## 總結

| # | 嚴重度 | 問題 | 修復難度 |
|---|--------|------|----------|
| 1 | 🔴 Blocker | bare except 靜默吞掉 reread 失敗 | 低（5 行） |
| 2 | 🔴 Blocker | Global singleton 阻礙並行/測試 | 中（需遷移 callers） |
| 3 | 🟡 Should fix | Oracle streak 無 TTL/decay | 低（dataclass + 3 行邏輯） |
| 4 | 🟡 Should fix | pixel_diff 固定門檻在動態場景失效 | 中（需 calibration 機制） |
| 5 | 🟡 Should fix | flags schema 無驗證導致靜默誤判 | 低（dataclass 欄位 + warning） |
| 6 | 💭 Nit | convenience functions 無 deprecation 提示 | 低（加 warnings.warn） |
