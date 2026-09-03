"""FastAPI product UI backed by the existing local paper catalog.

This module deliberately reuses the SQLite catalog, parsed-paper cache, and
evidence-first reports.  It does not send paper content to an external model.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from src.library import DEFAULT_PAPER_REPORT_DIRECTORY, PaperAnalysisService
from src.repository import DEFAULT_CATALOG_PATH, INGESTION_STATUSES, PaperCatalog, PaperRecord


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIRECTORY = Path(__file__).resolve().parent / "web_static"

STATUS_LABELS = {
    "discovered": "已发现",
    "metadata_pending": "待解析正文",
    "parsing": "正在解析",
    "parsed": "待建立索引",
    "indexing": "正在建立索引",
    "indexed": "已索引",
    "failed": "解析失败",
    "index_failed": "索引失败",
}

TAG_CATEGORY_LABELS = {
    "research_direction": "研究方向",
    "material": "材料",
    "device": "器件/设备",
    "method": "方法/工艺",
    "metric": "性能指标",
    "application": "应用场景",
    "teacher": "导师",
    "author": "作者",
    "year": "年份",
    "custom": "自定义",
}

CARD_TAG_ORDER = {
    category: position
    for position, category in enumerate(
        ("research_direction", "application", "device", "method", "metric", "material")
    )
}


def _default_catalog_path() -> Path:
    return Path(
        os.getenv("INDUSTRY_AGENT_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))
    ).resolve()


def _status_payload(status: str) -> dict[str, str]:
    tone = "success" if status == "indexed" else "warning"
    if status in {"failed", "index_failed"}:
        tone = "danger"
    elif status in {"parsing", "indexing"}:
        tone = "progress"
    return {
        "value": status,
        "label": STATUS_LABELS.get(status, status),
        "tone": tone,
    }


def _visible_tags(catalog: PaperCatalog, paper_id: str, limit: int = 8) -> list[dict[str, Any]]:
    tags = catalog.list_tags(paper_id, include_rejected=False)
    tags.sort(
        key=lambda tag: (
            0 if tag.review_status == "confirmed" else 1,
            CARD_TAG_ORDER.get(tag.category, 99),
            -tag.confidence,
            tag.value.casefold(),
        )
    )
    visible: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for tag in tags:
        identity = (tag.category, tag.normalized_value)
        if identity in seen or tag.category in {"teacher", "author", "year"}:
            continue
        seen.add(identity)
        visible.append(
            {
                "category": tag.category,
                "category_label": TAG_CATEGORY_LABELS.get(tag.category, tag.category),
                "value": tag.value,
                "confidence": round(tag.confidence, 3),
                "review_status": tag.review_status,
                "source": tag.source,
            }
        )
        if len(visible) >= limit:
            break
    return visible


def _paper_payload(
    catalog: PaperCatalog,
    analysis: PaperAnalysisService,
    record: PaperRecord,
    *,
    detailed: bool = False,
) -> dict[str, Any]:
    report_path = analysis.report_path(record.paper_id)
    payload: dict[str, Any] = {
        "paper_id": record.paper_id,
        "title": record.title,
        "teacher": record.teacher or "待识别",
        "authors": list(record.authors),
        "year": record.year,
        "institution": record.institution,
        "college": record.college,
        "direction": (
            "待识别" if record.direction == "unclassified" else record.direction
        ),
        "keywords": list(record.keywords),
        "page_count": record.page_count,
        "file_size_mb": (
            round(record.file_size_bytes / 1024 / 1024, 1)
            if record.file_size_bytes is not None
            else None
        ),
        "source_type": record.source_type,
        "status": _status_payload(record.ingestion_status),
        "tags": _visible_tags(catalog, record.paper_id, 12 if detailed else 6),
        "has_local_report": report_path.is_file(),
        "has_pdf": Path(record.file_path).is_file(),
        "updated_at": record.updated_at,
    }
    if detailed:
        payload.update(
            {
                "parser_version": record.parser_version,
                "pipeline_version": record.pipeline_version,
                "authorization_note": record.authorization_note,
                "error_message": record.error_message,
            }
        )
    return payload


def create_app(
    *,
    catalog_path: Path | None = None,
    report_directory: Path | None = None,
) -> FastAPI:
    catalog = PaperCatalog(Path(catalog_path or _default_catalog_path()))
    analysis = PaperAnalysisService(
        catalog,
        report_directory=Path(report_directory or DEFAULT_PAPER_REPORT_DIRECTORY),
    )

    application = FastAPI(
        title="产学研 Agent 产品网页",
        version="0.3.0-dev",
        docs_url="/api/docs",
        redoc_url=None,
    )
    application.state.catalog = catalog
    application.state.analysis = analysis
    application.mount(
        "/assets",
        StaticFiles(directory=STATIC_DIRECTORY),
        name="assets",
    )

    @application.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "catalog": catalog.count()}

    @application.get("/api/stats")
    def stats() -> dict[str, Any]:
        records = catalog.all_records()
        status_counts = Counter(record.ingestion_status for record in records)
        teacher_count = len({record.teacher for record in records if record.teacher})
        report_count = sum(
            analysis.report_path(record.paper_id).is_file() for record in records
        )
        return {
            "papers": len(records),
            "teachers": teacher_count,
            "parsed": sum(
                status_counts.get(status, 0)
                for status in ("parsed", "indexing", "indexed", "index_failed")
            ),
            "indexed": status_counts.get("indexed", 0),
            "reports": report_count,
            "status_counts": dict(status_counts),
        }

    @application.get("/api/teachers")
    def teachers(
        query: str = "",
        status: str = "",
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        if status and status not in INGESTION_STATUSES:
            raise HTTPException(status_code=422, detail="未知论文处理状态")
        facets = catalog.teacher_facets(
            query=query,
            ingestion_status=status,
            limit=limit,
        )
        return {
            "items": [item for item in facets if item["teacher"]],
            "total": catalog.count_teacher_facets(
                query=query,
                ingestion_status=status,
            ),
        }

    @application.get("/api/papers")
    def papers(
        query: str = "",
        teacher: str = "",
        status: str = "",
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=18, ge=1, le=60),
    ) -> dict[str, Any]:
        if status and status not in INGESTION_STATUSES:
            raise HTTPException(status_code=422, detail="未知论文处理状态")
        total = catalog.count_search(
            query=query,
            teacher=teacher,
            exact_teacher=bool(teacher),
            ingestion_status=status,
        )
        page_count = max(1, (total + page_size - 1) // page_size)
        safe_page = min(page, page_count)
        records = catalog.search(
            query=query,
            teacher=teacher,
            exact_teacher=bool(teacher),
            ingestion_status=status,
            limit=page_size,
            offset=(safe_page - 1) * page_size,
        )
        return {
            "items": [
                _paper_payload(catalog, analysis, record) for record in records
            ],
            "page": safe_page,
            "page_size": page_size,
            "page_count": page_count,
            "total": total,
        }

    def require_paper(paper_id: str) -> PaperRecord:
        record = catalog.get(paper_id)
        if record is None:
            raise HTTPException(status_code=404, detail="论文不存在")
        return record

    @application.get("/api/papers/{paper_id}")
    def paper_detail(paper_id: str) -> dict[str, Any]:
        record = require_paper(paper_id)
        return _paper_payload(catalog, analysis, record, detailed=True)

    @application.get("/api/papers/{paper_id}/report")
    def paper_report(paper_id: str, download: bool = False):
        record = require_paper(paper_id)
        report = analysis.load_report(record.paper_id)
        if report is None:
            raise HTTPException(status_code=404, detail="该论文尚未生成精读底稿")
        headers = None
        if download:
            filename = quote(f"{record.title}_精读底稿.md")
            headers = {
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
            }
        return PlainTextResponse(report, media_type="text/markdown", headers=headers)

    @application.post("/api/papers/{paper_id}/local-reading")
    def generate_local_reading(paper_id: str) -> dict[str, Any]:
        record = require_paper(paper_id)
        try:
            result = analysis.generate_local_reading(record)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "paper_id": result.paper_id,
            "report": result.report,
            "chunk_count": result.chunk_count,
            "evidence_count": result.evidence_count,
            "covered_sections": list(result.covered_sections),
        }

    @application.get("/api/papers/{paper_id}/pdf")
    def paper_pdf(paper_id: str):
        record = require_paper(paper_id)
        path = Path(record.file_path)
        if path.suffix.casefold() != ".pdf" or not path.is_file():
            raise HTTPException(status_code=404, detail="本机没有该论文原始 PDF")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=record.file_name,
            content_disposition_type="inline",
        )

    @application.get("/")
    def index():
        return FileResponse(STATIC_DIRECTORY / "index.html")

    return application


