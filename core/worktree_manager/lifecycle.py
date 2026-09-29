"""lifecycle.py — G1 创建/销毁生命周期（refactor-giant-classes D1/D5）。

原为 WorktreeManager 的 10 个方法（含 `__init__`），原样搬移为 mixin。
宿主实例化时按 MRO 命中本 mixin 的 `__init__`，实例属性初始化语义不变。
跨组协作经宿主实例 `self.<method>`（G1 无跨组方法直调）。

D3 patch 缝隙：本组使用 subprocess/time 模块名，经模块顶部导入即可——
mock.patch("core.worktree_manager.subprocess.run") 修改 subprocess 模块对象
自身，全进程共享，patch 依旧生效。
"""

from __future__ import annotations

import os
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

        # try 覆盖锁释放前的全部步骤（code-review item 545846c6e8cd）：reuse
        # 认领段与 base_dir.mkdir 原先位于 try 之外，权限不足等 OSError 会让
        # 异常携带着入口已持有的 spec 锁穿出 create()，陈锁清扫超时前该
        # spec+agent_type 无法再派发。失败路径与下方既有 except 一致：
        # discard 锁并 return None。
        try:
            # worktree 继承（fast-track 打回重派 / fix-provider-transient-backoff D3：
            # transient 终态保留的全 agent_type 遗产）：优先认领上一轮保留的复用遗产，
            # 在同一目录同一分支上继续（继承已提交成果与未提交现场），不再从零新建。
            # code-fix 车道（evo-code-fix-api-timeout-salvage 2.2）：api_timeout
            # salvage 后的 recovery legacy（reuse=True）由同链下一批 create 经本
            # 既有认领通路继承 salvaged 分支；认领不可用 fail-open 全新建树。
            if agent_type in ("fast-track", "implementer", "planner-plan", "planner-judge", "verifier", "code-fix"):
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
                    # 认领出口同样供给构建环境（code-review item 1e3f877e379b）：
                    # 仅分支模式经 create_worktree_on_branch 全新 checkout（queries
                    # 层明示「仅登记活动集与分支映射，不 seed」），新目录必无
                    # node_modules——与下方全新建树出口共用同一段幂等供给。
                    self._provision_worktree_deps(wt_path)
                    return wt_path
                # 无可复用遗产 → 清除上一轮的认领痕迹（prompt 注入以实际为准）。
                # 仅清不再指向活动集成员的残留（code-review item 097d73d377dd）：
                # _active_reuse 以 spec 为键、无 agent_type 维度，同 spec 他
                # agent_type 并发 create 刚认领成功的记录（path 仍在
                # _active_worktrees，其 run 在飞）不得在此抹掉——否则后续
                # get_reuse_record 读到 None，prompt 继承说明注入丢失。收工路径
                # （cleanup / keep_for_reuse）已把 path 摘出活动集，残留痕迹照旧清除。
                stale_rec = self._active_reuse.get(spec_name)
                if (
                    stale_rec is not None
                    and str(stale_rec.get("path") or "") not in self._active_worktrees
                ):
                    self._active_reuse.pop(spec_name, None)

            # Determine branch name — include timestamp to avoid collisions on re-verification
            # （evo-fix-worktree-name-collision-retry：跨 agent_type 同秒 create 会按
            # int(time.time()) 撞出同名分支与路径，后到者 add -b 报 already exists。
            # 在单次 create 调用内以单调递增时间戳同步重建分支名与路径就地重试
            # （换名至多 2 次、总计至多 3 次创建尝试），免去 runner 层 attempt
            # sleep 5 秒 + 重拉供给链的兜底消耗；末段保持纯数字时间戳，queries 层
            # rsplit+isdigit 解析契约不变。）
            timestamp = int(time.time())
            if agent_type == "verifier":
                prefix = "verify"
            else:
                prefix = "impl"

            def _names(ts: int):
                """按时间戳重建分支名与 worktree 目录名（撞名时同名双换）。"""
                if agent_type == "verifier":
                    return f"fenix/{prefix}-{spec_name}-{ts}", f"{prefix}-{spec_name}-{ts}"
                return f"fenix/{spec_name}-{ts}", f"{prefix}-{spec_name}-{ts}"

            branch, wt_name = _names(timestamp)
            wt_path = self.base_dir / wt_name

            self.base_dir.mkdir(parents=True, exist_ok=True)

            create_attempt = 0
            while True:
                create_attempt += 1
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
                    # 与 queries.create_worktree_on_branch 同款固化 C locale：
                    # git gettext 在非 C locale 下会把 "already exists" 翻译成本地化
                    # 文案，下方子串匹配落空 → 换名重试不触发（本地化 git 下同秒
                    # 撞名时仅降级为不重试，与 queries 同仓库同一逻辑两套口径）。
                    env={**os.environ, "LC_ALL": "C"},
                )

                if result.returncode == 0:
                    break

                # 非重名失败不重试；换名重试至多 2 次（总计至多 3 次创建尝试），
                # 耗尽仍失败沿用现状放弃路径（discard 锁、return None），
                # runner 层 attempt 循环兜底不变。
                if "already exists" not in (result.stderr or "") or create_attempt >= 3:
                    break

                # 换名重试：时间戳取 max(now, old+1) 保证新后缀严格大于旧值，
                # 分支名与路径同步重建（事故现场胜者已占用原路径）；重试全程
                # 持有创建锁（锁在入口获取、失败退出才释放），对调用方透明。
                old_branch = branch
                timestamp = max(int(time.time()), timestamp + 1)
                branch, wt_name = _names(timestamp)
                wt_path = self.base_dir / wt_name
                self.logger.warning(
                    "worktree_manager",
                    f"Worktree name collision for '{spec_name}' "
                    f"(attempt {create_attempt}/3): {old_branch} already "
                    f"exists, retrying with {branch}",
                )

            if result.returncode != 0:
                self.logger.error(
                    "worktree_manager",
                    f"Failed to create worktree: {result.stderr}",
                )
                with self._spec_lock_th:
                    self._spec_locks.discard(lock_key)
                    self._lock_since.pop(lock_key, None)
                return None

            self._active_worktrees.add(str(wt_path))
            self._wt_branches[str(wt_path)] = branch

            # Seed SPEC files for implementer and fast-track worktrees
            if agent_type in ("implementer", "fast-track"):
                self._seed_spec(spec_name, wt_path)

            self._provision_worktree_deps(wt_path)

            self.logger.info("worktree_manager", f"Worktree created: {wt_path}")
            return wt_path

        except subprocess.TimeoutExpired:
            self.logger.error("worktree_manager", "Worktree creation timed out")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
                self._lock_since.pop(lock_key, None)
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree creation error: {e}")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
                self._lock_since.pop(lock_key, None)
            return None

    def _provision_worktree_deps(self, wt_path: Path) -> None:
        """worktree 构建环境供给（deps_mode 双模式，best-effort 不阻塞派发）。

        git 不携带 node_modules，实现者每轮手工安装是既有摩擦源（fast-track
        复盘）。create() 的两条建树出口共用（全新 checkout / reuse 认领，含
        legacy_registry._take_reusable_worktree 的仅分支模式重建，code-review
        item 1e3f877e379b）：供给按 deps_mode 幂等，旧目录已带依赖时无副作用；
        失败仅 WARNING 降级，不阻塞派发。
        """
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

            # 路径作用域守卫（code-review item a83addc7fe6d）：裸 commit 会把 index
            # 里其它 staged 条目（用户手工暂存 / 自愈残留）连带入库。本场景 rel
            # 未被 rm --cached 移出 index（无 pathspec 解析失配问题），故改用
            # commit --only -- <rel> 限定提交集（与 _untrack_ignored_local_changes
            # / _purge_ignored_brought_in 的子集校验守卫同目的、实现更简）。
            commit = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.project_root),
                    "commit",
                    "--only",
                    "-m",
                    f"[fenix] spec: {spec_name}",
                    "--",
                    rel,
                ],
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
        except (subprocess.TimeoutExpired, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"SPEC commit aborted for '{spec_name}': {e}",
            )
            return False

    # [fenix-ignore:880e75c5874f] 条目过时：docstring 现行文案已写明 implementer 失败走 register_legacy 遗产保留不删分支，仅非实现者失败路径才 branch -D
    def cleanup(self, wt_path: Path, success: bool = True):
        """
        Clean up a worktree after an Agent run.

        Args:
            wt_path: Path to the worktree to clean up
            success: If True, retain the branch. If False, an implementer
                branch is NOT deleted: it is registered as legacy via
                register_legacy, keeping the worktree and branch for
                successor runs to consume; only non-implementer (e.g.
                verifier) failures delete the branch too (`branch -D`)
        """
        wt_str = str(wt_path)
        if wt_str not in self._active_worktrees:
            # d178acca8fe4：此处提前返回不经过 finally 摘锁段——若该 worktree
            # 的 spec 锁仍在 _spec_locks（登记表被 cleanup_orphans 清空后迟到的
            # cleanup、或调用方传入错误路径），锁由 refresh_locks 按陈锁空闲
            # 兜底回收（STALE_LOCK_IDLE_SECONDS，约 120s），期间 has_active_worktree
            # 持续 True、该 spec 派发短暂停顿（方向保守，不会双派发）。不在此处
            # 反推 spec 摘锁：spec 级锁可能属于同 spec 其他活跃 worktree，误摘
            # 会开双派发窗口。
            self.logger.warning(
                "worktree_manager",
                f"Unknown worktree: {wt_path} — 不在活动登记表，跳过收尾"
                f"（strays 清杀与快照留档一并跳过）；其 spec 锁若仍在册将由"
                f"陈锁清扫（约 120s）兜底回收，期间该 spec 派发可能短暂停顿",
            )
            return

        # ── 恢复重派遗产（add-recovery-legacy-check D1）─────────────────────────
        # 失败的 implementer worktree 不直接销毁，而是注册为「遗产」保留：死亡 run 的
        # 半成品可被后继重派的 run 收编（design D4）。verifier / 成功路径照常清理。
        # 判定依据分支名前缀：implementer 分支 `fenix/<spec>-<ts>`，verifier 分支
        # `fenix/verify-<spec>-<ts>`。
        branch = self._wt_branches.get(wt_str)
        # 入口快照（code-review item 3413cfc5b6e3）：try 内两路收尾（遗产/常规）
        # 都已先 pop 分支表，finally 再 get(wt_str) 常规路径恒为 None，故 finally
        # 的键解析须用此处捕获的入口值。
        wt_branch_at_entry = branch
        # 入口时刻快照（code-review item 1d1b4be9de25）：finally 摘锁以
        # _lock_since 晚于该时刻即跳过为界，收尾期间并发的同 spec 新锁
        # （另一 agent_type）不被误删
        cleanup_entry_ts = time.time()
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
                # 收工清扫（code-review item 54d372035862）：与常规路径及 keep_for_reuse
                # 口径对齐——目录保留，进程也不留。否则上一轮 dev-server 残留占着旧端口，
                # 后继 run create() 认领继承目录后可被存活探测误判为本轮实例已就绪。
                self._kill_worktree_strays(wt_path.name)
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
            # （code-review item 70ee0e162d66）branch -D 返回码须检查：失败时
            # stderr 已被 capture_output 吞掉，若仍记成功日志会掩盖残留死分支、
            # 误导排障，与 worktree remove 失败有 WARNING 的口径对齐。
            if not success and branch and branch != "HEAD":
                del_res = subprocess.run(
                    ["git", "-C", str(self.project_root), "branch", "-D", branch],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if del_res.returncode == 0:
                    self.logger.info("worktree_manager", f"Deleted branch: {branch}")
                else:
                    self.logger.warning(
                        "worktree_manager",
                        f"Branch delete failed for {branch}: "
                        f"{(del_res.stderr or '').strip()}",
                    )

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
            # 加锁口径与 create / release_spec_lock 对齐（code-review item
            # 318f41dcf125）：to_remove 计算与摘除全程持 _spec_lock_th，计算
            # 与摘除原子化（并发 create/cleanup 增删不撕裂迭代）。但持锁只
            # 封得住计算中途插入的子窗口——封不住进入临界区之前已完成的
            # 并发新 create（code-review item 1d1b4be9de25：收尾期间派发器
            # 对同一 spec 换 agent_type 发起新 create，如 verifier 收尾时
            # implementer 重派，键不同故加锁成功）。故摘除另以 _lock_since
            # 晚于入口时刻（cleanup_entry_ts）即跳过为界：晚于者认定并发
            # 新锁不误删（同键新锁不可能存在——本锁仍持有时 create 同键
            # 命中即返回 None），否则新 run 在 create 到子进程可被进程表
            # 扫到之间的构建窗口内失去锁保护，重开双派发事故（2026-09-03）
            # 窗口。
            with self._spec_lock_th:
                wt_spec = self._spec_from_branch(wt_branch_at_entry or "") or (
                    self._spec_from_worktree_name(wt_path.name)
                )
                # agent_type 维度限定（code-review item 79268616af63）：锁键为
                # "<spec>:<agent_type>"，仅按 spec 名过滤会把该 spec 名下全部
                # agent_type 的既有锁一并摘除——entry_ts 守卫只挡「cleanup 开始
                # 之后」新登记的锁，挡不住对方 run 在入口之前已 create 持有的键
                # （如 verifier 收尾时 implementer 已重派持锁），活 run 在构建
                # 窗口内失去锁保护（重开 2026-09-03 双派发事故同型窗口）。故按
                # 被清 worktree 自身形状反推键类型：verifier 形状（分支
                # fenix/verify-<spec>-<ts>，分支表缺失回落 verify- 目录前缀）
                # 只摘 :verifier；非 verifier 形状不摘 :verifier。分支名只编码
                # verify/impl 两族形状，impl 族内具体 agent_type（implementer/
                # fast-track 等）不可辨，同族维持全摘现状。非 impl-/verify-
                # 目录前缀的载体（create_worktree_on_branch 的 repair-/judge-
                # 产物等）自身从不登记锁，其收尾不摘任何键——同 spec 既有锁属
                # 他人，由其自身收尾释放或 refresh_locks 陈锁清扫兜底。
                wt_branch_text = wt_branch_at_entry or ""
                if wt_branch_text.startswith("fenix/verify-"):
                    wt_is_verifier = True
                elif wt_branch_text.startswith("fenix/"):
                    wt_is_verifier = False
                else:
                    wt_is_verifier = wt_path.name.startswith("verify-")
                wt_own_lock = wt_path.name.startswith(("impl-", "verify-"))
                to_remove = [
                    k
                    for k in self._spec_locks
                    if wt_spec is not None
                    and wt_own_lock
                    and k.split(":")[0] == wt_spec
                    and (
                        (k.partition(":")[2] == "verifier")
                        if wt_is_verifier
                        else (k.partition(":")[2] != "verifier")
                    )
                    and self._lock_since.get(k, 0.0) <= cleanup_entry_ts
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

        ``git stash create`` 只快照已跟踪文件的改动（index + worktree），实现
        者 WIP 最常见的新增未跟踪文件不进快照 commit（code-review item
        c61688ecd88a）。故快照前先对未跟踪文件补充留档：``git ls-files
        --others --exclude-standard`` 列出后批量 ``git hash-object -w`` 写入
        对象库（只增不可达 blob，不动 index / 引用 / 工作区），路径→blob SHA
        清单打进 WARNING 日志（``git cat-file -p <sha>`` 可还原内容）；留档
        失败仅 WARNING 明示「untracked 文件不在本快照内」，不影响 stash
        create，也不阻断删除主流程。

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
            # untracked 留档（code-review item c61688ecd88a）：stash create 不含
            # 未跟踪文件，先把它逐个 hash-object -w 写入对象库并打日志；失败仅
            # WARNING，不阻断 stash create 与删除主流程。
            try:
                # -z 双侧启用（code-review item a515d30d7e9d）：默认
                # core.quotePath=true 下非 ASCII/特殊字符路径会被 ls-files 输出
                # 成 C 转义引号形，而 --stdin-paths 按原始行取路径、不反转义，
                # hash-object 打不开该字面路径即 fatal、拖垮整批留档。改 NUL
                # 分隔后两侧均拿字面路径，非 ASCII 未跟踪文件留档不再失效。
                others = subprocess.run(
                    ["git", "-C", str(wt_path), "ls-files", "-z", "--others",
                     "--exclude-standard"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if others.returncode != 0:
                    raise OSError(
                        (others.stderr or "").strip() or "ls-files failed"
                    )
                ut_paths = [ln for ln in others.stdout.split("\0") if ln.strip()]
                if ut_paths:
                    hashed = subprocess.run(
                        ["git", "-C", str(wt_path), "hash-object", "-w",
                         "--stdin-paths", "-z"],
                        input="\0".join(ut_paths) + "\0",
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if hashed.returncode != 0:
                        raise OSError(
                            (hashed.stderr or "").strip() or "hash-object failed"
                        )
                    ut_shas = hashed.stdout.split()
                    if len(ut_shas) != len(ut_paths):
                        raise OSError(
                            f"hash-object wrote {len(ut_shas)} blobs for "
                            f"{len(ut_paths)} untracked paths"
                        )
                    pairs = [
                        f"{p} -> {s}" for p, s in zip(ut_paths, ut_shas)
                    ]
                    shown = "; ".join(pairs[:20])
                    if len(pairs) > 20:
                        shown += f"; (+{len(pairs) - 20} more)"
                    self.logger.warning(
                        "worktree_manager",
                        f"Pre-rmtree untracked files archived for {wt_path} "
                        f"({len(pairs)} files, recover via git cat-file -p "
                        f"<sha>): {shown}",
                    )
            except (subprocess.TimeoutExpired, OSError) as ue:
                self.logger.warning(
                    "worktree_manager",
                    f"Pre-rmtree untracked archive failed for {wt_path}: {ue} "
                    f"— untracked files are NOT in the snapshot",
                )
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
        """Clean up worktree directories registered in this process on shutdown.

        仅清理本轮在册（``_active_worktrees``）的 worktree 目录。daemon 重启后
        在册集为空，上一进程遗留的孤儿目录不在本方法覆盖范围，由陈锁清扫
        ``cleanup_stale_worktrees``（stale_sweep.py，daemon 启动路径调用，删除
        所有不在活动集合的目录）兜底回收，两法互补。

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

        收尾的 ``_active_worktrees.clear()`` 会连同 protected 跳过项的在册登记
        一并抹掉：shutdown 后登记随进程终结，无实害，语义上留意即可。
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
                # 收尾清扫（code-review item 11c4366528dc，与 cleanup() 口径对齐）：
                # 删除目录前先杀掉其残留测试子进程（dev-server 孤儿），否则目录
                # 删除后它们成为 cwd 失效的永生孤儿（曾致存活检测永久受骗）
                self._kill_worktree_strays(wt_dir.name)
                # 硬删前留档（D2）：git worktree remove --force 成功路径同样先
                # 留快照引用，消灭「先删后查」取证盲区；失败仅 WARNING 不阻塞。
                self._snapshot_dirty_worktree(wt_dir, self._wt_branches.get(str(wt_dir)))
                try:
                    result = subprocess.run(
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
                    # 返回非零（worktree locked / 权限 / 子模块残留）不抛异常：
                    # 参照 cleanup() 对 returncode != 0 做 rmtree 兜底，否则目录
                    # 静默滞留（末尾统一 worktree prune，此处不重复）。
                    if result.returncode != 0:
                        self.logger.warning(
                            "worktree_manager",
                            f"Orphan worktree remove warning: {result.stderr}",
                        )
                        if wt_dir.exists():
                            shutil.rmtree(str(wt_dir), ignore_errors=True)
                except Exception as e:
                    # subprocess 直接抛异常（如 git 挂起 TimeoutExpired / OSError）
                    # 不静默吞掉：先记 WARNING 留痕（异常类型 + stderr 现场），对齐
                    # cleanup() 与上方 returncode 分支「remove 失败必记 WARNING」
                    # 的口径（code-review item 67b788923b6e）；rmtree 兜底后复核
                    # 残留，目录仍在（如被占用删不掉）时追加留痕——否则下游存活
                    # 探测/孤儿清扫判定继续受骗且无任何日志可查。
                    stderr = getattr(e, "stderr", None) or ""
                    if isinstance(stderr, bytes):
                        stderr = stderr.decode("utf-8", "replace")
                    self.logger.warning(
                        "worktree_manager",
                        f"Orphan worktree remove failed for {wt_dir}: "
                        f"{type(e).__name__}: {e}"
                        + (
                            f"; stderr: {str(stderr).strip()[:200]}"
                            if str(stderr).strip()
                            else ""
                        ),
                    )
                    shutil.rmtree(str(wt_dir), ignore_errors=True)
                    if wt_dir.exists():
                        self.logger.warning(
                            "worktree_manager",
                            f"Orphan worktree dir still present after rmtree "
                            f"fallback: {wt_dir}",
                        )

        # Prune stale worktree references
        # （code-review item 506b30212499）收尾 prune 与循环体同款保护：git 挂起
        # 超时会抛 TimeoutExpired 穿出 shutdown 清理链并跳过下方登记清空，还可能
        # 中断后续收尾步骤。失败仅 WARNING，登记表照常清空。
        try:
            subprocess.run(
                ["git", "-C", str(self.project_root), "worktree", "prune"],
                capture_output=True,
                timeout=10,
            )
        except (subprocess.SubprocessError, OSError) as e:
            self.logger.warning(
                "worktree_manager",
                f"Worktree prune failed during orphan cleanup: {e}",
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
        # [fenix-ignore:a83d069b9197] 台账所述子串比对已修复为 _lock_spec_name 精确比对（split(":")[0]==spec），spec 名互为子串不再误判持锁
        # 快照容错（code-review ae95d059b22）：sorted() 构建快照本身就要迭代原
        # 集合，并非原子——并发 create/cleanup 增删 _spec_locks 仍可能在此抛
        # "Set changed size during iteration"，故捕获后保守视为持锁（本方法是
        # 派发闸门，各调用方都把 True 解释为「spec 忙则不动」，误 True 仅延后
        # 派发不会双派发），下次调用自然重判。不整方法持 _spec_lock_th 是因
        # 下方 _release_spec_locks 会再次取同一非重入锁；快照后的 any() 遍历
        # 的是独立列表，不再触碰原集合。
        # 入口时刻守卫（code-review item cec36ef4e1fb）：判定链（进程扫描 / 流
        # mtime）在持锁前完成，期间并发 create() / _register_spec_locks 登记的
        # 同键新锁 _lock_since 晚于本时刻，_release_spec_locks 按 not_after
        # 跳过不误删（同 cleanup finally 的 cleanup_entry_ts 口径，防新 run
        # 在构建窗口内失去锁保护重开双派发窗口）。
        entry_ts = time.time()
        try:
            snapshot = sorted(self._spec_locks)
        except RuntimeError:
            return True
        registered = any(
            self._lock_spec_name(lock) == spec_name for lock in snapshot
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
        released = self._release_spec_locks(
            spec_name, "stale lock (no live process)", not_after=entry_ts
        )
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
        # 入口时刻守卫（code-review item cec36ef4e1fb，同 has_active_worktree）：
        # 判定链在持锁前完成，期间并发 create 登记的同 spec 新锁按 not_after
        # 跳过不误删（防双派发窗口）。
        entry_ts = time.time()
        released: list = []
        # 快照容错（code-review ae95d059b22，同 has_active_worktree）：sorted()
        # 构建快照仍要迭代原集合，并非原子，并发 create/cleanup 增删可抛
        # RuntimeError。本轮放弃清扫即返回（陈锁回收是幂等周期任务，漏扫一轮
        # 由下一轮补上；保守方向——锁未回收只会延后派发，不会双派发）。
        try:
            snapshot = sorted(self._spec_locks)
        except RuntimeError:
            return released
        for lock_key in snapshot:
            spec = self._lock_spec_name(lock_key)
            # [fenix-ignore:216784713669] info 项按家族过滤须改 _process_scanner 注入契约与按 spec 键的扫描缓存/流 mtime 判定，且与 has_active_worktree 同粒度同链须同改（彼处不属本组条目），成本高风险大；方向保守（只延后派发不会双派发）且有 STALE_LOCK_IDLE_SECONDS 上界，维持 spec 粒度判活
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
                    not_after=entry_ts,
                )
            )
        if released:
            self.logger.warning(
                "worktree_manager",
                f"refresh_locks released stale lock(s): {released}",
            )
        return released
