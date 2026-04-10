# -*- coding: utf-8 -*-
"""FastGPT AI assistant chat: config, API call, citations, and debug output."""
from __future__ import annotations

import html
import json
import os
import re
import uuid
from typing import Any

import requests
import streamlit as st

TARGET_DATASET_ID = "69d75c92248968454034e3f1"

WELCOME_MESSAGE = (
    "\u4f60\u597d\uff0c\u6211\u662f\u300a\u4fe1\u606f\u9690\u85cf\u300b"
    "\u8fd9\u95e8\u8bfe\u7a0b\u7684\u52a9\u6559\u8001\u5e08\uff0c"
    "\u8bfe\u5802\u4e0a\u6709\u5565\u4e0d\u4f1a\u7684\u95ee\u9898\uff0c"
    "\u6216\u8005\u4f60\u6709\u5565\u5b66\u4e60\u4e0a\u7684\u5c0f\u601d\u8003\uff0c"
    "\u90fd\u6b22\u8fce\u6765\u627e\u6211\u5440\uff01"
)


def init_state() -> None:
    """Initialize Streamlit session state for AI chat."""
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "fastgpt_last_response" not in st.session_state:
        st.session_state.fastgpt_last_response = None
    if "fastgpt_data_detail_cache" not in st.session_state:
        st.session_state.fastgpt_data_detail_cache = {}

    if "fastgpt_api_key" not in st.session_state:
        st.session_state.fastgpt_api_key = os.getenv(
            "FASTGPT_API_KEY",
            "fastgpt-w0dY1cleY525nDWmvgsKomKv4SVpKc5Z0W5q1jXqVNm0vxumxcmpufHh",
        ).strip()

    if "fastgpt_base_url" not in st.session_state:
        st.session_state.fastgpt_base_url = os.getenv(
            "FASTGPT_BASE_URL", "https://cloud.fastgpt.io/api"
        ).strip()

    if "fastgpt_chat_id" not in st.session_state:
        st.session_state.fastgpt_chat_id = ""


def _build_chat_completions_url(base_url: str) -> str:
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


def _extract_citations(data: dict[str, Any]) -> list[dict[str, str]]:
    """Extract quoteList from responseData modules."""
    refs: list[dict[str, str]] = []
    seen: set[str] = set()

    # FastGPT detail response may only include quote id/source metadata in quoteList.
    # We can backfill detailed cite content from historyPreview <Cites> blocks.
    cite_content_map = _extract_cite_content_map(data)

    response_data = data.get("responseData")
    if not isinstance(response_data, list):
        return refs

    for module in response_data:
        if not isinstance(module, dict):
            continue
        quote_list = module.get("quoteList")
        if not isinstance(quote_list, list):
            continue
        for quote in quote_list:
            if not isinstance(quote, dict):
                continue
            quote_id = str(quote.get("id", "")).strip()
            if quote_id and quote_id in seen:
                continue
            if quote_id:
                seen.add(quote_id)

            q = str(quote.get("q", "")).strip()
            a = str(quote.get("a", "")).strip()
            source = str(quote.get("source", "")).strip()
            content = str(quote.get("content", "")).strip()
            if not content and quote_id:
                content = cite_content_map.get(quote_id, "")

            refs.append(
                {
                    "id": quote_id,
                    "q": q,
                    "a": a,
                    "source": source,
                    "content": content,
                    "sourceName": str(quote.get("sourceName", "")).strip(),
                    "sourceId": str(quote.get("sourceId", "")).strip(),
                    "chunkIndex": str(quote.get("chunkIndex", "")).strip(),
                    "datasetId": str(quote.get("datasetId", "")).strip(),
                }
            )
    return refs


def _build_api_root(base_url: str) -> str:
    """Build FastGPT API root, e.g. https://xxx/api."""
    b = base_url.strip().rstrip("/")
    lowered = b.lower()

    if lowered.endswith("/api"):
        return b
    if lowered.endswith("/api/v1"):
        return b[: -len("/v1")]
    if lowered.endswith("/api/v1/chat/completions"):
        return b[: -len("/v1/chat/completions")]
    if lowered.endswith("/v1/chat/completions"):
        return b[: -len("/v1/chat/completions")] + "/api"
    if lowered.endswith("/v1"):
        return b[: -len("/v1")] + "/api"
    if lowered.endswith("/chat/completions"):
        return b[: -len("/chat/completions")]
    return f"{b}/api"


def _fetch_dataset_data_detail(
    *,
    api_key: str,
    base_url: str,
    data_id: str,
) -> dict[str, Any] | None:
    """Fetch one data record by id via /core/dataset/data/detail."""
    if not data_id:
        return None

    cache: dict[str, Any] = st.session_state.get("fastgpt_data_detail_cache", {})
    if data_id in cache:
        return cache[data_id]

    api_root = _build_api_root(base_url)
    url = f"{api_root}/core/dataset/data/detail?id={data_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        cache[data_id] = None
        st.session_state.fastgpt_data_detail_cache = cache
        return None

    data = payload.get("data")
    cache[data_id] = data if isinstance(data, dict) else None
    st.session_state.fastgpt_data_detail_cache = cache
    return cache[data_id]


