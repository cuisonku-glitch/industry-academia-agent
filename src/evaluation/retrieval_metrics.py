"""Deterministic information-retrieval metrics for offline experiments."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSON objects from a UTF-8 JSON Lines file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 第 {line_number} 行不是合法 JSON：{path}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"JSONL 第 {line_number} 行顶层必须是对象：{path}")
        records.append(record)
    return records


def _normalize_qrels(
    records: Iterable[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    for record in records:
        query_id = str(record.get("query_id", "")).strip()
        chunk_id = str(record.get("chunk_id", "")).strip()
        relevance = record.get("relevance")
        if not query_id or not chunk_id:
            raise ValueError("qrels 的 query_id 和 chunk_id 不能为空")
        if not isinstance(relevance, int) or isinstance(relevance, bool):
            raise ValueError("qrels 的 relevance 必须是非负整数")
        if relevance < 0:
            raise ValueError("qrels 的 relevance 必须是非负整数")
        query_qrels = qrels.setdefault(query_id, {})
        query_qrels[chunk_id] = max(relevance, query_qrels.get(chunk_id, 0))
    if not qrels:
        raise ValueError("qrels 不能为空")
    if any(not any(value > 0 for value in values.values()) for values in qrels.values()):
        raise ValueError("每个 query_id 至少需要一条 relevance > 0 的标注")
    return qrels


def _normalize_run(
    records: Iterable[dict[str, Any]],
) -> dict[str, list[str]]:
    run: dict[str, list[str]] = {}
    for record in records:
        query_id = str(record.get("query_id", "")).strip()
        chunk_ids = record.get("chunk_ids")
        if not query_id:
            raise ValueError("run 的 query_id 不能为空")
        if not isinstance(chunk_ids, list):
            raise ValueError("run 的 chunk_ids 必须是数组")
        unique: list[str] = []
        seen: set[str] = set()
        for value in chunk_ids:
            chunk_id = str(value).strip()
            if chunk_id and chunk_id not in seen:
                seen.add(chunk_id)
                unique.append(chunk_id)
        run[query_id] = unique
    return run


def _dcg(relevances: Sequence[int]) -> float:
    return sum(
        (2**relevance - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances, start=1)
    )


def evaluate_retrieval(
    qrel_records: Iterable[dict[str, Any]],
    run_records: Iterable[dict[str, Any]],
    cutoffs: Sequence[int] = (5, 10),
) -> dict[str, Any]:
    """Calculate macro Recall, MRR, and nDCG at each requested cutoff.

    qrels use one record per judged query/chunk pair::

        {"query_id": "q1", "chunk_id": "paper_chunk_1", "relevance": 2}

    runs use one ranked chunk list per query::

        {"query_id": "q1", "chunk_ids": ["paper_chunk_1", "..."]}

    Only explicitly judged chunks count as relevant. Missing run queries receive zero.
    """
    normalized_cutoffs = sorted({int(value) for value in cutoffs})
    if not normalized_cutoffs or any(value <= 0 for value in normalized_cutoffs):
        raise ValueError("cutoffs 必须包含正整数")

    qrels = _normalize_qrels(qrel_records)
    run = _normalize_run(run_records)
    per_query: dict[str, dict[str, float]] = {}

    for query_id, judgments in qrels.items():
        relevant_ids = {chunk_id for chunk_id, grade in judgments.items() if grade > 0}
        ranking = run.get(query_id, [])
        query_metrics: dict[str, float] = {}

        for cutoff in normalized_cutoffs:
            retrieved = ranking[:cutoff]
            relevant_retrieved = sum(chunk_id in relevant_ids for chunk_id in retrieved)
            recall = relevant_retrieved / len(relevant_ids)

            reciprocal_rank = 0.0
            for rank, chunk_id in enumerate(retrieved, start=1):
                if judgments.get(chunk_id, 0) > 0:
                    reciprocal_rank = 1.0 / rank
                    break

            gains = [judgments.get(chunk_id, 0) for chunk_id in retrieved]
            ideal = sorted(judgments.values(), reverse=True)[:cutoff]
            ideal_dcg = _dcg(ideal)
            ndcg = _dcg(gains) / ideal_dcg if ideal_dcg else 0.0

            query_metrics[f"recall@{cutoff}"] = recall
            query_metrics[f"mrr@{cutoff}"] = reciprocal_rank
            query_metrics[f"ndcg@{cutoff}"] = ndcg

        per_query[query_id] = query_metrics

    aggregate = {
        metric: round(
            sum(values[metric] for values in per_query.values()) / len(per_query),
            6,
        )
        for metric in next(iter(per_query.values()))
    }
    return {
        "query_count": len(qrels),
        "run_query_count": sum(query_id in run for query_id in qrels),
        "cutoffs": normalized_cutoffs,
        "metrics": aggregate,
        "per_query": per_query,
    }
