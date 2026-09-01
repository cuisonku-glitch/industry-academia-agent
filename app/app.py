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

from views import render_match_result, render_rag_result
from src.agents.coordinator import build_coordinator
from src.matching.matcher import ResearchIndustryMatcher
from src.retrieval.rag import RAGPipeline


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
st.caption("输入企业真实需求，获得可复算评分、教师推荐、相关论文和页码证据。")

matching_tab, qa_tab = st.tabs(["企业需求匹配", "论文问答"])

with matching_tab:
    enterprise_request = st.text_area(
        "企业需求原话",
        height=150,
        placeholder="例如：我们正在开发……目前遇到……希望获得……能力，并满足……约束。",
        help="请直接填写真实业务描述。页面不会自动填入指南示例。",
    )
    if st.button("开始分析", type="primary", width="stretch"):
        if not enterprise_request.strip():
            st.error("请先输入企业需求原话。")
        else:
            try:
                with st.spinner("正在解析需求、检索论文并核验证据……"):
                    st.session_state["match_state"] = get_coordinator().run(
                        enterprise_request,
                        input_mode="user",
                    )
            except Exception as exc:
                st.error(f"分析失败：{exc}")
    if "match_state" in st.session_state:
        render_match_result(st.session_state["match_state"])

with qa_tab:
    st.markdown("根据本地论文检索结果向 Kimi 提问，回答会附论文与页码依据。")
    paper_question = st.text_input(
        "问",
        placeholder="这个老师主要做什么？",
    )
    consent = st.checkbox(
        "我同意将本地检索到的最多 5 个论文片段发送到 .env 配置的 Moonshot API。"
    )
    if st.button("查询论文", width="stretch"):
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
