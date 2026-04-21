"""空域 LSB 隐写核心逻辑。"""

from __future__ import annotations

from typing import Tuple

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

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
    """Generate grayscale histogram comparison with visible delta."""
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

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), dpi=120, sharex=True)
    axes[0].plot(bins, cover_hist, color="#2563eb", linewidth=1.4, label="Cover (Grayscale)")
    axes[0].plot(bins, stego_hist, color="#059669", linewidth=1.1, label="Stego (Grayscale)")
    axes[0].set_title("Histogram Comparison (cv2.calcHist)")
    axes[0].set_ylabel("Pixel Count")
    axes[0].legend(loc="upper right")
    axes[0].grid(alpha=0.15)

    axes[1].bar(bins, diff_hist, color="#ef4444", width=1.0, alpha=0.85)
    axes[1].set_title("Absolute Histogram Difference |Stego - Cover|")
    axes[1].set_xlabel("Gray Level (0-255)")
    axes[1].set_ylabel("Delta Count")
    axes[1].grid(alpha=0.15)

    peak_bin = int(np.argmax(diff_hist))
    peak_val = float(diff_hist[peak_bin])
    axes[1].annotate(
        f"Max delta at bin {peak_bin}: {peak_val:.0f}",
        xy=(peak_bin, peak_val),
        xytext=(min(peak_bin + 18, 240), peak_val * 1.1 + 1),
        arrowprops={"arrowstyle": "->", "color": "#111827"},
        fontsize=9,
        color="#111827",
    )

    fig.tight_layout()
    return fig


def estimate_capacity(image: Image.Image) -> Tuple[int, int]:
    """估算图像可嵌入容量（字节）。"""
    arr = _to_rgb_array(image)
    total_bits = arr.size
    usable_bits = max(total_bits - LENGTH_HEADER_BITS, 0)
    usable_bytes = usable_bits // 8
    return usable_bits, usable_bytes
