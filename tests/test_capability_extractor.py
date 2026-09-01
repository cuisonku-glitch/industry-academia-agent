"""Offline tests for traceable research capability extraction."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from src.extraction.capability_extractor import (
    CapabilityExtractor,
    STRUCTURED_FIELDS,
    build_extraction_prompt,
    evidence_rejection_reason,
    parse_json_object,
    validate_extraction,
)
from src.retrieval.rag import MoonshotConfig


class CapabilityExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.paper = {
            "file_name": "paper.pdf",
            "title": "测试论文",
            "author": "测试作者",
            "teacher": "测试导师",
            "year": 2026,
        }
        self.chunk = {
            "source_label": "S01",
            "chunk_id": "paper_chunk_0001",
            "text": "本文研究 X 射线探测材料，并采用 XRD 表征。",
            "matched_fields": ["research_problem", "methods"],
            "metadata": {"page_start": 12, "page_end": 12},
        }

    def _valid_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            field: [] for field in STRUCTURED_FIELDS[1:]
        }
        payload["research_problem"] = "提高 X 射线探测性能"
        payload["methods"] = ["XRD"]
        payload["evidence_map"] = [
            {
                "field": "research_problem",
                "claim": "提高 X 射线探测性能",
                "source_labels": ["S01"],
            },
            {"field": "methods", "claim": "XRD", "source_labels": ["S01"]},
        ]
        return payload

    def test_parse_json_code_fence(self) -> None:
        self.assertEqual(
            parse_json_object('```json\n{"ok": true}\n```'),
            {"ok": True},
        )

    def test_prompt_contains_traceable_source(self) -> None:
        prompt = build_extraction_prompt(self.paper, [self.chunk])
        self.assertIn("[S01]", prompt)
        self.assertIn("paper_chunk_0001", prompt)
        self.assertIn("页码：12-12", prompt)

    def test_validate_requires_real_source_labels(self) -> None:
        payload = self._valid_payload()
        payload["evidence_map"] = [
            {"field": "methods", "claim": "XRD", "source_labels": ["S99"]}
        ]
        with self.assertRaisesRegex(RuntimeError, "不存在的证据标签"):
            validate_extraction(payload, [self.chunk])

    def test_validate_requires_evidence_for_every_claim(self) -> None:
        payload = self._valid_payload()
        payload["evidence_map"] = [
            {"field": "methods", "claim": "XRD", "source_labels": ["S01"]}
        ]
        with self.assertRaisesRegex(RuntimeError, "没有证据映射"):
            validate_extraction(payload, [self.chunk])

    def test_validate_accepts_complete_payload(self) -> None:
        structured, evidence = validate_extraction(
            self._valid_payload(), [self.chunk]
        )
        self.assertEqual(structured["methods"], ["XRD"])
        self.assertEqual(len(evidence), 2)

    def test_filter_rejects_non_research_sections(self) -> None:
        self.assertIsNotNone(evidence_rejection_reason("致谢：感谢我的导师"))
        self.assertIsNotNone(
            evidence_rejection_reason("目录 第一章......................1")
        )
        self.assertIsNotNone(
            evidence_rejection_reason("[1] A [J]. [2] B [J]. [3] C [J].")
        )
        self.assertIsNotNone(
            evidence_rejection_reason("南京邮电大学学位论文使用授权声明")
        )
        self.assertIsNone(evidence_rejection_reason("本文采用 XRD 表征材料结构。"))

    def test_extract_resolves_sources_without_network(self) -> None:
        payload = self._valid_payload()

        class Recorder:
            def __init__(self) -> None:
                self.kwargs: dict[str, object] | None = None

            def create(self, **kwargs: object) -> SimpleNamespace:
                self.kwargs = kwargs
                message = SimpleNamespace(
                    content=json.dumps(payload, ensure_ascii=False)
                )
                choice = SimpleNamespace(message=message, finish_reason="stop")
                usage = SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                )
                return SimpleNamespace(choices=[choice], usage=usage)

        recorder = Recorder()
        client = SimpleNamespace(chat=SimpleNamespace(completions=recorder))
        extractor = CapabilityExtractor(
            config=MoonshotConfig("test-key", "https://example.invalid/v1", "kimi-k3"),
            client=client,
        )
        result = extractor.extract(self.paper, [self.chunk])

        self.assertEqual(result["sources"][0]["chunk_id"], "paper_chunk_0001")
        self.assertEqual(result["evidence_map"][0]["sources"][0]["page_start"], 12)
        self.assertEqual(result["usage"]["total_tokens"], 150)
        assert recorder.kwargs is not None
        self.assertEqual(recorder.kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(
            recorder.kwargs["extra_body"], {"thinking": {"type": "disabled"}}
        )


if __name__ == "__main__":
    unittest.main()
