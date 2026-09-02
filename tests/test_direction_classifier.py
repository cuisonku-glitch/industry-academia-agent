"""Tests for deterministic, provenance-aware paper direction routing."""

from __future__ import annotations

import unittest

from src.extraction.direction_classifier import (
    classify_paper_direction,
    load_direction_taxonomy,
    validate_direction_assignment,
)


class DirectionClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = load_direction_taxonomy()

    def test_explicit_metadata_has_priority_over_text_rules(self) -> None:
        assignment = classify_paper_direction(
            {
                "title": "含有闪烁体和空间分辨率字样的论文",
                "direction": "x_ray_detector",
            },
            "像素化闪烁体 X射线成像 空间分辨率",
            taxonomy=self.taxonomy,
        )
        self.assertEqual(assignment["direction_id"], "x_ray_detector")
        self.assertEqual(assignment["source"], "metadata")
        self.assertEqual(assignment["confidence"], 1.0)

    def test_keyword_rule_records_terms_and_confidence(self) -> None:
        assignment = classify_paper_direction(
            {"title": "像素化闪烁体的X射线成像性能", "direction": "unclassified"},
            "该体系具有较高空间分辨率和光产额。",
            taxonomy=self.taxonomy,
        )
        self.assertEqual(assignment["direction_id"], "x_ray_imaging")
        self.assertEqual(assignment["source"], "keyword_rule")
        self.assertIn("像素化闪烁体", assignment["matched_terms"])
        self.assertGreater(assignment["confidence"], 0.5)
        validate_direction_assignment(assignment, self.taxonomy)

    def test_unknown_metadata_is_not_forced_into_a_direction(self) -> None:
        assignment = classify_paper_direction(
            {"title": "没有方向信号", "direction": "invented_direction"},
            "普通研究内容。",
            taxonomy=self.taxonomy,
        )
        self.assertEqual(assignment["direction_id"], "unclassified")
        self.assertEqual(assignment["source"], "unclassified")
        self.assertIn("invented_direction", assignment["note"])

    def test_model_fallback_must_reach_confidence_threshold(self) -> None:
        def low_confidence(_paper: dict, _text: str) -> dict:
            return {"direction_id": "optoelectronic_detector", "confidence": 0.4}

        assignment = classify_paper_direction(
            {"title": "无关键词论文", "direction": "unclassified"},
            "无规则命中。",
            taxonomy=self.taxonomy,
            model_fallback=low_confidence,
        )
        self.assertEqual(assignment["direction_id"], "unclassified")


if __name__ == "__main__":
    unittest.main()
