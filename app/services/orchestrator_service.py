"""The review pipeline: chunk → index → plan → review (parallel, RAG) → score → report.

Design principles:
- Every LLM interaction is fault-isolated: one reviewer failing or returning
  malformed JSON degrades that one review, never the whole request.
- The planner's output is validated against the known reviewer categories;
  anything unparseable or empty falls back to running all reviewers.
- Each reviewer gets its *own* retrieval: the security agent sees the chunks
  most similar to auth/input-handling code, the performance agent sees loops
  and query code, and so on. This is what makes the FAISS index load-bearing.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.run.base import RunStatus
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.review import (
    AgentReview,
    ReviewCategory,
    ReviewResponse,
    ReviewStats,
    RiskLevel,
    Score,
)
from app.services.agent_service import AgentService
from app.services.chunk_service import ChunkService
from app.services.repo_service import SourceFile
from app.services.review_rules import get_rule_set
from app.services.vector_service import VectorService
from app.utils.json_utils import extract_json

logger = get_logger("services.orchestrator")


class OrchestratorError(Exception):
    """The review could not be performed. Messages are safe to show users."""


class ReviewUnavailableError(OrchestratorError):
    """No reviewer agent could run at all (e.g. LLM provider outage)."""


_REVIEWER_FAILED_SUMMARY = (
    "This reviewer failed to complete due to an internal error."
)
_REVIEWER_TIMEOUT_SUMMARY = "This reviewer did not complete in time."


def _is_rate_limit(obj: object) -> bool:
    """Heuristically detect a rate-limit (429) signal in an error or message."""
    text = str(obj).lower()
    return "429" in text or "rate-limit" in text or "rate limit" in text


def _sleep_backoff(attempt: int, settings, obj: object) -> None:
    """Sleep before a retry, honoring `retry_after_seconds` when present."""
    import re

    match = re.search(r"retry_after_seconds['\"]?[:=]\s*([0-9.]+)", str(obj))
    if match:
        delay = min(float(match.group(1)) + 1, settings.agent_retry_max_seconds)
    else:
        delay = min(
            settings.agent_retry_base_seconds * (2 ** attempt),
            settings.agent_retry_max_seconds,
        )
    logger.info("Rate limited; retrying in %.0fs (attempt %d)", delay, attempt + 1)
    time.sleep(delay)


class OrchestratorService:
    """Runs one full review. Stateless — safe to share across requests."""

    def execute(
        self,
        files: list[SourceFile],
        roles_text: str = "",
        selected: list[ReviewCategory] | None = None,
    ) -> ReviewResponse:
        """Run a full review.

        `selected` overrides the planner: when the caller (e.g. a user picking
        reviewers in the UI) names categories explicitly, exactly those run.
        """
        if not files:
            raise OrchestratorError(
                "The repository contains no reviewable source files."
            )

        started = time.perf_counter()

        # 1. Chunk and index the repository (RAG foundation).
        chunks = ChunkService.chunk_files(files)
        vector = VectorService()
        vector.build(chunks)

        # 2. Reviewers: explicit user selection wins; otherwise ask the planner.
        if selected:
            categories = list(dict.fromkeys(selected))
            logger.info(
                "User selected reviewers: %s", [c.value for c in categories]
            )
        else:
            categories = self._plan(files)

        # 3. Reviewers run in parallel, each on its own retrieved context.
        reviews = self._run_reviewers(categories, vector, roles_text)

        # If not a single reviewer produced output, scoring would fabricate a
        # perfect score from an empty review — refuse instead.
        if all(self._reviewer_failed(r) for r in reviews):
            raise ReviewUnavailableError(
                "The AI reviewers are currently unavailable, so no review "
                "could be produced. Please try again later."
            )

        # 4. Score and report.
        score = self._score(reviews)
        report = self._report(reviews, score, roles_text)

        elapsed = time.perf_counter() - started
        logger.info(
            "Review complete: %d files, %d chunks, %d agents, %.1fs",
            len(files), len(chunks), len(reviews), elapsed,
        )
        return ReviewResponse(
            score=score,
            reviews=reviews,
            report=report,
            stats=ReviewStats(
                files_reviewed=len(files),
                chunks_indexed=len(chunks),
                agents_run=[r.agent for r in reviews],
                elapsed_seconds=round(elapsed, 1),
            ),
        )

    @staticmethod
    def _run_agent(agent: Agent, prompt: str) -> str | None:
        """Run an agno agent, retrying transient rate limits, and raise on failure.

        agno does not raise on LLM provider errors — it returns the error text
        as content with `status = ERROR`. We check the status and turn a
        non-completed run into an exception so callers' failure paths stay
        honest. Rate-limit (429) responses are retried with backoff, which
        matters on free model tiers that throttle bursts of parallel calls.
        """
        settings = get_settings()
        last_exc: Exception | None = None

        for attempt in range(settings.agent_max_retries + 1):
            try:
                result = agent.run(prompt)
            except ModelProviderError as exc:
                # agno may raise this for provider errors (incl. 429).
                if not _is_rate_limit(exc) or attempt == settings.agent_max_retries:
                    raise
                last_exc = exc
                _sleep_backoff(attempt, settings, exc)
                continue

            status = getattr(result, "status", None)
            if status is None or status == RunStatus.completed:
                return result.content

            # Non-completed run: retry if it looks like a rate limit.
            content = result.content or ""
            if _is_rate_limit(content) and attempt < settings.agent_max_retries:
                _sleep_backoff(attempt, settings, content)
                continue
            raise RuntimeError(
                f"{agent.name} run ended with status {status}: {content[:200]}"
            )

        # Exhausted retries on a raised rate-limit error.
        raise last_exc if last_exc else RuntimeError(f"{agent.name} run failed")

    @staticmethod
    def _reviewer_failed(review: AgentReview) -> bool:
        """True when a reviewer produced nothing usable at all."""
        return (
            not review.findings
            and review.raw is None
            and review.summary in (
                _REVIEWER_FAILED_SUMMARY, _REVIEWER_TIMEOUT_SUMMARY
            )
        )

    # ------------------------------------------------------------------ #
    # Planning
    # ------------------------------------------------------------------ #
    def _plan(self, files: list[SourceFile]) -> list[ReviewCategory]:
        """Ask the planner which reviewers to run; fall back to all of them."""
        all_categories = list(ReviewCategory)
        listing = "\n".join(f.path for f in files[:200])

        try:
            raw = self._run_agent(
                AgentService.planner(),
                f"Repository files:\n{listing}\n\nWhich reviewers should run?",
            )
        except Exception:
            logger.exception("Planner call failed; running all reviewers")
            return all_categories

        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("Planner output unparseable; running all reviewers")
            return all_categories

        valid = {c.value: c for c in ReviewCategory}
        chosen = [
            valid[name.strip().lower()]
            for name in parsed.get("agents", [])
            if isinstance(name, str) and name.strip().lower() in valid
        ]
        chosen = list(dict.fromkeys(chosen))  # dedupe, keep order

        if not chosen:
            logger.warning("Planner chose no valid reviewers; running all")
            return all_categories

        logger.info("Planner selected: %s", [c.value for c in chosen])
        return chosen

    # ------------------------------------------------------------------ #
    # Reviewing
    # ------------------------------------------------------------------ #
    def _run_reviewers(
        self,
        categories: list[ReviewCategory],
        vector: VectorService,
        roles_text: str,
    ) -> list[AgentReview]:
        settings = get_settings()
        reviews: dict[ReviewCategory, AgentReview] = {}

        pool = ThreadPoolExecutor(max_workers=settings.agent_max_workers)
        futures = {
            pool.submit(self._run_one_reviewer, cat, vector, roles_text): cat
            for cat in categories
        }
        try:
            for future in as_completed(
                futures, timeout=settings.agent_timeout_seconds
            ):
                reviews[futures[future]] = future.result()
        except TimeoutError:
            unfinished = [futures[f] for f in futures if not f.done()]
            logger.error(
                "Reviewer timeout after %ds; unfinished: %s",
                settings.agent_timeout_seconds,
                [c.value for c in unfinished],
            )
        finally:
            # Don't let __exit__ block on the timed-out futures — cancel what
            # hasn't started and return without waiting for the rest.
            pool.shutdown(wait=False, cancel_futures=True)

        # Preserve requested order; mark anything that never finished.
        return [
            reviews.get(cat)
            or AgentReview(agent=cat, summary=_REVIEWER_TIMEOUT_SUMMARY)
            for cat in categories
        ]

    def _run_one_reviewer(
        self,
        category: ReviewCategory,
        vector: VectorService,
        roles_text: str,
    ) -> AgentReview:
        rule_set = get_rule_set(category)
        try:
            relevant = vector.search(rule_set.retrieval_query)
            prompt = self._build_review_prompt(roles_text, relevant)
            raw = self._run_agent(AgentService.reviewer(category), prompt)
        except Exception:
            logger.exception("%s reviewer failed", category.value)
            return AgentReview(agent=category, summary=_REVIEWER_FAILED_SUMMARY)
        return self._parse_review(category, raw)

    @staticmethod
    def _build_review_prompt(roles_text: str, chunks) -> str:
        roles = roles_text.strip() or "None provided."
        excerpts = "\n\n---\n\n".join(c.text for c in chunks)
        return (
            f"Team roles / review context:\n{roles}\n\n"
            f"Code excerpts to review:\n\n{excerpts}"
        )

    @staticmethod
    def _parse_review(category: ReviewCategory, raw: str | None) -> AgentReview:
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            try:
                return AgentReview.model_validate({
                    "agent": category.value,
                    "summary": str(parsed.get("summary", "")),
                    "findings": parsed.get("findings") or [],
                })
            except ValidationError as exc:
                logger.warning(
                    "%s reviewer JSON failed schema validation: %s",
                    category.value, exc,
                )
        logger.warning("%s reviewer output kept as raw text", category.value)
        return AgentReview(
            agent=category,
            summary="This reviewer's output could not be fully parsed.",
            raw=(raw or "").strip() or None,
        )

    # ------------------------------------------------------------------ #
    # Scoring
    # ------------------------------------------------------------------ #
    def _score(self, reviews: list[AgentReview]) -> Score:
        reviews_json = json.dumps(
            [r.model_dump(mode="json", exclude={"raw"}) for r in reviews],
            indent=2,
        )
        try:
            raw = self._run_agent(
                AgentService.scorer(), f"Reviewer results:\n{reviews_json}"
            )
        except Exception:
            logger.exception("Scorer call failed")
            return self._fallback_score(reviews)

        parsed = extract_json(raw)
        if not isinstance(parsed, dict):
            logger.warning("Scorer output unparseable; using fallback score")
            return self._fallback_score(reviews)

        valid = {c.value for c in ReviewCategory}
        raw_categories = parsed.get("category_scores")
        category_scores = {
            k: v for k, v in (raw_categories or {}).items()
            if isinstance(k, str) and k.strip().lower() in valid
        } if isinstance(raw_categories, dict) else {}

        try:
            return Score.model_validate({
                "final_score": parsed.get("final_score", 0),
                "category_scores": category_scores,
                "risk_level": parsed.get("risk_level", "unknown"),
                "reasoning": str(parsed.get("reasoning", "")),
            })
        except ValidationError:
            logger.warning("Scorer JSON failed schema validation; using fallback")
            return self._fallback_score(reviews)

    @staticmethod
    def _fallback_score(reviews: list[AgentReview]) -> Score:
        """Deterministic score when the scoring agent is unavailable."""
        weights = {"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0}
        penalty = sum(
            weights.get(f.severity.value, 0)
            for r in reviews for f in r.findings
        )
        final = max(0.0, 100.0 - penalty)
        risk = (
            RiskLevel.CRITICAL if final < 30
            else RiskLevel.HIGH if final < 55
            else RiskLevel.MEDIUM if final < 80
            else RiskLevel.LOW
        )
        return Score(
            final_score=final,
            risk_level=risk,
            reasoning=(
                "Automatic fallback score derived from finding severities "
                "(the scoring agent was unavailable)."
            ),
        )

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def _report(
        self, reviews: list[AgentReview], score: Score, roles_text: str
    ) -> str:
        payload = {
            "score": score.model_dump(mode="json"),
            "reviews": [r.model_dump(mode="json", exclude={"raw"}) for r in reviews],
        }
        roles = roles_text.strip() or "None provided."
        try:
            report = self._run_agent(
                AgentService.reporter(),
                f"Team roles / review context:\n{roles}\n\n"
                f"Review results:\n{json.dumps(payload, indent=2)}",
            )
            if report and report.strip():
                return report.strip()
        except Exception:
            logger.exception("Reporter call failed; using fallback report")

        return self._fallback_report(reviews, score)

    @staticmethod
    def _fallback_report(reviews: list[AgentReview], score: Score) -> str:
        """Minimal deterministic report when the reporter agent is unavailable.

        Kept short and non-duplicative — the per-file findings are shown
        separately, so this is just the narrative summary.
        """
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for review in reviews:
            for f in review.findings:
                counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
        serious = counts["critical"] + counts["high"]

        breakdown = ", ".join(
            f"{n} {sev}" for sev, n in counts.items() if n
        ) or "no findings"

        verdict = (
            "Resolve the critical and high-severity findings before deployment."
            if serious
            else "Address the findings above to improve quality."
        )
        lines = [
            "## Executive Summary",
            f"Automated review scored the codebase **{score.final_score:.0f}/100** "
            f"(risk: **{score.risk_level.value}**), with {breakdown}. {verdict} "
            "See the findings above for the specifics.",
            "",
            "## Risk Assessment",
            f"Overall risk is **{score.risk_level.value}**. "
            + (
                "There are critical or high-severity findings that should be "
                "addressed first."
                if serious
                else "No critical or high-severity findings were reported."
            ),
        ]
        return "\n".join(lines).strip()