def _enrich_citations_with_dataset_data(
    citations: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str,
) -> list[dict[str, str]]:
    """Backfill citation content from dataset data detail (q/a)."""
    enriched: list[dict[str, str]] = []
    for c in citations:
        item = dict(c)
        data_id = item.get("id", "").strip()
        dataset_id = item.get("datasetId", "").strip()

        # Only fetch target dataset records as requested.
        if data_id and (not dataset_id or dataset_id == TARGET_DATASET_ID):
            detail = _fetch_dataset_data_detail(
                api_key=api_key,
                base_url=base_url,
                data_id=data_id,
            )
            if isinstance(detail, dict):
                q = str(detail.get("q", "")).strip()
                a = str(detail.get("a", "")).strip()
                if q and not item.get("q"):
                    item["q"] = q
                if a and not item.get("a"):
                    item["a"] = a
                qa_content = q + (f"\n\n{a}" if a else "")
                if qa_content:
                    item["content"] = qa_content
                src_name = str(detail.get("sourceName", "")).strip()
                if src_name:
                    item["sourceName"] = src_name
                src_id = str(detail.get("sourceId", "")).strip()
                if src_id:
                    item["sourceId"] = src_id
        enriched.append(item)
    return enriched


def _extract_cite_content_map(data: dict[str, Any]) -> dict[str, str]:
    """Parse chatNode.historyPreview <Cites> blocks and map id -> content."""
    mapping: dict[str, str] = {}
    response_data = data.get("responseData")
    if not isinstance(response_data, list):
        return mapping

    for module in response_data:
        if not isinstance(module, dict):
            continue
        history_preview = module.get("historyPreview")
        if not isinstance(history_preview, list):
            continue
        for item in history_preview:
            if not isinstance(item, dict):
                continue
            value = item.get("value")
            if not isinstance(value, str):
                continue
            if "<Cites>" not in value or "</Cites>" not in value:
                continue

            cites_text = value.split("<Cites>", 1)[1].split("</Cites>", 1)[0]
            # FastGPT often separates cite json blocks by "------"
            blocks = [b.strip() for b in cites_text.split("------") if b.strip()]
            for block in blocks:
                try:
                    obj = json.loads(block)
                except Exception:
                    continue
                cite_id = str(obj.get("id", "")).strip()
                content = str(obj.get("content", "")).strip()
                if cite_id and content and cite_id not in mapping:
                    mapping[cite_id] = content
    return mapping


def _build_reference_marker(citations: list[dict[str, str]]) -> str:
    """Build numbered markers [1][2]... with custom hover cards."""
    if not citations:
        return ""

    tags: list[str] = []
    for i, c in enumerate(citations, 1):
        source_name = c.get("sourceName", "").strip()
        source = c.get("source", "").strip()
        source_id = c.get("sourceId", "").strip()
        content = c.get("content", "").strip()

        source_text = source_name or source or source_id or "Unknown Source"
        content_text = content or "(No content returned by API)"

        tags.append(
            '<span class="citation-wrap">'
            f'<span class="citation-tag">[{i}]</span>'
            '<span class="citation-card">'
            f'<span class="citation-source">Source: {html.escape(source_text)}</span>'
            f'<span class="citation-content">{html.escape(content_text)}</span>'
            "</span>"
            "</span>"
        )
    return "".join(tags)


def _render_assistant_with_citation(answer: str, citations: list[dict[str, str]]) -> None:
    safe_answer = html.escape(answer).replace("\n", "<br>")
    marker = _build_reference_marker(citations)
    st.markdown(f"{safe_answer}{marker}", unsafe_allow_html=True)


def _render_citation_styles() -> None:
    """Render shared CSS for citation hover cards."""
    st.markdown(
        """
<style>
.citation-wrap {
  position: relative;
  display: inline-block;
  margin-left: 4px;
}
.citation-tag {
  cursor: help;
  font-weight: 700;
  color: #1f6feb;
}
.citation-card {
  display: none;
  position: absolute;
  top: 1.6em;
  left: 0;
  z-index: 9999;
  width: min(46vw, 560px);
  max-width: 46vw;
  background: var(--background-color, #ffffff);
  color: var(--text-color, #24292f);
  border: 1px solid rgba(128, 128, 128, 0.35);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  padding: 10px 12px;
  white-space: normal;
}
.citation-wrap:hover .citation-card {
  display: block;
}
.citation-source {
  display: block;
  font-weight: 600;
  margin-bottom: 8px;
  word-break: break-word;
}
.citation-content {
  display: block;
  max-height: 300px;
  overflow: auto;
  line-height: 1.45;
  word-break: break-word;
}
</style>
        """,
        unsafe_allow_html=True,
    )


