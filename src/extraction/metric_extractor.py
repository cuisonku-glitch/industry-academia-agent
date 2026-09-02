"""Rule-first extraction of traceable quantitative paper metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:
    from .direction_classifier import (
        classify_paper_direction,
        load_direction_taxonomy,
        validate_direction_assignment,
    )
    from .metric_ontology import EVIDENCE_LEVELS, MetricOntology
    from ..retrieval.vector_store import PaperVectorStore
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.extraction.direction_classifier import (
        classify_paper_direction,
        load_direction_taxonomy,
        validate_direction_assignment,
    )
    from src.extraction.metric_ontology import EVIDENCE_LEVELS, MetricOntology
    from src.retrieval.vector_store import PaperVectorStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "processed" / "metrics"
EXTRACTION_SCHEMA = "paper_metric_extraction_v1"
RECORD_SCHEMA = "paper_metric_record_v1"
ALLOWED_OPERATORS = frozenset({"=", "≈", ">=", "<=", ">", "<"})

NUMBER_ATOM = (
    r"(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)"
    r"(?:\s*(?:×|x|X)\s*10\s*(?:\^)?\{?[+-]?\d+\}?)?"
)
NUMBER_PATTERN = rf"{NUMBER_ATOM}(?:\s*(?:~|～|至|—|–|-)\s*{NUMBER_ATOM})?"
OPERATOR_PATTERN = (
    r"(?P<operator>不低于|不少于|至少|高达|达到|达|"
    r"不超过|不高于|至多|低至|约为|约|为|≥|≤|>|<|=)?"
)
OPERATOR_MAP = {
    "不低于": ">=",
    "不少于": ">=",
    "至少": ">=",
    "高达": ">=",
    "达到": ">=",
    "达": ">=",
    "≥": ">=",
    "不超过": "<=",
    "不高于": "<=",
    "至多": "<=",
    "低至": "<=",
    "≤": "<=",
    "约为": "≈",
    "约": "≈",
    "为": "=",
    "=": "=",
    ">": ">",
    "<": "<",
    None: "=",
    "": "=",
}

REPORTED_MARKERS = (
    "据报道",
    "文献报道",
    "已有研究",
    "等人报道",
    "等人",
    "商用探测器",
    "目前已报道",
)
MEASURED_MARKERS = (
    "本研究",
    "本工作",
    "本文",
    "实验结果",
    "测试结果",
    "测得",
    "实测",
    "所制备",
    "所研制",
    "所设计",
    "我们",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flexible_literal(value: str) -> str:
    escaped = re.escape(value.strip())
    return re.sub(r"(?:\\\s)+", r"\\s*", escaped)


def _parse_number_atom(value: str) -> float:
    text = value.replace("−", "-").replace(" ", "").replace(",", "")
    scientific = re.fullmatch(
        r"([+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:[×xX]10(?:\^)?\{?([+-]?\d+)\}?)?",
        text,
    )
    if not scientific:
        raise ValueError(f"无法解析数值：{value}")
    base = float(scientific.group(1))
    exponent = int(scientific.group(2) or 0)
    return base * (10**exponent)


def _parse_numeric_values(value: str) -> list[float]:
    match = re.fullmatch(
        rf"(?P<first>{NUMBER_ATOM})(?:\s*(?:~|～|至|—|–|-)\s*"
        rf"(?P<second>{NUMBER_ATOM}))?",
        value.strip(),
    )
    if not match:
        raise ValueError(f"无法解析数值或范围：{value}")
    values = [_parse_number_atom(match.group("first"))]
    if match.group("second"):
        values.append(_parse_number_atom(match.group("second")))
    if any(item < 0 for item in values):
        raise ValueError("当前指标 ontology 只接受非负物理量")
    return sorted(values)


def _sentences(text: str) -> list[str]:
    return [
        " ".join(item.split())
        for item in re.split(r"(?<=[。！？；;])", str(text))
        if item.strip()
    ]


def _extract_test_condition(sentence: str, metric_start: int, metric_end: int) -> str:
    before = sentence[max(0, metric_start - 100) : metric_start]
    after = sentence[metric_end : metric_end + 80]
    for text, patterns in (
        (
            before,
            (
                r"(?:在|于)([^，。；]{1,60}?)(?:条件)?下[，,\s]*$",
                r"当([^，。；]{1,60}?)时[，,\s]*$",
            ),
        ),
        (
            after,
            (
                r"^[，,\s]*(?:在|于)([^，。；]{1,50}?)(?:条件)?下",
                r"^[，,\s]*当([^，。；]{1,50}?)时",
            ),
        ),
    ):
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return " ".join(match.group(1).split())
    return ""


def _evidence_level(sentence: str, section_type: str) -> str:
    if section_type == "reference" or any(
        marker in sentence for marker in REPORTED_MARKERS
    ):
        return "reported"
    if any(marker in sentence for marker in MEASURED_MARKERS):
        return "measured"
    return "reported"


def validate_metric_record(record: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "metric_id",
        "definition_id",
        "canonical_name",
        "scope",
        "raw_name",
        "raw_value",
        "raw_unit",
        "value_type",
        "normalized_value",
        "normalized_min",
        "normalized_max",
        "canonical_unit",
        "operator",
        "test_condition",
        "evidence_level",
        "extraction_channel",
        "evidence",
    }
    if not required.issubset(record):
        raise ValueError("指标记录字段不完整")
    if record["schema_version"] != RECORD_SCHEMA:
        raise ValueError("指标记录 schema 不受支持")
    if record["evidence_level"] not in EVIDENCE_LEVELS:
        raise ValueError("指标记录 evidence_level 无效")
    if record["operator"] not in ALLOWED_OPERATORS:
        raise ValueError("指标记录 operator 无效")
    if record["value_type"] not in {"point", "range"}:
        raise ValueError("指标记录 value_type 无效")
    if record["value_type"] == "point" and record["normalized_value"] is None:
        raise ValueError("点值指标缺少 normalized_value")
    if record["value_type"] == "range" and record["normalized_value"] is not None:
        raise ValueError("范围指标不能伪装成单点 normalized_value")
    if record["extraction_channel"] not in {"deterministic_rule", "kimi_supplement"}:
        raise ValueError("指标记录 extraction_channel 无效")
    evidence = record["evidence"]
    if not isinstance(evidence, dict) or not {
        "chunk_id",
        "page_start",
        "page_end",
        "quote",
    }.issubset(evidence):
        raise ValueError("指标记录缺少可定位证据")
    if str(record["raw_name"]).casefold() not in evidence["quote"].casefold():
        raise ValueError("指标名称不在证据原文中")
    if str(record["raw_value"]).replace(" ", "") not in evidence["quote"].replace(
        " ", ""
    ):
        raise ValueError("指标数值不在证据原文中")
    if record["evidence_level"] == "inferred" and record["extraction_channel"] == "deterministic_rule":
        raise ValueError("规则抽取不能把推断值标记为事实")


def validate_metric_extraction(result: dict[str, Any]) -> None:
    if result.get("schema_version") != EXTRACTION_SCHEMA:
        raise ValueError("论文指标抽取 schema 不受支持")
    if result.get("ontology_version") != "metric_ontology_v1":
        raise ValueError("论文指标抽取 ontology_version 不受支持")
    if not isinstance(result.get("paper"), dict):
        raise ValueError("论文指标抽取缺少 paper")
    validate_direction_assignment(
        result.get("direction_assignment", {}), load_direction_taxonomy()
    )
    metrics = result.get("metrics")
    if not isinstance(metrics, list):
        raise ValueError("论文指标抽取 metrics 必须是数组")
    for record in metrics:
        validate_metric_record(record)
    metric_ids = [record["metric_id"] for record in metrics]
    if len(metric_ids) != len(set(metric_ids)):
        raise ValueError("论文指标抽取包含重复 metric_id")
    summary = result.get("summary", {})
    expected = {
        "metric_count": len(metrics),
        "measured_count": sum(
            item["evidence_level"] == "measured" for item in metrics
        ),
        "reported_count": sum(
            item["evidence_level"] == "reported" for item in metrics
        ),
        "inferred_count": sum(
            item["evidence_level"] == "inferred" for item in metrics
        ),
        "missing_test_condition_count": sum(
            not item["test_condition"] for item in metrics
        ),
    }
    if summary != expected:
        raise ValueError("论文指标抽取 summary 与记录不一致")


def _definition_pattern(definition: dict[str, Any]) -> re.Pattern[str]:
    aliases = "|".join(
        _flexible_literal(value)
        for value in sorted(definition["aliases"], key=len, reverse=True)
    )
    unit_values = {
        value
        for unit in definition["units"]
        for value in [unit["symbol"], *unit["aliases"]]
    }
    units = "|".join(
        _flexible_literal(value)
        for value in sorted(unit_values, key=len, reverse=True)
    )
    return re.compile(
        rf"(?P<raw_name>{aliases})[^。！？；;\n]{{0,36}}?"
        rf"{OPERATOR_PATTERN}\s*(?P<raw_value>{NUMBER_PATTERN})\s*"
        rf"(?P<raw_unit>{units})(?!\s*(?:[A-Za-zμµΩ]|[\^/{{}}]))",
        flags=re.IGNORECASE,
    )


def extract_metrics_from_chunks(
    chunks: Sequence[dict[str, Any]],
    *,
    ontology: MetricOntology | None = None,
    direction_assignment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not chunks:
        raise ValueError("指标抽取至少需要一个 Chunk")
    ontology = ontology or MetricOntology.from_path()
    first_metadata = chunks[0].get("metadata", {})
    paper = {
        "paper_id": first_metadata.get("paper_id", ""),
        "file_name": first_metadata.get("file_name", ""),
        "title": first_metadata.get("title", ""),
        "author": first_metadata.get("author", ""),
        "teacher": first_metadata.get("teacher", ""),
        "year": first_metadata.get("year"),
    }
    if direction_assignment is None:
        direction_assignment = classify_paper_direction(
            first_metadata,
            "\n".join(chunk.get("text", "") for chunk in chunks[:20]),
        )
    definitions = ontology.definitions_for_direction(
        direction_assignment["direction_id"]
    )
    records: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for definition in definitions:
        pattern = _definition_pattern(definition)
        for chunk in chunks:
            metadata = chunk.get("metadata", {})
            for sentence in _sentences(chunk.get("text", "")):
                for match in pattern.finditer(sentence):
                    raw_value = match.group("raw_value")
                    raw_unit = match.group("raw_unit")
                    numeric_values = _parse_numeric_values(raw_value)
                    normalized_values = [
                        ontology.normalize_value(
                            definition["metric_id"], value, raw_unit
                        )
                        for value in numeric_values
                    ]
                    normalized = normalized_values[0]
                    value_type = "range" if len(normalized_values) == 2 else "point"
                    normalized_min = normalized_values[0]["normalized_value"]
                    normalized_max = normalized_values[-1]["normalized_value"]
                    normalized_value = (
                        normalized_min if value_type == "point" else None
                    )
                    identity = (
                        chunk["chunk_id"],
                        definition["metric_id"],
                        round(normalized_min, 12),
                        round(normalized_max, 12),
                        normalized["canonical_unit"],
                    )
                    if identity in seen:
                        continue
                    seen.add(identity)
                    stable_identity = json.dumps(
                        [
                            paper.get("paper_id") or paper.get("file_name"),
                            chunk["chunk_id"],
                            definition["metric_id"],
                            raw_value,
                            raw_unit,
                            normalized_min,
                            normalized_max,
                        ],
                        ensure_ascii=False,
                    )
                    record = {
                        "schema_version": RECORD_SCHEMA,
                        "metric_id": "MET-"
                        + hashlib.sha256(stable_identity.encode("utf-8")).hexdigest()[:16],
                        "definition_id": definition["metric_id"],
                        "canonical_name": definition["canonical_name"],
                        "scope": definition["scope"],
                        "raw_name": match.group("raw_name"),
                        "raw_value": raw_value,
                        "raw_unit": raw_unit,
                        "value_type": value_type,
                        "normalized_value": normalized_value,
                        "normalized_min": normalized_min,
                        "normalized_max": normalized_max,
                        "canonical_unit": normalized["canonical_unit"],
                        "source_unit": normalized["source_unit"],
                        "conversion": normalized["conversion"],
                        "operator": OPERATOR_MAP[match.group("operator")],
                        "test_condition": _extract_test_condition(
                            sentence, match.start(), match.end()
                        ),
                        "evidence_level": _evidence_level(
                            sentence, str(metadata.get("section_type", "unknown"))
                        ),
                        "extraction_channel": "deterministic_rule",
                        "evidence": {
                            "chunk_id": chunk["chunk_id"],
                            "page_start": metadata.get("page_start"),
                            "page_end": metadata.get("page_end"),
                            "section_path": metadata.get("section_path", ""),
                            "section_type": metadata.get("section_type", "unknown"),
                            "quote": sentence,
                        },
                    }
                    validate_metric_record(record)
                    records.append(record)
    result = {
        "schema_version": EXTRACTION_SCHEMA,
        "ontology_version": ontology.schema_version,
        "paper": paper,
        "direction_assignment": direction_assignment,
        "metrics": records,
        "summary": {
            "metric_count": len(records),
            "measured_count": sum(
                item["evidence_level"] == "measured" for item in records
            ),
            "reported_count": sum(
                item["evidence_level"] == "reported" for item in records
            ),
            "inferred_count": sum(
                item["evidence_level"] == "inferred" for item in records
            ),
            "missing_test_condition_count": sum(
                not item["test_condition"] for item in records
            ),
        },
        "extracted_at": _utc_now(),
    }
    validate_metric_extraction(result)
    return result


def save_metric_extraction(result: dict[str, Any], output_dir: Path) -> Path:
    validate_metric_extraction(result)
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = str(result["paper"].get("file_name", "paper.pdf"))
    safe_stem = Path(file_name).name.removesuffix(Path(file_name).suffix) or "paper"
    output_path = output_dir / f"{safe_stem}.metrics.json"
    temporary_path = output_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从本地论文 Chunk 规则抽取可追溯性能指标"
    )
    parser.add_argument("--paper", help="只处理题名或文件名包含该文字的论文")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="只打印统计，不保存本地指标 JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with PaperVectorStore() as store:
        papers = store.list_papers()
        if args.paper:
            keyword = args.paper.casefold()
            papers = [
                paper
                for paper in papers
                if keyword in str(paper["title"]).casefold()
                or keyword in str(paper["file_name"]).casefold()
            ]
        if not papers:
            raise RuntimeError("没有找到待抽取的本地论文")
        print(f"本地论文：{len(papers)} 篇｜向量 Chunk：{store.count()}")
        for paper in papers:
            chunks = store.get_chunks(where={"file_name": paper["file_name"]})
            result = extract_metrics_from_chunks(chunks)
            assignment = result["direction_assignment"]
            print(
                f"- 《{paper['title']}》｜{assignment['direction_id']} "
                f"({assignment['source']}, {assignment['confidence']:.2f})｜"
                f"指标 {result['summary']['metric_count']} 项"
            )
            if not args.preview_only:
                print(f"  已保存：{save_metric_extraction(result, args.output_dir)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
