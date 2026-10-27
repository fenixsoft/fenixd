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

from core.worktree_manager.constants import (  # noqa: E402
    STALE_LOCK_IDLE_SECONDS,
    STALE_LOCK_SWEEP_LOCK_AGE_CAP_SECONDS,
)
from core.worktree_manager.artifact_paths import (
    ArtifactPathMatcher,
    normalize_artifact_patterns,
)
from core.worktree_manager.shape import branch_shape_is_verifier


def _rmtree_with_residual_warning(logger, path, label: str) -> None:
    """worktree remove 失败后的 rmtree 兜底 + 残留复核留痕（cleanup/cleanup_orphans 共用）。

    ignore_errors=True 会静默吞掉权限不足/文件占用等删除失败，rmtree 后
    复核残留——目录仍在时追加 WARNING，否则下游存活探测/孤儿清扫继续受骗
    且无日志可查。label 为日志前缀（"Worktree" / "Orphan worktree"），
    与既有各处文案逐字对齐。
    """
    shutil.rmtree(str(path), ignore_errors=True)
    if path.exists():
        logger.warning(
            "worktree_manager",
            f"{label} dir still present after rmtree "
            f"fallback: {path}",
        )


def _wt_repo_common_dir(project_root):
    """项目根所属 git 仓库的 common dir（.git）；非 git 仓库返回 None。

    worktree 软链的 git 不可见性要写仓库级 info/exclude——per-worktree 的
    <gitdir>/info/exclude 不被 git 读取（实测），exclude 规则只有 common dir
    一份。锚定 project_root 而非 worktree 自身：防嵌套仓库语境（测试
    basetemp 落在框架仓库内等）把排除规则误写到宿主仓库。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-common-dir"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    p = Path(out.stdout.strip())
    if not p.is_absolute():
        p = Path(project_root) / p
    return p


def _path_git_ignored(wt_path, rel: str) -> bool:
    """rel 路径在该 worktree 的 git 判定下是否被忽略（check-ignore 语义：

    退出码 0=忽略、1=未忽略、128=出错；出错按未忽略处理，交由调用方走
    exclude 建立路径并复核）。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(wt_path), "check-ignore", "-q", rel],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def _ensure_git_exclude(common_dir, rel: str) -> bool:
    """把 rel 幂等追加进仓库 common dir 的 info/exclude；失败返回 False。

    info/exclude 是 git 为「仓库特定、无需共享」的忽略规则设计的本地位
    （不入库、不写工作区文件）。软链若不被 git 忽略，会以未跟踪形态永久
    弄脏 worktree——空变更 WIP checkpoint 的幂等跳过契约
    （tests/test_impl_wip_checkpoint 空变更断言）与 merge-back 干净判定都会
    被未跟踪软链击穿（3 例空变更断言失败的实证根因）。
    """
    excl = Path(common_dir) / "info" / "exclude"
    try:
        excl.parent.mkdir(parents=True, exist_ok=True)
        existing = excl.read_text(encoding="utf-8") if excl.exists() else ""
        if any(line.strip() == rel for line in existing.splitlines()):
            return True
        with excl.open("a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(
                "# fenix worktree provisioning: v2 dev-server static root"
                " (provisioned, do not track)\n"
                f"{rel}\n"
            )
        return True
    except OSError:
        return False


