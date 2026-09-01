"""Extract layout-aware, page-level evidence from PDF papers."""

from __future__ import annotations

import re
import sys
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pymupdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPERS_DIR = PROJECT_ROOT / "data" / "raw" / "papers"
PARSER_VERSION = "layout_v2"

# These conservative defaults were checked against the three local v0.1 papers
# and a generated PDF fixture. The audit script exposes the observed counts so a
# new corpus can be calibrated before bulk ingestion.
SCRIPT_MAX_SIZE_RATIO = 0.90
SCRIPT_MIN_VERTICAL_RATIO = 0.10
SAME_SIZE_SCRIPT_MIN_VERTICAL_RATIO = 0.30

FIGURE_CAPTION_PATTERN = re.compile(
    r"^(?:图\s*[A-Za-z一二三四五六七八九十\d]|Fig(?:ure)?\.?\s*\d)",
    flags=re.IGNORECASE,
)
TABLE_CAPTION_PATTERN = re.compile(
    r"^(?:表\s*[A-Za-z一二三四五六七八九十\d]|Table\s*\d)",
    flags=re.IGNORECASE,
)
SCRIPT_AT_END_PATTERN = re.compile(r"([_^])\{([^{}]*)\}$")
SCRIPT_AT_START_PATTERN = re.compile(r"^([_^])\{([^{}]*)\}")


def _clean_span_text(text: str) -> tuple[str, str, str]:
    """Separate surrounding whitespace from a span before adding script marks."""
    leading_length = len(text) - len(text.lstrip())
    trailing_length = len(text) - len(text.rstrip())
    leading = text[:leading_length]
    trailing = text[len(text) - trailing_length :] if trailing_length else ""
    end = len(text) - trailing_length if trailing_length else len(text)
    return leading, text[leading_length:end], trailing


def _script_kind(
    span: dict[str, Any],
    base_size: float,
    base_origin_y: float,
) -> str | None:
    """Classify a span as superscript/subscript from size and baseline offsets."""
    size = float(span.get("size", base_size) or base_size)
    if base_size <= 0:
        return None
    origin = span.get("origin") or (0.0, span.get("bbox", (0, 0, 0, 0))[3])
    origin_y = float(origin[1])
    ratio = size / base_size
    vertical_ratio = (base_origin_y - origin_y) / base_size

    is_small_and_shifted = (
        ratio <= SCRIPT_MAX_SIZE_RATIO
        and abs(vertical_ratio) >= SCRIPT_MIN_VERTICAL_RATIO
    )
    is_same_size_but_clearly_shifted = (
        ratio <= 1.03
        and abs(vertical_ratio) >= SAME_SIZE_SCRIPT_MIN_VERTICAL_RATIO
    )
    if not (is_small_and_shifted or is_same_size_but_clearly_shifted):
        return None
    return "superscript" if vertical_ratio > 0 else "subscript"


def _render_line(spans: Iterable[dict[str, Any]]) -> tuple[str, int]:
    """Rebuild one visual line while retaining explicit script notation."""
    visible = [span for span in spans if str(span.get("text", ""))]
    if not visible:
        return "", 0
    if len(visible) == 1:
        return str(visible[0].get("text", "")), 0

    weighted_sizes: dict[float, int] = {}
    for span in visible:
        size = round(float(span.get("size", 0.0)), 1)
        weight = max(1, len(str(span.get("text", "")).strip()))
        weighted_sizes[size] = weighted_sizes.get(size, 0) + weight
    base_size = max(weighted_sizes, key=lambda size: (weighted_sizes[size], size))
    largest_size = max(weighted_sizes)
    if base_size < largest_size * 0.80:
        base_size = largest_size

    base_spans = [
        span
        for span in visible
        if abs(float(span.get("size", base_size)) - base_size) <= 0.2
    ]
    if not base_spans:
        return "".join(str(span.get("text", "")) for span in visible), 0
    base_origin_y = median(
        float(
            (span.get("origin") or (0.0, span.get("bbox", (0, 0, 0, 0))[3]))[
                1
            ]
        )
        for span in base_spans
    )

    rendered: list[str] = []
    script_count = 0
    previous_bbox: tuple[float, float, float, float] | None = None
    for span in visible:
        text = str(span.get("text", ""))
        bbox_value = span.get("bbox") or (0.0, 0.0, 0.0, 0.0)
        bbox = tuple(float(value) for value in bbox_value)
        kind = _script_kind(span, base_size, base_origin_y)

        if (
            previous_bbox is not None
            and rendered
            and not rendered[-1].endswith((" ", "\t"))
            and not text.startswith((" ", "\t"))
            and kind is None
            and bbox[0] - previous_bbox[2] > base_size * 0.28
        ):
            rendered.append(" ")

        if kind:
            leading, core, trailing = _clean_span_text(text)
            if core:
                marker = "^" if kind == "superscript" else "_"
                rendered.extend((leading, f"{marker}{{{core}}}", trailing))
                script_count += 1
            else:
                rendered.append(text)
        else:
            rendered.append(text)
        previous_bbox = bbox
    return "".join(rendered), script_count


