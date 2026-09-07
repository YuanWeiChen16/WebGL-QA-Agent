"""Unattended Android autoplay — drives the game from its knowledge base.

Runs the same GameSession as the browser path over the adb driver, so the
perception layer, crash/freeze detector, oracle and HTML reporter are shared.
Unlike android_monitor.py this one sends input.

Everything it knows comes from ``knowledge/<game>/`` — nothing is hardcoded:

- Which screen is showing is decided by ``detection.anchors`` (region SSIM
  against stored UI crops) through ``GameSession.identify_screen()``. Motion is
  deliberately NOT used for this: animated title art moves as much as gameplay.
- How to get from that screen into gameplay comes from ``flow_graph.yaml``.
- Where to tap comes from the ``gameplay`` system (``fire_points`` inside
  ``fish_area``). Elements marked ``destructive: true`` on the screen being
  driven are refused as tap targets, and a near-total repaint mid-run stops
  the loop and re-identifies the screen instead of tapping blind.

Needs an unrestricted ADB shell (`input` must work). On BlueStacks that is
Settings -> Advanced -> Android Debug Bridge.

Usage (run with -X utf8 so game text prints on a cp950 console — project convention):
  python -X utf8 scripts/android_autoplay.py --package com.shouxin.hwby --steps 60
  python -X utf8 scripts/android_autoplay.py --package com.shouxin.hwby --dry-run
  python -X utf8 scripts/android_autoplay.py --package com.shouxin.hwby --auto-mode   # also toggle in-game auto
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from webgl_qa.adb_device import AdbCommandError, AdbDevice
from webgl_qa.agent import GameSession

# How close a tap may come to a destructive control before it is refused.
DESTRUCTIVE_MARGIN_PX = 60

# A single action changing this much of the screen means we probably left the
# screen the coordinates were authored for. Measured: pressing BACK out of
# gameplay produced a pixel_diff of 0.9925. It triggers a re-identification,
# not a verdict by itself.
SCREEN_CHANGE_DIFF = 0.90


class KnowledgeGap(SystemExit):
    """The game's knowledge base is missing something the autoplay needs."""


# --------------------------------------------------------------------------
# Knowledge-base plan
# --------------------------------------------------------------------------

def collect_destructive(kb, system_id: str = None) -> list[dict]:
    """Elements flagged destructive — an unattended run must not spend money,
    switch accounts, trigger downloads, or exit the app.

    Scope matters: each system's coordinates describe a different screen, so a
    control only threatens a tap while its own screen is showing. Pass
    ``system_id`` for the enforcing guard; omit it only to report cross-screen
    overlaps as information.
    """
    out = []
    items = ([(system_id, kb.systems_by_id.get(system_id))] if system_id
             else list(kb.systems_by_id.items()))
    for sid, system in items:
        if not system:
            continue
        for el in system.get("elements") or []:
            if el.get("destructive") and el.get("location"):
                out.append({"system": sid, "id": el["id"], "label": el.get("label", el["id"]),
                            "x": el["location"]["x"], "y": el["location"]["y"]})
    return out


def assert_safe(x: int, y: int, guards: list[dict], what: str) -> None:
    """Refuse a tap that lands on (or beside) a destructive control."""
    for g in guards:
        if abs(g["x"] - x) < DESTRUCTIVE_MARGIN_PX and abs(g["y"] - y) < DESTRUCTIVE_MARGIN_PX:
            raise KnowledgeGap(
                f"refusing {what} at ({x},{y}): within {DESTRUCTIVE_MARGIN_PX}px of "
                f"destructive element {g['system']}.{g['id']} ({g['label']}) at ({g['x']},{g['y']})")


def require_element(kb, system_id: str, element_id: str) -> dict:
    el = kb.get_element(system_id, element_id)
    if not el:
        raise KnowledgeGap(f"knowledge base has no element '{element_id}' in system '{system_id}' — "
                           f"add it to knowledge/<game>/systems/{system_id}.yaml")
    return el


