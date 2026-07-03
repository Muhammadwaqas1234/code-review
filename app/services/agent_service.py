"""Factories for the agno agents that power the review pipeline.

The LLM provider is selected in `app.core.config` (currently OpenRouter; the
Claude API path is kept commented out in `_model` for an easy switch-back).

Model split:
- Planner runs on the fast model — a cheap routing decision.
- Reviewers, scorer, and reporter run on the smart model, where quality
  matters.

Reviewer instructions are generated from the rule catalog in
`app.services.review_rules` — the single source of truth for what each
reviewer checks. Every structured agent's instructions end with a strict JSON
contract that mirrors the Pydantic schemas in `app.schemas.review`.
"""

from agno.agent import Agent
from agno.models.base import Model

from app.core.config import get_settings
from app.schemas.review import ReviewCategory
from app.services.review_rules import RULE_SETS, ReviewerRuleSet, get_rule_set


def _build_reviewer_instructions(rule_set: ReviewerRuleSet) -> str:
    """Assemble a senior-level reviewer prompt from a rule set.

    The persona, methodology, standards, and severity guidance turn the agent
    from a checklist-runner into an experienced specialist; the numbered rules
    remain the concrete coverage floor.
    """
    parts: list[str] = [rule_set.persona, ""]

    if rule_set.standards:
        parts += [f"THE BAR YOU HOLD CODE TO:\n{rule_set.standards}", ""]

    if rule_set.methodology:
        steps = "\n".join(f"- {m}" for m in rule_set.methodology)
        parts += [f"HOW YOU REVIEW (methodology):\n{steps}", ""]

    parts += [
        "You will receive: (1) optional team-roles context describing who this "
        "review is for (tailor emphasis to it when given), and (2) code "
        "excerpts, each preceded by a FILE: header naming its repository path. "
        "Review ONLY the code you are shown; do not invent issues in code you "
        "cannot see.",
        "",
    ]

    checklist = "\n".join(
        f"{i}. {rule}" for i, rule in enumerate(rule_set.rules, start=1)
    )
    parts += [
        "Systematically check the code against every rule below — these are "
        "your coverage floor, not a ceiling. Report anything a senior "
        f"specialist would flag, even if no rule names it exactly.\n\n"
        f"RULES — {rule_set.display_name}:\n{checklist}",
        "",
    ]

    if rule_set.severity_guidance:
        parts += [f"SEVERITY CALIBRATION:\n{rule_set.severity_guidance}", ""]

    parts.append(_FINDINGS_CONTRACT)
    return "\n".join(parts)


def _model(model_id: str, max_tokens: int) -> Model:
    """Build the LLM for an agent, based on the configured provider.

    Supports OpenAI, OpenRouter, and the Claude API. The API key is injected
    explicitly from app settings (rather than relying on a process environment
    variable) so configuration has a single source of truth in
    `app.core.config`.
    """
    settings = get_settings()
    provider = settings.provider

    if provider == "openai":
        from agno.models.openai import OpenAIChat

        return OpenAIChat(
            id=model_id,
            max_tokens=max_tokens,
            api_key=settings.openai_api_key,
        )

    if provider == "openrouter":
        from agno.models.openrouter import OpenRouter

        return OpenRouter(
            id=model_id,
            max_tokens=max_tokens,
            api_key=settings.openrouter_api_key,
        )

    if provider == "anthropic":
        from agno.models.anthropic import Claude

        return Claude(
            id=model_id,
            max_tokens=max_tokens,
            api_key=settings.anthropic_api_key,
        )

    raise RuntimeError(f"Unknown LLM provider: {provider!r}")


_FINDINGS_CONTRACT = """
Respond with ONLY a JSON object — no markdown fences, no text before or after — in exactly this shape:
{
  "summary": "<2-3 sentence overall assessment>",
  "findings": [
    {
      "severity": "critical" | "high" | "medium" | "low" | "info",
      "file": "<repository-relative path from the FILE: headers, or null>",
      "line": <integer line number, or null if unknown>,
      "issue": "<what is wrong, stated concretely — name the rule it violates>",
      "recommendation": "<how to fix or mitigate it>"
    }
  ]
}
Rules:
- Order findings most severe first.
- Report every issue you find, including ones you are uncertain about or
  consider low-severity — a downstream step filters and ranks them. Coverage
  matters more than restraint here.
- Cite the file path from the FILE: header of the chunk you saw the issue in.
- If the provided code shows no issues in your area, return an empty findings
  list and say so in the summary.
""".strip()


