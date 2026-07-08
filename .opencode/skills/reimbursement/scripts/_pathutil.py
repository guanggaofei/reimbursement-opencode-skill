"""Shared path resolution for reimbursement scripts.

Each script accepts a ``--root`` argument.  All project-relative paths
(invoices, images, output, JSON files, etc.) are resolved against the
given root.  Template paths are *not* resolved here — they are skill-local
and located via ``Path(__file__).resolve().parents[1] / "assets"``.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def resolve_path(root: Path, user_path: Path) -> Path:
    """Resolve ``user_path`` against ``root``, honouring absolute paths."""
    if user_path.is_absolute():
        return user_path
    return (root / user_path).resolve()


def add_root_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(),
        help="Project root directory (default: current working directory)",
    )
