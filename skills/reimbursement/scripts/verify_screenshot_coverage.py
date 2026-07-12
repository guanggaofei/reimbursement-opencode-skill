#!/usr/bin/env python3
"""Verify screenshot coverage from 匹配记录.json.

The match record is the single source of truth for screenshot matching.  It
stores stable original paths (invoices/<原发票名>, images/<原截图名>), so invoice
sequence changes do not invalidate prior manual matches.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _pathutil import INTERNAL_DIR, add_root_arg, resolve_path
from _matching_records import DEFAULT_MATCH_RECORD, invoice_images, invoice_key, load_match_record


@dataclass
class Invoice:
    seq: int
    source_file: str
    updated_file: str
    amount: float
    is_taxi: bool
    trip_file: str
    updated_trip_file: str


@dataclass
class TripEntry:
    invoice_seq: int
    item_index: int
    amount: float
    service_provider: str
    vehicle_type: str
    board_time: str


def read_invoices(sorted_json: Path) -> list[Invoice]:
    data = json.loads(sorted_json.read_text(encoding="utf-8"))
    invoices: list[Invoice] = []
    for inv in data.get("发票信息", []):
        updated = str(inv.get("更新后文件名") or "")
        match = re.match(r"^(\d+)_", updated)
        seq = int(match.group(1)) if match else int(inv.get("发票序号", 0)) + 1
        invoices.append(Invoice(
            seq=seq,
            source_file=str(inv.get("文件名") or ""),
            updated_file=updated,
            amount=float(inv.get("价税合计金额", 0) or 0),
            is_taxi=str(inv.get("行程单文件名") or "").strip() not in ("", "无需", "ERROR"),
            trip_file=str(inv.get("行程单文件名") or ""),
            updated_trip_file=str(inv.get("更新后行程单文件名") or ""),
        ))
    return invoices


def read_trip_entries(trip_json: Path) -> dict[int, list[TripEntry]]:
    if not trip_json.exists():
        return {}
    data = json.loads(trip_json.read_text(encoding="utf-8"))
    result: dict[int, list[TripEntry]] = defaultdict(list)
    for fname, trips in data.items():
        match = re.match(r"^(\d+)_", str(fname))
        if not match:
            continue
        seq = int(match.group(1))
        for trip in trips:
            result[seq].append(TripEntry(
                invoice_seq=seq,
                item_index=int(trip.get("序号", 0) or 0),
                amount=float(trip.get("金额", 0) or 0),
                service_provider=str(trip.get("服务商", "")),
                vehicle_type=str(trip.get("车型", "")),
                board_time=str(trip.get("上车时间", "")),
            ))
    return result


def trip_record(entry: dict[str, Any], trip_index: int) -> dict[str, Any] | None:
    for trip in entry.get("行程明细", []) or []:
        if int(trip.get("行程序号", 0) or 0) == int(trip_index):
            return trip
    return None


def has_images(entry: dict[str, Any], kind: str) -> bool:
    return bool(invoice_images(entry, kind))


def has_trip_images(entry: dict[str, Any], kind: str, trip_index: int, *, single_trip_fallback: bool) -> bool:
    trip = trip_record(entry, trip_index)
    if trip and trip.get(kind):
        return True
    return single_trip_fallback and bool(entry.get(kind))


def format_amount(value: float) -> str:
    return f"{value:.2f}"


def build_report_md(
    missing_all: list[Invoice],
    incomplete: list[tuple[Invoice, str]],
    missing_trip_screenshots: list[tuple[int, int, float, str, str]],
    pending: list[dict[str, Any]],
) -> str:
    lines: list[str] = ["# 支出记录 OCR 整理结果", ""]

    lines.extend(["## 未匹配到截图的发票", "", "| 发票 | 金额 | 类型 | 缺失截图 |", "| --- | ---: | --- | --- |"])
    if missing_all:
        for inv in sorted(missing_all, key=lambda item: item.seq):
            lines.append(f"| `{inv.updated_file}` | {format_amount(inv.amount)} | {'打车费' if inv.is_taxi else '材料费'} | 支付记录+账单截图 |")
    else:
        lines.append("| 无 |  |  |  |")

    lines.extend(["", "## 截图不完整的发票", "", "| 发票 | 金额 | 类型 | 缺失截图 |", "| --- | ---: | --- | --- |"])
    if incomplete:
        for inv, missing_kind in sorted(incomplete, key=lambda item: item[0].seq):
            lines.append(f"| `{inv.updated_file}` | {format_amount(inv.amount)} | {'打车费' if inv.is_taxi else '材料费'} | {missing_kind} |")
    else:
        lines.append("| 无 |  |  |  |")

    lines.extend(["", "## 未匹配到截图的行程单明细", "", "| 行程所属发票 | 行程序号 | 金额 | 缺失截图 | 详情 |", "| --- | ---: | ---: | --- | --- |"])
    if missing_trip_screenshots:
        for seq, trip_index, amount, missing_kind, detail in sorted(missing_trip_screenshots):
            lines.append(f"| `{seq}` | {trip_index} | {format_amount(amount)} | {missing_kind} | {detail} |")
    else:
        lines.append("| 无 |  |  |  |  |")

    lines.extend(["", "## 未匹配截图", "", "| 图片 | 金额 | 类型 | 原因 |", "| --- | ---: | --- | --- |"])
    if pending:
        for item in pending:
            lines.append(f"| `{item.get('图片', '')}` | {item.get('金额', '')} | {item.get('类型', '')} | {item.get('原因', '')} |")
    else:
        lines.append("| 无 |  |  |  |")
    return "\n".join(lines) + "\n"


def read_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def enrich_pending_from_cache(pending: list[dict[str, Any]], cache: dict[str, Any]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in pending:
        image = str(item.get("图片") or "")
        cached = cache.get(image, {}) if image else {}
        enriched.append({
            "图片": image,
            "金额": str(cached.get("amounts") or ""),
            "类型": str(cached.get("ocr_category") or cached.get("kind") or ""),
            "原因": str(item.get("原因") or ""),
        })
    return enriched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--sorted-json", type=Path, default=Path("invoice_results_sorted.json"))
    parser.add_argument("--trip-json", type=Path, default=INTERNAL_DIR / "行程单数据.json")
    parser.add_argument("--match-record", type=Path, default=DEFAULT_MATCH_RECORD)
    parser.add_argument("--ocr-cache", type=Path, default=Path("OCR缓存.json"))
    parser.add_argument("--update-report", type=Path, nargs="?", const=Path("支出记录OCR整理结果.md"), help="写入 Markdown 报告文件")
    args = parser.parse_args()

    root = args.root.resolve()
    invoices = read_invoices(resolve_path(root, args.sorted_json))
    trip_entries = read_trip_entries(resolve_path(root, args.trip_json))
    record = load_match_record(resolve_path(root, args.match_record))

    missing_all: list[Invoice] = []
    incomplete: list[tuple[Invoice, str]] = []
    missing_trip_screenshots: list[tuple[int, int, float, str, str]] = []

    mapping = record.get("发票映射", {})
    for inv in invoices:
        entry = mapping.get(invoice_key(inv.source_file), {})
        trips = trip_entries.get(inv.seq, [])
        if inv.is_taxi and trips:
            single_trip = len(trips) == 1
            any_image = has_images(entry, "支付记录") or has_images(entry, "账单截图")
            any_trip_image = any((trip.get("支付记录") or trip.get("账单截图")) for trip in entry.get("行程明细", []) or [])
            if not any_image and not any_trip_image:
                missing_all.append(inv)
                continue
            for trip in trips:
                missing: list[str] = []
                if not has_trip_images(entry, "支付记录", trip.item_index, single_trip_fallback=single_trip):
                    missing.append("支付记录")
                if not has_trip_images(entry, "账单截图", trip.item_index, single_trip_fallback=single_trip):
                    missing.append("账单截图")
                if missing:
                    detail = f"服务商={trip.service_provider}, 车型={trip.vehicle_type}, 时间={trip.board_time}"
                    missing_trip_screenshots.append((inv.seq, trip.item_index, trip.amount, "+".join(missing), detail))
            continue

        has_payment = has_images(entry, "支付记录")
        has_bill = has_images(entry, "账单截图")
        if not has_payment and not has_bill:
            missing_all.append(inv)
        else:
            if not has_payment:
                incomplete.append((inv, "支付记录"))
            if not has_bill:
                incomplete.append((inv, "账单截图"))

    cache = read_json_if_exists(resolve_path(root, args.ocr_cache))
    pending = enrich_pending_from_cache(list(record.get("未匹配截图", []) or []), cache)
    report = build_report_md(missing_all, incomplete, missing_trip_screenshots, pending)
    if args.update_report:
        resolve_path(root, args.update_report).write_text(report, encoding="utf-8")
    print(report)
    return 1 if missing_all or incomplete or missing_trip_screenshots else 0


if __name__ == "__main__":
    raise SystemExit(main())
