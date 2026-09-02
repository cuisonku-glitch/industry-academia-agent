"""Acceptance tests for the tracked public enterprise requirement case."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.extraction.enterprise_parser import parse_enterprise_need


CASE_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "public_enterprise_cases.json"
)


class PublicEnterpriseCaseTests(unittest.TestCase):
    def test_jiangxi_cable_case_is_traceable_and_quantitative(self) -> None:
        case = json.loads(CASE_PATH.read_text(encoding="utf-8"))["cases"][0]
        self.assertEqual(case["organization"], "江西电缆有限责任公司")
        self.assertTrue(case["source_url"].startswith("http"))
        self.assertIn("不代表本项目获得了该企业委托", case["notice"])

        profile = parse_enterprise_need(case["request_text"])
        self.assertEqual(profile["industry"], "先进装备制造")
        self.assertEqual(profile["product"], "超高压线缆在线测控系统")
        self.assertIn("超高压线缆在线同心度测量", profile["required_capabilities"])
        self.assertIn("线缆表面缺陷智能检测", profile["required_capabilities"])
        self.assertGreaterEqual(len(profile["target_metrics"]), 8)
        raw_metrics = "\n".join(
            metric["raw_text"] for metric in profile["target_metrics"]
        )
        self.assertIn("±0.02 mm", raw_metrics)
        self.assertIn("10 m/min", raw_metrics)


if __name__ == "__main__":
    unittest.main()
