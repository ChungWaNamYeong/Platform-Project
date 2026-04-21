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
    """生成载体图与隐写图直方图对比图。"""
    cover_arr = _to_rgb_array(cover_image).reshape(-1)
    stego_arr = _to_rgb_array(stego_image).reshape(-1)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4), dpi=120)
    axes[0].hist(cover_arr, bins=256, color="#3b82f6", alpha=0.85)
    axes[0].set_title("载体图直方图")
    axes[0].set_xlabel("像素值")
    axes[0].set_ylabel("频数")

    axes[1].hist(stego_arr, bins=256, color="#10b981", alpha=0.85)
    axes[1].set_title("隐写图直方图")
    axes[1].set_xlabel("像素值")
    axes[1].set_ylabel("频数")

    fig.tight_layout()
    return fig


def estimate_capacity(image: Image.Image) -> Tuple[int, int]:
    """估算图像可嵌入容量（字节）。"""
    arr = _to_rgb_array(image)
    total_bits = arr.size
    usable_bits = max(total_bits - LENGTH_HEADER_BITS, 0)
    usable_bytes = usable_bits // 8
    return usable_bits, usable_bytes
