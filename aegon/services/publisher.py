"""Commit a build onto a feature branch and open a PR into the base branch.

We never push app work straight to the base branch (e.g. main):

  • Empty remote → one-time bootstrap: the base branch is created and pushed so
    there is something for later PRs to target.
  • Otherwise    → the build is committed on a fresh ``aegon/<topic>-<ts>`` branch,
    pushed, and a PR into the base branch is opened (via gh, or a compare URL).
"""

from __future__ import annotations

from pathlib import Path

from aegon.adapters.git_vcs import make_branch_name
from aegon.config import Settings
from aegon.persistence.project_config import ProjectConfigRepository
from aegon.ports.ui import Decision, UserInterface
from aegon.ports.vcs import VersionControl


def ensure_gitignore(project: Path, entries: list[str]) -> None:
    """Make sure each entry is present in the project's .gitignore."""
    gi = project / ".gitignore"
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    to_add = [e for e in entries if e not in existing]
    if to_add:
        with gi.open("a", encoding="utf-8") as f:
            if existing and existing[-1].strip():
                f.write("\n")
            f.write("\n".join(to_add) + "\n")


class Publisher:
    def __init__(
        self,
        ui: UserInterface,
        vcs: VersionControl,
        config_repo: ProjectConfigRepository,
        settings: Settings,
    ) -> None:
        self._ui = ui
        self._vcs = vcs
        self._config_repo = config_repo
        self._settings = settings

    def publish(self, project: Path, idea: str) -> None:
        cfg = self._config_repo.load(project)
        repo = cfg.get("github_repo")
        if not repo:
            self._ui.notify("\nno GitHub repo configured — skipping publish.")
            self._ui.notify(
                f"   (add \"github_repo\" to {self._config_repo.path(project)} to enable it)"
            )
            return

        base = cfg.get("branch", "main")

        decision, _ = self._ui.checkpoint(f"Commit this build and open a PR on {repo} ?")
        if decision != Decision.APPROVE:
            self._ui.notify("skipped publishing.")
            return

        if not self._vcs.is_repo(project):
            self._vcs.git(["init"], project)
            self._vcs.git(["branch", "-M", base], project)

        # keep harness-only files out of the app's repo
        ensure_gitignore(project, list(self._settings.harness_only_files))

        # point origin at the configured repo (add or update)
        has_origin = self._vcs.git(["remote", "get-url", "origin"], project).ok
        self._vcs.git(
            ["remote", "set-url" if has_origin else "add", "origin", repo], project
        )

        if self._vcs.remote_is_empty(project):
            self._bootstrap(project, repo, base)
            return

        self._feature_branch_pr(project, repo, base, idea)

    def _bootstrap(self, project: Path, repo: str, base: str) -> None:
        self._ui.notify(f"\n(new repo — initializing '{base}' on {repo})")
        self._vcs.git(["checkout", base], project)  # best-effort; created above
        self._vcs.git(["add", "-A"], project)
        default_msg = f"Aegon: initialize {project.name}"
        msg = self._ui.ask(f"Commit message [{default_msg}]: ") or default_msg
        res = self._vcs.git(["commit", "-m", msg], project)
        if not res.ok and "nothing to commit" in res.output:
            self._ui.notify("nothing to commit.")
        self._ui.notify(f"pushing initial '{base}'…")
        res = self._vcs.git(["push", "-u", "origin", base], project)
        self._ui.notify(
            f"✓ initialized {repo} ({base}). Future builds will open PRs."
            if res.ok
            else f"push failed:\n{res.output}"
        )

    def _feature_branch_pr(
        self, project: Path, repo: str, base: str, idea: str
    ) -> None:
        head = make_branch_name(project, idea)
        self._vcs.git(["checkout", "-b", head], project)
        self._vcs.git(["add", "-A"], project)
        default_msg = f"Aegon: build {project.name}"
        msg = self._ui.ask(f"Commit message [{default_msg}]: ") or default_msg
        res = self._vcs.git(["commit", "-m", msg], project)
        if not res.ok and "nothing to commit" in res.output:
            self._ui.notify("nothing new to commit — skipping PR.")
            self._vcs.git(["checkout", base], project)
            return

        self._ui.notify(f"pushing branch '{head}'…")
        res = self._vcs.git(["push", "-u", "origin", head], project)
        if not res.ok:
            self._ui.notify(f"push failed:\n{res.output}")
            return

        body = f"Built by Aegon.\n\nTask: {idea}\n" if idea else "Built by Aegon.\n"
        self._vcs.open_pull_request(project, repo, base, head, msg, body)
