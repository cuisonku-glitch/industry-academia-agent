"""Offline tests for page-traceable paper figure extraction."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.library import PaperFigureService
from src.repository import PaperRecord


class PaperFigureTests(unittest.TestCase):
    def test_extracts_nearest_image_and_keeps_caption_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_path = root / "paper.pdf"
            document = pymupdf.open()
            page = document.new_page(width=595, height=842)
            pixmap = pymupdf.Pixmap(
                pymupdf.csRGB, pymupdf.IRect(0, 0, 180, 100), False
            )
            pixmap.clear_with(0x8BCBC1)
            page.insert_image(
                pymupdf.Rect(90, 110, 500, 330), stream=pixmap.tobytes("png")
            )
            page.insert_text((90, 355), "Figure 1 Sensor response")
            document.save(pdf_path)
            document.close()

            paper_id = "f" * 64
            record = PaperRecord(
                paper_id=paper_id,
                sha256=paper_id,
                file_name=pdf_path.name,
                file_path=str(pdf_path),
                title="Figure test",
                ingestion_status="indexed",
            )
            parsed_directory = root / "parsed"
            parsed_directory.mkdir()
            payload = {
                "paper_id": paper_id,
                "file_name": pdf_path.name,
                "pages": [
                    {
                        "page": 1,
                        "blocks": [
                            {
                                "block_number": 0,
                                "block_type": "figure_caption",
                                "text": "Figure 1 Sensor response",
                                "bbox": [90, 760, 420, 785],
                            },
                            {
                                "block_number": 1,
                                "block_type": "figure_caption",
                                "text": "Figure 1 Sensor response",
                                "bbox": [90, 340, 420, 365],
                            }
                        ],
                    }
                ],
            }
            with gzip.open(
                parsed_directory / f"{paper_id}.json.gz", "wt", encoding="utf-8"
            ) as destination:
                json.dump(payload, destination)

            service = PaperFigureService(
                parsed_directory=parsed_directory,
                asset_directory=root / "assets",
            )
            result = service.extract(record, max_assets=4)

            self.assertEqual(result.caption_count, 2)
            self.assertEqual(len(result.assets), 1)
            asset = result.assets[0]
            self.assertEqual(asset.asset_id, "F01")
            self.assertEqual(asset.page, 1)
            self.assertEqual(asset.extraction_source, "nearest_embedded_image")
            self.assertTrue(service.asset_path(asset).is_file())
            self.assertNotIn("file_name", asset.to_public_dict())
            self.assertEqual(service.load_assets(paper_id), result.assets)


if __name__ == "__main__":
    unittest.main()
