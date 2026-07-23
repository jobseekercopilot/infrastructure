"""Helpers for temporary compatibility wrappers."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable


def run_deprecated(module_name: str, old_command: str, new_command: str) -> int:
    print(f"Deprecated: use {new_command}", file=sys.stderr)
    print(f"Removal note: {old_command} is a temporary compatibility wrapper.", file=sys.stderr)
    module = importlib.import_module(module_name)
    main: Callable[[], object] = getattr(module, "main")
    result = main()
    return int(result) if isinstance(result, int) else 0
