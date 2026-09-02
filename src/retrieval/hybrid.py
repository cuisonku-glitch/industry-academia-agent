"""Deterministic filtered Dense/BM25/RRF retrieval with optional reranking."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

from ..extraction.direction_classifier import load_direction_taxonomy
from ..extraction.metric_ontology import EVIDENCE_LEVELS, MetricOntology
from ..ingestion.chunker import SECTION_TYPES


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRIC_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "metrics"
RETRIEVAL_FILTER_SCHEMA = "retrieval_filters_v1"
METRIC_OPERATORS = frozenset({"eq", "gte", "lte", "between"})
DEFAULT_NUMERIC_EVIDENCE_LEVELS = frozenset({"measured", "reported"})
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[._+/-][a-z0-9]+)*|[\u3400-\u9fff]+")


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize mixed Chinese/Latin technical text without external services."""
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        value = match.group(0)
        if re.fullmatch(r"[\u3400-\u9fff]+", value):
            tokens.extend(value)
            tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        else:
            tokens.append(value)
    return tokens


class BM25Index:
    """Small dependency-free BM25 index over traceable paper chunks."""

    def __init__(
        self,
        chunks: Sequence[dict[str, Any]],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("BM25 k1 必须大于 0")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b 必须在 0 到 1 之间")
        self.k1 = float(k1)
        self.b = float(b)
        self.chunks = [dict(chunk) for chunk in chunks]
        self.term_frequencies: list[Counter[str]] = []
        self.document_lengths: list[int] = []
        document_frequency: Counter[str] = Counter()
        for chunk in self.chunks:
            terms = tokenize_for_bm25(str(chunk.get("text", "")))
            frequencies = Counter(terms)
            self.term_frequencies.append(frequencies)
            self.document_lengths.append(len(terms))
            document_frequency.update(frequencies.keys())
        self.average_document_length = (
            sum(self.document_lengths) / len(self.document_lengths)
            if self.document_lengths
            else 0.0
        )
        document_count = len(self.chunks)
        self.inverse_document_frequency = {
            term: math.log(1 + (document_count - frequency + 0.5) / (frequency + 0.5))
            for term, frequency in document_frequency.items()
        }

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if not str(query).strip() or not self.chunks:
            return []
        query_terms = tokenize_for_bm25(query)
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for chunk, frequencies, document_length in zip(
            self.chunks, self.term_frequencies, self.document_lengths
        ):
            score = 0.0
            for term in query_terms:
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                length_ratio = (
                    document_length / self.average_document_length
                    if self.average_document_length
                    else 0.0
                )
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length_ratio
                )
                score += self.inverse_document_frequency.get(term, 0.0) * (
                    term_frequency * (self.k1 + 1) / denominator
                )
            if score > 0:
                scored.append((score, str(chunk["chunk_id"]), chunk))
        scored.sort(key=lambda item: (-item[0], item[1]))
        results: list[dict[str, Any]] = []
        for rank, (score, _, chunk) in enumerate(scored[:top_k], start=1):
            results.append(
                {
                    **chunk,
                    "rank": rank,
                    "bm25_score": score,
                    "retrieval_score": score,
                }
            )
        return results


def _require_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} 必须是有限数字")
    return number


