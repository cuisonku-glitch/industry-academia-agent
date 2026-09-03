"""Backward-compatible Streamlit entry point.

Older documentation and bookmarks launched this file directly. Keep that command
working by delegating to the canonical multipage router.
"""

from __future__ import annotations

import runpy
from pathlib import Path


ROUTER_PATH = Path(__file__).resolve().with_name("streamlit_app.py")
runpy.run_path(str(ROUTER_PATH), run_name="__main__")
