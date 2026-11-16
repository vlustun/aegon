"""The version-control port.

Abstracts the git/gh operations the publisher needs. The subprocess-backed
implementation is ``aegon.adapters.git_vcs``; tests inject a fake recorder.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    output: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class VersionControl(Protocol):
    def git(self, args: list[str], cwd: Path) -> CommandResult: ...

    def is_repo(self, project: Path) -> bool: ...

    def remote_is_empty(self, project: Path) -> bool:
        """True only if 'origin' is reachable and has no branches at all."""
        ...

    def open_pull_request(
        self, project: Path, repo: str, base: str, head: str, title: str, body: str
    ) -> None:
        """Open a PR (base ← head), falling back to printing a compare URL."""
        ...
