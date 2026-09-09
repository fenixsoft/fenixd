#!/usr/bin/env python3
"""
fenixd — Fenix Loop Engineering Daemon
=======================================
Background daemon that orchestrates the four Fenix Agents:
  1. Requirement Agent (user-interactive, via Claude Code Skill)
  2. Implementer Agent (automatic, Ralph-mode, worktree-isolated)
  3. Verifier Agent (automatic, independent validation)
  4. PM Engine (priority, scheduling, reporting)

Architecture:
  config.yaml → ConfigLoader
       ↓
  EventBus ← inotify on STATE.md
       ↓
  PM Engine (priority + scheduling)
       ↓
  AgentRunner → claude subprocess → WorktreeManager
       ↓
  Logger ← all components
"""

import os
import sys
import signal
import subprocess
import threading
import time
import json
import fcntl
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure .fenix/ is on the Python path
# 使用 .absolute()（不跟随软链接）：框架文件经项目内 .fenix/ 软链接调用，
# 这样 FENIX_DIR 始终指向项目内的 .fenix/，而非框架真实安装目录。
FENIX_DIR = Path(__file__).absolute().parent
PROJECT_ROOT = FENIX_DIR.parent
sys.path.insert(0, str(FENIX_DIR))

from core.config import ConfigLoader
from core.logger import Logger
from core.state_machine import StateMachine
from core.event_bus import EventBus
from core.worktree_manager import WorktreeManager
from core.agent_runner import AgentRunner
from core.agent_runner.runner import ADMIN_DISPOSITION_GLOB
from core.v2_dev_server import cleanup_orphans as v2_cleanup_orphans
from core.admin_store import AdminStore, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.hook_engine import HookEngine
from core.pm_engine import PMEngine

# Administrator 处置状态实例文件的残留清扫阈值（fix-admin-run-blocks-mainloop
# tasks 1.3）：run 异常中断时实例文件可能残留，无功能影响（按 run_id 读取），
# 拾取新请求时顺带清理超过该时长的残留。
ADMIN_DISPOSITION_STALE_SECONDS = 24 * 3600

# ── 中断恢复保全 sidecar（interrupt-recovery-preserve D3）────────────────────
# 排水窗口到期仍需 terminate 在跑 run 时，先把受影响 spec 的 branch/worktree
# 引用落盘供 boot recovery 读取续做；正常终态无需保全（sidecar 保持为空）。
PRESERVE_SIDECAR = PROJECT_ROOT / ".fenix" / "interrupted_runs.json"
# supervisor SIGKILL 等待相对排水窗口的固定余量（D2）：保证排水期不被截断。
SUPERVISOR_KILL_MARGIN_SECONDS = 120
# supervisor_runtime.started_at 漂移判定阈值（fix-daemon-lifecycle-races 3.2）：
# 当前 daemon 启动时间戳（.fenix/daemon_started）早于 runtime.started_at 超过
# 该值，视为 runtime 文件残留自此前 supervisor 进程（当前进程未刷新上报），按
# 「未上报」处理打 WARNING。缺省 24h：daemon 自动重启循环（restart_request/
# 崩溃自愈）间隔分钟级，健康 supervisor 场景漂移远小于该阈值；长驻 supervisor
# 残留文件的漂移必然超限，恰是「文件残留自旧进程」的检出信号。
SUPERVISOR_RUNTIME_DRIFT_SECONDS = 24 * 3600


