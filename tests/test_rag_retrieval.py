"""Offline tests for broad teacher-overview retrieval."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Sequence

from src.retrieval.rag import (
    MoonshotConfig,
    RAGPipeline,
    build_overview_retrieval_query,
    is_teacher_overview_question,
)


class RecordingEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        self.queries.extend(queries)
        return [[1.0, 0.0] for _ in queries]


class DiverseFakeStore:
    def __init__(self) -> None:
        self.papers = [
            {
                "file_name": f"paper_{index}.pdf",
                "title": f"论文{index}",
                "teacher": "徐修文",
            }
            for index in range(1, 4)
        ]

    def count(self) -> int:
        return 30

    def list_papers(self) -> list[dict[str, Any]]:
        return self.papers

    def _item(self, index: int, similarity: float) -> dict[str, Any]:
        paper = self.papers[index - 1]
        return {
            "rank": index,
            "chunk_id": f"paper_{index}_chunk_001",
            "text": f"论文{index}研究内容",
            "metadata": {
                **paper,
                "author": f"学生{index}",
                "year": 2025,
                "page_start": 1,
                "page_end": 2,
            },
            "similarity": similarity,
            "distance": 1 - similarity,
        }

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if where:
            index = int(str(where["file_name"]).split("_")[1].split(".")[0])
            return [self._item(index, 0.9 - index * 0.05)]
        return [self._item(1, 0.9), self._item(2, 0.8)][:top_k]


class RAGRetrievalTests(unittest.TestCase):
    def test_only_broad_teacher_questions_trigger_overview_strategy(self) -> None:
        self.assertTrue(is_teacher_overview_question("这个老师研究什么？"))
        self.assertTrue(is_teacher_overview_question("该团队的主要研究方向是什么？"))
        self.assertFalse(is_teacher_overview_question("哪篇论文研究了低压探测器？"))

    def test_overview_query_uses_local_teacher_and_paper_metadata(self) -> None:
        query = build_overview_retrieval_query(
            "这个老师研究什么？", DiverseFakeStore().list_papers()
        )
        self.assertIn("徐修文", query)
        self.assertIn("论文1", query)
        self.assertIn("研究方向、核心技术、实验方法", query)

    def test_overview_retrieval_keeps_evidence_from_every_paper(self) -> None:
        embedder = RecordingEmbedder()
        store = DiverseFakeStore()
        pipeline = RAGPipeline(
            config=MoonshotConfig("test-key", "https://example.invalid/v1", "test"),
            embedder=embedder,
            vector_store=store,
            client=SimpleNamespace(),
        )
        results = pipeline.retrieve("这个老师研究什么？", top_k=5)
        self.assertEqual(
            {item["metadata"]["file_name"] for item in results},
            {"paper_1.pdf", "paper_2.pdf", "paper_3.pdf"},
        )
        self.assertEqual([item["rank"] for item in results], [1, 2, 3])
        self.assertIn("论文主题", embedder.queries[0])


if __name__ == "__main__":
    unittest.main()
