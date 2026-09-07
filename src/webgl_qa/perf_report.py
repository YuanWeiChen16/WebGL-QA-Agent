"""Performance Reporter — pure data transformer for WebGL performance metrics.

Consumes raw metrics (FPS, memory, network, coverage) and produces
structured JSON, human-readable summary, and standalone HTML reports.
No async, no external dependencies beyond stdlib.
"""

import html
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class PerfReporter:
    """Transforms raw performance data into structured reports."""

    def __init__(
        self,
        metrics: dict,
        network_resources: list[dict],
        coverage: dict,
        trace_path: Optional[str] = None,
    ) -> None:
        self._metrics = metrics
        self._network_resources = network_resources
        self._coverage = coverage
        self._trace_path = trace_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_json_report(self, output_path: str) -> Path:
        """Write structured JSON report to output_path. Returns the Path."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "trace_path": self._trace_path,
            "fps": self._fps_stats(),
            "memory": self._memory_stats(),
            "network": {
                "total_resources": len(self._network_resources),
                "total_bytes": sum(r.get("size", 0) for r in self._network_resources),
                "resources": self._network_resources,
            },
            "coverage": self._coverage,
            "issues": self._detect_issues(),
        }

        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return path

    def generate_summary(self) -> str:
        """Return human-readable text summary."""
        fps = self._fps_stats()
        mem = self._memory_stats()
        top_assets = self._top_assets(10)
        dead_pct = self._dead_code_percent()
        total_bundle = sum(r.get("size", 0) for r in self._network_resources)
        issues = self._detect_issues()

        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  WebGL Performance Summary")
        lines.append("=" * 60)
        lines.append("")

        # FPS
        lines.append("── FPS ──")
        lines.append(f"  avg: {fps['avg']:.1f}  min: {fps['min']:.1f}  max: {fps['max']:.1f}  p95: {fps['p95']:.1f}")
        lines.append("")

        # Memory
        lines.append("── Memory ──")
        lines.append(f"  heap used: {mem['heap_used_mb']:.1f} MB")
        if mem.get("heap_growth_mb") is not None:
            lines.append(f"  heap growth: {mem['heap_growth_mb']:.1f} MB")
        if mem.get("leak_warning"):
            lines.append("  ⚠ LEAK WARNING: significant heap growth detected")
        lines.append("")

        # Top assets
        lines.append("── Top 10 Largest Assets ──")
        for i, asset in enumerate(top_assets, 1):
            size_kb = asset.get("size", 0) / 1024
            lines.append(f"  {i:2d}. {asset.get('url', 'unknown')[:60]:<60s} {size_kb:>8.1f} KB")
        lines.append("")

        # Coverage
        lines.append("── Coverage ──")
        lines.append(f"  dead code: {dead_pct:.1f}%")
        lines.append(f"  total bundle: {total_bundle / (1024 * 1024):.2f} MB")
        lines.append("")

        # Issues
        if issues:
            lines.append("── Issues ──")
            for issue in issues:
                severity_tag = issue["severity"].upper()
                lines.append(f"  [{severity_tag}] {issue['message']}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def generate_html_report(self, output_path: str) -> Path:
        """Create standalone dark-theme HTML report. Returns the Path."""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        fps = self._fps_stats()
        mem = self._memory_stats()
        issues = self._detect_issues()
        total_bundle = sum(r.get("size", 0) for r in self._network_resources)
        dead_pct = self._dead_code_percent()

        # Build issues HTML
        issues_html = ""
        for issue in issues:
            color = "#ff4757" if issue["severity"] == "critical" else "#ffa502"
            issues_html += (
                f'<div class="issue" style="border-left-color:{color};">'
                f'<span class="severity" style="background:{color};">{html.escape(issue["severity"].upper())}</span> '
                f'<span class="category">[{html.escape(issue["category"])}]</span> '
                f'{html.escape(issue["message"])}'
                f'</div>\n'
            )

        # Build network table rows
        net_rows = ""
        for r in sorted(self._network_resources, key=lambda x: x.get("size", 0), reverse=True):
            size_kb = r.get("size", 0) / 1024
            url_display = html.escape(r.get("url", "unknown")[:80])
            rtype = html.escape(r.get("type", "unknown"))
            net_rows += f"<tr><td>{url_display}</td><td>{rtype}</td><td>{size_kb:.1f} KB</td></tr>\n"

        # Build coverage table rows
        cov_rows = ""
        for entry in self._coverage.get("entries", []):
            url_display = html.escape(str(entry.get("url", "unknown"))[:80])
            total_bytes = entry.get("total_bytes", 0)
            used_bytes = entry.get("used_bytes", 0)
            unused_pct = ((total_bytes - used_bytes) / total_bytes * 100) if total_bytes > 0 else 0
            cov_rows += f"<tr><td>{url_display}</td><td>{total_bytes}</td><td>{used_bytes}</td><td>{unused_pct:.1f}%</td></tr>\n"

        report_html = _HTML_TEMPLATE.format(
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            fps_avg=f"{fps['avg']:.1f}",
            fps_min=f"{fps['min']:.1f}",
            fps_max=f"{fps['max']:.1f}",
            fps_p95=f"{fps['p95']:.1f}",
            heap_used=f"{mem['heap_used_mb']:.1f}",
            heap_growth=f"{mem.get('heap_growth_mb', 0):.1f}",
            total_bundle=f"{total_bundle / (1024 * 1024):.2f}",
            dead_code_pct=f"{dead_pct:.1f}",
            issue_count=len(issues),
            issues_section=issues_html if issues else '<p style="color:#7bed9f;">No issues detected.</p>',
            network_rows=net_rows,
            coverage_rows=cov_rows,
        )

        with open(path, "w", encoding="utf-8") as f:
            f.write(report_html)

        return path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fps_stats(self) -> dict:
        """Extract FPS statistics from metrics."""
        frames = self._metrics.get("fps_samples", [])
        if not frames:
            return {"avg": 0.0, "min": 0.0, "max": 0.0, "p95": 0.0}

        # frames are FPS values (higher = better)
        # p95 = 95th percentile of FPS values sorted ascending (i.e. only 5% of frames are worse)
        sorted_fps = sorted(frames)
        p95_idx = max(0, int(len(sorted_fps) * 0.05))
        return {
            "avg": statistics.mean(frames),
            "min": min(frames),
            "max": max(frames),
            "p95": sorted_fps[p95_idx],
        }

    def _memory_stats(self) -> dict:
        """Extract memory statistics."""
        mem = self._metrics.get("memory", {})
        heap_used = mem.get("heap_used", 0)
        heap_growth = mem.get("heap_growth", None)
        leak_warning = False
        if heap_growth is not None and heap_growth > 50 * 1024 * 1024:
            leak_warning = True
        return {
            "heap_used_mb": heap_used / (1024 * 1024),
            "heap_growth_mb": heap_growth / (1024 * 1024) if heap_growth is not None else None,
            "leak_warning": leak_warning,
        }

    def _top_assets(self, n: int) -> list[dict]:
        """Return top N largest network resources."""
        return sorted(self._network_resources, key=lambda r: r.get("size", 0), reverse=True)[:n]

    def _dead_code_percent(self) -> float:
        """Calculate dead code percentage from coverage data."""
        entries = self._coverage.get("entries", [])
        if not entries:
            return 0.0
        total_bytes = sum(e.get("total_bytes", 0) for e in entries)
        used_bytes = sum(e.get("used_bytes", 0) for e in entries)
        if total_bytes == 0:
            return 0.0
        return (total_bytes - used_bytes) / total_bytes * 100

    def _detect_issues(self) -> list[dict]:
        """Flag performance issues based on thresholds."""
        issues: list[dict] = []
        fps = self._fps_stats()
        mem = self._memory_stats()
        dead_pct = self._dead_code_percent()
        total_bundle = sum(r.get("size", 0) for r in self._network_resources)

        # FPS issues
        if fps["avg"] > 0 and fps["avg"] < 30:
            issues.append({
                "severity": "critical",
                "category": "fps",
                "message": f"Average FPS critically low: {fps['avg']:.1f}",
                "value": fps["avg"],
            })
        elif fps["avg"] > 0 and fps["avg"] < 50:
            issues.append({
                "severity": "warning",
                "category": "fps",
                "message": f"Average FPS below target: {fps['avg']:.1f}",
                "value": fps["avg"],
            })

        # Memory issues
        if mem["heap_used_mb"] > 512:
            issues.append({
                "severity": "critical",
                "category": "memory",
                "message": f"Heap usage exceeds 512 MB: {mem['heap_used_mb']:.1f} MB",
                "value": mem["heap_used_mb"],
            })

        if mem.get("heap_growth_mb") is not None and mem["heap_growth_mb"] > 50:
            issues.append({
                "severity": "warning",
                "category": "memory",
                "message": f"Heap growth exceeds 50 MB (possible leak): {mem['heap_growth_mb']:.1f} MB",
                "value": mem["heap_growth_mb"],
            })

        # Coverage issues
        if dead_pct > 30:
            issues.append({
                "severity": "warning",
                "category": "dead_code",
                "message": f"Dead code exceeds 30%: {dead_pct:.1f}%",
                "value": dead_pct,
            })

        # Asset size issues
        for resource in self._network_resources:
            size_mb = resource.get("size", 0) / (1024 * 1024)
            if size_mb > 5:
                issues.append({
                    "severity": "warning",
                    "category": "asset_size",
                    "message": f"Single asset exceeds 5 MB: {resource.get('url', 'unknown')[:60]} ({size_mb:.1f} MB)",
                    "value": size_mb,
                })

        # Total bundle size
        total_bundle_mb = total_bundle / (1024 * 1024)
        if total_bundle_mb > 20:
            issues.append({
                "severity": "warning",
                "category": "bundle_size",
                "message": f"Total bundle exceeds 20 MB: {total_bundle_mb:.1f} MB",
                "value": total_bundle_mb,
            })

        return issues


# ------------------------------------------------------------------
# HTML template (standalone, inline CSS, dark theme)
# ------------------------------------------------------------------

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WebGL Performance Report</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f1a; color: #e0e0e0; padding: 24px; line-height: 1.6; }}
h1 {{ color: #00d4ff; margin-bottom: 4px; font-size: 24px; }}
h2 {{ color: #a29bfe; margin: 24px 0 12px; font-size: 18px; }}
.meta {{ color: #888; margin-bottom: 24px; font-size: 13px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 24px; }}
.card {{ background: #1a1a2e; border-radius: 8px; padding: 16px; border-left: 4px solid #00d4ff; }}
.card h3 {{ font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 4px; }}
.card .val {{ font-size: 26px; font-weight: bold; color: #fff; }}
.card.warn {{ border-left-color: #ffa502; }}
.card.crit {{ border-left-color: #ff4757; }}
.issues {{ margin-bottom: 24px; }}
.issue {{ background: #1a1a2e; border-radius: 6px; padding: 12px 16px; margin-bottom: 8px; border-left: 4px solid #ffa502; }}
.issue .severity {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; color: #fff; margin-right: 8px; }}
.issue .category {{ color: #888; font-size: 12px; margin-right: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 24px; background: #1a1a2e; border-radius: 8px; overflow: hidden; }}
th {{ background: #16213e; text-align: left; padding: 10px 12px; font-size: 12px; color: #888; text-transform: uppercase; }}
td {{ padding: 8px 12px; border-top: 1px solid #2a2a3e; font-size: 13px; word-break: break-all; }}
tr:hover td {{ background: #16213e; }}
</style>
</head>
<body>
<h1>WebGL Performance Report</h1>
<p class="meta">Generated: {timestamp}</p>

<div class="cards">
    <div class="card"><h3>FPS Avg</h3><div class="val">{fps_avg}</div></div>
    <div class="card"><h3>FPS Min</h3><div class="val">{fps_min}</div></div>
    <div class="card"><h3>FPS Max</h3><div class="val">{fps_max}</div></div>
    <div class="card"><h3>FPS P95</h3><div class="val">{fps_p95}</div></div>
    <div class="card"><h3>Heap Used</h3><div class="val">{heap_used} MB</div></div>
    <div class="card"><h3>Heap Growth</h3><div class="val">{heap_growth} MB</div></div>
    <div class="card"><h3>Bundle Size</h3><div class="val">{total_bundle} MB</div></div>
    <div class="card"><h3>Dead Code</h3><div class="val">{dead_code_pct}%</div></div>
</div>

<h2>Issues ({issue_count})</h2>
<div class="issues">
{issues_section}
</div>

<h2>Network Resources</h2>
<table>
<thead><tr><th>URL</th><th>Type</th><th>Size</th></tr></thead>
<tbody>
{network_rows}
</tbody>
</table>

<h2>Code Coverage</h2>
<table>
<thead><tr><th>URL</th><th>Total Bytes</th><th>Used Bytes</th><th>Unused</th></tr></thead>
<tbody>
{coverage_rows}
</tbody>
</table>

</body>
</html>"""
