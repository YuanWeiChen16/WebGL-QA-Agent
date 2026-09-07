"""Performance profiling runner for WebGL games.

Usage:
  python perf_runner.py --url https://example.com/game/ --duration 30
  python perf_runner.py --headless --trace --output-dir ./perf_reports/
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.browser import GameBrowser
from webgl_qa.perf_profiler import PerfProfiler
from webgl_qa.network_analyzer import NetworkAnalyzer
from webgl_qa.perf_report import PerfReporter


async def main():
    parser = argparse.ArgumentParser(description="WebGL performance profiling runner")
    parser.add_argument(
        "--url",
        default=os.environ.get("GAME_URL", "https://nicephoton.github.io/atlantis-sea/"),
        help="Game URL to profile",
    )
    parser.add_argument("--duration", type=int, default=30, help="FPS measurement duration in seconds")
    parser.add_argument("--output-dir", default="./perf_reports/", help="Base output directory")
    parser.add_argument("--headless", action="store_true", default=False, help="Run in headless mode")
    parser.add_argument("--no-headless", action="store_true", help="Run in headed mode (default)")
    parser.add_argument("--trace", action="store_true", default=False, help="Enable Chrome tracing")
    args = parser.parse_args()

    headless = args.headless and not args.no_headless

    # Create timestamped output subdirectory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir) / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/7] Launching browser (headless={headless})...", flush=True)
    browser = GameBrowser(headless=headless)
    await browser.launch_browser()
    page = browser._page

    profiler = PerfProfiler(page)
    analyzer = NetworkAnalyzer(page)

    try:
        # Capture must be armed before navigation, otherwise every asset request
        # of the initial page load is missed.
        print("[2/7] Starting profiler and network capture...", flush=True)
        await profiler.start()
        await analyzer.start()
        await analyzer.start_capture()

        trace_path = None
        if args.trace:
            print("       Tracing enabled.", flush=True)
            await profiler.start_tracing()

        print(f"[3/7] Navigating to {args.url} ...", flush=True)
        await browser.navigate(args.url)
        await asyncio.sleep(10)

        print(f"[4/7] Measuring FPS for {args.duration}s...", flush=True)
        fps_data = await profiler.measure_fps(duration_seconds=args.duration)

        print("[5/7] Collecting performance metrics...", flush=True)
        perf_metrics = await profiler.get_performance_metrics()

        await profiler.start_cpu_profile()
        await asyncio.sleep(5)
        cpu_hotspots = await profiler.stop_cpu_profile()

        memory_snapshot = await profiler.get_memory_snapshot()
        coverage = await analyzer.get_js_css_coverage()

        print("[6/7] Stopping capture...", flush=True)
        network_data = await analyzer.stop_capture()
        resource_summary = analyzer.get_resource_summary()

        if args.trace:
            trace_path_obj = await profiler.stop_tracing(str(output_dir / "trace.json"))
            trace_path = str(trace_path_obj)

        print("[7/7] Generating reports...", flush=True)

        # Transform data into the shape PerfReporter expects
        # fps_data from measure_fps: {avg_fps, min_fps, max_fps, frame_times_ms}
        # Convert frame_times_ms to fps samples for the reporter
        frame_times = fps_data.get("frame_times_ms", [])
        fps_samples = [1000.0 / ft for ft in frame_times if ft > 0]

        reporter_metrics = {
            "fps_samples": fps_samples,
            "memory": {
                "heap_used": perf_metrics.get("js_heap_size_mb", 0) * 1024 * 1024,
                "heap_growth": memory_snapshot.get("heap_growth_mb", 0) * 1024 * 1024,
            },
        }

        # Transform network_data (list of dicts with encoded_size) into reporter format
        network_resources = []
        for entry in network_data:
            network_resources.append({
                "url": entry.get("url", "unknown"),
                "type": entry.get("mime_type", "unknown"),
                "size": entry.get("encoded_size", 0),
            })

        # Transform coverage into reporter format
        coverage_entries = []
        for js_file in coverage.get("js", {}).get("files", []):
            coverage_entries.append({
                "url": js_file.get("url", ""),
                "total_bytes": js_file.get("total_bytes", 0),
                "used_bytes": js_file.get("used_bytes", 0),
            })
        for css_file in coverage.get("css", {}).get("files", []):
            coverage_entries.append({
                "url": css_file.get("style_sheet_id", ""),
                "total_bytes": css_file.get("total_bytes", 0),
                "used_bytes": css_file.get("used_bytes", 0),
            })
        reporter_coverage = {"entries": coverage_entries}

        reporter = PerfReporter(
            metrics=reporter_metrics,
            network_resources=network_resources,
            coverage=reporter_coverage,
            trace_path=trace_path,
        )

        json_report = reporter.generate_json_report(str(output_dir / "report.json"))
        html_report = reporter.generate_html_report(str(output_dir / "report.html"))
        summary_text = reporter.generate_summary()

        print("\n" + summary_text, flush=True)
        print(f"\n  Output dir:  {output_dir}", flush=True)
        print(f"  JSON report: {json_report}", flush=True)
        print(f"  HTML report: {html_report}", flush=True)
        print(f"  FPS avg:     {fps_data.get('avg_fps', 'N/A')}", flush=True)
        print(f"  FPS min:     {fps_data.get('min_fps', 'N/A')}", flush=True)
        print(f"  FPS max:     {fps_data.get('max_fps', 'N/A')}", flush=True)
        print(f"  Network:     {len(network_data)} requests", flush=True)
        print(f"  CPU top fn:  {cpu_hotspots[0]['function_name'] if cpu_hotspots else 'N/A'}", flush=True)
        if trace_path:
            print(f"  Trace:       {trace_path}", flush=True)
        print("=================================", flush=True)

    except KeyboardInterrupt:
        print("\nInterrupted by user. Cleaning up...", flush=True)
    finally:
        await profiler.close()
        await analyzer.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
