"""Tests for deterministic, evidence-preserving teacher profiles."""

from __future__ import annotations

import copy
import json
import unittest

from src.extraction.teacher_profiler import (
    build_teacher_profile,
    build_teacher_profiles,
    validate_capability_record,
    validate_teacher_profile,
)


def make_record(
    title: str,
    author: str,
    direction: str,
    chunk_suffix: str,
) -> dict[str, object]:
    claims = {
        "research_direction": [direction],
        "core_technologies": ["像素化 X 射线探测器设计"],
        "applications": ["医学成像", "工业无损检测"],
        "industry_potential": ["可用于柔性曲面成像设备"],
    }
    evidence_map = []
    for field, values in claims.items():
        for index, claim in enumerate(values, start=1):
            evidence_map.append(
                {
                    "field": field,
                    "claim": claim,
                    "sources": [
                        {
                            "chunk_id": f"{chunk_suffix}_{field}_{index}",
                            "page_start": 10 + index,
                            "page_end": 10 + index,
                        }
                    ],
                }
            )
    return {
        "paper": {
            "file_name": f"{title}.pdf",
            "title": title,
            "author": author,
            "teacher": "徐修文",
            "year": 2025,
        },
        "research_problem": "提高 X 射线成像性能",
        **claims,
        "evidence_map": evidence_map,
        "_source_file": f"{title}.json",
    }


class TeacherProfilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            make_record("论文甲", "学生甲", "X 射线成像", "a"),
            make_record("论文乙", "学生乙", "x射线成像", "b"),
        ]

    def test_build_profile_merges_normalized_duplicate_directions(self) -> None:
        profile = build_teacher_profile("徐修文", self.records)
        self.assertEqual(profile["teacher"], "徐修文")
        self.assertEqual(profile["statistics"]["paper_count"], 2)
        self.assertEqual(profile["statistics"]["author_count"], 2)
        self.assertEqual(len(profile["research_directions"]), 1)
        self.assertEqual(len(profile["representative_papers"]), 2)

    def test_profile_derives_traceable_industry_tags(self) -> None:
        profile = build_teacher_profile("徐修文", self.records)
        self.assertIn("医疗影像与医疗器械", profile["potential_industries"])
        self.assertIn("工业无损检测", profile["potential_industries"])
        self.assertIn("柔性电子与可穿戴设备", profile["potential_industries"])
        industry_mappings = [
            item
            for item in profile["evidence_map"]
            if item["profile_field"] == "potential_industries"
        ]
        self.assertTrue(all(item["papers"] for item in industry_mappings))
        self.assertTrue(
            all(paper["sources"] for item in industry_mappings for paper in item["papers"])
        )

    def test_profile_does_not_copy_original_chunk_text(self) -> None:
        profile = build_teacher_profile("徐修文", self.records)
        serialized = json.dumps(profile, ensure_ascii=False)
        self.assertNotIn('"text"', serialized)
        self.assertIn('"chunk_id"', serialized)

    def test_build_profiles_groups_teachers(self) -> None:
        other = copy.deepcopy(self.records[0])
        other["paper"]["teacher"] = "另一位老师"
        profiles = build_teacher_profiles([*self.records, other])
        self.assertEqual([profile["teacher"] for profile in profiles], ["另一位老师", "徐修文"])

    def test_capability_validation_rejects_missing_evidence(self) -> None:
        invalid = copy.deepcopy(self.records[0])
        invalid["evidence_map"] = []
        with self.assertRaisesRegex(RuntimeError, "缺少证据"):
            validate_capability_record(invalid, "invalid.json")

    def test_profile_validation_rejects_missing_mapping(self) -> None:
        profile = build_teacher_profile("徐修文", self.records)
        profile["evidence_map"] = profile["evidence_map"][:-1]
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            validate_teacher_profile(profile)


if __name__ == "__main__":
    unittest.main()
