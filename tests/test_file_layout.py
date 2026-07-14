from __future__ import annotations

import math
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "reimbursement" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _pathutil import INTERNAL_DIR, resolve_path  # noqa: E402
from apply_match_actions import ActionError, slot_counts, validate_unique_slots  # noqa: E402
from generate_reimbursement_xlsx import build_rows, first_item_quantity  # noqa: E402
from merge_output_pdfs import (  # noqa: E402
    A4_HEIGHT,
    A4_WIDTH,
    SIGNATURE_LINE_LENGTH,
    center_page_on_a4,
    collect_pdfs,
    invoice_header_overlay,
    invoice_sequence,
)
from verify_screenshot_coverage import build_issue_summary  # noqa: E402

from pypdf._page import PageObject  # noqa: E402
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, RectangleObject  # noqa: E402


class PathLayoutTests(unittest.TestCase):
    def test_relative_and_absolute_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(resolve_path(root, INTERNAL_DIR / "x.json"), (root / INTERNAL_DIR / "x.json").resolve())
            absolute = (root / "outside.json").resolve()
            self.assertEqual(resolve_path(root, absolute), absolute)

    def test_pdf_classification_only_includes_material_and_taxi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            expected = []
            for folder, filename in [
                ("1_材料费", "10.pdf"),
                ("2_打车费", "2.pdf"),
                ("3_高价发票", "3.pdf"),
                ("4_辰景发票", "4.pdf"),
            ]:
                path = output / folder / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"pdf")
                if folder in {"1_材料费", "2_打车费"}:
                    expected.append(path)
            self.assertEqual(set(collect_pdfs(output)), set(expected))

    def test_super_invoice_output_contract_is_unchanged(self) -> None:
        source = (SCRIPTS / "super_invoice.py").read_text(encoding="utf-8")
        for folder in ("1_材料费", "2_打车费", "3_高价发票", "4_辰景发票"):
            self.assertIn(f'"{folder}"', source)
        self.assertIn('r / "invoice_results.json"', source)
        self.assertIn('root / "invoice_results_sorted.json"', source)
        self.assertIn('root / "invoice_errors.json"', source)
        self.assertIn('root / "output"', source)

    def test_internal_defaults_are_under_work_directory(self) -> None:
        expected_sources = {
            "check_invoice_errors.py": 'INTERNAL_DIR / "invoice_errors_raw.json"',
            "apply_invoice_fixes.py": 'INTERNAL_DIR / "invoice_fixes.json"',
            "extract_trip_sheets.py": 'INTERNAL_DIR / "行程单数据.json"',
            "organize_expense_records.py": 'INTERNAL_DIR / "支出记录OCR匹配明细.md"',
            "generate_expense_record_docx.py": 'INTERNAL_DIR / "支出记录DOCX生成结果.md"',
            "dump_ocr_cache.py": 'INTERNAL_DIR / "OCR缓存原文.md"',
            "generate_payment_record_docx.py": 'INTERNAL_DIR / "支付记录/xxx_17-24_支付记录.docx"',
            "generate_payment_explanations.py": 'INTERNAL_DIR / "支付说明"',
        }
        for filename, declaration in expected_sources.items():
            with self.subTest(filename=filename):
                source = (SCRIPTS / filename).read_text(encoding="utf-8")
                self.assertIn(declaration, source)


class ReimbursementXlsxTests(unittest.TestCase):
    @patch("generate_reimbursement_xlsx.subprocess.run")
    def test_first_item_quantity_truncates_decimal(self, run: unittest.mock.Mock) -> None:
        run.return_value = CompletedProcess(
            args=[],
            returncode=0,
            stdout="项目名称              数 量       单价\n螺丝                  2.9        10.00\n合计\n",
            stderr="",
        )

        self.assertEqual(first_item_quantity(Path("example.pdf")), Decimal("2"))

    @patch("generate_reimbursement_xlsx.first_item_quantity", return_value=Decimal("2"))
    def test_build_rows_sets_quantity_and_unit_price(self, _quantity: unittest.mock.Mock) -> None:
        invoices = [{
            "文件名": "example.pdf",
            "更新后文件名": "1_example.pdf",
            "价税合计金额": 39.04,
            "发票号码": "123",
            "行程单文件名": "无需",
            "项目列表": [{"项目名称": "螺丝"}],
        }]

        rows = build_rows(Path("."), invoices, {})

        self.assertEqual(rows[0]["quantity"], "2")
        self.assertEqual(rows[0]["unit_price"], "19.520000")

    @patch("generate_reimbursement_xlsx.first_item_quantity", return_value=Decimal("1"))
    def test_build_rows_rejects_unit_price_over_1000(self, _quantity: unittest.mock.Mock) -> None:
        invoices = [{
            "文件名": "example.pdf",
            "更新后文件名": "1_example.pdf",
            "价税合计金额": 1000.01,
            "发票号码": "123",
            "行程单文件名": "无需",
            "项目列表": [{"项目名称": "螺丝"}],
        }]

        with self.assertRaises(RuntimeError):
            build_rows(Path("."), invoices, {})


