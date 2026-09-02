"""Streamlit entry point for the industry-academia Agent MVP."""

from __future__ import annotations

import os
import sys
import uuid
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
from enterprise_editor import (
    editor_result_rows,
    lines,
    load_public_cases,
    metric_editor_rows,
    multiline,
)
from src.agents.coordinator import build_coordinator
from src.extraction.enterprise_parser import parse_enterprise_need
from src.extraction.enterprise_profile_editor import (
    ALLOWED_OPERATORS,
    apply_enterprise_edits,
    confirm_enterprise_profile,
)
from src.matching.matcher import ResearchIndustryMatcher
from src.repository import EnterpriseNeedVersionStore, new_need_id
from src.retrieval.rag import RAGPipeline
from src.solutions import build_clarification, decompose_technical_need


PUBLIC_CASES_PATH = PROJECT_ROOT / "examples" / "public_enterprise_cases.json"
DEFAULT_VERSION_DIRECTORY = (
    PROJECT_ROOT / "data" / "processed" / "enterprise_needs" / "versions"
)


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


@st.cache_data
def get_public_cases() -> list[dict]:
    return load_public_cases(PUBLIC_CASES_PATH)


@st.cache_resource
def get_version_store(directory: str) -> EnterpriseNeedVersionStore:
    return EnterpriseNeedVersionStore(Path(directory))


def set_requirement_draft(
    profile: dict,
    *,
    need_id: str,
    source: dict | None = None,
    saved_version_id: str | None = None,
) -> None:
    st.session_state["requirement_draft"] = {
        "request_text": profile["original_request"],
        "profile": profile,
        "clarification": build_clarification(profile),
        "modules": decompose_technical_need(profile),
        "need_id": need_id,
        "source": dict(source or {}),
        "editor_token": uuid.uuid4().hex,
    }
    st.session_state["saved_requirement_version_id"] = saved_version_id
    st.session_state["requirement_confirmation_checkbox"] = False
    st.session_state.pop("match_state", None)


st.session_state.setdefault("enterprise_request_input", "")
st.session_state.setdefault("requirement_draft", None)
st.session_state.setdefault("saved_requirement_version_id", None)
st.session_state.setdefault("requirement_confirmation_checkbox", False)

