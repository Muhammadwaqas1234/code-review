"""PDF text extraction and error handling."""

from pathlib import Path

import pytest

from app.services.pdf_service import PDFError, PDFService
from tests.conftest import build_pdf


def test_extracts_text(tmp_path: Path):
    p = tmp_path / "roles.pdf"
    p.write_bytes(build_pdf("Senior backend developer. Review security first."))
    text = PDFService.read_roles(p)
    assert "Senior backend developer" in text


def test_invalid_pdf_raises(tmp_path: Path):
    p = tmp_path / "fake.pdf"
    p.write_text("this is not a pdf", encoding="utf-8")
    with pytest.raises(PDFError):
        PDFService.read_roles(p)


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(PDFError):
        PDFService.read_roles(tmp_path / "nope.pdf")


def test_roles_truncated_to_cap(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_roles_chars", 20)
    p = tmp_path / "long.pdf"
    p.write_bytes(build_pdf("A" * 500))
    text = PDFService.read_roles(p)
    assert len(text) <= 20
