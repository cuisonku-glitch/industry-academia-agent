"""Deterministic report rendering for reviewed Agent results."""

from __future__ import annotations

from typing import Any

from .state import record_trace


def format_page_range(page_start: Any, page_end: Any) -> str:
    """Format one page or a page range without values such as 9-9."""
    return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"


class ReportAgent:
    """Render a collaboration report from evidence-reviewed results."""

    name = "Report Agent"

    def run(self, state: dict[str, Any]) -> None:
        result = state.get("match_result")
        review = state.get("evidence_review")
        if not result or not review:
            raise RuntimeError("Report Agent 缺少匹配结果或证据审查")

        mode_label = "指南示例演示" if state["input_mode"] == "demo" else "用户输入"
        lines = [
            "# 产学研匹配报告",
            "",
            f"> 输入类型：{mode_label}。本报告由本地、可复算流程生成。",
            "",
            "## 企业需求原文",
            "",
            state["request_text"],
            "",
            "## 推荐结果",
        ]
        review_by_teacher = {
            item["teacher"]: item for item in review["recommendations"]
        }
        for rank, recommendation in enumerate(result["recommendations"], start=1):
            teacher = recommendation["recommended_teacher"]
            teacher_review = review_by_teacher[teacher]
            lines.extend(
                [
                    "",
                    f"### {rank}. {teacher}",
                    "",
                    f"- 匹配分：{recommendation['matching_score']:.2f}/100",
                    f"- 证据审查：{teacher_review['status']}",
                    f"- 论文证据：{teacher_review['paper_evidence_count']} 个 Chunk",
                    "",
                    "核心匹配技术：",
                ]
            )
            matches = recommendation["core_matching_technologies"]
            lines.extend(
                [
                    f"- {item['required_capability']} ↔ "
                    f"{item['matched_teacher_capability']}（{item['similarity']:.3f}）"
                    for item in matches
                ]
                or ["- 暂无达到阈值的核心技术匹配。"]
            )
            lines.extend(["", "相关论文与证据："])
            evidence = recommendation["paper_evidence"]
            lines.extend(
                [
                    f"- 《{item['title']}》，第 "
                    f"{format_page_range(item['page_start'], item['page_end'])} 页，"
                    f"Chunk `{item['chunk_id']}`，相似度 {item['similarity']:.3f}"
                    for item in evidence[:5]
                ]
                or ["- 暂无达到阈值的论文证据。"]
            )
            lines.extend(["", "匹配理由："])
            lines.extend(f"- {item}" for item in recommendation["matching_reason"])
            lines.extend(["", "技术缺口："])
            gaps = recommendation["technology_gap"]
            lines.extend(
                [
                    f"- {item['required_capability']}：当前最佳相似度"
                    f" {item['similarity']:.3f}，未达到匹配阈值。"
                    for item in gaps
                ]
                or ["- 当前结构化需求中未发现低于阈值的能力。"]
            )
            lines.extend(["", "潜在合作方向："])
            lines.extend(
                f"- {item}"
                for item in recommendation["potential_collaboration_directions"]
            )

        lines.extend(
            [
                "",
                "## 评分说明",
                "",
                "总分由语义相似度、技术能力覆盖、应用领域匹配和论文证据数量"
                "四项指标加权生成，不使用大模型主观评分。",
            ]
        )
        state["report"] = "\n".join(lines) + "\n"
        record_trace(
            state,
            self.name,
            {"report_character_count": len(state["report"])},
        )
