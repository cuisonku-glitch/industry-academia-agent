"""Streamlit router with native top navigation."""

from __future__ import annotations

from pathlib import Path

import streamlit as st


APP_DIRECTORY = Path(__file__).resolve().parent

st.set_page_config(
    page_title="产学研 Agent",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="expanded",
)

page = st.navigation(
    [
        st.Page(
            APP_DIRECTORY / "app.py",
            title="企业端 · 组合方案",
            icon=":material/factory:",
            default=True,
        ),
        st.Page(
            APP_DIRECTORY / "app_pages" / "academy.py",
            title="院校端 · 成果对接",
            icon=":material/school:",
        ),
        st.Page(
            APP_DIRECTORY / "app_pages" / "lineage.py",
            title="谱系版图",
            icon=":material/account_tree:",
        ),
    ],
    position="top",
)
page.run()