def normalize_retrieval_filters(
    raw_filters: dict[str, Any] | None,
    *,
    ontology: MetricOntology | None = None,
) -> dict[str, Any]:
    """Validate query filters and normalize metric thresholds to canonical units."""
    if raw_filters is None:
        raw_filters = {}
    if not isinstance(raw_filters, dict):
        raise ValueError("filters 必须是对象")
    allowed_keys = {"direction", "section_types", "metrics"}
    unknown_keys = set(raw_filters) - allowed_keys
    if unknown_keys:
        raise ValueError(f"filters 包含未知字段：{sorted(unknown_keys)}")

    direction = str(raw_filters.get("direction", "")).strip()
    known_directions = {
        str(item["direction_id"]) for item in load_direction_taxonomy()["directions"]
    } | {"unclassified"}
    if direction and direction not in known_directions:
        raise ValueError(f"未知研究方向：{direction}")

    raw_section_types = raw_filters.get("section_types", [])
    if not isinstance(raw_section_types, list):
        raise ValueError("section_types 必须是数组")
    section_types = sorted({str(value).strip() for value in raw_section_types if str(value).strip()})
    invalid_sections = set(section_types) - SECTION_TYPES
    if invalid_sections:
        raise ValueError(f"未知章节类型：{sorted(invalid_sections)}")

    raw_metrics = raw_filters.get("metrics", [])
    if not isinstance(raw_metrics, list):
        raise ValueError("metrics 必须是数组")
    ontology = ontology or MetricOntology.from_path()
    metrics: list[dict[str, Any]] = []
    for index, constraint in enumerate(raw_metrics, start=1):
        if not isinstance(constraint, dict):
            raise ValueError(f"第 {index} 条 metric filter 必须是对象")
        allowed_metric_keys = {
            "definition_id",
            "operator",
            "value",
            "upper_value",
            "unit",
            "evidence_levels",
            "test_condition_contains",
        }
        unknown_metric_keys = set(constraint) - allowed_metric_keys
        if unknown_metric_keys:
            raise ValueError(
                f"第 {index} 条 metric filter 包含未知字段：{sorted(unknown_metric_keys)}"
            )
        definition_id = str(constraint.get("definition_id", "")).strip()
        if definition_id not in ontology.by_id:
            raise ValueError(f"未知指标：{definition_id}")
        operator = str(constraint.get("operator", "")).strip()
        if operator not in METRIC_OPERATORS:
            raise ValueError(f"指标 {definition_id} operator 无效：{operator}")
        raw_unit = str(constraint.get("unit", "")).strip()
        if not raw_unit:
            raise ValueError(f"指标 {definition_id} 缺少 unit")
        raw_value = _require_number(constraint.get("value"), "value")
        normalized_value = ontology.normalize_value(
            definition_id, raw_value, raw_unit
        )["normalized_value"]
        normalized_upper: float | None = None
        if operator == "between":
            raw_upper = _require_number(constraint.get("upper_value"), "upper_value")
            normalized_upper = ontology.normalize_value(
                definition_id, raw_upper, raw_unit
            )["normalized_value"]
            if normalized_upper < normalized_value:
                raise ValueError(f"指标 {definition_id} 的区间上界小于下界")
        elif "upper_value" in constraint:
            raise ValueError("只有 between operator 可以提供 upper_value")

        raw_levels = constraint.get(
            "evidence_levels", sorted(DEFAULT_NUMERIC_EVIDENCE_LEVELS)
        )
        if not isinstance(raw_levels, list) or not raw_levels:
            raise ValueError("evidence_levels 必须是非空数组")
        evidence_levels = sorted({str(value).strip() for value in raw_levels})
        if set(evidence_levels) - EVIDENCE_LEVELS:
            raise ValueError(f"指标 {definition_id} evidence_levels 无效")
        condition = " ".join(
            str(constraint.get("test_condition_contains", "")).split()
        )
        metrics.append(
            {
                "definition_id": definition_id,
                "operator": operator,
                "normalized_value": normalized_value,
                "normalized_upper_value": normalized_upper,
                "canonical_unit": ontology.by_id[definition_id]["canonical_unit"],
                "evidence_levels": evidence_levels,
                "test_condition_contains": condition,
            }
        )
    return {
        "schema_version": RETRIEVAL_FILTER_SCHEMA,
        "direction": direction or None,
        "section_types": section_types,
        "metrics": metrics,
    }


def _record_bounds(record: dict[str, Any]) -> tuple[float, float] | None:
    if record.get("value_type") == "range":
        lower = record.get("normalized_min")
        upper = record.get("normalized_max")
    else:
        lower = upper = record.get("normalized_value")
    if isinstance(lower, bool) or isinstance(upper, bool):
        return None
    if not isinstance(lower, (int, float)) or not isinstance(upper, (int, float)):
        return None
    return float(lower), float(upper)


