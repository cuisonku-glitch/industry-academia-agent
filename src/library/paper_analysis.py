"""Local, evidence-first paper reading reports with page citations."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from src.repository import PaperCatalog, PaperRecord

from .paper_indexing import build_library_chunks, load_parsed_paper
from .paper_ingestion import DEFAULT_PARSED_PAPER_DIRECTORY


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPER_REPORT_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "paper_reports"
LOCAL_READING_VERSION = "local_evidence_reading_v1"

SECTION_PLAN: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("摘要与研究目标", ("abstract",), ("摘要", "研究目的", "研究目标")),
    ("研究背景与问题", ("intro", "related_work"), ("研究背景", "研究现状", "存在的问题")),
    (
        "方法与技术路线",
        ("method", "experiment"),
        ("本文设计", "本系统", "总体设计", "硬件设计", "实验方案", "制备流程"),
    ),
    (
        "结果与性能证据",
        ("results", "discussion"),
        ("实验结果", "测试结果", "结果表明", "性能参数", "误报率", "准确率"),
    ),
    ("结论、局限与展望", ("conclusion",), ("结论", "不足", "局限", "展望")),
)


@dataclass(frozen=True)
class PaperReadingResult:
    paper_id: str
    report_path: Path
    report: str
    chunk_count: int
    evidence_count: int
    covered_sections: tuple[str, ...]


def _compact_text(text: str, max_chars: int = 520) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_chars:
        return compact
    boundary = max(
        compact.rfind(mark, 0, max_chars)
        for mark in ("。", "！", "？", ";", ".")
    )
    end = boundary + 1 if boundary >= int(max_chars * 0.55) else max_chars
    return compact[:end].rstrip() + "……"


def _candidate_score(
    chunk: dict[str, Any],
    section_types: tuple[str, ...],
    keywords: tuple[str, ...],
) -> tuple[int, int, int, str]:
    metadata = chunk["metadata"]
    section_type = str(metadata.get("section_type", "unknown"))
    section_path = str(metadata.get("section_path", ""))
    text = str(chunk.get("text", ""))
    exact_type = 1 if section_type in section_types else 0
    keyword_hits = sum(keyword in f"{section_path} {text}" for keyword in keywords)
    page = int(metadata.get("page_start", 999999))
    return (-exact_type, -keyword_hits, page, str(chunk["chunk_id"]))


def select_reading_evidence(
    chunks: Iterable[dict[str, Any]],
    *,
    per_section: int = 2,
) -> dict[str, list[dict[str, Any]]]:
    """Select traceable excerpts; never synthesize claims absent from the PDF."""
    usable = [
        chunk
        for chunk in chunks
        if len(re.sub(r"\s+", "", str(chunk.get("text", "")))) >= 50
        and chunk.get("metadata", {}).get("section_type")
        not in {"contents", "reference", "ack"}
    ]
    selected: dict[str, list[dict[str, Any]]] = {}
    used_ids: set[str] = set()
    for label, section_types, keywords in SECTION_PLAN:
        ranked = sorted(
            usable,
            key=lambda chunk: _candidate_score(chunk, section_types, keywords),
        )
        strong = [
            chunk
            for chunk in ranked
            if chunk["metadata"].get("section_type") in section_types
            or any(
                keyword
                in f"{chunk['metadata'].get('section_path', '')} {chunk['text']}"
                for keyword in keywords
            )
        ]
        if label != "摘要与研究目标":
            strong = [
                chunk
                for chunk in strong
                if not (
                    chunk["metadata"].get("section_type") == "unknown"
                    and int(chunk["metadata"].get("page_start", 0)) <= 3
                )
            ]
        section_items: list[dict[str, Any]] = []
        for chunk in strong:
            if chunk["chunk_id"] in used_ids:
                continue
            section_items.append(chunk)
            used_ids.add(chunk["chunk_id"])
            if len(section_items) == per_section:
                break
        selected[label] = section_items
    return selected


def render_reading_markdown(
    record: PaperRecord,
    parsed: dict[str, Any],
    chunks: list[dict[str, Any]],
    evidence: dict[str, list[dict[str, Any]]],
) -> str:
    lines = [
        f"# {record.title}",
        "",
        "> 本报告由本地规则进行证据型精读：只摘取论文原文并定位页码，"
        "未调用外部大模型，也不把自动摘录冒充专家结论。",
        "",
        "## 基础信息",
        "",
        f"- 导师：{record.teacher or '待识别'}",
        f"- 作者：{'、'.join(record.authors) or '待识别'}",
        f"- 年份：{record.year or '待识别'}",
        f"- PDF 页数：{parsed.get('total_pages', record.page_count or 0)}",
        f"- 解析版本：{parsed.get('parser_version', record.parser_version or '未知')}",
        f"- 精读版本：{LOCAL_READING_VERSION}",
        f"- 可追溯 Chunk：{len(chunks)}",
        "",
        "## 一页导读（抽取式）",
        "",
    ]
    for label, _, _ in SECTION_PLAN:
        items = evidence.get(label, [])
        if items:
            item = items[0]
            metadata = item["metadata"]
            page_start = int(metadata["page_start"])
            page_end = int(metadata["page_end"])
            page_label = (
                f"第 {page_start} 页"
                if page_start == page_end
                else f"第 {page_start}-{page_end} 页"
            )
            lines.append(f"- **{label}**：{_compact_text(item['text'], 220)}（{page_label}）")
        else:
            lines.append(f"- **{label}**：待人工核对。")
    lines.append("")
    evidence_number = 0
    missing: list[str] = []
    for label, _, _ in SECTION_PLAN:
        lines.extend([f"## {label}", ""])
        items = evidence.get(label, [])
        if not items:
            missing.append(label)
            lines.extend(["- 未找到足够明确的对应章节，保留为待人工核对。", ""])
            continue
        for item in items:
            evidence_number += 1
            metadata = item["metadata"]
            page_start = int(metadata["page_start"])
            page_end = int(metadata["page_end"])
            page_label = (
                f"第 {page_start} 页"
                if page_start == page_end
                else f"第 {page_start}-{page_end} 页"
            )
            section_path = metadata.get("section_path", "未识别章节")
            lines.extend(
                [
                    f"### 证据 E{evidence_number:02d}",
                    "",
                    f"> {_compact_text(item['text'])}",
                    "",
                    f"来源：{page_label}；章节：{section_path}；"
                    f"Chunk：`{item['chunk_id']}`",
                    "",
                ]
            )
    lines.extend(
        [
            "## 质量与使用边界",
            "",
            f"- 已覆盖精读栏目：{len(SECTION_PLAN) - len(missing)}/{len(SECTION_PLAN)}",
            f"- 待人工核对栏目：{'、'.join(missing) if missing else '无'}",
            "- 当前版本适合快速定位研究内容，不替代导师或领域专家判断。",
            "- 后续语义总结如调用 Kimi，必须由用户明确同意发送的论文片段范围。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".md.tmp",
            dir=path.parent,
            encoding="utf-8",
            newline="\n",
            delete=False,
        ) as temporary:
            temporary.write(text)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class PaperAnalysisService:
    def __init__(
        self,
        catalog: PaperCatalog,
        *,
        parsed_directory: Path = DEFAULT_PARSED_PAPER_DIRECTORY,
        report_directory: Path = DEFAULT_PAPER_REPORT_DIRECTORY,
    ) -> None:
        self.catalog = catalog
        self.parsed_directory = Path(parsed_directory)
        self.report_directory = Path(report_directory)

    def report_path(self, paper_id: str) -> Path:
        return self.report_directory / f"{paper_id}.md"

    def load_report(self, paper_id: str) -> str | None:
        path = self.report_path(paper_id)
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def generate_local_reading(self, record: PaperRecord) -> PaperReadingResult:
        if record.ingestion_status not in {"parsed", "indexing", "indexed", "index_failed"}:
            raise RuntimeError("论文尚未完成正文解析")
        parsed = load_parsed_paper(
            self.parsed_directory / f"{record.paper_id}.json.gz"
        )
        chunks = build_library_chunks(record, parsed)
        if not chunks:
            raise RuntimeError("正文为空，无法生成证据型精读")
        evidence = select_reading_evidence(chunks)
        report = render_reading_markdown(record, parsed, chunks, evidence)
        path = self.report_path(record.paper_id)
        _write_text_atomic(path, report)
        covered = tuple(label for label, items in evidence.items() if items)
        return PaperReadingResult(
            paper_id=record.paper_id,
            report_path=path,
            report=report,
            chunk_count=len(chunks),
            evidence_count=sum(len(items) for items in evidence.values()),
            covered_sections=covered,
        )
