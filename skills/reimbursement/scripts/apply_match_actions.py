#!/usr/bin/env python3
"""Apply screenshot match actions to 匹配记录.json.

Subagents write small action JSON files. This script is the only place that
merges those actions into the match record, so structural rules stay
consistent across agents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _matching_records import DEFAULT_MATCH_RECORD, load_match_record, mark_ignored, remove_unmatched, save_match_record
from _pathutil import add_root_arg, resolve_path


SLOTS = {"支付记录", "账单截图"}
BEARING_AGENT = "fix-bearing-invoice"


class ActionError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_image_path(value: Any) -> str:
    image = str(value or "")
    if not image:
        raise ActionError("image is required")
    if "\\" in image or image.startswith("/") or ":" in image:
        raise ActionError(f"image path must be project-relative POSIX style: {image}")
    if not image.startswith("images/") or image.count("/") != 1:
        raise ActionError(f"image path must look like images/<filename>: {image}")
    return image


def validate_invoice_path(value: Any) -> str:
    invoice = str(value or "")
    if not invoice:
        raise ActionError("invoice is required")
    if "\\" in invoice or invoice.startswith("/") or ":" in invoice:
        raise ActionError(f"invoice path must be project-relative POSIX style: {invoice}")
    if not invoice.startswith("invoices/") or invoice.count("/") != 1:
        raise ActionError(f"invoice path must look like invoices/<filename>: {invoice}")
    return invoice


def validate_slot(value: Any) -> str:
    slot = str(value or "")
    if slot not in SLOTS:
        raise ActionError(f"slot must be one of {sorted(SLOTS)}")
    return slot


def load_invoice_keys(sorted_json: Path) -> set[str]:
    if not sorted_json.exists():
        return set()
    data = read_json(sorted_json)
    return {f"invoices/{item.get('文件名')}" for item in data.get("发票信息", []) if item.get("文件名")}


def ensure_invoice_entry(record: dict[str, Any], invoice: str) -> dict[str, Any]:
    entry = record.setdefault("发票映射", {}).setdefault(invoice, {})
    entry.setdefault("发票文件", invoice)
    entry.setdefault("支付记录", [])
    entry.setdefault("账单截图", [])
    entry.setdefault("行程明细", [])
    entry.setdefault("购买日期", "")
    return entry


def ensure_trip_entry(entry: dict[str, Any], trip_seq: Any) -> dict[str, Any]:
    try:
        seq = int(trip_seq)
    except (TypeError, ValueError) as exc:
        raise ActionError(f"trip_seq must be a positive integer: {trip_seq}") from exc
    if seq <= 0:
        raise ActionError(f"trip_seq must be a positive integer: {trip_seq}")
    trips = entry.setdefault("行程明细", [])
    for trip in trips:
        if int(trip.get("行程序号", 0) or 0) == seq:
            trip.setdefault("支付记录", [])
            trip.setdefault("账单截图", [])
            return trip
    trip = {"行程序号": seq, "支付记录": [], "账单截图": []}
    trips.append(trip)
    trips.sort(key=lambda item: int(item.get("行程序号", 0) or 0))
    return trip


def remove_from_ignored(record: dict[str, Any], image: str) -> None:
    record["忽略截图"] = [item for item in record.get("忽略截图", []) if item.get("图片") != image]


def allow_multiple(payload: dict[str, Any], action: dict[str, Any]) -> bool:
    if payload.get("agent") != BEARING_AGENT:
        return False
    if not (payload.get("allow_multiple_same_slot") or action.get("allow_multiple_same_slot")):
        return False
    return bool(str(action.get("exception_reason") or payload.get("exception_reason") or "").strip())


def assign_to_slot(
    record: dict[str, Any],
    container: dict[str, Any],
    slot: str,
    image: str,
    action: dict[str, Any],
    *,
    multiple_allowed: bool,
) -> list[str]:
    changes: list[str] = []
    images = list(container.get(slot) or [])
    replace = str(action.get("replace") or "")
    if replace:
        replace = validate_image_path(replace)

    if image in images:
        remove_unmatched(record, image)
        remove_from_ignored(record, image)
        return [f"kept existing {slot}: {image}"]

    if images and not multiple_allowed:
        if not replace:
            raise ActionError(f"{slot} already has {images}; provide replace to keep exactly one image")
        if replace not in images:
            raise ActionError(f"replace image {replace} is not currently in {slot}: {images}")
        images = [item for item in images if item != replace]
        if action.get("ignore_replaced", True):
            reason = str(action.get("replace_reason") or action.get("reason") or f"同一位置被 {image} 替换")
            mark_ignored(record, replace, reason)
        changes.append(f"replaced {replace} with {image} in {slot}")

    images.append(image)
    container[slot] = images
    remove_unmatched(record, image)
    remove_from_ignored(record, image)
    if not changes:
        changes.append(f"assigned {image} to {slot}")
    return changes


def apply_action(
    record: dict[str, Any],
    payload: dict[str, Any],
    action: dict[str, Any],
    invoice_keys: set[str],
    root: Path,
) -> list[str]:
    action_type = str(action.get("type") or "")
    if action_type == "ignore_image":
        image = validate_image_path(action.get("image"))
        if not (root / image).exists():
            raise ActionError(f"image does not exist: {image}")
        mark_ignored(record, image, str(action.get("reason") or ""))
        return [f"ignored {image}"]

    if action_type not in {"assign_invoice_image", "assign_trip_image"}:
        raise ActionError(f"unsupported action type: {action_type}")

    invoice = validate_invoice_path(action.get("invoice"))
    image = validate_image_path(action.get("image"))
    slot = validate_slot(action.get("slot"))
    if invoice_keys and invoice not in invoice_keys:
        raise ActionError(f"invoice not found in invoice_results_sorted.json: {invoice}")
    if not (root / image).exists():
        raise ActionError(f"image does not exist: {image}")
    entry = ensure_invoice_entry(record, invoice)
    if action.get("purchase_date") and slot == "支付记录":
        entry["购买日期"] = str(action.get("purchase_date"))

    multiple_allowed = allow_multiple(payload, action)
    if action_type == "assign_invoice_image":
        return apply_invoice_action(record, entry, slot, image, action, multiple_allowed=multiple_allowed)

    trip = ensure_trip_entry(entry, action.get("trip_seq"))
    if action.get("purchase_date") and slot == "支付记录":
        entry["购买日期"] = str(action.get("purchase_date"))
    return assign_to_slot(record, trip, slot, image, action, multiple_allowed=multiple_allowed)


def apply_invoice_action(
    record: dict[str, Any],
    entry: dict[str, Any],
    slot: str,
    image: str,
    action: dict[str, Any],
    *,
    multiple_allowed: bool,
) -> list[str]:
    if entry.get("行程明细") and not multiple_allowed:
        raise ActionError("invoice-level assignment is not allowed for invoices that already have trip details")
    return assign_to_slot(record, entry, slot, image, action, multiple_allowed=multiple_allowed)


def slot_counts(record: dict[str, Any]) -> dict[tuple[str, int, str], int]:
    counts: dict[tuple[str, int, str], int] = {}
    for invoice, entry in record.get("发票映射", {}).items():
        for slot in SLOTS:
            counts[(invoice, 0, slot)] = len(entry.get(slot) or [])
        for trip in entry.get("行程明细", []) or []:
            seq = int(trip.get("行程序号", 0) or 0)
            for slot in SLOTS:
                counts[(invoice, seq, slot)] = len(trip.get(slot) or [])
    return counts


def validate_unique_slots(
    record: dict[str, Any], payload: dict[str, Any], existing_counts: dict[tuple[str, int, str], int]
) -> None:
    if payload.get("agent") == BEARING_AGENT and payload.get("allow_multiple_same_slot"):
        return
    for invoice, entry in record.get("发票映射", {}).items():
        for slot in SLOTS:
            images = list(entry.get(slot) or [])
            if len(images) > max(1, existing_counts.get((invoice, 0, slot), 0)):
                raise ActionError(f"{invoice} has multiple {slot}: {images}")
        for trip in entry.get("行程明细", []) or []:
            seq = trip.get("行程序号")
            for slot in SLOTS:
                images = list(trip.get(slot) or [])
                if len(images) > max(1, existing_counts.get((invoice, int(seq or 0), slot), 0)):
                    raise ActionError(f"{invoice} trip {seq} has multiple {slot}: {images}")


def apply_payload(record: dict[str, Any], payload: dict[str, Any], invoice_keys: set[str], root: Path) -> list[str]:
    if not isinstance(payload, dict):
        raise ActionError("action file must contain a JSON object")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise ActionError("action file must contain an actions list")
    existing_counts = slot_counts(record)
    changes: list[str] = []
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ActionError(f"action #{index} must be an object")
        try:
            changes.extend(apply_action(record, payload, action, invoice_keys, root))
        except ActionError as exc:
            raise ActionError(f"action #{index}: {exc}") from exc
    validate_unique_slots(record, payload, existing_counts)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--actions", type=Path, required=True, help="Subagent action JSON file")
    parser.add_argument("--match-record", type=Path, default=DEFAULT_MATCH_RECORD)
    parser.add_argument("--sorted-json", type=Path, default=Path("invoice_results_sorted.json"))
    args = parser.parse_args()

    root = args.root.resolve()
    actions_path = resolve_path(root, args.actions)
    record_path = resolve_path(root, args.match_record)
    sorted_json = resolve_path(root, args.sorted_json)

    try:
        payload = read_json(actions_path)
        record = load_match_record(record_path)
        invoice_keys = load_invoice_keys(sorted_json)
        changes = apply_payload(record, payload, invoice_keys, root)
        save_match_record(record_path, record)
    except (OSError, json.JSONDecodeError, ActionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"applied {len(payload.get('actions', []))} actions from {actions_path.name}")
    for change in changes:
        print(f"- {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
