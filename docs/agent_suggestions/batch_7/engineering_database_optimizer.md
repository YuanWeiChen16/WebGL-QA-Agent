# Database Optimizer 審查建議

> 審查角色：Database Optimizer（資料庫效能與架構專家）
> 審查對象：知識庫儲存架構（knowledge_base.py、YAML 資料層、session 資料）
> 日期：2026-07-16

---

## 審查摘要

本專案以 YAML 作為知識庫的主要儲存格式，搭配 singleton cache 與 BFS 路徑查詢。經與 KB Defender 對質後，多數設計選擇在**當前規模**（單遊戲、單 session、<50 節點）下是合理的「最簡單正確的事」。以下建議聚焦於 **已確認的弱點（併發安全）** 與 **低成本的架構改善**，不建議過度工程化。

---

## 建議 1：為 runtime knowledge.yaml 加入 filelock 防止併發寫入損毀

**嚴重度：中（已確認弱點）**

### 現況問題

`save_runtime()`（L493-498）直接 `open() + write()`，無任何檔案鎖。若未來需要多帳號並行 QA 同一款遊戲（合理的下一步需求），會發生 race condition 導致 YAML 檔案損毀（last-write-wins 或 partial write）。

### 建議方案

使用 `filelock` 套件（MIT、Production/Stable、跨平台）包裝所有 `save_runtime()` 呼叫：

```python
from filelock import FileLock

class KnowledgeBase:
    def __init__(self, game_name: str):
        ...
        self._lock = FileLock(f"{self.runtime_path}.lock", timeout=10)

    def save_runtime(self):
        with self._lock:
            with open(self.runtime_path, "w", encoding="utf-8") as f:
                yaml.dump(self._runtime_data, f, allow_unicode=True)
```

成本極低（一個依賴、幾行程式碼），且不改變現有架構。若需要 reader-writer 分離（多 reader、單 writer），`filelock` 3.29+ 提供 `ReadWriteLock`（SQLite-backed）。

### 參考資料

- filelock 官方文件 — Concepts and Design（race condition 說明 + 解法）：https://py-filelock.readthedocs.io/en/latest/concepts.html
- filelock How-to Guides（timeout、async、read-write lock 用法）：https://py-filelock.readthedocs.io/en/latest/how-to.html
- PyPI filelock 3.29.4（MIT, Production/Stable）：https://pypi.org/project/filelock/

---

## 建議 2：引入 SQLite 衍生索引層，支援跨 session 分析查詢

**嚴重度：低（未來增強，目前非阻塞）**

### 現況問題

KB Defender 正確指出跨 session 統計不是 `knowledge_base.py` 的職責。但從**專案層級**看，「某 bug 出現幾次」「某 transition 的歷史成功率」「哪些 session 觸發了 CONTEXT_LOST_WEBGL」這類查詢需求是 QA 工具的核心價值。目前 `runs/<game>/<timestamp>/session.json` 是純檔案，無法高效回答這些問題。

### 建議方案

採用業界常見的「YAML 為 source of truth + SQLite 為衍生索引」模式：

```
knowledge/<game>/
├── systems/*.yaml          ← 人類可讀、git-friendly（source of truth）
├── flow_graph.yaml
├── problems/*.md
└── .index.db               ← SQLite 衍生索引（gitignored、可重建）
    ├── sessions（timestamp, duration, anomaly_count, ...）
    ├── bugs（bug_id, session_id, screen, severity, reproduced_count）
    ├── transitions（from, to, success, timestamp）
    └── FTS5 index on problems
```

重點：**YAML 仍是 source of truth**，SQLite 是可隨時 `rebuild` 的快取索引。這個模式已被多個 AI agent memory 專案驗證。

### 參考資料

- Pyrite — YAML/Markdown source of truth + SQLite FTS5 衍生索引架構：https://github.com/markramm/pyrite
- secondbrain-db — file-backed ORM + SQLite knowledge graph（可重建、gitignored）：https://github.com/sergio-bershadsky/secondbrain-db/
- TRW-Memory — SQLite primary + YAML backup 雙儲存架構，含 hybrid search：https://github.com/wallter/trw-memory
- aiseed.dev — 「JSON/YAML for settings; SQLite for mutable data」決策框架：https://aiseed.dev/en/ai-native-ways/data-formats/

---

## 建議 3：problems/ 搜尋改用 FTS5 或按 system_id 分區

**嚴重度：低（目前 n<100 無痛點，但架構可預備）**

### 現況問題

`find_solution()` 的評分制字串比對在 <100 條時是亞毫秒級，KB Defender 的辯護成立。但若採納建議 2 的 SQLite 索引層，可以幾乎零額外成本地獲得 FTS5 全文搜尋能力。

### 建議方案（二擇一）

**方案 A（最小改動）**：在 `find_solution()` 前加一層 `system_id` 篩選，將搜尋空間從 O(n) 降到 O(n/k)：