def _classify_block_type(text: str) -> str:
    compact = " ".join(text.split())
    if FIGURE_CAPTION_PATTERN.match(compact):
        return "figure_caption"
    if TABLE_CAPTION_PATTERN.match(compact):
        return "table_caption"
    return "paragraph"


def _join_text_parts(parts: Iterable[str]) -> str:
    """Join visual lines and repair script tokens split at a PDF line boundary."""
    joined: list[str] = []
    for part in (value for value in parts if value.strip()):
        if joined:
            previous_match = SCRIPT_AT_END_PATTERN.search(joined[-1])
            current_match = SCRIPT_AT_START_PATTERN.match(part)
            if (
                previous_match
                and current_match
                and previous_match.group(1) == current_match.group(1)
            ):
                marker = previous_match.group(1)
                content = previous_match.group(2) + current_match.group(2)
                joined[-1] = (
                    joined[-1][: previous_match.start()]
                    + f"{marker}{{{content}}}"
                    + part[current_match.end() :]
                )
                continue
        joined.append(part)
    return "\n".join(joined)


def extract_page_layout(page: pymupdf.Page, page_number: int) -> dict[str, Any]:
    """Extract text blocks and preserve layout-encoded superscripts/subscripts."""
    layout = page.get_text("dict", sort=True)
    blocks: list[dict[str, Any]] = []
    page_script_count = 0
    for block in layout.get("blocks", []):
        if block.get("type") != 0:
            continue
        rendered_lines: list[str] = []
        block_script_count = 0
        for line in block.get("lines", []):
            rendered, script_count = _render_line(line.get("spans", []))
            if rendered.strip():
                rendered_lines.append(rendered.rstrip())
                block_script_count += script_count
        text = _join_text_parts(rendered_lines).strip()
        if not text:
            continue
        bbox = [round(float(value), 3) for value in block.get("bbox", (0, 0, 0, 0))]
        blocks.append(
            {
                "block_number": len(blocks) + 1,
                "block_type": _classify_block_type(text),
                "text": text,
                "bbox": bbox,
                "script_span_count": block_script_count,
            }
        )
        page_script_count += block_script_count

    page_text = _join_text_parts(block["text"] for block in blocks).strip()
    return {
        "page": page_number,
        "width": round(float(page.rect.width), 3),
        "height": round(float(page.rect.height), 3),
        "text": page_text,
        "plain_text": page.get_text("text", sort=True).strip(),
        "blocks": blocks,
        "script_span_count": page_script_count,
        "removed_margin_blocks": 0,
    }


def _extract_toc(document: pymupdf.Document) -> list[dict[str, Any]]:
    toc: list[dict[str, Any]] = []
    for item in document.get_toc(simple=True):
        if len(item) < 3:
            continue
        level, title, page_number = item[:3]
        cleaned_title = " ".join(str(title).split())
        if int(page_number) < 1 or not cleaned_title:
            continue
        toc.append(
            {
                "level": max(1, int(level)),
                "title": cleaned_title,
                "page": int(page_number),
            }
        )
    return toc


def _margin_key(page: dict[str, Any], block: dict[str, Any]) -> str | None:
    text = " ".join(str(block.get("text", "")).split())
    if not text or len(text) > 120:
        return None
    bbox = block.get("bbox") or (0.0, 0.0, 0.0, 0.0)
    page_height = float(page.get("height", 0.0))
    if page_height <= 0:
        return None
    in_top_margin = float(bbox[1]) <= page_height * 0.08
    in_bottom_margin = float(bbox[3]) >= page_height * 0.92
    if not (in_top_margin or in_bottom_margin):
        return None
    normalized = re.sub(r"\d+", "#", text.casefold())
    normalized = re.sub(r"\s+", "", normalized)
    return normalized or None


