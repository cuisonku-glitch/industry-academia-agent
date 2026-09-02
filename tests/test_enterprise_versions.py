"""Enterprise requirement editing and immutable version history tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.extraction.enterprise_parser import (
    parse_enterprise_need,
    validate_enterprise_profile,
)
from src.extraction.enterprise_profile_editor import (
    apply_enterprise_edits,
    confirm_enterprise_profile,
)
from src.repository.enterprise_versions import (
    EnterpriseNeedVersionStore,
    new_need_id,
)


REQUEST = (
    "我们开发工业X射线探伤设备，需要高灵敏度探测，"
    "灵敏度至少1200 μC Gy^-1 cm^-2，已有小型样机。"
)


def make_edits(profile: dict) -> dict:
    return {
        "industry": "工业在线检测",
        "product": "在线X射线质量检测系统",
        "technical_problems": profile["technical_problems"],
        "required_capabilities": [*profile["required_capabilities"], "产线联机闭环"],
        "constraints": ["单线改造预算不超过80万元"],
        "existing_foundations": profile["existing_foundations"],
        "excluded_approaches": [],
        "keywords": profile["keywords"],
        "target_metrics": [
            *profile["target_metrics"],
            {
                "name": "检测速度",
                "operator": ">=",
                "value_text": "12",
                "unit": "m/min",
                "test_condition": "连续产线",
            },
        ],
        "unparsed_fragments": [],
    }


class EnterpriseProfileEditorTests(unittest.TestCase):
    def test_edits_keep_original_and_record_user_provenance(self) -> None:
        original = parse_enterprise_need(REQUEST)
        edited = apply_enterprise_edits(original, make_edits(original))

        validate_enterprise_profile(edited)
        self.assertEqual(edited["original_request"], original["original_request"])
        self.assertEqual(edited["product"], "在线X射线质量检测系统")
        self.assertIn("产品系统：在线X射线质量检测系统", edited["confirmed_request"])
        added_metric = next(
            item for item in edited["target_metrics"] if item["name"] == "检测速度"
        )
        self.assertEqual(added_metric["provenance_type"], "enterprise_user_edit")
        evidence = next(
            item
            for item in edited["evidence_map"]
            if item["field"] == "target_metrics"
            and item["value"] == added_metric["raw_text"]
        )
        self.assertEqual(evidence["source_type"], "enterprise_user_edit")

    def test_incomplete_metric_is_rejected(self) -> None:
        original = parse_enterprise_need(REQUEST)
        edits = make_edits(original)
        edits["target_metrics"] = [{"name": "检测速度", "operator": ">="}]
        with self.assertRaisesRegex(ValueError, "指标名称和目标值"):
            apply_enterprise_edits(original, edits)


class EnterpriseVersionStoreTests(unittest.TestCase):
    def test_save_load_confirm_and_parent_chain(self) -> None:
        original = parse_enterprise_need(REQUEST)
        edited = apply_enterprise_edits(original, make_edits(original))
        need_id = new_need_id()
        with tempfile.TemporaryDirectory() as directory:
            store = EnterpriseNeedVersionStore(Path(directory))
            draft = store.save(
                edited,
                need_id=need_id,
                status="draft",
                label="验收指标补充",
            )
            confirmed_profile = confirm_enterprise_profile(
                edited,
                version_id=draft["version_id"],
            )
            confirmed = store.save(
                confirmed_profile,
                need_id=need_id,
                status="confirmed",
                parent_version_id=draft["version_id"],
            )

            loaded = store.load(confirmed["version_id"])
            self.assertEqual(loaded["parent_version_id"], draft["version_id"])
            self.assertEqual(
                loaded["profile"]["confirmation"]["status"],
                "confirmed_by_user",
            )
            self.assertEqual(len(store.list_versions(need_id)), 2)

    def test_modified_version_file_fails_integrity_check(self) -> None:
        original = parse_enterprise_need(REQUEST)
        with tempfile.TemporaryDirectory() as directory:
            store = EnterpriseNeedVersionStore(Path(directory))
            record = store.save(
                original,
                need_id=new_need_id(),
                status="draft",
            )
            path = Path(directory) / f"{record['version_id']}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["profile"]["product"] = "被手工篡改的产品"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "校验失败"):
                store.load(record["version_id"])

    def test_unsafe_version_id_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = EnterpriseNeedVersionStore(Path(directory))
            with self.assertRaisesRegex(ValueError, "格式无效"):
                store.load("../outside")

    def test_parent_must_belong_to_same_need(self) -> None:
        profile = parse_enterprise_need(REQUEST)
        with tempfile.TemporaryDirectory() as directory:
            store = EnterpriseNeedVersionStore(Path(directory))
            parent = store.save(
                profile,
                need_id=new_need_id(),
                status="draft",
            )
            with self.assertRaisesRegex(ValueError, "同一条企业需求"):
                store.save(
                    profile,
                    need_id=new_need_id(),
                    status="draft",
                    parent_version_id=parent["version_id"],
                )

    def test_confirmed_record_requires_confirmed_parent_snapshot(self) -> None:
        profile = parse_enterprise_need(REQUEST)
        need_id = new_need_id()
        with tempfile.TemporaryDirectory() as directory:
            store = EnterpriseNeedVersionStore(Path(directory))
            parent = store.save(profile, need_id=need_id, status="draft")
            with self.assertRaisesRegex(ValueError, "用户确认画像"):
                store.save(
                    profile,
                    need_id=need_id,
                    status="confirmed",
                    parent_version_id=parent["version_id"],
                )


if __name__ == "__main__":
    unittest.main()
