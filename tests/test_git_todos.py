"""Tests for tasks/sources/git_todos.py — TODO comment scanning."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wise_magpie.tasks.sources.git_todos import _TODO_RE, scan


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), capture_output=True, check=True)


def _commit(repo: Path, msg: str = "update") -> None:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", msg)


class TestTodoRegex:
    def test_hash_todo(self):
        assert _TODO_RE.search("# TODO: fix this")

    def test_slash_todo(self):
        assert _TODO_RE.search("// TODO: refactor")

    def test_fixme(self):
        m = _TODO_RE.search("# FIXME: broken")
        assert m and m.group(1).upper() == "FIXME"

    def test_hack(self):
        m = _TODO_RE.search("// HACK: workaround")
        assert m and m.group(1).upper() == "HACK"

    def test_xxx(self):
        m = _TODO_RE.search("# XXX: needs attention")
        assert m and m.group(1).upper() == "XXX"

    def test_case_insensitive(self):
        assert _TODO_RE.search("# todo: lowercase")

    def test_no_match_plain_text(self):
        assert _TODO_RE.search("this is a regular line") is None


class TestScan:
    def test_empty_repo(self, git_repo: Path):
        tasks = scan(str(git_repo))
        assert tasks == []

    def test_finds_todos(self, git_repo: Path):
        (git_repo / "main.py").write_text("# TODO: implement feature\nx = 1\n")
        _commit(git_repo)
        tasks = scan(str(git_repo))
        assert len(tasks) == 1
        assert "[TODO]" in tasks[0].title
        assert "implement feature" in tasks[0].title
        assert tasks[0].source_ref == "main.py:1"

    def test_ignores_untracked(self, git_repo: Path):
        (git_repo / "untracked.py").write_text("# TODO: should be ignored\n")
        tasks = scan(str(git_repo))
        assert tasks == []

    def test_multiple_file_types(self, git_repo: Path):
        (git_repo / "app.js").write_text("// TODO: js task\n")
        (git_repo / "lib.py").write_text("# FIXME: python fix\n")
        (git_repo / "style.css").write_text("/* HACK: css hack */\n")
        _commit(git_repo)
        tasks = scan(str(git_repo))
        assert len(tasks) == 3
        keywords = {t.title.split("]")[0].strip("[") for t in tasks}
        assert keywords == {"TODO", "FIXME", "HACK"}

    def test_multiple_todos_one_file(self, git_repo: Path):
        (git_repo / "multi.py").write_text(
            "# TODO: first\nx = 1\n# FIXME: second\n"
        )
        _commit(git_repo)
        tasks = scan(str(git_repo))
        assert len(tasks) == 2
        refs = [t.source_ref for t in tasks]
        assert "multi.py:1" in refs
        assert "multi.py:3" in refs

    def test_empty_body_skipped(self, git_repo: Path):
        # "# TODO" with no trailing text — regex requires .+? so no match
        (git_repo / "empty.py").write_text("# TODO\n")
        _commit(git_repo)
        tasks = scan(str(git_repo))
        assert tasks == []
