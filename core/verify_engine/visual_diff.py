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

视觉校验稳健性（fix-visual-baseline-settle）：
  - 截图前动画静置（settle）：等待 document.getAnimations() 全部 finished，
    覆盖 CLS 检测不到的 opacity/transform 渐变动画（antd Modal ~300ms fade
    污染基线事故链根因）。
  - SSIM 低分限次自动重拍（默认 2 次，每次重拍前再 settle），取最高 SSIM 分；
    仍低维持原判定（不放宽阈值、不篡改分数）。
  - 基线固化门：首次固化仅当该场景步骤与断言全部通过，否则 baseline_deferred
    顺延（健全性判定 blank/low_contrast 拒绝固化在门前保持）。
  - 存量污染基线侦测：连续 ≥3 轮 diff_detected 且 DOM 全过 → 基线标记
    suspicious + admin 告警；重建交人工确认（不自动覆盖/删除）。
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

from .browser import wait_animations_settled
from .screenshot_lab import classify_screenshot


class VisualDiffer:
    """基于SSIM的截图对比器。

    职责：
    - 首次运行建立基线（含动画静置 + 健全性判定 + 通过性固化门）
    - 后续运行与基线做SSIM对比（含低分限次重拍）
    - 生成差异图（高亮变化区域）
    - scikit-image 不可用时降级为像素diff
    - 追踪存量污染基线（baseline_streaks + suspicious 标记 + admin 告警）
    """

    # 阈值常量
    SSIM_PASS = 0.95  # >= 此值视为通过
    SSIM_WARN = 0.85  # >= 此值视为警告，< 此值视为失败
    PIXEL_DIFF_PASS = 0.01  # 像素差异 < 1% 视为通过
    PIXEL_DIFF_WARN = 0.05  # 像素差异 < 5% 视为警告

    # 配置缺省（fix-visual-baseline-settle D6）
    DEFAULT_SETTLE_TIMEOUT_MS = 3000
    DEFAULT_RETAKE_MAX = 2

    # 污染基线告警阈值（连续 ≥3 轮 diff_detected 且 DOM 全过）
    SUSPICIOUS_STREAK_THRESHOLD = 3
    # 侧车 ssims 滑动窗口上限（阈值 ×2）：长期 diff_detected（恰是本机制要
    # 侦测的污染场景）下逐轮 append 无上界，侧车 JSON 随时间无界增长——
    # 只保留最近窗口条目，告警证据可读性不受影响。
    SSIMS_WINDOW_LIMIT = SUSPICIOUS_STREAK_THRESHOLD * 2

    def __init__(
        self, spec_name: str, project_root: Path, config: Optional[dict] = None, logger=None
    ):
        self.spec_name = spec_name
        self.project_root = Path(project_root)
        self.config = config if isinstance(config, dict) else {}
        self.logger = logger
        self.base_dir = self.project_root / ".fenix" / "verify-progress" / spec_name

    # ── 配置读取（verify_engine 段，向后兼容缺省）────────────────

    def _verify_config(self) -> dict:
        """verify_engine 配置段（非 dict/缺失返回空 dict）。"""
        ve = self.config.get("verify_engine")
        return ve if isinstance(ve, dict) else {}

    def _settle_timeout_ms(self) -> int:
        """settle 等待上限（毫秒）；0/负值=禁用（行为与现状一致）。"""
        try:
            val = int(
                self._verify_config().get(
                    "visual_settle_timeout_ms", self.DEFAULT_SETTLE_TIMEOUT_MS
                )
            )
        except (TypeError, ValueError):
            val = self.DEFAULT_SETTLE_TIMEOUT_MS
        return max(val, 0)

    def _retake_max(self) -> int:
        """SSIM 低分重拍次数上限。"""
        try:
            val = int(self._verify_config().get("visual_retake_max", self.DEFAULT_RETAKE_MAX))
        except (TypeError, ValueError):
            val = self.DEFAULT_RETAKE_MAX
        return max(val, 0)

    @staticmethod
    def _scenario_passed(scenario_context: Optional[dict]) -> bool:
        """场景通过性上下文（web_runner 传入）：步骤全成功且断言全 pass。

        上下文缺失（向后兼容旧调用 / 测试直调）按通过处理。判定失败场景
        不固化基线的语义基础（fix-visual-baseline-settle D3）。
        """
        if not isinstance(scenario_context, dict):
            return True
        if scenario_context.get("steps_failed"):
            return False
        for a in scenario_context.get("assertion_results") or []:
            if isinstance(a, dict) and not a.get("pass", True):
                return False
        return True

    async def compare(
        self,
        page,
        baseline_name: str,
        scenario_id: str,
        scenario_context: Optional[dict] = None,
    ) -> list[dict]:
        """对当前页面与基线进行视觉对比。

        Args:
            page: Playwright Page 对象
            baseline_name: 基线名称（用于文件命名和查找）
            scenario_id: 场景ID（用于生成当前截图文件名）
            scenario_context: 场景通过性上下文（steps_failed + 断言结果），
                供基线固化门与污染基线侦测判定「DOM 是否全过」。

        Returns:
            对比结果列表（通常只有1个元素，但保留扩展性）
        """
        baseline_path = self.base_dir / "baselines" / f"{baseline_name}.png"
        screenshots_dir = self.base_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        current_path = screenshots_dir / f"{scenario_id}_current.png"

        settle_timeout_ms = self._settle_timeout_ms()
        retake_max = self._retake_max()
        retake_count = 0
        settle_waited_ms = 0

        async def _settle():
            """截图前动画静置；累计实际等待毫秒（记录于 settle_waited_ms）。"""
            nonlocal settle_waited_ms
            if settle_timeout_ms <= 0:
                return
            t0 = time.monotonic()
            await wait_animations_settled(page, settle_timeout_ms)
            settle_waited_ms += int((time.monotonic() - t0) * 1000)

        def _evidence_fields(result: dict) -> dict:
            """结果 dict 统一补充重拍/静置证据字段（未等待为 0）。"""
            merged = dict(result)
            merged["retake_count"] = retake_count
            merged["settle_waited_ms"] = settle_waited_ms
            merged["scenario_id"] = scenario_id
            return merged

        def _compare_once() -> list[dict]:
            """单次对比（SSIM，skimage 不可用时降级像素对比）。

            解码失败（基线/当前截图损坏或非图像文件）不向上抛：返回
            status='error' 结构化结果，首次对比与重拍循环两条路径同被覆盖。
            """
            try:
                try:
                    return self._ssim_compare(
                        baseline_path,
                        current_path,
                        baseline_name,
                        scenario_id,
                        screenshots_dir,
                    )
                except ImportError:
                    return self._pixel_fallback_compare(
                        baseline_path,
                        current_path,
                        baseline_name,
                        scenario_id,
                    )
            except (OSError, ValueError) as e:
                # ImportError 兜底接不住解码异常（PIL 的 UnidentifiedImageError
                # 属 OSError 子系，skimage 对损坏文件多抛 ValueError）——落盘
                # 中断等导致的坏图返回结构化 error 结果（与 size_mismatch/
                # skipped 同型），不击穿整场验证。
                return [
                    {
                        "baseline": baseline_name,
                        "status": "error",
                        "ssim": None,
                        "pass": False,
                        "detail": (
                            "截图读取/解码失败，视觉对比不可用: "
                            f"{type(e).__name__}: {e}"
                        ),
                        "scenario_id": scenario_id,
                    }
                ]

        # 截取当前页面（截图前动画静置——opacity 渐变动画只有 getAnimations
        # 能判定，CLS 布局偏移对纯淡入不敏感，见 _wait_stable 注释）
        await _settle()
        await page.screenshot(path=str(current_path), full_page=False)

        # ── 视觉基线防污染（attribution-freshness-governance / D5）──
        # 首次建立基线前先做健全性判定：命中 blank_screenshot / low_contrast →
        # 拒绝固化（白屏/低对比度基线无断言价值，且会污染后续 SSIM 对比——
        # 事故链教训：白屏被固化为基线，干净截图反而被判差异）。后续轮次
        # 截图干净时正常建立，不扩大失败。
        if not baseline_path.exists():
            labels = classify_screenshot(str(current_path))
            has_pollution = labels.get("blank_screenshot") or labels.get("low_contrast")
            if has_pollution:
                return [
                    _evidence_fields(
                        {
                            "baseline": baseline_name,
                            "status": "baseline_rejected",
                            "ssim": None,
                            "pass": False,
                            "note": (
                                "首次运行，截图健全性判定不通过"
                                f"（{'blank_screenshot' if labels.get('blank_screenshot') else 'low_contrast'}），"
                                "拒绝固化为基线——环境性伪画面不得固化，"
                                "后续轮次截图干净时正常建立基线"
                            ),
                            "screenshot_labels": labels,
                        }
                    )
                ]

            # ── 基线固化门（fix-visual-baseline-settle D3）──
            # 健全性判定在前（拒绝污染画面），通过性门在后（拒绝失败场景固化）
            # ——两道独立防线。不满足前置条件则本轮不固化，视觉结果记
            # baseline_deferred（非 pass 非 fail，下游按非打回依据处理），
            # 下轮干净时正常固化。已声明无法验证的步骤失败/断言失败画面
            # 与断言态不一致，固化即污染（取证定案：antd Modal 首轮 fade
            # 未完成 → 污染基线恒比恒低）。
            if not self._scenario_passed(scenario_context):
                return [
                    _evidence_fields(
                        {
                            "baseline": baseline_name,
                            "status": "baseline_deferred",
                            "ssim": None,
                            "pass": False,
                            "note": (
                                "首次运行且存在步骤/断言失败，基线固化前置条件不满足"
                                "（步骤全成功 + 断言全通过才固化），本轮不固化，"
                                "顺延至场景干净轮次"
                            ),
                        }
                    )
                ]

        # 首次运行：建立基线（正常画面 + 通过性门通过）
        if not baseline_path.exists():
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(str(current_path), str(baseline_path))
            return [
                _evidence_fields(
                    {
                        "baseline": baseline_name,
                        "status": "baseline_created",
                        "ssim": None,
                        "pass": True,
                        "note": "首次运行，已自动建立基线",
                    }
                )
            ]

        # 执行对比（首次）
        # [fenix-ignore:7cf3ba96236e] 问题已由提交 9362f29b 修复：_compare_once
        # 内层已有 (OSError, ValueError) 解码异常兜底，返回与 size_mismatch/
        # skipped 同型的 status='error' 结构化结果，首次调用与重拍循环均覆盖。
        results = _compare_once()
        best = results[0]

        # ── SSIM 低分自动重拍（fix-visual-baseline-settle D2）──
        # pass=False（含 warning 档：0.85-0.95 的时序噪声）时重拍，每次重拍前
        # 再 settle；限 retake_max 次，取最高 SSIM 分做最终结果。时序噪声单侧
        # 分布（重拍只会更干净），取最高分等价「择优取证」；重拍后仍低则维持
        # 原判定（不掩盖真回归），不重拍第 N+1 次。
        for _ in range(retake_max):
            if best.get("pass"):
                break
            if best.get("status") not in ("warning", "diff_detected"):
                break  # 结构性失败（size_mismatch 等）重拍无意义
            await _settle()
            await page.screenshot(path=str(current_path), full_page=False)
            retake_count += 1
            cand = _compare_once()[0]
            if self._compare_score(cand) > self._compare_score(best):
                best = cand

        final = _evidence_fields(best)

        # ── 存量污染基线侦测（fix-visual-baseline-settle D5）──
        # 同场景连续 diff_detected 且同期 DOM 全过 → 累计；达 3 轮标记基线
        # suspicious + admin 人工告警。基线只标记不处置（重建交人工确认，
        # 自动覆盖会洗白「基线对、当前版本真回归」镜像场景）。
        self._update_baseline_streaks(scenario_id, baseline_name, scenario_context, final)

        return [final]

    @staticmethod
    def _compare_score(result: dict):
        """单次对比结果的比较分（越高越好）：SSIM 优先，像素降级用 1-差异比。"""
        ssim = result.get("ssim")
        if isinstance(ssim, (int, float)):
            return float(ssim)
        ratio = result.get("pixel_diff_ratio")
        if isinstance(ratio, (int, float)):
            return 1.0 - float(ratio)
        return -1.0

    # ── 存量污染基线侦测 ──────────────────────────────────────

    def _streaks_path(self) -> Path:
        return self.base_dir / "baseline_streaks.json"

    def _load_baseline_streaks(self) -> dict:
        """读取连续异常计数侧车（同 warning_streaks.json 模式）。

        结构 {scenario_id: {"count": int, "suspicious": bool,
        "ssims": [每轮最终 SSIM]}}；缺失/损坏返回 {}（fail-open）。
        """
        path = self._streaks_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save_baseline_streaks(self, streaks: dict) -> None:
        """原子写回连续异常计数侧车（temp + rename，与 warning_streaks 同型）。

        并发语义（code-review item c046b5c543e6）：读-改-写三段非原子，
        两进程并发验证同一 spec 时为后写覆盖，最多丢对方一轮累计——仅把
        suspicious 告警推迟一轮、不产生误报；每轮 _update_baseline_streaks
        都重新 load 盘上最新态，下一轮即追平。故有意不加锁/不合并：
        count 存在清零分支（pass/DOM 失败），max 类合并会在「并发一真
        pass 一 diff」交错下复活已清零的计数，风险大于收益。
        """
        path = self._streaks_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), prefix=".baseline_streaks.", suffix=".json.tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(streaks, f, ensure_ascii=False, indent=2)
                    f.flush()
                os.replace(tmp_path, path)
            except OSError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except OSError as e:
            self._log_warning(f"baseline_streaks 写回失败: {e}")

    def _suspicious_marker_path(self, baseline_name: str) -> Path:
        return self.base_dir / "baselines" / f"{baseline_name}.suspicious"

    def _mark_suspicious(self, baseline_name: str, scenario_id: str) -> None:
        """基线旁写 <name>.suspicious 标记文件（只标记，不覆盖/删除基线）。"""
        try:
            marker = self._suspicious_marker_path(baseline_name)
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                json.dumps(
                    {
                        "baseline": baseline_name,
                        "scenario_id": scenario_id,
                        "suspicious": True,
                        "note": "连续多轮 diff_detected 且 DOM 断言全过，基线疑似污染；"
                        "重建需人工确认（框架不会自动覆盖/删除基线）",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError as e:
            self._log_warning(f"suspicious 标记写失败: {e}")

    def _remove_suspicious(self, baseline_name: str) -> None:
        """SSIM 恢复非 diff_detected 时撤除 suspicious 标记。"""
        try:
            self._suspicious_marker_path(baseline_name).unlink(missing_ok=True)
        except OSError:
            pass

    def _alert_suspicious(
        self, scenario_id: str, baseline_name: str, count: int, ssims: list
    ) -> None:
        """连续 ≥3 轮 diff_detected + DOM 全过 → admin 人工告警（D5）。

        复用既有 admin 告警通道（AdminStore，.fenix/admin_alerts.json），
        正文含场景 ID、各轮 SSIM、基线文件路径（与人工冻结/失效可修等既有
        告警同模式）。告警只提醒人工核实，不自动处置。
        """
        try:
            from core.admin_store import AdminStore, ESCALATION

            baseline_path = self.base_dir / "baselines" / f"{baseline_name}.png"
            ssim_text = ", ".join(str(s) if s is not None else "-" for s in (ssims or []))
            store = AdminStore(self.project_root, self.logger)
            entry = {
                "kind": ESCALATION,
                "signal_type": "visual_baseline_suspicious",
                "spec": self.spec_name,
                "severity": "major",
                "description": (
                    f"视觉基线疑似污染：场景 {scenario_id}（基线 {baseline_name}）"
                    f"连续 {count} 轮 SSIM 恒 diff_detected 且 DOM 断言全过"
                ),
                "evidence": (f"各轮 SSIM: {ssim_text}；基线文件: {baseline_path}"),
                "recommended_action": (
                    "人工核实基线画面与断言态是否一致（如首轮 antd Modal fade "
                    "未完成固化的污染基线）；确认为污染后删除基线文件，下一轮"
                    "验证将自动重建干净基线——框架不会自动覆盖或删除已固化基线。"
                ),
            }
            from core.alert_lifecycle import build_trigger

            trigger = build_trigger("visual_baseline_suspicious", self.spec_name)
            if trigger:
                entry["trigger"] = trigger
            store.append(entry)
        except Exception as e:
            self._log_warning(f"suspicious 告警发送失败: {type(e).__name__}: {e}")

    def _update_baseline_streaks(
        self, scenario_id: str, baseline_name: str, scenario_context: Optional[dict], result: dict
    ) -> None:
        """连续异常计数侧车更新（D5，仅对已存在基线的对比轮）。

        - diff_detected + DOM 全过 → 计数 +1（达 3 标记 suspicious + 告警）
        - diff_detected + DOM 有失败 → 本轮不累计、计数清零（真实产品缺陷
          不伪装成基线污染，不告警）
        - 恢复 pass/warning → 计数清零并撤 suspicious 标记
        - baseline_deferred 等其他状态 → 不累计也不清零（等下次真实对比再判定）
        """
        status = result.get("status")
        streaks = self._load_baseline_streaks()
        if status == "diff_detected":
            if self._scenario_passed(scenario_context):
                entry = streaks.get(scenario_id)
                if not isinstance(entry, dict):
                    entry = {"count": 0, "suspicious": False, "ssims": []}
                # 脏 count 容错（code-review item c106c112a806）：侧车仅校验
                # 顶层 dict，条目内 count 可能为 null/非数值（历史写手/手改），
                # 与 _settle_timeout_ms/_retake_max 同惯例回退 0，防脏值击穿对比
                try:
                    prev_count = int(entry.get("count", 0))
                except (TypeError, ValueError):
                    prev_count = 0
                entry["count"] = prev_count + 1
                ssim = result.get("ssim")
                ssim_list = entry.setdefault("ssims", [])
                ssim_list.append(
                    round(float(ssim), 4) if isinstance(ssim, (int, float)) else None
                )
                # 滑动窗口截断（code-review item 76391cfd1e3c）：持续
                # diff_detected 下 ssims 逐轮追加无上界，防侧车文件无界增长
                del ssim_list[: max(0, len(ssim_list) - self.SSIMS_WINDOW_LIMIT)]
                newly_suspicious = entry[
                    "count"
                ] >= self.SUSPICIOUS_STREAK_THRESHOLD and not entry.get("suspicious")
                if newly_suspicious:
                    entry["suspicious"] = True
                    self._mark_suspicious(baseline_name, scenario_id)
                    self._alert_suspicious(
                        scenario_id, baseline_name, entry["count"], entry.get("ssims") or []
                    )
                streaks[scenario_id] = entry
            else:
                # DOM 有真实失败：该轮不累计，计数清零；已标记的 suspicious
                # 保留待人工（仅在 SSIM 恢复时撤除，见下方 pass/warning 分支）
                prev = streaks.get(scenario_id)
                streaks[scenario_id] = {
                    "count": 0,
                    "suspicious": bool(isinstance(prev, dict) and prev.get("suspicious")),
                    "ssims": [],
                }
        elif status in ("pass", "warning"):
            # SSIM 恢复非 diff_detected → 清零并撤 suspicious 标记
            streaks[scenario_id] = {"count": 0, "suspicious": False, "ssims": []}
            self._remove_suspicious(baseline_name)
        else:
            # baseline_deferred / baseline_rejected / baseline_created /
            # size_mismatch / error / skipped：不累计也不清零
            return
        self._save_baseline_streaks(streaks)

    def _log_warning(self, message: str) -> None:
        """宽容双形态 logger（兼容标准 logging 与 fenixd (component, msg)）。"""
        if not self.logger:
            return
        log_fn = getattr(self.logger, "warning", None)
        if not log_fn:
            return
        try:
            log_fn(f"[visual_diff] {message}")
        except TypeError:
            log_fn("visual_diff", message)

    # ── SSIM 对比 ──────────────────────────────────────────────

    def _ssim_compare(
        self,
        baseline_path: Path,
        current_path: Path,
        baseline_name: str,
        scenario_id: str,
        output_dir: Path,
    ) -> list[dict]:
        """使用 scikit-image 的 SSIM 进行感知对比。"""
        from skimage.metrics import structural_similarity as ssim
        from skimage import io, img_as_float
        import numpy as np

        baseline_img = img_as_float(io.imread(str(baseline_path)))
        current_img = img_as_float(io.imread(str(current_path)))

        # 尺寸不匹配
        if baseline_img.shape != current_img.shape:
            return [
                {
                    "baseline": baseline_name,
                    "status": "size_mismatch",
                    "ssim": None,
                    "pass": False,
                    "detail": (
                        f"尺寸不匹配: "
                        f"baseline={baseline_img.shape[1]}x{baseline_img.shape[0]}, "
                        f"current={current_img.shape[1]}x{current_img.shape[0]}"
                    ),
                    "scenario_id": scenario_id,
                }
            ]

        # 计算 channel-by-channel SSIM
        score = float(
            ssim(
                baseline_img,
                current_img,
                channel_axis=2,
                data_range=1.0,
            )
        )

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

        return [
            {
                "baseline": baseline_name,
                "status": status,
                "ssim": score,
                "pass": status == "pass",
                "threshold_pass": self.SSIM_PASS,
                "threshold_warn": self.SSIM_WARN,
                "diff_image": str(diff_path),
                "current_image": str(current_path),
                "baseline_image": str(baseline_path),
                "scenario_id": scenario_id,
            }
        ]

    # ── 降级方案：像素对比 ──────────────────────────────────────

    def _pixel_fallback_compare(
        self,
        baseline_path: Path,
        current_path: Path,
        baseline_name: str,
        scenario_id: str,
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
            return [
                {
                    "baseline": baseline_name,
                    "status": "skipped",
                    "ssim": None,
                    "pass": True,
                    "error": "PIL 不可用，无法进行像素对比，跳过",
                    "scenario_id": scenario_id,
                }
            ]

        if baseline.size != current.size:
            return [
                {
                    "baseline": baseline_name,
                    "status": "size_mismatch",
                    "ssim": None,
                    "pass": False,
                    "detail": (
                        f"尺寸不匹配: "
                        f"baseline={baseline.size[0]}x{baseline.size[1]}, "
                        f"current={current.size[0]}x{current.size[1]}"
                    ),
                    "scenario_id": scenario_id,
                }
            ]

        b_arr = np.array(baseline)
        c_arr = np.array(current)

        # 容忍10像素值的着色差异（掩码归约到像素级：(H,W,3) 逐通道比较经
        # any(axis=2) 收敛为 (H,W)，否则布尔索引赋值 [255,0,0] 无法广播）
        diff_mask = (np.abs(b_arr.astype(int) - c_arr.astype(int)) > 10).any(axis=2)
        diff_pixels = int(diff_mask.sum())
        total_pixels = int(b_arr.shape[0] * b_arr.shape[1])
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

        return [
            {
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
                "scenario_id": scenario_id,
                "note": "使用像素对比降级方案（安装 scikit-image 可获得更准确的SSIM对比）",
            }
        ]
