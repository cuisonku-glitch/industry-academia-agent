"""Reusable Streamlit renderers for matching and RAG results."""

from __future__ import annotations

from typing import Any

import streamlit as st


def _page_text(page_start: Any, page_end: Any) -> str:
    return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"


def render_requirement_preview(draft: dict[str, Any]) -> None:
    """Render the lightweight confirmation gate before GPU retrieval starts."""
    profile = draft["profile"]
    clarification = draft["clarification"]
    modules = draft["modules"]

    st.markdown("### 2. 核对结构化拆解")
    industry_column, product_column, module_column, metric_column = st.columns(4)
    industry_column.metric("行业场景", profile["industry"])
    product_column.metric("产品/系统", profile["product"])
    module_column.metric("技术模块", str(len(modules)))
    metric_column.metric("量化指标", str(len(profile.get("target_metrics", []))))

    if clarification["blocking_count"]:
        st.warning(
            f"发现 {clarification['blocking_count']} 个阻塞型未知项。"
            "仍可确认当前拆解并生成草案，但系统不会把未知项填成事实。"
        )
    else:
        st.success("关键字段已具备，可确认拆解后进入模块级论文检索。")

    for module in modules:
        with st.expander(f"{module['module_id']} · {module['name']}"):
            st.markdown(f"**企业原话：** {'；'.join(module['source_phrases'])}")
            st.markdown(f"**当前问题：** {module['problem_statement']}")
            st.markdown(
                "**量化验收：** "
                + (
                    "；".join(
                        metric["raw_text"]
                        for metric in module["acceptance_metrics"]
                    )
                    or "待企业补充"
                )
            )
            for item in module["missing_information"]:
                st.caption(f"待澄清：{item}")

    with st.expander("查看所有待澄清问题"):
        if clarification["questions"]:
            for item in clarification["questions"]:
                st.markdown(
                    f"- **[{item['severity']}] {item['question']}**  "
                    f"{item['reason']}"
                )
        else:
            st.markdown("- 暂无待澄清项。")


