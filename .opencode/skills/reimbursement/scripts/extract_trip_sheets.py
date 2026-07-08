#!/usr/bin/env python3
"""Extract trip data from all 行程单 PDFs in output/2_打车费/.

Reads each *行程单.pdf with pdftotext -layout, parses the table-like
format, and writes 行程单数据.json with structured trip records.

Usage:
    python reimbursement/scripts/extract_trip_sheets.py --root .
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from _pathutil import add_root_arg, resolve_path


# Fixed-width column positions (approximate, in characters):
# 序号(4) 服务商(10) 车型(8) 上车时间(22) 城市(8) 起点+终点(...) 金额(10)
# We parse by splitting on 2+ spaces from the right, then reconstruct.
TRIP_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s{2,}(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s{2,}(\S+)\s{2,}(.+?)\s{2,}(\d+\.?\d*).*$"
)


def extract_trips(pdf_path: Path) -> list[dict]:
    """Parse all trips from one 行程单 PDF."""
    try:
        text = subprocess.check_output(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
    except FileNotFoundError:
        raise RuntimeError("pdftotext not found; install poppler-utils")
    except subprocess.CalledProcessError:
        return []

    lines = text.split("\n")

    # Detect format: 滴滴/花小猪 show platform name in header
    is_didi = any(kw in text for kw in ["滴滴出行", "花小猪打车"])
    if is_didi:
        return _extract_didi(lines)
    else:
        return _extract_gaode(lines)


def _extract_didi(lines: list[str]) -> list[dict]:
    """Parse 滴滴/花小猪 format: 序号 车型 上车时间 城市 起点 终点 里程 金额 备注"""
    trips: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        m = re.match(r"^\s*(\d+)\s+", line)
        if not m:
            continue

        # Split by 2+ spaces
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) < 6:
            continue

        seq = int(cols[0])

        # For 滴滴/花小猪: cols[1]=车型, cols[2]=上车时间(MM-DD HH:MM 周X),
        # cols[3]=城市, cols[4]+=起点终点, last=金额
        car_type = cols[1].strip() if len(cols) > 1 else ""
        time_str = cols[2].strip() if len(cols) > 2 else ""

        # Extract amount from last column
        amount = 0.0
        amt_match = re.search(r"(\d+\.?\d*)", cols[-1])
        if amt_match:
            amount = float(amt_match.group(1))

        # Everything between cols[3] and cols[-2] is route
        route_parts = cols[3:-1] if len(cols) > 4 else [""]
        route = " ".join(r.strip() for r in route_parts).strip()

        # Extract city (first part of cols[3])
        city = cols[3].strip() if len(cols) > 3 else ""

        trips.append({
            "序号": seq,
            "服务商": "",
            "车型": car_type,
            "上车时间": time_str,
            "城市": city,
            "起点终点": route,
            "金额": amount,
        })

    return trips


def _extract_gaode(lines: list[str]) -> list[dict]:
    """Parse 高德 format: 序号 服务商 车型 上车时间(YYYY-MM-DD HH:MM) 城市 起点...终点 金额"""
    trip_line_indices: list[int] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\d+)\s{2,}", line)
        if m:
            trip_line_indices.append(i)

    trips: list[dict] = []
    for idx in trip_line_indices:
        data_line = lines[idx]

        route_fragments: list[str] = []
        j = idx + 1
        while j < len(lines):
            next_line = lines[j]
            if not next_line.strip():
                j += 1
                continue
            if re.match(r"^\s*\d", next_line):
                break
            if re.match(r"^[\s\-=—]+$", next_line):
                j += 1
                continue
            if re.match(r"^\s{8,}", next_line):
                route_fragments.append(next_line.strip())
                j += 1
                continue
            j += 1

        amt_match = re.search(r"(\d+\.?\d*)\s*元", data_line)
        amount = float(amt_match.group(1)) if amt_match else 0.0

        line_clean = re.sub(r"\s*\d+\.?\d*\s*元\s*$", "", data_line)
        cols = re.split(r"\s{3,}", line_clean.strip())

        route = " ".join(cols[5:]) if len(cols) > 5 else ""
        if route_fragments:
            route += " " + " ".join(route_fragments)
        route = re.sub(r"\s+", " ", route).strip()

        trips.append({
            "序号": int(cols[0]),
            "服务商": cols[1].strip() if len(cols) > 1 else "",
            "车型": cols[2].strip() if len(cols) > 2 else "",
            "上车时间": " ".join(cols[3:5]).strip() if len(cols) > 4 else "",
            "城市": cols[5].strip() if len(cols) > 5 else "",
            "起点终点": route,
            "金额": amount,
        })

    return trips


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--trip-dir", type=Path, default=Path("output/2_打车费"))
    parser.add_argument("--output", type=Path, default=Path("行程单数据.json"))
    args = parser.parse_args()

    root = args.root.resolve()
    trip_dir = resolve_path(root, args.trip_dir)
    output = resolve_path(root, args.output)

    if not trip_dir.is_dir():
        print(f"trip dir not found: {trip_dir}")
        return 1

    all_trips: dict[str, list[dict]] = {}
    for pdf in sorted(trip_dir.glob("*行程单.pdf")):
        trips = extract_trips(pdf)
        if trips:
            all_trips[pdf.name] = trips
            print(f"{pdf.name}: {len(trips)} trips")

    output.write_text(
        json.dumps(all_trips, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nwrote {output}  ({len(all_trips)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