def _read_preserve_sidecar() -> list:
    """读取中断保全 sidecar（.fenix/interrupted_runs.json）。

    文件缺失/损坏（非 JSON/非列表）返回空列表且不抛错——保全信息非停机
    关键路径，读取失败按「无保全」处理。
    """
    try:
        data = json.loads(PRESERVE_SIDECAR.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_preserve_sidecar(entries: list) -> bool:
    """写中断保全 sidecar。返回 True 表示落盘成功；失败仅记调用方日志。"""
    try:
        PRESERVE_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        PRESERVE_SIDECAR.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def _clear_preserve_sidecar() -> None:
    """清空中断保全 sidecar（boot recovery 消费后调用，幂等）。"""
    try:
        PRESERVE_SIDECAR.unlink(missing_ok=True)
    except OSError:
        pass


# ── 代码陈旧检测（improve-hot-reload-robustness D4）────────────────────
# daemon 启动后代码更新（rsync/patch/checkout/未提交修改）时，进程内校验规则
# 可能是旧版；以 mtime 指纹判定并在热重载检测点提示重启。mtime 覆盖 git
# rev-parse 覆盖不了的未提交修改，worktree 友好；误报面仅"touch 无内容变化"。
_CODE_STALE_WARNED = False  # 每进程生命周期只提示一次（模块级旗标）


def code_tracked_files(project_root) -> list:
    """启动一次性 glob 受跟踪代码文件：fenixd.py + core/**/*.py（D4 缓存列表）。

    core 目录缺失（异常安装）时仍返回 fenixd.py 单项；缺失文件的 stat 由
    code_files_changed_since 忽略。
    """
    root = Path(project_root)
    files = [root / "fenixd.py"]
    core = root / "core"
    if core.is_dir():
        files.extend(sorted(core.rglob("*.py")))
    return files


def max_code_mtime_ns(files) -> int:
    """文件列表最大 st_mtime_ns（缺失忽略）；空表/全缺失返回 0。"""
    latest = 0
    for path in files:
        try:
            latest = max(latest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return latest


def code_files_changed_since(baseline_ns: int, files) -> bool:
    """纯函数：任一现存文件 mtime > baseline 即 True；文件缺失忽略。

    improve-hot-reload-robustness tasks 2.2：供 _maybe_reload_config 每轮做
    ~60 次 stat，代价可忽略；也便于单测隔离文件系统行为。
    """
    for path in files:
        try:
            if path.stat().st_mtime_ns > baseline_ns:
                return True
        except OSError:
            continue
    return False


class FenixDaemon:
    """Main daemon process for the Fenix Loop Engineering Framework."""

    def __init__(self):
        self.running = False
        self.config = None
        self.logger = None
        self.state_machine = None
        self.event_bus = None
        self.worktree_manager = None
        self.agent_runner = None
        self.admin_store = None
        self.admin_monitor = None
        self._admin_thread = None
        # Administrator 后台执行 worker 池（fix-admin-run-blocks-mainloop D1/D6）：
        # 处置移出主循环，主循环只拾取与投递；admin.workers=0 回退同步行为。
        self._admin_executor = None
        self._admin_pool_lock = threading.Lock()
        self._admin_pool_stats = {"submitted": 0, "completed": 0, "failed": 0}
        self.pm_engine = None
        self.hook_engine = None

    def initialize(self):
        """Load config and initialize all components."""
        # 1. Load configuration（有效配置：用户级 ~/.fenix/config.yaml + 项目级
        #    .fenix/config.yaml 深合并；任一或全部缺失都允许，内置默认兜底）
        self.config = ConfigLoader.resolve_config(PROJECT_ROOT)

        # 2. Initialize logger
        log_dir = PROJECT_ROOT / self.config.get("logging.dir", ".fenix/logs")
        log_level = self.config.get("logging.level", "INFO")
        self.logger = Logger(log_dir, log_level)
        self.logger.info("fenixd", "Initializing Fenix Loop Engineering Framework...")

        # 3. Initialize StateMachine（状态文件在 .fenix/ 下，.STATE.md.lock 随同目录）
        state_path = PROJECT_ROOT / ".fenix" / "STATE.md"
        self.state_machine = StateMachine(state_path, self.logger)
        self.logger.info("fenixd", "StateMachine initialized")

        # 4. Initialize WorktreeManager
        wt_base = PROJECT_ROOT / self.config.get("worktree.base_dir", ".claude/worktrees")
        self.worktree_manager = WorktreeManager(wt_base, PROJECT_ROOT, self.logger)
        self.logger.info("fenixd", "WorktreeManager initialized")

        # 5. Initialize AgentRunner
        self.agent_runner = AgentRunner(
            self.config,
            self.worktree_manager,
            self.state_machine,
            PROJECT_ROOT,
            self.logger,
        )
        self.logger.info("fenixd", "AgentRunner initialized")

        # 5.5. Initialize AdminStore + AdminMonitor（零成本健康监视 + 困境唤起）
        self.admin_store = AdminStore(PROJECT_ROOT, self.logger)
        self.admin_monitor = AdminMonitor(
            self.config,
            self.state_machine,
            PROJECT_ROOT,
            self.logger,
            store=self.admin_store,
            agent_runner=self.agent_runner,
        )
        if self.admin_monitor.enabled:
            self.logger.info(
                "fenixd",
                "AdminMonitor initialized "
                f"(interval: {self.admin_monitor.interval_minutes}m, "
                f"cooldown: {self.admin_monitor.cooldown_minutes}m)",
            )
        else:
            self.logger.info("fenixd", "AdminMonitor disabled (admin.enabled: false)")

        # 5.6. Administrator 后台 worker 池（fix-admin-run-blocks-mainloop D1/D6）：
        # 处置在 worker 线程执行，主循环 1s 粒度调度不再被阻塞；多个 worker 可并行
        # 执行多个 admin run（用户决策：不建 worktree、容忍主树写冲突风险）。
        # admin.workers=0 → 不启用后台池，回退主循环内同步执行（逃生门）。
        admin_workers = int(ConfigLoader.get(self.config, "admin.workers", 2) or 0)
        if admin_workers > 0:
            self._admin_executor = ThreadPoolExecutor(
                max_workers=admin_workers,
                thread_name_prefix="fenixd-admin-run",
            )
            self.logger.info(
                "fenixd",
                f"Admin run worker pool started (max_workers: {admin_workers})",
            )
        else:
            self._admin_executor = None
            self.logger.info(
                "fenixd",
                "Admin run worker pool disabled (admin.workers: 0) — synchronous fallback",
            )

        # 6. Initialize PMEngine
        self.pm_engine = PMEngine(
            self.state_machine,
            self.agent_runner,
            self.config,
            PROJECT_ROOT,
            self.logger,
        )
        self.logger.info("fenixd", "PMEngine initialized")

        # 6.5 Initialize HookEngine（add-spec-hooks：SPEC 状态事件 hook 引擎）。
        # 配置从共享 config 对象实时读取（30s 热更新自动生效）；失败告警复用
        # admin_store 站内告警通道。实例化后注入 EventBus 作为 hook_dispatcher。
        self.hook_engine = HookEngine(
            PROJECT_ROOT,
            self.config,
            self.logger,
            admin_store=self.admin_store,
        )
        self.logger.info("fenixd", "HookEngine initialized")

        # 7. Initialize EventBus (last, as it triggers the PM Engine)
        self.event_bus = EventBus(
            state_path,
            self.state_machine,
            self.pm_engine,
            self.config,
            self.logger,
            hook_dispatcher=self.hook_engine.dispatch,
        )
        self.logger.info("fenixd", "EventBus initialized")

        self.logger.info("fenixd", "All components initialized successfully")

        # 记录启动时配置文件 mtime，供主循环热更新检测基线
        self._config_snapshot = self._config_mtimes()

        # 代码陈旧检测 baseline（improve-hot-reload-robustness D4）：一次性 glob
        # fenixd.py + core/**/*.py 缓存文件列表并取 max st_mtime_ns。热重载检测点
        # （_maybe_reload_config）据此判定磁盘代码较启动时更新 → 每进程一次 WARNING。
        self._code_files = code_tracked_files(FENIX_DIR)
        self._code_baseline_ns = max_code_mtime_ns(self._code_files)

    def start(self):
        """Start the daemon main loop."""
        self.running = True
        self.logger.info("fenixd", f"fenixd starting (PID: {os.getpid()})")

        # Scan initial state
        self.logger.info("fenixd", "Performing initial STATE.md scan...")

        # ── 启动终态补写扫描（fix-daemon-lifecycle-races D1）──
        # AgentRunner 已初始化、任何派发与恢复派发之前：对上次 daemon 非正常
        # 死亡（SIGKILL/断电/崩溃）遗留的无终态 run 补写 interrupted 终态。
        # daemon 刚启动时注册表为空 + 单实例锁，存量无终态 run 必为遗留死 run；
        # 孤儿 claude 进程存活不阻塞补写（run 文件由 daemon 侧转写）。sweep
        # 仅启动期执行一次，运行期不重复。异常降级 WARNING，不阻塞 daemon 启动。
        try:
            from core.agent_runner.liveness import sweep_runs_without_terminal_state
            _runs_dir = PROJECT_ROOT / ".fenix" / "runs"
            _swept = sweep_runs_without_terminal_state(_runs_dir)
            if _swept:
                self.logger.warning(
                    "fenixd",
                    f"Startup terminal-state sweep: 补写 {len(_swept)} 个遗留 "
                    f"无终态 run 的 interrupted 终态: "
                    + ", ".join(run_id for run_id, _ in _swept),
                )
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"Startup terminal-state sweep failed (non-blocking): {e}",
            )

        # ── 排水窗口一致性自检（fix-daemon-lifecycle-races D2）──
        # supervisor SIGKILL 等待窗口 vs 排水窗口；不一致/旧进程 → WARNING。
        try:
            self._check_supervisor_drain_consistency()
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"Supervisor drain consistency check failed (non-blocking): {e}",
            )

        # 启动清理孤儿 worktree（fix-fenix-token-waste）：上次异常退出的残留。
        # 锁治理（improve-run-lifecycle-governance D4）：清理前先以进程表重建在册锁
        # —— 孤儿 attempt 进程仍存活的 worktree 会被跳过并重建登记，不被误删。
        self.worktree_manager.refresh_locks()

        # ── 恢复保留判定先于孤儿清理（interrupt-recovery-preserve D6）──
        # recover_interrupted 的保留续做会把保全在册的 worktree（在场或重建）
        # 登记进活动集；先于 cleanup_stale_worktrees 完成，使孤儿清理自然跳过
        # 被保全引用的 worktree——清理与保全永不互删。
        # verify_redo_budget（fix-daemon-lifecycle-races D3）：重启恢复重验的
        # 预算阈值，缺省 3；恢复路径据此决定重验派发或冻结等待人工裁决。
        _redo_budget = int(ConfigLoader.get(self.config, "agents.verify_redo_budget", 3) or 3)
        self.state_machine.recover_interrupted(
            PROJECT_ROOT, self.worktree_manager, verify_redo_budget=_redo_budget)
        # 消费后的保全 sidecar 清除（幂等；中断全部由 recovery 接管）
        _clear_preserve_sidecar()

        self.worktree_manager.cleanup_stale_worktrees()

        # add-worktree-test-server（D2 启动清扫）：上次异常退出遗留的 dev-server 进程
        # 在 daemon 重启时早已失活（worktree 已清），需按命令行标记回收端口。
        v2_cleanup_orphans(self.logger)

        # verify-process-lifecycle（D6 启动收割）：上轮 daemon 崩退时登记者全部
        # 视为非在飞——servers.json 中进程仍存活的登记实例按 /proc liveness 收割。
        self._sweep_verify_serving_registry(use_in_flight=False)

        # Start event bus monitoring——必须先于 initial full_scan：
        # start() 会建立 STATE 基线快照（_update_known_state），若首扫先行，
        # _known_specs 为空，全部存量 SPEC 被判为「新出现」，pushed 等 hook
        # 事件被全量重放（2026-09-07：重启后 15+ pushed spec 的 commit-push
        # hook 连环触发，因 index.lock 冲突失败才未酿成连环误提交）。
        self.event_bus.start()

        # 恢复上次异常退出遗留的中断状态（implementing/testing → ready）。
        # recover_interrupted 此前定义了但从未被调用，导致 daemon 重启后卡死的
        # spec 永远不被重新调度（fix-fenix-token-waste）；保留判定已在上面与
        # 孤儿清理协同完成。
        self.event_bus.full_scan()

        # 启动 Administrator 监视线程（admin.enabled 时；间隔见 admin.interval_minutes）
        if self.admin_monitor and self.admin_monitor.enabled:
            self._admin_thread = threading.Thread(
                target=self._admin_monitor_loop,
                name="fenixd-admin-monitor",
                daemon=True,
            )
            self._admin_thread.start()
            self.logger.info("fenixd", "Admin monitor thread started")

        # Main loop — keep the process alive + 配置热更新轮询
        self.logger.info("fenixd", "Entering main loop")
        config_check_ts = time.time()
        recovery_watch_ts = time.time()
        # add-spec-archive D4：自动归档独立计时（300s，对齐配置热更新/恢复复查模式）
        archive_check_ts = time.time()
        # verify-process-lifecycle（D4/D6 周期清扫）：dev-server 孤儿 + 登记制
        # command 实例回收的独立计时（600s ≤ 规格 10 分钟上限）
        orphan_clean_ts = time.time()
        # add-spec-scheduling-controls D3：定时调度到期检测独立计时（60s，
        # 对齐恢复复查/recovery watch 模式：try/except 记日志不中断主循环）。
        scheduling_check_ts = time.time()
        try:
            while self.running:
                time.sleep(1)
                # 手动唤起 Admin 文件信号拾取（add-spec-manual-admin-invoke）：
                # dashboard 写入 .fenix/admin_invoke_request.json，主循环下一轮
                # （≤2s）扫描并立即唤起 Administrator，处理完即删。
                try:
                    self._check_admin_invoke_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"admin_invoke pickup failed: {e}")
                # run 人工取消文件信号拾取（add-run-cancel D5）：
                # dashboard 写入 .fenix/cancel_run_request.json，主循环下一轮
                # 消费并调 agent_runner.cancel_run（只设旗标，微秒级，不投 worker 池）。
                try:
                    self._check_cancel_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"cancel_run pickup failed: {e}")
                # 清空定时拾取即派发信号（2026-09-08 清空 start_after 后等 30min
                # recovery 才派发事故的 API 侧修复）：dashboard 清空 start_after
                # 时写入 .fenix/scheduling_kick_request.json，主循环下一轮（≤2s）
                # 消费并唤起派发。
                try:
                    self._check_scheduling_kick_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"scheduling_kick pickup failed: {e}")
                # 配置热更新：每 30s 检查配置文件 mtime，变更则原地重载
                if time.time() - config_check_ts >= 30:
                    config_check_ts = time.time()
                    try:
                        self._maybe_reload_config()
                    except Exception as e:
                        self.logger.error("fenixd", f"Config hot-reload failed: {e}")
                # 恢复闭环复查（improve-run-lifecycle-governance D6）：每分钟检查
                # 到期的观察项——followup 窗口（默认 15m）短于全量扫描间隔，
                # 不能只依赖 event_bus 的 full_scan 触发。
                if time.time() - recovery_watch_ts >= 60:
                    recovery_watch_ts = time.time()
                    try:
                        self.pm_engine.check_recovery_watch()
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Recovery watch check failed: {e}")
                    # 滞留 autostash 兜底回收（fix-autostash-orphans）：主树干净且
                    # 无活跃 run 时，把历史上被派发前 stash 吞掉的用户改动 pop 回来。
                    try:
                        self.pm_engine.reclaim_stale_autostash_if_idle()
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Autostash reclaim check failed: {e}")
                # 自动归档周期检查（add-spec-archive D4）：每 300s 遍历项目内
                # 终态未归档 SPEC，超阈值按 updated 升序归档直至达标；异常捕获
                # 记日志不中断主循环。阈值热更新经 effective_auto_archive_threshold
                # 每轮重读，改配置立即生效。
                if time.time() - archive_check_ts >= 300:
                    archive_check_ts = time.time()
                    try:
                        from core.dashboard.data import auto_archive_check
                        auto_archive_check(PROJECT_ROOT, self.config, self.logger)
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Auto-archive check failed: {e}")
                # 定时调度到期检测（add-spec-scheduling-controls D3）：每 60s
                # 检查 auto 解冻（frozen_until 到期）与定时拾取（start_after
                # 到期唤起派发）。周期扫描（full_scan）作为兜底，二者先后到达
                # 均只触发一次（幂等由写前重读 STATE 保证）。
                if time.time() - scheduling_check_ts >= 60:
                    scheduling_check_ts = time.time()
                    try:
                        self.pm_engine.check_scheduling_deadlines()
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Scheduling deadlines check failed: {e}")
                # verify-process-lifecycle（D4 周期清扫）：孤儿泄漏可见窗口
                # ≤ 一个周期（600s）。覆盖 dev-server 与 servers.json 登记实例；
                # 首轮启动清扫已处理存量，此后周期性兜底。
                if time.time() - orphan_clean_ts >= 600:
                    orphan_clean_ts = time.time()
                    try:
                        v2_cleanup_orphans(self.logger)
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Periodic V2 orphan cleanup failed: {e}")
                    try:
                        self._sweep_verify_serving_registry()
                    except Exception as e:
                        self.logger.error(
                            "fenixd", f"Periodic serving registry sweep failed: {e}")
        except KeyboardInterrupt:
            self.logger.info("fenixd", "Received interrupt signal")
        finally:
            self.shutdown()

    def _is_spec_in_flight(self, spec_name: str) -> bool:
        """spec 是否在飞（验证活跃）：状态为 testing 视作在飞。

        serving 实例（command 型）在验证期由 `_ensure_app_reachable` 启动，
        spec 全程处于 testing；终局（done/verified/bug-found）后状态离开
        testing → 该实例成为收割候选。
        """
        try:
            entry = self.state_machine.read_one(spec_name) or {}
            return entry.get("status") == "testing"
        except Exception:
            return False

    def _sweep_verify_serving_registry(self, use_in_flight: bool = True) -> None:
        """servers.json 登记制收割：无在飞 spec 但进程仍存活的登记项。

        启动清扫（use_in_flight=False：前一轮 daemon 已死，登记者全部视为
        非在飞，一律按 liveness 收割）与周期清扫（use_in_flight=True：按
        spec 状态判定在飞，testing 中的保留）共用同一执行器。
        """
        from core.serving_registry import sweep as serving_sweep
        kw = ({"is_spec_in_flight": self._is_spec_in_flight}
              if use_in_flight else {})
        serving_sweep(PROJECT_ROOT, self.logger, **kw)

    def _config_mtimes(self):
        """两个配置文件的当前 mtime（不存在计为 None）。"""
        from core.config import USER_CONFIG_DIR
        mtimes = []
        for p in (USER_CONFIG_DIR / "config.yaml", PROJECT_ROOT / ".fenix" / "config.yaml"):
            try:
                mtimes.append(p.stat().st_mtime_ns)
            except OSError:
                mtimes.append(None)
        return tuple(mtimes)

    def _maybe_reload_config(self):
        """配置文件 mtime 变化时热加载：原地更新共享 config dict，组件自动看到新值。

        校验失败保留旧值并告警；成功则刷新 admin_cfg 快照。每次调用顺带执行
        代码陈旧检测（improve-hot-reload-robustness tasks 2.3）：磁盘代码 mtime
        超启动 baseline → 每进程一次 WARNING 提示重启。
        """
        self._warn_stale_code_once()
        current = self._config_mtimes()
        if current == getattr(self, "_config_snapshot", None):
            return
        ConfigLoader.resolve_config_into(self.config, PROJECT_ROOT)
        # admin_monitor 的 admin_cfg 是启动快照，同步刷新
        if self.admin_monitor is not None:
            from core.config import ConfigLoader as _CL
            self.admin_monitor.admin_cfg = _CL.get_admin_config(self.config)
        # admin.workers 变更不热生效（worker 池在启动时定型）：提示重启后生效
        if self._admin_executor is not None:
            workers = int(ConfigLoader.get(self.config, "admin.workers", 2) or 0)
            if workers != self._admin_executor._max_workers:  # noqa: SLF001 只读探测
                self.logger.info(
                    "fenixd",
                    f"admin.workers 变为 {workers}，worker 池大小在 daemon 重启后生效"
                    f"（当前 {self._admin_executor._max_workers}）",
                )
        self._config_snapshot = current
        self.logger.info(
            "fenixd",
            "Configuration hot-reloaded (user/project config.yaml changed)",
        )

    def _warn_stale_code_once(self):
        """磁盘代码较启动 baseline 更新 → 提示重启（每进程生命周期一次）。

        improve-hot-reload-robustness tasks 2.3 / D4：进程内校验规则可能为旧版，
        未知键白名单等演进不会自动生效，需重启 daemon。mtime 指纹误报面仅
        "touch 无内容变化"，且每进程只提示一次，噪音可控。
        """
        global _CODE_STALE_WARNED
        if _CODE_STALE_WARNED:
            return
        baseline = getattr(self, "_code_baseline_ns", None)
        files = getattr(self, "_code_files", None)
        if baseline is None or not files:
            return
        try:
            changed = code_files_changed_since(baseline, files)
        except Exception:  # noqa: BLE001 — 陈旧检测非关键路径，失败静默跳过
            return
        if not changed:
            return
        _CODE_STALE_WARNED = True
        self.logger.warning(
            "fenixd",
            "检测到磁盘代码较进程启动时已更新（fenixd.py/core/**/*.py mtime 超 "
            "baseline），进程内校验规则可能为旧版，建议重启 daemon 生效"
            "（touch .fenix/restart_request）",
        )

    def _admin_monitor_loop(self):
        """周期运行健康检查（间隔 admin.interval_minutes）。

        启动首轮立即执行（add-alert-auto-resolve D4）：首轮扫描对存量
        handled=False 告警执行一次回填闭环判定，其后按间隔轮询。
        """
        interval = max(float(self.admin_monitor.interval_minutes), 0.5)
        while self.running:
            try:
                self.admin_monitor.run_once()
            except Exception as e:
                self.logger.error("admin_monitor", f"Admin monitor check failed: {e}")
            time.sleep(interval * 60)
            if not self.running:
                break

    def _check_admin_invoke_requests(self):
        """主循环每轮扫描手动唤起 Admin 的文件信号并投递后台执行。

        dashboard 的 /api/spec-admin-invoke 会原子写入
        .fenix/admin_invoke_request.json（含 spec/source/created）；本方法在
        主循环（1s 粒度）中检测其存在：读取→删除→构造 manual-intervention 信号
        →投递 worker 池（fix-admin-run-blocks-mainloop：处置移出主循环，拾取后
        本扫描周期内继续后续工作）。与 admin_monitor 自动检测共存：二者各自走
        store 记录与节流锚点，互不吞并。

        投递被拒（executor 已关闭等）时不丢痕——写一条 failed disposition 到
        admin_store 记录原因，供前端时间线/告警可见，且请求文件已删避免反复重试。
        """
        req_path = PROJECT_ROOT / ".fenix" / "admin_invoke_request.json"
        if not req_path.exists():
            return
        try:
            with req_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 损坏的信号文件：删除避免每轮报错卡死
            try:
                req_path.unlink()
            except OSError:
                pass
            return
        # 先读后删：删除失败（被并发消费）则本次跳过，下一轮再试
        try:
            req_path.unlink()
        except OSError:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "admin_invoke 请求缺少 spec，忽略")
            return

        signal = {
            "signal_type": "manual-intervention",
            "spec": spec,
            "severity": "major",
            "source": payload.get("source", "manual"),
            "created": payload.get("created"),
            # 用户在 Dashboard 处置弹窗输入的提示词（prompt）优先；缺省用默认文案
            "description": (
                payload.get("prompt")
                or f"人工呼叫：检查 SPEC {spec} 出现什么问题并尝试处置"
            ),
        }
        self.logger.info(
            "fenixd",
            f"手动唤起 Administrator 处置 SPEC {spec}（manual-intervention）",
        )
        # 顺带清扫残留的处置状态实例文件（tasks 1.3）：run 异常中断可能遗留
        # admin_disposition-<run_id>.json，无功能影响但会累积。
        self._sweep_stale_admin_dispositions()
        self._submit_admin_run(signal)

    # ── run 人工取消信号消费（add-run-cancel D5）────────────────────

    def _check_cancel_requests(self):
        """主循环每轮扫描 run 取消的文件信号并消费（不投 worker 池）。

        dashboard 写入 .fenix/cancel_run_request.json（含 run_id/reason/source/
        created）；本方法在主循环（1s 粒度）中检测其存在：读取→删除→校验
        run_id 非空→调 agent_runner.cancel_run(run_id, reason, by=source)。
        与 _check_admin_invoke_requests 同构：损坏 JSON 删除防卡死；删除失败
        下轮再试。
        """
        req_path = PROJECT_ROOT / ".fenix" / "cancel_run_request.json"
        if not req_path.exists():
            return
        try:
            with req_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 损坏的信号文件：删除避免每轮报错卡死
            try:
                req_path.unlink()
            except OSError:
                pass
            return
        # 先读后删：删除失败（被并发消费）则本次跳过，下一轮再试
        try:
            req_path.unlink()
        except OSError:
            return

        run_id = payload.get("run_id")
        if not run_id:
            self.logger.warning("fenixd", "cancel_run 请求缺少 run_id，忽略")
            return

        reason = payload.get("reason", "")
        source = payload.get("source", "dashboard")
        self.logger.info(
            "fenixd",
            f"消费 run 取消信号：run_id={run_id}, reason={reason!r}, source={source}",
        )
        try:
            result = self.agent_runner.cancel_run(run_id, reason=reason, by=source)
            self.logger.info(
                "fenixd",
                f"cancel_run 结果：{result}",
            )
        except Exception as e:
            self.logger.error(
                "fenixd",
                f"cancel_run 调用失败 run_id={run_id}: {e}",
            )

    def _check_scheduling_kick_requests(self):
        """主循环每轮扫描「清空定时拾取即派发」的文件信号并消费。

        dashboard 的 /api/spec-start-after 在清空 start_after（value=null）时
        原子写入 .fenix/scheduling_kick_request.json（含 spec/action/created）；
        本方法在主循环（1s 粒度）中检测其存在：读取→删除→按 spec 当前状态
        唤起 _on_spec_ready / _on_spec_drafted（与 check_scheduling_deadlines
        的到期拾取同语义）→立即 _process_queue。与 _check_cancel_requests
        同构：损坏 JSON 删除防卡死；删除失败下轮再试。

        spec 已不在 STATE.md（已归档/删除）时仍删信号防反复报错；spec 处于
        终态或派发中时由 _on_spec_ready 内部谓词自然拦截（幂等，无需此处
        重复校验——2026-09-08 清空 start_after 后等 30min recovery 才派发事故
        的 API 侧修复）。
        """
        req_path = PROJECT_ROOT / ".fenix" / "scheduling_kick_request.json"
        if not req_path.exists():
            return
        try:
            with req_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 损坏的信号文件：删除避免每轮报错卡死
            try:
                req_path.unlink()
            except OSError:
                pass
            return
        # 先读后删：删除失败（被并发消费）则本次跳过，下一轮再试
        try:
            req_path.unlink()
        except OSError:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "scheduling_kick 请求缺少 spec，忽略")
            return
        if self.pm_engine is None:
            self.logger.warning("fenixd", "pm_engine 未初始化，丢弃 scheduling_kick 请求")
            return

        entry = self.pm_engine.state_machine.read_one(spec)
        if not entry:
            self.logger.info(
                "fenixd",
                f"消费 scheduling_kick 信号：spec '{spec}' 已不存在，丢弃",
            )
            return
        status = entry.get("status")
        self.logger.info(
            "fenixd",
            f"消费 scheduling_kick 信号：唤起 spec '{spec}'（status={status}）",
        )
        try:
            if status == "drafted":
                # drafted 走晋升链（lint 拦截/error 写回由 _on_spec_drafted 自理）
                self.pm_engine._on_spec_drafted(spec)
            else:
                self.pm_engine._on_spec_ready(spec)
            # 唤起后立即处理派发队列，对齐 check_scheduling_deadlines 的到期拾取
            self.pm_engine._process_queue()
        except Exception as e:
            self.logger.error(
                "fenixd",
                f"scheduling_kick 唤起 '{spec}' 失败（full_scan 兜底）: {e}",
            )

    def _submit_admin_run(self, signal: dict) -> bool:
        """把一次 Administrator 处置投递到后台 worker 池（D1/D2）。

        admin.workers=0（未启用后台池）时回退主循环内同步执行，保持既有行为
        （逃生门）。投递被拒（executor 已关闭等 RuntimeError）落 failed
        disposition 不丢痕。

        Returns:
            True = 已投递（或同步执行完成）；False = 投递被拒绝。
        """
        spec = signal.get("spec")
        if self._admin_executor is None:
            self._execute_admin_disposition(signal)
            return True
        try:
            self._admin_executor.submit(self._admin_run_worker, signal)
        except RuntimeError as e:
            self.logger.error(
                "fenixd",
                f"Administrator 处置投递被拒绝（SPEC {spec}）：{e}",
            )
            self._record_failed_admin_disposition(spec, f"投递被拒绝：{e}")
            return False
        with self._admin_pool_lock:
            stats = dict(self._admin_pool_stats)
            stats["submitted"] += 1
            self._admin_pool_stats = stats
        queued = stats["submitted"] - stats["completed"] - stats["failed"]
        self.logger.info(
            "fenixd",
            f"Administrator 处置已投递后台（SPEC {spec}，"
            f"已提交 {stats['submitted']}，排队中 {queued}）",
        )
        return True

    def _admin_run_worker(self, signal: dict):
        """worker 线程体：执行一次处置并维护池计数（D4）。

        catch-all：单次处置异常不得影响 worker 线程领取后续任务（spec「后台
        处置失败不丢痕」）——异常在 _execute_admin_disposition 内落 failed
        disposition 并返回 False，此处只兜底统计与日志。
        """
        spec = signal.get("spec")
        try:
            ok = self._execute_admin_disposition(signal)
        except Exception as e:  # noqa: BLE001 — worker 兜底，防线程带病退出
            self.logger.error(
                "fenixd",
                f"Administrator 后台处置异常（SPEC {spec}）：{e}",
            )
            self._record_failed_admin_disposition(spec, str(e))
            with self._admin_pool_lock:
                self._admin_pool_stats["failed"] += 1
            return
        with self._admin_pool_lock:
            self._admin_pool_stats["completed" if ok else "failed"] += 1
        if ok:
            self.logger.info("fenixd", f"Administrator 处置完成（SPEC {spec}）")

    def _execute_admin_disposition(self, signal: dict) -> bool:
        """执行一次 Administrator 处置并保持既有落痕语义（主循环回退/worker 共用）。

        fix-manual-admin-disposition-finalize：走 AdminMonitor 公共入口而非直接调
        run_administrator——后者开头落的 pending disposition 需要在返回后由
        _invoke_administrator 落最终记录终结。异常不外抛：落 failed disposition
        （不丢痕）后返回 False。
        """
        spec = signal.get("spec")
        try:
            if self.admin_monitor is not None:
                self.admin_monitor.invoke_manual(signal)
            else:
                self.agent_runner.run_administrator(signal)
            return True
        except Exception as e:
            self.logger.error(
                "fenixd",
                f"手动唤起 Administrator 失败（SPEC {spec}）：{e}",
            )
            self._record_failed_admin_disposition(spec, str(e))
            return False

    def _record_failed_admin_disposition(self, spec, reason: str):
        """落一条 failed disposition（不丢痕，供 admin 活动区/告警可见）。"""
        try:
            self.admin_store.append({
                "kind": DISPOSITION,
                "status": "failed",
                "signal_type": "manual-intervention",
                "spec": spec,
                "admin_run_id": None,
                "description": f"手动唤起 Administrator 处理 SPEC {spec} 时出错：{reason}",
                "result": "failed",
            })
        except Exception:  # noqa: BLE001 — 落痕失败不影响主流程
            pass

    def _sweep_stale_admin_dispositions(self):
        """清理超时的残留处置状态实例文件（tasks 1.3）。

        run 异常中断（daemon 被杀等）时 .fenix/admin_disposition-<run_id>.json
        可能残留；无功能影响（每个实例按 run_id 读写），但会无限累积。旧全局
        文件 admin_disposition.json 已不再读写，存在即视为残留一并清理。
        """
        fenix_dir = PROJECT_ROOT / ".fenix"
        cutoff = time.time() - ADMIN_DISPOSITION_STALE_SECONDS
        try:
            candidates = list(fenix_dir.glob(ADMIN_DISPOSITION_GLOB))
            legacy = fenix_dir / "admin_disposition.json"
            if legacy.exists():
                candidates.append(legacy)
        except OSError:
            return
        for path in candidates:
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
                self.logger.info(
                    "fenixd",
                    f"清理残留处置状态文件：{path.name}（超过 24h 未消费）",
                )
            except OSError:
                continue

    def _shutdown_drain_seconds(self) -> int:
        """规划性重启排水窗口（admin.shutdown_drain_seconds，缺省 1800，0=现行快速停机）。

        interrupt-recovery-preserve D1：非法值（负/非数字）回退缺省；0 显式回退
        现行快速停机（不排水、不保全）。
        """
        raw = ConfigLoader.get(self.config, "admin.shutdown_drain_seconds", 1800)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            self.logger.error(
                "fenixd",
                f"admin.shutdown_drain_seconds 非法（应为非负整数）: {raw!r}，回退 1800",
            )
            return 1800
        return max(0, value)

    def _drain_log_waiting(self) -> list:
        """排水开始日志 + 等待的 run 清单（interrupt-recovery-preserve 4.3）。"""
        if not self.agent_runner:
            return []
        running = self.agent_runner.running_run_ids()
        if running:
            self.logger.info(
                "fenixd",
                f"Drain: waiting for running agents to finish: {running}",
            )
        else:
            self.logger.info("fenixd", "Drain: no running agents to wait for")
        return running

    def _check_supervisor_drain_consistency(self) -> None:
        """启动自检：supervisor SIGKILL 等待窗口与 daemon 排水窗口的一致性。

        fix-daemon-lifecycle-races（D2）：排水窗口（shutdown_drain_seconds）
        必须被 supervisor 的 SIGKILL 等待覆盖，否则排水期被强杀截断、在途 run
        永久无终态（09-05 实证）。supervisor 每次启动把等待窗口写入
        `.fenix/supervisor_runtime.json`；此处读取并比对：
          - 文件缺失 → 旧代码 supervisor 进程未升级（8/26 实证场景）；
          - sigkill_wait < drain + 120 → supervisor 配置陈旧/计算口径漂移；
          - started_at 与本次 daemon 启动时间戳（daemon_started）漂移超阈值
            → runtime 文件残留自此前 supervisor 进程。
        任一命中 → logger WARNING + 项目日志（提示重启 supervisor）；一致配置
        静默通过。drain≤0（现行快速停机）时无需比对，直接返回。
        """
        drain_seconds = self._shutdown_drain_seconds()
        if drain_seconds <= 0:
            return
        runtime_path = PROJECT_ROOT / ".fenix" / "supervisor_runtime.json"
        warnings = []
        if not runtime_path.is_file():
            warnings.append(
                f"supervisor 未上报 SIGKILL 等待窗口（.fenix/supervisor_runtime.json "
                f"缺失）——疑似旧代码 supervisor 进程，排水窗口 {drain_seconds}s 可能被 "
                f"SIGKILL 截断，建议重启 supervisor"
            )
        else:
            try:
                data = json.loads(runtime_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                warnings.append(
                    f"supervisor runtime 解析失败（{e}）——按未上报处理，建议重启 "
                    f"supervisor 刷新上报"
                )
                data = {}
            if not warnings and isinstance(data, dict):
                try:
                    sigkill_wait = int(data.get("sigkill_wait") or 0)
                except (TypeError, ValueError):
                    sigkill_wait = 0
                if sigkill_wait < drain_seconds + SUPERVISOR_KILL_MARGIN_SECONDS:
                    warnings.append(
                        f"supervisor SIGKILL 等待窗口 {sigkill_wait}s < 排水窗口 "
                        f"{drain_seconds}s + 余量 {SUPERVISOR_KILL_MARGIN_SECONDS}s —— "
                        f"排水期可能被截断，建议重启 supervisor 使配置生效"
                    )
                # started_at 与 daemon_started 漂移判定（残留自旧进程）
                daemon_started = PROJECT_ROOT / ".fenix" / "daemon_started"
                drift_error = None
                try:
                    runtime_ts = datetime.fromisoformat(
                        str(data.get("started_at") or "")).timestamp()
                    daemon_ts = datetime.fromisoformat(
                        daemon_started.read_text(encoding="utf-8").strip()
                    ).timestamp()
                    if runtime_ts and daemon_ts and daemon_ts - runtime_ts > SUPERVISOR_RUNTIME_DRIFT_SECONDS:
                        drift_error = (
                            f"supervisor runtime 上报于 {data.get('started_at')}，"
                            f"早于本次 daemon 启动 {SUPERVISOR_RUNTIME_DRIFT_SECONDS}s 以上"
                        )
                except (ValueError, OSError, TypeError):
                    drift_error = None  # 时间戳不可解析时不判定漂移
                if drift_error:
                    warnings.append(
                        f"{drift_error}——疑似 runtime 文件残留自此前 supervisor 进程，"
                        f"建议重启 supervisor 刷新上报"
                    )
        for w in warnings:
            self.logger.warning("fenixd", w)
            try:
                if self.pm_engine is not None:
                    self.pm_engine._append_project_log(f"⚠️ {w}")
            except Exception:
                pass

    def _preserve_interrupted_runs(self, run_ids: list, reason: str) -> list:
        """排水超时 terminate 前保全在跑 run 的 spec 上下文到 sidecar（D3）。

        对每个仍存活的 in-flight run，解析其 spec 名并从 STATE 取 branch，
        组装保全条目（spec/run_id/branch/worktree/ahead_commits/reason/timestamp）
        写入 ``.fenix/interrupted_runs.json``。写入失败降级 WARNING 不阻塞停机。
        ``ahead_commits`` 以 ``git rev-list --count main..<branch>`` 为据（recovery
        保留判定同口径）；worktree 以 git worktree 注册为据。

        Returns: 已登记保全的 worktree 路径列表（供 cleanup_orphans 保护集）。
        """
        entries = list(_read_preserve_sidecar())
        seen_wt = {e.get("worktree") for e in entries if e.get("worktree")}
        for run_id in run_ids:
            spec = self._spec_from_run_id(run_id)
            if not spec:
                self.logger.warning(
                    "fenixd",
                    f"Preserve: cannot parse spec from run_id '{run_id}' — skip",
                )
                continue
            entry = self.state_machine.read_one(spec) or {}
            branch = entry.get("branch")
            worktree = ""
            if branch and self.worktree_manager:
                wt = self.worktree_manager.find_worktree_path(branch)
                worktree = str(wt) if wt else ""
                if wt:
                    seen_wt.add(str(wt))
            ahead = 0
            if branch:
                try:
                    res = subprocess.run(
                        ["git", "-C", str(PROJECT_ROOT), "rev-list", "--count",
                         f"main..{branch}"],
                        capture_output=True, text=True, timeout=15,
                    )
                    if res.returncode == 0:
                        try:
                            ahead = int(res.stdout.strip() or "0")
                        except ValueError:
                            ahead = 0
                except (subprocess.TimeoutExpired, OSError):
                    ahead = 0
            entries.append({
                "spec": spec,
                "run_id": run_id,
                "branch": branch or "",
                "worktree": worktree,
                "ahead_commits": ahead,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            self.logger.warning(
                "fenixd",
                f"Preserving interrupted run '{run_id}' (spec '{spec}', "
                f"branch '{branch or 'none'}', worktree '{worktree or 'none'}', "
                f"ahead={ahead})",
            )
        if not _write_preserve_sidecar(entries):
            self.logger.warning(
                "fenixd",
                f"Preserve sidecar write failed (non-blocking) — "
                f"{len(entries)} entry/ies not persisted",
            )
        return sorted(seen_wt)

    @staticmethod
    def _spec_from_run_id(run_id: str) -> Optional[str]:
        """run_id（``<prefix>-<spec>-<ts>-a<attempt>`` 或无 attempt 后缀）→ spec 名。

        与 worktree_manager._spec_from_worktree_name 对称：spec 名可含连字符，
        取前缀之后、末段时间戳之前的部分。run_id 附 ``-a<attempt>`` 时先剥掉。
        """
        if not run_id:
            return None
        rid = run_id
        for prefix in ("impl", "verify", "repair"):
            if rid.startswith(f"{prefix}-"):
                rest = rid[len(prefix) + 1:]
                break
        else:
            return None
        if "-a" in rest:
            rest = rest.rsplit("-a", 1)[0]
        parts = rest.rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1].isdigit():
            return parts[0]
        return None

    def shutdown(self):
        """Graceful shutdown."""
        self.logger.info("fenixd", "Shutting down...")
        self.running = False

        # 关闭期间禁止派发新 agent（fix-admin-self-heal）：
        # 否则 wait_for_running_agents 等待期间 dispatcher 持续起新 agent，
        # 造成「杀一个又起一个」的关闭死循环
        if self.pm_engine:
            self.pm_engine.shutting_down = True

        if self._admin_thread:
            self._admin_thread.join(timeout=5)
        # Administrator worker 池优雅关闭（fix-admin-run-blocks-mainloop tasks 2.3）：
        # 取消排队中任务、不等待在途处置——在途 run 由 pending disposition 标记
        # 可追溯，其 claude 子进程随后被 wait_for_running_agents 终止（interrupted
        # 标记 → 巡检按已知中断终结 pending，不升级人工）。
        if self._admin_executor is not None:
            try:
                self._admin_executor.shutdown(wait=False, cancel_futures=True)
            except Exception as e:
                self.logger.error("fenixd", f"Admin worker pool shutdown failed: {e}")
            with self._admin_pool_lock:
                stats = dict(self._admin_pool_stats)
            in_flight = max(0, stats["submitted"] - stats["completed"] - stats["failed"])
            if in_flight:
                self.logger.info(
                    "fenixd",
                    f"Admin worker pool shutdown: {in_flight} 处置在途，由 pending "
                    f"disposition 标记可追溯",
                )
        if self.event_bus:
            self.event_bus.stop()

        # ── 规划性重启排水（interrupt-recovery-preserve D1/D4）──
        # restart_request 在册 = 规划性重启（supervisor 协议唯一信号源）→ 排水
        # 模式：禁新派发（shutting_down + admin 池/event_bus 已停）+ 等待在跑 run
        # 自然终态（上限 shutdown_drain_seconds，缺省 1800）；到期仍有在跑 run →
        # 先写 sidecar 保全，再走现行 terminate 收口。非计划 SIGTERM
        #（restart_request 不在册）或 drain=0 时行为逐字节不变（快速 terminate，
        # 无保全）。
        planned_restart = (PROJECT_ROOT / ".fenix" / "restart_request").exists()
        drain_seconds = self._shutdown_drain_seconds()
        preserved_wts: list = []
        if planned_restart and drain_seconds > 0 and self.agent_runner:
            wait_list = self._drain_log_waiting()
            self.logger.info(
                "fenixd",
                f"Drain: planned restart, drain window {drain_seconds}s, "
                f"waiting runs: {wait_list}",
            )
            start_ts = time.time()
            remaining = self.agent_runner.drain_wait(timeout=drain_seconds)
            self.logger.info(
                "fenixd",
                f"Drain finished after {time.time() - start_ts:.0f}s, "
                f"remaining runs: {remaining}",
            )
            if remaining:
                # 排水超时：先保全再 terminate（sidecar 先于 terminate）
                preserved_wts = self._preserve_interrupted_runs(
                    remaining, "drain timeout")
        else:
            self.logger.debug(
                "fenixd",
                f"Shutdown mode: planned={planned_restart}, "
                f"drain={drain_seconds}s → "
                f"{'drain' if planned_restart and drain_seconds > 0 else 'fast'}",
            )

        if self.agent_runner:
            # fix-graceful-shutdown-agents：wait_for_running_agents 已改为 terminate 流程
            # （SIGTERM→interrupted 标记→≤10s 缓冲→SIGKILL），默认 grace 窗口即收口，
            # 不传 timeout 以沿用 AGENT_TERMINATE_GRACE_SECONDS，确保总关停 ≪ supervisor 60s。
            # 排水到期残留 run 在此收口（sidecar 保全已先行落盘）。
            self.agent_runner.wait_for_running_agents()
            # add-worktree-test-server（D2 关闭回收）：agent 收尾后回收全部在册 dev-server，
            # 释放端口，避免遗留进程占用。
            try:
                self.agent_runner._v2_stop_all()
            except Exception as e:
                self.logger.error("fenixd", f"V2 dev-server cleanup on shutdown failed: {e}")
        if self.worktree_manager:
            # 清理协调（D6）：保全在册 worktree 传入保护集，禁止清理与保全互删
            self.worktree_manager.cleanup_orphans(protected=set(preserved_wts))

        self.logger.info("fenixd", "fenixd stopped")
        sys.exit(0)


# 单实例锁：fd 保持全局引用，进程生命周期内持有，退出时 OS 自动释放
_LOCK_FD = None


def _acquire_singleton_lock() -> None:
    """获取 daemon 单实例 flock 排他锁（fix-fenix-token-waste）。

    同一项目重复启动第二个实例时打印提示并立即退出（非零码），
    防止双 daemon 并发读取 STATE.md 造成双派发。
    """
    global _LOCK_FD
    lock_path = FENIX_DIR / "daemon.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(
            f"Fenixd 已在运行（单实例锁被持有: {lock_path}），本实例退出",
            file=sys.stderr,
        )
        sys.exit(1)
    _LOCK_FD = fd


def main():
    """Entry point for fenixd."""
    _acquire_singleton_lock()
    daemon = FenixDaemon()

    # Register signal handlers
    signal.signal(signal.SIGTERM, lambda s, f: daemon.shutdown())
    signal.signal(signal.SIGINT, lambda s, f: daemon.shutdown())

    try:
        daemon.initialize()
        daemon.start()
    except Exception as e:
        print(f"FATAL: Failed to start fenixd: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
