"""Tests for deterministic offline retrieval metrics."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_retrieval_eval import load_queries
from src.evaluation import evaluate_retrieval, load_jsonl


class RetrievalEvaluationTests(unittest.TestCase):
    def test_query_file_requires_unique_ids_and_nonempty_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "queries.jsonl"
            path.write_text(
                '{"query_id":"q1","query":"真实问题"}\n'
                '{"query_id":"q1","query":"重复问题"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "重复"):
                load_queries(path)

    def setUp(self) -> None:
        self.qrels = [
            {"query_id": "q1", "chunk_id": "a", "relevance": 2},
            {"query_id": "q1", "chunk_id": "c", "relevance": 1},
            {"query_id": "q2", "chunk_id": "d", "relevance": 1},
        ]
        self.run = [
            {"query_id": "q1", "chunk_ids": ["x", "a", "c", "a"]},
            {"query_id": "q2", "chunk_ids": ["d", "z"]},
        ]

    def test_metrics_are_macro_averaged_and_rank_aware(self) -> None:
        result = evaluate_retrieval(self.qrels, self.run, cutoffs=[1, 2, 3])
        self.assertEqual(result["query_count"], 2)
        self.assertEqual(result["run_query_count"], 2)
        self.assertEqual(result["metrics"]["recall@1"], 0.5)
        self.assertEqual(result["metrics"]["recall@2"], 0.75)
        self.assertEqual(result["metrics"]["recall@3"], 1.0)
        self.assertEqual(result["metrics"]["mrr@2"], 0.75)
        self.assertGreater(result["metrics"]["ndcg@3"], result["metrics"]["ndcg@2"])

    def test_missing_run_query_scores_zero(self) -> None:
        result = evaluate_retrieval(self.qrels, self.run[:1], cutoffs=[5])
        self.assertEqual(result["run_query_count"], 1)
        self.assertEqual(result["metrics"]["mrr@5"], 0.25)

    def test_qrels_require_a_positive_judgment_per_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少需要一条"):
            evaluate_retrieval(
                [{"query_id": "q1", "chunk_id": "a", "relevance": 0}],
                [],
            )

    def test_load_jsonl_reports_the_bad_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "bad.jsonl"
            path.write_text('{"ok": true}\nnot-json\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "第 2 行"):
                load_jsonl(path)


if __name__ == "__main__":
    unittest.main()
