"""Immutable local version records for edited enterprise requirements."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..extraction.enterprise_parser import validate_enterprise_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENTERPRISE_VERSION_DIRECTORY = (
    PROJECT_ROOT / "data" / "processed" / "enterprise_needs" / "versions"
)
VERSION_SCHEMA = "enterprise_need_version_v1"
VERSION_STATUSES = frozenset({"draft", "confirmed"})
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,96}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_need_id() -> str:
    return f"NEED-{uuid.uuid4().hex[:12]}"


def _profile_digest(profile: dict[str, Any]) -> str:
    canonical = json.dumps(profile, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EnterpriseNeedVersionStore:
    """Write append-only JSON snapshots under a gitignored local directory."""

    def __init__(self, directory: Path = DEFAULT_ENTERPRISE_VERSION_DIRECTORY) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        if not SAFE_ID.fullmatch(value):
            raise ValueError(f"{label} 格式无效")

    def _path(self, version_id: str) -> Path:
        self._validate_id(version_id, "version_id")
        return self.directory / f"{version_id}.json"

    def save(
        self,
        profile: dict[str, Any],
        *,
        need_id: str,
        status: str,
        parent_version_id: str | None = None,
        label: str = "",
        source: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_enterprise_profile(profile)
        self._validate_id(need_id, "need_id")
        if status not in VERSION_STATUSES:
            raise ValueError(f"未知版本状态：{status}")
        if parent_version_id is not None:
            self._validate_id(parent_version_id, "parent_version_id")
            parent = self.load(parent_version_id)
            if parent["need_id"] != need_id:
                raise ValueError("父版本不属于同一条企业需求")
        confirmation = profile.get("confirmation", {})
        if status == "confirmed":
            if confirmation.get("status") != "confirmed_by_user":
                raise ValueError("confirmed 版本必须来自用户确认画像")
            if confirmation.get("version_id") != parent_version_id:
                raise ValueError("确认画像必须指向本次冻结的父版本")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        version_id = f"ENV-{timestamp}-{uuid.uuid4().hex[:8]}"
        record = {
            "schema_version": VERSION_SCHEMA,
            "version_id": version_id,
            "need_id": need_id,
            "parent_version_id": parent_version_id,
            "status": status,
            "label": str(label).strip(),
            "source": dict(source or {}),
            "profile_sha256": _profile_digest(profile),
            "profile": profile,
            "saved_at": _utc_now(),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        final_path = self._path(version_id)
        temporary_path = final_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(final_path)
        return record

    def load(self, version_id: str) -> dict[str, Any]:
        path = self._path(version_id)
        if not path.is_file():
            raise KeyError(f"找不到企业需求版本：{version_id}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schema_version") != VERSION_SCHEMA:
            raise RuntimeError("企业需求版本 schema 不受支持")
        if record.get("version_id") != version_id:
            raise RuntimeError("企业需求版本 ID 与文件名不一致")
        self._validate_id(record.get("need_id", ""), "need_id")
        if record.get("status") not in VERSION_STATUSES:
            raise RuntimeError("企业需求版本状态不受支持")
        parent_version_id = record.get("parent_version_id")
        if parent_version_id is not None:
            self._validate_id(parent_version_id, "parent_version_id")
        if record.get("profile_sha256") != _profile_digest(record["profile"]):
            raise RuntimeError("企业需求版本内容校验失败，文件可能已被修改")
        validate_enterprise_profile(record["profile"])
        return record

    def list_versions(self, need_id: str | None = None) -> list[dict[str, Any]]:
        if need_id is not None:
            self._validate_id(need_id, "need_id")
        if not self.directory.is_dir():
            return []
        records = [self.load(path.stem) for path in self.directory.glob("ENV-*.json")]
        if need_id is not None:
            records = [item for item in records if item.get("need_id") == need_id]
        records.sort(key=lambda item: item.get("saved_at", ""), reverse=True)
        return records
