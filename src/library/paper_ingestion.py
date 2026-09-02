"""Recoverable, local-only batch parsing for the registered paper library."""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.ingestion.pdf_parser import PARSER_VERSION, parse_pdf
from src.repository import PaperCatalog, PaperRecord

from .paper_library import PaperLibraryService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PARSED_PAPER_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "papers"
LIBRARY_PARSE_PIPELINE_VERSION = "library_parse_v1"


@dataclass(frozen=True)
class ParseBatchResult:
    requested: int
    completed: int
    failed: int
    content_tags_added: int
    paper_ids: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)


def _write_parsed_paper(path: Path, payload: dict) -> None:
    """Write one compressed JSON record atomically so interrupted files are ignored."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".json.gz.tmp",
            dir=path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with gzip.open(temporary_path, mode="wt", encoding="utf-8") as destination:
            json.dump(payload, destination, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class PaperIngestionService:
    """Parse a bounded batch and persist progress in the paper catalog."""

    def __init__(
        self,
        catalog: PaperCatalog,
        *,
        output_directory: Path = DEFAULT_PARSED_PAPER_DIRECTORY,
        library_service: PaperLibraryService | None = None,
    ) -> None:
        self.catalog = catalog
        self.output_directory = Path(output_directory)
        self.library_service = library_service or PaperLibraryService(catalog)

    def _candidates(
        self,
        *,
        limit: int,
        teacher: str = "",
        retry_failed: bool = False,
    ) -> list[PaperRecord]:
        candidates = self.catalog.search(
            teacher=teacher,
            exact_teacher=bool(teacher.strip()),
            ingestion_status="metadata_pending",
            limit=limit,
        )
        if retry_failed and len(candidates) < limit:
            candidates.extend(
                self.catalog.search(
                    teacher=teacher,
                    exact_teacher=bool(teacher.strip()),
                    ingestion_status="failed",
                    limit=limit - len(candidates),
                )
            )
        return candidates

    def recover_interrupted(self, *, limit: int = 500) -> int:
        records = self.catalog.search(ingestion_status="parsing", limit=limit)
        for record in records:
            self.catalog.update_ingestion_status(
                record.paper_id,
                "metadata_pending",
                error_message="上次正文解析中断，已恢复为待重试。",
            )
        return len(records)

    def parse_batch(
        self,
        *,
        limit: int = 10,
        teacher: str = "",
        retry_failed: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ParseBatchResult:
        if limit <= 0 or limit > 100:
            raise ValueError("单批解析数量必须在 1–100 之间")
        candidates = self._candidates(
            limit=limit,
            teacher=teacher,
            retry_failed=retry_failed,
        )
        completed = failed = content_tags_added = 0
        paper_ids: list[str] = []
        errors: list[str] = []
        total = len(candidates)
        for index, record in enumerate(candidates, start=1):
            if progress:
                progress(index - 1, total, record.title)
            self.catalog.update_ingestion_status(
                record.paper_id,
                "parsing",
                error_message="",
            )
            try:
                parsed = parse_pdf(Path(record.file_path))
                parsed["paper_id"] = record.paper_id
                parsed["teacher"] = record.teacher
                parsed["title"] = record.title
                parsed["pipeline_version"] = LIBRARY_PARSE_PIPELINE_VERSION
                output_path = self.output_directory / f"{record.paper_id}.json.gz"
                _write_parsed_paper(output_path, parsed)
                updated = self.catalog.mark_parsed(
                    record.paper_id,
                    page_count=int(parsed["total_pages"]),
                    parser_version=str(parsed.get("parser_version", PARSER_VERSION)),
                    pipeline_version=LIBRARY_PARSE_PIPELINE_VERSION,
                )
                content_tags_added += self.library_service.ensure_content_tags(
                    updated,
                    parsed.get("pages", []),
                )
                completed += 1
                paper_ids.append(record.paper_id)
            except Exception as exc:
                failed += 1
                message = str(exc).strip() or exc.__class__.__name__
                self.catalog.update_ingestion_status(
                    record.paper_id,
                    "failed",
                    error_message=message[:1000],
                )
                if len(errors) < 50:
                    errors.append(f"{record.title}: {message}")
            if progress:
                progress(index, total, record.title)
        return ParseBatchResult(
            requested=total,
            completed=completed,
            failed=failed,
            content_tags_added=content_tags_added,
            paper_ids=tuple(paper_ids),
            errors=tuple(errors),
        )
