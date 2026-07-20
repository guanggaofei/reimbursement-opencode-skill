#!/usr/bin/env python3
"""Render source PDFs as images and place them on centered portrait A4 pages."""

from __future__ import annotations

import argparse
from io import BytesIO
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from _pathutil import add_root_arg, resolve_path


A4_WIDTH = 595.2755905511812
A4_HEIGHT = 841.8897637795277
CM_TO_POINTS = 72 / 2.54
SIGNATURE_LINE_LENGTH = 3 * CM_TO_POINTS
HEADER_FONT_SIZE = 12.0
DEFAULT_DPI = 400


def natural_key(path: Path) -> list[object]:
    text = path.as_posix()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def collect_pdfs(input_dir: Path) -> list[Path]:
    included_dirs = [input_dir / "1_材料费", input_dir / "2_打车费"]
    return sorted(
        (path for directory in included_dirs if directory.is_dir() for path in directory.rglob("*.pdf") if path.is_file()),
        key=natural_key,
    )


def invoice_sequence(path: Path) -> int | None:
    if "发票" not in path.stem or "行程单" in path.stem:
        return None
    match = re.match(r"^(\d+)_", path.name)
    return int(match.group(1)) if match else None


def render_pdf_pages(pdf: Path, output_dir: Path, dpi: int) -> list[Path]:
    executable = shutil.which("pdftoppm")
    if executable is None:
        raise SystemExit("pdftoppm is required to render source PDF pages as images")

    prefix = output_dir / "page"
    command = [
        executable,
        "-png",
        "-r",
        str(dpi),
        "-cropbox",
        str(pdf),
        str(prefix),
    ]
    result = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"failed to render {pdf} with pdftoppm: {result.stderr.strip()}")
    if "Couldn't create a font" in result.stderr:
        raise SystemExit(f"pdftoppm could not render fonts in {pdf}: {result.stderr.strip()}")

    pages = sorted(output_dir.glob("page-*.png"), key=natural_key)
    if not pages:
        raise SystemExit(f"pdftoppm produced no page images for {pdf}")
    return pages


def load_header_font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def add_invoice_header(image, sequence: int, content_top: int, dpi: int) -> None:
    from PIL import ImageDraw

    points_to_pixels = dpi / 72
    line_y = max(content_top - round(24 * points_to_pixels), round(24 * points_to_pixels))
    line_length = round(SIGNATURE_LINE_LENGTH * points_to_pixels)
    number_gap = round(8 * points_to_pixels)
    line_gap = round(10 * points_to_pixels)
    font = load_header_font(max(1, round(HEADER_FONT_SIZE * points_to_pixels)))
    draw = ImageDraw.Draw(image)
    text = str(sequence)
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    number_width = max(round(18 * points_to_pixels), text_width)
    total_width = number_width + number_gap + line_length * 2 + line_gap
    start_x = (image.width - total_width) // 2
    text_x = start_x + number_width - text_width
    text_y = line_y - text_height // 2 - text_box[1]
    first_line_x = start_x + number_width + number_gap
    second_line_x = first_line_x + line_length + line_gap
    line_width = max(1, round(0.8 * points_to_pixels))

    draw.line((first_line_x, line_y, first_line_x + line_length, line_y), fill="black", width=line_width)
    draw.line((second_line_x, line_y, second_line_x + line_length, line_y), fill="black", width=line_width)
    draw.text((text_x, text_y), text, fill="black", font=font)


def center_image_on_a4(source_path: Path, margin_x: float, margin_y: float, dpi: int, sequence: int | None):
    from PIL import Image

    canvas_width = round(A4_WIDTH * dpi / 72)
    canvas_height = round(A4_HEIGHT * dpi / 72)
    margin_x_pixels = round(margin_x * dpi / 72)
    margin_y_pixels = round(margin_y * dpi / 72)
    max_width = canvas_width - margin_x_pixels * 2
    max_height = canvas_height - margin_y_pixels * 2
    if max_width <= 0 or max_height <= 0:
        raise SystemExit("margins leave no usable A4 page area")

    with Image.open(source_path) as opened:
        source = opened.convert("RGB")
    scale = min(max_width / source.width, max_height / source.height)
    target_size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    if target_size != source.size:
        source = source.resize(target_size, Image.Resampling.LANCZOS)

    x = (canvas_width - source.width) // 2
    y = (canvas_height - source.height) // 2
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    canvas.paste(source, (x, y))
    if sequence is not None:
        add_invoice_header(canvas, sequence, y, dpi)
    return canvas


