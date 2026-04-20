# -*- coding: utf-8 -*-
"""实验模块页：登录后选择实验并控制沙箱生命周期。"""

from __future__ import annotations

import time
from typing import Any

import streamlit as st

from stego_frontend.modules import auth
from stego_frontend.modules import branding

EXPERIMENT_TOPICS = (
    "空域 LSB 隐写",
    "频域 DCT 隐写",
    "AI 水印检测",
)


def _set_feedback(level: str, message: str) -> None:
    st.session_state.lab_feedback = {"level": level, "message": message}


def _render_feedback() -> None:
    feedback = st.session_state.get("lab_feedback")
    if not feedback:
        return
    level = feedback.get("level")
    message = feedback.get("message", "")
    if level == "success":
        st.success(message)
    elif level == "warning":
        st.warning(message)
    else:
        st.error(message)


def _render_running_status(run: dict[str, Any] | None) -> None:
    """展示当前沙箱状态。"""
    if not run:
        st.warning("当前没有运行中的沙箱。")
        return

    st.success("沙箱运行中")
    st.write(f"容器 ID：`{run.get('container_id', '-')}`")
    st.write(f"实验课题：{run.get('experiment_topic', '-')}")
    st.write(f"访问端口：{run.get('web_port', '-')}")


def _load_status() -> dict[str, Any] | None:
    """从后端读取当前用户沙箱状态。"""
    result = auth.api_request("GET", "/labs/sandbox/status", with_auth=True, timeout=30)
    if not result["ok"]:
        st.error(f"读取沙箱状态失败：{result['error']}")
        return None
    return result["data"] or {}


def _start_sandbox(experiment_topic: str) -> None:
    """启动实验沙箱并展示启动进度。"""
    progress = st.progress(0, text="准备启动沙箱...")
    progress.progress(20, text="校验实验参数...")
    time.sleep(0.2)
    progress.progress(45, text="向后端提交启动请求...")

    result = auth.api_request(
        "POST",
        "/labs/sandbox/start",
        with_auth=True,
        json_data={"experiment_topic": experiment_topic},
        timeout=60,
    )
    if not result["ok"]:
        progress.progress(100, text="启动失败")
        payload = result.get("data") or {}
        hint = payload.get("hint")
        message = f"启动失败：{result['error']}"
        if hint:
            message = f"{message}\n\n排查建议：{hint}"
        _set_feedback("error", message)
        return

    progress.progress(80, text="容器已创建，读取状态...")
    time.sleep(0.2)
    progress.progress(100, text="启动完成")
    payload = result["data"] or {}
    run = payload.get("run") or {}
    if payload.get("reused"):
        _set_feedback("warning", "检测到你已有运行中的沙箱，已复用现有实例。")
    else:
        _set_feedback("success", "实验环境启动成功。")


def _stop_sandbox() -> None:
    """停止当前用户沙箱。"""
    result = auth.api_request("POST", "/labs/sandbox/stop", with_auth=True, timeout=60)
    if not result["ok"]:
        _set_feedback("error", f"停止失败：{result['error']}")
        return
    detail = (result.get("data") or {}).get("detail") or "沙箱已停止。"
    if "没有运行中的沙箱" in detail:
        _set_feedback("warning", detail)
    else:
        _set_feedback("success", detail)


def _admin_force_stop(run_id: int) -> None:
    """超级管理员按记录 ID 强制停止沙箱。"""
    result = auth.api_request(
        "POST",
        "/labs/sandbox/stop",
        with_auth=True,
        json_data={"run_id": run_id},
        timeout=120,
    )
    if not result["ok"]:
        _set_feedback("error", f"强制停止失败（记录 #{run_id}）：{result['error']}")
        return
    detail = (result.get("data") or {}).get("detail") or "已处理。"
    if "无需停止" in detail or "已不在运行" in detail:
        _set_feedback("warning", f"{detail}（记录 #{run_id}）")
    else:
        _set_feedback("success", f"{detail}（记录 #{run_id}）")


