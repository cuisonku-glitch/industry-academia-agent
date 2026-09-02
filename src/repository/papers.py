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
CATALOG_SCHEMA_VERSION = 2
INGESTION_STATUSES = frozenset(
    {"discovered", "metadata_pending", "parsing", "parsed", "indexed", "failed"}
)
SOURCE_TYPES = frozenset({"local", "upload", "sample"})
TAG_CATEGORIES = frozenset(
    {
        "research_direction",
        "material",
        "device",
        "method",
        "metric",
        "application",
        "teacher",
        "author",
        "year",
        "custom",
    }
)
TAG_SOURCES = frozenset(
    {"metadata", "filename_rule", "content_rule", "model", "user"}
)
TAG_REVIEW_STATUSES = frozenset({"suggested", "confirmed", "rejected"})


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
    institution: str = ""
    college: str = ""
    year: int | None = None
    direction: str = "unclassified"
    keywords: tuple[str, ...] = field(default_factory=tuple)
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
        value["keywords"] = list(self.keywords)
        return value


@dataclass(frozen=True)
class PaperTag:
    """A reviewable paper tag with provenance instead of a hidden label."""

    paper_id: str
    category: str
    value: str
    source: str = "filename_rule"
    confidence: float = 0.5
    review_status: str = "suggested"
    evidence: str = ""
    tag_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def validate(self) -> None:
        if not self.paper_id or not self.value.strip():
            raise ValueError("paper_id 和标签值不能为空")
        if self.category not in TAG_CATEGORIES:
            raise ValueError(f"未知标签类别：{self.category}")
        if self.source not in TAG_SOURCES:
            raise ValueError(f"未知标签来源：{self.source}")
        if self.review_status not in TAG_REVIEW_STATUSES:
            raise ValueError(f"未知标签审核状态：{self.review_status}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("标签置信度必须在 0–1 之间")

    @property
    def normalized_value(self) -> str:
        return " ".join(self.value.casefold().split())

    def stable_id(self) -> str:
        if self.tag_id:
            return self.tag_id
        identity = "\x1f".join(
            (self.paper_id, self.category, self.normalized_value, self.source)
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class PaperCatalog:
    """Store searchable paper metadata separately from the vector database."""

    def __init__(self, database_path: Path | None = None) -> None:
        explicit_path = database_path is not None
        self.database_path = Path(database_path or DEFAULT_CATALOG_PATH)
        uses_windows_alias = os.name == "nt" and not explicit_path
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
                    institution TEXT NOT NULL DEFAULT '',
                    college TEXT NOT NULL DEFAULT '',
                    year INTEGER,
                    direction TEXT NOT NULL DEFAULT 'unclassified',
                    keywords_json TEXT NOT NULL DEFAULT '[]',
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
                CREATE TABLE IF NOT EXISTS paper_tags (
                    tag_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    review_status TEXT NOT NULL,
                    evidence TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE,
                    UNIQUE(paper_id, category, normalized_value, source)
                );
                CREATE INDEX IF NOT EXISTS idx_paper_tags_paper ON paper_tags(paper_id);
                CREATE INDEX IF NOT EXISTS idx_paper_tags_lookup
                    ON paper_tags(category, normalized_value, review_status);
                CREATE TABLE IF NOT EXISTS paper_sources (
                    source_path TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    modified_time_ns INTEGER NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    FOREIGN KEY(paper_id) REFERENCES papers(paper_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_paper_sources_paper
                    ON paper_sources(paper_id);
                """
            )
            existing_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(papers)").fetchall()
            }
            for column, definition in (
                ("institution", "TEXT NOT NULL DEFAULT ''"),
                ("college", "TEXT NOT NULL DEFAULT ''"),
                ("keywords_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if column not in existing_columns:
                    connection.execute(
                        f"ALTER TABLE papers ADD COLUMN {column} {definition}"
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
            institution=row["institution"],
            college=row["college"],
            year=row["year"],
            direction=row["direction"],
            keywords=tuple(json.loads(row["keywords_json"])),
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
                "keywords": tuple(record.keywords),
                "created_at": created_at,
                "updated_at": now,
            }
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO papers (
                    paper_id, sha256, file_name, file_path, title, authors_json,
                    teacher, institution, college, year, direction, keywords_json,
                    page_count, file_size_bytes,
                    source_type, ingestion_status, parser_version, pipeline_version,
                    authorization_note, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    file_name=excluded.file_name,
                    file_path=excluded.file_path,
                    title=excluded.title,
                    authors_json=excluded.authors_json,
                    teacher=excluded.teacher,
                    institution=excluded.institution,
                    college=excluded.college,
                    year=excluded.year,
                    direction=excluded.direction,
                    keywords_json=excluded.keywords_json,
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
                    updated.institution,
                    updated.college,
                    updated.year,
                    updated.direction,
                    json.dumps(updated.keywords, ensure_ascii=False),
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
        institution: str = "",
        college: str = "",
        year: int | None = None,
        direction: str = "unclassified",
        keywords: Iterable[str] = (),
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
            institution=institution.strip(),
            college=college.strip(),
            year=year,
            direction=direction.strip() or "unclassified",
            keywords=tuple(value.strip() for value in keywords if value.strip()),
            page_count=page_count,
            file_size_bytes=path.stat().st_size,
            source_type=source_type,
            ingestion_status=ingestion_status,
            parser_version=parser_version,
            pipeline_version=pipeline_version,
            authorization_note=authorization_note.strip(),
        )
        registered = self.upsert(record)
        self.record_source(registered, path)
        return registered

    def record_source(self, record: PaperRecord, path: Path) -> None:
        """Remember an unchanged source file so later scans can skip re-hashing it."""
        path = Path(path).resolve()
        stat = path.stat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_sources (
                    source_path, paper_id, file_size_bytes, modified_time_ns, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    paper_id=excluded.paper_id,
                    file_size_bytes=excluded.file_size_bytes,
                    modified_time_ns=excluded.modified_time_ns,
                    last_seen_at=excluded.last_seen_at
                """,
                (str(path), record.paper_id, stat.st_size, stat.st_mtime_ns, utc_now()),
            )

    def source_paper_id(self, path: Path) -> str | None:
        """Return a cached paper ID only when size and modification time still match."""
        path = Path(path).resolve()
        if not path.is_file():
            return None
        stat = path.stat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT paper_id FROM paper_sources
                WHERE source_path = ? AND file_size_bytes = ? AND modified_time_ns = ?
                """,
                (str(path), stat.st_size, stat.st_mtime_ns),
            ).fetchone()
        return str(row["paper_id"]) if row else None

    def get(self, paper_id: str) -> PaperRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def count(self) -> int:
        with self._connect() as connection:
            return int(
                connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            )

    @staticmethod
    def _tag_from_row(row: sqlite3.Row) -> PaperTag:
        return PaperTag(
            tag_id=row["tag_id"],
            paper_id=row["paper_id"],
            category=row["category"],
            value=row["value"],
            source=row["source"],
            confidence=float(row["confidence"]),
            review_status=row["review_status"],
            evidence=row["evidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_tag(self, tag: PaperTag) -> PaperTag:
        tag.validate()
        if self.get(tag.paper_id) is None:
            raise KeyError(f"论文不存在：{tag.paper_id}")
        tag_id = tag.stable_id()
        now = utc_now()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM paper_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()
            created_at = (
                str(existing["created_at"]) if existing else (tag.created_at or now)
            )
            connection.execute(
                """
                INSERT INTO paper_tags (
                    tag_id, paper_id, category, value, normalized_value, source,
                    confidence, review_status, evidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tag_id) DO UPDATE SET
                    value=excluded.value,
                    confidence=excluded.confidence,
                    review_status=excluded.review_status,
                    evidence=excluded.evidence,
                    updated_at=excluded.updated_at
                """,
                (
                    tag_id,
                    tag.paper_id,
                    tag.category,
                    tag.value.strip(),
                    tag.normalized_value,
                    tag.source,
                    float(tag.confidence),
                    tag.review_status,
                    tag.evidence.strip(),
                    created_at,
                    now,
                ),
            )
        return replace(tag, tag_id=tag_id, created_at=created_at, updated_at=now)

    def list_tags(
        self,
        paper_id: str,
        *,
        include_rejected: bool = True,
    ) -> list[PaperTag]:
        clause = "" if include_rejected else " AND review_status <> 'rejected'"
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_tags WHERE paper_id = ?"
                + clause
                + " ORDER BY category, value, source",
                (paper_id,),
            ).fetchall()
        return [self._tag_from_row(row) for row in rows]

    def review_tag(self, tag_id: str, review_status: str) -> PaperTag:
        if review_status not in TAG_REVIEW_STATUSES:
            raise ValueError(f"未知标签审核状态：{review_status}")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM paper_tags WHERE tag_id = ?", (tag_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"标签不存在：{tag_id}")
        return self.upsert_tag(
            replace(self._tag_from_row(row), review_status=review_status)
        )

    def count_tags(self, *, review_status: str = "") -> int:
        if review_status and review_status not in TAG_REVIEW_STATUSES:
            raise ValueError(f"未知标签审核状态：{review_status}")
        query = "SELECT COUNT(*) FROM paper_tags"
        params: tuple[str, ...] = ()
        if review_status:
            query += " WHERE review_status = ?"
            params = (review_status,)
        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()[0])

    def update_metadata(
        self,
        paper_id: str,
        *,
        title: str,
        authors: Iterable[str],
        teacher: str,
        institution: str,
        college: str,
        year: int | None,
        direction: str,
        keywords: Iterable[str],
        authorization_note: str,
    ) -> PaperRecord:
        existing = self.get(paper_id)
        if existing is None:
            raise KeyError(f"论文不存在：{paper_id}")
        return self.upsert(
            replace(
                existing,
                title=title.strip(),
                authors=tuple(value.strip() for value in authors if value.strip()),
                teacher=teacher.strip(),
                institution=institution.strip(),
                college=college.strip(),
                year=year,
                direction=direction.strip() or "unclassified",
                keywords=tuple(value.strip() for value in keywords if value.strip()),
                authorization_note=authorization_note.strip(),
            )
        )

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

    def mark_parsed(
        self,
        paper_id: str,
        *,
        page_count: int,
        parser_version: str,
        pipeline_version: str = "",
    ) -> PaperRecord:
        existing = self.get(paper_id)
        if existing is None:
            raise KeyError(f"论文不存在：{paper_id}")
        return self.upsert(
            replace(
                existing,
                page_count=page_count,
                ingestion_status="parsed",
                parser_version=parser_version,
                pipeline_version=pipeline_version,
                error_message="",
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
        year: int | None = None,
        keyword: str = "",
        tag: str = "",
        exact_teacher: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperRecord]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit 必须在 1–500 之间")
        if offset < 0:
            raise ValueError("offset 不能为负数")
        if ingestion_status and ingestion_status not in INGESTION_STATUSES:
            raise ValueError(f"未知 ingestion_status：{ingestion_status}")

        where_sql, params = self._search_filter(
            query=query,
            teacher=teacher,
            title=title,
            direction=direction,
            ingestion_status=ingestion_status,
            year=year,
            keyword=keyword,
            tag=tag,
            exact_teacher=exact_teacher,
        )
        sql = (
            "SELECT * FROM papers"
            + where_sql
            + " ORDER BY teacher COLLATE NOCASE, title COLLATE NOCASE, paper_id LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _search_filter(
        *,
        query: str = "",
        teacher: str = "",
        title: str = "",
        direction: str = "",
        ingestion_status: str = "",
        year: int | None = None,
        keyword: str = "",
        tag: str = "",
        exact_teacher: bool = False,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if query.strip():
            pattern = f"%{query.strip()}%"
            clauses.append(
                "(title LIKE ? OR teacher LIKE ? OR file_name LIKE ? OR "
                "authors_json LIKE ? OR keywords_json LIKE ? OR EXISTS ("
                "SELECT 1 FROM paper_tags pt WHERE pt.paper_id = papers.paper_id "
                "AND pt.review_status <> 'rejected' AND pt.value LIKE ?))"
            )
            params.extend([pattern, pattern, pattern, pattern, pattern, pattern])
        for column, value in (
            ("teacher", teacher),
            ("title", title),
            ("direction", direction),
            ("ingestion_status", ingestion_status),
        ):
            if value.strip():
                if column == "teacher" and exact_teacher:
                    clauses.append("teacher = ?")
                    params.append(value.strip())
                else:
                    clauses.append(f"{column} LIKE ?")
                    params.append(f"%{value.strip()}%")
        if year is not None:
            clauses.append("year = ?")
            params.append(int(year))
        if keyword.strip():
            clauses.append("keywords_json LIKE ?")
            params.append(f"%{keyword.strip()}%")
        if tag.strip():
            clauses.append(
                "EXISTS (SELECT 1 FROM paper_tags pt WHERE pt.paper_id = papers.paper_id "
                "AND pt.review_status <> 'rejected' AND pt.value LIKE ?)"
            )
            params.append(f"%{tag.strip()}%")
        where_sql = " WHERE " + " AND ".join(clauses) if clauses else ""
        return where_sql, params

    def count_search(
        self,
        query: str = "",
        *,
        teacher: str = "",
        title: str = "",
        direction: str = "",
        ingestion_status: str = "",
        year: int | None = None,
        keyword: str = "",
        tag: str = "",
        exact_teacher: bool = False,
    ) -> int:
        if ingestion_status and ingestion_status not in INGESTION_STATUSES:
            raise ValueError(f"未知 ingestion_status：{ingestion_status}")
        where_sql, params = self._search_filter(
            query=query,
            teacher=teacher,
            title=title,
            direction=direction,
            ingestion_status=ingestion_status,
            year=year,
            keyword=keyword,
            tag=tag,
            exact_teacher=exact_teacher,
        )
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM papers" + where_sql, params
                ).fetchone()[0]
            )

    def count_teacher_facets(
        self,
        query: str = "",
        *,
        ingestion_status: str = "",
    ) -> int:
        where_sql, params = self._search_filter(
            query=query,
            ingestion_status=ingestion_status,
        )
        with self._connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(DISTINCT teacher) FROM papers" + where_sql,
                    params,
                ).fetchone()[0]
            )

    def teacher_facets(
        self,
        query: str = "",
        *,
        ingestion_status: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if limit <= 0 or limit > 500:
            raise ValueError("limit 必须在 1–500 之间")
        if offset < 0:
            raise ValueError("offset 不能为负数")
        where_sql, params = self._search_filter(
            query=query,
            ingestion_status=ingestion_status,
        )
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT teacher, COUNT(*) AS paper_count FROM papers"
                + where_sql
                + " GROUP BY teacher ORDER BY paper_count DESC, teacher COLLATE NOCASE "
                "LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [
            {"teacher": str(row["teacher"]), "paper_count": int(row["paper_count"])}
            for row in rows
        ]

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