class AgentService:
    """Builds configured agno agents. Agents are stateless and cheap to create."""

    # ------------------------------------------------------------------ #
    @staticmethod
    def planner() -> Agent:
        catalog = "\n".join(
            f"- {rs.category.value}: {rs.description}"
            for rs in RULE_SETS.values()
        )
        return Agent(
            name="PlannerAgent",
            model=_model(get_settings().fast_model, max_tokens=1024),
            instructions=(
                "You decide which code reviewers to run for a repository, based "
                "on a listing of its files. Available reviewers:\n"
                f"{catalog}\n"
                "Choose every reviewer that is plausibly relevant — when in "
                "doubt, include it. Respond with ONLY a JSON object, no fences:\n"
                '{"agents": ["<reviewer>", ...]}'
            ),
        )

    @staticmethod
    def reviewer(category: ReviewCategory) -> Agent:
        rule_set = get_rule_set(category)
        return Agent(
            name=f"{category.value.capitalize()}Reviewer",
            model=_model(get_settings().smart_model, max_tokens=4096),
            instructions=_build_reviewer_instructions(rule_set),
        )

    @staticmethod
    def scorer() -> Agent:
        categories = ", ".join(c.value for c in ReviewCategory)
        return Agent(
            name="ScoringAgent",
            model=_model(get_settings().smart_model, max_tokens=2048),
            instructions=(
                "You aggregate code-review results into scores. You will receive "
                "the JSON output of several reviewer agents.\n"
                "Respond with ONLY a JSON object, no markdown fences:\n"
                "{\n"
                '  "final_score": <number 0-100, 100 = excellent production-ready code>,\n'
                f'  "category_scores": {{"<category>": <number 0-100>, ...}} (categories: {categories}),\n'
                '  "risk_level": "critical" | "high" | "medium" | "low",\n'
                '  "reasoning": "<3-4 sentences justifying the score and risk level>"\n'
                "}\n"
                "Weight critical/high severity findings heavily; do not let many "
                "info-level findings drag down an otherwise sound codebase."
            ),
        )

    @staticmethod
    def reporter() -> Agent:
        return Agent(
            name="ReportAgent",
            model=_model(get_settings().smart_model, max_tokens=8192),
            instructions=(
                "You write the final code-review report for engineering "
                "leadership. You will receive reviewer findings, scores, and "
                "optional team-roles context; tailor emphasis and tone to those "
                "roles when given.\n\n"
                "The detailed, per-file findings are already listed separately "
                "for the reader. Your report is the NARRATIVE that sits above "
                "them — the synthesis, not a re-listing. Do NOT include a table "
                "of individual findings; refer to the most important ones in "
                "prose instead.\n\n"
                "Respond in clean Markdown (no top-level H1) with exactly these "
                "two sections, and keep it tight:\n\n"
                "## Executive Summary\n"
                "3-4 sentences: the overall verdict, the score in context, and "
                "the single most important thing to fix. This is the part a busy "
                "leader reads first — make it count.\n\n"
                "## Risk Assessment\n"
                "2-3 sentences: the risk level and the concrete failure scenario "
                "the worst findings enable (e.g. 'an attacker can log in without "
                "credentials via the login query'). Name the top 2-3 issues in "
                "prose; do not enumerate all findings.\n\n"
                "Do NOT add any other sections — no 'Production Readiness', no "
                "'Recommended Action Plan', no 'Key Findings' table. Only the two "
                "sections above.\n\n"
                "Rules: be specific — cite actual file paths, never generalities. "
                "Use **bold** for verdicts and severity words. Keep the whole "
                "report under 250 words."
            ),
        )
