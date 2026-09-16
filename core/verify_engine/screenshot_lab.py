"""
screenshot_lab.py — 截图健全性算法标签（screenshot-evidence-labeling）

设计依据：design.md D1 / spec: screenshot-evidence-labeling。

职责：
  - 对落盘截图做像素级健全性判定（纯算法，不依赖 LLM/多模态能力）
  - 产出结构化标签（blank_screenshot / low_contrast + 量化指标）
  - 判定自身异常时返回空标签并记 warning，绝不抛出（不阻断截图主流程）

阈值集中为模块常量，便于调参。
"""

import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

# ── 阈值常量 ───────────────────────────────────────────────────
# 像素标准差阈值（uint8 [0,255] 归一化后 [0,1]）
# std < 3/255 ≈ 0.0118：纯色图（含纯白/纯黑）的典型值
BLANK_STD_THRESHOLD = 3.0 / 255.0

# 主色占比阈值：> 99% 像素属于同一颜色 → 纯色图
BLANK_DOMINANT_COLOR_PCT = 0.99

# 低对比度阈值（对齐 skimage exposure.is_low_contrast 的 int8 口径）
# skimage 默认 low_contrast_limit=0.4（对应直方图累积范围占比）
# 此处用像素值范围 / std 近似：std 在 BLANK_STD_THRESHOLD 之上但 < 0.08 视为低对比度
LOW_CONTRAST_STD_UPPER = 0.08

logger = logging.getLogger(__name__)


def classify_screenshot(
    path: Union[str, Path],
    *,
    blank_std_threshold: float = BLANK_STD_THRESHOLD,
    blank_dominant_pct: float = BLANK_DOMINANT_COLOR_PCT,
    low_contrast_upper: float = LOW_CONTRAST_STD_UPPER,
) -> Dict[str, Any]:
    """对截图做健全性判定，返回结构化标签字典。

    标签规则：
      - blank_screenshot: std < blank_std_threshold 且主色占比 > blank_dominant_pct
      - low_contrast: std >= blank_std_threshold 但 < low_contrast_upper
      - 无标签: 正常截图（消费方以「缺标签」为正常态，向后兼容）

    Args:
        path: 截图 PNG 文件路径
        blank_std_threshold: 纯色判定的像素标准差上限（uint8 归一化到 [0,1]）
        blank_dominant_pct: 纯色判定的主色占比下限
        low_contrast_upper: 低对比度判定的 std 上限

    Returns:
        dict: 标签字典，至少含 blank_screenshot / low_contrast 之一（bool），
              及量化指标（pixel_std, dominant_color_pct, width, height）；
              判定异常时返回空 dict。
    """
    try:
        return _classify_impl(
            path,
            blank_std_threshold,
            blank_dominant_pct,
            low_contrast_upper,
        )
    except Exception as e:
        logger.warning(
            "screenshot_lab: 截图健全性判定失败（跳过标签，截图照常落盘）: "
            f"{type(e).__name__}: {e}",
        )
        return {}


def _classify_impl(
    path: Union[str, Path],
    blank_std_threshold: float,
    blank_dominant_pct: float,
    low_contrast_upper: float,
) -> Dict[str, Any]:
    """classify_screenshot 的内部实现（异常由调用方 try/except 捕获）。"""
    import numpy as np
    from PIL import Image

    img = Image.open(str(path)).convert("RGB")
    width, height = img.size
    pixels = np.array(img, dtype=np.float64)  # shape: (H, W, 3), range [0, 255]

    # 像素标准差（全局，跨 RGB 通道）
    pixel_std = float(np.std(pixels) / 255.0)

    # 主色占比：统计最常见像素值（RGB 三元组）的出现比例
    # 将每个像素展平为单个 "颜色 token"，统计频次
    flat = pixels.reshape(-1, 3).astype(np.uint8)
    # 用 numpy unique 按行统计；为避免 OOM 对超大图采样
    max_samples = 500_000
    if flat.shape[0] > max_samples:
        rng = np.random.default_rng(42)
        indices = rng.choice(flat.shape[0], size=max_samples, replace=False)
        flat = flat[indices]
    # 按行 hash 统计唯一值出现次数
    # PIL RGBA→RGB 已确保 3 通道；将 RGB 拼成单个 int 以便 unique
    color_tokens = (
        flat[:, 0].astype(np.uint32) << 16
        | flat[:, 1].astype(np.uint32) << 8
        | flat[:, 2].astype(np.uint32)
    )
    unique, counts = np.unique(color_tokens, return_counts=True)
    dominant_count = int(counts.max())
    dominant_color_pct = dominant_count / len(color_tokens)

    # 判定
    labels: Dict[str, Any] = {
        "pixel_std": round(pixel_std, 6),
        "dominant_color_pct": round(dominant_color_pct, 6),
        "width": width,
        "height": height,
    }

    if pixel_std < blank_std_threshold and dominant_color_pct > blank_dominant_pct:
        labels["blank_screenshot"] = True
    elif pixel_std < low_contrast_upper:
        labels["low_contrast"] = True
    # else: 无标签（正常截图）

    return labels
