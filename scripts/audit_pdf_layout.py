"""Audit layout-sensitive PDF text extraction before bulk ingestion."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.pdf_parser import DEFAULT_PAPERS_DIR, parse_pdf


SCRIPT_PATTERN = re.compile(r"(?:\^|_)\{[^{}]+\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="统计 PDF 中依赖字号/基线才能保留的上下标片段"
    )
    parser.add_argument("--papers", type=Path, default=DEFAULT_PAPERS_DIR)
    parser.add_argument(
        "--examples",
        type=int,
        default=0,
        help="每篇最多显示多少条重建示例；默认不显示论文原文",
    )
    parser.add_argument("--output", type=Path, help="可选的 JSON 审计结果路径")
    return parser.parse_args()


def audit_paper(path: Path, example_limit: int = 0) -> dict[str, object]:
    parsed = parse_pdf(path)
    examples: list[dict[str, object]] = []
    pages_with_scripts = 0
    for page in parsed["pages"]:
        if page["script_span_count"]:
            pages_with_scripts += 1
        if len(examples) >= example_limit:
            continue
        for line in page["text"].splitlines():
            if SCRIPT_PATTERN.search(line):
                examples.append(
                    {
                        "page": page["page"],
                        "text": line[:240],
                    }
                )
                if len(examples) >= example_limit:
                    break
    result: dict[str, object] = {
        "file_name": path.name,
        "total_pages": parsed["total_pages"],
        "toc_entries": len(parsed["toc"]),
        "script_span_count": parsed["script_span_count"],
        "pages_with_scripts": pages_with_scripts,
        "removed_margin_blocks": parsed["removed_margin_blocks"],
        "parser_version": parsed["parser_version"],
    }
    if example_limit:
        result["examples"] = examples
    return result


def main() -> None:
    args = parse_args()
    if not args.papers.is_dir():
        raise NotADirectoryError(args.papers)
    paths = sorted(args.papers.glob("*.pdf"), key=lambda path: path.name.casefold())
    if not paths:
        raise FileNotFoundError(f"没有找到 PDF：{args.papers}")
    results = [audit_paper(path, args.examples) for path in paths]
    payload = {
        "paper_count": len(results),
        "script_span_count": sum(int(item["script_span_count"]) for item in results),
        "removed_margin_blocks": sum(
            int(item["removed_margin_blocks"]) for item in results
        ),
        "papers": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
