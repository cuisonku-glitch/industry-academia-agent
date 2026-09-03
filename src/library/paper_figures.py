"""Local extraction of traceable paper figures and caption regions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pymupdf

from src.repository import PaperRecord

from .paper_indexing import load_parsed_paper
from .paper_ingestion import DEFAULT_PARSED_PAPER_DIRECTORY


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPER_ASSET_DIRECTORY = PROJECT_ROOT / "data" / "processed" / "paper_assets"
FIGURE_EXTRACTION_VERSION = "caption_region_v1"
CAPTION_PATTERN = re.compile(
    r"^(?P<prefix>图|表|figure|fig\.?|table)\s*"
    r"(?P<number>[0-9一二三四五六七八九十]+(?:[.\-—_][0-9]+)?)?\s*"
    r"(?P<caption>.*)$",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class FigureAsset:
    asset_id: str
    paper_id: str
    page: int
    kind: str
    label: str
    caption: str
    file_name: str
    extraction_source: str
    bbox: tuple[float, float, float, float]
    width: int
    height: int

    def to_public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("file_name", None)
        value["bbox"] = list(self.bbox)
        return value


@dataclass(frozen=True)
class FigureExtractionResult:
    paper_id: str
    manifest_path: Path
    assets: tuple[FigureAsset, ...]
    caption_count: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json.tmp",
            dir=path.parent,
            encoding="utf-8",
            newline="\n",
            delete=False,
        ) as temporary:
            json.dump(payload, temporary, ensure_ascii=False, indent=2)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _clean_caption(text: str) -> tuple[str, str, str] | None:
    compact = " ".join(str(text).split())
    match = CAPTION_PATTERN.match(compact)
    if not match:
        return None
    prefix = match.group("prefix")
    number = (match.group("number") or "").strip(" .-—_")
    caption = (match.group("caption") or "").strip(" ：:.-—")
    kind = "table" if prefix.casefold() in {"表", "table"} else "figure"
    label = f"{prefix.rstrip('.')}{number}" if number else prefix.rstrip(".")
    return kind, label, caption or compact


def _intersection_width(left: pymupdf.Rect, right: pymupdf.Rect) -> float:
    return max(0.0, min(left.x1, right.x1) - max(left.x0, right.x0))


def _choose_clip(
    page: pymupdf.Page,
    caption_bbox: tuple[float, float, float, float],
) -> tuple[pymupdf.Rect, str]:
    page_rect = page.rect
    caption_rect = pymupdf.Rect(caption_bbox)
    candidates: list[tuple[float, float, pymupdf.Rect]] = []
    for info in page.get_image_info(xrefs=True):
        bbox = info.get("bbox")
        if not bbox:
            continue
        image_rect = pymupdf.Rect(bbox)
        if image_rect.width < 55 or image_rect.height < 45:
            continue
        if image_rect.y1 > caption_rect.y1 + 18:
            continue
        horizontal_overlap = _intersection_width(image_rect, caption_rect)
        overlap_ratio = horizontal_overlap / max(1.0, min(image_rect.width, caption_rect.width))
        vertical_gap = max(0.0, caption_rect.y0 - image_rect.y1)
        if overlap_ratio < 0.12 or vertical_gap > page_rect.height * 0.42:
            continue
        candidates.append((vertical_gap, -image_rect.get_area(), image_rect))

    if candidates:
        selected = min(candidates, key=lambda item: (item[0], item[1]))[2]
        expanded = pymupdf.Rect(
            max(page_rect.x0, selected.x0 - 6),
            max(page_rect.y0, selected.y0 - 6),
            min(page_rect.x1, selected.x1 + 6),
            min(page_rect.y1, caption_rect.y0 - 2),
        )
        return expanded, "nearest_embedded_image"

    height = min(page_rect.height * 0.42, 300.0)
    fallback = pymupdf.Rect(
        page_rect.x0 + page_rect.width * 0.06,
        max(page_rect.y0, caption_rect.y0 - height),
        page_rect.x1 - page_rect.width * 0.06,
        max(page_rect.y0 + 12, caption_rect.y0 - 2),
    )
    return fallback, "caption_region"


class PaperFigureService:
    """Extract figure/table regions without sending paper data off-device."""

    def __init__(
        self,
        *,
        parsed_directory: Path = DEFAULT_PARSED_PAPER_DIRECTORY,
        asset_directory: Path = DEFAULT_PAPER_ASSET_DIRECTORY,
    ) -> None:
        self.parsed_directory = Path(parsed_directory)
        self.asset_directory = Path(asset_directory)

    def paper_directory(self, paper_id: str) -> Path:
        return self.asset_directory / paper_id

    def manifest_path(self, paper_id: str) -> Path:
        return self.paper_directory(paper_id) / "figures.json"

    def load_assets(self, paper_id: str) -> tuple[FigureAsset, ...]:
        path = self.manifest_path(paper_id)
        if not path.is_file():
            return ()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            raw_assets = payload.get("assets", [])
            return tuple(
                FigureAsset(
                    asset_id=str(item["asset_id"]),
                    paper_id=str(item["paper_id"]),
                    page=int(item["page"]),
                    kind=str(item["kind"]),
                    label=str(item["label"]),
                    caption=str(item["caption"]),
                    file_name=str(item["file_name"]),
                    extraction_source=str(item["extraction_source"]),
                    bbox=tuple(float(value) for value in item["bbox"]),
                    width=int(item["width"]),
                    height=int(item["height"]),
                )
                for item in raw_assets
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"论文图像清单损坏：{path.name}：{exc}") from exc

    def asset_path(self, asset: FigureAsset) -> Path:
        path = (self.paper_directory(asset.paper_id) / asset.file_name).resolve()
        expected_parent = self.paper_directory(asset.paper_id).resolve()
        if path.parent != expected_parent:
            raise RuntimeError("论文图像文件路径无效")
        return path

    def extract(
        self,
        record: PaperRecord,
        *,
        max_assets: int = 8,
        scale: float = 1.7,
    ) -> FigureExtractionResult:
        if max_assets < 1 or max_assets > 24:
            raise ValueError("单篇提取图像数量必须在 1–24 之间")
        if record.ingestion_status not in {"parsed", "indexing", "indexed", "index_failed"}:
            raise RuntimeError("论文尚未完成正文解析")
        pdf_path = Path(record.file_path)
        if pdf_path.suffix.casefold() != ".pdf" or not pdf_path.is_file():
            raise RuntimeError("本机没有找到论文原始 PDF")

        parsed = load_parsed_paper(self.parsed_directory / f"{record.paper_id}.json.gz")
        output_directory = self.paper_directory(record.paper_id)
        output_directory.mkdir(parents=True, exist_ok=True)
        candidates: list[tuple[int, tuple[float, float, float, float], str, str, str]] = []
        for page_payload in parsed.get("pages", []):
            page_number = int(page_payload.get("page", 0))
            for block in page_payload.get("blocks", []):
                if block.get("block_type") not in {"figure_caption", "table_caption"}:
                    continue
                parsed_caption = _clean_caption(str(block.get("text", "")))
                bbox = block.get("bbox")
                if parsed_caption is None or not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                kind, label, caption = parsed_caption
                candidates.append(
                    (page_number, tuple(float(value) for value in bbox), kind, label, caption)
                )

        assets: list[FigureAsset] = []
        with pymupdf.open(pdf_path) as document:
            chosen: dict[
                tuple[int, str, str],
                tuple[
                    int,
                    tuple[float, float, float, float],
                    str,
                    str,
                    str,
                    pymupdf.Rect,
                    str,
                ],
            ] = {}
            for page_number, bbox, kind, label, caption in candidates:
                if not (1 <= page_number <= len(document)):
                    continue
                page = document[page_number - 1]
                clip, source = _choose_clip(page, bbox)
                if clip.width < 20 or clip.height < 20:
                    continue
                key = (page_number, kind, label.casefold())
                prepared = (page_number, bbox, kind, label, caption, clip, source)
                current = chosen.get(key)
                if current is None or (
                    source == "nearest_embedded_image"
                    and current[-1] != "nearest_embedded_image"
                ):
                    chosen[key] = prepared

            selected = sorted(
                chosen.values(), key=lambda item: (item[0], item[1][1], item[3])
            )[:max_assets]
            for page_number, bbox, kind, label, caption, clip, source in selected:
                page = document[page_number - 1]
                asset_id = f"F{len(assets) + 1:02d}"
                file_name = f"{asset_id}.png"
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    clip=clip,
                    alpha=False,
                )
                pixmap.save(output_directory / file_name)
                assets.append(
                    FigureAsset(
                        asset_id=asset_id,
                        paper_id=record.paper_id,
                        page=page_number,
                        kind=kind,
                        label=label,
                        caption=caption,
                        file_name=file_name,
                        extraction_source=source,
                        bbox=tuple(round(value, 3) for value in (clip.x0, clip.y0, clip.x1, clip.y1)),
                        width=pixmap.width,
                        height=pixmap.height,
                    )
                )

        manifest_path = self.manifest_path(record.paper_id)
        _write_json_atomic(
            manifest_path,
            {
                "paper_id": record.paper_id,
                "version": FIGURE_EXTRACTION_VERSION,
                "generated_at": _utc_now(),
                "caption_count": len(candidates),
                "assets": [asdict(asset) for asset in assets],
            },
        )
        return FigureExtractionResult(
            paper_id=record.paper_id,
            manifest_path=manifest_path,
            assets=tuple(assets),
            caption_count=len(candidates),
        )
