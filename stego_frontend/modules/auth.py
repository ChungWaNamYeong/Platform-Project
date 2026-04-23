# -*- coding: utf-8 -*-
"""Streamlit authentication UI and Django API helpers."""
from __future__ import annotations

import os
import time
from typing import Any

import requests
import streamlit as st

from stego_frontend.modules import branding


def _extract_api_error(payload: Any) -> str:
    """将后端返回的各种错误结构格式化为可读字符串。"""
    if payload is None:
        return "请求失败"
    if isinstance(payload, str):
        return payload.strip() or "请求失败"
    if isinstance(payload, list):
        parts = [str(item).strip() for item in payload if str(item).strip()]
        return "; ".join(parts) or "请求失败"
    if isinstance(payload, dict):
        if payload.get("detail"):
            return str(payload["detail"]).strip() or "请求失败"
        parts: list[str] = []
        for key, value in payload.items():
            value_text = _extract_api_error(value)
            if not value_text:
                continue
            if key in {"non_field_errors", "__all__"}:
                parts.append(value_text)
            else:
                parts.append(f"{key}: {value_text}")
        return "; ".join(parts) or "请求失败"
    return str(payload).strip() or "请求失败"


def _classify_connection_issue(error_text: str) -> str:
    """将 requests 异常文本归类成简短技术原因。"""
    text = (error_text or "").lower()
    if (
        "nameresolutionerror" in text
        or "name or service not known" in text
        or "failed to resolve" in text
        or "getaddrinfo failed" in text
    ):
        return "DNS 解析失败（NameResolutionError）"
    if "connection refused" in text or "winerror 10061" in text:
        return "连接被拒绝（Connection refused）"
    if "read timed out" in text or "connect timeout" in text or "timed out" in text:
        return "连接超时（Timeout）"
    if "ssl" in text or "certificate" in text:
        return "TLS/证书握手失败"
    if "connection aborted" in text or "connection reset" in text or "winerror 10054" in text:
        return "连接被重置（Connection reset）"
    return "网络请求异常"


def _summarize_connection_errors(errors: list[str]) -> str:
    """将多次连接失败压缩为简短可读的排障信息。"""
    if not errors:
        return "请求失败"
    reasons: list[str] = []
    for err in errors:
        try:
            base_url, raw = err.split(": ", 1)
        except ValueError:
            base_url, raw = "-", err
        reason = _classify_connection_issue(raw)
        item = f"{reason} @ {base_url}"
        if item not in reasons:
            reasons.append(item)
    brief = "；".join(reasons[:3])
    if len(reasons) > 3:
        brief += "；..."
    return f"请求失败（{brief}）"


def init_auth_state() -> None:
    if "platform_api_base_url" not in st.session_state:
        st.session_state.platform_api_base_url = os.getenv(
            "DJANGO_API_BASE_URL",
            "http://django:8000/api",
        ).strip()
    if "auth_token" not in st.session_state:
        st.session_state.auth_token = ""
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "auth_ready_checked" not in st.session_state:
        st.session_state.auth_ready_checked = False


def _normalized_base_url() -> str:
    return (st.session_state.get("platform_api_base_url") or "").strip().rstrip("/")


def _candidate_base_urls() -> list[str]:
    base = _normalized_base_url()
    out = [base] if base else []
    preferred = (st.session_state.get("platform_api_last_ok_base_url") or "").strip().rstrip("/")
    if preferred:
        out.insert(0, preferred)
    # 兼容容器内/宿主机两种访问方式，降低切页时偶发连接失败概率。
    if "django:8000" in base:
        out.append(base.replace("django:8000", "127.0.0.1:8000"))
        out.append(base.replace("django:8000", "localhost:8000"))
        out.append(base.replace("django:8000", "host.docker.internal:8000"))
    if "localhost:8000" in base:
        out.append(base.replace("localhost:8000", "django:8000"))
        out.append(base.replace("localhost:8000", "host.docker.internal:8000"))
    if "127.0.0.1:8000" in base:
        out.append(base.replace("127.0.0.1:8000", "django:8000"))
        out.append(base.replace("127.0.0.1:8000", "host.docker.internal:8000"))
    if "host.docker.internal:8000" in base:
        out.append(base.replace("host.docker.internal:8000", "django:8000"))
        out.append(base.replace("host.docker.internal:8000", "localhost:8000"))
        out.append(base.replace("host.docker.internal:8000", "127.0.0.1:8000"))
    return [x for i, x in enumerate(out) if x and x not in out[:i]]


