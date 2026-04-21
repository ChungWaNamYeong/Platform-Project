"""空域 LSB 隐写核心逻辑。"""

from __future__ import annotations

from typing import Tuple

import numpy as np
from PIL import Image
from plotly.subplots import make_subplots
import plotly.graph_objects as go

LENGTH_HEADER_BITS = 32


def _to_rgb_array(image: Image.Image) -> np.ndarray:
    """统一转换为 RGB 三通道数组。"""
    return np.array(image.convert("RGB"), dtype=np.uint8)


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
    """Generate interactive grayscale histogram comparison figure."""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
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
        vertical_spacing=0.2,
        row_heights=[0.56, 0.44],
        subplot_titles=(
            "Normalized Histogram Comparison (cv2.calcHist)",
            "Absolute Histogram Difference |Stego - Cover|",
        ),
    )

    fig.add_trace(
        go.Scatter(
            x=bins,
            y=cover_hist_norm,
            mode="lines",
            line={"color": "#2563eb", "width": 2},
            name="Cover (Normalized)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=bins,
            y=stego_hist_norm,
            mode="lines",
            line={"color": "#059669", "width": 2},
            name="Stego (Normalized)",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=bins,
            y=diff_hist,
            marker_color="#ef4444",
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
    fig.update_layout(
        height=760,
        hovermode="x unified",
        bargap=0,
        margin={"l": 70, "r": 230, "t": 80, "b": 60},
        legend={"orientation": "h", "x": 0, "y": 1.12},
    )
    fig.add_annotation(
        x=1.02,
        y=0.92,
        xref="paper",
        yref="paper",
        showarrow=False,
        align="left",
        bordercolor="#d1d5db",
        borderwidth=1,
        borderpad=6,
        bgcolor="#f9fafb",
        text=f"<b>Max delta at</b><br>bin={peak_bin}<br>delta={peak_val:.0f}",
    )

    return fig


def estimate_capacity(image: Image.Image) -> Tuple[int, int]:
    """估算图像可嵌入容量（字节）。"""
    arr = _to_rgb_array(image)
    total_bits = arr.size
    usable_bits = max(total_bits - LENGTH_HEADER_BITS, 0)
    usable_bytes = usable_bits // 8
    return usable_bits, usable_bytes
