"""Offline tests for the stage-10 Agent coordinator and evidence gate."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from src.agents.workflow import (
    Coordinator,
    EvidenceAgent,
    MatchingAgent,
    PaperAgent,
    ReportAgent,
    RequirementAgent,
    ResearchAgent,
    new_state,
)
from src.agents.coordinator import build_coordinator


def make_teacher_profile() -> dict[str, Any]:
    return {
        "teacher": "徐修文",
        "research_directions": ["X射线探测"],
        "core_capabilities": ["高灵敏度探测"],
        "application_domains": ["工业无损检测"],
        "potential_industries": ["工业检测"],
        "evidence_map": [],
    }


def make_paper_evidence() -> dict[str, Any]:
    return {
        "rank": 1,
        "chunk_id": "paper_chunk_001",
        "title": "测试论文",
        "author": "测试学生",
        "teacher": "徐修文",
        "year": 2025,
        "page_start": 10,
        "page_end": 11,
        "similarity": 0.8,
        "excerpt": "高灵敏度 X 射线探测。",
    }


def make_match_result(with_paper_evidence: bool = True) -> dict[str, Any]:
    paper_evidence = [make_paper_evidence()] if with_paper_evidence else []
    return {
        "enterprise_need": {},
        "scoring_method": {},
        "recommendations": [
            {
                "recommended_teacher": "徐修文",
                "matching_score": 57.5,
                "score_breakdown": {
                    "semantic_similarity": {
                        "raw": 0.5,
                        "weight": 0.45,
                        "contribution": 22.5,
                    },
                    "technical_capability_coverage": {
                        "raw": 0.5,
                        "weight": 0.25,
                        "contribution": 12.5,
                    },
                    "application_domain_match": {
                        "raw": 0.5,
                        "weight": 0.15,
                        "contribution": 7.5,
                    },
                    "paper_evidence_count": {
                        "raw": 1.0,
                        "weight": 0.15,
                        "contribution": 15.0,
                    },
                },
                "core_matching_technologies": [
                    {
                        "required_capability": "高灵敏度X射线探测",
                        "matched_teacher_capability": "高灵敏度探测",
                        "similarity": 0.9,
                        "profile_evidence": [
                            {
                                "value": "高灵敏度探测",
                                "papers": [
                                    {
                                        "title": "测试论文",
                                        "sources": [
                                            {
                                                "chunk_id": "paper_chunk_001",
                                                "page_start": 10,
                                                "page_end": 11,
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "relevant_papers": [],
                "paper_evidence": paper_evidence,
                "matching_reason": ["存在语义、能力和论文证据。"],
                "technology_gap": [
                    {
                        "required_capability": "低成本材料",
                        "matched_teacher_capability": "材料制备",
                        "similarity": 0.3,
                    }
                ],
                "potential_collaboration_directions": ["开展样品验证。"],
            }
        ],
        "generated_at": "2026-01-01T00:00:00+00:00",
    }


class FakeMatcher:
    def __init__(self, with_paper_evidence: bool = True) -> None:
        self.with_paper_evidence = with_paper_evidence
        self.received_evidence: dict[str, list[dict[str, Any]]] | None = None

    def retrieve_paper_evidence(
        self, enterprise_query: str, teacher: str, top_k: int
    ) -> list[dict[str, Any]]:
        if not self.with_paper_evidence:
            return []
        evidence = make_paper_evidence()
        evidence["teacher"] = teacher
        return [evidence]

    def match(
        self,
        enterprise: dict[str, Any],
        teacher_profiles: list[dict[str, Any]],
        top_k: int,
        paper_evidence_by_teacher: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        self.received_evidence = paper_evidence_by_teacher
        return make_match_result(self.with_paper_evidence)


class AgentWorkflowTests(unittest.TestCase):
    def _coordinator(self, matcher: FakeMatcher) -> Coordinator:
        return Coordinator(
            requirement_agent=RequirementAgent(),
            research_agent=ResearchAgent(
                teacher_directory=Path("unused"),
                loader=lambda _: [make_teacher_profile()],
            ),
            paper_agent=PaperAgent(matcher, top_k=5),
            matching_agent=MatchingAgent(matcher, top_k=5),
            evidence_agent=EvidenceAgent(),
            report_agent=ReportAgent(),
        )

    def test_coordinator_runs_six_agents_in_dependency_order(self) -> None:
        matcher = FakeMatcher()
        state = self._coordinator(matcher).run(
            "我们开发工业X射线探伤设备，需要高灵敏度探测。",
            input_mode="user",
        )
        self.assertEqual(
            [item["agent"] for item in state["trace"]],
            [
                "Requirement Agent",
                "Research Agent",
                "Paper Agent",
                "Matching Agent",
                "Evidence Agent",
                "Report Agent",
            ],
        )
        self.assertIn("徐修文", state["report"])
        self.assertIn("Chunk `paper_chunk_001`", state["report"])
        self.assertEqual(state["evidence_review"]["overall_status"], "passed")
        self.assertEqual(len(matcher.received_evidence["徐修文"]), 1)

    def test_evidence_agent_flags_recommendation_without_paper_chunks(self) -> None:
        state = new_state("测试需求", "user")
        state["match_result"] = make_match_result(with_paper_evidence=False)
        EvidenceAgent().run(state)
        self.assertEqual(state["evidence_review"]["overall_status"], "needs_review")
        self.assertIn(
            "没有达到阈值的论文 Chunk 证据",
            state["evidence_review"]["recommendations"][0]["issues"],
        )

    def test_demo_mode_is_explicitly_labeled_in_report(self) -> None:
        state = self._coordinator(FakeMatcher()).run(
            "指南中的演示需求。",
            input_mode="demo",
        )
        self.assertIn("输入类型：指南示例演示", state["report"])

    def test_evidence_agent_rejects_tampered_teacher_source(self) -> None:
        state = new_state("测试需求", "user")
        result = make_match_result()
        tampered = copy.deepcopy(result)
        tampered["recommendations"][0]["paper_evidence"][0]["teacher"] = "其他老师"
        state["match_result"] = tampered
        EvidenceAgent().run(state)
        self.assertEqual(state["evidence_review"]["overall_status"], "needs_review")

    def test_production_builder_reuses_one_matcher_across_agents(self) -> None:
        matcher = FakeMatcher()
        coordinator = build_coordinator(matcher=matcher)
        self.assertIs(coordinator.agents[2].matcher, matcher)
        self.assertIs(coordinator.agents[3].matcher, matcher)


if __name__ == "__main__":
    unittest.main()
