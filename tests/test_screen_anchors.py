"""Tests for anchor-based screen identification — perceiver.match_region and
KnowledgeBase.identify_system — using synthetic frames and a temp knowledge dir."""

import numpy as np
import pytest
import yaml
from PIL import Image

from webgl_qa.perceiver import match_region
from webgl_qa.knowledge_base import KnowledgeBase

R1 = {"x": 20, "y": 20, "width": 64, "height": 32}
R2 = {"x": 120, "y": 140, "width": 48, "height": 48}


def _checker(h, w, cell=8):
    yy, xx = np.mgrid[0:h, 0:w]
    v = (((yy // cell) + (xx // cell)) % 2) * 255
    return np.stack([v, v, v], axis=-1).astype(np.uint8)


def _stripes(h, w, period=6):
    yy, xx = np.mgrid[0:h, 0:w]
    v = (((xx + yy) // period) % 2) * 255
    return np.stack([v, 255 - v, v // 2], axis=-1).astype(np.uint8)


def _noise(h, w, seed):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _paste(frame, region, patch):
    x, y, w, h = region["x"], region["y"], region["width"], region["height"]
    frame[y:y + h, x:x + w] = patch
    return frame


def _frame_a(seed=1):
    f = _noise(240, 240, seed)
    _paste(f, R1, _checker(R1["height"], R1["width"]))
    return f


def _frame_b(seed=2):
    f = _noise(240, 240, seed)
    _paste(f, R2, _stripes(R2["height"], R2["width"]))
    return f


class TestMatchRegion:
    def test_identical_region_scores_one(self):
        f = _frame_a()
        tmpl = f[R1["y"]:R1["y"] + R1["height"], R1["x"]:R1["x"] + R1["width"]]
        assert match_region(f, tmpl, R1) == pytest.approx(1.0, abs=1e-6)

    def test_unrelated_region_scores_low(self):
        tmpl = _checker(R1["height"], R1["width"])
        assert match_region(_frame_b(), tmpl, R1) < 0.3

    def test_out_of_bounds_region_is_zero(self):
        f = _frame_a()
        assert match_region(f, _checker(32, 64), {"x": 200, "y": 230, "width": 64, "height": 32}) == 0.0


@pytest.fixture
def kb_dir(tmp_path):
    (tmp_path / "systems").mkdir()
    (tmp_path / "anchors").mkdir()
    fa, fb = _frame_a(), _frame_b()
    Image.fromarray(fa[R1["y"]:R1["y"] + R1["height"], R1["x"]:R1["x"] + R1["width"]]).save(tmp_path / "anchors" / "a.png")
    Image.fromarray(fb[R2["y"]:R2["y"] + R2["height"], R2["x"]:R2["x"] + R2["width"]]).save(tmp_path / "anchors" / "b.png")
    (tmp_path / "systems" / "a.yaml").write_text(yaml.safe_dump({
        "system_id": "a", "name": "A",
        "detection": {"anchors": [{"element": "e", "image": "anchors/a.png", "region": R1, "min_ssim": 0.6}]},
    }), encoding="utf-8")
    (tmp_path / "systems" / "b.yaml").write_text(yaml.safe_dump({
        "system_id": "b", "name": "B",
        "detection": {"anchors": [{"element": "e", "image": "anchors/b.png", "region": R2, "min_ssim": 0.6}]},
    }), encoding="utf-8")
    (tmp_path / "systems" / "c.yaml").write_text(yaml.safe_dump({"system_id": "c", "name": "no anchors"}),
                                                  encoding="utf-8")
    return tmp_path


class TestIdentifySystem:
    def test_identifies_each_screen(self, kb_dir):
        kb = KnowledgeBase("synthetic", base_dir=kb_dir)
        ra, rb = kb.identify_system(_frame_a()), kb.identify_system(_frame_b())
        assert ra["system_id"] == "a" and ra["confidence"] == pytest.approx(1.0, abs=1e-3)
        assert rb["system_id"] == "b"
        assert "c" not in ra["scores"]  # systems without anchors are not scored

    def test_unknown_frame_returns_none_not_a_guess(self, kb_dir):
        kb = KnowledgeBase("synthetic", base_dir=kb_dir)
        r = kb.identify_system(_noise(240, 240, seed=99))
        assert r["system_id"] is None and r["best"] is None

    def test_same_screen_with_background_change_still_matches(self, kb_dir):
        # Animated backgrounds change everything except the anchor region.
        kb = KnowledgeBase("synthetic", base_dir=kb_dir)
        assert kb.identify_system(_frame_a(seed=7))["system_id"] == "a"

    def test_missing_anchor_image_disqualifies_system(self, kb_dir):
        (kb_dir / "anchors" / "b.png").unlink()
        kb = KnowledgeBase("synthetic", base_dir=kb_dir)
        assert kb.identify_system(_frame_b())["system_id"] is None

    def test_get_detection_anchors(self, kb_dir):
        kb = KnowledgeBase("synthetic", base_dir=kb_dir)
        assert kb.get_detection_anchors("a")[0]["image"] == "anchors/a.png"
        assert kb.get_detection_anchors("c") == []
        assert kb.get_detection_anchors("missing") == []
