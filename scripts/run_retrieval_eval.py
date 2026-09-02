"""Generate filtered Dense/BM25/RRF/rerank runs for offline evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import torch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import evaluate_retrieval, load_jsonl
from src.retrieval.embedder import LocalEmbedder
from src.retrieval.hybrid import (
    DEFAULT_METRIC_DIRECTORY,
    CrossEncoderScorer,
    HybridRetriever,
    MetricEvidenceIndex,
)
from src.retrieval.vector_store import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_DB_PATH,
    PaperVectorStore,
)


METHODS = ("dense", "bm25", "rrf", "rerank")


def load_queries(path: Path) -> list[dict[str, Any]]:
    records = load_jsonl(path)
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        query_id = str(record.get("query_id", "")).strip()
        query = str(record.get("query", "")).strip()
        if not query_id or not query:
            raise ValueError("queries 的 query_id 和 query 不能为空")
        if query_id in seen:
            raise ValueError(f"queries 的 query_id 重复：{query_id}")
        filters = record.get("filters", {})
        if not isinstance(filters, dict):
            raise ValueError(f"query {query_id} 的 filters 必须是对象")
        seen.add(query_id)
        queries.append({"query_id": query_id, "query": query, "filters": filters})
    if not queries:
        raise ValueError("queries 不能为空")
    return queries


def _percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(content, encoding="utf-8")
    temporary_path.replace(path)


def _cuda_sync(device: str) -> None:
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()


def run_method(
    engine: HybridRetriever,
    queries: Sequence[dict[str, Any]],
    *,
    method: str,
    top_k: int,
    candidate_k: int,
    rrf_k: int,
    device: str,
    reranker: CrossEncoderScorer | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run: list[dict[str, Any]] = []
    latencies: list[float] = []
    peak_cuda_memory: list[float] = []
    for item in queries:
        if device == "cuda" and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        _cuda_sync(device)
        started = time.perf_counter()
        results = engine.search(
            item["query"],
            method=method,
            top_k=top_k,
            candidate_k=candidate_k,
            rrf_k=rrf_k,
            raw_filters=item["filters"],
            reranker=reranker,
        )
        _cuda_sync(device)
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        if device == "cuda" and torch.cuda.is_available():
            peak_cuda_memory.append(
                torch.cuda.max_memory_allocated() / (1024 * 1024)
            )
        run.append(
            {
                "query_id": item["query_id"],
                "method": method,
                "chunk_ids": [result["chunk_id"] for result in results],
                "ranked_results": [
                    {
                        "chunk_id": result["chunk_id"],
                        "score": round(float(result.get("retrieval_score", 0.0)), 10),
                        **(
                            {"component_ranks": result["component_ranks"]}
                            if "component_ranks" in result
                            else {}
                        ),
                    }
                    for result in results
                ],
                "latency_ms": round(latency_ms, 3),
            }
        )
    return run, {
        "query_count": len(queries),
        "mean_latency_ms": round(statistics.fmean(latencies), 3),
        "p50_latency_ms": round(statistics.median(latencies), 3),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 3),
        "max_latency_ms": round(max(latencies), 3),
        "peak_cuda_memory_mb": round(max(peak_cuda_memory), 3)
        if peak_cuda_memory
        else None,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="生成可公平比较的 Dense/BM25/RRF/CrossEncoder 检索运行文件"
    )
    parser.add_argument("--queries", type=Path, required=True)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument(
        "--output",
        type=Path,
        help="兼容旧入口：只运行一个方法并写入指定 JSONL",
    )
    destination.add_argument(
        "--output-dir",
        type=Path,
        help="运行一个或多个方法，各自写入独立 JSONL，并生成 manifest.json",
    )
    parser.add_argument(
        "--methods", nargs="+", choices=METHODS, default=["dense"]
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION_NAME)
    parser.add_argument("--metrics-dir", type=Path, default=DEFAULT_METRIC_DIRECTORY)
    parser.add_argument(
        "--qrels",
        type=Path,
        help="可选人工相关性标注；提供后为所有 methods 使用同一份 qrels",
    )
    parser.add_argument("--cutoffs", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument(
        "--reranker-model",
        help="仅在 methods 包含 rerank 时加载；可能需要事先下载模型",
    )
    parser.add_argument("--reranker-device", choices=("cpu", "cuda"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.top_k <= 0:
        raise ValueError("top-k 必须大于 0")
    if args.candidate_k < args.top_k:
        raise ValueError("candidate-k 必须大于等于 top-k")
    if args.rrf_k <= 0:
        raise ValueError("rrf-k 必须大于 0")
    if not args.cutoffs or any(value <= 0 for value in args.cutoffs):
        raise ValueError("cutoffs 必须包含正整数")
    methods = list(dict.fromkeys(args.methods))
    if args.output and len(methods) != 1:
        raise ValueError("--output 只能配合一个 method；多方法请使用 --output-dir")
    if "rerank" in methods and not args.reranker_model:
        raise ValueError("rerank 方法必须显式提供 --reranker-model")

    queries = load_queries(args.queries)
    requires_dense = any(method in {"dense", "rrf", "rerank"} for method in methods)
    embedder = LocalEmbedder() if requires_dense else None
    device = embedder.device if embedder is not None else "cpu"
    reranker = (
        CrossEncoderScorer(args.reranker_model, device=args.reranker_device or device)
        if "rerank" in methods
        else None
    )
    metric_index = MetricEvidenceIndex.from_directory(args.metrics_dir)
    query_bytes = args.queries.read_bytes()
    qrel_records = load_jsonl(args.qrels) if args.qrels else None
    manifest: dict[str, Any] = {
        "schema_version": "retrieval_experiment_manifest_v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries_file": args.queries.name,
        "queries_sha256": hashlib.sha256(query_bytes).hexdigest(),
        "collection_name": args.collection_name,
        "top_k": args.top_k,
        "candidate_k": args.candidate_k,
        "rrf_k": args.rrf_k,
        "device": device,
        "reranker_model": args.reranker_model,
        "model_load_time_excluded": True,
        "filtered_query_count": sum(bool(item["filters"]) for item in queries),
        "quality_evaluation": (
            {
                "status": "evaluated",
                "qrels_file": args.qrels.name,
                "qrels_sha256": hashlib.sha256(args.qrels.read_bytes()).hexdigest(),
                "cutoffs": sorted(set(args.cutoffs)),
            }
            if args.qrels
            else {
                "status": "not_run",
                "reason": "no_human_qrels",
            }
        ),
        "methods": {},
    }

    with PaperVectorStore(
        persist_directory=args.db_path,
        collection_name=args.collection_name,
    ) as store:
        if store.count() == 0:
            raise RuntimeError("当前版本向量集合为空，请先重新建库")
        for method in methods:
            # A fresh engine prevents BM25 cache warm-up in one method from making
            # a later method look artificially faster.
            engine = HybridRetriever(
                store,
                embedder=embedder,
                metric_index=metric_index,
            )
            run, measurements = run_method(
                engine,
                queries,
                method=method,
                top_k=args.top_k,
                candidate_k=args.candidate_k,
                rrf_k=args.rrf_k,
                device="cpu" if method == "bm25" else device,
                reranker=reranker,
            )
            output_path = args.output or (args.output_dir / f"{method}.jsonl")
            _atomic_write_text(
                output_path,
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in run),
            )
            method_manifest: dict[str, Any] = {
                "run_file": output_path.name,
                **measurements,
            }
            if qrel_records is not None:
                evaluation = evaluate_retrieval(
                    qrel_records, run, cutoffs=args.cutoffs
                )
                metrics_path = output_path.with_suffix(".metrics.json")
                _atomic_write_text(
                    metrics_path,
                    json.dumps(evaluation, ensure_ascii=False, indent=2) + "\n",
                )
                method_manifest["metrics_file"] = metrics_path.name
                method_manifest["retrieval_metrics"] = evaluation["metrics"]
            manifest["methods"][method] = method_manifest
            print(
                f"{method}: {len(run)} 条查询｜P50 {measurements['p50_latency_ms']} ms｜"
                f"{output_path}"
            )

    manifest_path = (
        args.output.with_suffix(args.output.suffix + ".manifest.json")
        if args.output
        else args.output_dir / "manifest.json"
    )
    _atomic_write_text(
        manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"实验清单：{manifest_path}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
