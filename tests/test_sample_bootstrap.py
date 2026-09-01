"""Tests for the copyright-safe synthetic sample bootstrap."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Sequence

from scripts.bootstrap_sample_data import (
    DEFAULT_DATASET_PATH,
    install_sample_dataset,
    load_sample_dataset,
)


class FakeEmbedder:
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(len(text)), 1.0] for text in texts]


class FakeStore:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def count(self) -> int:
        return len(self.items)

    def upsert_chunks(
        self,
        chunks: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        self.items.extend(chunks)


class SampleBootstrapTests(unittest.TestCase):
    def test_dataset_is_synthetic_and_traceable(self) -> None:
        dataset = load_sample_dataset(DEFAULT_DATASET_PATH)
        self.assertIn("完全由项目维护者合成", dataset["notice_zh"])
        self.assertEqual(len(dataset["capability_records"]), 2)
        self.assertEqual(len(dataset["chunks"]), 4)

    def test_install_builds_profiles_without_real_papers(self) -> None:
        dataset = load_sample_dataset(DEFAULT_DATASET_PATH)
        store = FakeStore()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            result = install_sample_dataset(
                dataset,
                store,
                FakeEmbedder(),
                root / "capabilities",
                root / "teachers",
            )
            self.assertEqual(result["chunk_count"], 4)
            self.assertEqual(result["paper_count"], 2)
            self.assertEqual(result["teacher_count"], 1)
            self.assertEqual(len(list((root / "capabilities").glob("*.json"))), 2)
            self.assertEqual(len(list((root / "teachers").glob("*.json"))), 1)

    def test_install_refuses_to_mix_with_existing_data(self) -> None:
        dataset = load_sample_dataset(DEFAULT_DATASET_PATH)
        store = FakeStore()
        store.items.append({"existing": True})
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaisesRegex(RuntimeError, "避免混入真实数据"):
                install_sample_dataset(
                    dataset,
                    store,
                    FakeEmbedder(),
                    root / "capabilities",
                    root / "teachers",
                )


if __name__ == "__main__":
    unittest.main()
