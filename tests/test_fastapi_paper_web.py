from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # setup gate gives a clearer failure before installation
    TestClient = None

from src.repository import PaperCatalog, PaperRecord, PaperTag


@unittest.skipIf(TestClient is None, "FastAPI is not installed")
class FastApiPaperWebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.catalog_path = root / "papers.sqlite3"
        self.report_directory = root / "reports"
        self.pdf_path = root / "paper.pdf"
        self.pdf_path.write_bytes(b"%PDF-1.4\n% local test fixture\n")

        self.catalog = PaperCatalog(self.catalog_path)
        record = PaperRecord(
            paper_id="a" * 64,
            sha256="a" * 64,
            file_name=self.pdf_path.name,
            file_path=str(self.pdf_path),
            title="光纤传感系统研究",
            authors=("王同学",),
            teacher="万老师",
            institution="测试大学",
            year=2025,
            direction="分布式光纤传感",
            page_count=88,
            file_size_bytes=self.pdf_path.stat().st_size,
            ingestion_status="indexed",
            parser_version="layout_v2",
        )
        self.catalog.upsert(record)
        self.catalog.upsert_tag(
            PaperTag(
                paper_id=record.paper_id,
                category="application",
                value="管线监测",
                source="content_rule",
                confidence=0.9,
            )
        )

        from app.web_api import create_app

        self.client = TestClient(
            create_app(
                catalog_path=self.catalog_path,
                report_directory=self.report_directory,
            )
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_paper_cards_and_teacher_facets(self) -> None:
        response = self.client.get("/api/papers", params={"query": "光纤"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        card = payload["items"][0]
        self.assertEqual(card["teacher"], "万老师")
        self.assertEqual(card["status"]["label"], "已索引")
        self.assertEqual(card["tags"][0]["value"], "管线监测")
        self.assertNotIn("file_path", card)

        teachers = self.client.get("/api/teachers").json()["items"]
        self.assertEqual(teachers, [{"teacher": "万老师", "paper_count": 1}])

    def test_detail_report_and_pdf_routes(self) -> None:
        paper_id = "a" * 64
        detail = self.client.get(f"/api/papers/{paper_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["has_pdf"])

        missing_report = self.client.get(f"/api/papers/{paper_id}/report")
        self.assertEqual(missing_report.status_code, 404)

        self.report_directory.mkdir(parents=True)
        (self.report_directory / f"{paper_id}.md").write_text(
            "# 本地精读\n\n证据来自第 3 页。",
            encoding="utf-8",
        )
        report = self.client.get(f"/api/papers/{paper_id}/report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("证据来自第 3 页", report.text)

        pdf = self.client.get(f"/api/papers/{paper_id}/pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")

    def test_home_and_health(self) -> None:
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("论文成果库", home.text)
        health = self.client.get("/api/health")
        self.assertEqual(health.json(), {"status": "ok", "catalog": 1})


if __name__ == "__main__":
    unittest.main()
