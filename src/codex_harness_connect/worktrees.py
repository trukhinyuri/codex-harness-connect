"""Explicit, non-destructive git workspaces for parallel native agents."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def create_worktree(repository: str, name: str, base: str = "HEAD") -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", name):
        raise ValueError("Worktree name must be a short lowercase identifier")
    if not base or base.startswith("-") or "\x00" in base or len(base) > 256:
        raise ValueError("Invalid base revision")
    repo = Path(repository).resolve(strict=True)
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True, timeout=30).stdout.strip()
    root = Path(git("rev-parse", "--show-toplevel"))
    revision = git("rev-parse", "--verify", f"{base}^{{commit}}")
    target = root.parent / f"{root.name}-harness-{name}"
    if target.exists() or target.is_symlink():
        raise FileExistsError("Worktree target already exists")
    branch = f"harness/{name}"
    git("worktree", "add", "-b", branch, str(target), revision)
    return {"path": str(target), "branch": branch, "base_commit": revision,
            "ownership": "User-owned native git worktree; not a Codex managed-worktree attachment"}