def _remove_recurring_margin_blocks(pages: list[dict[str, Any]]) -> int:
    """Remove short headers/footers repeated across many pages of one paper."""
    if len(pages) < 3:
        return 0
    counts: Counter[str] = Counter()
    for page in pages:
        page_keys = {
            key
            for block in page.get("blocks", [])
            if (key := _margin_key(page, block)) is not None
        }
        counts.update(page_keys)

    minimum_occurrences = max(3, ceil(len(pages) * 0.15))
    recurring = {
        key for key, count in counts.items() if count >= minimum_occurrences
    }
    if not recurring:
        return 0

    removed_total = 0
    for page in pages:
        retained: list[dict[str, Any]] = []
        removed = 0
        for block in page.get("blocks", []):
            key = _margin_key(page, block)
            if key in recurring:
                removed += 1
            else:
                retained.append(block)
        page["blocks"] = retained
        page["text"] = _join_text_parts(
            block["text"] for block in retained
        ).strip()
        page["script_span_count"] = sum(
            int(block.get("script_span_count", 0)) for block in retained
        )
        page["removed_margin_blocks"] = removed
        removed_total += removed
    return removed_total


def parse_pdf(pdf_path: Path) -> dict:
    """Extract layout-aware page text and a table-of-contents hierarchy."""
    pdf_path = Path(pdf_path)

    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file: {pdf_path}")

    pages = []

    with pymupdf.open(pdf_path) as document:
        if document.needs_pass:
            raise ValueError(f"PDF is password-protected: {pdf_path.name}")

        toc = _extract_toc(document)
        for page_number, page in enumerate(document, start=1):
            pages.append(extract_page_layout(page, page_number))

    removed_margin_blocks = _remove_recurring_margin_blocks(pages)

    return {
        "file_name": pdf_path.name,
        "source_path": str(pdf_path.resolve()),
        "total_pages": len(pages),
        "pages": pages,
        "toc": toc,
        "parser_version": PARSER_VERSION,
        "script_span_count": sum(page["script_span_count"] for page in pages),
        "removed_margin_blocks": removed_margin_blocks,
    }


def parse_papers(papers_dir: Path = DEFAULT_PAPERS_DIR) -> list[dict]:
    """Parse every PDF in a directory in a stable filename order."""
    papers_dir = Path(papers_dir)

    if not papers_dir.is_dir():
        raise NotADirectoryError(f"Papers directory does not exist: {papers_dir}")

    pdf_paths = sorted(
        (path for path in papers_dir.iterdir() if path.suffix.lower() == ".pdf"),
        key=lambda path: path.name.casefold(),
    )

    if not pdf_paths:
        raise FileNotFoundError(f"No PDF files found in: {papers_dir}")

    return [parse_pdf(pdf_path) for pdf_path in pdf_paths]


def print_summary(parsed_pdf: dict) -> None:
    """Print a small human-readable extraction summary."""
    pages = parsed_pdf["pages"]
    total_characters = sum(len(page["text"]) for page in pages)
    first_page_preview = pages[0]["text"][:300].replace("\n", " ")

    print(f"论文：{parsed_pdf['file_name']}")
    print(f"页数：{parsed_pdf['total_pages']}")
    print(f"正文字符：{total_characters}")
    print(f"章节书签：{len(parsed_pdf.get('toc', []))}")
    print(f"保留的上下标 Span：{parsed_pdf.get('script_span_count', 0)}")
    print(f"移除的重复页眉页脚块：{parsed_pdf.get('removed_margin_blocks', 0)}")
    print(f"解析器版本：{parsed_pdf.get('parser_version', 'legacy')}")
    print("第一页前 300 字：")
    print(first_page_preview or "[第一页未提取到文本]")


def main() -> None:
    """Parse the default paper directory and print validation summaries."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parsed_papers = parse_papers()

    for index, parsed_pdf in enumerate(parsed_papers):
        if index > 0:
            print("-" * 60)
        print_summary(parsed_pdf)


if __name__ == "__main__":
    main()
