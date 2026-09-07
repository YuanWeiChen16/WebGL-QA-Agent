"""Android driver over adb — native apps, emulators (BlueStacks/AVD), real devices.

Targets a device the way the browser driver targets a page: capture frames,
deliver touch input, report the action space. The perception, oracle,
knowledge and reporting layers above are reused unchanged.

Coordinates need no scaling here. ``screencap`` returns the framebuffer at
the device's real resolution and ``input tap`` addresses that same pixel
grid, so the DPR mismatch that complicates browser targets does not arise —
knowledge-base coordinates read off a screenshot are directly tappable.

What is NOT available compared to the browser driver: no console logs, no
page errors, no JS heap, no network capture, no DOM. Memory and frame timing
come from ``dumpsys`` instead, which is why this driver still advertises
CAP_PERFORMANCE.
"""

import asyncio
import base64
import math
import re
import shutil
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from .driver import CAP_KEYBOARD, CAP_PERFORMANCE, Driver, empty_metrics


class AdbCommandError(RuntimeError):
    """An adb invocation failed or returned an error string."""


class AdbDevice(Driver):
    """Drives an Android target through adb.

    Args:
        serial: Device serial. A ``host:port`` value (e.g. ``127.0.0.1:5555``
            for BlueStacks) is connected automatically on launch. None uses
            adb's single-device default.
        package: App under test. Used to launch the app and to scope the
            ``dumpsys`` performance queries.
        adb_path: Path to the adb binary. Resolved from PATH when omitted.
    """

    name = "adb"
    # No console/page errors on a native app; memory and frame timing come
    # from dumpsys. Scroll is absent by design — a swipe is drag().
    capabilities = frozenset({CAP_PERFORMANCE, CAP_KEYBOARD})

    def __init__(self, serial: Optional[str] = None, package: Optional[str] = None,
                 adb_path: Optional[str] = None, timeout: float = 30.0):
        self.serial = serial
        self.package = package
        self.timeout = timeout
        self._adb = adb_path or shutil.which("adb")
        if not self._adb:
            raise AdbCommandError(
                "adb not found on PATH — pass adb_path=... "
                r"(Android SDK ships it in platform-tools\adb.exe)"
            )
        self._viewport: Optional[dict] = None

    # --- adb plumbing --------------------------------------------------

    def _args(self, *args: str) -> list[str]:
        base = [self._adb]
        if self.serial:
            base += ["-s", self.serial]
        return base + list(args)

    async def _run(self, *args: str) -> bytes:
        """Run an adb command, returning raw stdout."""
        proc = await asyncio.create_subprocess_exec(
            *self._args(*args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise AdbCommandError(f"adb {' '.join(args)} timed out after {self.timeout}s")
        if proc.returncode != 0:
            raise AdbCommandError(
                f"adb {' '.join(args)} failed ({proc.returncode}): "
                f"{err.decode(errors='replace').strip()}"
            )
        return out

    async def _shell(self, command: str) -> str:
        """Run a shell command, returning decoded stdout.

        adb reports some failures on stdout with a zero exit code, so the
        common ``error:`` prefix is turned into an exception here. Emulators
        with ADB access disabled answer most shell commands with
        ``error: closed`` — that surfaces as a clear error rather than a
        silently empty result.
        """
        try:
            out = (await self._run("shell", command)).decode("utf-8", errors="replace")
        except AdbCommandError as e:
            raise AdbCommandError(self._explain(command, str(e))) from None
        stripped = out.strip()
        if stripped.startswith("error:"):
            raise AdbCommandError(self._explain(command, stripped))
        return out

    @staticmethod
    def _explain(command: str, message: str) -> str:
        """Attach the usual cause when adb refuses a shell command."""
        hint = ""
        if "closed" in message:
            hint = (
                " — the device accepted the connection but refused the shell. "
                "This is what a disabled ADB toggle looks like: screencap and "
                "getprop keep working while input/wm/pm are cut off. On "
                "BlueStacks, enable Settings -> Advanced -> Android Debug Bridge."
            )
        return f"adb shell {command!r}: {message}{hint}"

    # --- lifecycle -----------------------------------------------------

    async def launch(self, target: str) -> None:
        """Connect to the device and bring the app under test to the front.

        Args:
            target: ``package``, ``package/activity``, or either prefixed with
                ``adb://`` so a GameSession can carry it in its ``game_url``.
                A bare ``adb://`` (or empty string) attaches to whatever is
                already on screen — the usual case when a tester already has
                the app open, and the only mode that works on a device whose
                ADB shell is restricted.
        """
        target = target.removeprefix("adb://").strip("/")

        if self.serial and ":" in self.serial:
            # Networked device (emulator, wireless debugging) — idempotent.
            # adb reports a refused connection on stdout with exit code 0, and
            # a later `wait-for-device` on a serial that never appeared just
            # blocks until the timeout, so check the message here instead.
            reply = (await self._run("connect", self.serial)).decode(
                "utf-8", errors="replace").strip()
            if "cannot connect" in reply.lower() or "failed" in reply.lower():
                raise AdbCommandError(
                    f"cannot reach {self.serial}: {reply} — the emulator or device is "
                    f"not running, or its ADB port differs. Start it and confirm with "
                    f"`adb devices`."
                )

        await self._run("wait-for-device")

        if target:
            self.package = target.split("/")[0]
            if "/" in target:
                await self._shell(f"am start -n {target}")
            else:
                await self._shell(
                    f"monkey -p {target} -c android.intent.category.LAUNCHER 1"
                )
            await asyncio.sleep(2)  # let the activity settle before first capture

        # Cache the action space now so every later call is cheap.
        self._viewport = await self._read_screen_size()

    async def close(self) -> None:
        """Forget cached device state. The device/emulator keeps running.

        This driver attaches to something the user started, so it neither
        stops the target nor tears down the adb transport: disconnecting a
        networked serial here would break the next run (and any other tool
        sharing the adb server) for no benefit — ``connect`` is idempotent.
        """
        self._viewport = None

    # --- perception ----------------------------------------------------

    async def screenshot(self, path: Optional[str] = None) -> str:
        """Capture the framebuffer via ``screencap -p``.

        ``exec-out`` is used rather than ``shell`` so the PNG bytes arrive
        without line-ending translation.
        """
        raw = await self._run("exec-out", "screencap", "-p")
        if not raw.startswith(b"\x89PNG"):
            raise AdbCommandError(
                f"screencap did not return a PNG (got {len(raw)} bytes starting "
                f"{raw[:16]!r}) — check that ADB access is enabled on the device"
            )
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(raw)
        return base64.b64encode(raw).decode("utf-8")

    async def _read_screen_size(self) -> dict:
        """Screen bounds, measured from a real capture.

        ``wm size`` would be the obvious source but it is one of the commands
        emulators commonly refuse, and it reports the logical size rather than
        the framebuffer. Measuring the screenshot guarantees the action space
        matches the pixels the perception layer sees.
        """
        b64 = await self.screenshot()
        with Image.open(BytesIO(base64.b64decode(b64))) as im:
            width, height = im.size
        return {"x": 0, "y": 0, "width": width, "height": height}

    async def get_viewport_size(self) -> dict:
        if self._viewport is None:
            self._viewport = await self._read_screen_size()
        return dict(self._viewport)

    # --- actions -------------------------------------------------------

    async def click(self, x: int, y: int) -> None:
        await self._shell(f"input tap {int(x)} {int(y)}")

    async def double_click(self, x: int, y: int) -> None:
        await self._shell(f"input tap {int(x)} {int(y)}")
        await asyncio.sleep(0.08)  # inside Android's double-tap window
        await self._shell(f"input tap {int(x)} {int(y)}")

    async def drag(self, from_x: int, from_y: int, to_x: int, to_y: int) -> None:
        """Swipe. The 300ms duration reads as a drag rather than a fling."""
        await self._shell(
            f"input swipe {int(from_x)} {int(from_y)} {int(to_x)} {int(to_y)} 300"
        )

    async def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        """Press and hold — a zero-distance swipe."""
        await self._shell(f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}")

    async def key_press(self, key: str) -> None:
        """Send a keyevent. Accepts ``BACK`` or ``KEYCODE_BACK``."""
        keycode = key if key.upper().startswith("KEYCODE_") else f"KEYCODE_{key.upper()}"
        await self._shell(f"input keyevent {keycode}")

    async def type_text(self, text: str) -> None:
        """Type a string. ``input text`` reads spaces as %s and has no quoting."""
        await self._shell(f"input text {text.replace(' ', '%s')}")

    # --- instrumentation -----------------------------------------------

    _PSS_RE = re.compile(r"TOTAL(?:\s+PSS)?:?\s+(\d+)")
    _GFX_TOTAL_RE = re.compile(r"Total frames rendered:\s*(\d+)")
    _JANK_RE = re.compile(r"Janky frames:\s*\d+\s*\(([\d.]+)%\)")
    _PCT_RE = re.compile(r"(\d+)th percentile:\s*(\d+)ms")

    # SurfaceFlinger marks a not-yet-presented frame with INT64_MAX.
    _SF_PENDING = (1 << 63) - 1

    async def get_performance_metrics(self) -> dict:
        """Memory and frame timing from dumpsys, in the neutral schema.

        Scoped to ``package``; without one there is nothing to measure and
        everything stays None.

        Frame timing has two possible sources and they are not
        interchangeable. ``gfxinfo`` measures Android's HWUI (view hierarchy)
        pipeline, which a game rendering into its own SurfaceView bypasses
        entirely — there it reports a handful of stray frames and a nonsense
        100% jank figure that never changes. SurfaceFlinger's per-surface
        present timestamps are the real signal for those apps, so they are
        tried first and ``gfxinfo`` is only trusted when HWUI is actually
        drawing.
        """
        metrics = empty_metrics()
        if not self.package:
            return metrics

        try:
            meminfo = await self._shell(f"dumpsys meminfo {self.package}")
            metrics["memory"]["used_mb"] = self.parse_meminfo_pss_mb(meminfo)
        except AdbCommandError:
            pass  # instrumentation is best-effort; never fail an observation

        frames = await self._surface_frame_stats()
        if frames is None:
            frames = await self._hwui_frame_stats()
        if frames:
            metrics["frames"].update(frames)

        return metrics

    async def _find_surface_layer(self) -> Optional[str]:
        """Locate the package's rendering layer in SurfaceFlinger.

        A SurfaceView layer is preferred — that is where a game engine draws.
        """
        try:
            listing = await self._shell("dumpsys SurfaceFlinger --list")
        except AdbCommandError:
            return None

        candidates = [
            line.strip() for line in listing.splitlines()
            if self.package in line and "'" not in line
        ]
        if not candidates:
            return None
        for line in candidates:
            if line.startswith("SurfaceView"):
                return line
        return candidates[-1]

    async def _surface_frame_stats(self) -> Optional[dict]:
        """Real frame intervals from SurfaceFlinger present timestamps.

        Returns None when the surface cannot be read, so the caller can fall
        back. Jank is measured against the *observed median* interval rather
        than the display's refresh period: emulators report a virtual refresh
        (240Hz here) unrelated to what the app targets, which would mark every
        frame of a healthy 60fps game as janky.
        """
        layer = await self._find_surface_layer()
        if not layer:
            return None

        try:
            out = await self._shell(f"dumpsys SurfaceFlinger --latency '{layer}'")
        except AdbCommandError:
            return None
        return self.parse_surfaceflinger_latency(out)

    @classmethod
    def parse_surfaceflinger_latency(cls, out: str) -> Optional[dict]:
        """Turn `dumpsys SurfaceFlinger --latency` output into frame stats.

        Pure function so it can be unit-tested without a device. The first line
        is the display refresh period; every following line is
        ``desiredPresent actualPresent frameReady`` in nanoseconds, with
        INT64_MAX marking frames not yet presented.
        """
        stamps: list[int] = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) != 3:
                continue
            try:
                actual = int(parts[1])
            except ValueError:
                continue
            if actual <= 0 or actual >= cls._SF_PENDING:
                continue
            stamps.append(actual)

        if len(stamps) < 4:
            return None

        stamps.sort()
        intervals = [
            (b - a) / 1_000_000.0                       # ns -> ms
            for a, b in zip(stamps, stamps[1:])
            if 0 < (b - a) < 1_000_000_000              # drop gaps over 1s
        ]
        if len(intervals) < 3:
            return None

        ordered = sorted(intervals)

        def pct(p: float) -> float:
            # Nearest-rank percentile (ceil(p*N), 1-based): with 60 samples the
            # p99 is the worst frame, so a single 50ms stall is not averaged away.
            idx = min(len(ordered) - 1, max(0, math.ceil(p * len(ordered)) - 1))
            return round(ordered[idx], 2)

        median = ordered[len(ordered) // 2]
        janky = sum(1 for v in intervals if v > median * 1.5)
        mean = sum(intervals) / len(intervals)

        return {
            "source": "surfaceflinger",
            "sample_frames": len(intervals),
            "fps_avg": round(1000.0 / mean, 1) if mean > 0 else None,
            "janky_percent": round(100.0 * janky / len(intervals), 1),
            "p50_ms": pct(0.50),
            "p90_ms": pct(0.90),
            "p99_ms": pct(0.99),
        }

    async def _hwui_frame_stats(self) -> Optional[dict]:
        """gfxinfo stats, but only when the HWUI pipeline is actually drawing.

        The counters are cumulative since process start and there is no
        resettable window on many builds, so a near-zero frame count means
        the app does not render through HWUI — reporting its percentiles then
        would be worse than reporting nothing.
        """
        try:
            gfx = await self._shell(f"dumpsys gfxinfo {self.package}")
        except AdbCommandError:
            return None
        return self.parse_gfxinfo(gfx)

    @classmethod
    def parse_gfxinfo(cls, gfx: str) -> Optional[dict]:
        """Parse `dumpsys gfxinfo <pkg>`; pure function for unit tests."""
        total_match = cls._GFX_TOTAL_RE.search(gfx)
        if not total_match:
            return None
        total = int(total_match.group(1))

        # A real HWUI app accumulates thousands of frames within seconds; a
        # SurfaceView game shows single digits for its whole lifetime.
        if total < 100:
            return {"source": "gfxinfo_inactive", "sample_frames": total}

        stats: dict = {"source": "gfxinfo", "sample_frames": total}
        jank = cls._JANK_RE.search(gfx)
        if jank:
            stats["janky_percent"] = float(jank.group(1))
        for pct_label, ms in cls._PCT_RE.findall(gfx):
            key = f"p{pct_label}_ms"
            if key in ("p50_ms", "p90_ms", "p99_ms"):
                stats[key] = int(ms)
        return stats

    @classmethod
    def parse_meminfo_pss_mb(cls, meminfo: str) -> Optional[float]:
        """Total PSS in MB from `dumpsys meminfo <pkg>` (dumpsys reports KB)."""
        m = cls._PSS_RE.search(meminfo)
        return round(int(m.group(1)) / 1024, 2) if m else None
