"""Synchronize local PDFs into the searchable SQLite paper catalog."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingestion.chunker import CHUNKER_VERSION
from src.ingestion.pdf_parser import DEFAULT_PAPERS_DIR, parse_papers
from src.repository import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_METADATA_SEED_PATH,
    PaperCatalog,
    load_metadata_seed,
    sync_parsed_papers,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步本地 PDF 与论文目录数据库")
    parser.add_argument("--papers-dir", type=Path, default=DEFAULT_PAPERS_DIR)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_METADATA_SEED_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parsed_papers = parse_papers(args.papers_dir)
    catalog = PaperCatalog(args.catalog)
    records = sync_parsed_papers(
        catalog,
        parsed_papers,
        metadata_by_file=load_metadata_seed(args.seed),
        papers_directory=args.papers_dir,
        pipeline_version=CHUNKER_VERSION,
    )
    print(f"目录数据库：{catalog.database_path}")
    if catalog.access_path != catalog.database_path:
        print(f"Windows 兼容入口：{catalog.access_path}")
    print(f"本次同步：{len(records)} 篇｜目录总数：{catalog.count()} 篇")
    for record in records:
        print(
            f"- {record.title}｜导师：{record.teacher or '待补充'}｜"
            f"页数：{record.page_count or '未知'}｜状态：{record.ingestion_status}"
        )


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
