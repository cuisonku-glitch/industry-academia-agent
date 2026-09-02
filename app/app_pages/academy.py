"""Academy workbench page."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


APP_DIRECTORY = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_DIRECTORY.parent
for path in (PROJECT_ROOT, APP_DIRECTORY):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from academy_page import render_academy_page


with st.sidebar:
    st.title(":material/hub: 产学研 Agent")
    st.caption("本地论文、目录数据库和解析结果不会随 Git 提交上传。")

render_academy_page()
