"""Tests for the local SQLite paper catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.repository import (
    PaperCatalog,
    PaperRecord,
    calculate_sha256,
    load_metadata_seed,
    sync_parsed_papers,
)


class PaperCatalogTests(unittest.TestCase):
    def test_register_search_and_metadata_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4 synthetic test fixture")
            catalog = PaperCatalog(root / "catalog.sqlite3")
            record = catalog.register_pdf(
                pdf,
                title="可检索论文题名",
                authors=["学生甲"],
                teacher="导师乙",
                year=2026,
                direction="detector",
                page_count=10,
            )

            self.assertEqual(record.paper_id, calculate_sha256(pdf))
            self.assertEqual(catalog.count(), 1)
            self.assertEqual(catalog.search(query="导师")[0].title, "可检索论文题名")
            self.assertEqual(catalog.search(title="论文")[0].teacher, "导师乙")
            self.assertEqual(catalog.search(direction="detector")[0].year, 2026)
            self.assertEqual(
                catalog.metadata_by_file()["paper.pdf"]["paper_id"], record.paper_id
            )

    def test_upsert_preserves_created_at_and_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = PaperCatalog(Path(temporary_directory) / "catalog.sqlite3")
            base = PaperRecord(
                paper_id="a" * 64,
                sha256="a" * 64,
                file_name="paper.pdf",
                file_path="C:/papers/paper.pdf",
                title="Paper",
            )
            first = catalog.upsert(base)
            second = catalog.upsert(
                PaperRecord(
                    **{
                        **base.to_public_dict(),
                        "authors": (),
                        "ingestion_status": "indexed",
                    }
                )
            )
            self.assertEqual(first.created_at, second.created_at)
            self.assertEqual(second.ingestion_status, "indexed")

    def test_invalid_closed_enums_are_rejected(self) -> None:
        record = PaperRecord(
            paper_id="b" * 64,
            sha256="b" * 64,
            file_name="paper.pdf",
            file_path="paper.pdf",
            title="Paper",
            ingestion_status="made-up",
        )
        with self.assertRaisesRegex(ValueError, "ingestion_status"):
            record.validate()

    def test_update_ingestion_status_rejects_unknown_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = PaperCatalog(Path(temporary_directory) / "catalog.sqlite3")
            with self.assertRaises(KeyError):
                catalog.update_ingestion_status("missing", "indexed")

    def test_search_is_parameterized_and_does_not_execute_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = PaperCatalog(Path(temporary_directory) / "catalog.sqlite3")
            result = catalog.search(query="%' OR 1=1 --")
            self.assertEqual(result, [])
            self.assertEqual(catalog.count(), 0)

    def test_metadata_mapping_is_not_limited_to_five_hundred_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog = PaperCatalog(Path(temporary_directory) / "catalog.sqlite3")
            for index in range(501):
                sha256 = f"{index:064x}"
                catalog.upsert(
                    PaperRecord(
                        paper_id=sha256,
                        sha256=sha256,
                        file_name=f"paper-{index:03d}.pdf",
                        file_path=f"C:/papers/paper-{index:03d}.pdf",
                        title=f"Paper {index:03d}",
                    )
                )
            self.assertEqual(len(catalog.metadata_by_file()), 501)

    def test_load_seed_and_sync_parsed_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4 catalog sync fixture")
            seed_path = root / "seed.json"
            seed_path.write_text(
                '{"papers":[{"file_name":"paper.pdf","authors":["A"],'
                '"teacher":"T","year":2025,"direction":"detector"}]}',
                encoding="utf-8",
            )
            catalog = PaperCatalog(root / "catalog.sqlite3")
            metadata = load_metadata_seed(seed_path)
            records = sync_parsed_papers(
                catalog,
                [{
                    "file_name": "paper.pdf",
                    "source_path": str(pdf),
                    "total_pages": 9,
                    "parser_version": "layout_test",
                }],
                metadata_by_file=metadata,
                pipeline_version="section_test",
            )
            self.assertEqual(records[0].teacher, "T")
            self.assertEqual(records[0].page_count, 9)
            self.assertEqual(records[0].pipeline_version, "section_test")

    def test_teacher_facets_group_matching_papers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            catalog = PaperCatalog(root / "catalog.sqlite3")
            for index, teacher in enumerate(("导师甲", "导师甲", "导师乙")):
                pdf = root / f"paper-{index}.pdf"
                pdf.write_bytes(f"%PDF-1.4 fixture {index}".encode())
                catalog.register_pdf(
                    pdf,
                    title=f"论文 {index}",
                    teacher=teacher,
                    ingestion_status="metadata_pending",
                )

            facets = catalog.teacher_facets(ingestion_status="metadata_pending")
            self.assertEqual(
                facets,
                [
                    {"teacher": "导师甲", "paper_count": 2},
                    {"teacher": "导师乙", "paper_count": 1},
                ],
            )
            self.assertEqual(catalog.count_teacher_facets(), 2)
            self.assertEqual(
                len(catalog.search(teacher="导师甲", exact_teacher=True)), 2
            )


if __name__ == "__main__":
    unittest.main()
