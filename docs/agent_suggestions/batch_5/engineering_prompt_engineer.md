# Prompt Engineer 審查建議 — Batch 5

**審查角色**：Engineering Prompt Engineer  
**審查對象**：`src/webgl_qa/prompts.py`、Vision prompt 設計與 oracle 讀數可靠性  
**日期**：2026-07-16  

---

## 摘要

針對 `prompts.py` 的 5 項設計挑戰與 arch-defender 辯論後，確認目前架構在關鍵路徑（oracle ground truth）使用 tool_use schema enforcement 是合理的分層設計。但在 **Vision OCR 準確率提升**、**不確定性處理**、以及 **prompt 變更可追溯性** 方面仍有可量化改進空間。以下 5 項建議均附業界研究佐證。

---

## 建議 1：為 game_state 讀數加入 Preprocessing Hints（圖像前置描述）

**問題**：`build_screen_analysis_prompt` 要求模型讀取數值（score/currency/level/lives），但未告知模型「這些數字長什麼樣」——字型、顏色、位置區域等先驗資訊完全缺失。

**arch-defender 回應**：認為 tool_use schema 的 field description（"read the digits exactly as displayed"）已足夠。

**反駁與佐證**：

業界研究明確指出，Multimodal LLM 的 OCR 準確率在給予 **Preprocessing Hints**（告知圖像狀態、字型特徵、數字位置）時顯著提升。特別是遊戲 UI 字型通常有描邊、發光、動態背景等干擾因素，模型需要知道「哪個區域有數字、大概是什麼風格」才能正確聚焦。

> "Just 3 hints — 'handwriting,' 'elderly,' and 'medical terminology' — significantly change the model's interpretation policy. The instruction 'if ambiguous, lean toward medical terminology' is especially effective."

**具體建議**：

在 `build_screen_analysis_prompt` 中，當 `known_elements` 包含 `type: display` 元素時，自動注入位置與視覺 hint：

```python
# 從 knowledge_base 的 elements 中提取 display 類型元素的位置描述
display_hints = []
for el in known_elements_raw:
    if el.get("type") == "display":
        loc = el.get("location", {})
        display_hints.append(
            f"- {el['label']}: around ({loc.get('x')},{loc.get('y')}), "
            f"likely bright digits on dark background"
        )
if display_hints:
    prompt += f"\n\nNumeric display locations (focus here for game_state):\n"
    prompt += "\n".join(display_hints)
```

**預期效果**：根據研究，coordinate-based grounding 可將定位誤差從 23% 降至 4%。

**參考**：
- https://www.codeworm.dev/2026/04/multimodal-llm-prompt-engineering_0224807796.html
- https://zenn.dev/coffin299/articles/60ba24446c0c27?locale=en （Technique 1: Preprocessing Hints）

---

## 建議 2：引入 Multi-pass OCR / Self-Verification 模式取代盲目二次確認

**問題**：AD-2 的 reread 機制是「違規時重截圖重讀」——但兩次都是完全獨立的 Vision 呼叫，沒有利用第一次的結果來引導第二次。

**arch-defender 回應**：兩次獨立截圖的壓縮 artifact 不同，系統性誤讀機率極低。

**反駁與佐證**：

Multi-pass OCR 研究顯示，「先讀一遍 → 標記低信心區域 → 針對性重讀」比「盲目讀兩遍取一致」更有效率且更準確。關鍵差異：第二次重讀時，模型已知道「哪個欄位可能有問題」，可以專注注意力。

> "The key is to have the AI mark [?] on areas it is not confident about in Pass 1. It is more efficient to identify problematic areas and then re-read them rather than blindly having it read twice."

**具體建議**：

新增一個 `build_verify_reading_prompt` 函數，用於 reread 時傳入第一次讀到的值：

```python
def build_verify_reading_prompt(config: dict, previous_reading: dict) -> str:
    """Build a verification prompt that focuses on previously-read values."""
    fields_to_verify = []
    for field, value in previous_reading.items():
        if value is not None:
            fields_to_verify.append(f"- {field}: previously read as {value}")
    
    return f"""Re-read the numeric displays in this screenshot.
Focus specifically on these values and confirm or correct them:
{chr(10).join(fields_to_verify)}

If a digit is ambiguous (e.g., 6 vs 8, 1 vs 7), report BOTH candidates.
Use the game_analysis tool to report your findings."""
```

