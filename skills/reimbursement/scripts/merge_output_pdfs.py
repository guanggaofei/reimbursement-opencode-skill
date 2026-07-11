#!/usr/bin/env python3
"""Merge ordinary offline-submission PDFs onto centered portrait A4 pages."""

from __future__ import annotations

import argparse
from copy import copy
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject

from _pathutil import add_root_arg, resolve_path


A4_WIDTH = 595.2755905511812
A4_HEIGHT = 841.8897637795277


def natural_key(path: Path) -> list[object]:
    text = path.as_posix()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def collect_pdfs(input_dir: Path) -> list[Path]:
    included_dirs = [input_dir / "1_材料费", input_dir / "2_打车费"]
    return sorted(
        (path for directory in included_dirs if directory.is_dir() for path in directory.rglob("*.pdf") if path.is_file()),
        key=natural_key,
    )


def page_size(page: PageObject) -> tuple[float, float]:
    box = page.mediabox
    return float(box.width), float(box.height)


def center_page_on_a4(page: PageObject, margin_x: float, margin_y: float) -> PageObject:
    # Normalize page rotation so dimensions and content transform match.
    page = copy(page)
    if page.rotation:
        page.transfer_rotation_to_content()

    src_width, src_height = page_size(page)
    max_width = A4_WIDTH - margin_x * 2
    max_height = A4_HEIGHT - margin_y * 2
    scale = min(max_width / src_width, max_height / src_height)

    x = (A4_WIDTH - src_width * scale) / 2
    y = (A4_HEIGHT - src_height * scale) / 2

    target = PageObject.create_blank_page(width=A4_WIDTH, height=A4_HEIGHT)
    target.merge_transformed_page(page, Transformation().scale(scale).translate(x, y))
    return target


def merge_pdfs(input_dir: Path, output_path: Path, margin_x: float, margin_y: float) -> int:
    pdfs = collect_pdfs(input_dir)
    if not pdfs:
        raise SystemExit(f"no PDFs found under {input_dir}")

    writer = PdfWriter()
    page_count = 0
    for pdf in pdfs:
        reader = PdfReader(str(pdf))
        for page in reader.pages:
            writer.add_page(center_page_on_a4(page, margin_x, margin_y))
            page_count += 1
        print(f"added {pdf} ({len(reader.pages)} pages)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        writer.write(output_file)
    print(f"wrote {output_path} ({len(pdfs)} files, {page_count} pages)")
    return page_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--input", type=Path, default=Path("output"), help="Directory containing PDFs")
    parser.add_argument("--output", type=Path, default=Path("合并发票_纵向居中.pdf"), help="Merged PDF path")
    parser.add_argument("--margin-x", type=float, default=0.0, help="Left/right margin in PDF points")
    parser.add_argument("--margin-y", type=float, default=72.0, help="Top/bottom margin in PDF points")
    args = parser.parse_args()

    root = args.root.resolve()
    input_dir = resolve_path(root, args.input)
    output_path = resolve_path(root, args.output)
    merge_pdfs(input_dir, output_path, args.margin_x, args.margin_y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
