"""Persist paper chunk embeddings in ChromaDB and run local similarity search."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Sequence

import chromadb
from chromadb.config import Settings

try:
    from .embedder import LocalEmbedder
    from ..ingestion.chunker import PAPER_METADATA, chunk_papers
    from ..ingestion.pdf_parser import parse_papers
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.ingestion.chunker import PAPER_METADATA, chunk_papers
    from src.ingestion.pdf_parser import parse_papers
    from src.retrieval.embedder import LocalEmbedder


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vector_db"
WINDOWS_DB_ALIAS = (
    Path(os.environ["LOCALAPPDATA"]) / "industry-academia-agent" / "vector_db"
    if os.name == "nt" and "LOCALAPPDATA" in os.environ
    else DEFAULT_DB_PATH
)
DEFAULT_COLLECTION_NAME = "paper_chunks"
DEFAULT_QUERY = "该团队是否研究过 X 射线探测？"


class PaperVectorStore:
    """Store precomputed BGE vectors and their paper metadata in ChromaDB."""

    def __init__(
        self,
        persist_directory: Path = DEFAULT_DB_PATH,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        self.persist_directory = persist_directory
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        uses_windows_alias = (
            persist_directory == DEFAULT_DB_PATH
            and WINDOWS_DB_ALIAS.exists()
            and persist_directory.resolve() == WINDOWS_DB_ALIAS.resolve()
        )
        self.access_directory = WINDOWS_DB_ALIAS if uses_windows_alias else persist_directory
        self.client = chromadb.PersistentClient(
            path=self.access_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )

    def upsert_chunks(
        self,
        chunks: Sequence[dict[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Insert new chunks or update existing chunks with the same IDs."""
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk 数量必须和 Embedding 数量一致")

        ids = [chunk["chunk_id"] for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {"chunk_id": chunk["chunk_id"], **chunk["metadata"]} for chunk in chunks
        ]
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def count(self) -> int:
        """Return the number of stored chunks."""
        return self.collection.count()

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Return the nearest chunks ranked by cosine similarity."""
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.count() == 0:
            return []

        raw_results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.count()),
            include=["documents", "metadatas", "distances"],
        )
        ids = raw_results["ids"][0]
        documents = raw_results["documents"][0]
        metadatas = raw_results["metadatas"][0]
        distances = raw_results["distances"][0]

        results: list[dict[str, Any]] = []
        for rank, (chunk_id, document, metadata, distance) in enumerate(
            zip(ids, documents, metadatas, distances),
            start=1,
        ):
            results.append(
                {
                    "rank": rank,
                    "chunk_id": chunk_id,
                    "text": document,
                    "metadata": metadata,
                    "distance": float(distance),
                    "similarity": 1.0 - float(distance),
                }
            )
        return results


def index_chunks(
    store: PaperVectorStore,
    chunks: Sequence[dict[str, Any]],
    embedder: LocalEmbedder,
    batch_size: int = 32,
) -> int:
    """Embed and upsert chunks in small batches so progress is visible."""
    if batch_size <= 0:
        raise ValueError("batch_size 必须大于 0")

    total = len(chunks)
    for start in range(0, total, batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = embedder.embed_documents([chunk["text"] for chunk in batch])
        store.upsert_chunks(batch, embeddings)
        completed = min(start + batch_size, total)
        print(f"建库进度：{completed}/{total}", flush=True)
    return store.count()


def print_results(query: str, results: Sequence[dict[str, Any]]) -> None:
    """Print Top-K retrieval results with source information."""
    print(f"\n查询：{query}")
    for result in results:
        metadata = result["metadata"]
        print("-" * 72)
        print(f"Top {result['rank']}")
        print(f"Similarity：{result['similarity']:.4f}")
        print(f"论文：{metadata['title']}")
        print(f"作者：{metadata['author']}｜导师：{metadata['teacher']}")
        print(f"年份：{metadata['year']}｜页码：{metadata['page_start']}-{metadata['page_end']}")
        print(f"Chunk ID：{result['chunk_id']}")
        print(f"文本：{result['text'][:300].replace(chr(10), ' ')}")


def main() -> None:
    """Build the local paper vector database and run the required test query."""
    parsed_papers = parse_papers()
    chunks = chunk_papers(parsed_papers, metadata_by_file=PAPER_METADATA)
    print(f"待写入 Chunk：{len(chunks)}")

    embedder = LocalEmbedder()
    print(f"Embedding 模型：{embedder.model_name}")
    print(f"推理设备：{embedder.device}")

    store = PaperVectorStore()
    print(f"向量数据库：{store.persist_directory}")
    if store.access_directory != store.persist_directory:
        print(f"Windows 兼容入口：{store.access_directory}")
    stored_count = index_chunks(store, chunks, embedder)
    print(f"数据库记录数：{stored_count}")

    query_embedding = embedder.embed_queries([DEFAULT_QUERY])[0]
    results = store.query(query_embedding, top_k=3)
    print_results(DEFAULT_QUERY, results)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
