# -*- coding: utf-8 -*-
"""Experiment module placeholder page."""
import streamlit as st

from stego_frontend.modules import auth
from stego_frontend.modules import branding


def main() -> None:
    st.set_page_config(
        page_title="\u5b9e\u9a8c\u6a21\u5757\uff08\u9884\u7559\uff09",
        page_icon="\U0001f9ea",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    auth.require_login()

    branding.render_title_with_logo_left("\u5b9e\u9a8c\u6a21\u5757\uff08\u9884\u7559\u5165\u53e3\uff09")
    st.info(
        "\u540e\u7eed\u5c06\u5728\u6b64\u63a5\u5165\u4fe1\u606f\u9690\u85cf\u76f8\u5173\u5b9e\u9a8c\uff0c"
        "\u4f8b\u5982\u56fe\u7247\u9690\u5199\u3001\u97f3\u9891\u9690\u5199\u548c\u9c81\u68d2\u6027\u6d4b\u8bd5\u7b49\u3002"
    )


if __name__ == "__main__":
    main()
