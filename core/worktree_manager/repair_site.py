"""repair_site.py — G9 repair/resume 站点认领（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 4 个方法，原样搬移为 mixin（方法体零改动）。
仅 repair_site_facts 是纯只读查询；resolve_repair_site/resolve_resume_site
属「查询 + 登记/重建」副作用方法（WT_AVAILABLE 时向 _active_worktrees/
_wt_branches 写入登记，WT_REBUILDABLE 时经 create_worktree_on_branch
新建 worktree）；claim_legacy_for_repair 有副作用（修改 self._legacy）。
"""

from __future__ import annotations

import subprocess
import time

from typing import Optional

from core.worktree_manager import (  # noqa: E402
    WT_AVAILABLE,
    WT_UNAVAILABLE,
)
from core.worktree_manager.constants import LEGACY_GRACE_SECONDS  # noqa: E402


class G9RepairSiteMixin:
    """G9 repair/resume 站点认领（design D1 表 A G9）；repair_site_facts 纯只读，其余方法带登记/重建副作用。"""

    def repair_site_facts(self, wt_path) -> dict:
        """repair 现场 git 事实（只读）：未解决冲突清单 + 是否残留未完成 merge。

        fix-repair-commit-enforcement D2：复核「冲突残留 + MERGE_HEAD」两项
        硬事实——
        - ``unmerged``：``git ls-files -u -z`` 输出的未合并路径清单（stage
          1/2/3 每冲突文件 1~3 条记录，按路径去重）；
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
                ["git", "-C", str(wt_path), "ls-files", "-u", "-z"],
                capture_output=True,
                text=True,
                # -z 记录以 NUL 分隔且不做路径引用（code-review item
                # fe265f8ce9c5）：文本模式默认按 core.quotePath 把「异常字符」
                # 路径做 C 风格引用——中文等非 ASCII 路径输出为带双引号的八进制
                # 转义（如 "\346\226\207.txt"），含反斜杠/双引号的路径也会被加
                # 引号转义，按行切分取到的将是转义形态而非真实路径（该引用发生
                # 在编码层之前，仅显式 UTF-8 解码达成不了中文可读）。-z 的路径
                # 字段即真实字节（记录终止符改为 NUL，字段内仍以 \t 分隔），
                # 按记录切分后路径与磁盘实际路径一致。
                # 显式 UTF-8：text=True 缺省按 locale 解码，非 UTF-8 locale
                # 下读中文等非 ASCII 未合并路径抛 UnicodeDecodeError（ValueError
                # 子类，逃逸下方 except，对齐 session_routes._list_project_files 同款惯例）
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if ls.returncode == 0:
                paths = []
                for record in ls.stdout.split("\x00"):
                    # 记录格式：<mode> <sha> <stage>\t<path>（路径不经引用，
                    # 不做 strip——真实路径允许首尾空格）
                    if "\t" in record:
                        path = record.split("\t", 1)[1]
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
                encoding="utf-8",
                errors="replace",
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
        # code-review item f7623a814c4d：先查一次注册路径，命中即以
        # known_registered 带入 is_available 复用同一次 ``git worktree list``
        # 结果——AVAILABLE 分支不再二次 find_worktree_path 子进程（对齐
        # e4d825bb770e 的重复子进程治理先例）；未命中不带入，保持原单源
        # 查询语义（is_available 内部自行判定）。
        existing = self.find_worktree_path(branch)
        if existing is not None:
            avail = self.is_available(branch=branch, known_registered=existing)
        else:
            avail = self.is_available(branch=branch)
        if avail == WT_UNAVAILABLE:
            return None, None
        if avail == WT_AVAILABLE:
            # known_registered 即三态判定所用的 registered：AVAILABLE 成立时
            # 必非 None（注册在场且目录有效）；None 防御保留（两次查询间
            # 的竞态窗口）→ 走下方重建分支，与原「意外返回 None」同语义。
            if existing is not None:
                self._active_worktrees.add(str(existing))
                self._wt_branches[str(existing)] = branch
                return existing, branch
        # WT_REBUILDABLE（或 WT_AVAILABLE 但注册路径意外为 None）
        wt = self.create_worktree_on_branch(spec_name, branch)
        if wt is None:
            return None, None
        # 重建新目录必无 node_modules（queries 层明示 create_worktree_on_branch
        # 「仅登记活动集与分支映射，不 seed」）——与 lifecycle.create() 两条出口
        # 共用同一段幂等供给（code-review item cb5e28c5cb13）。_provision_worktree_deps
        # best-effort：失败仅 WARNING 降级，不阻塞 repair/resume 认领。
        self._provision_worktree_deps(wt)
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

        出册持锁 + pop 后复核（code-review item ae4697f9486e，对齐包内 _legacy
        变更的单一持锁纪律 fb49eca84deb/d6c32c0b63b6）：认领探测与 pop 之间该
        spec 可能被并发车道重新登记——pop 到宽限期内刚登记的新遗产时 setdefault
        放回出册位（清扫豁免保持完整）并返回 None，调度层降级走全新建树。
        """
        with self._spec_lock_th:
            rec = self._legacy.pop(spec_name, None)
            if rec is not None and (
                time.time() - rec.get("registered_at", 0) <= LEGACY_GRACE_SECONDS
            ):
                self._legacy.setdefault(spec_name, rec)
                rec = None
        if rec:
            self.logger.info(
                "worktree_manager",
                f"Repair claimed legacy for '{spec_name}': "
                f"worktree={rec.get('path')} branch={rec.get('branch')}",
            )
        return rec

