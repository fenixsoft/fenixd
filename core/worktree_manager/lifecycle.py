"""lifecycle.py — G1 创建/销毁生命周期（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 10 个方法（含 `__init__`），原样搬移为 mixin。
宿主实例化时按 MRO 命中本 mixin 的 `__init__`，实例属性初始化语义不变。
跨组协作经宿主实例 `self.<method>`（G1 无跨组方法直调）。

D3 patch 缝隙：本组使用 subprocess/time 模块名，经模块顶部导入即可——
mock.patch("core.worktree_manager.subprocess.run") 修改 subprocess 模块对象
自身，全进程共享，patch 依旧生效。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time

from pathlib import Path
from typing import Dict, Optional, Set

from core.worktree_manager import (  # noqa: E402
    STALE_LOCK_IDLE_SECONDS,
)
from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    normalize_artifact_patterns,
)


class G1LifecycleMixin:
    """G1 创建/销毁生命周期（design D1 表 A G1）。"""
    def __init__(
        self,
        base_dir: Path,
        project_root: Path,
        logger,
        process_scanner=None,
        implement_branch_prefix: str = None,
        state_reader=None,
        mergeback_wip_overlap_policy=None,
        merge_precheck_bypass=False,
        build_artifact_paths=None,
        has_build_artifacts=None,
    ):
        self.base_dir = Path(base_dir)
        self.project_root = Path(project_root)
        # logger=None 兜底（add-cancelled-spec-resume-action BUG-01）：dashboard
        # 侧独立进程以 logger=None 构造（admin_actions.py unfreeze/resume 两处），
        # 而各组 mixin（如 queries.create_worktree_on_branch）无条件调
        # self.logger → AttributeError。对齐 state_machine.py:502 的 _NullLogger
        # 先例（延迟导入避免模块级循环依赖，stale_sweep 同款）。
        if logger is None:
            from core.state_machine import _NullLogger
            logger = _NullLogger()
        self.logger = logger
        self._active_worktrees: Set[str] = set()
        self._wt_branches: Dict[str, str] = {}  # wt_path -> branch name
        self._spec_locks: Set[str] = set()  # SPECs currently being worked on
        # 分支创建端口径前缀（fix-recovery-branch-anchor D2）：
        # 分支创建端硬编码 `fenix/`（create() 第 223/226 行），此参数用于
        # `find_branches_by_spec` 枚举前缀——取配置值与创建端口径的并集，
        # 确保非 fenix 配置下仍命中 fenix 创建的分支（若配置值为 fenix，
        # 只枚举一次，无重复扫描）。
        self._implement_branch_prefix = implement_branch_prefix or "fenix"
        # STATE 读取器（fix-recovery-branch-anchor D6 分支在飞引用保护）：
        # 注入 `() -> Dict[spec_name, entry]`；缺省 None 时按 project_root
        # 就地解析 `.fenix/STATE.md`（StateParser 无循环依赖）。读取失败
        # MUST 保守处理（不清分支），不阻塞 boot 路径。
        self._state_reader = state_reader
        # 锁龄登记（双派发穿透原地修 2026-09-06）：key -> 拿锁时刻。run 流文件由
        # attempt 子进程启动后才创建，而锁在 create() 内即持有（worktree add + seed +
        # node_modules 供给实测可达十几秒）——「无进程且无流文件」无法区分 create
        # 构建中与孤儿死锁，陈锁判定按锁龄豁免构建窗口（见 _lock_young）。
        self._lock_since: Dict[str, float] = {}
        # 锁治理（D4）：进程表扫描函数，默认 pgrep 实现；测试可注入替身。
        # 签名 (spec_name) -> bool，表示进程表中是否存在指向该 spec worktree 的进程。
        self._process_scanner = process_scanner or self._pgrep_spec_process
        self._proc_scan_cache: Dict[str, tuple] = {}  # spec -> (expires_at, alive)
        # 恢复重派遗产（add-recovery-legacy-check D1）：死亡 run 的 worktree 与分支
        # 注册为 spec 的遗产，保留至「后继 run 成功 merge」或「宽限期超时」二者先到。
        # 内存态，不持久化（与锁同策略，daemon 重启后遗产按孤儿清扫兜底）。覆盖式
        # 更新：同一 spec 多次死亡只留最新一份（D5 避免遗产链膨胀）。
        # 结构：{spec_name: {"path": str, "branch": str, "registered_at": float,
        #                     "dirty": bool, "worktree_name": str}}
        self._legacy: Dict[str, dict] = {}
        # worktree 继承（fast-track 打回重派复用）：本轮 run 已认领的复用 worktree
        # （take 时从 _legacy 摘出，防 sweeper 宽限期误回收在用目录）。prompt 构建
        # 据此注入「继承说明」。结构：{spec_name: {"path": str, "branch": str}}
        self._active_reuse: Dict[str, dict] = {}
        # 主树 merge-clean guard 串行锁（fix-autostash-orphans）：stash→merge→pop
        # 是必须原子完成的段——并发 worker 若各自独立 stash/pop，会与共享的 stash
        # 栈发生 LIFO 错配（A 恢复出 B 刚 stash 的内容）。
        self._main_tree_lock = threading.Lock()
        # spec 锁原子化（fix-restart-dual-dispatch S2）：create 的 check-then-add
        # 必须原子完成——2026-09-03 事故中两个并发 create 都通过了入口检查，同秒
        # 同名分支 fatal 后失败路径 discard 掉了胜出者刚 add 的同一把锁，第二梯队
        # 换名重试成功 → 两个 claude 并行跑同一 spec。
        self._spec_lock_th = threading.Lock()
        # 最近一次 guard 段内 stash pop 冲突自愈丢弃的文件清单（dispatch 层读走
        # 做 admin 告警后失效）；guard 进入时清空。
        self.last_stash_pop_conflicts: list = []
        # 最近一次 pop 冲突自愈后 stash 条目去向（fix-mergeback-stashpop-silent-loss
        # D1/D2）：{"kept": bool, "sha": str}——kept=False 表示已被自动 drop（sha
        # 可 gc 前找回），kept=True 表示条目保留。dispatch 层读走并入告警文本。
        self.last_stash_entry_fate: dict = {"kept": True, "sha": ""}
        # merge-back 前 WIP 重叠闸门策略（evo-merge-back-wip-overlap-gate D1；
        # add-pipeline-throughput-governance D2 缺省处置改为升级拦截）：
        # 缺省 None → escalate（交集非空即拦截，不发起 merge、人工升级告警、
        # spec 保持可重试）；显式 "auto" = 保留自动收纳（stash→merge→恢复，pop
        # 冲突保留条目）；显式 "block" 并入升级出口。fenixd 从
        # worktree.mergeback_wip_overlap_policy 解析注入；解析细节与变更依据见
        # mergeback._wip_gate_policy。
        self._mergeback_wip_overlap_policy = mergeback_wip_overlap_policy
        # merge 前置预检逃生门（add-pipeline-throughput-governance 2.3）：
        # true 时跳过 WIP 重叠预检直接 merge（紧急推送用，冲突按既有失败路径
        # 处理）。fenixd 从 worktree.merge_precheck_bypass（兼容顶层键）注入。
        self._merge_precheck_bypass = merge_precheck_bypass

        # 构建产物路径判定器（evo-merge-back-wip-artifact-scope D4 /
        # fix-artifact-paths-hardcoded-default D1）：产物判定从全局常量改为实例
        # 状态。配置值经 normalize_artifact_patterns 规范化（非法项丢弃并 WARNING）；
        # 缺省 None / 全非法 → 空列表构造，判定恒假（未裁决的保守侧，**无任何内置
        # 默认路径**）。has_build_artifacts 三态注入（None=未裁决 / False=已声明无
        # 产物 / True=按路径判定），False 时判定器短路恒假。判定器是构造期必需
        # 属性——MUST NOT 用 getattr 兜底，缺失应暴露而非静默降级。
        self._artifacts = ArtifactPathMatcher(
            normalize_artifact_patterns(build_artifact_paths),
            has_build_artifacts=has_build_artifacts,
        )

    def create(self, spec_name: str, agent_type: str = "implementer") -> Optional[Path]:
        """
        Create a git worktree for an Agent run.

        Args:
            spec_name: The SPEC name (e.g., "add-user-login")
            agent_type: "implementer" or "verifier"

        Returns: Path to the worktree, or None on failure.
        """
        # Prevent duplicate worktrees for the same SPEC+agent_type
        # （fix-restart-dual-dispatch S2：check-then-add 原子化，见 __init__ 注释）
        lock_key = f"{spec_name}:{agent_type}"
        with self._spec_lock_th:
            if lock_key in self._spec_locks:
                self.logger.warning(
                    "worktree_manager",
                    f"Worktree already active for {lock_key}",
                )
                return None
            self._spec_locks.add(lock_key)
            self._lock_since[lock_key] = time.time()

        # worktree 继承（fast-track 打回重派 / fix-provider-transient-backoff D3：
        # transient 终态保留的全 agent_type 遗产）：优先认领上一轮保留的复用遗产，
        # 在同一目录同一分支上继续（继承已提交成果与未提交现场），不再从零新建。
        if agent_type in ("fast-track", "implementer", "planner-plan", "planner-judge", "verifier"):
            reuse = self._take_reusable_worktree(spec_name)
            if reuse is not None:
                wt_path, branch = reuse
                self._active_worktrees.add(str(wt_path))
                self._wt_branches[str(wt_path)] = branch
                self.logger.info(
                    "worktree_manager",
                    f"Reusing inherited worktree for '{spec_name}': "
                    f"{wt_path} (branch {branch})",
                )
                return wt_path
            # 无可复用遗产 → 清除上一轮的认领痕迹（prompt 注入以实际为准）
            self._active_reuse.pop(spec_name, None)

        # Determine branch name — include timestamp to avoid collisions on re-verification
        timestamp = int(time.time())
        if agent_type == "verifier":
            branch = f"fenix/verify-{spec_name}-{timestamp}"
            prefix = "verify"
        else:
            branch = f"fenix/{spec_name}-{timestamp}"
            prefix = "impl"

        # Ensure unique worktree directory
        wt_name = f"{prefix}-{spec_name}-{timestamp}"
        wt_path = self.base_dir / wt_name

        self.base_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.logger.info(
                "worktree_manager",
                f"Creating worktree: {wt_path} on branch {branch}",
            )

            # Create worktree
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(wt_path),
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                self.logger.error(
                    "worktree_manager",
                    f"Failed to create worktree: {result.stderr}",
                )
                with self._spec_lock_th:
                    self._spec_locks.discard(lock_key)
                return None

            self._active_worktrees.add(str(wt_path))
            self._wt_branches[str(wt_path)] = branch

            # Seed SPEC files for implementer and fast-track worktrees
            if agent_type in ("implementer", "fast-track"):
                self._seed_spec(spec_name, wt_path)

            # worktree 构建环境供给（deps_mode 双模式，best-effort 不阻塞派发）：
            # git 不携带 node_modules，实现者每轮手工安装是既有摩擦源（fast-track 复盘）
            try:
                from core.verify_contract import (
                    load_verify_contract,
                    provision_worktree_node_modules,
                    read_config_deps_mode,
                    resolve_deps_mode,
                )

                contract = load_verify_contract(self.project_root)
                sub_dirs = sorted({(s.cwd or ".") for s in contract.prepare}) if contract else []
                if sub_dirs:
                    provision_worktree_node_modules(
                        wt_path,
                        self.project_root,
                        sub_dirs,
                        mode=resolve_deps_mode(contract, read_config_deps_mode(self.project_root)),
                        logger=self.logger,
                    )
            except Exception as e:
                self.logger.warning("worktree_manager", f"worktree node_modules 供给跳过: {e}")

            self.logger.info("worktree_manager", f"Worktree created: {wt_path}")
            return wt_path

        except subprocess.TimeoutExpired:
            self.logger.error("worktree_manager", "Worktree creation timed out")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree creation error: {e}")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
            return None

    def has_active_lock(self, spec_name: str, agent_type: str = "implementer") -> bool:
        """查询该 spec+agent_type 是否有活跃的 worktree 锁（fix-restart-dual-dispatch）。

        供 dispatch 派发前与 agent_runner attempt 重试前判定「是否已有另一 run
        在跑」——锁活跃即并行风险，调用方应放弃派发/重试，而不是换名再造一个
        worktree 形成并行 run（2026-09-03 双派发事故的第二梯队成因）。
        """
        return f"{spec_name}:{agent_type}" in self._spec_locks

    def release_spec_lock(self, spec_name: str, agent_type: str = "implementer") -> bool:
        """释放该 spec+agent_type 的在册 spec 锁（code-fix defer 车道专用原语）。

        fix-codefix-wipgate-defer D3：defer 收尾保留 worktree 目录/分支与
        ``_active_worktrees`` 在册（sweeper 扫孤儿跳过在册目录、重试收尾
        ``cleanup`` 语义不变），仅摘锁——``create()`` 对同键命中即返回 None、
        批 worker 对 None 走 halt 终止链，不放锁则 defer 后下一批建树必败、
        整条车道在主树脏期间死锁。``wip_gate_blocked`` 标志与闸门策略零改动。

        Returns: 是否确有在册锁被释放（无锁时 False，幂等安全）。
        """
        lock_key = f"{spec_name}:{agent_type}"
        with self._spec_lock_th:
            released = lock_key in self._spec_locks
            self._spec_locks.discard(lock_key)
            self._lock_since.pop(lock_key, None)
        return released

    def _seed_spec(self, spec_name: str, wt_path: Path):
        """Seed SPEC source files into a new worktree.

        If spec/changes/<spec>/ exists in the main worktree but not in the
        new worktree (the branch HEAD doesn't contain it), copy the directory
        into the worktree and commit it to the isolated branch.

        Failures are logged but never block — the implementer falls back to
        the main repository path.
        """
        try:
            main_spec_dir = self.project_root / "spec" / "changes" / spec_name
            wt_spec_dir = wt_path / "spec" / "changes" / spec_name

            if not main_spec_dir.is_dir():
                return
            if wt_spec_dir.is_dir():
                return

            self.logger.info(
                "worktree_manager",
                f"Seeding SPEC '{spec_name}' into worktree",
            )

            # Copy the entire SPEC directory
            wt_spec_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(main_spec_dir), str(wt_spec_dir))

            # Git add + commit in the worktree
            result = subprocess.run(
                ["git", "-C", str(wt_path), "add", "spec/changes/"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"git add failed during seeding: {result.stderr}",
                )
                return

            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(wt_path),
                    "commit",
                    "-m",
                    f"[fenix] spec: {spec_name}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"git commit failed during seeding: {result.stderr}",
                )
                return

            self.logger.info(
                "worktree_manager",
                f"SPEC '{spec_name}' seeded and committed in worktree",
            )
        except Exception as e:
            self.logger.warning(
                "worktree_manager",
                f"SPEC seeding failed (non-fatal): {e}",
            )

    def ensure_spec_committed(self, spec_name: str) -> bool:
        """派发 implementer 前把 spec 目录提交进主树（fix-merge-back-deadlock 根因修复）。

        spec 目录（spec/changes/<spec>/）若在主树 untracked，而 worktree 分支里
        _seed_spec 已 commit 一份同名路径，merge-back 时 git 会拒绝「untracked working
        tree files would be overwritten by merge」。在派发前把 spec 提交进主树使其被跟踪，
        分支从新 HEAD 建即可直接包含 spec（_seed_spec 跳过），merge 变为干净三方合并。

        Returns: True 表示已提交或本已无改动（干净）；False 表示提交失败。
        """
        rel = f"spec/changes/{spec_name}"
        try:
            status = subprocess.run(
                ["git", "-C", str(self.project_root), "status", "--porcelain", "--", rel],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if status.returncode != 0:
                return False
            if not status.stdout.strip():
                return True  # 本已 tracked + clean，无需提交

            add = subprocess.run(
                ["git", "-C", str(self.project_root), "add", "--", rel],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if add.returncode != 0:
                return False

            commit = subprocess.run(
                ["git", "-C", str(self.project_root), "commit", "-m", f"[fenix] spec: {spec_name}"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if commit.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"SPEC commit failed: {commit.stderr.strip() or commit.stdout.strip()}",
                )
                return False
            self.logger.info("worktree_manager", f"Committed SPEC '{spec_name}' into main tree")
            return True
        except subprocess.TimeoutExpired:
            return False

    def cleanup(self, wt_path: Path, success: bool = True):
        """
        Clean up a worktree after an Agent run.

        Args:
            wt_path: Path to the worktree to clean up
            success: If True, retain the branch; if False, delete branch too
        """
        wt_str = str(wt_path)
        if wt_str not in self._active_worktrees:
            self.logger.warning("worktree_manager", f"Unknown worktree: {wt_path}")
            return

        # ── 恢复重派遗产（add-recovery-legacy-check D1）─────────────────────────
        # 失败的 implementer worktree 不直接销毁，而是注册为「遗产」保留：死亡 run 的
        # 半成品可被后继重派的 run 收编（design D4）。verifier / 成功路径照常清理。
        # 判定依据分支名前缀：implementer 分支 `fenix/<spec>-<ts>`，verifier 分支
        # `fenix/verify-<spec>-<ts>`。
        branch = self._wt_branches.get(wt_str)
        is_implementer = bool(branch) and not branch.startswith("fenix/verify-")

        try:
            self.logger.info(
                "worktree_manager",
                f"Cleaning up worktree: {wt_path} (success={success})",
            )

            if (not success) and is_implementer:
                # 死亡 implementer run：保留 worktree 与分支为遗产，仅释放锁 + 移出活动集。
                # 物理目录留给后继 run 只读参考，由 sweeper（宽限期超时）或 merge 成功
                # （consume_legacy）回收。注册发生在删除之前，避免指向已删路径。
                spec = self._spec_from_branch(branch)
                if spec:
                    self.register_legacy(spec, wt_path, branch)
                self._active_worktrees.discard(wt_str)
                self._wt_branches.pop(wt_str, None)
                return

            # Get branch name BEFORE removing worktree
            branch = None
            if not success:
                try:
                    br = subprocess.run(
                        ["git", "-C", str(wt_path), "rev-parse", "--abbrev-ref", "HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if br.returncode == 0:
                        branch = br.stdout.strip()
                except Exception:
                    pass

            # 收工清扫：agent 已退出，先杀掉其残留测试子进程（dev-server 孤儿），
            # 否则目录删除后它们成为 cwd 失效的永生孤儿（曾致存活检测永久受骗）
            self._kill_worktree_strays(wt_path.name)

            # 硬删前置留档（fix-preserve-chain-first-round-gap D2）：删除前对
            # dirty worktree 做快照引用——不再只挂在 `git worktree remove`
            # 失败的 rmtree 兜底分支（排水强杀 --force 通常成功，旧路径
            # 系统性触发不了留档）；--force 成功路径同样留档。
            # 快照失败降级 WARNING，不阻断删除。
            self._snapshot_dirty_worktree(wt_path, self._wt_branches.get(wt_str))

            # Build command without empty strings
            cmd = [
                "git",
                "-C",
                str(self.project_root),
                "worktree",
                "remove",
                str(wt_path),
            ]
            if not success:
                cmd.append("--force")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                self.logger.warning(
                    "worktree_manager",
                    f"Worktree remove warning: {result.stderr}",
                )
                # If git worktree remove fails, try manual directory removal
                # 快照已在上方完成（Task 3.3 幂等保证），rmtree 前不再重复留档。
                if wt_path.exists():
                    shutil.rmtree(str(wt_path), ignore_errors=True)
                    # Also prune the worktree reference
                    subprocess.run(
                        ["git", "-C", str(self.project_root), "worktree", "prune"],
                        capture_output=True,
                        timeout=10,
                    )

            # On failure, delete the branch we captured earlier
            if not success and branch and branch != "HEAD":
                subprocess.run(
                    ["git", "-C", str(self.project_root), "branch", "-D", branch],
                    capture_output=True,
                    timeout=10,
                )
                self.logger.info("worktree_manager", f"Deleted branch: {branch}")

            self._active_worktrees.discard(wt_str)
            self._wt_branches.pop(wt_str, None)

        except Exception as e:
            self.logger.error("worktree_manager", f"Cleanup error: {e}")
        finally:
            # Release the spec lock
            # 键解析（code-review item 62e4613d6390）：用该 worktree 的分支反推
            # spec 后按 `k.split(":")[0] == spec` 精确匹配释放（与 keep_for_reuse
            # / legacy_registry 对齐）。旧子串包含匹配在 spec 名互为子串
            # （fix-auth 与 fix-auth2）时会把他 spec 的锁一并释放——在飞 run
            # 失去锁保护后派发器可对同一 spec 派第二个并行 run（双派发事故形态）。
            # 分支表缺失（daemon 重启重建表）时回落 worktree 目录名解析；两路
            # 皆不可解析则不释放（宁可靠 refresh_locks 的陈锁清扫兜底，不误放
            # 他人锁）。
            wt_spec = self._spec_from_branch(
                self._wt_branches.get(wt_str) or ""
            ) or self._spec_from_worktree_name(wt_path.name)
            to_remove = [
                k
                for k in self._spec_locks
                if wt_spec is not None and k.split(":")[0] == wt_spec
            ]
            for k in to_remove:
                self._spec_locks.discard(k)
                self._lock_since.pop(k, None)
            # 进程扫描缓存随之失效（下一次判定须重新扫描，防读到陈旧「存活」结果）
            for k in to_remove:
                self._proc_scan_cache.pop(self._lock_spec_name(k), None)
                # worktree 继承：认领痕迹随之清除（防止后续 prompt 误注入继承说明）
                self._active_reuse.pop(self._lock_spec_name(k), None)

    def _snapshot_dirty_worktree(self, wt_path: Path, branch: str | None = None) -> str:
        """cleanup rmtree fallback 前对 dirty worktree 做 stash create 快照留档。

        add-impl-terminal-nocommit-gate（D4）：用 ``git stash create``（引用式、
        不入 stash 栈）生成快照 commit SHA，记入日志（WARNING 级，含分支名）；
        后续争议裁决可通过 ``git stash store <sha>`` 将其转正进栈、或
        ``git fsck --unreachable | grep <sha>`` 追溯，消灭「现场毁灭后取证靠
        转录间接复原」的盲区。

        Returns: 快照 commit SHA（留档成功）或空字符串（跳过/失败）。
        """
        try:
            status = subprocess.run(
                ["git", "-C", str(wt_path), "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if status.returncode != 0 or not status.stdout.strip():
                return ""  # 干净，无快照价值
            snap = subprocess.run(
                [
                    "git",
                    "-C",
                    str(wt_path),
                    "stash",
                    "create",
                    f"fenix: pre-rmtree snapshot {branch or wt_path.name}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if snap.returncode != 0 or not snap.stdout.strip():
                self.logger.warning(
                    "worktree_manager",
                    f"Pre-rmtree snapshot skipped for {wt_path}: "
                    f"{snap.stderr.strip() or 'empty stash create output'}",
                )
                return ""
            sha = snap.stdout.strip()
            self.logger.warning(
                "worktree_manager",
                f"Pre-rmtree snapshot saved for {wt_path} "
                f"(branch {branch or '?'}): commit {sha} — "
                f"recover via: git stash store {sha}",
            )
            return sha
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Pre-rmtree snapshot failed for {wt_path}: {e} — " f"cleanup proceeds",
            )
            return ""

    def cleanup_orphans(self, protected: set | None = None):
        """Clean up any remaining worktree directories on shutdown.

        Args:
            protected: 保护集（路径字符串集合）——被保全引用覆盖的 worktree
                （interrupt-recovery-preserve D6：`.fenix/interrupted_runs.json`
                在册项与保留分支对应的 worktree）在 shutdown 清理时跳过，
                防止「保全」与「清理」两条链路对同一 worktree 处置不一致。
                缺省空集，行为与旧版完全一致。

        清理协调（fix-preserve-chain-first-round-gap D2/D3）：任何删除 worktree
        目录的路径 MUST 在目录被物理删除前对该 worktree 执行
        ``_snapshot_dirty_worktree`` 留档——清理不留快照是最需要取证场景（排水
        强杀）里保全链系统性失效的另一半。快照失败降级 WARNING，不阻塞删除。
        """
        protected = {str(p) for p in (protected or set())}
        if not self.base_dir.exists():
            return

        for wt_dir in self.base_dir.iterdir():
            if wt_dir.is_dir() and str(wt_dir) in self._active_worktrees:
                if str(wt_dir) in protected:
                    self.logger.info(
                        "worktree_manager",
                        f"Skip orphan cleanup for {wt_dir} — protected by "
                        f"interrupted-runs preserve entry",
                    )
                    continue
                self.logger.info("worktree_manager", f"Cleaning up orphan: {wt_dir}")
                # 硬删前留档（D2）：git worktree remove --force 成功路径同样先
                # 留快照引用，消灭「先删后查」取证盲区；失败仅 WARNING 不阻塞。
                self._snapshot_dirty_worktree(wt_dir, self._wt_branches.get(str(wt_dir)))
                try:
                    subprocess.run(
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
                        timeout=30,
                    )
                except Exception:
                    shutil.rmtree(str(wt_dir), ignore_errors=True)

        # Prune stale worktree references
        subprocess.run(
            ["git", "-C", str(self.project_root), "worktree", "prune"],
            capture_output=True,
            timeout=10,
        )

        self._active_worktrees.clear()
        self._spec_locks.clear()
        self._lock_since.clear()
        self._proc_scan_cache.clear()

    def has_active_worktree(self, spec_name: str) -> bool:
        """Check if any worktree is active for the given SPEC.

        锁治理（improve-run-lifecycle-governance D4）：先以进程表校验在册锁——
        锁在册但扫描不到进程、且 run 流文件停止增长超过 STALE_LOCK_IDLE_SECONDS
        时判定为陈锁并回收（孤儿 attempt 已死，锁放行后续派发）；锁在册且进程
        存活（或流仍新鲜）则照常视为持锁。

        daemon 重启后内存锁丢失、但进程表仍存在指向该 spec worktree 的存活
        agent 进程时，同样返回 True（重建登记），防止创建第二个并发 worktree。
        """
        registered = any(
            self._lock_spec_name(lock) == spec_name for lock in self._spec_locks
        )
        if not registered:
            # 无在册锁：以进程为真相兜底（daemon 重启 / 孤儿 resume 场景），
            # 命中时重建登记，使后续判定回到内存快路径。
            if self._spec_process_alive(spec_name):
                self._register_spec_locks(spec_name)
                self.logger.info(
                    "worktree_manager",
                    f"Rebuilt lock from process table for '{spec_name}' "
                    "(daemon restart with live child)",
                )
                return True
            return False

        # 在册锁：疑似陈锁时按「进程 + 流新鲜度」二次确认
        if self._spec_process_alive(spec_name):
            return True
        mtime = self._latest_stream_mtime(spec_name)
        if mtime is not None and (time.time() - mtime) <= STALE_LOCK_IDLE_SECONDS:
            return True  # 进程扫描未命中但流仍在增长：保守视为持锁
        # create 构建窗口豁免（双派发穿透原地修 2026-09-06）：流文件缺失时以锁龄
        # 二次确认——锁在 create() 拿到而 attempt 子进程与其流文件尚未产生（实测
        # 构建可达十几秒），年轻锁保守保留，防误释放后第二派穿透；超龄仍按陈锁
        # 回收，孤儿清理语义不变。
        if mtime is None and self._lock_young(spec_name):
            return True
        released = self._release_spec_locks(spec_name, "stale lock (no live process)")
        if released:
            self.logger.warning(
                "worktree_manager",
                f"Released stale lock(s) {released} for '{spec_name}' — "
                f"no live process and stream idle >{STALE_LOCK_IDLE_SECONDS}s",
            )
        return False

    def refresh_locks(self) -> list:
        """以真实进程表重建/校验在册锁，回收陈锁（daemon 启动首扫 + 周期调用）。

        对每个在册锁：
          - 进程表存在指向该 spec worktree 的进程 → 保留（孤儿 resume 存活的情形）
          - 无匹配进程且对应 run 流文件 mtime 距今超过 STALE_LOCK_IDLE_SECONDS
            （或根本没有流文件）→ 陈锁，释放放行后续派发
          - 无匹配进程但流仍在增长 → 保守保留（进程扫描可能受窗口/权限影响）

        Returns: 被回收的锁 key 列表（审计/测试用）。
        """
        released: list = []
        for lock_key in sorted(self._spec_locks):
            spec = self._lock_spec_name(lock_key)
            if self._spec_process_alive(spec):
                continue
            mtime = self._latest_stream_mtime(spec)
            if mtime is not None and (time.time() - mtime) <= STALE_LOCK_IDLE_SECONDS:
                continue
            if mtime is None and self._lock_young(spec):
                continue  # create 构建窗口豁免（同 has_active_worktree，防误回收年轻锁）
            # ── 恢复重派遗产（add-recovery-legacy-check D2）──
            # 陈锁释放的同一时刻：若该 spec 尚有未被清理的 implementer worktree（孤儿，
            # 如 daemon 重启后锁已失、但 worktree 目录仍在），注册为遗产兜底保留，
            # 避免被下方 cleanup_stale_worktrees 直接回收。实现死亡主路径在 cleanup()
            # 已注册，此处为补充（幂等：register_legacy 覆盖式更新）。
            self._maybe_register_legacy_for_stale_lock(spec)
            released.extend(
                self._release_spec_locks(
                    spec,
                    f"stale lock: no live process, stream idle " f">{STALE_LOCK_IDLE_SECONDS}s",
                )
            )
        if released:
            self.logger.warning(
                "worktree_manager",
                f"refresh_locks released stale lock(s): {released}",
            )
        return released
