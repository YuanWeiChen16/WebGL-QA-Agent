"""Platform-agnostic driver interface.

Everything above this layer — perceiver, detector, oracle, knowledge_base,
reporter — works on screenshots and coordinates alone, so it is reused
unchanged across platforms. Only this layer knows how a screen is captured
and how an input event is delivered.

A driver supplies the mandatory verbs (capture a frame, deliver an input,
report the viewport). Instrumentation that only some platforms can provide —
console logs, page errors, heap metrics — is declared through ``capabilities``
and defaults to returning nothing, so a driver never has to implement a
capability its platform lacks.

Implementations:
    browser.GameBrowser   Playwright + Chromium (WebGL games in a browser)
    adb_device.AdbDevice  adb (native Android apps / Android browsers)
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional


# Capability names a driver may advertise in ``Driver.capabilities``.
CAP_CONSOLE = "console"          # get_console_logs() / get_errors() return real data
CAP_PERFORMANCE = "performance"  # get_performance_metrics() returns real data
CAP_SCROLL = "scroll"            # scroll() is implemented
CAP_KEYBOARD = "keyboard"        # key_press() / type_text() are implemented


class Driver(ABC):
    """Drives one target under test: capture frames, deliver inputs."""

    #: Short identifier used in reports and run metadata.
    name: str = "driver"

    #: Optional instrumentation this driver actually provides. Callers should
    #: check membership rather than calling and inspecting an empty result —
    #: it keeps browser-only work out of the loop on other platforms.
    capabilities: frozenset = frozenset()

    # --- lifecycle -----------------------------------------------------

    @abstractmethod
    async def launch(self, target: str) -> None:
        """Open the target under test.

        Args:
            target: A URL for browser drivers, a package/activity for device
                drivers. Interpreted by the driver.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release everything the driver owns. Must be safe to call twice."""

    # --- perception ----------------------------------------------------

    @abstractmethod
    async def screenshot(self, path: Optional[str] = None) -> str:
        """Capture the current frame.

        Returns a base64-encoded PNG, and also writes it to ``path`` if given.
        """

    @abstractmethod
    async def get_viewport_size(self) -> dict:
        """Bounds of the area actions are addressed against.

        Returns ``{"x", "y", "width", "height"}``. Coordinates passed to the
        action verbs are in this space, and screenshots are expected to match
        it — a driver whose capture resolution differs from its input
        resolution must reconcile the two itself rather than leaking the
        scale factor to callers.
        """

    # --- actions -------------------------------------------------------

    @abstractmethod
    async def click(self, x: int, y: int) -> None:
        """Single tap/click at a viewport coordinate."""

    @abstractmethod
    async def drag(self, from_x: int, from_y: int, to_x: int, to_y: int) -> None:
        """Drag/swipe between two viewport coordinates."""

    async def double_click(self, x: int, y: int) -> None:
        """Two rapid clicks. Drivers with a native gesture should override."""
        await self.click(x, y)
        await self.click(x, y)

    async def scroll(self, x: int, y: int, delta_y: int) -> None:
        """Scroll at a coordinate. Requires CAP_SCROLL."""
        raise NotImplementedError(f"{self.name} driver does not support scroll")

    async def key_press(self, key: str) -> None:
        """Press a single key. Requires CAP_KEYBOARD."""
        raise NotImplementedError(f"{self.name} driver does not support key_press")

    async def type_text(self, text: str) -> None:
        """Type a string. Requires CAP_KEYBOARD."""
        raise NotImplementedError(f"{self.name} driver does not support type_text")

    async def wait(self, seconds: float) -> None:
        """Idle. Platform-independent, so implemented once here."""
        await asyncio.sleep(seconds)

    # --- optional instrumentation --------------------------------------
    # Defaults return empty so a driver only implements what its platform
    # can actually observe. Declare the matching capability when overriding.

    def get_console_logs(self, clear: bool = False) -> list[dict]:
        """Captured log records: ``{"type", "text", "timestamp"}``."""
        return []

    def get_errors(self, clear: bool = False) -> list[dict]:
        """Captured uncaught errors: ``{"message", "timestamp"}``."""
        return []

    async def get_performance_metrics(self) -> dict:
        """Runtime metrics in a platform-neutral shape.

        Drivers translate their native counters into the shape returned by
        :func:`empty_metrics`. The sources differ wildly per platform — the
        browser reads ``performance.memory`` over CDP, Android reads
        ``dumpsys meminfo`` / ``dumpsys gfxinfo`` — but a frame time is a
        frame time everywhere, so thresholds and regression analysis stay in
        the platform-neutral layer.

        Missing values are None rather than 0 — the detector must be able to
        tell "not measurable here" from "measured as zero".
        """
        return {}


def empty_metrics() -> dict:
    """The neutral metrics shape with everything unmeasured.

    Absolute values are only comparable against the same platform's own
    baseline; never compare a number here across platforms.
    """
    return {
        "memory": {"used_mb": None, "total_mb": None},
        "timing": {"load_time_ms": None},
        # ``source`` names where the frame numbers came from, because what
        # counts as a frame differs per platform and a reader has to know
        # which pipeline was measured before trusting the percentiles.
        "frames": {
            "source": None,
            "sample_frames": None,
            "fps_avg": None,
            "janky_percent": None,
            "p50_ms": None,
            "p90_ms": None,
            "p99_ms": None,
        },
    }
