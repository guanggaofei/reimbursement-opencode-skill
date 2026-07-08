#!/usr/bin/env python3
"""Dump OCR cache ocr_text to a markdown file."""
import json
from pathlib import Path

cache = json.loads(Path("OCR缓存.json").read_text(encoding="utf-8"))

lines = ["# OCR 缓存原文", "", f"共 {len(cache)} 条记录", ""]

for h, entry in sorted(cache.items(), key=lambda x: x[0]):
    text = entry.get("ocr_text", "")
    lines.append(f"## {h}")
    lines.append("")
    lines.append("```")
    lines.append(text)
    lines.append("```")
    lines.append("")

Path("OCR缓存原文.md").write_text("\n".join(lines), encoding="utf-8")
print(f"已写入 {len(cache)} 条记录到 OCR缓存原文.md")
