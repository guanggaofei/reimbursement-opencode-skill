#!/usr/bin/env python3
"""Package user-facing reimbursement attachments from internal source folders."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

from _pathutil import INTERNAL_DIR, add_root_arg, resolve_path


PAYMENT_ARCHIVE = Path("支付说明与支付记录.zip")
CHENJING_ARCHIVE = Path("辰景发票.zip")


def collect_files(directory: Path, suffix: str) -> list[Path]:
    if not directory.is_dir():
        return []
    normalized_suffix = suffix.lower()
    return sorted(path for path in directory.rglob("*") if path.is_file() and path.suffix.lower() == normalized_suffix)


def replace_archive(output: Path, entries: list[tuple[Path, str]]) -> bool:
    if output.exists():
        output.unlink()
    if not entries:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, archive_name in entries:
            archive.write(source, archive_name)
    return True


def package_payment_materials(root: Path, output: Path) -> bool:
    internal = root / INTERNAL_DIR
    entries: list[tuple[Path, str]] = []
    for folder_name in ("支付记录", "支付说明"):
        folder = internal / folder_name
        for source in sorted(path for path in folder.glob("*") if path.is_file() and path.suffix.lower() == ".docx"):
            entries.append((source, (Path(folder_name) / source.relative_to(folder)).as_posix()))
    return replace_archive(output, entries)


def package_chenjing_invoices(root: Path, output: Path) -> bool:
    folder = root / "output" / "4_辰景发票"
    entries = [(source, source.relative_to(folder).as_posix()) for source in collect_files(folder, ".pdf")]
    return replace_archive(output, entries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--payment-output", type=Path, default=PAYMENT_ARCHIVE)
    parser.add_argument("--chenjing-output", type=Path, default=CHENJING_ARCHIVE)
    args = parser.parse_args()

    root = args.root.resolve()
    payment_output = resolve_path(root, args.payment_output)
    chenjing_output = resolve_path(root, args.chenjing_output)
    payment_created = package_payment_materials(root, payment_output)
    chenjing_created = package_chenjing_invoices(root, chenjing_output)
    print(f"payment_archive={'created' if payment_created else 'absent'} path={payment_output}")
    print(f"chenjing_archive={'created' if chenjing_created else 'absent'} path={chenjing_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
