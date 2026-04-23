"""频域 DCT 隐写核心逻辑（8x8 分块）。"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
from PIL import Image

LENGTH_HEADER_BITS = 32
COEF_POS = (3, 4)  # 选取中频系数，避免 DC 与极高频
EMBED_STEP = 12.0  # 量化步长，提升嵌入/提取稳定性


def _to_rgb_array(image: Image.Image) -> np.ndarray:
    """统一转换为 RGB 三通道数组。"""
    return np.array(image.convert("RGB"), dtype=np.uint8)


def _text_to_bits(text: str) -> list[int]:
    """文本转二进制 bit 列表（含长度头）。"""
    data = text.encode("utf-8")
    length_bits = f"{len(data):0{LENGTH_HEADER_BITS}b}"
    payload_bits = "".join(f"{b:08b}" for b in data)
    return [int(ch) for ch in (length_bits + payload_bits)]


def _safe_work_shape(height: int, width: int) -> tuple[int, int]:
    """可进行 8x8 分块 DCT 的工作区域尺寸（向下取整）。"""
    return height - (height % 8), width - (width % 8)


def _iter_blocks(height: int, width: int):
    """按 8x8 顺序迭代块左上角坐标。"""
    for top in range(0, height, 8):
        for left in range(0, width, 8):
            yield top, left


def _embed_bit_to_coeff(value: float, bit: int) -> float:
    """将单 bit 写入系数量化奇偶性。"""
    q = int(np.round(value / EMBED_STEP))
    if (q % 2) != bit:
        # 按当前符号方向调整，尽量减小改动幅度
        if q >= 0:
            q += 1
        else:
            q -= 1
    if (q % 2) != bit:
        q += 1
    # 避免 q=0 带来对称点不稳定（0 仅对应偶数）
    if q == 0:
        q = 2 if bit == 0 else 1
    return float(q) * EMBED_STEP


def _extract_bit_from_coeff(value: float) -> int:
    """从系数量化奇偶性提取单 bit。"""
    q = int(np.round(value / EMBED_STEP))
    return int(q % 2)


def _dct_channel_embed(channel: np.ndarray, bits: list[int]) -> np.ndarray:
    """在单通道上完成 8x8 DCT 嵌入。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    height, width = channel.shape
    work_h, work_w = _safe_work_shape(height, width)
    if work_h < 8 or work_w < 8:
        raise ValueError("图像尺寸过小，至少需要 8x8 像素。")

    block_capacity = (work_h // 8) * (work_w // 8)
    if len(bits) > block_capacity:
        raise ValueError("文本过长，当前图像容量不足。")

    out = channel.astype(np.float32).copy()
    bit_idx = 0
    for top, left in _iter_blocks(work_h, work_w):
        if bit_idx >= len(bits):
            break
        block = out[top : top + 8, left : left + 8]
        shifted = block - 128.0
        dct_block = cv2.dct(shifted)
        u, v = COEF_POS
        dct_block[u, v] = _embed_bit_to_coeff(float(dct_block[u, v]), bits[bit_idx])
        restored = cv2.idct(dct_block) + 128.0
        out[top : top + 8, left : left + 8] = np.clip(restored, 0.0, 255.0)
        bit_idx += 1

    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def _dct_channel_extract_bits(channel: np.ndarray, bit_count: int) -> list[int]:
    """从单通道 8x8 DCT 系数中提取指定数量的 bit。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    height, width = channel.shape
    work_h, work_w = _safe_work_shape(height, width)
    if work_h < 8 or work_w < 8:
        raise ValueError("图像尺寸过小，至少需要 8x8 像素。")

    block_capacity = (work_h // 8) * (work_w // 8)
    read_limit = min(bit_count, block_capacity)
    bits: list[int] = []
    for top, left in _iter_blocks(work_h, work_w):
        if len(bits) >= read_limit:
            break
        block = channel[top : top + 8, left : left + 8].astype(np.float32)
        shifted = block - 128.0
        dct_block = cv2.dct(shifted)
        u, v = COEF_POS
        bits.append(_extract_bit_from_coeff(float(dct_block[u, v])))
    return bits


def embed_message(image: Image.Image, text: str) -> Image.Image:
    """将文本嵌入图像的 DCT 系数。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    bits = _text_to_bits(text)
    rgb = _to_rgb_array(image)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y_channel = ycrcb[:, :, 0]
    y_embedded = _dct_channel_embed(y_channel, bits)
    ycrcb[:, :, 0] = y_embedded
    stego_rgb = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2RGB)
    return Image.fromarray(stego_rgb.astype(np.uint8), mode="RGB")


def extract_message(image: Image.Image) -> str:
    """从图像的 DCT 系数提取并还原文本。"""
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime environment dependency
        raise RuntimeError(
            "OpenCV is unavailable in current runtime. "
            "Please install opencv-python-headless or required system libraries."
        ) from exc

    rgb = _to_rgb_array(image)
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y_channel = ycrcb[:, :, 0]

    header_bits = _dct_channel_extract_bits(y_channel, LENGTH_HEADER_BITS)
    if len(header_bits) < LENGTH_HEADER_BITS:
        raise ValueError("图像中的隐写数据不完整。")
    payload_len = int("".join(str(int(b)) for b in header_bits), 2)
    payload_bits_len = payload_len * 8

    all_bits = _dct_channel_extract_bits(y_channel, LENGTH_HEADER_BITS + payload_bits_len)
    payload_bits = all_bits[LENGTH_HEADER_BITS : LENGTH_HEADER_BITS + payload_bits_len]
    if len(payload_bits) < payload_bits_len:
        raise ValueError("图像中的隐写数据不完整。")

    out = bytearray()
    for idx in range(0, payload_bits_len, 8):
        byte_bits = payload_bits[idx : idx + 8]
        out.append(int("".join(str(int(b)) for b in byte_bits), 2))
    return out.decode("utf-8", errors="replace")


def psnr(img_1: np.ndarray, img_2: np.ndarray) -> float:
    """计算两幅同尺寸图像的 PSNR（dB）。"""
    if img_1.shape != img_2.shape:
        raise ValueError("两幅图像尺寸不一致，无法计算 PSNR。")
    mse = float(np.mean((img_1 / 1.0 - img_2 / 1.0) ** 2))
    if mse < 1.0e-10:
        return 100.0
    return float(10 * math.log10(255.0**2 / mse))


def psnr_rgb_images(cover: Image.Image, stego: Image.Image) -> float:
    """对 RGB 图像计算 PSNR（载体 vs 隐写）。"""
    return psnr(_to_rgb_array(cover), _to_rgb_array(stego))


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


def estimate_capacity(image: Image.Image) -> Tuple[int, int]:
    """估算图像可嵌入容量（字节）。"""
    rgb = _to_rgb_array(image)
    height, width = rgb.shape[:2]
    work_h, work_w = _safe_work_shape(height, width)
    if work_h < 8 or work_w < 8:
        return 0, 0
    total_bits = (work_h // 8) * (work_w // 8)
    usable_bits = max(total_bits - LENGTH_HEADER_BITS, 0)
    usable_bytes = usable_bits // 8
    return usable_bits, usable_bytes
