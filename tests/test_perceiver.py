"""Tests for webgl_qa.perceiver — pixel diff, SSIM, blank/freeze detection."""

import numpy as np
import pytest
from webgl_qa.perceiver import (
    pixel_diff_ratio, is_frozen, is_blank_screen,
    get_dominant_color, compute_ssim, decode_to_array,
)


def _make_rgb(r, g, b, shape=(100, 100)):
    """Create a solid-color RGB array."""
    arr = np.zeros((*shape, 3), dtype=np.uint8)
    arr[:, :, 0] = r
    arr[:, :, 1] = g
    arr[:, :, 2] = b
    return arr


class TestPixelDiffRatio:
    """Test pixel_diff_ratio with numpy arrays."""

    def test_identical_frames(self):
        frame = _make_rgb(128, 64, 200)
        assert pixel_diff_ratio(frame, frame.copy()) == 0.0

    def test_completely_different_frames(self):
        frame1 = _make_rgb(0, 0, 0)
        frame2 = _make_rgb(255, 255, 255)
        ratio = pixel_diff_ratio(frame1, frame2)
        assert ratio == 1.0

    def test_partial_change(self):
        frame1 = _make_rgb(100, 100, 100)
        frame2 = frame1.copy()
        # Change top half
        frame2[:50, :, :] = 200
        ratio = pixel_diff_ratio(frame1, frame2)
        assert 0.4 < ratio < 0.6  # ~50%

    def test_below_threshold_ignored(self):
        frame1 = _make_rgb(100, 100, 100)
        frame2 = frame1.copy()
        # Change by less than default threshold (10)
        frame2[:, :, 0] = 105
        ratio = pixel_diff_ratio(frame1, frame2, threshold=10)
        assert ratio == 0.0

    def test_different_sizes_resized(self):
        frame1 = _make_rgb(50, 50, 50, shape=(100, 100))
        frame2 = _make_rgb(50, 50, 50, shape=(200, 200))
        ratio = pixel_diff_ratio(frame1, frame2)
        assert ratio == 0.0


class TestIsFrozen:
    """Test freeze detection via SSIM."""

    def test_identical_is_frozen(self):
        frame = _make_rgb(100, 150, 200)
        assert is_frozen(frame, frame.copy()) is True

    def test_different_is_not_frozen(self):
        frame1 = _make_rgb(0, 0, 0)
        frame2 = _make_rgb(255, 255, 255)
        assert is_frozen(frame1, frame2) is False

    def test_none_input_returns_false(self):
        frame = _make_rgb(100, 100, 100)
        assert is_frozen(None, frame) is False
        assert is_frozen(frame, None) is False


class TestIsBlankScreen:
    """Test blank screen detection."""

    def test_white_screen(self):
        frame = _make_rgb(250, 250, 250)
        assert is_blank_screen(frame) == "white"

    def test_black_screen(self):
        frame = _make_rgb(5, 5, 5)
        assert is_blank_screen(frame) == "black"

    def test_normal_screen(self):
        frame = _make_rgb(100, 150, 80)
        assert is_blank_screen(frame) is None

    def test_almost_white_not_blank(self):
        frame = _make_rgb(230, 230, 230)
        assert is_blank_screen(frame) is None


class TestGetDominantColor:
    """Test dominant color extraction."""

    def test_solid_red(self):
        frame = _make_rgb(255, 0, 0)
        r, g, b = get_dominant_color(frame)
        assert r == 255
        assert g == 0
        assert b == 0

    def test_solid_blue(self):
        frame = _make_rgb(0, 0, 200)
        r, g, b = get_dominant_color(frame)
        assert r == 0
        assert g == 0
        assert b == 200


class TestComputeSSIM:
    """Test SSIM computation."""

    def test_identical_images_ssim_1(self):
        frame = _make_rgb(128, 128, 128)
        ssim = compute_ssim(frame, frame.copy())
        assert ssim > 0.99

    def test_different_images_low_ssim(self):
        frame1 = _make_rgb(0, 0, 0)
        frame2 = _make_rgb(255, 255, 255)
        ssim = compute_ssim(frame1, frame2)
        assert ssim < 0.1

    def test_ssim_is_symmetric(self):
        frame1 = _make_rgb(50, 100, 150)
        frame2 = _make_rgb(200, 50, 75)
        assert abs(compute_ssim(frame1, frame2) - compute_ssim(frame2, frame1)) < 0.001