class G1LifecycleMixin:
    """G1 创建/销毁生命周期（design D1 表 A G1）。"""
    def __init__(
        self,
        base_dir: Path,
        project_root: Path,
        logger,
        process_scanner=None,
        implement_branch_prefix: Optional[str] = None,
        state_reader=None,
        mergeback_wip_overlap_policy=None,
        merge_precheck_bypass=False,
        build_artifact_paths=None,
        has_build_artifacts=None,
        branch_gc_enabled=True,
        branch_gc_retention_days=7,
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
        # 锁 owner 归属（fix-worktree-lock-release-degrade-gate D1）：锁键
        # ``<spec>:<agent_type>`` → 持锁 run_id（create(owner_run_id=…) 记录；
        # 无 run 上下文的登记路径（locks._register_spec_locks 重建、repair 车道
        # 直写 _spec_locks）无条目，owner 语义 = None）。与 _spec_locks 并行的
        # 归属映射而非改结构（design D1「新增 dict 或改结构均可」取前者）：既有
        # 成员判定/迭代/快照读点零改动，写侧摘锁点同步 pop 本表。释放 API
        # （release_spec_lock owner_run_id=…）与 acquire 陈锁清扫按本表核对
        # 持锁主归属；owner 未知（无条目）时清扫退回锁龄判据（保守不清扫）。
        self._spec_lock_owners: Dict[str, Optional[str]] = {}
        # 分支创建端口径前缀（fix-recovery-branch-anchor D2）：
        # 分支创建端硬编码 `fenix/`（同 mixin create() 内 _names 闭包的分支名
        # 拼装；code-review item ded13afb19bb：拆包后失效行号引用改方法级定位），
        # 此参数用于 `find_branches_by_spec` 枚举前缀——取配置值与创建端口径的并集，
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
        # node_modules 供给实测可达十几秒）——重派 spec 按名 glob 必命中上一轮残留
        # 旧流，「无进程」时新旧流皆无法区分 create 构建中与孤儿死锁，陈锁判定按
        # 锁龄豁免构建窗口、不以流文件缺失为前提（见 _lock_young）。
        self._lock_since: Dict[str, float] = {}
        # 锁治理（D4）：进程表扫描函数，默认 pgrep 实现；测试可注入替身。
        # 签名 (spec_name) -> bool，表示进程表中是否存在指向该 spec worktree 的进程。
        # （家族限定扫描会附带 prefixes= 关键字，替身不支持时按 TypeError 退回
        # spec 粒度——见 locks._spec_process_alive，code-review item 216784713669。）
        self._process_scanner = process_scanner or self._pgrep_spec_process
        # 键为裸 spec 名（spec 粒度扫描）或 (spec, prefixes) 二元组（家族限定扫描）
        self._proc_scan_cache: Dict[str, tuple] = {}  # spec/(spec,prefixes) -> (expires_at, alive)
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
        # 本轮 WIP 重叠闸门 D3b 已对齐 HEAD 的产物清单（code-review item
        # 106be2cef569）：__init__ 显式初始化（与上两项同批次），使
        # merge_back_from_branch 的 spec 目录在飞卫检查早退路径读取本属性
        # 不依赖 _wip_overlap_gate 已执行；_wip_overlap_gate 体内只做重置。
        self._wip_gate_aligned_artifacts: list = []
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

        # 已合并分支 GC 配置（add-merged-branch-gc 2.1）：fenixd 启动时经
        # ConfigLoader.get_branch_gc_config 解析注入（enabled 缺省 True /
        # retention_days 缺省 7）。GC 仅在 daemon 启动清扫路径执行一次，
        # 构造期注入与「每轮启动取当时配置」语义天然对齐（30s 热更新对
        # 启动一次性动作无意义）。enabled=False 时 GC 环节整体跳过且无日志。
        self._branch_gc_enabled = bool(branch_gc_enabled)
        # retention_days 非法值（非 int / bool / < 1）在此兜底回退 7：
        # 构造端（fenixd / 测试）直传不经 ConfigLoader 归一时仍不放大脏值。
        self._branch_gc_retention_days = (
            branch_gc_retention_days
            if isinstance(branch_gc_retention_days, int)
            and not isinstance(branch_gc_retention_days, bool)
            and branch_gc_retention_days >= 1
            else 7
        )

    def create(self, spec_name: str, agent_type: str = "implementer",
               owner_run_id: Optional[str] = None) -> Optional[Path]:
        """
        Create a git worktree for an Agent run.

        Args:
            spec_name: The SPEC name (e.g., "add-user-login")
            agent_type: "implementer" or "verifier"
            owner_run_id: 持锁 run 归属（fix-worktree-lock-release-degrade-gate
                D1）：非 None 时登记进 _spec_lock_owners，供终态释放的 owner
                校验与 acquire 陈锁清扫的存活核对消费；缺省 None 维持现状
                （无 run 上下文的调用方零改动）。

        Returns: Path to the worktree, or None on failure.
        """
        # Prevent duplicate worktrees for the same SPEC+agent_type
        # （fix-restart-dual-dispatch S2：check-then-add 原子化，见 __init__ 注释）
        lock_key = f"{spec_name}:{agent_type}"
        with self._spec_lock_th:
            if lock_key in self._spec_locks:
                # 陈锁存活清扫（fix-worktree-lock-release-degrade-gate D3）：
                # 早退前核对持锁 run 存活性——确认死亡（末行死亡判据 / 记录缺失
                # 且锁龄超 early give-up cap / owner 未知但锁龄超 cap）则清扫
                # 放行本次 acquire；判据不确定（记录在飞且末行非死亡判据行、
                # 锁龄未知或年轻）维持既有早退（宁可慢清扫不可错杀活锁）。
                # 判定与摘除同处持锁临界区（check-then-add 原子段内完成，并发
                # create 无缝隙可插）；_stale_lock_owner_dead 只做判定不做摘除
                # （_spec_lock_th 非重入，摘除由本调用方在锁内直做）。
                dead, sweep_reason = self._stale_lock_owner_dead(lock_key)
                if dead:
                    self.logger.warning(
                        "worktree_manager",
                        f"Stale lock swept for {lock_key}: {sweep_reason} "
                        f"— reacquiring (fix-worktree-lock-release-degrade-gate)",
                    )
                    self._spec_locks.discard(lock_key)
                    self._lock_since.pop(lock_key, None)
                    self._spec_lock_owners.pop(lock_key, None)
                else:
                    owner = self._spec_lock_owners.get(lock_key)
                    self.logger.warning(
                        "worktree_manager",
                        f"Worktree already active for {lock_key}"
                        + (f" (owner={owner})" if owner else ""),
                    )
                    return None
            self._spec_locks.add(lock_key)
            self._lock_since[lock_key] = time.time()
            self._spec_lock_owners[lock_key] = owner_run_id

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
                # 传发起方 agent_type 供家族校验（code-review item 7f66c46fffef）：
                # verify 族遗产仅 verifier 可认领、非 verify 族遗产不被 verifier
                # 认领，不匹配在 _take_reusable_worktree 内跳过认领走全新建树。
                reuse = self._take_reusable_worktree(spec_name, agent_type)
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
                    encoding="utf-8",
                    errors="replace",
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
                    self._spec_lock_owners.pop(lock_key, None)
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
                self._spec_lock_owners.pop(lock_key, None)
            return None
        except Exception as e:
            self.logger.error("worktree_manager", f"Worktree creation error: {e}")
            with self._spec_lock_th:
                self._spec_locks.discard(lock_key)
                self._lock_since.pop(lock_key, None)
                self._spec_lock_owners.pop(lock_key, None)
            return None

    def _provision_worktree_deps(self, wt_path: Path) -> None:
        """worktree 构建环境供给（deps_mode 双模式，best-effort 不阻塞派发）。

        git 不携带 node_modules，实现者每轮手工安装是既有摩擦源（fast-track
        复盘）。create() 的两条建树出口共用（全新 checkout / reuse 认领，含
        legacy_registry._take_reusable_worktree 的仅分支模式重建，code-review
        item 1e3f877e379b）：供给按 deps_mode 幂等，旧目录已带依赖时无副作用；
        失败仅 WARNING 降级，不阻塞派发。
        """
        # core/dashboard/static 软链供给（fix-v2-devserver-fallback-attribution
        # 1.2）：消除 v2 dev-server 的主树静态根回退形态本身。独立兜底 try：
        # 软链任何意外失败都不阻塞 node_modules 供给与派发。
        try:
            self._provision_worktree_static_root(wt_path)
        except Exception as e:
            self.logger.warning(
                "worktree_manager", f"worktree static 软链供给跳过: {e}"
            )
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

    def _provision_worktree_static_root(self, wt_path: Path) -> None:
        """worktree 补 core/dashboard/static 软链（fix-v2-devserver-fallback-
        attribution 1.2，create 两出口共用——经 _provision_worktree_deps）。

        git 不携带构建产物目录：非框架目标项目（仓库无 core/dashboard）的
        worktree 天然缺 core/dashboard/static，v2 dev-server 启动即落主树静态
        根回退形态（argv 失去 worktree 归属线索，清扫判不可归因）。对框架侧
        静态根建软链——推导与 v2_dev_server.start() 回退分支同源（框架仓库
        根 = ``Path(__file__).parent.parent.parent``，本文件深踞
        core/worktree_manager/ 一层，比 core/v2_dev_server.py 多一层 parent），
        链接后 start() 走 worktree 路径、不再回退。幂等：目标
        已存在（跟踪产物或历史软链）跳过——框架目标项目 worktree 自带跟踪的
        static 目录，本供给零开销。

        git 不可见性闸门（回归修复）：软链对 git 是未跟踪文件，直接落盘会
        永久弄脏 worktree——空变更 WIP checkpoint 的幂等跳过契约与 merge-back
        干净判定都会被未跟踪软链击穿（tests/test_impl_wip_checkpoint 3 例空
        变更断言失败的实证根因）。故软链前确保路径被 git 忽略：已忽略（仓库
        自带 ignore 规则）直接链接；否则幂等追加进仓库 common dir 的
        info/exclude（不入库、不写工作区文件）并用 check-ignore 复核；无法
        保证忽略时**跳过软链**静默降级（非 git 仓库语境无「脏」概念，直接
        链接）。软链/闸门任何失败仅 WARNING，不阻塞 create 派发：回退形态
        仍有 argv 归因标记（1.1）与清扫记账（2.1）兜底。
        """
        wt_static = Path(wt_path) / "core" / "dashboard" / "static"
        if wt_static.is_dir() or wt_static.is_symlink():
            return  # 已有（跟踪产物/历史软链）：幂等跳过（is_dir 对指向目录
            # 的软链为真，先判软链覆盖悬空链形态）
        framework_static = (
            Path(__file__).absolute().parent.parent.parent
            / "core" / "dashboard" / "static"
        )
        if not framework_static.is_dir():
            return  # 框架侧无静态根（非常规布局）：无从链接，静默跳过
        rel = "core/dashboard/static"
        common_dir = _wt_repo_common_dir(self.project_root)
        if common_dir is not None and not _path_git_ignored(wt_path, rel):
            # 仓库语境且路径尚未被忽略：先写 info/exclude 建立忽略并复核，
            # 通过才落软链；建不成（只读/异常/仓库否定规则反杀）→ 跳过软链
            # 降级，防未跟踪软链永久弄脏 worktree。
            if not _ensure_git_exclude(common_dir, rel) or not _path_git_ignored(
                wt_path, rel
            ):
                self.logger.warning(
                    "worktree_manager",
                    f"worktree static root provisioning skipped: {rel} 无法"
                    f"安全对 git 不可见（exclude 不可写或被仓库规则反杀），"
                    f"跳过软链防 worktree 变脏；dev-server 走主树静态根回退"
                    f"形态（argv 归因标记兜底）: {wt_static}",
                )
                return
        try:
            wt_static.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(framework_static, wt_static)
        except OSError as e:
            if wt_static.is_symlink():
                return  # EEXIST 竞态（并发 provision 已落地）：按已存在处理
            self.logger.warning(
                "worktree_manager",
                f"worktree static root symlink failed ({e}); dev-server 将走"
                f"主树静态根回退形态（argv 归因标记兜底）: {wt_static}",
            )
            return
        self.logger.info(
            "worktree_manager",
            f"worktree static root linked: {wt_static} -> {framework_static}",
        )

    def has_active_lock(self, spec_name: str, agent_type: str = "implementer") -> bool:
        """查询该 spec+agent_type 是否有活跃的 worktree 锁（fix-restart-dual-dispatch）。

        供 dispatch 派发前与 agent_runner attempt 重试前判定「是否已有另一 run
        在跑」——锁活跃即并行风险，调用方应放弃派发/重试，而不是换名再造一个
        worktree 形成并行 run（2026-09-03 双派发事故的第二梯队成因）。
        """
        return f"{spec_name}:{agent_type}" in self._spec_locks

    def release_spec_lock(self, spec_name: str, agent_type: str = "implementer",
                          owner_run_id: Optional[str] = None) -> bool:
        """释放该 spec+agent_type 的在册 spec 锁（code-fix defer 车道专用原语）。

        fix-codefix-wipgate-defer D3：defer 收尾保留 worktree 目录/分支与
        ``_active_worktrees`` 在册（sweeper 扫孤儿跳过在册目录、重试收尾
        ``cleanup`` 语义不变），仅摘锁——``create()`` 对同键命中即返回 None、
        批 worker 对 None 走 halt 终止链，不放锁则 defer 后下一批建树必败、
        整条车道在主树脏期间死锁。``wip_gate_blocked`` 标志与闸门策略零改动。

        owner_run_id（fix-worktree-lock-release-degrade-gate D1）：传非 None
        时做 owner 一致校验——在册锁的归属与本参一致才摘除，不一致 no-op +
        DEBUG 留痕（杜绝误放他人锁：陈锁清扫窗口内同键已被后继 run 重新取得
        时，原 run 迟到的终态释放不得把新锁摘掉）；不传（None）维持既有幂等
        语义（不校验归属，defer 车道既有 caller 零改动）。

        Returns: 是否确有在册锁被释放（无锁时 False，幂等安全）。
        """
        lock_key = f"{spec_name}:{agent_type}"
        with self._spec_lock_th:
            if lock_key not in self._spec_locks:
                return False
            if owner_run_id is not None:
                owner = self._spec_lock_owners.get(lock_key)
                if owner != owner_run_id:
                    self.logger.debug(
                        "worktree_manager",
                        f"release_spec_lock({lock_key}) skipped: owner "
                        f"mismatch (lock owner={owner!r}, releaser="
                        f"{owner_run_id!r}) — no-op",
                    )
                    return False
            released = True
            self._spec_locks.discard(lock_key)
            self._lock_since.pop(lock_key, None)
            self._spec_lock_owners.pop(lock_key, None)
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
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
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
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            if add.returncode != 0:
                # 留痕口径对齐下方 commit 失败分支（code-review item fe67f0001bd2）
                self.logger.warning(
                    "worktree_manager",
                    f"SPEC add failed: {rel}: {add.stderr.strip() or add.stdout.strip()}",
                )
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
                encoding="utf-8",
                errors="replace",
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
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
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
        # 判定依据分支名形状（verify- 开头 spec 名消歧，shape.py 单源）：实现
        # 族分支 `fenix/<spec>-<ts>`，verifier 分支 `fenix/verify-<spec>-<ts>`。
        # 裸前缀 startswith("fenix/verify-") 会把 verify- 开头 spec 名的实现
        # 分支（fenix/verify-dsh-plugins-live-<ts>）误判为 verifier 形状——
        # 失败路径遗产登记被跳过、分支被 -D（admin-global-1791999865 同型）。
        branch = self._wt_branches.get(wt_str)
        # 入口快照（code-review item 3413cfc5b6e3）：try 内两路收尾（遗产/常规）
        # 都已先 pop 分支表，finally 再 get(wt_str) 常规路径恒为 None，故 finally
        # 的键解析须用此处捕获的入口值。
        wt_branch_at_entry = branch
        # 入口时刻快照（code-review item 1d1b4be9de25）：finally 摘锁以
        # _lock_since 晚于该时刻即跳过为界，收尾期间并发的同 spec 新锁
        # （另一 agent_type）不被误删
        cleanup_entry_ts = time.time()
        is_implementer = bool(branch) and (
            branch_shape_is_verifier(branch, wt_path.name) is not True
        )

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
                # spec 解析以目录名为首选锚（admin-global-1791999865）：目录名
                # 前缀（impl-/verify-）按 agent_type 定、与 spec 名无关，对
                # verify- 开头 spec 名无歧义；_spec_from_branch 会把实现分支
                # fenix/verify-<spec>-<ts> 按验证语义剥前缀回推出错 spec。
                spec = self._spec_from_worktree_name(wt_path.name) or (
                    self._spec_from_branch(branch or "")
                )
                if spec:
                    self.register_legacy(spec, wt_path, branch)
                else:
                    # 登记不成立留痕（code-review item e0a4e5c15072）：spec 不可
                    # 解析时 register_legacy 无法登记遗产，目录失去清扫豁免、将被
                    # cleanup_stale_worktrees 按孤儿回收（对齐
                    # _maybe_register_legacy_for_stale_lock 的跳过留痕口径）。
                    self.logger.warning(
                        "worktree_manager",
                        f"Failed-worktree legacy registration skipped: spec "
                        f"unresolvable from branch '{branch}' (wt={wt_path}) — "
                        f"no sweep exemption, directory is subject to "
                        f"cleanup_stale_worktrees reclaim",
                    )
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
                        encoding="utf-8",
                        errors="replace",
                        timeout=10,
                    )
                    if br.returncode == 0:
                        branch = br.stdout.strip()
                    else:
                        # 解析失败留痕（code-review item c11ad5bb37e1）：branch
                        # 保持 None 会使下方 branch -D 整段跳过，失败分支静默
                        # 残留且无日志可查，与本方法 worktree remove / rmtree /
                        # branch -D 失败必记 WARNING 的口径对齐。
                        self.logger.warning(
                            "worktree_manager",
                            f"Branch name resolve failed for {wt_path} "
                            f"(rc={br.returncode}): {(br.stderr or '').strip()} — "
                            f"failure-path branch delete will be skipped",
                        )
                except Exception as e:
                    self.logger.warning(
                        "worktree_manager",
                        f"Branch name resolve error for {wt_path}: {e} — "
                        f"failure-path branch delete will be skipped",
                    )

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
                encoding="utf-8",
                errors="replace",
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
                    # rmtree 兜底 + 残留复核留痕（code-review item 765918a1c98c，
                    # 与 cleanup_orphans 两处兜底分支收敛到同一模块级辅助）
                    _rmtree_with_residual_warning(self.logger, wt_path, "Worktree")
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
                # 分支在飞引用保护（code-review item d35168265657，对齐
                # legacy_registry._physically_reclaim_legacy 与 stale_sweep 的
                # 删分支前口径）：失败分支被 STATE 在飞/冻结保持引用时保留分支
                # 仅回收 worktree，解冻后续做/恢复不降级为从零重做。
                kept, reason = self._branch_protected_by_state(branch)
                if kept:
                    self.logger.warning(
                        "worktree_manager",
                        f"分支在飞引用保护：保留分支 '{branch}'（{reason}）— "
                        f"worktree 已清理，分支留待恢复/后继 run 收编",
                    )
                else:
                    del_res = subprocess.run(
                        ["git", "-C", str(self.project_root), "branch", "-D", branch],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
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
                # spec 解析以目录名为首选锚（admin-global-1791999865，同上方
                # 失败路径口径）：_spec_from_branch 对 verify- 开头 spec 名的
                # 实现分支剥错前缀，wt_spec 对不上锁键段 → 过滤恒空、锁永不
                # 释放（与形状误判叠加的第二重泄漏机制）。
                wt_spec = self._spec_from_worktree_name(wt_path.name) or (
                    self._spec_from_branch(wt_branch_at_entry or "")
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
                # 形状判定单源走 shape.py 结构消歧（admin-global-1791999865
                # 根因修复）：裸前缀 startswith("fenix/verify-") 会把 verify-
                # 开头 spec 名的实现分支（fenix/verify-dsh-plugins-live-<ts>）
                # 误判为 verifier 形状，收尾只摘 :verifier 族锁 → 同键
                # :implementer 锁泄漏 → 后续重派 create() 即撞锁 early
                # give-up（Failed to create worktree）→ 同因重派循环 → spec
                # 冻结。
                wt_branch_text = wt_branch_at_entry or ""
                _shape = branch_shape_is_verifier(
                    wt_branch_text, wt_path.name, spec_hint=wt_spec,
                )
                if _shape is None:
                    wt_is_verifier = wt_path.name.startswith("verify-")
                else:
                    wt_is_verifier = _shape
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
                    # 入口时刻守卫对齐 locks._release_spec_locks_core 的
                    # not_after 口径（code-review item 279dac9d45dc，同
                    # 98ad40e18a38）：缺 _lock_since 记录=无法证明陈旧，保守
                    # 跳过摘除——repair_lane._claim_repair_site 的
                    # <spec>:repair 只写 _spec_locks 不写 _lock_since，旧
                    # get(k, 0.0) 兜底把这类在飞新锁按远古时刻处理、恒过守卫
                    # 被摘，非 verifier 形状收尾会误摘 repair 车道在飞锁
                    # （宁可靠 refresh_locks 陈锁清扫兜底，不误摘）。
                    and (since := self._lock_since.get(k)) is not None
                    and since <= cleanup_entry_ts
                ]
                for k in to_remove:
                    self._spec_locks.discard(k)
                    self._lock_since.pop(k, None)
                    self._spec_lock_owners.pop(k, None)
                # 进程扫描缓存随之失效（下一次判定须重新扫描，防读到陈旧「存活」结果）
                for k in to_remove:
                    self._proc_scan_cache.pop(self._lock_spec_name(k), None)
                    # 家族限定缓存键一并失效（code-review item 47b98315d174）：
                    # _spec_process_alive 按 (spec, prefixes) 二元组为家族限定
                    # 扫描单独缓存（refresh_locks 家族过滤判活消费，prefixes
                    # 取 _lock_family_prefix 值域 verify/impl），仅清裸 spec 键
                    # 会在缓存窗口内残留摘锁前的家族存活判定，与上方「防读到
                    # 陈旧存活结果」的意图不完整一致。
                    self._proc_scan_cache.pop(
                        (self._lock_spec_name(k), ("verify",)), None,
                    )
                    self._proc_scan_cache.pop(
                        (self._lock_spec_name(k), ("impl",)), None,
                    )
                    # worktree 继承：认领痕迹随之清除（防止后续 prompt 误注入继承说明）。
                    # 仅清不再指向活动集成员的残留（code-review item 23e1bc091552，
                    # 同 create() 的 097d73d377dd 口径）：_active_reuse 以 spec 为键、
                    # 无 agent_type 维度，verifier 收尾只摘 :verifier 家族锁，仍按
                    # spec 单键 pop 会把同 spec 仍在飞他族 run（如 implementer 重派）
                    # 的认领记录一并抹掉——get_reuse_record 随后返回 None，后续
                    # relint/重派 prompt 的继承说明注入丢失。记录 path 仍在活动集
                    # （其 run 在飞）则保留；指向已清 worktree 自身的残留照旧清除。
                    k_spec = self._lock_spec_name(k)
                    reuse_rec = self._active_reuse.get(k_spec)
                    if (
                        reuse_rec is not None
                        and str(reuse_rec.get("path") or "")
                        not in self._active_worktrees
                    ):
                        self._active_reuse.pop(k_spec, None)

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
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            if status.returncode != 0:
                # 探测失败（超时/锁争用/git 故障）≠ 干净：脏 worktree 上静默
                # 跳过即现场毁灭后取证盲区，按失败降级口径 WARNING 留档。
                self.logger.warning(
                    "worktree_manager",
                    f"Pre-rmtree snapshot skipped for {wt_path}: "
                    f"git status failed rc={status.returncode} "
                    f"{(status.stderr or '').strip() or 'no stderr'} — "
                    f"snapshot not attempted, cleanup proceeds",
                )
                return ""
            if not status.stdout.strip():
                return ""  # 干净，无快照价值
            # untracked 留档（code-review item c61688ecd88a）：stash create 不含
            # 未跟踪文件，先把它逐个 hash-object -w 写入对象库并打日志；失败仅
            # WARNING，不阻断 stash create 与删除主流程。
            try:
                # ls-files 侧 -z（code-review item a515d30d7e9d）：默认
                # core.quotePath=true 下非 ASCII/特殊字符路径会被 ls-files 输出
                # 成 C 转义引号形，而 --stdin-paths 按原始行取路径、不反转义，
                # hash-object 打不开该字面路径即 fatal、拖垮整批留档。-z 后
                # ls-files 侧拿到字面路径，非 ASCII 未跟踪文件留档不再失效。
                # hash-object 侧无 -z 开关（git 2.54 选项表实测 unknown
                # switch，code-review item 9734ebf6c937），--stdin-paths 只能
                # 按 LF 行读路径，故输入用 LF 分隔；路径含换行的极端形态
                # 不在留档覆盖内。
                others = subprocess.run(
                    ["git", "-C", str(wt_path), "ls-files", "-z", "--others",
                     "--exclude-standard"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
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
                         "--stdin-paths"],
                        input="\n".join(ut_paths) + "\n",
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
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
                encoding="utf-8",
                errors="replace",
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
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
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

        # 迭代前物化快照（code-review item 17750ac199fb，同 _reclaim_expired_legacy
        # 对 _legacy 的物化纪律）：循环体内 rmtree / worktree remove 删除的是同一
        # base_dir 的子项，iterdir 惰性迭代期间修改目录在 POSIX 未定义（Linux
        # getdents 缓冲条目可能因并发删除漏报/重报），会跳过本轮 shutdown 清理的
        # 部分孤儿目录。
        for wt_dir in list(self.base_dir.iterdir()):
            if wt_dir.is_dir() and str(wt_dir) in self._active_worktrees:
                if str(wt_dir) in protected:
                    self.logger.info(
                        "worktree_manager",
                        f"Skip orphan cleanup for {wt_dir} — protected by "
                        f"interrupted-runs preserve entry",
                    )
                    continue
                self.logger.info("worktree_manager", f"Cleaning up orphan: {wt_dir}")
                try:
                    # 收尾清扫（code-review item 11c4366528dc，与 cleanup() 口径对齐）：
                    # 删除目录前先杀掉其残留测试子进程（dev-server 孤儿），否则目录
                    # 删除后它们成为 cwd 失效的永生孤儿（曾致存活检测永久受骗）
                    # 杀残留与留档两调用移入 try（code-review item 5f3dee9b3ef8）：
                    # 与 cleanup() 把收尾全程包进 except Exception 的口径一致，二者的
                    # 未预期异常不再穿出 for 循环中断剩余孤儿目录的清理与登记清空，
                    # 改由下方 except 分支 WARNING 留痕并 rmtree 兜底后继续下一目录。
                    self._kill_worktree_strays(wt_dir.name)
                    # 硬删前留档（D2）：git worktree remove --force 成功路径同样先
                    # 留快照引用，消灭「先删后查」取证盲区；失败仅 WARNING 不阻塞。
                    self._snapshot_dirty_worktree(wt_dir, self._wt_branches.get(str(wt_dir)))
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
                        encoding="utf-8",
                        errors="replace",
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
                            # rmtree 兜底 + 残留复核留痕（code-review item
                            # 765918a1c98c，与 cleanup() 收敛到同一模块级辅助）
                            _rmtree_with_residual_warning(
                                self.logger, wt_dir, "Orphan worktree"
                            )
                except Exception as e:
                    # subprocess 直接抛异常（如 git 挂起 TimeoutExpired / OSError），
                    # 上方杀残留/留档调用的未预期异常（item 5f3dee9b3ef8）同样落到
                    # 这里，均不静默吞掉：先记 WARNING 留痕（异常类型 + 现场），对齐
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
                    _rmtree_with_residual_warning(
                        self.logger, wt_dir, "Orphan worktree"
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

        # 登记清空与其他锁变更点同纪律持 _spec_lock_th（code-review item
        # 342c3b64ac76）：并发 runner/dispatcher 侧 _release_spec_locks 的
        # 列表推导迭代无 RuntimeError 容错，无锁 clear() 会令其抛
        # "Set changed size during iteration" 穿出派发闸门调用链。本方法
        # 其余路径未持该非重入锁，锁内取锁无死锁风险。
        with self._spec_lock_th:
            self._active_worktrees.clear()
            # 分支映射表与活动集同属 create/cleanup 成对维护的活动登记
            # （code-review item 3c4a2e810936）：shutdown 清理语义完整化，
            # 一并清空，防同实例二次 shutdown 时残留已删 worktree 的
            # path→branch 陈旧映射（此后按分支表反推 spec 的读路径不再命中
            # 已删目录）。dict.clear() 原子完成，无迭代撕裂问题；boot 侧
            # 恢复路径（recover_interrupted / preservation）自行重建登记，
            # 不依赖本进程残留。
            self._wt_branches.clear()
            self._spec_locks.clear()
            self._lock_since.clear()
            self._spec_lock_owners.clear()
            self._proc_scan_cache.clear()
            # _legacy / _active_reuse 不在此清空（code-review item
            # 3c4a2e810936 保留原因说明）：二者非本进程活动登记，有独立
            # 生命周期与专门回收机制——_legacy 保留至后继 run 成功 merge
            # （consume_legacy）或宽限期超时（stale_sweep 的
            # _reclaim_expired_legacy 兜底回收）；_active_reuse 由收工路径
            # （cleanup / keep_for_reuse / _take_reusable_worktree 认领时
            # 摘出）管理。shutdown 后登记随进程终结，同进程无再消费路径；
            # daemon 重启后本就为空（内存态不持久化），boot/恢复路径以
            # git 与 STATE 为真相重建，不读本进程残留（find_worktree_by_spec
            # 等明示不信任内存表）。测试复用同实例二次 shutdown 时残留记录
            # 为惰性数据：读取方（get_legacy / get_reuse_record → prompt
            # 注入）不在 shutdown 链路上，cleanup / 孤儿清扫循环另有
            # _active_worktrees 门卫，不会据陈旧记录错误动作。

    def has_active_worktree(self, spec_name: str) -> bool:
        """Check if any worktree is active for the given SPEC.

        锁治理（improve-run-lifecycle-governance D4）：先以进程表校验在册锁——
        锁在册但扫描不到进程、且 run 流文件停止增长超过 STALE_LOCK_IDLE_SECONDS
        时判定为陈锁并回收（孤儿 attempt 已死，锁放行后续派发；年轻锁按锁龄豁免
        回收，见下方豁免分支）；锁在册且进程存活（或流仍新鲜）则照常视为持锁。

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
        # create 构建窗口豁免（双派发穿透原地修 2026-09-06）：以锁龄二次确认——
        # 锁在 create() 拿到而 attempt 子进程与其流文件尚未产生（实测构建可达十几
        # 秒）。豁免按锁龄独立生效、不以「无流文件」为前提（code-review item
        # ee35ee5b3e5b）：流文件按 spec 名 glob 命中全部轮次并逐轮留存，重派 spec
        # 必有上一轮残留旧流（mtime 早超阈值），若仅无流才豁免，构建窗口内的年轻
        # 锁会被当陈锁摘除、重开双派发穿透窗口。年轻锁保守保留；超龄仍按陈锁
        # 回收，孤儿清理语义不变。此处豁免保持 spec 全量、不按家族过滤
        # （code-review item 5d9601004a62）：下方陈锁释放按 spec 全摘（含他族
        # 键），豁免须覆盖全部将被摘除的家族——按本族过滤会让他族年轻锁在全摘
        # 中失去锁保护、重开双派发穿透窗口；家族过滤豁免仅适用于 refresh_locks
        # 的单键回收路径。
        if self._lock_young(spec_name):
            return True
        # ── 恢复重派遗产（add-recovery-legacy-check D2，同 refresh_locks 口径）──
        # 陈锁释放的同一时刻为孤儿 implementer worktree 注册遗产兜底
        # （code-review item 72e12f537b2a）：若锁在此处先被释放，refresh_locks
        # 的快照不再包含该键，D2 的遗产注册时机被永久跳过，死亡 run 的 WIP 目录
        # 失去清扫豁免与快照留档保障。幂等（register_legacy 覆盖式更新；
        # worktree 仍在活动集时该方法自身跳过）。
        self._maybe_register_legacy_for_stale_lock(spec_name)
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

        对每个在册锁（code-review item 216784713669：锁键为 <spec>:<agent_type>，
        进程扫描与流 mtime 判定按本族前缀 verify/impl 限定——同 spec 他族活进程/
        新鲜流不再庇护本族死锁，如 implementer 在飞时死 verifier 的锁可按时回收；
        解析不出 agent_type 的键维持 spec 粒度保守判活。回收只摘本族锁键，在飞
        他族锁不受牵连）：
          - 进程表存在指向该 spec worktree 的进程 → 保留（孤儿 resume 存活的情形）
          - 无匹配进程且对应 run 流文件 mtime 距今超过 STALE_LOCK_IDLE_SECONDS
            （或根本没有流文件）→ 陈锁，释放放行后续派发
          - 无匹配进程但流仍在增长 → 保守保留（进程扫描可能受窗口/权限影响）
          - 年轻锁（_lock_since 距今不足阈值）→ 保守保留（create 构建窗口豁免，
            按锁龄独立生效、不以流文件缺失为前提）

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
            # 家族过滤判活（code-review item 216784713669）：进程扫描与流 mtime
            # 按锁键 agent_type 的家族前缀（create() 两族形状：verifier → verify、
            # 其余 → impl）限定，死家族的锁不再被同 spec 他族活进程/新鲜流庇护；
            # 解析不出 agent_type 时退回 spec 粒度保守判活。
            family = self._lock_family_prefix(lock_key)
            if family is not None:
                alive = self._spec_process_alive(spec, prefixes=(family,))
                mtime = self._latest_stream_mtime(spec, prefixes=(family,))
            else:
                alive = self._spec_process_alive(spec)
                mtime = self._latest_stream_mtime(spec)
            if alive:
                continue
            if mtime is not None and (time.time() - mtime) <= STALE_LOCK_IDLE_SECONDS:
                continue
            if self._lock_young(spec, family=family):
                # 构建窗口豁免按锁龄独立生效、不以「无流文件」为前提（同
                # has_active_worktree 口径，code-review item ee35ee5b3e5b）：重派
                # spec 的上一轮残留旧流不使豁免失效。豁免只覆盖本族年轻锁
                # （code-review item 5d9601004a62）：与上方家族过滤判活同口径，
                # 本族陈锁不因他族年轻构建被庇护延后回收；family=None（键解析不
                # 出 agent_type）时维持 spec 粒度保守豁免，与同分支 alive/mtime 的
                # 退回口径一致。
                continue
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
                    # 家族已知时只摘本锁键：同 spec 在飞他族锁的生死未判定，
                    # 全摘会让其失去锁保护（code-review item 216784713669）
                    lock_key=lock_key if family is not None else None,
                )
            )
        if released:
            self.logger.warning(
                "worktree_manager",
                f"refresh_locks released stale lock(s): {released}",
            )
        return released
