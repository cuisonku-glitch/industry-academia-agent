"""Evaluate a saved retrieval run against human relevance judgments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import evaluate_retrieval, load_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="计算检索结果的 Recall、MRR 和 nDCG"
    )
    parser.add_argument("--qrels", type=Path, required=True, help="人工标注 JSONL")
    parser.add_argument("--run", type=Path, required=True, help="检索结果 JSONL")
    parser.add_argument(
        "--cutoffs",
        type=int,
        nargs="+",
        default=[5, 10],
        help="评测截断位置，默认 5 10",
    )
    parser.add_argument("--output", type=Path, help="可选的指标 JSON 输出路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = evaluate_retrieval(
        load_jsonl(args.qrels),
        load_jsonl(args.run),
        cutoffs=args.cutoffs,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
