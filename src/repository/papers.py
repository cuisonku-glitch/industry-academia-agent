"""SQLite-backed paper catalog with deterministic, local-only metadata."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG_PATH = PROJECT_ROOT / "data" / "metadata" / "papers.sqlite3"
WINDOWS_CATALOG_ALIAS = (
    Path.home() / ".industry-academia-agent" / "metadata" / "papers.sqlite3"
    if os.name == "nt"
    else DEFAULT_CATALOG_PATH
)
DEFAULT_METADATA_SEED_PATH = PROJECT_ROOT / "config" / "paper_metadata.seed.json"
CATALOG_SCHEMA_VERSION = 1
INGESTION_STATUSES = frozenset(
    {"discovered", "metadata_pending", "parsing", "parsed", "indexed", "failed"}
)
SOURCE_TYPES = frozenset({"local", "upload", "sample"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def calculate_sha256(path: Path, block_size: int = 1024 * 1024) -> str:
    """Calculate a stable file identifier without loading the whole PDF in memory."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(block_size):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class PaperRecord:
    """One catalog entry. Free text is never used as a hidden enum."""

    paper_id: str
    sha256: str
    file_name: str
    file_path: str
    title: str
    authors: tuple[str, ...] = field(default_factory=tuple)
    teacher: str = ""
    year: int | None = None
    direction: str = "unclassified"
    page_count: int | None = None
    file_size_bytes: int | None = None
    source_type: str = "local"
    ingestion_status: str = "discovered"
    parser_version: str = ""
    pipeline_version: str = ""
    authorization_note: str = ""
    error_message: str = ""
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> None:
        if not self.paper_id or not self.sha256:
            raise ValueError("paper_id 和 sha256 不能为空")
        if self.paper_id != self.sha256:
            raise ValueError("paper_id 必须等于文件 sha256")
        if not self.file_name or not self.file_path or not self.title:
            raise ValueError("file_name、file_path 和 title 不能为空")
        if self.ingestion_status not in INGESTION_STATUSES:
            raise ValueError(f"未知 ingestion_status：{self.ingestion_status}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"未知 source_type：{self.source_type}")
        if self.year is not None and not 1800 <= self.year <= 2200:
            raise ValueError("year 超出允许范围 1800–2200")
        if self.page_count is not None and self.page_count < 0:
            raise ValueError("page_count 不能为负数")
        if self.file_size_bytes is not None and self.file_size_bytes < 0:
            raise ValueError("file_size_bytes 不能为负数")

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["authors"] = list(self.authors)
        return value


class PaperCatalog:
    """Store searchable paper metadata separately from the vector database."""

    def __init__(self, database_path: Path = DEFAULT_CATALOG_PATH) -> None:
        self.database_path = Path(database_path)
        uses_windows_alias = os.name == "nt" and self.database_path == DEFAULT_CATALOG_PATH
        self.access_path = (
            WINDOWS_CATALOG_ALIAS if uses_windows_alias else self.database_path
        )
        self.access_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.access_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL DEFAULT '[]',
                    teacher TEXT NOT NULL DEFAULT '',
                    year INTEGER,
                    direction TEXT NOT NULL DEFAULT 'unclassified',
                    page_count INTEGER,
                    file_size_bytes INTEGER,
                    source_type TEXT NOT NULL,
                    ingestion_status TEXT NOT NULL,
                    parser_version TEXT NOT NULL DEFAULT '',
                    pipeline_version TEXT NOT NULL DEFAULT '',
                    authorization_note TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_papers_teacher ON papers(teacher);
                CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
                CREATE INDEX IF NOT EXISTS idx_papers_direction ON papers(direction);
                CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(ingestion_status);
                CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
                """
            )
            connection.execute(f"PRAGMA user_version = {CATALOG_SCHEMA_VERSION}")

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PaperRecord:
        return PaperRecord(
            paper_id=row["paper_id"],
            sha256=row["sha256"],
            file_name=row["file_name"],
            file_path=row["file_path"],
            title=row["title"],
            authors=tuple(json.loads(row["authors_json"])),
            teacher=row["teacher"],
            year=row["year"],
            direction=row["direction"],
            page_count=row["page_count"],
            file_size_bytes=row["file_size_bytes"],
            source_type=row["source_type"],
            ingestion_status=row["ingestion_status"],
            parser_version=row["parser_version"],
            pipeline_version=row["pipeline_version"],
            authorization_note=row["authorization_note"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert(self, record: PaperRecord) -> PaperRecord:
        record.validate()
        existing = self.get(record.paper_id)
        now = utc_now()
        created_at = existing.created_at if existing else (record.created_at or now)
        updated = PaperRecord(
            **{
                **record.to_public_dict(),
                "authors": tuple(record.authors),
                "created_at": created_at,
                "updated_at": now,
            }
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO papers (
                    paper_id, sha256, file_name, file_path, title, authors_json,
                    teacher, year, direction, page_count, file_size_bytes,
                    source_type, ingestion_status, parser_version, pipeline_version,
                    authorization_note, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    file_name=excluded.file_name,
                    file_path=excluded.file_path,
                    title=excluded.title,
                    authors_json=excluded.authors_json,
                    teacher=excluded.teacher,
                    year=excluded.year,
                    direction=excluded.direction,
                    page_count=excluded.page_count,
                    file_size_bytes=excluded.file_size_bytes,
                    source_type=excluded.source_type,
                    ingestion_status=excluded.ingestion_status,
                    parser_version=excluded.parser_version,
                    pipeline_version=excluded.pipeline_version,
                    authorization_note=excluded.authorization_note,
                    error_message=excluded.error_message,
                    updated_at=excluded.updated_at
                """,
                (
                    updated.paper_id,
                    updated.sha256,
                    updated.file_name,
                    updated.file_path,
                    updated.title,
                    json.dumps(updated.authors, ensure_ascii=False),
                    updated.teacher,
                    updated.year,
                    updated.direction,
                    updated.page_count,
                    updated.file_size_bytes,
                    updated.source_type,
                    updated.ingestion_status,
                    updated.parser_version,
                    updated.pipeline_version,
                    updated.authorization_note,
                    updated.error_message,
                    updated.created_at,
                    updated.updated_at,
                ),
            )
        return updated

    def register_pdf(
        self,
        path: Path,
        *,
        title: str | None = None,
        authors: Iterable[str] = (),
        teacher: str = "",
        year: int | None = None,
        direction: str = "unclassified",
        page_count: int | None = None,
        source_type: str = "local",
        ingestion_status: str = "discovered",
        parser_version: str = "",
        pipeline_version: str = "",
        authorization_note: str = "",
    ) -> PaperRecord:
        path = Path(path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.suffix.casefold() != ".pdf":
            raise ValueError(f"只允许登记 PDF：{path}")
        sha256 = calculate_sha256(path)
        record = PaperRecord(
            paper_id=sha256,
            sha256=sha256,
            file_name=path.name,
            file_path=str(path),
            title=(title or path.stem).strip(),
            authors=tuple(value.strip() for value in authors if value.strip()),
            teacher=teacher.strip(),
            year=year,
            direction=direction.strip() or "unclassified",
            page_count=page_count,
            file_size_bytes=path.stat().st_size,
            source_type=source_type,
            ingestion_status=ingestion_status,
            parser_version=parser_version,
            pipeline_version=pipeline_version,
            authorization_note=authorization_note.strip(),
        )
        return self.upsert(record)

    def get(self, paper_id: str) -> PaperRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0])

    def update_ingestion_status(
        self,
        paper_id: str,
        status: str,
        *,
        error_message: str = "",
        parser_version: str | None = None,
        pipeline_version: str | None = None,
    ) -> PaperRecord:
        """Move one paper through the ingestion state machine."""
        if status not in INGESTION_STATUSES:
            raise ValueError(f"未知 ingestion_status：{status}")
        existing = self.get(paper_id)
        if existing is None:
            raise KeyError(f"论文不存在：{paper_id}")
        return self.upsert(
            replace(
                existing,
                ingestion_status=status,
                error_message=error_message,
                parser_version=(
                    existing.parser_version
                    if parser_version is None
                    else parser_version
                ),
                pipeline_version=(
                    existing.pipeline_version
                    if pipeline_version is None
                    else pipeline_version
                ),
            )
        )

    def search(
        self,
        query: str = "",
        *,
        teacher: str = "",
        title: str = "",
        direction: str = "",
        ingestion_status: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperRecord]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit 必须在 1–500 之间")
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if ingestion_status and ingestion_status not in INGESTION_STATUSES:
            raise ValueError(f"未知 ingestion_status：{ingestion_status}")

        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            pattern = f"%{query.strip()}%"
            clauses.append(
                "(title LIKE ? OR teacher LIKE ? OR file_name LIKE ? OR authors_json LIKE ?)"
            )
            params.extend([pattern, pattern, pattern, pattern])
        for column, value in (
            ("teacher", teacher),
            ("title", title),
            ("direction", direction),
            ("ingestion_status", ingestion_status),
        ):
            if value.strip():
                clauses.append(f"{column} LIKE ?")
                params.append(f"%{value.strip()}%")
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM papers"
            + where_sql
            + " ORDER BY teacher COLLATE NOCASE, title COLLATE NOCASE, paper_id LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    def all_records(self) -> list[PaperRecord]:
        """Return the complete catalog without imposing an interactive-search cap."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM papers "
                "ORDER BY teacher COLLATE NOCASE, title COLLATE NOCASE, paper_id"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def metadata_by_file(self) -> dict[str, dict[str, Any]]:
        return {
            record.file_name: {
                "title": record.title,
                "author": "、".join(record.authors),
                "teacher": record.teacher,
                "year": record.year,
                "direction": record.direction,
                "paper_id": record.paper_id,
            }
            for record in self.all_records()
        }


def load_metadata_seed(
    path: Path = DEFAULT_METADATA_SEED_PATH,
) -> dict[str, dict[str, Any]]:
    """Load reviewable bootstrap metadata; the SQLite catalog remains authoritative."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"论文元数据种子文件不是有效 JSON：{path}") from exc
    papers = payload.get("papers") if isinstance(payload, dict) else None
    if not isinstance(papers, list):
        raise ValueError(f"论文元数据种子文件必须包含 papers 数组：{path}")

    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(papers, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 条论文元数据必须是对象")
        file_name = str(item.get("file_name", "")).strip()
        if not file_name or Path(file_name).name != file_name:
            raise ValueError(f"第 {index} 条论文元数据的 file_name 无效")
        if file_name in result:
            raise ValueError(f"论文元数据 file_name 重复：{file_name}")
        authors = item.get("authors", [])
        if not isinstance(authors, list) or not all(
            isinstance(author, str) for author in authors
        ):
            raise ValueError(f"论文 {file_name} 的 authors 必须是字符串数组")
        result[file_name] = {
            "title": str(item.get("title") or Path(file_name).stem).strip(),
            "authors": [author.strip() for author in authors if author.strip()],
            "teacher": str(item.get("teacher", "")).strip(),
            "year": item.get("year"),
            "direction": str(item.get("direction", "unclassified")).strip()
            or "unclassified",
            "authorization_note": str(item.get("authorization_note", "")).strip(),
        }
    return result


def sync_parsed_papers(
    catalog: PaperCatalog,
    parsed_papers: Iterable[dict[str, Any]],
    *,
    metadata_by_file: dict[str, dict[str, Any]] | None = None,
    papers_directory: Path | None = None,
    pipeline_version: str = "",
) -> list[PaperRecord]:
    """Register parsed local PDFs and preserve searchable ingestion state."""
    overrides = metadata_by_file or {}
    records: list[PaperRecord] = []
    for parsed in parsed_papers:
        file_name = str(parsed["file_name"])
        metadata = overrides.get(file_name, {})
        source_path = parsed.get("source_path")
        if not source_path and papers_directory is not None:
            source_path = str(Path(papers_directory) / file_name)
        if not source_path:
            raise ValueError(f"无法确定论文原文件路径：{file_name}")
        records.append(
            catalog.register_pdf(
                Path(source_path),
                title=str(metadata.get("title") or Path(file_name).stem),
                authors=metadata.get("authors", ()),
                teacher=str(metadata.get("teacher", "")),
                year=metadata.get("year"),
                direction=str(metadata.get("direction", "unclassified")),
                page_count=int(parsed.get("total_pages", 0)) or None,
                source_type="local",
                ingestion_status="parsed",
                parser_version=str(parsed.get("parser_version", "legacy")),
                pipeline_version=pipeline_version,
                authorization_note=str(metadata.get("authorization_note", "")),
            )
        )
    return records