class MatchActionValidationTests(unittest.TestCase):
    def test_existing_duplicate_slot_does_not_block_unrelated_action(self) -> None:
        record = {
            "发票映射": {
                "invoices/example.pdf": {
                    "支付记录": ["images/a.png", "images/b.png"],
                    "账单截图": [],
                    "行程明细": [],
                }
            }
        }
        existing_counts = slot_counts(record)

        validate_unique_slots(record, {"agent": "fix-trip-ambiguity"}, existing_counts)

    def test_new_duplicate_slot_is_rejected(self) -> None:
        record = {
            "发票映射": {
                "invoices/example.pdf": {
                    "支付记录": ["images/a.png"],
                    "账单截图": [],
                    "行程明细": [],
                }
            }
        }
        existing_counts = slot_counts(record)
        record["发票映射"]["invoices/example.pdf"]["支付记录"].append("images/b.png")

        with self.assertRaises(ActionError):
            validate_unique_slots(record, {"agent": "fix-trip-ambiguity"}, existing_counts)


class ScreenshotIssueSummaryTests(unittest.TestCase):
    def test_issue_summary_counts_repeatable_categories(self) -> None:
        record = {
            "未匹配截图": [
                {"原因": "金额对应多个候选发票，交由后处理视觉识别"},
                {"原因": "金额对应多个候选行程，交由后处理视觉识别"},
                {"原因": "与截图 x.png 同时匹配同一发票，需人工识别"},
                {"原因": "金额不匹配任何发票或打车行程"},
            ]
        }

        summary = build_issue_summary(record, [object()], [(object(), "支付记录")], [object()])  # type: ignore[list-item]

        self.assertEqual(summary["店铺名称歧义"], 1)
        self.assertEqual(summary["行程歧义"], 1)
        self.assertEqual(summary["重复截图"], 1)
        self.assertEqual(summary["完全无截图发票"], 1)
        self.assertEqual(summary["截图不完整发票"], 1)
        self.assertEqual(summary["缺失行程截图"], 1)
        self.assertEqual(summary["未匹配截图总数"], 4)


class MergedPdfLayoutTests(unittest.TestCase):
    def test_invoice_sequence_excludes_trip_sheet(self) -> None:
        self.assertEqual(invoice_sequence(Path("47_价税合计_25_00_发票.pdf")), 47)
        self.assertIsNone(invoice_sequence(Path("47_价税合计_25_00_行程单.pdf")))

    def test_header_has_sequence_and_two_three_centimeter_lines(self) -> None:
        overlay = invoice_header_overlay(47, 700)
        operations = overlay.get_contents().operations
        line_lengths = []
        markers = []
        for index, (operands, operator) in enumerate(operations):
            if operator == b"m" and index + 1 < len(operations) and operations[index + 1][1] == b"l":
                next_operands = operations[index + 1][0]
                line_lengths.append(math.hypot(
                    float(next_operands[0]) - float(operands[0]),
                    float(next_operands[1]) - float(operands[1]),
                ))
            if operator == b"Tj":
                markers.append(str(operands[0]))

        self.assertEqual(markers, ["47"])
        self.assertEqual(len(line_lengths), 2)
        for length in line_lengths:
            self.assertAlmostEqual(length, SIGNATURE_LINE_LENGTH, places=5)

    def test_cropbox_and_annotations_are_transformed_together(self) -> None:
        source = PageObject.create_blank_page(width=600, height=800)
        source.cropbox = RectangleObject((0, 400, 600, 800))
        annotation = DictionaryObject({
            NameObject("/Subtype"): NameObject("/Square"),
            NameObject("/Rect"): RectangleObject((100, 500, 200, 600)),
            NameObject("/Path"): ArrayObject([
                ArrayObject(FloatObject(value) for value in (50, 450, 150, 550)),
            ]),
        })
        source[NameObject("/Annots")] = ArrayObject([annotation])

        target, content_top = center_page_on_a4(source, margin_x=0, margin_y=72)
        scale = min(A4_WIDTH / 600, (A4_HEIGHT - 144) / 400)
        target_x = (A4_WIDTH - 600 * scale) / 2
        target_y = (A4_HEIGHT - 400 * scale) / 2
        rect = target["/Annots"][0].get_object()["/Rect"]

        self.assertAlmostEqual(float(target.mediabox.width), A4_WIDTH, places=5)
        self.assertAlmostEqual(float(target.mediabox.height), A4_HEIGHT, places=5)
        self.assertAlmostEqual(content_top, target_y + 400 * scale, places=5)
        self.assertAlmostEqual(float(rect[0]), 100 * scale + target_x, places=5)
        self.assertAlmostEqual(float(rect[1]), (500 - 400) * scale + target_y, places=5)
        self.assertAlmostEqual(float(rect[2]), 200 * scale + target_x, places=5)
        self.assertAlmostEqual(float(rect[3]), (600 - 400) * scale + target_y, places=5)
        path = target["/Annots"][0].get_object()["/Path"][0]
        self.assertAlmostEqual(float(path[0]), 50 * scale + target_x, places=5)
        self.assertAlmostEqual(float(path[1]), (450 - 400) * scale + target_y, places=5)
        self.assertAlmostEqual(float(path[2]), 150 * scale + target_x, places=5)
        self.assertAlmostEqual(float(path[3]), (550 - 400) * scale + target_y, places=5)


if __name__ == "__main__":
    unittest.main()
