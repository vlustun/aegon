"""Markdown plan-file writers (progress.md / per-task plans).

These produce the checkbox plan file that is simultaneously the plan, the work
queue and the progress ledger — the single source of truth the harness resumes
from.
"""

from __future__ import annotations

from pathlib import Path

from aegon.domain.plan import Plan, extract_tasks


def write_progress_md(
    plan: Plan, out_path: Path, idea: str, title: str = "Build Plan"
) -> Path:
    """Write a checkbox plan file for live progress + resuming."""
    idea_line = " ".join(idea.splitlines())
    lines = [
        f"# {title}", "", f"> {idea_line}", "",
        f"**Stack:** {plan.stack}", "", "## Files", "",
    ]
    for f in plan.files:
        if isinstance(f, dict):
            lines.append(f"- `{f.get('path', '?')}` — {f.get('purpose', '')}")
        else:
            lines.append(f"- `{f}`")
    lines += ["", "## Tasks", ""]
    for step in plan.steps:
        lines.append(f"- [ ] {step}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_progress_md_fallback(
    raw: str, out_path: Path, idea: str, title: str = "Build Plan"
) -> Path:
    """Write a plan file from unparseable planner output, so a run is still
    resumable. Any bullet/numbered lines become checkboxes."""
    idea_line = " ".join(idea.splitlines())
    tasks = extract_tasks(raw) or ["Complete the plan described above"]
    lines = [f"# {title}", "", f"> {idea_line}", "", "## Plan", "", raw.strip(), "",
             "## Tasks", ""]
    lines += [f"- [ ] {t}" for t in tasks]
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