def load_plan(session) -> dict:
    """Read and validate the autoplay plan out of the knowledge base."""
    kb = session.knowledge
    if not kb.systems_by_id:
        raise KnowledgeGap(f"no knowledge base for '{session.game_name}' — create "
                           f"knowledge/{session.game_name}/systems/gameplay.yaml first. "
                           f"Blind tapping is not autoplay.")
    gameplay = kb.systems_by_id.get("gameplay")
    if not gameplay:
        raise KnowledgeGap("knowledge base has no 'gameplay' system")
    if not kb.get_detection_anchors("gameplay"):
        raise KnowledgeGap("gameplay system has no detection.anchors — the run cannot tell "
                           "whether it is really on the gameplay screen, so it will not tap")

    area = require_element(kb, "gameplay", "fish_area").get("bounds")
    fire_points = gameplay.get("fire_points") or []
    if not fire_points:
        if not area:
            raise KnowledgeGap("gameplay needs 'fire_points' or a 'fish_area' element with bounds")
        # Derive a sweep from the declared area: a fixed cannon angle could
        # otherwise let a frozen game look like it is responding.
        fire_points = [{"x": area["x"] + int(area["width"] * fx), "y": area["y"] + int(area["height"] * fy)}
                       for fx, fy in ((0.15, 0.2), (0.5, 0.15), (0.85, 0.3), (0.9, 0.7), (0.6, 0.9), (0.25, 0.75))]

    guards = collect_destructive(kb, "gameplay")
    for p in fire_points:
        assert_safe(p["x"], p["y"], guards, "fire point")
        if area and not (area["x"] <= p["x"] <= area["x"] + area["width"]
                         and area["y"] <= p["y"] <= area["y"] + area["height"]):
            raise KnowledgeGap(f"fire point ({p['x']},{p['y']}) lies outside declared fish_area {area}")

    elsewhere = [g for g in collect_destructive(kb) if g["system"] != "gameplay"]
    overlaps = [(p, g) for p in fire_points for g in elsewhere
                if abs(g["x"] - p["x"]) < DESTRUCTIVE_MARGIN_PX and abs(g["y"] - p["y"]) < DESTRUCTIVE_MARGIN_PX]

    plan = {"fire_points": fire_points, "fish_area": area, "guards": guards,
            "cross_screen_overlaps": overlaps,
            "auto_fire": kb.get_element("gameplay", "auto_fire"),
            "claim_reward": kb.get_element("gameplay", "claim_reward"),
            "known_issues": kb.get_known_issues("gameplay")}
    for key in ("auto_fire", "claim_reward"):
        el = plan[key]
        if el and el.get("location"):
            assert_safe(el["location"]["x"], el["location"]["y"], guards, key)
    return plan


# --------------------------------------------------------------------------
# Screen identification + navigation
# --------------------------------------------------------------------------

async def where_am_i(session) -> dict:
    """Capture a frame and identify the screen from knowledge-base anchors."""
    await session.observe()
    ident = session.identify_screen()
    scores = ", ".join(f"{k}={v}" for k, v in sorted(ident["scores"].items(), key=lambda kv: -kv[1]))
    label = ident["system_id"] or (f"ambiguous(best={ident['best']})" if ident["ambiguous"] else "unknown")
    print(f"      screen: {label}  [{scores}]", flush=True)
    return ident


