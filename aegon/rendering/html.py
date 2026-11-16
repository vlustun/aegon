"""Self-contained HTML plan render with task checkboxes."""

from __future__ import annotations

import html
from pathlib import Path

from aegon.domain.plan import Plan, Task, parse_tasks


def write_plan_html(
    plan: Plan, out_path: Path, idea: str, progress_md: Path | None = None
) -> Path:
    """Render the plan as a self-contained, styled HTML file with task checkboxes.

    Task checked-state is read from ``progress_md`` when available (so the HTML can
    be refreshed after scaffolding to show progress); otherwise all unchecked.
    """
    esc = html.escape

    if progress_md and progress_md.exists():
        tasks = parse_tasks(progress_md.read_text(encoding="utf-8"))
    else:
        tasks = [Task(str(s), False) for s in plan.steps]
    done = sum(1 for t in tasks if t.done)
    total = len(tasks)

    file_rows = ""
    for f in plan.files:
        if isinstance(f, dict):
            file_rows += (
                f"<tr><td class='path'>{esc(str(f.get('path', '?')))}</td>"
                f"<td>{esc(str(f.get('purpose', '')))}</td></tr>"
            )
        else:
            file_rows += f"<tr><td class='path'>{esc(str(f))}</td><td></td></tr>"

    task_items = ""
    for task in tasks:
        box = "checked" if task.done else ""
        cls = "done" if task.done else ""
        task_items += (
            f"<li class='{cls}'><label><input type='checkbox' disabled "
            f"{box}> {esc(task.text)}</label></li>"
        )

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Build Plan</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 760px;
         margin: 2rem auto; padding: 0 16px; }}
  h1 {{ font-size: 1.4rem; margin-bottom: .2rem; }}
  .idea {{ color: #888; margin-bottom: 1.5rem; white-space: pre-wrap; }}
  .k {{ font-weight: 600; }}
  .prog {{ color: #888; font-size: .9rem; margin-bottom: .3rem; }}
  table {{ border-collapse: collapse; width: 100%; margin: .5rem 0 1.5rem; }}
  td {{ padding: 6px 10px; border-bottom: 1px solid #8884; vertical-align: top; }}
  .path {{ font-family: ui-monospace, monospace; white-space: nowrap; }}
  ul.tasks {{ list-style: none; padding-left: 0; }}
  ul.tasks li {{ margin: .3rem 0; }}
  ul.tasks li.done label {{ color: #888; text-decoration: line-through; }}
  input[type=checkbox] {{ margin-right: .5rem; }}
  section {{ margin-bottom: 1.5rem; }}
</style></head><body>
<h1>🜂 Build Plan</h1>
<div class="idea">{esc(idea)}</div>
<section><span class="k">Summary:</span> {esc(plan.summary)}</section>
<section><span class="k">Stack:</span> {esc(plan.stack)}</section>
<section><div class="k">Files</div><table>{file_rows}</table></section>
<section><div class="k">Tasks</div>
<div class="prog">{done}/{total} done</div>
<ul class="tasks">{task_items}</ul></section>
</body></html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    return out_path
