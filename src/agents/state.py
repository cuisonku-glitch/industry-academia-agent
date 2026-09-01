"""Shared state and trace helpers for the Agent workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def new_state(request_text: str, input_mode: str) -> dict[str, Any]:
    """Create the state passed between the six agents."""
    if not request_text.strip():
        raise ValueError("企业需求不能为空")
    return {
        "request_text": request_text.strip(),
        "input_mode": input_mode,
        "enterprise_need": None,
        "teacher_profiles": [],
        "paper_candidates": {},
        "match_result": None,
        "evidence_review": None,
        "report": None,
        "trace": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


def record_trace(
    state: dict[str, Any], agent: str, summary: dict[str, Any]
) -> None:
    """Record a compact handoff rather than hidden reasoning."""
    state["trace"].append(
        {
            "sequence": len(state["trace"]) + 1,
            "agent": agent,
            "status": "completed",
            "output_summary": summary,
        }
    )
