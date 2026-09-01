"""Rank teacher profiles against enterprise needs with transparent hybrid scores."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    from ..retrieval.embedder import LocalEmbedder, cosine_similarity
    from ..retrieval.vector_store import PaperVectorStore
except ImportError:
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root))
    from src.retrieval.embedder import LocalEmbedder, cosine_similarity
    from src.retrieval.vector_store import PaperVectorStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENTERPRISE_PATH = (
    PROJECT_ROOT / "data" / "processed" / "enterprise_needs" / "enterprise_need.json"
)
DEFAULT_TEACHER_DIRECTORY = (
    PROJECT_ROOT / "data" / "processed" / "teacher_profiles"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "data" / "processed" / "matches" / "match_result.json"
)
DEFAULT_TOP_K = 5
DEFAULT_CAPABILITY_THRESHOLD = 0.55
DEFAULT_PAPER_THRESHOLD = 0.45

SCORE_WEIGHTS = {
    "semantic_similarity": 0.45,
    "technical_capability_coverage": 0.25,
    "application_domain_match": 0.15,
    "paper_evidence_count": 0.15,
}


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        key = "".join(cleaned.casefold().split())
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _bounded_similarity(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_enterprise_query(profile: dict[str, Any]) -> str:
    """Combine the original product request and its structured research needs."""
    parts = [
        profile.get("original_request", ""),
        f"行业：{profile.get('industry', '')}",
        f"产品：{profile.get('product', '')}",
        "技术问题：" + "；".join(profile.get("technical_problems", [])),
        "所需科研能力：" + "；".join(profile.get("required_capabilities", [])),
        "约束：" + "；".join(profile.get("constraints", [])),
        "关键词：" + "；".join(profile.get("keywords", [])),
    ]
    return "\n".join(part for part in parts if part and not part.endswith("："))


def teacher_profile_items(profile: dict[str, Any]) -> list[str]:
    """Return the research statements used for overall semantic alignment."""
    return _unique_strings(
        [
            *profile.get("research_directions", []),
            *profile.get("core_capabilities", []),
            *profile.get("application_domains", []),
            *profile.get("potential_industries", []),
        ]
    )


def teacher_technology_items(profile: dict[str, Any]) -> list[str]:
    """Return research directions and capabilities used for demand coverage."""
    return _unique_strings(
        [
            *profile.get("core_capabilities", []),
            *profile.get("research_directions", []),
        ]
    )


def teacher_application_items(profile: dict[str, Any]) -> list[str]:
    """Return application and industry statements used for domain matching."""
    return _unique_strings(
        [
            *profile.get("application_domains", []),
            *profile.get("potential_industries", []),
        ]
    )


def profile_evidence_for_value(
    profile: dict[str, Any], value: str
) -> list[dict[str, Any]]:
    """Find stage-7 evidence mappings for one teacher-profile value."""
    return [
        item
        for item in profile.get("evidence_map", [])
        if isinstance(item, dict) and item.get("value") == value
    ]


def calculate_weighted_score(raw_scores: dict[str, float]) -> tuple[float, dict[str, Any]]:
    """Calculate a 0-100 score and expose every contribution."""
    missing = set(SCORE_WEIGHTS) - set(raw_scores)
    if missing:
        raise ValueError(f"评分缺少指标：{', '.join(sorted(missing))}")

    breakdown: dict[str, Any] = {}
    total = 0.0
    for metric, weight in SCORE_WEIGHTS.items():
        raw = _bounded_similarity(raw_scores[metric])
        contribution = raw * weight * 100
        breakdown[metric] = {
            "raw": round(raw, 4),
            "weight": weight,
            "contribution": round(contribution, 2),
        }
        total += contribution
    return round(total, 2), breakdown


def summarize_relevant_papers(
    evidence: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group retrieved chunks into paper-level evidence summaries."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in evidence:
        grouped[str(item["title"])].append(item)

    papers: list[dict[str, Any]] = []
    for title, items in grouped.items():
        first = items[0]
        pages = sorted(
            {
                page
                for item in items
                for page in range(int(item["page_start"]), int(item["page_end"]) + 1)
            }
        )
        papers.append(
            {
                "title": title,
                "author": first["author"],
                "year": first["year"],
                "best_similarity": round(
                    max(float(item["similarity"]) for item in items), 4
                ),
                "evidence_chunk_count": len(items),
                "evidence_pages": pages,
            }
        )
    return sorted(
        papers,
        key=lambda item: (-item["best_similarity"], item["title"]),
    )


def validate_match_result(result: dict[str, Any]) -> None:
    """Validate score arithmetic and traceability before saving a result."""
    recommendations = result.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        raise RuntimeError("匹配结果必须包含至少一位推荐教师")

    for recommendation in recommendations:
        breakdown = recommendation.get("score_breakdown")
        if not isinstance(breakdown, dict) or set(breakdown) != set(SCORE_WEIGHTS):
            raise RuntimeError("匹配评分分项不完整")
        calculated = round(
            sum(float(item["contribution"]) for item in breakdown.values()), 2
        )
        if abs(calculated - float(recommendation.get("matching_score", -1))) > 0.02:
            raise RuntimeError("匹配总分与分项贡献不一致")

        for match in recommendation.get("core_matching_technologies", []):
            if not match.get("profile_evidence"):
                raise RuntimeError("核心匹配技术缺少教师画像证据")
        for evidence in recommendation.get("paper_evidence", []):
            required = {"chunk_id", "title", "page_start", "page_end", "similarity"}
            if not required.issubset(evidence):
                raise RuntimeError("论文检索证据缺少 Chunk 或页码字段")


class ResearchIndustryMatcher:
    """Match structured enterprise needs to traceable teacher profiles."""

    def __init__(
        self,
        embedder: LocalEmbedder | None = None,
        vector_store: PaperVectorStore | None = None,
        capability_threshold: float = DEFAULT_CAPABILITY_THRESHOLD,
        paper_threshold: float = DEFAULT_PAPER_THRESHOLD,
    ) -> None:
        self.embedder = embedder or LocalEmbedder()
        self.vector_store = vector_store or PaperVectorStore()
        self.capability_threshold = capability_threshold
        self.paper_threshold = paper_threshold

    def _similarities(
        self,
        query_vectors: Sequence[Sequence[float]],
        document_vectors: Sequence[Sequence[float]],
    ) -> list[list[float]]:
        return [
            [
                _bounded_similarity(cosine_similarity(query_vector, document_vector))
                for document_vector in document_vectors
            ]
            for query_vector in query_vectors
        ]

    def _semantic_score(
        self, enterprise_query: str, profile_items: Sequence[str]
    ) -> float:
        if not profile_items:
            return 0.0
        query_vector = self.embedder.embed_queries([enterprise_query])[0]
        item_vectors = self.embedder.embed_documents(profile_items)
        similarities = self._similarities([query_vector], item_vectors)[0]
        return _mean(sorted(similarities, reverse=True)[:3])

    def _capability_matches(
        self,
        required_capabilities: Sequence[str],
        profile: dict[str, Any],
    ) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
        teacher_items = teacher_technology_items(profile)
        if not required_capabilities or not teacher_items:
            gaps = [
                {"required_capability": item, "best_similarity": 0.0}
                for item in required_capabilities
            ]
            return 0.0, [], gaps

        query_vectors = self.embedder.embed_queries(required_capabilities)
        document_vectors = self.embedder.embed_documents(teacher_items)
        similarities = self._similarities(query_vectors, document_vectors)

        matches: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for requirement, scores in zip(required_capabilities, similarities):
            best_index = max(range(len(scores)), key=scores.__getitem__)
            best_item = teacher_items[best_index]
            best_score = scores[best_index]
            detail = {
                "required_capability": requirement,
                "matched_teacher_capability": best_item,
                "similarity": round(best_score, 4),
            }
            if best_score >= self.capability_threshold:
                detail["profile_evidence"] = profile_evidence_for_value(
                    profile, best_item
                )
                matches.append(detail)
            else:
                gaps.append(detail)
        return len(matches) / len(required_capabilities), matches, gaps

    def _application_score(
        self, enterprise: dict[str, Any], profile: dict[str, Any]
    ) -> tuple[float, str | None]:
        application_items = teacher_application_items(profile)
        enterprise_domain = "；".join(
            value
            for value in (enterprise.get("industry"), enterprise.get("product"))
            if isinstance(value, str) and value and value != "未明确"
        )
        if not enterprise_domain or not application_items:
            return 0.0, None
        query_vector = self.embedder.embed_queries([enterprise_domain])[0]
        item_vectors = self.embedder.embed_documents(application_items)
        scores = self._similarities([query_vector], item_vectors)[0]
        best_index = max(range(len(scores)), key=scores.__getitem__)
        return scores[best_index], application_items[best_index]

    def _retrieve_paper_evidence(
        self, enterprise_query: str, teacher: str, top_k: int
    ) -> list[dict[str, Any]]:
        if self.vector_store.count() == 0:
            raise RuntimeError("向量数据库为空，请先运行 vector_store.py 建库")
        query_vector = self.embedder.embed_queries([enterprise_query])[0]
        retrievals = self.vector_store.query(
            query_vector,
            top_k=top_k,
            where={"teacher": teacher},
        )
        evidence: list[dict[str, Any]] = []
        for retrieval in retrievals:
            similarity = _bounded_similarity(float(retrieval["similarity"]))
            if similarity < self.paper_threshold:
                continue
            metadata = retrieval["metadata"]
            evidence.append(
                {
                    "rank": retrieval["rank"],
                    "chunk_id": retrieval["chunk_id"],
                    "title": metadata["title"],
                    "author": metadata["author"],
                    "teacher": metadata["teacher"],
                    "year": metadata["year"],
                    "page_start": metadata["page_start"],
                    "page_end": metadata["page_end"],
                    "similarity": round(similarity, 4),
                    "excerpt": retrieval["text"][:500].replace("\n", " "),
                }
            )
        return evidence

    def match_teacher(
        self,
        enterprise: dict[str, Any],
        profile: dict[str, Any],
        top_k: int = DEFAULT_TOP_K,
    ) -> dict[str, Any]:
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        teacher = str(profile.get("teacher", "")).strip()
        if not teacher:
            raise RuntimeError("教师画像缺少 teacher")

        enterprise_query = build_enterprise_query(enterprise)
        required = _unique_strings(enterprise.get("required_capabilities", []))
        semantic_score = self._semantic_score(
            enterprise_query, teacher_profile_items(profile)
        )
        coverage_score, capability_matches, gaps = self._capability_matches(
            required, profile
        )
        application_score, closest_application = self._application_score(
            enterprise, profile
        )
        paper_evidence = self._retrieve_paper_evidence(
            enterprise_query, teacher, top_k
        )
        evidence_count_score = min(len(paper_evidence) / top_k, 1.0)
        matching_score, breakdown = calculate_weighted_score(
            {
                "semantic_similarity": semantic_score,
                "technical_capability_coverage": coverage_score,
                "application_domain_match": application_score,
                "paper_evidence_count": evidence_count_score,
            }
        )

        reasons = [
            f"企业需求与教师研究画像的语义相似度为 {semantic_score:.3f}。",
            f"{len(required)} 项所需能力中有 {len(capability_matches)} 项达到"
            f" {self.capability_threshold:.2f} 的匹配阈值。",
            f"应用领域最接近“{closest_application}”，相似度为 {application_score:.3f}。"
            if closest_application
            else "企业行业/产品或教师应用领域信息不足，应用领域项计 0 分。",
            f"本地向量库检索到 {len(paper_evidence)} 个达到"
            f" {self.paper_threshold:.2f} 阈值的论文片段。",
        ]
        collaborations = [
            f"围绕“{item['required_capability']}”与教师已有能力"
            f"“{item['matched_teacher_capability']}”开展样品制备、性能测试与工业场景验证。"
            for item in capability_matches
        ]
        if gaps:
            collaborations.append(
                "对匹配较弱的需求先开展小规模可行性预研，并补充成本、工艺放大或设备适配证据。"
            )

        return {
            "recommended_teacher": teacher,
            "matching_score": matching_score,
            "score_breakdown": breakdown,
            "core_matching_technologies": capability_matches,
            "relevant_papers": summarize_relevant_papers(paper_evidence),
            "paper_evidence": paper_evidence,
            "matching_reason": reasons,
            "technology_gap": gaps,
            "potential_collaboration_directions": collaborations,
        }

    def match(
        self,
        enterprise: dict[str, Any],
        teacher_profiles: Sequence[dict[str, Any]],
        top_k: int = DEFAULT_TOP_K,
    ) -> dict[str, Any]:
        if not teacher_profiles:
            raise RuntimeError("没有可用于匹配的教师画像")
        recommendations = [
            self.match_teacher(enterprise, profile, top_k=top_k)
            for profile in teacher_profiles
        ]
        recommendations.sort(
            key=lambda item: (-item["matching_score"], item["recommended_teacher"])
        )
        result = {
            "enterprise_need": {
                field: enterprise.get(field)
                for field in (
                    "industry",
                    "product",
                    "technical_problems",
                    "required_capabilities",
                    "constraints",
                    "keywords",
                    "original_request",
                )
            },
            "scoring_method": {
                "name": "deterministic_hybrid_matching_v1",
                "weights": SCORE_WEIGHTS,
                "capability_similarity_threshold": self.capability_threshold,
                "paper_similarity_threshold": self.paper_threshold,
                "note": "总分完全由四项可复算指标生成，不使用大模型主观打分。",
            },
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        validate_match_result(result)
        return result


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError(f"JSON 顶层必须是对象：{path}")
    return data


def load_teacher_profiles(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        raise FileNotFoundError(directory)
    profiles = [load_json(path) for path in sorted(directory.glob("*.json"))]
    if not profiles:
        raise RuntimeError(f"教师画像目录中没有 JSON：{directory}")
    return profiles


def save_match_result(result: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行透明、可追溯的科研—产业匹配")
    parser.add_argument("--enterprise", type=Path, default=DEFAULT_ENTERPRISE_PATH)
    parser.add_argument("--teachers", type=Path, default=DEFAULT_TEACHER_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    return parser.parse_args()


def print_result(result: dict[str, Any], output_path: Path) -> None:
    print("科研—产业匹配结果：")
    for index, recommendation in enumerate(result["recommendations"], start=1):
        print(
            f"{index}. {recommendation['recommended_teacher']}｜"
            f"匹配分：{recommendation['matching_score']:.2f}/100｜"
            f"核心匹配技术：{len(recommendation['core_matching_technologies'])}｜"
            f"论文证据：{len(recommendation['paper_evidence'])} 个 Chunk"
        )
        for metric, detail in recommendation["score_breakdown"].items():
            print(
                f"   - {metric}: 原始值 {detail['raw']:.4f}，"
                f"权重 {detail['weight']:.0%}，贡献 {detail['contribution']:.2f}"
            )
    print(f"完整证据结果已保存：{output_path}")


def main() -> None:
    args = parse_args()
    enterprise = load_json(args.enterprise)
    teacher_profiles = load_teacher_profiles(args.teachers)
    matcher = ResearchIndustryMatcher()
    print(f"本地 Embedding 设备：{matcher.embedder.device}")
    print(f"向量数据库记录：{matcher.vector_store.count()}")
    print(f"教师画像数量：{len(teacher_profiles)}")
    result = matcher.match(enterprise, teacher_profiles, top_k=args.top_k)
    output_path = save_match_result(result, args.output)
    print_result(result, output_path)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
