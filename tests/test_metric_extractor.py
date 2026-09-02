"""Tests for deterministic, evidence-located paper metric extraction."""

from __future__ import annotations

import copy
import unittest

from src.extraction.metric_extractor import (
    extract_metrics_from_chunks,
    validate_metric_extraction,
    validate_metric_record,
)


def make_chunk(text: str, *, direction: str = "x_ray_detector") -> dict:
    return {
        "chunk_id": "paper_chunk_0042",
        "text": text,
        "metadata": {
            "paper_id": "a" * 64,
            "file_name": "paper.pdf",
            "title": "测试X射线论文",
            "author": "测试作者",
            "teacher": "测试导师",
            "year": 2026,
            "direction": direction,
            "page_start": 20,
            "page_end": 20,
            "section_path": "第三章 > 性能测试",
            "section_type": "results",
        },
    }


class MetricExtractorTests(unittest.TestCase):
    def test_extracts_normalized_values_conditions_and_pages(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "本研究所设计的探测器在20 V/mm低偏压下，"
                    "灵敏度达12028 μC Gyair^{-1} cm^{-2}，"
                    "检测限低至0.48 μGyair s^{-1}。"
                )
            ]
        )
        by_id = {item["definition_id"]: item for item in result["metrics"]}
        self.assertEqual(by_id["sensitivity"]["normalized_value"], 12028.0)
        self.assertEqual(by_id["sensitivity"]["operator"], ">=")
        self.assertEqual(by_id["detection_limit"]["normalized_value"], 480.0)
        self.assertEqual(by_id["detection_limit"]["operator"], "<=")
        self.assertEqual(by_id["sensitivity"]["test_condition"], "20 V/mm低偏压")
        self.assertEqual(by_id["sensitivity"]["evidence_level"], "measured")
        self.assertEqual(by_id["sensitivity"]["evidence"]["page_start"], 20)
        self.assertEqual(result["direction_assignment"]["source"], "metadata")

    def test_imaging_metrics_use_direction_specific_ontology(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "本文所制备的闪烁体PLQY达98.32%，光产额为16994 photons/MeV，"
                    "空间分辨率达到4.4 lp mm^{-1}。",
                    direction="x_ray_imaging",
                )
            ]
        )
        definition_ids = {item["definition_id"] for item in result["metrics"]}
        self.assertEqual(
            definition_ids,
            {"plqy", "light_yield", "spatial_resolution"},
        )

    def test_literature_value_is_reported_not_measured(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "已有研究报道该探测器灵敏度为20 μC Gyair^{-1} cm^{-2}。"
                )
            ]
        )
        self.assertEqual(result["metrics"][0]["evidence_level"], "reported")

    def test_thousands_separator_is_part_of_the_number(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "本文所设计的探测器灵敏度为12,028 μC Gyair^{-1} cm^{-2}。"
                )
            ]
        )
        metric = result["metrics"][0]
        self.assertEqual(metric["raw_value"], "12,028")
        self.assertEqual(metric["normalized_value"], 12028.0)

    def test_unit_prefix_does_not_consume_a_longer_physical_unit(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "光子能量公式中普朗克常数约为4.13567 × 10^{-15} eV s。"
                )
            ]
        )
        self.assertEqual(result["metrics"], [])

    def test_distant_condition_is_not_attached_to_an_earlier_metric(self) -> None:
        result = extract_metrics_from_chunks(
            [
                make_chunk(
                    "Luo等人所设计器件的暗电流密度为0.016 nA cm^{-2}，"
                    "其后讨论了材料结构，并在另一器件作用下获得其他结果。"
                )
            ]
        )
        metric = result["metrics"][0]
        self.assertEqual(metric["evidence_level"], "reported")
        self.assertEqual(metric["test_condition"], "")

    def test_numeric_range_is_not_collapsed_into_a_negative_endpoint(self) -> None:
        result = extract_metrics_from_chunks(
            [make_chunk("本文使用的X射线光子能量为20-40 keV。")]
        )
        metric = result["metrics"][0]
        self.assertEqual(metric["definition_id"], "x_ray_energy")
        self.assertEqual(metric["value_type"], "range")
        self.assertIsNone(metric["normalized_value"])
        self.assertEqual(metric["normalized_min"], 20.0)
        self.assertEqual(metric["normalized_max"], 40.0)

    def test_rule_channel_cannot_emit_inferred_fact(self) -> None:
        result = extract_metrics_from_chunks(
            [make_chunk("本文测得响应时间为2.5 ms。")]
        )
        tampered = copy.deepcopy(result["metrics"][0])
        tampered["evidence_level"] = "inferred"
        with self.assertRaisesRegex(ValueError, "推断值"):
            validate_metric_record(tampered)

    def test_extraction_ids_are_stable_and_summary_is_validated(self) -> None:
        chunks = [make_chunk("本文测得响应时间为2.5 ms。")]
        first = extract_metrics_from_chunks(chunks)
        second = extract_metrics_from_chunks(chunks)
        self.assertEqual(
            first["metrics"][0]["metric_id"], second["metrics"][0]["metric_id"]
        )
        tampered = copy.deepcopy(first)
        tampered["summary"]["metric_count"] = 99
        with self.assertRaisesRegex(ValueError, "summary"):
            validate_metric_extraction(tampered)


if __name__ == "__main__":
    unittest.main()
