"""Streamlit entry point for the industry-academia Agent MVP."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIRECTORY = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(APP_DIRECTORY))

from views import (
    render_match_result,
    render_rag_result,
    render_requirement_preview,
    render_solution_result,
)
from src.agents.coordinator import build_coordinator
from src.extraction.enterprise_parser import parse_enterprise_need
from src.matching.matcher import ResearchIndustryMatcher
from src.retrieval.rag import RAGPipeline
from src.solutions import build_clarification, decompose_technical_need


st.set_page_config(
    page_title="产学研 Agent",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2rem; padding-bottom: 4rem;}
    [data-testid="stMetric"] {border: 1px solid #d9e2ec; border-radius: 12px; padding: 14px;}
    [data-testid="stSidebar"] {border-right: 1px solid #e7edf3;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="正在加载本地 BGE 模型和向量数据库……")
def get_matcher() -> ResearchIndustryMatcher:
    return ResearchIndustryMatcher()


@st.cache_resource
def get_coordinator():
    return build_coordinator(matcher=get_matcher())


@st.cache_resource
def get_rag_pipeline() -> RAGPipeline:
    matcher = get_matcher()
    return RAGPipeline(
        embedder=matcher.embedder,
        vector_store=matcher.vector_store,
    )


with st.sidebar:
    st.title("🔬 产学研 Agent")
    st.caption("从论文证据出发，连接企业技术需求与教师科研能力。")
    st.markdown("**本地数据集**")
    st.caption("论文、教师画像和向量数据库只保存在当前电脑，不包含在公开仓库中。")
    st.info("企业匹配完全本地运行；论文问答需要调用 Moonshot API。")

st.title("产学研合作智能分析")
st.caption("先确认需求拆解，再生成有论文证据的技术方案、路线与落地计划。")

matching_tab, qa_tab = st.tabs(["企业端 · 组合方案", "论文问答"])

with matching_tab:
    st.markdown("### 1. 输入并核对需求")
    with st.form("enterprise_requirement_form"):
        enterprise_request = st.text_area(
            "企业需求原话",
            height=170,
            placeholder=(
                "建议包含：产品与场景、当前问题、目标能力、量化指标与测试条件、"
                "已有基础、成本/周期/材料等约束、明确不能采用的路线。"
            ),
            help="页面不会自动填入指南示例，也不会把系统建议冒充企业需求。",
        )
        parse_submitted = st.form_submit_button(
            "解析需求",
            type="primary",
            width="stretch",
        )
    if parse_submitted:
        if not enterprise_request.strip():
            st.error("请先输入企业需求原话。")
        else:
            try:
                profile = parse_enterprise_need(enterprise_request)
                st.session_state["requirement_draft"] = {
                    "request_text": enterprise_request.strip(),
                    "profile": profile,
                    "clarification": build_clarification(profile),
                    "modules": decompose_technical_need(profile),
                }
                st.session_state.pop("match_state", None)
            except Exception as exc:
                st.error(f"需求解析失败：{exc}")

    draft = st.session_state.get("requirement_draft")
    if draft:
        render_requirement_preview(draft)
        confirmation = st.checkbox(
            "我已逐项核对：下方拆解忠实反映企业原话；未知项继续保留为待澄清。",
            key="requirement_confirmation_checkbox",
        )
        if st.button(
            "确认需求并生成组合方案",
            type="primary",
            width="stretch",
            disabled=not confirmation,
        ):
            try:
                with st.spinner("正在按技术模块检索论文、生成路线并执行转化闸门……"):
                    st.session_state["match_state"] = get_coordinator().run(
                        draft["request_text"],
                        input_mode="user",
                        requirement_confirmed=True,
                    )
            except Exception as exc:
                st.error(f"方案生成失败：{exc}")
    if "match_state" in st.session_state:
        state = st.session_state["match_state"]
        render_solution_result(state)
        with st.expander("查看原有教师匹配明细"):
            render_match_result(state)
        report_column, route_column = st.columns(2)
        report_column.download_button(
            "下载完整 Markdown 报告",
            data=state["report"],
            file_name="enterprise_solution_report.md",
            mime="text/markdown",
            width="stretch",
        )
        route_column.download_button(
            "下载可编辑 draw.io 技术路线",
            data=state["route_drawio"],
            file_name="enterprise_technical_route.drawio",
            mime="application/xml",
            width="stretch",
        )

with qa_tab:
    st.markdown("根据本地论文检索结果向 Kimi 提问，回答会附论文与页码依据。")
    with st.form("paper_qa_form"):
        paper_question = st.text_input(
            "问",
            placeholder="这个老师主要做什么？",
        )
        consent = st.checkbox(
            "我同意将本地检索到的最多 5 个论文片段发送到 .env 配置的 Moonshot API。"
        )
        qa_submitted = st.form_submit_button("查询论文", width="stretch")
    if qa_submitted:
        if not paper_question.strip():
            st.error("请先输入论文问题。")
        elif not consent:
            st.error("请先确认论文片段发送范围。")
        else:
            try:
                with st.spinner("正在本地检索论文并生成有依据的回答……"):
                    st.session_state["rag_result"] = get_rag_pipeline().answer(
                        paper_question,
                        top_k=5,
                    )
            except Exception as exc:
                st.error(f"论文问答失败：{exc}")
    if "rag_result" in st.session_state:
        render_rag_result(st.session_state["rag_result"])
