from __future__ import annotations

import json
from pathlib import Path
from typing import Any


MATCH_RECORD_VERSION = 2
DEFAULT_MATCH_RECORD = Path("匹配记录.json")


def empty_record() -> dict[str, Any]:
    return {
        "版本": MATCH_RECORD_VERSION,
        "发票映射": {},
        "未匹配截图": [],
        "忽略截图": [],
    }


def normalize_record(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    record = empty_record()
    record.update(data)
    if not isinstance(record.get("发票映射"), dict):
        record["发票映射"] = {}
    if not isinstance(record.get("未匹配截图"), list):
        record["未匹配截图"] = []
    if not isinstance(record.get("忽略截图"), list):
        record["忽略截图"] = []
    record["版本"] = MATCH_RECORD_VERSION
    record["发票映射"] = {
        str(key): normalize_invoice_entry(str(key), value)
        for key, value in record.get("发票映射", {}).items()
        if str(key)
    }
    record["未匹配截图"] = [
        normalize_unmatched(item)
        for item in record.get("未匹配截图", [])
        if isinstance(item, dict) and item.get("图片")
    ]
    record["忽略截图"] = [
        {"图片": str(item.get("图片") or ""), "原因": str(item.get("原因") or "")}
        for item in record.get("忽略截图", [])
        if isinstance(item, dict) and item.get("图片")
    ]
    return record


def normalize_invoice_entry(key: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    entry = {
        "发票文件": str(value.get("发票文件") or key),
        "支付记录": list(value.get("支付记录") or []),
        "账单截图": list(value.get("账单截图") or []),
        "行程明细": [],
        "购买日期": str(value.get("购买日期") or ""),
    }
    for trip in value.get("行程明细", []) or []:
        if not isinstance(trip, dict):
            continue
        try:
            trip_index = int(trip.get("行程序号", 0) or 0)
        except (TypeError, ValueError):
            continue
        if trip_index <= 0:
            continue
        entry["行程明细"].append({
            "行程序号": trip_index,
            "支付记录": list(trip.get("支付记录") or []),
            "账单截图": list(trip.get("账单截图") or []),
        })
    entry["行程明细"].sort(key=lambda item: int(item.get("行程序号", 0)))
    return entry


def normalize_unmatched(item: dict[str, Any]) -> dict[str, str]:
    return {
        "图片": str(item.get("图片") or ""),
        "原因": str(item.get("原因") or ""),
    }


def load_match_record(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_record()
    return normalize_record(json.loads(path.read_text(encoding="utf-8")))


def save_match_record(path: Path, record: dict[str, Any]) -> None:
    path.write_text(json.dumps(normalize_record(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel_path(root: Path, path: Path | str) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.relative_to(root)
        except ValueError:
            pass
    return p.as_posix()


def invoice_key(filename: str) -> str:
    return f"invoices/{filename}"


def image_key(root: Path, image_path: Path | str) -> str:
    rel = rel_path(root, image_path)
    if rel.startswith("images/"):
        return rel
    return f"images/{Path(rel).name}"


def ensure_invoice_entry(record: dict[str, Any], inv: dict[str, Any]) -> dict[str, Any]:
    key = invoice_key(str(inv.get("文件名") or ""))
    mapping = record.setdefault("发票映射", {})
    entry = mapping.setdefault(key, {})
    entry.setdefault("发票文件", key)
    entry.setdefault("支付记录", [])
    entry.setdefault("账单截图", [])
    entry.setdefault("行程明细", [])
    entry.setdefault("购买日期", "")
    return entry


def display_index(inv: dict[str, Any]) -> int:
    import re

    updated = str(inv.get("更新后文件名") or "")
    match = re.match(r"^(\d+)_", updated)
    if match:
        return int(match.group(1))
    try:
        return int(inv.get("发票序号", 0)) + 1
    except (TypeError, ValueError):
        return 0


def is_taxi_invoice(inv: dict[str, Any]) -> bool:
    return str(inv.get("行程单文件名") or "").strip() not in ("", "无需", "ERROR")


def money_text(value: Any) -> str:
    try:
        from decimal import Decimal, ROUND_HALF_UP

        return f"{Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
    except Exception:
        return str(value or "")


def ensure_trip_entry(invoice_entry: dict[str, Any], trip_index: int, amount: Any = "") -> dict[str, Any]:
    trips = invoice_entry.setdefault("行程明细", [])
    for trip in trips:
        if int(trip.get("行程序号", 0)) == int(trip_index):
            trip.setdefault("支付记录", [])
            trip.setdefault("账单截图", [])
            return trip
    trip = {
        "行程序号": int(trip_index),
        "支付记录": [],
        "账单截图": [],
    }
    trips.append(trip)
    trips.sort(key=lambda item: int(item.get("行程序号", 0)))
    return trip


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def remove_unmatched(record: dict[str, Any], image: str) -> None:
    record["未匹配截图"] = [item for item in record.get("未匹配截图", []) if item.get("图片") != image]


def add_match(
    record: dict[str, Any],
    invoice_file: str,
    image: str,
    kind: str,
    *,
    trip_index: int | None = None,
    amount: Any = "",
    payment_date: str = "",
) -> None:
    entry = record.setdefault("发票映射", {}).setdefault(invoice_file, {
        "发票文件": invoice_file,
        "支付记录": [],
        "账单截图": [],
        "行程明细": [],
        "购买日期": "",
    })
    if trip_index is None:
        _append_unique(entry.setdefault(kind, []), image)
    else:
        trip = ensure_trip_entry(entry, trip_index, amount)
        _append_unique(trip.setdefault(kind, []), image)
    if kind == "支付记录" and payment_date and not entry.get("购买日期"):
        entry["购买日期"] = payment_date
    remove_unmatched(record, image)


def add_unmatched(record: dict[str, Any], image: str, reason: str) -> None:
    remove_unmatched(record, image)
    record.setdefault("未匹配截图", []).append({"图片": image, "原因": reason})


def mark_ignored(record: dict[str, Any], image: str, reason: str = "") -> None:
    remove_unmatched(record, image)
    ignored = record.setdefault("忽略截图", [])
    if not any(item.get("图片") == image for item in ignored):
        ignored.append({"图片": image, "原因": reason})


def used_images(record: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for entry in record.get("发票映射", {}).values():
        for kind in ("支付记录", "账单截图"):
            result.update(str(item) for item in entry.get(kind, []) if item)
        for trip in entry.get("行程明细", []) or []:
            for kind in ("支付记录", "账单截图"):
                result.update(str(item) for item in trip.get(kind, []) if item)
    result.update(str(item.get("图片")) for item in record.get("忽略截图", []) if item.get("图片"))
    return result


def image_paths(root: Path, values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = root / value
        if path.exists():
            paths.append(path)
    return paths


def invoice_images(entry: dict[str, Any], kind: str) -> list[str]:
    images = list(entry.get(kind, []) or [])
    for trip in entry.get("行程明细", []) or []:
        images.extend(trip.get(kind, []) or [])
    return images
