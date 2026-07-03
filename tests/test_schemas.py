"""Schema validation and LLM-output normalization."""

import pytest
from pydantic import ValidationError

from app.schemas.review import (
    AgentReview,
    Finding,
    ReviewCategory,
    ReviewResponse,
    ReviewStats,
    RiskLevel,
    Score,
    Severity,
)


@pytest.mark.parametrize(
    "raw,expected",
    [("Critical", Severity.CRITICAL), ("  HIGH ", Severity.HIGH), ("info", Severity.INFO)],
)
def test_severity_normalized_from_messy_llm_output(raw, expected):
    assert Finding(severity=raw, issue="x").severity is expected


def test_score_clamped_into_range():
    s = Score(final_score=120, risk_level="High", category_scores={"security": -5, "style": 88})
    assert s.final_score == 100.0
    assert s.category_scores[ReviewCategory.SECURITY] == 0.0
    assert s.category_scores[ReviewCategory.STYLE] == 88.0
    assert s.risk_level is RiskLevel.HIGH


def test_empty_issue_rejected():
    with pytest.raises(ValidationError):
        Finding(severity="low", issue="")


def test_unknown_agent_rejected():
    with pytest.raises(ValidationError):
        AgentReview(agent="not-a-real-agent")


def test_unknown_severity_rejected():
    with pytest.raises(ValidationError):
        Finding(severity="super-bad", issue="x")


def test_line_must_be_positive():
    with pytest.raises(ValidationError):
        Finding(severity="low", issue="x", line=0)


def test_negative_stats_rejected():
    with pytest.raises(ValidationError):
        ReviewStats(files_reviewed=-1, chunks_indexed=0, agents_run=[], elapsed_seconds=0)


def test_parse_failed_flag():
    ok = AgentReview(agent="bugs", summary="fine", findings=[Finding(severity="low", issue="x")])
    broken = AgentReview(agent="bugs", raw="not json")
    assert not ok.parse_failed
    assert broken.parse_failed and broken.findings == []


def test_full_response_json_round_trip():
    resp = ReviewResponse(
        score=Score(final_score=62.5, risk_level="high"),
        reviews=[AgentReview(agent="Security", findings=[Finding(severity="critical", issue="SQLi", file="db.py")])],
        report="## Report",
        stats=ReviewStats(files_reviewed=3, chunks_indexed=9, agents_run=["security"], elapsed_seconds=12.5),
    )
    restored = ReviewResponse.model_validate_json(resp.model_dump_json())
    assert restored == resp
    assert restored.reviews[0].agent is ReviewCategory.SECURITY
