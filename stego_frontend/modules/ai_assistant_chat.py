# -*- coding: utf-8 -*-
"""FastGPT AI assistant chat: sidebar config + chat UI + API call."""
from __future__ import annotations

import os
import re
import uuid
from typing import Any

import requests
import streamlit as st


def init_state() -> None:
    """Initialize Streamlit session state for AI chat."""
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    if "fastgpt_api_key" not in st.session_state:
        st.session_state.fastgpt_api_key = os.getenv("FASTGPT_API_KEY", "").strip()

    if "fastgpt_base_url" not in st.session_state:
        st.session_state.fastgpt_base_url = os.getenv(
            "FASTGPT_BASE_URL", "https://cloud.fastgpt.io/api"
        ).strip()

    if "fastgpt_chat_id" not in st.session_state:
        st.session_state.fastgpt_chat_id = ""


def _build_chat_completions_url(base_url: str) -> str:
    """Build FastGPT /v1/chat/completions URL from base."""
    b = base_url.strip().rstrip("/")
    if not b:
        raise ValueError("Base URL is empty")

    lowered = b.lower()
    if lowered.endswith("/chat/completions"):
        return b
    if lowered.endswith("/api/v1"):
        return f"{b}/chat/completions"
    if lowered.endswith("/v1"):
        return f"{b}/chat/completions"
    if lowered.endswith("/api"):
        return f"{b}/v1/chat/completions"
    return f"{b}/api/v1/chat/completions"


def _normalize_messages_for_api(raw: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Keep only user/assistant/system with string content."""
    roles = {"user", "assistant", "system"}
    out: list[dict[str, str]] = []
    for m in raw:
        role = m.get("role")
        content = m.get("content")
        if role not in roles or not isinstance(content, str):
            continue
        text = content.strip()
        if not text:
            continue
        out.append({"role": str(role), "content": text})
    return out


def call_ai_assistant(query: str) -> str:
    """POST to FastGPT chat completions; return assistant text."""
    api_key = (st.session_state.get("fastgpt_api_key") or "").strip()
    base_url = (st.session_state.get("fastgpt_base_url") or "").strip()
    if not api_key:
        return "\u8bf7\u5728\u4fa7\u8fb9\u680f\u586b\u5199 FastGPT \u5e94\u7528 API Key\u3002"
    if not base_url:
        return "\u8bf7\u5728\u4fa7\u8fb9\u680f\u586b\u5199 Base URL\u3002"

    url = _build_chat_completions_url(base_url)
    history = _normalize_messages_for_api(st.session_state.get("chat_messages") or [])
    messages = history + [{"role": "user", "content": query.strip()}]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    chat_id = (st.session_state.get("fastgpt_chat_id") or "").strip()
    if chat_id:
        api_messages: list[dict[str, str]] = [{"role": "user", "content": query.strip()}]
    else:
        api_messages = messages

    payload: dict[str, Any] = {"stream": False, "detail": False, "messages": api_messages}
    if chat_id:
        payload["chatId"] = chat_id

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = ""
        if exc.response is not None:
            body = exc.response.text.strip()
        if body:
            return f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}\n\n\u670d\u52a1\u7aef\u54cd\u5e94\uff1a{body}"
        return f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}"
    except requests.RequestException as exc:
        return f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}"

    try:
        data = resp.json()
    except ValueError:
        return "\u670d\u52a1\u7aef\u8fd4\u56de\u4e0d\u662f\u5408\u6cd5 JSON\u3002"

    try:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str) and content.strip():
            return content
    except (KeyError, IndexError, TypeError):
        pass

    return f"\u672a\u80fd\u8bc6\u522b\u7684\u54cd\u5e94\u683c\u5f0f\uff1a{data!r}"


def render_sidebar() -> None:
    """FastGPT settings and chat actions in sidebar."""
    st.sidebar.header("FastGPT \u914d\u7f6e")
    st.sidebar.text_input(
        "API Key\uff08\u5e94\u7528\u4e13\u5c5e\uff09",
        key="fastgpt_api_key",
        type="password",
        help=(
            "FastGPT \u5e94\u7528\u4e13\u5c5e API Key\uff08Bearer\uff09\u3002"
            "\u4e5f\u53ef\u901a\u8fc7\u73af\u5883\u53d8\u91cf FASTGPT_API_KEY \u6ce8\u5165\u3002"
        ),
    )
    st.sidebar.text_input(
        "Base URL",
        key="fastgpt_base_url",
        help=(
            "\u4f8b\u5982 https://cloud.fastgpt.io/api \u6216\u81ea\u5efa\u57df\u540d\uff0c"
            "\u7a0b\u5e8f\u4f1a\u81ea\u52a8\u62fc\u63a5 /v1/chat/completions\u3002"
        ),
    )
    st.sidebar.text_input(
        "chatId\uff08\u53ef\u9009\uff09",
        key="fastgpt_chat_id",
        help=(
            "\u7559\u7a7a\u7528\u672c\u5730\u5bf9\u8bdd\u5386\u53f2\u4f5c\u4e3a\u4e0a\u4e0b\u6587\uff1b"
            "\u586b\u5199\u5219\u542f\u7528 FastGPT \u670d\u52a1\u7aef\u8bb0\u5fc6\uff08\u5efa\u8bae\u552f\u4e00\uff09\u3002"
        ),
    )

    st.sidebar.divider()
    if st.sidebar.button("\u6e05\u7a7a\u5bf9\u8bdd", use_container_width=True):
        st.session_state.chat_messages = []
        st.session_state.fastgpt_chat_id = ""
        st.rerun()

    if st.sidebar.button("\u65b0\u5efa chatId\uff08\u670d\u52a1\u7aef\u8bb0\u5fc6\uff09", use_container_width=True):
        st.session_state.fastgpt_chat_id = uuid.uuid4().hex[:24]
        st.session_state.chat_messages = []
        st.rerun()


def render_chat_page() -> None:
    """Chat layout: history + bottom input."""
    st.title("AI \u52a9\u6559\u95ee\u7b54")
    st.caption("\u57fa\u4e8e FastGPT \u7684\u5bf9\u8bdd\u5f0f\u52a9\u6559")

    for msg in st.session_state.chat_messages:
        role = msg.get("role", "user")
        with st.chat_message(role):
            st.markdown(msg.get("content", ""))

    user_text = st.chat_input("\u8bf7\u8f93\u5165\u95ee\u9898\uff0c\u6309 Enter \u53d1\u9001\u2026")
    if not user_text:
        return

    cleaned = re.sub(r"\s+", " ", user_text).strip()
    if not cleaned:
        return

    with st.chat_message("user"):
        st.markdown(cleaned)

    with st.chat_message("assistant"):
        with st.spinner("\u52a9\u6559\u601d\u8003\u4e2d\u2026"):
            reply = call_ai_assistant(cleaned)
        st.markdown(reply)

    st.session_state.chat_messages.append({"role": "user", "content": cleaned})
    st.session_state.chat_messages.append({"role": "assistant", "content": reply})
