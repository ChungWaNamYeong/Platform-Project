"""空域 LSB 隐写核心逻辑。"""

from __future__ import annotations

import base64
import math
from io import BytesIO
from typing import Any, Tuple

import numpy as np
from PIL import Image

LENGTH_HEADER_BITS = 32


def _to_rgb_array(image: Image.Image) -> np.ndarray:
    """统一转换为 RGB 三通道数组。"""
    return np.array(image.convert("RGB"), dtype=np.uint8)


def psnr(img_1: np.ndarray, img_2: np.ndarray) -> float:
    """计算两幅同尺寸图像的 PSNR（dB），与常见教材公式一致。"""
    if img_1.shape != img_2.shape:
        raise ValueError("两幅图像尺寸不一致，无法计算 PSNR。")
    mse = float(np.mean((img_1 / 1.0 - img_2 / 1.0) ** 2))
    if mse < 1.0e-10:
        return 100.0
    return float(10 * math.log10(255.0**2 / mse))


def psnr_rgb_images(cover: Image.Image, stego: Image.Image) -> float:
    """对 RGB 图像计算 PSNR（载体 vs 隐写）。"""
    return psnr(_to_rgb_array(cover), _to_rgb_array(stego))


def _text_to_bits(text: str) -> list[int]:
    """文本转二进制 bit 列表。"""
    data = text.encode("utf-8")
    length_bits = f"{len(data):0{LENGTH_HEADER_BITS}b}"
    payload_bits = "".join(f"{b:08b}" for b in data)
    return [int(ch) for ch in (length_bits + payload_bits)]


def embed_message(image: Image.Image, text: str) -> Image.Image:
    """
    将文本嵌入到图像最低位。

    嵌入公式：pixel = pixel & ~1 | bit
    """
    bits = _text_to_bits(text)
    arr = _to_rgb_array(image)
    flat = arr.reshape(-1)

    if len(bits) > flat.size:
        raise ValueError("文本过长，当前图像容量不足。")

    for i, bit in enumerate(bits):
        # 使用 0xFE 掩码清零最低位，避免 ~1 在 uint8 场景下产生负数边界问题。
        flat[i] = (flat[i] & 0xFE) | bit

    stego_arr = flat.reshape(arr.shape)
    return Image.fromarray(stego_arr, mode="RGB")


def extract_message(image: Image.Image) -> str:
    """从图像最低位提取并还原文本。"""
    arr = _to_rgb_array(image)
    flat = arr.reshape(-1)

    header = flat[:LENGTH_HEADER_BITS] & 1
    payload_len = int("".join(str(int(b)) for b in header), 2)
    payload_bits_len = payload_len * 8

    payload_bits = flat[LENGTH_HEADER_BITS : LENGTH_HEADER_BITS + payload_bits_len] & 1
    if payload_bits.size < payload_bits_len:
        raise ValueError("图像中的隐写数据不完整。")

    out = bytearray()
    for i in range(0, payload_bits_len, 8):
        byte_bits = payload_bits[i : i + 8]
        out.append(int("".join(str(int(b)) for b in byte_bits), 2))
    return out.decode("utf-8", errors="replace")


