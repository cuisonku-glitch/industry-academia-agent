"""Split parsed papers into overlapping text chunks with source metadata."""

from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

try:
    from .pdf_parser import parse_papers
except ImportError:
    from pdf_parser import parse_papers


DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 100

# Dataset v0.1 metadata, checked against the title pages of the three PDFs.
PAPER_METADATA: dict[str, dict[str, Any]] = {
    "MAPbBr3钙钛矿的直写印刷及其高性能X射线探测器的设计.pdf": {
        "author": "周全",
        "teacher": "徐修文",
        "year": 2025,
    },
    "像素化闪烁体的制备及其X射线成像性能研究.pdf": {
        "author": "石怀耀",
        "teacher": "徐修文",
        "year": 2025,
    },
    "基于异质金属掺杂钙钛矿同质结的构筑及其X射线探测器设计.pdf": {
        "author": "王亚聪",
        "teacher": "徐修文",
        "year": 2025,
    },
}


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


def chunk_document(
    parsed_pdf: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    """Create overlapping chunks from one parsed PDF."""
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap 必须大于等于 0，且小于 chunk_size")

    file_name = parsed_pdf["file_name"]
    paper_metadata = metadata or {}
    full_text, page_ranges = _join_pages(parsed_pdf)
    if not full_text:
        return []

    chunks: list[dict[str, Any]] = []
    start = 0
    chunk_number = 1

    while start < len(full_text):
        end = min(start + chunk_size, len(full_text))
        chunk_text = full_text[start:end].strip()
        covered_pages = [
            page_number
            for page_start, page_end, page_number in page_ranges
            if page_start < end and page_end > start
        ]

        if chunk_text and covered_pages:
            chunks.append(
                {
                    "chunk_id": f"{Path(file_name).stem}_chunk_{chunk_number:04d}",
                    "text": chunk_text,
                    "metadata": {
                        "file_name": file_name,
                        "title": paper_metadata.get("title", Path(file_name).stem),
                        "author": paper_metadata.get("author", ""),
                        "teacher": paper_metadata.get("teacher", ""),
                        "year": paper_metadata.get("year"),
                        "page_start": min(covered_pages),
                        "page_end": max(covered_pages),
                    },
                }
            )
            chunk_number += 1

        if end == len(full_text):
            break
        start = end - overlap

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
        f"切块参数：chunk_size={DEFAULT_CHUNK_SIZE}，"
        f"overlap={DEFAULT_OVERLAP}，步长={DEFAULT_CHUNK_SIZE - DEFAULT_OVERLAP}\n"
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
        print(f"字符数：{len(chunk['text'])}")
        print(f"文本预览：{chunk['text'][:300].replace(chr(10), ' ')}")


def main() -> None:
    """Parse Dataset v0.1, create chunks, and print validation output."""
    parsed_papers = parse_papers()
    chunks = chunk_papers(parsed_papers, metadata_by_file=PAPER_METADATA)
    print_chunk_summary(parsed_papers, chunks)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
