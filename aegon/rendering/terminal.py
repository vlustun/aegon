"""Terminal rendering of a plan as a scannable block (pure: returns a string)."""

from __future__ import annotations

from aegon.domain.plan import Plan


def format_plan(plan: Plan) -> str:
    """Return a structured plan as a clean, scannable multi-line block."""
    lines = ["\n╭─ BUILD PLAN " + "─" * 46]
    lines.append(f"│ summary : {plan.summary}")
    lines.append(f"│ stack   : {plan.stack}")
    lines.append("│ files   :")
    for f in plan.files:
        if isinstance(f, dict):
            lines.append(f"│    • {f.get('path', '?'):<28} {f.get('purpose', '')}")
        else:
            lines.append(f"│    • {f}")
    lines.append("│ steps   :")
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"│    {i}. {step}")
    lines.append("╰" + "─" * 59)
    return "\n".join(lines)
