from __future__ import annotations

"""Cross-batch deduplication: extract invoice numbers from prior 第x批报账单.xlsx,
compare with invoice_results.json, and delete duplicate PDFs from invoices/.

No external libraries
    Reads xl/worksheets/sheet1.xml and xl/sharedStrings.xml directly
    from the xlsx zip. Does NOT depend on openpyxl or any spreadsheet
    library.

How it works
    1. Looks for 第x批报账单.xlsx at the project root.
    2. Extracts invoice numbers from column K (发票号码) of the
       支出流水表 sheet.
    3. Cross-references with 发票号码 values in invoice_results.json.
    4. For each duplicate: renames the PDF in invoices/ to .backup.
    5. The caller must then re-run super_invoice.py, which auto-detects
       the missing file and removes the entry from invoice_results.json.

Backup convention
    ``浙江大学_3185959443369940070.pdf`` → ``...pdf.backup``.
    Backups can be restored manually (rename back to .pdf) or deleted.
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _pathutil import add_root_arg, resolve_path

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def extract_invoice_numbers_from_xlsx(xlsx_path: Path) -> set[str]:
    """Extract invoice numbers from column K of the first sheet."""
    with zipfile.ZipFile(xlsx_path, "r") as z:
        # Read shared strings
        ss_xml = z.read("xl/sharedStrings.xml")
        ss_root = ET.fromstring(ss_xml)
        strings: list[str] = []
        for si in ss_root.findall("s:si", NS):
            # Concatenate all <t> text runs
            texts = si.iterfind(".//s:t", NS)
            text = "".join(t.text or "" for t in texts)
            strings.append(text)

        # Read sheet data
        sheet_xml = z.read("xl/worksheets/sheet1.xml")
        sheet_root = ET.fromstring(sheet_xml)

    invoice_nums: set[str] = set()
    for row in sheet_root.findall(".//s:row", NS):
        row_num = int(row.get("r", "0"))
        if row_num <= 1:  # skip header
            continue
        for c in row.findall("s:c", NS):
            ref = c.get("r", "")
            if not ref.startswith("K"):
                continue
            v_el = c.find("s:v", NS)
            if v_el is None or not v_el.text:
                continue
            v = v_el.text
            if c.get("t") == "s":
                idx = int(v)
                num_str = strings[idx] if idx < len(strings) else ""
            else:
                num_str = v
            num_str = num_str.strip().strip("=").strip('"').strip("'")
            num_str = num_str.replace("'", "")
            if num_str and num_str.isdigit():
                invoice_nums.add(num_str)

    return invoice_nums


def get_current_invoice_numbers(results_path: Path) -> dict[str, str]:
    """Return {invoice_number: filename} from invoice_results.json."""
    data = json.loads(results_path.read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for inv in data.get("发票信息", []):
        num = str(inv.get("发票号码", "")).strip()
        fname = inv.get("文件名", "")
        if num and fname:
            mapping[num] = fname
    return mapping


def find_prior_xlsx(root: Path) -> Path | None:
    """Find the most recent 第x批报账单.xlsx."""
    patterns = list(root.glob("第*批报账单.xlsx"))
    return patterns[0] if patterns else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    args = parser.parse_args()
    root = args.root.resolve()

    xlsx_path = find_prior_xlsx(root)
    if xlsx_path is None:
        print("No prior 第x批报账单.xlsx found — skipping cross-batch dedup.")
        return

    results_path = root / "invoice_results.json"
    if not results_path.exists():
        print("invoice_results.json not found. Run super_invoice.py first.")
        sys.exit(1)

    print(f"Reading prior batch: {xlsx_path.name}")
    prior_nums = extract_invoice_numbers_from_xlsx(xlsx_path)
    print(f"  Prior invoice numbers: {len(prior_nums)}")

    current = get_current_invoice_numbers(results_path)
    print(f"  Current invoice numbers: {len(current)}")

    overlap = prior_nums & set(current.keys())
    print(f"  Cross-batch duplicates: {len(overlap)}")

    if not overlap:
        print("No duplicates found.")
        return

    invoices_dir = root / "invoices"
    removed_files: list[str] = []
    for num in sorted(overlap):
        fname = current[num]
        pdf_path = invoices_dir / fname
        if pdf_path.exists():
            # Backup and delete
            backup_path = pdf_path.with_suffix(pdf_path.suffix + ".backup")
            os.rename(pdf_path, backup_path)
            removed_files.append(fname)
            print(f"  Removed: {fname} (backup → {backup_path.name})")
        else:
            print(f"  Already missing: {fname}")

    if removed_files:
        print(f"\nRemoved {len(removed_files)} duplicate PDFs from invoices/.")
        print("Re-run super_invoice.py to auto-clean invoice_results.json.")
    else:
        print("No files to remove.")


if __name__ == "__main__":
    main()
