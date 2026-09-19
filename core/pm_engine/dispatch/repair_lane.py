"""repair_lane.py — P merge-back 修复车道（refactor-giant-classes D1/D3/D5/D6）。

原为 Dispatcher 的 9 个方法（`core/pm_engine/dispatch/_legacy.py`），
原样搬移为 mixin（方法体零改动）。跨组协作（_reconcile_and_merge /
_run_fast_track_flow 等 F 组）仍经宿主实例 `self.<method>` 协作。

D6 无环约束：本组 MUST NOT 直接 import `core.worktree_manager`
（现状经 `self._pm.agent_runner.<...>` 属性链间接访问，无边）。

D3 patch 缝隙：本组使用 `time` 模块，经模块顶部导入——测试
patch time 模块对象属性全进程共享，重绑依旧生效。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, start_after_pending

from core.pm_engine.dispatch import (  # noqa: E402
    MAX_REPAIR_ROUNDS_PER_FAILURE,
)


class PRepairLaneMixin:
    """P merge-back 修复车道（design D1 表 B P 组）。"""

    def _direct_rehearsed_to_repair(
        self, spec_name: str, merge_info, branch: str, merge_error: str
    ) -> None:
        """预演语义冲突直通 repair（add-merge-tree-rehearsal D2/D5）。

        implementer 与 fast-track 失败分支共用：merge-tree 预演已在主树零污染点
        检出语义冲突（``rehearsed=True``）——真合并从未发生，``_merge_fp``/
        ``_merge_streak`` 记账与 ready 降级在此路径均无意义（fp 熔断的职责——
        阻断「根因不消除→整轮重跑→再败」循环——由 repair 轮次上限承接）。
        spec 保持 in-flight，repair agent 在实现分支内把 main 合入解决冲突。

        轮次兜底（D5）：``_should_enter_repair`` 拒绝（已 blocked / ``_repair_round``
        超限）时回退现行 fallback 重派路径（prompt 注入冲突上下文），不产生无限
        repair 循环；repair 后 re-merge 失败链仍走既有 fp 熔断（本方法不动熔断语义）。
        """
        breaker_threshold = self._pm._get_config("agents.merge_breaker_threshold", 2)
        if self._pm._should_enter_repair(spec_name, merge_info, 0, breaker_threshold):
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突直通 repair '{spec_name}'："
                f"{len(merge_info.conflict_paths)} path(s) "
                f"{getattr(merge_info, 'conflict_paths', [])} — 主树零污染，"
                f"不经 fp 记账（rehearsed）",
            )
            self._pm._dispatch_repair_lane(spec_name, merge_info, branch)
        else:
            self._pm.logger.info(
                "pm_engine",
                f"预演检出语义冲突但 repair 不可用 '{spec_name}'"
                f"（轮次超限/已 blocked）— 回退 fallback 重派（rehearsed，"
                f"prompt 注入冲突上下文）",
            )
            self._fallback_after_repair(spec_name, branch, merge_error)

    def _should_enter_repair(
        self, spec_name: str, merge_info, streak: int, breaker_threshold: int
    ) -> bool:
        """merge-back 失败后是否进入 repair 通道（语义冲突 + 熔断未触发 + 未超轮次）。

        判定依据（spec-mergeback-inplace-repair）：
        - merge_info 携带结构化冲突分类（D1）；
        - 全部冲突路径均为构建产物且自愈成功时（success=True）不会走到这里——
          调用方仅在 ``not merge_ok`` 分支内调用；
        - 冲突含语义文件（has_semantic_conflict）→ 产物/ignored-DU 自愈均不适用；
        - 熔断未触发（streak < threshold）：blocked spec 不再派发 repair；
        - 同一失败链内 repair 未超轮次（_repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE）。
        """
        # 兼容 (bool, str) 元组调用（merge_info 可能非 MergeConflictInfo）
        info_has_semantic = bool(getattr(merge_info, "has_semantic_conflict", False))
        if not info_has_semantic:
            return False
        try:
            spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        except Exception:
            spec_entry = {}
        if spec_entry.get("status") == "blocked":
            return False
        if streak >= breaker_threshold:
            return False
        try:
            repair_round = int(spec_entry.get("_repair_round", 0) or 0)
        except (TypeError, ValueError):
            repair_round = 0
        return repair_round < MAX_REPAIR_ROUNDS_PER_FAILURE

    def _dispatch_repair_lane(
        self, spec_name: str, merge_info, branch: str, fp: str | None = None, streak: int = 0
    ) -> None:
        """进入 repair 通道：三态解析载体 → 认领现场 → 派发 repair worker。

        载体三态（design D3，以 git 事实为判定基准）：
        (a) 原 worktree 存在 → 原地进入（保留 node_modules/构建缓存）；
        (b) worktree 已清但分支存在 → 换壳：在分支上新建 worktree；
        (c) 分支不存在 → 回退 fallback 全新重派（prompt 注入 merge 失败上下文）。

        轮次控制（D5/D6）：``_repair_round`` 在派发前递增并持久化，
        超限不派发（_should_enter_repair 已拦截，此处兜底回退）。
        """
        wm = self._pm.agent_runner.worktree_manager
        # cli-retry-backoff 2.2：秒挂冷却期内不派发 repair（repair agent 同样会秒挂）。
        # spec 保持原状，冷却到期由恢复定时器 / full_scan 重新唤起实现派发。
        if self._pm._instant_fail_cooled(spec_name):
            self._pm.logger.debug(
                "pm_engine",
                f"秒挂冷却中，跳过 repair 派发 '{spec_name}'（冷却期后恢复调度）",
            )
            self._schedule_instant_fail_recovery(spec_name)
            return
        # evo-sigterm-source-tracking-cooldown：信号死法冷却期内不派发 repair。
        # 与秒挂冷却并存：两条通道各自排程恢复，取更晚的冷却截止生效。
        if self._pm._signal_kill_cooled(spec_name):
            self._pm.logger.debug(
                "pm_engine",
                f"信号死法冷却中，跳过 repair 派发 '{spec_name}'"
                f"（冷却期后恢复调度）",
            )
            self._schedule_signal_kill_recovery(spec_name)
            return
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        # 分支消亡 → fallback（三态 (c)）
        if not branch or not wm.branch_exists(branch):
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体分支 '{branch}' 不存在 — 回退 fallback 全新重派",
            )
            self._fallback_after_repair(
                spec_name,
                None,
                getattr(merge_info, "error", "") or "",
            )
            return
        # 三态解析：原地 / 换壳
        wt_path, resolved_branch = wm.resolve_repair_site(spec_name, branch)
        if wt_path is None:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 载体解析失败（分支 '{branch}' 不可用）— 回退 fallback",
            )
            self._fallback_after_repair(
                spec_name,
                branch,
                getattr(merge_info, "error", "") or "",
            )
            return
        # 认领现场（D4）：_legacy take 摘出 + _spec_locks 注册，防 sweeper 宽限期回收
        self._pm._claim_repair_site(spec_name, wt_path, resolved_branch)
        # 轮次递增（D5/D6）：repair 轮计入该 spec 的实现预算（token 记名下）；
        # 连续计数 _merge_fp/_merge_streak 不被 repair 轮清零（熔断协同）。
        round_no = repair_round + 1
        # ── 基准 tip 记录（fix-repair-commit-enforcement D2）─────────────
        # repair 派发前记录分支 tip，repair 后 worker 复核「tip 是否前进」。
        # 与 _repair_round/_repair_merge_fp 同处一次 update_spec 落盘，
        # 语义一致（统一 repair 轮次元数据）。
        base_tip = wm.branch_tip(resolved_branch)
        try:
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "_repair_round": round_no,
                    "_repair_merge_error": getattr(merge_info, "error", "") or "",
                    "_repair_merge_fp": fp,
                    "_repair_base_tip": base_tip,
                    # 进入下一轮 repair：上一轮若曾写入「待 re-merge」标记则一并清除
                    # （fix-recovery-branch-anchor D3 清除点 2/4）。
                    "_repair_awaiting_remerge": False,
                },
            )
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"repair 轮次计数回写失败 '{spec_name}'（非阻塞）: {e}",
            )
        self._pm.logger.warning(
            "pm_engine",
            f"进入 repair 通道 '{spec_name}'（第 {round_no}/{MAX_REPAIR_ROUNDS_PER_FAILURE} 轮）"
            f"worktree={wt_path} branch={resolved_branch}",
        )
        t = threading.Thread(
            target=self._pm._run_repair_worker,
            args=(spec_name, wt_path, resolved_branch, merge_info),
            daemon=True,
            name=f"fenix-repair-{spec_name}",
        )
        t.start()

    def _claim_repair_site(self, spec_name: str, wt_path, branch: str) -> None:
        """认领 repair 现场（add-merge-back-repair-lane D4）。

        与 fast-track 复用同款 take 动作：认领时从 ``_legacy`` 摘出（防 sweeper
        宽限期按孤儿回收正在使用的现场）；在 ``_spec_locks`` 注册 repair 锁
        （防 repair 进行中重复派发）。worktree 已在三态解析时登记进活动集
        （``_active_worktrees``/``_wt_branches``），sweeper 不再豁免该目录。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 认领即摘出登记表（与 fast-track `_take_reusable_worktree` 同款 take）
        if hasattr(wm, "claim_legacy_for_repair"):
            wm.claim_legacy_for_repair(spec_name)
        elif spec_name in getattr(wm, "_legacy", {}):  # 兜底：直接摘出
            wm._legacy.pop(spec_name, None)
        if hasattr(wm, "_spec_locks"):
            wm._spec_locks.add(f"{spec_name}:repair")
        if branch:
            wm._wt_branches[str(wt_path)] = branch

    def _run_repair_worker(self, spec_name: str, wt_path, branch: str, merge_info) -> None:
        """repair worker：派发 repair agent → re-merge-back → 状态推进。

        在守护线程内同步执行（与 implementer worker 同线程语义）。repair agent
        在实现分支一侧把 main 合入分支并解决冲突、commit；成功后框架对该分支
        重新执行 merge-back（分支已含 main 历史应快速前进）。

        熔断协同（D6）：re-merge-back 再失败时 ``_merge_fp``/``_merge_streak``
        连续累计（repair 轮不清零）；blocked 后不再派发 repair。
        """
        wm = self._pm.agent_runner.worktree_manager
        try:
            repair_ok = False
            repair_error = ""
            r = None
            try:
                r = self._pm.agent_runner.run_repair(
                    spec_name,
                    wt_path,
                    conflict_summary=self._repair_conflict_summary(spec_name, merge_info),
                )
                # 读取 repair 结果文件（repair agent 在 worktree 写 .fenix-run-result.json）
                wt_result = Path(wt_path) / ".fenix-run-result.json"
                repair_ok = bool(r.success)
                if wt_result.exists():
                    try:
                        data = json.loads(wt_result.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            stamped = data.get("spec")
                            if stamped and stamped != spec_name:
                                repair_ok = False
                                repair_error = f"结果文件 spec 戳 '{stamped}' 与 '{spec_name}' 不符"
                            elif data.get("status") == "error":
                                repair_ok = False
                                repair_error = data.get("error") or "repair agent 显式报告失败"
                    except (json.JSONDecodeError, OSError) as e:
                        repair_ok = False
                        repair_error = f"repair 结果文件解析失败: {e}"
            except Exception as e:
                repair_ok = False
                repair_error = str(e)
                self._pm.logger.error(
                    "pm_engine",
                    f"repair agent 派发异常 '{spec_name}': {e}",
                )

            # ── 人工取消 hold-state（add-run-cancel D4，repair worker）──
            # repair run 被取消：spec 保持原状（implementing），只写 error，
            # 不动 _retry_count/_merge_fp/_merge_streak、不入队重派。
            if getattr(r, "cancelled", False):
                r_err = getattr(r, "error", None) or repair_error or ""
                cancelled_err = f"run 被人工取消：{r_err}" if r_err else "run 被人工取消"
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair run 被人工取消 — hold-state '{spec_name}'"
                    f"（保持原状）: {cancelled_err}",
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

            # ── repair git 事实复核（fix-repair-commit-enforcement D1/D2）──
            # repair agent 声明 success 只是「声明」，worker 在此以分支 git 事实
            # 独立验证「repair 确实被落地」：① 分支 tip 相对派发前基准前进（至少
            # 一个新提交）；② worktree 内无未解决冲突；③ 不处于未完成 merge。
            # 任一不满足即判 repair 未完成，repair_error 携带具体事实注入
            # fallback 重派上下文（不再以笼统「merge-back failed」重派）。
            if repair_ok:
                facts_ok, fact_err = self._pm._check_repair_commit_facts(spec_name, wt_path, branch)
                if not facts_ok:
                    repair_ok = False
                    repair_error = fact_err
                    self._pm.logger.error(
                        "pm_engine",
                        f"repair git 事实复核未通过 '{spec_name}'：{fact_err}",
                    )

            if not repair_ok:
                # repair 失败/超时/显式失败 → 回退 fallback 全新重派（原分支按既有
                # 清扫策略处理：登记遗产供后继 run 参考）
                self._fallback_after_repair(
                    spec_name,
                    branch,
                    repair_error,
                    merge_error=getattr(merge_info, "error", "") or "",
                )
                return

            # repair 成功：对分支重新执行 merge-back（分支已含 main 历史）
            self._pm._reconcile_impl_budget(spec_name)
            # ── 锚点提前落盘（fix-recovery-branch-anchor D1）─────────
            # repair run 终态成功后、re-merge-back 之前写入 branch/implementer_run，
            # 使恢复链在「repair 成功待 re-merge」窗口内可命中实现分支。
            # 同时写入 _repair_awaiting_remerge 标记（D3），标识「仅剩合并」。
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "branch": branch,
                    "implementer_run": getattr(r, "run_id", None) or None,
                    "_repair_awaiting_remerge": True,
                },
            )
            self._pm.logger.info(
                "pm_engine",
                f"锚点已提前落盘（repair）'{spec_name}': "
                f"branch={branch}, _repair_awaiting_remerge=True",
            )
            remerge_info = wm.merge_back_from_branch(branch)
            remerge_ok, remerge_error = remerge_info

            if remerge_ok:
                # 链成功：回收 repair worktree，推进 implemented
                # ── 顺序修复（fix-recovery-branch-anchor D1 1.4）───────
                # update_spec(branch=...) MUST 先于 wm.cleanup 执行
                # （先写锚点载体、后删 worktree，happy path 上不留窗口）。
                # fix-observability-gaps 2.2：repair re-merge 成功 → implemented
                # 合并收尾 ready 态兜底（evo-spec-concurrency-flight-guard D3）：
                # status=ready（评审收尾竞态回退残留）时先补记 ready→implementing，
                # 再推进 implemented（消除 ready→implemented 非法转移 ERROR）。
                self._pm._merge_ready_fallback(
                    spec_name,
                    getattr(r, "run_id", None) or None,
                    "repair",
                    branch,
                )
                self._pm.state_machine.transition(
                    spec_name, "implemented",
                    trigger_run_id=getattr(r, "run_id", None) or None,
                    agent_type="repair", channel="auto",
                )
                self._pm.state_machine.update_spec(
                    spec_name,
                    {
                        "implementer_run": getattr(r, "run_id", None) or None,
                        "branch": branch,
                        "error": None,
                        "_retry_count": 0,
                        "_merge_fp": None,
                        "_merge_streak": 0,
                        "_repair_round": 0,
                        "_repair_merge_error": None,
                        # repair 链成功收口：基准 tip 随 _repair_round 一并清零
                        # （fix-repair-commit-enforcement 1.4），避免 stale 基准残留。
                        "_repair_base_tip": None,
                        "_repair_awaiting_remerge": False,
                        **self._pm._clear_dispatch_conflict(spec_name),
                    },
                )
                # 锚点已落盘（branch/implementer_run 已写入 STATE），此时才清理
                # repair worktree 载体（1.4 顺序修复：先写锚点、后删载体）。
                try:
                    self._pm.agent_runner._v2_stop_for_worktree(wt_path)
                except Exception:
                    pass
                try:
                    wm.cleanup(wt_path, success=True)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"repair worktree 清理失败 '{spec_name}'（非阻塞）: {e}",
                    )
                try:
                    self._pm._sync_task_progress(spec_name)
                except Exception as e:
                    self._pm.logger.warning(
                        "pm_engine",
                        f"repair 任务进度回写失败 '{spec_name}'（非阻塞）: {e}",
                    )
                try:
                    wm.consume_legacy(spec_name)
                except Exception:
                    pass
                self._enqueue_front(spec_name, "verifier")
                self._pm.logger.info(
                    "pm_engine",
                    f"repair 链成功：'{spec_name}' re-merge-back 完成 → implemented",
                )
                return

            # re-merge-back 再失败：与首次 merge 失败同路径处理（熔断计数连续累计），
            # repair 轮不清零 _merge_fp/_merge_streak（spec-merge-circuit-breaker）。
            self._pm._handle_remerge_failure(spec_name, remerge_info, branch)

        except Exception as e:
            self._pm.logger.error(
                "pm_engine",
                f"repair worker 异常 '{spec_name}': {e}",
            )
            # verify-process-lifecycle（D3 dispatch 兜底）：hand-off 边界内异常
            # 时收割 repair 载体 worktree 的 dev-server 注册条目（run_repair 的
            # runner 收割因 repair 属 handed_off 而跳过）。幂等，双调无害。
            try:
                self._pm.agent_runner._v2_stop_for_worktree(Path(wt_path))
            except Exception:
                pass
            self._fallback_after_repair(
                spec_name,
                branch,
                str(e),
                merge_error=getattr(merge_info, "error", "") or "",
            )
        finally:
            # 释放 repair 锁（_spec_locks 中 {spec}:repair 条目）
            try:
                wm._spec_locks.discard(f"{spec_name}:repair")
            except Exception:
                pass
            self._pm._process_queue()

    # ── repair git 事实复核（fix-repair-commit-enforcement D1/D2/D5）──────

    def _check_repair_commit_facts(self, spec_name: str, wt_path, branch: str) -> tuple[bool, str]:
        """repair git 事实复核：分支 tip 前进 + 无冲突残留 + 无未完成 merge。

        repair agent 的 success 是「声明」，worker 在此以分支 git 事实独立验证
        「repair 确实被落地」。复核逻辑为**可测试的纯组合判定**（D5）：只读
        查询委托 worktree_manager（``branch_tip`` / ``repair_site_facts``），
        组合判定在此方法内完成——单测可注入 mock worktree_manager 覆盖四态
        （tip 未前进 / 有未合并条目 / 有 MERGE_HEAD / 全 ok），沿用
        ``test_mergeback_repair_lane.py`` 的临时仓库夹具风格。

        判定规则（任一不满足 → 判未完成）：
        - ``repair_site_facts.unmerged`` 非空 → 未解决冲突残留；
        - ``repair_site_facts.merge_head`` 为 True → 仍处于未完成 merge；
        - 基准 ``_repair_base_tip`` 可判时，``branch_tip(branch) != base_tip``
          → 分支 tip 未前进（可能只暂存未提交）。
        ``_repair_base_tip`` 缺失（老状态迁移或查询失败）时跳过 tip 前进
        校验，仅查冲突残留 + MERGE_HEAD（保守放行，与现状一致，不引入新
        假阴性硬门——修复后只读层的失败也按同样保守原则处理）。

        Returns:
            ``(ok, error_text)``：ok=True 表示复核通过；ok=False 时
            error_text 携带可诊断事实（如 tip SHA、未合并条目计数、MERGE_HEAD
            有无），供 ``_fallback_after_repair`` 注入下一轮重派上下文。
        """
        wm = self._pm.agent_runner.worktree_manager
        # ── 查询侧（D2：只读，不新增 worktree 写操作）──
        try:
            facts = wm.repair_site_facts(wt_path)
        except Exception as e:
            facts = {}
            self._pm.logger.warning(
                "pm_engine",
                f"repair git 事实查询异常（fail-open 防误拦）'{spec_name}': {e}",
            )
        unmerged = list(facts.get("unmerged") or [])
        merge_head = bool(facts.get("merge_head"))
        # ── 冲突残留 / MERGE_HEAD 是硬事实，任一出问题即判未完成 ──
        if unmerged or merge_head:
            parts = []
            if unmerged:
                shown = ", ".join(unmerged[:3])
                tail = "…" if len(unmerged) > 3 else ""
                parts.append(f"未解决冲突残留 {len(unmerged)} 个文件" f"（{shown}{tail}）")
            if merge_head:
                parts.append("存在未完成 merge（MERGE_HEAD）")
            return False, f"repair git 事实复核未通过：{'; '.join(parts)}"
        # ── tip 前进校验（基准可判时，D2）──
        try:
            base_tip = (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_base_tip")
        except Exception:
            base_tip = None
        if base_tip:
            now_tip = None
            try:
                now_tip = wm.branch_tip(branch)
            except Exception as e:
                self._pm.logger.warning(
                    "pm_engine",
                    f"repair 分支 tip 查询异常（按未前进判未完成，保守）" f"'{spec_name}': {e}",
                )
            if not now_tip or now_tip == base_tip:
                base_short = base_tip[:12] if base_tip else "N/A"
                now_short = now_tip[:12] if now_tip else "N/A"
                return False, (
                    f"repair git 事实复核未通过：分支 tip 未前进"
                    f"（base={base_short}, now={now_short}）"
                    f"——repair 声称成功但分支无新提交，可能只暂存未提交"
                )
        return True, ""

    def _handle_remerge_failure(self, spec_name: str, remerge_info, branch: str) -> None:
        """repair 后的 re-merge-back 失败：熔断 → repair 下一轮 → fallback。

        与首次 merge-back 失败同判定基准（fp/streak 连续累计，repair 不重置），
        轮次超过上限回退 fallback。不重复 testing/implemented 保护检查——
        repair 链内 spec 保持 implementing，无在飞 tester。
        """
        merge_error = getattr(remerge_info, "error", "") or str(remerge_info)
        # ── WIP 重叠闸门阻塞旁路（evo-merge-back-wip-overlap-gate D3）──
        # repair 后 re-merge-back 同样可能被主树 WIP 重叠闸门阻塞（repair 期间
        # 主树出现新 WIP 与分支改动重叠）：阻塞是前置拦截而非 merge 失败，主树
        # 未被 stash/merge/pop 触碰——不经 _merge_fp/_merge_streak 记账、不
        # blocked、不进 repair 轮，spec 保持 in-flight，仅直发告警等待人工处置。
        if getattr(remerge_info, "wip_gate_blocked", False):
            self._report_mergeback_wip_overlap(spec_name, remerge_info, branch, merge_error)
            return
        spec_entry = self._pm.state_machine.read_one(spec_name) or {}
        fp = self._pm._merge_fingerprint(merge_error)
        prev_fp = spec_entry.get("_merge_fp")
        try:
            prev_streak = int(spec_entry.get("_merge_streak", 0) or 0)
        except (TypeError, ValueError):
            prev_streak = 0
        streak = prev_streak + 1 if prev_fp == fp else 1
        final_error = f"Merge-back failed (fp={fp}): {merge_error}"
        breaker_threshold = self._pm._get_config("agents.merge_breaker_threshold", 2)
        if streak >= breaker_threshold:
            # fix-observability-gaps 2.2：repair re-merge 熔断 blocked（自动降级路径）
            self._pm.state_machine.transition(
                spec_name, "blocked",
                trigger_run_id=None, agent_type="repair", channel="auto",
            )
            self._pm.state_machine.update_spec(
                spec_name,
                {
                    "error": final_error,
                    "_merge_fp": fp,
                    "_merge_streak": streak,
                    "_retry_count": 0,
                    # 熔断封顶时一并清除「待 re-merge」标记（D3）：blocked
                    # 状态下无论 admin 如何处置（unfreeze/重置），该标记不应
                    # 残留导致后续启动误走 re-merge 路径。
                    "_repair_awaiting_remerge": False,
                },
            )
            self._pm.logger.error(
                "pm_engine",
                f"Circuit breaker tripped after repair for '{spec_name}' (fp={fp}) "
                f"— spec blocked (repair 不绕过熔断)",
            )
            return
        if self._pm._should_enter_repair(spec_name, remerge_info, streak, breaker_threshold):
            self._pm._dispatch_repair_lane(
                spec_name,
                remerge_info,
                branch,
                fp=fp,
                streak=streak,
            )
            return
        # 未触发熔断且不可 repair → fallback 全新重派
        self._fallback_after_repair(spec_name, branch, merge_error)

    def _fallback_after_repair(
        self, spec_name: str, branch: str | None, repair_error: str, merge_error: str = ""
    ) -> None:
        """repair 链失败回退：全新重派 implementer，prompt 注入 merge 失败上下文。

        - 清理 repair worktree（保留分支：按既有清扫策略登记遗产，供后继 run 参考）；
        - ``_repair_round`` 归零：fallback 后新 implementer 的 merge 失败开启新链
          （design D6）；
        - 状态置 ready + error（既有 _prev_error_section 会把它注入新 implementer
          prompt，即「prompt 注入当次 merge 失败上下文」）；
        - ``_merge_fp``/``_merge_streak`` **不清零**：repair 失败后 fallback 重派
          引发的 merge-back 失败与前序失败连续累计（熔断协同）。
        """
        wm = self._pm.agent_runner.worktree_manager
        # 清理 repair worktree（若有现场）：分支按既有清扫策略登记遗产
        try:
            if branch and wm.branch_exists(branch):
                wt_path = wm.find_worktree_path(branch)
                if wt_path is not None and wt_path.exists():
                    try:
                        self._pm.agent_runner._v2_stop_for_worktree(wt_path)
                    except Exception:
                        pass
                    wm.cleanup(wt_path, success=True)
                # 成功收工清理后仅分支留存（已解决的冲突成果随分支保留），
                # 登记为仅分支遗产供后继 run 参考收编（不丢失修复工作）
                wm.register_legacy(spec_name, None, branch)
            elif branch:
                wm.register_legacy(spec_name, None, branch)
        except Exception as e:
            self._pm.logger.warning(
                "pm_engine",
                f"fallback 清理 repair worktree 失败 '{spec_name}'（非阻塞）: {e}",
            )
        # 失败链收尾：归零轮次，回退 fallback
        try:
            prev_retries = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_retry_count", 0) or 0
            )
        except (TypeError, ValueError):
            prev_retries = 0
        retries = prev_retries + 1
        base_error = merge_error or "merge-back failed"
        if repair_error:
            full_error = (
                f"repair 失败（{repair_error[:300]}）→ 回退全新重派。"
                f"原 merge 失败上下文：{base_error[:600]}"
            )
        else:
            full_error = base_error
        max_r = self._pm._get_config("agents.max_retries", 3)
        updates: dict = {
            "status": "ready",
            "error": full_error,
            "_repair_round": 0,
            "_repair_merge_error": None,
            # 基准 tip 随 fallback 一并清零（fix-repair-commit-enforcement 2.2）：
            # 复核失败 / remerge 再失败 / worker 异常三条 fallback 路径都不再续
            # repair 链，清空避免 STATE 残留 stale 基准 tip 孤儿字段（新 implementer
            # 的 merge 失败开启新链，与 _repair_round 归零同族）。
            "_repair_base_tip": None,
            # 清除待 re-merge 标记（fix-recovery-branch-anchor D3）：fallback
            # 重派后由新 implementer 正常收口，不得再被恢复链当「待 re-merge」处理。
            # （fix-fasttrack-recovery-resume 4.1 出口矩阵·例外）此清除**不涉及**
            # branch/implementer_run（二者保持原值，不新增清锚点），也**不消费**
            # _recovery_resume（恢复标记在 dispatch 入口一次性消费，此处不触碰）。
            "_repair_awaiting_remerge": False,
            "_retry_count": retries,
        }
        if retries >= max_r:
            updates["status"] = "blocked"
            updates["error"] = (
                f"实现尝试连续 {max_r} 次失败（含 repair 通道）— 已 blocked，"
                f"需人工检查。最近失败：{full_error[:400]}"
            )
        self._pm.state_machine.update_spec(spec_name, updates)
        self._pm.logger.error(
            "pm_engine",
            f"repair 链回退 fallback '{spec_name}'：{full_error[:200]}",
        )
        if updates["status"] == "ready":
            # 回退通道按 spec 实现模式选择（fast-track 接入 repair lane 配套）：
            # fast-track spec 的 repair 失败回 fast-track 重派，不硬派 implementer
            try:
                from core.spec_mode import read_spec_mode

                channel = (
                    "fast-track"
                    if read_spec_mode(self._pm.project_root, spec_name) == "fast-track"
                    else "implementer"
                )
            except Exception:
                channel = "implementer"
            self._enqueue_front(spec_name, channel)

    def _repair_conflict_summary(self, spec_name: str, merge_info) -> dict:
        """构造 repair prompt 的冲突摘要（D5：spec 身份 + 冲突清单 + 方向说明）。

        不含原 worktree 地址类间接情报（agent 即在现场，冲突状态自查）。
        """
        try:
            repair_round = int(
                (self._pm.state_machine.read_one(spec_name) or {}).get("_repair_round", 0) or 0
            )
        except (TypeError, ValueError):
            repair_round = 0
        return {
            "spec": spec_name,
            "merge_error": getattr(merge_info, "error", "") or "",
            "conflict_paths": list(getattr(merge_info, "conflict_paths", []) or []),
            "has_semantic_conflict": bool(getattr(merge_info, "has_semantic_conflict", False)),
            "repair_round": repair_round,
        }
