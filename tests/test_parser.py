"""Tests for webgl_qa.parser — Vision response JSON parsing."""

import pytest
from webgl_qa.parser import parse_vision, _normalize, _fallback


class TestParseVisionDirect:
    """Strategy 1: Direct JSON parse."""

    def test_valid_json(self):
        raw = '{"screen_id": "gameplay", "description": "捕魚中", "elements": [], "anomalies": []}'
        result = parse_vision(raw)
        assert result["screen_id"] == "gameplay"
        assert result["description"] == "捕魚中"
        assert result["elements"] == []
        assert result["anomalies"] == []

    def test_valid_json_with_all_fields(self):
        raw = '''{
            "screen_id": "tutorial",
            "description": "教學畫面",
            "current_task": "執行動作10次",
            "task_progress": "3/10",
            "is_hall_switch": false,
            "is_lobby": false,
            "is_popup": false,
            "has_reward_button": true,
            "has_finger_indicator": true,
            "finger_location": {"x": 400, "y": 300},
            "elements": [{"id": "btn1", "label": "確認", "location": {"x": 640, "y": 400}}],
            "suggested_click": {"x": 640, "y": 400, "reason": "click confirm"},
            "anomalies": []
        }'''
        result = parse_vision(raw)
        assert result["screen_id"] == "tutorial"
        assert result["has_reward_button"] is True
        assert result["has_finger_indicator"] is True
        assert result["finger_location"] == {"x": 400, "y": 300}
        assert len(result["elements"]) == 1


class TestParseVisionMarkdown:
    """Strategy 2: Extract JSON from markdown code block."""

    def test_json_in_code_block(self):
        raw = '''Here's the analysis:

```json
{"screen_id": "login", "description": "登入畫面", "elements": [], "anomalies": []}
```
'''
        result = parse_vision(raw)
        assert result["screen_id"] == "login"

    def test_json_in_plain_code_block(self):
        raw = '''Analysis:

```
{"screen_id": "popup", "description": "彈窗", "elements": [], "anomalies": ["ui_overlap"]}
```
'''
        result = parse_vision(raw)
        assert result["screen_id"] == "popup"
        assert result["anomalies"] == ["ui_overlap"]


class TestParseVisionRegex:
    """Strategy 3: Find JSON object with regex."""

    def test_json_with_prefix_text(self):
        raw = 'Based on the screenshot, I can see: {"screen_id": "gameplay", "description": "遊戲中", "elements": [], "anomalies": []}'
        result = parse_vision(raw)
        assert result["screen_id"] == "gameplay"

    def test_json_with_surrounding_text(self):
        raw = '''The game shows a fishing scene.

{"screen_id": "fishing_game_active", "description": "活躍捕魚場景", "elements": [{"id": "fish1", "label": "金魚", "location": {"x": 500, "y": 300}}], "anomalies": []}

That's what I see.'''
        result = parse_vision(raw)
        assert result["screen_id"] == "fishing_game_active"
        assert len(result["elements"]) == 1


class TestParseVisionFixup:
    """Strategy 4: Fix common JSON issues (trailing commas)."""

    def test_trailing_comma(self):
        raw = '{"screen_id": "loading", "description": "載入中", "elements": [], "anomalies": [],}'
        result = parse_vision(raw)
        assert result["screen_id"] == "loading"


class TestParseVisionFallback:
    """Strategy 5: Fallback when nothing works."""

    def test_empty_input(self):
        result = parse_vision("")
        assert result["screen_id"] == "empty_response"
        assert "parse_error" in result["anomalies"]

    def test_none_input(self):
        result = parse_vision(None)
        assert result["screen_id"] == "empty_response"

    def test_unparseable_text(self):
        result = parse_vision("This is just plain text with no JSON at all.")
        assert result["screen_id"] == "parse_error"
        assert "parse_error" in result["anomalies"]


class TestNormalize:
    """Test _normalize fills in missing keys."""

    def test_missing_keys_filled(self):
        result = _normalize({"screen_id": "test"})
        assert result["description"] == ""
        assert result["current_task"] == ""
        assert result["elements"] == []
        assert result["anomalies"] == []
        assert result["is_hall_switch"] is False
        assert result["has_finger_indicator"] is False

    def test_invalid_elements_replaced(self):
        result = _normalize({"screen_id": "test", "elements": "not a list"})
        assert result["elements"] == []

    def test_invalid_anomalies_replaced(self):
        result = _normalize({"screen_id": "test", "anomalies": "string"})
        assert result["anomalies"] == []
