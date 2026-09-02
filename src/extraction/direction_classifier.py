"""Deterministic research-direction routing with explicit provenance."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TAXONOMY_PATH = PROJECT_ROOT / "config" / "research_direction_taxonomy.json"
ASSIGNMENT_SCHEMA = "paper_direction_assignment_v1"
DIRECTION_SOURCES = frozenset(
    {"metadata", "keyword_rule", "model_fallback", "unclassified"}
)


def load_direction_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "research_direction_taxonomy_v1":
        raise ValueError("研究方向 taxonomy schema 不受支持")
    directions = payload.get("directions")
    if not isinstance(directions, list) or not directions:
        raise ValueError("研究方向 taxonomy 缺少 directions")
    ids: set[str] = set()
    for item in directions:
        required = {"direction_id", "label", "aliases", "keywords"}
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError("研究方向定义字段不完整")
        direction_id = str(item["direction_id"]).strip()
        if not direction_id or direction_id in ids:
            raise ValueError("研究方向 ID 为空或重复")
        if not all(
            isinstance(item[field], list)
            and all(isinstance(value, str) and value.strip() for value in item[field])
            for field in ("aliases", "keywords")
        ):
            raise ValueError(f"研究方向 {direction_id} 的别名或关键词无效")
        ids.add(direction_id)
    return payload


def _unclassified(taxonomy_version: str, note: str = "") -> dict[str, Any]:
    return {
        "schema_version": ASSIGNMENT_SCHEMA,
        "taxonomy_version": taxonomy_version,
        "direction_id": "unclassified",
        "label": "未分类",
        "source": "unclassified",
        "confidence": 0.0,
        "matched_terms": [],
        "review_status": "pending",
        "note": note or "没有达到规则阈值，保留为未分类。",
    }


def validate_direction_assignment(
    assignment: dict[str, Any], taxonomy: dict[str, Any]
) -> None:
    if assignment.get("schema_version") != ASSIGNMENT_SCHEMA:
        raise ValueError("论文方向 assignment schema 不受支持")
    allowed_ids = {
        item["direction_id"] for item in taxonomy["directions"]
    } | {"unclassified"}
    if assignment.get("direction_id") not in allowed_ids:
        raise ValueError("论文方向 assignment 包含未知方向")
    if assignment.get("source") not in DIRECTION_SOURCES:
        raise ValueError("论文方向 assignment 包含未知来源")
    confidence = assignment.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
        raise ValueError("论文方向置信度必须在 0–1 之间")
    if not isinstance(assignment.get("matched_terms"), list):
        raise ValueError("论文方向 matched_terms 必须是数组")


def classify_paper_direction(
    paper_metadata: dict[str, Any],
    text: str = "",
    *,
    taxonomy: dict[str, Any] | None = None,
    model_fallback: Callable[[dict[str, Any], str], dict[str, Any]] | None = None,
    minimum_rule_score: int = 2,
    minimum_model_confidence: float = 0.6,
) -> dict[str, Any]:
    """Classify metadata first, then rules, then an explicitly supplied model."""
    taxonomy = taxonomy or load_direction_taxonomy()
    taxonomy_version = taxonomy["schema_version"]
    directions = {item["direction_id"]: item for item in taxonomy["directions"]}
    alias_to_id = {
        alias.casefold(): item["direction_id"]
        for item in taxonomy["directions"]
        for alias in [item["direction_id"], *item["aliases"]]
    }

    declared = str(paper_metadata.get("direction", "")).strip()
    if declared and declared.casefold() != "unclassified":
        direction_id = alias_to_id.get(declared.casefold())
        if direction_id:
            assignment = {
                "schema_version": ASSIGNMENT_SCHEMA,
                "taxonomy_version": taxonomy_version,
                "direction_id": direction_id,
                "label": directions[direction_id]["label"],
                "source": "metadata",
                "confidence": 1.0,
                "matched_terms": [declared],
                "review_status": "pending",
                "note": "采用论文目录中的显式方向元数据。",
            }
            validate_direction_assignment(assignment, taxonomy)
            return assignment

    title = str(paper_metadata.get("title", ""))
    title_folded = title.casefold()
    text_folded = str(text).casefold()
    scored: list[tuple[int, str, list[str]]] = []
    for direction_id, definition in directions.items():
        title_matches = [
            term for term in definition["keywords"] if term.casefold() in title_folded
        ]
        text_matches = [
            term
            for term in definition["keywords"]
            if term.casefold() in text_folded and term not in title_matches
        ]
        score = len(title_matches) * 3 + len(text_matches)
        scored.append((score, direction_id, title_matches + text_matches))
    scored.sort(key=lambda item: (-item[0], item[1]))
    if scored and scored[0][0] >= minimum_rule_score:
        top_score, direction_id, matched_terms = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0
        if top_score > second_score:
            confidence = round(top_score / max(top_score + second_score, 1), 4)
            assignment = {
                "schema_version": ASSIGNMENT_SCHEMA,
                "taxonomy_version": taxonomy_version,
                "direction_id": direction_id,
                "label": directions[direction_id]["label"],
                "source": "keyword_rule",
                "confidence": confidence,
                "matched_terms": matched_terms,
                "review_status": "pending",
                "note": "标题关键词权重为正文关键词的 3 倍；并列最高分不强制分类。",
            }
            validate_direction_assignment(assignment, taxonomy)
            return assignment

    if model_fallback is not None:
        raw = model_fallback(paper_metadata, text)
        direction_id = str(raw.get("direction_id", "")).strip()
        confidence = float(raw.get("confidence", 0.0))
        if direction_id in directions and confidence >= minimum_model_confidence:
            assignment = {
                "schema_version": ASSIGNMENT_SCHEMA,
                "taxonomy_version": taxonomy_version,
                "direction_id": direction_id,
                "label": directions[direction_id]["label"],
                "source": "model_fallback",
                "confidence": round(confidence, 4),
                "matched_terms": [
                    str(value).strip()
                    for value in raw.get("matched_terms", [])
                    if str(value).strip()
                ],
                "review_status": "pending",
                "note": str(raw.get("note", "模型兜底分类，等待人工复核。")),
            }
            validate_direction_assignment(assignment, taxonomy)
            return assignment

    note = (
        f"目录元数据方向 {declared!r} 不在 taxonomy 中，且规则未形成唯一结论。"
        if declared and declared.casefold() != "unclassified"
        else "规则未形成唯一且达到阈值的方向结论。"
    )
    return _unclassified(taxonomy_version, note)
