"""Offline contract tests for the Chroma evidence-index adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ingestion.chunker import CHUNKER_VERSION
from src.repository import EvidenceIndex
from src.retrieval.vector_store import DEFAULT_COLLECTION_NAME, PaperVectorStore


class PaperVectorStoreTests(unittest.TestCase):
    def test_default_collection_is_versioned_and_uses_cosine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with PaperVectorStore(
                persist_directory=Path(temporary_directory)
            ) as store:
                self.assertEqual(
                    DEFAULT_COLLECTION_NAME, f"paper_chunks_{CHUNKER_VERSION}"
                )
                self.assertEqual(
                    store.collection.configuration["hnsw"]["space"], "cosine"
                )
                self.assertIsInstance(store, EvidenceIndex)

    def test_none_metadata_is_removed_before_chroma_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with PaperVectorStore(
                persist_directory=Path(temporary_directory)
            ) as store:
                store.upsert_chunks(
                    [{
                        "chunk_id": "chunk-1",
                        "text": "测试文本",
                        "metadata": {"file_name": "paper.pdf", "year": None},
                    }],
                    [[1.0, 0.0]],
                )
                metadata = store.get_chunks()[0]["metadata"]
                self.assertNotIn("year", metadata)
                self.assertEqual(metadata["file_name"], "paper.pdf")

    def test_list_papers_keeps_direction_and_paper_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            with PaperVectorStore(
                persist_directory=Path(temporary_directory)
            ) as store:
                store.upsert_chunks(
                    [{
                        "chunk_id": "chunk-1",
                        "text": "测试文本",
                        "metadata": {
                            "file_name": "paper.pdf",
                            "title": "Paper",
                            "direction": "x_ray_detector",
                            "paper_id": "a" * 64,
                        },
                    }],
                    [[1.0, 0.0]],
                )
                paper = store.list_papers()[0]
                self.assertEqual(paper["direction"], "x_ray_detector")
                self.assertEqual(paper["paper_id"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
