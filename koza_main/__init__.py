"""Koza entry-point package.

This package exists so that the koza console script works reliably even
when pip's editable-install .pth file is missing or stale (e.g. after
a WinError 32 update).  It explicitly adds the repo root to sys.path
before importing the real entry point.
"""
import sys
import os

# Ensure the repo root (parent of this package) is on sys.path
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from koza_run import main  # noqa: E402

__all__ = ["main"]
