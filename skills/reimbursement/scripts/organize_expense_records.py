#!/usr/bin/env python3
"""OCR and match reimbursement expense screenshots.

Default mode updates 匹配记录.json.  Screenshots are never copied or
renamed; all references use original paths under images/.
Use --dry-run to preview without writing output files.

OCR cache
    Screenshot content is hashed (SHA-256) and cached in OCR缓存.json.
    Subsequent runs skip re-OCR for unchanged images.  Use --no-cache
    to force a full re-OCR pass.  The cache is never removed by any
    step; delete the file manually to purge it.

Match record
    Matched and unmatched screenshots are written to 匹配记录.json.
    Invoice keys use invoices/<原发票文件名>, image keys use
    images/<原截图文件名>.

Occupancy check
    Only one screenshot per slot is auto-matched.  When a second
    screenshot would claim the same slot, both the existing match and
    the new one are recorded as pending in 匹配记录.json.

    Slots:
        Non-taxi — (invoice_seq, kind)
        Taxi    — (invoice_seq, kind, trip_item_index)

    Manually-confirmed screenshots should be recorded in 匹配记录.json;
    the original images stay under images/.

Non-taxi matching
    OCR amounts extracted from screenshots are compared against
    价税合计金额 in invoice_results_sorted.json.  Unique match → add to
    匹配记录.json.  Zero or multiple matches → 未匹配截图[].

Taxi matching
    Trip-sheet PDFs are read from output/ (classified copies), NOT from
    invoices/.  Each line in the trip sheet is parsed for an item index
    and amount.  Taxi screenshots are matched against individual trip
    line-item amounts, filtered by platform (高德 vs 滴滴).  Successful
    matches are named with the trip-sheet item index suffix (e.g. ``_8``).

Purchase dates
    Extracted from the 支付时间 line in payment-record OCR text and stored
    on the corresponding invoice entry in 匹配记录.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

import pdfplumber
from rapidocr_onnxruntime import RapidOCR

from _pathutil import add_root_arg, resolve_path
from _matching_records import (
    DEFAULT_MATCH_RECORD,
    add_match,
    add_unmatched,
    ensure_invoice_entry,
    image_key,
    invoice_key,
    load_match_record,
    save_match_record,
    used_images,
)


MONEY_RE = re.compile(r"(?<!\d)-?[¥￥]?\d+(?:\.\d{1,2})?(?!\d)")
YUAN_AMOUNT_RE = re.compile(r"(?<!\d)(\d+(?:\.\d{1,2})?)\s*元")
TAXI_WORDS = ("出行", "打车", "滴滴", "花小猪")


@dataclass
class Invoice:
    seq: int
    amount: Decimal
    source_file: str
    updated_file: str
    output_dir: Path
    is_taxi: bool
    trip_file: str
    updated_trip_file: str
    taxi_platform: str
    keywords: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class TripEntry:
    invoice: Invoice
    item_index: int
    amount: Decimal


@dataclass
class ImageMatch:
    image: Path
    kind: str
    ocr_category: str
    taxi_platform: str
    amount: Decimal | None
    invoice: Invoice | None
    target: Path | None
    status: str
    reason: str
    ocr_text: str
    payment_date: str
    trip_item_index: int | None = None


def money(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    if not text or text == "ERROR":
        return None
    try:
        return Decimal(text).copy_abs().quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def money_token(value: Decimal) -> str:
    return f"{value:.2f}"


def extract_keywords(*texts: str) -> set[str]:
    keywords: set[str] = set()
    for text in texts:
        if not text:
            continue
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", text):
            if len(token) >= 2:
                keywords.add(token.lower())
    return keywords


def read_invoices(sorted_json: Path, output_root: Path) -> list[Invoice]:
    data = json.loads(sorted_json.read_text(encoding="utf-8"))
    invoices: list[Invoice] = []
    for inv in data.get("发票信息", []):
        updated = inv.get("更新后文件名") or ""
        match = re.match(r"^(\d+)_", updated)
        if not match:
            continue
        amount = money(inv.get("价税合计金额"))
        if amount is None:
            continue

        output_pdf = next(output_root.glob(f"*/{updated}"), None)
        output_dir = output_pdf.parent if output_pdf else output_root
        items = inv.get("项目列表") or []
        item_text = " ".join(str(item.get("项目名称", "")) for item in items if isinstance(item, dict))
        keywords = extract_keywords(inv.get("销售方名称", ""), item_text, inv.get("文件名", ""))
        platform_text = " ".join(
            str(inv.get(key, ""))
            for key in ("文件名", "更新后文件名", "行程单文件名", "更新后行程单文件名", "销售方名称")
        )
        taxi_platform = "高德" if "高德" in platform_text else "滴滴"

        invoices.append(
            Invoice(
                seq=int(match.group(1)),
                amount=amount,
                source_file=inv.get("文件名", ""),
                updated_file=updated,
                output_dir=output_dir,
                is_taxi=inv.get("行程单文件名") not in ("", "无需", "ERROR"),
                trip_file=inv.get("行程单文件名", ""),
                updated_trip_file=inv.get("更新后行程单文件名", ""),
                taxi_platform=taxi_platform,
                keywords=keywords,
            )
        )
    return invoices


def pdf_text(path: Path) -> str:
    if not path.exists():
        return ""
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def trip_amounts(invoices: Iterable[Invoice], output_root: Path) -> dict[Decimal, list[TripEntry]]:
    amount_to_entries: dict[Decimal, list[TripEntry]] = defaultdict(list)
    for inv in invoices:
        if not inv.is_taxi or not inv.updated_trip_file:
            continue
        trip_path = inv.output_dir / inv.updated_trip_file
        text = pdf_text(trip_path)
        for line in text.splitlines():
            seq_match = re.match(r"\s*(\d+)\s+", line)
            if not seq_match:
                continue
            raw_values = re.findall(r"\d+\.\d{1,2}", line)
            if not raw_values:
                continue
            raw = raw_values[-1]
            value = money(raw)
            if value is None:
                continue
            amount_to_entries[value].append(
                TripEntry(invoice=inv, item_index=int(seq_match.group(1)), amount=value)
            )
    return amount_to_entries


def run_ocr(ocr: RapidOCR, image: Path) -> tuple[str, list]:
    result, _ = ocr(str(image))
    lines = result or []
    texts = [line[1] for line in lines if len(line) >= 2]
    return "\n".join(texts), lines


def valid_amount(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value < Decimal("1.00") or value > Decimal("10000.00"):
        return None
    return value


def bbox_top(bbox: list) -> float:
    return min(point[1] for point in bbox)


def bbox_bottom(bbox: list) -> float:
    return max(point[1] for point in bbox)


def bbox_left(bbox: list) -> float:
    return min(point[0] for point in bbox)


def amount_like_values(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw in re.findall(r"(?<!\d)-?[¥￥]?\d+\.\d{1,2}(?!\d)", text):
        value = valid_amount(money(raw))
        if value is not None:
            values.append(value)
    return values


def numeric_values(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for raw in MONEY_RE.findall(text):
        value = valid_amount(money(raw))
        if value is not None:
            values.append(value)
    return values


def classify_image(ocr_text: str) -> tuple[str, str, str]:
    compact = ocr_text.replace(" ", "")
    if "支付成功" in compact and "费用说明" in compact:
        return "账单截图", "打车账单截图", "高德"
    if "行程已结束" in compact:
        return "账单截图", "打车账单截图", "滴滴"
    if "账单详情" in compact and "高德打车" in compact:
        return "支付记录", "打车支付记录", "高德"
    if "账单" in compact and "滴滴出行" in compact:
        return "支付记录", "打车支付记录", "滴滴"
    if "订单信息" in compact and (
        "微信支付金额" in compact or "支付宝支付金额" in compact or "交易成功" in compact
    ):
        return "账单截图", "非打车账单截图", ""
    if "账单" in compact:
        return "支付记录", "非打车支付记录", ""
    return "支付记录", "非打车支付记录", ""


def classify_kind(ocr_text: str) -> str:
    return classify_image(ocr_text)[0]


def is_taxi_related(ocr_text: str) -> bool:
    return classify_image(ocr_text)[1].startswith("打车")


def extract_payment_date(ocr_text: str) -> str:
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "支付时间" not in line:
            continue
        candidates = lines[index : index + 4]
        for candidate in candidates:
            match = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", candidate)
            if match:
                year, month, day = (int(part) for part in match.groups())
                return f"{year}/{month}/{day}"
    return ""


def choose_amount_by_yaxis(raw_lines: list, keyword: str) -> Decimal | None:
    sf_line = next((line for line in raw_lines if keyword in line[1]), None)
    if not sf_line:
        return None
    sf_bbox = sf_line[0]
    sf_y_top, sf_y_bot = sf_bbox[0][1], sf_bbox[2][1]
    best = None
    best_right = -1
    for bbox, text, conf in raw_lines:
        if keyword in text:
            continue
        ly_top, ly_bot = bbox[0][1], bbox[2][1]
        if max(ly_top, sf_y_top) >= min(ly_bot, sf_y_bot):
            continue
        m = re.search(r'(?:[¥￥])?\s*(\d+\.?\d{0,2})', text)
        if m:
            v = money(m.group(1))
            if v and Decimal("1.00") <= v <= Decimal("10000.00"):
                right_edge = max(p[0] for p in bbox)
                if right_edge > best_right:
                    best_right = right_edge
                    best = v
    return best


def choose_payment_record_amount(raw_lines: list | None) -> Decimal:
    if not raw_lines:
        return Decimal(0)
    payment_time = next((line for line in raw_lines if "支付时间" in line[1]), None)
    upper = bbox_top(payment_time[0]) - 50 if payment_time else float("inf")
    rows = [
        (bbox_top(bbox), bbox_left(bbox), text)
        for bbox, text, conf in raw_lines
        if bbox_top(bbox) >= 150 and bbox_top(bbox) < upper
    ]
    rows.sort()
    fallback: Decimal | None = None
    for _, _, text in rows:
        values = amount_like_values(text)
        if values:
            return values[0]
        if fallback is None:
            numeric = numeric_values(text)
            if numeric:
                fallback = numeric[0]
    return fallback or Decimal(0)


def choose_gaode_trip_bill_amount(raw_lines: list | None) -> Decimal:
    if not raw_lines:
        return Decimal(0)
    invoice_line = next((line for line in raw_lines if "开发票" in line[1]), None)
    fee_line = next((line for line in raw_lines if "费用说明" in line[1]), None)
    if not invoice_line or not fee_line:
        return Decimal(0)
    lower = bbox_bottom(invoice_line[0])
    upper = bbox_top(fee_line[0])
    if lower >= upper:
        return Decimal(0)
    values: list[Decimal] = []
    for bbox, text, conf in raw_lines:
        top = bbox_top(bbox)
        if lower < top < upper:
            for raw in YUAN_AMOUNT_RE.findall(text):
                value = valid_amount(money(raw))
                if value is not None:
                    values.append(value)
    return max(values) if values else Decimal(0)


def choose_didi_trip_bill_amount(raw_lines: list | None) -> Decimal:
    if not raw_lines:
        return Decimal(0)
    fee_line = next((line for line in raw_lines if "费用明细" in line[1]), None)
    if not fee_line:
        return Decimal(0)
    center = (bbox_top(fee_line[0]) + bbox_bottom(fee_line[0])) / 2
    lower = center - 100
    upper = center + 50
    values: list[Decimal] = []
    for bbox, text, conf in raw_lines:
        top = bbox_top(bbox)
        if lower <= top <= upper:
            values.extend(numeric_values(text))
    return max(values) if values else Decimal(0)


def choose_amount(ocr_text: str, ocr_category: str, taxi_platform: str, raw_lines: list | None = None) -> Decimal:
    if ocr_category == "非打车账单截图":
        pay_amount_match = re.search(
            r"(?:微信支付金额|支付宝支付金额)[：:]\s*(\d+(?:\.\d{1,2})?)",
            ocr_text,
        )
        if pay_amount_match:
            value = money(pay_amount_match.group(1))
            if value:
                return value
        if raw_lines:
            for kw in ("实付款", "合计"):
                v = choose_amount_by_yaxis(raw_lines, kw)
                if v:
                    return v
        return Decimal(0)
    if ocr_category.endswith("支付记录"):
        return choose_payment_record_amount(raw_lines)
    if ocr_category == "打车账单截图" and taxi_platform == "高德":
        return choose_gaode_trip_bill_amount(raw_lines)
    if ocr_category == "打车账单截图" and taxi_platform == "滴滴":
        return choose_didi_trip_bill_amount(raw_lines)
    return Decimal(0)


def choose_unique_invoice(candidates: list[Invoice]) -> tuple[Invoice | None, str]:
    unique_candidates: dict[int, Invoice] = {}
    for candidate in candidates:
        unique_candidates[candidate.seq] = candidate
    candidates = list(unique_candidates.values())
    if not candidates:
        return None, "没有金额匹配的发票"
    if len(candidates) == 1:
        return candidates[0], "金额唯一匹配"
    candidate_names = ", ".join(inv.updated_file for inv in candidates)
    return None, f"金额对应多个候选发票，交由后处理视觉识别：{candidate_names}"


def choose_unique_trip(candidates: list[TripEntry], platform: str = "") -> tuple[TripEntry | None, str]:
    if platform:
        candidates = [candidate for candidate in candidates if candidate.invoice.taxi_platform == platform]
    unique_candidates: dict[tuple[int, int], TripEntry] = {}
    for candidate in candidates:
        unique_candidates[(candidate.invoice.seq, candidate.item_index)] = candidate
    candidates = list(unique_candidates.values())
    if not candidates:
        platform_text = f"{platform} " if platform else ""
        return None, f"没有金额匹配的{platform_text}行程"
    if len(candidates) == 1:
        candidate = candidates[0]
        return candidate, f"打车行程单第 {candidate.item_index} 条金额唯一匹配"
    candidate_names = ", ".join(
        f"{entry.invoice.updated_file}#行程{entry.item_index}" for entry in candidates
    )
    return None, f"金额对应多个候选行程，交由后处理视觉识别：{candidate_names}"


def next_target_path(base: Path, used: set[Path], allow_existing: bool = False) -> Path:
    if allow_existing and base not in used:
        used.add(base)
        return base
    if base not in used and not base.exists():
        used.add(base)
        return base
    stem = base.stem
    suffix = base.suffix
    index = 1
    while True:
        candidate = base.with_name(f"{stem}_{index}{suffix}")
        if allow_existing and candidate not in used:
            used.add(candidate)
            return candidate
        if candidate not in used and not candidate.exists():
            used.add(candidate)
            return candidate
        index += 1


def assign_targets(matches: list[ImageMatch], records_root: Path, overwrite: bool) -> None:
    groups: dict[tuple[int, str, str], list[ImageMatch]] = defaultdict(list)
    for match in matches:
        if match.status == "copy" and match.invoice is not None:
            key = (match.invoice.seq, match.kind)
            groups[key].append(match)

    used_targets: set[Path] = set()
    for group in groups.values():
        group.sort(key=lambda match: match.image.name)
        multiple = len(group) > 1
        for index, match in enumerate(group, 1):
            assert match.invoice is not None
            stem = f"{match.invoice.seq}_{match.kind}"
            if match.invoice.is_taxi and match.trip_item_index is not None:
                stem = f"{stem}_{match.trip_item_index}"
            elif multiple:
                stem = f"{stem}_{index}"
            category = match.invoice.output_dir.name if match.invoice.output_dir.name else "未分类"
            base = records_root / category / f"{stem}{match.image.suffix.lower()}"
            match.target = next_target_path(base, used_targets, allow_existing=overwrite)

    pending = [match for match in matches if match.status == "pending"]
    for match in pending:
        subdir = "打车" if match.ocr_category.startswith("打车") else "非打车"
        price_tag = f"_{money_token(match.amount)}" if match.amount is not None else ""
        base = records_root / "待人工识别" / subdir / f"待识别{price_tag}_{match.image.name}"
        match.target = next_target_path(base, used_targets, allow_existing=overwrite)


def match_images(args: argparse.Namespace) -> tuple[list[ImageMatch], list[Invoice], list[TripEntry]]:
    invoices = read_invoices(args.sorted_json, args.output)
    amount_to_invoices: dict[Decimal, list[Invoice]] = defaultdict(list)
    for inv in invoices:
        if not inv.is_taxi:
            amount_to_invoices[inv.amount].append(inv)
    invoice_amounts = set(amount_to_invoices)
    trip_index = trip_amounts(invoices, args.output)

    # Pre-scan images
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
    images_list = sorted([p for p in args.images.glob("*") if p.suffix.lower() in IMAGE_EXTS])
    total = len(images_list)

    # Load OCR cache
    cache: dict[str, dict] = {}
    if not args.no_cache and args.cache_file.exists():
        cache = json.loads(args.cache_file.read_text(encoding="utf-8"))

    if not args.no_cache:
        args.cache_file.parent.mkdir(parents=True, exist_ok=True)

    ocr = RapidOCR()
    matches: list[ImageMatch] = []
    occupied_non_taxi: dict[tuple[int, str], int] = {}
    occupied_taxi: dict[tuple[int, str, int], int] = {}
    for idx, image in enumerate(images_list, 1):

        if idx % 10 == 0:
            print(f"已处理 {idx}/{len(images_list)} 张图片")

        file_hash = hashlib.sha256(image.read_bytes()).hexdigest()
        image_rel = image_key(args.root, image)

        cached_entry = cache.get(image_rel)
        if cached_entry is None and file_hash in cache:
            # Legacy cache compatibility: old versions keyed OCR cache by SHA256.
            cached_entry = cache[file_hash]
            cached_entry["sha256"] = file_hash
            cached_entry["image"] = image_rel
            cache[image_rel] = cached_entry

        if not args.no_cache and cached_entry is not None and cached_entry.get("sha256", file_hash) == file_hash:
            c = cached_entry
            ocr_text = c["ocr_text"]
            raw_lines = c["ocr_boxes"]
            kind, ocr_category, taxi_platform = classify_image(ocr_text)
            payment_date = extract_payment_date(ocr_text) if kind == "支付记录" else ""
            amount = choose_amount(ocr_text, ocr_category, taxi_platform, raw_lines)
            c["kind"] = kind
            c["ocr_category"] = ocr_category
            c["taxi_platform"] = taxi_platform
            c["amounts"] = str(amount) if amount is not None else ""
            if payment_date:
                c["payment_date"] = payment_date
        else:
            ocr_text, raw_lines = run_ocr(ocr, image)
            kind, ocr_category, taxi_platform = classify_image(ocr_text)
            payment_date = extract_payment_date(ocr_text) if kind == "支付记录" else ""
            amount = choose_amount(ocr_text, ocr_category, taxi_platform, raw_lines)
            if not args.no_cache:
                cache[image_rel] = {
                    "image": image_rel,
                    "sha256": file_hash,
                    "ocr_text": ocr_text,
                    "ocr_boxes": raw_lines,
                    "amounts": str(amount) if amount is not None else "",
                    "ocr_category": ocr_category,
                    "kind": kind,
                    "taxi_platform": taxi_platform,
                    "payment_date": payment_date,
                }
        is_taxi = ocr_category.startswith("打车")

        invoice: Invoice | None = None
        trip_item_index: int | None = None
        reason = ""
        if amount is None:
            reason = "OCR 未识别到有效金额"
        elif is_taxi and amount in trip_index:
            candidates = trip_index[amount]
            trip_entry, reason = choose_unique_trip(candidates, taxi_platform)
            if trip_entry is not None:
                invoice = trip_entry.invoice
                trip_item_index = trip_entry.item_index
        elif amount in amount_to_invoices:
            invoice, reason = choose_unique_invoice(amount_to_invoices[amount])
        else:
            reason = f"金额 {amount:.2f} 不匹配任何发票或打车行程"

        status = "pending"
        if invoice is not None:
            status = "copy"

        if status == "copy" and invoice is not None:
            if is_taxi and trip_item_index is not None:
                slot = (invoice.seq, kind, trip_item_index)
                occupied = occupied_taxi
            else:
                slot = (invoice.seq, kind)
                occupied = occupied_non_taxi
            if slot in occupied:
                prev_idx = occupied[slot]
                prev = matches[prev_idx]
                prev.status = "pending"
                prev.reason = f"与截图 {image.name} 同时匹配同一发票，需人工识别"
                status = "pending"
                invoice = None
                trip_item_index = None
                reason = f"与截图 {prev.image.name} 同时匹配同一发票，需人工识别"
            else:
                occupied[slot] = len(matches)

        matches.append(
            ImageMatch(
                image=image,
                kind=kind,
                ocr_category=ocr_category,
                taxi_platform=taxi_platform,
                amount=amount,
                invoice=invoice,
                target=None,
                status=status,
                reason=reason,
                ocr_text=ocr_text,
                payment_date=payment_date,
                trip_item_index=trip_item_index,
            )
        )

        # Persist cache immediately after each image to survive crashes
        if not args.no_cache:
            args.cache_file.write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    all_trip_entries: list[TripEntry] = []
    seen_trips: set[tuple[int, int]] = set()
    for entries in trip_index.values():
        for entry in entries:
            key = (entry.invoice.seq, entry.item_index)
            if key not in seen_trips:
                seen_trips.add(key)
                all_trip_entries.append(entry)

    return matches, invoices, all_trip_entries


def unmatched_invoices(matches: list[ImageMatch], invoices: list[Invoice]) -> list[Invoice]:
    matched_seq = {match.invoice.seq for match in matches if match.status == "copy" and match.invoice is not None}
    return [inv for inv in invoices if inv.seq not in matched_seq]


AI_REPORT_NAME = "支出记录OCR匹配明细.md"
HUMAN_REPORT_NAME = "支出记录OCR整理结果.md"

IMAGE_RE = re.compile(r"^(\d+)_(支付记录|账单截图)(?:_\d+)?\.(?:jpe?g|png)$", re.IGNORECASE)
PENDING_RE = re.compile(r"^待识别_(\d+(?:\.\d{1,2})?)_(.+)$")


def write_ai_report(matches: list[ImageMatch], root: Path, applied: bool) -> None:
    """Pending-only screenshot list — for AI/人工 diagnosis."""
    path = root / AI_REPORT_NAME
    lines: list[str] = [
        "# 支出记录 OCR 待处理截图明细",
        "",
        f"模式：{'已复制' if applied else 'dry-run'}",
        "",
        "## 待人工识别截图",
        "",
    ]
    pending = [match for match in matches if match.status == "pending"]
    if pending:
        lines.extend(["| 原图片 | OCR金额 | 类型 | 图片路径 | 原因 |", "| --- | ---: | --- | --- | --- |"])
        for match in pending:
            amount = f"{match.amount:.2f}" if match.amount is not None else ""
            lines.append(f"| `{match.image.name}` | {amount} | {match.ocr_category} | `{image_key(root, match.image)}` | {match.reason} |")
    else:
        lines.append("无。")

    path.write_text("\n".join(lines), encoding="utf-8")


def report_only(args: argparse.Namespace) -> None:
    """Regenerate reports from current filesystem state — no OCR, no matching."""
    invoices = read_invoices(args.sorted_json, args.output)

    # Scan matched files in 1_材料费/ and 2_打车费/
    matched: dict[int, set[str]] = defaultdict(set)
    matched_trips: set[tuple[int, int]] = set()
    for root_dir in (args.records_root / "1_材料费", args.records_root / "2_打车费"):
        if not root_dir.exists():
            continue
        for p in root_dir.iterdir():
            m = IMAGE_RE.match(p.name)
            if not m:
                continue
            seq = int(m.group(1))
            kind = m.group(2)
            matched[seq].add(kind)
            # For taxi, also track trip item index
            parts = p.stem.split("_")
            if len(parts) >= 3 and parts[2].isdigit():
                matched_trips.add((seq, int(parts[2])))

    # Read trip entries from 行程单数据.json
    trip_path = args.root / "行程单数据.json"
    all_trip_entries: list[TripEntry] = []
    if trip_path.exists():
        trips_dict = json.loads(trip_path.read_text(encoding="utf-8"))
        for fname, trip_list in trips_dict.items():
            if not isinstance(trip_list, list):
                continue
            for trip in trip_list:
                seq = trip.get("发票输出序号")
                item_index = trip.get("序号")
                amount = money(trip.get("金额"))
                if seq is None or item_index is None or amount is None:
                    continue
                inv = next((inv for inv in invoices if inv.seq == seq), None)
                if inv is None:
                    continue
                all_trip_entries.append(TripEntry(invoice=inv, item_index=item_index, amount=amount))

    # Scan pending files in 待人工识别/
    pending_matches: list[ImageMatch] = []
    for subdir in ("打车", "非打车"):
        pending_dir = args.records_root / "待人工识别" / subdir
        if not pending_dir.exists():
            continue
        for p in sorted(pending_dir.iterdir()):
            m = PENDING_RE.match(p.name)
            amount = money(m.group(1)) if m else None
            ocr_category = f"打车" if subdir == "打车" else "非打车"
            pending_matches.append(ImageMatch(
                image=p,
                kind="",
                ocr_category=ocr_category,
                taxi_platform="",
                amount=amount,
                invoice=None,
                target=p,
                status="pending",
                reason="",
                ocr_text="",
                payment_date="",
            ))

    # Build fake matches list for write_human_report completeness check
    fake_matches: list[ImageMatch] = []
    for inv in invoices:
        for kind in matched.get(inv.seq, set()):
            fake_matches.append(ImageMatch(
                image=Path(""),
                kind=kind,
                ocr_category="",
                taxi_platform="",
                amount=None,
                invoice=inv,
                target=None,
                status="copy",
                reason="",
                ocr_text="",
                payment_date="",
            ))

    write_human_report(fake_matches + pending_matches, invoices, all_trip_entries, args.root, True)
    write_ai_report(fake_matches + pending_matches, args.root, True)
    print(f"报告已更新：{AI_REPORT_NAME}、{HUMAN_REPORT_NAME}")


def write_human_report(matches: list[ImageMatch], invoices: list[Invoice], all_trip_entries: list[TripEntry], root: Path, applied: bool) -> None:
    """Summary tables for human review."""
    path = root / HUMAN_REPORT_NAME
    missing_invoices = unmatched_invoices(matches, invoices)
    lines: list[str] = [
        "# 支出记录 OCR 整理结果",
        "",
        f"模式：{'已复制' if applied else 'dry-run'}",
    ]

    lines.extend(["", "## 未匹配到截图的发票", ""])
    if missing_invoices:
        lines.extend(["| 发票 | 金额 | 类型 |", "| --- | ---: | --- |"])
        for inv in missing_invoices:
            kind = "打车费" if inv.is_taxi else "材料费"
            lines.append(f"| `{inv.updated_file}` | {inv.amount:.2f} | {kind} |")
    else:
        lines.append("无。")

    matched_by_inv: dict[int, set[str]] = defaultdict(set)
    for match in matches:
        if match.status == "copy" and match.invoice is not None:
            matched_by_inv[match.invoice.seq].add(match.kind)
    incomplete: list[tuple[Invoice, str]] = []
    for inv in invoices:
        kinds = matched_by_inv.get(inv.seq, set())
        if not kinds:
            continue
        if "支付记录" not in kinds:
            incomplete.append((inv, "支付记录"))
        if "账单截图" not in kinds:
            incomplete.append((inv, "账单截图"))
    lines.extend(["", "## 截图不完整的发票", ""])
    if incomplete:
        lines.extend(["| 发票 | 金额 | 类型 | 缺失截图 |", "| --- | ---: | --- | --- |"])
        for inv, missing_kind in incomplete:
            kind_label = "打车费" if inv.is_taxi else "材料费"
            lines.append(f"| `{inv.updated_file}` | {inv.amount:.2f} | {kind_label} | {missing_kind} |")
    else:
        lines.append("无。")

    matched_trips: set[tuple[int, int]] = set()
    for match in matches:
        if match.status == "copy" and match.invoice is not None and match.trip_item_index is not None:
            matched_trips.add((match.invoice.seq, match.trip_item_index))
    unmatched_trips = [entry for entry in all_trip_entries if (entry.invoice.seq, entry.item_index) not in matched_trips]
    lines.extend(["", "## 未匹配到截图的行程单明细", ""])
    if unmatched_trips:
        lines.extend(["| 行程所属发票 | 行程序号 | 金额 |", "| --- | ---: | ---: |"])
        for entry in unmatched_trips:
            lines.append(f"| `{entry.invoice.updated_file}` | {entry.item_index} | {entry.amount:.2f} |")
    else:
        lines.append("无。")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_purchase_dates(matches: list[ImageMatch], path: Path) -> None:
    dates: dict[str, str] = {}
    payment_matches = [
        match
        for match in matches
        if match.status == "copy"
        and match.invoice is not None
        and match.kind == "支付记录"
        and match.payment_date
    ]
    payment_matches.sort(key=lambda match: str(match.target or match.image.name))
    for match in payment_matches:
        assert match.invoice is not None
        dates.setdefault(match.invoice.updated_file, match.payment_date)
    path.write_text(json.dumps(dates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def invoice_as_dict(inv: Invoice) -> dict[str, object]:
    return {
        "文件名": inv.source_file,
        "更新后文件名": inv.updated_file,
        "价税合计金额": str(inv.amount),
        "行程单文件名": inv.trip_file or "无需",
        "更新后行程单文件名": inv.updated_trip_file,
    }


def update_match_record(matches: list[ImageMatch], invoices: list[Invoice], root: Path, path: Path) -> dict:
    record = load_match_record(path)
    for inv in invoices:
        ensure_invoice_entry(record, invoice_as_dict(inv))

    already_used = used_images(record)
    for match in matches:
        image_rel = image_key(root, match.image)
        if image_rel in already_used:
            continue
        if match.status == "copy" and match.invoice is not None:
            add_match(
                record,
                invoice_key(match.invoice.source_file),
                image_rel,
                match.kind,
                trip_index=match.trip_item_index,
                amount=match.amount,
                payment_date=match.payment_date,
            )
        elif match.status == "pending":
            add_unmatched(record, image_rel, match.reason)
    save_match_record(path, record)
    return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--images", type=Path, default=Path("images"))
    parser.add_argument("--invoices-dir", type=Path, default=Path("invoices"))
    parser.add_argument("--sorted-json", type=Path, default=Path("invoice_results_sorted.json"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--records-root", type=Path, default=Path("支出记录整理"), help="deprecated; kept for CLI compatibility")
    parser.add_argument("--match-record", type=Path, default=DEFAULT_MATCH_RECORD)
    parser.add_argument("--purchase-dates", type=Path, default=Path("支出记录购买日期.json"), help="deprecated; dates are stored in 匹配记录.json")
    scan_group = parser.add_mutually_exclusive_group()
    scan_group.add_argument("--no-cache", action="store_true", help="skip OCR cache, force full OCR")
    scan_group.add_argument("--scan-only", action="store_true", help="process only new images (not in cache): update 匹配记录.json, print conflicts/unmatched")
    parser.add_argument("--cache-file", type=Path, default=Path("OCR缓存.json"))
    parser.add_argument("--dry-run", action="store_true", help="preview matches without copying files")
    parser.add_argument("--no-clean", action="store_true", help="keep existing records-root and report before running")
    parser.add_argument("--overwrite", action="store_true", help="allow overwriting existing target files when --no-clean is used")
    parser.add_argument("--report-only", action="store_true", help="regenerate reports from filesystem state without OCR or matching")
    return parser.parse_args()


def clean_previous_outputs(root: Path, records_root: Path, purchase_dates_path: Path) -> None:
    """Remove stale OCR outputs before a normal run."""
    removed: list[str] = []
    for name in (HUMAN_REPORT_NAME, AI_REPORT_NAME):
        p = root / name
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if removed:
        print("cleaned=" + ",".join(removed))


def print_scan_report(matches: list[ImageMatch], root: Path) -> None:
    """Print actionable scan results for new images — no file changes."""
    copy_matches = [m for m in matches if m.status == "copy" and m.invoice is not None]
    pending_matches = [m for m in matches if m.status == "pending"]

    print("# 扫描结果 — 新增图片处理方法\n")

    if copy_matches:
        print("## 可自动匹配")
        print("| 图片 | 金额 | 分类 | 匹配记录 |")
        print("| --- | ---: | --- | --- |")
        for m in copy_matches:
            assert m.invoice is not None
            target = f"{invoice_key(m.invoice.source_file)} / {m.kind}"
            if m.trip_item_index is not None:
                target += f" / 行程{m.trip_item_index}"
            print(f"| `{m.image.name}` | {m.amount or ''} | {m.ocr_category} | `{target}` |")
        print()

    if pending_matches:
        pending_non_conflict = [m for m in pending_matches if "同时匹配" not in m.reason]
        pending_conflict = [m for m in pending_matches if "同时匹配" in m.reason]
        if pending_non_conflict:
            print("## 待人工识别")
            print("| 图片 | 金额 | 分类 | 原因 |")
            print("| --- | ---: | --- | --- |")
            for m in pending_non_conflict:
                print(f"| `{m.image.name}` | {m.amount or ''} | {m.ocr_category} | {m.reason} |")
            print()
        if pending_conflict:
            print("## 冲突（已有截图占用同一槽位）")
            print("| 图片 | 金额 | 分类 | 原因 |")
            print("| --- | ---: | --- | --- |")
            for m in pending_conflict:
                print(f"| `{m.image.name}` | {m.amount or ''} | {m.ocr_category} | {m.reason} |")
            print()

    if not copy_matches and not pending_matches:
        print("无新增图片需要处理。\n")


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    args.images = resolve_path(root, args.images)
    args.invoices_dir = resolve_path(root, args.invoices_dir)
    args.sorted_json = resolve_path(root, args.sorted_json)
    args.output = resolve_path(root, args.output)
    args.records_root = resolve_path(root, args.records_root)
    args.match_record = resolve_path(root, args.match_record)
    args.purchase_dates = resolve_path(root, args.purchase_dates)
    args.cache_file = resolve_path(root, args.cache_file)
    apply_changes = not args.dry_run and not args.scan_only
    no_clean = args.no_clean or args.scan_only

    if args.report_only:
        report_only(args)
        return 0

    # Snapshot cached hashes before processing (for scan-only)
    cached_images_before: set[str] = set()
    if args.scan_only and args.cache_file.exists():
        cached_images_before = {key for key in json.loads(args.cache_file.read_text(encoding="utf-8")).keys() if key.startswith("images/")}

    if apply_changes and not no_clean:
        clean_previous_outputs(root, args.records_root, args.purchase_dates)

    matches, invoices, all_trip_entries = match_images(args)

    if args.scan_only:
        new_matches = [
            m for m in matches
            if image_key(root, m.image) not in cached_images_before
        ]
        update_match_record(new_matches, invoices, root, args.match_record)
        print_scan_report(new_matches, root)
        return 0

    if apply_changes:
        update_match_record(matches, invoices, root, args.match_record)

    write_ai_report(matches, root, apply_changes)
    write_human_report(matches, invoices, all_trip_entries, root, apply_changes)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
