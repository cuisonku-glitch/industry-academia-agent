"""Recoverable incremental chunking and vector indexing for parsed papers."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from src.ingestion.chunker import CHUNKER_VERSION, chunk_document
from src.repository import PaperCatalog, PaperRecord

from .paper_ingestion import DEFAULT_PARSED_PAPER_DIRECTORY


@dataclass(frozen=True)
class IndexBatchResult:
    requested: int
    completed: int
    failed: int
    chunks_indexed: int
    starting_chunk_count: int
    ending_chunk_count: int
    paper_ids: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)


def load_parsed_paper(path: Path) -> dict[str, Any]:
    """Load and minimally validate one compressed parsed-paper record."""
    try:
        with gzip.open(path, mode="rt", encoding="utf-8") as source:
            payload = json.load(source)
    except FileNotFoundError as exc:
        raise RuntimeError(f"解析结果不存在：{path.name}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"解析结果损坏：{path.name}：{exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list):
        raise RuntimeError(f"解析结果结构无效：{path.name}")
    if not str(payload.get("file_name", "")).strip():
        raise RuntimeError(f"解析结果缺少 file_name：{path.name}")
    return payload


def _paper_metadata(record: PaperRecord) -> dict[str, Any]:
    return {
        "paper_id": record.paper_id,
        "file_name": record.file_name,
        "title": record.title,
        "author": "、".join(record.authors),
        "teacher": record.teacher,
        "year": record.year,
        "direction": record.direction,
    }


def build_library_chunks(
    record: PaperRecord,
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create globally stable chunk IDs based on the paper SHA-256."""
    if parsed.get("paper_id") not in {None, "", record.paper_id}:
        raise RuntimeError(f"解析结果与论文 ID 不一致：{record.title}")
    chunks = chunk_document(parsed, metadata=_paper_metadata(record))
    for index, chunk in enumerate(chunks, start=1):
        chunk["chunk_id"] = f"{record.paper_id}_chunk_{index:04d}"
    return chunks


class PaperIndexingService:
    """Index parsed papers one at a time so completed work survives interruption."""

    def __init__(
        self,
        catalog: PaperCatalog,
        *,
        embedder: Any,
        vector_store: Any,
        parsed_directory: Path = DEFAULT_PARSED_PAPER_DIRECTORY,
    ) -> None:
        self.catalog = catalog
        self.embedder = embedder
        self.vector_store = vector_store
        self.parsed_directory = Path(parsed_directory)

    def _candidates(
        self,
        *,
        limit: int,
        teacher: str = "",
        retry_failed: bool = False,
    ) -> list[PaperRecord]:
        records = self.catalog.search(
            teacher=teacher,
            exact_teacher=bool(teacher.strip()),
            ingestion_status="parsed",
            limit=limit,
        )
        if retry_failed and len(records) < limit:
            records.extend(
                self.catalog.search(
                    teacher=teacher,
                    exact_teacher=bool(teacher.strip()),
                    ingestion_status="index_failed",
                    limit=limit - len(records),
                )
            )
        return records

    def recover_interrupted(self, *, limit: int = 500) -> int:
        records = self.catalog.search(ingestion_status="indexing", limit=limit)
        for record in records:
            self.catalog.update_ingestion_status(
                record.paper_id,
                "parsed",
                error_message="上次向量索引中断，已恢复为待重试。",
            )
        return len(records)

    def index_batch(
        self,
        *,
        limit: int = 10,
        teacher: str = "",
        retry_failed: bool = False,
        embedding_batch_size: int = 32,
        progress: Callable[[int, int, str, int], None] | None = None,
    ) -> IndexBatchResult:
        if limit <= 0 or limit > 100:
            raise ValueError("单批索引数量必须在 1-100 之间")
        if embedding_batch_size <= 0:
            raise ValueError("Embedding 批大小必须大于 0")
        candidates = self._candidates(
            limit=limit,
            teacher=teacher,
            retry_failed=retry_failed,
        )
        starting_count = int(self.vector_store.count())
        completed = failed = chunks_indexed = 0
        paper_ids: list[str] = []
        errors: list[str] = []
        total = len(candidates)

        for position, record in enumerate(candidates, start=1):
            if progress:
                progress(position - 1, total, record.title, 0)
            self.catalog.update_ingestion_status(
                record.paper_id,
                "indexing",
                error_message="",
            )
            try:
                parsed = load_parsed_paper(
                    self.parsed_directory / f"{record.paper_id}.json.gz"
                )
                chunks = build_library_chunks(record, parsed)
                if not chunks:
                    raise RuntimeError("正文为空，未生成可索引 Chunk")
                for start in range(0, len(chunks), embedding_batch_size):
                    batch = chunks[start : start + embedding_batch_size]
                    vectors = self.embedder.embed_documents(
                        [chunk["text"] for chunk in batch]
                    )
                    self.vector_store.upsert_chunks(batch, vectors)
                    if progress:
                        progress(
                            position - 1,
                            total,
                            record.title,
                            min(start + embedding_batch_size, len(chunks)),
                        )
                self.catalog.update_ingestion_status(
                    record.paper_id,
                    "indexed",
                    parser_version=str(parsed.get("parser_version", record.parser_version)),
                    pipeline_version=CHUNKER_VERSION,
                )
                completed += 1
                chunks_indexed += len(chunks)
                paper_ids.append(record.paper_id)
            except Exception as exc:
                failed += 1
                message = str(exc).strip() or exc.__class__.__name__
                self.catalog.update_ingestion_status(
                    record.paper_id,
                    "index_failed",
                    error_message=message[:1000],
                )
                if len(errors) < 50:
                    errors.append(f"{record.title}: {message}")
            if progress:
                progress(position, total, record.title, 0)

        return IndexBatchResult(
            requested=total,
            completed=completed,
            failed=failed,
            chunks_indexed=chunks_indexed,
            starting_chunk_count=starting_count,
            ending_chunk_count=int(self.vector_store.count()),
            paper_ids=tuple(paper_ids),
            errors=tuple(errors),
        )
