import subprocess

import pytest

from codex_harness_connect.worktrees import create_worktree


def test_isolated_worktrees_and_invalid_revision(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True)
    git("init", "-b", "main")
    (repo / "source.txt").write_text("original")
    git("add", "source.txt")
    git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "core.hooksPath=/dev/null", "commit", "-m", "fixture")
    first = create_worktree(str(repo), "one")
    second = create_worktree(str(repo), "two")
    from pathlib import Path
    (Path(first["path"]) / "source.txt").write_text("first change")
    assert (Path(second["path"]) / "source.txt").read_text() == "original"
    assert (repo / "source.txt").read_text() == "original"
    with pytest.raises(ValueError):
        create_worktree(str(repo), "../unsafe")
    with pytest.raises(ValueError):
        create_worktree(str(repo), "three", "--help")
    with pytest.raises(FileExistsError):
        create_worktree(str(repo), "one")
