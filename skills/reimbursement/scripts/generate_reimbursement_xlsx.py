#!/usr/bin/env python3
"""Fill the reimbursement xlsx template directly from invoice_results_sorted.json.

No intermediate CSV
    Reads invoice_results_sorted.json and 匹配记录.json directly.
    The legacy CSV step was removed — this script handles the full pipeline.

Content inference (expense_content)
    Item text from the invoice is classified by keyword:
      - 轴承 → "轴承"
      - 螺丝 / 螺栓 / 螺母 → "螺丝"
      - 铝柱 / 铝合金 → "铝材"
      - 弹簧 → "弹簧"
      - 金属制品 → "标准件"
    Otherwise, the text after the first bracket/paren is trimmed and
    truncated to 5 Chinese characters.

Invoice number format
    Written as formula strings (t="str") to prevent Excel from converting
    long numeric invoice numbers to scientific notation.  E.g.
    ``="26342000002001430366"``.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from lxml import etree

from _pathutil import add_root_arg, resolve_path
from _matching_records import DEFAULT_MATCH_RECORD as DEFAULT_MATCH_RECORD_PATH, invoice_key, load_match_record


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
MAIN_NS = NS["m"]
SHEET_PATH = "xl/worksheets/sheet1.xml"

SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def template_path(name: str) -> Path:
    for candidate in [
        SCRIPT_ROOT / "assets/templates" / name,
        SCRIPT_ROOT / "reimbursement/assets/templates" / name,
    ]:
        if candidate.exists():
            return candidate
    return candidate[0]  # Will fail if missing


DEFAULT_TEMPLATE = template_path("Hello World 2026报账单模板V1.1.xlsx")
DEFAULT_SORTED_JSON = Path("invoice_results_sorted.json")
DEFAULT_MATCH_RECORD = DEFAULT_MATCH_RECORD_PATH
DEFAULT_OUTPUT = Path("Hello World 2026报账单填写结果.xlsx")

COLS = {
    "batch": "A",
    "seq": "B",
    "date": "C",
    "content": "D",
    "project": "E",
    "category": "F",
    "amount": "I",
    "invoice_no": "K",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def money_text(value: Any) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def is_taxi_invoice(inv: dict[str, Any]) -> bool:
    return str(inv.get("行程单文件名") or "").strip() not in ("", "无需", "ERROR")


def expense_content(inv: dict[str, Any]) -> str:
    if is_taxi_invoice(inv):
        return "打车费"
    items = inv.get("项目列表") or []
    text = " ".join(str(item.get("项目名称", "")) for item in items if isinstance(item, dict))
    for needles, label in [
        (("轴承",), "轴承"),
        (("螺丝", "螺栓", "螺母"), "螺丝"),
        (("铝柱", "铝合金"), "铝材"),
        (("弹簧",), "弹簧"),
        (("金属制品",), "标准件"),
    ]:
        if any(needle in text for needle in needles):
            return label[:5]
    cleaned = re.sub(r"[【\\[（(].*$", "", text).strip()
    cleaned = re.sub(r"\s+", "", cleaned)
    return (cleaned or "材料费")[:5]


def read_purchase_dates_from_record(path: Path, invoices: list[dict[str, Any]]) -> dict[str, str]:
    if not path.exists():
        return {}
    record = load_match_record(path)
    mapping = record.get("发票映射", {})
    dates: dict[str, str] = {}
    for inv in invoices:
        entry = mapping.get(invoice_key(str(inv.get("文件名") or "")), {})
        date_value = str(entry.get("购买日期") or "")
        if date_value:
            dates[str(inv.get("更新后文件名") or "")] = date_value
    return dates


def read_purchase_dates(path: Path) -> dict[str, str]:
    if path.exists():
        return {str(k): str(v) for k, v in read_json(path).items()}
    return {}


def build_rows(invoices: list[dict[str, Any]], purchase_dates: dict[str, str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for inv in invoices:
        updated_file = str(inv.get("更新后文件名") or "")
        taxi = is_taxi_invoice(inv)
        rows.append({
            "date": purchase_dates.get(updated_file, ""),
            "content": expense_content(inv),
            "project": "差旅" if taxi else "步兵机器人",
            "category": "差旅费" if taxi else "机械标准件",
            "amount": money_text(inv.get("价税合计金额")),
            "invoice_no": str(inv.get("发票号码") or ""),
        })
    return rows


def read_zip(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as zin:
        return {name: zin.read(name) for name in zin.namelist()}


def write_zip(path: Path, files: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, data in files.items():
            zout.writestr(name, data)


def excel_serial(value: str) -> str | None:
    if not value:
        return None
    match = re.match(r"^(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})$", value.strip())
    if not match:
        raise ValueError(f"unsupported date format: {value}")
    year, month, day = map(int, match.groups())
    return str((date(year, month, day) - date(1899, 12, 30)).days)


def invoice_number_formula(value: str) -> tuple[str, str]:
    stripped = value.strip()
    match = re.fullmatch(r'="([^"]*)"', stripped)
    number = match.group(1) if match else stripped
    return f'"{number}"', number


def col_name(cell_ref: str) -> str:
    match = re.match(r"^[A-Z]+", cell_ref)
    if not match:
        raise ValueError(f"invalid cell reference: {cell_ref}")
    return match.group(0)


def remove_value_nodes(cell: etree._Element) -> None:
    for child in list(cell):
        if child.tag in {f"{{{MAIN_NS}}}v", f"{{{MAIN_NS}}}f", f"{{{MAIN_NS}}}is"}:
            cell.remove(child)


def set_text(cell: etree._Element, text: str) -> None:
    remove_value_nodes(cell)
    cell.set("t", "inlineStr")
    is_el = etree.SubElement(cell, f"{{{MAIN_NS}}}is")
    t_el = etree.SubElement(is_el, f"{{{MAIN_NS}}}t")
    t_el.text = text


def set_number(cell: etree._Element, value: str | Decimal | int) -> None:
    remove_value_nodes(cell)
    cell.attrib.pop("t", None)
    v_el = etree.SubElement(cell, f"{{{MAIN_NS}}}v")
    v_el.text = str(value)


def set_blank(cell: etree._Element) -> None:
    remove_value_nodes(cell)
    cell.attrib.pop("t", None)


def set_formula_string(cell: etree._Element, formula: str, cached: str) -> None:
    remove_value_nodes(cell)
    cell.set("t", "str")
    f_el = etree.SubElement(cell, f"{{{MAIN_NS}}}f")
    f_el.text = formula
    v_el = etree.SubElement(cell, f"{{{MAIN_NS}}}v")
    v_el.text = cached


def update_cell_ref(cell: etree._Element, row_num: int) -> None:
    ref = cell.get("r")
    if ref:
        cell.set("r", f"{col_name(ref)}{row_num}")


def row_cells(row: etree._Element) -> dict[str, etree._Element]:
    return {col_name(cell.get("r")): cell for cell in row.findall("m:c", NS) if cell.get("r")}


def fill_row(row: etree._Element, row_index: int, data: dict[str, str]) -> None:
    cells = row_cells(row)
    set_text(cells[COLS["batch"]], "n")
    set_number(cells[COLS["seq"]], row_index)
    serial = excel_serial(data["date"])
    if serial is None:
        set_blank(cells[COLS["date"]])
    else:
        set_number(cells[COLS["date"]], serial)
    set_text(cells[COLS["content"]], data["content"])
    set_text(cells[COLS["project"]], data["project"])
    set_text(cells[COLS["category"]], data["category"])
    set_number(cells[COLS["amount"]], Decimal(data["amount"]))
    formula, cached = invoice_number_formula(f'="{data["invoice_no"]}"')
    set_formula_string(cells[COLS["invoice_no"]], formula, cached)


def generate(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    invoices_data = read_json(resolve_path(root, args.sorted_json))
    invoices = invoices_data.get("发票信息", [])
    if not invoices:
        raise RuntimeError("No invoices found in sorted JSON")
    match_record = resolve_path(root, args.match_record)
    if match_record.exists():
        purchase_dates = read_purchase_dates_from_record(match_record, invoices)
    else:
        purchase_dates = read_purchase_dates(resolve_path(root, args.dates_json))
    rows = build_rows(invoices, purchase_dates)

    files = read_zip(resolve_path(root, args.template))
    root = etree.fromstring(files[SHEET_PATH])
    sheet_data = root.find("m:sheetData", NS)
    if sheet_data is None:
        raise RuntimeError("worksheet has no sheetData")

    existing_rows = sheet_data.findall("m:row", NS)
    if len(existing_rows) < 2:
        raise RuntimeError("template sheet must include a header and at least one data row")

    templates = existing_rows[1:]
    for row in existing_rows[1:]:
        sheet_data.remove(row)

    for index, data_row in enumerate(rows, start=1):
        source = templates[min(index - 1, len(templates) - 1)]
        row = copy.deepcopy(source)
        excel_row = index + 1
        row.set("r", str(excel_row))
        for cell in row.findall("m:c", NS):
            update_cell_ref(cell, excel_row)
        fill_row(row, index, data_row)
        sheet_data.append(row)

    final_row = len(rows) + 1
    dimension = root.find("m:dimension", NS)
    if dimension is not None:
        dimension.set("ref", f"A1:P{final_row}")
    auto_filter = root.find("m:autoFilter", NS)
    if auto_filter is not None:
        auto_filter.set("ref", f"A1:P{final_row}")

    files[SHEET_PATH] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    output = resolve_path(args.root.resolve(), args.output)
    write_zip(output, files)
    print(f"wrote={output} rows={len(rows)}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--sorted-json", type=Path, default=DEFAULT_SORTED_JSON)
    parser.add_argument("--match-record", type=Path, default=DEFAULT_MATCH_RECORD)
    parser.add_argument("--dates-json", type=Path, default=Path("支出记录购买日期.json"), help="deprecated fallback if 匹配记录.json is absent")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    generate(parse_args())