version_directory = os.getenv(
    "INDUSTRY_AGENT_VERSION_DIR",
    str(DEFAULT_VERSION_DIRECTORY),
)
version_store = get_version_store(version_directory)
public_cases = get_public_cases()


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
    st.markdown("### 1. 输入需求")
    public_case = public_cases[0]
    case_column, history_column = st.columns(2)
    if case_column.button(
        "载入江西电缆公开验收案例",
        icon=":material/public:",
        width="stretch",
    ):
        st.session_state["enterprise_request_input"] = public_case["request_text"]
        profile = parse_enterprise_need(public_case["request_text"])
        set_requirement_draft(
            profile,
            need_id=new_need_id(),
            source=public_case,
        )
        st.rerun()

    try:
        version_records = version_store.list_versions()
    except Exception as exc:
        version_records = []
        st.error(f"本地版本历史校验失败：{exc}")
    selected_version_id = history_column.selectbox(
        "本地历史版本",
        options=[item["version_id"] for item in version_records],
        format_func=lambda version_id: next(
            (
                f"{item['saved_at'][:19]} · {item['status']} · "
                f"{item['label'] or item['version_id'][-8:]}"
                for item in version_records
                if item["version_id"] == version_id
            ),
            version_id,
        ),
        placeholder="还没有保存的版本",
        disabled=not version_records,
        key="version_history_selector",
    )
    if history_column.button(
        "载入所选版本",
        icon=":material/history:",
        width="stretch",
        disabled=not selected_version_id,
    ):
        record = version_store.load(selected_version_id)
        st.session_state["enterprise_request_input"] = record["profile"][
            "original_request"
        ]
        set_requirement_draft(
            record["profile"],
            need_id=record["need_id"],
            source=record.get("source"),
            saved_version_id=record["version_id"],
        )
        st.rerun()

    if (st.session_state.get("requirement_draft") or {}).get("source"):
        source = st.session_state["requirement_draft"]["source"]
        st.info(source.get("notice", "公开来源案例"))
        source_url = source.get("source_mirror_url") or source.get("source_url")
        if source_url:
            st.link_button("查看案例公开来源", source_url)

    with st.form("enterprise_requirement_form"):
        enterprise_request = st.text_area(
            "企业需求原话",
            height=170,
            placeholder=(
                "建议包含：产品与场景、当前问题、目标能力、量化指标与测试条件、"
                "已有基础、成本/周期/材料等约束、明确不能采用的路线。"
            ),
            help="页面不会自动填入指南示例，也不会把系统建议冒充企业需求。",
            key="enterprise_request_input",
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
                set_requirement_draft(profile, need_id=new_need_id())
            except Exception as exc:
                st.error(f"需求解析失败：{exc}")

    draft = st.session_state.get("requirement_draft")
    if draft:
        render_requirement_preview(draft)
        profile = draft["profile"]
        token = draft["editor_token"]
        st.markdown("### 3. 逐项修改并保存版本")
        st.caption(
            "每个列表字段一行一项；保存会产生不可覆盖的新版本，原始企业文本始终保留。"
        )
        with st.form(f"enterprise_profile_editor_{token}"):
            industry_column, product_column = st.columns(2)
            industry = industry_column.text_input(
                "行业场景",
                value=profile["industry"],
                key=f"industry_{token}",
            )
            product = product_column.text_input(
                "产品或系统",
                value=profile["product"],
                key=f"product_{token}",
            )
            problem_column, capability_column = st.columns(2)
            technical_problems = problem_column.text_area(
                "当前技术问题（每行一项）",
                value=multiline(profile["technical_problems"]),
                key=f"problems_{token}",
            )
            required_capabilities = capability_column.text_area(
                "目标技术能力（每行一项）",
                value=multiline(profile["required_capabilities"]),
                key=f"capabilities_{token}",
            )
            st.markdown("**量化验收指标**")
            target_metrics = st.data_editor(
                metric_editor_rows(profile),
                num_rows="dynamic",
                hide_index=True,
                width="stretch",
                key=f"metrics_{token}",
                column_config={
                    "name": st.column_config.TextColumn("指标名称", required=True),
                    "operator": st.column_config.SelectboxColumn(
                        "关系",
                        options=sorted(ALLOWED_OPERATORS),
                        required=True,
                    ),
                    "value_text": st.column_config.TextColumn("目标值", required=True),
                    "unit": st.column_config.TextColumn("单位"),
                    "test_condition": st.column_config.TextColumn("测试条件/方法"),
                },
            )
            constraint_column, foundation_column = st.columns(2)
            constraints = constraint_column.text_area(
                "成本、周期、设备等约束（每行一项）",
                value=multiline(profile["constraints"]),
                key=f"constraints_{token}",
            )
            foundations = foundation_column.text_area(
                "已有样机、设备、数据等基础（每行一项）",
                value=multiline(profile["existing_foundations"]),
                key=f"foundations_{token}",
            )
            exclusion_column, unparsed_column = st.columns(2)
            exclusions = exclusion_column.text_area(
                "明确不能采用的路线（每行一项）",
                value=multiline(profile["excluded_approaches"]),
                key=f"exclusions_{token}",
            )
            unparsed = unparsed_column.text_area(
                "仍待归类的原话（每行一项）",
                value=multiline(profile["unparsed_fragments"]),
                key=f"unparsed_{token}",
            )
            version_label = st.text_input(
                "版本备注",
                placeholder="例如：补充生产线速度和验收条件",
                key=f"version_label_{token}",
            )
            save_version = st.form_submit_button(
                "保存当前修改为新版本",
                icon=":material/save:",
                type="primary",
                width="stretch",
            )

        if save_version:
            try:
                edited_profile = apply_enterprise_edits(
                    profile,
                    {
                        "industry": industry,
                        "product": product,
                        "technical_problems": lines(technical_problems),
                        "required_capabilities": lines(required_capabilities),
                        "target_metrics": editor_result_rows(target_metrics),
                        "constraints": lines(constraints),
                        "existing_foundations": lines(foundations),
                        "excluded_approaches": lines(exclusions),
                        "keywords": profile["keywords"],
                        "unparsed_fragments": lines(unparsed),
                    },
                )
                record = version_store.save(
                    edited_profile,
                    need_id=draft["need_id"],
                    status="draft",
                    parent_version_id=st.session_state.get(
                        "saved_requirement_version_id"
                    ),
                    label=version_label,
                    source=draft.get("source"),
                )
                set_requirement_draft(
                    edited_profile,
                    need_id=draft["need_id"],
                    source=draft.get("source"),
                    saved_version_id=record["version_id"],
                )
                st.success(f"已本地保存版本：{record['version_id']}")
            except Exception as exc:
                st.error(f"保存版本失败：{exc}")

        saved_version_id = st.session_state.get("saved_requirement_version_id")
        st.markdown("### 4. 确认已保存版本")
        if saved_version_id:
            st.success(f"待确认版本：`{saved_version_id}`")
        else:
            st.warning("请先保存一个版本；未保存的页面修改不会进入方案生成。")
        confirmation = st.checkbox(
            "我确认使用上述已保存版本生成方案；未知项继续保留为待澄清。",
            key="requirement_confirmation_checkbox",
            disabled=not saved_version_id,
        )
        if st.button(
            "确认版本并生成组合方案",
            icon=":material/play_arrow:",
            type="primary",
            width="stretch",
            disabled=not confirmation or not saved_version_id,
        ):
            try:
                saved_record = version_store.load(saved_version_id)
                confirmed_profile = confirm_enterprise_profile(
                    saved_record["profile"],
                    version_id=saved_version_id,
                )
                confirmed_record = version_store.save(
                    confirmed_profile,
                    need_id=saved_record["need_id"],
                    status="confirmed",
                    parent_version_id=saved_version_id,
                    label="用户确认冻结",
                    source=saved_record.get("source"),
                )
                with st.spinner("正在按技术模块检索论文、生成路线并执行转化闸门……"):
                    st.session_state["match_state"] = get_coordinator().run(
                        confirmed_profile["original_request"],
                        input_mode=(
                            "public_case"
                            if saved_record.get("source")
                            else "user"
                        ),
                        requirement_confirmed=True,
                        enterprise_profile=confirmed_profile,
                    )
                st.session_state["confirmed_requirement_version_id"] = (
                    confirmed_record["version_id"]
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
