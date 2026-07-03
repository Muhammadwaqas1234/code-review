"""Vector index build/search and relevance (uses the real local embedder)."""

import pytest

from app.services.chunk_service import ChunkService
from app.services.repo_service import SourceFile
from app.services.vector_service import VectorIndexError, VectorService


@pytest.fixture(scope="module")
def indexed():
    files = [
        SourceFile("app/auth.py",
                   "def login(u, p):\n    q = \"SELECT * FROM users WHERE n='\" + u + \"'\"\n    db.execute(q)\n"),
        SourceFile("app/ui.js", "function render(){ el.innerHTML = userInput; }\n"),
        SourceFile("app/math.py", "def add(a, b):\n    return a + b\n"),
        SourceFile("app/loop.py",
                   "for o in orders:\n    r = db.query(f'SELECT t FROM x WHERE id={o.id}')\n"),
    ]
    vs = VectorService()
    vs.build(ChunkService.chunk_files(files))
    return vs


def test_search_before_build_raises():
    with pytest.raises(VectorIndexError):
        VectorService().search("anything")


def test_build_empty_raises():
    with pytest.raises(VectorIndexError):
        VectorService().build([])


def test_security_query_ranks_auth_first(indexed):
    top = [c.file_path for c in indexed.search("sql injection user input password auth", k=2)]
    assert "app/auth.py" in top


def test_performance_query_ranks_loop(indexed):
    top = [c.file_path for c in indexed.search("database query inside loop N+1", k=2)]
    assert "app/loop.py" in top


def test_k_capped_to_index_size(indexed):
    assert len(indexed.search("anything", k=999)) == indexed.size
