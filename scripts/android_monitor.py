"""Unattended Android monitoring run — screenshots, anomalies, memory, frame timing.

Drives an Android target (BlueStacks / AVD / real device) through the adb
driver and the same GameSession as the browser path, so the perception,
detector, knowledge and reporting layers are shared.

Read-only: it observes and measures but sends no input, so it works on a
device whose ADB shell is restricted (screencap and dumpsys keep working
while `input` is refused). To also drive taps, enable ADB on the device.

Usage (run with -X utf8 so game text prints on a cp950 console — project convention):
  python -X utf8 scripts/android_monitor.py --serial 127.0.0.1:5555 --package com.example.game
  python -X utf8 scripts/android_monitor.py --duration 300 --interval 5 --launch
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.adb_device import AdbCommandError, AdbDevice
from webgl_qa.agent import GameSession


def _fmt(value, suffix=""):
    return "n/a" if value is None else f"{value}{suffix}"


async def main():
    parser = argparse.ArgumentParser(description="Unattended Android QA monitor")
    parser.add_argument("--serial", default=os.environ.get("ADB_SERIAL", "127.0.0.1:5555"),
                        help="Device serial; host:port is auto-connected (BlueStacks default 127.0.0.1:5555)")
    parser.add_argument("--package", default=os.environ.get("ANDROID_PACKAGE"),
                        help="Package under test — required for memory/frame metrics")
    parser.add_argument("--adb-path", default=os.environ.get("ADB_PATH"),
                        help="Path to adb.exe (defaults to PATH lookup)")
    parser.add_argument("--duration", type=int, default=60, help="Total monitoring seconds")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between observations")
    parser.add_argument("--launch", action="store_true",
                        help="Bring the package to the front first (needs an unrestricted ADB shell)")
    parser.add_argument("--game-name", default=None, help="Knowledge/run directory name")
    args = parser.parse_args()

    if not args.package:
        parser.error("--package is required (or set ANDROID_PACKAGE)")

    device = AdbDevice(serial=args.serial, package=args.package, adb_path=args.adb_path)
    # An empty target attaches to whatever is on screen; --launch asks the
    # device to foreground the app, which a restricted shell will refuse.
    target = f"adb://{args.package}" if args.launch else "adb://"

    session = GameSession(
        game_url=target,
        game_name=args.game_name or args.package.replace(".", "_"),
        driver=device,
    )

    print(f"[1/4] Attaching to {args.serial} ({args.package})...", flush=True)
    info = await session.start()
    print(f"      viewport: {info['canvas']['width']}x{info['canvas']['height']}"
          f"  driver: {session.driver.name}"
          f"  capabilities: {sorted(session.driver.capabilities)}", flush=True)

    steps = max(1, int(args.duration / args.interval))
    print(f"[2/4] Observing for {args.duration}s ({steps} samples @ {args.interval}s)...", flush=True)

    memory_series: list[float] = []
    jank_series: list[float] = []
    fps_series: list[float] = []
    all_anomalies: list[dict] = []
    frame_source = None

    try:
        for i in range(steps):
            obs = await session.observe()
            metrics = await device.get_performance_metrics()

            used = metrics["memory"]["used_mb"]
            frame_source = metrics["frames"]["source"] or frame_source
            jank = metrics["frames"]["janky_percent"]
            if used is not None:
                memory_series.append(used)
            if jank is not None:
                jank_series.append(jank)
            if metrics["frames"]["fps_avg"] is not None:
                fps_series.append(metrics["frames"]["fps_avg"])
            if obs["anomalies"]:
                all_anomalies.extend(obs["anomalies"])

            fps = metrics["frames"]["fps_avg"]
            p90 = metrics["frames"]["p90_ms"]
            print(f"      [{i + 1:>3}/{steps}] change={obs['pixel_change_ratio']:.4f}"
                  f"  mem={_fmt(used, 'MB')}"
                  f"  fps={_fmt(fps)}"
                  f"  jank={_fmt(jank, '%')}"
                  f"  p90={_fmt(p90, 'ms')}"
                  + (f"  ANOMALY: {obs['anomalies']}" if obs["anomalies"] else ""), flush=True)

            if i < steps - 1:
                await asyncio.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n      Interrupted — writing the report for what was collected.", flush=True)
    except AdbCommandError as e:
        print(f"\n      Device error: {e}", flush=True)

    print("[3/4] Summarising...", flush=True)
    if memory_series:
        growth = memory_series[-1] - memory_series[0]
        print(f"      memory: {memory_series[0]:.1f} -> {memory_series[-1]:.1f} MB"
              f"  (peak {max(memory_series):.1f}, growth {growth:+.1f} MB)", flush=True)
    else:
        print("      memory: not measurable (check --package matches a running app)", flush=True)
    if fps_series:
        print(f"      fps:    {min(fps_series):.1f} - {max(fps_series):.1f}"
              f"  (mean {sum(fps_series) / len(fps_series):.1f})"
              f"  source={frame_source}", flush=True)
    if jank_series:
        print(f"      jank:   {min(jank_series):.1f}% - {max(jank_series):.1f}%"
              f"  (mean {sum(jank_series) / len(jank_series):.1f}%)", flush=True)
    print(f"      anomalies: {len(all_anomalies)}", flush=True)
    for a in all_anomalies[:10]:
        print(f"        [{a['severity']}] {a['type']}: {a['description']}", flush=True)

    print("[4/4] Generating report...", flush=True)
    result = await session.finish()
    print(f"\n  Run dir:  {result['run_dir']}")
    print(f"  Report:   {result['report_path']}")
    print(f"  Session:  {result['session_log_path']}")
    print(f"  Steps:    {result['total_steps']}   Bugs: {result['bugs_found']}")


if __name__ == "__main__":
    asyncio.run(main())
