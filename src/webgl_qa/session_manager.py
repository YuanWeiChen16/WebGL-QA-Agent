"""Session manager — handles per-test-run folder isolation and session metadata."""

from pathlib import Path
from datetime import datetime
from typing import Optional
import json
import shutil


class SessionManager:
    """Creates and manages isolated test session folders.
    
    Each test run gets its own timestamped folder:
      runs/
        20260630_170800_explore/
          screenshots/
          screenshots_annotated/
          report.html
          session_log.json
          knowledge_snapshot.yaml
    """

    def __init__(self, project_dir: str = None):
        # Default to the repo root (this file lives at src/webgl_qa/session_manager.py)
        self.project_dir = Path(project_dir) if project_dir else Path(__file__).resolve().parent.parent.parent
        self.runs_dir = self.project_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._current_run: Optional[Path] = None

    def create_run(self, label: str = "test") -> Path:
        """Create a new run folder. Returns the path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_name = f"{timestamp}_{label}"
        run_dir = self.runs_dir / run_name
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "screenshots").mkdir(exist_ok=True)
        (run_dir / "screenshots_annotated").mkdir(exist_ok=True)

        # Write run metadata
        metadata = {
            "run_name": run_name,
            "label": label,
            "started_at": datetime.now().isoformat(),
            "status": "running",
        }
        (run_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._current_run = run_dir
        return run_dir

    @property
    def current_run(self) -> Path:
        if self._current_run is None:
            raise RuntimeError("No active run. Call create_run() first.")
        return self._current_run

    @property
    def screenshots_dir(self) -> Path:
        return self.current_run / "screenshots"

    @property
    def annotated_dir(self) -> Path:
        return self.current_run / "screenshots_annotated"

    def finish_run(self, summary: dict = None) -> None:
        """Mark the run as complete and write summary."""
        metadata_path = self.current_run / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["finished_at"] = datetime.now().isoformat()
        metadata["status"] = "complete"
        if summary:
            metadata["summary"] = summary
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def list_runs(self) -> list[dict]:
        """List all test runs."""
        runs = []
        for d in sorted(self.runs_dir.iterdir()):
            if d.is_dir() and (d / "metadata.json").exists():
                meta = json.loads((d / "metadata.json").read_text(encoding="utf-8"))
                meta["path"] = str(d)
                runs.append(meta)
        return runs

    def get_run(self, run_name: str) -> Path:
        """Get a specific run folder by name."""
        run_dir = self.runs_d