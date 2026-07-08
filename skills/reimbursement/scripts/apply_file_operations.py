#!/usr/bin/env python3
"""Apply manual screenshot matching operations to 匹配记录.json.

New operation format:
{
  "操作列表": [
    {"动作": "匹配", "发票文件": "invoices/foo.pdf", "截图": "images/IMG_1.png", "类型": "支付记录"},
    {"动作": "匹配", "发票文件": "invoices/taxi.pdf", "截图": "images/IMG_2.png", "类型": "账单截图", "行程序号": 1},
    {"动作": "忽略", "截图": "images/IMG_3.png", "原因": "重复截图"}
  ]
}

Legacy 移动/删除 operations are accepted for compatibility but no files are
moved or deleted.  The instruction file is kept after execution and each
operation is marked with 已执行=true.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from _matching_records import add_match, image_key, invoice_key, load_match_record, mark_ignored, save_match_record


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def invoice_by_seq(root: Path) -> dict[int, str]:
    path = root / "invoice_results_sorted.json"
    if not path.exists():
        return {}
    data = read_json(path)
    result: dict[int, str] = {}
    for inv in data.get("发票信息", []) or []:
        updated = str(inv.get("更新后文件名") or "")
        match = re.match(r"^(\d+)_", updated)
        seq = int(match.group(1)) if match else int(inv.get("发票序号", 0)) + 1
        result[seq] = invoice_key(str(inv.get("文件名") or ""))
    return result


def parse_legacy_source(root: Path, src: str) -> str:
    path = Path(src)
    if src.startswith("images/") or path.is_absolute() and "images" in path.parts:
        return image_key(root, path)
    name = path.name
    match = re.match(r"^待识别_(?:\d+(?:\.\d{1,2})?)_(.+)$", name)
    if match:
        return f"images/{match.group(1)}"
    return f"images/{name}"


def parse_legacy_target(dst: str, seq_map: dict[int, str]) -> tuple[str, str, int | None] | None:
    name = Path(dst).name
    match = re.match(r"^(\d+)_(支付记录|账单截图)(?:_(?:行程)?(\d+))?\.", name)
    if not match:
        return None
    seq = int(match.group(1))
    invoice = seq_map.get(seq)
    if not invoice:
        return None
    trip_index = int(match.group(3)) if match.group(3) else None
    return invoice, match.group(2), trip_index


def normalize_operation(root: Path, op: dict[str, Any], seq_map: dict[int, str]) -> dict[str, Any] | None:
    action = op.get("动作")
    if action == "匹配":
        return op
    if action == "忽略":
        return op
    if action == "删除":
        src = op.get("截图") or op.get("来源路径")
        if not src:
            return None
        return {"动作": "忽略", "截图": parse_legacy_source(root, str(src)), "原因": op.get("原因", "删除/重复截图")}
    if action == "移动":
        src = op.get("截图") or op.get("来源路径")
        dst = op.get("目标路径")
        if not src or not dst:
            return None
        parsed = parse_legacy_target(str(dst), seq_map)
        if not parsed:
            return None
        invoice, kind, trip_index = parsed
        new_op: dict[str, Any] = {
            "动作": "匹配",
            "发票文件": invoice,
            "截图": parse_legacy_source(root, str(src)),
            "类型": kind,
        }
        if trip_index is not None:
            new_op["行程序号"] = trip_index
        return new_op
    return None


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    instruction_file = root / "文件操作指令.json"
    match_record = root / "匹配记录.json"

    if not instruction_file.exists():
        instruction_file.write_text(json.dumps({"操作列表": []}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("文件操作指令.json 不存在，已创建空文件")
        return 0

    data = read_json(instruction_file)
    ops = data.get("操作列表", []) or []
    pending_ops = [op for op in ops if not op.get("已执行")]
    if not pending_ops:
        print("无待执行操作")
        return 0

    record = load_match_record(match_record)
    seq_map = invoice_by_seq(root)
    matched = ignored = skipped = 0

    for op in pending_ops:
        normalized = normalize_operation(root, op, seq_map)
        if not normalized:
            print(f"跳过无法识别的操作: {op}")
            op["已执行"] = False
            op["执行结果"] = "无法识别"
            skipped += 1
            continue

        action = normalized.get("动作")
        if action == "匹配":
            invoice = str(normalized.get("发票文件") or "")
            image = str(normalized.get("截图") or "")
            kind = str(normalized.get("类型") or "")
            if not invoice or not image or kind not in ("支付记录", "账单截图"):
                print(f"跳过字段不完整的匹配操作: {op}")
                skipped += 1
                continue
            add_match(
                record,
                invoice,
                image,
                kind,
                trip_index=normalized.get("行程序号"),
                amount=normalized.get("金额", ""),
                payment_date=str(normalized.get("购买日期") or ""),
            )
            matched += 1
            print(f"匹配: {image} -> {invoice} / {kind}" + (f" / 行程{normalized.get('行程序号')}" if normalized.get("行程序号") else ""))
        elif action == "忽略":
            image = str(normalized.get("截图") or "")
            if not image:
                skipped += 1
                continue
            mark_ignored(record, image, str(normalized.get("原因") or ""))
            ignored += 1
            print(f"忽略: {image}")

        op["已执行"] = True
        op["执行时间"] = datetime.now().isoformat(timespec="seconds")
        op["规范化操作"] = normalized

    save_match_record(match_record, record)
    instruction_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n完成: 匹配 {matched} 个，忽略 {ignored} 个，跳过 {skipped} 个")
    print(f"已更新: {match_record}")
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
