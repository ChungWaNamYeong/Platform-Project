# -*- coding: utf-8 -*-
"""实验模块页：登录后选择实验并控制沙箱生命周期。"""

from __future__ import annotations

import base64
import csv
import hashlib
from io import BytesIO, StringIO
import json
import time
from typing import Any

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image

from stego_frontend.modules import auth
from stego_frontend.modules import branding
from stego_logic.lsb_steg import (
    build_bit_plane_payload,
    build_histogram_figure,
    embed_message,
    estimate_capacity,
    extract_message,
    psnr_rgb_images,
)

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


def _image_to_b64(image: Image.Image) -> str:
    """将 PIL 图片编码为 PNG Base64 字符串。"""
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _json_safe(data: Any) -> Any:
    """将对象转换成可 JSON 序列化结构。"""
    if hasattr(data, "to_json"):
        try:
            return json.loads(data.to_json())
        except Exception:
            pass
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _data_url_to_bytes(data_url: str) -> bytes | None:
    """解析 data URL 为二进制内容。"""
    if not data_url or "," not in data_url:
        return None
    try:
        _, b64_data = data_url.split(",", 1)
        return base64.b64decode(b64_data)
    except Exception:
        return None


def _records_to_csv_text(records: list[dict[str, Any]]) -> str:
    """将记录列表导出为 CSV 文本。"""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "username",
            "experiment_name",
            "started_at",
            "completed_at",
            "psnr",
            "source_text",
            "extracted_text",
            "cover_image_b64_length",
            "stego_image_b64_length",
            "created_at",
        ]
    )
    for item in records:
        writer.writerow(
            [
                item.get("id", ""),
                item.get("username", ""),
                item.get("experiment_name", ""),
                item.get("started_at", ""),
                item.get("completed_at", ""),
                item.get("psnr", ""),
                item.get("source_text", ""),
                item.get("extracted_text", ""),
                len(str(item.get("cover_image_b64") or "")),
                len(str(item.get("stego_image_b64") or "")),
                item.get("created_at", ""),
            ]
        )
    return output.getvalue()


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