def api_request(
    method: str,
    path: str,
    *,
    json_data: dict[str, Any] | None = None,
    with_auth: bool = True,
    timeout: int = 30,
) -> dict[str, Any]:
    token = (st.session_state.get("auth_token") or "").strip()
    headers = {"Content-Type": "application/json"}
    if with_auth and token:
        headers["Authorization"] = f"Token {token}"

    if not path.startswith("/"):
        path = f"/{path}"

    # 快速切页时容器网络可能短暂抖动；做轻量重试避免直接报连接失败。
    errors: list[str] = []
    max_rounds = 2
    for round_idx in range(max_rounds):
        for base_url in _candidate_base_urls():
            url = f"{base_url}{path}"
            try:
                request_timeout = max(3, min(timeout, 30))
                resp = requests.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    json=json_data,
                    timeout=request_timeout,
                )
                payload: Any
                try:
                    payload = resp.json()
                except ValueError:
                    payload = {"detail": resp.text.strip()}
                if resp.status_code >= 400:
                    detail = _extract_api_error(payload)
                    return {"ok": False, "status_code": resp.status_code, "error": detail, "data": payload}

                st.session_state.platform_api_last_ok_base_url = base_url
                return {"ok": True, "status_code": resp.status_code, "data": payload}
            except requests.RequestException as exc:
                errors.append(f"{base_url}: {exc}")

        if round_idx < max_rounds - 1:
            time.sleep(0.2)
    return {
        "ok": False,
        "status_code": 0,
        "error": _summarize_connection_errors(errors),
        "data": None,
    }


def _hydrate_current_user() -> None:
    token = (st.session_state.get("auth_token") or "").strip()
    if not token:
        return
    result = api_request("GET", "/auth/me", with_auth=True)
    if result["ok"]:
        st.session_state.current_user = result["data"]
        return

    # 仅在鉴权明确失败时清理本地登录态；网络抖动时保留会话避免“切页掉线”。
    if result.get("status_code") in {401, 403}:
        st.session_state.auth_token = ""
        st.session_state.current_user = None


def _logout_local() -> None:
    st.session_state.auth_token = ""
    st.session_state.current_user = None
    st.session_state.auth_ready_checked = False
    # 清理聊天缓存，避免跨用户残留。
    st.session_state.chat_messages = []
    st.session_state.chat_loaded_for_session = None
    st.session_state.active_chat_session_id = None


def render_auth_sidebar() -> None:
    branding.render_sidebar_brand()
    st.sidebar.header("账户")
    st.sidebar.text_input("后端 API Base URL", key="platform_api_base_url")
    user = st.session_state.get("current_user")
    if user:
        st.sidebar.success(f"已登录：{user.get('username', '-')}")
        st.sidebar.caption(
            "超级管理员" if user.get("is_superuser") else "普通用户"
        )
        if st.sidebar.button("退出登录", width="stretch"):
            api_request("POST", "/auth/logout", with_auth=True)
            _logout_local()
            st.rerun()
    else:
        st.sidebar.info("请先登录后使用平台功能")


def require_login() -> bool:
    init_auth_state()
    if not st.session_state.get("auth_ready_checked"):
        _hydrate_current_user()
        st.session_state.auth_ready_checked = True

    render_auth_sidebar()
    if st.session_state.get("current_user"):
        return True

    branding.render_main_logo_title_centered()
    st.title("用户登录")
    login_tab, register_tab = st.tabs(["登录", "注册"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", width="stretch")
        if submitted:
            result = api_request(
                "POST",
                "/auth/login",
                with_auth=False,
                json_data={"username": username, "password": password},
            )
            if result["ok"]:
                data = result["data"] or {}
                st.session_state.auth_token = data.get("token", "")
                st.session_state.current_user = data.get("user")
                st.success("登录成功")
                st.rerun()
            else:
                st.error(f"登录失败：{result['error']}")

    with register_tab:
        with st.form("register_form", clear_on_submit=True):
            username = st.text_input("用户名（注册）")
            email = st.text_input("邮箱")
            password = st.text_input("密码（至少8位）", type="password")
            student_id = st.text_input("学号（可选）")
            major = st.text_input("专业（可选）")
            grade = st.text_input("年级（可选）")
            submitted = st.form_submit_button("注册并登录", width="stretch")
        if submitted:
            payload = {
                "username": username,
                "password": password,
                "email": email,
                "student_id": student_id or None,
                "major": major,
                "grade": grade,
            }
            result = api_request("POST", "/auth/register", with_auth=False, json_data=payload)
            if result["ok"]:
                data = result["data"] or {}
                st.session_state.auth_token = data.get("token", "")
                st.session_state.current_user = data.get("user")
                st.success("注册成功，已自动登录")
                st.rerun()
            else:
                st.error(f"注册失败：{result['error']}")

    st.stop()