def _status_badge_html(status: str) -> str:
    """状态胶囊：圆角背景仅包裹文字，不占满整格。"""
    palette: dict[str, tuple[str, str]] = {
        "running": ("#065f46", "#d1fae5"),
        "starting": ("#1e40af", "#dbeafe"),
        "stopped": ("#4b5563", "#e5e7eb"),
        "failed": ("#991b1b", "#fee2e2"),
    }
    fg, bg = palette.get(status, ("#374151", "#f3f4f6"))
    safe = (status or "-").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        f'background:{bg};color:{fg};font-size:12px;font-weight:500;white-space:nowrap;">'
        f"{safe}</span>"
    )


def _short_container_id(cid: str | None, head: int = 12) -> str:
    if not cid:
        return "-"
    s = str(cid)
    if len(s) <= head + 3:
        return s
    return f"{s[:head]}…"


def _format_dt(value: Any) -> str:
    if not value:
        return "-"
    text = str(value).replace("T", " ")
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _render_admin_panel(user: dict[str, Any]) -> None:
    """超级管理员查看全局沙箱运行记录。"""
    if not user.get("is_superuser"):
        return

    st.divider()
    st.subheader("管理员沙箱视图")
    result = auth.api_request("GET", "/labs/sandbox/admin/runs", with_auth=True, timeout=30)
    if not result["ok"]:
        st.error(f"读取全局记录失败：{result['error']}")
        return
    runs = result["data"] or []
    if not runs:
        st.caption("当前没有可展示的沙箱记录。")
        return

    # 列宽比例：ID 约四位数宽度、时间列略宽、状态列为文字胶囊不占满格
    col_weights = [0.32, 0.95, 1.35, 0.68, 1.15, 0.36, 1.12, 1.12, 0.78]
    headers = (
        "ID",
        "用户",
        "课题",
        "状态",
        "容器",
        "端口",
        "开始时间",
        "停止时间",
        "操作",
    )
    header_cols = st.columns(col_weights, gap="small")
    for col, title in zip(header_cols, headers, strict=True):
        col.markdown(f"**{title}**")

    for item in runs:
        rid = item.get("id")
        status = str(item.get("status") or "")
        can_force_stop = status in {"running", "starting"}
        row_cols = st.columns(col_weights, gap="small")
        with row_cols[0]:
            st.caption(str(rid) if rid is not None else "-")
        with row_cols[1]:
            st.caption(str(item.get("username") or "-"))
        with row_cols[2]:
            st.caption(str(item.get("experiment_topic") or "-"))
        with row_cols[3]:
            st.markdown(_status_badge_html(status), unsafe_allow_html=True)
        with row_cols[4]:
            st.caption(_short_container_id(item.get("container_id")))
        with row_cols[5]:
            p = item.get("web_port")
            st.caption(str(p) if p is not None else "-")
        with row_cols[6]:
            st.caption(_format_dt(item.get("started_at")))
        with row_cols[7]:
            st.caption(_format_dt(item.get("stopped_at")))
        with row_cols[8]:
            if rid is not None and can_force_stop:
                if st.button("强制停止", key=f"admin_stop_run_{rid}", width="stretch"):
                    _admin_force_stop(int(rid))
                    st.rerun()
            elif rid is not None:
                st.caption("—")


def main() -> None:
    st.set_page_config(
        page_title="实验模块",
        page_icon="🧪",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    auth.require_login()

    # 显式检查登录态，满足“状态检查基于 st.session_state”的要求。
    current_user = st.session_state.get("current_user")
    if not current_user:
        st.error("请先登录后再进入实验模块。")
        st.stop()

    branding.render_title_with_logo_left("实验台")
    st.caption("流程：登录 → 选择实验 → 启动沙箱 → 停止沙箱")
    _render_feedback()

    st.info(
        "实验沙箱镜像基于 `python:3.12-slim`，并预装 `opencv-python`、`scipy`、`stegano`、`numpy`。"
    )

    selected_topic = st.selectbox("请选择实验课题", options=EXPERIMENT_TOPICS, index=0)
    st.write(f"当前选择：**{selected_topic}**（实验内容后续补充）")

    status_data = _load_status()
    running_run = (status_data or {}).get("running")
    _render_running_status(running_run)

    col_start, col_stop = st.columns(2)
    with col_start:
        if st.button("启动实验环境", type="primary", width="stretch"):
            _start_sandbox(selected_topic)
            st.rerun()
    with col_stop:
        if st.button("停止沙箱", width="stretch"):
            _stop_sandbox()
            st.rerun()

    _render_admin_panel(current_user)


if __name__ == "__main__":
    main()
