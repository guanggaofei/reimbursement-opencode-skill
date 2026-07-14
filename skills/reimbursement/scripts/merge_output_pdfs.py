#!/usr/bin/env python3
"""Merge ordinary offline-submission PDFs onto centered portrait A4 pages."""

from __future__ import annotations

import argparse
from copy import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pypdf._page import PageObject

from _pathutil import add_root_arg, resolve_path


A4_WIDTH = 595.2755905511812
A4_HEIGHT = 841.8897637795277
CM_TO_POINTS = 72 / 2.54
SIGNATURE_LINE_LENGTH = 3 * CM_TO_POINTS
HEADER_FONT_SIZE = 12.0


def natural_key(path: Path) -> list[object]:
    text = path.as_posix()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def collect_pdfs(input_dir: Path) -> list[Path]:
    included_dirs = [input_dir / "1_材料费", input_dir / "2_打车费"]
    return sorted(
        (path for directory in included_dirs if directory.is_dir() for path in directory.rglob("*.pdf") if path.is_file()),
        key=natural_key,
    )


def transform_page_annotations(
    page: PageObject,
    source_left: float,
    source_bottom: float,
    scale: float,
    target_x: float,
    target_y: float,
) -> None:
    from pypdf.generic import ArrayObject, FloatObject, NameObject

    def transform_coordinates(values: object) -> ArrayObject:
        coordinates = [float(value) for value in values]  # type: ignore[arg-type]
        transformed = ArrayObject()
        for index in range(0, len(coordinates), 2):
            transformed.append(FloatObject((coordinates[index] - source_left) * scale + target_x))
            transformed.append(FloatObject((coordinates[index + 1] - source_bottom) * scale + target_y))
        return transformed

    for annotation_ref in page.get("/Annots", []) or []:
        annotation = annotation_ref.get_object()
        for key in ("/Rect", "/QuadPoints", "/Vertices", "/L", "/CL"):
            if key in annotation and len(annotation[key]) % 2 == 0:
                annotation[NameObject(key)] = transform_coordinates(annotation[key])
        for key in ("/InkList", "/Path"):
            if key not in annotation:
                continue
            annotation[NameObject(key)] = ArrayObject(
                transform_coordinates(path) for path in annotation[key]
            )


def center_page_on_a4(page: PageObject, margin_x: float, margin_y: float) -> tuple[PageObject, float]:
    from pypdf import Transformation
    from pypdf._page import PageObject

    # Normalize page rotation so dimensions and content transform match.
    page = copy(page)
    if page.rotation:
        page.transfer_rotation_to_content()

    # CropBox is the visible page. Some invoices place a half-page CropBox
    # inside a full A4 MediaBox, so centering by MediaBox leaves them offset.
    source_box = page.cropbox
    source_left = float(source_box.left)
    source_bottom = float(source_box.bottom)
    src_width = float(source_box.width)
    src_height = float(source_box.height)
    max_width = A4_WIDTH - margin_x * 2
    max_height = A4_HEIGHT - margin_y * 2
    scale = min(max_width / src_width, max_height / src_height)

    x = (A4_WIDTH - src_width * scale) / 2
    y = (A4_HEIGHT - src_height * scale) / 2

    target = PageObject.create_blank_page(width=A4_WIDTH, height=A4_HEIGHT)
    transform_page_annotations(page, source_left, source_bottom, scale, x, y)
    transform = Transformation().translate(-source_left, -source_bottom).scale(scale).translate(x, y)
    target.merge_transformed_page(page, transform)
    return target, y + src_height * scale


def invoice_sequence(path: Path) -> int | None:
    if "发票" not in path.stem or "行程单" in path.stem:
        return None
    match = re.match(r"^(\d+)_", path.name)
    return int(match.group(1)) if match else None


def invoice_header_overlay(sequence: int, line_y: float) -> PageObject:
    from pypdf._page import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    overlay = PageObject.create_blank_page(width=A4_WIDTH, height=A4_HEIGHT)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    overlay[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/FSEQ"): font}),
    })

    text = str(sequence)
    text_width = len(text) * HEADER_FONT_SIZE * 0.556
    number_width = max(18.0, text_width)
    number_gap = 8.0
    line_gap = 10.0
    total_width = number_width + number_gap + SIGNATURE_LINE_LENGTH * 2 + line_gap
    start_x = (A4_WIDTH - total_width) / 2
    text_x = start_x + number_width - text_width
    first_line_x = start_x + number_width + number_gap
    second_line_x = first_line_x + SIGNATURE_LINE_LENGTH + line_gap
    text_y = line_y - HEADER_FONT_SIZE * 0.32

    commands = (
        "q\n"
        "0 G\n"
        "0 g\n"
        "0.8 w\n"
        f"{first_line_x:.6f} {line_y:.6f} m "
        f"{first_line_x + SIGNATURE_LINE_LENGTH:.6f} {line_y:.6f} l S\n"
        f"{second_line_x:.6f} {line_y:.6f} m "
        f"{second_line_x + SIGNATURE_LINE_LENGTH:.6f} {line_y:.6f} l S\n"
        "BT\n"
        f"/FSEQ {HEADER_FONT_SIZE:.2f} Tf\n"
        f"1 0 0 1 {text_x:.6f} {text_y:.6f} Tm\n"
        f"({text}) Tj\n"
        "ET\n"
        "Q\n"
    )
    stream = DecodedStreamObject()
    stream.set_data(commands.encode("ascii"))
    overlay[NameObject("/Contents")] = stream
    return overlay


def add_invoice_header(page: PageObject, sequence: int, content_top: float) -> None:
    line_y = min(content_top + 24.0, A4_HEIGHT - 24.0)
    page.merge_page(invoice_header_overlay(sequence, line_y))


def merge_pdfs(input_dir: Path, output_path: Path, margin_x: float, margin_y: float) -> int:
    from pypdf import PdfReader, PdfWriter

    pdfs = collect_pdfs(input_dir)
    if not pdfs:
        raise SystemExit(f"no PDFs found under {input_dir}")

    writer = PdfWriter()
    page_count = 0
    annotated_page_count = 0
    for pdf in pdfs:
        reader = PdfReader(str(pdf))
        sequence = invoice_sequence(pdf)
        for page in reader.pages:
            target, content_top = center_page_on_a4(page, margin_x, margin_y)
            if sequence is not None:
                add_invoice_header(target, sequence, content_top)
                annotated_page_count += 1
            writer.add_page(target)
            page_count += 1
        print(f"added {pdf} ({len(reader.pages)} pages)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        writer.write(output_file)
    print(f"wrote {output_path} ({len(pdfs)} files, {page_count} pages, {annotated_page_count} annotated invoice pages)")
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
