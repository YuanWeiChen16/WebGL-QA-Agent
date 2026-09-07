"""Browser control layer using Playwright for WebGL game interaction."""

import asyncio
import base64
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from .driver import (
    CAP_CONSOLE, CAP_KEYBOARD, CAP_PERFORMANCE, CAP_SCROLL, Driver, empty_metrics,
)


class GameBrowser(Driver):
    """Controls a Chromium browser instance for WebGL game interaction."""

    name = "browser"
    capabilities = frozenset({CAP_CONSOLE, CAP_PERFORMANCE, CAP_SCROLL, CAP_KEYBOARD})

    def __init__(self, headless: bool = True, viewport_width: int = 1280, viewport_height: int = 720):
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._console_logs: list[dict] = []
        self._errors: list[dict] = []

    async def launch(self, url: str) -> None:
        """Launch browser and navigate to the game URL."""
        await self.launch_browser()
        await self.navigate(url)

    async def launch_browser(self) -> None:
        """Launch the browser and open a blank page, without navigating.

        Split out from launch() so callers that need CDP domains active during
        page load (e.g. network capture) can attach before navigation happens.
        """
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--enable-webgl",
                "--enable-gpu",
                "--no-sandbox",
                "--disable-web-security",
                "--disable-gpu-sandbox",
                "--ignore-gpu-blocklist",
                "--use-gl=angle",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-first-run",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            device_scale_factor=1,
        )
        self._page = await self._context.new_page()

        # Intercept console messages
        self._page.on("console", self._on_console)
        self._page.on("pageerror", self._on_error)

    async def navigate(self, url: str) -> None:
        """Navigate to a URL and wait for the WebGL canvas to come up."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.goto(url, wait_until="commit", timeout=60000)
        # WebGL games stream assets; wait for canvas to appear then extra time for rendering
        try:
            await self._page.wait_for_selector("canvas", timeout=30000)
        except Exception:
            pass  # Canvas may already exist or game uses different rendering
        await asyncio.sleep(5)  # Let WebGL initialize

    def _on_console(self, msg) -> None:
        """Capture console messages."""
        self._console_logs.append({
            "type": msg.type,
            "text": msg.text,
            "timestamp": time.monotonic(),
        })

    def _on_error(self, error) -> None:
        """Capture page errors."""
        self._errors.append({
            "message": str(error),
            "timestamp": time.monotonic(),
        })

    async def screenshot(self, path: Optional[str] = None) -> str:
        """Take a screenshot. Returns base64 encoded PNG."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        raw = None
        # Attempt 1: normal page screenshot (may hang on WebGL fonts)
        for attempt in range(2):
            try:
                raw = await self._page.screenshot(
                    type="png", full_page=False,
                    timeout=15000,
                    animations="disabled",
                )
                break
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(2)
        # Attempt 2: fallback via CDP Page.captureScreenshot (bypasses font wait)
        if raw is None:
            try:
                cdp = await self._page.context.new_cdp_session(self._page)
                result = await cdp.send("Page.captureScreenshot", {"format": "png"})
                await cdp.detach()
                raw = base64.b64decode(result["data"])
            except Exception:
                pass
        # Attempt 3: canvas-only screenshot
        if raw is None:
            try:
                canvas = self._page.locator("canvas").first
                raw = await canvas.screenshot(type="png", timeout=10000)
            except Exception as e:
                raise RuntimeError(f"All screenshot methods failed: {e}")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(raw)
        return base64.b64encode(raw).decode("utf-8")

    async def click(self, x: int, y: int) -> None:
        """Click at specific coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.click(x, y)

    async def double_click(self, x: int, y: int) -> None:
        """Double click at specific coordinates."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.dblclick(x, y)

    async def drag(self, from_x: int, from_y: int, to_x: int, to_y: int) -> None:
        """Drag from one point to another."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.move(from_x, from_y)
        await self._page.mouse.down()
        await self._page.mouse.move(to_x, to_y, steps=10)
        await self._page.mouse.up()

    async def scroll(self, x: int, y: int, delta_y: int) -> None:
        """Scroll via the mouse wheel at a coordinate."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.mouse.move(x, y)
        await self._page.mouse.wheel(0, delta_y)

    async def key_press(self, key: str) -> None:
        """Press a keyboard key."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.keyboard.press(key)

    async def type_text(self, text: str) -> None:
        """Type text."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        await self._page.keyboard.type(text)

    async def wait(self, seconds: float) -> None:
        """Wait for specified seconds."""
        await asyncio.sleep(seconds)

    async def get_canvas_size(self) -> dict:
        """Get the WebGL canvas dimensions."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        result = await self._page.evaluate("""() => {
            const canvas = document.querySelector('canvas');
            if (!canvas) return null;
            const rect = canvas.getBoundingClientRect();
            return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
        }""")
        return result or {"x": 0, "y": 0, "width": self.viewport_width, "height": self.viewport_height}

    async def get_viewport_size(self) -> dict:
        """Bounds actions are addressed against — the canvas when one exists.

        WebGL games render into a canvas that may be inset in the page, so the
        canvas rect (not the viewport) is the meaningful action space.
        """
        return await self.get_canvas_size()

    async def get_performance_metrics(self) -> dict:
        """Browser counters, translated into the neutral driver schema."""
        if not self._page:
            raise RuntimeError("Browser not launched")
        raw = await self._page.evaluate("""() => {
            const perf = performance.getEntriesByType('navigation')[0] || {};
            let memory = null;
            if (performance.memory) {
                memory = {
                    used: performance.memory.usedJSHeapSize,
                    total: performance.memory.totalJSHeapSize,
                };
            }
            const load = perf.loadEventEnd ? perf.loadEventEnd - perf.startTime : null;
            return {memory, load_time_ms: load};
        }""")

        metrics = empty_metrics()
        mem = raw.get("memory")
        if mem:
            # performance.memory is Chromium-only; absent elsewhere, which the
            # neutral schema represents as None rather than 0.
            metrics["memory"]["used_mb"] = round(mem["used"] / (1024 * 1024), 2)
            metrics["memory"]["total_mb"] = round(mem["total"] / (1024 * 1024), 2)
        metrics["timing"]["load_time_ms"] = raw.get("load_time_ms")
        return metrics

    def get_console_logs(self, clear: bool = False) -> list[dict]:
        """Get captured console logs."""
        logs = list(self._console_logs)
        if clear:
            self._console_logs.clear()
        return logs

    def get_errors(self, clear: bool = False) -> list[dict]:
        """Get captured page errors."""
        errors = list(self._errors)
        if clear:
            self._errors.clear()
        return errors

    async def close(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
