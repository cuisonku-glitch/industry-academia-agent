"""Regression tests for layout-aware PDF parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.ingestion.pdf_parser import PARSER_VERSION, _join_text_parts, parse_pdf


class PdfParserTests(unittest.TestCase):
    def _write_fixture(self, path: Path) -> None:
        document = pymupdf.open()
        first = document.new_page()
        first.insert_htmlbox(
            pymupdf.Rect(40, 40, 500, 160),
            "<p>value 1.2x10<sup>4</sup> unit cm<sup>-2</sup> and H<sub>2</sub>O</p>",
        )
        second = document.new_page()
        second.insert_text((40, 80), "Results are reported here.", fontsize=12)
        document.set_toc([[1, "1 Introduction", 1], [1, "2 Results", 2]])
        document.save(path)
        document.close()

    def test_scripts_are_explicit_in_layout_text_and_plain_text_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "scripts.pdf"
            self._write_fixture(path)
            result = parse_pdf(path)

        first_page = result["pages"][0]
        self.assertIn("10^{4}", first_page["text"])
        self.assertIn("cm^{-2}", first_page["text"])
        self.assertIn("H_{2}O", first_page["text"])
        self.assertIn("104", first_page["plain_text"])
        self.assertGreaterEqual(first_page["script_span_count"], 3)

    def test_toc_and_parser_version_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "toc.pdf"
            self._write_fixture(path)
            result = parse_pdf(path)

        self.assertEqual(result["parser_version"], PARSER_VERSION)
        self.assertEqual(result["total_pages"], 2)
        self.assertEqual(
            [(item["level"], item["title"], item["page"]) for item in result["toc"]],
            [(1, "1 Introduction", 1), (1, "2 Results", 2)],
        )
        self.assertEqual(result["pages"][1]["blocks"][0]["block_type"], "paragraph")

    def test_script_fragments_split_across_visual_lines_are_joined(self) -> None:
        self.assertEqual(
            _join_text_parts(["unit cm^{-}", "^{3} continues"]),
            "unit cm^{-3} continues",
        )
        self.assertEqual(
            _join_text_parts(["H_{", "2}O"]),
            "H_{\n2}O",
        )

    def test_non_pdf_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "paper.txt"
            path.write_text("not a pdf", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Expected a PDF"):
                parse_pdf(path)

    def test_recurring_margin_headers_and_page_numbers_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "margins.pdf"
            document = pymupdf.open()
            for page_number in range(1, 5):
                page = document.new_page()
                page.insert_text((40, 25), "Repeated paper header", fontsize=8)
                page.insert_text((40, 100), f"Unique body {page_number}", fontsize=12)
                page.insert_text((290, 825), str(page_number), fontsize=8)
            document.save(path)
            document.close()
            result = parse_pdf(path)

        self.assertEqual(result["removed_margin_blocks"], 8)
        self.assertNotIn("Repeated paper header", result["pages"][0]["text"])
        self.assertIn("Repeated paper header", result["pages"][0]["plain_text"])
        self.assertEqual(result["pages"][0]["text"], "Unique body 1")


if __name__ == "__main__":
    unittest.main()
