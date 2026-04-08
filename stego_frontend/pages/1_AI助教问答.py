# -*- coding: utf-8 -*-
"""AI assistant chat page (FastGPT)."""
import streamlit as st

from stego_frontend.modules import ai_assistant_chat


def main() -> None:
    st.set_page_config(
        page_title="AI \u52a9\u6559\u95ee\u7b54",
        page_icon="\U0001f4ac",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ai_assistant_chat.init_state()
    ai_assistant_chat.render_sidebar()
    ai_assistant_chat.render_chat_page()


if __name__ == "__main__":
    main()
