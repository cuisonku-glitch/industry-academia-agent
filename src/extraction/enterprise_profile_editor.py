"""Build validated enterprise profiles from explicit user edits."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any, Iterable

from .enterprise_parser import PROFILE_LIST_FIELDS, validate_enterprise_profile


ALLOWED_OPERATORS = frozenset({"<=", "<", ">=", ">", "=", "范围"})
EDITABLE_LIST_FIELDS = (
    "technical_problems",
    "required_capabilities",
    "constraints",
    "existing_foundations",
    "excluded_approaches",
    "keywords",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        identity = "".join(cleaned.casefold().split())
        if cleaned and identity not in seen:
            seen.add(identity)
            result.append(cleaned)
    return result


def _metric_raw_text(metric: dict[str, Any]) -> str:
    return " ".join(
        value
        for value in (
            str(metric["name"]).strip(),
            str(metric["operator"]).strip(),
            str(metric["value_text"]).strip(),
            str(metric.get("unit", "")).strip(),
            str(metric.get("test_condition", "")).strip(),
        )
        if value
    )


def _clean_metrics(
    rows: Iterable[dict[str, Any]],
    original_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    original_by_signature = {
        (
            item["name"],
            item["operator"],
            item["value_text"],
            item.get("unit", ""),
            item.get("test_condition", ""),
        ): item
        for item in original_metrics
    }
    metrics: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        value_text = str(row.get("value_text", "")).strip()
        if not name and not value_text:
            continue
        if not name or not value_text:
            raise ValueError("每项指标必须同时填写指标名称和目标值")
        operator = str(row.get("operator", "")).strip()
        if operator not in ALLOWED_OPERATORS:
            raise ValueError(f"不支持的指标运算符：{operator}")
        unit = str(row.get("unit", "")).strip()
        test_condition = str(row.get("test_condition", "")).strip()
        signature = (name, operator, value_text, unit, test_condition)
        original = original_by_signature.get(signature)
        metric = {
            "metric_id": f"TM{len(metrics) + 1:02d}",
            "name": name,
            "operator": operator,
            "value_text": value_text,
            "unit": unit,
            "test_condition": test_condition,
            "raw_text": (
                original["raw_text"] if original else _metric_raw_text(row)
            ),
            "source_type": "enterprise_confirmed",
            "provenance_type": (
                "enterprise_original" if original else "enterprise_user_edit"
            ),
        }
        metrics.append(metric)
    return metrics


def _canonical_confirmation_text(profile: dict[str, Any]) -> str:
    lines = [
        f"行业场景：{profile['industry']}",
        f"产品系统：{profile['product']}",
    ]
    labels = {
        "technical_problems": "技术问题",
        "required_capabilities": "目标能力",
        "constraints": "约束条件",
        "existing_foundations": "已有基础",
        "excluded_approaches": "排除路线",
        "keywords": "关键词",
    }
    for field in EDITABLE_LIST_FIELDS:
        for value in profile[field]:
            lines.append(f"{labels[field]}：{value}")
    for metric in profile["target_metrics"]:
        lines.append(f"量化指标：{metric['raw_text']}")
    for fragment in profile["unparsed_fragments"]:
        lines.append(f"待归类原话：{fragment}")
    return "\n".join(lines)


def _rebuild_evidence_map(
    base_profile: dict[str, Any], edited: dict[str, Any]
) -> list[dict[str, Any]]:
    original_records = {
        (item.get("field"), item.get("value")): item
        for item in base_profile.get("evidence_map", [])
    }
    evidence: list[dict[str, Any]] = []

    def add(field: str, value: str, provenance: str | None = None) -> None:
        original = original_records.get((field, value))
        if original and provenance != "enterprise_user_edit":
            evidence.append(copy.deepcopy(original))
        else:
            evidence.append(
                {
                    "field": field,
                    "value": value,
                    "matched_phrases": [value],
                    "source_type": "enterprise_user_edit",
                }
            )

    for field in ("industry", "product"):
        if edited[field] != "未明确":
            add(field, edited[field])
    for field in PROFILE_LIST_FIELDS:
        for value in edited[field]:
            add(field, value)
    for metric in edited["target_metrics"]:
        add(
            "target_metrics",
            metric["raw_text"],
            metric.get("provenance_type"),
        )
    return evidence


def apply_enterprise_edits(
    base_profile: dict[str, Any],
    edits: dict[str, Any],
) -> dict[str, Any]:
    """Create a draft whose original request and user-confirmed snapshot coexist."""
    validate_enterprise_profile(base_profile)
    profile = copy.deepcopy(base_profile)
    profile["industry"] = str(edits.get("industry", "")).strip() or "未明确"
    profile["product"] = str(edits.get("product", "")).strip() or "未明确"
    for field in EDITABLE_LIST_FIELDS:
        profile[field] = _clean_strings(edits.get(field, []))
    profile["target_metrics"] = _clean_metrics(
        edits.get("target_metrics", []),
        base_profile.get("target_metrics", []),
    )
    profile["unparsed_fragments"] = _clean_strings(
        edits.get("unparsed_fragments", [])
    )
    profile["confirmation"] = {
        "status": "draft_user_edited",
        "version_id": None,
        "confirmed_at": None,
    }
    profile["editor"] = "enterprise_profile_editor_v1"
    profile["edited_at"] = _utc_now()
    profile["confirmed_request"] = _canonical_confirmation_text(profile)
    profile["evidence_map"] = _rebuild_evidence_map(base_profile, profile)
    validate_enterprise_profile(profile)
    return profile


def confirm_enterprise_profile(
    profile: dict[str, Any], *, version_id: str
) -> dict[str, Any]:
    """Freeze an already-saved draft as the only profile used downstream."""
    validate_enterprise_profile(profile)
    confirmed = copy.deepcopy(profile)
    confirmed["confirmation"] = {
        "status": "confirmed_by_user",
        "version_id": version_id,
        "confirmed_at": _utc_now(),
    }
    validate_enterprise_profile(confirmed)
    return confirmed
