"""git / gh CLI implementation of the ``VersionControl`` port."""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from aegon.domain.plan import slugify
from aegon.ports.ui import UserInterface
from aegon.ports.vcs import CommandResult


def parse_github_slug(repo_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub git URL (ssh or https), else None."""
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", repo_url.strip())
    return m.group(1) if m else None


def make_branch_name(project: Path, idea: str) -> str:
    """A unique, readable feature-branch name for this build."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    topic = slugify(idea) if idea else project.name
    return f"aegon/{topic}-{stamp}"[:60].rstrip("-")


class GitVersionControl:
    """Runs git and gh via subprocess."""

    def __init__(self, ui: UserInterface) -> None:
        self._ui = ui

    def _run(self, args: list[str], cwd: Path) -> CommandResult:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)
        return CommandResult(proc.returncode, (proc.stdout + proc.stderr).strip())

    def git(self, args: list[str], cwd: Path) -> CommandResult:
        return self._run(["git", *args], cwd)

    def is_repo(self, project: Path) -> bool:
        return (project / ".git").exists()

    def remote_is_empty(self, project: Path) -> bool:
        """True only if 'origin' is reachable and has no branches at all.

        Any error (unreachable, auth) returns False, so we never push to the base
        branch on a guess.
        """
        res = self.git(["ls-remote", "--heads", "origin"], project)
        return res.ok and not res.output.strip()

    def open_pull_request(
        self, project: Path, repo: str, base: str, head: str, title: str, body: str
    ) -> None:
        """Open a PR (base ← head) via the gh CLI; fall back to a compare URL."""
        slug = parse_github_slug(repo)
        if shutil.which("gh"):
            res = self._run(
                [
                    "gh", "pr", "create", "--base", base, "--head", head,
                    "--title", title, "--body", body,
                ],
                project,
            )
            if res.ok:
                self._ui.notify(f"✓ opened PR: {res.output.strip().splitlines()[-1]}")
                return
            if "already exists" in res.output:
                view = self._run(
                    ["gh", "pr", "view", head, "--json", "url", "-q", ".url"], project
                )
                self._ui.notify(
                    f"   (a PR for {head} already exists)"
                    + (f": {view.output}" if view.ok else "")
                )
                return
            self._ui.notify(
                f"gh pr create failed:\n{res.output}\n   (falling back to a compare link)"
            )
        if slug:
            self._ui.notify(
                "→ open a PR here:\n"
                f"   https://github.com/{slug}/compare/{base}...{head}?expand=1"
            )
        else:
            self._ui.notify(f"→ open a PR for branch '{head}' into '{base}' on your repo.")
