"""Aggregate per-paper capabilities into traceable teacher profiles."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "processed" / "capabilities"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "teacher_profiles"

PROFILE_FIELDS = (
    "research_directions",
    "core_capabilities",
    "representative_papers",
    "application_domains",
    "potential_industries",
)
EVIDENCE_PROFILE_FIELDS = (
    "research_directions",
    "core_capabilities",
    "application_domains",
    "potential_industries",
)

INDUSTRY_RULES: dict[str, tuple[str, ...]] = {
    "高端X射线探测与成像设备": (
        "x射线探测",
        "x 射线探测",
        "x-ray detection",
        "x-ray imaging",
        "x射线成像",
        "原理样机",
        "平板探测器",
    ),
    "医疗影像与医疗器械": ("医学成像", "医疗设备", "胸透", "medical imaging"),
    "工业无损检测": ("工业无损检测", "工业检测", "无损检测", "non-destructive"),
    "公共安全与安检": ("安全检查", "安检", "security inspection"),
    "柔性电子与可穿戴设备": ("柔性", "可穿戴", "曲面成像", "wearable"),
}


def _clean_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"字段 {field} 必须是字符串")
    return " ".join(value.split())


def _claim_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _deduplicate_sources(sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for source in sources:
        chunk_id = _clean_text(source.get("chunk_id", ""), "source.chunk_id")
        if not chunk_id:
            raise RuntimeError("证据来源缺少 chunk_id")
        page_start = source.get("page_start")
        page_end = source.get("page_end")
        if not isinstance(page_start, int) or not isinstance(page_end, int):
            raise RuntimeError(f"Chunk 页码无效：{chunk_id}")
        unique[chunk_id] = {
            "chunk_id": chunk_id,
            "page_start": page_start,
            "page_end": page_end,
        }
    return [unique[chunk_id] for chunk_id in sorted(unique)]


def validate_capability_record(record: dict[str, Any], source_file: str) -> None:
    """Validate the stage-6 fields required for teacher aggregation."""
    paper = record.get("paper")
    if not isinstance(paper, dict):
        raise RuntimeError(f"{source_file} 缺少 paper 对象")
    for field in ("file_name", "title", "author", "teacher"):
        if not _clean_text(paper.get(field, ""), f"paper.{field}"):
            raise RuntimeError(f"{source_file} 缺少 paper.{field}")
    if not isinstance(paper.get("year"), int):
        raise RuntimeError(f"{source_file} 的 paper.year 必须是整数")

    for field in (
        "research_direction",
        "core_technologies",
        "applications",
        "industry_potential",
    ):
        value = record.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RuntimeError(f"{source_file} 的 {field} 必须是字符串数组")

    evidence_map = record.get("evidence_map")
    if not isinstance(evidence_map, list):
        raise RuntimeError(f"{source_file} 的 evidence_map 必须是数组")
    evidence_keys = {
        (item.get("field"), item.get("claim"))
        for item in evidence_map
        if isinstance(item, dict) and item.get("sources")
    }
    for field in (
        "research_direction",
        "core_technologies",
        "applications",
        "industry_potential",
    ):
        for claim in record[field]:
            if (field, claim) not in evidence_keys:
                raise RuntimeError(f"{source_file} 的结论缺少证据：{field} / {claim}")


def load_capability_records(input_dir: Path) -> list[dict[str, Any]]:
    """Load and validate all stage-6 capability JSON files."""
    if not input_dir.is_dir():
        raise RuntimeError(f"能力抽取目录不存在：{input_dir}")
    records: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"JSON 文件损坏：{path}：{exc}") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"JSON 顶层必须是对象：{path}")
        validate_capability_record(record, path.name)
        record["_source_file"] = path.name
        records.append(record)
    if not records:
        raise RuntimeError(f"没有找到阶段 6 JSON：{input_dir}")
    return records


def _evidence_lookup(record: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in record["evidence_map"]:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        claim = item.get("claim")
        sources = item.get("sources")
        if isinstance(field, str) and isinstance(claim, str) and isinstance(sources, list):
            lookup[(field, claim)] = _deduplicate_sources(sources)
    return lookup


def _paper_occurrence(
    record: dict[str, Any],
    source_field: str,
    claim: str,
) -> dict[str, Any]:
    paper = record["paper"]
    sources = _evidence_lookup(record).get((source_field, claim), [])
    if not sources:
        raise RuntimeError(f"无法回溯结论：{source_field} / {claim}")
    return {
        "title": paper["title"],
        "author": paper["author"],
        "year": paper["year"],
        "source_file": record["_source_file"],
        "paper_field": source_field,
        "paper_claim": claim,
        "sources": sources,
    }


def _aggregate_entries(
    entries: Iterable[tuple[str, dict[str, Any]]],
    profile_field: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    groups: dict[str, dict[str, Any]] = {}
    for value, occurrence in entries:
        cleaned_value = _clean_text(value, profile_field)
        if not cleaned_value:
            continue
        key = _claim_key(cleaned_value)
        group = groups.setdefault(
            key,
            {"variants": Counter(), "papers": []},
        )
        group["variants"][cleaned_value] += 1
        group["papers"].append(occurrence)

    aggregated: list[dict[str, Any]] = []
    for group in groups.values():
        variants: Counter[str] = group["variants"]
        representative = sorted(
            variants,
            key=lambda item: (-variants[item], len(item), item.casefold()),
        )[0]
        papers_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for occurrence in group["papers"]:
            occurrence_key = (
                occurrence["title"],
                occurrence["paper_field"],
                occurrence["paper_claim"],
            )
            papers_by_key[occurrence_key] = occurrence
        papers = sorted(
            papers_by_key.values(),
            key=lambda item: (item["title"], item["paper_field"], item["paper_claim"]),
        )
        aggregated.append(
            {
                "profile_field": profile_field,
                "value": representative,
                "paper_count": len({paper["title"] for paper in papers}),
                "papers": papers,
            }
        )

    aggregated.sort(
        key=lambda item: (-item["paper_count"], item["value"].casefold())
    )
    return [item["value"] for item in aggregated], aggregated


def _direct_entries(
    records: Sequence[dict[str, Any]], source_field: str
) -> Iterable[tuple[str, dict[str, Any]]]:
    for record in records:
        for claim in record[source_field]:
            yield claim, _paper_occurrence(record, source_field, claim)


def _industry_entries(
    records: Sequence[dict[str, Any]],
) -> Iterable[tuple[str, dict[str, Any]]]:
    for record in records:
        for source_field in ("applications", "industry_potential"):
            for claim in record[source_field]:
                normalized_claim = unicodedata.normalize("NFKC", claim).casefold()
                for industry, keywords in INDUSTRY_RULES.items():
                    if any(keyword.casefold() in normalized_claim for keyword in keywords):
                        yield industry, _paper_occurrence(record, source_field, claim)


def build_teacher_profile(
    teacher: str,
    records: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build one deterministic teacher profile with paper-level evidence."""
    if not records:
        raise ValueError("教师画像至少需要一篇论文")
    if any(record["paper"]["teacher"] != teacher for record in records):
        raise RuntimeError("输入记录包含其他教师的论文")

    directions, direction_evidence = _aggregate_entries(
        _direct_entries(records, "research_direction"), "research_directions"
    )
    capabilities, capability_evidence = _aggregate_entries(
        _direct_entries(records, "core_technologies"), "core_capabilities"
    )
    applications, application_evidence = _aggregate_entries(
        _direct_entries(records, "applications"), "application_domains"
    )
    industries, industry_evidence = _aggregate_entries(
        _industry_entries(records), "potential_industries"
    )

    representative_papers = [
        {
            "title": record["paper"]["title"],
            "author": record["paper"]["author"],
            "year": record["paper"]["year"],
            "research_problem": record.get("research_problem", ""),
            "research_directions": record["research_direction"],
            "core_capabilities": record["core_technologies"],
            "source_file": record["_source_file"],
        }
        for record in sorted(records, key=lambda item: item["paper"]["title"])
    ]

    profile = {
        "teacher": teacher,
        "research_directions": directions,
        "core_capabilities": capabilities,
        "representative_papers": representative_papers,
        "application_domains": applications,
        "potential_industries": industries,
        "evidence_map": (
            direction_evidence
            + capability_evidence
            + application_evidence
            + industry_evidence
        ),
        "statistics": {
            "paper_count": len(records),
            "author_count": len({record["paper"]["author"] for record in records}),
            "evidence_chunk_count": len(
                {
                    source["chunk_id"]
                    for item in (
                        direction_evidence
                        + capability_evidence
                        + application_evidence
                        + industry_evidence
                    )
                    for paper in item["papers"]
                    for source in paper["sources"]
                }
            ),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation_method": "deterministic_stage6_aggregation",
    }
    validate_teacher_profile(profile)
    return profile


def validate_teacher_profile(profile: dict[str, Any]) -> None:
    """Require every profile value to have paper and Chunk/page evidence."""
    if not _clean_text(profile.get("teacher", ""), "teacher"):
        raise RuntimeError("教师姓名不能为空")
    for field in PROFILE_FIELDS:
        if not isinstance(profile.get(field), list):
            raise RuntimeError(f"画像字段 {field} 必须是数组")

    expected = {
        (field, value)
        for field in EVIDENCE_PROFILE_FIELDS
        for value in profile[field]
    }
    mappings = profile.get("evidence_map")
    if not isinstance(mappings, list):
        raise RuntimeError("画像 evidence_map 必须是数组")
    actual = {
        (item.get("profile_field"), item.get("value"))
        for item in mappings
        if isinstance(item, dict)
    }
    if actual != expected:
        raise RuntimeError("画像字段与 evidence_map 不一致")

    paper_titles = {paper["title"] for paper in profile["representative_papers"]}
    for item in mappings:
        papers = item.get("papers")
        if not isinstance(papers, list) or not papers:
            raise RuntimeError(f"画像结论缺少论文证据：{item.get('value')}")
        for paper in papers:
            if paper.get("title") not in paper_titles:
                raise RuntimeError(f"画像引用了未知论文：{paper.get('title')}")
            if not paper.get("sources"):
                raise RuntimeError(f"画像结论缺少 Chunk 证据：{item.get('value')}")
            _deduplicate_sources(paper["sources"])


def build_teacher_profiles(records: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group validated paper records by teacher and build all profiles."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["paper"]["teacher"], []).append(record)
    return [build_teacher_profile(teacher, grouped[teacher]) for teacher in sorted(grouped)]


def save_teacher_profile(profile: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{profile['teacher']}.json"
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="聚合同一教师的多篇论文科研能力")
    parser.add_argument("--teacher", help="只生成指定教师的画像")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = load_capability_records(args.input_dir)
    profiles = build_teacher_profiles(records)
    if args.teacher:
        profiles = [profile for profile in profiles if profile["teacher"] == args.teacher]
        if not profiles:
            raise RuntimeError(f"没有找到教师：{args.teacher}")

    print(f"阶段 6 能力文件：{len(records)}")
    print(f"教师数量：{len(profiles)}")
    for profile in profiles:
        output_path = save_teacher_profile(profile, args.output_dir)
        print(f"\n教师：{profile['teacher']}")
        print(f"论文：{len(profile['representative_papers'])} 篇")
        print(f"研究方向：{len(profile['research_directions'])} 项")
        print(f"核心能力：{len(profile['core_capabilities'])} 项")
        print(f"应用领域：{len(profile['application_domains'])} 项")
        print(f"潜在产业：{len(profile['potential_industries'])} 项")
        print(f"证据 Chunk：{profile['statistics']['evidence_chunk_count']} 个")
        print(f"已保存：{output_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
