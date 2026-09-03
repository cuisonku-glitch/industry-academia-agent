"""Academy-side paper library and review workbench."""

from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path

import streamlit as st

from src.library import (
    DEFAULT_LIBRARY_ROOT,
    DEFAULT_PARSED_PAPER_DIRECTORY,
    PaperAnalysisService,
    PaperIngestionService,
    PaperIndexingService,
    PaperLibraryService,
)
from src.repository import (
    DEFAULT_CATALOG_PATH,
    INGESTION_STATUSES,
    TAG_CATEGORIES,
    TAG_REVIEW_STATUSES,
    PaperCatalog,
    PaperRecord,
    PaperTag,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEACHERS_PER_PAGE = 12
CATEGORY_LABELS = {
    "research_direction": "研究方向",
    "material": "材料",
    "device": "器件/设备",
    "method": "方法/工艺",
    "metric": "性能指标",
    "application": "应用场景",
    "teacher": "导师",
    "author": "作者",
    "year": "年份",
    "custom": "自定义",
}
STATUS_LABELS = {
    "discovered": "已发现，待登记",
    "metadata_pending": "已登记，待解析正文",
    "parsing": "正在解析正文",
    "parsed": "正文已解析，待建立索引",
    "indexing": "正在建立索引",
    "indexed": "已索引",
    "failed": "解析失败，可重试",
    "index_failed": "索引失败，可重试",
}
REVIEW_LABELS = {
    "suggested": "待确认",
    "confirmed": "已确认",
    "rejected": "已驳回",
}


@st.cache_resource
def get_paper_catalog(database_path: str) -> PaperCatalog:
    return PaperCatalog(Path(database_path))


@st.cache_resource
def get_library_service(database_path: str) -> PaperLibraryService:
    return PaperLibraryService(get_paper_catalog(database_path))


@st.cache_resource
def get_ingestion_service(database_path: str) -> PaperIngestionService:
    return PaperIngestionService(
        get_paper_catalog(database_path),
        library_service=get_library_service(database_path),
    )


@st.cache_resource
def get_analysis_service(database_path: str) -> PaperAnalysisService:
    return PaperAnalysisService(get_paper_catalog(database_path))


def _catalog_path() -> str:
    return os.getenv("INDUSTRY_AGENT_CATALOG_PATH", str(DEFAULT_CATALOG_PATH))


def _library_root() -> Path:
    return Path(
        os.getenv("INDUSTRY_AGENT_PAPER_LIBRARY_DIR", str(DEFAULT_LIBRARY_ROOT))
    ).resolve()


def _split_lines(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.replace("，", "\n").splitlines() if item.strip())


def _optional_year(value: int) -> int | None:
    return value or None


def _report_markdown(record: PaperRecord, tags: list[PaperTag]) -> str:
    visible_tags = [tag for tag in tags if tag.review_status != "rejected"]
    tag_lines = [
        f"- {CATEGORY_LABELS.get(tag.category, tag.category)}：{tag.value} "
        f"（{REVIEW_LABELS[tag.review_status]}；来源 {tag.source}；"
        f"置信度 {tag.confidence:.0%}）"
        for tag in visible_tags
    ]
    return "\n".join(
        [
            f"# {record.title}",
            "",
            "> 当前为论文目录与标签审核预览，不是论文精读结论。",
            "",
            "## 基础信息",
            "",
            f"- 导师：{record.teacher or '待补充'}",
            f"- 作者：{'、'.join(record.authors) or '待补充'}",
            f"- 院校/学院：{record.institution or '待补充'} / {record.college or '待补充'}",
            f"- 年份：{record.year or '待补充'}",
            f"- 状态：{STATUS_LABELS.get(record.ingestion_status, record.ingestion_status)}",
            f"- 论文 ID：{record.paper_id}",
            "",
            "## 可审核标签",
            "",
            *(tag_lines or ["- 暂无标签"]),
            "",
            "## 后续分析状态",
            "",
            "- 论文精读：待执行",
            "- 技术路线：待执行并人工审核节点/连线",
            "- 产业转化分析：待执行",
            "",
            "事实、推断、专家判断和未知项将在正式分析报告中分开标记。",
        ]
    )


def _render_sync_panel(service: PaperLibraryService, root: Path) -> None:
    with st.popover("同步本地目录", icon=":material/sync:", width="stretch"):
        st.caption(f"只扫描 PDF，并跳过 .venv、.idea 等目录：{root}")
        if st.button("开始/继续增量同步", type="primary", width="stretch"):
            progress_bar = st.progress(0, text="正在扫描论文……")

            def update_progress(current: int, total: int) -> None:
                progress_bar.progress(
                    current / total if total else 1.0,
                    text=f"正在登记 {current}/{total}",
                )

            try:
                result = service.sync_directory(root, progress=update_progress)
                progress_bar.empty()
                st.success(
                    f"同步完成：新增/变更 {result.registered}，"
                    f"未变化 {result.unchanged}，失败 {result.failed}。"
                )
                for error in result.errors[:10]:
                    st.warning(error)
                st.cache_data.clear()
                st.rerun()
            except Exception as exc:
                progress_bar.empty()
                st.error(f"同步失败，可修复后重试：{exc}")


def _render_upload_panel(service: PaperLibraryService) -> None:
    with st.popover("上传 PDF", icon=":material/upload_file:", width="stretch"):
        with st.form("academy_upload_form", clear_on_submit=True):
            uploaded = st.file_uploader(
                "选择论文 PDF",
                type="pdf",
                max_upload_size=100,
                help="会检查文件头、大小、加密状态和 SHA-256；同一论文不会重复保存。",
            )
            title = st.text_input("题名（可留空，默认取文件名）")
            teacher = st.text_input("导师")
            authors = st.text_input("作者（每行或中文逗号分隔）")
            authorization_note = st.text_area(
                "授权/使用说明",
                placeholder="例如：本人论文，仅限本地科研分析。",
            )
            submitted = st.form_submit_button(
                "校验并登记",
                type="primary",
                width="stretch",
            )
        if submitted:
            if uploaded is None:
                st.error("请先选择 PDF。")
            else:
                try:
                    uploaded.seek(0)
                    result = service.import_upload(
                        uploaded,
                        uploaded.name,
                        title=title,
                        teacher=teacher,
                        authors=_split_lines(authors),
                        authorization_note=authorization_note,
                    )
                    st.session_state["academy_selected_paper_id"] = (
                        result.record.paper_id
                    )
                    if result.duplicate:
                        st.info("检测到相同 SHA-256，已关联已有论文，没有重复保存。")
                    else:
                        st.success("PDF 已保存到本地隔离目录并登记，等待后续解析。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"上传失败，可修复后重试：{exc}")


def _render_parse_panel(service: PaperIngestionService) -> None:
    with st.popover("解析正文", icon=":material/text_snippet:", width="stretch"):
        st.caption("纯本地执行。建议先按 10 篇小批次运行，失败论文可单独重试。")
        batch_size = st.number_input(
            "本批数量",
            min_value=1,
            max_value=20,
            value=10,
            step=1,
            key="academy_parse_batch_size",
        )
        retry_failed = st.toggle("同时重试失败论文", key="academy_retry_failed")
        if st.button("开始解析本批", type="primary", width="stretch"):
            recovered = service.recover_interrupted()
            progress_bar = st.progress(0, text="准备解析正文……")

            def update_progress(current: int, total: int, title: str) -> None:
                progress_bar.progress(
                    current / total if total else 1.0,
                    text=f"{current}/{total} · {title}",
                )

            result = service.parse_batch(
                limit=int(batch_size),
                retry_failed=retry_failed,
                progress=update_progress,
            )
            progress_bar.empty()
            if result.failed:
                st.warning(
                    f"完成 {result.completed}，失败 {result.failed}；失败项已记录，可重试。"
                )
                for error in result.errors[:5]:
                    st.caption(error)
            else:
                st.success(
                    f"正文解析完成 {result.completed} 篇，"
                    f"新增正文标签 {result.content_tags_added} 条。"
                )
            if recovered:
                st.caption(f"本次先恢复了 {recovered} 个中断任务。")
            st.rerun()


def _render_index_panel(catalog: PaperCatalog) -> None:
    with st.popover("建立索引", icon=":material/database:", width="stretch"):
        st.caption("使用本机 BGE + GPU 增量建库；已完成论文不会重复处理。")
        batch_size = st.number_input(
            "本批索引数量",
            min_value=1,
            max_value=20,
            value=5,
            step=1,
            key="academy_index_batch_size",
        )
        retry_failed = st.toggle("同时重试索引失败论文", key="academy_retry_index")
        if st.button("开始建立本批索引", type="primary", width="stretch"):
            from src.retrieval.embedder import LocalEmbedder
            from src.retrieval.vector_store import PaperVectorStore

            progress_bar = st.progress(0, text="正在加载本地 Embedding 模型……")
            try:
                embedder = LocalEmbedder()
                with PaperVectorStore() as store:
                    service = PaperIndexingService(
                        catalog,
                        embedder=embedder,
                        vector_store=store,
                        parsed_directory=DEFAULT_PARSED_PAPER_DIRECTORY,
                    )
                    recovered = service.recover_interrupted()

                    def update_progress(
                        current: int,
                        total: int,
                        title: str,
                        chunks: int,
                    ) -> None:
                        detail = f" · 本篇 {chunks} Chunk" if chunks else ""
                        progress_bar.progress(
                            current / total if total else 1.0,
                            text=f"{current}/{total} · {title}{detail}",
                        )

                    result = service.index_batch(
                        limit=int(batch_size),
                        retry_failed=retry_failed,
                        progress=update_progress,
                    )
                progress_bar.empty()
                if result.failed:
                    st.warning(
                        f"完成 {result.completed}，失败 {result.failed}；可修复后重试。"
                    )
                    for error in result.errors[:5]:
                        st.caption(error)
                else:
                    st.success(
                        f"索引完成 {result.completed} 篇，共写入 "
                        f"{result.chunks_indexed} 个 Chunk。"
                    )
                if recovered:
                    st.caption(f"本次先恢复了 {recovered} 个中断索引任务。")
                st.rerun()
            except Exception as exc:
                progress_bar.empty()
                st.error(f"索引失败，可修复后重试：{exc}")


def _render_metadata_editor(catalog: PaperCatalog, record: PaperRecord) -> None:
    with st.expander("基础信息与授权", expanded=False):
        token = record.updated_at
        with st.form(f"paper_metadata_{record.paper_id}_{token}"):
            title = st.text_input("论文题名", value=record.title)
            teacher = st.text_input("导师", value=record.teacher)
            authors = st.text_area("作者（每行一位）", value="\n".join(record.authors))
            institution_column, college_column = st.columns(2)
            institution = institution_column.text_input("院校", value=record.institution)
            college = college_column.text_input("学院", value=record.college)
            year = st.number_input(
                "年份（0 表示未知）",
                min_value=0,
                max_value=2200,
                value=record.year or 0,
                step=1,
            )
            direction = st.text_input("主研究方向", value=record.direction)
            keywords = st.text_area("关键词（每行一个）", value="\n".join(record.keywords))
            authorization_note = st.text_area(
                "授权/使用说明", value=record.authorization_note
            )
            saved = st.form_submit_button("保存基础信息", type="primary")
        if saved:
            try:
                catalog.update_metadata(
                    record.paper_id,
                    title=title,
                    teacher=teacher,
                    authors=_split_lines(authors),
                    institution=institution,
                    college=college,
                    year=_optional_year(int(year)),
                    direction=direction,
                    keywords=_split_lines(keywords),
                    authorization_note=authorization_note,
                )
                st.success("基础信息已保存。")
                st.rerun()
            except Exception as exc:
                st.error(f"保存失败：{exc}")


def _render_tag_editor(catalog: PaperCatalog, record: PaperRecord) -> list[PaperTag]:
    tags = catalog.list_tags(record.paper_id)
    st.markdown("#### 多层标签审核")
    st.caption("自动标签只给建议；修改审核状态后保存。已驳回标签不参与检索。")
    rows = [
        {
            "tag_id": tag.tag_id,
            "类别": CATEGORY_LABELS.get(tag.category, tag.category),
            "标签": tag.value,
            "来源": tag.source,
            "置信度": tag.confidence,
            "审核状态": tag.review_status,
            "依据": tag.evidence,
        }
        for tag in tags
    ]
    edited = st.data_editor(
        rows,
        hide_index=True,
        width="stretch",
        disabled=["tag_id", "类别", "标签", "来源", "置信度", "依据"],
        column_order=["类别", "标签", "来源", "置信度", "审核状态", "依据"],
        column_config={
            "置信度": st.column_config.ProgressColumn(
                "置信度", min_value=0.0, max_value=1.0, format="percent"
            ),
            "审核状态": st.column_config.SelectboxColumn(
                "审核状态", options=sorted(TAG_REVIEW_STATUSES), required=True
            ),
        },
        key=f"paper_tags_{record.paper_id}_{record.updated_at}",
    )
    if st.button("保存标签审核", icon=":material/fact_check:"):
        try:
            by_id = {tag.tag_id: tag for tag in tags}
            for row in edited:
                tag_id = row["tag_id"]
                if row["审核状态"] != by_id[tag_id].review_status:
                    catalog.review_tag(tag_id, row["审核状态"])
            st.success("标签审核状态已保存。")
            st.rerun()
        except Exception as exc:
            st.error(f"保存标签失败：{exc}")

    with st.form(f"custom_tag_{record.paper_id}"):
        category_column, value_column = st.columns([1, 2])
        category = category_column.selectbox(
            "类别",
            sorted(TAG_CATEGORIES),
            format_func=lambda value: CATEGORY_LABELS.get(value, value),
        )
        value = value_column.text_input("人工标签")
        add_tag = st.form_submit_button("新增并确认")
    if add_tag:
        try:
            catalog.upsert_tag(
                PaperTag(
                    paper_id=record.paper_id,
                    category=category,
                    value=value,
                    source="user",
                    confidence=1.0,
                    review_status="confirmed",
                    evidence="用户在院校端工作台确认",
                )
            )
            st.success("人工标签已确认。")
            st.rerun()
        except Exception as exc:
            st.error(f"新增标签失败：{exc}")
    return tags


def _render_analysis_actions(
    service: PaperAnalysisService,
    record: PaperRecord,
) -> None:
    st.markdown("#### 论文分析任务")
    ready = record.ingestion_status in {
        "parsed",
        "indexing",
        "indexed",
        "index_failed",
    }
    reading_result = None
    with st.container(horizontal=True):
        run_reading = st.button(
            "论文精读总结",
            icon=":material/menu_book:",
            disabled=not ready,
        )
        st.button(
            "技术路线提取",
            icon=":material/route:",
            disabled=True,
            help="下一纵切接入 draw.io 和证据节点。",
        )
        st.button(
            "产业转化分析",
            icon=":material/handshake:",
            disabled=True,
            help="将在技术路线完成后接入。",
        )
    if not ready:
        st.info(
            "这篇论文目前只完成目录登记。先完成文本解析/索引，随后才会启用精读、"
            "路线和转化分析；系统不会仅凭文件名编造结论。"
        )
    else:
        st.caption("精读总结完全在本地生成，每条摘录保留页码与 Chunk；不会调用 Kimi。")
        if run_reading:
            try:
                with st.spinner("正在从已解析正文中定位摘要、方法、结果和结论……"):
                    reading_result = service.generate_local_reading(record)
                st.success(
                    f"本地精读完成：{reading_result.evidence_count} 条可定位证据，"
                    f"覆盖 {len(reading_result.covered_sections)}/5 个栏目。"
                )
            except Exception as exc:
                st.error(f"精读生成失败：{exc}")
        report = (
            reading_result.report
            if reading_result is not None
            else service.load_report(record.paper_id)
        )
        if report:
            with st.expander("查看本地证据型精读", expanded=reading_result is not None):
                st.markdown(report)
            st.download_button(
                "下载 Markdown 精读报告",
                data=report,
                file_name=f"paper_{record.paper_id[:12]}_reading.md",
                mime="text/markdown",
                icon=":material/download:",
            )


def _render_pdf_preview(record: PaperRecord, *, height: int = 680) -> None:
    path = Path(record.file_path)
    if not path.is_file():
        st.warning("本地 PDF 路径已失效，请重新同步来源目录。")
        return
    if importlib.util.find_spec("streamlit_pdf") is None:
        st.info("PDF 在线预览依赖尚未安装；论文仍保存在本机，目录与标签功能不受影响。")
        return
    st.pdf(path, height=height, key=f"pdf_{record.paper_id}_{height}")


def _render_full_preview(catalog: PaperCatalog, record: PaperRecord) -> None:
    with st.container(horizontal=True, vertical_alignment="center"):
        if st.button(
            "返回论文工作台",
            icon=":material/arrow_back:",
            type="tertiary",
        ):
            st.session_state["academy_fullscreen_preview"] = False
            st.rerun()
        st.caption(f"论文 ID：{record.paper_id[:12]}")
    st.title(record.title)
    st.caption(
        f"导师：{record.teacher or '待识别'} · "
        f"状态：{STATUS_LABELS.get(record.ingestion_status, record.ingestion_status)}"
    )
    reading_report = PaperAnalysisService(catalog).load_report(record.paper_id)
    preview_options = (["精读报告"] if reading_report else []) + ["目录报告", "PDF 原文"]
    mode = st.segmented_control(
        "全页预览内容",
        preview_options,
        default=("精读报告" if reading_report else "目录报告"),
        required=True,
        key="academy_full_preview_mode",
    )
    if mode == "PDF 原文":
        _render_pdf_preview(record, height=1050)
    elif mode == "精读报告" and reading_report:
        with st.container(border=True):
            st.markdown(reading_report)
        st.download_button(
            "下载 Markdown 精读报告",
            data=reading_report,
            file_name=f"paper_{record.paper_id[:12]}_reading.md",
            mime="text/markdown",
            icon=":material/download:",
        )
    else:
        report = _report_markdown(record, catalog.list_tags(record.paper_id))
        with st.container(border=True):
            st.markdown(report)
        st.download_button(
            "下载 Markdown 目录报告",
            data=report,
            file_name=f"paper_{record.paper_id[:12]}_catalog.md",
            mime="text/markdown",
            icon=":material/download:",
        )


def _render_teacher_browser(
    catalog: PaperCatalog,
    *,
    query: str,
    status: str,
) -> None:
    total_papers = catalog.count_search(query=query, ingestion_status=status)
    teacher_count = catalog.count_teacher_facets(
        query=query,
        ingestion_status=status,
    )
    page_count = max(1, math.ceil(teacher_count / TEACHERS_PER_PAGE))
    page = st.pagination(
        page_count,
        key="academy_teacher_page",
        max_visible_pages=5,
        width="stretch",
    )
    facets = catalog.teacher_facets(
        query=query,
        ingestion_status=status,
        limit=TEACHERS_PER_PAGE,
        offset=(page - 1) * TEACHERS_PER_PAGE,
    )
    st.caption(
        f"匹配 {total_papers} 篇 · {teacher_count} 位导师 · "
        f"当前第 {page}/{page_count} 页"
    )
    if not facets:
        st.info("没有找到匹配论文。")
        return
    for facet in facets:
        teacher = facet["teacher"]
        teacher_label = teacher or "导师待识别"
        expander = st.expander(
            f"{teacher_label} · {facet['paper_count']} 篇",
            icon=":material/person:",
            key=f"teacher_{teacher_label}",
            on_change="rerun",
        )
        if not expander.open:
            continue
        with expander:
            if teacher:
                records = catalog.search(
                    query=query,
                    teacher=teacher,
                    exact_teacher=True,
                    ingestion_status=status,
                    limit=500,
                )
            else:
                records = [
                    record
                    for record in catalog.search(
                        query=query,
                        ingestion_status=status,
                        limit=500,
                    )
                    if not record.teacher
                ]
            for record in records:
                selected = record.paper_id == st.session_state.get(
                    "academy_selected_paper_id"
                )
                if st.button(
                    record.title,
                    key=f"select_paper_{record.paper_id}",
                    type="primary" if selected else "tertiary",
                    icon=":material/article:",
                    width="stretch",
                    wrap=True,
                ):
                    st.session_state["academy_selected_paper_id"] = record.paper_id
                    st.session_state["academy_fullscreen_preview"] = False
                    st.rerun()
                st.caption(
                    STATUS_LABELS.get(record.ingestion_status, record.ingestion_status)
                )


def render_academy_page() -> None:
    database_path = _catalog_path()
    library_root = _library_root()
    try:
        catalog = get_paper_catalog(database_path)
        service = get_library_service(database_path)
        analysis_service = get_analysis_service(database_path)
    except Exception as exc:
        st.error(f"论文目录数据库无法打开：{exc}")
        st.stop()

    selected_id = st.session_state.get("academy_selected_paper_id")
    selected = catalog.get(selected_id) if selected_id else None
    if st.session_state.get("academy_fullscreen_preview") and selected is not None:
        _render_full_preview(catalog, selected)
        return

    st.title("院校端 · 论文成果工作台")
    st.caption("按导师浏览论文，系统批量解析正文；你只需复核冲突和低置信度结果。")

    metric_columns = st.columns(4)
    metric_columns[0].metric("论文总数", catalog.count())
    metric_columns[1].metric("待审核标签", catalog.count_tags(review_status="suggested"))
    metric_columns[2].metric("已确认标签", catalog.count_tags(review_status="confirmed"))
    metric_columns[3].metric("本地来源目录", "可用" if library_root.is_dir() else "未配置")

    left, center, right = st.columns([0.32, 0.43, 0.30], gap="medium")
    with left:
        st.subheader("论文来源库")
        with st.container(horizontal=True):
            _render_sync_panel(service, library_root)
            _render_upload_panel(service)
            _render_parse_panel(get_ingestion_service(database_path))
            _render_index_panel(catalog)
        query = st.text_input(
            "搜索导师、作者、题名或标签",
            placeholder="支持模糊搜索",
            key="academy_search_query",
        )
        status = st.selectbox(
            "处理状态",
            options=[""] + sorted(INGESTION_STATUSES),
            format_func=lambda value: "全部状态" if not value else STATUS_LABELS[value],
            key="academy_status_filter",
        )
        st.caption(
            "“已登记，待解析正文”表示系统已经找到 PDF，接下来会自动抽取正文、"
            "页码和标签；不是要求你手工补齐。"
        )
        _render_teacher_browser(catalog, query=query, status=status)
    with center:
        st.subheader("论文工作台")
        if selected is None:
            st.info("请先从左侧选择一篇论文。")
        else:
            st.markdown(f"### {selected.title}")
            st.caption(
                f"导师：{selected.teacher or '待补充'} · "
                f"状态：{STATUS_LABELS.get(selected.ingestion_status, selected.ingestion_status)} · "
                f"ID：{selected.paper_id[:12]}"
            )
            _render_metadata_editor(catalog, selected)
            tags = _render_tag_editor(catalog, selected)
            _render_analysis_actions(analysis_service, selected)

    with right:
        st.subheader("报告与原文预览")
        if selected is None:
            st.info("选择论文后在这里预览标签报告和 PDF 原文。")
        else:
            tags = catalog.list_tags(selected.paper_id)
            reading_report = analysis_service.load_report(selected.paper_id)
            if st.button(
                "打开全页预览",
                icon=":material/open_in_full:",
                width="stretch",
            ):
                st.session_state["academy_fullscreen_preview"] = True
                st.rerun()
            preview_options = (["精读报告"] if reading_report else []) + [
                "目录报告",
                "PDF 原文",
            ]
            preview_mode = st.segmented_control(
                "预览内容",
                preview_options,
                default="精读报告" if reading_report else "目录报告",
                required=True,
                label_visibility="collapsed",
                width="stretch",
                key="academy_preview_mode",
            )
            if preview_mode == "PDF 原文":
                _render_pdf_preview(selected)
            elif preview_mode == "精读报告" and reading_report:
                with st.container(border=True, height=620):
                    st.markdown(reading_report)
                st.download_button(
                    "下载 Markdown 精读报告",
                    data=reading_report,
                    file_name=f"paper_{selected.paper_id[:12]}_reading.md",
                    mime="text/markdown",
                    width="stretch",
                )
            else:
                report = _report_markdown(selected, tags)
                with st.container(border=True, height=620):
                    st.markdown(report)
                st.download_button(
                    "下载 Markdown 目录报告",
                    data=report,
                    file_name=f"paper_{selected.paper_id[:12]}_catalog.md",
                    mime="text/markdown",
                    width="stretch",
                )
