"""Parse enterprise product language into a traceable technical need profile."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "enterprise_needs" / "enterprise_need.json"
)
DEFAULT_REQUEST = """我们开发工业 X 射线探伤设备，
现在希望寻找低成本、高灵敏度的探测材料，
最好可以进行大面积制备。"""

INDUSTRY_RULES: dict[str, tuple[str, ...]] = {
    "工业检测": ("工业", "探伤", "无损检测", "缺陷检测"),
    "医疗影像": ("医学成像", "医疗影像", "医疗设备", "放射诊断"),
    "公共安全": ("安检", "安全检查", "公共安全"),
    "科研仪器": ("科学仪器", "实验仪器", "科研设备"),
}

PRODUCT_TERMS = (
    "X射线探伤设备",
    "X 射线探伤设备",
    "X射线成像设备",
    "X 射线成像设备",
    "X射线探测器",
    "X 射线探测器",
    "平板探测器",
    "成像系统",
    "探测材料",
)

TECHNICAL_PROBLEM_RULES: dict[str, tuple[str, ...]] = {
    "现有探测灵敏度不足": ("灵敏度不足", "灵敏度低", "探测能力不足"),
    "材料或制备成本偏高": ("成本过高", "成本高", "降低成本"),
    "大面积制备能力不足": ("难以大面积", "无法大面积", "面积受限"),
    "器件稳定性不足": ("稳定性不足", "容易衰减", "基线漂移", "寿命短"),
    "成像分辨率不足": ("分辨率不足", "分辨率低", "图像模糊"),
}

CAPABILITY_RULES: dict[str, tuple[str, ...]] = {
    "高灵敏度X射线探测": ("高灵敏度", "提升灵敏度", "灵敏探测"),
    "低成本材料": ("低成本", "成本可控", "降低材料成本"),
    "大面积制备": ("大面积制备", "大尺寸制备", "规模化制备"),
    "高分辨率X射线成像": ("高分辨率", "提高分辨率", "精细成像"),
    "低电压或自驱动探测": ("低电压", "低偏压", "自驱动", "无外加偏压"),
    "高稳定性探测器": ("高稳定性", "长期稳定", "降低基线漂移"),
    "柔性或曲面成像": ("柔性", "曲面成像", "可穿戴"),
    "快速响应探测": ("快速响应", "实时成像", "高速探测"),
}

PREFERENCE_RULES: dict[str, tuple[str, ...]] = {
    "优先支持大面积制备": (
        "最好可以进行大面积制备",
        "最好能够大面积制备",
        "优先大面积制备",
    ),
    "优先采用低成本方案": ("最好低成本", "优先低成本", "成本优先"),
    "优先具备柔性适配能力": ("最好具有柔性", "优先柔性", "最好适配曲面"),
}

KEYWORD_RULES: dict[str, tuple[str, ...]] = {
    "X射线": ("x射线", "x 射线", "x-ray"),
    "工业探伤": ("工业探伤", "工业 x 射线探伤", "探伤"),
    "探测材料": ("探测材料", "探测器材料"),
    "低成本": ("低成本", "降低成本"),
    "高灵敏度": ("高灵敏度", "提升灵敏度"),
    "大面积制备": ("大面积制备", "大尺寸制备", "规模化制备"),
    "高分辨率": ("高分辨率", "提高分辨率"),
    "低电压": ("低电压", "低偏压"),
    "自驱动": ("自驱动", "无外加偏压"),
    "柔性成像": ("柔性", "曲面成像", "可穿戴"),
}

PROFILE_LIST_FIELDS = (
    "technical_problems",
    "required_capabilities",
    "constraints",
    "existing_foundations",
    "excluded_approaches",
    "keywords",
)

TARGET_METRIC_NAMES = (
    "灵敏度",
    "检测限",
    "分辨率",
    "成本",
    "面积",
    "尺寸",
    "厚度",
    "电压",
    "功耗",
    "响应时间",
    "温度",
    "良率",
    "寿命",
    "稳定性",
)

METRIC_OPERATOR_MAP = {
    "不超过": "<=",
    "低于": "<",
    "小于": "<",
    "以内": "<=",
    "以下": "<=",
    "至多": "<=",
    "不低于": ">=",
    "高于": ">",
    "大于": ">",
    "至少": ">=",
    "以上": ">=",
    "达到": ">=",
    "≤": "<=",
    "<": "<",
    "≥": ">=",
    ">": ">",
}

FOUNDATION_MARKERS = ("已有", "已经具备", "现有", "目前具备", "现有设备", "已有样机")
EXCLUSION_MARKERS = ("不采用", "不能使用", "不得使用", "排除", "避免使用", "禁止使用")


def normalize_request(text: str) -> str:
    """Normalize spacing while preserving the user's wording and punctuation."""
    normalized = re.sub(r"[ \t\u3000]+", " ", text.strip())
    normalized = re.sub(r"\s*\n\s*", "\n", normalized)
    if not normalized:
        raise ValueError("企业需求不能为空")
    return normalized


