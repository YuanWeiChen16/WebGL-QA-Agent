# ZK Steward 審查建議 — Batch 8

> 審查角色：Zettelkasten 知識管理觀點（Luhmann 原子筆記、連結性、驗證迴圈）
> 日期：2026-07-16

---

## 摘要

從 Niklas Luhmann 的 Zettelkasten 方法論出發，審查 `KNOWLEDGE_ARCHITECTURE.md` 與 `knowledge_base.py` 的知識結構設計。KB Defender 承認了 5 項挑戰中的 3 項弱點（連結密度、品質閘門、回饋迴圈），並辯護了原子性取捨與多重索引的現況。以下為基於外部研究的具體改善建議。

---

## 建議 1：引入 `affected_systems` / `affected_elements` 顯式反向連結

**問題**：`problems/*.md` 與 `systems/*.yaml` 之間缺乏 machine-readable 反向連結。KB Defender 承認這是「當前最大的結構性弱點之一」，在 problems 超過 ~20 條時會成為維護痛點。

**建議**：在每份 `problems/*.md` 的 YAML frontmatter 加入：

```yaml
---
affected_systems: [upgrade, skills]
affected_elements: [upgrade_confirm, skill_panel]
related_sessions: ["2026-07-10T14:30:00"]
---
```

同時在 `systems/*.yaml` 的 `known_issues` 條目加入 `problem_ref: stuck_upgrade` 指向 problems 目錄。這建立雙向連結，符合 Zettelkasten 的「每筆知識至少 2 條有意義連結」原則。

**依據**：Zettelkasten 方法的核心在於 backlinks 建立雙向關係，使知識可從多角度被發現。如同 Obsidian 社群所強調：「Links over folders — the structure emerges from the connections, not from a predetermined filing system。」

**參考 URL**：
- https://zettelkasten.de/atomicity/guide/ — Zettelkasten 原子性與連結原則完整指南
- https://www.apragmaticmind.com/blog/zettelkasten-method — 「Links over folders」原則的實務解釋

---

## 建議 2：導入知識庫新鮮度（Staleness）自動偵測機制

**問題**：`problems/*.md` 的 status 欄位（open/investigating/resolved）為人工維護，無自動過期機制。KB Defender 承認「永遠 investigating」的風險確實存在。座標漂移、過時的 known_issues 會累積為「死筆記」。

**建議**：實作 staleness scoring 工作流：

1. 每份知識文件加入 `last_verified_date` 欄位
2. 建立 `scripts/kb_freshness.py`，計算每份文件距上次驗證的天數
3. 分層告警：Fresh（< 30 天）→ Aging（30-90 天）→ Stale（> 90 天）
4. 在 QA session 結束時，自動更新被使用到的知識文件之 `last_verified_date`

可參考 frootai 的 `fai-knowledge-staleness` workflow 設計：基於 git log 計算天數、加權評分、自動產生更新建議。

**參考 URL**：
- https://github.com/frootai/frootai/blob/main/workflows/fai-knowledge-staleness.md — 完整的知識庫新鮮度偵測 workflow 範本（含加權公式與 CI 整合）
- https://snapsynapse.com/tools/knowledge-as-code/ — 「Knowledge as Code」模式：自我驗證的知識庫，每筆資料攜帶 `Checked` 日期，7 天未驗證視為 stale

---

## 建議 3：`update_element_location` 加入 confidence 閘門

**問題**：KB Defender 承認 `update_element_location()` 直接寫入 static YAML，沒有品質驗證步驟。Runtime transitions 有 confidence 漸進（low → medium → high），但座標更新缺乏同等機制。

**建議**：套用與 runtime transitions 相同的 confidence 漸進模式：

```python
def update_element_location(self, system_id, element_id, new_x, new_y, source="vision"):
    key = f"{system_id}.{element_id}"
    pending = self._pending_updates.get(key, [])
    pending.append({"x": new_x, "y": new_y, "timestamp": now()})
    
    # 只有連續 3 次 Vision 回報相近座標（容差 < 10px）才寫入 static YAML
    if len(pending) >= 3 and self._coordinates_converge(pending[-3:], tolerance=10):
        self._commit_to_yaml(system_id, element_id, new_x, new_y)
        self._pending_updates.pop(key)
```

這等同於 COMPASS KB Validation 框架中的 "HARD gate"：只有通過確定性驗證的資料才能進入正式知識庫。

**參考 URL**：
- https://pypi.org/project/compass-kb-validation/1.30.0/ — COMPASS：config-driven 的 KB 完整性閘門框架，分 HARD/WARN 層級
- https://github.com/soviar-systems/vadocs — vadocs：Documentation-as-Code 的驗證引擎，偵測 YAML metadata 漂移