def metric_record_matches(
    record: dict[str, Any], constraint: dict[str, Any]
) -> bool:
    """Apply a conservative hard threshold to one normalized metric record."""
    if record.get("definition_id") != constraint["definition_id"]:
        return False
    if record.get("canonical_unit") != constraint["canonical_unit"]:
        return False
    if record.get("evidence_level") not in constraint["evidence_levels"]:
        return False
    condition = constraint.get("test_condition_contains", "").casefold()
    if condition and condition not in str(record.get("test_condition", "")).casefold():
        return False
    bounds = _record_bounds(record)
    if bounds is None:
        return False
    lower, upper = bounds
    target = float(constraint["normalized_value"])
    operator = constraint["operator"]
    if operator == "eq":
        return lower <= target <= upper
    if operator == "gte":
        return lower >= target
    if operator == "lte":
        return upper <= target
    if operator == "between":
        return lower >= target and upper <= float(
            constraint["normalized_upper_value"]
        )
    raise ValueError(f"未知 metric operator：{operator}")


class MetricEvidenceIndex:
    """Map normalized metric evidence to the chunks that contain it."""

    def __init__(self, records: Sequence[dict[str, Any]]) -> None:
        self.records_by_chunk: dict[str, list[dict[str, Any]]] = defaultdict(list)
        seen_metric_ids: set[str] = set()
        for record in records:
            metric_id = str(record.get("metric_id", "")).strip()
            chunk_id = str(record.get("evidence", {}).get("chunk_id", "")).strip()
            if not metric_id or not chunk_id:
                raise ValueError("指标记录缺少 metric_id 或 evidence.chunk_id")
            if metric_id in seen_metric_ids:
                raise ValueError(f"指标记录 ID 重复：{metric_id}")
            seen_metric_ids.add(metric_id)
            self.records_by_chunk[chunk_id].append(dict(record))

    @classmethod
    def from_directory(cls, directory: Path = DEFAULT_METRIC_DIRECTORY) -> "MetricEvidenceIndex":
        records: list[dict[str, Any]] = []
        directory = Path(directory)
        if not directory.is_dir():
            return cls([])
        for path in sorted(directory.glob("*.metrics.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != "paper_metric_extraction_v1":
                raise ValueError(f"指标文件 schema 不受支持：{path}")
            file_records = payload.get("metrics")
            if not isinstance(file_records, list):
                raise ValueError(f"指标文件 metrics 必须是数组：{path}")
            records.extend(file_records)
        return cls(records)

    def matching_chunk_ids(self, constraints: Sequence[dict[str, Any]]) -> set[str]:
        if not constraints:
            return set(self.records_by_chunk)
        matched_sets: list[set[str]] = []
        for constraint in constraints:
            matched_sets.append(
                {
                    chunk_id
                    for chunk_id, records in self.records_by_chunk.items()
                    if any(metric_record_matches(record, constraint) for record in records)
                }
            )
        return set.intersection(*matched_sets) if matched_sets else set()


def build_chroma_where(
    filters: dict[str, Any], allowed_chunk_ids: set[str] | None = None
) -> dict[str, Any] | None:
    """Build a Chroma metadata prefilter from a normalized filter contract."""
    clauses: list[dict[str, Any]] = []
    if filters.get("direction"):
        clauses.append({"direction": filters["direction"]})
    section_types = filters.get("section_types", [])
    if len(section_types) == 1:
        clauses.append({"section_type": section_types[0]})
    elif section_types:
        clauses.append({"section_type": {"$in": list(section_types)}})
    if allowed_chunk_ids is not None:
        if not allowed_chunk_ids:
            return None
        chunk_ids = sorted(allowed_chunk_ids)
        if len(chunk_ids) == 1:
            clauses.append({"chunk_id": chunk_ids[0]})
        else:
            clauses.append({"chunk_id": {"$in": chunk_ids}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def chunk_matches_filters(
    chunk: dict[str, Any],
    filters: dict[str, Any],
    allowed_chunk_ids: set[str] | None,
) -> bool:
    metadata = chunk.get("metadata", {})
    if filters.get("direction") and metadata.get("direction") != filters["direction"]:
        return False
    if filters.get("section_types") and metadata.get("section_type") not in filters["section_types"]:
        return False
    if allowed_chunk_ids is not None and chunk.get("chunk_id") not in allowed_chunk_ids:
        return False
    return True


def reciprocal_rank_fusion(
    rankings: dict[str, Sequence[dict[str, Any]]],
    *,
    top_k: int,
    rrf_k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    if top_k <= 0 or rrf_k <= 0:
        raise ValueError("top_k 和 rrf_k 必须大于 0")
    weights = weights or {}
    merged: dict[str, dict[str, Any]] = {}
    for method, ranking in rankings.items():
        weight = float(weights.get(method, 1.0))
        if weight <= 0:
            raise ValueError("RRF 权重必须大于 0")
        for rank, item in enumerate(ranking, start=1):
            chunk_id = str(item["chunk_id"])
            entry = merged.setdefault(
                chunk_id,
                {
                    "item": dict(item),
                    "score": 0.0,
                    "component_ranks": {},
                },
            )
            entry["score"] += weight / (rrf_k + rank)
            entry["component_ranks"][method] = rank
    ordered = sorted(
        merged.items(), key=lambda pair: (-pair[1]["score"], pair[0])
    )
    results: list[dict[str, Any]] = []
    for rank, (_, entry) in enumerate(ordered[:top_k], start=1):
        item = entry["item"]
        item.update(
            {
                "rank": rank,
                "rrf_score": entry["score"],
                "retrieval_score": entry["score"],
                "component_ranks": entry["component_ranks"],
            }
        )
        results.append(item)
    return results


class PairScorer(Protocol):
    def score_pairs(self, query: str, texts: Sequence[str]) -> Sequence[float]: ...


class CrossEncoderScorer:
    """Lazily loaded optional sentence-transformers CrossEncoder adapter."""

    def __init__(self, model_name: str, device: str | None = None) -> None:
        if not str(model_name).strip():
            raise ValueError("reranker model name 不能为空")
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.model = CrossEncoder(model_name, device=device)

    def score_pairs(self, query: str, texts: Sequence[str]) -> Sequence[float]:
        if not texts:
            return []
        scores = self.model.predict([(query, text) for text in texts])
        return [float(value) for value in scores]


def rerank_results(
    query: str,
    candidates: Sequence[dict[str, Any]],
    scorer: PairScorer,
    *,
    top_k: int,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    scores = list(
        scorer.score_pairs(query, [str(item.get("text", "")) for item in candidates])
    )
    if len(scores) != len(candidates):
        raise ValueError("reranker 分数数量与候选数量不一致")
    scored = [
        (float(score), index, str(item["chunk_id"]), dict(item))
        for index, (item, score) in enumerate(zip(candidates, scores))
    ]
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    results: list[dict[str, Any]] = []
    for rank, (score, source_index, _, item) in enumerate(scored[:top_k], start=1):
        item.update(
            {
                "rank": rank,
                "source_rank": source_index + 1,
                "rerank_score": score,
                "retrieval_score": score,
            }
        )
        results.append(item)
    return results


@dataclass(frozen=True)
class FilterPlan:
    filters: dict[str, Any]
    where: dict[str, Any] | None
    allowed_chunk_ids: set[str] | None
    empty: bool


class HybridRetriever:
    """Apply the same candidate filters to Dense, BM25, RRF, and reranking."""

    def __init__(
        self,
        vector_store: Any,
        *,
        embedder: Any | None = None,
        metric_index: MetricEvidenceIndex | None = None,
        ontology: MetricOntology | None = None,
    ) -> None:
        self.vector_store = vector_store
        self.embedder = embedder
        self.metric_index = metric_index
        self.ontology = ontology or MetricOntology.from_path()
        self._bm25_cache: dict[str, BM25Index] = {}

    def plan_filters(self, raw_filters: dict[str, Any] | None) -> FilterPlan:
        filters = normalize_retrieval_filters(raw_filters, ontology=self.ontology)
        allowed_ids: set[str] | None = None
        if filters["metrics"]:
            if self.metric_index is None:
                raise RuntimeError("数值过滤需要先生成本地指标记录")
            allowed_ids = self.metric_index.matching_chunk_ids(filters["metrics"])
        where = build_chroma_where(filters, allowed_ids)
        return FilterPlan(
            filters=filters,
            where=where,
            allowed_chunk_ids=allowed_ids,
            empty=allowed_ids is not None and not allowed_ids,
        )

    def _candidate_chunks(self, plan: FilterPlan) -> list[dict[str, Any]]:
        if plan.empty:
            return []
        cache_key = json.dumps(
            {
                "filters": plan.filters,
                "ids": sorted(plan.allowed_chunk_ids)
                if plan.allowed_chunk_ids is not None
                else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if cache_key not in self._bm25_cache:
            chunks = self.vector_store.get_chunks(where=plan.where)
            chunks = [
                chunk
                for chunk in chunks
                if chunk_matches_filters(
                    chunk, plan.filters, plan.allowed_chunk_ids
                )
            ]
            self._bm25_cache[cache_key] = BM25Index(chunks)
        return self._bm25_cache[cache_key].chunks

    def dense_search(
        self,
        query: str,
        *,
        top_k: int,
        plan: FilterPlan,
    ) -> list[dict[str, Any]]:
        if plan.empty:
            return []
        if self.embedder is None:
            raise RuntimeError("Dense 检索缺少 embedder")
        embedding = self.embedder.embed_queries([query])[0]
        results = self.vector_store.query(embedding, top_k=top_k, where=plan.where)
        filtered = [
            result
            for result in results
            if chunk_matches_filters(result, plan.filters, plan.allowed_chunk_ids)
        ]
        for rank, result in enumerate(filtered, start=1):
            result["rank"] = rank
            result["retrieval_score"] = float(result.get("similarity", 0.0))
        return filtered

    def bm25_search(
        self,
        query: str,
        *,
        top_k: int,
        plan: FilterPlan,
    ) -> list[dict[str, Any]]:
        if plan.empty:
            return []
        self._candidate_chunks(plan)
        cache_key = json.dumps(
            {
                "filters": plan.filters,
                "ids": sorted(plan.allowed_chunk_ids)
                if plan.allowed_chunk_ids is not None
                else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return self._bm25_cache[cache_key].search(query, top_k=top_k)

    def search(
        self,
        query: str,
        *,
        method: str,
        top_k: int = 10,
        candidate_k: int = 50,
        rrf_k: int = 60,
        raw_filters: dict[str, Any] | None = None,
        reranker: PairScorer | None = None,
    ) -> list[dict[str, Any]]:
        if method not in {"dense", "bm25", "rrf", "rerank"}:
            raise ValueError(f"未知检索方法：{method}")
        if top_k <= 0 or candidate_k < top_k:
            raise ValueError("candidate_k 必须大于等于正整数 top_k")
        plan = self.plan_filters(raw_filters)
        if method == "dense":
            return self.dense_search(query, top_k=top_k, plan=plan)
        if method == "bm25":
            return self.bm25_search(query, top_k=top_k, plan=plan)
        dense = self.dense_search(query, top_k=candidate_k, plan=plan)
        bm25 = self.bm25_search(query, top_k=candidate_k, plan=plan)
        fused = reciprocal_rank_fusion(
            {"dense": dense, "bm25": bm25}, top_k=candidate_k, rrf_k=rrf_k
        )
        if method == "rrf":
            return fused[:top_k]
        if reranker is None:
            raise RuntimeError("rerank 方法需要显式提供 CrossEncoder scorer")
        return rerank_results(query, fused, reranker, top_k=top_k)
