"""Offline tests for transparent hybrid research-industry matching."""

from __future__ import annotations

import copy
import math
import unittest
from typing import Any, Sequence

from src.matching.matcher import (
    ResearchIndustryMatcher,
    SCORE_WEIGHTS,
    calculate_weighted_score,
    validate_match_result,
)


class FakeEmbedder:
    """Create tiny normalized vectors from known technical concepts."""

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.casefold()
        values = [
            float("x射线" in lowered or "x 射线" in lowered or "探测" in lowered),
            float("高灵敏度" in lowered),
            float("大面积" in lowered or "直写" in lowered),
            float("低成本" in lowered),
            float("工业" in lowered or "无损" in lowered),
        ]
        if not any(values):
            values[0] = 0.01
        norm = math.sqrt(sum(value * value for value in values))
        return [value / norm for value in values]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class FakeVectorStore:
    def __init__(self) -> None:
        self.query_calls = 0

    def count(self) -> int:
        return 10

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.query_calls += 1
        teacher = (where or {}).get("teacher", "徐修文")
        return [
            {
                "rank": 1,
                "chunk_id": "paper_a_chunk_001",
                "text": "高灵敏度 X 射线探测及工业无损检测。",
                "metadata": {
                    "title": "论文甲",
                    "author": "学生甲",
                    "teacher": teacher,
                    "year": 2025,
                    "page_start": 10,
                    "page_end": 10,
                },
                "similarity": 0.90,
            },
            {
                "rank": 2,
                "chunk_id": "paper_a_chunk_002",
                "text": "直写工艺支持大面积制备。",
                "metadata": {
                    "title": "论文甲",
                    "author": "学生甲",
                    "teacher": teacher,
                    "year": 2025,
                    "page_start": 11,
                    "page_end": 12,
                },
                "similarity": 0.80,
            },
            {
                "rank": 3,
                "chunk_id": "paper_b_chunk_001",
                "text": "无关内容。",
                "metadata": {
                    "title": "论文乙",
                    "author": "学生乙",
                    "teacher": teacher,
                    "year": 2025,
                    "page_start": 5,
                    "page_end": 5,
                },
                "similarity": 0.20,
            },
        ][:top_k]


def make_enterprise() -> dict[str, Any]:
    return {
        "industry": "工业检测",
        "product": "X射线探伤设备",
        "technical_problems": [],
        "required_capabilities": [
            "高灵敏度X射线探测",
            "大面积制备",
            "低成本材料",
        ],
        "constraints": [],
        "keywords": ["X射线", "工业探伤"],
        "original_request": "工业 X 射线探伤需要高灵敏度、大面积和低成本材料。",
    }


def make_teacher_profile() -> dict[str, Any]:
    values = ["高灵敏度X射线探测", "大面积直写制备"]
    return {
        "teacher": "徐修文",
        "research_directions": ["X射线探测器"],
        "core_capabilities": values,
        "application_domains": ["工业无损检测"],
        "potential_industries": ["工业检测设备"],
        "representative_papers": [],
        "evidence_map": [
            {
                "profile_field": "core_capabilities",
                "value": value,
                "papers": [
                    {
                        "title": "论文甲",
                        "sources": [
                            {
                                "chunk_id": f"evidence_{index}",
                                "page_start": index,
                                "page_end": index,
                            }
                        ],
                    }
                ],
            }
            for index, value in enumerate(values, start=1)
        ],
    }


class MatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = ResearchIndustryMatcher(
            embedder=FakeEmbedder(),
            vector_store=FakeVectorStore(),
            capability_threshold=0.8,
            paper_threshold=0.45,
        )

    def test_weighted_score_is_reproducible(self) -> None:
        raw = {metric: 1.0 for metric in SCORE_WEIGHTS}
        score, breakdown = calculate_weighted_score(raw)
        self.assertEqual(score, 100.0)
        self.assertAlmostEqual(sum(item["contribution"] for item in breakdown.values()), 100.0)

    def test_match_outputs_all_guide_fields_and_traceable_evidence(self) -> None:
        result = self.matcher.match(make_enterprise(), [make_teacher_profile()], top_k=3)
        recommendation = result["recommendations"][0]

        self.assertEqual(recommendation["recommended_teacher"], "徐修文")
        self.assertEqual(set(recommendation["score_breakdown"]), set(SCORE_WEIGHTS))
        self.assertEqual(len(recommendation["core_matching_technologies"]), 2)
        self.assertEqual(len(recommendation["technology_gap"]), 1)
        self.assertEqual(recommendation["technology_gap"][0]["required_capability"], "低成本材料")
        self.assertEqual(len(recommendation["paper_evidence"]), 2)
        self.assertEqual(recommendation["relevant_papers"][0]["evidence_pages"], [10, 11, 12])
        self.assertTrue(recommendation["matching_reason"])
        self.assertTrue(recommendation["potential_collaboration_directions"])

    def test_validation_rejects_tampered_total_score(self) -> None:
        result = self.matcher.match(make_enterprise(), [make_teacher_profile()], top_k=3)
        invalid = copy.deepcopy(result)
        invalid["recommendations"][0]["matching_score"] += 10
        with self.assertRaisesRegex(RuntimeError, "不一致"):
            validate_match_result(invalid)

    def test_teacher_recommendations_are_sorted_by_score_then_name(self) -> None:
        second = make_teacher_profile()
        second["teacher"] = "另一位老师"
        result = self.matcher.match(make_enterprise(), [second, make_teacher_profile()], top_k=3)
        self.assertEqual(
            [item["recommended_teacher"] for item in result["recommendations"]],
            ["另一位老师", "徐修文"],
        )

    def test_precomputed_paper_evidence_is_reused_by_matching_agent(self) -> None:
        store = FakeVectorStore()
        matcher = ResearchIndustryMatcher(
            embedder=FakeEmbedder(),
            vector_store=store,
            capability_threshold=0.8,
            paper_threshold=0.45,
        )
        matcher.match(
            make_enterprise(),
            [make_teacher_profile()],
            top_k=3,
            paper_evidence_by_teacher={"徐修文": []},
        )
        self.assertEqual(store.query_calls, 0)


if __name__ == "__main__":
    unittest.main()
