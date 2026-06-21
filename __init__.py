"""calltrace - Record the call stack of any Python script/CLI into a readable HTML report.

Usage:
    python -m calltrace [--project DIR ...] [--step-all-imports] SCRIPT [SCRIPT_ARGS...]
"""

from .cli import main

__all__ = ["main"]
