"""Utility for applying effects to terminal text with ANSI escape sequences."""
from enum import Enum
from typing import Any


class TerminalColors(Enum):
    """Utility for applying effects to terminal text with ANSI escape sequences."""

    RESET = "\033[0m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[0;1m"
    UNDERLINE = "\033[0;4m"

    def __call__(self, text: Any):
        return self.value + str(text) + self.RESET.value  # type: ignore
