"""Reporter — generates HTML timeline reports from session data."""

from pathlib import Path
from datetime import datetime
from typing import Optional

from jinja2 import Template


REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>WebGL QA Report — {{ title }}</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #1a1a2e; color: #e0e0e0; padding: 20px; }
h1 { color: #00d4ff; margin-bottom: 10px; }
.meta { color: #888; margin-bottom: 30px; }
.summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }
.summary-card { background: #16213e; border-radius: 8px; padding: 15px; border-left: 4px solid #00d4ff; }
.summary-card.error { border-left-color: #ff4757; }
.summary-card.warn { border-left-color: #ffa502; }
.summary-card h3 { font-size: 14px; color: #888; margin-bottom: 5px; }
.summary-card .value { font-size: 28px; font-weight: bold; }
.timeline { position: relative; padding-left: 30px; }
.timeline::before { content: ''; position: absolute; left: 14px; top: 0; bottom: 0; width: 2px; background: #333; }
.step { position: relative; margin-bottom: 20px; background: #16213e; border-radius: 8px; padding: 15px; }
.step::before { content: ''; position: absolute; left: -22px; top: 20px; width: 12px; height: 12px; border-radius: 50%; background: #00d4ff; }
.step.bug::before { background: #ff4757; }
.step .time { color: #888; font-size: 12px; }
.step .action { color: #00d4ff; font-weight: bold; margin: 5px 0; }
.step .screen { color: #a29bfe; }
.step img { max-width: 100%; max-height: 300px; border-radius: 4px; margin-top: 10px; }
.bugs { margin-top: 30px; }
.bug-item { background: #2d1b1b; border-radius: 8px; padding: 15px; margin-bottom: 10px; border-left: 4px solid #ff4757; }
.bug-item .severity { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: bold; }
.bug-item .severity.high { background: #ff4757; color: white; }
.bug-item .severity.medium { background: #ffa502; color: black; }
.bug-item .severity.low { background: #7bed9f; color: black; }
.flow-graph { margin-top: 30px; background: #16213e; border-radius: 8px; padding: 20px; }
.flow-graph pre { color: #00d4ff; font-size: 14px; line-height: 1.8; }
</style>
</head>
<body>
<h1>🎮 WebGL QA Report</h1>
<p class="meta">{{ game_url }} — {{ timestamp }}</p>

<div class="summary">
    <div class="summary-card">
        <h3>Total Steps</h3>
        <div class="value">{{ steps | length }}</div>
    </div>
    <div class="summary-card">
        <h3>Screens Found</h3>
        <div class="value">{{ screens_found }}</div>
    </div>
    <div class="summary-card {{ 'error' if bugs | length > 0 else '' }}">
        <h3>Bugs Found</h3>
        <div class="value">{{ bugs | length }}</div>
    </div>
    <div class="summary-card {{ 'warn' if console_errors > 0 else '' }}">
        <h3>Console Errors</h3>
        <div class="value">{{ console_errors }}</div>
    </div>
</div>

<h2>📋 Timeline</h2>
<div class="timeline">
{% for step in steps %}
    <div class="step {{ 'bug' if step.anomalies else '' }}">
        <div class="time">{{ step.timestamp }}</div>
        <div class="action">{{ step.action }}</div>
        <div class="screen">Screen: {{ step.screen_id or 'unknown' }}</div>
        {% if step.description %}<p>{{ step.description }}</p>{% endif %}
        {% if step.anomalies %}
        <p style="color: #ff4757;">⚠️ {{ step.anomalies | join(', ') }}</p>
        {% endif %}
        {% if step.screenshot_path %}
        <img src="{{ step.screenshot_path }}" alt="step screenshot">
        {% endif %}
    </div>
{% endfor %}
</div>

{% if bugs %}
<div class="bugs">
<h2>🐛 Bugs Found</h2>
{% for bug in bugs %}
    <div class="bug-item">
        <span class="severity {{ bug.severity }}">{{ bug.severity | upper }}</span>
        <strong>{{ bug.id }}</strong> — {{ bug.description }}
        {% if bug.repro_steps %}
        <p style="margin-top: 8px; color: #888;">Repro: {{ bug.repro_steps | join(' → ') }}</p>
        {% endif %}
    </div>
{% endfor %}
</div>
{% endif %}

{% if flow_summary %}
<div class="flow-graph">
<h2>🔀 Discovered Flow</h2>
<pre>{{ flow_summary }}</pre>
</div>
{% endif %}

</body>
</html>"""


from dataclasses import dataclass


@dataclass
class SessionStep:
    """One step in a QA session."""
    timestamp: str
    action: str
    screen_id: Optional[str] = None
    description: Optional[str] = None
    screenshot_path: Optional[str] = None
    anomalies: list = None

    def __post_init__(self):
        if self.anomalies is None:
            self.anomalies = []


class Reporter:
    """Generates HTML QA reports from session data."""

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict] = []
        self.bugs: list[dict] = []
        self.console_errors: int = 0
        self.screens_found: set = set()

    def add_step(self, action: str, screen_id: str = None, description: str = None,
                 screenshot_path: str = None, anomalies: list = None) -> None:
        """Record a step."""
        self.steps.append({
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "action": action,
            "screen_id": screen_id,
            "description": description,
            "screenshot_path": screenshot_path,
            "anomalies": anomalies or [],
        })
        if screen_id:
            self.screens_found.add(screen_id)

    def add_bug(self, bug: dict) -> None:
        """Record a bug."""
        self.bugs.append(bug)

    def add_console_errors(self, count: int) -> None:
        """Increment console error count."""
        self.console_errors += count

    def generate(self, game_url: str, flow_summary: str = "") -> str:
        """Generate HTML report. Returns the file path."""
        filepath = self.output_dir / "report.html"

        # Convert screenshot paths to relative (so report is portable)
        import os
        steps_for_render = []
        for step in self.steps:
            step_copy = dict(step)
            if step_copy.get("screenshot_path"):
                step_copy["screenshot_path"] = os.path.relpath(
                    step_copy["screenshot_path"], self.output_dir
                )
            steps_for_render.append(step_copy)

        template = Template(REPORT_TEMPLATE)
        html = template.render(
            title=f"Session {datetime.now().strftime('%Y%m%d_%H%M%S')}",
            game_url=game_url,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            steps=steps_for_render,
            bugs=self.bugs,
            console_errors=self.console_errors,
            screens_found=len(self.screens_found),
            flow_summary=flow_summary,
        )

        filepath.write_text(html, encoding="utf-8")
        return str(filepath)

    def generate_session_log(self) -> dict:
        """Generate JSON session log for replay."""
        return {
            "timestamp": datetime.now().isoformat(),
            "steps": self.steps,
            "bugs": self.bugs,
            "console_errors": self.console_errors,
            "screens_found": list(self.screens_found),
        }
