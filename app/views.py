"""Reusable Streamlit renderers for matching and RAG results."""

from __future__ import annotations

from typing import Any

import streamlit as st


def _page_text(page_start: Any, page_end: Any) -> str:
    return str(page_start) if page_start == page_end else f"{page_start}-{page_end}"


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
