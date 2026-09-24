"""rollback.py — R 失败回滚/诊断上报（refactor-giant-classes D1/D3/D5）。

原为 Dispatcher 的 4 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。含 2 个 staticmethod：

- `_honest_exit_gap`：测试经 ``Dispatcher._honest_exit_gap`` 类直调
  （`tests/test_honest_exit_convergence.py`），D3 须留类命名空间——mixin 上的
  staticmethod 经继承仍挂在类命名空间；
- `_dispatch_backoffed`：`admin_monitor.py` 生产类直调 `Dispatcher._dispatch_backoffed`
  （D3），同上经继承保留。

跨组协作仍经宿主实例 `self.<method>` / `self._pm.<method>`。
"""

from __future__ import annotations

import shlex
import time
from datetime import datetime, timezone

from core.pm_engine.dispatch.queue import WIP_DEFER_WINDOW_MINUTES, WIP_DEFER_MAX_ROUNDS


class RRollbackMixin:
    """R 失败回滚/诊断上报（design D1 表 B R 组）。"""

    @staticmethod
    def _honest_exit_gap(pm, spec_name: str, impl_result) -> list:
        """partial 收工的「缺口全部 ⊆ unattainable 申报」判定（诚实退出收敛）。

        返回非空列表 = 缺口确实存在且**每一项**都由结果文件顶层 ``unattainable``
        申报覆盖（如「需用户确认时机后重启 daemon」这类人工运维门控）；空列表 =
        无缺口、或存在未申报缺口、或申报含非法项（防 partial 洗白 / 防非法申报
        部分采信，仍按失败处置）。

        判据单点（fix-redispatch-loop-governance D1/D2b/D4）：收敛判定本体在
        ``core.run_task_track.honest_exit_convergence_gap``（内部即
        ``gap_from_result`` + ``parse_unattainable``），本方法为经 Dispatcher
        命名空间暴露的薄封装（既有调用点与测试经 ``Dispatcher._honest_exit_gap``
        类直调）。缺口口径 MUST 取结果文件，MUST NOT 回退主树 tasks.md 勾选
        （partial 收敛走不到 ``_sync_task_progress`` 回写路径，读主树会把已完成
        任务也算成缺口形成读侧自锁，2026-09-17 事故）。

        与 ``engine._task_completion_blocker`` 的诚实退出分支同判据（同一实现点）。
        判定异常一律返回空（fail-closed 按失败处置）。
        """
        try:
            from core.run_task_track import honest_exit_convergence_gap as _h

            return _h(impl_result or {}, pm.project_root, spec_name)
        except Exception as e:  # noqa: BLE001 — 判定异常按失败处置（不阻断收敛主流程）
            try:
                pm.logger.debug(
                    "pm_engine",
                    f"unattainable 收敛判定异常 '{spec_name}'（按失败处置）: {e}",
                )
            except Exception:
                pass
        return []

    @staticmethod
    def _dispatch_backoffed(spec: dict) -> bool:
        """判断 spec 是否处于派发退避期（派发基础设施失败后防振荡）。

        返回 True 表示本轮不可派发；条目保留在队列中，退避过期后自然恢复，
        配合 periodic full_scan 的 recovery 兜底最多延迟一个扫描周期。
        """
        until = spec.get("_dispatch_backoff_until")
        if not until:
            return False
        try:
            return float(until) > datetime.now(timezone.utc).timestamp()
        except (TypeError, ValueError):
            return False

    def _dispatch_rollback_backoff_seconds(self) -> int:
        """派发异常回滚后的防振荡退避窗（秒）。

        可配 ``pm.dispatch_rollback_backoff_seconds``，默认 300s
        （code-review item 7b281a0886ea：原硬编码 +300 与可配置的
        ``pm.dispatch_backoff_schedule`` 双源不统一，调参/行为诊断困难）。
        非正数/非法值回退缺省。
        """
        default = 300
        try:
            v = float(self._pm._get_config("pm.dispatch_rollback_backoff_seconds", default))
        except (TypeError, ValueError):
            return default
        if v != v or v in (float("inf"), float("-inf")) or v <= 0:
            return default
        return int(v)

    def _rollback_failed_dispatch(self, spec_name: str, agent_type: str, exc: Exception):
        """派发/执行异常时回滚滞留中间态的 spec 到可重试态（fix: 伪 bug 卡死）。

        - implementer 失败：implementing → ready，清空 run 字段；error 置 None 以便
          full_scan 的 spec_ready recovery 再次拾起（错误详情记入 _last_dispatch_error）。
        - verifier 失败：testing → implemented，清 tester_run；实现保留（不重实现）。
        设置 _dispatch_backoff_until（默认 5 分钟，可配
        ``pm.dispatch_rollback_backoff_seconds``）吸收 inotify 触发的即时重派振荡；
        重试由队列条目 + full_scan recovery 兜底（最长 30 分钟窗口）。
        """
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name)
            if not spec_entry:
                return
            status = spec_entry.get("status")
            backoff_until = int(datetime.now(timezone.utc).timestamp()) + (
                self._dispatch_rollback_backoff_seconds()
            )
            if agent_type == "verifier" and status == "testing":
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "implemented",
                        "tester_run": None,
                        "error": f"Verification infrastructure failure (retryable): {exc}",
                        "_dispatch_backoff_until": backoff_until,
                    },
                )
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' testing → implemented (verifier never started): {exc}",
                )
                # 入队独立守卫（code-review item 01bfb767effe，与 implementer 分支
                # 同款）：_enqueue 若裸露在大 try 内，队列写入抛错（锁/IO）会跳到
                # 外层 except 记误导性「State rollback failed」（尽管上方 update_spec
                # 已把 spec 复位 implemented）且重派条目静默丢失。单独守卫：失败
                # 如实记 ERROR，不覆盖状态复位成果（full_scan recovery 兜底）。
                try:
                    self._enqueue(spec_name, "verifier")
                except Exception as enqueue_exc:  # noqa: BLE001 —— 入队失败不吞回滚成果
                    self._pm.logger.error(
                        "pm_engine",
                        f"Redispatch enqueue failed for '{spec_name}' "
                        f"(state rolled back to implemented, pending full_scan "
                        f"recovery): {type(enqueue_exc).__name__}: {enqueue_exc}",
                    )
            elif agent_type == "spec-review" and status == "reviewing":
                # 评审 worker 异常回滚（fix-spec-review-blocking-dispatch 1.8
                # 双保险）：四步链之外异常（构造失败/快照路径异常）时 spec 可能
                # 停在 reviewing 且 reviewer_run 未被推进——清锚点、保持
                # reviewing。MUST NOT 在此处重新入队：_run_spec_review_worker
                # 已在四步链外异常路径显式入队（tasks 1.8），此处作为
                # defense-in-depth 兜底仅清理状态，避免双入队导致无限重派
                # （worker 异常 → 入队 → 再 worker 异常 → 再入队…）。
                # 未入队的残余场景由 recovery 的 reviewing 分支兜底拾取。
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "reviewer_run": None,
                        "error": f"spec-review-incomplete: dispatch exception: {exc}",
                    },
                )
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' reviewing（评审 worker 异常，"
                    f"清理锚点待恢复拾取）: {exc}",
                )
            elif agent_type in ("implementer", "fast-track") and status == "implementing":
                # 死亡 run 豁免（fix-budget-counting-semantics D1）：异常路径＝
                # run 无收工结果产出（进程消失/零输出/网关链路耗尽），回退本次
                # 启动的预算计数。计数在 worker 启动处先行递增，此处补偿回退。
                # run_reason 传入 exc 信息（派发异常不属监督超时/停滞，应豁免）。
                #
                # 隔离（code-review item a986aab6fa9d）：豁免是**尽力而为的记账**
                # （bump_impl_budget / bump_budget_exempt_runs 均写状态文件），若它
                # 自己抛异常（状态文件锁/IO、_impl_run_budget_used 读取失败），
                # 控制流会直接跳到外层 except，使下面的
                # update_spec(→ready)/_last_dispatch_error/_enqueue **永远执行不到**
                # ——spec 卡在 implementing 且无队列条目，正是本方法要修复的故障。
                # 故必须独立 try/except，让豁免失败不能中止回滚。
                # exempt_applied 标记（code-review item 6d56aa5de387）：审计日志
                # 无条件落盘，须携带豁免是否实际生效，否则记账失败（状态文件
                # 锁/IO 异常）时对账会把未生效的豁免当作已豁免。
                exempt_applied = False
                try:
                    self._pm._exempt_dead_run_budget(
                        spec_name,
                        f"dispatch exception: {str(exc)[:80]}",
                        run_reason=str(exc) if exc else None,
                    )
                    exempt_applied = True
                except Exception as exempt_exc:  # noqa: BLE001 —— 记账失败不阻塞回滚
                    self._pm.logger.warning(
                        "pm_engine",
                        f"budget exempt failed for '{spec_name}'（按未豁免继续回滚）: "
                        f"{type(exempt_exc).__name__}: {exempt_exc}",
                    )
                self._pm.logger.info(
                    "pm_engine",
                    f"budget_exempt_audit: spec={spec_name}, "
                    f"dispatch_exception, exempt_applied={exempt_applied}, "
                    f"exc={str(exc)[:120]}, "
                    f"run_reason={str(exc)[:80] if exc else ''}",
                )
                # fix-run-hang-amplification 2.5：update_spec 增量更新——此处只清
                # error 与 run 字段，_impl_diagnosis 结构化诊断 MUST NOT 被清除
                # （重派 attempt 需继承上轮诊断）。
                # （fix-fasttrack-recovery-resume D5 区分注释）本处清锚点属**有意回滚**
                # ——run **从未启动**（dispatch 异常），`_recovery_resume` 尚未被消费、
                # 锚点亦非本轮产出。MUST NOT 消费该标记（保持原值），使其在原样重派
                # 时仍可被 dispatch 入口消费；清 branch/implementer_run 只是剥除
                # 从未启动的 run 留下的空壳字段，恢复续做锚点不在其列。
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "status": "ready",
                        "implementer_run": None,
                        "tester_run": None,
                        "branch": None,
                        "error": None,
                        "_last_dispatch_error": f"Implementation dispatch failed (retryable): {exc}",
                        "_dispatch_backoff_until": backoff_until,
                    },
                )
                self._pm.logger.warning(
                    "pm_engine",
                    f"Rolled back '{spec_name}' implementing → ready "
                    f"({agent_type} never started): {exc}",
                )
                # 入队独立守卫（code-review item 9842741702fe）：_enqueue 原在大
                # try 内任何守卫外——队列写入抛错（锁/IO）会跳到外层 except 记
                # 误导性「State rollback failed」（尽管上方 update_spec 已把 spec
                # 复位 ready）且重派条目静默丢失，正是本方法要修复的卡死状态
                # （只剩 full_scan recovery 兜底）。单独守卫：失败如实记 ERROR，
                # 不覆盖状态复位成果。
                try:
                    self._enqueue(spec_name, agent_type)
                except Exception as enqueue_exc:  # noqa: BLE001 —— 入队失败不吞回滚成果
                    self._pm.logger.error(
                        "pm_engine",
                        f"Redispatch enqueue failed for '{spec_name}' "
                        f"(state rolled back to ready, pending full_scan "
                        f"recovery): {type(enqueue_exc).__name__}: {enqueue_exc}",
                    )
            else:
                # 未覆盖 (agent_type, status) 组合（code-review item 01c0160765d2）：
                # 旧 if/elif 链无兜底——静默返回、无日志、无回滚，残余卡死形态在
                # 日志里不可诊断。至少记一条 WARNING 暴露观测到的组合。
                self._pm.logger.warning(
                    "pm_engine",
                    f"派发失败回滚：未覆盖组合 spec='{spec_name}' "
                    f"agent_type={agent_type!r} status={status!r}（无回滚动作，仅留痕）",
                )
        except Exception as e2:
            self._pm.logger.error("pm_engine", f"State rollback failed for '{spec_name}': {e2}")

    def _report_stash_pop_conflict(
        self, spec_name: str, conflict_files: list, merge_info=None
    ) -> None:
        """pop 冲突自愈后上报被丢弃的 stash 改动文件清单（fix-stashpop-deadlock）。

        主树已通过 checkout HEAD + reset 自愈回到干净可写状态，merge 结果不丢失、
        状态正常推进到 implemented。上报走双通道（fix-mergeback-stashpop-silent-loss
        D1）：既有 spec.error 字段写入保持不变（向后兼容 dashboard 时间轴读侧）；
        另经 admin_store.append 直发一条 ``signal_type=stash_pop_conflict`` 告警——
        通知不再依赖瞬态 error 字段或日志指纹风暴规则。告警 description 含 spec 名、
        冲突文件清单、stash 条目去向（保留/drop + sha）、逐文件找回命令，以及
        merge-back 前的 WIP 重叠预检清单（若有）。

        error 文本格式（供 dashboard/admin 可读）：``stash pop conflict: files=[...]``
        """
        if not conflict_files:
            return
        msg = f"stash pop conflict: files={conflict_files}"
        try:
            self._pm.state_machine.update_spec(spec_name, {"error": msg})
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"stash pop conflict 上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' {msg} —— stash 保留，可用 git stash show 找回被丢弃改动",
        )
        # admin 告警直发（fix-mergeback-stashpop-silent-loss D1）：低频事件、
        # 无风暴风险，不加节流。任何异常都不阻塞 merge-back 主流程。
        try:
            from core.admin_store import AdminStore, SIGNAL

            # 条目去向从 worktree_manager 读（dispatch 层不持锁，读实例属性足够——
            # guard 段已结束、无并发写者）。kept 缺键时按 **True** 保守默认
            # （code-review item f09a5bfeb402）：旧实现 `fate.get("kept")` 缺键
            # 回 None（falsy）会误报「已被自动 drop」并写 stash_kept=False，
            # 编造数据丢失声明；缺键与读取失败同属「无法确证 drop」，一律按保留。
            try:
                fate = dict(self._pm.agent_runner.worktree_manager.last_stash_entry_fate)
            except Exception:
                fate = {"kept": True, "sha": ""}
            sha = fate.get("sha", "") or ""
            short_sha = sha[:12] if sha else ""
            if fate.get("kept", True):
                fate_desc = (
                    f"stash 条目保留在栈中（栈顶 sha {short_sha}，" f"git stash list 可见）"
                    if short_sha
                    else "stash 条目保留在栈中"
                )
            else:
                fate_desc = (
                    f"stash 版已被合并结果完全取代，条目已自动 drop"
                    f"（commit {short_sha}，gc 前可按 sha 找回）"
                    if short_sha
                    else "stash 条目已被自动 drop"
                )
            recover_cmds = (
                "; ".join(f"git show {sha}:{shlex.quote(f)}" for f in conflict_files)
                if sha
                else "git stash show / git stash list 人工核对"
            )
            overlap = list(getattr(merge_info, "wip_overlap", []) or [])
            overlap_desc = (
                f"；merge-back 前 WIP 重叠预检命中 {len(overlap)} 文件"
                f"（可能与本次丢弃相关）：{overlap}"
                if overlap
                else ""
            )
            description = (
                f"SPEC '{spec_name}' merge-back stash pop 冲突已自愈："
                f"{len(conflict_files)} 个文件的未提交改动被丢弃 "
                f"({', '.join(conflict_files)})。{fate_desc}{overlap_desc}。"
                f"逐文件找回：{recover_cmds}"
            )
            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "stash_pop_conflict",
                    "spec": spec_name,
                    "severity": "major",
                    "description": description,
                    "evidence": {
                        "conflict_files": list(conflict_files),
                        "stash_kept": bool(fate.get("kept", True)),
                        "stash_sha": sha,
                        "wip_overlap": overlap,
                    },
                    "recommended_action": (
                        "git stash list 查条目去向；按逐文件 git show <sha>:<file> 命令"
                        "核对内容，仍需要的改动手动落回工作区；确认零独有内容后 "
                        "git stash drop 清理"
                    ),
                }
            )
            self._pm.logger.info(
                "pm_engine",
                f"stash_pop_conflict 告警已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"stash_pop_conflict 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _report_mergeback_wip_overlap(
        self, spec_name: str, merge_info, branch: str, merge_error: str
    ) -> None:
        """WIP 重叠闸门阻塞告警直发（evo-merge-back-wip-overlap-gate D1/D3）。

        在 merge 结果处理的**失败/阻塞分支**、``wip_gate_blocked=True`` 时调用
        （主通道与 fast-track 通道两处站点均覆盖）：merge-back 未发生（不 stash、
        不 merge、不 pop，主树零污染），spec 保持 in-flight。告警含 spec 名、
        重叠文件清单、策略（阻塞）、找回命令与处置指引——signal_type=
        ``mergeback_wip_overlap``，经 admin_monitor 白名单摄取唤起 Administrator。

        **序列化加固（D6）**：evidence 一律先经 ``_str_field``（实现在
        core/agent_runner/prompt_builder.py）序列化为 str 再入 record——dict
        穿透 ``str.replace`` 会致 Administrator 唤起失败（fix-alert-evidence-
        render-crash 先例）。

        任何异常都不阻塞 merge 结果处理主流程。
        """
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        recover_cmds = (
            "git stash list 查条目去向；逐文件 git show <sha>:<file> 核对"
            "（如 git show stash@{0}:<file>）"
        )
        description = (
            f"SPEC '{spec_name}' merge-back 被 WIP 重叠闸门阻塞（策略=block）："
            f"主树 {len(overlap)} 个已跟踪文件存在未提交改动，与分支 "
            f"'{branch}' 的改动路径重叠（{overlap}）——为避免 pop 冲突静默丢弃，"
            f"已中止合并（主树零污染，未 stash/未 merge/未 pop）。"
            f"找回/核对：{recover_cmds}。"
            f"处置指引：提交（git add/commit）或 stash（git stash push）主树这些"
            f"重叠改动后，重新放行该 spec（ready 重派）即可继续 merge-back。"
        )
        try:
            # 结构化等待载体（evo-add-wip-defer-merge-retry-consumer 1.1）：
            # error 文本不再作为唯一现场标志——同次 update_spec 增写
            # _wip_gate_deferred=True + 复用 _merge_retry_count/_merge_retry_first_at
            # 记账（与 spec_dir_inflight 顺延共用一套计数，混账已知、接受——
            # 见设计「风险与边界」）。首阻时刻沿用既有值（同一 spec 先后经历
            # 两种阻断时窗口不重置），缺省取当前时刻。消费者（queue.py 周期
            # 复查）据此自动 merge-only 重试；标志的生命周期不变式：
            # implementing+_wip_gate_deferred ⇒ 无在飞实现 run（触发阻断的
            # run 已在结果处理期收尾，新 run 只能自 ready 派发而 boot 两个
            # 复位写点已清标志）。
            entry = self._pm.state_machine.read_one(spec_name) or {}
            try:
                prev_count = int(entry.get("_merge_retry_count", 0) or 0)
            except (TypeError, ValueError):
                prev_count = 0
            prev_first = entry.get("_merge_retry_first_at")
            try:
                first_f = float(prev_first) if prev_first else None
            except (TypeError, ValueError):
                first_f = None
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": f"mergeback wip overlap blocked (policy=block): files={overlap}",
                    "_wip_gate_deferred": True,
                    "_merge_retry_count": prev_count,
                    "_merge_retry_first_at": int(first_f) if first_f else int(time.time()),
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback wip overlap 状态上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' mergeback wip overlap blocked —— 主树零污染，"
            f"等待人工提交/stash 重叠改动后重新放行",
        )
        try:
            from core.agent_runner.prompt_builder import _str_field
            from core.admin_store import AdminStore, SIGNAL

            evidence = _str_field(
                {
                    "overlap_files": overlap,
                    "policy": "block",
                    "branch": branch,
                    "merge_error": str(merge_error),
                }
            )
            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "mergeback_wip_overlap",
                    "spec": spec_name,
                    "severity": "major",
                    "description": description,
                    "evidence": evidence,
                    "recommended_action": (
                        "提交或 stash 主树与分支重叠的未提交改动"
                        "（git add/commit 或 git stash push）后重新放行该 spec"
                        "（ready 重派）继续 merge-back；被收纳/保留的改动可用 "
                        "git stash list 与逐文件 git show <sha>:<file> 找回核对"
                    ),
                }
            )
            self._pm.logger.info(
                "pm_engine",
                f"mergeback_wip_overlap 告警已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback_wip_overlap 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _report_mergeback_spec_dir_inflight_stuck(
        self, spec_name: str, merge_info, branch: str, merge_error: str,
        retry_count: int, first_at: int,
    ) -> None:
        """spec 目录在飞编辑顺延超限回落告警（evo-merge-back-spec-dir-inflight-guard D1a/D2）。

        顺延窗口（``mergeback.spec_dir_inflight_grace_minutes``，缺省 30 分钟）或
        连续顺延轮数（``mergeback.spec_dir_inflight_max_rounds``，缺省 3）超限时
        调用：MUST NOT 无限顺延（无上限顺延会把事故中的「整轮重派」换成「永不再
        处理」，比事故更差）。走既有「发告警 + 等待人工处置」直通，对齐
        ``_report_mergeback_wip_overlap`` 同型语义：

        - spec 保持 in-flight（implementing），分支/锚点原样保留（MUST NOT 静默
          丢弃分支）；
        - 写 admin store 信号（signal_type=``mergeback_spec_dir_inflight_stuck``）——
          该 spec 对本窗口的可见性由本告警 + 后续 orphaned_state 探测（implementing
          无活动 run 超短阈值）共同兜底（周期巡检对 ready 态在飞等待不可见，
          故不降级 ready）；
        - 任何异常不阻塞调用方主流程。

        告警描述含找回/处置指引（提交主树 spec 目录后，人工可 reset 复位实现状态
        重新放行，或等待 daemon 恢复通道重试）。
        """
        description = (
            f"SPEC '{spec_name}' merge-back 顺延超限（spec 目录在飞编辑）："
            f"自首轮顺延（{first_at}）起已连续 {retry_count} 轮仍未解除"
            f"（窗口/轮数上限已到），已停止自动重试等待人工处置。分支 "
            f"'{branch}' 保留（已成功实现、仅剩合并）。处置指引：提交主树 "
            f"spec/changes/{spec_name}/ 目录的未提交改动（git add/commit，"
            f"含 spec 迭代修补），再把该 spec 复位 ready 重新放行 merge-back；"
            f"或等待 daemon 恢复通道（recovery）下一轮再试。"
        )
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": (
                        f"mergeback spec_dir_inflight stuck after {retry_count} "
                        f"rounds since {first_at}: {str(merge_error)[:120]}"
                    ),
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback spec_dir_inflight_stuck 状态上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' merge-back 顺延超限（spec 目录在飞编辑）—— 已停止自动"
            f"重试，等待人工提交 spec 目录后重新放行（分支与产物保留）",
        )
        try:
            from core.agent_runner.prompt_builder import _str_field
            from core.admin_store import AdminStore, SIGNAL

            evidence = _str_field(
                {
                    "retry_count": retry_count,
                    "first_at": first_at,
                    "branch": branch,
                    "merge_error": str(merge_error),
                }
            )
            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "mergeback_spec_dir_inflight_stuck",
                    "spec": spec_name,
                    "severity": "major",
                    "description": description,
                    "evidence": evidence,
                    "recommended_action": (
                        "提交主树 spec/changes/ 目录的未提交改动"
                        "（git add/commit，含 spec 迭代修补）后重新放行该 spec"
                        "（ready 重派）继续 merge-back；分支与已成功实现保留"
                    ),
                }
            )
            self._pm.logger.info(
                "pm_engine",
                f"mergeback_spec_dir_inflight_stuck 告警已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback_spec_dir_inflight_stuck 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )

    def _report_mergeback_wip_defer_stuck(
        self, spec_name: str, retry_count: int, first_at: int,
    ) -> None:
        """WIP 等待超限降级告警（evo-add-wip-defer-merge-retry-consumer 2.1）。

        周期消费者在等待超窗口（90 分钟，对齐 code-fix defer 范式）或重试超
        轮数（6 次）时调用（``_report_mergeback_spec_dir_inflight_stuck`` 同型
        语义）：停止自动 merge-only 重试、降级为人工处置告警。现场标志
        （``_wip_gate_deferred``）保留供人工与取证——orphaned_state 探测的
        豁免随之自动失效（同一上限常量口径，admin_monitor 2.3），孤儿探测
        恢复兜底。任何异常不阻塞调用方主流程。
        """
        description = (
            f"SPEC '{spec_name}' WIP 延迟合回等待超限：自首阻（{first_at}）起已等 "
            f"{retry_count} 轮仍未解除（窗口/轮数上限已到），已停止自动 "
            f"merge-only 重试，转人工处置。分支保留（已成功实现、仅剩合并，"
            f"主树零污染）。处置指引：确认主树与分支改动路径重叠的未提交改动"
            f"归属后，提交（git add/commit）或 stash（git stash push）主树重叠"
            f"改动，再把该 spec 复位 ready 重新放行 merge-back；或人工完成合并。"
        )
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": (
                        f"mergeback wip defer stuck after {retry_count} "
                        f"rounds since {first_at} — manual handling required"
                    ),
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback wip defer stuck 状态上报失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.error(
            "pm_engine",
            f"'{spec_name}' WIP 延迟合回等待超限 —— 已停止自动重试，"
            f"等待人工处置主树重叠改动（分支与产物保留）",
        )
        try:
            from core.agent_runner.prompt_builder import _str_field
            from core.admin_store import AdminStore, SIGNAL

            evidence = _str_field(
                {
                    "retry_count": retry_count,
                    "first_blocked_at": first_at,
                    "window_minutes": int(WIP_DEFER_WINDOW_MINUTES),
                    "max_rounds": WIP_DEFER_MAX_ROUNDS,
                }
            )
            store = AdminStore(self._pm.project_root, self._pm.logger)
            store.append(
                {
                    "kind": SIGNAL,
                    "signal_type": "mergeback_wip_defer_stuck",
                    "spec": spec_name,
                    "severity": "major",
                    "description": description,
                    "evidence": evidence,
                    "recommended_action": (
                        "人工核对主树与分支重叠的未提交改动归属后提交/stash，"
                        "再把该 spec 复位 ready 重新放行 merge-back；"
                        "或人工完成该分支向主树的合并"
                    ),
                }
            )
            self._pm.logger.info(
                "pm_engine",
                f"mergeback_wip_defer_stuck 告警已写入 admin store: '{spec_name}'",
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"mergeback_wip_defer_stuck 告警写入失败 '{spec_name}'（非阻塞）: {e}",
            )