"""fast_track.py — F fast-track 车道（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 17 个方法，refactor-giant-classes 拆包时原样搬移为
mixin（方法体零改动；当时的中转文件 core/pm_engine/dispatch/_legacy.py
已随拆包完成移除）。F 组方法在原 Dispatcher 中被 P 组（repair）物理
分隔（段1：scale_precheck..reconcile_and_merge，段2：
hard_check_fast_track..deliverable_gate），两段合并在本模块中。

跨组协作（_direct_rehearsed_to_repair / _should_enter_repair /
_dispatch_repair_lane 等 P 组方法，现位于 core/pm_engine/dispatch/
repair_lane.py，与其余各组 mixin 同拼装于 Dispatcher）仍经宿主实例
`self.<method>` 协作。

D3 patch 缝隙：本组使用 `time` 模块，经模块顶部导入——测试
patch time 模块对象属性全进程共享，重绑依旧生效。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from core.fast_track_result import (
    budget_tier_for_scale,
    estimate_spec_scale,
    get_scale_precheck_config,
)
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD
from core.agent_runner.provider_circuit import (
    MODEL_CHAIN_UNAVAILABLE_MARKER,
    PROVIDER_CIRCUIT_ERROR_MARKER,
)


def _normalize_int_config(value, default: int) -> int:
    """整型配置归一单点工具（code-review item c832188fbbac）。

    「try int + except (TypeError, ValueError) 回退缺省 + None 判空防 or
    吞 0」归一化的单一落点：字符串配置裸用于比较会抛 TypeError，非法值
    回退缺省（code-review item 74317ab4a77a）；``None`` 判空而非 ``or``
    兜底，合法配置 0 不被吞成缺省（code-review item c54ffbef69c5）。
    供 merge_breaker_threshold / max_retries 等整型配置键共用，新副本
    不再复制 try/except 形态。
    """
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class FFastTrackMixin:
    """F fast-track 车道（design D1 表 B F 组）。"""

    def _fast_track_scale_precheck(self, spec_name: str) -> tuple:
        """fast-track 派发前规模预估：返回 (scale, tier)，含预留日志。

        - 配置 ``agents.scale_precheck``（设置界面「预算」页签）总开关关闭时
          **整个跳过预检**，返回 ``(0, "disabled")``——调用方据此既不写
          higher 档位标记也不触发 full 降级（回到预检上线前行为）；
        - scale = estimate_spec_scale(spec_dir)：tasks.md 未勾选任务条数 ×1
          + 声明段交付物数 ×2；
        - tier = budget_tier_for_scale(scale, higher/full 阈值取自配置)；
        - 预检异常（tasks.md 缺失/IO 失败/路径非法）保守低档放行（design D2，
          不阻断派发），WARNING 留痕；异常不扩散（不抛）。
        - 日志含 spec、规模分、档位（任务 2.1「预留日志」）。
        """
        # 开关与阈值取同一份配置快照（code-review item 61bc711dab89）：
        # 同一轮预检只读一次，避免两读之间设置保存新阈值时开关按旧值判过、
        # tier 按新阈值算出的取值不一致窗口。
        cfg = self._scale_precheck_config()
        if not cfg["enabled"]:
            self._pm.logger.debug(
                "pm_engine",
                f"fast-track 规模预检已关闭，跳过 '{spec_name}'",
            )
            return 0, "disabled"
        spec_dir = self._pm.project_root / "spec" / "changes" / spec_name
        scale = 0
        tier = "normal"
        try:
            scale = int(estimate_spec_scale(spec_dir, logger=self._pm.logger))
            tier = budget_tier_for_scale(
                scale,
                higher_threshold=cfg["higher_threshold"],
                full_threshold=cfg["full_threshold"],
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 规模预检异常 '{spec_name}'（低档放行）: {e}",
            )
        self._pm.logger.info(
            "pm_engine",
            f"fast-track 规模预检 '{spec_name}': scale={scale} tier={tier}",
        )
        return scale, tier

    def _scale_precheck_config(self) -> dict:
        """读取并归一化 ``agents.scale_precheck``（缺省 enabled=True / 30 / 45）。

        归一化（非法值回退缺省、阈值倒挂整段回退）单点在
        ``core.fast_track_result.get_scale_precheck_config``，与设置界面读侧
        同源，避免展示值与生效值脱节。
        """
        return get_scale_precheck_config(self._pm.config or {})

    def _downgrade_fast_track_scale(self, spec_name: str, scale: int) -> None:
        """full 档规模降级：fast-track 大任务面改走完整模式（design D1）。

        - 改写 .spec.yaml mode → full（复用既有升级路径的改写语义）；
        - spec 状态回滚 ready（error 写明降级原因与规模分），重新入队
          implementer（完整模式车道，预算闸门/内容完整性闸门同层生效）；
        - 本次不启动 fast-track run、不递增实现预算（_run_agent_worker 调用
          点先于 _increment_impl_run_budget_used）；
        - 改写失败仅 WARNING（非阻塞，下轮派发仍按 fast-track 原档重试）。

        （fix-fasttrack-recovery-resume D4 锚点要求）本路径 MUST NOT 清空
        ``branch``/``implementer_run``，MUST NOT 消费 ``_recovery_resume``——
        降级后走 implementer 车道，由后者按其分支消费续做标记（design D4）：
        降级路径在 dispatch 入口的续做判定**之前** return，若此处清锚点/消费
        标记，随后的 implementer 派发将丢失可续做的保留分支。
        """
        # _rewrite_fast_track_to_full 内部已自吞改写异常（仅记 WARNING，非阻塞，
        # 改写失败时下轮派发仍按 fast-track 原档重试），此处无需再包 try/except。
        self._rewrite_fast_track_to_full(spec_name)
        # （fix-fasttrack-recovery-resume D4）本 update_spec 只写 status/error——
        # **不得**在此清空 branch/implementer_run，也**不得**消费 _recovery_resume：
        # 降级后走 implementer 车道，保留的锚点与标记须原样交给其派发入口消费。
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "status": "ready",
                "error": (f"fast-track 规模预检降级完整模式（scale={scale}，任务面超阈）"),
            },
        )
        self._enqueue(spec_name, "implementer")
        self._pm.logger.warning(
            "pm_engine",
            f"fast-track 规模预检降级 '{spec_name}'：scale={scale} 超阈，"
            f"改走完整模式 implementer 车道（不再按 3.5h 统一档）",
        )

    def _run_fast_track_worker(
        self, spec_name: str, pre_wt_path: Path | None = None
    ) -> None:
        """处理 fast-track 单 run 结果：守卫 → 硬校验 → 状态推进。

        在 _run_agent_worker 的 fast-track 分支被同步调用（同线程，预算已递增）。
        完整路径：ensure_spec_committed → run_fast_track → guards → merge →
        hard-check → state advance；任一步骤失败按失败重派（与 implementer 同语义）。

        Args:
            spec_name: SPEC 名称。
            pre_wt_path: 可选。非 None 时经 ``agent_runner.run_fast_track``
                透传到 ``_execute_agent``——在既有 worktree 内续做
                （interrupt-recovery-preserve 恢复续做），不创建新 worktree；
                语义与 implementer 车道的 ``run_implementer(pre_wt_path=...)``
                相同。本方法是 ``run_fast_track`` 的**唯一**调用点（queue.py
                fast-track 分支），无其它调用点需同步。
        """
        wm = self._pm.agent_runner.worktree_manager
        try:
            wm.ensure_spec_committed(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track ensure_spec_committed 失败 '{spec_name}': {e}（非阻塞）",
            )

        # ── 派发时落可信基线快照（add-declaration-relocation-protocol D3）──
        # 把当前**主树**声明集合快照到 .fenix/verify-progress/<spec>/
        # declaration-baseline.json（worktree 之外，实现 Agent 路径不写入），
        # 作为收工守卫收缩防护的独立参照系。
        # 写入异常仅 WARNING 不阻塞派发（收缩防护该轮降级保守）。
        try:
            from core.deliverables import snapshot_declaration_baseline

            snapshot_declaration_baseline(
                spec_name,
                f"ft-dispatch-{int(time.time())}",
                self._pm.project_root,
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 基线快照落盘失败 '{spec_name}'（仅 WARNING 不阻塞）: {e}",
            )
        try:
            result = self._pm.agent_runner.run_fast_track(
                spec_name, pre_wt_path=pre_wt_path
            )
        except Exception as e:
            self._pm._rollback_failed_dispatch(spec_name, "fast-track", e)
            return

        # verify-process-lifecycle（D3 dispatch 兜底）：runner success 返回后的
        # hand-off 边界内抛异常时，runner 的 finally 因 fast-track 属 handed_off
        # 而跳过收割——此处兜底收割 result.worktree_path 的 dev-server 注册条目，
        # 避免 keep/release 判定未执行而 dev-server 永久滞留。
        try:
            self._run_fast_track_flow(spec_name, result)
        except Exception:
            self._harvest_fast_track_worktree(spec_name, result)
            raise

    def _run_fast_track_flow(self, spec_name: str, result) -> None:
        """fast-track run 结果处理主体（守卫/校验/推进）。

        与 _run_fast_track_worker 分离，使 worker 可对其包 try/except 兜底收割
        （verify-process-lifecycle D3）。任一步骤失败按失败重派同语义返回。
        """
        # ── 冻结终止 hold-state（add-freeze-stop-inflight-agents 3.2）──
        # 被冻结终止的 fast-track run：独立保持分支，在 cancelled 分支之前
        #（spec 级 > run 级）。只写 _frozen_hold 标记 + error、不翻转 status、
        # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派、不豁免预算；
        # worktree 保留语义不变（runner 保留现场供解冻后续做）。
        # 判定用 `is True`（修复验证轮 BUG：MagicMock 替身自动生成 truthy
        # 属性，裸布尔会误判）；生产结果 frozen_terminated 为显式 bool。
        if getattr(result, "frozen_terminated", False) is True:
            ft_err = getattr(result, "error", None) or ""
            frozen_err = (
                f"run 因 spec 冻结被终止（进度已保全，解冻后续做）"
                f"{': ' + ft_err if ft_err else ''}"
            )
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track run 因 spec 冻结被终止 '{spec_name}' — "
                f"_frozen_hold，不重试/不重派: {frozen_err}",
            )
            self._pm.state_machine.mark_frozen_hold(
                spec_name, frozen_err)
            return

        # ── 人工取消 hold-state（add-run-cancel D4，fast-track 同语义）──
        # 被取消的 fast-track run 结果 cancelled=True：只写 error、不翻 status、
        # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派；worktree
        # 保留语义不变（_keep_fast_track_worktree 幂等，runner 已在取消路径保留）。
        # 判定与上方 frozen_terminated 同用 `is True`（MagicMock 替身自动生成
        # truthy cancelled 属性，裸真值会把正常 run 误入取消分支；生产结果
        # cancelled 为显式 bool，runner.py 取消路径写 True）。
        if getattr(result, "cancelled", False) is True:
            ft_err = getattr(result, "error", None) or ""
            cancelled_err = f"run 被人工取消：{ft_err}" if ft_err else "run 被人工取消"
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track run 被人工取消 '{spec_name}' — hold-state，"
                f"不重试/不重派: {cancelled_err}",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": cancelled_err,
                    # 取消保持持久标记（fix-cancel-holdstate-recovery D1）。
                    "_cancelled_hold": True,
                },
            )
            return

        # ── 读取结果文件（fast-track 结果文件是强制的，缺文件 = 失败） ──
        ft_result = self._pm._read_implementer_result(spec_name)
        if ft_result is None:
            # ── 结果文件缺失分流（fix-fasttrack-resultfile-missing-redispatch D2）──
            # 两起事故：分支已提交的成果被当「run 死亡」discard 后从零重派
            # （add-turn-limit-anchor-c run1 / add-main-tree-deps-provision run1，
            # 均已全量提交仍判死亡）。结果文件缺失但实现分支相对 main 已有提交
            # → 不判死亡：不回退预算、不 reset ready，merge 分支 + 改写
            # .spec.yaml mode→full + enqueue 完整模式 verifier 补齐缺失的 verdict，
            # 随后走既有 verified→done 门。分支零提交/无 branch → 维持既有
            # 死亡豁免 + reset ready + 自动重派（原封不动）。
            # result.success 门：runner 仅在 success 时填 branch（runner.py:2644），
            # 失败/中断 run 的 branch 为空——显式保留该前置，对齐 spec WHEN 子句
            # 「正常收工（exit 0，result.success 为真、result.branch 非空）」。
            # （fix-fasttrack-recovery-resume 4.1 出口矩阵：结果文件缺失分流）
            # 本出口对 branch/implementer_run/_recovery_resume 均**不触碰**——
            # merge 路径（_handle_fast_track_missing_result_merge）复用成功语义，
            # 失败路径（_handle_fast_track_failure）仅退预算/重试，均不新增清锚点
            # 也不消费恢复标记（标记属 dispatch 入口一次性消费，见 queue.py）。
            if getattr(result, "success", False) and self._pm._implementation_branch_has_commits(
                result
            ):
                self._handle_fast_track_missing_result_merge(spec_name, result)
                return
            self._keep_fast_track_worktree(spec_name, result)
            # 文案面向人：说明发生了什么 + 系统将自动重试（轮次由
            # _handle_fast_track_failure 按实际计数追加）。"fail-closed 不推进"
            # 类状态机术语曾让用户误读为 spec 被阻塞（2026-09-04 反馈）。
            self._handle_fast_track_failure(
                spec_name,
                result,
                "本轮实现中断：fast-track 结果文件未产出（run 异常结束），将自动重试",
                # 豁免判据传真实归因而非上方固定人文案（code-review item
                # 2d2da33c5b15，对齐 full 车道 queue.py 死亡 run 豁免形态：
                # run_reason 用 result.error、error 字段用人话文案）——固定文案
                # 永不命中监督击杀关键词，会把监督超时/停滞击杀的 run 误豁免。
                run_reason=getattr(result, "error", None),
            )
            return
        # ── 诚实退出收敛（fast-track 车道，2026-09-16 改进② 补齐收敛路径）──
        # partial 收工且**缺口全部 ⊆ unattainable 申报**时视同成功收口，继续走
        # 零变更哨 / 交付物守卫 / relint / merge / verified 推进；未申报缺口或
        # 非 partial 的失败形态仍走既有重派通道（防 partial 洗白）。
        honest_exit_gap: list = []
        if result.success and ft_result.get("status") == "partial":
            honest_exit_gap = self._honest_exit_gap(self._pm, spec_name, ft_result)
        if not result.success or (
            ft_result.get("status") != "success" and not honest_exit_gap
        ):
            self._keep_fast_track_worktree(spec_name, result)
            if result.success:
                status_val = ft_result.get("status")
                if status_val == "partial":
                    # fix-impl-tasks-completion-gate D6：fast-track partial 同
                    # implementer 语义——is_success 为假、不进 implemented；
                    # 失败归因 MUST 非空（unfinished 清单与缺口 id 构成，不得
                    # 沿用为 None 的 result.error）。partial 走 _handle_fast_track_
                    # failure 的失败/预算消耗通道（连续 partial 由预算上限收口）。
                    final_error = self._pm._partial_attribution(spec_name, ft_result, result)
                else:
                    # run 正常收工但结果文件顶层 status 非法：error 写明实际值与修法
                    # 处方——不用无信息量兜底文案（add-agent-prompt-files 事故：
                    # status 被写成 'verified'，兜底文案 'fast-track run failed' 让
                    # 重派 run 不知错在哪，可能原样再犯）。
                    final_error = (
                        f"结果文件 status={status_val!r} 非法——顶层合同唯一合法值为 "
                        f"'success'（verified/bug-found 属于 verification.verdict；"
                        f"partial 用于申报未完成）。"
                        f"修复：重写 .fenix-run-result.json 顶层 status"
                    )
            else:
                final_error = ft_result.get("error") or result.error or "fast-track run failed"
            # 传入 flow 层已解析结果（非 None），豁免判定不再二次读盘
            # （code-review item 417ec4668570）。
            self._handle_fast_track_failure(
                spec_name, result, final_error, ft_result=ft_result
            )
            return

        if honest_exit_gap:
            # 人工退出放行留痕（与 full 车道同语义）：/fenix-approve 环节可见
            # 「哪些任务交给了人工」。告警写失败仅 debug，不阻断收敛。
            self._pm.logger.warning(
                "pm_engine",
                f"诚实退出收敛（fast-track）'{spec_name}'：partial 缺口全部 ⊆ "
                f"unattainable 申报 {honest_exit_gap} —— 不重派，按成功收口",
            )
            try:
                self._pm._note_unattainable_todos(spec_name, ft_result, honest_exit_gap)
            except Exception as e:  # noqa: BLE001 — 非阻塞
                self._pm.logger.debug(
                    "pm_engine",
                    f"unattainable 待办告警写入失败（不阻断收敛）: {e}",
                )

        # ── 零变更成功哨 ──
        if self._pm._implementer_zero_change(spec_name, result):
            self._keep_fast_track_worktree(spec_name, result)
            # ── 验证确认型 no-op 放行（code-review item 9e148901155e，与 full
            # 车道 queue.py 零变更哨守卫同源，add-web-ui 事故原地修）── 分支零
            # 提交 + 交付物齐备 = 合法验证确认完成（分支零提交时 rev-list
            # main..branch == 0 ⟺ 已并入 main），走成功收口不重派；缺件仍按空转
            # 重派（_handle_fast_track_zero_change）。成功收口复用正常路径形态：
            # _reconcile_and_merge（merge 失败内部已处置，早退；merge 成功分支
            # 内含 implemented 推进 + _zero_change_attempts 清零）→ 快照/清理 →
            # _fast_track_advance_to_verified。
            if not self._pm._deliverable_gate_missing(spec_name, result):
                self._pm.logger.warning(
                    "pm_engine",
                    f"零变更哨·确认型 no-op（fast-track）'{spec_name}' — 交付物齐备"
                    f"且分支零提交（已并入 main），走成功收口（不重派）"
                    f"run={getattr(result, 'run_id', '') or ''}",
                )
                merged = self._reconcile_and_merge(spec_name, result)
                if not merged:
                    return  # merge 失败内部已处置（保留 worktree + 重派/熔断）
                try:
                    self._pm._write_impl_result_snapshot(spec_name, ft_result)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"fast-track 确认型 no-op impl-result 快照写入失败 "
                        f"'{spec_name}'（非阻塞）: {e}",
                    )
                self._pm._cleanup_shared_result_file(spec_name)
                self._fast_track_advance_to_verified(spec_name, result)
                return
            self._handle_fast_track_zero_change(spec_name, result)
            return

        # ── 交付物守卫 ──
        missing = self._pm._deliverable_gate_missing(spec_name, result)
        if missing:
            self._keep_fast_track_worktree(spec_name, result)
            # 接入同源裁决流水线（4.4）：陈日重定位 / 预分类软化 / LLM 终审 /
            # 防洗白复检与 full 车道一致，MUST NOT 直按缺件重派。裁决放行
            # （action=proceed）→ 继续后续 merge 推进；handled（已终态处置：
            # 重派/blocked）→ 直接 return。
            adjudication = self._handle_fast_track_deliverable_gate(
                spec_name, result, missing, impl_result=ft_result
            )
            if adjudication.get("action") != "proceed":
                return

        # ── tasks.md 收口复检门禁（add-tasksmd-relint-gate）──────────────
        # 与 full 车道同语义的事后复检：fast-track 成功收口前以 worktree 内
        # tasks.md（最新版本，worktree 成功路径延迟清理仍在）为基准判定。
        # 违规 → 保留 worktree + 走失败重派（error 写违规明细与修正处方）。
        # 读取失败/无 path/异常 → fail-open 不拦（lint 既有 fail-open 语义）。
        try:
            relint = self._pm._tasks_md_relint_from_worktree(
                spec_name, getattr(result, "worktree_path", None)
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"tasks.md relint 执行异常（fail-open）'{spec_name}': {e}",
            )
            relint = []
        if relint:
            self._keep_fast_track_worktree(spec_name, result)
            self._redispatch_tasks_relint(
                spec_name,
                relint,
                agent_type="fast-track",
                run_id=getattr(result, "run_id", "") or "",
            )
            return

        # ── 诚实退出收敛：跳过 fast-track 硬校验，降级完整模式补独立验证（D2a）──
        # partial + 缺口全申报的结果文件**必然不含合法 verification 段**
        # （agent 明确申报「做不完」，不可能同时产出完整验证裁决）→ 下方
        # _hard_check_fast_track 的 parse_fast_track_verification fail-closed
        # 会把收敛打回重派，fast-track 车道诚实退出收敛实质是死路（2026-09-17
        # 调研实证，design D2a）。诚实退出意味着「实现做完了、部分任务没做」，
        # 其验证本就该走完整模式的三阶段独立验证（而非 fast-track 单 run 自证）。
        # 复用既有 _handle_fast_track_missing_result_merge 的「merge + mode 改写
        # + enqueue verifier」语义（design D2a 方案 (a)；裁决理由见 design.md）。
        if honest_exit_gap:
            merged = self._reconcile_and_merge(spec_name, result)
            if not merged:
                return  # merge 失败内部已处置（保留 worktree + 重派/熔断）
            self._rewrite_fast_track_to_full(spec_name)
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": "诚实退出收敛（fast-track）：缺口全部 ⊆ unattainable，"
                    "降级完整模式补独立验证",
                },
            )
            # impl-result per-spec 快照 + 共享结果文件清理（与其余成功收口同语义）
            try:
                self._pm._write_impl_result_snapshot(spec_name, ft_result)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"fast-track 诚实退出收敛 impl-result 快照写入失败 "
                    f"'{spec_name}'（非阻塞）: {e}",
                )
            self._pm._cleanup_shared_result_file(spec_name)
            self._enqueue(spec_name, "verifier")
            self._pm.logger.warning(
                "pm_engine",
                f"诚实退出收敛（fast-track）'{spec_name}'：缺口全部 ⊆ unattainable "
                f"申报 {honest_exit_gap} —— 降级完整模式，入队 verifier 补独立验证",
            )
            return

        # ── 硬校验（merge 前执行，失败则不合并、按失败重派） ──
        verification = self._hard_check_fast_track(spec_name, ft_result)
        if verification is None:
            # worktree-reuse：打回保留 worktree，重派在同一目录继承上一轮成果
            self._keep_fast_track_worktree(spec_name, result)
            return  # _hard_check 已设 error + enqueue

        # ── 校验全通过：merge → 状态推进 ──
        # merge 失败时 _reconcile_and_merge 内部已处置（保留 worktree + 重派/熔断），
        # 必须早退——否则会继续走 advance_to_verified 把 error 踩成 None（伪 verified）。
        merged = self._reconcile_and_merge(spec_name, result)
        if not merged:
            return

        # ── impl-result per-spec 快照（fast-track 车道与 full 车道同语义）──
        # merge 成功即快照，供 verified→done 门禁 _task_completion_blocker 读取。
        # fast-track 的 verified→done 虽与本收口同周期同步执行，但 spec 可因门禁
        # 拦截（未勾任务）滞留 verified 跨周期——此窗口内共享文件
        # .fenix/.fenix-run-result.json 会被其它 spec 成功覆盖，无快照则门禁
        # fail-closed 误报「run 证据缺失」（2026-09-10 add-planready-artifact-gate
        # 实证）。快照写失败仅 WARNING 不阻塞（fail-open，门禁 fail-closed 兜底）；
        # 重派后新成功原子覆盖旧快照（幂等）。
        try:
            self._pm._write_impl_result_snapshot(spec_name, ft_result)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track impl-result 快照写入失败 '{spec_name}'（非阻塞）: {e}",
            )
        # ── 消费后清理共享结果文件（fix-fasttrack-resultfile-missing-redispatch D4）──
        # 本次采信消费 + 快照落盘之后删除主树共享 .fenix/.fenix-run-result.json
        # （仅当 stamp 严格匹配本 spec 即正是本文件被消费时删除），避免已消费
        # 残留跨 spec 存留对后续死亡判定/读侧的误拦与噪声。删除失败仅 WARNING
        # 不阻塞（fail-open，残留由 stamp 严格校验兜底拒绝）。
        self._pm._cleanup_shared_result_file(spec_name)

        if verification.get("verdict") == "bug-found":
            self._escalate_to_full_mode(spec_name, result, verification)
            return

        # ── verified → implemented → testing → verified → _on_spec_verified ──
        self._fast_track_advance_to_verified(spec_name, result)

    def _harvest_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 异常兜底（verify-process-lifecycle D3）：回收 dev-server。

        runner 的终态收割因 fast-track 属 handed_off（有意交接 dispatch 层）
        而跳过；本方法在 hand-off 边界内抛异常时兜底：停止
        result.worktree_path 的 dev-server 注册条目并扫杀游离进程。
        幂等：条目已不存在/进程已死时安全空转。
        """
        wt = getattr(result, "worktree_path", None)
        if not wt:
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(Path(wt))
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"fast-track 兜底收割 V2 stop 失败 '{spec_name}': {e}"
            )
        try:
            self._pm.agent_runner.worktree_manager._kill_worktree_strays(Path(wt).name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine", f"fast-track 兜底收割 strays 失败 '{spec_name}': {e}"
            )

    def _keep_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 打回/失败：保留 worktree 供重派继承（worktree-reuse）。

        runner 对 fast-track 成功路径延迟清理（worktree_kept=False 时由本层处置）；
        终态失败路径 runner 已保留（worktree_kept=True，此处幂等跳过）。
        """
        wt = getattr(result, "worktree_path", None)
        if wt is None or getattr(result, "worktree_kept", False):
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(wt)
            # agent_type 传参（code-review item 1c6d47a74461）：供 keep_for_reuse
            # 摘锁时按家族限定（fast-track 属非 verifier 家族，不误摘 :verifier）
            self._pm.agent_runner.worktree_manager.keep_for_reuse(
                spec_name, wt, agent_type="fast-track")
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track worktree 保留失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _release_fast_track_worktree(self, spec_name: str, result) -> None:
        """fast-track 校验通过且 merge 完成：回收 runner 延迟保留的 worktree。"""
        wt = getattr(result, "worktree_path", None)
        if wt is None:
            return
        try:
            self._pm.agent_runner._v2_stop_for_worktree(wt)
            self._pm.agent_runner.worktree_manager.cleanup(wt, success=True)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track worktree 延迟清理失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _reconcile_and_merge(self, spec_name: str, result) -> bool:
        """预算对账 + merge（fast-track 与 implementer 成功路径同语义）。

        Returns: merge 是否成功（失败时调用方必须早退，不得继续状态推进）。"""
        self._pm._reconcile_impl_budget(spec_name)
        wm = self._pm.agent_runner.worktree_manager
        branch = result.branch
        if branch:
            # add-impl-ocr-parallel-lane（任务 4.1）：ocr join 指纹 base 分量
            # MUST 在 merge 前捕获（merge 后 merge-base(main, branch) 恒为
            # branch head），随锚点同批持久化——与 queue 主路径同语义。
            _ocr_base = None
            if self._impl_ocr_enabled():
                _ocr_base = self._git_merge_base_main(branch)
                try:
                    self._pm.state_machine.update_spec(
                        spec_name, {"_ocr_base_commit": _ocr_base}
                    )
                except Exception as e:  # noqa: BLE001 — 非阻塞（缺失以 head 兜底）
                    self._pm.logger.warning(
                        "pm_engine",
                        f"ocr base 捕获落盘失败 '{spec_name}'（非阻塞）: {e}",
                    )
            merge_info = wm.merge_back_from_branch(branch)
            merge_ok, merge_error = merge_info
            if not merge_ok:
                # （fix-fasttrack-recovery-resume 4.1 出口矩阵：merge-back 失败
                # 分支出口——blocked 熔断 / repair 通道 / ready+重派三岔，见下）
                # 三岔对 branch/implementer_run/_recovery_resume 均**不触碰**：
                # - blocked/repair/retry 保留 spec in-flight 或在 ready 降级时经
                #   dispatch 入口重新消费标记与锚点（若有）；
                # - MUST NOT 在此新增清锚点（merge 失败不代表 stale 锚点）、
                #   也 MUST NOT 消费 _recovery_resume（标记在入口一次性消费）。
                # worktree-reuse：merge 失败同样保留 worktree，重派继承后重试 merge
                self._keep_fast_track_worktree(spec_name, result)
                # ── 预演语义冲突直通 repair（add-merge-tree-rehearsal D2）──
                # 与 implementer 路径同语义：主树零污染检出语义冲突 → 不经 fp
                # 记账与 ready 降级，spec 保持 in-flight 直通 repair（轮次兜底在
                # _direct_rehearsed_to_repair 内）。
                if getattr(merge_info, "rehearsed", False):
                    self._direct_rehearsed_to_repair(spec_name, merge_info, branch, merge_error)
                    return False
                # ── WIP 重叠闸门阻塞旁路（evo-merge-back-wip-overlap-gate D3）──
                # 与 implementer 路径同语义：阻塞是前置拦截而非 merge 失败，主树
                # 未被 stash/merge/pop 触碰——不经 _merge_fp/_merge_streak 记账、
                # 不做 ready 降级、不进 repair 通道，spec 保持 in-flight，仅直发
                # 告警等待人工处置主树 WIP（提交或 stash 重叠改动后重新放行）。
                if getattr(merge_info, "wip_gate_blocked", False):
                    self._report_mergeback_wip_overlap(spec_name, merge_info, branch, merge_error)
                    return False
                # ── spec 目录在飞编辑顺延（evo-merge-back-spec-dir-inflight-guard
                # D1/D1a；code-review item a84787292647，fast-track 对齐 full 车道
                # _defer_merge_back）── 与 full 车道同语义：写 _merge_retry_pending
                # 记账 + 排程 merge-only 重试（_retry_merge_back_only 按 branch
                # 锚点通用实现，天然覆盖 fast-track 车道），有界顺延自动重试合并；
                # 窗口/轮数超限由 _defer_merge_back 内部回落「告警 + 人工处置」
                # 通道（_report_mergeback_spec_dir_inflight_stuck）。MUST NOT
                # 在飞顺延零重试——原行为 spec 悬置 implementing 且无活跃 run，
                # 只能等 admin_monitor stuck 阈值唤起人工，两侧有界性不对称。
                # spec 保持 in-flight（implementing），保留 worktree/锚点。
                if getattr(merge_info, "spec_dir_inflight", False):
                    self._pm.logger.warning(
                        "pm_engine",
                        f"fast-track merge-back 顺延 '{spec_name}'（branch '{branch}'）: "
                        f"{merge_error} — spec 目录在飞编辑，不推进状态，保留 "
                        f"worktree/锚点，写顺延记账并排程 merge-only 重试",
                    )
                    self._defer_merge_back(spec_name, merge_info, branch, merge_error)
                    return False
                spec_entry = self._pm.state_machine.read_one(spec_name) or {}
                # （code-review item 9f857a108821）此处旧有 `max_r = ...
                # agents.max_retries` 赋值从未被本方法读取（下方 merge 失败分岔只用
                # breaker_threshold；max_r 仅在 _handle_fast_track_failure 使用），
                # 属死赋值，会误导读者以为 merge 重试受 max_retries 封顶，已删除。
                fp = self._pm._merge_fingerprint(merge_error)
                prev_fp = spec_entry.get("_merge_fp")
                # _merge_streak 走锁内原子递增（bump_counters 返回写后值参与
                # 阈值判定，对齐 queue.py _handle_merge_back_real_failure 同型
                # 收口，code-review item 893c06695fab）：原先「read_one 读 →
                # 算 +1 → 并进 update_spec 写回」读与写分处两次 STATE 锁临界
                # 区，merge-only 重试定时器、WIP 周期消费者与 worker 失败链
                # 并发进入同一 spec 时各持相同旧值写回、丢一次递增，同指纹
                # 熔断晚一轮触发、多烧一轮 fast-track run。指纹切换属重置
                # 语义（绝对写 1，无丢增量面），不 bump、随后续 update_spec
                # 落盘（streak_bumped=True 时各分支不再并写该字段）。
                if prev_fp == fp:
                    streak = self._pm.state_machine.bump_counters(
                        spec_name, {"_merge_streak": 1}
                    ).get("_merge_streak", 0)
                    streak_bumped = True
                else:
                    streak = 1
                    streak_bumped = False
                # 配置侧 int() 归一（code-review item 74317ab4a77a，与 budget.py
                # _budget_exempt_alert_threshold 同款）：字符串配置裸用于比较抛
                # TypeError 中断 merge 失败处置，非法值回退缺省；None 判空而非
                # or 兜底（code-review item c54ffbef69c5）：合法配置 0（每次
                # merge 失败立即熔断）不被 or 吞成缺省 2。归一化单点工具
                # （code-review item c832188fbbac）。
                breaker_threshold = _normalize_int_config(
                    self._pm._get_config("agents.merge_breaker_threshold", 2), 2
                )
                final_error = f"Merge-back failed (fp={fp}): {merge_error}"
                if streak >= breaker_threshold:
                    # fix-observability-gaps 2.2：repair/fast-track merge 熔断 blocked
                    # （code-review item 9e02c14cb283）本车道 blocked 归因
                    # agent_type="fast-track"（与下方成功转移一致），避免审计/
                    # 告警误归 implementer 车道；agent_type 为自由字符串无枚举约束。
                    self._pm.state_machine.transition(
                        spec_name, "blocked",
                        trigger_run_id=None, agent_type="fast-track", channel="auto",
                    )
                    # _retry_count: 0 是重置语义（绝对写，无丢增量面）；streak
                    # 已由 bump_counters 原子递增落盘时不再并写（同上，防并发
                    # 写回互相覆盖丢增量）。
                    breaker_updates: dict = {
                        "error": final_error,
                        "_merge_fp": fp,
                        "_retry_count": 0,
                    }
                    if not streak_bumped:
                        breaker_updates["_merge_streak"] = streak
                    self._pm.state_machine.update_spec(spec_name, breaker_updates)
                elif self._pm._should_enter_repair(
                    spec_name, merge_info, streak, breaker_threshold
                ):
                    # ── repair 通道（add-merge-back-repair-lane；fast-track 接入）──
                    # 语义冲突失败且熔断未触发：派 repair agent 在实现分支上把
                    # main 合入原地修复，而非 ready+重派废弃整轮成果
                    # （2026-09-04 task-track 事故：112 turns 因混合冲突整单废弃）。
                    # 与 implementer 路径同序：熔断优先，repair 次之，普通重试兜底。
                    self._pm._dispatch_repair_lane(
                        spec_name,
                        merge_info,
                        branch,
                        fp=fp,
                        streak=streak,
                    )
                else:
                    # _retry_count 同型收口：锁内原子递增，不再并入 update_spec
                    # （对齐 queue.py 先例，防并发写回互相覆盖丢增量；本分支
                    # 无 max_retries 判定，不需消费写后值）。
                    self._pm.state_machine.bump_counters(spec_name, {"_retry_count": 1})
                    ready_updates: dict = {
                        "status": "ready",
                        "error": final_error,
                        "_merge_fp": fp,
                    }
                    if not streak_bumped:
                        ready_updates["_merge_streak"] = streak
                    self._pm.state_machine.update_spec(spec_name, ready_updates)
                    self._enqueue_front(spec_name, "fast-track")
                self._pm.logger.error(
                    "pm_engine",
                    f"fast-track merge-back failed '{spec_name}': {final_error}",
                )
                return False
        else:
            # （code-review item 69fe26c88579）防御「success 蕴含 branch 非空」契约：
            # 本方法仅在三处 success 前置的调用点进入，branch 为空即契约被破坏
            # （runner 成功但 get_branch_name 未取到分支名，成功 run 的 branch
            # 可为 None）——绝不能静默落入下方成功分支（成果未经合并即被伪推进
            # implemented + branch=None + error=None，且现场被清理）。按既有
            # merge 失败路径处置：保留 worktree + 记 error + ready 重派；
            # 无真实 merge 失败可归因，不经 fingerprint/breaker/repair 记账。
            contract_err = (
                "fast-track merge skipped（success 但 branch 为空，违反"
                "「success 蕴含 branch 非空」契约）：实现成果未经合并，"
                "按 merge 失败重派"
            )
            self._keep_fast_track_worktree(spec_name, result)
            spec_entry = self._pm.state_machine.read_one(spec_name) or {}
            # _retry_count 同型收口（code-review item 0a1571596925）：锁内原子
            # 递增取写后值参与 max_retries 判定，随后 update_spec 不再并写该
            # 字段（对齐本方法 merge 失败 ready 分支与 backoff.py
            # _handle_dispatch_lock_conflict 先例，防并发写回互相覆盖丢增量）
            # ——原两段式「读 → 算 +1 → 绝对写回」读与写分处两次 STATE 锁临界
            # 区，并发交错丢一次递增，封顶晚一轮触发、多烧一轮 fast-track run。
            retries = self._pm.state_machine.bump_counters(
                spec_name, {"_retry_count": 1}
            ).get("_retry_count", 0)
            # （code-review item a7395837fcbb）本出口重派同样受 agents.max_retries
            # 封顶：派发入口不读 _retry_count 设闸，持续性「success 但 branch 为空」
            # 若只递增重派会无限烧 fast-track run 预算——封顶判据与
            # _handle_fast_track_failure 同源，达阈冻结转人工、不再自动重派。
            max_r = _normalize_int_config(self._pm._get_config("agents.max_retries", 3), 3)
            if retries >= max_r:
                fp = self._pm._redispatch_cause_fingerprint(contract_err)
                orig_status = spec_entry.get("status") or "implementing"
                self._pm.state_machine.freeze_for_human(
                    spec_name,
                    error=(
                        f"原状态 {orig_status} · fast-track 重试耗尽"
                        f"（{max_r}/{max_r} 轮，指纹 {fp}）：{contract_err}"
                    ),
                    signal_type="redispatch_loop_detected",
                    severity="major",
                    description=(
                        f"'{spec_name}' fast-track 契约违反（success 但 branch 为空）"
                        f"连续重试 {max_r} 轮已达上限（max_retries），自动重试终止"
                        f"——已冻结转人工处置"
                    ),
                    evidence=(
                        f"spec={spec_name}; retries={retries}; max_retries={max_r}; "
                        f"fp={fp}; final_error={contract_err}"
                    ),
                    recommended_action=(
                        "检查 runner 成功但分支名缺失的根因；处置后解冻"
                        "（unfreeze_spec 自动清零计数）可重新获得自动修复机会"
                    ),
                    alert_callback=self._pm._send_human_escalation_alert,
                )
                self._pm.logger.error(
                    "pm_engine",
                    f"fast-track all retries exhausted '{spec_name}' — 冻结转人工，"
                    f"不再重派（{retries}/{max_r}，fp={fp}）",
                )
                return False
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "ready",
                    "error": contract_err,
                    # _retry_count 已由上方 bump_counters 原子递增落盘，此处
                    # 不再并写（防并发写回互相覆盖丢增量）
                },
            )
            self._enqueue_front(spec_name, "fast-track")
            self._pm.logger.error(
                "pm_engine",
                f"fast-track merge-back failed '{spec_name}': {contract_err}",
            )
            return False
        # merge 成功：回收 runner 延迟保留的 fast-track worktree（worktree-reuse）
        self._release_fast_track_worktree(spec_name, result)
        # fix-observability-gaps 2.2：fast-track merge 成功 → implemented
        # 合并收尾 ready 态兜底（evo-spec-concurrency-flight-guard D3）：
        # status=ready（评审收尾竞态回退残留）时先补记 ready→implementing，
        # 再推进 implemented（消除 ready→implemented 非法转移 ERROR）。
        self._pm._merge_ready_fallback(
            spec_name, result.run_id, "fast-track", result.branch
        )
        # transition 返回值校验（code-review item 40292d21fd97，对齐 spec_review
        # 同仓 TOCTOU 处置）：上方读态/fallback 与 implemented 转移之间存在窗口，
        # 并发写者可能已把 spec 推进/冻结（非法转移返回 False）。失败时保留计数
        # 与 error 原样、不继续清字段——否则清零与清 error 照常落盘、后续转移
        # 同样失败，spec 停在并发方写入的状态但错误现场已被抹掉。返回值不因
        # 转移失败翻转（本方法既有契约，见
        # test_fast_track_verify_branch_no_fallback），后续 verified 推进由
        # 状态机拒绝自然拦截，错误现场留给收口重试/审计。
        if not self._pm.state_machine.transition(
            spec_name, "implemented",
            trigger_run_id=result.run_id, agent_type="fast-track", channel="auto",
        ):
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track merge 成功但 transition 到 implemented 失败，"
                f"保留计数与 error 待收口重试/审计: {spec_name}",
            )
            return True
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "implementer_run": result.run_id,
                "branch": result.branch,
                "error": None,
                "_retry_count": 0,
                "_merge_fp": None,
                "_merge_streak": 0,
                # 与 full 车道零变更成功收口同款清零（queue.py 确认型 no-op
                # 分支）：非连续的零变更不应累计进「连续 3 次」哨。
                "_zero_change_attempts": 0,
                **self._pm._clear_dispatch_conflict(spec_name),
            },
        )
        # 任务进度回写（与 implementer 成功路径一致，非阻塞）
        try:
            self._pm._sync_task_progress(spec_name)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 任务进度回写失败 '{spec_name}'（非阻塞）: {e}",
            )
        try:
            wm.consume_legacy(spec_name)
        except Exception as e:
            # 失败不再静默吞掉（code-review item 2aef9b8f5cd0）：与
            # queue.py 的等价调用同款非阻塞 WARNING，使持续的 legacy 清理失败
            # 在本车道可观测（fail-open 但可见）。
            self._pm.logger.warning(
                "pm_engine",
                f"consume_legacy 清理失败 '{spec_name}'（非阻塞）: "
                f"{type(e).__name__}: {e}",
            )
        # add-impl-ocr-parallel-lane（任务 4.1）：fast-track merge-back 成功时点
        # 同点启动 ocr 车道（与 implementer 主路径 merge 成功启动点同语义）；
        # join 于 _fast_track_advance_to_verified 的 testing 出口。异常不阻塞
        # merge 收尾（join 门禁幂等补启兜底）。
        try:
            fp = self._ocr_current_fingerprint(spec_name)
            if fp is not None:
                self._start_impl_ocr_lane(spec_name, fp)
        except Exception as e:  # noqa: BLE001
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track ocr 车道启动失败 '{spec_name}'（非阻塞）: "
                f"{type(e).__name__}: {e}",
            )
        return True

    # ── repair 通道（add-merge-back-repair-lane D1/D2/D4/D5/D6）──────────────
    # merge-back 语义冲突失败后的原地修复通道。分层边界（design D1）：git 层
    # （worktree_manager）只做冲突分类与载体解析，**是否进入 repair、派发与轮次
    # 计数**在本层决策。修复方向反转（D2）：repair agent 在实现分支一侧把 main
    # 合入分支并解决冲突，主树在派发前已 abort 保持干净。

    def _hard_check_fast_track(self, spec_name: str, ft_result: dict):
        """对 fast-track 结果做框架侧硬校验；失败记原因并按失败重派。

        fix-impl-tasks-completion-gate D9/5.1：在既有校验（verification 段结构 +
        场景 ID 覆盖 + verdict 证据）之上叠加与 implementer **同源**的完成度判据
        ——复用 runner 产物硬门的同一实现点（`_check_impl_result_artifact`，同一
        解析函数与同一归因构造），不另起一套判定。fast-track 结果文件顶层 status
        契约本就是 "success"（verdict 承载在 verification 段），与硬门白名单
        {"success","error","partial"} 兼容（5.2）；status != success 的形态已在
        同文件 ``_run_fast_track_flow`` 的 status 非法拦截分支（run 成功但
        status 非 success 且无诚实退出缺口时写明非法值并转失败重派）拦截，
        到本方法时必为 success。

        叠加判据以 worktree 内 tasks.md 为对象（runner 硬门同款）。worktree 不可得
        或结果文件已随收口清理 → fail-open（记录 debug 日志不误拦——runner 产物硬门
        已在本轮 run 结束时于源头校验过同一判据，此处是 merge 前双保险兜底）。

        Returns:
            规整后的验证段 dict（含 verdict/bugs/scenarios），校验失败返回 None。
        """
        from core.fast_track_result import parse_fast_track_verification
        from core.verdict_check import validate_fast_track_result

        # ── 完成度叠加判据（fix-impl-tasks-completion-gate 5.1）──
        # （fix-fasttrack-recovery-resume 4.1 出口矩阵：完成度判据拦截分支）
        # 本出口仅写 error + _enqueue_front 重派，对 branch/implementer_run/
        # _recovery_resume 均**不触碰**——重派走 dispatch 入口，由其按续做
        # 标记决定是否清锚点；不新增清锚点、不消费恢复标记。
        try:
            wt_path = self._pm._find_implementer_worktree(spec_name)
            if wt_path is not None and (wt_path / ".fenix-run-result.json").exists():
                gate_err = self._pm.agent_runner._check_impl_result_artifact(
                    spec_name, None, wt_path
                )
                # 仅返回字符串归因才是判据失败（兼容单测 mock 环境：MagicMock
                # 非 None 非 str，按通过处理——产品环境恒返回 str|None）。
                if isinstance(gate_err, str):
                    err = f"fast-track 完成度判据未通过：{gate_err}"
                    self._pm.state_machine.update_spec(spec_name, {"error": err})
                    self._enqueue_front(spec_name, "fast-track")
                    self._pm.logger.error(
                        "pm_engine",
                        f"fast-track 完成度判据拦截 '{spec_name}': {err}",
                    )
                    return None
            elif wt_path is None:
                self._pm.logger.debug(
                    "pm_engine",
                    f"fast-track 完成度判据跳过（worktree 不可得，runner 硬门已"
                    f"源头校验）'{spec_name}'",
                )
            else:
                # wt_path 在但结果文件已随收口清理：同为 fail-open 降级，降级
                # MUST 留痕（code-review item 13e3cefdcfc8）——与上方 worktree
                # 不可得分支同款 debug 级，双保险兜底被跳过时有迹可查。
                self._pm.logger.debug(
                    "pm_engine",
                    f"fast-track 完成度判据跳过（结果文件已随收口清理，"
                    f"runner 硬门已源头校验）'{spec_name}'",
                )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 完成度判据执行异常（fail-open 防误拦）'{spec_name}': {e}",
            )

        verification = parse_fast_track_verification(ft_result or {})
        # （fix-fasttrack-recovery-resume 4.1 出口矩阵：verification 解析失败
        # 拦截分支）本出口与下方校验失败分支同——仅写 error + _enqueue_front
        # 重派，对 branch/implementer_run/_recovery_resume 均**不触碰**，不新增
        # 清锚点、不消费恢复标记。
        if verification is None:
            err = "fast-track 结果文件非法（verification 段缺失或结构不完整）"
            self._pm.state_machine.update_spec(spec_name, {"error": err})
            self._enqueue_front(spec_name, "fast-track")
            self._pm.logger.error(
                "pm_engine",
                f"fast-track 硬校验失败 '{spec_name}': {err}",
            )
            return None

        # 加载设计场景 ID（Phase 2 写入的 test_scenarios.json）
        scenarios_path = (
            self._pm.project_root / ".fenix" / "verify-progress" / spec_name / "test_scenarios.json"
        )
        designed_ids: list = []
        if scenarios_path.exists():
            degrade_reason = ""
            try:
                sc_data = json.loads(scenarios_path.read_text(encoding="utf-8"))
                if isinstance(sc_data, list):
                    designed_ids = [
                        s.get("id") for s in sc_data if isinstance(s, dict) and s.get("id")
                    ]
                    if not designed_ids:
                        degrade_reason = f"数组内 {len(sc_data)} 条条目均无可取 id"
                else:
                    # 写侧（planner-plan/fast-track 车道按注入 schema）仅产出
                    # 顶层数组形态，dict 包裹等漂移形态不做隐式解包，拒绝采信。
                    degrade_reason = f"顶层载荷为 {type(sc_data).__name__} 非数组"
            except (OSError, json.JSONDecodeError) as e:
                # 覆盖门降级 MUST 留痕（code-review item 75770d2d2cc6）：静默
                # 吞掉会使 designed_ids 保持空 → validate 按 None 跳过全量执行
                # 比对，fail-closed 硬校验无声退化为仅结构校验。
                self._pm.logger.warning(
                    "pm_engine",
                    f"fast-track 读取 test_scenarios.json 失败 '{spec_name}'"
                    f"（按无设计集降级，仅做结构与证据校验）: {type(e).__name__}: {e}",
                )
            if degrade_reason:
                # 覆盖门降级 MUST 留痕（code-review item 58efa16245ef，同上方
                # 75770d2d2cc6 口径）：合法 JSON 但解析不出设计集（顶层非数组/
                # 条目均无可取 id）同样使 designed_ids 保持空 → validate 按
                # None 跳过全量执行比对，静默遗漏场景会逃过拦截。
                self._pm.logger.warning(
                    "pm_engine",
                    f"fast-track 读取 test_scenarios.json 失败 '{spec_name}'"
                    f"（按无设计集降级，仅做结构与证据校验）: {degrade_reason}",
                )

        check = validate_fast_track_result(ft_result, designed_ids or None)
        # （fix-fasttrack-recovery-resume 4.1 出口矩阵：硬校验失败重派分支）
        # 本出口仅写 error + _enqueue_front 重派（validate 不通过 / bug-found
        # 升级完整模式由更下的 _escalate_to_full_mode 处理），对
        # branch/implementer_run/_recovery_resume 均**不触碰**，不新增清锚点、
        # 不消费恢复标记。
        if not check["ok"]:
            violations_str = "；".join(check["violations"])
            err = f"fast-track 硬校验失败（fail-closed）：{violations_str}"
            self._pm.state_machine.update_spec(spec_name, {"error": err})
            self._enqueue_front(spec_name, "fast-track")
            self._pm.logger.error(
                "pm_engine",
                f"fast-track 硬校验不通过 '{spec_name}': {violations_str}",
            )
            return None

        return verification

    def _fast_track_advance_to_verified(self, spec_name: str, result) -> None:
        """fast-track 硬校验通过 + verdict=verified：implemented → testing → verified。"""
        # verified 洗白门禁（help-center 0/15 verified 事故防线）已下沉到
        # _fast_track_finalize_after_testing 开头（code-review item
        # 35dfeabfd01d）：重启恢复重入路径（_resume_fast_track_after_restart）
        # 不经本方法直连收尾段，门禁只挂在本方法 transition testing 之前时
        # 该路径绕过门禁——下沉到两路径共用的收尾段入口使门禁位点唯一。
        # fix-observability-gaps 2.2：fast-track 自动连跳（同一 run 触发两次转换）
        self._pm.state_machine.transition(
            spec_name, "testing",
            trigger_run_id=getattr(result, "run_id", None) or None,
            agent_type="fast-track", channel="auto",
        )
        # add-impl-ocr-parallel-lane（任务 4.1/4.2）：fast-track 出口 join 门禁
        # ——插在 testing 转移之后、verified 之前：defer 时 spec 停留 testing
        # （车道完成回调经 _resume_verified_after_ocr 重入本方法，同状态转移
        # 幂等保证安全）；reject 时打回已在门禁内完成。
        # fix-fasttrack-implemented-deadstate 1.1：testing 之后段抽取为
        # _fast_track_finalize_after_testing，与重启恢复重入路径共用。
        self._fast_track_finalize_after_testing(spec_name, result)

    def _fast_track_finalize_after_testing(self, spec_name: str, result) -> None:
        """testing 出口收尾段：洗白门禁 → join 门禁 → verified 转移 →
        清零点 update → ``_on_spec_verified``（fix-fasttrack-implemented-deadstate
        1.1）。

        自 ``_fast_track_advance_to_verified`` 抽取的私有方法，正常收尾流与
        重启恢复重入（``_resume_fast_track_after_restart``）两处复用——
        **禁止**复制粘贴状态推进序列（清零点字段集漂移即事故）。defer 时
        spec 停留 testing（车道完成回调既有唤醒路径接手）；reject 已在
        门禁内完成。
        """
        # verified 洗白门禁（help-center 0/15 verified 事故防线）：fast-track
        # 结果文件 0 通过或 env 失败不得放行，升级 admin 处置（升级在门禁内
        # 完成，返回 False 直接终止推进）。原挂 _fast_track_advance_to_verified
        # 的 transition testing 之前；下沉到本收尾段入口（code-review item
        # 35dfeabfd01d）——重启恢复重入不经 advance 方法直连本段，门禁挂原
        # 位点时该路径绕过防线。两条路径共用唯一位点；门禁通过时纯读无副
        # 作用，defer 后回调重入时幂等重跑（与既有 join 门禁同性质）。
        if not self._pm._env_whitewash_gate(spec_name):
            return
        ocr_decision = self._ocr_join_gate(spec_name, "fast-track")
        if ocr_decision != "pass":
            return
        self._pm.state_machine.transition(
            spec_name, "verified",
            trigger_run_id=getattr(result, "run_id", None) or None,
            agent_type="fast-track", channel="auto",
        )
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "tester_run": result.run_id,
                "error": None,
                "_inconclusive_attempts": 0,
                # add-verify-parallel-backoff / design D2：fast-track verified 是
                # 既有清零点，降档并行度同轮复位（与 _inconclusive_attempts 同生命周期）。
                "_verify_parallel_override": None,
                "_verify_fail_rounds": 0,
                # fix-daemon-lifecycle-races D3：验证自然通过清零点（fast-track 同语义）。
                "_verify_redo_count": 0,
                # add-blocked-reverify-lane D3：env 阻塞轮次清零点（fast-track verified
                # 属「验证通过」唯一自动清零点语义，与全模式 verified 落定同款）。
                ENV_BLOCK_ROUNDS_FIELD: 0,
            },
        )
        self._pm.logger.info(
            "pm_engine",
            f"fast-track verified: '{spec_name}' → 推进 verified",
        )
        self._pm._on_spec_verified(spec_name)

    def _resume_fast_track_after_restart(self, spec_name: str, already_testing: bool = False) -> None:
        """重启恢复重入：implemented 死态 → testing → 收尾段（Cap 1 / D2）。

        fast-track spec 卡 ``implemented`` 死态（daemon 重启恢复形态：重启把
        testing 回滚 implemented、event-bus 每 30 分钟重发 spec_implemented 被
        engine 既有短路吞掉）时的收尾重入入口，由 engine
        ``_on_spec_implemented`` 恢复三条件全成立时调用：

        - transition ``implemented → testing``（channel=auto，
          trigger_run_id=implementer_run）；
        - 随后复用 ``_fast_track_finalize_after_testing`` 收尾段（洗白门禁 →
          join 门禁 → verified → 清零点 → ``_on_spec_verified``）；defer 时车道完成回调
          ``_on_impl_ocr_lane_finished`` 既有唤醒路径接手（回调前置
          status==testing，重入后恰好满足，闭环）。

        ``already_testing=True``（code-review item 3766612aca27 搁浅态）：spec
        已在 ``testing``（首次收尾段在 testing 转移之后抛异常搁浅，VALID_TRANSITIONS
        不允许 testing→implemented 回滚重走），跳过转移、仅重跑收尾段——engine
        侧恢复判据①的 testing 形态据此重入。

        **不读** fast-track 共享结果文件（早已在首次收尾时消费清理）：验证
        结论以 per-spec impl-result 快照（merge 成功时点已落盘）+ tasks 勾选
        为准（verified→done 门禁 ``_task_completion_blocker`` 读快照）。
        """
        entry = self._pm.state_machine.read_one(spec_name) or {}
        implementer_run = entry.get("implementer_run") or None
        if not already_testing:
            self._pm.state_machine.transition(
                spec_name, "testing",
                trigger_run_id=implementer_run,
                agent_type="fast-track", channel="auto",
            )
        from types import SimpleNamespace

        self._fast_track_finalize_after_testing(
            spec_name, SimpleNamespace(run_id=implementer_run)
        )

    def _rewrite_fast_track_to_full(self, spec_name: str) -> None:
        """把 .spec.yaml 的 mode 从 fast-track 改写为 full（升级路径复用）。

        供 ``_escalate_to_full_mode``（verdict=bug-found 升级）与
        ``_handle_fast_track_missing_result_merge``（结果文件缺失、分支已提交
        升级补验证）共用。写失败仅记 WARNING（非阻塞，mode 未改写时由 verifier
        车道语义处置）。
        """
        import yaml as _yaml

        # 1. .spec.yaml 写 mode: full
        yaml_path = self._pm.project_root / "spec" / "changes" / spec_name / ".spec.yaml"
        try:
            if yaml_path.is_file():
                data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("mode") == "fast-track":
                    data["mode"] = "full"
                    # mkstemp 唯一临时文件 + fsync + os.replace 原子写（复用仓库
                    # 统一助手 scenario_gate.atomic_write_text，code-review item
                    # efb92f4ba1d7）：原固定名 ``.spec.yaml.tmp`` + 裸 write_text
                    # 两个漂移点——① 无 flush+fsync，掉电/内核崩溃时 replace 后
                    # 内容可能在文件系统层未持久；② 固定临时名在并发改写同一
                    # .spec.yaml 时互踩同一 tmp，后写者可能把截断/混合内容
                    # replace 成正式文件。唯一临时名保证 rename 前目标不变、
                    # rename 后内容完整（函数内 import 同 serving.py 先例，避开
                    # verification 包门面的重依赖导入链）。
                    from core.pm_engine.verification.scenario_gate import (
                        atomic_write_text,
                    )

                    atomic_write_text(
                        yaml_path,
                        _yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
                    )
                    self._pm.logger.info(
                        "pm_engine",
                        f"fast-track 升级: .spec.yaml mode → full " f"for '{spec_name}'",
                    )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 升级 .spec.yaml 失败（非阻塞） '{spec_name}': {e}",
            )

    def _escalate_to_full_mode(
        self,
        spec_name: str,
        result,
        verification: dict,
    ) -> None:
        """fast-track verdict=bug-found 时升级为完整模式（add-fast-track-mode D5）。

        - mode 改写为 full（同步 .spec.yaml）
        - spec 保持 implemented，派发完整模式 verifier 流水线
        - 升级原因写入 spec entry error 字段
        - 保留已有实现成果，不丢回 ready 重跑 implementer

        （fix-fasttrack-recovery-resume 4.1 出口矩阵：bug-found 升级完整模式
        分支）本出口仅改写 mode + enqueue verifier，对 branch/implementer_run/
        _recovery_resume 均**不触碰**——实现成果保留、不新增清锚点、不消费
        恢复标记（spec 已 implemented，恢复链不再针对本分支续做）。
        """
        # 1. .spec.yaml 写 mode: full
        self._rewrite_fast_track_to_full(spec_name)
        # 2. 记录升级原因
        bugs_summary = (
            "; ".join(
                # 防 TypeError（code-review item 58abca526f2e）：bugs 条目是半受信
                # agent 输出，上游 parse 只校验 bugs 是 list，不保证 description
                # 是 str（{"description": null} 形态 None[:80] 抛 TypeError）。
                # 调用点在 merge 成功推进 implemented 之后，异常沿 flow→worker
                # 外层 except 转 _rollback_failed_dispatch，会把正常 bug-found
                # 升级误成对已合并 spec 的回滚重派。
                str(b.get("description") or "")[:80]
                for b in (verification.get("bugs") or [])
                if isinstance(b, dict)
            )
            or "fast-track 判定 bug-found"
        )
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "error": f"fast-track 升级完整模式：{bugs_summary[:200]}",
            },
        )
        # 3. 派发完整模式 verifier 流水线
        self._enqueue(spec_name, "verifier")
        self._pm.logger.warning(
            "pm_engine",
            f"fast-track 升级完整模式 '{spec_name}'：verdict=bug-found，"
            f"实现保留，完整模式 verifier 流水线接管",
        )

    def _handle_fast_track_missing_result_merge(
        self,
        spec_name: str,
        result,
    ) -> None:
        """结果文件缺失但实现分支已有提交：merge + 升级完整模式补验证（D2）。

        触发因「结果文件缺失、分支已提交」而非 bug-found：不判 run 死亡——
        不回退预算、不 reset ready。merge 复用 ``_reconcile_and_merge``（失败时
        其内部已处置：保留 worktree + 重派/熔断，此处必须早退）；合并成功后改写
        .spec.yaml mode→full 并 enqueue 完整模式 verifier 补齐缺失的 verdict
        （复用 ``_escalate_to_full_mode`` 的 mode-改写 + enqueue 语义），后续走
        既有 verified→done 门。缺失的逐场景 fail-closed 校验整体移交完整模式
        verifier 的既有门（verify.yaml 契约 + verdict evidence），不损失校验强度。
        """
        # 预算对账 + merge（merge 失败内部已处置，必须早退）
        merged = self._reconcile_and_merge(spec_name, result)
        if not merged:
            return
        # 改写 mode=full + enqueue 完整模式 verifier（复用升级语义，触发因不同）
        self._rewrite_fast_track_to_full(spec_name)
        # 原因写入 spec entry（供人工审计：为何从 fast-track 转完整模式）
        self._pm.state_machine.update_spec(
            spec_name,
            {
                "error": "结果文件缺失，分支已提交，升级补验证",
            },
        )
        self._enqueue(spec_name, "verifier")
        self._pm.logger.warning(
            "pm_engine",
            f"fast-track 结果文件缺失、分支已提交 '{spec_name}'：merge 完成，"
            f"升级完整模式 verifier 补验证（不豁免预算、不 reset ready），"
            f"后续走既有 verified→done 门",
        )

    def _handle_fast_track_failure(
        self,
        spec_name: str,
        result,
        final_error: str,
        run_reason: str | None = None,
        ft_result: dict | None = None,
    ) -> None:
        """fast-track run 失败处理：与 implementer 同语义（重派/重试计数/blocked）。

        run_reason：预算豁免判据（run 真实终态归因，供 _is_exemptable_reason
        关键词检查）；None 时回退 final_error（既有行为）。展示文案与豁免
        判据分离（code-review item 2d2da33c5b15）。

        ft_result：调用方已解析的实现结果 dict（``_run_fast_track_flow`` 在
        读取结果文件后传入，code-review item 417ec4668570），豁免判定直接
        采信——消除「flow 判文件存在/缺失」与「本方法重读」之间的竞态分裂
        与重复 IO；缺省 None 时保留既有重读行为（兼容其它调用点）。
        """
        # 死亡 run 豁免（无收工结果 = run 异常死亡）
        impl_status = None
        try:
            if ft_result is None:
                ft_result = self._pm._read_implementer_result(spec_name)
            impl_status = ft_result.get("status") if ft_result else None
        except Exception as e:
            # 读失败不阻断失败处置，但 MUST 留痕（code-review item
            # b7bd800cd5a0）：静默吞掉会把瞬态 IO/parse 错误误成「无
            # run-result」→ 下方 _exempt_dead_run_budget 预算豁免无痕迹。
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track 读取 run-result 失败 '{spec_name}'"
                f"（按无结果处置，触发预算豁免）: {type(e).__name__}: {e}",
            )
        if impl_status is None:
            # 展示文案与豁免判据分离（code-review item 2d2da33c5b15）：调用方
            # 显式传 run_reason（真实终态归因）时按其判定豁免，缺省回退
            # final_error（既有行为）——固定人文案永不命中 _is_exemptable_reason
            # 的监督击杀关键词，会让监督击杀的 run 被误豁免（预算回退）。
            exempt_reason = run_reason if run_reason is not None else final_error
            # 隔离（code-review item efeb8db73d75，与 full 车道 queue.py 同站点
            # 同款）：豁免是**尽力而为的记账**（写状态文件，锁/IO 可能失败），若
            # 它自己抛异常，整个 failure handler 中断、异常沿 _run_fast_track_flow
            # → _run_fast_track_worker 外层 except 转 _rollback_failed_dispatch，
            # 下方 provider 熔断 / [provider-transient] / 模型链不可用 / 重试计数
            # 四段终态分类全部被跳过。故必须独立 try/except，豁免失败仅 WARNING、
            # 按未生效继续走失败分类链。
            try:
                self._pm._exempt_dead_run_budget(
                    spec_name,
                    f"fast-track no run-result (error={str(final_error)[:80]})",
                    # （code-review item 867125061b61）对齐 full 车道（queue.py 死亡
                    # run 豁免）：run_reason 传入豁免判据——监督超时/被判停滞而杀
                    # （extension budget exhausted / stagnant）不豁免（确实消耗了整份
                    # 预算）；缺此实参此类 run 被错误豁免（预算回退），同一次监督击杀
                    # 两条车道预算记账口径不一致，被击杀 run 可无限重派烧预算。
                    run_reason=str(exempt_reason) if exempt_reason else None,
                )
            except Exception as exempt_exc:  # noqa: BLE001 —— 记账失败不阻塞失败分类
                self._pm.logger.warning(
                    "pm_engine",
                    f"budget exempt failed for '{spec_name}'（按未豁免"
                    f"继续失败分类）: {type(exempt_exc).__name__}: "
                    f"{exempt_exc}",
                )
        # ── MUST 同步（code-review item 0caca76e37b1）──────────────────
        # 本方法以下四段「终态错误分类→处置动作」（provider 熔断
        # "provider circuit open" 保持原状 / [provider-transient] 延迟重派 /
        # MODEL_CHAIN_UNAVAILABLE_MARKER 保持原状 / _retry_count 递增与
        # max_r 封顶冻结转人工）与 queue.py `_run_agent_worker` 内
        # agent_type == "implementer" 的失败处置链（死亡 run 豁免之后的
        # provider 熔断 → [provider-transient] → 模型链不可用 → else 重试/
        # 冻结段）逐段同构、手工双维护。fast-track 侧历史上曾多次缺失、
        # 事后补齐对齐（code-review item 498a7c7432f1、867125061b61、
        # 6e6259821f64）。任一车道新增/修改终态失败分支时 MUST 同步另一
        # 车道的对应段，禁止只改一处；对照定位用方法名/分支语义，勿写
        # 裸行号（行号会漂移）。
        # provider 熔断拦截（code-review item 6cc1577c5086：子串匹配共用
        # PROVIDER_CIRCUIT_ERROR_MARKER 常量，防上游文案调整使本消费点静默失配）
        if final_error and PROVIDER_CIRCUIT_ERROR_MARKER in final_error:
            self._pm.state_machine.update_spec(spec_name, {"error": final_error})
            return
        # provider 瞬断终态延迟重派（code-review item 498a7c7432f1）：与 full 车道
        # 的 [provider-transient] 分支同语义（queue.py `_run_agent_worker`
        # implementer 失败处置链的 [provider-transient] elif 段）——瞬断终态不走
        # _retry_count 递增/清零路径，改按 transient_redispatch_delay_seconds
        # 排程等待后重派，避免把网关瞬断计入重试并快速重派。缺此分支会使
        # fast-track 车道与全车道语义不一致。
        if final_error and "[provider-transient]" in final_error:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track provider transient '{spec_name}' — scheduling "
                f"delayed redispatch, no retry/state flip: {final_error}",
            )
            self._pm.state_machine.update_spec(spec_name, {"error": final_error})
            self._schedule_transient_recovery(spec_name)
            return
        # 全链模型不可用终态（add-impl-selfcheck-model-probe 2.2，fast-track 车道
        # 对等）：链尾拒模型是确定性失败，同因重派必然撞同一拒模型链——不重派、
        # 不增 retry、不翻转状态机，error 落盘供 dashboard/admin 可见。摘除拒模型
        # 条目后恢复属人工运维（docs/help/12-faq.md）。
        if final_error and MODEL_CHAIN_UNAVAILABLE_MARKER in final_error:
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track model chain unavailable '{spec_name}' — holding "
                f"state, no redispatch/retry/state flip: {final_error}",
            )
            self._pm.state_machine.update_spec(spec_name, {"error": final_error})
            return
        # 重试
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        # _retry_count 走锁内原子递增（bump_counters 消费写后值判阈值，对齐本
        # 文件 _reconcile_and_merge 同型收口，code-review item 8164fca82421）：
        # 原先「read_one 读 → 算 +1 → update_spec 绝对写回」读与写分处两次
        # STATE 锁临界区，merge-only 重试定时器/周期恢复扫描与 worker 失败链
        # 并发进入同一 spec 时各持相同旧值写回、丢一次递增，max_retries 冻结
        # 封顶晚一轮触发、多烧一轮 fast-track run。bump 自带 int 归一（非法值
        # 按 0 起算），下方 update_spec 不再并写该字段（防并发写回互相覆盖）。
        retries = self._pm.state_machine.bump_counters(
            spec_name, {"_retry_count": 1}
        ).get("_retry_count", 0)
        # 配置侧 int() 归一（code-review item 74317ab4a77a）：字符串配置裸用于
        # `retries >= max_r` 比较抛 TypeError 中断失败重派，非法值回退缺省；
        # None 判空而非 or 兜底（code-review item c54ffbef69c5）：合法配置
        # 0（不自动重试）不被 or 吞成缺省 3。归一化单点工具
        # （code-review item c832188fbbac）。
        max_r = _normalize_int_config(self._pm._get_config("agents.max_retries", 3), 3)
        # fix-redispatch-loop-governance 3.4（fast-track 车道对等）：retries 达
        # max_r 时真正终止自动重试——冻结转人工（freeze_for_human，error 内嵌
        # 「原状态 X」供 parse_orig_status 解冻还原）。原实现「清零 _retry_count
        # 后照样 _enqueue」是空转（与 full 车道同款事故形态）。同因 streak 记账
        # 只在 full 车道通用失败重派分支（design D3 作用域边界），此处只做封顶冻结。
        if retries >= max_r:
            fp = self._pm._redispatch_cause_fingerprint(final_error)
            orig_status = (spec_entry or {}).get("status") or "implementing"
            self._pm.state_machine.freeze_for_human(
                spec_name,
                error=(
                    f"原状态 {orig_status} · fast-track 重试耗尽"
                    f"（{max_r}/{max_r} 轮，指纹 {fp}）：{final_error}"
                ),
                signal_type="redispatch_loop_detected",
                severity="major",
                description=(
                    f"'{spec_name}' fast-track 连续失败重试 {max_r} 轮已达上限"
                    f"（max_retries），自动重试终止——已冻结转人工处置"
                ),
                evidence=(
                    f"spec={spec_name}; retries={retries}; max_retries={max_r}; "
                    f"fp={fp}; final_error={final_error}"
                ),
                recommended_action=(
                    "检查失败根因；处置后解冻（unfreeze_spec 自动清零计数）可重新"
                    "获得自动修复机会"
                ),
                alert_callback=self._pm._send_human_escalation_alert,
            )
            self._pm.logger.error(
                "pm_engine",
                f"fast-track all retries exhausted '{spec_name}' — 冻结转人工，"
                f"不再重派（{retries}/{max_r}，fp={fp}）",
            )
        else:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "status": "ready",
                    "error": f"{final_error}｜自动重试 {retries}/{max_r}",
                    # _retry_count 已由上方 bump_counters 原子递增落盘，此处
                    # 不再并写（防并发写回互相覆盖丢增量）
                },
            )
            # 复位 ready 后显式重新入队（code-review item 6e6259821f64）：调用方
            # _run_fast_track_flow 失败分支立即 return，本模块其它「复位 ready」
            # 点（零变更哨/_hard_check/merge-retry）均 _enqueue_front 显式驱动
            # 重派——只翻状态不入队时「自动重试」承诺落空，spec 悬挂 ready 只能
            # 等周期恢复兜底（队列去重吸收重复条目，见 _enqueue_front）。
            self._enqueue_front(spec_name, "fast-track")
            self._pm.logger.warning(
                "pm_engine",
                f"fast-track retry {retries}/{max_r} '{spec_name}'",
            )

    def _handle_fast_track_zero_change(self, spec_name: str, result) -> None:
        """fast-track 零变更哨处理：与 implementer 同逻辑。

        （fix-fasttrack-recovery-resume 4.1 出口矩阵：零变更哨重派分支）
        本出口仅写 status/error/_zero_change_attempts + _enqueue_front 重派，
        对 branch/implementer_run/_recovery_resume 均**不触碰**——不新增清锚点、
        不消费恢复标记（重派经 dispatch 入口按续做标记处置）。
        """
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        # _zero_change_attempts 同型收口（code-review item 8164fca82421）：锁内
        # 原子递增、消费写后值判「连续 3 次」哨阈值，下方 update_spec 与 freeze
        # extra_updates 不再并写该字段（对齐 _reconcile_and_merge 的 bump_counters
        # 收口形态，防并发写回互相覆盖丢增量、零变更哨晚触发多烧 run）。
        attempts = self._pm.state_machine.bump_counters(
            spec_name, {"_zero_change_attempts": 1}
        ).get("_zero_change_attempts", 0)
        dirty = list(getattr(result, "worktree_dirty", None) or [])
        if dirty:
            err_note = (
                f"fast-track 宣称成功但零提交，worktree 有 "
                f"{len(dirty)} 个未提交修改——重派时务必 commit 后再报完成"
            )
        else:
            err_note = "fast-track 零变更报成功（疑似空转）— " "不合并不推进，重派"
        updates: dict = {
            "status": "ready",
            "error": err_note + f"（第 {attempts} 次）",
            # _zero_change_attempts 已由上方 bump_counters 原子递增落盘，此处
            # 不再并写（防并发写回互相覆盖丢增量）
        }
        if attempts >= 3:
            # 同型收敛（code-review item 44d5bfbf87a6，与 full 车道零变更哨 twin
            # 分支 queue.py 同款）：连续失败交人工收敛到 freeze_for_human 单一
            # 入口（frozen + 人工升级告警成对写入）。原裸 status=blocked 既无
            # frozen 标记也无成对告警，admin_monitor 的 blocked_stuck 豁免判据
            # 一条不占，冷却期满会被按 stuck 自动召唤 admin run，形成与 full
            # 车道分裂的两套处置机制。error 内嵌「原状态 X」供 parse_orig_status
            # 解冻还原；blocked 终态清旧 tester_run 指针沿用
            # （code-review item 14a6755b9728）。
            orig_status = spec_entry.get("status") or "implementing"
            self._pm.state_machine.freeze_for_human(
                spec_name,
                error=(
                    f"原状态 {orig_status} · fast-track 连续 {attempts} 次"
                    f"零变更报成功 — 已冻结转人工，需人工检查"
                ),
                signal_type="redispatch_loop_detected",
                severity="major",
                description=(
                    f"'{spec_name}' fast-track 连续 {attempts} 次零变更报成功"
                    f"（疑似空转），自动重派终止——已冻结转人工处置"
                ),
                evidence=(
                    f"spec={spec_name}; zero_change_attempts={attempts}; "
                    f"run={getattr(result, 'run_id', '') or ''}"
                ),
                recommended_action=(
                    "检查任务书/上下文/网关稳定性；处置后解冻"
                    "（unfreeze_spec 自动清零计数）可重新获得自动修复机会"
                ),
                alert_callback=self._pm._send_human_escalation_alert,
                extra_updates={
                    # _zero_change_attempts 已由 bump_counters 原子递增落盘，
                    # 不再并写（防并发写回互相覆盖丢增量）
                    "tester_run": None,
                },
            )
            self._pm.logger.error(
                "pm_engine",
                f"fast-track 零变更哨超限 '{spec_name}'（第 {attempts} 次）— "
                f"冻结转人工，不再重派",
            )
        else:
            self._pm.state_machine.update_spec(spec_name, updates)
        if attempts < 3:
            self._enqueue_front(spec_name, "fast-track")

    def _handle_fast_track_deliverable_gate(
        self,
        spec_name: str,
        result,
        missing: list,
        impl_result=None,
    ) -> dict:
        """fast-track 交付物守卫触发：接入同源裁决流水线（add-declaration-relocation-protocol 4.4）。

        与 full 车道同源（``_adjudicate_deliverable_missing``），保持 LLM 终审 /
        重定位 / 预分类软化 / 防洗白的统一行为与输出契约。``impl_result`` 为已
        解析的实现结果 dict（``_read_implementer_result`` 产物，与 full 车道同
        源），供 dispute-judge 输入携带实现者自报 findings；缺省 None 时 judge
        输入 findings 为空（fail-open）。重派时按 fast-track 车道入队（MUST NOT
        直按缺件重派）。
        """
        adjudication = self._pm._adjudicate_deliverable_missing(
            spec_name, result, impl_result, missing, agent_type="fast-track"
        )
        return adjudication
