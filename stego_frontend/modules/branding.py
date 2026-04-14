# -*- coding: utf-8 -*-
"""Shared logo / title assets for Streamlit pages."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

FRONTEND_ROOT = Path(__file__).resolve().parent.parent
LOGO_TITLE_PATH = FRONTEND_ROOT / "image" / "logo&title.png"
LOGO_PATH = FRONTEND_ROOT / "image" / "logo.png"

# Match Streamlit page title (h1) line height (~88px in default theme).
_TITLE_LOGO_PX = 88


def _inject_branding_css() -> None:
    """Re-inject every script run: Streamlit rebuilds the DOM on navigation; session-only inject loses rules."""
    st.markdown(
        """
<style>
/* st.logo → stretch to remaining sidebar header width (beside collapse control) */
section[data-testid="stSidebar"] [data-testid="stLogo"] {
  flex: 1 1 0 !important;
  min-width: 0 !important;
  width: auto !important;
  max-width: none !important;
  box-sizing: border-box !important;
  align-self: stretch !important;
}
section[data-testid="stSidebar"] [data-testid="stLogo"] a {
  display: block !important;
  width: 100% !important;
  max-width: 100% !important;
  box-sizing: border-box !important;
}
section[data-testid="stSidebar"] [data-testid="stLogo"] img {
  width: 100% !important;
  height: auto !important;
  max-width: 100% !important;
  max-height: none !important;
  object-fit: contain !important;
  display: block !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: nowrap !important;
  width: 100% !important;
  max-width: 100% !important;
  box-sizing: border-box !important;
  align-items: flex-start !important;
  gap: 0.25rem !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] img {
  width: 100% !important;
  height: auto !important;
  max-height: none !important;
  object-fit: contain !important;
  display: block !important;
}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] a {
  width: 100% !important;
  display: block !important;
}
[data-testid="collapsedControl"] img {
  width: auto !important;
  height: 2rem !important;
  max-width: 48px !important;
}
</style>
""",
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    _inject_branding_css()
    if not LOGO_TITLE_PATH.is_file():
        st.sidebar.caption("品牌图未找到：image/logo&title.png")
        return
    logo_cmd = getattr(st, "logo", None)
    if callable(logo_cmd):
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
    """Logo and title on one row (Streamlit columns), logo fixed ~88px — no fragile HTML/CSS flex."""
    if not LOGO_PATH.is_file():
        st.title(title)
        st.caption("Logo 未找到：image/logo.png")
        return
    col_logo, col_title = st.columns(
        [1, 12],
        gap="small",
        vertical_alignment="center",
    )
    with col_logo:
        st.image(str(LOGO_PATH), width=_TITLE_LOGO_PX)
    with col_title:
        st.title(title)
