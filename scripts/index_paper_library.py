"""Incrementally chunk and index parsed library papers with the local BGE model."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.library import DEFAULT_PARSED_PAPER_DIRECTORY, PaperIndexingService
from src.repository import DEFAULT_CATALOG_PATH, PaperCatalog
from src.retrieval.embedder import LocalEmbedder
from src.retrieval.vector_store import DEFAULT_DB_PATH, PaperVectorStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="增量切块并索引已解析的本地论文")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--parsed-dir", type=Path, default=DEFAULT_PARSED_PAPER_DIRECTORY)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--teacher", default="")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--recover-interrupted", action="store_true")
    parser.add_argument("--embedding-batch-size", type=int, default=32)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog = PaperCatalog(args.catalog)
    print("正在加载本地 BGE 模型……", flush=True)
    embedder = LocalEmbedder()
    print(f"Embedding 设备：{embedder.device}", flush=True)
    with PaperVectorStore(persist_directory=args.db_path) as store:
        service = PaperIndexingService(
            catalog,
            embedder=embedder,
            vector_store=store,
            parsed_directory=args.parsed_dir,
        )
        if args.recover_interrupted:
            print(f"恢复中断索引：{service.recover_interrupted()} 篇", flush=True)

        last_reported = -1

        def show_progress(current: int, total: int, title: str, chunks: int) -> None:
            nonlocal last_reported
            if chunks or current == last_reported:
                return
            last_reported = current
            print(f"索引进度：{current}/{total}｜{title}", flush=True)

        result = service.index_batch(
            limit=args.limit,
            teacher=args.teacher,
            retry_failed=args.retry_failed,
            embedding_batch_size=args.embedding_batch_size,
            progress=show_progress,
        )
    print(
        f"本批请求：{result.requested}｜完成：{result.completed}｜失败：{result.failed}｜"
        f"新增/更新 Chunk：{result.chunks_indexed}｜"
        f"向量库：{result.starting_chunk_count} -> {result.ending_chunk_count}"
    )
    for error in result.errors:
        print(f"[ERROR] {error}", file=sys.stderr)
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
