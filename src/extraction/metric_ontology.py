"""Versioned metric ontology and conservative unit normalization."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ONTOLOGY_PATH = PROJECT_ROOT / "config" / "metric_ontology.json"
ONTOLOGY_SCHEMA = "metric_ontology_v1"
METRIC_SCOPES = frozenset({"general", "direction", "device_process"})
EVIDENCE_LEVELS = frozenset({"measured", "reported", "inferred"})


def normalize_unit_key(value: str) -> str:
    """Collapse typographic variants without changing dimensional meaning."""
    text = str(value).strip().casefold()
    replacements = {
        "μ": "u",
        "µ": "u",
        "−": "-",
        "–": "-",
        "ₐᵢᵣ": "air",
        "⁻¹": "^-1",
        "⁻²": "^-2",
        "⁻³": "^-3",
        "²": "^2",
        "³": "^3",
        "ω": "ohm",
        "Ω": "ohm",
        "·": "",
        "⋅": "",
        "_": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\^\{([+-]?\d+)\}", r"^\1", text)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", "", text)


class MetricOntology:
    """Validated lookup object for metric aliases and unit conversions."""

    def __init__(self, payload: dict[str, Any]) -> None:
        if payload.get("schema_version") != ONTOLOGY_SCHEMA:
            raise ValueError("指标 ontology schema 不受支持")
        if set(payload.get("evidence_levels", [])) != EVIDENCE_LEVELS:
            raise ValueError("指标 ontology 的 evidence_levels 不完整")
        metrics = payload.get("metrics")
        if not isinstance(metrics, list) or not metrics:
            raise ValueError("指标 ontology 缺少 metrics")
        self.schema_version = payload["schema_version"]
        self.metrics: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self._unit_lookup: dict[str, dict[str, dict[str, Any]]] = {}
        for definition in metrics:
            required = {
                "metric_id",
                "canonical_name",
                "scope",
                "directions",
                "aliases",
                "canonical_unit",
                "units",
            }
            if not isinstance(definition, dict) or not required.issubset(definition):
                raise ValueError("指标定义字段不完整")
            metric_id = str(definition["metric_id"]).strip()
            if not metric_id or metric_id in self.by_id:
                raise ValueError("指标 ID 为空或重复")
            if definition["scope"] not in METRIC_SCOPES:
                raise ValueError(f"指标 {metric_id} scope 无效")
            if not isinstance(definition["aliases"], list) or not definition["aliases"]:
                raise ValueError(f"指标 {metric_id} 缺少 aliases")
            unit_lookup: dict[str, dict[str, Any]] = {}
            canonical_seen = False
            for unit in definition["units"]:
                if not isinstance(unit, dict) or not {
                    "symbol",
                    "aliases",
                    "scale",
                }.issubset(unit):
                    raise ValueError(f"指标 {metric_id} unit 字段不完整")
                scale = float(unit["scale"])
                offset = float(unit.get("offset", 0.0))
                if scale <= 0:
                    raise ValueError(f"指标 {metric_id} unit scale 必须大于 0")
                if unit["symbol"] == definition["canonical_unit"]:
                    canonical_seen = True
                for alias in [unit["symbol"], *unit["aliases"]]:
                    key = normalize_unit_key(alias)
                    normalized = {
                        "symbol": unit["symbol"],
                        "scale": scale,
                        "offset": offset,
                    }
                    existing = unit_lookup.get(key)
                    if existing and existing != normalized:
                        raise ValueError(f"指标 {metric_id} 的单位别名冲突：{alias}")
                    unit_lookup[key] = normalized
            if not canonical_seen:
                raise ValueError(f"指标 {metric_id} 缺少规范单位定义")
            cleaned = dict(definition)
            self.metrics.append(cleaned)
            self.by_id[metric_id] = cleaned
            self._unit_lookup[metric_id] = unit_lookup

    @classmethod
    def from_path(cls, path: Path = DEFAULT_ONTOLOGY_PATH) -> "MetricOntology":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def definitions_for_direction(self, direction_id: str) -> list[dict[str, Any]]:
        return [
            definition
            for definition in self.metrics
            if not definition["directions"]
            or direction_id == "unclassified"
            or direction_id in definition["directions"]
        ]

    def normalize_value(
        self, metric_id: str, value: float, raw_unit: str
    ) -> dict[str, Any]:
        if metric_id not in self.by_id:
            raise KeyError(f"未知指标：{metric_id}")
        unit = self._unit_lookup[metric_id].get(normalize_unit_key(raw_unit))
        if unit is None:
            raise ValueError(f"指标 {metric_id} 不支持单位：{raw_unit}")
        normalized_value = float(value) * unit["scale"] + unit["offset"]
        return {
            "normalized_value": normalized_value,
            "canonical_unit": self.by_id[metric_id]["canonical_unit"],
            "source_unit": raw_unit,
            "conversion": {
                "scale": unit["scale"],
                "offset": unit["offset"],
            },
        }


def comparable_metrics(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Require the same metric/unit and an explicit identical test condition."""
    left_condition = " ".join(str(left.get("test_condition", "")).split()).casefold()
    right_condition = " ".join(str(right.get("test_condition", "")).split()).casefold()
    return bool(
        left.get("definition_id") == right.get("definition_id")
        and left.get("canonical_unit") == right.get("canonical_unit")
        and left_condition
        and left_condition == right_condition
    )