def render_solution_result(state: dict[str, Any]) -> None:
    """Render the P1 enterprise solution, route, evaluation, and landing plan."""
    bundle = state["solution_bundle"]
    gate = bundle["solution_gate"]
    evaluation = bundle["transfer_evaluation"]

    st.divider()
    st.markdown("### 3. 证据约束的组合方案")
    if gate["status"] == "passed":
        st.success("方案闸门通过：核心模块有论文证据且关键指标具备测试条件。")
    elif gate["status"] == "provisional":
        st.warning("当前为待确认草案；请根据闸门说明补齐指标或论文证据。")
    else:
        st.error("方案闸门暂停，当前不会生成无依据的候选方案。")
    for reason in gate["reasons"]:
        st.caption(reason)

    for option in bundle["solution_options"]:
        st.markdown(f"#### {option['solution_id']} · {option['name']}")
        st.markdown(option["overall_principle"])
        teacher_column, module_column, gap_column = st.columns(3)
        teacher_column.metric("建议对接教师", option["recommended_teacher"])
        module_column.metric("技术模块", str(len(option["modules"])))
        gap_column.metric("证据缺口", str(len(option["uncovered_gaps"])))
        rows = []
        for module in option["modules"]:
            rows.append(
                {
                    "模块": module["module_name"],
                    "状态": module["status"],
                    "导师": module["teacher"],
                    "论文 Chunk": len(module["paper_evidence"]),
                    "验收指标": "；".join(
                        metric["raw_text"]
                        for metric in module["acceptance_metrics"]
                    ) or "待企业补充",
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")
    if not bundle["solution_options"]:
        st.info("请先关闭需求确认或论文证据缺口。")

    st.markdown("### 4. 技术路线")
    route_rows = [
        {
            "节点": node["node_id"],
            "阶段": node["stage"],
            "任务": node["name"],
            "状态": node["status"],
            "前置": "、".join(node["predecessors"]) or "无",
            "责任建议": node["responsible_party"],
        }
        for node in bundle["technical_route"]["nodes"]
    ]
    if route_rows:
        st.dataframe(route_rows, hide_index=True, width="stretch")
        st.caption("下方可下载原生 `.drawio` 文件，节点与连线均可继续编辑。")
    else:
        st.info("方案闸门通过后才会生成技术路线。")

    st.markdown("### 5. 转化评估与决策门")
    decision_column, score_column, completeness_column = st.columns(3)
    decision_column.metric("当前决策", evaluation["decision"])
    score_column.metric(
        "已知维度分",
        (
            f"{evaluation['known_dimension_score']}/100"
            if evaluation["known_dimension_score"] is not None
            else "未知"
        ),
    )
    completeness_column.metric(
        "证据完整度", f"{evaluation['evidence_completeness']}%"
    )
    st.caption(
        f"已知维度覆盖权重 {evaluation['known_weight']:.0%}。"
        f"{evaluation['note']}"
    )
    dimension_rows = []
    for dimension in evaluation["dimensions"].values():
        dimension_rows.append(
            {
                "维度": dimension["label"],
                "分数": (
                    f"{dimension['score']}/100"
                    if dimension["score"] is not None
                    else "未知"
                ),
                "来源": dimension["source_type"],
                "缺口": "；".join(dimension["missing"]),
            }
        )
    st.dataframe(dimension_rows, hide_index=True, width="stretch")
    with st.expander("查看五项硬门槛"):
        for gate_item in evaluation["hard_gates"]:
            st.markdown(
                f"- **{gate_item['gate_id']} {gate_item['name']}**："
                f"{gate_item['status']}"
            )

    st.markdown("### 6. 分阶段落地计划")
    for milestone in bundle["landing_plan"]:
        with st.expander(f"{milestone['milestone_id']} · {milestone['goal']}"):
            st.markdown(f"**责任建议：** {milestone['responsible_party']}")
            st.markdown(f"**交付物：** {'；'.join(milestone['deliverables'])}")
            st.markdown(
                "**验收/退出：** "
                + "；".join(milestone["acceptance_or_exit_criteria"])
            )
            st.markdown(f"**决策门：** {milestone['decision_gate']}")


def render_match_result(state: dict[str, Any]) -> None:
    """Show all matching fields required by the project guide."""
    result = state["match_result"]
    review = state["evidence_review"]
    recommendation = result["recommendations"][0]

    st.subheader("推荐结果")
    teacher_column, score_column, evidence_column = st.columns(3)
    teacher_column.metric("推荐教师", recommendation["recommended_teacher"])
    score_column.metric("匹配度", f"{recommendation['matching_score']:.2f}%")
    evidence_column.metric(
        "论文证据", f"{len(recommendation['paper_evidence'])} 个 Chunk"
    )
    st.progress(
        recommendation["matching_score"] / 100,
        text=f"综合匹配分 {recommendation['matching_score']:.2f}/100",
    )

    if review["overall_status"] == "passed":
        st.success("证据审查通过：推荐结论具有可定位的教师画像与论文 Chunk 证据。")
    else:
        st.warning("证据审查需要人工复核，请查看论文证据和审查问题。")

    st.markdown("#### 核心技术")
    technologies = recommendation["core_matching_technologies"]
    if technologies:
        for item in technologies:
            st.markdown(
                f"- **{item['required_capability']}** ↔ "
                f"{item['matched_teacher_capability']} "
                f"（相似度 {item['similarity']:.3f}）"
            )
    else:
        st.info("暂时没有达到阈值的核心技术匹配。")

    st.markdown("#### 相关论文")
    papers = recommendation["relevant_papers"]
    if papers:
        for paper in papers:
            pages = "、".join(str(page) for page in paper["evidence_pages"])
            st.markdown(
                f"- **《{paper['title']}》**｜{paper['author']}｜{paper['year']}｜"
                f"证据页：{pages}｜最佳相似度 {paper['best_similarity']:.3f}"
            )
    else:
        st.info("暂时没有达到阈值的相关论文。")

    with st.expander("查看论文 Chunk 与页码证据"):
        for item in recommendation["paper_evidence"]:
            st.markdown(
                f"**《{item['title']}》第 "
                f"{_page_text(item['page_start'], item['page_end'])} 页**  "
                f"相似度：{item['similarity']:.3f}  "
                f"Chunk：`{item['chunk_id']}`"
            )
            st.caption(item["excerpt"])

    reason_column, gap_column = st.columns(2)
    with reason_column:
        st.markdown("#### 匹配依据")
        for reason in recommendation["matching_reason"]:
            st.markdown(f"- {reason}")
    with gap_column:
        st.markdown("#### 技术缺口")
        gaps = recommendation["technology_gap"]
        if gaps:
            for gap in gaps:
                st.markdown(
                    f"- {gap['required_capability']}：最佳相似度 "
                    f"{gap['similarity']:.3f}，未达到阈值"
                )
        else:
            st.markdown("- 当前结构化需求中没有低于阈值的能力。")

    st.markdown("#### 潜在合作建议")
    for direction in recommendation["potential_collaboration_directions"]:
        st.markdown(f"- {direction}")

    with st.expander("查看透明评分明细"):
        rows = [
            {
                "指标": metric,
                "原始值": detail["raw"],
                "权重": detail["weight"],
                "分数贡献": detail["contribution"],
            }
            for metric, detail in recommendation["score_breakdown"].items()
        ]
        st.dataframe(rows, hide_index=True, width="stretch")


def render_rag_result(result: dict[str, Any]) -> None:
    """Show a grounded paper answer followed by deterministic sources."""
    st.subheader("论文回答")
    st.markdown(result["answer"])
    st.markdown("#### 论文依据")
    for source in result["sources"]:
        st.markdown(f"- {source}")
    usage = result.get("usage", {})
    if usage.get("total_tokens") is not None:
        st.caption(
            f"模型：{result['model']}｜Token：输入 {usage['prompt_tokens']}，"
            f"输出 {usage['completion_tokens']}，合计 {usage['total_tokens']}"
        )