**預期效果**：將 false positive（oracle 誤報 bug）率降低，同時不增加額外 Vision 呼叫次數（reread 本來就會呼叫，只是換一個更精準的 prompt）。

**參考**：
- https://zenn.dev/coffin299/articles/60ba24446c0c27?locale=en （Technique 3: Multi-pass OCR、Technique 10: Self-Verification）
- https://www.codeworm.dev/2026/03/multimodal-llm-prompt-engineering_01668183862.html （Graded Prompts: clarify → extract → verify）

---

## 建議 3：為輔助 prompt（task/menu）改用 Structured Outputs JSON Schema 替代 raw JSON 指示

**問題**：`build_task_analysis_prompt` 和 `build_menu_analysis_prompt` 要求 "Respond ONLY in JSON" 但走 raw text 回傳，容易被模型加 preamble 或 markdown code block 包裹導致 parse 失敗。

**arch-defender 回應**：這些是輔助路徑，不進 oracle；呼叫端有 JSON 萃取 fallback。

**反駁與佐證**：

Anthropic 2025-11 正式推出 Structured Outputs（`output_config.format: json_schema`），**不需要 tool_use 也能保證 schema compliance**。這比 `tool_choice: tool` 更輕量（不需定義完整 tool），又比 raw JSON prompt 更可靠（constrained decoding 保證格式）。

> "Structured outputs guarantee schema-compliant responses through constrained decoding: Always valid — No more JSON.parse() errors; Type safe — Guaranteed field types and required fields; Reliable — No retries needed for schema violations."

**具體建議**：

將輔助 prompt 的呼叫從 `analyze_screenshot()`（raw text）遷移到使用 `output_config.format` 的 API 呼叫：

```python
# vision.py 新增輕量級結構化呼叫
async def analyze_lightweight(self, screenshot, prompt, schema):
    """Structured JSON output without full tool_use overhead."""
    response = await self.client.messages.create(
        model=self.model,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": [image_block, {"type": "text", "text": prompt}]}]
    )
    return json.loads(response.content[0].text)
```

**預期效果**：消除輔助路徑的 JSON parse 失敗，不增加 token 成本（structured output 不需額外 tool definition tokens）。

**參考**：
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://claude.com/blog/structured-outputs-on-the-claude-developer-platform
- https://platform.claude.com/cookbook/tool-use-extracting-structured-json

---

## 建議 4：引入 Uncertainty Policy — 3 級信心制度

**問題**：prompt 只有 "use null when not visible" 的二值指示，無法區分「完全不可見」vs「模糊但可辨認」vs「清晰可讀」。

**arch-defender 回應**：LLM self-reported confidence calibration 差；用 null + 二次確認機制更可靠。

**反駁與佐證**：

同意 continuous confidence 不可靠，但 **discrete 3-level policy**（clear / ambiguous / not_visible）在 OCR 場景有明確實用價值。這不是要模型報 0.7 這種數字，而是讓它區分「看到但不確定」的情況——這直接影響 reread 觸發策略。

> "A 3-level confidence policy dramatically improves the efficiency of subsequent human review. It allows for 'only check fields with confidence: low' instead of 'visually check every field.'"

**具體建議**：

在 `game_state` schema 中加入 `reading_confidence` 欄位：

```python
# vision.py CORE_SCHEMA_PROPERTIES 擴充
"reading_confidence": {
    "type": "object",
    "description": "For each game_state field that has a value, report: "
                   "'clear' (digits sharp and unobstructed), "
                   "'ambiguous' (partially occluded, glowing, or small), "
                   "'null' (not attempted). Do NOT report numeric scores.",
    "properties": {
        "score": {"type": ["string", "null"], "enum": ["clear", "ambiguous", None]},
        "currency": {"type": ["string", "null"], "enum": ["clear", "ambiguous", None]},
        "level": {"type": ["string", "null"], "enum": ["clear", "ambiguous", None]},
        "lives": {"type": ["string", "null"], "enum": ["clear", "ambiguous", None]},
    }
}
```

呼叫端邏輯：`ambiguous` 欄位自動觸發 reread（使用建議 2 的 verify prompt），`clear` 欄位跳過 reread 節省成本。

