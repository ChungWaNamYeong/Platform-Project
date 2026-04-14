# -*- coding: utf-8 -*-
"""Streamlit home: entry to AI assistant and experiment modules."""
import streamlit as st

from stego_frontend.modules import auth
from stego_frontend.modules import branding


def main() -> None:
    st.set_page_config(
        page_title="\u4fe1\u606f\u9690\u85cf\u5b9e\u9a8c\u5e73\u53f0",
        page_icon="\U0001f3e0",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    auth.require_login()
    user = st.session_state.get("current_user") or {}

    branding.render_main_logo_title_centered()
    st.write("\u8bf7\u9009\u62e9\u8981\u8fdb\u5165\u7684\u6a21\u5757\uff1a")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("AI \u52a9\u6559\u95ee\u7b54")
        st.write(
            "\u57fa\u4e8e FastGPT \u7684\u5bf9\u8bdd\u5f0f\u52a9\u6559\uff0c"
            "\u652f\u6301\u5bf9\u8bdd\u4e0a\u4e0b\u6587\u8bb0\u5fc6\u3002"
        )
        # \u4e0d\u4f20 icon\uff1a\u5404\u73af\u5883\u5bf9 emoji \u6821\u9a8c\u4e0d\u4e00\uff0c\u907f\u514d\u62a5\u9519
        st.page_link(
            "pages/1_AI\u52a9\u6559\u95ee\u7b54.py",
            label="\u8fdb\u5165 AI \u52a9\u6559",
        )

    with col2:
        st.subheader("\u5b9e\u9a8c\u6a21\u5757\uff08\u9884\u7559\uff09")
        st.write(
            "\u9884\u7559\u4fe1\u606f\u9690\u85cf\u5b9e\u9a8c\u5165\u53e3\uff0c"
            "\u540e\u7eed\u53ef\u63a5\u5165\u56fe\u50cf/\u97f3\u9891\u9690\u5199\u7b49\u5b9e\u9a8c\u3002"
        )
        st.page_link(
            "pages/2_\u5b9e\u9a8c\u6a21\u5757.py",
            label="\u8fdb\u5165 \u5b9e\u9a8c\u6a21\u5757",
        )

    if user.get("is_superuser"):
        st.divider()
        st.subheader("\u7528\u6237\u7ba1\u7406")
        st.write("\u4ec5\u8d85\u7ea7\u7ba1\u7406\u5458\u53ef\u8bbf\u95ee\u3002")
        st.page_link(
            "pages/3_\u7528\u6237\u7ba1\u7406.py",
            label="\u8fdb\u5165 \u7528\u6237\u7ba1\u7406",
        )

    st.sidebar.info(
        "\u4e5f\u53ef\u4ee5\u901a\u8fc7\u5de6\u4fa7\u9875\u9762\u5bfc\u822a\u5207\u6362\u6a21\u5757\u3002"
    )


if __name__ == "__main__":
    main()