---

## 建議 4：視覺特徵索引（Screen Signature Index）作為第五入口

**問題**：KB Defender 承認缺少「視覺特徵」入口。目前 agent 看到畫面只能靠 Vision LLM → OCR → keyword match。SSIM 已用於凍結偵測但未作為知識庫索引鍵。

**建議**：為每個 system 建立 `visual_signature` 欄位：

```yaml
system_id: upgrade
visual_signature:
  dominant_colors: ["#2D5A8C", "#FFD700"]  # 升級面板的主色調
  template_region: {x: 40, y: 180, width: 320, height: 60}
  ssim_reference: "references/upgrade_panel.png"
  min_ssim_threshold: 0.75
```

這讓 `perceiver.py` 的 SSIM 計算直接作為知識庫查詢條件，不依賴 OCR。符合 Zettelkasten 的「多重入口」原則——同一筆知識可透過任務語意、關鍵字、症狀描述、拓撲位置、**和視覺特徵**五個維度被發現。

**依據**：KLPEG 論文（2025）展示了 Knowledge Graph 增強的遊戲測試框架如何透過多重推理路徑（multi-hop reasoning）從不同角度定位受影響的遊戲元素。視覺特徵索引是同一概念在感知層的應用。

**參考 URL**：
- https://doi.org/10.48550/arxiv.2511.02534 — KLPEG：Knowledge Graph-enhanced LLM for Incremental Game PlayTesting，展示結構化知識如何提升遊戲測試精確度
- https://nodemori.com/ — Nodemori：autonomous AI QA，每次 session 累積學習，改善覆蓋率與準確度的 feedback loop

---

## 建議 5：解法信心分數與回饋溯源（Solution Confidence Scoring）

**問題**：KB Defender 承認 `find_solution()` 回傳解法後無紀錄「是否生效」的機制。解法沒有 success_count / failure_count。知識不會「隨使用而成長或衰退」。

**建議**：在 `problems/*.md` 或 runtime knowledge 層加入回饋追蹤：

```yaml
solution_feedback:
  - session: "2026-07-10T14:30:00"
    result: success
    context: "upgrade from level 2 to 3"
  - session: "2026-07-11T09:15:00"
    result: failure
    context: "coordinate drifted after resolution change"
    
success_rate: 0.5
last_succeeded: "2026-07-10T14:30:00"
last_failed: "2026-07-11T09:15:00"
```

`find_solution()` 回傳時附帶 confidence score，讓 agent 在低信心時嘗試替代方案或觸發 Vision 重新探索。這等同於 Zettelkasten 中「continued dialogue」原則——筆記不是靜態記錄，而是持續對話的活體。

**依據**：GameDriver 的 QaaS 模型與 Nodemori 的 continuous feedback loop 都展示了「每次執行回饋改善下次判斷」的循環機制。知識庫需要同樣的「anti-entropy」——主動偵測知識與現實的偏離。

**參考 URL**：
- https://gamedriver.ai/ — GameDriver QaaS：AI 持續維護測試覆蓋，每次 build 回饋調整
- https://snapsynapse.com/tools/knowledge-as-code/ — 「Anti-entropy for knowledge」：如同分散式系統偵測狀態漂移，知識庫需要主動修復機制

---

## 優先順序建議

| # | 建議 | 緊急度 | 實作難度 | KB Defender 態度 |
|---|------|--------|----------|-----------------|
| 1 | 顯式反向連結 | 高 | 低 | ⚠️ 承認弱點 |
| 2 | Staleness 偵測 | 高 | 中 | ⚠️ 承認弱點 |
| 3 | Confidence 閘門 | 高 | 中 | ⚠️ 承認弱點 |
| 4 | 視覺特徵索引 | 中 | 高 | ⚖️ 認可方向 |
| 5 | 解法信心分數 | 中 | 中 | ⚠️ 承認缺失 |

建議 1-3 為 KB Defender 明確承認的弱點且實作成本可控，應優先處理。建議 4-5 需要更多設計討論但長期價值高。

---

## Zettelkasten 四原則驗證

| 原則 | 現況評估 |
|------|----------|
| 原子性（Atomicity） | ⚖️ 刻意取捨——以「操作單位內聚」換取載入簡潔性，可接受但 known_issues 應抽離 |
| 連結性（Connectivity） | ⚠️ 隱式語意連結（keyword scoring）存在，但缺乏顯式 machine-readable backlinks |
| 有機成長（Organic Growth） | ⚠️ 自動學習缺品質閘門，可能累積低品質「死筆記」|
| 持續對話（Continued Dialogue） | ⚠️ 解法無回饋機制，知識不會隨使用而演化 |
