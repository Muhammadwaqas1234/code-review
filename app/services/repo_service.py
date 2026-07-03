"""Clone GitHub/GitLab/Bitbucket repositories safely and read their source files.

Security and robustness notes:
- Only https URLs on an allowlist of known git hosts are accepted, and URLs
  carrying credentials (``https://user:token@...``) are rejected outright.
- Clones are shallow (``depth=1``, single branch) — we only need a snapshot.
- ``GIT_TERMINAL_PROMPT=0`` prevents git from hanging on a password prompt
  when someone submits a private repository URL.
- ``cleanup()`` handles Windows: git's object files are read-only, which makes
  a plain ``shutil.rmtree`` fail, so we clear the read-only bit and retry.
"""

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from git import GitCommandError, Repo

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("services.repo")


class RepoError(Exception):
    """Base error for repository operations. Messages are safe to show users."""


class InvalidRepoURL(RepoError):
    """The submitted URL is not an acceptable repository URL."""


class CloneError(RepoError):
    """The repository could not be cloned."""


@dataclass(frozen=True)
class SourceFile:
    """One source file read from the repository."""

    path: str  # repository-relative, posix-style (e.g. "src/app/main.py")
    content: str


class RepoService:
    ALLOWED_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})

    CODE_EXTENSIONS = frozenset({
        ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".cpp", ".cc",
        ".c", ".h", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift",
        ".scala", ".sql", ".sh", ".ps1", ".html", ".css", ".scss", ".vue",
        ".yaml", ".yml", ".toml",
    })

    SKIP_DIRS = frozenset({
        ".git", ".github", ".idea", ".vscode", "node_modules", "vendor",
        "venv", ".venv", "env", ".env", "__pycache__", ".pytest_cache",
        ".mypy_cache", "dist", "build", "out", "target", "coverage",
        ".next", ".nuxt",
    })

    SKIP_FILE_SUFFIXES = (".min.js", ".min.css", ".map", ".lock")
    SKIP_FILE_NAMES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml"})

    # ------------------------------------------------------------------ #
    # URL validation
    # ------------------------------------------------------------------ #
    @classmethod
    def validate_url(cls, repo_url: str) -> str:
        """Validate and normalize a repository URL.

        Returns the normalized https URL, or raises `InvalidRepoURL` with a
        message safe to show the end user.
        """
        candidate = (repo_url or "").strip()
        if not candidate:
            raise InvalidRepoURL("Repository URL is required.")

        parsed = urlparse(candidate)
        if parsed.scheme != "https":
            raise InvalidRepoURL("Only https:// repository URLs are supported.")
        if parsed.username or parsed.password:
            raise InvalidRepoURL("Repository URLs must not contain credentials.")

        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host not in cls.ALLOWED_HOSTS:
            allowed = ", ".join(sorted(cls.ALLOWED_HOSTS))
            raise InvalidRepoURL(f"Unsupported git host. Supported hosts: {allowed}.")

        # Expect at least /owner/repo
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise InvalidRepoURL(
                "URL must point to a repository, e.g. https://github.com/owner/repo."
            )

        owner, repo = parts[0], parts[1].removesuffix(".git")
        return f"https://{host}/{owner}/{repo}.git"

    # ------------------------------------------------------------------ #
    # Clone / cleanup
    # ------------------------------------------------------------------ #
    @classmethod
    def clone(cls, repo_url: str) -> str:
        """Shallow-clone the repository into a temp directory and return its path.

        The caller is responsible for calling `cleanup()` on the returned path.
        """
        url = cls.validate_url(repo_url)
        repo_dir = tempfile.mkdtemp(prefix="code_review_repo_")
        logger.info("Cloning %s (shallow)", url)
        try:
            Repo.clone_from(
                url,
                repo_dir,
                depth=1,
                single_branch=True,
                no_tags=True,
                env={"GIT_TERMINAL_PROMPT": "0"},  # never hang on auth prompts
            )
        except GitCommandError as exc:
            cls.cleanup(repo_dir)
            logger.warning("Clone failed for %s: %s", url, exc)
            raise CloneError(
                "Could not clone the repository. Check that the URL is correct "
                "and the repository is public."
            ) from exc
        return repo_dir

    @staticmethod
    def cleanup(repo_dir: str | None) -> None:
        """Delete a cloned repository, tolerating Windows read-only git objects."""
        if not repo_dir or not os.path.isdir(repo_dir):
            return

        def _clear_readonly_and_retry(func, path, _exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        try:
            shutil.rmtree(repo_dir, onerror=_clear_readonly_and_retry)
        except OSError:
            # Never let cleanup break a request; leftover temp dirs are logged.
            logger.warning("Could not fully remove temp clone %s", repo_dir)

    # ------------------------------------------------------------------ #
    # Reading source files
    # ------------------------------------------------------------------ #
    @classmethod
    def read_code(cls, repo_dir: str) -> list[SourceFile]:
        """Read reviewable source files from a cloned repository.

        Applies skip rules (vendored/generated dirs, minified files, size cap)
        and returns files with repository-relative posix paths.
        """
        settings = get_settings()
        root = Path(repo_dir)
        files: list[SourceFile] = []
        skipped = 0

        for dirpath, dirnames, filenames in os.walk(repo_dir):
            # Prune skipped directories in place so os.walk never descends.
            dirnames[:] = [
                d for d in dirnames
                if d not in cls.SKIP_DIRS and not d.startswith(".")
            ]

            for name in sorted(filenames):
                if len(files) >= settings.max_repo_files:
                    logger.warning(
                        "File cap reached (%d); remaining files skipped",
                        settings.max_repo_files,
                    )
                    return files

                if not cls._is_reviewable(name):
                    continue

                full_path = Path(dirpath) / name
                try:
                    if full_path.stat().st_size > settings.max_source_file_bytes:
                        skipped += 1
                        continue
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    logger.warning("Could not read %s: %s", full_path, exc)
                    continue

                if not content.strip():
                    continue

                rel_path = str(PurePosixPath(full_path.relative_to(root).as_posix()))
                files.append(SourceFile(path=rel_path, content=content))

        logger.info(
            "Read %d source files (%d skipped as oversized)", len(files), skipped
        )
        return files

    @classmethod
    def _is_reviewable(cls, filename: str) -> bool:
        lower = filename.lower()
        if lower in cls.SKIP_FILE_NAMES:
            return False
        if lower.endswith(cls.SKIP_FILE_SUFFIXES):
            return False
        return Path(lower).suffix in cls.CODE_EXTENSIONS
