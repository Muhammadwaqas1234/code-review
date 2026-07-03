"""Extract text from the uploaded roles PDF.

The roles PDF describes team roles / review context and is injected into the
reviewer agents' prompts. Failure modes (corrupt file, password-protected,
scanned image with no text layer) raise `PDFError` with a message that is
safe and helpful to show the end user.
"""

from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("services.pdf")


class PDFError(Exception):
    """The PDF could not be read. Messages are safe to show users."""


class PDFService:
    @staticmethod
    def read_roles(file_path: str | Path) -> str:
        """Extract the text of the roles PDF, truncated to the configured cap."""
        settings = get_settings()

        try:
            reader = PdfReader(str(file_path))
        except PdfReadError as exc:
            raise PDFError("The uploaded file is not a valid PDF.") from exc
        except OSError as exc:
            raise PDFError("The uploaded PDF could not be opened.") from exc

        if reader.is_encrypted:
            # Some PDFs are "encrypted" with an empty owner password; try that
            # before giving up.
            try:
                if not reader.decrypt(""):
                    raise PDFError(
                        "The PDF is password-protected. Upload an unprotected copy."
                    )
            except PDFError:
                raise
            except Exception as exc:
                raise PDFError(
                    "The PDF is password-protected. Upload an unprotected copy."
                ) from exc

        pages: list[str] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                extracted = page.extract_text() or ""
            except Exception as exc:  # pypdf can fail on malformed page content
                logger.warning("Could not extract page %d: %s", page_number, exc)
                continue
            if extracted.strip():
                pages.append(extracted.strip())

        text = "\n\n".join(pages).strip()
        if not text:
            raise PDFError(
                "No text could be extracted from the PDF. If it is a scanned "
                "document, upload a text-based PDF instead."
            )

        if len(text) > settings.max_roles_chars:
            logger.info(
                "Roles text truncated from %d to %d characters",
                len(text),
                settings.max_roles_chars,
            )
            text = text[: settings.max_roles_chars]

        logger.info("Extracted roles text (%d characters, %d pages)", len(text), len(pages))
        return text
