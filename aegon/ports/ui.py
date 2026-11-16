"""The user-interaction port.

The core talks to a human only through this abstraction (DIP). The terminal
implementation lives in ``aegon.adapters.console_ui``; tests can supply a scripted
fake with no terminal at all.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol


class Decision(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    QUIT = "quit"


class UserInterface(Protocol):
    def ask(self, prompt: str) -> str:
        """Prompt for a single line of input and return it (stripped)."""
        ...

    def read_multiline(self, prompt: str) -> str:
        """Read a possibly multi-line / pasted instruction until EOF."""
        ...

    def notify(self, message: str) -> None:
        """Show an informational message to the user."""
        ...

    def checkpoint(
        self, question: str, *, allow_revise: bool = False
    ) -> tuple[Decision, str]:
        """Ask the user to approve/quit (and optionally revise).

        Returns (decision, feedback); feedback is non-empty only for REVISE.
        """
        ...

    def open_in_browser(self, path: Path) -> bool:
        """Best-effort open of a local file in the browser. Returns success."""
        ...
