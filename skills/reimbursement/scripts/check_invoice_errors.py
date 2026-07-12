#!/usr/bin/env python3
"""Detect fixable invoice extraction errors in invoice_results.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _pathutil import INTERNAL_DIR, add_root_arg, resolve_path


ERROR_VALUES = {"ERROR", "需人工校验"}


def add_error(errors: list[dict[str, Any]], filename: str, field: str, value: Any, error_type: str) -> None:
    errors.append({
        "文件名": filename,
        "字段": field,
        "当前值": value,
        "错误类型": error_type,
    })


def scan_value(errors: list[dict[str, Any]], filename: str, value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "开票时间" and child == []:
                add_error(errors, filename, child_path, child, "开票时间为空")
            scan_value(errors, filename, child, child_path)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}.{index}" if path else str(index)
            scan_value(errors, filename, child, child_path)
        return

    if value in ERROR_VALUES:
        add_error(errors, filename, path, value, str(value))


def detect_errors(data: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    invoices = data.get("发票信息")
    if not isinstance(invoices, list):
        raise ValueError("invoice_results.json missing 发票信息 list")
    for invoice in invoices:
        if not isinstance(invoice, dict):
            continue
        filename = str(invoice.get("文件名") or "")
        scan_value(errors, filename, invoice, "")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--input", type=Path, default=Path("invoice_results.json"))
    parser.add_argument("--output", type=Path, default=INTERNAL_DIR / "invoice_errors_raw.json")
    args = parser.parse_args()

    root = args.root.resolve()
    input_path = resolve_path(root, args.input)
    output_path = resolve_path(root, args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = json.loads(input_path.read_text(encoding="utf-8"))
        errors = detect_errors(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    result = {
        "has_error": bool(errors),
        "error_count": len(errors),
        "errors": errors,
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output_path} ({len(errors)} errors)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
