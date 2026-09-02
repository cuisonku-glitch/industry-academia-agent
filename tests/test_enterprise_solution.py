"""Tests for the evidence-gated P1 enterprise solution loop."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from src.extraction.enterprise_parser import DEFAULT_REQUEST, parse_enterprise_need
from src.extraction.enterprise_profile_editor import apply_enterprise_edits
from src.solutions import (
    build_clarification,
    build_enterprise_solution,
    decompose_technical_need,
    route_to_drawio,
    validate_solution_bundle,
)


def make_match_result() -> dict:
    return {
        "recommendations": [
            {
                "recommended_teacher": "测试导师",
                "matching_score": 70.0,
            }
        ]
    }


def make_evidence(module_id: str, similarity: float = 0.8) -> dict:
    return {
        "chunk_id": f"paper_{module_id}_chunk_001",
        "title": "测试论文",
        "author": "测试作者",
        "teacher": "测试导师",
        "page_start": 3,
        "page_end": 4,
        "similarity": similarity,
        "excerpt": "可定位的测试论文证据。",
    }


def evidence_for_all(profile: dict) -> dict:
    modules = decompose_technical_need(profile, confirmed=True)
    return {
        module["module_id"]: {
            "测试导师": [make_evidence(module["module_id"])]
        }
        for module in modules
    }


class EnterpriseSolutionTests(unittest.TestCase):
    def test_unconfirmed_requirement_cannot_generate_a_solution(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            evidence_for_all(profile),
            confirmed=False,
        )
        self.assertEqual(bundle["solution_gate"]["status"], "blocked")
        self.assertEqual(bundle["solution_options"], [])
        self.assertEqual(
            bundle["transfer_evaluation"]["decision"],
            "pause_for_confirmation",
        )

    def test_qualitative_request_produces_only_one_provisional_solution(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            evidence_for_all(profile),
            confirmed=True,
        )
        self.assertEqual(bundle["solution_gate"]["allowed_solution_count"], 1)
        self.assertEqual(bundle["solution_gate"]["status"], "provisional")
        self.assertEqual(len(bundle["solution_options"]), 1)
        self.assertEqual(
            bundle["transfer_evaluation"]["decision"],
            "proceed_to_clarification",
        )
        self.assertIn(
            "target_metrics",
            [item["field"] for item in bundle["clarification"]["questions"]],
        )

    def test_complete_metrics_and_module_evidence_reach_feasibility_gate(self) -> None:
        profile = parse_enterprise_need(
            "我们开发工业X射线探伤设备，现有灵敏度不足，"
            "希望高灵敏度，灵敏度至少1200 μC Gy^-1 cm^-2，"
            "在50 kVp条件下测试，已有小型样机，不能使用铅。"
        )
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            evidence_for_all(profile),
            confirmed=True,
        )
        evaluation = bundle["transfer_evaluation"]
        self.assertEqual(bundle["solution_gate"]["status"], "passed")
        self.assertEqual(evaluation["decision"], "proceed_to_feasibility")
        self.assertEqual(evaluation["known_weight"], 0.7)
        self.assertEqual(
            set(evaluation["unknown_dimensions"]),
            {"engineering_maturity", "landing_constraints"},
        )
        self.assertIsNone(
            evaluation["dimensions"]["engineering_maturity"]["score"]
        )

    def test_missing_module_evidence_stops_at_evidence_gate(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        module_evidence = evidence_for_all(profile)
        module_evidence["M02"]["测试导师"] = []
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            module_evidence,
            confirmed=True,
        )
        self.assertEqual(
            bundle["transfer_evaluation"]["decision"],
            "pause_for_evidence",
        )
        self.assertIn(
            "低成本材料",
            bundle["solution_options"][0]["uncovered_gaps"],
        )

    def test_validator_rejects_a_module_phrase_not_in_enterprise_request(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            evidence_for_all(profile),
            confirmed=True,
        )
        tampered = copy.deepcopy(bundle)
        tampered["need_modules"][0]["source_phrases"] = ["企业从未说过这句话"]
        with self.assertRaisesRegex(RuntimeError, "不存在的企业原文"):
            validate_solution_bundle(tampered, profile["original_request"])

    def test_public_case_module_can_reference_original_phrase_after_edit_save(self) -> None:
        case_path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "public_enterprise_cases.json"
        )
        request = json.loads(case_path.read_text(encoding="utf-8"))["cases"][0][
            "request_text"
        ]
        parsed = parse_enterprise_need(request)
        edited = apply_enterprise_edits(
            parsed,
            {
                "industry": parsed["industry"],
                "product": parsed["product"],
                "technical_problems": parsed["technical_problems"],
                "required_capabilities": parsed["required_capabilities"],
                "constraints": parsed["constraints"],
                "existing_foundations": parsed["existing_foundations"],
                "excluded_approaches": parsed["excluded_approaches"],
                "keywords": parsed["keywords"],
                "target_metrics": parsed["target_metrics"],
                "unparsed_fragments": parsed["unparsed_fragments"],
            },
        )
        self.assertIn("多电极阵列", edited["original_request"])
        self.assertNotIn("多电极阵列", edited["confirmed_request"])

        bundle = build_enterprise_solution(
            edited,
            make_match_result(),
            evidence_for_all(edited),
            confirmed=True,
        )

        self.assertEqual(bundle["solution_gate"]["status"], "passed")
        validate_solution_bundle(bundle, edited)

    def test_drawio_export_is_native_xml_with_editable_nodes_and_edges(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        bundle = build_enterprise_solution(
            profile,
            make_match_result(),
            evidence_for_all(profile),
            confirmed=True,
        )
        xml = route_to_drawio(bundle["technical_route"])
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "mxfile")
        self.assertNotIn("<!--", xml)
        cells = root.findall(".//mxCell")
        ids = {cell.attrib["id"] for cell in cells}
        self.assertIn("R01", ids)
        self.assertTrue(any(cell.attrib.get("edge") == "1" for cell in cells))

    def test_clarification_exposes_unparsed_fragments(self) -> None:
        profile = parse_enterprise_need("希望获得快速响应能力，最好蓝色。")
        clarification = build_clarification(profile)
        questions = [item["question"] for item in clarification["questions"]]
        self.assertTrue(any("最好蓝色" in question for question in questions))


if __name__ == "__main__":
    unittest.main()