def _find_phrases(text: str, patterns: Iterable[str]) -> list[str]:
    lowered = text.casefold()
    return [pattern for pattern in patterns if pattern.casefold() in lowered]


def _append_evidence(
    evidence_map: list[dict[str, Any]],
    field: str,
    value: str,
    phrases: Iterable[str],
) -> None:
    unique_phrases = list(dict.fromkeys(phrase for phrase in phrases if phrase))
    if unique_phrases:
        evidence_map.append(
            {"field": field, "value": value, "matched_phrases": unique_phrases}
        )


def _match_list_rules(
    text: str,
    field: str,
    rules: dict[str, tuple[str, ...]],
    evidence_map: list[dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    for value, patterns in rules.items():
        phrases = _find_phrases(text, patterns)
        if phrases:
            values.append(value)
            _append_evidence(evidence_map, field, value, phrases)
    return values


def _detect_industry(text: str, evidence_map: list[dict[str, Any]]) -> str:
    scored: list[tuple[int, str, list[str]]] = []
    for industry, patterns in INDUSTRY_RULES.items():
        phrases = _find_phrases(text, patterns)
        if phrases:
            scored.append((len(phrases), industry, phrases))
    if not scored:
        return "未明确"
    _, industry, phrases = sorted(scored, key=lambda item: (-item[0], item[1]))[0]
    _append_evidence(evidence_map, "industry", industry, phrases)
    return industry


def _detect_product(text: str, evidence_map: list[dict[str, Any]]) -> str:
    for term in PRODUCT_TERMS:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if match:
            product = "".join(match.group(0).split())
            _append_evidence(evidence_map, "product", product, [match.group(0)])
            return product

    product_match = re.search(
        r"(?:开发|研制|生产|制造|提供)([^，。；\n]{2,40}?(?:设备|系统|装置|产品|材料|器件))",
        text,
    )
    if product_match:
        product = product_match.group(1).strip()
        _append_evidence(evidence_map, "product", product, [product_match.group(0)])
        return product
    return "未明确"


def _detect_constraints(text: str, evidence_map: list[dict[str, Any]]) -> list[str]:
    constraints = _match_list_rules(
        text, "constraints", PREFERENCE_RULES, evidence_map
    )
    numeric_pattern = re.compile(
        r"(?:成本|温度|尺寸|厚度|电压|功耗|检测限|灵敏度)"
        r"[^，。；\n]{0,20}?(?:不超过|低于|高于|至少|以内|以下|以上)"
        r"[^，。；\n]{1,20}"
    )
    for match in numeric_pattern.finditer(text):
        value = match.group(0).strip()
        if value not in constraints:
            constraints.append(value)
            _append_evidence(evidence_map, "constraints", value, [value])
    return constraints


def _split_clauses(text: str) -> list[str]:
    return [
        clause.strip(" ，。；;\n")
        for clause in re.split(r"[，。；;\n]+", text)
        if clause.strip(" ，。；;\n")
    ]


def _detect_marked_clauses(
    text: str,
    field: str,
    markers: Iterable[str],
    evidence_map: list[dict[str, Any]],
) -> list[str]:
    values: list[str] = []
    for clause in _split_clauses(text):
        if any(marker.casefold() in clause.casefold() for marker in markers):
            values.append(clause)
            _append_evidence(evidence_map, field, clause, [clause])
    return list(dict.fromkeys(values))


def _detect_target_metrics(
    text: str, evidence_map: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract explicit numeric targets without inventing units or test conditions."""
    metric_names = "|".join(map(re.escape, TARGET_METRIC_NAMES))
    operators = "|".join(
        map(re.escape, sorted(METRIC_OPERATOR_MAP, key=len, reverse=True))
    )
    pattern = re.compile(
        rf"(?P<name>{metric_names})"
        rf"(?P<context>[^，。；;\n]{{0,16}}?)"
        rf"(?P<operator>{operators})\s*"
        rf"(?P<value>\d+(?:\.\d+)?(?:\s*[×xX]\s*10\s*(?:\^\s*)?[-−]?\d+)?)"
        rf"\s*(?P<unit>[^，。；;\n]{{0,24}})"
    )
    test_conditions = [
        match.group(0).strip()
        for match in re.finditer(r"在[^，。；;\n]{1,40}(?:下|条件下)(?:测试|测量)?", text)
    ]
    metrics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, match in enumerate(pattern.finditer(text), start=1):
        raw_text = match.group(0).strip()
        unit = match.group("unit").strip()
        # A trailing action phrase is not a unit. Keep the original text, but leave
        # the normalized unit empty instead of pretending to understand it.
        if re.search(r"(?:测试|测量|验证|实现|制备)$", unit):
            unit = ""
        identity = "".join(raw_text.casefold().split())
        if identity in seen:
            continue
        seen.add(identity)
        metric = {
            "metric_id": f"TM{index:02d}",
            "name": match.group("name"),
            "operator": METRIC_OPERATOR_MAP[match.group("operator")],
            "value_text": match.group("value").replace("−", "-"),
            "unit": unit,
            "test_condition": "；".join(test_conditions),
            "raw_text": raw_text,
            "source_type": "enterprise_confirmed",
        }
        metrics.append(metric)
        _append_evidence(
            evidence_map,
            "target_metrics",
            raw_text,
            [raw_text, *test_conditions],
        )
    return metrics


def _find_unparsed_fragments(
    text: str, evidence_map: list[dict[str, Any]]
) -> list[str]:
    matched_phrases = [
        str(phrase).casefold()
        for item in evidence_map
        for phrase in item.get("matched_phrases", [])
    ]
    return [
        clause
        for clause in _split_clauses(text)
        if not any(phrase in clause.casefold() for phrase in matched_phrases)
    ]


def validate_enterprise_profile(profile: dict[str, Any]) -> None:
    """Require all parsed values to be grounded in original request phrases."""
    original_request = profile.get("original_request")
    if not isinstance(original_request, str) or not original_request.strip():
        raise RuntimeError("企业画像缺少 original_request")
    for field in ("industry", "product"):
        if not isinstance(profile.get(field), str) or not profile[field]:
            raise RuntimeError(f"企业画像字段 {field} 必须是非空字符串")
    for field in PROFILE_LIST_FIELDS:
        value = profile.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise RuntimeError(f"企业画像字段 {field} 必须是字符串数组")
    target_metrics = profile.get("target_metrics")
    if not isinstance(target_metrics, list):
        raise RuntimeError("企业画像 target_metrics 必须是数组")
    required_metric_fields = {
        "metric_id",
        "name",
        "operator",
        "value_text",
        "unit",
        "test_condition",
        "raw_text",
        "source_type",
    }
    for metric in target_metrics:
        if not isinstance(metric, dict) or not required_metric_fields.issubset(metric):
            raise RuntimeError("企业画像 target_metrics 字段不完整")
        if metric["source_type"] != "enterprise_confirmed":
            raise RuntimeError("企业目标指标必须标记为 enterprise_confirmed")
        if metric["raw_text"].casefold() not in original_request.casefold():
            raise RuntimeError("企业目标指标缺少原文依据")
    unparsed = profile.get("unparsed_fragments")
    if not isinstance(unparsed, list) or any(
        not isinstance(item, str) for item in unparsed
    ):
        raise RuntimeError("企业画像 unparsed_fragments 必须是字符串数组")

    expected = {
        (field, profile[field])
        for field in ("industry", "product")
        if profile[field] != "未明确"
    }
    expected.update(
        (field, value)
        for field in PROFILE_LIST_FIELDS
        for value in profile[field]
    )
    expected.update(
        ("target_metrics", metric["raw_text"]) for metric in target_metrics
    )
    evidence_map = profile.get("evidence_map")
    if not isinstance(evidence_map, list):
        raise RuntimeError("企业画像 evidence_map 必须是数组")
    actual = {
        (item.get("field"), item.get("value"))
        for item in evidence_map
        if isinstance(item, dict)
    }
    if expected != actual:
        raise RuntimeError("企业需求字段与 evidence_map 不一致")
    for item in evidence_map:
        phrases = item.get("matched_phrases")
        if not isinstance(phrases, list) or not phrases:
            raise RuntimeError(f"企业需求字段缺少原文证据：{item.get('value')}")
        if any(phrase.casefold() not in original_request.casefold() for phrase in phrases):
            raise RuntimeError(f"企业需求引用了不存在的原文短语：{item.get('value')}")


def parse_enterprise_need(text: str) -> dict[str, Any]:
    """Build a deterministic enterprise need profile from product language."""
    normalized = normalize_request(text)
    evidence_map: list[dict[str, Any]] = []
    target_metrics = _detect_target_metrics(normalized, evidence_map)
    existing_foundations = _detect_marked_clauses(
        normalized,
        "existing_foundations",
        FOUNDATION_MARKERS,
        evidence_map,
    )
    excluded_approaches = _detect_marked_clauses(
        normalized,
        "excluded_approaches",
        EXCLUSION_MARKERS,
        evidence_map,
    )
    profile = {
        "industry": _detect_industry(normalized, evidence_map),
        "product": _detect_product(normalized, evidence_map),
        "technical_problems": _match_list_rules(
            normalized,
            "technical_problems",
            TECHNICAL_PROBLEM_RULES,
            evidence_map,
        ),
        "required_capabilities": _match_list_rules(
            normalized,
            "required_capabilities",
            CAPABILITY_RULES,
            evidence_map,
        ),
        "constraints": _detect_constraints(normalized, evidence_map),
        "target_metrics": target_metrics,
        "existing_foundations": existing_foundations,
        "excluded_approaches": excluded_approaches,
        "keywords": _match_list_rules(
            normalized, "keywords", KEYWORD_RULES, evidence_map
        ),
        "original_request": normalized,
        "evidence_map": evidence_map,
        "unparsed_fragments": _find_unparsed_fragments(normalized, evidence_map),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "parser": "deterministic_product_to_research_v2",
    }
    validate_enterprise_profile(profile)
    return profile


def save_enterprise_profile(profile: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把企业产品语言解析为科研需求画像")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--text", help="企业需求文本")
    source_group.add_argument("--input-file", type=Path, help="UTF-8 企业需求文本文件")
    source_group.add_argument(
        "--demo",
        action="store_true",
        help="显式使用操作指南中的 X 射线探伤示例",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.demo:
        request_text = DEFAULT_REQUEST
    elif args.input_file:
        request_text = args.input_file.read_text(encoding="utf-8")
    else:
        request_text = args.text

    profile = parse_enterprise_need(request_text)
    output_path = save_enterprise_profile(profile, args.output)
    print("企业需求：")
    print(profile["original_request"])
    print("\n解析结果：")
    print(json.dumps({key: profile[key] for key in (
        "industry",
        "product",
        "technical_problems",
        "required_capabilities",
        "constraints",
        "keywords",
    )}, ensure_ascii=False, indent=2))
    print(f"\n证据映射：{len(profile['evidence_map'])} 项")
    print(f"已保存：{output_path}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
