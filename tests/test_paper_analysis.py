"""Tests for local evidence-first paper reading reports."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from src.library import PaperAnalysisService, select_reading_evidence
from src.repository import PaperCatalog


class PaperAnalysisTests(unittest.TestCase):
    def test_evidence_selection_and_report_keep_page_citations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_path = root / "paper.pdf"
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "fixture")
            document.save(pdf_path)
            document.close()
            catalog = PaperCatalog(root / "catalog.sqlite3")
            record = catalog.register_pdf(
                pdf_path,
                title="证据精读测试",
                teacher="导师甲",
                authors=("学生乙",),
                ingestion_status="indexed",
            )
            parsed_directory = root / "parsed"
            parsed_directory.mkdir()
            parsed = {
                "paper_id": record.paper_id,
                "file_name": record.file_name,
                "total_pages": 5,
                "parser_version": "layout_v2",
                "toc": [
                    {"level": 1, "title": "摘要", "page": 1},
                    {"level": 1, "title": "研究方法", "page": 2},
                    {"level": 1, "title": "实验结果", "page": 3},
                    {"level": 1, "title": "结论", "page": 5},
                ],
                "pages": [
                    {
                        "page": page,
                        "text": f"{heading}\n{body}",
                        "blocks": [
                            {"block_number": 1, "block_type": "paragraph", "text": heading},
                            {"block_number": 2, "block_type": "paragraph", "text": body},
                        ],
                    }
                    for page, heading, body in (
                        (1, "摘要", "本文研究光纤传感，面向工业现场连续监测需求，提出可定位的传感方案，并完成系统设计、样机搭建与性能验证。"),
                        (2, "研究方法", "本文设计光栅封装结构和解调电路，本系统采用分阶段实验方案，依次完成器件标定、样机集成、环境测试和结果复核。"),
                        (3, "实验结果", "测试结果表明系统灵敏度提高，并在多轮重复实验中保持稳定；实验结果同时记录响应时间、测量误差和工作范围。"),
                        (4, "研究背景", "行业现场需要实时监测，但现有设备在复杂环境下存在的问题包括抗干扰能力不足、测量范围有限以及维护成本较高。"),
                        (5, "结论", "研究完成了系统设计和实验验证，结论显示方案具备进一步工程化的基础，同时提出长期稳定性和现场适配仍需后续研究。"),
                    )
                ],
            }
            with gzip.open(
                parsed_directory / f"{record.paper_id}.json.gz",
                mode="wt",
                encoding="utf-8",
            ) as destination:
                json.dump(parsed, destination, ensure_ascii=False)
            service = PaperAnalysisService(
                catalog,
                parsed_directory=parsed_directory,
                report_directory=root / "reports",
            )

            result = service.generate_local_reading(record)

            self.assertGreaterEqual(result.evidence_count, 3)
            self.assertIn("第 2 页", result.report)
            self.assertIn("Chunk：`", result.report)
            self.assertIn("未调用外部大模型", result.report)
            self.assertEqual(service.load_report(record.paper_id), result.report)

    def test_selection_does_not_use_reference_chunks(self) -> None:
        chunks = [
            {
                "chunk_id": "reference",
                "text": "方法 结果 结论",
                "metadata": {
                    "section_type": "reference",
                    "section_path": "参考文献",
                    "page_start": 8,
                    "page_end": 8,
                },
            }
        ]
        selected = select_reading_evidence(chunks)
        self.assertTrue(all(not items for items in selected.values()))


if __name__ == "__main__":
    unittest.main()