def add_image_page(writer, image, jpeg_quality: int) -> None:
    from pypdf._page import PageObject
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject, StreamObject

    encoded = BytesIO()
    image.save(encoded, format="JPEG", quality=jpeg_quality, subsampling=0, optimize=True)

    image_stream = StreamObject()
    image_stream._data = encoded.getvalue()
    image_stream.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Image"),
        NameObject("/Width"): NumberObject(image.width),
        NameObject("/Height"): NumberObject(image.height),
        NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
        NameObject("/BitsPerComponent"): NumberObject(8),
        NameObject("/Filter"): NameObject("/DCTDecode"),
    })
    image_ref = writer._add_object(image_stream)

    page = PageObject.create_blank_page(width=A4_WIDTH, height=A4_HEIGHT)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/PageImage"): image_ref}),
    })
    content = DecodedStreamObject()
    content.set_data(
        f"q\n{A4_WIDTH:.8f} 0 0 {A4_HEIGHT:.8f} 0 0 cm\n/PageImage Do\nQ\n".encode("ascii")
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.add_page(page)


def merge_pdfs(
    input_dir: Path,
    output_path: Path,
    margin_x: float,
    margin_y: float,
    dpi: int,
    jpeg_quality: int,
) -> int:
    from pypdf import PdfWriter

    pdfs = collect_pdfs(input_dir)
    if not pdfs:
        raise SystemExit(f"no PDFs found under {input_dir}")

    writer = PdfWriter()
    page_count = 0
    annotated_page_count = 0
    with TemporaryDirectory(prefix="reimbursement-pdf-render-") as temporary:
        temporary_root = Path(temporary)
        for file_index, pdf in enumerate(pdfs):
            render_dir = temporary_root / str(file_index)
            render_dir.mkdir()
            rendered_pages = render_pdf_pages(pdf, render_dir, dpi)
            sequence = invoice_sequence(pdf)
            for rendered_page in rendered_pages:
                image = center_image_on_a4(rendered_page, margin_x, margin_y, dpi, sequence)
                add_image_page(writer, image, jpeg_quality)
                image.close()
                page_count += 1
                if sequence is not None:
                    annotated_page_count += 1
            print(f"rendered {pdf} ({len(rendered_pages)} pages)")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as output_file:
        writer.write(output_file)
    print(
        f"wrote {output_path} ({len(pdfs)} files, {page_count} image pages, "
        f"{annotated_page_count} annotated invoice pages, {dpi} DPI)"
    )
    return page_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--input", type=Path, default=Path("output"), help="Directory containing PDFs")
    parser.add_argument("--output", type=Path, default=Path("合并发票_纵向居中.pdf"), help="Merged PDF path")
    parser.add_argument("--margin-x", type=float, default=0.0, help="Left/right margin in PDF points")
    parser.add_argument("--margin-y", type=float, default=72.0, help="Top/bottom margin in PDF points")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Source-page rasterization resolution")
    parser.add_argument("--jpeg-quality", type=int, default=92, help="Embedded page image JPEG quality (1-100)")
    args = parser.parse_args()
    if args.dpi <= 0:
        parser.error("--dpi must be greater than zero")
    if not 1 <= args.jpeg_quality <= 100:
        parser.error("--jpeg-quality must be between 1 and 100")

    root = args.root.resolve()
    input_dir = resolve_path(root, args.input)
    output_path = resolve_path(root, args.output)
    merge_pdfs(input_dir, output_path, args.margin_x, args.margin_y, args.dpi, args.jpeg_quality)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