```python
def find_solution(self, symptoms: list[str], system_id: str | None = None):
    candidates = self.problems
    if system_id:
        candidates = [p for p in candidates if p.get("system_id") == system_id]
    # existing scoring logic...
```

**方案 B（若已有 SQLite 索引）**：建立 FTS5 虛擬表：

```sql
CREATE VIRTUAL TABLE problems_fts USING fts5(
    problem_id, system_id, symptoms, solution,
    tokenize='unicode61'
);
```

中文 tokenize 可用 `unicode61` 的 character-level 或搭配 jieba 前處理。

### 參考資料

- ai-wiki — SQLite FTS5 用於中英文知識搜尋：https://libraries.io/pypi/ai-wiki
- SQLite FTS5 官方文件（tokenizer 選項）：https://www.sqlite.org/fts5.html
- kaygee — flat SQLite-native knowledge graph with YAML frontmatter：https://pypi.org/project/kaygee/

---

## 建議 4：runtime 學習層改為 per-session 寫入 + session 結束時 merge

**嚴重度：低（配合建議 1 的併發安全設計）**

### 現況問題

目前 `knowledge.yaml` 是全域 runtime 狀態的唯一檔案。即使加了 filelock，高頻寫入（每次 transition 都 save）在多 session 場景下仍會造成鎖競爭。

### 建議方案

將 runtime 寫入改為 per-session 檔案，session 結束時再 merge 回主檔：

```
knowledge/<game>/
├── knowledge.yaml              ← 合併後的穩定版
└── .sessions/
    ├── session_20260716_1000.yaml  ← session A 的 runtime delta
    └── session_20260716_1001.yaml  ← session B 的 runtime delta（並行無衝突）
```

merge 邏輯：
- transitions：取 union，confidence 取 max
- bugs：取 union，reproduced 取 sum
- screens：取 union，元素位置取最新

這消除了 runtime 期間的檔案競爭，只在 `finish()` 時做一次受控合併。

### 參考資料

- secondbrain-db 的 per-doc sidecar 模式（兩個 PR 改不同 doc、git merge 零衝突）：https://github.com/sergio-bershadsky/secondbrain-db/
- SQLite 官方 — 「database sharding: separate database files for different subdomains」：https://sqlite.org/whentouse.html
- filelock ReadWriteLock — 若 merge 時需要 exclusive write：https://py-filelock.readthedocs.io/en/latest/how-to.html

---

## 建議 5：為 YAML 知識庫加入 schema 驗證防止手動編輯破壞結構

**嚴重度：低（防禦性措施）**

### 現況問題

YAML 的一大優勢是「人類可讀可編輯」，但劣勢是**一個縮排錯誤就能破壞整個檔案**。目前 `_load_systems()` 載入時若 YAML 格式錯誤，會直接拋例外中斷 session。知識庫是跨 session 累積的資產，損毀代價高。

### 建議方案

1. **載入時 graceful degradation**：YAML parse 失敗時 log warning 並跳過該檔案，而非中斷整個 session
2. **寫入時 schema 驗證**：用 JSON Schema 或 Pydantic model 驗證 systems/*.yaml 的結構正確性
3. **備份機制**：每次 `save_runtime()` 前自動備份前一版（`.knowledge.yaml.bak`）

```python
import shutil

def save_runtime(self):
    with self._lock:
        if self.runtime_path.exists():
            shutil.copy2(self.runtime_path, f"{self.runtime_path}.bak")
        with open(self.runtime_path, "w", encoding="utf-8") as f:
            yaml.dump(self._runtime_data, f, allow_unicode=True)
```

### 參考資料

- secondbrain-db — JSON Schema 2020-12 驗證 YAML frontmatter + integrity signing：https://github.com/sergio-bershadsky/secondbrain-db/
- aiseed.dev — 「Hand-editing a JSON/YAML file can break the whole file with a bracket or indentation error」：https://aiseed.dev/en/ai-native-ways/data-formats/
- YantrikDB — schema validation at write time 的 0% invalid admission rate vs filesystem 的 97%：https://yantrikdb.com/papers/skill-substrate/

---

## 總結優先級

| # | 建議 | 優先級 | 成本 | 理由 |
|---|------|--------|------|------|
| 1 | filelock 併發保護 | **高** | 極低（1 依賴 + 3 行） | 已確認弱點，修復成本極低 |
| 4 | per-session runtime 寫入 | 中 | 低 | 配合 #1，徹底解決併發問題 |
| 5 | schema 驗證 + backup | 中 | 低 | 保護累積資產，防禦性措施 |
| 2 | SQLite 衍生索引層 | 低 | 中 | 未來需求，可在需要跨 session 分析時再引入 |
| 3 | FTS5 / system_id 分區 | 低 | 極低 | 順手改，或等 #2 一起做 |

**核心觀點**：本專案的 YAML-first 設計在當前規模下是正確的。建議 1 是唯一「現在就該做」的改善；其餘建議為「成長路徑上的 checkpoint」，在需求出現時再引入即可。不建議為了假設性的規模而過度工程化。
