"""Split parsed papers into overlapping text chunks with source metadata."""

from __future__ import annotations

import random
import re
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    from .pdf_parser import parse_papers
    from ..repository import PaperCatalog, load_metadata_seed, sync_parsed_papers
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from pdf_parser import parse_papers
    from src.repository import PaperCatalog, load_metadata_seed, sync_parsed_papers


DEFAULT_CHUNK_SIZE = 450
DEFAULT_OVERLAP = 80
CHUNKER_VERSION = "section_v2"
UNKNOWN_SECTION_PATH = "未识别章节"

SECTION_TYPES = frozenset(
    {
        "abstract",
        "intro",
        "related_work",
        "method",
        "experiment",
        "results",
        "discussion",
        "conclusion",
        "reference",
        "ack",
        "appendix",
        "contents",
        "unknown",
    }
)

HEADING_PATTERNS = (
    re.compile(r"^第\s*[一二三四五六七八九十百\d]+\s*章(?:\s+|$)"),
    re.compile(r"^(?:[1-9]|\d+(?:\.\d+){1,3})\s+[A-Za-z\u4e00-\u9fff]"),
    re.compile(
        r"^(?:摘\s*要|Abstract|引\s*言|参考文献|References|致\s*谢|"
        r"Acknowledgements?|附\s*录|Appendix|结论与展望|全文总结)$",
        flags=re.IGNORECASE,
    ),
)

SECTION_TYPE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("contents", re.compile(r"(?:目\s*录|\bcontents\b)", re.IGNORECASE)),
    ("abstract", re.compile(r"(?:摘\s*要|\babstract\b)", re.IGNORECASE)),
    ("reference", re.compile(r"(?:参考文献|\breferences\b)", re.IGNORECASE)),
    ("ack", re.compile(r"(?:致\s*谢|acknowledg)", re.IGNORECASE)),
    ("appendix", re.compile(r"(?:附\s*录|\bappendix\b)", re.IGNORECASE)),
    (
        "conclusion",
        re.compile(r"(?:结论|总结|展望|conclusion|summary|outlook)", re.IGNORECASE),
    ),
    (
        "related_work",
        re.compile(r"(?:研究现状|文献综述|国内外现状|related\s+work)", re.IGNORECASE),
    ),
    (
        "discussion",
        re.compile(r"(?:结果与讨论|分析与讨论|discussion)", re.IGNORECASE),
    ),
    (
        "results",
        re.compile(r"(?:实验结果|性能测试|性能表征|研究结果|\bresults?\b)", re.IGNORECASE),
    ),
    (
        "experiment",
        re.compile(r"(?:实验部分|测试方法|表征方法|实验装置|experiment)", re.IGNORECASE),
    ),
    (
        "method",
        re.compile(r"(?:制备方法|制备工艺|研究方法|材料与方法|method|fabrication)", re.IGNORECASE),
    ),
    (
        "intro",
        re.compile(r"(?:绪\s*论|引\s*言|研究背景|introduction)", re.IGNORECASE),
    ),
)

def _join_pages(parsed_pdf: dict[str, Any]) -> tuple[str, list[tuple[int, int, int]]]:
    """Join non-empty pages and record each page's character-offset range."""
    parts: list[str] = []
    page_ranges: list[tuple[int, int, int]] = []
    current_offset = 0

    for page in parsed_pdf["pages"]:
        page_text = page["text"].strip()
        if not page_text:
            continue

        if parts:
            parts.append("\n")
            current_offset += 1

        page_start = current_offset
        parts.append(page_text)
        current_offset += len(page_text)
        page_ranges.append((page_start, current_offset, page["page"]))

    return "".join(parts), page_ranges


def _normalize_heading(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text.casefold())


def _looks_like_heading(text: str) -> bool:
    compact = " ".join(text.split())
    return len(compact) <= 100 and any(
        pattern.search(compact) for pattern in HEADING_PATTERNS
    )


def _apply_heading(
    hierarchy: list[str], level: int, title: str
) -> list[str]:
    normalized_level = max(1, level)
    result = hierarchy[: normalized_level - 1]
    while len(result) < normalized_level - 1:
        result.append("未识别上级章节")
    result.append(" ".join(title.split()))
    return result


def _fallback_heading_level(text: str) -> int:
    compact = " ".join(text.split())
    numbered = re.match(r"^(\d+(?:\.\d+){0,3})\s+", compact)
    if numbered:
        return numbered.group(1).count(".") + 1
    return 1


def _infer_section_type(section_path: str, text: str) -> tuple[str, str]:
    excerpt = " ".join(text.split())[:180]
    if re.search(r"\.{6,}|…{3,}", excerpt):
        return "contents", "content_rule"

    heading_context = "" if section_path == UNKNOWN_SECTION_PATH else section_path
    for section_type, pattern in SECTION_TYPE_PATTERNS:
        if heading_context and pattern.search(heading_context):
            return section_type, "heading_rule"

    # Content is only a conservative fallback. Unknown is retained rather than
    # forcing every paragraph into a misleading chapter class.
    for section_type, pattern in SECTION_TYPE_PATTERNS:
        if pattern.search(excerpt):
            return section_type, "content_rule"
    return "unknown", "unknown"


