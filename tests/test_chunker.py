"""Tests for section-aware and caption-safe paper chunking."""

from __future__ import annotations

import unittest

from src.ingestion.chunker import (
    CHUNKER_VERSION,
    _fallback_heading_level,
    _looks_like_heading,
    chunk_document,
)


class SectionAwareChunkerTests(unittest.TestCase):
    def _parsed_paper(self) -> dict[str, object]:
        return {
            "file_name": "paper.pdf",
            "parser_version": "layout_v2",
            "toc": [
                {"level": 1, "title": "1 Introduction", "page": 1},
                {"level": 1, "title": "2 Results", "page": 2},
            ],
            "pages": [
                {
                    "page": 1,
                    "text": "1 Introduction\nBackground text.",
                    "blocks": [
                        {"block_number": 1, "block_type": "paragraph", "text": "1 Introduction"},
                        {"block_number": 2, "block_type": "paragraph", "text": "Background text."},
                    ],
                },
                {
                    "page": 2,
                    "text": "2 Results\nMeasured result.\nFigure 2 response curve",
                    "blocks": [
                        {"block_number": 1, "block_type": "paragraph", "text": "2 Results"},
                        {
                            "block_number": 2,
                            "block_type": "paragraph",
                            "text": "Measured result.",
                        },
                        {
                            "block_number": 3,
                            "block_type": "figure_caption",
                            "text": "Figure 2 response curve",
                        },
                    ],
                },
            ],
        }

    def test_chunks_never_cross_toc_sections(self) -> None:
        chunks = chunk_document(
            self._parsed_paper(),
            metadata={
                "author": "A",
                "teacher": "T",
                "year": 2026,
                "paper_id": "a" * 64,
            },
            chunk_size=100,
            overlap=10,
        )
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0]["metadata"]["section_type"], "intro")
        self.assertEqual(chunks[1]["metadata"]["section_type"], "results")
        self.assertNotIn("Measured result", chunks[0]["text"])
        self.assertEqual(chunks[0]["metadata"]["pipeline_version"], CHUNKER_VERSION)
        self.assertEqual(chunks[0]["metadata"]["paper_id"], "a" * 64)

    def test_caption_is_a_standalone_chunk(self) -> None:
        chunks = chunk_document(self._parsed_paper(), chunk_size=100, overlap=10)
        caption = chunks[-1]
        self.assertEqual(caption["text"], "Figure 2 response curve")
        self.assertEqual(caption["metadata"]["block_type"], "figure_caption")
        self.assertEqual(caption["metadata"]["page_start"], 2)

    def test_heading_fallback_works_without_pdf_bookmarks(self) -> None:
        parsed = {
            "file_name": "no-toc.pdf",
            "pages": [
                {
                    "page": 1,
                    "text": "参考文献\n[1] Example",
                    "blocks": [
                        {"block_number": 1, "block_type": "paragraph", "text": "参考文献"},
                        {"block_number": 2, "block_type": "paragraph", "text": "[1] Example"},
                    ],
                }
            ],
        }
        chunks = chunk_document(parsed, chunk_size=100, overlap=10)
        self.assertEqual(chunks[0]["metadata"]["section_path"], "参考文献")
        self.assertEqual(chunks[0]["metadata"]["section_type"], "reference")

    def test_numeric_table_value_is_not_mistaken_for_a_heading(self) -> None:
        self.assertFalse(_looks_like_heading("9.8 × 10^{8} 1.2×10^{-3} 0.61"))
        self.assertFalse(_looks_like_heading("20 世纪 50 年代末期，人们实现了材料调控"))
        self.assertTrue(_looks_like_heading("1.4.2 钙钛矿薄膜的制备工艺"))
        self.assertEqual(_fallback_heading_level("1.4.2 钙钛矿薄膜的制备工艺"), 3)

    def test_dotted_table_of_contents_is_classified_separately(self) -> None:
        parsed = {
            "file_name": "contents.pdf",
            "toc": [{"level": 1, "title": "Abstract", "page": 1}],
            "pages": [
                {
                    "page": 1,
                    "text": "Abstract\n1.2 Methods .......... 3",
                    "blocks": [
                        {"block_number": 1, "block_type": "paragraph", "text": "Abstract"},
                        {
                            "block_number": 2,
                            "block_type": "paragraph",
                            "text": "1.2 Methods .......... 3",
                        },
                    ],
                }
            ],
        }
        chunks = chunk_document(parsed, chunk_size=100, overlap=10)
        self.assertEqual(chunks[0]["metadata"]["section_type"], "contents")

    def test_legacy_page_text_still_chunks_with_unknown_section(self) -> None:
        parsed = {
            "file_name": "legacy.pdf",
            "pages": [{"page": 1, "text": "Legacy page text."}],
        }
        chunks = chunk_document(parsed, chunk_size=100, overlap=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["metadata"]["section_type"], "unknown")
        self.assertEqual(chunks[0]["metadata"]["parser_version"], "legacy")

    def test_invalid_overlap_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            chunk_document(self._parsed_paper(), chunk_size=100, overlap=100)


if __name__ == "__main__":
    unittest.main()
