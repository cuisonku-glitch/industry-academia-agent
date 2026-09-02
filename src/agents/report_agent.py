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
        bundle = state.get("solution_bundle")
        if not result or not review or not bundle:
            raise RuntimeError("Report Agent 缺少匹配结果、企业方案或证据审查")

        mode_label = {
            "demo": "指南示例演示",
            "public_case": "公开榜单验收案例",
            "user_file": "用户文件",
        }.get(state["input_mode"], "用户输入")
        lines = [
            "# 产学研匹配报告",
            "",
            f"> 输入类型：{mode_label}。本报告由本地、可复算流程生成。",
            "",
            "## 企业需求原文",
            "",
            state["request_text"],
            "",
        ]
        profile = state["enterprise_need"]
        if profile.get("confirmed_request") != state["request_text"]:
            lines.extend(
                [
                    "## 用户确认后的需求快照",
                    "",
                    profile["confirmed_request"],
                    "",
                    "> 原始企业文本保留不变；本节是用户逐项编辑并确认后用于方案生成的版本。",
                    "",
                ]
            )
        lines.extend(
            [
                "## 需求确认与待澄清项",
                "",
                "- 需求确认状态："
                + bundle["requirement_confirmation"]["status"],
                "- 需求版本："
                + str(
                    profile.get("confirmation", {}).get("version_id") or "未保存"
                ),
                f"- 阻塞型问题：{bundle['clarification']['blocking_count']} 项",
            ]
        )
        questions = bundle["clarification"]["questions"]
        lines.extend(
            [
                f"- [{item['severity']}] {item['question']}（{item['reason']}）"
                for item in questions
            ]
            or ["- 暂无待澄清项。"]
        )
        lines.extend(["", "## 技术模块拆解", ""])
        for module in bundle["need_modules"]:
            metrics = "；".join(
                item["raw_text"] for item in module["acceptance_metrics"]
            ) or "待企业补充"
            lines.extend(
                [
                    f"### {module['module_id']} · {module['name']}",
                    "",
                    f"- 企业原话：{'；'.join(module['source_phrases'])}",
                    f"- 当前问题：{module['problem_statement']}",
                    f"- 验收指标：{metrics}",
                    f"- 确认状态：{module['confirmation_status']}",
                ]
            )
        lines.extend(
            [
            "",
            "## 推荐结果",
            ]
        )
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
                "## 证据约束方案",
                "",
                f"- 方案闸门：{bundle['solution_gate']['status']}",
            ]
        )
        lines.extend(
            f"- 闸门说明：{reason}"
            for reason in bundle["solution_gate"]["reasons"]
        )
        for option in bundle["solution_options"]:
            lines.extend(
                [
                    "",
                    f"### {option['solution_id']} · {option['name']}",
                    "",
                    f"- 状态：{option['status']}",
                    f"- 推荐教师：{option['recommended_teacher']}",
                    f"- 原则：{option['overall_principle']}",
                    f"- 证据缺口：{'、'.join(option['uncovered_gaps']) or '无'}",
                    "",
                    "模块证据：",
                ]
            )
            for module in option["modules"]:
                lines.append(
                    f"- {module['module_id']} {module['module_name']}："
                    f"{module['status']}，论文 Chunk "
                    f"{len(module['paper_evidence'])} 个"
                )
        if not bundle["solution_options"]:
            lines.append("- 当前没有通过方案生成闸门的候选方案。")

        lines.extend(["", "## 技术路线", ""])
        for node in bundle["technical_route"]["nodes"]:
            criteria = "；".join(
                item["criterion"] for item in node["acceptance_criteria"]
            )
            lines.extend(
                [
                    f"### {node['node_id']} · {node['name']}",
                    "",
                    f"- 阶段：{node['stage']}｜状态：{node['status']}",
                    f"- 前置节点：{'、'.join(node['predecessors']) or '无'}",
                    f"- 责任建议：{node['responsible_party']}",
                    f"- 验收/退出口径：{criteria}",
                ]
            )
        if not bundle["technical_route"]["nodes"]:
            lines.append("- 技术路线尚未生成；请先确认需求并关闭证据缺口。")

        evaluation = bundle["transfer_evaluation"]
        score_text = (
            str(evaluation["known_dimension_score"])
            if evaluation["known_dimension_score"] is not None
            else "未知"
        )
        lines.extend(
            [
                "",
                "## 转化评估",
                "",
                f"- 当前决策：`{evaluation['decision']}`",
                f"- 已知维度分：{score_text}/100（覆盖权重 "
                f"{evaluation['known_weight']:.0%}）",
                f"- 证据完整度：{evaluation['evidence_completeness']}%",
                f"- 说明：{evaluation['note']}",
                "",
                "### 四维评估",
                "",
            ]
        )
        for dimension in evaluation["dimensions"].values():
            value = (
                f"{dimension['score']}/100"
                if dimension["score"] is not None
                else "未知"
            )
            missing = "；".join(dimension["missing"])
            lines.append(
                f"- {dimension['label']}：{value}｜来源 "
                f"{dimension['source_type']}"
                + (f"｜缺口：{missing}" if missing else "")
            )
        lines.extend(["", "### 硬门槛", ""])
        for gate in evaluation["hard_gates"]:
            lines.append(
                f"- {gate['gate_id']} {gate['name']}：{gate['status']}"
            )

        lines.extend(["", "## 分阶段落地计划", ""])
        for milestone in bundle["landing_plan"]:
            lines.extend(
                [
                    f"### {milestone['milestone_id']} · {milestone['goal']}",
                    "",
                    f"- 责任建议：{milestone['responsible_party']}",
                    f"- 交付物：{'；'.join(milestone['deliverables'])}",
                    "- 验收/退出："
                    + "；".join(milestone["acceptance_or_exit_criteria"]),
                    f"- 决策门：{milestone['decision_gate']}",
                ]
            )

        lines.extend(
            [
                "",
                "## 评分说明",
                "",
                "总分由语义相似度、技术能力覆盖、应用领域匹配和论文证据数量"
                "四项指标加权生成，不使用大模型主观评分。",
                "",
                "## 事实边界",
                "",
                "- `enterprise_confirmed`：来自企业原话及本次确认。",
                "- `paper_evidence`：来自可定位的本地论文 Chunk 与页码。",
                "- `system_suggestion`：系统提出的项目组织建议，不是企业事实。",
                "- `unknown`：当前材料无法判断，未用默认值冒充结论。",
                "- 本报告不替代知识产权、法规、安全、财务和工程专业审查。",
            ]
        )
        state["report"] = "\n".join(lines) + "\n"
        record_trace(
            state,
            self.name,
            {"report_character_count": len(state["report"])},
        )