def _matching_toc_index(text: str, entries: list[dict[str, Any]]) -> int | None:
    normalized_text = _normalize_heading(text)
    if not normalized_text:
        return None
    for index, entry in enumerate(entries):
        normalized_title = _normalize_heading(str(entry["title"]))
        if normalized_title and (
            normalized_text == normalized_title
            or normalized_text.startswith(normalized_title)
            or normalized_title.startswith(normalized_text)
        ):
            return index
    return None


def _iter_structured_segments(parsed_pdf: dict[str, Any]) -> Iterable[dict[str, Any]]:
    toc = sorted(
        parsed_pdf.get("toc", []),
        key=lambda item: (int(item.get("page", 0)), int(item.get("level", 1))),
    )
    toc_index = 0
    hierarchy: list[str] = []
    has_toc = bool(toc)

    for page in parsed_pdf["pages"]:
        page_number = int(page["page"])
        while toc_index < len(toc) and int(toc[toc_index]["page"]) < page_number:
            entry = toc[toc_index]
            hierarchy = _apply_heading(
                hierarchy, int(entry["level"]), str(entry["title"])
            )
            toc_index += 1

        page_entries: list[dict[str, Any]] = []
        while toc_index < len(toc) and int(toc[toc_index]["page"]) == page_number:
            page_entries.append(toc[toc_index])
            toc_index += 1

        blocks = page.get("blocks") or [
            {
                "block_number": 1,
                "block_type": "paragraph",
                "text": page.get("text", ""),
            }
        ]
        remaining_entries = list(page_entries)
        for block in blocks:
            text = str(block.get("text", "")).strip()
            if not text:
                continue

            toc_match = _matching_toc_index(text, remaining_entries)
            if toc_match is not None:
                for entry in remaining_entries[: toc_match + 1]:
                    hierarchy = _apply_heading(
                        hierarchy, int(entry["level"]), str(entry["title"])
                    )
                remaining_entries = remaining_entries[toc_match + 1 :]
                continue

            if not has_toc and _looks_like_heading(text):
                hierarchy = _apply_heading(
                    hierarchy, _fallback_heading_level(text), text
                )
                continue

            section_path = " > ".join(hierarchy) or UNKNOWN_SECTION_PATH
            section_type, section_type_source = _infer_section_type(
                section_path, text
            )
            yield {
                "text": text,
                "page_start": page_number,
                "page_end": page_number,
                "block_start": int(block.get("block_number", 1)),
                "block_end": int(block.get("block_number", 1)),
                "block_type": str(block.get("block_type", "paragraph")),
                "section_path": section_path,
                "section_type": section_type,
                "section_type_source": section_type_source,
            }

        for entry in remaining_entries:
            hierarchy = _apply_heading(
                hierarchy, int(entry["level"]), str(entry["title"])
            )


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    minimum_boundary = max(1, int(chunk_size * 0.60))
    while start < len(text):
        maximum_end = min(start + chunk_size, len(text))
        end = maximum_end
        if maximum_end < len(text):
            window = text[start + minimum_boundary : maximum_end]
            boundaries = [
                match.end()
                for match in re.finditer(r"[\n。！？；.!?]\s*", window)
            ]
            if boundaries:
                end = start + minimum_boundary + boundaries[-1]
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(start + 1, end - overlap)
        start = next_start
    return chunks


def _base_metadata(
    file_name: str,
    paper_metadata: dict[str, Any],
    parsed_pdf: dict[str, Any],
) -> dict[str, Any]:
    return {
        "file_name": file_name,
        "title": paper_metadata.get("title", Path(file_name).stem),
        "author": paper_metadata.get("author", ""),
        "teacher": paper_metadata.get("teacher", ""),
        "year": paper_metadata.get("year"),
        "direction": paper_metadata.get("direction", "unclassified"),
        "paper_id": paper_metadata.get("paper_id", ""),
        "parser_version": parsed_pdf.get("parser_version", "legacy"),
        "pipeline_version": CHUNKER_VERSION,
    }


def _append_chunk(
    chunks: list[dict[str, Any]],
    file_name: str,
    text: str,
    metadata: dict[str, Any],
) -> None:
    if not text.strip():
        return
    chunk_number = len(chunks) + 1
    chunks.append(
        {
            "chunk_id": f"{Path(file_name).stem}_chunk_{chunk_number:04d}",
            "text": text.strip(),
            "metadata": metadata,
        }
    )