def _render_bit_plane_decomposition(cover_image: Image.Image, stego_image: Image.Image) -> dict[str, Any]:
    """渲染位平面分解交互组件（悬停叠放 + 点击平铺）。"""
    payload = build_bit_plane_payload(cover_image, stego_image)
    payload_json = json.dumps(payload, ensure_ascii=False)
    html = f"""
    <style>
      .bp-wrap {{
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        margin-top: 4px;
      }}
      .bp-grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 20px;
      }}
      .bp-panel {{
        border: 1px solid #e5e7eb;
        border-radius: 14px;
        padding: 10px;
        background: #ffffff;
        transition: box-shadow 180ms ease;
      }}
      .bp-panel:hover {{
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.08);
      }}
      .bp-title {{
        font-size: 14px;
        font-weight: 600;
        margin: 0 0 6px 0;
      }}
      .bp-original {{
        width: 100%;
        max-height: 220px;
        object-fit: contain;
        border-radius: 10px;
        border: 1px solid #e5e7eb;
        background: #f8fafc;
        display: block;
      }}
      .bp-hint {{
        margin-top: 6px;
        font-size: 12px;
        color: #4b5563;
      }}
      .bp-stack {{
        position: relative;
        height: 176px;
        margin-top: 8px;
        border-radius: 10px;
        border: 1px dashed #cbd5e1;
        background: #f8fafc;
        overflow: hidden;
        cursor: pointer;
      }}
      .bp-card {{
        position: absolute;
        left: 50%;
        top: 50%;
        width: 118px;
        height: 118px;
        transform: translate(-50%, -50%) scale(0.78);
        transform-origin: center;
        transition: transform 280ms ease, opacity 280ms ease;
        border-radius: 8px;
        border: 1px solid #d1d5db;
        background: #ffffff;
        padding: 4px;
        opacity: 0.92;
      }}
      .bp-card img {{
        width: 100%;
        height: 92px;
        object-fit: cover;
        border-radius: 6px;
      }}
      .bp-card span {{
        display: block;
        text-align: center;
        font-size: 10px;
        margin-top: 3px;
        color: #334155;
      }}
      .bp-panel:hover .bp-stack:not(.expanded) .bp-card {{
        transform:
          translate(calc(-50% + (var(--idx) - 3.5) * 11px),
                    calc(-50% + (var(--idx) - 3.5) * -7px))
          scale(0.82);
      }}
      .bp-panel.expanded .bp-stack {{
        height: 0;
        margin: 0;
        border: 0;
        overflow: hidden;
      }}
      .bp-planes-grid {{
        margin-top: 8px;
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 8px;
        max-height: 0;
        opacity: 0;
        transform: translateY(10px);
        overflow: hidden;
        transition: max-height 320ms ease, opacity 320ms ease, transform 320ms ease;
      }}
      .bp-panel.expanded .bp-planes-grid {{
        max-height: 1000px;
        opacity: 1;
        transform: translateY(0);
      }}
      .bp-plane-item {{
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 4px;
        background: #fff;
        cursor: zoom-in;
      }}
      .bp-plane-item img {{
        width: 100%;
        height: 72px;
        object-fit: cover;
        border-radius: 6px;
      }}
      .bp-plane-item div {{
        text-align: center;
        font-size: 11px;
        margin-top: 2px;
      }}
      .bp-toggle {{
        margin-top: 8px;
        width: 100%;
        border: 1px solid #cbd5e1;
        background: #fff;
        border-radius: 8px;
        padding: 6px 8px;
        cursor: pointer;
        font-size: 12px;
      }}
      .bp-modal {{
        position: fixed;
        inset: 0;
        z-index: 9999;
        background: rgba(15, 23, 42, 0.72);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
      }}
      .bp-modal.open {{
        display: flex;
      }}
      .bp-modal-content {{
        max-width: min(92vw, 920px);
        width: fit-content;
        background: #ffffff;
        border-radius: 12px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 12px 26px rgba(0, 0, 0, 0.28);
        padding: 10px;
      }}
      .bp-modal-toolbar {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
        gap: 8px;
      }}
      .bp-modal-title {{
        font-size: 14px;
        color: #0f172a;
        font-weight: 600;
      }}
      .bp-modal-close {{
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        background: #ffffff;
        color: #334155;
        padding: 4px 10px;
        cursor: pointer;
      }}
      .bp-modal img {{
        display: block;
        max-width: min(92vw, 900px);
        max-height: 74vh;
        width: auto;
        height: auto;
        border-radius: 8px;
        border: 1px solid #e5e7eb;
        background: #f8fafc;
      }}
      @media (max-width: 920px) {{
        .bp-grid {{
          grid-template-columns: 1fr;
        }}
        .bp-planes-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}
    </style>
    <div class="bp-wrap">
      <div id="bpRoot" class="bp-grid"></div>
      <div id="bpModal" class="bp-modal" role="dialog" aria-modal="true">
        <div class="bp-modal-content">
          <div class="bp-modal-toolbar">
            <div id="bpModalTitle" class="bp-modal-title">位平面大图</div>
            <button id="bpModalClose" type="button" class="bp-modal-close">关闭</button>
          </div>
          <img id="bpModalImage" src="" alt="位平面大图" />
        </div>
      </div>
    </div>
    <script>
      const payload = {payload_json};
      const root = document.getElementById("bpRoot");
      const modal = document.getElementById("bpModal");
      const modalImage = document.getElementById("bpModalImage");
      const modalTitle = document.getElementById("bpModalTitle");
      const modalClose = document.getElementById("bpModalClose");

      function openModal(src, title) {{
        modalImage.src = src;
        modalImage.alt = title;
        modalTitle.textContent = title;
        modal.classList.add("open");
      }}

      function closeModal() {{
        modal.classList.remove("open");
      }}

      function makePanel(data) {{
        const panel = document.createElement("div");
        panel.className = "bp-panel";
        panel.innerHTML = `
          <div class="bp-title">${{data.title}}</div>
          <img class="bp-original" src="${{data.original_url}}" alt="${{data.title}}" />
          <div class="bp-hint">鼠标悬停可预览位平面叠放，点击下方按钮可展开平铺。</div>
          <div class="bp-stack" title="Hover 预览叠放，Click 展开平铺"></div>
          <button class="bp-toggle" type="button">点击展开 8 张位平面</button>
          <div class="bp-planes-grid"></div>
        `;

        const stack = panel.querySelector(".bp-stack");
        const grid = panel.querySelector(".bp-planes-grid");
        const toggle = panel.querySelector(".bp-toggle");
        data.planes.forEach((item, idx) => {{
          const card = document.createElement("div");
          card.className = "bp-card";
          card.style.setProperty("--idx", String(idx));
          card.innerHTML = `<img src="${{item.url}}" alt="${{item.label}}" /><span>${{item.label}}</span>`;
          stack.appendChild(card);

          const plane = document.createElement("div");
          plane.className = "bp-plane-item";
          plane.innerHTML = `<img src="${{item.url}}" alt="${{item.label}}" /><div>${{item.label}}</div>`;
          plane.addEventListener("click", (event) => {{
            event.stopPropagation();
            openModal(item.url, `${{data.title}} - ${{item.label}}`);
          }});
          grid.appendChild(plane);
        }});

        const toggleExpand = () => {{
          panel.classList.toggle("expanded");
          const expanded = panel.classList.contains("expanded");
          stack.classList.toggle("expanded", expanded);
          toggle.textContent = expanded ? "点击收起为叠放预览" : "点击展开 8 张位平面";
        }};
        toggle.addEventListener("click", toggleExpand);
        stack.addEventListener("click", toggleExpand);
        return panel;
      }}

      root.appendChild(makePanel(payload.cover));
      root.appendChild(makePanel(payload.stego));
      modalClose.addEventListener("click", closeModal);
      modal.addEventListener("click", (event) => {{
        if (event.target === modal) {{
          closeModal();
        }}
      }});
      window.addEventListener("keydown", (event) => {{
        if (event.key === "Escape") {{
          closeModal();
        }}
      }});
    </script>
    """
    components.html(html, height=860, scrolling=False)
    return payload


