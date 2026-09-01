"""Coordinator construction, execution, and persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..matching.matcher import (
    DEFAULT_TEACHER_DIRECTORY,
    DEFAULT_TOP_K,
    ResearchIndustryMatcher,
)
from .decision_agents import EvidenceAgent, MatchingAgent
from .report_agent import ReportAgent
from .source_agents import PaperAgent, RequirementAgent, ResearchAgent
from .state import new_state


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "agent_runs"
DEFAULT_JSON_PATH = DEFAULT_RUN_DIRECTORY / "latest.json"
DEFAULT_REPORT_PATH = DEFAULT_RUN_DIRECTORY / "latest_report.md"


class Coordinator:
    """Run the six agents in their dependency-safe order."""

    name = "Coordinator"

    def __init__(
        self,
        requirement_agent: RequirementAgent,
        research_agent: ResearchAgent,
        paper_agent: PaperAgent,
        matching_agent: MatchingAgent,
        evidence_agent: EvidenceAgent,
        report_agent: ReportAgent,
    ) -> None:
        self.agents = [
            requirement_agent,
            research_agent,
            paper_agent,
            matching_agent,
            evidence_agent,
            report_agent,
        ]

    def run(self, request_text: str, input_mode: str = "user") -> dict[str, Any]:
        state = new_state(request_text, input_mode)
        for agent in self.agents:
            try:
                agent.run(state)
            except Exception as exc:
                state["trace"].append(
                    {
                        "sequence": len(state["trace"]) + 1,
                        "agent": agent.name,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                raise
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        return state


def build_coordinator(
    teacher_directory: Path = DEFAULT_TEACHER_DIRECTORY,
    top_k: int = DEFAULT_TOP_K,
    matcher: ResearchIndustryMatcher | None = None,
) -> Coordinator:
    """Create production agents sharing one local matcher and vector store."""
    matcher = matcher or ResearchIndustryMatcher()
    return Coordinator(
        requirement_agent=RequirementAgent(),
        research_agent=ResearchAgent(teacher_directory=teacher_directory),
        paper_agent=PaperAgent(matcher, top_k=top_k),
        matching_agent=MatchingAgent(matcher, top_k=top_k),
        evidence_agent=EvidenceAgent(),
        report_agent=ReportAgent(),
    )


def save_run(
    state: dict[str, Any], json_path: Path, report_path: Path
) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(state["report"], encoding="utf-8")
    return json_path, report_path
