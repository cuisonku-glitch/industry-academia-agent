"""Agents that prepare enterprise, teacher, and paper inputs."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from ..extraction.enterprise_parser import (
    parse_enterprise_need,
    validate_enterprise_profile,
)
from ..matching.matcher import (
    DEFAULT_TEACHER_DIRECTORY,
    DEFAULT_TOP_K,
    ResearchIndustryMatcher,
    build_enterprise_query,
    load_teacher_profiles,
)
from ..solutions import (
    build_clarification,
    build_module_query,
    decompose_technical_need,
)
from .state import record_trace


class RequirementAgent:
    """Turn original enterprise wording into a structured need profile."""

    name = "Requirement Agent"

    def __init__(
        self,
        parser: Callable[[str], dict[str, Any]] = parse_enterprise_need,
    ) -> None:
        self.parser = parser

    def run(self, state: dict[str, Any]) -> None:
        existing = state.get("enterprise_need")
        if existing:
            validate_enterprise_profile(existing)
            profile = copy.deepcopy(existing)
        else:
            profile = self.parser(state["request_text"])
        state["enterprise_need"] = profile
        record_trace(
            state,
            self.name,
            {
                "industry": profile["industry"],
                "product": profile["product"],
                "required_capability_count": len(profile["required_capabilities"]),
            },
        )


class ResearchAgent:
    """Load the evidence-grounded teacher research profiles."""

    name = "Research Agent"

    def __init__(
        self,
        teacher_directory: Path = DEFAULT_TEACHER_DIRECTORY,
        loader: Callable[[Path], list[dict[str, Any]]] = load_teacher_profiles,
    ) -> None:
        self.teacher_directory = teacher_directory
        self.loader = loader

    def run(self, state: dict[str, Any]) -> None:
        profiles = self.loader(self.teacher_directory)
        state["teacher_profiles"] = profiles
        record_trace(
            state,
            self.name,
            {
                "teacher_count": len(profiles),
                "teachers": [profile["teacher"] for profile in profiles],
            },
        )


class ClarificationAgent:
    """Expose unknowns and build only traceable technical modules."""

    name = "Clarification Agent"

    def run(self, state: dict[str, Any]) -> None:
        profile = state.get("enterprise_need")
        if not profile:
            raise RuntimeError("Clarification Agent 缺少企业画像")
        confirmed = bool(state["requirement_confirmation"]["confirmed"])
        clarification = build_clarification(profile)
        modules = decompose_technical_need(profile, confirmed=confirmed)
        state["clarification"] = clarification
        state["need_modules"] = modules
        record_trace(
            state,
            self.name,
            {
                "requirement_confirmed": confirmed,
                "module_count": len(modules),
                "blocking_question_count": clarification["blocking_count"],
            },
        )


class PaperAgent:
    """Find relevant local paper chunks for each candidate teacher."""

    name = "Paper Agent"

    def __init__(
        self,
        matcher: ResearchIndustryMatcher,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.matcher = matcher
        self.top_k = top_k

    def run(self, state: dict[str, Any]) -> None:
        enterprise = state.get("enterprise_need")
        profiles = state.get("teacher_profiles")
        if not enterprise or not profiles:
            raise RuntimeError("Paper Agent 缺少企业画像或教师画像")

        query = build_enterprise_query(enterprise)
        candidates: dict[str, list[dict[str, Any]]] = {}
        for profile in profiles:
            teacher = profile["teacher"]
            candidates[teacher] = self.matcher.retrieve_paper_evidence(
                query, teacher, self.top_k
            )
        state["paper_candidates"] = candidates
        module_candidates: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for module in state.get("need_modules", []):
            module_query = build_module_query(module, enterprise)
            module_candidates[module["module_id"]] = {
                profile["teacher"]: self.matcher.retrieve_paper_evidence(
                    module_query,
                    profile["teacher"],
                    self.top_k,
                )
                for profile in profiles
            }
        state["module_evidence"] = module_candidates
        record_trace(
            state,
            self.name,
            {
                "top_k_per_teacher": self.top_k,
                "evidence_count_by_teacher": {
                    teacher: len(items) for teacher, items in candidates.items()
                },
                "module_evidence_count": {
                    module_id: sum(len(items) for items in by_teacher.values())
                    for module_id, by_teacher in module_candidates.items()
                },
            },
        )
