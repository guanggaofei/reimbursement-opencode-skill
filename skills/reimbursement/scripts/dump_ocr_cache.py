#!/usr/bin/env python3
"""Write OCR cache text to an internal Markdown diagnostic file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _pathutil import INTERNAL_DIR, add_root_arg, resolve_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root_arg(parser)
    parser.add_argument("--cache", type=Path, default=Path("OCR缓存.json"))
    parser.add_argument("--output", type=Path, default=INTERNAL_DIR / "OCR缓存原文.md")
    args = parser.parse_args()

    root = args.root.resolve()
    cache_path = resolve_path(root, args.cache)
    output_path = resolve_path(root, args.output)
    cache = json.loads(cache_path.read_text(encoding="utf-8"))

    lines: list[str] = ["# OCR 缓存原文", "", f"共 {len(cache)} 条记录", ""]
    for image_path, item in sorted(cache.items(), key=lambda pair: pair[0]):
        lines.extend(
            [
                f"## {image_path}",
                "",
                "```",
                str(item.get("ocr_text") or ""),
                "```",
                "",
            ]
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {len(cache)} 条记录到 {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
