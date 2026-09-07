"""Bug/anomaly detector — monitors console errors, freezes, blank screens, performance.

All detection thresholds are read from Config (config/default.yaml + game_info.yaml).
"""

from dataclasses import dataclass, field
from typing import Optional, Union
from datetime import datetime

import numpy as np


@dataclass
class Anomaly:
    """Represents a detected anomaly."""
    type: str  # "console_error" | "freeze" | "blank_screen" | "performance" | "crash"
    severity: str  # "low" | "medium" | "high" | "critical"
    description: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    evidence: dict = field(default_factory=dict)


class BugDetector:
    """Monitors browser state for anomalies.

    Args:
        config: Optional Config instance. If provided, thresholds are read from it.
            If None, hardcoded defaults are used (matching config/default.yaml).
    """

    def __init__(self, config=None):
        self.anomalies: list[Anomaly] = []
        self._prev_frame_array: Optional[np.ndarray] = None
        self._frozen_count: int = 0
        self._prev_heap_size: Optional[int] = None
        self._heap_growth_count: int = 0
        self._check_count: int = 0

        # Load thresholds from config
        if config:
            det = config.get_section("detection") if hasattr(config, 'get_section') else {}
        else:
            det = {}

        freeze_cfg = det.get("freeze", {})
        self._freeze_ssim_threshold = freeze_cfg.get("ssim_threshold", 0.995)
        self._freeze_consecutive = freeze_cfg.get("consecutive_checks", 3)

        blank_cfg = det.get("blank_screen", {})
        self._blank_white_threshold = blank_cfg.get("white_threshold", 240)
        self._blank_black_threshold = blank_cfg.get("black_threshold", 15)

        perf_cfg = det.get("performance", {})
        self._heap_growth_mb = perf_cfg.get("heap_growth_mb", 50)
        self._heap_consecutive = perf_cfg.get("consecutive_growth", 3)
        self._warmup_checks = perf_cfg.get("warmup_checks", 5)

        console_cfg = det.get("console_errors", {})
        self._critical_patterns = console_cfg.get("critical_patterns", ["crash", "fatal", "CONTEXT_LOST"])
        self._high_patterns = console_cfg.get("high_patterns", ["error", "exception", "failed"])
        self._ignore_patterns = console_cfg.get("ignore_patterns", ["DevTools", "favicon.ico", "404"])

    def check_console_errors(self, logs: list[dict]) -> list[Anomaly]:
        """Check console logs for errors and warnings."""
        found = []
        for log in logs:
            if log.get("type") != "error":
                continue

            text = log.get("text", "") or log.get("message", "")

            # Skip ignored patterns
            if any(pat.lower() in text.lower() for pat in self._ignore_patterns):
                continue

            # Determine severity
            text_lower = text.lower()
            if any(pat.lower() in text_lower for pat in self._critical_patterns):
                severity = "critical"
            elif any(pat.lower() in text_lower for pat in self._high_patterns):
                severity = "high"
            else:
                severity = "medium"

            anomaly = Anomaly(
                type="console_error",
                severity=severity,
                description=text[:500],
                evidence={"full_text": text},
            )
            found.append(anomaly)
            self.anomalies.append(anomaly)
        return found

    def check_freeze(self, current_array: np.ndarray) -> Optional[Anomaly]:
        """Check if the screen appears frozen."""
        from .perceiver import is_frozen

        if self._prev_frame_array is not None:
            if is_frozen(self._prev_frame_array, current_array, threshold=self._freeze_ssim_threshold):
                self._frozen_count += 1
                if self._frozen_count >= self._freeze_consecutive:
                    anomaly = Anomaly(
                        type="freeze",
                        severity="high",
                        description=f"Screen appears frozen for {self._frozen_count} consecutive checks",
                        evidence={"frozen_frames": self._frozen_count},
                    )
                    self.anomalies.append(anomaly)
                    return anomaly
            else:
                self._frozen_count = 0

        self._prev_frame_array = current_array
        return None

    def check_blank_screen(self, current_array: np.ndarray) -> Optional[Anomaly]:
        """Check if the screen is blank (white or black)."""
        from .perceiver import is_blank_screen

        blank_type = is_blank_screen(
            current_array,
            white_threshold=self._blank_white_threshold,
            black_threshold=self._blank_black_threshold,
        )
        if blank_type:
            anomaly = Anomaly(
                type="blank_screen",
                severity="high",
                description=f"Screen is completely {blank_type}",
                evidence={"blank_type": blank_type},
            )
            self.anomalies.append(anomaly)
            return anomaly
        return None

    def check_performance(self, metrics: dict) -> Optional[Anomaly]:
        """Check memory growth using the driver's neutral metrics schema.

        Reads ``memory.used_mb``; None means the platform cannot measure it,
        which is skipped rather than treated as zero.
        """
        self._check_count += 1

        memory = metrics.get("memory") or {}
        used_mb = memory.get("used_mb")

        # Skip warmup period
        if self._check_count <= self._warmup_checks:
            if used_mb is not None:
                self._prev_heap_size = used_mb
            return None

        if used_mb is not None and self._prev_heap_size is not None:
            growth = used_mb - self._prev_heap_size
            if growth > self._heap_growth_mb:
                self._heap_growth_count += 1
                if self._heap_growth_count >= self._heap_consecutive:
                    anomaly = Anomaly(
                        type="performance",
                        severity="medium",
                        description=f"Possible memory leak: memory grew by {growth:.1f}MB",
                        evidence={"used_mb": used_mb, "growth_mb": round(growth, 2)},
                    )
                    self.anomalies.append(anomaly)
                    return anomaly
            else:
                self._heap_growth_count = 0

        if used_mb is not None:
            self._prev_heap_size = used_mb
        return None

    def run_all_checks(self, frame_array: np.ndarray, console_logs: list[dict],
                       performance_metrics: dict) -> list[Anomaly]:
        """Run all anomaly checks. Returns list of new anomalies found."""
        found = []
        found.extend(self.check_console_errors(console_logs))

        freeze = self.check_freeze(frame_array)
        if freeze:
            found.append(freeze)

        blank = self.check_blank_screen(frame_array)
        if blank:
            found.append(blank)

        perf = self.check_performance(performance_metrics)
        if perf:
            found.append(perf)

        return found

    def get_summary(self) -> dict:
        """Get anomaly summary."""
        by_type = {}
        for a in self.anomalies:
            by_type.setdefault(a.type, []).append(a)
        return {
            "total": len(self.anomalies),
            "by_type": {k: len(v) for k, v in by_type.items()},
            "critical": [a for a in self.anomalies if a.severity == "critical"],
            "high": [a for a in self.anomalies if a.severity == "high"],
        }
