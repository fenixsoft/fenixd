"""dist_conflicts.py — G5 构建产物冲突/dist 重建（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 8 个方法，原样搬移为 mixin（方法体零改动）。
verify_contract 函数延迟导入（原方法体内已有延迟 import 模式）。
"""

from __future__ import annotations

import subprocess

from pathlib import Path

from core.worktree_manager import (  # noqa: E402
    DASHBOARD_STATIC_ROOT,
)


class G5DistConflictsMixin:
    """G5 构建产物冲突/dist 重建（design D1 表 A G5）。"""


    def _resolve_build_artifact_conflicts(self, branch: str) -> bool:
        """merge 冲突自愈：产物冲突无条件对齐 HEAD，语义冲突只看非产物路径。

        dist 冲突根治 A（2026-09-04 task-track 混合冲突连坐治理）。仅分支模式
        调用（merge 冲突态中）。判定与解决：
        1. ``git status --porcelain`` 收集 unmerged 条目（rename 形如
           ``old -> new`` 两侧路径都计入）；
        2. 无产物冲突路径 → False（纯语义冲突，交回调用方语义路径）；
        3. 产物路径**无条件对齐 HEAD**：HEAD 存在 → checkout HEAD -- p；
           HEAD 已删 → git rm。不再区分对齐分支版/主树版——merge 时 dist 永远
           以主树为准，分支重建的最终一致性由 merge 后 ``_rebuild_dist_after_merge``
           从合并后 src 确定性重建（dist 只是 src 的投影）；
        4. 收口：分支侧**干净 add** 的产物（非冲突新增，如新 hash chunk）一律
           移除，不复活旧构建物（原「布局被主树移动」场景的 stray 收口无条件化）；
        5. 全部冲突均为产物 → commit 完成 merge，return True；仍有语义冲突 →
           return False（**不 abort**——调用方语义路径统一 abort 并分类，
           此时收集到的冲突清单只含语义文件，失败指纹不再被 dist 噪声污染）。

        Returns: True 表示自愈完成且 merge 已提交。
        """
        if not branch:
            return False
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode != 0:
                return False

            def _collect_unmerged(status_text: str) -> list:
                paths: list = []
                for line in status_text.splitlines():
                    st = line[:2]
                    if not ("U" in st or st in ("AA", "DD", "AU", "UA", "DU", "UD")):
                        continue
                    path = line[3:].strip()
                    if " -> " in path:
                        paths.extend(p.strip() for p in path.split(" -> "))
                    else:
                        paths.append(path)
                return [p for p in paths if p]

            conflict_paths = _collect_unmerged(res.stdout)
            if not conflict_paths:
                return False
            # 产物判定走实例判定器（evo-merge-back-wip-artifact-scope D3）：
            # 项目配置的产物路径（如根级 dist/）也参与自愈判定。
            artifact_paths = self._artifacts.paths_in(conflict_paths)
            if not artifact_paths:
                return False

            # 产物路径无条件对齐 HEAD（HEAD 存在→取 HEAD 版；HEAD 已删→删除）
            head_artifacts = self._artifact_paths("HEAD")
            for p in artifact_paths:
                if p in head_artifacts:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "checkout", "HEAD", "--", p],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                else:
                    subprocess.run(
                        [
                            "git",
                            "-C",
                            str(self.project_root),
                            "rm",
                            "-f",
                            "--ignore-unmatch",
                            "--",
                            p,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
            # 收口：分支侧干净 add 的产物（非冲突新增）不复活——staged 产物中
            # HEAD 没有的一律移除（含旧路径双胞胎、对方重命名后的旧 hash chunk）
            staged = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=A",
                    "--",
                    DASHBOARD_STATIC_ROOT,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if staged.returncode == 0:
                strays = [
                    line
                    for line in staged.stdout.splitlines()
                    if self._artifacts.is_artifact(line) and line not in head_artifacts
                ]
                for p in strays:
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "rm", "-q", "-f", "--", p],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
            # 剩余冲突：非产物路径仍冲突 → 语义冲突，交回调用方（不 abort）
            res2 = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            remaining = _collect_unmerged(res2.stdout) if res2.returncode == 0 else []
            if remaining:
                self.logger.warning(
                    "worktree_manager",
                    f"Build-artifact conflicts aligned to HEAD "
                    f"({len(artifact_paths)} paths); semantic conflicts remain: "
                    f"{remaining[:5]}",
                )
                return False
            # 完成原 merge
            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--no-edit"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Build-artifact self-heal commit failed: "
                    f"{(commit.stderr or '').strip()[:200]}",
                )
                subprocess.run(
                    ["git", "-C", str(self.project_root), "merge", "--abort"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return False
            self.logger.warning(
                "worktree_manager",
                f"Build-artifact conflicts aligned to HEAD "
                f"({len(artifact_paths)} paths) — dist rebuilt from merged src "
                f"afterwards to restore cross-spec consistency",
            )
            return True
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Build-artifact self-heal error: {e}",
            )
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "merge", "--abort"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except Exception:
                pass
            return False

    def _run_dist_build(self) -> bool:
        """执行主树构建（.fenix/verify.yaml prepare 驱动，回退 npm run build）。

        构建什么从 verify.yaml 的 prepare 段读取——不预设目标为 nodejs 项目，
        步骤自带 cwd、每步受 PREPARE_STEP_TIMEOUT 约束；契约缺失时回退历史
        行为（DASHBOARD_STATIC_ROOT 下 npm run build）；契约存在但未声明
        prepare 视为「无构建步骤」，直接成功。
        供 merge 后确定性重建使用；测试通过 patch 本方法模拟构建产物/失败。
        """
        from core.verify_contract import (
            ensure_main_tree_deps,
            load_verify_contract,
            read_config_deps_mode,
            resolve_deps_mode,
            run_prepare_steps,
        )

        contract = load_verify_contract(self.project_root, self.logger)
        if contract is not None:
            if not contract.prepare:
                return True
            # add-main-tree-deps-provision：merge 后主树重建 dist 与验证同样
            # 可能缺 node_modules（主树只被 merge-back 写入、无人手工安装），
            # prepare 前按 cwd 集合预装依赖（mode 无 pm 配置通道，走
            # read_config_deps_mode + resolve_deps_mode 同源解析）。
            ensure_main_tree_deps(
                self.project_root,
                sorted({(s.cwd or ".") for s in contract.prepare}),
                mode=resolve_deps_mode(contract, read_config_deps_mode(self.project_root)),
                logger=self.logger,
            )
            err = run_prepare_steps(contract, self.project_root)
            if err:
                self.logger.warning(
                    "worktree_manager",
                    f"dist rebuild prepare 失败: {err}",
                )
                return False
            return True
        static_dir = self.project_root / DASHBOARD_STATIC_ROOT
        if not (static_dir / "package.json").exists():
            self.logger.warning(
                "worktree_manager",
                f"dist rebuild skipped: no package.json under {DASHBOARD_STATIC_ROOT}",
            )
            return False
        try:
            r = subprocess.run(
                ["npm", "run", "build"],
                cwd=str(static_dir),
                capture_output=True,
                text=True,
                timeout=600,
            )
            return r.returncode == 0
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"dist build invocation failed: {e}",
            )
            return False

    def _rebuild_dist_after_merge(self) -> None:
        """merge 后从合并后 src 确定性重建主树产物（dist 冲突根治 B）。

        dist 已不入库（2026-09-04 决策）：本方法只负责刷新主树工作区产物，
        供常驻 dashboard（实时读盘）立即呈现合并后 UI。git 侧语义：dist 被
        ignore，重建产物不再 amend 进提交（git add 无可暂存）；历史分支仍
        携带跟踪版 dist 时，产物冲突无条件对齐 HEAD（=删除），merge 后重建
        即恢复工作区版。构建内容从 .fenix/verify.yaml prepare 读取（契约
        驱动，见 _run_dist_build）。
        仅当 merge 提交（HEAD^1..HEAD）触碰 static 根下非产物路径时重建。
        失败时保留现有工作区产物并告警——不回滚 merge、不抛异常（merge
        本身的成功语义不被重建失败否定）。
        """
        try:
            diff = subprocess.run(
                ["git", "-C", str(self.project_root), "diff", "--name-only", "HEAD^1", "HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if diff.returncode != 0:
                return
            changed = [l.strip() for l in diff.stdout.splitlines() if l.strip()]
            # 首个子句以 DASHBOARD_STATIC_ROOT 限定重建作用域（Non-Goals：不改
            # 重建触发面）；产物判定走实例判定器（evo-merge-back-wip-artifact-scope
            # D3，与预演闸/自愈同一口径）。
            src_touched = any(
                p.startswith(DASHBOARD_STATIC_ROOT) and not self._artifacts.is_artifact(p)
                for p in changed
            )
            if not src_touched:
                return
            if not self._run_dist_build():
                self.logger.error(
                    "worktree_manager",
                    "dist rebuild failed after merge — keeping committed dist "
                    "(may lag merged src); run `npm run build` in "
                    f"{DASHBOARD_STATIC_ROOT} manually",
                )
                return
            subprocess.run(
                ["git", "-C", str(self.project_root), "add", "-A", "--", DASHBOARD_STATIC_ROOT],
                capture_output=True,
                text=True,
                timeout=60,
            )
            staged = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "status",
                    "--porcelain",
                    "--",
                    DASHBOARD_STATIC_ROOT,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if not staged.stdout.strip():
                return  # 重建结果与提交版一致，无需 amend
            amend = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "--amend", "--no-edit"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if amend.returncode != 0:
                # 恢复干净：unstage + dist 回到提交版，不让脏树阻塞后续 merge
                subprocess.run(
                    ["git", "-C", str(self.project_root), "reset", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(self.project_root),
                        "checkout",
                        "HEAD",
                        "--",
                        DASHBOARD_STATIC_ROOT,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.logger.error(
                    "worktree_manager",
                    f"dist rebuild amend failed: " f"{(amend.stderr or '').strip()[:200]}",
                )
                return
            self.logger.info(
                "worktree_manager",
                "dist rebuilt from merged src（不入库；常驻 dashboard 读盘即最新）",
            )
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.error(
                "worktree_manager",
                f"dist rebuild after merge failed unexpectedly: {e}",
            )

    def _artifact_paths(self, rev: str) -> set:
        """列出 <rev> 中 static 根下全部构建产物路径（按目录层次容错判定）。"""
        ls = subprocess.run(
            [
                "git",
                "-C",
                str(self.project_root),
                "ls-tree",
                "-r",
                "--name-only",
                rev,
                DASHBOARD_STATIC_ROOT,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ls.returncode != 0:
            return set()
        # 产物判定走实例判定器（evo-merge-back-wip-artifact-scope D3），与其余
        # 调用点同一口径。查询范围仍限 DASHBOARD_STATIC_ROOT（既有语义）。
        return {
            line
            for line in ls.stdout.splitlines()
            if self._artifacts.is_artifact(line)
        }

    def _parse_merge_blockers(self, error: str) -> list:
        """从 git 的 'local changes would be overwritten by merge' 错误中解析路径。

        错误形如::

            error: Your local changes to the following files would be overwritten by merge:
            \t<path1>
            \t<path2>
            Please commit your changes or stash them before you merge.

        无法解析或不含该错误时返回空列表。
        """
        marker = "would be overwritten by merge:"
        idx = error.find(marker)
        if idx == -1:
            return []
        paths = []
        for line in error[idx + len(marker) :].splitlines():
            if not line.strip():
                if paths:
                    break  # 空行＝路径段结束
                continue
            text = line.strip().lstrip("\t").strip()
            if not text or text.startswith(("Please commit", "Aborting", "error:", "Merge with")):
                break
            paths.append(text)
        return paths

    def _list_unmerged_files(self) -> list:
        """枚举主树中全部 UU 未合并文件（merge 冲突 / stash pop 冲突残留）。

        ``git ls-files -u`` 对每个冲突文件输出 1~3 行（stage 1/2/3），行末为路径；
        去重后返回排序后的路径列表。命令失败返回空列表（不阻塞自愈）。
        """
        try:
            ls = subprocess.run(
                ["git", "-C", str(self.project_root), "ls-files", "-u"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        if ls.returncode != 0 or not ls.stdout.strip():
            return []
        paths: set = set()
        for line in ls.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # 行格式：<mode> <hash> <stage>\t<path>
            tab = line.split("\t", 1)
            if len(tab) == 2 and tab[1].strip():
                paths.add(tab[1].strip())
        return sorted(paths)

    def _collect_conflict_paths(self) -> list:
        """枚举主树 merge 冲突挂起态的冲突路径（自愈判定与 repair 分类共用）。

        add-merge-back-repair-lane D1：与 ``_resolve_build_artifact_conflicts``
        同一采集口径（``git status --porcelain`` 中 unmerged 状态码的路径，
        rename ``old -> new`` 双胞胎两侧都计入），确保「产物自愈已尝试仍失败」的
        冲突分类与实际自愈判定一致。非冲突态/命令失败返回空列表。
        """
        try:
            res = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return []
        if res.returncode != 0:
            return []
        conflict_paths: list = []
        for line in res.stdout.splitlines():
            st = line[:2]
            if not ("U" in st or st in ("AA", "DD", "AU", "UA", "DU", "UD")):
                continue
            path = line[3:].strip()
            if " -> " in path:
                conflict_paths.extend(p.strip() for p in path.split(" -> "))
            else:
                conflict_paths.append(path)
        return [p for p in conflict_paths if p]

    def _heal_unmerged_files(self, conflict_files: list) -> None:
        """对 UU 文件执行自愈：丢弃 stash 版本、保留 merge 结果、清空 index。

        每个 UU 文件处于 unmerged 状态，普通 ``git checkout HEAD -- <file>`` 会报
        "path is unmerged"，因此用 ``-f`` 强制从 HEAD 还原（清空 stage 1/2/3、工作区
        覆盖为已 merge 的实现）。随后 ``git reset`` 兜底清空 index 中任何残留的 staged
        冲突条目，使主树回到干净可写状态。
        """
        for f in conflict_files:
            try:
                subprocess.run(
                    ["git", "-C", str(self.project_root), "checkout", "-f", "HEAD", "--", f],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired:
                self.logger.warning(
                    "worktree_manager",
                    f"checkout -f HEAD -- {f} timed out during self-heal",
                )
        # 清空 index 残留的 staged 冲突条目（mixed reset，不动工作区）
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "reset"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "worktree_manager",
                "git reset timed out during stash-pop self-heal",
            )
