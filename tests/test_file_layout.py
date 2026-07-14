from __future__ import annotations

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
from merge_output_pdfs import collect_pdfs  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
