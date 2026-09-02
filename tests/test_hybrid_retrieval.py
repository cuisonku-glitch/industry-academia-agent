"""Tests for filtered BM25, RRF, and optional reranking."""

from __future__ import annotations

import unittest
from typing import Any, Sequence

from src.extraction.metric_ontology import MetricOntology
from src.retrieval.hybrid import (
    BM25Index,
    HybridRetriever,
    MetricEvidenceIndex,
    build_chroma_where,
    normalize_retrieval_filters,
    reciprocal_rank_fusion,
    rerank_results,
    tokenize_for_bm25,
)


def make_chunk(
    chunk_id: str,
    text: str,
    *,
    direction: str = "x_ray_detector",
    section_type: str = "results",
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "text": text,
        "metadata": {
            "direction": direction,
            "section_type": section_type,
            "title": "测试论文",
        },
    }


def make_metric_record(
    metric_id: str,
    chunk_id: str,
    value: float,
    *,
    evidence_level: str = "measured",
) -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "definition_id": "sensitivity",
        "canonical_unit": "μC Gy_air^{-1} cm^{-2}",
        "value_type": "point",
        "normalized_value": value,
        "normalized_min": None,
        "normalized_max": None,
        "evidence_level": evidence_level,
        "test_condition": "80 kV",
        "evidence": {"chunk_id": chunk_id},
    }


class FakeEmbedder:
    device = "cpu"

    def embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in queries]


