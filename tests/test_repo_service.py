"""Repository URL validation, file skip rules, and cleanup (no network)."""

import os
from pathlib import Path

import pytest

from app.services.repo_service import InvalidRepoURL, RepoService, SourceFile


@pytest.mark.parametrize(
    "url,normalized",
    [
        ("https://github.com/octocat/Hello-World", "https://github.com/octocat/Hello-World.git"),
        ("  https://www.github.com/octocat/Hello-World/  ", "https://github.com/octocat/Hello-World.git"),
        ("https://github.com/a/b.git", "https://github.com/a/b.git"),
        ("https://gitlab.com/g/p/-/tree/main", "https://gitlab.com/g/p.git"),
        ("https://bitbucket.org/team/repo", "https://bitbucket.org/team/repo.git"),
    ],
)
def test_valid_urls_normalized(url, normalized):
    assert RepoService.validate_url(url) == normalized


@pytest.mark.parametrize(
    "url",
    [
        "",
        "   ",
        "http://github.com/a/b",             # not https
        "ftp://github.com/a/b",
        "https://evil.example.com/a/b",      # unknown host
        "https://user:token@github.com/a/b",  # embedded credentials
        "https://github.com/onlyowner",      # no repo segment
        "https://github.com/",               # nothing
        "not a url at all",
    ],
)
def test_invalid_urls_rejected(url):
    with pytest.raises(InvalidRepoURL):
        RepoService.validate_url(url)


def test_read_code_skips_junk(tmp_path: Path):
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "styles.css").write_text("body{color:red}\n", encoding="utf-8")
    (tmp_path / "app.min.js").write_text("var a=1", encoding="utf-8")       # minified
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")     # lockfile
    (tmp_path / "readme.txt").write_text("hello", encoding="utf-8")         # not code
    (tmp_path / "empty.py").write_text("   \n", encoding="utf-8")           # blank
    node = tmp_path / "node_modules" / "dep"
    node.mkdir(parents=True)
    (node / "index.js").write_text("module.exports={}", encoding="utf-8")   # vendored
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("x", encoding="utf-8")

    files = RepoService.read_code(str(tmp_path))
    paths = {f.path for f in files}
    assert paths == {"app.py", "styles.css"}
    assert all("\\" not in p for p in paths), "paths must be posix-style"


def test_read_code_respects_size_cap(tmp_path: Path, monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_source_file_bytes", 50)
    (tmp_path / "small.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("y = 2\n" * 100, encoding="utf-8")

    files = RepoService.read_code(str(tmp_path))
    assert {f.path for f in files} == {"small.py"}


def test_cleanup_is_safe_on_missing_and_none():
    RepoService.cleanup(None)             # no error
    RepoService.cleanup("/does/not/exist")  # no error


def test_cleanup_removes_directory(tmp_path: Path):
    d = tmp_path / "clone"
    d.mkdir()
    (d / "f.py").write_text("x", encoding="utf-8")
    RepoService.cleanup(str(d))
    assert not d.exists()