def build_histogram_figure(cover_image: Image.Image, stego_image: Image.Image):
    """生成可缩放的灰度直方图柱状图与差值图。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    try:
        from plotly.subplots import make_subplots  # type: ignore[import-not-found]
        import plotly.graph_objects as go  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "plotly 未安装。请在当前 Python 环境中执行：pip install plotly"
        ) from exc

    cover_rgb = _to_rgb_array(cover_image)
    stego_rgb = _to_rgb_array(stego_image)

    cover_gray = cv2.cvtColor(cover_rgb, cv2.COLOR_RGB2GRAY)
    stego_gray = cv2.cvtColor(stego_rgb, cv2.COLOR_RGB2GRAY)

    cover_hist = cv2.calcHist([cover_gray], [0], None, [256], [0, 256]).flatten()
    stego_hist = cv2.calcHist([stego_gray], [0], None, [256], [0, 256]).flatten()
    diff_hist = np.abs(stego_hist - cover_hist)
    bins = np.arange(256)
    cover_hist_norm = cover_hist / max(float(cover_hist.sum()), 1.0)
    stego_hist_norm = stego_hist / max(float(stego_hist.sum()), 1.0)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.28,
        row_heights=[0.56, 0.44],
        subplot_titles=(
            "Normalized Histogram Comparison (cv2.calcHist)",
            "Absolute Histogram Difference |Stego - Cover|",
        ),
    )

    fig.add_trace(
        go.Bar(
            x=bins,
            y=cover_hist_norm,
            marker_color="#2563eb",
            opacity=0.55,
            marker_line={"width": 0},
            name="Cover (Normalized)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=bins,
            y=stego_hist_norm,
            marker_color="#ef4444",
            opacity=0.55,
            marker_line={"width": 0},
            name="Stego (Normalized)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=bins,
            y=diff_hist,
            marker_color="#22c55e",
            opacity=0.82,
            name="Absolute Difference",
        ),
        row=2,
        col=1,
    )

    peak_bin = int(np.argmax(diff_hist))
    peak_val = float(diff_hist[peak_bin])

    fig.update_xaxes(title_text="Gray Level (0-255)", row=2, col=1)
    fig.update_yaxes(title_text="Normalized Count", row=1, col=1)
    fig.update_yaxes(title_text="Delta Count", row=2, col=1)
    # 右侧留白需容纳「Max delta」说明框；xanchor=left + x=1 使框从绘图区右缘向外延伸，避免压住柱状图
    fig.update_layout(
        height=760,
        hovermode="x unified",
        bargap=0,
        barmode="overlay",
        margin={"l": 70, "r": 260, "t": 80, "b": 60},
        legend={"orientation": "h", "x": 0, "y": 1.12},
    )
    fig.add_annotation(
        x=1.0,
        y=0.92,
        xref="paper",
        yref="paper",
        xanchor="left",
        yanchor="top",
        showarrow=False,
        align="left",
        bordercolor="#d1d5db",
        borderwidth=1,
        borderpad=6,
        bgcolor="#f9fafb",
        text=f"<b>Max delta at</b><br>bin={peak_bin}<br>delta={peak_val:.0f}",
    )

    return fig


def _image_to_data_url(image: Image.Image) -> str:
    """将 PIL 图像编码为可直接嵌入前端的 data URL。"""
    buf = BytesIO()
    image.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _bit_plane_images(image: Image.Image) -> list[dict[str, Any]]:
    """提取 8 个位平面（bit7 到 bit0）。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    gray = cv2.cvtColor(_to_rgb_array(image), cv2.COLOR_RGB2GRAY)
    out: list[dict[str, Any]] = []
    for bit in range(7, -1, -1):
        plane = ((gray >> bit) & 1).astype(np.uint8) * 255
        plane_img = Image.fromarray(plane, mode="L")
        out.append(
            {
                "label": f"Bit {bit}",
                "url": _image_to_data_url(plane_img),
            }
        )
    return out


def build_bit_plane_payload(cover_image: Image.Image, stego_image: Image.Image) -> dict[str, Any]:
    """构建位平面交互组件的数据载荷（载体图+隐写图）。"""
    return {
        "cover": {
            "title": "载体图位平面分解",
            "original_url": _image_to_data_url(cover_image.convert("RGB")),
            "planes": _bit_plane_images(cover_image),
        },
        "stego": {
            "title": "隐写图位平面分解",
            "original_url": _image_to_data_url(stego_image.convert("RGB")),
            "planes": _bit_plane_images(stego_image),
        },
    }


def estimate_capacity(image: Image.Image) -> Tuple[int, int]:
    """估算图像可嵌入容量（字节）。"""
    arr = _to_rgb_array(image)
    total_bits = arr.size
    usable_bits = max(total_bits - LENGTH_HEADER_BITS, 0)
    usable_bytes = usable_bits // 8
    return usable_bits, usable_bytes