class FakeStore:
    def __init__(self, chunks: Sequence[dict[str, Any]]) -> None:
        self.chunks = list(chunks)
        self.query_calls = 0
        self.get_calls = 0

    def count(self) -> int:
        return len(self.chunks)

    def get_chunks(self, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self.get_calls += 1
        return [dict(chunk) for chunk in self.chunks]

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        self.query_calls += 1
        return [
            {
                **dict(chunk),
                "similarity": 1 - index * 0.1,
                "distance": index * 0.1,
                "rank": index + 1,
            }
            for index, chunk in enumerate(self.chunks[:top_k])
        ]


class FixedScorer:
    def score_pairs(self, query: str, texts: Sequence[str]) -> Sequence[float]:
        return [0.1, 0.9][: len(texts)]


class HybridRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ontology = MetricOntology.from_path()

    def test_tokenizer_keeps_latin_terms_and_chinese_bigrams(self) -> None:
        tokens = tokenize_for_bm25("MAPbBr3 X射线探测灵敏度")
        self.assertIn("mapbbr3", tokens)
        self.assertIn("射线", tokens)
        self.assertIn("灵敏", tokens)

    def test_bm25_prefers_matching_technical_chunk(self) -> None:
        index = BM25Index(
            [
                make_chunk("c1", "高灵敏度 X射线探测器的实验结果"),
                make_chunk("c2", "普通材料制备流程"),
            ]
        )
        results = index.search("X射线探测灵敏度", top_k=2)
        self.assertEqual(results[0]["chunk_id"], "c1")
        self.assertGreater(results[0]["bm25_score"], 0)

    def test_metric_threshold_is_normalized_and_excludes_inferred_by_default(self) -> None:
        filters = normalize_retrieval_filters(
            {
                "metrics": [
                    {
                        "definition_id": "sensitivity",
                        "operator": "gte",
                        "value": 1.2,
                        "unit": "mC Gyair^-1 cm^-2",
                    }
                ]
            },
            ontology=self.ontology,
        )
        constraint = filters["metrics"][0]
        self.assertEqual(constraint["normalized_value"], 1200.0)
        self.assertEqual(constraint["evidence_levels"], ["measured", "reported"])

        index = MetricEvidenceIndex(
            [
                make_metric_record("m1", "c1", 1300.0),
                make_metric_record("m2", "c2", 1400.0, evidence_level="inferred"),
                make_metric_record("m3", "c3", 1100.0),
            ]
        )
        self.assertEqual(index.matching_chunk_ids(filters["metrics"]), {"c1"})

    def test_range_must_fully_satisfy_hard_threshold(self) -> None:
        record = make_metric_record("m1", "c1", 0)
        record.update(
            {
                "value_type": "range",
                "normalized_value": None,
                "normalized_min": 900.0,
                "normalized_max": 1300.0,
            }
        )
        index = MetricEvidenceIndex([record])
        filters = normalize_retrieval_filters(
            {
                "metrics": [
                    {
                        "definition_id": "sensitivity",
                        "operator": "gte",
                        "value": 1000,
                        "unit": "μC Gy_air^{-1} cm^{-2}",
                    }
                ]
            },
            ontology=self.ontology,
        )
        self.assertEqual(index.matching_chunk_ids(filters["metrics"]), set())

    def test_chroma_where_combines_direction_section_and_metric_candidates(self) -> None:
        filters = normalize_retrieval_filters(
            {
                "direction": "x_ray_detector",
                "section_types": ["results", "discussion"],
            },
            ontology=self.ontology,
        )
        where = build_chroma_where(filters, {"c2", "c1"})
        self.assertEqual(
            where,
            {
                "$and": [
                    {"direction": "x_ray_detector"},
                    {"section_type": {"$in": ["discussion", "results"]}},
                    {"chunk_id": {"$in": ["c1", "c2"]}},
                ]
            },
        )

    def test_rrf_uses_both_rankings_and_is_deterministic(self) -> None:
        c1 = make_chunk("c1", "a")
        c2 = make_chunk("c2", "b")
        fused = reciprocal_rank_fusion(
            {"dense": [c1, c2], "bm25": [c2, c1]}, top_k=2, rrf_k=60
        )
        self.assertEqual([item["chunk_id"] for item in fused], ["c1", "c2"])
        self.assertEqual(fused[0]["component_ranks"], {"dense": 1, "bm25": 2})

    def test_injected_reranker_preserves_source_rank(self) -> None:
        results = rerank_results(
            "query",
            [make_chunk("c1", "a"), make_chunk("c2", "b")],
            FixedScorer(),
            top_k=2,
        )
        self.assertEqual([item["chunk_id"] for item in results], ["c2", "c1"])
        self.assertEqual(results[0]["source_rank"], 2)

    def test_hybrid_engine_runs_dense_bm25_and_rrf(self) -> None:
        store = FakeStore(
            [
                make_chunk("c1", "X射线探测灵敏度"),
                make_chunk("c2", "闪烁体成像", direction="x_ray_imaging"),
            ]
        )
        engine = HybridRetriever(store, embedder=FakeEmbedder(), ontology=self.ontology)
        for method in ("dense", "bm25", "rrf"):
            results = engine.search(
                "X射线探测", method=method, top_k=1, candidate_k=2
            )
            self.assertEqual(results[0]["chunk_id"], "c1")

    def test_empty_numeric_filter_short_circuits_all_backends(self) -> None:
        store = FakeStore([make_chunk("c1", "X射线探测")])
        index = MetricEvidenceIndex([make_metric_record("m1", "c1", 100.0)])
        engine = HybridRetriever(
            store,
            embedder=FakeEmbedder(),
            metric_index=index,
            ontology=self.ontology,
        )
        raw_filters = {
            "metrics": [
                {
                    "definition_id": "sensitivity",
                    "operator": "gte",
                    "value": 1000,
                    "unit": "μC Gy_air^{-1} cm^{-2}",
                }
            ]
        }
        for method in ("dense", "bm25", "rrf"):
            self.assertEqual(
                engine.search(
                    "query",
                    method=method,
                    top_k=1,
                    candidate_k=2,
                    raw_filters=raw_filters,
                ),
                [],
            )
        self.assertEqual(store.query_calls, 0)
        self.assertEqual(store.get_calls, 0)


if __name__ == "__main__":
    unittest.main()
