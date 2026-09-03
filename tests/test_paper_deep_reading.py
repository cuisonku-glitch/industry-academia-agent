"""Offline tests for Kimi structured reading, citations, and draw.io output."""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pymupdf

from src.library.paper_deep_reading import (
    PaperDeepReadingService,
    validate_deep_reading,
)
from src.library.paper_figures import PaperFigureService
from src.repository import PaperRecord
from src.retrieval.rag import MoonshotConfig


class PaperDeepReadingTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return {
            "executive_summary": {"text": "完成传感器设计与验证。", "source_labels": ["E01"]},
            "research_problem": {"text": "提升传感灵敏度。", "source_labels": ["E01"]},
            "innovations": [{"claim": "提出新型结构。", "source_labels": ["E01"]}],
            "method_steps": [{"name": "结构设计", "description": "完成器件设计。", "source_labels": ["E01"]}],
            "key_findings": [{"claim": "灵敏度得到提升。", "source_labels": ["E01"]}],
            "figure_interpretations": [],
            "formula_interpretations": [{"source_id": "Q01", "formula": "S=Δλ/ΔT", "meaning": "描述灵敏度。", "conditions": "测试区间内。", "source_labels": ["Q01", "E01"]}],
            "transfer_assets": [{"claim": "可复用器件结构。", "source_labels": ["E01"]}],
            "limitations": [{"claim": "长期稳定性待验证。", "source_labels": ["E01"]}],
            "uncertainties": ["符号定义需对照 PDF 复核。"],
        }

    def test_rejects_unknown_citation(self) -> None:
        payload = self._payload()
        payload["executive_summary"] = {"text": "错误", "source_labels": ["E99"]}
        with self.assertRaisesRegex(RuntimeError, "不存在的证据标签"):
            validate_deep_reading(
                payload,
                evidence_labels={"E01"},
                figure_labels=set(),
                formula_labels={"Q01"},
            )

    def test_generate_persists_report_and_editable_route_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            pdf_path = root / "paper.pdf"
            document = pymupdf.open()
            document.new_page().insert_text((72, 72), "fixture")
            document.save(pdf_path)
            document.close()
            paper_id = "d" * 64
            record = PaperRecord(
                paper_id=paper_id,
                sha256=paper_id,
                file_name=pdf_path.name,
                file_path=str(pdf_path),
                title="结构化精读测试",
                authors=("作者甲",),
                teacher="导师乙",
                year=2026,
                ingestion_status="indexed",
            )
            parsed_directory = root / "parsed"
            parsed_directory.mkdir()
            parsed = {
                "paper_id": paper_id,
                "file_name": pdf_path.name,
                "total_pages": 1,
                "toc": [{"level": 1, "title": "摘要", "page": 1}],
                "pages": [
                    {
                        "page": 1,
                        "text": "摘要 本文提出新型传感结构并完成实验验证。灵敏度 S=Δλ/ΔT，在测试区间内获得提升，长期稳定性仍需验证。",
                        "blocks": [
                            {"block_number": 1, "block_type": "paragraph", "text": "摘要"},
                            {"block_number": 2, "block_type": "paragraph", "text": "本文提出新型传感结构并完成实验验证。灵敏度 S=Δλ/ΔT，在测试区间内获得提升，长期稳定性仍需验证。该研究形成可复用的器件设计和实验流程，可作为后续工程样机开发的论文证据。"},
                        ],
                    }
                ],
            }
            with gzip.open(
                parsed_directory / f"{paper_id}.json.gz", "wt", encoding="utf-8"
            ) as destination:
                json.dump(parsed, destination, ensure_ascii=False)

            class Recorder:
                def __init__(self, payload: dict[str, object]) -> None:
                    self.payload = payload
                    self.kwargs: dict[str, object] | None = None

                def create(self, **kwargs: object) -> SimpleNamespace:
                    self.kwargs = kwargs
                    message = SimpleNamespace(content=json.dumps(self.payload, ensure_ascii=False))
                    choice = SimpleNamespace(message=message, finish_reason="stop")
                    usage = SimpleNamespace(prompt_tokens=120, completion_tokens=80, total_tokens=200)
                    return SimpleNamespace(choices=[choice], usage=usage)

            recorder = Recorder(self._payload())
            client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
            figure_service = PaperFigureService(
                parsed_directory=parsed_directory,
                asset_directory=root / "assets",
            )
            service = PaperDeepReadingService(
                parsed_directory=parsed_directory,
                report_directory=root / "reports",
                route_directory=root / "routes",
                figure_service=figure_service,
                config=MoonshotConfig("test", "https://example.invalid/v1", "kimi-k3"),
                client=client,
            )
            result = service.generate(record, include_figures=False)

            self.assertTrue(result.report_path.is_file())
            self.assertTrue(result.json_path.is_file())
            self.assertTrue(result.drawio_path.is_file())
            self.assertIn("## 图版解读", result.report)
            self.assertIn("## 公式解读", result.report)
            root_element = ET.fromstring(result.drawio_path.read_text(encoding="utf-8"))
            self.assertEqual(root_element.tag, "mxfile")
            assert recorder.kwargs is not None
            self.assertEqual(recorder.kwargs["response_format"], {"type": "json_object"})
            messages = recorder.kwargs["messages"]
            self.assertIsInstance(messages[1]["content"], list)
            self.assertEqual(messages[1]["content"][0]["type"], "text")


if __name__ == "__main__":
    unittest.main()