**預期效果**：減少不必要的 reread（clear 欄位不需二次確認）、對 ambiguous 欄位提供更精準的 reread 引導。

**參考**：
- https://zenn.dev/coffin299/articles/60ba24446c0c27?locale=en （Technique 7: Uncertainty Policy — 3 級制度）
- https://www.codeworm.dev/2026/04/multimodal-llm-prompt-engineering_0224807796.html （"Require confidence scores < 0.7 to trigger human review"）

---

## 建議 5：導入 Prompt Regression Testing（schema 層 + 統計層分離）

**問題**：prompts.py 無版本控管、無自動化驗證。prompt 變更後無法偵測 Vision 輸出品質退化。

**arch-defender 回應**：tool_use schema 是穩定 contract；Vision 本身不可確定性測試，需 n>30 統計測試花真錢；AD-7 標 🧊 是刻意排序。

**部分同意，但建議分層實施**：

業界已有成熟的 prompt regression testing 框架，且支持分層：

1. **Schema contract test（零成本、確定性）**：驗證 prompt builder 產出格式正確、schema 欄位完整。現有 `test_oracle.py` 只測 oracle 邏輯，未測 prompt 本身。
2. **Golden set regression（低成本、CI 可整合）**：5-10 張標記過的參考截圖 + 預期讀數，每次 prompt 改動後跑一次，用 PromptForge/PromptCheck 類框架管理 baseline vs candidate diff。

> "In 2026, prompt changes are the most common cause of silent LLM regressions. Teams edit prompts in Google Docs, paste them into code, and ship — with zero version control, no diff visibility, and no quality gates."

**具體建議**：

**Phase 1（立即可做、零 API 成本）**：

```python
# tests/test_prompts.py
import pytest
from webgl_qa.prompts import build_screen_analysis_prompt, build_task_analysis_prompt

def test_screen_prompt_contains_game_state_instruction():
    """Regression: prompt must instruct reading game_state fields."""
    config = {"vision_context": {"game_type": "fishing game", "resolution_hint": "1280x720"}}
    prompt = build_screen_analysis_prompt(config)
    assert "game_state" in prompt
    assert "score" in prompt
    assert "null" in prompt  # must mention null for missing values
    assert "game_analysis" in prompt  # must reference tool

def test_task_prompt_json_schema_shape():
    """Regression: task prompt must request all required JSON fields."""
    config = {"vision_context": {"game_type": "WebGL game"}}
    prompt = build_task_analysis_prompt(config)
    for field in ["screen_id", "current_task", "suggested_click", "elements"]:
        assert field in prompt
```

**Phase 2（AD-4/AD-5 穩定後）**：

採用 PromptForge 或 PromptCheck 建立 golden dataset regression baseline，在 CI 中每次 prompt 變更時比對輸出品質。

```yaml
# .github/workflows/prompt-eval.yaml (示意)
- name: Run prompt regression
  uses: MPrazeres-1983/promptforge@v1
  with:
    prompt: prompts/screen_analysis.yaml
    dataset: datasets/golden_screenshots.yaml
    fail-on-regression: "true"
```

**參考**：
- https://github.com/MPrazeres-1983/promptforge （PromptForge — prompt versioning + regression testing in CI/CD）
- https://github.com/PromptCheck/promptcheck （PromptCheck — CI-first test harness for LLM prompts）
- https://pypi.org/project/promptci/ （promptci — prompt versioning with regression gates）
- https://github.com/cb7chaitanya/prompttest （prompttest — catch prompt regressions before production）

---

## 優先順序建議

| 優先級 | 建議 | 成本 | 預期 ROI |
|--------|------|------|----------|
| 高 | #5 Phase 1 — schema contract tests | 零（純 pytest） | 防止 prompt 意外 break |
| 高 | #1 — Preprocessing Hints | 低（改 prompt 文字） | OCR 準確率提升 |
| 中 | #2 — Verify reading prompt | 低（新增一個函數） | reread 精準度提升 |
| 中 | #4 — 3 級 confidence | 中（schema 擴充） | 智慧 reread 觸發 |
| 低 | #3 — Structured Outputs 遷移 | 中（API 呼叫重構） | 消除 parse 失敗 |
