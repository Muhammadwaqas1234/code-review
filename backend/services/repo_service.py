import os
import tempfile
from pathlib import Path
from git import Repo
from typing import List, Dict
from backend.config import logger


class RepoService:

    CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".java", ".cpp",
        ".c", ".cs", ".go", ".rb", ".php",
        ".html", ".css"
    }

    @staticmethod
    def clone_repo(repo_url: str) -> str:
        logger.info(f"Cloning repo: {repo_url}")
        repo_dir = tempfile.mkdtemp()
        Repo.clone_from(repo_url, repo_dir)
        return repo_dir

    @staticmethod
    def read_code(repo_dir: str) -> List[Dict]:
        logger.info("Reading repository files...")
        code_files = []

        for root, _, files in os.walk(repo_dir):
            for file in files:
                ext = Path(file).suffix
                if ext in RepoService.CODE_EXTENSIONS:
                    path = os.path.join(root, file)
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            code_files.append({
                                "file": path,
                                "content": f.read()
                            })
                    except Exception as e:
                        logger.warning(f"Error reading {path}: {e}")

        return code_files
