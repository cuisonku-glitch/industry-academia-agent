"""Register a recursive local PDF library and create reviewable tag suggestions."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.library import DEFAULT_LIBRARY_ROOT, PaperLibraryService
from src.repository import DEFAULT_CATALOG_PATH, PaperCatalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="递归登记本地 PDF，并生成带来源和置信度的待审核标签"
    )
    parser.add_argument(
        "--papers-dir",
        type=Path,
        default=Path(
            os.getenv("INDUSTRY_AGENT_PAPER_LIBRARY_DIR", str(DEFAULT_LIBRARY_ROOT))
        ),
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--limit", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = PaperCatalog(args.catalog)
    service = PaperLibraryService(catalog)

    last_percent = -1

    def print_progress(current: int, total: int) -> None:
        nonlocal last_percent
        percent = int(current * 100 / total) if total else 100
        if percent != last_percent and (percent % 5 == 0 or current == total):
            print(f"进度：{current}/{total} ({percent}%)")
            last_percent = percent

    result = service.sync_directory(
        args.papers_dir,
        limit=args.limit,
        progress=print_progress,
    )
    print(f"论文目录：{args.papers_dir.resolve()}")
    print(f"目录数据库：{catalog.access_path}")
    print(
        "本次发现：{0}｜新增/变更：{1}｜未变化：{2}｜失败：{3}".format(
            result.discovered,
            result.registered,
            result.unchanged,
            result.failed,
        )
    )
    print(
        f"目录总数：{catalog.count()}｜标签总数：{catalog.count_tags()}｜"
        f"待审核：{catalog.count_tags(review_status='suggested')}"
    )
    for error in result.errors:
        print(f"- {error}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
