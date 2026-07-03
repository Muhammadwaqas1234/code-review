"""POST /api/review — accepts a GitHub repo URL and roles PDF, returns the review.

Endpoint hygiene:
- The upload is streamed to a server-generated temp path; the client's
  filename is never used, so it cannot influence where anything is written.
- A size cap is enforced while streaming, so an oversized upload is rejected
  before it is fully on disk.
- Declared as a sync `def`, so FastAPI runs it in the threadpool and the
  (minutes-long, blocking) review never stalls the event loop.
- User errors (bad URL, private repo, broken PDF) → 4xx with a helpful
  message. Internal errors → 500 with a generic message; details go to the
  server log only.
- `finally` removes both the uploaded PDF and the cloned repository.
"""

import os
import tempfile

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.review import ReviewCategory, ReviewerInfo, ReviewResponse
from app.services.orchestrator_service import (
    OrchestratorError,
    OrchestratorService,
    ReviewUnavailableError,
)
from app.services.pdf_service import PDFError, PDFService
from app.services.repo_service import RepoError, RepoService
from app.services.review_rules import all_rule_sets

logger = get_logger("api.review")

router = APIRouter(prefix="/api", tags=["review"])

_orchestrator = OrchestratorService()

_UPLOAD_CHUNK_BYTES = 1024 * 1024


@router.get(
    "/reviewers",
    response_model=list[ReviewerInfo],
    summary="List the available reviewers and the rules they enforce",
)
def list_reviewers() -> list[ReviewerInfo]:
    """The frontend renders its reviewer picker from this — adding a rule set
    in the backend makes it appear in the UI with no frontend change."""
    return [
        ReviewerInfo(
            id=rs.category,
            name=rs.display_name,
            description=rs.description,
            rules=list(rs.rules),
        )
        for rs in all_rule_sets()
    ]


@router.post(
    "/review",
    response_model=ReviewResponse,
    summary="Run an AI code review on a public repository",
)
def create_review(
    repo_url: str = Form(..., description="Public https repository URL"),
    roles_file: UploadFile | None = File(
        None, description="Optional roles/context PDF"
    ),
    reviewers: str | None = Form(
        None,
        description=(
            "Optional comma-separated reviewer ids (see GET /api/reviewers). "
            "Omit to let the planner choose."
        ),
    ),
) -> ReviewResponse:
    # The roles PDF is optional; validate it only when one was uploaded.
    has_pdf = roles_file is not None and roles_file.filename
    if has_pdf:
        _validate_upload_is_pdf(roles_file)
    selected = _parse_reviewers(reviewers)

    pdf_path: str | None = None
    repo_dir: str | None = None
    try:
        # Validate the URL before doing any expensive work, so an obviously
        # bad URL gets an immediate, specific error.
        RepoService.validate_url(repo_url)

        roles_text = ""
        if has_pdf:
            pdf_path = _save_upload(roles_file)
            roles_text = PDFService.read_roles(pdf_path)

        repo_dir = RepoService.clone(repo_url)
        files = RepoService.read_code(repo_dir)
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No reviewable source files were found in the repository. "
                    "Only code repositories are supported."
                ),
            )

        return _orchestrator.execute(files, roles_text, selected=selected)

    except ReviewUnavailableError as exc:
        # Upstream LLM outage — our fault category, but temporary.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (RepoError, PDFError, OrchestratorError) as exc:
        # Expected, user-correctable failures — message is safe to show.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("Review failed unexpectedly for %s", repo_url)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The review failed due to an internal error. Please try again.",
        )
    finally:
        if pdf_path:
            _remove_quietly(pdf_path)
        RepoService.cleanup(repo_dir)


# ---------------------------------------------------------------------- #
# Input parsing / validation
# ---------------------------------------------------------------------- #
def _parse_reviewers(raw: str | None) -> list[ReviewCategory] | None:
    """Parse the optional comma-separated reviewer selection."""
    if raw is None or not raw.strip():
        return None

    valid = {c.value: c for c in ReviewCategory}
    selected: list[ReviewCategory] = []
    for name in raw.split(","):
        key = name.strip().lower()
        if not key:
            continue
        if key not in valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Unknown reviewer '{name.strip()}'. "
                    f"Valid reviewers: {', '.join(sorted(valid))}."
                ),
            )
        selected.append(valid[key])
    return selected or None



def _validate_upload_is_pdf(upload: UploadFile) -> None:
    filename = (upload.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The roles file must be a PDF (.pdf).",
        )


def _save_upload(upload: UploadFile) -> str:
    """Stream the upload to a server-generated temp path, enforcing the size cap."""
    max_bytes = get_settings().max_upload_bytes
    received = 0

    fd, path = tempfile.mkstemp(prefix="code_review_roles_", suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := upload.file.read(_UPLOAD_CHUNK_BYTES):
                received += len(chunk)
                if received > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"The PDF exceeds the "
                            f"{max_bytes // (1024 * 1024)} MB upload limit."
                        ),
                    )
                out.write(chunk)
    except Exception:
        _remove_quietly(path)
        raise
    return path


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        logger.warning("Could not remove temp file %s", path)
