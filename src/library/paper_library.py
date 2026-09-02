"""Scan, register, deduplicate, and tag a local PDF library without external calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterable

import pymupdf

from src.repository import PaperCatalog, PaperRecord, PaperTag


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIBRARY_ROOT = PROJECT_ROOT.parent / "论文"
DEFAULT_UPLOAD_DIRECTORY = PROJECT_ROOT / "data" / "raw" / "uploads"
DEFAULT_TAG_TAXONOMY_PATH = PROJECT_ROOT / "config" / "paper_tag_taxonomy.json"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SKIPPED_DIRECTORY_NAMES = frozenset(
    {".git", ".idea", ".venv", "venv", "__pycache__", "node_modules"}
)
INVALID_WINDOWS_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class LibrarySyncResult:
    discovered: int = 0
    registered: int = 0
    unchanged: int = 0
    failed: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class UploadImportResult:
    record: PaperRecord
    duplicate: bool
    saved_path: Path


def _load_taxonomy(path: Path) -> tuple[dict, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    if not isinstance(rules, list):
        raise ValueError("论文标签规则必须包含 rules 数组")
    cleaned: list[dict] = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            raise ValueError(f"第 {index} 条论文标签规则必须是对象")
        keywords = rule.get("keywords")
        if not isinstance(keywords, list) or not keywords:
            raise ValueError(f"第 {index} 条论文标签规则缺少 keywords")
        cleaned.append(
            {
                "category": str(rule.get("category", "")).strip(),
                "value": str(rule.get("value", "")).strip(),
                "keywords": tuple(
                    str(value).casefold().strip()
                    for value in keywords
                    if str(value).strip()
                ),
                "confidence": float(rule.get("confidence", 0.5)),
            }
        )
    return tuple(cleaned)


class PaperLibraryService:
    """Coordinate the filesystem library with the SQLite paper catalog."""

    def __init__(
        self,
        catalog: PaperCatalog,
        *,
        taxonomy_path: Path = DEFAULT_TAG_TAXONOMY_PATH,
    ) -> None:
        self.catalog = catalog
        self.taxonomy_path = Path(taxonomy_path)
        self.rules = _load_taxonomy(self.taxonomy_path)

    @staticmethod
    def iter_pdf_paths(root: Path) -> Iterable[Path]:
        root = Path(root).resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"论文目录不存在：{root}")
        for current_root, directory_names, file_names in os.walk(root):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in SKIPPED_DIRECTORY_NAMES and not name.startswith(".")
            )
            current = Path(current_root)
            for file_name in sorted(file_names, key=str.casefold):
                if Path(file_name).suffix.casefold() == ".pdf":
                    yield current / file_name

    @staticmethod
    def _teacher_from_path(root: Path, path: Path) -> str:
        relative = path.resolve().relative_to(Path(root).resolve())
        return relative.parts[0] if len(relative.parts) > 1 else ""

    @staticmethod
    def _validate_pdf_header(path: Path) -> None:
        with Path(path).open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise ValueError("文件头不是有效 PDF")

    def suggested_tags(self, record: PaperRecord) -> list[PaperTag]:
        suggestions: list[PaperTag] = []
        if record.teacher:
            suggestions.append(
                PaperTag(
                    paper_id=record.paper_id,
                    category="teacher",
                    value=record.teacher,
                    source="metadata",
                    confidence=1.0,
                    evidence="论文所在的教师目录名",
                )
            )
        for author in record.authors:
            suggestions.append(
                PaperTag(
                    paper_id=record.paper_id,
                    category="author",
                    value=author,
                    source="metadata",
                    confidence=1.0,
                    evidence="论文元数据",
                )
            )
        if record.year is not None:
            suggestions.append(
                PaperTag(
                    paper_id=record.paper_id,
                    category="year",
                    value=str(record.year),
                    source="metadata",
                    confidence=1.0,
                    evidence="论文元数据",
                )
            )

        normalized_title = record.title.casefold()
        seen: set[tuple[str, str]] = set()
        for rule in self.rules:
            matches = [word for word in rule["keywords"] if word in normalized_title]
            identity = (rule["category"], rule["value"].casefold())
            if not matches or identity in seen:
                continue
            seen.add(identity)
            suggestions.append(
                PaperTag(
                    paper_id=record.paper_id,
                    category=rule["category"],
                    value=rule["value"],
                    source="filename_rule",
                    confidence=rule["confidence"],
                    evidence="题名命中：" + "、".join(matches),
                )
            )
        return suggestions

    def ensure_suggested_tags(self, record: PaperRecord) -> int:
        existing = {tag.tag_id for tag in self.catalog.list_tags(record.paper_id)}
        added = 0
        for tag in self.suggested_tags(record):
            if tag.stable_id() in existing:
                continue
            self.catalog.upsert_tag(tag)
            added += 1
        return added

    def sync_directory(
        self,
        root: Path,
        *,
        limit: int | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> LibrarySyncResult:
        root = Path(root).resolve()
        paths = list(self.iter_pdf_paths(root))
        if limit is not None:
            if limit <= 0:
                raise ValueError("limit 必须为正整数")
            paths = paths[:limit]
        registered = unchanged = failed = 0
        errors: list[str] = []
        total = len(paths)
        for index, path in enumerate(paths, start=1):
            try:
                cached_paper_id = self.catalog.source_paper_id(path)
                if cached_paper_id:
                    record = self.catalog.get(cached_paper_id)
                    if record is not None:
                        self.ensure_suggested_tags(record)
                        unchanged += 1
                        if progress:
                            progress(index, total)
                        continue
                self._validate_pdf_header(path)
                record = self.catalog.register_pdf(
                    path,
                    title=path.stem,
                    teacher=self._teacher_from_path(root, path),
                    source_type="local",
                    ingestion_status="metadata_pending",
                    authorization_note="用户指定的本地论文目录；仅在本机登记。",
                )
                self.ensure_suggested_tags(record)
                registered += 1
            except Exception as exc:
                failed += 1
                if len(errors) < 50:
                    errors.append(f"{path.name}: {exc}")
            if progress:
                progress(index, total)
        return LibrarySyncResult(
            discovered=total,
            registered=registered,
            unchanged=unchanged,
            failed=failed,
            errors=tuple(errors),
        )

    @staticmethod
    def _safe_filename(value: str) -> str:
        name = INVALID_WINDOWS_FILENAME.sub("_", Path(value).name).strip(" .")
        return name or "uploaded.pdf"

    def import_upload(
        self,
        stream: BinaryIO,
        file_name: str,
        *,
        target_directory: Path = DEFAULT_UPLOAD_DIRECTORY,
        title: str = "",
        authors: Iterable[str] = (),
        teacher: str = "",
        institution: str = "",
        college: str = "",
        year: int | None = None,
        keywords: Iterable[str] = (),
        authorization_note: str = "",
        max_bytes: int = MAX_UPLOAD_BYTES,
    ) -> UploadImportResult:
        safe_name = self._safe_filename(file_name)
        if Path(safe_name).suffix.casefold() != ".pdf":
            raise ValueError("只允许上传 .pdf 文件")
        target_directory = Path(target_directory).resolve()
        target_directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".upload", dir=target_directory, delete=False
            ) as destination:
                temporary_path = Path(destination.name)
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(f"单个 PDF 不能超过 {max_bytes // 1024 // 1024} MB")
                    digest.update(chunk)
                    destination.write(chunk)
            if total < 5:
                raise ValueError("上传文件为空或不完整")
            self._validate_pdf_header(temporary_path)
            with pymupdf.open(temporary_path) as document:
                if document.needs_pass:
                    raise ValueError("暂不接收加密 PDF")
                page_count = len(document)
                if page_count <= 0:
                    raise ValueError("PDF 没有可读取页面")

            paper_id = digest.hexdigest()
            existing = self.catalog.get(paper_id)
            final_path = target_directory / f"{paper_id[:12]}_{safe_name}"
            duplicate = existing is not None
            if duplicate:
                temporary_path.unlink(missing_ok=True)
                record = existing
            else:
                os.replace(temporary_path, final_path)
                temporary_path = None
                now_size = final_path.stat().st_size
                record = self.catalog.upsert(
                    PaperRecord(
                        paper_id=paper_id,
                        sha256=paper_id,
                        file_name=safe_name,
                        file_path=str(final_path),
                        title=(title or Path(safe_name).stem).strip(),
                        authors=tuple(value.strip() for value in authors if value.strip()),
                        teacher=teacher.strip(),
                        institution=institution.strip(),
                        college=college.strip(),
                        year=year,
                        keywords=tuple(value.strip() for value in keywords if value.strip()),
                        page_count=page_count,
                        file_size_bytes=now_size,
                        source_type="upload",
                        ingestion_status="metadata_pending",
                        authorization_note=authorization_note.strip(),
                    )
                )
                self.catalog.record_source(record, final_path)
            self.ensure_suggested_tags(record)
            return UploadImportResult(
                record=record,
                duplicate=duplicate,
                saved_path=Path(record.file_path),
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