async def try_dismiss_popups(session) -> dict:
    """Unknown screen: tap only the knowledge-base's declared popup close
    positions (``game_info.popup_dismiss``), re-identifying after each tap.

    Bounded by ``max_attempts`` and stops the moment a known screen appears,
    so it never degenerates into tapping around an unmapped screen.
    """
    cfg = session.config.get_section("popup_dismiss")
    node_types = {n.get("id"): n.get("type") for n in session.knowledge.flow_graph.get("nodes", [])}

    # Transient overlays (level-up, reward toasts) clear themselves; give them
    # that chance before touching anything.
    transient_wait = float(cfg.get("transient_wait", 0) or 0)
    if transient_wait > 0:
        print(f"      waiting {transient_wait:.0f}s for a transient overlay to clear", flush=True)
        await asyncio.sleep(transient_wait)
        ident = await where_am_i(session)
        if ident["system_id"] and node_types.get(ident["system_id"]) != "transient":
            return ident
        if ident["system_id"] and node_types.get(ident["system_id"]) == "transient":
            # Known transient: keep waiting rather than tapping.
            await asyncio.sleep(transient_wait)
            return await where_am_i(session)

    positions = cfg.get("close_positions") or []
    if not positions:
        print("      no popup_dismiss.close_positions declared — cannot try to clear a popup",
              flush=True)
        return await where_am_i(session)
    max_attempts = int(cfg.get("max_attempts", 3))
    wait_s = float(cfg.get("wait_between", 1.5))
    ident = {"system_id": None}
    for attempt in range(max_attempts):
        pos = positions[attempt % len(positions)]
        print(f"      popup fallback {attempt + 1}/{max_attempts}: close at ({pos['x']},{pos['y']})"
              f" {pos.get('note', '')}", flush=True)
        await session.execute_action({"type": "click", "x": pos["x"], "y": pos["y"]})
        await asyncio.sleep(wait_s)
        ident = await where_am_i(session)
        if ident["system_id"]:
            return ident
    return ident


async def wait_until_not(session, screen_id: str, timeout_s: float, interval_s: float) -> dict:
    """Poll identification until the screen is no longer ``screen_id``."""
    waited = 0.0
    while waited < timeout_s:
        await asyncio.sleep(interval_s)
        waited += interval_s
        ident = await where_am_i(session)
        if ident["system_id"] and ident["system_id"] != screen_id:
            return ident
        if ident["system_id"] is None and not ident["ambiguous"]:
            # Between screens: keep waiting rather than declaring anything.
            continue
    return await where_am_i(session)


async def navigate_to_gameplay(session, start: str) -> bool:
    """Follow the flow graph from ``start`` into gameplay, verifying each hop
    by re-identifying the screen rather than trusting the tap."""
    kb, cfg = session.knowledge, session.config
    path = kb.get_path(start, "gameplay")
    if not path:
        raise KnowledgeGap(f"flow_graph has no route from '{start}' to 'gameplay'")
    print("      route: " + " -> ".join([path[0]["from"]] + [e["to"] for e in path]), flush=True)

    order = [path[0]["from"]] + [e["to"] for e in path]
    node_types = {n.get("id"): n.get("type") for n in kb.flow_graph.get("nodes", [])}
    i = 0
    while i < len(path):
        edge = path[i]
        src, dst = edge["from"], edge["to"]
        if node_types.get(src) == "transition":
            timeout_s = cfg.get("timing.title_to_lobby_load", 200)
            interval_s = cfg.get("timing.load_poll_interval", 14)
            print(f"      [{src} -> {dst}] waiting for the transition to finish (up to {timeout_s}s)",
                  flush=True)
            ident = await wait_until_not(session, src, timeout_s, interval_s)
        else:
            action = edge.get("action") or {}
            if not (isinstance(action, dict) and "system" in action):
                raise KnowledgeGap(f"edge {src}->{dst} has no executable action in flow_graph")
            steps = kb.get_action_sequence(action["system"], action["action"])
            if not steps:
                raise KnowledgeGap(f"no steps for {action['system']}.{action['action']}")
            print(f"      [{src} -> {dst}] {action['system']}.{action['action']}", flush=True)
            for step in steps:
                if step.get("type") == "click":
                    r = await session.execute_action({"type": "click", "x": step["x"], "y": step["y"]})
                    print(f"        click({step['x']},{step['y']}) pixel_diff="
                          f"{(r.get('effect') or {}).get('pixel_diff')}", flush=True)
                elif step.get("type") == "wait":
                    secs = step.get("seconds", 1)
                    print(f"        wait {secs}s", flush=True)
                    await asyncio.sleep(secs)
            ident = await where_am_i(session)

        cur = ident["system_id"]
        if cur == dst:
            i += 1
            continue
        if cur in order and order.index(cur) > order.index(dst):
            # The game moved further along the route than this hop (e.g. a
            # fast load) — resume from where we actually are.
            print(f"      already at '{cur}' — skipping ahead", flush=True)
            i = order.index(cur)
            continue
        if cur is None and node_types.get(dst) == "transition":
            # Transition screens change second to second and may not match
            # their anchors; the next hop polls until a known screen appears.
            print(f"      transition '{dst}' not matched by anchors — polling until a known "
                  f"screen appears", flush=True)
            i += 1
            continue
        if cur is None:
            # Most likely an unmapped popup over the expected screen.
            ident = await try_dismiss_popups(session)
            cur = ident["system_id"]
            if cur == dst:
                i += 1
                continue
            if cur in order and order.index(cur) > order.index(dst):
                print(f"      already at '{cur}' — skipping ahead", flush=True)
                i = order.index(cur)
                continue
        print(f"      expected '{dst}' after this hop, identified '{cur}' — stopping navigation",
              flush=True)
        return False
    return True