def chunk_document(
    parsed_pdf: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Create section-bounded chunks with page, block, and version metadata."""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0，且小于 chunk_size")

    file_name = parsed_pdf["file_name"]
    paper_metadata = metadata or {}
    chunks: list[dict[str, Any]] = []
    common = _base_metadata(file_name, paper_metadata, parsed_pdf)
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        metadata_for_chunk = {
            **common,
            **{key: value for key, value in current.items() if key != "parts"},
        }
        _append_chunk(
            chunks,
            file_name,
            "\n".join(current["parts"]),
            metadata_for_chunk,
        )
        current = None

    for segment in _iter_structured_segments(parsed_pdf):
        pieces = _split_long_text(segment["text"], chunk_size, overlap)
        for piece in pieces:
            if segment["block_type"] in {"figure_caption", "table_caption"}:
                flush()
                _append_chunk(
                    chunks,
                    file_name,
                    piece,
                    {**common, **{key: value for key, value in segment.items() if key != "text"}},
                )
                continue

            section_key = (
                segment["section_path"],
                segment["section_type"],
                segment["section_type_source"],
            )
            current_key = (
                current.get("section_path"),
                current.get("section_type"),
                current.get("section_type_source"),
            ) if current else None
            current_length = (
                sum(len(part) for part in current["parts"]) + len(current["parts"])
                if current
                else 0
            )
            if (
                current is None
                or current_key != section_key
                or current_length + len(piece) > chunk_size
            ):
                flush()
                current = {
                    "parts": [piece],
                    "page_start": segment["page_start"],
                    "page_end": segment["page_end"],
                    "block_start": segment["block_start"],
                    "block_end": segment["block_end"],
                    "block_type": "paragraph",
                    "section_path": segment["section_path"],
                    "section_type": segment["section_type"],
                    "section_type_source": segment["section_type_source"],
                }
            else:
                current["parts"].append(piece)
                current["page_end"] = segment["page_end"]
                current["block_end"] = segment["block_end"]
    flush()

    return chunks


def chunk_papers(
    parsed_papers: list[dict[str, Any]],
    metadata_by_file: dict[str, dict[str, Any]] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Create chunks for multiple parsed PDFs."""
    metadata_by_file = metadata_by_file or {}
    all_chunks: list[dict[str, Any]] = []

    for parsed_pdf in parsed_papers:
        all_chunks.extend(
            chunk_document(
                parsed_pdf,
                metadata=metadata_by_file.get(parsed_pdf["file_name"]),
                chunk_size=chunk_size,
                overlap=overlap,
            )
        )

    return all_chunks


def print_chunk_summary(
    parsed_papers: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> None:
    """Print per-paper statistics and deterministic sample chunks."""
    print(
        f"切块策略：{CHUNKER_VERSION}｜最大长度={DEFAULT_CHUNK_SIZE}｜"
        f"长段重叠={DEFAULT_OVERLAP}\n"
    )

    for parsed_pdf in parsed_papers:
        file_chunks = [
            chunk
            for chunk in chunks
            if chunk["metadata"]["file_name"] == parsed_pdf["file_name"]
        ]
        original_characters = sum(len(page["text"]) for page in parsed_pdf["pages"])
        average_length = (
            sum(len(chunk["text"]) for chunk in file_chunks) / len(file_chunks)
            if file_chunks
            else 0
        )
        print(f"论文：{parsed_pdf['file_name']}")
        print(f"  原始字符数：{original_characters:,}")
        print(f"  生成 Chunk：{len(file_chunks)}")
        print(f"  平均 Chunk 长度：{average_length:.1f}\n")

    print(f"总 Chunk 数：{len(chunks)}")
    print("\n随机抽查 3 个 Chunk（固定随机种子 42）：")
    for chunk in random.Random(42).sample(chunks, k=min(3, len(chunks))):
        metadata = chunk["metadata"]
        print("-" * 72)
        print(f"Chunk ID：{chunk['chunk_id']}")
        print(
            f"作者：{metadata['author']}｜导师：{metadata['teacher']}｜"
            f"年份：{metadata['year']}｜页码：{metadata['page_start']}-{metadata['page_end']}"
        )
        print(
            f"章节：{metadata['section_path']}｜类型：{metadata['section_type']}｜"
            f"块类型：{metadata['block_type']}"
        )
        print(f"字符数：{len(chunk['text'])}")
        print(f"文本预览：{chunk['text'][:300].replace(chr(10), ' ')}")


def main() -> None:
    """Parse Dataset v0.1, create chunks, and print validation output."""
    parsed_papers = parse_papers()
    catalog = PaperCatalog()
    sync_parsed_papers(
        catalog,
        parsed_papers,
        metadata_by_file=load_metadata_seed(),
        pipeline_version=CHUNKER_VERSION,
    )
    chunks = chunk_papers(parsed_papers, metadata_by_file=catalog.metadata_by_file())
    print_chunk_summary(parsed_papers, chunks)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
