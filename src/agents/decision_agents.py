"""Agents that score matches and enforce evidence requirements."""

from __future__ import annotations

from typing import Any

from ..matching.matcher import (
    DEFAULT_TOP_K,
    ResearchIndustryMatcher,
    validate_match_result,
)
from ..solutions import (
    build_enterprise_solution,
    route_to_drawio,
    validate_solution_bundle,
)
from .state import record_trace


class MatchingAgent:
    """Calculate hybrid scores from profiles and Paper Agent evidence."""

    name = "Matching Agent"

    def __init__(
        self,
        matcher: ResearchIndustryMatcher,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.matcher = matcher
        self.top_k = top_k

    def run(self, state: dict[str, Any]) -> None:
        result = self.matcher.match(
            state["enterprise_need"],
            state["teacher_profiles"],
            top_k=self.top_k,
            paper_evidence_by_teacher=state["paper_candidates"],
        )
        state["match_result"] = result
        record_trace(
            state,
            self.name,
            {
                "recommendation_count": len(result["recommendations"]),
                "ranking": [
                    {
                        "teacher": item["recommended_teacher"],
                        "score": item["matching_score"],
                    }
                    for item in result["recommendations"]
                ],
            },
        )


class SolutionAgent:
    """Build one evidence-gated solution, route, evaluation, and landing plan."""

    name = "Solution Agent"

    def run(self, state: dict[str, Any]) -> None:
        profile = state.get("enterprise_need")
        match_result = state.get("match_result")
        if not profile or not match_result:
            raise RuntimeError("Solution Agent 缺少企业画像或匹配结果")
        bundle = build_enterprise_solution(
            profile,
            match_result,
            state.get("module_evidence", {}),
            confirmed=bool(state["requirement_confirmation"]["confirmed"]),
        )
        state["solution_bundle"] = bundle
        state["clarification"] = bundle["clarification"]
        state["need_modules"] = bundle["need_modules"]
        state["route_drawio"] = route_to_drawio(bundle["technical_route"])
        record_trace(
            state,
            self.name,
            {
                "solution_gate": bundle["solution_gate"]["status"],
                "solution_count": len(bundle["solution_options"]),
                "route_node_count": len(bundle["technical_route"]["nodes"]),
                "transfer_decision": bundle["transfer_evaluation"]["decision"],
            },
        )


def _profile_sources_exist(match: dict[str, Any]) -> bool:
    mappings = match.get("profile_evidence", [])
    return bool(mappings) and all(
        paper.get("sources")
        for mapping in mappings
        for paper in mapping.get("papers", [])
    )


class EvidenceAgent:
    """Check that recommendations have profile and paper evidence."""

    name = "Evidence Agent"

    def run(self, state: dict[str, Any]) -> None:
        result = state.get("match_result")
        if not result:
            raise RuntimeError("Evidence Agent 缺少匹配结果")
        validate_match_result(result)
        solution_bundle = state.get("solution_bundle")
        if not solution_bundle:
            raise RuntimeError("Evidence Agent 缺少企业方案")
        validate_solution_bundle(solution_bundle, state["enterprise_need"])

        reviews: list[dict[str, Any]] = []
        for recommendation in result["recommendations"]:
            teacher = recommendation["recommended_teacher"]
            issues: list[str] = []
            paper_evidence = recommendation["paper_evidence"]
            if not paper_evidence:
                issues.append("没有达到阈值的论文 Chunk 证据")
            if any(item.get("teacher") != teacher for item in paper_evidence):
                issues.append("论文证据中的导师与推荐教师不一致")
            if any(
                not _profile_sources_exist(item)
                for item in recommendation["core_matching_technologies"]
            ):
                issues.append("核心匹配技术缺少可定位的教师画像来源")
            reviews.append(
                {
                    "teacher": teacher,
                    "status": "passed" if not issues else "needs_review",
                    "paper_evidence_count": len(paper_evidence),
                    "profile_evidence_checked": len(
                        recommendation["core_matching_technologies"]
                    ),
                    "issues": issues,
                }
            )

        review = {
            "overall_status": (
                "passed"
                if all(item["status"] == "passed" for item in reviews)
                else "needs_review"
            ),
            "recommendations": reviews,
            "solution_validation": "passed",
        }
        state["evidence_review"] = review
        record_trace(
            state,
            self.name,
            {
                "overall_status": review["overall_status"],
                "checked_recommendations": len(reviews),
            },
        )
