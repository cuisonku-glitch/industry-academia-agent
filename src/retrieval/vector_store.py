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
    from ..ingestion.chunker import CHUNKER_VERSION, chunk_papers
    from ..ingestion.pdf_parser import parse_papers
    from ..repository import PaperCatalog, load_metadata_seed, sync_parsed_papers
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.ingestion.chunker import CHUNKER_VERSION, chunk_papers
    from src.ingestion.pdf_parser import parse_papers
    from src.repository import PaperCatalog, load_metadata_seed, sync_parsed_papers
    from src.retrieval.embedder import LocalEmbedder


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vector_db"
WINDOWS_DB_ALIAS = (
    Path.home() / ".industry-academia-agent" / "vector_db"
    if os.name == "nt"
    else DEFAULT_DB_PATH
)
DEFAULT_COLLECTION_NAME = f"paper_chunks_{CHUNKER_VERSION}"
DEFAULT_QUERY = "该团队是否研究过 X 射线探测？"


class PaperVectorStore:
    """Store precomputed BGE vectors and their paper metadata in ChromaDB."""

    def __init__(
        self,
        persist_directory: Path = DEFAULT_DB_PATH,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        self.persist_directory = persist_directory
        uses_windows_alias = os.name == "nt" and persist_directory == DEFAULT_DB_PATH
        self.access_directory = WINDOWS_DB_ALIAS if uses_windows_alias else persist_directory
        # On Windows, DEFAULT_DB_PATH may already be a Junction. Calling mkdir on
        # that existing reparse point can raise WinError 183 in a normal shell.
        # A user-home path also avoids per-app LOCALAPPDATA virtualization when
        # Python is launched from Microsoft Store builds of PowerShell or Codex.
        self.access_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=self.access_directory,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )
        configured_space = self.collection.configuration.get("hnsw", {}).get("space")
        if configured_space != "cosine":
            raise RuntimeError(
                f"向量集合距离类型必须是 cosine，实际为：{configured_space!r}"
            )

    def close(self) -> None:
        """Release SQLite/HNSW handles, which is especially important on Windows."""
        self.client.close()

    def __enter__(self) -> "PaperVectorStore":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

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
        metadatas = []
        for chunk in chunks:
            raw_metadata = {"chunk_id": chunk["chunk_id"], **chunk["metadata"]}
            metadata = {
                key: value
                for key, value in raw_metadata.items()
                if value is not None and isinstance(value, (str, int, float, bool))
            }
            metadatas.append(metadata)
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    def count(self) -> int:
        """Return the number of stored chunks."""
        return self.collection.count()

    def get_chunks(
        self, where: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Return stored chunks, optionally filtered by metadata."""
        get_options: dict[str, Any] = {"include": ["documents", "metadatas"]}
        if where:
            get_options["where"] = where
        raw_results = self.collection.get(**get_options)
        chunks = [
            {"chunk_id": chunk_id, "text": document, "metadata": metadata}
            for chunk_id, document, metadata in zip(
                raw_results["ids"],
                raw_results["documents"],
                raw_results["metadatas"],
            )
            if document is not None and metadata is not None
        ]
        return sorted(chunks, key=lambda chunk: chunk["chunk_id"])

    def list_papers(self) -> list[dict[str, Any]]:
        """Return one deterministic metadata record for each indexed paper."""
        papers_by_file: dict[str, dict[str, Any]] = {}
        for chunk in self.get_chunks():
            metadata = chunk["metadata"]
            file_name = str(metadata.get("file_name", "")).strip()
            if file_name and file_name not in papers_by_file:
                papers_by_file[file_name] = {
                    "file_name": file_name,
                    "title": metadata.get("title", Path(file_name).stem),
                    "author": metadata.get("author", ""),
                    "teacher": metadata.get("teacher", ""),
                    "year": metadata.get("year"),
                }
        return [papers_by_file[name] for name in sorted(papers_by_file)]

    def query(
        self,
        query_embedding: Sequence[float],
        top_k: int = 3,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the nearest chunks ranked by cosine similarity."""
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if self.count() == 0:
            return []

        query_options: dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, self.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_options["where"] = where
        raw_results = self.collection.query(
            **query_options,
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
    catalog = PaperCatalog()
    catalog_records = sync_parsed_papers(
        catalog,
        parsed_papers,
        metadata_by_file=load_metadata_seed(),
        pipeline_version=CHUNKER_VERSION,
    )
    chunks = chunk_papers(parsed_papers, metadata_by_file=catalog.metadata_by_file())
    print(f"待写入 Chunk：{len(chunks)}")

    embedder = LocalEmbedder()
    print(f"Embedding 模型：{embedder.model_name}")
    print(f"推理设备：{embedder.device}")

    store = PaperVectorStore()
    print(f"向量数据库：{store.persist_directory}")
    if store.access_directory != store.persist_directory:
        print(f"Windows 兼容入口：{store.access_directory}")
    stored_count = index_chunks(store, chunks, embedder)
    for record in catalog_records:
        catalog.update_ingestion_status(
            record.paper_id,
            "indexed",
            pipeline_version=CHUNKER_VERSION,
        )
    print(f"数据库记录数：{stored_count}")

    query_embedding = embedder.embed_queries([DEFAULT_QUERY])[0]
    results = store.query(query_embedding, top_k=3)
    print_results(DEFAULT_QUERY, results)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
