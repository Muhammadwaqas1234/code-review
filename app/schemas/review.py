"""API contract for the review pipeline.

These models are the single source of truth for the shape of a review:
agent outputs are parsed into them, the orchestrator returns them, and the
`POST /review` endpoint declares `ReviewResponse` as its response model, so
the OpenAPI docs and the frontend both rely on exactly this structure.

Values produced by LLMs are normalized on the way in (case-insensitive
enums, clamped scores) so one loosely-formatted model response degrades
gracefully instead of failing the whole review.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewCategory(str, Enum):
    """The reviewer agents the pipeline can run."""

    STYLE = "style"
    BUGS = "bugs"
    SECURITY = "security"
    ARCHITECTURE = "architecture"
    PERFORMANCE = "performance"


class Severity(str, Enum):
    """Severity of a single finding, highest first."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class RiskLevel(str, Enum):
    """Overall risk assessment for the repository."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


def _normalize_enum(value: object) -> object:
    """Lowercase string enum inputs so LLM output like "High" still parses."""
    if isinstance(value, str):
        return value.strip().lower()
    return value


class Finding(BaseModel):
    """One concrete issue reported by a reviewer agent."""

    severity: Severity = Field(
        default=Severity.INFO,
        description="Impact of the issue, from 'critical' down to 'info'.",
    )
    file: Optional[str] = Field(
        default=None,
        description="Repository-relative path the finding refers to, if known.",
    )
    line: Optional[int] = Field(
        default=None,
        ge=1,
        description="1-based line number within the file, if known.",
    )
    issue: str = Field(
        min_length=1,
        description="What is wrong, stated concretely.",
    )
    recommendation: Optional[str] = Field(
        default=None,
        description="How to fix or mitigate the issue.",
    )

    _normalize_severity = field_validator("severity", mode="before")(_normalize_enum)


class AgentReview(BaseModel):
    """The full output of one reviewer agent."""

    agent: ReviewCategory = Field(description="Which reviewer produced this.")
    summary: str = Field(
        default="",
        description="Short overall assessment from this reviewer.",
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="Individual issues, ordered most severe first.",
    )
    raw: Optional[str] = Field(
        default=None,
        description=(
            "Unparsed agent output. Populated only when the agent's response "
            "could not be parsed into structured findings."
        ),
    )

    _normalize_agent = field_validator("agent", mode="before")(_normalize_enum)

    @property
    def parse_failed(self) -> bool:
        return self.raw is not None


class Score(BaseModel):
    """Aggregate scoring produced from all agent reviews."""

    final_score: float = Field(
        ge=0,
        le=100,
        description="Overall repository quality score, 0 (worst) to 100 (best).",
    )
    category_scores: dict[ReviewCategory, float] = Field(
        default_factory=dict,
        description="Per-category scores on the same 0-100 scale.",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.UNKNOWN,
        description="Overall production-risk assessment.",
    )
    reasoning: str = Field(
        default="",
        description="Brief justification for the score and risk level.",
    )

    _normalize_risk = field_validator("risk_level", mode="before")(_normalize_enum)

    @field_validator("final_score", "category_scores", mode="before")
    @classmethod
    def _clamp_scores(cls, value: object) -> object:
        """Clamp model-produced scores into [0, 100] instead of erroring."""

        def clamp(v: object) -> object:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return min(100.0, max(0.0, float(v)))
            return v

        if isinstance(value, dict):
            return {k: clamp(v) for k, v in value.items()}
        return clamp(value)


class ReviewStats(BaseModel):
    """Operational metadata about a completed review run."""

    files_reviewed: int = Field(ge=0)
    chunks_indexed: int = Field(ge=0)
    agents_run: list[ReviewCategory] = Field(default_factory=list)
    elapsed_seconds: float = Field(ge=0)


class ReviewerInfo(BaseModel):
    """Public description of one available reviewer (drives the frontend)."""

    id: ReviewCategory
    name: str = Field(description="Human-readable reviewer name.")
    description: str = Field(description="One-line summary of what it checks.")
    rules: list[str] = Field(description="The concrete rules this reviewer enforces.")


class ReviewResponse(BaseModel):
    """Top-level result returned by `POST /review`."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "score": {
                    "final_score": 62.5,
                    "category_scores": {"security": 40, "style": 75},
                    "risk_level": "high",
                    "reasoning": "Solid structure, but unauthenticated endpoints.",
                },
                "reviews": [
                    {
                        "agent": "security",
                        "summary": "Two injection risks found.",
                        "findings": [
                            {
                                "severity": "critical",
                                "file": "app/db.py",
                                "line": 42,
                                "issue": "SQL built by string concatenation.",
                                "recommendation": "Use parameterized queries.",
                            }
                        ],
                    }
                ],
                "report": "## Executive Summary\n...",
                "stats": {
                    "files_reviewed": 12,
                    "chunks_indexed": 48,
                    "agents_run": ["security", "style"],
                    "elapsed_seconds": 41.3,
                },
            }
        }
    )

    score: Score
    reviews: list[AgentReview] = Field(
        description="One entry per reviewer agent that ran."
    )
    report: str = Field(
        description="Human-readable report in Markdown "
        "(executive summary, risk assessment, recommendations)."
    )
    stats: ReviewStats
