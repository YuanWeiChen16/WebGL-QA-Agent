"""Tests for the pure parsers in webgl_qa.adb_device — no device required."""

import pytest
from webgl_qa.adb_device import AdbDevice


def _latency_text(intervals_ms, refresh_ns=4166666, start_ns=403_309_941_830):
    """Build `dumpsys SurfaceFlinger --latency` output from frame intervals."""
    lines = ["Total number of currently running services:0", str(refresh_ns)]
    t = start_ns
    for dt in intervals_ms:
        t += int(dt * 1_000_000)
        lines.append(f"{t - 2_500_000}\t{t}\t{t - 2_500_000}")
    return "\n".join(lines) + "\n"


class TestSurfaceFlingerLatency:
    def test_steady_60fps(self):
        text = _latency_text([16.67] * 60)
        stats = AdbDevice.parse_surfaceflinger_latency(text)
        assert stats["source"] == "surfaceflinger"
        assert stats["sample_frames"] == 59
        assert 59.0 <= stats["fps_avg"] <= 60.5
        assert stats["janky_percent"] == 0.0
        assert stats["p50_ms"] == pytest.approx(16.67, abs=0.01)

    def test_jank_measured_against_observed_median_not_refresh_rate(self):
        # A 240Hz virtual refresh (emulator) must not turn a healthy 60fps game
        # into 100% jank; only the real outlier counts.
        text = _latency_text([16.67] * 40 + [50.0] + [16.67] * 19, refresh_ns=4166666)
        stats = AdbDevice.parse_surfaceflinger_latency(text)
        assert stats["janky_percent"] == pytest.approx(100 / 59, abs=0.2)
        assert stats["p99_ms"] >= 49.0

    def test_pending_sentinel_rows_ignored(self):
        text = _latency_text([16.67] * 10)
        pending = (1 << 63) - 1
        text += f"{pending}\t{pending}\t{pending}\n0\t0\t0\n"
        stats = AdbDevice.parse_surfaceflinger_latency(text)
        assert stats["sample_frames"] == 9

    def test_too_few_frames_returns_none(self):
        assert AdbDevice.parse_surfaceflinger_latency(_latency_text([16.67] * 2)) is None
        assert AdbDevice.parse_surfaceflinger_latency("garbage\n") is None


class TestGfxinfo:
    def test_surfaceview_app_is_reported_inactive_not_janky(self):
        gfx = ("** Graphics info for pid 4696 [com.x] **\n"
               "Total frames rendered: 3\nJanky frames: 3 (100.00%)\n"
               "50th percentile: 15ms\n90th percentile: 350ms\n99th percentile: 350ms\n")
        stats = AdbDevice.parse_gfxinfo(gfx)
        assert stats == {"source": "gfxinfo_inactive", "sample_frames": 3}
        assert "janky_percent" not in stats

    def test_hwui_app_percentiles_parsed(self):
        gfx = ("Total frames rendered: 1200\nJanky frames: 60 (5.00%)\n"
               "50th percentile: 8ms\n90th percentile: 14ms\n95th percentile: 17ms\n"
               "99th percentile: 24ms\n")
        stats = AdbDevice.parse_gfxinfo(gfx)
        assert stats["source"] == "gfxinfo"
        assert stats["sample_frames"] == 1200
        assert stats["janky_percent"] == 5.0
        assert (stats["p50_ms"], stats["p90_ms"], stats["p99_ms"]) == (8, 14, 24)

    def test_missing_totals_returns_none(self):
        assert AdbDevice.parse_gfxinfo("No process found\n") is None


class TestMeminfo:
    def test_total_pss_kb_to_mb(self):
        meminfo = ("        TOTAL   483314   343620   123252        0    69146\n"
                   " App Summary\n               TOTAL:   483314       TOTAL SWAP PSS:        0\n")
        assert AdbDevice.parse_meminfo_pss_mb(meminfo) == pytest.approx(471.99, abs=0.01)

    def test_no_total_returns_none(self):
        assert AdbDevice.parse_meminfo_pss_mb("nothing here") is None
