# -*- coding: utf-8 -*-
"""Streamlit authentication UI and Django API helpers."""
from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st


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
    # Docker 内可用 django 主机名，本地调试常见 localhost。
    if "django:8000" in base:
        out.append(base.replace("django:8000", "127.0.0.1:8000"))
        out.append(base.replace("django:8000", "localhost:8000"))
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

    errors: list[str] = []
    for base_url in _candidate_base_urls():
        url = f"{base_url}{path}"
        try:
            resp = requests.request(
                method=method.upper(),
                url=url,
                headers=headers,
                json=json_data,
                timeout=timeout,
            )
            payload: Any
            try:
                payload = resp.json()
            except ValueError:
                payload = {"detail": resp.text.strip()}
            if resp.status_code >= 400:
                detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
                return {"ok": False, "status_code": resp.status_code, "error": detail, "data": payload}
            return {"ok": True, "status_code": resp.status_code, "data": payload}
        except requests.RequestException as exc:
            errors.append(str(exc))
    return {"ok": False, "status_code": 0, "error": "; ".join(errors) or "请求失败", "data": None}


def _hydrate_current_user() -> None:
    token = (st.session_state.get("auth_token") or "").strip()
    if not token:
        return
    result = api_request("GET", "/auth/me", with_auth=True)
    if result["ok"]:
        st.session_state.current_user = result["data"]
    else:
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
    st.sidebar.header("账户")
    st.sidebar.text_input("后端 API Base URL", key="platform_api_base_url")
    user = st.session_state.get("current_user")
    if user:
        st.sidebar.success(f"已登录：{user.get('username', '-')}")
        st.sidebar.caption(
            "超级管理员" if user.get("is_superuser") else "普通用户"
        )
        if st.sidebar.button("退出登录", use_container_width=True):
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

    st.title("用户登录")
    login_tab, register_tab = st.tabs(["登录", "注册"])

    with login_tab:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", use_container_width=True)
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
            submitted = st.form_submit_button("注册并登录", use_container_width=True)
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
