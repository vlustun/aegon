"""Terminal implementation of the ``UserInterface`` port."""

from __future__ import annotations

import shutil
import subprocess
import webbrowser
from pathlib import Path

from aegon.ports.ui import Decision


class ConsoleUI:
    """Reads from stdin and writes to stdout — the real, interactive UI."""

    def ask(self, prompt: str) -> str:
        return input(prompt).strip()

    def read_multiline(self, prompt: str) -> str:
        """Read a possibly multi-line / pasted instruction until EOF (Ctrl-D).

        A single input() captures only one line, so a pasted multi-line block
        would spill into later prompts. Reading until EOF captures the whole thing.
        """
        print(prompt)
        print("  (enter your instruction — paste is fine — then Ctrl-D on an empty line)")
        lines: list[str] = []
        try:
            while True:
                lines.append(input())
        except EOFError:
            print()  # tidy newline after the Ctrl-D
        return "\n".join(lines).strip()

    def notify(self, message: str) -> None:
        print(message)

    def checkpoint(
        self, question: str, *, allow_revise: bool = False
    ) -> tuple[Decision, str]:
        opts = "[a]pprove / [r]evise / [q]uit" if allow_revise else "[a]pprove / [q]uit"
        while True:
            choice = self.ask(f"\n⏸  {question}  {opts}: ").lower()
            if choice in ("a", "approve", ""):
                return Decision.APPROVE, ""
            if choice in ("q", "quit"):
                return Decision.QUIT, ""
            if allow_revise and choice in ("r", "revise"):
                fb = self.ask("   what should change? ")
                return Decision.REVISE, fb
            print("   (please answer a" + ("/r" if allow_revise else "") + "/q)")

    def open_in_browser(self, path: Path) -> bool:
        """Best-effort open of a local file in the browser (handles WSL)."""
        target = str(path.resolve())
        for opener in ("wslview", "xdg-open"):
            if shutil.which(opener):
                try:
                    subprocess.Popen(
                        [opener, target],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True
                except OSError:
                    pass
        try:
            return webbrowser.open(path.resolve().as_uri())
        except webbrowser.Error:
            return False
