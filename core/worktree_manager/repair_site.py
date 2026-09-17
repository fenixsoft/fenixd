"""repair_site.py — G9 repair/resume 站点认领（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 4 个方法，原样搬移为 mixin（方法体零改动）。
repair_site_facts/resolve_repair_site/resolve_resume_site 为只读查询，
claim_legacy_for_repair 为唯一有副作用的方法（修改 self._legacy）。
"""

from __future__ import annotations

import subprocess

from typing import Optional

from core.worktree_manager import (  # noqa: E402
    WT_AVAILABLE,
    WT_UNAVAILABLE,
)

class G9RepairSiteMixin:
    def repair_site_facts(self, wt_path) -> dict:
        """repair 现场 git 事实（只读）：未解决冲突清单 + 是否残留未完成 merge。

        fix-repair-commit-enforcement D2：复核「冲突残留 + MERGE_HEAD」两项
        硬事实——
        - ``unmerged``：``git ls-files -u`` 输出的未合并路径清单（stage 1/2/3
          每冲突文件 1~3 行，按路径去重）；
        - ``merge_head``：worktree 内 ``git rev-parse -q --verify MERGE_HEAD``
          是否成功（MERGE_HEAD 是 worktree 级 git 文件，须以 wt_path 为 -C 目标）。

        查询异常时以保守值降级不抛穿（``unmerged=[]``、``merge_head=False``，
        与现状一致放行，不引入新假阴性硬门）。
        """
        facts = {"unmerged": [], "merge_head": False}
        if wt_path is None:
            return facts
        try:
            ls = subprocess.run(
                ["git", "-C", str(wt_path), "ls-files", "-u"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if ls.returncode == 0:
                paths = []
                for line in ls.stdout.splitlines():
                    # 行格式：<mode> <sha> <stage>\t<path>
                    if "\t" in line:
                        path = line.split("\t", 1)[1].strip()
                        if path and path not in paths:
                            paths.append(path)
                facts["unmerged"] = paths
        except (subprocess.TimeoutExpired, OSError):
            pass
        try:
            mh = subprocess.run(
                ["git", "-C", str(wt_path), "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            facts["merge_head"] = mh.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            pass
        return facts

    def resolve_repair_site(self, spec_name: str, branch: str):
        """解析 repair/恢复续做 分支载体三态（共用 is_available 单源查询，D5）。

        与 resolve_resume_site 同源（repair 换壳 / recovery 保留 续做）：
        - WT_AVAILABLE → 原地（git 注册的 worktree，登记活动集供 cleanup/sweeper 豁免）
        - WT_REBUILDABLE → 在既有分支上重建 worktree（checkout，create_worktree_on_branch）
        - WT_UNAVAILABLE → (None, None)，调用方降级清空重建

        Returns:
            - ``(wt_path, branch)``：载体可用——wt_path 为原 worktree（原地）
              或换壳新建的 worktree；branch 为实现分支名。
            - ``(None, None)``：载体不可用，调度层全新重派。
            产物自愈可静态判断本方法不涉 — 是否进入 repair 由调度层决定。
        """
        if not branch:
            return None, None
        avail = self.is_available(branch=branch)
        if avail == WT_UNAVAILABLE:
            return None, None
        if avail == WT_AVAILABLE:
            existing = self.find_worktree_path(branch)
            if existing is not None:
                self._active_worktrees.add(str(existing))
                self._wt_branches[str(existing)] = branch
                return existing, branch
        # WT_REBUILDABLE（或 WT_AVAILABLE 但 find_worktree_path 意外返回 None）
        wt = self.create_worktree_on_branch(spec_name, branch)
        if wt is None:
            return None, None
        return wt, branch

    def resolve_resume_site(self, spec_name: str, branch: str):
        """恢复续做载体三态解析（interrupt-recovery-preserve D4/D5）。

        与 resolve_repair_site 同源（共用 is_available 单源查询），语义相同：
        - WT_AVAILABLE → 原地续做（保留 node_modules/构建缓存/--resume 会话）
        - WT_REBUILDABLE → 在既有分支上重建 worktree（checkout，不从零新建分支）
        - WT_UNAVAILABLE → (None, None)，调用方降级清空重建并 WARNING

        与 resolve_repair_site 的区分：命名恢复专用（可独立演进语义），当前
        行为等价。resume 续做在 dispatch 层通过 pre_wt_path 进入 _execute_agent，
        复用 implementer 的 prompt 构建与 claude --resume 断点续跑。
        """
        return self.resolve_repair_site(spec_name, branch)

    def claim_legacy_for_repair(self, spec_name: str) -> Optional[dict]:
        """repair 认领时摘出 _legacy 登记（add-merge-back-repair-lane D4）。

        与 fast-track ``_take_reusable_worktree`` 同款 take 动作：认领即从
        ``_legacy`` 登记表摘出，sweeper 宽限期超时后不再回收该现场（遗产豁免
        只在登记期内生效）。物理回收（目录/分支）由 repair 链收尾决定——
        成功路径 consume_legacy，fallback 由调度层按既有清扫策略处理。

        Returns: 被摘出的遗产记录 dict（结构同 register_legacy），无则 None。
        """
        rec = self._legacy.pop(spec_name, None)
        if rec:
            self.logger.info(
                "worktree_manager",
                f"Repair claimed legacy for '{spec_name}': "
                f"worktree={rec.get('path')} branch={rec.get('branch')}",
            )
        return rec

