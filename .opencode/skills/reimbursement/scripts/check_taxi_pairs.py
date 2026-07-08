#!/usr/bin/env python3
"""Check taxi trip-sheet ↔ invoice filename pairing.

Scans ``invoices/`` for PDFs whose name contains ``行程单``, derives the
expected invoice filename by replacing ``行程单`` with ``发票``, and
verifies the invoice file exists.

Usage::

    python scripts/check_taxi_pairs.py --root .

Exit codes::

    0  — all trip sheets have a matching invoice file
    1  — one or more trip sheets are unmatched
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _pathutil import add_root_arg, resolve_path


def check_pairs(invoices_dir: Path) -> list[tuple[str, str]]:
    """Return list of (trip_filename, expected_invoice_filename) for unmatched pairs."""
    unmatched: list[tuple[str, str]] = []
    for f in sorted(invoices_dir.glob("*行程单*")):
        if f.suffix.lower() not in (".pdf",):
            continue
        expected = f.name.replace("行程单", "发票")
        if not (invoices_dir / expected).exists():
            unmatched.append((f.name, expected))
    return unmatched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--invoices-dir", type=Path, default=Path("invoices"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    invoices_dir = resolve_path(root, args.invoices_dir)

    if not invoices_dir.is_dir():
        print(f"错误：目录不存在 {invoices_dir}")
        return 1

    unmatched = check_pairs(invoices_dir)
    if not unmatched:
        return 0

    print(f"以下 {len(unmatched)} 个行程单找不到对应发票：")
    for trip_name, expected_name in unmatched:
        print(f"  {trip_name}")
        print(f"    → 期望文件名: {expected_name}")
    print()
    print("请修改文件名后重新运行。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
