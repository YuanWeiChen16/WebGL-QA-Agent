"""CDP-based performance profiler for WebGL game sessions."""

import asyncio
import json
from pathlib import Path
from typing import Optional

from playwright.async_api import Page


class PerfProfiler:
    """Profiles WebGL game performance via Chrome DevTools Protocol."""

    def __init__(self, page: Page):
        self._page = page
        self._cdp = None
        self._tracing = False
        self._profiling = False

    async def start(self) -> None:
        """Create and attach CDP session."""
        self._cdp = await self._page.context.new_cdp_session(self._page)
        # Performance.getMetrics returns an empty list until the domain is enabled.
        await self._cdp.send("Performance.enable")

    async def start_tracing(self, categories: Optional[list[str]] = None) -> None:
        """Start Chrome tracing with specified categories."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")
        params = {}
        if categories:
            params["traceConfig"] = {"includedCategories": categories}
        await self._cdp.send("Tracing.start", params)
        self._tracing = True

    async def stop_tracing(self, output_path: str) -> Path:
        """Stop tracing and save chrome://tracing JSON to output_path."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")
        if not self._tracing:
            raise RuntimeError("Tracing not active")

        trace_events: list[dict] = []
        event = asyncio.Event()

        def on_data(params):
            # params["value"] is a list of trace event objects
            trace_events.extend(params["value"])

        def on_complete(params):
            event.set()

        self._cdp.on("Tracing.dataCollected", on_data)
        self._cdp.on("Tracing.tracingComplete", on_complete)
        await self._cdp.send("Tracing.end")
        try:
            await asyncio.wait_for(event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            self._tracing = False
            raise RuntimeError("Tracing data collection timed out")
        self._tracing = False

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(trace_events), encoding="utf-8")
        return path

    async def get_performance_metrics(self) -> dict:
        """Get JS heap, DOM nodes, layout count and script duration.

        Note: the Performance domain exposes no rendered-frame counter, so FPS is
        not derivable here — use measure_fps(), which samples requestAnimationFrame.
        """
        if not self._cdp:
            raise RuntimeError("Profiler not started")

        result = await self._cdp.send("Performance.getMetrics")
        metrics = {m["name"]: m["value"] for m in result["metrics"]}

        return {
            "js_heap_size_mb": round(metrics.get("JSHeapUsedSize", 0) / (1024 * 1024), 2),
            "js_heap_total_mb": round(metrics.get("JSHeapTotalSize", 0) / (1024 * 1024), 2),
            "dom_nodes": int(metrics.get("Nodes", 0)),
            "layout_count": int(metrics.get("LayoutCount", 0)),
            "script_duration_ms": round(metrics.get("ScriptDuration", 0) * 1000, 2),
        }

    async def start_cpu_profile(self) -> None:
        """Start CPU profiling via the Profiler domain."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")
        await self._cdp.send("Profiler.enable")
        await self._cdp.send("Profiler.start")
        self._profiling = True

    async def stop_cpu_profile(self) -> list[dict]:
        """Stop CPU profiling and return top 20 functions by self-time."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")
        if not self._profiling:
            raise RuntimeError("CPU profiling not active")

        result = await self._cdp.send("Profiler.stop")
        self._profiling = False
        await self._cdp.send("Profiler.disable")

        profile = result["profile"]
        nodes = profile.get("nodes", [])

        # Calculate self-time from hit counts and sample intervals
        time_deltas = profile.get("timeDeltas", [])
        samples = profile.get("samples", [])

        # Build node-id to self-time mapping
        self_times: dict[int, float] = {}
        for i, sample_id in enumerate(samples):
            delta = time_deltas[i] if i < len(time_deltas) else 0
            self_times[sample_id] = self_times.get(sample_id, 0) + delta

        # Build function entries
        functions = []
        for node in nodes:
            node_id = node["id"]
            call_frame = node.get("callFrame", {})
            self_time_us = self_times.get(node_id, 0)
            if self_time_us > 0:
                functions.append({
                    "function_name": call_frame.get("functionName", "(anonymous)"),
                    "url": call_frame.get("url", ""),
                    "line_number": call_frame.get("lineNumber", -1),
                    "self_time_ms": round(self_time_us / 1000, 2),
                })

        # Sort by self-time descending, return top 20
        functions.sort(key=lambda f: f["self_time_ms"], reverse=True)
        return functions[:20]

    async def get_memory_snapshot(self) -> dict:
        """Take 5 heap samples over 5s and detect potential memory leaks."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")

        samples = []
        for _ in range(5):
            result = await self._cdp.send("Performance.getMetrics")
            metrics = {m["name"]: m["value"] for m in result["metrics"]}
            samples.append(metrics.get("JSHeapUsedSize", 0) / (1024 * 1024))
            await asyncio.sleep(1.0)

        heap_growth_mb = round(samples[-1] - samples[0], 2)
        return {
            "samples_mb": [round(s, 2) for s in samples],
            "heap_growth_mb": heap_growth_mb,
            "potential_leak": heap_growth_mb > 10.0,
        }

    async def measure_fps(self, duration_seconds: float = 5.0) -> dict:
        """Measure FPS by injecting a requestAnimationFrame loop via Runtime.evaluate."""
        if not self._cdp:
            raise RuntimeError("Profiler not started")

        js_code = f"""
        () => new Promise((resolve) => {{
            const frameTimes = [];
            // The gap between evaluate() and the first callback is not a frame
            // interval; the first tick only seeds lastTime and is not recorded.
            let lastTime = null;
            let end = null;

            function tick(now) {{
                if (lastTime === null) {{
                    lastTime = now;
                    end = now + {duration_seconds * 1000};
                    requestAnimationFrame(tick);
                    return;
                }}
                frameTimes.push(now - lastTime);
                lastTime = now;
                if (now < end) {{
                    requestAnimationFrame(tick);
                }} else {{
                    resolve(frameTimes);
                }}
            }}
            requestAnimationFrame(tick);
        }})
        """

        result = await self._cdp.send("Runtime.evaluate", {
            "expression": f"({js_code})()",
            "awaitPromise": True,
            "returnByValue": True,
        })

        if "exceptionDetails" in result:
            exc = result["exceptionDetails"]
            text = exc.get("text", exc.get("exception", {}).get("description", "Unknown error"))
            raise RuntimeError(f"FPS measurement script failed: {text}")

        frame_times = result.get("result", {}).get("value", [])
        if not frame_times:
            return {"avg_fps": 0.0, "min_fps": 0.0, "max_fps": 0.0, "frame_times_ms": []}

        # Convert frame deltas to FPS values
        fps_values = [1000.0 / ft for ft in frame_times if ft > 0]
        if not fps_values:
            return {"avg_fps": 0.0, "min_fps": 0.0, "max_fps": 0.0, "frame_times_ms": frame_times}

        return {
            "avg_fps": round(sum(fps_values) / len(fps_values), 1),
            "min_fps": round(min(fps_values), 1),
            "max_fps": round(max(fps_values), 1),
            "frame_times_ms": [round(ft, 2) for ft in frame_times],
        }

    async def close(self) -> None:
        """Detach the CDP session."""
        if self._cdp:
            try:
                await self._cdp.detach()
            except Exception:
                pass
            self._cdp = None
