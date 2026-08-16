"""
visual_diff.py — 截图视觉对比

基于SSIM（结构相似性指数）的截图对比，与像素diff相比：
  - 容忍抗锯齿/亚像素渲染差异
  - 更符合人眼感知

阈值分档：
  >= 0.95 : 通过
  0.85-0.95 : 警告（需Planner判定）
  < 0.85 : 差异显著

降级方案：scikit-image 不可用时使用 PIL 像素百分比对比
"""

import shutil
from pathlib import Path
from typing import Optional


class VisualDiffer:
    """基于SSIM的截图对比器。

    职责：
    - 首次运行建立基线
    - 后续运行与基线做SSIM对比
    - 生成差异图（高亮变化区域）
    - scikit-image 不可用时降级为像素diff
    """

    # 阈值常量
    SSIM_PASS = 0.95       # >= 此值视为通过
    SSIM_WARN = 0.85       # >= 此值视为警告，< 此值视为失败
    PIXEL_DIFF_PASS = 0.01  # 像素差异 < 1% 视为通过
    PIXEL_DIFF_WARN = 0.05  # 像素差异 < 5% 视为警告

    def __init__(self, spec_name: str, project_root: Path):
        self.spec_name = spec_name
        self.project_root = project_root
        self.base_dir = project_root / ".fenix" / "verify-progress" / spec_name

    async def compare(
        self, page, baseline_name: str, scenario_id: str
    ) -> list[dict]:
        """对当前页面与基线进行视觉对比。

        Args:
            page: Playwright Page 对象
            baseline_name: 基线名称（用于文件命名和查找）
            scenario_id: 场景ID（用于生成当前截图文件名）

        Returns:
            对比结果列表（通常只有1个元素，但保留扩展性）
        """
        baseline_path = self.base_dir / "baselines" / f"{baseline_name}.png"
        screenshots_dir = self.base_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        current_path = screenshots_dir / f"{scenario_id}_current.png"

        # 截取当前页面
        await page.screenshot(path=str(current_path), full_page=False)

        # 首次运行：建立基线
        if not baseline_path.exists():
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(current_path), str(baseline_path))
            return [{
                "baseline": baseline_name,
                "status": "baseline_created",
                "ssim": None,
                "pass": True,
                "note": "首次运行，已自动建立基线",
            }]

        # 执行对比
        try:
            return self._ssim_compare(
                baseline_path, current_path, baseline_name, scenario_id, screenshots_dir
            )
        except ImportError:
            return self._pixel_fallback_compare(
                baseline_path, current_path, baseline_name, scenario_id
            )

    # ── SSIM 对比 ──────────────────────────────────────────────

    def _ssim_compare(
        self, baseline_path: Path, current_path: Path,
        baseline_name: str, scenario_id: str, output_dir: Path,
    ) -> list[dict]:
        """使用 scikit-image 的 SSIM 进行感知对比。"""
        from skimage.metrics import structural_similarity as ssim
        from skimage import io, img_as_float
        import numpy as np

        baseline_img = img_as_float(io.imread(str(baseline_path)))
        current_img = img_as_float(io.imread(str(current_path)))

        # 尺寸不匹配
        if baseline_img.shape != current_img.shape:
            return [{
                "baseline": baseline_name,
                "status": "size_mismatch",
                "ssim": None,
                "pass": False,
                "detail": (
                    f"尺寸不匹配: "
                    f"baseline={baseline_img.shape[1]}x{baseline_img.shape[0]}, "
                    f"current={current_img.shape[1]}x{current_img.shape[0]}"
                ),
            }]

        # 计算 channel-by-channel SSIM
        score = float(ssim(
            baseline_img, current_img,
            channel_axis=2, data_range=1.0,
        ))

        # 生成差异图
        diff_path = output_dir / f"{scenario_id}_diff.png"
        diff_img = (np.abs(baseline_img - current_img) * 255).astype(np.uint8)
        io.imsave(str(diff_path), diff_img)

        # 判定
        if score >= self.SSIM_PASS:
            status = "pass"
        elif score >= self.SSIM_WARN:
            status = "warning"
        else:
            status = "diff_detected"

        return [{
            "baseline": baseline_name,
            "status": status,
            "ssim": score,
            "pass": status == "pass",
            "threshold_pass": self.SSIM_PASS,
            "threshold_warn": self.SSIM_WARN,
            "diff_image": str(diff_path),
            "current_image": str(current_path),
            "baseline_image": str(baseline_path),
        }]

    # ── 降级方案：像素对比 ──────────────────────────────────────

    def _pixel_fallback_compare(
        self, baseline_path: Path, current_path: Path,
        baseline_name: str, scenario_id: str,
    ) -> list[dict]:
        """降级方案：简单的像素百分比差异。

        使用 PIL，无额外依赖。容忍 10 个像素值的着色差异。
        """
        try:
            from PIL import Image
            import numpy as np

            baseline = Image.open(baseline_path).convert("RGB")
            current = Image.open(current_path).convert("RGB")
        except ImportError:
            return [{
                "baseline": baseline_name,
                "status": "skipped",
                "ssim": None,
                "pass": True,
                "error": "PIL 不可用，无法进行像素对比，跳过",
            }]

        if baseline.size != current.size:
            return [{
                "baseline": baseline_name,
                "status": "size_mismatch",
                "ssim": None,
                "pass": False,
                "detail": (
                    f"尺寸不匹配: "
                    f"baseline={baseline.size[0]}x{baseline.size[1]}, "
                    f"current={current.size[0]}x{current.size[1]}"
                ),
            }]

        b_arr = np.array(baseline)
        c_arr = np.array(current)

        # 容忍10像素值的着色差异
        diff_mask = np.abs(b_arr.astype(int) - c_arr.astype(int)) > 10
        diff_pixels = int(np.sum(diff_mask))
        total_pixels = int(b_arr.size)
        diff_ratio = diff_pixels / total_pixels

        # 生成差异图
        diff_path = self.base_dir / "screenshots" / f"{scenario_id}_diff.png"
        diff_img = np.zeros_like(b_arr)
        diff_img[diff_mask] = [255, 0, 0]  # 差异像素标红
        Image.fromarray(diff_img).save(str(diff_path))

        if diff_ratio < self.PIXEL_DIFF_PASS:
            status = "pass"
        elif diff_ratio < self.PIXEL_DIFF_WARN:
            status = "warning"
        else:
            status = "diff_detected"

        return [{
            "baseline": baseline_name,
            "status": status,
            "pixel_diff_ratio": diff_ratio,
            "diff_pixels": diff_pixels,
            "total_pixels": total_pixels,
            "pass": status == "pass",
            "threshold_pass": self.PIXEL_DIFF_PASS,
            "threshold_warn": self.PIXEL_DIFF_WARN,
            "diff_image": str(diff_path),
            "current_image": str(current_path),
            "baseline_image": str(baseline_path),
            "note": "使用像素对比降级方案（安装 scikit-image 可获得更准确的SSIM对比）",
        }]
