"""Ensure sibling packages under local/ (e.g. ocr) are importable."""

from __future__ import annotations

import sys
from pathlib import Path

_LOCAL_ROOT: Path | None = None
_BOOTSTRAPPED = False


def local_root() -> Path:
    """Path to Moodle local/ (parent of chatbot/ and ocr/)."""
    global _LOCAL_ROOT
    if _LOCAL_ROOT is None:
        _LOCAL_ROOT = Path(__file__).resolve().parents[2]
    return _LOCAL_ROOT


def ensure_local_packages() -> Path:
    """Add local/ to sys.path once so `import ocr` works from rag_service."""
    global _BOOTSTRAPPED
    root = local_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    _BOOTSTRAPPED = True
    return root
