from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "skills" / "reimbursement" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _pathutil import INTERNAL_DIR, resolve_path  # noqa: E402
from merge_output_pdfs import collect_pdfs  # noqa: E402
from package_final_outputs import (  # noqa: E402
    CHENJING_ARCHIVE,
    PAYMENT_ARCHIVE,
    package_chenjing_invoices,
    package_payment_materials,
)


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


class PackagingTests(unittest.TestCase):
    def test_archives_only_target_docx_and_pdf_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payment = root / INTERNAL_DIR / "支付记录"
            explanation = root / INTERNAL_DIR / "支付说明"
            unpacked = explanation / "docx_unpacked"
            chenjing = root / "output" / "4_辰景发票"
            for directory in (payment, explanation, unpacked, chenjing):
                directory.mkdir(parents=True, exist_ok=True)

            (payment / "record.docx").write_bytes(b"docx")
            (explanation / "explanation.docx").write_bytes(b"docx")
            (unpacked / "debug.docx").write_bytes(b"debug")
            (root / INTERNAL_DIR / "agent.actions.json").write_text("{}", encoding="utf-8")
            (explanation / "report.md").write_text("report", encoding="utf-8")
            (chenjing / "invoice.pdf").write_bytes(b"pdf")
            (chenjing / "notes.md").write_text("notes", encoding="utf-8")

            payment_zip = root / PAYMENT_ARCHIVE
            chenjing_zip = root / CHENJING_ARCHIVE
            self.assertTrue(package_payment_materials(root, payment_zip))
            self.assertTrue(package_chenjing_invoices(root, chenjing_zip))

            with zipfile.ZipFile(payment_zip) as archive:
                self.assertEqual(archive.namelist(), ["支付记录/record.docx", "支付说明/explanation.docx"])
            with zipfile.ZipFile(chenjing_zip) as archive:
                self.assertEqual(archive.namelist(), ["invoice.pdf"])

    def test_empty_sources_remove_stale_archives(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payment_zip = root / PAYMENT_ARCHIVE
            chenjing_zip = root / CHENJING_ARCHIVE
            payment_zip.write_bytes(b"stale")
            chenjing_zip.write_bytes(b"stale")

            self.assertFalse(package_payment_materials(root, payment_zip))
            self.assertFalse(package_chenjing_invoices(root, chenjing_zip))
            self.assertFalse(payment_zip.exists())
            self.assertFalse(chenjing_zip.exists())


if __name__ == "__main__":
    unittest.main()
