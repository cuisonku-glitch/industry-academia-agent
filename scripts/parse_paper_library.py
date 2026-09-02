"""Parse a bounded batch of registered papers without calling an external API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.library import DEFAULT_PARSED_PAPER_DIRECTORY, PaperIngestionService
from src.repository import DEFAULT_CATALOG_PATH, PaperCatalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="按小批次解析已登记论文正文；纯本地运行，可从 SQLite 状态恢复"
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_PARSED_PAPER_DIRECTORY
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--teacher", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--recover-interrupted", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = PaperCatalog(args.catalog)
    service = PaperIngestionService(catalog, output_directory=args.output_dir)
    if args.recover_interrupted:
        recovered = service.recover_interrupted()
        print(f"恢复中断任务：{recovered} 篇")

    def print_progress(current: int, total: int, title: str) -> None:
        print(f"解析进度：{current}/{total}｜{title}")

    result = service.parse_batch(
        limit=args.limit,
        teacher=args.teacher,
        retry_failed=args.retry_failed,
        progress=print_progress,
    )
    print(
        f"本批请求：{result.requested}｜完成：{result.completed}｜"
        f"失败：{result.failed}｜新增正文标签：{result.content_tags_added}"
    )
    for error in result.errors:
        print(f"- {error}")
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
