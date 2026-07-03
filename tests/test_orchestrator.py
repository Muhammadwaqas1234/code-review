"""Orchestrator pipeline logic with mocked agents (no live LLM calls).

These tests exercise the parts that are easy to get wrong: planner fallback,
per-reviewer fault isolation, malformed-JSON handling, the all-failed guard,
and the deterministic scoring/reporting fallbacks.
"""

import pytest

from app.schemas.review import AgentReview, ReviewCategory, RiskLevel
from app.services.orchestrator_service import (
    OrchestratorError,
    OrchestratorService,
    ReviewUnavailableError,
)
from app.services.repo_service import SourceFile


class FakeResult:
    def __init__(self, content, status="COMPLETED"):
        self.content = content
        self.status = _FakeStatus(status)


class _FakeStatus:
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return getattr(other, "value", other) == self.value


@pytest.fixture
def files():
    return [
        SourceFile("app/db.py", "q = 'SELECT * FROM t WHERE id=' + uid\ndb.execute(q)\n"),
        SourceFile("app/util.py", "def add(a, b):\n    return a + b\n"),
    ]


def _patch_agents(monkeypatch, *, planner, reviewer, scorer, reporter):
    """Replace AgentService factories with fakes whose .run() returns canned output."""
    import app.services.orchestrator_service as orch

    class FakeAgent:
        def __init__(self, name, responder):
            self.name = name
            self._responder = responder

        def run(self, prompt):
            return self._responder(prompt)

    monkeypatch.setattr(orch.AgentService, "planner",
                        staticmethod(lambda: FakeAgent("planner", planner)))
    monkeypatch.setattr(orch.AgentService, "reviewer",
                        staticmethod(lambda cat: FakeAgent(f"{cat.value}-reviewer",
                                                           lambda p: reviewer(cat, p))))
    monkeypatch.setattr(orch.AgentService, "scorer",
                        staticmethod(lambda: FakeAgent("scorer", scorer)))
    monkeypatch.setattr(orch.AgentService, "reporter",
                        staticmethod(lambda: FakeAgent("reporter", reporter)))


def test_happy_path_all_parsed(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult('{"agents": ["security", "bugs"]}'),
        reviewer=lambda cat, p: FakeResult(
            '{"summary": "found stuff", "findings": [{"severity": "high", '
            '"file": "app/db.py", "issue": "SQL injection", '
            '"recommendation": "parameterize"}]}'),
        scorer=lambda p: FakeResult(
            '{"final_score": 45, "category_scores": {"security": 30}, '
            '"risk_level": "high", "reasoning": "injection present"}'),
        reporter=lambda p: FakeResult("## Executive Summary\nBad."),
    )
    result = OrchestratorService().execute(files, "roles")
    assert {r.agent for r in result.reviews} == {ReviewCategory.SECURITY, ReviewCategory.BUGS}
    assert result.score.final_score == 45.0
    assert result.score.risk_level is RiskLevel.HIGH
    assert all(not r.parse_failed for r in result.reviews)
    assert result.stats.files_reviewed == 2


def test_planner_garbage_falls_back_to_all(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult("total nonsense, no json"),
        reviewer=lambda cat, p: FakeResult('{"summary": "ok", "findings": []}'),
        scorer=lambda p: FakeResult('{"final_score": 90, "risk_level": "low", "reasoning": "clean"}'),
        reporter=lambda p: FakeResult("## Executive Summary\nGood."),
    )
    result = OrchestratorService().execute(files, "")
    assert {r.agent for r in result.reviews} == set(ReviewCategory)


def test_malformed_reviewer_json_becomes_raw(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult('{"agents": ["style"]}'),
        reviewer=lambda cat, p: FakeResult("I could not produce JSON, sorry."),
        scorer=lambda p: FakeResult('{"final_score": 70, "risk_level": "medium", "reasoning": "x"}'),
        reporter=lambda p: FakeResult("## Executive Summary\nMixed."),
    )
    result = OrchestratorService().execute(files, "")
    style = next(r for r in result.reviews if r.agent is ReviewCategory.STYLE)
    assert style.parse_failed and style.raw


def test_all_reviewers_error_raises_unavailable(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult('{"agents": ["style", "bugs"]}'),
        reviewer=lambda cat, p: FakeResult("boom", status="ERROR"),
        scorer=lambda p: FakeResult('{"final_score": 100, "risk_level": "low", "reasoning": "x"}'),
        reporter=lambda p: FakeResult("## report"),
    )
    with pytest.raises(ReviewUnavailableError):
        OrchestratorService().execute(files, "")


def test_scorer_failure_uses_deterministic_fallback(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult('{"agents": ["security"]}'),
        reviewer=lambda cat, p: FakeResult(
            '{"summary": "s", "findings": ['
            '{"severity": "critical", "issue": "a"},'
            '{"severity": "critical", "issue": "b"}]}'),
        scorer=lambda p: FakeResult("no json", status="ERROR"),
        reporter=lambda p: FakeResult("## Executive Summary\nx"),
    )
    result = OrchestratorService().execute(files, "")
    # two criticals => 100 - 2*25 = 50 => high risk
    assert result.score.final_score == 50.0
    assert result.score.risk_level is RiskLevel.HIGH
    assert "fallback" in result.score.reasoning.lower()


def test_reporter_failure_uses_fallback_report(monkeypatch, files):
    _patch_agents(
        monkeypatch,
        planner=lambda p: FakeResult('{"agents": ["bugs"]}'),
        reviewer=lambda cat, p: FakeResult(
            '{"summary": "s", "findings": [{"severity": "low", "issue": "minor", "file": "app/util.py"}]}'),
        scorer=lambda p: FakeResult('{"final_score": 80, "risk_level": "low", "reasoning": "ok"}'),
        reporter=lambda p: FakeResult("", status="ERROR"),
    )
    result = OrchestratorService().execute(files, "")
    assert "## Executive Summary" in result.report
    assert "## Risk Assessment" in result.report


def test_selected_reviewers_override_planner(monkeypatch, files):
    called = {"planner": False}

    def planner(p):
        called["planner"] = True
        return FakeResult('{"agents": ["style"]}')

    _patch_agents(
        monkeypatch,
        planner=planner,
        reviewer=lambda cat, p: FakeResult('{"summary": "ok", "findings": []}'),
        scorer=lambda p: FakeResult('{"final_score": 90, "risk_level": "low", "reasoning": "x"}'),
        reporter=lambda p: FakeResult("## Executive Summary\nx"),
    )
    result = OrchestratorService().execute(
        files, "", selected=[ReviewCategory.SECURITY, ReviewCategory.PERFORMANCE])
    assert {r.agent for r in result.reviews} == {ReviewCategory.SECURITY, ReviewCategory.PERFORMANCE}
    assert called["planner"] is False, "planner must be skipped when reviewers are selected"


def test_no_files_raises():
    with pytest.raises(OrchestratorError):
        OrchestratorService().execute([], "")