def _render_psnr_banner(
    cover_image: Image.Image,
    stego_image: Image.Image,
    psnr_db: float | None = None,
) -> None:
    """在载体图/隐写图下方、直方图上方展示 PSNR 及分级说明（悬停问号）。"""
    if psnr_db is None:
        try:
            psnr_db = psnr_rgb_images(cover_image, stego_image)
        except Exception as exc:
            st.warning(f"PSNR 计算失败：{exc}")
            return

    if psnr_db >= 40:
        bg, border, fg = "#dcfce7", "#22c55e", "#166534"
    elif psnr_db >= 30:
        bg, border, fg = "#dbeafe", "#3b82f6", "#1e40af"
    elif psnr_db >= 20:
        bg, border, fg = "#fef9c3", "#eab308", "#854d0e"
    else:
        bg, border, fg = "#fee2e2", "#ef4444", "#991b1b"

    tip_lines = (
        "PSNR 分级参考（峰值信噪比，单位 dB）：",
        "· 高于 40：图像质量极好，与原始图像非常接近；",
        "· 30～40：图像质量较好，失真可察觉但通常可接受；",
        "· 20～30：图像质量较差；",
        "· 低于 20：图像质量不可接受。",
    )
    tip_html = "<br/>".join(tip_lines)

    html = f"""
    <style>
      .lsb-psnr-banner {{
        position: relative;
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 6px 10px;
        padding: 12px 16px;
        margin: 12px 0 16px 0;
        border-radius: 12px;
        border: 2px solid {border};
        background: {bg};
        color: {fg};
        font-size: 16px;
        font-weight: 600;
        line-height: 1.4;
      }}
      .lsb-psnr-qwrap {{
        position: relative;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-left: 4px;
        vertical-align: middle;
      }}
      .lsb-psnr-q {{
        display: inline-flex;
        width: 22px;
        height: 22px;
        border-radius: 50%;
        border: 2px solid currentColor;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        font-weight: 700;
        cursor: help;
        line-height: 1;
        user-select: none;
      }}
      .lsb-psnr-tip {{
        display: none;
        position: absolute;
        left: 50%;
        transform: translateX(-50%);
        top: calc(100% + 10px);
        z-index: 100;
        min-width: 300px;
        max-width: 420px;
        padding: 14px 16px;
        background: #ffffff;
        color: #1f2937;
        font-size: 13px;
        font-weight: 400;
        line-height: 1.6;
        text-align: left;
        border-radius: 10px;
        border: 1px solid #e5e7eb;
        box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
        pointer-events: none;
      }}
      .lsb-psnr-qwrap:hover .lsb-psnr-tip {{
        display: block;
      }}
    </style>
    <div class="lsb-psnr-banner">
      <span>PSNR（峰值信噪比）：{psnr_db:.2f} dB</span>
      <span class="lsb-psnr-qwrap">
        <span class="lsb-psnr-q">?</span>
        <div class="lsb-psnr-tip">{tip_html}</div>
      </span>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)


def _auto_save_experiment_record(
    *,
    experiment_name: str,
    running_run: dict[str, Any] | None,
    cover_image: Image.Image,
    stego_image: Image.Image,
    psnr_db: float | None,
    histogram_data: dict[str, Any],
    bit_plane_data: dict[str, Any],
    source_text: str,
    extracted_text: str,
) -> None:
    """实验结果就绪后自动写入后端记录。"""
    cover_b64 = _image_to_b64(cover_image)
    stego_b64 = _image_to_b64(stego_image)
    signature_payload = {
        "experiment_name": experiment_name,
        "cover_digest": hashlib.sha256(cover_b64.encode("utf-8")).hexdigest(),
        "stego_digest": hashlib.sha256(stego_b64.encode("utf-8")).hexdigest(),
        "psnr": psnr_db,
        "source_text": source_text,
        "extracted_text": extracted_text,
    }
    signature = hashlib.sha256(
        json.dumps(signature_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if st.session_state.get("lsb_last_record_signature") == signature:
        return

    payload: dict[str, Any] = {
        "experiment_name": experiment_name,
        "cover_image_b64": cover_b64,
        "stego_image_b64": stego_b64,
        "psnr": psnr_db,
        "histogram_data": histogram_data,
        "bit_planes_data": bit_plane_data,
        "source_text": source_text,
        "extracted_text": extracted_text,
    }
    started_at = (running_run or {}).get("started_at")
    if started_at:
        payload["started_at"] = started_at
    result = auth.api_request(
        "POST",
        "/labs/records",
        with_auth=True,
        json_data=payload,
        timeout=45,
    )
    if result["ok"]:
        st.session_state.lsb_last_record_signature = signature
        st.session_state.lsb_last_record_error_signature = ""
        st.caption("已自动记录本次实验结果。")
        return

    if st.session_state.get("lsb_last_record_error_signature") != signature:
        st.session_state.lsb_last_record_error_signature = signature
        st.warning(f"自动记录失败：{result['error']}")


def _render_experiment_records_panel(current_user: dict[str, Any]) -> None:
    """展示实验记录列表、删除与导出能力。"""
    st.divider()
    st.subheader("实验记录")
    result = auth.api_request("GET", "/labs/records", with_auth=True, timeout=30)
    if not result["ok"]:
        st.error(f"读取实验记录失败：{result['error']}")
        return
    records = result["data"] or []
    if not records:
        st.caption("暂无实验记录。完成一次实验后将自动出现在这里。")
        return

    json_text = json.dumps(records, ensure_ascii=False, indent=2)
    csv_text = _records_to_csv_text(records)
    export_name_prefix = "all" if current_user.get("is_superuser") else "mine"
    col_json, col_csv = st.columns(2)
    with col_json:
        st.download_button(
            "导出当前列表（JSON）",
            data=json_text.encode("utf-8"),
            file_name=f"experiment_records_{export_name_prefix}.json",
            mime="application/json",
            width="stretch",
        )
    with col_csv:
        st.download_button(
            "导出当前列表（CSV）",
            data=csv_text.encode("utf-8-sig"),
            file_name=f"experiment_records_{export_name_prefix}.csv",
            mime="text/csv",
            width="stretch",
        )

    for item in records:
        rid = item.get("id")
        owner = str(item.get("username") or "-")
        title = str(item.get("experiment_name") or "-")
        created_at = _format_dt(item.get("created_at"))
        expander_title = f"#{rid} | {title} | {owner} | {created_at}"
        with st.expander(expander_title, expanded=False):
            st.write(f"启动时间：{_format_dt(item.get('started_at'))}")
            st.write(f"完成时间：{_format_dt(item.get('completed_at'))}")
            psnr_val = item.get("psnr")
            st.write(f"PSNR：{psnr_val if psnr_val is not None else '-'}")

            cover_b64 = str(item.get("cover_image_b64") or "")
            stego_b64 = str(item.get("stego_image_b64") or "")
            if cover_b64 and stego_b64:
                img_cols = st.columns(2)
                with img_cols[0]:
                    st.markdown("**载体图（记录）**")
                    st.image(base64.b64decode(cover_b64), width="stretch")
                with img_cols[1]:
                    st.markdown("**隐写图（记录）**")
                    st.image(base64.b64decode(stego_b64), width="stretch")

            bit_data = item.get("bit_planes_data") or {}
            cover_planes = bit_data.get("cover") or []
            stego_planes = bit_data.get("stego") or []
            if cover_planes:
                st.markdown("**位平面（载体图）**")
                cols = st.columns(8)
                for idx, plane in enumerate(cover_planes[:8]):
                    with cols[idx]:
                        img_bytes = _data_url_to_bytes(str(plane.get("url") or ""))
                        if img_bytes:
                            st.image(img_bytes, caption=str(plane.get("label") or ""), width="stretch")
            if stego_planes:
                st.markdown("**位平面（隐写图）**")
                cols = st.columns(8)
                for idx, plane in enumerate(stego_planes[:8]):
                    with cols[idx]:
                        img_bytes = _data_url_to_bytes(str(plane.get("url") or ""))
                        if img_bytes:
                            st.image(img_bytes, caption=str(plane.get("label") or ""), width="stretch")

            hist = item.get("histogram_data") or {}
            if hist:
                st.markdown("**直方图（记录）**")
                st.plotly_chart(hist, use_container_width=True)

            st.markdown("**文本提取校验（记录）**")
            txt_cols = st.columns(2)
            with txt_cols[0]:
                st.text_area(
                    "原始文本（记录）",
                    value=str(item.get("source_text") or ""),
                    height=120,
                    disabled=True,
                    key=f"record_source_{rid}",
                )
            with txt_cols[1]:
                st.text_area(
                    "提取文本（记录）",
                    value=str(item.get("extracted_text") or ""),
                    height=120,
                    disabled=True,
                    key=f"record_extracted_{rid}",
                )

            if rid is not None and st.button("删除该记录", key=f"delete_record_{rid}", width="stretch"):
                delete_result = auth.api_request(
                    "DELETE",
                    f"/labs/records/{rid}",
                    with_auth=True,
                    timeout=30,
                )
                if delete_result["ok"]:
                    st.success("记录已删除。")
                    st.rerun()
                else:
                    st.error(f"删除失败：{delete_result['error']}")


def _render_lsb_experiment_panel(running_run: dict[str, Any] | None, selected_topic: str) -> None:
    """渲染空域 LSB 隐写实验交互区。"""
    if selected_topic != "空域 LSB 隐写":
        return

    st.divider()
    st.subheader("空域 LSB 隐写实验")
    if not running_run:
        st.info("请先点击“启动实验环境”，再进行 LSB 隐写实验。")
        return

    uploaded_file = st.file_uploader(
        "上传载体图（PNG/JPG）",
        type=["png", "jpg", "jpeg"],
        accept_multiple_files=False,
    )
    message_text = st.text_area("输入要嵌入的文本", height=120, placeholder="请输入需要隐藏的文本内容...")

    cover_image: Image.Image | None = None
    if uploaded_file is not None:
        cover_image = Image.open(uploaded_file).convert("RGB")
        _, cap_bytes = estimate_capacity(cover_image)
        st.caption(f"当前图像可用隐写容量约：{cap_bytes} 字节（UTF-8）")

    if st.button("执行 LSB 隐写", type="primary", width="stretch"):
        if cover_image is None:
            st.error("请先上传载体图。")
        elif not message_text.strip():
            st.error("请先输入要嵌入的文本。")
        else:
            try:
                stego_image = embed_message(cover_image, message_text)
            except Exception as exc:
                st.error(f"隐写失败：{exc}")
            else:
                st.session_state.lsb_cover_image = cover_image
                st.session_state.lsb_stego_image = stego_image
                st.session_state.lsb_source_text = message_text
                st.success("隐写完成，已生成隐写图。")

    cover_saved = st.session_state.get("lsb_cover_image")
    stego_saved = st.session_state.get("lsb_stego_image")
    if not cover_saved or not stego_saved:
        return

    col_cover, col_stego = st.columns(2)
    with col_cover:
        st.markdown("**载体图**")
        st.image(cover_saved, width="stretch")
    with col_stego:
        st.markdown("**隐写图**")
        st.image(stego_saved, width="stretch")
        buf = BytesIO()
        stego_saved.save(buf, format="PNG")
        st.download_button(
            "下载隐写图（PNG）",
            data=buf.getvalue(),
            file_name="lsb_stego.png",
            mime="image/png",
            width="stretch",
        )

    try:
        psnr_db = psnr_rgb_images(cover_saved, stego_saved)
    except Exception:
        psnr_db = None
    _render_psnr_banner(cover_saved, stego_saved, psnr_db=psnr_db)

    st.markdown("**直方图对比（载体图 vs 隐写图）**")
    histogram_data: dict[str, Any] = {}
    try:
        fig = build_histogram_figure(cover_saved, stego_saved)
    except Exception as exc:
        st.error(f"直方图渲染失败：{exc}")
    else:
        histogram_data = _json_safe(fig)
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={
                "scrollZoom": True,
                "displaylogo": False,
                "modeBarButtonsToAdd": ["zoom2d", "pan2d", "resetScale2d"],
            },
        )
        st.caption("可使用鼠标滚轮/框选自由缩放图表，双击图表可恢复全尺度。")

    st.markdown("**位平面分解（载体图 vs 隐写图）**")
    bit_plane_payload = _render_bit_plane_decomposition(cover_saved, stego_saved)

    source_text = st.session_state.get("lsb_source_text", "")
    try:
        extracted = extract_message(stego_saved)
    except Exception as exc:
        extracted = ""
        st.error(f"提取失败：{exc}")

    st.markdown("**文本提取校验**")
    col_src, col_ext = st.columns(2)
    with col_src:
        st.text_area("原始文本", value=source_text, height=120, disabled=True)
    with col_ext:
        st.text_area("提取文本", value=extracted, height=120, disabled=True)

    if source_text and extracted:
        if source_text == extracted:
            st.success("提取结果与原始文本一致。")
        else:
            mismatch_idx = next(
                (i for i, (a, b) in enumerate(zip(source_text, extracted)) if a != b),
                min(len(source_text), len(extracted)),
            )
            st.warning(
                f"提取结果与原始文本不一致，首个差异位置：{mismatch_idx}。"
            )

    _auto_save_experiment_record(
        experiment_name=selected_topic,
        running_run=running_run,
        cover_image=cover_saved,
        stego_image=stego_saved,
        psnr_db=psnr_db,
        histogram_data=histogram_data,
        bit_plane_data={
            "cover": (bit_plane_payload.get("cover") or {}).get("planes", []),
            "stego": (bit_plane_payload.get("stego") or {}).get("planes", []),
        },
        source_text=source_text,
        extracted_text=extracted,
    )


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

    _render_lsb_experiment_panel(running_run, selected_topic)
    _render_experiment_records_panel(current_user)
    _render_admin_panel(current_user)


if __name__ == "__main__":
    main()
