"""Network traffic analysis via CDP for WebGL resource loading inspection."""

import asyncio
import json
import time
from pathlib import Path
from typing import Optional

from playwright.async_api import Page


class NetworkAnalyzer:
    """Captures and analyzes network traffic using Chrome DevTools Protocol."""

    def __init__(self, page: Page):
        self._page = page
        self._cdp = None
        self._requests: dict[str, dict] = {}
        self._capturing: bool = False
        self._listeners_attached: bool = False

    async def start(self) -> None:
        """Create a CDP session attached to the page."""
        self._cdp = await self._page.context.new_cdp_session(self._page)

    async def start_capture(self) -> None:
        """Enable Network domain and attach event listeners."""
        if not self._cdp:
            raise RuntimeError("CDP session not started; call start() first")

        self._requests.clear()
        self._capturing = True

        # Only attach listeners once to prevent accumulation on repeated calls
        if not self._listeners_attached:
            self._cdp.on("Network.requestWillBeSent", self._on_request_will_be_sent)
            self._cdp.on("Network.responseReceived", self._on_response_received)
            self._cdp.on("Network.loadingFinished", self._on_loading_finished)
            self._cdp.on("Network.loadingFailed", self._on_loading_failed)
            self._listeners_attached = True

        await self._cdp.send("Network.enable")

    def _on_request_will_be_sent(self, params: dict) -> None:
        """Handle requestWillBeSent event."""
        request_id = params["requestId"]
        request = params["request"]
        self._requests[request_id] = {
            "url": request["url"],
            "method": request["method"],
            "status": None,
            "mime_type": None,
            "encoded_size": 0,
            "decoded_size": 0,
            "timing": {},
            "start_time": params.get("wallTime", time.time()),
            "end_time": None,
        }

    def _on_response_received(self, params: dict) -> None:
        """Handle responseReceived event."""
        request_id = params["requestId"]
        if request_id not in self._requests:
            return
        response = params["response"]
        self._requests[request_id]["status"] = response.get("status")
        self._requests[request_id]["mime_type"] = response.get("mimeType")
        timing = response.get("timing")
        if timing:
            self._requests[request_id]["timing"] = {
                "dns_start": timing.get("dnsStart", -1),
                "dns_end": timing.get("dnsEnd", -1),
                "connect_start": timing.get("connectStart", -1),
                "connect_end": timing.get("connectEnd", -1),
                "ssl_start": timing.get("sslStart", -1),
                "ssl_end": timing.get("sslEnd", -1),
                "send_start": timing.get("sendStart", -1),
                "send_end": timing.get("sendEnd", -1),
                "receive_headers_end": timing.get("receiveHeadersEnd", -1),
            }

    def _on_loading_finished(self, params: dict) -> None:
        """Handle loadingFinished event."""
        request_id = params["requestId"]
        if request_id not in self._requests:
            return
        self._requests[request_id]["encoded_size"] = params.get("encodedDataLength", 0)
        self._requests[request_id]["end_time"] = time.time()

    def _on_loading_failed(self, params: dict) -> None:
        """Handle loadingFailed event."""
        request_id = params["requestId"]
        if request_id not in self._requests:
            return
        self._requests[request_id]["status"] = -1
        self._requests[request_id]["end_time"] = time.time()

    async def stop_capture(self) -> list[dict]:
        """Disable Network domain and return all captured resources."""
        if not self._cdp:
            raise RuntimeError("CDP session not started")

        self._capturing = False
        await self._cdp.send("Network.disable")
        return list(self._requests.values())

    def get_resource_summary(self) -> dict:
        """Aggregate resources by type with count, total_size, and largest."""
        type_map: dict[str, list[dict]] = {}

        for entry in self._requests.values():
            resource_type = self._classify_resource(entry.get("mime_type"), entry.get("url", ""))
            type_map.setdefault(resource_type, []).append(entry)

        summary: dict[str, dict] = {}
        for resource_type, entries in type_map.items():
            sizes = [e.get("encoded_size", 0) for e in entries]
            summary[resource_type] = {
                "count": len(entries),
                "total_size": sum(sizes),
                "largest": max(sizes) if sizes else 0,
            }
        return summary

    def _classify_resource(self, mime_type: Optional[str], url: str) -> str:
        """Classify a resource into a type category."""
        mime = (mime_type or "").lower()
        url_lower = url.lower()

        if "javascript" in mime or url_lower.endswith((".js", ".mjs")):
            return "js"
        if "css" in mime or url_lower.endswith(".css"):
            return "css"
        if "wasm" in mime or url_lower.endswith(".wasm"):
            return "wasm"
        if mime.startswith("image/") or url_lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico")):
            return "image"
        if mime.startswith("audio/") or url_lower.endswith((".mp3", ".ogg", ".wav", ".m4a")):
            return "audio"
        if "font" in mime or url_lower.endswith((".woff", ".woff2", ".ttf", ".otf", ".eot")):
            return "font"
        if "html" in mime or url_lower.endswith((".html", ".htm")):
            return "html"
        return "other"

    async def get_js_css_coverage(self) -> dict:
        """Collect JS and CSS coverage using Profiler and CSS domains.

        Starts precise coverage, waits 2 seconds for execution, then stops
        and calculates used/unused bytes with per-file breakdown.
        """
        if not self._cdp:
            raise RuntimeError("CDP session not started")

        # Start JS coverage via Profiler
        await self._cdp.send("Profiler.enable")
        await self._cdp.send("Profiler.startPreciseCoverage", {
            "callCount": False,
            "detailed": True,
        })

        # Start CSS coverage — CSS domain refuses to enable unless DOM is enabled first
        await self._cdp.send("DOM.enable")
        await self._cdp.send("CSS.enable")
        await self._cdp.send("CSS.startRuleUsageTracking")

        # Let code execute
        await asyncio.sleep(2)

        # Collect JS coverage
        js_result = await self._cdp.send("Profiler.takePreciseCoverage")
        await self._cdp.send("Profiler.stopPreciseCoverage")
        await self._cdp.send("Profiler.disable")

        # Collect CSS coverage
        css_result = await self._cdp.send("CSS.stopRuleUsageTracking")
        await self._cdp.send("CSS.disable")
        await self._cdp.send("DOM.disable")

        # Process JS coverage
        js_total_bytes = 0
        js_used_bytes = 0
        js_files: list[dict] = []

        for script in js_result.get("result", []):
            url = script.get("url", "")
            if not url:
                continue
            ranges = script.get("functions", [])
            script_end = 0
            used = 0
            for func in ranges:
                for r in func.get("ranges", []):
                    end = r.get("endOffset", 0)
                    if end > script_end:
                        script_end = end
                    if r.get("count", 0) > 0:
                        used += r["endOffset"] - r["startOffset"]
            js_total_bytes += script_end
            js_used_bytes += used
            js_files.append({
                "url": url,
                "total_bytes": script_end,
                "used_bytes": used,
            })

        # Process CSS coverage
        css_total_bytes = 0
        css_used_bytes = 0
        css_files_map: dict[str, dict] = {}

        for rule in css_result.get("ruleUsage", []):
            style_sheet_id = rule.get("styleSheetId", "unknown")
            end_offset = rule.get("endOffset", 0)
            start_offset = rule.get("startOffset", 0)
            used = rule.get("used", False)
            length = end_offset - start_offset

            if style_sheet_id not in css_files_map:
                css_files_map[style_sheet_id] = {
                    "style_sheet_id": style_sheet_id,
                    "total_bytes": 0,
                    "used_bytes": 0,
                }
            entry = css_files_map[style_sheet_id]
            entry["total_bytes"] += length
            if used:
                entry["used_bytes"] += length

        css_files = list(css_files_map.values())
        for f in css_files:
            css_total_bytes += f["total_bytes"]
            css_used_bytes += f["used_bytes"]

        return {
            "js": {
                "total_bytes": js_total_bytes,
                "used_bytes": js_used_bytes,
                "unused_bytes": js_total_bytes - js_used_bytes,
                "files": js_files,
            },
            "css": {
                "total_bytes": css_total_bytes,
                "used_bytes": css_used_bytes,
                "unused_bytes": css_total_bytes - css_used_bytes,
                "files": css_files,
            },
        }

    def get_waterfall(self) -> list[dict]:
        """Return all captured resources sorted by start_time."""
        entries = list(self._requests.values())
        entries.sort(key=lambda e: e.get("start_time") or 0)
        return entries

    async def export_results(self, path: str) -> Path:
        """Save all analysis results to a JSON file."""
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        results = {
            "resources": list(self._requests.values()),
            "summary": self.get_resource_summary(),
            "waterfall": self.get_waterfall(),
        }

        output_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        return output_path

    async def close(self) -> None:
        """Detach the CDP session."""
        if self._cdp:
            try:
                await self._cdp.detach()
            except Exception:
                pass
            self._cdp = None
