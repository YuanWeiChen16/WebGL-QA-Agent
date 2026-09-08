"""GameSession must leave an analysable run even when it is not finished cleanly."""

import asyncio
import json
from typing import Optional

import pytest

from webgl_qa import agent as agent_mod
from webgl_qa.agent import GameSession
from webgl_qa.driver import Driver


class NullDriver(Driver):
    """A driver that never touches a device — enough to construct a session."""
    name = "null"

    async def launch(self, target: str) -> None: ...
    async def close(self) -> None: ...
    async def screenshot(self, path: Optional[str] = None) -> str: return ""
    async def get_viewport_size(self) -> dict: return {"x": 0, "y": 0, "width": 1, "height": 1}
    async def click(self, x: int, y: int) -> None: ...
    async def drag(self, from_x: int, from_y: int, to_x: int, to_y: int) -> None: ...


@pytest.fixture
def session(tmp_path):
    # project_dir=tmp_path keeps runs/ and knowledge/ out of the real repo.
    return GameSession(game_url="adb://", game_name="synthetic_abort",
                       project_dir=str(tmp_path), driver=NullDriver())


class TestAbort:
    def test_abort_writes_aborted_session_and_report(self, session):
        session.step_count = 3
        log = session.abort("unit test")
        data = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))
        assert data["status"] == "aborted"
        assert data["abort_reason"] == "unit test"
        assert data["total_steps"] == 3
        assert data["game_name"] == "synthetic_abort"
        assert (session.run_dir / "report.html").exists()
        assert log["status"] == "aborted"
        # The timeline records why the run ended.
        assert any(s["action"] == "aborted" for s in data["steps"])

    def test_abort_is_idempotent(self, session):
        assert session.abort("first") is not None
        assert session.abort("second") is None
        data = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))
        assert data["abort_reason"] == "first"

    def test_live_registry_tracks_unfinished_sessions(self, session):
        assert session in agent_mod._live_sessions
        session.abort("done")
        assert session not in agent_mod._live_sessions

    def test_exit_hook_flushes_open_sessions(self, session):
        assert not (session.run_dir / "session.json").exists()
        agent_mod._flush_live_sessions_at_exit()
        data = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))
        assert data["status"] == "aborted"
        assert "process exited" in data["abort_reason"]
        assert session not in agent_mod._live_sessions

    def test_finish_marks_completed_and_deregisters(self, session):
        result = asyncio.run(session.finish())
        data = json.loads((session.run_dir / "session.json").read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert session not in agent_mod._live_sessions
        assert session.abort("late") is None          # nothing to do after a clean finish
        assert result["run_dir"] == str(session.run_dir)
