"""Pure helpers for the Streamlit enterprise requirement editor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


def load_public_cases(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("公开案例文件必须包含 cases 数组")
    required = {"case_id", "title", "organization", "request_text", "notice"}
    if any(not isinstance(item, dict) or not required.issubset(item) for item in cases):
        raise ValueError("公开案例字段不完整")
    return cases


def multiline(values: Iterable[Any]) -> str:
    return "\n".join(str(value) for value in values if str(value).strip())


def lines(value: str) -> list[str]:
    return [item.strip() for item in value.splitlines() if item.strip()]


def metric_editor_rows(profile: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "name": str(item["name"]),
            "operator": str(item["operator"]),
            "value_text": str(item["value_text"]),
            "unit": str(item.get("unit", "")),
            "test_condition": str(item.get("test_condition", "")),
        }
        for item in profile.get("target_metrics", [])
    ]


def editor_result_rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        return list(value.to_dict(orient="records"))
    if isinstance(value, list):
        return [dict(item) for item in value]
    raise TypeError("指标编辑器返回了不支持的数据类型")
