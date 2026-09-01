"""Install the repository's synthetic, copyright-safe demonstration dataset."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction.teacher_profiler import (
    build_teacher_profiles,
    save_teacher_profile,
    validate_capability_record,
)
from src.retrieval.embedder import LocalEmbedder
from src.retrieval.vector_store import (
    DEFAULT_DB_PATH,
    PaperVectorStore,
    index_chunks,
)


DEFAULT_DATASET_PATH = PROJECT_ROOT / "examples" / "sample_dataset.json"
DEFAULT_CAPABILITY_DIRECTORY = (
    PROJECT_ROOT / "data" / "processed" / "capabilities"
)
DEFAULT_TEACHER_DIRECTORY = (
    PROJECT_ROOT / "data" / "processed" / "teacher_profiles"
)


def load_sample_dataset(path: Path) -> dict[str, Any]:
    """Load and validate the public synthetic dataset before touching local data."""
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"示例数据文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"示例数据 JSON 损坏：{path}：{exc}") from exc

    if not isinstance(dataset, dict):
        raise RuntimeError("示例数据 JSON 顶层必须是对象")
    chunks = dataset.get("chunks")
    records = dataset.get("capability_records")
    if not isinstance(chunks, list) or not chunks:
        raise RuntimeError("示例数据必须包含非空 chunks 数组")
    if not isinstance(records, list) or not records:
        raise RuntimeError("示例数据必须包含非空 capability_records 数组")

    chunks_by_id: dict[str, dict[str, Any]] = {}
    required_metadata = {
        "file_name",
        "title",
        "author",
        "teacher",
        "year",
        "page_start",
        "page_end",
    }
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            raise RuntimeError(f"第 {index} 个示例 Chunk 必须是对象")
        chunk_id = str(chunk.get("chunk_id", "")).strip()
        text = str(chunk.get("text", "")).strip()
        metadata = chunk.get("metadata")
        if not chunk_id or not text or not isinstance(metadata, dict):
            raise RuntimeError(f"第 {index} 个示例 Chunk 缺少 ID、文本或 metadata")
        if chunk_id in chunks_by_id:
            raise RuntimeError(f"示例 Chunk ID 重复：{chunk_id}")
        if not required_metadata.issubset(metadata):
            raise RuntimeError(f"示例 Chunk metadata 字段不完整：{chunk_id}")
        if not isinstance(metadata["year"], int):
            raise RuntimeError(f"示例 Chunk 年份必须是整数：{chunk_id}")
        if not isinstance(metadata["page_start"], int) or not isinstance(
            metadata["page_end"], int
        ):
            raise RuntimeError(f"示例 Chunk 页码必须是整数：{chunk_id}")
        chunks_by_id[chunk_id] = chunk

    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise RuntimeError(f"第 {index} 个能力记录必须是对象")
        source_file = f"synthetic_record_{index:02d}.json"
        validate_capability_record(record, source_file)
        for mapping in record["evidence_map"]:
            for source in mapping["sources"]:
                chunk_id = source["chunk_id"]
                if chunk_id not in chunks_by_id:
                    raise RuntimeError(f"示例能力证据引用了未知 Chunk：{chunk_id}")
                metadata = chunks_by_id[chunk_id]["metadata"]
                if metadata["file_name"] != record["paper"]["file_name"]:
                    raise RuntimeError(f"示例能力证据跨论文引用：{chunk_id}")
                if not (
                    metadata["page_start"] <= source["page_start"]
                    <= source["page_end"] <= metadata["page_end"]
                ):
                    raise RuntimeError(f"示例能力证据页码越界：{chunk_id}")

    return dataset


def ensure_empty_sample_targets(
    store: Any,
    capability_directory: Path,
    teacher_directory: Path,
) -> None:
    """Refuse to mix the public sample with any existing local research data."""
    existing_capabilities = (
        list(capability_directory.glob("*.json"))
        if capability_directory.exists()
        else []
    )
    existing_teachers = (
        list(teacher_directory.glob("*.json"))
        if teacher_directory.exists()
        else []
    )
    if store.count() or existing_capabilities or existing_teachers:
        raise RuntimeError(
            "EXISTING_DATA: 检测到现有论文向量或教师数据。"
            "为避免混入真实数据，示例安装已停止。"
        )


def install_sample_dataset(
    dataset: dict[str, Any],
    store: Any,
    embedder: Any,
    capability_directory: Path,
    teacher_directory: Path,
) -> dict[str, Any]:
    """Index synthetic chunks and generate validated local teacher profiles."""
    ensure_empty_sample_targets(store, capability_directory, teacher_directory)

    records = copy.deepcopy(dataset["capability_records"])
    for index, record in enumerate(records, start=1):
        record["_source_file"] = f"synthetic_record_{index:02d}.json"
    profiles = build_teacher_profiles(records)

    stored_count = index_chunks(
        store,
        copy.deepcopy(dataset["chunks"]),
        embedder,
        batch_size=32,
    )

    capability_directory.mkdir(parents=True, exist_ok=True)
    for record in records:
        clean_record = {key: value for key, value in record.items() if key != "_source_file"}
        output_path = capability_directory / (
            Path(record["paper"]["file_name"]).stem + ".json"
        )
        output_path.write_text(
            json.dumps(clean_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    teacher_paths = [
        save_teacher_profile(profile, teacher_directory) for profile in profiles
    ]
    return {
        "chunk_count": stored_count,
        "paper_count": len(records),
        "teacher_count": len(profiles),
        "teacher_paths": teacher_paths,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="安装完全合成、无论文版权内容的公开演示数据"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--capability-dir", type=Path, default=DEFAULT_CAPABILITY_DIRECTORY
    )
    parser.add_argument("--teacher-dir", type=Path, default=DEFAULT_TEACHER_DIRECTORY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = load_sample_dataset(args.dataset)
    print(dataset["notice_zh"])
    store = PaperVectorStore(persist_directory=args.db_path)
    ensure_empty_sample_targets(store, args.capability_dir, args.teacher_dir)
    print("正在加载本地 BGE 模型并建立示例向量库……")
    embedder = LocalEmbedder()
    result = install_sample_dataset(
        dataset,
        store,
        embedder,
        args.capability_dir,
        args.teacher_dir,
    )
    print(f"示例教师：{result['teacher_count']} 位")
    print(f"示例论文：{result['paper_count']} 篇")
    print(f"示例 Chunk：{result['chunk_count']} 条")
    print("示例数据安装完成。")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
