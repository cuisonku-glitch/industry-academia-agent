"""Offline tests for the stage-10 Agent coordinator and evidence gate."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from src.agents.workflow import (
    ClarificationAgent,
    Coordinator,
    EvidenceAgent,
    MatchingAgent,
    PaperAgent,
    ReportAgent,
    RequirementAgent,
    ResearchAgent,
    SolutionAgent,
    new_state,
)
from src.agents.coordinator import build_coordinator
from src.extraction.enterprise_parser import parse_enterprise_need
from src.extraction.enterprise_profile_editor import (
    apply_enterprise_edits,
    confirm_enterprise_profile,
)
from src.solutions import build_enterprise_solution


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
            clarification_agent=ClarificationAgent(),
            research_agent=ResearchAgent(
                teacher_directory=Path("unused"),
                loader=lambda _: [make_teacher_profile()],
            ),
            paper_agent=PaperAgent(matcher, top_k=5),
            matching_agent=MatchingAgent(matcher, top_k=5),
            solution_agent=SolutionAgent(),
            evidence_agent=EvidenceAgent(),
            report_agent=ReportAgent(),
        )

    def test_coordinator_runs_p1_agents_in_dependency_order(self) -> None:
        matcher = FakeMatcher()
        state = self._coordinator(matcher).run(
            "我们开发工业X射线探伤设备，需要高灵敏度探测。",
            input_mode="user",
            requirement_confirmed=True,
        )
        self.assertEqual(
            [item["agent"] for item in state["trace"]],
            [
                "Requirement Agent",
                "Clarification Agent",
                "Research Agent",
                "Paper Agent",
                "Matching Agent",
                "Solution Agent",
                "Evidence Agent",
                "Report Agent",
            ],
        )
        self.assertIn("徐修文", state["report"])
        self.assertIn("Chunk `paper_chunk_001`", state["report"])
        self.assertEqual(state["evidence_review"]["overall_status"], "passed")
        self.assertEqual(len(matcher.received_evidence["徐修文"]), 1)
        self.assertEqual(state["solution_bundle"]["solution_gate"]["status"], "provisional")
        self.assertTrue(state["route_drawio"].startswith("<?xml"))

    def _state_for_evidence_agent(self, result: dict[str, Any]) -> dict[str, Any]:
        request = "我们开发工业X射线探伤设备，需要高灵敏度探测。"
        profile = parse_enterprise_need(request)
        module_evidence = {
            "M01": {"徐修文": list(result["recommendations"][0]["paper_evidence"])}
        }
        state = new_state(request, "user", requirement_confirmed=True)
        state["enterprise_need"] = profile
        state["match_result"] = result
        state["solution_bundle"] = build_enterprise_solution(
            profile,
            result,
            module_evidence,
            confirmed=True,
        )
        return state

    def test_evidence_agent_flags_recommendation_without_paper_chunks(self) -> None:
        result = make_match_result(with_paper_evidence=False)
        state = self._state_for_evidence_agent(result)
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
            requirement_confirmed=True,
        )
        self.assertIn("输入类型：指南示例演示", state["report"])

    def test_confirmed_edited_profile_is_used_downstream(self) -> None:
        request = "我们开发工业X射线探伤设备，需要高灵敏度探测。"
        original = parse_enterprise_need(request)
        edited = apply_enterprise_edits(
            original,
            {
                "industry": "工业在线检测",
                "product": "产线X射线质量检测系统",
                "technical_problems": original["technical_problems"],
                "required_capabilities": [
                    *original["required_capabilities"],
                    "产线联机闭环",
                ],
                "constraints": ["单线改造预算不超过80万元"],
                "existing_foundations": [],
                "excluded_approaches": [],
                "keywords": original["keywords"],
                "target_metrics": [],
                "unparsed_fragments": [],
            },
        )
        confirmed = confirm_enterprise_profile(
            edited,
            version_id="ENV-20260902T000000000000Z-12345678",
        )

        state = self._coordinator(FakeMatcher()).run(
            request,
            input_mode="user",
            requirement_confirmed=True,
            enterprise_profile=confirmed,
        )

        self.assertEqual(state["enterprise_need"]["product"], "产线X射线质量检测系统")
        self.assertEqual(state["enterprise_need"]["original_request"], request)
        self.assertIn("用户确认后的需求快照", state["report"])
        self.assertIn("单线改造预算不超过80万元", state["report"])

    def test_edited_profile_must_match_current_original_request(self) -> None:
        profile = parse_enterprise_need("需求原文 A。")
        with self.assertRaisesRegex(ValueError, "original_request"):
            self._coordinator(FakeMatcher()).run(
                "需求原文 B。",
                requirement_confirmed=True,
                enterprise_profile=profile,
            )

    def test_evidence_agent_rejects_tampered_teacher_source(self) -> None:
        result = make_match_result()
        tampered = copy.deepcopy(result)
        tampered["recommendations"][0]["paper_evidence"][0]["teacher"] = "其他老师"
        state = self._state_for_evidence_agent(tampered)
        EvidenceAgent().run(state)
        self.assertEqual(state["evidence_review"]["overall_status"], "needs_review")

    def test_production_builder_reuses_one_matcher_across_agents(self) -> None:
        matcher = FakeMatcher()
        coordinator = build_coordinator(matcher=matcher)
        self.assertIs(coordinator.agents[3].matcher, matcher)
        self.assertIs(coordinator.agents[4].matcher, matcher)


if __name__ == "__main__":
    unittest.main()
