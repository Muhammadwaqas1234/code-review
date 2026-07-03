"""Chunking: file headers, line-boundary splits, caps, pathological lines."""

from app.core.config import get_settings
from app.services.chunk_service import ChunkService
from app.services.repo_service import SourceFile


def test_small_file_single_chunk_with_header():
    files = [SourceFile("src/a.py", "def f():\n    return 1\n")]
    chunks = ChunkService.chunk_files(files)
    assert len(chunks) == 1
    assert chunks[0].text.startswith("FILE: src/a.py\n")
    assert chunks[0].file_path == "src/a.py"


def test_large_file_split_on_lines_respects_cap():
    cap = get_settings().chunk_max_chars
    body = "x = 1\n" * (cap // 3)  # forces multiple chunks
    chunks = ChunkService.chunk_files([SourceFile("src/big.py", body)])
    assert len(chunks) > 1
    for c in chunks:
        # header adds a small fixed prefix; body content stays within cap
        assert len(c.text) <= cap + len("FILE: src/big.py\n") + 10
        assert c.file_path == "src/big.py"


def test_pathological_long_line_hard_split():
    cap = get_settings().chunk_max_chars
    one_line = "a" * (cap * 3) + "\n"
    chunks = ChunkService.chunk_files([SourceFile("src/x.py", one_line)])
    assert len(chunks) >= 3


def test_global_chunk_cap(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "max_chunks", 3)
    files = [SourceFile(f"f{i}.py", "line\n") for i in range(10)]
    chunks = ChunkService.chunk_files(files)
    assert len(chunks) == 3


def test_empty_input():
    assert ChunkService.chunk_files([]) == []