async def confirm_gameplay(session, motion_threshold: float) -> bool:
    """Gameplay = anchors say gameplay AND the frame is alive (moving)."""
    ident = await where_am_i(session)
    if ident["system_id"] != "gameplay":
        return False
    obs = await session.observe()
    print(f"      liveness: pixel_change={obs['pixel_change_ratio']:.4f} (threshold {motion_threshold})",
          flush=True)
    return obs["pixel_change_ratio"] > motion_threshold


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Unattended Android autoplay + QA watch")
    parser.add_argument("--serial", default=os.environ.get("ADB_SERIAL", "127.0.0.1:5555"))
    parser.add_argument("--package", default=os.environ.get("ANDROID_PACKAGE"))
    parser.add_argument("--adb-path", default=os.environ.get("ADB_PATH"))
    parser.add_argument("--steps", type=int, default=60, help="Number of fire actions")
    parser.add_argument("--interval", type=float, default=1.5, help="Seconds between actions")
    parser.add_argument("--observe-every", type=int, default=5,
                        help="Run a full anomaly observation every N actions")
    parser.add_argument("--claim-every", type=int, default=20,
                        help="Clear the reward banner every N actions (0 disables)")
    parser.add_argument("--no-navigate", action="store_true",
                        help="Do not follow the flow graph into gameplay; require it already showing")
    parser.add_argument("--auto-mode", action="store_true",
                        help="Also toggle the game's built-in auto button. Off by default: it is a "
                             "toggle with unknown initial state, and this runner already drives the "
                             "cannon itself")
    parser.add_argument("--dry-run", action="store_true",
                        help="Load and validate the knowledge base, send no input")
    parser.add_argument("--game-name", default=None)
    args = parser.parse_args()
    if not args.package:
        parser.error("--package is required (or set ANDROID_PACKAGE)")

    device = AdbDevice(serial=args.serial, package=args.package, adb_path=args.adb_path)
    session = GameSession(game_url="adb://", game_name=args.game_name or args.package.replace(".", "_"),
                          driver=device)
    # game_info.yaml is merged into the session config, so thresholds and timing
    # are game-specific without touching config/default.yaml.
    motion_threshold = session.config.get("motion.gameplay_min_change", 0.15)

    print(f"[1/5] Reading knowledge base for '{session.game_name}'...", flush=True)
    plan = load_plan(session)
    kb = session.knowledge
    print(f"      systems: {sorted(kb.systems_by_id)}", flush=True)
    print(f"      anchors: " + ", ".join(f"{s}:{len(kb.get_detection_anchors(s))}"
                                          for s in sorted(kb.systems_by_id)), flush=True)
    print(f"      fish_area: {plan['fish_area']}   fire points: {len(plan['fire_points'])}", flush=True)
    print(f"      destructive guards (gameplay screen): {len(plan['guards'])}", flush=True)
    for p_, g in plan["cross_screen_overlaps"]:
        print(f"      note: fire point ({p_['x']},{p_['y']}) coincides with {g['system']}.{g['id']} "
              f"({g['label']}) on another screen — that is why the screen is re-identified after any "
              f"large repaint", flush=True)
    for issue in plan["known_issues"]:
        print(f"      known issue [{issue.get('status')}] {issue.get('id')}: {issue.get('solution', '')}",
              flush=True)
    if args.dry_run:
        print("      --dry-run: knowledge base validated, no input sent.", flush=True)
        return

    print(f"[2/5] Attaching to {args.serial} ({args.package})...", flush=True)
    info = await session.start()
    vp = info["canvas"]
    declared = session.config.get("screen", {}) or {}
    print(f"      viewport {vp['width']}x{vp['height']}  driver={session.driver.name}", flush=True)
    if declared and (declared.get("width"), declared.get("height")) != (vp["width"], vp["height"]):
        print(f"      device is {vp['width']}x{vp['height']} but the knowledge base was authored for "
              f"{declared.get('width')}x{declared.get('height')} — coordinates and anchors would be "
              f"off. Aborting.", flush=True)
        await session.finish()
        return

    print("[3/5] Identifying the current screen...", flush=True)
    ident = await where_am_i(session)
    if not ident["system_id"] and not args.no_navigate:
        print("      screen not recognised — trying the declared popup close positions", flush=True)
        ident = await try_dismiss_popups(session)
    in_gameplay = ident["system_id"] == "gameplay"
    if not in_gameplay and not args.no_navigate:
        if not ident["system_id"]:
            print("      screen still not recognised by any anchor — refusing to navigate blind.",
                  flush=True)
        else:
            print(f"      navigating from '{ident['system_id']}' via the flow graph", flush=True)
            if await navigate_to_gameplay(session, ident["system_id"]):
                in_gameplay = True
    if in_gameplay:
        in_gameplay = await confirm_gameplay(session, motion_threshold)
    if not in_gameplay:
        print("      NOT in gameplay — refusing to tap blindly.", flush=True)
        result = await session.finish()
        print(f"      report: {result['report_path']}", flush=True)
        return

    enabled_auto = False
    if args.auto_mode and plan["auto_fire"]:
        loc = plan["auto_fire"]["location"]
        print(f"[4/5] Enabling built-in auto mode ({plan['auto_fire']['label']} at {loc['x']},{loc['y']})...",
              flush=True)
        r = await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
        enabled_auto = r.get("status") == "ok"
        print(f"      {r['status']}  pixel_diff={(r.get('effect') or {}).get('pixel_diff')}", flush=True)
    else:
        print("[4/5] Built-in auto mode left untouched (pass --auto-mode to toggle it).", flush=True)

    print(f"[5/5] Firing {args.steps} actions @ {args.interval}s...", flush=True)
    fire_points, guards = plan["fire_points"], plan["guards"]
    node_types = {n.get("id"): n.get("type") for n in kb.flow_graph.get("nodes", [])}
    blocked, anomalies, metrics_series = 0, [], []
    try:
        for step in range(args.steps):
            p = fire_points[step % len(fire_points)]
            assert_safe(p["x"], p["y"], guards, "fire")
            r = await session.execute_action({"type": "click", "x": p["x"], "y": p["y"]})
            eff = r.get("effect") or {}
            if eff.get("blocked"):
                blocked += 1

            diff = eff.get("pixel_diff")
            if diff is not None and diff >= SCREEN_CHANGE_DIFF:
                print(f"      large repaint after fire (pixel_diff={diff}) — re-identifying", flush=True)
                ident = await where_am_i(session)
                if ident["system_id"] is None:
                    # Usually an in-game popup (boss alert, reward, event) over
                    # the play field: wait for transients, then try the declared
                    # close positions.
                    ident = await try_dismiss_popups(session)
                cur = ident["system_id"]
                if cur and cur != "gameplay":
                    # A known screen: the flow graph says how to get back (a
                    # transient overlay is simply waited out). Leaving gameplay
                    # for anything other than an overlay/transient is worth a
                    # note in the report even when recovery succeeds.
                    ntype = node_types.get(cur)
                    if ntype not in ("transient", "overlay"):
                        session.report_bug(f"Autoplay left the gameplay screen after a fire tap at "
                                           f"({p['x']},{p['y']}); identified '{cur}' "
                                           f"(pixel_diff={diff}); see attached screenshot",
                                           severity="medium")
                    print(f"      on '{cur}' ({ntype}) — recovering via the flow graph", flush=True)
                    try:
                        recovered = await navigate_to_gameplay(session, cur)
                    except KnowledgeGap as e:
                        print(f"      {e}", flush=True)
                        recovered = False
                    ident = await where_am_i(session) if recovered else ident
                    cur = ident["system_id"]
                if cur != "gameplay":
                    session.report_bug(f"Autoplay could not return to the gameplay screen after a fire "
                                       f"tap at ({p['x']},{p['y']}); last identified '{cur}' "
                                       f"(pixel_diff={diff}); see attached screenshot", severity="medium")
                    print("      not on gameplay and no knowledge-base route restored it — stopping.",
                          flush=True)
                    break
                print("      back on gameplay — continuing", flush=True)

            if (step + 1) % args.observe_every == 0:
                obs = await session.observe()
                m = await device.get_performance_metrics()
                metrics_series.append(m)
                if obs["anomalies"]:
                    anomalies.extend(obs["anomalies"])
                print(f"      [{step + 1:>3}/{args.steps}] fire({p['x']},{p['y']})  diff={diff}"
                      f"  change={obs['pixel_change_ratio']:.4f}  mem={m['memory']['used_mb']}MB"
                      f"  fps={m['frames']['fps_avg']}  jank={m['frames']['janky_percent']}%"
                      + (f"  ANOMALY {obs['anomalies']}" if obs["anomalies"] else ""), flush=True)

            claim = plan["claim_reward"]
            if args.claim_every and claim and (step + 1) % args.claim_every == 0:
                loc = claim["location"]
                assert_safe(loc["x"], loc["y"], guards, "claim_reward")
                await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
            await asyncio.sleep(args.interval)
    except KnowledgeGap as e:
        print(f"\n      SAFETY STOP: {e}", flush=True)
    except KeyboardInterrupt:
        print("\n      Interrupted — writing the report for what was collected.", flush=True)
    except AdbCommandError as e:
        print(f"\n      Device error: {e}", flush=True)

    # Final ground truth for the report: which screen did we end on?
    final = await where_am_i(session)

    # Leave the game as we found it: the built-in auto mode keeps spending
    # coins unattended. Only toggle it back when we can see the gameplay screen
    # — tapping that spot on any other screen would be a blind tap.
    if enabled_auto and plan["auto_fire"]:
        if final["system_id"] == "gameplay":
            loc = plan["auto_fire"]["location"]
            await session.execute_action({"type": "click", "x": loc["x"], "y": loc["y"]})
            print("      built-in auto mode toggled back off", flush=True)
        else:
            print(f"      WARNING: auto mode was enabled but the final screen is "
                  f"'{final['system_id']}', so it was left on — check the game", flush=True)
    mems = [m["memory"]["used_mb"] for m in metrics_series if m["memory"]["used_mb"] is not None]
    fpss = [m["frames"]["fps_avg"] for m in metrics_series if m["frames"]["fps_avg"] is not None]
    print("      --- summary ---", flush=True)
    print(f"      final screen: {final['system_id']}", flush=True)
    if mems:
        print(f"      memory: {mems[0]:.1f} -> {mems[-1]:.1f} MB  (peak {max(mems):.1f}, "
              f"growth {mems[-1] - mems[0]:+.1f})", flush=True)
    if fpss:
        print(f"      fps:    {min(fpss):.1f} - {max(fpss):.1f}  (mean {sum(fpss) / len(fpss):.1f})", flush=True)
    print(f"      no-effect-loop blocks: {blocked}", flush=True)
    print(f"      anomalies: {len(anomalies)}", flush=True)
    for a in anomalies[:10]:
        print(f"        [{a['severity']}] {a['type']}: {a['description']}", flush=True)

    result = await session.finish()
    print(f"\n  Run dir: {result['run_dir']}\n  Report:  {result['report_path']}\n"
          f"  Steps:   {result['total_steps']}   Bugs: {result['bugs_found']}")


if __name__ == "__main__":
    asyncio.run(main())
