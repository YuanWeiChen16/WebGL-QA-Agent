"""Tests for webgl_qa.knowledge_base — YAML loading, task routing, path finding, problems.

Uses the bundled generic example knowledge base at knowledge/example_game/
(illustrative placeholder data — not tied to any real game).
"""

import pytest
from pathlib import Path
from webgl_qa.knowledge_base import KnowledgeBase


KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"


@pytest.fixture
def kb():
    """Load the bundled example knowledge base."""
    return KnowledgeBase("example_game", base_dir=KNOWLEDGE_DIR / "example_game")


class TestKnowledgeBaseLoading:
    """Test YAML loading and structure."""

    def test_systems_loaded(self, kb):
        assert len(kb.systems) >= 4  # gameplay, login, skills, upgrade

    def test_systems_by_id(self, kb):
        assert "upgrade" in kb.systems_by_id
        assert "skills" in kb.systems_by_id
        assert "gameplay" in kb.systems_by_id

    def test_flow_graph_has_edges(self, kb):
        edges = kb.flow_graph.get("edges", [])
        assert len(edges) > 0

    def test_problems_loaded(self, kb):
        assert len(kb.problems) >= 2

    def test_summary(self, kb):
        summary = kb.summary()
        assert "Systems:" in summary
        assert "upgrade" in summary


class TestFindSystemForTask:
    """Test system identification from task text."""

    def test_upgrade_task(self, kb):
        system = kb.find_system_for_task("提升等級至 2")
        assert system is not None
        assert system.get("system_id") == "upgrade"

    def test_skill_task(self, kb):
        system = kb.find_system_for_task("使用技能瞄準目標")
        assert system is not None
        assert system.get("system_id") == "skills"

    def test_gameplay_task(self, kb):
        system = kb.find_system_for_task("射擊目標 10 次")
        assert system is not None
        assert system.get("system_id") == "gameplay"

    def test_unknown_task(self, kb):
        system = kb.find_system_for_task("completely unknown text xyz")
        assert system is None


class TestGetActionForTask:
    """Test task → action routing (data-driven from YAML recognition_keywords + default_action)."""

    def test_upgrade_routes_correctly(self, kb):
        sys_id, action, steps = kb.get_action_for_task("提升等級至 2")
        assert sys_id == "upgrade"
        assert action == "do_upgrade"
        assert len(steps) >= 2  # open panel + click upgrade

    def test_skill_routes_correctly(self, kb):
        sys_id, action, steps = kb.get_action_for_task("使用技能")
        assert sys_id == "skills"
        assert action == "use_skill"

    def test_gameplay_routes_correctly(self, kb):
        sys_id, action, _ = kb.get_action_for_task("射擊目標")
        assert sys_id == "gameplay"
        assert action == "primary_action"

    def test_unknown_returns_none(self, kb):
        sys_id, action, steps = kb.get_action_for_task("xyzzy not a real task")
        assert sys_id is None
        assert action is None
        assert steps == []


class TestGetActionSequence:
    """Test fetching action steps from YAML."""

    def test_upgrade_steps(self, kb):
        steps = kb.get_action_sequence("upgrade", "do_upgrade")
        assert len(steps) >= 2
        assert steps[0]["type"] == "click"
        assert steps[0]["x"] == 100   # illustrative placeholder coords
        assert steps[0]["y"] == 200

    def test_skill_steps(self, kb):
        steps = kb.get_action_sequence("skills", "use_skill")
        assert len(steps) >= 2

    def test_nonexistent_system(self, kb):
        steps = kb.get_action_sequence("nonexistent", "whatever")
        assert steps == []

    def test_nonexistent_action(self, kb):
        steps = kb.get_action_sequence("upgrade", "nonexistent_action")
        assert steps == []


class TestGetPath:
    """Test BFS path finding in flow graph."""

    def test_path_exists(self, kb):
        edges = kb.flow_graph.get("edges", [])
        if len(edges) >= 2:
            first_from = edges[0].get("from")
            for edge in edges[1:]:
                if edge.get("from") != first_from:
                    path = kb.get_path(first_from, edge.get("to"))
                    assert isinstance(path, list)
                    break

    def test_no_path(self, kb):
        path = kb.get_path("nonexistent_start", "nonexistent_end")
        assert path == []


class TestProblems:
    """Test problems loading and find_solution."""

    def test_problems_have_structure(self, kb):
        for problem in kb.problems:
            assert "id" in problem
            assert "title" in problem
            assert "symptoms" in problem
            assert "status" in problem

    def test_browser_crash_problem(self, kb):
        crash_problem = None
        for p in kb.problems:
            if "browser_crash" in p["id"]:
                crash_problem = p
                break
        assert crash_problem is not None
        assert crash_problem["status"] == "resolved"
        assert len(crash_problem["symptoms"]) > 0

    def test_find_solution_targetclosed(self, kb):
        result = kb.find_solution(["TargetClosedError", "browser has been closed"])
        if result:
            assert "crash" in result["id"] or "browser" in result["id"]

    def test_find_solution_network(self, kb):
        result = kb.find_solution(["網路狀況不佳", "重新連線"])
        if result:
            assert "network" in result["id"]

    def test_find_solution_no_match(self, kb):
        result = kb.find_solution(["completely unrelated symptom xyz123"])
        assert result is None

    def test_get_all_problems(self, kb):
        all_problems = kb.get_all_problems()
        assert len(all_problems) >= 2

        resolved = kb.get_all_problems(status="resolved")
        assert all(p["status"] == "resolved" for p in resolved)


class TestKnownIssues:
    """Test per-system known issues."""

    def test_upgrade_has_issues(self, kb):
        issues = kb.get_known_issues("upgrade")
        assert len(issues) >= 1
        assert any("stuck" in i.get("id", "") for i in issues)

    def test_skills_has_issues(self, kb):
        issues = kb.get_known_issues("skills")
        assert len(issues) >= 1

    def test_nonexistent_system_no_issues(self, kb):
        issues = kb.get_known_issues("nonexistent")
        assert issues == []
