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

from datetime import datetime, timezone


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

    def _rollback_failed_dispatch(self, spec_name: str, agent_type: str, exc: Exception):
        """派发/执行异常时回滚滞留中间态的 spec 到可重试态（fix: 伪 bug 卡死）。

        - implementer 失败：implementing → ready，清空 run 字段；error 置 None 以便
          full_scan 的 spec_ready recovery 再次拾起（错误详情记入 _last_dispatch_error）。
        - verifier 失败：testing → implemented，清 tester_run；实现保留（不重实现）。
        设置 _dispatch_backoff_until（5 分钟）吸收 inotify 触发的即时重派振荡；
        重试由队列条目 + full_scan recovery 兜底（最长 30 分钟窗口）。
        """
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name)
            if not spec_entry:
                return
            status = spec_entry.get("status")
            backoff_until = int(datetime.now(timezone.utc).timestamp()) + 300
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
                self._enqueue(spec_name, "verifier")
            elif agent_type in ("implementer", "fast-track") and status == "implementing":
                # 死亡 run 豁免（fix-budget-counting-semantics D1）：异常路径＝
                # run 无收工结果产出（进程消失/零输出/网关链路耗尽），回退本次
                # 启动的预算计数。计数在 worker 启动处先行递增，此处补偿回退。
                # run_reason 传入 exc 信息（派发异常不属监督超时/停滞，应豁免）。
                self._pm._exempt_dead_run_budget(
                    spec_name,
                    f"dispatch exception: {str(exc)[:80]}",
                    run_reason=str(exc) if exc else None,
                )
                self._pm.logger.info(
                    "pm_engine",
                    f"budget_exempt_audit: spec={spec_name}, "
                    f"dispatch_exception, exc={str(exc)[:120]}, "
                    f"run_reason={str(exc)[:80] if exc else ''}",
                )
                # fix-run-hang-amplification 2.5：update_spec 增量更新——此处只清
                # error 与 run 字段，_impl_diagnosis 结构化诊断 MUST NOT 被清除
                # （重派 attempt 需继承上轮诊断）。
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
                self._enqueue(spec_name, agent_type)
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
            # guard 段已结束、无并发写者）。
            try:
                fate = dict(self._pm.agent_runner.worktree_manager.last_stash_entry_fate)
            except Exception:
                fate = {"kept": True, "sha": ""}
            sha = fate.get("sha", "") or ""
            short_sha = sha[:12] if sha else ""
            if fate.get("kept"):
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
                "; ".join(f"git show {sha}:{f}" for f in conflict_files)
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
                        "stash_kept": bool(fate.get("kept")),
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