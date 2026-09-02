"""Tests for local paper discovery, reviewable tags, and safe uploads."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.library import PaperIngestionService, PaperLibraryService
from src.repository import PaperCatalog, PaperTag


def make_pdf(path: Path, text: str = "test") -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class PaperLibraryServiceTests(unittest.TestCase):
    def test_recursive_sync_skips_environment_directories_and_suggests_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            teacher_directory = root / "导师甲"
            teacher_directory.mkdir()
            paper = teacher_directory / "钙钛矿X射线探测器研究.pdf"
            make_pdf(paper)
            hidden = root / ".venv"
            hidden.mkdir()
            make_pdf(hidden / "不应入库.pdf")

            catalog = PaperCatalog(root / "catalog.sqlite3")
            service = PaperLibraryService(catalog)
            first = service.sync_directory(root)
            second = service.sync_directory(root)

            self.assertEqual(first.discovered, 1)
            self.assertEqual(first.registered, 1)
            self.assertEqual(second.unchanged, 1)
            record = catalog.search(query="导师甲")[0]
            self.assertEqual(record.teacher, "导师甲")
            tags = catalog.list_tags(record.paper_id)
            self.assertIn("钙钛矿", [tag.value for tag in tags])
            self.assertTrue(all(tag.review_status == "suggested" for tag in tags))

    def test_tag_review_and_tag_search_are_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paper = root / "paper.pdf"
            make_pdf(paper)
            catalog = PaperCatalog(root / "catalog.sqlite3")
            record = catalog.register_pdf(paper)
            tag = catalog.upsert_tag(
                PaperTag(
                    paper_id=record.paper_id,
                    category="custom",
                    value="可转化成果",
                    source="user",
                    confidence=1.0,
                    review_status="confirmed",
                )
            )

            self.assertEqual(catalog.search(tag="可转化")[0].paper_id, record.paper_id)
            reviewed = catalog.review_tag(tag.tag_id, "rejected")
            self.assertEqual(reviewed.review_status, "rejected")
            self.assertEqual(catalog.search(tag="可转化"), [])

    def test_upload_validates_pdf_and_deduplicates_by_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source.pdf"
            make_pdf(source)
            payload = source.read_bytes()
            catalog = PaperCatalog(root / "catalog.sqlite3")
            service = PaperLibraryService(catalog)
            uploads = root / "uploads"

            first = service.import_upload(
                io.BytesIO(payload),
                "论文.pdf",
                target_directory=uploads,
                title="上传论文",
                teacher="导师乙",
            )
            second = service.import_upload(
                io.BytesIO(payload),
                "副本.pdf",
                target_directory=uploads,
            )

            self.assertFalse(first.duplicate)
            self.assertTrue(second.duplicate)
            self.assertEqual(catalog.count(), 1)
            self.assertTrue(first.saved_path.is_file())

    def test_upload_rejects_extension_spoofing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            service = PaperLibraryService(PaperCatalog(root / "catalog.sqlite3"))
            with self.assertRaisesRegex(ValueError, "文件头"):
                service.import_upload(
                    io.BytesIO(b"not a pdf"),
                    "fake.pdf",
                    target_directory=root / "uploads",
                )

    def test_batch_parser_persists_status_and_content_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paper = root / "X-ray detector.pdf"
            make_pdf(paper, "X ray detector for industrial testing")
            catalog = PaperCatalog(root / "catalog.sqlite3")
            record = catalog.register_pdf(
                paper,
                teacher="导师甲",
                ingestion_status="metadata_pending",
            )
            service = PaperIngestionService(
                catalog,
                output_directory=root / "parsed",
            )

            result = service.parse_batch(limit=1)

            self.assertEqual(result.completed, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue((root / "parsed" / f"{record.paper_id}.json.gz").is_file())
            updated = catalog.get(record.paper_id)
            self.assertEqual(updated.ingestion_status, "parsed")
            self.assertEqual(updated.page_count, 1)
            self.assertIn(
                "探测器",
                [tag.value for tag in catalog.list_tags(record.paper_id)],
            )
            self.assertEqual(service.parse_batch(limit=1).requested, 0)

    def test_batch_parser_records_failure_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            paper = root / "broken.pdf"
            paper.write_bytes(b"%PDF- broken")
            catalog = PaperCatalog(root / "catalog.sqlite3")
            record = catalog.register_pdf(
                paper,
                ingestion_status="metadata_pending",
            )
            service = PaperIngestionService(catalog, output_directory=root / "parsed")

            result = service.parse_batch(limit=1)

            self.assertEqual(result.failed, 1)
            updated = catalog.get(record.paper_id)
            self.assertEqual(updated.ingestion_status, "failed")
            self.assertTrue(updated.error_message)


if __name__ == "__main__":
    unittest.main()
