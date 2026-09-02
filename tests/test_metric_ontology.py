"""Tests for metric definitions, unit conversions, and comparison safety."""

from __future__ import annotations

import unittest

from src.extraction.metric_ontology import (
    MetricOntology,
    comparable_metrics,
    normalize_unit_key,
)


class MetricOntologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ontology = MetricOntology.from_path()

    def test_typographic_unit_variants_share_one_key(self) -> None:
        self.assertEqual(
            normalize_unit_key("μC Gyair^{−1} cm^{−2}"),
            normalize_unit_key("µC Gyair^-1 cm^-2"),
        )

    def test_sensitivity_and_dose_rate_units_are_normalized(self) -> None:
        sensitivity = self.ontology.normalize_value(
            "sensitivity", 12.0, "mC Gyair^{-1} cm^{-2}"
        )
        detection_limit = self.ontology.normalize_value(
            "detection_limit", 0.5, "μGyair s^{-1}"
        )
        self.assertEqual(sensitivity["normalized_value"], 12000.0)
        self.assertEqual(sensitivity["canonical_unit"], "μC Gy_air^{-1} cm^{-2}")
        self.assertEqual(detection_limit["normalized_value"], 500.0)

    def test_unsupported_unit_is_rejected_instead_of_guessed(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持单位"):
            self.ontology.normalize_value("response_time", 2.0, "frames")

    def test_metrics_without_matching_conditions_are_not_comparable(self) -> None:
        base = {
            "definition_id": "sensitivity",
            "canonical_unit": "μC Gy_air^{-1} cm^{-2}",
            "test_condition": "20 V/mm 低偏压",
        }
        self.assertTrue(comparable_metrics(base, dict(base)))
        self.assertFalse(comparable_metrics(base, {**base, "test_condition": ""}))
        self.assertFalse(
            comparable_metrics(base, {**base, "test_condition": "75 V/mm 电场"})
        )


if __name__ == "__main__":
    unittest.main()
