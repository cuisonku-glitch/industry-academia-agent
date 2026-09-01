"""Generate a deterministic local dense-retrieval run for offline evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import load_jsonl
from src.retrieval.embedder import LocalEmbedder
from src.retrieval.vector_store import DEFAULT_DB_PATH, PaperVectorStore


def load_queries(path: Path) -> list[dict[str, str]]:
    records = load_jsonl(path)
    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        query_id = str(record.get("query_id", "")).strip()
        query = str(record.get("query", "")).strip()
        if not query_id or not query:
            raise ValueError("queries 的 query_id 和 query 不能为空")
        if query_id in seen:
            raise ValueError(f"queries 的 query_id 重复：{query_id}")
        seen.add(query_id)
        queries.append({"query_id": query_id, "query": query})
    if not queries:
        raise ValueError("queries 不能为空")
    return queries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成本地 Dense 检索评测结果")
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--top-k", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("top-k 必须大于 0")
    queries = load_queries(args.queries)
    embedder = LocalEmbedder()
    run: list[dict[str, Any]] = []
    with PaperVectorStore(persist_directory=args.db_path) as store:
        if store.count() == 0:
            raise RuntimeError("当前版本向量集合为空，请先重新建库")
        embeddings = embedder.embed_queries([item["query"] for item in queries])
        for item, embedding in zip(queries, embeddings):
            results = store.query(embedding, top_k=args.top_k)
            run.append(
                {
                    "query_id": item["query_id"],
                    "chunk_ids": [result["chunk_id"] for result in results],
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in run),
        encoding="utf-8",
    )
    print(f"已生成 {len(run)} 条检索结果：{args.output}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
