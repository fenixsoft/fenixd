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


def _collect_unmerged_paths(status_text: str) -> list:
    """从 ``git status --porcelain`` 输出采集 unmerged 冲突路径（唯一采集口径）。

    porcelain 状态码过滤（含 U 的双字符码与 AA/DD/AU/UA/DU/UD）+ rename
    ``old -> new`` 双胞胎拆分（两侧路径都计入）。``_resolve_build_artifact_conflicts``
    的产物自愈判定与 ``_collect_conflict_paths`` 的失败分类共用本函数，
    口径变更只动这一处，避免自愈判定与冲突分类漂移。
    """
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


def run_dist_build(
    project_root: Path,
    static_root: str | Path = DASHBOARD_STATIC_ROOT,
    logger=None,
    error_detail: list | None = None,
) -> bool:
    """执行主树构建（.fenix/verify.yaml prepare 驱动，回退 npm run build）。

    构建什么从 verify.yaml 的 prepare 段读取——不预设目标为 nodejs 项目，
    步骤自带 cwd、每步受 PREPARE_STEP_TIMEOUT 约束；契约缺失时回退历史
    行为（static_root 下 npm run build）；契约存在但未声明 prepare 视为
    「无构建步骤」，直接成功。

    fix-verdict-env-exemption-admin-handshake 1.1：自 ``_run_dist_build``
    提取的构建执行体模块级化（merge-back 确定性重建与 serving dist 新鲜度
    探针两处同源复用；design D3「构建命令契约与 merge-back 同源，不在
    serving 层硬编码 npm run build」）。

    Args:
        project_root: 主树项目根。
        static_root: 静态根（回退构建 cwd 与日志文案），缺省 dashboard 静态根。
        logger: 结构化 logger（warning 口径与提取前逐字一致）；传 None 时
            入口静默兜底（_NullLogger），按缺省签名调用不会 AttributeError。
        error_detail: 可选失败现场收集器（list）：失败时追加尾部日志文案
            （prepare 失败原因 / fallback 构建 stderr+stdout 尾 200 字符），
            供 serving 探针把构建失败尾部日志写入 run 错误现场；不传时
            行为与提取前逐字节一致。
    """
    # logger=None 兜底（code-review item 0f9cdf3a8cec）：按缺省签名（只传
    # project_root）调用时，契约缺失回退 / prepare 失败 / 回退构建失败 /
    # 构建调用异常四条路径无条件 logger.warning 会 AttributeError。对齐
    # lifecycle.py 与 state_machine.py:502 的 _NullLogger 先例（延迟导入
    # 避免循环依赖；warning 为 *args 形参，与两参结构化调用签名兼容）。
    if logger is None:
        from core.state_machine import _NullLogger
        logger = _NullLogger()

    from core.verify_contract import (
        ensure_main_tree_deps,
        load_verify_contract,
        read_config_deps_mode,
        resolve_deps_mode,
        run_prepare_steps,
    )

    contract = load_verify_contract(project_root, logger)
    if contract is not None:
        if not contract.prepare:
            return True
        # add-main-tree-deps-provision：merge 后主树重建 dist 与验证同样
        # 可能缺 node_modules（主树只被 merge-back 写入、无人手工安装），
        # prepare 前按 cwd 集合预装依赖（mode 无 pm 配置通道，走
        # read_config_deps_mode + resolve_deps_mode 同源解析）。
        ensure_main_tree_deps(
            project_root,
            sorted({(s.cwd or ".") for s in contract.prepare}),
            mode=resolve_deps_mode(contract, read_config_deps_mode(project_root)),
            logger=logger,
        )
        err = run_prepare_steps(contract, project_root)
        if err:
            logger.warning(
                "worktree_manager",
                f"dist rebuild prepare 失败: {err}",
            )
            if error_detail is not None:
                error_detail.append(str(err))
            return False
        return True
    static_dir = Path(project_root) / static_root
    if not (static_dir / "package.json").exists():
        logger.warning(
            "worktree_manager",
            f"dist rebuild skipped: no package.json under {static_root}",
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
        if r.returncode != 0:
            # 回退构建失败时保留输出尾部现场（截断口径与 commit 失败取
            # stderr[:200] 的既有做法一致），编译错误多在末尾，便于从日志
            # 直接定位而不必人工重跑。
            detail = ((r.stderr or "") + "\n" + (r.stdout or "")).strip()[-200:]
            logger.warning(
                "worktree_manager",
                f"dist rebuild fallback build failed: {detail}",
            )
            if error_detail is not None:
                error_detail.append(detail)
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning(
            "worktree_manager",
            f"dist build invocation failed: {e}",
        )
        if error_detail is not None:
            error_detail.append(str(e))
        return False


class G5DistConflictsMixin:
    """G5 构建产物冲突/dist 重建（design D1 表 A G5）。"""


    def _resolve_build_artifact_conflicts(self) -> bool:
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
        try:
            # -c core.quotePath=false（code-review item 4b0f8e543e15）：非 ASCII
            # 路径保持原样输出，否则 porcelain 的 C 转义引号形会让下方
            # checkout/git rm 因路径失配而静默失效。与 _collect_conflict_paths
            # 的采集点同口径。
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "-c",
                    "core.quotePath=false",
                    "status",
                    "--porcelain",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode != 0:
                return False

            conflict_paths = _collect_unmerged_paths(res.stdout)
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
                    co = subprocess.run(
                        ["git", "-C", str(self.project_root), "checkout", "HEAD", "--", p],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    if co.returncode != 0:
                        # 非阻塞记录（remaining 复查仍兜底降级语义冲突），
                        # 避免 checkout 失败被静默吞掉（item 4b0f8e543e15）
                        self.logger.warning(
                            "worktree_manager",
                            f"checkout HEAD -- {p} failed during artifact "
                            f"self-heal: {(co.stderr or '').strip()[:200]}",
                        )
                else:
                    rm = subprocess.run(
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
                    if rm.returncode != 0:
                        self.logger.warning(
                            "worktree_manager",
                            f"git rm -- {p} failed during artifact "
                            f"self-heal: {(rm.stderr or '').strip()[:200]}",
                        )
            # 收口：分支侧干净 add 的产物（非冲突新增）不复活——staged 产物中
            # HEAD 没有的一律移除（含旧路径双胞胎、对方重命名后的旧 hash chunk）。
            # 全量 staged 新增后按配置判定器过滤（code-review item
            # 6d8414eb218c）：不带 DASHBOARD_STATIC_ROOT 路径限定——配置在静态
            # 根之外（如根级 dist/）的产物同属「一律移除」语义，与判定器口径一致。
            staged = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "diff",
                    "--cached",
                    "--name-only",
                    "--diff-filter=A",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if staged.returncode == 0:
                strays = [
                    line
                    for line in self._artifacts.paths_in(
                        [p for p in staged.stdout.splitlines() if p]
                    )
                    if line not in head_artifacts
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
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "-c",
                    "core.quotePath=false",
                    "status",
                    "--porcelain",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            remaining = _collect_unmerged_paths(res2.stdout) if res2.returncode == 0 else []
            if res2.returncode != 0:
                # 复查失败 = 无法确认剩余冲突：不静默吞掉分类证据，记 warning
                # 后仍尝试 commit（若确有 unmerged 条目，git 会拒绝提交走向
                # abort 路径，等价交回调用方）。
                self.logger.warning(
                    "worktree_manager",
                    f"Build-artifact self-heal status recheck failed "
                    f"(rc={res2.returncode}): "
                    f"{(res2.stderr or '').strip()[:200]} — cannot confirm "
                    f"remaining semantic conflicts, trying commit anyway",
                )
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

        fix-verdict-env-exemption-admin-handshake 1.1：构建执行体已提取为
        模块级 ``run_dist_build``（serving dist 新鲜度探针同源复用），本方法
        保留为薄委托、行为不变。供 merge 后确定性重建使用；测试通过 patch
        本方法模拟构建产物/失败的既有契约不变。
        """
        return run_dist_build(self.project_root, DASHBOARD_STATIC_ROOT, self.logger)

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
            # merge 提交已在 upstream 上（已被外部推送）时，amend 会改写已发布
            # 历史——跳过 amend，unstage 后仅保留工作区重建。
            if self._head_on_upstream():
                subprocess.run(
                    ["git", "-C", str(self.project_root), "reset", "-q"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.logger.warning(
                    "worktree_manager",
                    "merge commit already on upstream — dist rebuild kept in "
                    "working tree only, amend skipped",
                )
                return
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

    def _head_on_upstream(self) -> bool:
        """HEAD 是否已被推送到 upstream（远程跟踪分支已包含 HEAD）。

        code-review item 302b781b7c51：amend 会改写刚产生的合并提交，若该提交
        已被外部（人工/其它实例）推送，amend 即改写已发布历史。判定口径：
        ``@{u}`` 存在且 HEAD 为其祖先（``merge-base --is-ancestor``，覆盖
        upstream 等于或领先 HEAD 两种已推送形态）。无 upstream 或探针失败时
        返回 False——保守维持原 amend 行为，不让探针故障阻断重建。
        """
        try:
            upstream = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "rev-parse",
                    "--verify",
                    "--quiet",
                    "@{u}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if upstream.returncode != 0 or not upstream.stdout.strip():
                return False
            ancestor = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "merge-base",
                    "--is-ancestor",
                    "HEAD",
                    "@{u}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return ancestor.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def _artifact_paths(self, rev: str) -> set:
        """列出 <rev> 中全部构建产物路径（按目录层次容错判定，全树枚举）。

        全树枚举（code-review item 044c4c78d747）：产物路径由项目配置驱动，
        可声明在 DASHBOARD_STATIC_ROOT 之外（如根级 dist/）；若只在 static 根
        内枚举，冲突对齐分支会把这些路径误判为「HEAD 已删」而遭 git rm——
        错误删除随 merge 提交固化，且 ``_rebuild_dist_after_merge`` 的
        src_touched 判定同样限静态根、不会触发重建兜底。
        """
        # -c core.quotePath=false（code-review item 3de86817b197）：非 ASCII
        # 产物路径保持原样输出，否则 HEAD 侧 C 转义引号形与 conflict_paths
        # 的原样形态失配，真实存在的路径会误判「HEAD 已删」而遭 git rm。
        # 与 _resolve_build_artifact_conflicts/_collect_conflict_paths 的
        # 采集点同口径。
        ls = subprocess.run(
            [
                "git",
                "-C",
                str(self.project_root),
                "-c",
                "core.quotePath=false",
                "ls-tree",
                "-r",
                "--name-only",
                rev,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ls.returncode != 0:
            return set()
        # 产物判定走实例判定器（evo-merge-back-wip-artifact-scope D3），与其余
        # 调用点同一口径。
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

        路径不转义：``-c core.quotePath=false``（与 ``_collect_conflict_paths``
        的采集点同口径）让非 ASCII 路径按原样输出——路径原样传给
        ``_triage_stash_pop_conflicts`` 拼 cat-file/checkout --theirs 的
        pathspec，带引号 C 转义形会永不命中，态 1/态 2 自愈对非 ASCII
        冲突文件恒失败退到态 3。
        """
        try:
            ls = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "-c",
                    "core.quotePath=false",
                    "ls-files",
                    "-u",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
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
            # -c core.quotePath=false：与 _resolve_build_artifact_conflicts 的
            # 采集点同口径（item 4b0f8e543e15），非 ASCII 路径不做 C 转义
            res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "-c",
                    "core.quotePath=false",
                    "status",
                    "--porcelain",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        if res.returncode != 0:
            return []
        return _collect_unmerged_paths(res.stdout)

    def _heal_unmerged_files(self, conflict_files: list) -> None:
        """对 UU 文件执行自愈：丢弃 stash/冲突合并态，统一回退 HEAD 版本。

        每个 UU 文件处于 unmerged 状态，普通 ``git checkout HEAD -- <file>`` 会报
        "path is unmerged"，因此用 ``-f`` 强制从 HEAD 还原——stash 应用内容与
        冲突合并态一并丢弃，工作区与 index 统一回到 HEAD 侧版本（不存在被
        「保留」的 merge 结果，丢弃面即 conflict_files 上的全部本地改动，调用点
        告警须明示）。随后 ``git reset`` 兜底清空 index 中任何残留的 staged 冲突
        条目，使主树回到干净可写状态。
        """
        for f in conflict_files:
            try:
                res = subprocess.run(
                    ["git", "-C", str(self.project_root), "checkout", "-f", "HEAD", "--", f],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            except (subprocess.SubprocessError, OSError):
                self.logger.warning(
                    "worktree_manager",
                    f"checkout -f HEAD -- {f} timed out during self-heal",
                )
            else:
                if res.returncode != 0:
                    # 非阻塞记录（调用点 remaining 复查仍兜底），避免 checkout
                    # 失败被静默吞掉（item f5c6d3e28733，口径对齐
                    # _resolve_build_artifact_conflicts 的先例）
                    self.logger.warning(
                        "worktree_manager",
                        f"checkout -f HEAD -- {f} failed during stash-pop "
                        f"self-heal: {(res.stderr or '').strip()[:200]}",
                    )
        # 清空 index 残留的 staged 冲突条目（mixed reset，不动工作区）
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "reset"],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            self.logger.warning(
                "worktree_manager",
                "git reset timed out during stash-pop self-heal",
            )
