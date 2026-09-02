"""Shared state and trace helpers for the Agent workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def new_state(
    request_text: str,
    input_mode: str,
    *,
    requirement_confirmed: bool = False,
) -> dict[str, Any]:
    """Create the auditable state passed through the enterprise workflow."""
    if not request_text.strip():
        raise ValueError("企业需求不能为空")
    return {
        "request_text": request_text.strip(),
        "input_mode": input_mode,
        "requirement_confirmation": {
            "confirmed": requirement_confirmed,
            "status": (
                "confirmed_by_user"
                if requirement_confirmed
                else "pending_user_confirmation"
            ),
        },
        "enterprise_need": None,
        "clarification": None,
        "need_modules": [],
        "teacher_profiles": [],
        "paper_candidates": {},
        "module_evidence": {},
        "match_result": None,
        "solution_bundle": None,
        "route_drawio": None,
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
