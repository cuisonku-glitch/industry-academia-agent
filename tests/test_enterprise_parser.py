"""Tests for deterministic, evidence-grounded enterprise need parsing."""

from __future__ import annotations

import copy
import contextlib
import io
import sys
import unittest
from unittest.mock import patch

from src.extraction.enterprise_parser import (
    DEFAULT_REQUEST,
    parse_enterprise_need,
    parse_args,
    validate_enterprise_profile,
)


class EnterpriseParserTests(unittest.TestCase):
    def test_guide_example_maps_product_language_to_research_capabilities(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)

        self.assertEqual(profile["industry"], "工业检测")
        self.assertEqual(profile["product"], "X射线探伤设备")
        self.assertEqual(profile["technical_problems"], [])
        self.assertEqual(
            profile["required_capabilities"],
            ["高灵敏度X射线探测", "低成本材料", "大面积制备"],
        )
        self.assertIn("优先支持大面积制备", profile["constraints"])
        self.assertIn("工业探伤", profile["keywords"])
        self.assertIn("探测材料", profile["keywords"])

    def test_every_parsed_value_retains_an_original_phrase(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        for mapping in profile["evidence_map"]:
            self.assertTrue(mapping["matched_phrases"])
            for phrase in mapping["matched_phrases"]:
                self.assertIn(phrase.casefold(), profile["original_request"].casefold())

    def test_explicit_problems_and_numeric_constraint_are_extracted(self) -> None:
        profile = parse_enterprise_need(
            "我们生产X射线探测器，现有灵敏度不足、成本过高，"
            "希望高灵敏度，工作电压不超过20 V。"
        )
        self.assertIn("现有探测灵敏度不足", profile["technical_problems"])
        self.assertIn("材料或制备成本偏高", profile["technical_problems"])
        self.assertIn("高灵敏度X射线探测", profile["required_capabilities"])
        self.assertTrue(any("电压不超过20 V" in item for item in profile["constraints"]))

    def test_numeric_targets_foundations_and_exclusions_remain_traceable(self) -> None:
        request = (
            "我们生产X射线探测器，已有小型样机，要求灵敏度至少1200 μC "
            "Gy^-1 cm^-2，工作电压不超过20 V，在50 kVp条件下测试，不能使用铅。"
        )
        profile = parse_enterprise_need(request)
        self.assertEqual(len(profile["target_metrics"]), 2)
        self.assertEqual(profile["target_metrics"][0]["name"], "灵敏度")
        self.assertEqual(profile["target_metrics"][0]["operator"], ">=")
        self.assertEqual(profile["target_metrics"][0]["unit"], "μC Gy^-1 cm^-2")
        self.assertEqual(
            profile["target_metrics"][0]["test_condition"],
            "在50 kVp条件下测试",
        )
        self.assertEqual(profile["existing_foundations"], ["已有小型样机"])
        self.assertEqual(profile["excluded_approaches"], ["不能使用铅"])
        self.assertNotIn("在50 kVp条件下测试", profile["unparsed_fragments"])

    def test_unknown_industry_and_product_remain_explicitly_unknown(self) -> None:
        profile = parse_enterprise_need("希望获得快速响应能力。")
        self.assertEqual(profile["industry"], "未明确")
        self.assertEqual(profile["product"], "未明确")
        self.assertEqual(profile["required_capabilities"], ["快速响应探测"])

    def test_empty_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "不能为空"):
            parse_enterprise_need("  \n  ")

    def test_validation_rejects_unmapped_claim(self) -> None:
        profile = parse_enterprise_need(DEFAULT_REQUEST)
        invalid = copy.deepcopy(profile)
        invalid["required_capabilities"].append("不存在的能力")
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            validate_enterprise_profile(invalid)

    def test_cli_does_not_silently_use_the_guide_example(self) -> None:
        with patch.object(sys, "argv", ["enterprise_parser.py"]):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    parse_args()

    def test_cli_requires_explicit_demo_flag_for_the_guide_example(self) -> None:
        with patch.object(sys, "argv", ["enterprise_parser.py", "--demo"]):
            self.assertTrue(parse_args().demo)


if __name__ == "__main__":
    unittest.main()
