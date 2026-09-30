"""stale_sweep.py — G7 陈旧清扫（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 3 个方法，原样搬移为 mixin（方法体零改动）。
StateParser 延迟导入（方法体内已有 from core.state_machine import StateParser）。
"""

from __future__ import annotations

import shutil
import subprocess

from typing import Optional


class G7StaleSweepMixin:
    """G7 陈旧清扫（design D1 表 A G7）。"""


    def cleanup_stale_worktrees(self):
        """启动时全量清理孤儿 worktree：删除所有不在活动集合的目录 + 对应分支 + prune。

        与 shutdown 的 cleanup_orphans 互补：后者清活动集合内残留，本方法清
        上次异常退出遗留的孤儿。失败记 WARNING，不阻塞 daemon 启动。

        锁治理（improve-run-lifecycle-governance D4）：daemon 重启后仍可能有
        孤儿 attempt 进程在某个 worktree 里继续干活，删除其目录会让进程当场
        失去工作区。凡进程表仍能扫到指向该目录的进程，跳过清理并把锁重建
        回内存（保守：宁可不清理，不可误删在用的 worktree）。

        恢复重派遗产（add-recovery-legacy-check D2）：在册遗产 worktree 在宽限期内
        豁免清理（清扫器跳过），直到后继 run 成功 merge（consume_legacy）或宽限期
        超时（_reclaim_expired_legacy 兜底回收）。先触发一次宽限期兜底回收，再扫
        孤儿——宽限期内的遗产保持不动，宽限期外的遗产在此被兜底清除。
        """
        # 宽限期兜底回收：超时遗产由 sweeper 在此清除并记审计（设计 D2）。
        self._reclaim_expired_legacy()
        if not self.base_dir.exists():
            return
        # 在册遗产 worktree 名集合（宽限期内豁免）；实时监控避免与 _reclaim 竞争。
        # 迭代前物化快照（code-review item 19fc3ac92552）：register_legacy /
        # consume_legacy / keep_for_reuse 可在本清扫期间并发增删 _legacy，
        # 直接迭代 values() 会触发 "dictionary changed size during iteration"。
        legacy_names = {
            rec.get("worktree_name") for rec in list(self._legacy.values())
        }
        # 迭代前物化列表（sorted）：循环体内会删除 base_dir 的子目录
        # （git worktree remove / shutil.rmtree），边扫边删的目录遍历行为未定义，
        # 物化后删除不再作用于正在扫描的目录流。
        for wt_dir in sorted(self.base_dir.iterdir()):
            if not wt_dir.is_dir() or str(wt_dir) in self._active_worktrees:
                continue
            # 遗产豁免（add-recovery-legacy-check D2）：宽限期内不得清，留给后继 run 收编
            if wt_dir.name in legacy_names:
                self.logger.info(
                    "worktree_manager",
                    f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                    f"registered as recovery legacy (grace period)",
                )
                continue
            spec = self._spec_from_worktree_name(wt_dir.name)
            # 守卫与 spec 解析解耦（a3005d21763e）：活进程在场时无条件跳过清理，
            # 不依赖目录名能解析出 spec——repair- 等未识别前缀同样不得强删
            # （宁可不清理，不可误删在用的 worktree）。
            if self._worktree_has_live_process(wt_dir.name):
                if spec:
                    self._register_spec_locks(spec)
                    self.logger.warning(
                        "worktree_manager",
                        f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                        f"live process present, lock rebuilt for '{spec}'",
                    )
                else:
                    self.logger.warning(
                        "worktree_manager",
                        f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                        f"live process present, spec unparseable, conservative keep",
                    )
                continue
            if not spec:
                # spec 解析失败（repair- 等非 impl-/verify- 命名）保守跳过清理
                self.logger.warning(
                    "worktree_manager",
                    f"Skip stale worktree cleanup for '{wt_dir.name}' — "
                    f"unrecognized worktree naming, conservative keep",
                )
                continue
            self.logger.info("worktree_manager", f"Cleaning up stale worktree: {wt_dir}")
            # 无 agent 存活才走到这里：一并清掉残留测试子进程（dev-server 孤儿），
            # 避免删目录后留下 cwd 失效的永生进程
            self._kill_worktree_strays(wt_dir.name)
            try:
                branch = None
                br = subprocess.run(
                    ["git", "-C", str(wt_dir), "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if br.returncode == 0:
                    branch = br.stdout.strip()
                # 硬删前留档（lifecycle D2 同款约定）：本路径清的恰是上次异常
                # 退出遗留、最可能携带未提交现场的孤儿，删前必须快照留档，
                # 消灭「先删后查」取证盲区；失败降级 WARNING，不阻塞删除。
                self._snapshot_dirty_worktree(wt_dir, branch or None)
                res = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "worktree",
                        "remove",
                        str(wt_dir),
                        "--force",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if res.returncode != 0:
                    # remove 失败先留痕（5e6b1e0ed934）：与同函数分支删除失败
                    # / prune 失败同款 WARNING 口径——降级 rmtree 前记录 git 侧
                    # 拒绝原因，避免「删不掉也不留痕」的清扫观测盲区。
                    self.logger.warning(
                        "worktree_manager",
                        f"Stale worktree remove failed (non-blocking), "
                        f"falling back to rmtree: '{wt_dir}' — {res.stderr.strip()}",
                    )
                    shutil.rmtree(str(wt_dir), ignore_errors=True)
                    if wt_dir.exists():
                        # 降级删除也失败（目录被占用/权限异常等被 rmtree 吞掉）：
                        # 目录保留交下轮清扫，同样必须留痕。
                        self.logger.warning(
                            "worktree_manager",
                            f"Stale worktree rmtree fallback also failed "
                            f"(non-blocking): '{wt_dir}' kept for next sweep",
                        )
                    # 兜底删除后先清注册再删分支（69bc35ca6e4c）：rmtree 只删目录
                    # 不清 git 注册，陈旧注册仍 checkout 该分支会令下方 branch -D
                    # 被 git 拒绝——对齐 lifecycle.cleanup() 先 prune 再 -D 的次序；
                    # 收尾 prune 虽能清注册但目录已消失、分支无重试入口即残留。
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "worktree", "prune"],
                        capture_output=True,
                        timeout=10,
                    )
                if branch and branch != "HEAD":
                    # ── 分支在飞引用保护（fix-recovery-branch-anchor D6）──
                    # 删分支前检查该分支是否被 STATE 中在飞/待收口 spec 引用
                    # （implementing/implemented/testing/带 _recovery_resume 的
                    # ready），或按「完整 spec 名 + 分隔符边界」匹配任一
                    # implementing spec 的实现分支（覆盖锚点尚未落盘的场合）。
                    # 命中则保留分支（worktree 目录照常已删）并打 WARNING；
                    # STATE 不可解析时保守处理（保留分支 + WARNING），
                    # MUST NOT 按「无引用」放行删除。
                    kept, reason = self._branch_protected_by_state(branch)
                    if kept:
                        self.logger.warning(
                            "worktree_manager",
                            f"分支在飞引用保护：保留分支 '{branch}'（{reason}）— "
                            f"worktree 目录已清理，分支留待恢复/后继 run 收编",
                        )
                    else:
                        del_res = subprocess.run(
                            ["git", "-C", str(self.project_root), "branch", "-D", branch],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        if del_res.returncode != 0:
                            # 与同函数其它失败分支同款降级口径：删除失败不阻塞
                            # 清扫，但必须留 WARNING 线索，避免孤儿分支静默残留。
                            self.logger.warning(
                                "worktree_manager",
                                f"Stale branch delete failed (non-blocking): "
                                f"'{branch}' — {del_res.stderr.strip()}",
                            )
            except Exception as e:
                self.logger.warning("worktree_manager", f"Stale worktree cleanup failed: {e}")
        # 收尾 prune 同样不得抛穿（297556cff10d）：与循环体一致降级 WARNING，
        # 不阻塞 daemon 启动清扫。
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "worktree", "prune"],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Final worktree prune failed (non-blocking): {e}",
            )

    def _read_state_entries(self) -> Optional[dict]:
        """读取 STATE 全部 spec 条目（fix-recovery-branch-anchor D6）。

        经构造注入的 ``state_reader``（调用点 fenixd.py 传入 state_machine
        读取器）或就地解析 ``.fenix/STATE.md``（StateParser 无循环依赖）。
        读取/解析失败返回 None（区别于「无引用」的空 dict）——调用方据此
        保守处理（不清分支），MUST NOT 按「无引用」放行删除（tasks 6.3）。
        """
        if self._state_reader is not None:
            try:
                data = self._state_reader()
                if data is None:
                    return None
                if not isinstance(data, dict):
                    # 非 dict 形态（上游反序列化异常返回 list/str 等）属读取
                    # 异常，与 None 同路保守保留——归一为空 dict 会被按
                    # 「无引用」放行删分支，违背本函数的保守处理承诺。
                    self.logger.warning(
                        "worktree_manager",
                        f"state_reader 返回非 dict（{type(data).__name__}），"
                        f"按读取失败保守不清分支",
                    )
                    return None
                return data
            except Exception as e:
                self.logger.warning(
                    "worktree_manager",
                    f"state_reader 读取失败（保守不清分支）: {e}",
                )
                return None
        state_path = self.project_root / ".fenix" / "STATE.md"
        try:
            if not state_path.exists():
                return {}
            from core.state_machine import StateParser

            return StateParser.parse(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"STATE.md 解析失败（保守不清分支）: {e}",
            )
            return None

    def _branch_protected_by_state(self, branch: str) -> tuple:
        """分支是否被 STATE 在飞/待收口 spec 引用（fix-recovery-branch-anchor D6）。

        判据（D6）：
        (a) 分支等于任一 ``implementing``/``implemented``/``testing`` spec 的
            ``branch`` 字段值；或带 ``_recovery_resume`` 标记的 ``ready`` spec
            （§4.3 失败回落形态）的 ``branch`` 字段值；
        (b) 分支按「完整 spec 名 + 分隔符边界」全等匹配任一 ``implementing``
            spec 的实现分支（``<prefix>/<spec>-<ts>``，解析统一走
            ``_impl_branch_owned_by_spec``（queries G8），口径同
            D2/find_branches_by_spec：去前缀后末段纯数字时间戳、其前段与
            spec 名全等）——覆盖锚点尚未落盘的场合。

        Returns: ``(kept: bool, reason: str)``；STATE 不可解析时 ``(True, ...)``
        保守保留。
        """
        if not branch:
            return False, ""
        states = self._read_state_entries()
        if states is None:
            return True, "STATE 不可解析，保守保留"
        # (a) 字段值直接命中
        for sname, entry in states.items():
            status = entry.get("status", "")
            if status in ("implementing", "implemented", "testing", "ready"):
                if entry.get("branch") == branch:
                    # ready 仅当带 _recovery_resume 标记才算在飞引用
                    if status != "ready" or entry.get("_recovery_resume"):
                        return True, f"STATE 字段引用（{sname}: {status}）"
            # add-freeze-stop-inflight-agents 2.7：frozen + _frozen_hold 的 spec
            # 其 branch 属在飞引用（保留分支）。冻结终止的保留分支所在 spec 是
            # blocked（不在既有豁免集内），而 _reclaim_expired_legacy 不查本保护
            # 地 git branch -D（legacy_registry），宽限期仅 LEGACY_GRACE_SECONDS
            # = 120s——若不扩展，冻结终止后在解冻前重启 daemon（cleanup_stale
            # _worktrees 在 fenixd 启动路径）就可能删该分支，使「解冻后续做」
            # 降级为从零重派。entry.get("branch") 已在上方分支命中；此处按 status
            # 为 blocked 且 frozen+_frozen_hold 命中时直接判受保护。
            if status == "blocked" and entry.get("frozen") and entry.get("_frozen_hold"):
                if entry.get("branch") == branch:
                    return True, f"STATE 冻结保持引用（{sname}: blocked+frozen）"
        # (b) 命名空间口径：任一 implementing spec 的 <prefix>/<spec>-<ts>
        # 边界解析统一走 _impl_branch_owned_by_spec（9dd92d791918 三处内联
        # 归一：去前缀 + 末段纯数字时间戳 + 前段与 spec 名全等、verify- 结构
        # 判别剔除）；前缀并集 {"fenix", 配置值} 口径不变。
        prefixes = ("fenix", self._implement_branch_prefix or "fenix")
        for sname, entry in states.items():
            if entry.get("status") != "implementing":
                continue
            if not sname:
                continue
            if self._impl_branch_owned_by_spec(branch, sname, prefixes):
                return True, f"命名空间匹配 implementing spec '{sname}'"
        return False, ""
