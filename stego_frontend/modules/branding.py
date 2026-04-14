# -*- coding: utf-8 -*-
"""Shared logo / title assets for Streamlit pages."""
from __future__ import annotations

import base64
import html
from pathlib import Path

import streamlit as st

FRONTEND_ROOT = Path(__file__).resolve().parent.parent
LOGO_TITLE_PATH = FRONTEND_ROOT / "image" / "logo&title.png"
LOGO_PATH = FRONTEND_ROOT / "image" / "logo.png"

# Title row: Streamlit h1 is ~2.75rem; logo slightly taller for visual balance.
_TITLE_ROW_FONT_REM = 2.75
_LOGO_ROW_HEIGHT_REM = 3.15


def _logo_png_data_uri() -> str | None:
    if not LOGO_PATH.is_file():
        return None
    raw = LOGO_PATH.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def render_sidebar_brand() -> None:
    if not LOGO_TITLE_PATH.is_file():
        st.sidebar.caption("品牌图未找到：image/logo&title.png")
        return
    logo_cmd = getattr(st, "logo", None)
    if callable(logo_cmd):
        # Renders above multipage sidebar navigation; wide image scales to sidebar width.
        kwargs: dict = {
            "image": str(LOGO_TITLE_PATH),
            "size": "large",
        }
        if LOGO_PATH.is_file():
            kwargs["icon_image"] = str(LOGO_PATH)
        logo_cmd(**kwargs)
    else:
        st.sidebar.image(str(LOGO_TITLE_PATH), use_container_width=True)


def render_main_logo_title_centered() -> None:
    if not LOGO_TITLE_PATH.is_file():
        st.caption("品牌图未找到：image/logo&title.png")
        return
    left, mid, right = st.columns([1, 3, 1])
    with mid:
        st.image(str(LOGO_TITLE_PATH), use_container_width=True)


def render_title_with_logo_left(title: str) -> None:
    """Single header row: logo on the left, title on the right, vertically centered."""
    data_uri = _logo_png_data_uri()
    if not data_uri:
        st.title(title)
        st.caption("Logo 未找到：image/logo.png")
        return
    safe_title = html.escape(title)
    st.markdown(
        f"""
<style>
.brand-title-row {{
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 0.75rem;
    margin: 0 0 1rem 0;
}}
.brand-title-row img {{
    height: {_LOGO_ROW_HEIGHT_REM}rem;
    width: auto;
    object-fit: contain;
    flex-shrink: 0;
}}
.brand-title-row h1 {{
    margin: 0;
    padding: 0;
    line-height: 1.15;
    font-size: {_TITLE_ROW_FONT_REM}rem;
    font-weight: 700;
}}
</style>
<div class="brand-title-row">
  <img src="{data_uri}" alt="" />
  <h1>{safe_title}</h1>
</div>
""",
        unsafe_allow_html=True,
    )