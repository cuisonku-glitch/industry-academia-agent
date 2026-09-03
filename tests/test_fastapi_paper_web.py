from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
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
        self.parsed_directory = root / "parsed"
        self.asset_directory = root / "paper-assets"
        self.deep_report_directory = root / "deep-reports"
        self.route_directory = root / "routes"
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
                parsed_directory=self.parsed_directory,
                asset_directory=self.asset_directory,
                deep_report_directory=self.deep_report_directory,
                route_directory=self.route_directory,
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
        self.assertFalse(detail.json()["has_deep_report"])

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

        figures = self.client.get(f"/api/papers/{paper_id}/figures")
        self.assertEqual(figures.status_code, 200)
        self.assertEqual(figures.json()["total"], 0)

        no_consent = self.client.post(
            f"/api/papers/{paper_id}/kimi-reading",
            json={"consent": False},
        )
        self.assertEqual(no_consent.status_code, 403)

    def test_portable_deep_report_package_and_asset_route(self) -> None:
        paper_id = "a" * 64
        paper_directory = self.deep_report_directory / paper_id
        assets = paper_directory / "assets"
        assets.mkdir(parents=True)
        (assets / "F01.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        structured = {
            "executive_summary": {"text": "本地摘要", "source_labels": ["E01"]},
            "research_problem": {"text": "研究问题", "source_labels": ["E01"]},
            "innovations": [], "method_steps": [], "key_findings": [],
            "figure_interpretations": [], "formula_interpretations": [],
            "transfer_assets": [], "limitations": [], "uncertainties": [],
        }
        payload = {
            "model": "kimi-k3", "structured": structured,
            "figures": [], "formulas": [],
        }
        (paper_directory / "latest.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        (paper_directory / "latest.md").write_text("# old", encoding="utf-8")
        route_directory = self.route_directory / paper_id
        route_directory.mkdir(parents=True)
        (route_directory / "latest.drawio").write_text("<mxfile/>", encoding="utf-8")

        report = self.client.get(f"/api/papers/{paper_id}/deep-report")
        self.assertEqual(report.status_code, 200)
        self.assertIn("证据与判断边界", report.text)

        image = self.client.get(f"/api/papers/{paper_id}/deep-assets/F01.png")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image.headers["content-type"], "image/png")

        package = self.client.get(f"/api/papers/{paper_id}/deep-report-package")
        self.assertEqual(package.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            names = set(archive.namelist())
        self.assertIn("00_Kimi结构化精读.md", names)
        self.assertIn("01_结构化数据.json", names)
        self.assertIn("02_技术路线.drawio", names)
        self.assertNotIn("assets/F01.png", names)

    def test_home_and_health(self) -> None:
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("论文成果库", home.text)
        self.assertEqual(home.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/assets/app.js").headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/favicon.ico").status_code, 204)
        health = self.client.get("/api/health")
        self.assertEqual(health.json(), {"status": "ok", "catalog": 1})


if __name__ == "__main__":
    unittest.main()