def call_ai_assistant(query: str) -> dict[str, Any]:
    """POST to FastGPT; return answer + citations + raw response."""
    api_key = (st.session_state.get("fastgpt_api_key") or "").strip()
    base_url = (st.session_state.get("fastgpt_base_url") or "").strip()
    if not api_key:
        return {
            "answer": "\u8bf7\u5728\u4fa7\u8fb9\u680f\u586b\u5199 FastGPT \u5e94\u7528 API Key\u3002",
            "citations": [],
            "raw_response": None,
        }
    if not base_url:
        return {
            "answer": "\u8bf7\u5728\u4fa7\u8fb9\u680f\u586b\u5199 Base URL\u3002",
            "citations": [],
            "raw_response": None,
        }

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

    # detail=true is required for responseData/quoteList.
    payload: dict[str, Any] = {"stream": False, "detail": True, "messages": api_messages}
    if chat_id:
        payload["chatId"] = chat_id

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        body = ""
        if exc.response is not None:
            body = exc.response.text.strip()
        text = f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}"
        if body:
            text += f"\n\n\u670d\u52a1\u7aef\u54cd\u5e94\uff1a{body}"
        return {"answer": text, "citations": [], "raw_response": {"error": body or text}}
    except requests.RequestException as exc:
        text = f"\u8bf7\u6c42\u5931\u8d25\uff1a{exc}"
        return {"answer": text, "citations": [], "raw_response": {"error": text}}

    try:
        data = resp.json()
    except ValueError:
        return {
            "answer": "\u670d\u52a1\u7aef\u8fd4\u56de\u4e0d\u662f\u5408\u6cd5 JSON\u3002",
            "citations": [],
            "raw_response": {"raw_text": resp.text},
        }

    citations = _extract_citations(data)
    citations = _enrich_citations_with_dataset_data(
        citations,
        api_key=api_key,
        base_url=base_url,
    )
    st.session_state.fastgpt_last_response = data

    answer = ""
    try:
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str):
            answer = content.strip()
    except (KeyError, IndexError, TypeError):
        answer = ""

    if not answer:
        answer = f"\u672a\u80fd\u8bc6\u522b\u7684\u54cd\u5e94\u683c\u5f0f\uff1a{data!r}"

    return {"answer": answer, "citations": citations, "raw_response": data}


def render_sidebar() -> None:
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
        st.session_state.fastgpt_last_response = None
        st.rerun()

    if st.sidebar.button("\u65b0\u5efa chatId\uff08\u670d\u52a1\u7aef\u8bb0\u5fc6\uff09", use_container_width=True):
        st.session_state.fastgpt_chat_id = uuid.uuid4().hex[:24]
        st.session_state.chat_messages = []
        st.session_state.fastgpt_last_response = None
        st.rerun()

    st.sidebar.divider()
    with st.sidebar.expander("\u6700\u65b0 API \u54cd\u5e94\uff08\u8c03\u8bd5\uff09", expanded=False):
        if st.session_state.fastgpt_last_response is None:
            st.caption("\u6682\u65e0\u8c03\u8bd5\u6570\u636e")
        else:
            st.json(st.session_state.fastgpt_last_response)


def render_chat_page() -> None:
    st.title("AI \u52a9\u6559\u95ee\u7b54")
    st.caption("\u57fa\u4e8e FastGPT \u7684\u5bf9\u8bdd\u5f0f\u52a9\u6559")
    _render_citation_styles()

    # Always show the configured assistant opening sentence at session start.
    if not st.session_state.chat_messages:
        st.session_state.chat_messages.append(
            {
                "role": "assistant",
                "content": WELCOME_MESSAGE,
                "citations": [],
                "raw_response": None,
            }
        )

    for msg in st.session_state.chat_messages:
        role = msg.get("role", "user")
        with st.chat_message(role):
            if role == "assistant":
                _render_assistant_with_citation(
                    msg.get("content", ""),
                    msg.get("citations", []),
                )
                raw = msg.get("raw_response")
                if raw is not None:
                    with st.expander("\u67e5\u770b\u8be5\u8f6e API \u539f\u59cb\u54cd\u5e94", expanded=False):
                        st.json(raw)
            else:
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
            result = call_ai_assistant(cleaned)
        answer = result.get("answer", "")
        citations = result.get("citations", [])
        raw_response = result.get("raw_response")

        _render_assistant_with_citation(answer, citations)
        with st.expander("\u67e5\u770b\u8be5\u8f6e API \u539f\u59cb\u54cd\u5e94", expanded=False):
            st.json(raw_response)

    st.session_state.chat_messages.append({"role": "user", "content": cleaned})
    st.session_state.chat_messages.append(
        {
            "role": "assistant",
            "content": answer,
            "citations": citations,
            "raw_response": raw_response,
        }
    )
