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
import re
import sys
import signal
import subprocess
import tempfile
import threading
import time
import json
import math
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

from core.timelib import from_epoch, parse_ts
from core.git_base_branch import resolve_base_branch
from core.config import ConfigLoader
from core.logger import Logger
from core.state_machine import StateMachine
from core.event_bus import EventBus
from core.worktree_manager import WorktreeManager
from core.agent_runner import AgentRunner
from core.agent_runner.runner import ADMIN_DISPOSITION_GLOB
from core.v2_dev_server import cleanup_orphans as v2_cleanup_orphans
from core.v2_dev_server import reconcile_v2_servers as v2_reconcile_v2_servers
# fix-scheduling-kick-single-slot D2：scheduling kick 信号载体（目录形态）定义在
# 中性模块 core.signals——daemon 消费侧与 dashboard 写入侧共用同一份常量，
# 不产生 dashboard → 根 daemon 的反向依赖。
from core.signals import SCHEDULING_KICK_DIR

# fix-scheduling-kick-single-slot D4：陈旧信号回收阈值（代码常量 1 小时，
# 对齐信号时序族）。daemon 正常运行时消费延迟 ≤ 2s（1s 主循环），超过 1 小时
# 未消费只可能是消费方缺席——此时「唤醒」已失去即时语义，退化为「下次扫描自然
# 会处理」。MUST NOT 进配置（对齐 docs/help/06-governance.md 既有记载）。
# code-review item 69d57b48a605：approve_push 车道 created 时效分档复用同判据同阈值。
# code-review item 6cc24b51f6b9：code_fix / regression_fix 手动触发车道同判据同阈值。
SCHEDULING_KICK_STALE_THRESHOLD_SECONDS = 3600
from core.wip_checkpoint import (
    ANCHOR_DRAIN_PRESERVE,
    commit_wip_checkpoint,
)
from core.admin_store import (
    AdminStore,
    DISPOSITION,
    ESCALATION,
    INFO,
    SIGNAL,
    severity_needs_human,
)
from core.admin_monitor import AdminMonitor, DISPOSITION_AUTO_RESET_SIGNAL_TYPES
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
# 保全条目 ``ahead_commits`` 的统计口径（code-review item 89d3e927d59c）：基线
# 分支与 subprocess 超时收敛为常量，两处保全路径共用一份口径，避免双处漂移。
# 基线分支不再硬编码取用（code-review item ec528621b2ec）：该值仅作探测失败
# 的回退，实际基线由 _preserve_base_branch() 经共享解析器解析得到
# （evo-fix-resume-base-branch-portability 5.1——解析器补齐本地 main/master
# 探测，无 remote 的 master 主干仓库不再回退常量）。
PRESERVE_AHEAD_BASE_BRANCH = "main"
PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS = 15


def _preserve_base_branch() -> str:
    """探测保全统计的基线分支（委托共享解析器，进程内缓存，失败回退常量）。

    code-review item ec528621b2ec：旧实现硬编码 ``main``，默认分支为
    master 等非 main 主干的仓库里 ``git rev-list --count main..<branch>``
    持续非零退出，ahead 恒按 0 口径，中断恢复的保留续做判定不命中。现委托
    ``core.git_base_branch.resolve_base_branch``（origin/HEAD → 本地 main →
    本地 master → 回退 PRESERVE_AHEAD_BASE_BRANCH）；缓存与超时口径由解析器
    承担（按 project_root 进程内缓存一次、子进程带
    PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS 超时，语义与旧实现一致，不抛错）。
    """
    return resolve_base_branch(
        PROJECT_ROOT,
        timeout=PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS,
        fallback=PRESERVE_AHEAD_BASE_BRANCH,
    )


# 评审锚点候选的短 TTL 缓存（fix-state-atomicity-and-selfheal-restart D3/3.3）：
# 空闲判定经主循环 1s 粒度轮询，每次 read_all 都要解析整份 STATE.md——实测真实
# 项目（279 条 spec）单次约 14ms（≈1.4% 单核），且「陈旧待自愈」期间可持续数
# 小时。缓存只存**候选集合**（哪些 spec 带 reviewer_run 锚点），在飞结论仍逐次
# 实时复核；TTL MUST 显著小于 stale_code_selfheal.idle_confirm_seconds（缺省
# 120s），以免延迟在飞识别——2s 远小于 120s 确认窗口，不会造成误触发。
STALE_SELFHEAL_REVIEW_ANCHOR_CACHE_SECONDS = 2.0

# stale_code 告警跨重启窗口去重阈值（stale-code-alert-window-dedup 1.1，模块
# 常量不入 config，对齐 admin_monitor 的 DAEMON_ERROR_RESTART_COOLDOWN_MINUTES
# 风格，规避「新增配置项必须带 Dashboard UI」约束）。告警写入侧虽已是假→真
# 边沿触发（单 daemon 生命周期一条），但高频提交下 daemon 生命周期本身快速
# 轮换——每次重启新进程都会再次「首次变陈旧」成条。admin_alerts.json 落盘
# 持久，窗口判定直接复用存储（latest_signal），去重状态天然跨重启存活、零
# 新增状态文件。60 分钟与自愈重启节奏（实测窗口内约 1-2 小时一次）同量级，
# 超 60 分钟的新陈旧周期照常成条，真·新周期不被吞。
# 治理参数后续可由告警治理 SPEC 统一参数化。
STALE_ALERT_DEDUP_MINUTES = 60

# supervisor 漂移告警 PROJECT_LOG 追加跨重启窗口去重阈值
# （evo-supervisor-drift-log-dedup 1.1，与 STALE_ALERT_DEDUP_MINUTES 同层声明、
# 同风格：模块常量不入 config，规避「新增配置项必须带 Dashboard UI」约束）。
# drain 一致性检查在每次 daemon 启动自检都会重新产出同一组 supervisor 异常
# 告警，高频提交下生命周期快速轮换、PROJECT_LOG 逐次刷屏。去重状态复用
# admin_alerts.json（latest_signal 窗口查询，键为 supervisor_runtime_drift
# 族），天然跨重启存活、零新增状态文件。60 分钟远短于漂移阈值
# SUPERVISOR_RUNTIME_DRIFT_SECONDS（24h），真·新异常周期照常超窗成条。
SUPERVISOR_LOG_DEDUP_MINUTES = 60

# 单飞 fallback 锁的惰性创建守卫（code-review item d51f639c500c）：旧实现
# 「检查→为 None→new Lock→写回」非原子，两线程可各建一把锁并同时通过
# check-then-set——创建本身必须互斥。
_SINGLEFLIGHT_FALLBACK_GUARD = threading.Lock()


def _read_preserve_sidecar() -> list:
    """读取中断保全 sidecar（.fenix/interrupted_runs.json）。

    文件缺失/损坏（非 JSON/非列表）返回空列表且不抛错——保全信息非停机
    关键路径，读取失败按「无保全」处理。

    元素级校验（code-review item bc3bece2b2d6）：docstring 承诺「损坏亦容忍」，
    但旧实现只滤掉非 JSON / 非列表形态；语法合法而元素非对象的列表（如
    ``[1, 2]``、``["x"]``，由部分写入或手工编辑产生）会通过校验，随后
    ``_preserve_interrupted_runs`` / ``_wip_checkpoint_preserved_worktrees``
    对元素调 ``e.get(...)`` 直接抛 AttributeError。此处一并过滤非 dict 元素。
    """
    try:
        data = json.loads(PRESERVE_SIDECAR.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict)]
    except (OSError, ValueError):
        return []


def _write_preserve_sidecar(entries: list) -> bool:
    """写中断保全 sidecar（原子替换）。返回 True 表示落盘成功；失败仅记调用方日志。

    原子写（code-review item 80bcbbf05e5b）：旧实现 ``write_text`` 原地截断后写，
    崩溃/SIGKILL 落在截断与落盘之间会留下截断/非法 JSON，而上方读取侧会把这类
    文件按空列表静默吞掉——恰好丢失本 sidecar 存在意义所在的保全数据
    （branch/worktree/保护集）。改用同目录 tempfile + fsync + os.replace。
    """
    tmp_path = None
    try:
        PRESERVE_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_str = tempfile.mkstemp(
            prefix=f".{PRESERVE_SIDECAR.name}.", suffix=".tmp",
            dir=str(PRESERVE_SIDECAR.parent),
        )
        tmp_path = Path(tmp_str)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(entries, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_str, str(PRESERVE_SIDECAR))
        return True
    except OSError:
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
        return False


def _clear_preserve_sidecar() -> None:
    """清空中断保全 sidecar（boot recovery 消费后调用，幂等）。"""
    try:
        PRESERVE_SIDECAR.unlink(missing_ok=True)
    except OSError:
        pass


def _strict_bool(value, default: bool) -> bool:
    """严格 bool 读取（对齐 core.config get_admin_config 的严格 bool 范式，
    code-review item 2f257c49fa5c）：bool() 直转会把任何 truthy 非 bool 值
    （如 YAML 引号串 "false"）静默翻成 True——破坏性开关（merge 前预检
    旁路 / serving 目录强回收等）须只认真 bool，非 bool 值一律回退文档缺省。
    """
    return value if isinstance(value, bool) else default


# 无 spec 绑定车道的 run_id 前缀（code-review item 67c551e85f1c）：这些车道
# 的 run 不绑 SPEC（run_id 均为 <prefix>-<epoch/date> 形态），排水保全路径
# （_preserve_interrupted_runs）解析不出 spec 属预期形态，降级 info 留痕跳过。
# 其余解析失败（_spec_from_run_id 返回 None）仍按 warning 留痕，提示可能缺
# 前缀、须人工确认——包括 admin-<spec>-<ts> / planner-<mode>-<spec>-<ts> 等
# 前缀表未覆盖的命名、车道复合前缀 impl-ocr-<spec>-<ts>（code-review item
# cb8408ba09ec：_spec_from_run_id 对 impl 剥离后第二段为保留字 ocr 的形态
# 显式返回 None，不再误产出脏 spec 名「ocr-<spec>」）以及未知新形态。
_RUN_ID_NO_SPEC_PREFIXES = (
    "code-review-",
    "regression-",
    "code-fix-",
    "evo-",
    "review-",
)


def _ahead_commit_count(branch: str) -> int:
    """统计 branch 相对基线分支的 ahead 提交数（recovery 保留判定同口径）。

    ``_preserve_interrupted_runs`` 与 ``_preserve_implementing_specs`` 两处
    保全条目共用（code-review item 89d3e927d59c）；非停机关键路径，超时/
    失败/输出不可解析一律按 0 处理，不抛错。
    """
    try:
        res = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "rev-list", "--count",
             f"{_preserve_base_branch()}..{branch}"],
            capture_output=True,
            text=True,
            timeout=PRESERVE_AHEAD_COUNT_TIMEOUT_SECONDS,
        )
        if res.returncode == 0:
            try:
                return int(res.stdout.strip() or "0")
            except ValueError:
                return 0
    except (subprocess.TimeoutExpired, OSError):
        pass
    return 0


# ── 代码陈旧检测（improve-hot-reload-robustness D4 / add-stale-code-selfheal）─
# daemon 启动后代码更新（rsync/patch/checkout/未提交修改）时，进程内校验规则
# 可能是旧版；以 mtime 指纹判定并在热重载检测点提示重启。mtime 覆盖 git
# rev-parse 覆盖不了的未提交修改，worktree 友好；误报面仅"touch 无内容变化"。
# add-stale-code-selfheal：愈发渲染为持续状态 self._code_stale（每检测周期重算），
# 不再用模块级一次性旗标——命中后保持可见（escalation 告警），并驱动空闲自愈。


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
        # SPEC 删除后台投递单飞（code-review item dc0563435ba5）：删除（先停
        # 后删，含最长 60s 有界等待）整体投递 _admin_executor 后台执行，主循环
        # 只做信号消费；在飞期间新请求留在盘上下轮再消费——不重复投递、不丢
        # 请求。派发即置位、worker finally 复位（对齐 _evolution_in_flight）。
        self._spec_delete_in_flight = False
        self.pm_engine = None
        self.hook_engine = None
        # 框架自进化检查点（add-framework-self-evolution D3 单飞）：
        # _evolution_in_flight 在派发即置位、worker 收尾复位——与 _running_agents
        # 的 evo- 前缀判定互补（派发与子进程登记之间的窗口由本标记兜底）。
        self._evolution_in_flight = False
        # 宿主守卫去重（add-framework-self-evolution D1/5.2）：非自托管部署
        # 只记一次日志，不刷屏。
        self._evolution_host_guard_logged = False
        # 代码陈旧持续状态（add-stale-code-selfheal D1）：每检测周期重算的
        # self._code_stale 取代「每进程一次性提示」的模块级旗标；为真期间保持
        # 可见（WARNING 仅状态边沿落一次 + 未处置 escalation 告警去重），并作为
        # 空闲自愈触发的前置。_stale_idle_since 为连续空闲计时起点（None=未开始）。
        self._code_stale = False
        self._stale_idle_since = None
        self._heal_block_reason = None
        # 悬空起点（evo-add-stale-code-dangling-deadline 2.1）：_code_stale 假→真
        # 边沿记录（UTC datetime，与 restart_history.jsonl 时间戳同源）；基线恢复
        # 新鲜清零。启动即陈旧（baseline 计算后、首个检测点前代码已被改，或测试
        # 基线替身）时取进程启动时刻。_stale_check_fresh_seen 记录「进程启动后
        # 是否已见过新鲜检测」——首检即陈旧无法精确定位变更时刻（baseline 为启动
        # 时 max mtime，磁盘此刻必不超 baseline），按 SPEC 取启动时刻下界。
        # _dangling_timeout_fired 为本悬空周期的超时防重复写标志（2.3）。
        self._code_stale_since = None
        self._stale_check_fresh_seen = False
        self._proc_started_utc = datetime.now(timezone.utc)
        self._dangling_timeout_fired = False
        # 本悬空周期「自触发窗口内悬空超时」的告警/WARNING 边沿标志（item
        # a6fb64ba17d4）：与 _dangling_timeout_fired 分立——后者闸收尾重启写
        # 请求（并被 _stale_selfheal_healthy 健康谓词读取），前者只闸告警入口
        # （其 WARNING 在 admin 去重判断之前无条件执行），互不挤占。读取走
        # getattr，容忍未走 initialize 的裸对象（既有测试形态）。
        self._dangling_timeout_alert_fired = False
        # 重启冷却锁存起点（evo-stale-selfheal-restart-cooldown）：None=不在冷却中；
        # 首次因滑动窗口计数进入冷却的那个 tick 时刻——锁存是「冷却持续
        # cooldown_duration_seconds」的落地点（窗口计数会因条目老化提前回落）。
        # _self_triggered_cycle 标记「本重启周期内曾判定为自触发型 stale」，
        # 周期收尾重启时据此累计持久化 streak（进程重启后由 restart_history 续算）。
        # 两者均以 getattr 读取，容忍未走 initialize 的裸对象（既有测试形态）。
        self._cooldown_started_at = None
        self._self_triggered_cycle = False
        # _selfheal_loop_alerted 标记「本重启循环已升过 stale_selfheal_loop
        # critical 告警」：边沿判定为 streak >= threshold（阈值经热更新可被调低
        # 于已累计 streak，等值判定将令告警永久静默），靠本标记去重防逐周期
        # 重复堆积；循环断裂处（streak 归零/陈旧解除）一并复位，下一循环不受
        # 旧标记压制。以 getattr 读取，容忍未走 initialize 的裸对象。
        self._selfheal_loop_alerted = False
        # 收口幂等守卫（fix-supervisor-hosting-chain 验证修复 BUG-01）：supervisor
        # 见 stop flag 会主动 SIGTERM daemon（停止协作），与 stop_daemon 的 SIGTERM
        # 可能叠加成双重信号。Python 信号处理器在字节码边界打断主线程——若在第一次
        # shutdown 收口中再触发，重入的 shutdown 会在 wait_for_running_agents 完成
        # 前提前 sys.exit(0)，遗留未终止的 agent。首次进入置位，重入直接返回。
        self._shutdown_started = False

    def initialize(self):
        """Load config and initialize all components."""
        # 1. Load configuration（有效配置：用户级 ~/.fenix/config.yaml + 项目级
        #    .fenix/config.yaml 深合并；任一或全部缺失都允许，内置默认兜底）
        self.config = ConfigLoader.resolve_config(PROJECT_ROOT)

        # 2. Initialize logger
        # 配置读取一律走 ConfigLoader.get 的点号路径解析：self.config 是
        # resolve_config 深合并后的**嵌套 dict**（如 {"worktree": {...}}），
        # 而 dict.get("worktree.base_dir") 是按**扁平字面键**查找——恒返回缺省
        # 兜底值，显式配置静默失效（2026-09-19 事故：worktree.has_build_artifacts
        # / build_artifact_paths / mergeback_wip_overlap_policy 三键读成缺省，
        # 已裁决的 has_build_artifacts=false 读不到 → 产物判定永久「未裁决」→
        # merge-back WIP 重叠闸门误发 build_artifact_paths_missing 信号）。
        log_dir = PROJECT_ROOT / ConfigLoader.get(self.config, "logging.dir", ".fenix/logs")
        log_level = ConfigLoader.get(self.config, "logging.level", "INFO")
        self.logger = Logger(log_dir, log_level)
        self.logger.info("fenixd", "Initializing Fenix Loop Engineering Framework...")
        # supervision-timeout-config-consistency：启动配置校验（resolve_config 内
        # _validate）完成后，把默认自动对齐抬升的 absolute_max 值经既有写路径
        # 持久化（不一致且 auto_align 显式关闭时 resolve_config 已 fail-fast，
        # 不会走到此处）。
        self._maybe_persist_supervision_alignment()

        # 3. Initialize StateMachine（状态文件在 .fenix/ 下，.STATE.md.lock 随同目录）
        state_path = PROJECT_ROOT / ".fenix" / "STATE.md"
        self.state_machine = StateMachine(state_path, self.logger)
        self.logger.info("fenixd", "StateMachine initialized")

        # 4. Initialize WorktreeManager
        # 本段四键均为点号路径读取（见上方「2. Initialize logger」注释）：
        # 写成 self.config.get("worktree.x") 会静默取缺省值。
        wt_base = PROJECT_ROOT / ConfigLoader.get(
            self.config, "worktree.base_dir", ".claude/worktrees"
        )
        # 分支枚举前缀（fix-recovery-branch-anchor D2）：与分支创建端同源取
        # 并集；配置值仅作推送侧前缀，非创建端事实源（非 fenix 配置下创建端
        # 仍产出 fenix/<spec>-<ts>，须并集枚举才不扫空命名空间）。
        _impl_prefix = ConfigLoader.get(
            self.config, "worktree.implement_branch_prefix", "fenix"
        )
        # merge-back 前 WIP 重叠闸门策略（evo-merge-back-wip-overlap-gate D1；
        # add-pipeline-throughput-governance D2 起缺省升级拦截 escalate）：
        # 交集非空缺省不再 auto stash 收纳，而是拦截升级人工（spec 保持可重试）；
        # 显式 auto 保留收纳语义、显式 block 并入升级出口（解析见
        # mergeback._wip_gate_policy）。
        _wip_policy = ConfigLoader.get(
            self.config, "worktree.mergeback_wip_overlap_policy", None
        )
        # merge 前置预检逃生门（add-pipeline-throughput-governance 2.3）：
        # worktree.merge_precheck_bypass=true（兼容顶层 merge_precheck_bypass）
        # 时跳过 WIP 重叠预检直接 merge（紧急推送用）。
        _precheck_bypass = ConfigLoader.get(
            self.config,
            "worktree.merge_precheck_bypass",
            ConfigLoader.get(self.config, "merge_precheck_bypass", False),
        )
        # 构建产物路径判定配置（evo-merge-back-wip-artifact-scope D2/D4 /
        # fix-artifact-paths-hardcoded-default D1/D4）：项目可声明自己的产物根
        # （前缀，以 / 结尾）与产物文件（后缀通配，含 *），供产物判定器实例化。
        # MUST 谨慎——判定变宽会把语义改动误判为产物并被静默丢弃
        # （fix-mergeback-stashpop-silent-loss 事故家族），故默认（未裁决）判定
        # 恒假，产品项目须显式声明后才判真。has_build_artifacts 三态：
        # 缺省 None=未裁决（判定恒假 + 运行期触发起草信号）、false=已声明无产物、
        # true=按 build_artifact_paths 判定。
        _artifact_paths = ConfigLoader.get(
            self.config, "worktree.build_artifact_paths", None
        )
        _has_build_artifacts = ConfigLoader.get(
            self.config, "worktree.has_build_artifacts", None
        )
        self.worktree_manager = WorktreeManager(
            wt_base,
            PROJECT_ROOT,
            self.logger,
            implement_branch_prefix=str(_impl_prefix) if _impl_prefix else "fenix",
            # 分支在飞引用保护（D6）：注入 STATE 读取器——stale 清扫删分支前
            # 检查在飞/待收口 spec 的分支引用（宁可多留分支不可误删成果）。
            state_reader=self.state_machine.read_all,
            mergeback_wip_overlap_policy=str(_wip_policy) if _wip_policy else None,
            # 严格 bool（code-review item 2f257c49fa5c）：引号串 "false" 经
            # bool() 直转会静默打开 merge 前 WIP 重叠预检旁路
            merge_precheck_bypass=_strict_bool(_precheck_bypass, False),
            build_artifact_paths=_artifact_paths,
            has_build_artifacts=_has_build_artifacts,
        )
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

        # 5.4. Initialize PMEngine（提前于 AdminMonitor：add-blocked-reverify-lane
        # D2 的处置收尾复位需要 pm_engine 引用以派发 verifier；PMEngine 构造仅
        # 轻量初始化 + 加载 recovery_watch，无启动扫描副作用）
        self.pm_engine = PMEngine(
            self.state_machine,
            self.agent_runner,
            self.config,
            PROJECT_ROOT,
            self.logger,
        )
        self.logger.info("fenixd", "PMEngine initialized")

        # 5.5. Initialize AdminStore + AdminMonitor（零成本健康监视 + 困境唤起）
        self.admin_store = AdminStore(PROJECT_ROOT, self.logger)
        self.admin_monitor = AdminMonitor(
            self.config,
            self.state_machine,
            PROJECT_ROOT,
            self.logger,
            store=self.admin_store,
            agent_runner=self.agent_runner,
            pm_engine=self.pm_engine,
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
        # 非法值（非数字字符串等）回退缺省并留痕（code-review item
        # 8f6bf8446388，同 _shutdown_drain_seconds 范式）：裸 int() 抛
        # ValueError 会令 initialize FATAL 退出、supervisor 拉起即再崩
        raw_workers = ConfigLoader.get(self.config, "admin.workers", 2)
        try:
            admin_workers = int(raw_workers or 0)
        except (TypeError, ValueError):
            self.logger.error(
                "fenixd",
                f"admin.workers 非法（应为非负整数）: {raw_workers!r}，回退 2",
            )
            admin_workers = 2
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
        # add-code-review-agent-and-quality-tab：注入 code-review executor
        # 到 AdminMonitor（对齐 _evolution_worker 形态，投递后台 worker）
        if self.admin_monitor is not None:
            self.admin_monitor._code_review_executor = self._admin_executor

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

        # 8. 自动修复编排器装配（add-code-review-auto-fix，task 7.3）：在
        # admin_monitor/executor 就绪后构造，注入 agent_runner（审查收尾触发，
        # task 7.1）与 event_bus（full scan 兜底，task 7.2）。executor 复用
        # _admin_executor（对齐 _code_review_executor 注入形态）；宿主禁用态
        # （admin_monitor is None / admin.workers=0）构造仍成功，checkpoint()
        # 的 enabled 守卫缺省关 → 返回 disabled（全链路零动作）。
        # config 传 None：checkpoint 时经 runner._get_config 实时读取
        # admin.code_review_fix（配置热更新 30s 内生效）。
        from core.code_fix import CodeFixOrchestrator

        self.code_fix_orchestrator = CodeFixOrchestrator(
            self.agent_runner,
            PROJECT_ROOT,
            config=None,
            logger=self.logger,
            executor=self._admin_executor,
        )
        self.agent_runner._code_fix_orchestrator = self.code_fix_orchestrator
        self.event_bus.code_fix_orchestrator = self.code_fix_orchestrator
        self.logger.info("fenixd", "CodeFixOrchestrator initialized")

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
                    f"无终态 run 的 interrupted 终态: " + ", ".join(run_id for run_id, _ in _swept),
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
        # 恢复期 re-merge-back 收口回调（fix-recovery-branch-anchor D4/4.2）：
        # recover_interrupted 内 re-merge 成功后的 PMEngine 侧副作用
        # （_clear_dispatch_conflict / _sync_task_progress / _reconcile_impl_budget
        # / consume_legacy）由 fenixd 注入——state_machine 无 pm_engine 引用，
        # 缺省 None 时行为与旧版逐字节一致。
        remerge_cb = None
        try:
            remerge_cb = self._build_remerge_callback()
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"remerge 收口回调构造失败（按无回调恢复，非阻塞）: {e}",
            )
        # fix-blocked-freeze-classification D4/1.2 接线：恢复期冻结人工升级告警
        # 回调（非 None——缺省 None 会使恢复路径退回静默冻结，违反「冻结必告警」
        # 不变式；helper 内对 None 打审计 ERROR 兜底）
        human_alert_cb = self._build_human_alert_callback()
        self.state_machine.recover_interrupted(
            PROJECT_ROOT,
            self.worktree_manager,
            verify_redo_budget=_redo_budget,
            remerge_callback=remerge_cb,
            human_alert_callback=human_alert_cb,
        )
        # 消费后的保全 sidecar 清除（幂等；中断全部由 recovery 接管）
        _clear_preserve_sidecar()

        # 启动清扫 non-blocking 包裹（code-review item ea0ba60cd65f）：清扫内
        # 仍有未纳入其内部 try 的路径（活进程探测 / spec 解析 / 快照留档等），
        # 任何异常不得中断后续启动序列（v2_cleanup_orphans、event_bus.start
        # 等），与周边启动步骤的 non-blocking 口径一致。
        try:
            self.worktree_manager.cleanup_stale_worktrees()
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"Stale worktree cleanup failed (non-blocking, daemon 启动继续): {e}",
            )

        # add-worktree-test-server（D2 启动清扫）：上次异常退出遗留的 dev-server 进程
        # 在 daemon 重启时早已失活（worktree 已清），需按命令行标记回收端口。
        # worktree_base 项目收窄（fix-v2-devserver-fallback-attribution 2.1）：
        # 只考量 argv 携带本项目 worktree 基路径的 dev-server，双 daemon 主机
        # 不互刷（他项目进程不记账、不告警、不清扫）。
        v2_cleanup_orphans(
            self.logger, worktree_base=self.worktree_manager.base_dir
        )
        # 重启对账（fix-v2-devserver-fallback-attribution 2.3）：登记在册的
        # 重启前实例按「身份核对 + 归属引用判定」只收割无主进程，有主保留。
        try:
            v2_reconcile_v2_servers(PROJECT_ROOT, self.logger)
        except Exception as e:
            self.logger.error("fenixd", f"V2 server restart reconcile failed: {e}")

        # verify-process-lifecycle（D6 启动收割）：上轮 daemon 崩退时登记者全部
        # 视为非在飞——servers.json 中进程仍存活的登记实例按 /proc liveness 收割。
        self._sweep_verify_serving_registry(use_in_flight=False)

        # fix-verify-serving-disk-reclaim（D4 启动 reconcile）：登记收割之后再
        # 按「无主」判据回收 verify-serving 目录与 boot.log（启动 use_in_flight=
        # False：前一轮 daemon 已死，无在飞保留；覆盖 daemon 死机期间累积孤儿）。
        self._reclaim_verify_serving_tree(use_in_flight=False)

        # Start event bus monitoring——必须先于 initial full_scan：
        # start() 会建立 STATE 基线快照（_update_known_state），若首扫先行，
        # _known_specs 为空，全部存量 SPEC 被判为「新出现」，pushed 等 hook
        # 事件被全量重放（2026-09-07：重启后 15+ pushed spec 的 commit-push
        # hook 连环触发，因 index.lock 冲突失败才未酿成连环误提交）。
        self.event_bus.start()

        # fix-scheduling-kick-single-slot D4：启动清扫调度 kick 信号对账。
        # MUST 排在 event_bus.start()（同步建立 STATE 基线快照）之后、进入主
        # 循环之前——阈值内的条目会被「先消费再删」唤起并写 STATE；早于基线
        # 快照的写入会被随后的首扫 _dispatch_changes 当作新变化重放（本文件
        # 2026-09-07 hook 全量重放事故的注释即为此防线）。
        try:
            self._reclaim_stale_scheduling_kicks()
        except Exception as e:
            self.logger.error("fenixd", f"Startup scheduling_kick reclaim failed: {e}")

        # 原子消费崩溃窗口残留回收（code-review item bd0b3d74ebca）：启动清扫
        # 处理存量，主循环 600s 周期时点兜底（与 scheduling_kick 对账同挂载）。
        try:
            self._reclaim_consumed_request_residues()
        except Exception as e:
            self.logger.error("fenixd", f"Startup consumed-residue reclaim failed: {e}")

        # 恢复上次异常退出遗留的中断状态（implementing/testing → ready）。
        # recover_interrupted 此前定义了但从未被调用，导致 daemon 重启后卡死的
        # spec 永远不被重新调度（fix-fenix-token-waste）；保留判定已在上面与
        # 孤儿清理协同完成。
        # ── 初扫异步化（fix-spec-review-blocking-dispatch 4.2/4.3/4.4）──
        # 评审派发入队化后，首扫的 recovery 分支（reviewing → spec-review 入队）
        # 不再阻塞调用线程，但首扫本身在历史上有 1802s 长尾记录（design D5）。
        # 基线快照（_snapshot_baseline）由 event_bus.start() 内的
        # _update_known_state 同步完成（2026-09-07 事故的防线，D5 不变量保持），
        # 扫描主体提交到后台 daemon 线程（命名对齐 fenixd-* 同族，句柄由
        # EventBus 持有、stop() 收口覆盖）——主循环不再等首扫完成，恢复
        # 「进入主循环 ≤ 数秒」的用户可见指标。MUST NOT 在此等待扫描主体。
        self.event_bus.start_initial_scan()

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
        # fix-dashboard-read-path-performance D4：runs 保留清理独立计时（300s，
        # 对齐自动归档模式）：终态 run 移入归档 + 无主归档产物天龄兜底
        # （fix-run-cleanup-attach-spec-archive D2）。
        runs_retention_ts = time.time()
        # verify-process-lifecycle（D4/D6 周期清扫）：dev-server 孤儿 + 登记制
        # command 实例回收的独立计时（600s ≤ 规格 10 分钟上限）
        orphan_clean_ts = time.time()
        # add-spec-scheduling-controls D3：定时调度到期检测独立计时（60s，
        # 对齐恢复复查/recovery watch 模式：try/except 记日志不中断主循环）。
        scheduling_check_ts = time.time()
        # fix-orphan-ready-recovery-liveness D3：孤儿 ready 短周期精触发独立计时
        # （60s，对齐 recovery_watch_ts / scheduling_check_ts 挂载方式——同步调用、
        # 不新建线程/Timer）。恢复延迟从「最坏一个扫描周期（30 分钟）」降到
        # 「最坏一个精触发周期（60 秒）」；full_scan 周期扫描仍为兜底。
        orphan_ready_check_ts = time.time()
        # evo-add-wip-defer-merge-retry-consumer 2.2：WIP 延迟合回周期复查独立
        # 计时（120 秒节拍，常量先行不新增配置面，对齐 orphan_ready_check_ts
        # 挂载方式——同步调用、try/except 记日志不中断主循环）。节拍远短于
        # orphaned_state 探测的 15 分钟缺省阈值，自动合回先于孤儿探测生效。
        wip_defer_check_ts = time.time()
        # add-framework-self-evolution 5.1：自进化检查点独立计时（节拍复用
        # admin.interval_minutes，缺省 5 分钟）。
        evolution_check_ts = time.time()
        # add-knowledge-atlas-maintenance 3.3：知识真相源维护每日检查点独立计时
        # （300s 节拍对齐自动归档挂载；检查点内部按自然日防重，每日只跑一次，
        # audit → graph 先后共用同一唤醒）。
        knowledge_check_ts = time.time()
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
                # 陈旧自愈触发（add-stale-code-selfheal 2.2）：主循环 1s 粒度累计
                # 连续空闲时长，达到 idle_confirm_seconds 后 touch restart_request。
                # 异常捕获记日志不中断主循环（同其它轮询项模式）。
                try:
                    self._maybe_stale_selfheal_tick()
                except Exception as e:
                    self.logger.error("fenixd", f"Stale-code selfheal check failed: {e}")
                # run 人工取消文件信号拾取（add-run-cancel D5）：
                # dashboard 写入 .fenix/cancel_run_request.json，主循环下一轮
                # 消费并调 agent_runner.cancel_run（只设旗标，微秒级，不投 worker 池）。
                try:
                    self._check_cancel_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"cancel_run pickup failed: {e}")
                # 清空定时拾取即派发信号（2026-09-08 清空 start_after 后等 30min
                # recovery 才派发事故的 API 侧修复）：dashboard 清空 start_after
                # 时写入 .fenix/scheduling_kick/<spec>.json（每 SPEC 一文件，多槽位），
                # 主循环下一轮（≤2s）消费并唤起派发。
                try:
                    self._check_scheduling_kick_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"scheduling_kick pickup failed: {e}")
                # SPEC 审批推送信号（add-spec-approve-push-modal）：dashboard
                # 审批 done SPEC 时写入 .fenix/approve_push_request.json，主循环
                # 下一轮（≤2s）消费并调 pm_engine.approve_push 执行推送。
                try:
                    self._check_approve_push_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"approve_push pickup failed: {e}")
                # add-freeze-stop-inflight-agents 5.2：SPEC 删除信号（异步受理）
                # dashboard 写入 .fenix/spec_delete_request.json（含 spec/source/
                # created/stopping），主循环下一轮消费（仅信号拾取与后台投递，
                # code-review item dc0563435ba5：最长 60s 的先停后删有界等待
                # 不得内联阻塞主循环其它信号车道）：枚举该 spec 在跑 run
                # → cancel_run 逐个停止 → 有界等待终态 → soft_delete_spec 完成
                # 删除，全程在 _admin_executor worker 执行。信号文件先读后删，
                # 损坏 JSON 删除防卡死。
                try:
                    self._check_spec_delete_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"spec_delete pickup failed: {e}")
                # add-code-review-agent-and-quality-tab：code-review 手动触发
                # 文件信号拾取（dashboard 写入 .fenix/code_review_request.json），
                # 主循环下一轮消费（scope→review_kind 映射 + manifest 收集 +
                # 后台投递 run_code_review），与 _check_cancel_requests 同构。
                try:
                    self._check_code_review_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"code_review pickup failed: {e}")
                # add-test-regression-tab：regression 手动触发文件信号拾取
                # （dashboard 写入 .fenix/regression_request.json），主循环
                # 下一轮消费（校验回归段 + 单飞 + 后台投递 run_regression），
                # 与 _check_code_review_requests 同构。
                try:
                    self._check_regression_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"regression pickup failed: {e}")
                # add-code-fix-manual-trigger：手动「立即自动修复」文件信号
                # 拾取（dashboard 写入 .fenix/code_fix_request.json），主循环
                # 下一轮消费（先读后删 + override_enabled=True 临时授权调
                # checkpoint + 判定结果原子写回），与 _check_code_review_requests
                # 同构。
                try:
                    self._check_code_fix_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"code_fix pickup failed: {e}")
                # add-regression-auto-fix：手动「自动修复回归问题」文件信号
                # 拾取（dashboard 写入 .fenix/regression_fix_request.json），
                # 主循环下一轮消费（先读后删 + 读回归快照转换为台账条目 +
                # 复发重开 + override_enabled=True 投递 + 判定结果原子写回），
                # 与 _check_code_fix_requests 同构。
                try:
                    self._check_regression_fix_requests()
                except Exception as e:
                    self.logger.error("fenixd", f"regression_fix pickup failed: {e}")
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
                        self.logger.error("fenixd", f"Recovery watch check failed: {e}")
                    # 滞留 autostash 兜底回收（fix-autostash-orphans）：主树干净且
                    # 无活跃 run 时，把历史上被派发前 stash 吞掉的用户改动 pop 回来。
                    try:
                        self.pm_engine.reclaim_stale_autostash_if_idle()
                    except Exception as e:
                        self.logger.error("fenixd", f"Autostash reclaim check failed: {e}")
                    # 主树散件 WIP 周期盘点（evo-add-maintree-stray-wip-sweep
                    # 2.1）：只读盘点主树 tracked 未提交改动并归因在飞实现车道；
                    # 无主且宽限耗尽经 AdminStore 发一次性 major 告警。全程零
                    # 触碰（不 stash/checkout/clean/reset），与 merge-back 互斥
                    # 由主树锁非阻塞 acquire 兜住（锁忙即弃本轮）。异常捕获留
                    # 日志，不阻断主循环。
                    try:
                        self.pm_engine.sweep_maintree_stray_wip()
                    except Exception as e:
                        self.logger.error("fenixd", f"Stray WIP sweep failed: {e}")
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
                        self.logger.error("fenixd", f"Auto-archive check failed: {e}")
                # runs 保留周期清理（fix-dashboard-read-path-performance D4）：
                # 每 300s 终态 run 移入归档 + 无主归档产物天龄兜底（参照既有
                # archive_check 段的挂载方式，不新建独立线程）；异常捕获记日志
                # 不中断主循环。（runs.keep 已随 fix-run-cleanup-attach-spec-
                # archive 取消，本调用不再消费配置。）

                if time.time() - runs_retention_ts >= 300:
                    runs_retention_ts = time.time()
                    try:
                        from core.dashboard.data import runs_retention_check

                        runs_retention_check(PROJECT_ROOT, self.config, self.logger)
                    except Exception as e:
                        self.logger.error("fenixd", f"Runs retention check failed: {e}")
                # 知识真相源维护每日检查点（add-knowledge-atlas-maintenance 3.3）：
                # 每 300s 唤醒一次（与自动归档同款挂载，不新建线程），内部按自然日
                # 防重——当日未跑则先后执行 audit 车道与 graph 生成（各自受
                # knowledge.audit_enabled / knowledge.graph_enabled 门控，双禁用时
                # 静默零动作）。异常捕获记日志不中断主循环。
                if time.time() - knowledge_check_ts >= 300:
                    knowledge_check_ts = time.time()
                    try:
                        from core.knowledge_audit import knowledge_daily_check

                        knowledge_daily_check(PROJECT_ROOT, self.config, self.logger)
                    except Exception as e:
                        self.logger.error("fenixd", f"Knowledge maintenance check failed: {e}")
                # 定时调度到期检测（add-spec-scheduling-controls D3）：每 60s
                # 检查 auto 解冻（frozen_until 到期）与定时拾取（start_after
                # 到期唤起派发）。周期扫描（full_scan）作为兜底，二者先后到达
                # 均只触发一次（幂等由写前重读 STATE 保证）。
                if time.time() - scheduling_check_ts >= 60:
                    scheduling_check_ts = time.time()
                    try:
                        self.pm_engine.check_scheduling_deadlines()
                    except Exception as e:
                        self.logger.error("fenixd", f"Scheduling deadlines check failed: {e}")
                # 孤儿 ready 短周期精触发（fix-orphan-ready-recovery-liveness D3）：
                # 每 60s 对 ready 态孤儿 SPEC 走与 full_scan 恢复同源的
                # event_bus.recover_orphan_ready()，恢复延迟从「最坏一个扫描周期
                # （30 分钟）」降到「最坏一个精触发周期（60 秒）」；不新建线程，
                # 同步调用 + 异常捕获记日志不中断主循环；不缩短 poll_interval_
                # minutes、不改 full_scan 触发源（周期扫描仍为兜底）。
                if time.time() - orphan_ready_check_ts >= 60:
                    orphan_ready_check_ts = time.time()
                    try:
                        self.event_bus.recover_orphan_ready()
                    except Exception as e:
                        self.logger.error("fenixd", f"Orphan ready recovery check failed: {e}")
                # WIP 延迟合回周期复查（evo-add-wip-defer-merge-retry-consumer
                # 2.2）：每 120s 复查带 _wip_gate_deferred 标志的 implementing
                # 条目——主树重叠文件已干净即 merge-only 自动合回（implemented
                # 推进 + 标志清账 + 告警闭环），超限降级人工。同步调用 +
                # 异常捕获记日志不中断主循环；先于 orphaned_state 探测（15 分钟
                # 阈值）生效，使自动合回成为默认路径。
                if time.time() - wip_defer_check_ts >= 120:
                    wip_defer_check_ts = time.time()
                    try:
                        self.pm_engine._dispatcher._recheck_wip_deferred_merges()  # noqa: SLF001 — 周期消费者挂 Dispatcher（deliverable 声明面约束）
                    except Exception as e:
                        self.logger.error("fenixd", f"WIP defer merge recheck failed: {e}")
                # verify-process-lifecycle（D4 周期清扫）：孤儿泄漏可见窗口
                # ≤ 一个周期（600s）。覆盖 dev-server 与 servers.json 登记实例；
                # 首轮启动清扫已处理存量，此后周期性兜底。
                if time.time() - orphan_clean_ts >= 600:
                    orphan_clean_ts = time.time()
                    try:
                        v2_cleanup_orphans(
                            self.logger,
                            worktree_base=self.worktree_manager.base_dir,
                        )
                    except Exception as e:
                        self.logger.error("fenixd", f"Periodic V2 orphan cleanup failed: {e}")
                    try:
                        self._sweep_verify_serving_registry()
                    except Exception as e:
                        self.logger.error("fenixd", f"Periodic serving registry sweep failed: {e}")
                    # fix-verify-serving-disk-reclaim（D4 周期清扫）：登记收割之后
                    # 再按无主判据回收目录与 boot.log（use_in_flight=True 保留 testing
                    # 中的 spec），覆盖长期运行中的增量孤儿。
                    try:
                        self._reclaim_verify_serving_tree()
                    except Exception as e:
                        self.logger.error("fenixd", f"Periodic serving tree reclaim failed: {e}")
                    # fix-scheduling-kick-single-slot D4：陈旧 scheduling kick 信号
                    # 周期对账（复用 600s 孤儿清扫时点）。启动清扫已处理存量，
                    # 此后周期性兜底：超阈值条目仅删不唤起、非 .json 残留按
                    # mtime 同阈值清理、损坏条目删除防卡死。
                    try:
                        self._reclaim_stale_scheduling_kicks()
                    except Exception as e:
                        self.logger.error("fenixd", f"Periodic scheduling_kick reclaim failed: {e}")
                    # 原子消费崩溃窗口残留（item bd0b3d74ebca）周期兜底回收
                    try:
                        self._reclaim_consumed_request_residues()
                    except Exception as e:
                        self.logger.error("fenixd", f"Periodic consumed-residue reclaim failed: {e}")
                # add-framework-self-evolution 5.1：自进化检查点（节拍复用
                # admin.interval_minutes，缺省 5 分钟；异常记 ERROR 不中断主循环，
                # 就绪即入队、无在途立即启动分析 run）。
                # 口径与 _admin_monitor_loop 一致（float + 0.5 下限）：int 截断会
                # 把 0.5 这类小数分钟变成 0 再被 or 5 静默兜回缺省 5 分钟。
                # 非法值（非数字字符串等）回退缺省并留痕（code-review item
                # 8f6bf8446388，同 _shutdown_drain_seconds 范式）：裸 float() 在
                # 主循环体直接抛出会越过逐任务异常隔离与 except KeyboardInterrupt，
                # 经 finally shutdown 后以 FATAL 结束（supervisor 拉起即再崩）
                raw_interval = ConfigLoader.get(self.config, "admin.interval_minutes", 5)
                try:
                    interval_minutes = float(raw_interval or 5)
                except (TypeError, ValueError):
                    self.logger.error(
                        "fenixd",
                        f"admin.interval_minutes 非法（应为数值分钟）: "
                        f"{raw_interval!r}，回退 5",
                    )
                    interval_minutes = 5.0
                evo_interval = max(interval_minutes, 0.5) * 60
                if time.time() - evolution_check_ts >= evo_interval:
                    evolution_check_ts = time.time()
                    try:
                        self._check_evolution_checkpoint()
                    except Exception as e:
                        self.logger.error("fenixd", f"Evolution checkpoint failed: {e}")
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

        kw = {"is_spec_in_flight": self._is_spec_in_flight} if use_in_flight else {}
        serving_sweep(PROJECT_ROOT, self.logger, **kw)

    def _reclaim_verify_serving_tree(self, use_in_flight: bool = True) -> None:
        """verify-serving 目录与 boot.log 生命周期回收（fix-verify-serving-disk-reclaim）。

        与登记制收割叠加的目录维度清扫：对 `.fenix/verify-serving/` 下无主
        worktree（spec 不在 changes/archive、未登记、无活进程、超宽限期）执行
        `git worktree remove --force` + `prune`，并按同判据回收 `<spec>-boot.log`。

        启动清扫（use_in_flight=False：前一轮 daemon 已死，全部视为非在飞）与
        周期清扫（use_in_flight=True：testing 中的 spec 视为在飞保留）共用。
        开关 `verify.serving_reclaim.enabled` 为 false 时早退（不调 git、不删文件）。
        """
        # 严格 bool（code-review item 2f257c49fa5c）：引号串 "false" 经 bool()
        # 直转会静默打开 .fenix/verify-serving/ 的强制回收，非 bool 值回退
        # 文档缺省 True
        enabled = _strict_bool(
            ConfigLoader.get(self.config, "verify.serving_reclaim.enabled", True),
            True,
        )
        if not enabled:
            self.logger.info(
                "fenixd", "verify.serving_reclaim.enabled=false，跳过 serving 目录回收"
            )
            return
        from core.pm_engine.verification.serving_reclaim import reclaim_verify_serving

        kw = {"is_spec_in_flight": self._is_spec_in_flight} if use_in_flight else {}
        try:
            result = reclaim_verify_serving(PROJECT_ROOT, self.logger, **kw)
            if self.logger:
                self.logger.info(
                    "fenixd",
                    f"verify-serving 回收完成：reclaimed={len(result['reclaimed'])}，"
                    f"kept={len(result['kept'])}，"
                    f"boot_logs_reclaimed={len(result['boot_logs_reclaimed'])}",
                )
        except Exception as e:
            self.logger.error("fenixd", f"Serving tree reclaim failed: {e}")

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
        代码陈旧检测（improve-hot-reload-robustness tasks 2.3 → add-stale-code-
        selfheal 1.1）：磁盘代码 mtime 超启动 baseline → 更新持续状态
        self._code_stale（每周期重算，不再一次性置位后永久静默）。
        """
        self._update_stale_code_state()
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
        # supervision-timeout-config-consistency：热更新完成校验后持久化自动对齐值
        #（校验层已把低于配置层下限的 absolute_max 抬升至下限，内存生效）。
        self._maybe_persist_supervision_alignment()

    def _maybe_persist_supervision_alignment(self) -> None:
        """supervision 自动对齐持久化（supervision-timeout-config-consistency 1.3/1.4）。

        配置校验层（ConfigLoader._check_supervision_consistency，经 resolve_config /
        resolve_config_into 于启动与热更新共入）在发现 absolute_max_seconds 低于配置
        校验层下限时，默认自动对齐：把内存值抬升至下限并记录（take_supervision_alignment）。
        本方法消费该记录，把对齐值经既有受管键写路径 core.dashboard.data.write_config
        落盘（受管键白名单 + 原子写 + 配置头注释保留）。core/config.py MUST NOT 直接
        写配置文件（避免与 launcher/dashboard 写路径竞争、避免 safe_dump 丢注释）。

        幂等：未发生对齐时消费返回 None，直接返回；对齐已由人工手工调平时，记录
        为空同样无操作。持久化失败仅 ERROR 留痕（对齐值已在内存生效，不阻断运行）。
        """
        from core.config import ConfigLoader
        from core.dashboard.data import write_config

        try:
            aligned = ConfigLoader.take_supervision_alignment()
        except Exception as e:
            self.logger.error("fenixd", f"supervision 对齐记录读取失败: {e}")
            return
        if aligned is None:
            return
        aligned_value = int(aligned) if float(aligned).is_integer() else float(aligned)
        res = write_config(
            PROJECT_ROOT,
            {"agents": {"timeout_supervision": {"absolute_max_seconds": aligned_value}}},
        )
        if not res.get("ok"):
            self.logger.error(
                "fenixd",
                f"supervision 自动对齐持久化失败: {res.get('error')} "
                f"（对齐值 {aligned_value}s 已在内存生效，配置文件未更新）",
            )
            return
        self.logger.info(
            "fenixd",
            f"supervision absolute_max_seconds 自动对齐已持久化至 {res.get('path')} "
            f"（={aligned_value}s）",
        )

    def _update_stale_code_state(self):
        """代码陈旧持续状态更新（add-stale-code-selfheal 1.1/1.2/1.3）。

        每检测周期（既有 30s 配置热更新检测点）重算 self._code_stale：磁盘代码
        mtime 超启动 baseline → 为真；否则为假。取代「命中后永久跳过检测」的
        一次性旗标语义，按状态边沿记录：
          - 假→真：落一次 WARNING（保留 improve-hot-reload-robustness D4 文案），
            并经 AdminStore 写入一条 signal_type: stale_code 告警——陈旧成为
            dashboard 可见的持续状态。
            evo-reduce-stale-code-selfheal-noise 2.2：按自愈健康谓词分流——
            stale_code_selfheal.enabled 且未悬空超限（写入时点可判定，见
            _stale_selfheal_healthy）时以 info 级 kind 留痕（无处理生命周期，
            不进人工队列/升级路径，日志附当日累计计数）；selfheal disabled 沿用
            既有 escalation 写入路径（warning 级、写入即自动 mark_handled）。
            悬空超限的升级由 _alert_dangling_timeout 独立承接（signal_type=
            stale_code_dangling_timeout），此处不双重升级；自愈动作失败（写
            restart_request 失败）的升级在 _maybe_stale_selfheal_tick 落点。
            两条路径写入前均经 latest_signal 做 STALE_ALERT_DEDUP_MINUTES
            窗口去重（stale-code-alert-window-dedup）：60 分钟内已有同信号记录
            （info 或 escalation 任一，kind 白名单已含 INFO）则跳过写入降级为
            日志，覆盖高频提交下 daemon 快速轮换重启的跨生命周期重复；超窗新
            周期照常成条。
          - 真→假：记录状态解除（重启后新进程 baseline 刷新，或磁盘代码回退），
            不产生新告警；既有历史告警可经既有处置流程关闭。
        """
        baseline = getattr(self, "_code_baseline_ns", None)
        files = getattr(self, "_code_files", None)
        if baseline is None or not files:
            return
        try:
            changed = code_files_changed_since(baseline, files)
        except Exception:  # noqa: BLE001 — 陈旧检测非关键路径，失败静默跳过
            return
        if changed == self._code_stale:
            if not changed:
                # evo-add-stale-code-dangling-deadline 2.1：进程启动后首个「新鲜」
                # 检测确认 baseline 与磁盘一致——此后的假→真边沿才能精确取检测
                # 时刻（变更就发生在上一周期之后），而非笼统的启动时刻。
                self._stale_check_fresh_seen = True
            return
        self._code_stale = changed
        if changed:
            # 悬空起点（evo-add-stale-code-dangling-deadline 2.1）：假→真边沿
            # 记录 UTC 时刻。首检即陈旧（从未见过新鲜检测）说明启动前/启动窗口
            # 内代码已被改（或测试基线替身），无法定位真实变更时刻，按 SPEC 取
            # 进程启动时刻；其余边沿（上一周期仍新鲜）取当前检测时刻。
            if not getattr(self, "_stale_check_fresh_seen", False):
                self._code_stale_since = getattr(
                    self, "_proc_started_utc", None
                ) or datetime.now(timezone.utc)
            else:
                self._code_stale_since = datetime.now(timezone.utc)
            self.logger.warning(
                "fenixd",
                "检测到磁盘代码较进程启动时已更新（fenixd.py/core/**/*.py mtime 超 "
                "baseline），进程内校验规则可能为旧版，建议重启 daemon 生效"
                "（touch .fenix/restart_request）——stale_code_selfheal 启用时将在"
                "连续空闲后自动触发重启",
            )
            try:
                if self.admin_store is not None:
                    # 跨生命周期窗口去重（stale-code-alert-window-dedup 1.1）：
                    # 边沿触发只覆盖单 daemon 生命周期，高频提交下生命周期快速
                    # 轮换——每次重启新进程都再次「首次变陈旧」重复成条。写入
                    # 前查持久化存储：60 分钟窗口内已有同信号记录则跳过写入
                    # （降级为日志），去重状态复用 admin_alerts.json 天然跨重启
                    # 存活。超窗新周期照常成条，真·新陈旧周期不被吞。
                    recent = self.admin_store.latest_signal(
                        None, "stale_code", STALE_ALERT_DEDUP_MINUTES
                    )
                    if recent is not None:
                        self.logger.info(
                            "fenixd",
                            f"stale_code 告警窗口去重命中："
                            f"{STALE_ALERT_DEDUP_MINUTES} 分钟内已有同信号记录"
                            f"（created {recent.get('created')}），跳过写入仅留日志",
                        )
                    else:
                        # evo-reduce-stale-code-selfheal-noise 2.2：按自愈健康谓词
                        # 分流。健康（selfheal enabled 且未悬空超限）→ info 级留痕；
                        # disabled → 沿用既有 escalation 写入路径（下方保留原块）。
                        # 悬空超限不在此分流——其升级由 _alert_dangling_timeout
                        # 以独立 signal_type=stale_code_dangling_timeout 承接，
                        # 此处双重写入只会重复成条。
                        if self._stale_selfheal_healthy():
                            rec = self.admin_store.append(
                                {
                                    "kind": INFO,
                                    "signal_type": "stale_code",
                                    "spec": None,
                                    "severity": "info",
                                    "description": (
                                        "daemon 进程持旧代码，陈旧自愈已启用且链路健康，"
                                        "将在连续空闲后自动重启装载新代码"
                                    ),
                                    "evidence": (
                                        "fenixd 30s 检测点：fenixd.py/core/**/*.py mtime "
                                        "超进程启动 baseline"
                                    ),
                                    "action_taken": (
                                        "fenixd 陈旧检测命中，按 info 级留痕"
                                        "（自愈健康路径降噪，不进人工队列）"
                                    ),
                                    "recommended_action": (
                                        "无需人工干预：连续空闲达到 "
                                        "stale_code_selfheal.idle_confirm_seconds"
                                        "（缺省 600 秒）后自适应重启；如需立即生效可 "
                                        "touch .fenix/restart_request 或手动重启 "
                                        "daemon；关闭自愈见 stale_code_selfheal.enabled"
                                    ),
                                    # info 级无处理生命周期（mark_handled 仅锚定
                                    # ESCALATION，语义不可放宽）：写入 payload 自带
                                    # handled=true + handled_at 落盘，避免该记录在
                                    # read_all 遍历视图里呈现为永久未处理。
                                    "handled": True,
                                    "handled_at": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                            # 日计数（跨重启存活）：当日累计以 admin_alerts.json 中
                            # 当日 signal_type=stale_code 记录数计——进程内计数器在
                            # daemon 高频自愈重启下每次归零，撑不起「当日」语义。
                            self.logger.info(
                                "fenixd",
                                f"stale_code info 级留痕已写入（id {rec['id']}），"
                                f"当日累计 {self._stale_code_daily_count()} 条",
                            )
                        else:
                            # 降噪（2026-09-13 用户决策）：陈旧是可自愈收敛的持续状态，
                            # 降为 warning 级——写入即自动标记已处理，不进人工告警横幅/
                            # 待处理队列（复用 token_budget 同款处置），仅留历史记录。
                            # 状态边沿（假→真）触发写入，单个陈旧周期内不会重复堆积，
                            # 故不再依赖「未处置告警去重」。本分支现为 selfheal
                            # disabled 的升级路径（evo-reduce-stale-code-selfheal-
                            # noise 2.3）：禁用即无自动收敛通道，维持 escalation 口径。
                            rec = self.admin_store.append(
                                {
                                    "kind": ESCALATION,
                                    "signal_type": "stale_code",
                                    "spec": None,
                                    "severity": "warning",
                                    "description": (
                                        "daemon 进程持旧代码，自愈将在连续空闲后触发重启"
                                        "（stale_code_selfheal 配置启用时）"
                                    ),
                                    "evidence": (
                                        "fenixd 30s 检测点：fenixd.py/core/**/*.py mtime "
                                        "超进程启动 baseline"
                                    ),
                                    "action_taken": "fenixd 陈旧检测命中，标记为警告（等待空闲自愈）",
                                    "recommended_action": (
                                        "无需人工干预：连续空闲达到 "
                                        "stale_code_selfheal.idle_confirm_seconds 后自适应重启；"
                                        "如需立即生效可 touch .fenix/restart_request 或手动重启 "
                                        "daemon；关闭自愈见 stale_code_selfheal.enabled"
                                    ),
                                }
                            )
                            if not severity_needs_human(rec.get("severity")):
                                self.admin_store.mark_handled(rec["id"])
            except Exception as e:
                self.logger.warning("fenixd", f"stale_code 告警写入失败（non-blocking）: {e}")
        else:
            # evo-add-stale-code-dangling-deadline 2.1：基线恢复新鲜 → 悬空起点
            # 清零、超时防重复写/告警边沿标志复位（下一悬空周期从零计量）。
            self._code_stale_since = None
            self._dangling_timeout_fired = False
            self._dangling_timeout_alert_fired = False
            self._stale_check_fresh_seen = True
            self.logger.info(
                "fenixd",
                "代码陈旧状态解除：磁盘代码与进程运行代码已一致（重启后新 baseline 或磁盘回退）",
            )

    def _stale_selfheal_healthy(self) -> bool:
        """自愈健康谓词（evo-reduce-stale-code-selfheal-noise 2.2，写入时点可判定）。

        「健康」= stale_code_selfheal.enabled 且未悬空超限（_dangling_timeout_fired
        未触发）。「自愈重启请求成功发出并生效」发生在告警写入之后的 idle_confirm
        窗口末尾，不可写入时点判定，不作分支条件；写失败的升级在
        _maybe_stale_selfheal_tick 的 OSError 落点独立承接。配置读取异常按启用
        处理（与 _maybe_stale_selfheal_tick 的兜底口径一致）。
        """
        try:
            cfg = ConfigLoader.get_stale_code_selfheal_config(self.config)
            enabled = bool(cfg.get("enabled", True))
        except Exception:  # noqa: BLE001 — 配置读取异常按缺省启用处理
            enabled = True
        return enabled and not getattr(self, "_dangling_timeout_fired", False)

    def _stale_code_daily_count(self) -> int:
        """当日 stale_code 记录数（evo-reduce-stale-code-selfheal-noise 2.2）。

        以 admin_alerts.json 中当日（UTC 日界）signal_type=stale_code 的在册
        记录数计（read_all 遍历，info/escalation 两口径合计），跨重启存活；
        存储裁剪（MAX_RECORDS）只丢最旧历史，对「当日」读数的影响仅限极端
        高产日，可接受。读取失败按 0 计（仅用于日志，不阻断写入）。
        """
        try:
            today = datetime.now(timezone.utc).date().isoformat()
            records = self.admin_store.read_all()
        except Exception:  # noqa: BLE001 — 计数仅用于日志
            return 0
        count = 0
        for rec in records:
            if rec.get("signal_type") != "stale_code":
                continue
            created = str(rec.get("created") or "")
            if created[:10] == today:
                count += 1
        return count

    def _is_idle(self) -> bool:
        """空闲判定（add-stale-code-selfheal D2 + fix-state-atomicity-and-selfheal-restart D3
        + evo-stale-selfheal-restart-cooldown 2.1）：内部状态判定，不依赖外部进程扫描。

        「空闲」= ①``pm_engine`` 无活跃 run（``_active_runs == 0``，覆盖 planner /
        implementer / verifier / judge 全部 run 形态）**且** ②不存在未收口的在飞
        评审 run **且** ③``agent_runner._running_agents`` 为空 **且** ④admin 处置
        worker 池无在途任务 **且** ⑤无在飞 impl-ocr 车道（fix-fasttrack-implemented-
        deadstate 2.2，``pm_engine.ocr_lane_busy()`` 为假）。任一非空即判非空闲；
        ``_admin_executor`` 为 None（admin.workers=0 同步回退）时该维度视为空闲。
        admin 池在途数 = submitted - completed - failed（``_admin_pool_stats`` 计数，
        独立成法便于单测隔离）。

        ②为加强项（fix-state-atomicity-and-selfheal-restart D3）：评审 run
        **从不计入 ``_active_runs``**（``dispatch/queue.py`` 对 spec-review 派发
        分支显式 MUST NOT 增减它，只记 ``_active_reviews``），故
        ``_active_runs == 0`` 与「评审是否在飞」无关。2026-09-21 事故即评审 run
        处于 API 长重试（转录不增长）时被判空闲，连续 120s 后自愈 SIGTERM 杀掉
        在跑 run。故 MUST NOT 以「核对 ``_active_runs`` 递减时机」为修法，也 MUST NOT
        以转录新鲜度单独作在飞依据（停滞 run 的转录本就不增长）。

        ③为 evo-stale-selfheal-restart-cooldown 2.1 的进程注册表维度：
        ``agent_runner._running_agents`` 是 daemon 进程内 run 注册表（键 = run_id，
        值 = Popen），任何登记在册的 run 都计非空闲（含 ② 的分层判据尚未覆盖的
        窗口）。读法用 getattr 链（与 fenixd.py 其它调用点同款）：裸对象 / CLI 态
        缺 agent_runner 属性时该维度视为空，MUST NOT 抛异常——本方法的「异常按
        非空闲」策略会把 AttributeError 吞成非空闲，使既有用例
        （tests/test_stale_code_selfheal.py::_DaemonParts 未设置该属性）失真。
        """
        if self.pm_engine is not None:
            try:
                if self.pm_engine._active_runs != 0:  # noqa: SLF001 — 既有内部状态复用
                    return False
            except Exception:
                return False  # 内部状态不可读按非空闲处理，宁紧勿松
            try:
                if self._review_lane_busy():
                    return False
            except Exception as e:  # noqa: BLE001 — 判定异常按非空闲处理（宁紧勿松）
                self.logger.warning(
                    "fenixd",
                    f"评审车道在飞判定异常（按非空闲处理，不触发自愈重启）: {e}",
                )
                return False
            # ⑤ fix-fasttrack-implemented-deadstate 2.2：在飞 impl-ocr 车道维度
            # （code-review item e557560d61c0：守卫链委托
            # _ocr_lane_selfheal_block 单点维护——getattr 链容错/仅采纳真 bool/
            # 异常按阻断=非空闲，三段语义与本维度原实现逐一等价，含非 callable
            # 替身落到「不阻断=空闲」的形态）。车道线程不进 _active_runs /
            # _running_agents（裸后台线程跑维护型 run），缺本维度时车道在飞
            # 即被判空闲，120s 后自愈 SIGTERM 杀掉在飞车道 run（2026-09-23 事故）。
            if self._ocr_lane_selfheal_block():
                return False
        if getattr(getattr(self, "agent_runner", None), "_running_agents", None) or {}:
            return False  # 有在飞 agent run（含评审 run）→ 非空闲
        if self._admin_executor is not None:
            with self._admin_pool_lock:
                stats = dict(self._admin_pool_stats)
            if stats["submitted"] - stats["completed"] - stats["failed"] > 0:
                return False
        return True

    def _ocr_lane_selfheal_block(self) -> bool:
        """在飞 impl-ocr 车道自愈阻断判定（fix-fasttrack-implemented-deadstate 2.2）。

        供 ``_maybe_stale_selfheal_tick`` 阻断原因体系（reason="ocr-lane" 边沿
        日志）使用，与 ``_is_idle`` 第五维同源（``pm_engine.ocr_lane_busy()``
        无参口径）：

        - getattr 链容错：瘦门面/替身缺 ``ocr_lane_busy`` 属性时该维度不阻断
          （不抛异常，替身用例不失真）；
        - 仅采纳真 bool True（``_review_lane_busy`` 读侧同纪律：替身返回非
          bool 不误判为阻断）；
        - 判定异常按阻断处理（宁紧勿松：车道在飞期间自愈重启会 SIGTERM 杀掉
          在飞车道 run）。
        """
        busy_fn = getattr(self.pm_engine, "ocr_lane_busy", None)
        if not callable(busy_fn):
            return False
        try:
            return busy_fn() is True
        except Exception as e:  # noqa: BLE001 — 判定异常按阻断处理（宁紧勿松）
            self.logger.warning(
                "fenixd",
                f"ocr 车道在飞判定异常（按阻断处理，不触发自愈重启）: {e}",
            )
            return True

    def _codefix_selfheal_block(self) -> bool:
        """code-fix 批在飞自愈阻断判定（09-23 批5/6 烧毁事故热修）。

        supervisor 优雅重启会 SIGKILL 排水中的批 worker：run result 已落盘
        success 而回归/合回/核销未跑的批，其 agent 产出随 worktree 孤儿清扫
        整批作废（09-23 批 5/6 连烧实证：两次重启各毁一批）。两条判定任一
        命中即阻断：

        - ``fix-progress.json`` ``running=true``（链在飞，覆盖 fixing/
          regressing/merging 全程）；
        - agent_runner 在飞注册表含 ``code-fix-`` 前缀 run（兜底进度文件
          异常窗口）。

        判定异常按阻断处理（宁紧勿松，同 ocr-lane 纪律）。
        """
        try:
            from core.code_fix import read_progress

            if read_progress(PROJECT_ROOT).get("running") is True:
                return True
        except Exception as e:  # noqa: BLE001 — 判定异常按阻断处理
            self.logger.warning(
                "fenixd",
                f"code-fix 进度读取异常（按在飞阻断处理，不触发自愈重启）: {e}",
            )
            return True
        try:
            runner = getattr(self, "agent_runner", None)
            running = getattr(runner, "_running_agents", None) or {}
            if any(str(rid).startswith("code-fix-") for rid in running):
                return True
        except Exception as e:  # noqa: BLE001 — 判定异常按阻断处理
            self.logger.warning(
                "fenixd",
                f"code-fix 在飞注册表读取异常（按在飞阻断处理）: {e}",
            )
            return True
        return False

    # 重启历史保留窗口（evo-stale-selfheal-restart-cooldown）：超过该时长的条目
    # 在 tick 入口清理，避免文件无界增长（只影响统计，不影响自愈正确性）。
    _RESTART_HISTORY_KEEP_SECONDS = 24 * 3600

    @staticmethod
    def _restart_history_path() -> Path:
        """自愈重启历史文件路径（append-only JSONL，冷却与自触发判定的数据源）。"""
        return PROJECT_ROOT / ".fenix" / "restart_history.jsonl"

    @staticmethod
    def _parse_history_ts(raw) -> Optional[float]:
        """解析 restart_history 条目的 ``ts``（ISO8601；容忍 Z 后缀与 epoch 数值）。

        无法解析返回 None（调用方按「该条忽略」处理，不抛异常）。
        """
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        # SPEC-B 批②：解析收拢 parse_ts（唯一入口，失败返回 None）。存量
        # 写入方恒为 aware（datetime.now(timezone.utc).isoformat()，1670 行）
        # 或 epoch 数值；naive 防御分支解读跟齐唯一策略（naive→本地）。
        parsed = parse_ts(raw)
        return parsed.timestamp() if parsed is not None else None

    @staticmethod
    def _history_streak(rec: dict) -> int:
        """读一条历史记录的 self_triggered_streak，缺失/非法按 0（该条忽略该字段）。"""
        value = rec.get("self_triggered_streak", 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            return 0
        return int(value)

    def _read_restart_history(self, now: float) -> list:
        """读取 .fenix/restart_history.jsonl → ``[{ts: float, self_triggered_streak: int}]``。

        同时清理超过 _RESTART_HISTORY_KEEP_SECONDS（24h）的旧条目（仅在确有过期
        条目时整体重写，避免每秒 tick 空写）。容错：文件不存在 / 不可读按空处理，
        单行损坏 / 非对象 / ts 不可解析的条目按「该条忽略」，任何异常不向上抛、
        不阻断自愈。
        """
        path = self._restart_history_path()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001 — 历史文件非关键路径，缺失/损坏按空
            return []
        entries = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:  # noqa: BLE001 — 单行损坏按该条忽略
                continue
            if not isinstance(rec, dict):
                continue
            ts = self._parse_history_ts(rec.get("ts"))
            if ts is None:
                continue
            entries.append(
                {
                    "ts": ts,
                    "self_triggered": bool(rec.get("self_triggered", False)),
                    "self_triggered_streak": self._history_streak(rec),
                }
            )
        cutoff = now - self._RESTART_HISTORY_KEEP_SECONDS
        fresh = [e for e in entries if e["ts"] >= cutoff]
        if len(fresh) != len(entries):
            self._write_restart_history(fresh)
        return fresh

    def _write_restart_history(self, entries: list) -> None:
        """整体重写历史文件（仅清理路径使用）；失败仅记日志。

        原子写（code-review item 7152c09095f8，对齐 _write_preserve_sidecar）：
        旧实现固定名 .tmp + write_text 无 fsync，SIGKILL/断电落在写入与 replace
        之间会留半截文件——读侧 _read_restart_history 逐行容错会跳过损坏尾行，
        而尾行恰携带最新 self_triggered_streak，streak 归零使重启循环 critical
        告警与冷却窗口计数低估。改用同目录 mkstemp + fsync + os.replace，
        失败清理残留 tmp。
        """
        path = self._restart_history_path()
        tmp_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = "".join(
                json.dumps(
                    {
                        "ts": from_epoch(e["ts"]).isoformat(),
                        "self_triggered": bool(e.get("self_triggered", False)),
                        "self_triggered_streak": e["self_triggered_streak"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
                for e in entries
            )
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_str, str(path))
        except Exception as e:  # noqa: BLE001 — 清理失败不影响自愈
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
            self.logger.warning("fenixd", f"restart_history 清理写入失败（non-blocking）: {e}")

    def _append_restart_history(self, record: dict) -> None:
        """追加一条重启记录到 .fenix/restart_history.jsonl；写失败不阻断重启。

        追加而非重写：同一路径由 tick（清理）与重启成功路径并发使用时，append
        模式的写窗口最小（清理走 temp+rename，见 _write_restart_history）。
        """
        path = self._restart_history_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:  # noqa: BLE001 — 写失败仅记日志（SPEC：不阻断重启）
            self.logger.warning("fenixd", f"restart_history 追加失败（non-blocking）: {e}")

    def _record_selfheal_restart(
        self, *, history: list, window: int, threshold: int
    ) -> int:
        """记录一次自愈重启，返回累计 self_triggered_streak。

        streak 以「重启周期」为单位（同一进程内多次 tick 只计一次，收尾重启时
        才落一条），并按下列规则持久化累计——只放进程内存则阈值恒不可达：
          - 本周期在自触发窗口内陈旧再现（_self_triggered_cycle）→ 上一条
            streak + 1（循环延续：本次重启正是上一轮重启的后果）；
          - 否则（距上条记录 ≥ window 的过期重启）→ 归零（循环已断）。

        抑制门保证「窗口内不会写入历史」（窗口内一律不触发重启），故这里的延续
        判定只由 _self_triggered_cycle 承载：窗口内重启的 +1 等价于该标记，距上条
        ≥ window 的归零等价于标记为空——无须再比对 gap（那样得到的恒为同一结论）。

        streak 达 threshold 起（>= 判定：阈值经热更新可被调低于已累计 streak，
        等值判定将令 critical 告警永久静默）经 AdminStore 升
        ``signal_type: stale_selfheal_loop`` / ``severity: critical`` 告警——
        以「本循环已告警」标记去重，不逐周期重复堆积同一循环的告警；标记在
        循环断裂处（streak 归零/陈旧解除）复位，下一循环不受旧标记压制。
        """
        prev_streak = int(history[-1]["self_triggered_streak"]) if history else 0
        self_triggered = bool(getattr(self, "_self_triggered_cycle", False))
        streak = prev_streak + 1 if self_triggered else 0
        self._append_restart_history(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "self_triggered": self_triggered,
                "self_triggered_streak": streak,
            }
        )
        self._self_triggered_cycle = False
        if not self_triggered:
            # 循环已断（streak 归零）：解除「本循环已 critical 告警」去重标记
            self._selfheal_loop_alerted = False
        if streak >= threshold and not getattr(self, "_selfheal_loop_alerted", False):
            self._selfheal_loop_alerted = True
            self._alert_selfheal_loop(streak, threshold, window)
        return streak

    def _alert_selfheal_cooldown(
        self, recent_count: int, threshold: int, window: int, duration: int
    ) -> None:
        """冷却首次进入（边沿）：INFO 日志 + stale_selfheal_cooldown 告警（warning）。

        MUST NOT 复用 stale_code 类型——该类型写入即自动 mark_handled
        （_update_stale_code_state），复用会被当已处置吞掉，人工看不到过频重启。
        """
        self.logger.info(
            "fenixd",
            f"陈旧自愈进入冷却：{int(window)}s 窗口内自愈重启 {recent_count} 次"
            f"（阈值 {threshold}），暂停自愈触发 {int(duration)}s"
            "（陈旧状态与告警仍保持，仅跳过触发重启）",
        )
        try:
            admin_store = getattr(self, "admin_store", None)
            if admin_store is not None:
                admin_store.append(
                    {
                        "kind": ESCALATION,
                        "signal_type": "stale_selfheal_cooldown",
                        "spec": None,
                        "severity": "warning",
                        "description": (
                            "陈旧自愈重启过频（滑动窗口内达阈值），已进入冷却并暂停"
                            "自愈触发，避免重启正反馈循环杀死在飞 run"
                        ),
                        "evidence": (
                            f"restart_history 窗口 {int(window)}s 内 {recent_count} 次"
                            f"自愈重启，阈值 {threshold}；冷却锁存 {int(duration)}s"
                        ),
                        "action_taken": "冷却锁存期内跳过自愈触发（陈旧状态与告警仍保持）",
                        "recommended_action": (
                            "无需立即干预：冷却期满自动恢复；若反复进入冷却，核查是否"
                            "存在重启循环（.fenix/restart_history.jsonl），必要时临时"
                            "置 stale_code_selfheal.enabled: false"
                        ),
                    }
                )
        except Exception as e:  # noqa: BLE001 — 告警写入失败不阻断自愈
            self.logger.warning("fenixd", f"stale_selfheal_cooldown 告警写入失败（non-blocking）: {e}")

    def _alert_dangling_timeout(self, dangling_seconds: float, max_dangling: int) -> None:
        """悬空超时升级告警（evo-add-stale-code-dangling-deadline 3.1）。

        新 signal_type=stale_code_dangling_timeout / severity=warning，MUST NOT
        复用 stale_code 类型——该类型写入即自动 mark_handled
        （_update_stale_code_state，2026-09-13 降噪决策），复用会被当已处置
        吞掉，人工看不到忙时强推重启的升级事件。本告警也不写入即 handled：
        悬空超时重启会排水中断在飞 run（有界重跑代价），属「需人工知悉」，
        须进人工待处理视图（参照 stale_selfheal_cooldown 的写入模式）。

        写入前经 latest_signal 做 STALE_ALERT_DEDUP_MINUTES（60 分钟）窗口去重：
        同 stale-code-alert-window-dedup 的跨生命周期 rationale——超时重启加载
        新代码后若再次悬空超时，是新升级事件照常成条；60 分钟内的重复命中
        跳过写入降级为日志，去重状态复用 admin_alerts.json 天然跨重启存活。
        """
        self.logger.warning(
            "fenixd",
            f"陈旧悬空升级：持旧代码悬空 {dangling_seconds:.0f}s 超过时限 "
            f"{int(max_dangling)}s，忙时强制规划性重启（需人工知悉：在飞 run "
            "被排水中断，有界重跑）",
        )
        try:
            admin_store = getattr(self, "admin_store", None)
            if admin_store is not None:
                recent = admin_store.latest_signal(
                    None, "stale_code_dangling_timeout", STALE_ALERT_DEDUP_MINUTES
                )
                if recent is not None:
                    self.logger.info(
                        "fenixd",
                        f"stale_code_dangling_timeout 告警窗口去重命中："
                        f"{STALE_ALERT_DEDUP_MINUTES} 分钟内已有同信号记录"
                        f"（created {recent.get('created')}），跳过写入仅留日志",
                    )
                    return
                # 注意：不调用 mark_handled——升级事件须留在人工待处理视图
                admin_store.append(
                    {
                        "kind": ESCALATION,
                        "signal_type": "stale_code_dangling_timeout",
                        "spec": None,
                        "severity": "warning",
                        "description": (
                            "daemon 持旧代码悬空超过 max_dangling_seconds 时限，"
                            "已不再等待空闲、直接触发规划性重启（在飞 run 经 "
                            "planned_restart 排水宽限收尾或断点续做）"
                        ),
                        "evidence": (
                            f"悬空 {dangling_seconds:.0f}s > 时限 {int(max_dangling)}s"
                            "（stale_code_selfheal.max_dangling_seconds）；悬空起点见"
                            " _code_stale_since（UTC）"
                        ),
                        "action_taken": (
                            "touch .fenix/restart_request 强制规划性重启（cooldown/"
                            "self-triggered 闸门仍生效）"
                        ),
                        "recommended_action": (
                            "无需立即干预：重启使已合回修复生效、在飞 run 断点续做；"
                            "若频繁出现，核查提交/合回节律与 max_dangling_seconds "
                            "取值是否匹配，必要时调大时限或置 0 关闭升级（仅保留"
                            "空闲自愈）"
                        ),
                    }
                )
        except Exception as e:  # noqa: BLE001 — 告警写入失败不阻断自愈重启
            self.logger.warning(
                "fenixd", f"stale_code_dangling_timeout 告警写入失败（non-blocking）: {e}"
            )

    def _alert_selfheal_write_failure(self, error: OSError) -> None:
        """自愈动作失败升级告警（evo-reduce-stale-code-selfheal-noise 2.3）。

        空闲确认达成却 touch .fenix/restart_request 失败（OSError）= 自动收敛
        通道已断，原先仅 logger.error、无人知悉。本方法补一条 escalation：
        signal_type 仍取 stale_code（与健康路径 info 留痕同信号族，共用 60 分钟
        去重窗口——写失败与留痕互斥成条，不刷屏），severity=warning 且不调用
        mark_handled——须留在人工待处理视图（参照 _alert_dangling_timeout 的
        写入模式；mark_handled 仅锚定 ESCALATION 的闭环锚点语义不受影响）。
        悬空超限路径的写失败不经过此处：该路径本就有独立升级告警，重复写入
        只会双重升级。
        """
        try:
            admin_store = getattr(self, "admin_store", None)
            if admin_store is not None:
                recent = admin_store.latest_signal(
                    None, "stale_code", STALE_ALERT_DEDUP_MINUTES
                )
                if recent is not None:
                    self.logger.info(
                        "fenixd",
                        f"stale_code 写失败升级窗口去重命中："
                        f"{STALE_ALERT_DEDUP_MINUTES} 分钟内已有同信号记录"
                        f"（created {recent.get('created')}），跳过写入仅留日志",
                    )
                    return
                # 注意：不调用 mark_handled——升级事件须留在人工待处理视图
                admin_store.append(
                    {
                        "kind": ESCALATION,
                        "signal_type": "stale_code",
                        "spec": None,
                        "severity": "warning",
                        "description": (
                            "daemon 持旧代码且空闲确认已达成，但自愈重启请求"
                            "（.fenix/restart_request）写入失败，自动收敛通道"
                            "中断，需人工知悉"
                        ),
                        "evidence": (
                            f"restart_request 写入 OSError: {error}；空闲计时已"
                            "复位，下个检测 tick 自动重试"
                        ),
                        "action_taken": "记录 error 日志并落本升级告警（陈旧状态保持，触发自动重试）",
                        "recommended_action": (
                            "核查 .fenix 目录权限/磁盘空间与只读挂载；修复后自愈"
                            "将自动重试；如需立即生效可手动重启 daemon 或临时置 "
                            "stale_code_selfheal.enabled: false"
                        ),
                    }
                )
        except Exception:  # noqa: BLE001 — 告警写入失败不阻断自愈重试
            self.logger.warning(
                "fenixd", "stale_code 写失败升级告警写入异常（non-blocking）"
            )

    def _alert_selfheal_loop(self, streak: int, threshold: int, window: int) -> None:
        """自触发 streak 达阈值：stale_selfheal_loop 告警（critical，需人工判断）。"""
        try:
            admin_store = getattr(self, "admin_store", None)
            if admin_store is not None:
                admin_store.append(
                    {
                        "kind": ESCALATION,
                        "signal_type": "stale_selfheal_loop",
                        "spec": None,
                        "severity": "critical",
                        "description": (
                            f"陈旧自愈重启自触发循环：连续 {streak} 个重启周期在"
                            f"自触发窗口内再次判为陈旧（阈值 {threshold}）"
                        ),
                        "evidence": (
                            f"restart_history.self_triggered_streak={streak} ≥ "
                            f"{threshold}（自触发窗口 {int(window)}s）"
                        ),
                        "action_taken": "已记录自触发 streak 达阈值（重启仍按冷却策略节流）",
                        "recommended_action": (
                            "人工核查是否 evo run / 代码更新形成重启循环："
                            "查 .fenix/restart_history.jsonl 与近期 run 记录，"
                            "必要时临时置 stale_code_selfheal.enabled: false"
                        ),
                    }
                )
        except Exception as e:  # noqa: BLE001 — 告警写入失败不阻断自愈
            self.logger.warning("fenixd", f"stale_selfheal_loop 告警写入失败（non-blocking）: {e}")

    def _review_anchor_candidates(self) -> dict:
        """带短 TTL 的评审锚点候选读取（收敛 1s 轮询的 STATE 解析开销）。

        ``PMEngine.review_anchors()`` 每次都要解析整份 STATE.md（实测 279 条 spec
        约 14ms）；1s 粒度轮询下这是可观的固定开销，故按 design D3 加
        ``STALE_SELFHEAL_REVIEW_ANCHOR_CACHE_SECONDS``（2s，远小于
        ``idle_confirm_seconds``）短缓存。

        缓存对象**只是候选集合**：哪些 spec 带 ``reviewer_run`` 锚点。在飞**结论**
        每次都经 ``is_review_in_flight`` / ``reviewer_in_flight`` 实时复核，故
        缓存最多把「新出现的在飞评审」晚识别 TTL 秒（≪ 120s 确认窗口），
        MUST NOT 把在飞判成空闲超过该窗口。

        实例属性用 ``getattr`` 惰性初始化：测试以 ``FenixDaemon.__new__`` 构造裸
        对象（不跑 ``__init__``），不得因此抛 AttributeError。
        """
        now = time.time()
        cached = getattr(self, "_review_anchor_cache", None)
        if cached is not None and now - cached[0] < STALE_SELFHEAL_REVIEW_ANCHOR_CACHE_SECONDS:
            return cached[1]
        anchors = self.pm_engine.review_anchors()
        if not isinstance(anchors, dict):
            anchors = {}
        self._review_anchor_cache = (now, anchors)
        return anchors

    def _review_lane_busy(self) -> bool:
        """是否存在未收口的在飞评审 run（候选收窄 + 命中即短路）。

        fix-state-atomicity-and-selfheal-restart D3：判定口径与派发守卫
        （``core/pm_engine/engine.py:_on_spec_ready`` 派发前在飞评审校验）**同源**，
        按评审在飞生命周期的两段拼合：

        ⓪ ``PMEngine.has_queued_review()``——覆盖「评审条目已入队、``reviewer_run``
           锚点尚未落盘」的窗口（此段 STATE 里没有任何锚点可枚举，只有
           ``_active_reviews`` 登记）；
        ① ``PMEngine.is_review_in_flight(spec_name)``——同上窗口的 per-spec 口径；
        ② ``LivenessSupervisor.reviewer_in_flight(spec_name, reviewer_run)``——
           分层判据（``_active_reviews`` → **进程表 ``running_run_ids()``** →
           流文件新鲜度 → 陈旧锚点）。**进程表判据**才是「停滞 run 仍算在飞」的
           成立依据（API 长重试期转录不增长但进程存活），流文件新鲜度 MUST NOT
           单独作在飞依据。

        开销约束（主循环 1s 粒度，见 ``_maybe_stale_selfheal_tick``）：候选先经
        ``_review_anchor_candidates`` 收窄为 ``reviewer_run`` 非空者（拒绝全量
        STATE 条目逐条判定），命中任一在飞**立即返回**，不做其余条目判定。实测
        真实 STATE.md（279 条 spec）单次解析约 14ms，按 design D3 以 2s 短 TTL
        缓存候选集合收敛该固定开销（在飞结论仍逐次实时复核）。

        反向约束（D3/3.2）：陈旧锚点（run 已终态但锚点残留）经判据 ② 返回
        ``(False, "stale")`` 天然不占位——本方法 MUST NOT 自造「锚点非空即非空闲」
        的永真条件，否则自愈永不触发。
        """
        # ① 入队未落盘窗口：评审登记已在册但 STATE 尚无锚点（O(1) 锁读，
        #    锚点枚举覆盖不到这一段）。只在返回真 bool 时采纳——瘦门面/替身
        #    返回非 bool 不误判为非空闲。
        queried = self.pm_engine.has_queued_review()
        if isinstance(queried, bool) and queried:
            return True
        anchors = self._review_anchor_candidates()
        if not isinstance(anchors, dict) or not anchors:
            # 无候选（含瘦门面/替身返回非 dict）：无在飞评审，不启用评审维度。
            # 候选为空即无评审 run 的锚点落点，无需再做任何探测。
            return False
        for spec_name, reviewer_run in anchors.items():
            try:
                if self.pm_engine.is_review_in_flight(spec_name):
                    return True  # ② 入队/出队窗口，命中即短路
            except Exception:  # noqa: BLE001 — 判据异常按在飞处理（宁紧勿松）
                return True
            try:
                in_flight, _reason = self.pm_engine.agent_runner.reviewer_in_flight(
                    spec_name, reviewer_run
                )
            except Exception:  # noqa: BLE001 — 判据异常按在飞处理（宁紧勿松）
                return True
            if in_flight:
                # ③ 进程存活（停滞 run 亦命中）/ 流新鲜；"stale" 等否定结论不占位
                return True
        return False

    def _maybe_stale_selfheal_tick(self) -> None:
        """陈旧自愈触发（add-stale-code-selfheal 2.2/2.3，主循环 1s 粒度轮询）。

        前置：self._code_stale 为真 + stale_code_selfheal.enabled 为真 + 项目受
        supervisor 托管（supervisor_running）且 .fenix/restart_request 不在册。
        满足前置且空闲时累计连续空闲时长，达到 idle_confirm_seconds 后 touch
        .fenix/restart_request（复用既有 supervisor 优雅重启协议，不改变协议
        语义）并记录触发日志（含触发原因与等待时长）。任一阻断/非空闲信号
        出现立即清零计时。阻断原因按状态边沿记日志（原因变化时打一次），
        不刷屏。

        evo-stale-selfheal-restart-cooldown 增量（插在 in-flight 阻断之后、
        _is_idle 之前，不影响首次触发流程）：
          - 重启历史：tick 入口读取 .fenix/restart_history.jsonl 并清理 24h 前
            条目（容错，见 _read_restart_history）。
          - 冷却：窗口内重启数 ≥ cooldown_threshold **或** 冷却锁存未到期
            （now - _cooldown_started_at < cooldown_duration_seconds）→ 不触发、
            清零 idle 计时；首次进入（边沿）落一条 stale_selfheal_cooldown 告警。
          - 自触发：距上次重启 < self_triggered_window_seconds 而再次判可触发 →
            只记一次 WARNING、不写 restart_request（本周期标记自触发），窗口
            过期后照常重启并在写历史时累计 streak，达阈值升
            stale_selfheal_loop critical 告警。
        """
        req = PROJECT_ROOT / ".fenix" / "restart_request"
        if not self._code_stale:
            # 状态解除：清零计时与边沿记忆，恢复正常（自触发周期随陈旧一并收尾）；
            # stale_selfheal_loop 去重标记一并复位（循环随陈旧解除终结）
            self._stale_idle_since = None
            self._heal_block_reason = None
            self._self_triggered_cycle = False
            # evo-add-stale-code-dangling-deadline 2.3：悬空周期收尾，超时防重复
            # 写标志（含自触发窗口内告警边沿标志，item a6fb64ba17d4）一并复位
            # （下一悬空周期允许再次超时触发）。
            self._dangling_timeout_fired = False
            self._dangling_timeout_alert_fired = False
            self._selfheal_loop_alerted = False
            return

        now = time.time()
        # 重启历史（冷却窗口计数 / 自触发窗口 / streak 累计的数据源），入口清理
        history = self._read_restart_history(now)

        # 阻断原因判定（边沿日志：仅原因变化时打一次明示，避免 1s 粒度刷屏）
        reason = None
        try:
            cfg = ConfigLoader.get_stale_code_selfheal_config(self.config)
        except Exception:  # noqa: BLE001 — 配置读取异常按缺省启用处理
            # 兜底缺省引用 ConfigLoader 常量（evo-reduce-stale-code-selfheal-
            # noise：原硬编码 120 与新缺省 600 漂移会放大重启节律；item
            # c79caa073d87：兜底字典全部键与下方冷却/自触发五键同口径引用
            # 常量，MUST NOT 硬编码字面量——ConfigLoader 侧调缺省时兜底值
            # 不随之更新会分裂出两套缺省）
            cfg = {
                "enabled": True,
                "idle_confirm_seconds": (
                    ConfigLoader.STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT
                ),
                "max_dangling_seconds": (
                    ConfigLoader.STALE_CODE_SELFHEAL_MAX_DANGLING_SECONDS_DEFAULT
                ),
            }
        enabled, confirm_seconds = bool(cfg.get("enabled", True)), cfg.get(
            "idle_confirm_seconds",
            ConfigLoader.STALE_CODE_SELFHEAL_IDLE_SECONDS_DEFAULT,
        )
        # 冷却/自触发五键的读取缺省同样引用 ConfigLoader 常量（item
        # c79caa073d87：与上方 idle_confirm_seconds 既有口径对齐——两条读取
        # 路径 MUST 共用同一套缺省，防 ConfigLoader 侧调缺省后此处漂移）
        cooldown_window = cfg.get(
            "cooldown_window_seconds",
            ConfigLoader.STALE_CODE_SELFHEAL_COOLDOWN_WINDOW_SECONDS_DEFAULT,
        )
        cooldown_threshold = cfg.get(
            "cooldown_threshold",
            ConfigLoader.STALE_CODE_SELFHEAL_COOLDOWN_THRESHOLD_DEFAULT,
        )
        cooldown_duration = cfg.get(
            "cooldown_duration_seconds",
            ConfigLoader.STALE_CODE_SELFHEAL_COOLDOWN_DURATION_SECONDS_DEFAULT,
        )
        self_triggered_window = cfg.get(
            "self_triggered_window_seconds",
            ConfigLoader.STALE_CODE_SELFHEAL_SELF_TRIGGERED_WINDOW_SECONDS_DEFAULT,
        )
        self_triggered_threshold = cfg.get(
            "self_triggered_threshold",
            ConfigLoader.STALE_CODE_SELFHEAL_SELF_TRIGGERED_THRESHOLD_DEFAULT,
        )
        if not enabled:
            reason = "disabled"
        elif req.exists():
            reason = "in-flight"
        else:
            try:
                from core.fenix_session import supervisor_running

                supervised = supervisor_running(PROJECT_ROOT)
            except Exception:
                supervised = False  # /proc 不可读等：按未托管处理，宁紧勿松
            if not supervised:
                reason = "unmanaged"
            elif self._ocr_lane_selfheal_block():
                # fix-fasttrack-implemented-deadstate 2.2：在飞 impl-ocr 车道
                # 挂入阻断原因体系——车道跑着不自愈（重启会 SIGTERM 杀掉在飞
                # 车道 run），空闲计时一并清零，车道收尾后重新累计。
                reason = "ocr-lane"
            elif self._codefix_selfheal_block():
                # 09-23 批5/6 烧毁事故：code-fix 批在飞期间自愈重启会把回归
                # 进行中/收尾中的批 worker 连带杀掉（supervisor 排水 SIGKILL），
                # agent 已产出的批结果随 worktree 孤儿清扫整批作废——镜像
                # ocr-lane 模式挂入阻断体系，空闲计时一并清零。
                reason = "code-fix"

        if reason is not None:
            # 阻断 → 清零空闲计时；边沿日志明示原因
            if reason != self._heal_block_reason:
                self._heal_block_reason = reason
                if reason == "disabled":
                    self.logger.info(
                        "fenixd",
                        "陈旧自愈已被配置关闭（stale_code_selfheal.enabled: false），"
                        "不触发重启（陈旧状态与告警仍保持）",
                    )
                elif reason == "unmanaged":
                    self.logger.info(
                        "fenixd",
                        "未受 supervisor 托管，自愈跳过（restart_request 无人消费，"
                        "陈旧告警维持，等待恢复托管）",
                    )
                elif reason == "ocr-lane":
                    self.logger.info(
                        "fenixd",
                        "impl-ocr 车道在飞，自愈跳过（不杀在飞车道 run），"
                        "空闲计时清零，待车道收尾后重新累计",
                    )
                elif reason == "code-fix":
                    self.logger.info(
                        "fenixd",
                        "code-fix 批在飞，自愈跳过（不杀批 worker/回归），"
                        "空闲计时清零，待批收尾后重新累计",
                    )
                else:  # in-flight
                    self.logger.info(
                        "fenixd",
                        "restart_request 已在，重启在途，自愈不重复写入",
                    )
            self._stale_idle_since = None
            return

        # 自触发型 stale 判定与标记（FR-3）：距上次自愈重启 < self_triggered_window_seconds
        # 时陈旧再现 → 本轮陈旧是上一轮重启的自触发产物（重启后 5 分钟内再次检测到
        # stale），本周期标记为自触发并落一次 WARNING；窗口过期前不写 restart_request
        # （此刻重启只会延长循环），窗口过期后由同一连续空闲收尾重启，收尾时按标记
        # 累计持久化 streak。
        # 位置约束：MUST 早于冷却早退——否则窗口计数达冷却阈值后永远到不了标记分支，
        # self_triggered_streak 恒不可达阈值（缺省阈值下 critical 告警永不触发）。
        last_restart = history[-1]["ts"] if history else None
        self_triggered_now = (
            last_restart is not None and (now - last_restart) < self_triggered_window
        )
        if self_triggered_now and not getattr(self, "_self_triggered_cycle", False):
            self._self_triggered_cycle = True
            self.logger.warning(
                "fenixd",
                f"检测到自触发型陈旧：距上次自愈重启仅 {now - last_restart:.0f}s"
                f"（< {int(self_triggered_window)}s 窗口）陈旧再现，本周期仅告警、"
                "不触发重启（待窗口过期后由后续周期收尾）；若反复出现说明存在"
                "重启循环（见 stale_selfheal_loop 告警）",
            )

        # 冷却检查（窗口计数 OR 锁存未到期）：两个条件任一成立即不触发重启。
        # 放此位置：in-flight 阻断之后、_is_idle 之前——不影响正常的首次触发流程。
        cooldown_started = getattr(self, "_cooldown_started_at", None)
        latched = (
            cooldown_started is not None
            and (now - cooldown_started) < cooldown_duration
        )
        recent_restarts = len(
            [e for e in history if (now - e["ts"]) <= cooldown_window]
        )
        # [fenix-ignore:81d7b258e3b5] 误报：_cooldown_started_at 在整段冷却（锁存 OR 窗口计数超阈）持续期内保持非 None，下方清锁存仅在两条件均转假（冷却整体退出）时才执行，锁存到期而计数仍超阈的 tick 走 if 体但不满足 is None 边沿条件，不会重复告警（tests/test_stale_selfheal_cooldown.py::test_cooldown_alert_is_edge_only 已锁定该行为）
        if latched or recent_restarts >= cooldown_threshold:
            if cooldown_started is None:
                # 首次进入冷却（边沿）：置锁存起点 + 一次告警/日志，后续 tick 不重复
                self._cooldown_started_at = now
                self._alert_selfheal_cooldown(
                    recent_restarts, cooldown_threshold, cooldown_window, cooldown_duration
                )
            self._stale_idle_since = None
            return
        # 冷却已退出：清锁存起点，使下次进入重新按边沿告警
        self._cooldown_started_at = None

        # ── 悬空超时分支（evo-add-stale-code-dangling-deadline 2.2/2.3）────
        # _code_stale 持续超过 stale_code_selfheal.max_dangling_seconds（缺省
        # 4h，0 = 关闭升级）时不再等待空闲：当前负载形态几乎不产生连续空闲
        # 窗口，无限期悬空等于已合回修复被静默（2026-09-24 单日实测 2.1h
        # 停摆）。本分支位于冷却/自触发闸门之后（冷却窗口/锁存期内到不了
        # 这里，仍受闸门约束）、_is_idle 之前——忙时也直接写 restart_request，
        # 在飞 run 由 supervisor planned_restart 排水兜底（60s 宽限 + checkpoint
        # 保全 + 断点续做）。缺省配置下悬空超时触发时距上次自愈重启必然已超
        # self_triggered_window_seconds（重启即刷新 baseline，_code_stale 归零
        # 重新起算）；但 max_dangling_seconds 是独立可配的非负整数、允许配成
        # 小于自触发窗口，此时悬空时限可能在窗口内到期——由下方
        # self_triggered_now 守卫拦下不写请求（code-review item 74da2c8c7864，
        # FR-3「窗口内不写请求」语义优先于悬空升级）。本分支不触碰
        # _self_triggered_cycle（不强制置真），_record_selfheal_restart 按既有
        # 语义如实记录。
        max_dangling = cfg.get(
            "max_dangling_seconds",
            ConfigLoader.STALE_CODE_SELFHEAL_MAX_DANGLING_SECONDS_DEFAULT,
        )
        stale_since = getattr(self, "_code_stale_since", None)
        dangling_seconds = (
            (now - stale_since.timestamp())
            if stale_since is not None
            else None
        )
        if (
            max_dangling
            and max_dangling > 0
            and dangling_seconds is not None
            and dangling_seconds > max_dangling
        ):
            if self_triggered_now:
                # FR-3 语义守卫（code-review item 74da2c8c7864）：max_dangling_seconds
                # 允许配成小于 self_triggered_window_seconds，悬空超时可能在
                # 自触发窗口内到期——窗口内仅落升级告警不写 restart_request
                # （避免延长重启循环），窗口过期后由后续 tick 在此收尾触发
                # （dangling_seconds 只增不减，无需重新起算）。
                # 边沿控制（code-review item a6fb64ba17d4）：_alert_dangling_timeout
                # 入口的 logger.warning 在 admin 侧 60 分钟窗口去重判断之前无条件
                # 执行，1s 粒度下本分支不加防重复会在自触发窗口（缺省 300s）内
                # 每秒打一条同文 WARNING——此处以独立边沿标志保证告警与 WARNING
                # 仅本悬空周期首次命中执行、后续 tick 直接 return。MUST NOT 复用
                # _dangling_timeout_fired：那会把窗口过期后的收尾重启一并拦下
                # （下方防重复写守卫读的是同一标志）。
                if getattr(self, "_dangling_timeout_alert_fired", False):
                    return
                self._dangling_timeout_alert_fired = True
                self._alert_dangling_timeout(dangling_seconds, max_dangling)
                return
            if getattr(self, "_dangling_timeout_fired", False):
                # 防重复写（2.3）：本悬空周期已成功触发过，1s tick 直接跳过。
                # req 已在场的情形由上方 in-flight 阻断覆盖（req.exists() →
                # reason="in-flight" 早退），本标志兜底 supervisor 秒级消费
                # request 后、SIGTERM 到来前的窗口，避免重复 touch/重复告警。
                return
            self._stale_idle_since = None
            wrote = False
            try:
                req.parent.mkdir(parents=True, exist_ok=True)
                req.write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
                wrote = True
                self.logger.warning(
                    "fenixd",
                    f"陈旧悬空超时触发：daemon 持旧代码已 {dangling_seconds:.0f}s"
                    f"（超过 stale_code_selfheal.max_dangling_seconds "
                    f"{int(max_dangling)}s）且系统不再等待空闲，已 touch "
                    ".fenix/restart_request，supervisor 将执行规划性重启"
                    "（planned_restart 排水：在飞宽限收尾/checkpoint 保全/断点续做）",
                )
            except OSError as e:
                self.logger.error("fenixd", f"restart_request 写入失败: {e}")
            if wrote:
                # 触发成功才置防重复标志 + 写升级告警 + 落历史；写失败仅记
                # error 日志，标志未置位，下个 tick 自动重试。
                self._dangling_timeout_fired = True
                self._alert_dangling_timeout(dangling_seconds, max_dangling)
                self._record_selfheal_restart(
                    history=history,
                    window=self_triggered_window,
                    threshold=self_triggered_threshold,
                )
            return

        self._heal_block_reason = None
        if not self._is_idle():
            # 任一非空闲信号（活跃 run / 在飞评审 run / admin 在途）出现 → 立即清零计时
            self._stale_idle_since = None
            return

        if self._stale_idle_since is None:
            self._stale_idle_since = now
            return
        waited = now - self._stale_idle_since
        if waited >= confirm_seconds:
            if self_triggered_now:
                # 自触发窗口内不写 restart_request（仅告警）；不清零计时——窗口过期后
                # 由同一段连续空闲立即收尾，本周期标记在收尾重启时转为 streak
                return
            wrote = False
            try:
                req.parent.mkdir(parents=True, exist_ok=True)
                req.write_text(datetime.now(timezone.utc).isoformat() + "\n", encoding="utf-8")
                wrote = True
                self.logger.warning(
                    "fenixd",
                    f"陈旧自愈触发：daemon 持旧代码且连续空闲 {waited:.0f}s"
                    f"（阈值 {confirm_seconds}s），已 touch .fenix/restart_request，"
                    "supervisor 将执行优雅重启使新代码生效",
                )
            except OSError as e:
                # evo-reduce-stale-code-selfheal-noise 2.3：自愈动作失败的升级点。
                # 原先仅 logger.error——写失败意味着自动收敛通道已断（空闲确认
                # 达成却发不出重启请求），升级 escalation 提请人工知悉；复用
                # _alert_dangling_timeout 的 append + latest_signal 去重范式，
                # signal_type 仍取 stale_code（与 info 留痕同受 60 分钟窗口互斥
                # 成条，不刷屏）。陈旧状态保持，空闲计时已在 finally 复位——
                # 下个 tick 重新累计 idle_confirm_seconds 后自动重试。
                self.logger.error("fenixd", f"restart_request 写入失败: {e}")
                self._alert_selfheal_write_failure(e)
            finally:
                self._stale_idle_since = None
            if wrote:
                # 成功触发后才落历史（写失败仅记日志，不回滚重启）
                self._record_selfheal_restart(
                    history=history,
                    window=self_triggered_window,
                    threshold=self_triggered_threshold,
                )

    def _admin_monitor_loop(self):
        """周期运行健康检查（间隔 admin.interval_minutes）。

        启动首轮立即执行（add-alert-auto-resolve D4）：首轮扫描对存量
        handled=False 告警执行一次回填闭环判定，其后按间隔轮询。
        """
        while self.running:
            try:
                self.admin_monitor.run_once()
            except Exception as e:
                self.logger.error("admin_monitor", f"Admin monitor check failed: {e}")
            # 每轮重读间隔（对齐主循环自进化检查点的读法）：_maybe_reload_config
            # 热更新会原地刷新 admin_cfg 快照，interval_minutes 属性随之热生效。
            # float + 0.5 下限防 int 截断（0.5 类小数分钟变 0 再被 or 5 兜回缺省）。
            interval = max(float(self.admin_monitor.interval_minutes), 0.5)
            time.sleep(interval * 60)
            if not self.running:
                break

    @staticmethod
    def _consume_request_file(req_path, outcome=None):
        """原子消费文件信号：读+删作为整体，返回 payload dict 或 None。

        code-review item bfd39d85860e：dashboard 侧以 tempfile + os.replace 原子写
        信号文件；消费侧若「先 open/json.load 再 unlink」，则在**读之后、删之前**
        新落盘（或用户重复点击）的请求会被这个 unlink 一并删掉而从未被处理——用户
        操作静默丢失（旧注释只覆盖「删失败=已被消费」的反向窗口）。改为先把文件
        rename 到进程唯一临时名（原子占位：新写入者拿到的是全新路径、不会被误删），
        再读该私有副本并删除；读取/解析失败同样返回 None 并清理。

        code-review item 94618d6567ee：outcome 为可选 dict 出参，记录返回 None
        的归因——"absent"=信号不在场或已被并发取走；"io"=mkstemp/rename 阶段
        IO 异常（磁盘满/权限等），信号**未被消费**仍留盘待下轮重试；
        "payload"=信号已消费但内容非法/不可读。消费方（code_review 车道）据此
        区分「payload 非法」与「IO 异常」，后者不落 invalid_payload 结果。
        其余调用方不传 outcome，返回形态与行为完全不变。
        """
        if outcome is None:
            outcome = {}
        # 「信号不存在」是各车道每秒轮询的绝对常态，先 exists() 判空避免稳态下每轮 mkstemp+unlink 的无谓churn（item 97fdc0ac0a2f）
        if not req_path.exists():
            outcome["kind"] = "absent"
            return None
        tmp_path = None
        try:
            # 私有副本后缀 MUST NOT 是 .json（code-review item bd0b3d74ebca，
            # 对齐 scheduling_kick 消费器 item e286692801c1 同型教训）：
            # os.replace 占位与 finally unlink 之间被 SIGKILL/断电时，.fenix/
            # 下会留下 .json 结尾的残留且无任何回收方、永久堆积；去后缀命名
            # 由 _reclaim_consumed_request_residues 按 mtime 阈值统一回收
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{req_path.name}.consumed.",
                dir=str(req_path.parent),
            )
            os.close(fd)
            tmp_path = Path(tmp_str)
            os.replace(str(req_path), str(tmp_path))
        except FileNotFoundError:
            # 信号文件不存在（稀疏事件的绝大多数轮次）：mkstemp 已建出私有临时
            # 副本路径，此处必须清理，否则主循环每轮泄漏一个零字节 .consumed.* 文件
            # （线上实测堆积 11 万+）。与下方 OSError 分支同样清理 tmp_path。
            outcome["kind"] = "absent"
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None
        except OSError:
            # 非缺失类 IO 异常（磁盘满/权限等）：信号未被 rename 走、仍留盘，
            # 归因为 io 而非 payload 非法（item 94618d6567ee）。
            outcome["kind"] = "io"
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None
        try:
            with tmp_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 信号已被 rename 消费（不会再重试），读不出合法内容按 payload
            # 非法归因。
            outcome["kind"] = "payload"
            return None
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
        if isinstance(payload, dict):
            return payload
        outcome["kind"] = "payload"
        return None

    @staticmethod
    def _reclaim_consumed_request_residues() -> None:
        """回收 _consume_request_file 崩溃窗口残留的 .consumed 私有副本
        （code-review item bd0b3d74ebca）。

        mkstemp 占位与 finally unlink 之间被 SIGKILL/断电时，.fenix/ 下会留下
        ``.<名>.json.consumed.<rand>`` 残留：副本不带 .json 结尾故不会被任何
        车道当合法信号再次消费，但也无写入方、每次崩溃惰性累积。与
        _reclaim_temp_scheduling_kick 同口径，按 mtime 超过
        SCHEDULING_KICK_STALE_THRESHOLD_SECONDS 清理；由启动清扫与主循环
        600s 周期时点挂载调用，不新建线程。
        """
        fenix_dir = PROJECT_ROOT / ".fenix"
        cutoff = time.time() - SCHEDULING_KICK_STALE_THRESHOLD_SECONDS
        try:
            candidates = list(fenix_dir.glob(".*.consumed.*"))
        except OSError:
            return
        for path in candidates:
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
            except OSError:
                continue

    @staticmethod
    def _signal_created_is_stale(created) -> bool:
        """信号车道 created 时效分档判据（code-review item 69d57b48a605 抽取）。

        与 scheduling_kick D4/D5 同判据（唯一判据 = created 时间戳，消费方
        时钟）：created 缺失 / 非字符串 / ISO 格式非法，或早于
        SCHEDULING_KICK_STALE_THRESHOLD_SECONDS → 陈旧（True），仅消费不执行。
        approve_push 车道经此复用同判据同阈值（同一常量，防漂移）。
        """
        if not isinstance(created, str) or not created:
            return True
        # SPEC-B 批②：解析收拢 parse_ts（唯一入口，失败返回 None）。存量
        # created 恒为 aware（admin_store._utcnow_iso）；naive 防御分支解读
        # 跟齐唯一策略（naive→本地）。
        dt = parse_ts(created)
        if dt is None:
            return True  # created 非法 → 按陈旧处理
        return (
            datetime.now(timezone.utc) - dt
        ).total_seconds() > SCHEDULING_KICK_STALE_THRESHOLD_SECONDS

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
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "admin_invoke 请求缺少 spec，忽略")
            return
        # 时效分档（code-review item 225b38618faf）：与 scheduling_kick /
        # approve_push 等兄弟车道同判据同阈值（经 _signal_created_is_stale）——
        # daemon 停机期间积压的旧唤起信号重启后仅消费不执行（人工呼叫
        # Administrator 属昂贵动作，不对旧请求重放）；created 缺失/非法保守
        # 按陈旧处理
        created = payload.get("created")
        if self._signal_created_is_stale(created):
            self.logger.warning(
                "fenixd",
                f"admin_invoke 陈旧信号（created={created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不唤起 "
                f"Administrator: spec='{spec}'（积压旧请求，如仍需处置请在 "
                f"dashboard 重新发起）",
            )
            return

        # 底层 signal_type 透传（fix-manual-invoke-signal-type-passthrough 1.1 +
        # fix-escalation-autoinvoke-passthrough）：手动唤起通道把信号压平为
        # manual-intervention，处置收尾自动复位判定门（admin_monitor 对
        # DISPOSITION_AUTO_RESET_SIGNAL_TYPES 的前置检查）因此对人工唤起通道
        # 永不命中。取值两源：① 请求文件 payload 直传（自动呼叫路径，其升级
        # 记录降噪即被标 handled、反查不可见）；② 反查兜底——基于
        # admin_store.read_all()（created 倒序）
        # 过滤该 spec 最近一条未处置（非 handled）SIGNAL/ESCALATION 记录，取其
        # signal_type 以独立字段透传；查不到为 None（字段可选，缺省 None）。
        # MUST 只透传复位门可消费的类型（code-review item db8c9b226fe4）：
        # 透传字段唯一消费方是自动复位判定门，机制自产、永不命中复位集合的
        # 记录（manual-intervention 自产 ESCALATION、admin_dispatch/programming
        # error 族——signal_rec=None 使 close_dispatch_failure_alerts 也不关它）
        # 一旦成为最新未处置记录会永久遮蔽其下真实 env 阻塞记录，人工处置成功
        # 后复位门仍不命中。跳过这类记录继续向前反查，取最近一条命中
        # DISPOSITION_AUTO_RESET_SIGNAL_TYPES 的记录。
        underlying_signal_type = None
        # 直传优先（fix-escalation-autoinvoke-passthrough）：env 阻塞等自动
        # 呼叫路径在请求文件 payload 里自带底层 signal_type——该路径的升级
        # 记录多为 warning 级降噪（_send_human_escalation_alert 落库即标
        # handled），下方基于未处置记录的反查对此不可见。直传值仍按复位
        # 集合白名单过滤（MUST 只透传复位门可消费的类型），不在集合内视为
        # 未提供，回退反查。
        payload_type = str(payload.get("underlying_signal_type") or "").strip()
        if payload_type in DISPOSITION_AUTO_RESET_SIGNAL_TYPES:
            underlying_signal_type = payload_type
        if underlying_signal_type is None:
            try:
                for rec in self.admin_store.read_all():
                    if rec.get("kind") not in (SIGNAL, ESCALATION):
                        continue
                    if rec.get("handled"):
                        continue
                    if rec.get("spec") != spec:
                        continue
                    if rec.get("signal_type") not in DISPOSITION_AUTO_RESET_SIGNAL_TYPES:
                        continue
                    underlying_signal_type = rec.get("signal_type")
                    break
            except Exception as e:  # noqa: BLE001 — 反查失败不阻塞唤起，退化为不透传
                self.logger.warning(
                    "fenixd",
                    f"admin_invoke 反查底层 signal_type 失败（spec={spec}）: {e}",
                )
                underlying_signal_type = None

        signal = {
            "signal_type": "manual-intervention",
            "spec": spec,
            "severity": "major",
            "source": payload.get("source", "manual"),
            "created": payload.get("created"),
            # 用户在 Dashboard 处置弹窗输入的提示词（prompt）优先；缺省用默认文案
            "description": (
                payload.get("prompt") or f"人工呼叫：检查 SPEC {spec} 出现什么问题并尝试处置"
            ),
            # 底层 signal_type 透传字段（fix-manual-invoke-signal-type-passthrough
            # D2）：独立字段而非替换顶层类型——顶层保持 manual-intervention 不变
            # （store 记录、节流锚点、活动区展示零回归）。消费点清单：仅
            # core/admin_monitor.py 的处置收尾自动复位判定门（signal_type 或
            # underlying_signal_type 任一命中 DISPOSITION_AUTO_RESET_SIGNAL_TYPES
            # 即触发）；其余消费方不读该字段。
            "underlying_signal_type": underlying_signal_type,
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
        created）；本方法在主循环（1s 粒度）中检测其存在：原子消费→校验
        run_id 非空→调 agent_runner.cancel_run(run_id, reason, by=source)。
        与 _check_admin_invoke_requests 同构：损坏 JSON 删除防卡死；删除失败
        下轮再试。

        消费走 _consume_request_file 原子模式（code-review item
        69fdd0ab526e）：先 rename 占位再读，消灭「先读后删」窗口内 dashboard
        重写新请求被 unlink 一并误删而从未被处理的丢请求形态（与 admin_invoke /
        approve_push / code_review / regression 四条已迁移车道同口径）。

        时效分档豁免说明（code-review item 04cdc784e187，有意豁免）：本车道
        不经 _signal_created_is_stale 做 created 时效分档——run_id 全局唯一且
        cancel_run 幂等无害，停机积压的旧取消信号重启后重放至多对早已结束的
        run_id 空转一次（未命中即返回），不存在兄弟车道那种「昂贵/破坏性动作
        被旧请求重放」的风险，故豁免并在此留痕。
        """
        req_path = PROJECT_ROOT / ".fenix" / "cancel_run_request.json"
        payload = self._consume_request_file(req_path)
        if payload is None:
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

    # 唤起失败退避（code-review item aeb6d238b51d）：同一信号连续唤起失败按
    # 次数指数退避（1s 起步、封顶 60s），达放弃阈值改为删信号并落一条
    # ESCALATION 告警收敛——handler 确定性异常时不再以主循环 1s 粒度每秒
    # 重试并各落一条 ERROR（丢弃的唤起交 full_scan 周期兜底）。
    _SCHED_KICK_FAIL_BACKOFF_CAP_SECONDS = 60
    _SCHED_KICK_FAIL_GIVEUP_COUNT = 10

    def _check_scheduling_kick_requests(self):
        """主循环每轮扫描「清空定时拾取即派发」的目录形态信号并消费。

        fix-scheduling-kick-single-slot：载体由单文件单槽位演进为每 SPEC 一文件
        （.fenix/scheduling_kick/<spec>.json）——不同 SPEC 写不同文件，无共享
        槽位即无跨 SPEC 冲突。本方法在主循环（1s 粒度）中扫描目录 *.json 条目
        逐条消费：「读取 → 按 spec 当前状态唤起（drafted 走 _on_spec_drafted，
        否则 _on_spec_ready）→ 唤起成功后删除 → _process_queue」（先唤起后删：
        唤起异常时信号保留留待下轮重试，删除失败亦留待下轮）。逐条消费相互
        隔离：单条异常捕获记日志后继续下一条，MUST NOT 中断同轮其余信号。

        目录不存在视为空；非 *.json 条目一律忽略且 MUST NOT 删除（避免误删
        并发写入中的临时文件——那些由 _reclaim_stale_scheduling_kicks 按 mtime
        阈值清理）。损坏/非法 JSON/缺 spec 字段的信号文件删除防卡死。

        旧单文件路径 .fenix/scheduling_kick_request.json 兼容消费（D5，只读
        兼容——新写入一律走目录，存量旧文件在下次被消费后消失），与目录扫描
        在同一轮内互不阻塞；旧文件同样适用 D4 回收阈值分档（created 早于阈值
        的旧文件仅删除、MUST NOT 唤起——防 daemon 长期停机残留的旧信号在恢复时
        引发一轮病态集中派发）。
        """
        kick_dir = PROJECT_ROOT / SCHEDULING_KICK_DIR
        if kick_dir.is_dir():
            for path in sorted(kick_dir.glob("*.json")):
                try:
                    if self._sched_kick_backoff_active(path):
                        # 连续失败退避期内：本轮跳过，推迟重试（item aeb6d238b51d）
                        continue
                    self._consume_scheduling_kick_file(path)
                except Exception as e:  # noqa: BLE001 逐条隔离：继续下一条
                    self.logger.error(
                        "fenixd",
                        f"scheduling_kick 条目消费异常（继续下一条）: {path.name}: {e}",
                    )
                    self._record_sched_kick_failure(path)
        # 旧单文件路径兼容消费（D5：与目录扫描同轮、互不阻塞）。
        # 常量定义在 core/dashboard/data/admin_actions.SCHEDULING_KICK_REQUEST，
        # 本文件按既有风格用字面路径（旧路径只读兼容、无共享常量义务）。
        legacy = PROJECT_ROOT / ".fenix" / "scheduling_kick_request.json"
        if legacy.exists() and not self._sched_kick_backoff_active(legacy):
            try:
                self._consume_scheduling_kick_file(legacy)
            except Exception as e:  # noqa: BLE001
                self.logger.error("fenixd", f"scheduling_kick 旧文件消费异常: {e}")
                self._record_sched_kick_failure(legacy)

    def _consume_scheduling_kick_file(self, path: Path) -> None:
        """消费/清理单个 scheduling kick 信号文件（目录条目与旧单文件共用）。

        分档语义（fix-scheduling-kick-single-slot D4/D5，唯一判据 = created
        时间戳，消费方时钟）：
        - 损坏 / 非法 JSON / 缺 spec 字段 → 删除防卡死（记日志）
        - created 缺失 / 非法 / 早于回收阈值 → 陈旧信号：仅删除不唤起
          （daemon 长期停机后的积压不应引发一轮集中派发）
        - created 在阈值内 → 按 spec 当前状态唤起（drafted → _on_spec_drafted，
          否则 _on_spec_ready）→ 唤起成功后删除 → _process_queue
          （先唤起后删：唤起异常时信号保留留待下轮重试，删除失败亦留待下轮；
          重复唤起由下游 handler 既有幂等谓词吸收）
        - spec 已不在 STATE.md → 删除信号并记日志

        注（code-review item 0e1eafada5d6）：本消费器**有意不走**
        _consume_request_file 原子消费——彼者「先消费后处理」，而本车道
        语义是「唤起成功才删，失败/未就绪信号保留留待下轮重试」（D4/D5）；
        payload 形状校验（isinstance dict）在任何删除动作之前完成，不存在
        「先 unlink 后 payload.get」丢请求形态。唤起成功后的删除防重写竞态
        （item 6888607ae472）：删除前重读 path，仅当仍是本次已消费的同一代
        payload（created 一致）才 os.replace 改名到私有副本再删——读取至删除
        窗口内 dashboard 原子重写的新 kick（created 变更）会被保留、下一轮
        照常消费。旧实现先读后占位 rename（item 690e48370279）在任意交错下均
        与直接 unlink 等价（读取与 rename 间隔唤起/排队的长时间处理，窗口内
        重写的新 kick 会被改名到 tmp 销毁），已弃。
        """
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # 损坏的信号文件：删除避免每轮报错卡死
            self.logger.warning("fenixd", f"scheduling_kick 信号损坏，删除: {path.name}")
            try:
                path.unlink()
            except OSError:
                pass
            return
        if not isinstance(payload, dict):
            self.logger.warning("fenixd", f"scheduling_kick 信号非对象，删除: {path.name}")
            try:
                path.unlink()
            except OSError:
                pass
            return
        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", f"scheduling_kick 信号缺少 spec，删除: {path.name}")
            try:
                path.unlink()
            except OSError:
                pass
            return
        # 陈旧分档（D4/D5）：created 缺失/非法按陈旧处理（仅删）；
        # 判据抽为 _signal_created_is_stale（item 69d57b48a605：approve_push 共用）
        created = payload.get("created")
        if self._signal_created_is_stale(created):
            self.logger.info(
                "fenixd",
                f"scheduling_kick 陈旧信号（created={created}），仅删除不唤起: {path.name}",
            )
            try:
                path.unlink()
            except OSError:
                pass
            return
        if self.pm_engine is None:
            self.logger.warning("fenixd", "pm_engine 未初始化，跳过 scheduling_kick 信号")
            return

        entry = self.pm_engine.state_machine.read_one(spec)
        if not entry:
            self.logger.info(
                "fenixd",
                f"消费 scheduling_kick 信号：spec '{spec}' 已不存在，删除信号",
            )
            try:
                path.unlink()
            except OSError:
                pass
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
            # 唤起异常：信号保留留待下轮重试（对齐「异常者留待下轮重试」语义；
            # item aeb6d238b51d：连续失败按次数退避，超阈值删信号收敛）
            self.logger.error(
                "fenixd",
                f"scheduling_kick 唤起 '{spec}' 失败（full_scan 兜底）: {e}",
            )
            self._record_sched_kick_failure(path, spec=spec)
            return
        # 唤起成功：清空该信号的连续失败退避记录（item aeb6d238b51d）
        fails = getattr(self, "_sched_kick_fail", None)
        if fails:
            fails.pop(str(path), None)
        # 唤起成功后删除；删除失败亦留待下轮。删除前重读 path 校验「仍是本次
        # 已消费的同一代 payload（created 一致）才删」（item 6888607ae472）：
        # 旧占位块（item 690e48370279）先 mkstemp 再 os.replace(path, tmp) 后
        # unlink(tmp)，意图复刻 _consume_request_file 的「新写入不丢」消费语义；
        # 但读取发生在函数开头，rename 在唤起 + _process_queue 全部完成后才发生
        # ——窗口内 dashboard 原子重写的新 kick 会被 rename 到 tmp 并销毁、从未
        # 被消费，任意交错下与直接 path.unlink() 等价，声称的不变量不成立。重读
        # 判定同代后，rename 与删除间仅隔微秒级连续操作；created 已变更（重写）
        # 或 path 消失时保留现场，新 kick 下一轮照常消费。corrupt/stale/missing-
        # spec 的 plain unlink 清理分支属防御路径（读侧先判坏再删、dashboard
        # 写侧 mkstemp+fsync+os.replace 原子替换，坏值与新值的覆盖窗口微秒级），
        # 不引入一致性检查。
        same_generation = False
        try:
            with path.open("r", encoding="utf-8") as f:
                current = json.load(f)
            same_generation = (
                isinstance(current, dict)
                and current.get("spec") == spec
                and current.get("created") == created
            )
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            # path 消失/读失败：无可删或无法判定，均不再触碰 path
            pass
        if not same_generation:
            self.logger.info(
                "fenixd",
                f"scheduling_kick 信号疑似已更新，保留供下一轮消费: {path.name}",
            )
            return
        # [fenix-ignore:f9299c2f3cc4] 删除前已重读 path 并校验 created 同代，读后重写的新 kick 保留待下轮消费（item 6888607ae472 落地）
        tmp_path = None
        try:
            # 私有副本后缀 MUST NOT 是 .json（code-review item e286692801c1）：
            # os.replace 与 unlink 之间崩溃/被 SIGKILL 时，.json 结尾的残留会被
            # _check_scheduling_kick_requests 的 *.json 扫描与
            # _reclaim_stale_scheduling_kicks 的 endswith(".json") 分支当合法
            # 信号再次唤起消费（payload 即已消费过的同一代、created 新鲜）——
            # 非 .json 命名落入 _reclaim_temp_scheduling_kick 按 mtime 阈值回收。
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{path.name}.consumed.",
                dir=str(path.parent),
            )
            os.close(fd)
            tmp_path = Path(tmp_str)
            os.replace(str(path), str(tmp_path))
        except OSError:
            self.logger.warning(
                "fenixd", f"scheduling_kick 信号删除失败，留待下轮: {path.name}"
            )
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    def _sched_kick_backoff_active(self, path: Path) -> bool:
        """该信号文件处于唤起失败退避期内（code-review item aeb6d238b51d）。"""
        state = getattr(self, "_sched_kick_fail", {}).get(str(path))
        return state is not None and time.monotonic() < state[0]

    def _record_sched_kick_failure(self, path: Path, spec=None) -> None:
        """记录 scheduling_kick 唤起连续失败并按次数退避（code-review item
        aeb6d238b51d）。

        信号在唤起异常时仍保留留待下轮重试（D4/D5 语义不变），但同一信号
        的连续失败按次数指数退避（1s 起步、封顶 60s）——handler 确定性异常
        时不再以主循环 1s 粒度每秒重试并各落一条 ERROR；连续失败达放弃阈值
        改为删信号 + 落一条 ESCALATION 告警收敛，唤起交 full_scan 周期兜底。
        唤起成功由消费方清空记录、计数归零。
        """
        now = time.monotonic()
        fails = getattr(self, "_sched_kick_fail", None)
        if fails is None:
            fails = self._sched_kick_fail = {}
        count = fails.get(str(path), (now, 0))[1] + 1
        if count < self._SCHED_KICK_FAIL_GIVEUP_COUNT:
            delay = min(2 ** (count - 1), self._SCHED_KICK_FAIL_BACKOFF_CAP_SECONDS)
            fails[str(path)] = (now + delay, count)
            return
        # 达放弃阈值：删信号防无限重试；告警一次即可——信号删除后不再有
        # 重试来源，不构成刷屏源
        fails.pop(str(path), None)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        self.logger.error(
            "fenixd",
            f"scheduling_kick 信号连续 {count} 次唤起失败，已删除信号改由 "
            f"full_scan 周期兜底: {path.name}",
        )
        try:
            admin_store = getattr(self, "admin_store", None)
            if admin_store is not None:
                admin_store.append(
                    {
                        "kind": ESCALATION,
                        "severity": "major",
                        "signal_type": "scheduling_kick",
                        "spec": spec,
                        "description": (
                            f"scheduling_kick 信号连续 {count} 次唤起失败"
                            f"（{path.name}），已删除信号并退避收敛，该 spec "
                            "的唤起交由 full_scan 周期兜底；若反复出现请核查 "
                            "handler 侧确定性异常"
                        ),
                    }
                )
        except Exception as e:  # noqa: BLE001 — 告警失败不阻断主循环
            self.logger.warning("fenixd", f"scheduling_kick 放弃告警写入失败: {e}")

    def _reclaim_stale_scheduling_kicks(self) -> None:
        """陈旧 scheduling kick 信号回收（启动清扫 + 周期计时段，600s 对齐孤儿清扫）。

        fix-scheduling-kick-single-slot D4：对信号目录对账，逐条按 created 分档：
        - *.json 条目：created 在回收阈值（1 小时，代码常量）内 → 消费（唤起）
          后删除（幂等，复用 _consume_scheduling_kick_file 的唤起路径）；created
          早于阈值 / 缺失 / 非法 → 仅删除不唤起；损坏 JSON / 缺 spec → 删除防卡死。
        - 非 *.json 残留（写入中断留下的临时文件，及消费端 os.replace 改名后
          unlink 前崩溃残留的 .<name>.consumed.* 私有副本——item e286692801c1，
          该副本不带 .json 后缀故不会被再次唤起消费）：按 mtime 同阈值清理
          （MUST NOT 在 _check_scheduling_kick_requests 的消费扫描中被当作损坏
          信号删除——那里只忽略不删，由本对账统一回收）。
        - 旧单文件路径 .fenix/scheduling_kick_request.json：同判据分档（D5）。

        异常捕获记日志不中断主循环。
        """
        kick_dir = PROJECT_ROOT / SCHEDULING_KICK_DIR
        if kick_dir.is_dir():
            for path in sorted(kick_dir.iterdir()):
                try:
                    if path.name.endswith(".json"):
                        self._consume_scheduling_kick_file(path)
                    else:
                        self._reclaim_temp_scheduling_kick(path)
                except Exception as e:  # noqa: BLE001 逐条隔离：继续下一条
                    self.logger.error(
                        "fenixd",
                        f"scheduling_kick 对账异常（继续）: {path.name}: {e}",
                    )
        legacy = PROJECT_ROOT / ".fenix" / "scheduling_kick_request.json"
        if legacy.exists():
            try:
                self._consume_scheduling_kick_file(legacy)
            except Exception as e:  # noqa: BLE001
                self.logger.error("fenixd", f"scheduling_kick 旧文件对账异常: {e}")

    def _reclaim_temp_scheduling_kick(self, path: Path) -> None:
        """非 .json 残留（写入中断留下的临时文件，及消费端崩溃残留的
        .consumed 私有副本，见 item e286692801c1）按 mtime 同阈值清理。"""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if time.time() - mtime > SCHEDULING_KICK_STALE_THRESHOLD_SECONDS:
            try:
                path.unlink()
            except OSError:
                pass

    # ── SPEC 审批推送信号消费（add-spec-approve-push-modal） ───────

    def _check_approve_push_requests(self):
        """主循环每轮扫描「SPEC 审批推送」的文件信号并消费。

        dashboard 的 /api/spec-approve-push 校验通过后原子写入
        .fenix/approve_push_request.json（含 spec/source/created）；本方法在
        主循环（1s 粒度）中检测其存在：读取→删除→调 pm_engine.approve_push(spec)。
        与 _check_cancel_requests / _check_scheduling_kick_requests 同构：
        损坏 JSON 删除防卡死；删除失败（先读后删被并发消费）下轮再试。

        推送语义完全复用 pm_engine.approve_push 既有实现（单飞锁、main 先行+
        分支尽力、SHA 去重、退避、归档收口、project log），本方法不新增任何
        推送语义。返回 False 时记 WARNING 不重试（design D3）：False 的三种
        来源各有既有兜底——非 done（幂等拒绝，重试无意义）、退避期内
        （_is_push_backoffed，重放由 recovery full_scan 覆盖）、推送失败
        （_handle_push_failure 已写回退避标记或升级 push_failed 信号）。

        消费走 _consume_request_file 原子模式（code-review item
        0e1eafada5d6）：先 rename 占位再读（payload 非法/损坏一律已消费返回
        None），消灭「先 unlink 后 payload.get」对合法 JSON 非对象值的
        AttributeError 丢请求形态与 read-unlink 窗口竞态。

        时效分档（code-review item 69d57b48a605）：created 与 scheduling_kick
        同判据同阈值（经 _signal_created_is_stale）——daemon 停机期间积压的旧
        审批信号重启后仅消费不执行（warning 留痕、明示积压旧审批）；created
        缺失/非法保守按陈旧处理。消费本身已由 _consume_request_file 占位完成，
        时效只决定「是否执行推送」。
        """
        req_path = PROJECT_ROOT / ".fenix" / "approve_push_request.json"
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "approve_push 请求缺少 spec，忽略")
            return
        # 时效分档（item 69d57b48a605）：与 scheduling_kick 同判据同阈值，
        # 停机积压的旧审批重启后不执行推送；created 缺失/非法保守按陈旧处理
        created = payload.get("created")
        if self._signal_created_is_stale(created):
            self.logger.warning(
                "fenixd",
                f"approve_push 陈旧信号（created={created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不执行推送: "
                f"spec='{spec}'（积压旧审批，如仍需推送请在 dashboard 重新发起）",
            )
            return
        if self.pm_engine is None:
            self.logger.warning("fenixd", "pm_engine 未初始化，丢弃 approve_push 请求")
            return

        self.logger.info(
            "fenixd",
            f"消费审批推送信号：spec='{spec}'，source={payload.get('source', 'dashboard')}",
        )
        try:
            ok = self.pm_engine.approve_push(spec)
        except Exception as e:
            self.logger.error(
                "fenixd",
                f"approve_push 调用失败 spec={spec}（recovery 兜底）: {e}",
            )
            return
        if ok:
            self.logger.info("fenixd", f"审批推送成功：spec='{spec}' 已推进 pushed")
        else:
            # design D3：不重试；退避重放由 recovery full_scan 覆盖，推送失败
            # 由 _handle_push_failure 退避/升级链路接管
            self.logger.warning(
                "fenixd",
                f"审批推送未成功 spec='{spec}'（非 done/退避期内/推送失败），"
                "不重试，退避与 recovery 兜底覆盖",
            )

    # ── SPEC 删除信号消费（add-freeze-stop-inflight-agents 5.2/5.3）────────

    def _check_spec_delete_requests(self):
        """主循环每轮扫描「SPEC 删除」的文件信号并消费（先停后删）。

        dashboard 的 /api/spec-delete 在检测到在跑 agent 时原子写入
        .fenix/spec_delete_request.json（含 spec/source/created/stopping）；
        本方法在主循环（1s 粒度）中检测其存在：原子消费→**投递后台**执行
        枚举该 spec 在跑 run→逐个 cancel_run 停止→有界等待终态→调
        soft_delete_spec 完成删除（code-review item dc0563435ba5：最长
        SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS=60s 的有界等待不得在主循环线程
        内联执行，整体投 _admin_executor——对齐 _submit_admin_run 的
        submitted 计数与 RuntimeError 回滚；admin.workers=0 回退同步保留
        逃生门）。与 _check_cancel_requests / _check_approve_push_requests
        同构：损坏 JSON 删除防卡死；删除失败（先读后删被并发消费）下轮再试。

        有界等待（task 5.3）：复用 running_run_ids 轮询 + drain_wait 形态，
        总超时上限 SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS；超时记 WARNING、
        放弃本轮删除且**不再重写信号**（避免无限循环），交由用户重试或
        人工处置。

        软删除以注入停止回调调 ``soft_delete_spec(stop_callback=...)`` 完成
        ——回调内已对全部在跑 run 发 cancel_run；等待融入 soft_delete_spec
        的既有有界窗口，删除内部完成「全部终止 → 移目录 → 剔 STATE」。

        消费走 _consume_request_file 原子模式（code-review item
        69fdd0ab526e）：先 rename 占位再读，消灭「先读后删」窗口内 dashboard
        重写新请求被 unlink 一并误删而从未被处理的丢请求形态（与 admin_invoke /
        approve_push / code_review / regression 四条已迁移车道同口径）。

        去重（item dc0563435ba5）：在飞判定在消费信号**之前**——删除在飞期间
        新请求留在盘上，worker 收尾（finally 复位 _spec_delete_in_flight）后
        下一轮再消费，既不重复投递也不丢请求。
        """
        if self._spec_delete_in_flight:
            # 删除在飞（最长 60s 有界等待）：静默让路不消费——主循环 1s 一轮，
            # 在飞期间每轮都会走到这里；请求文件留在盘上，worker 收尾后下一轮
            # 再消费（去重门，item dc0563435ba5）
            return
        req_path = PROJECT_ROOT / ".fenix" / "spec_delete_request.json"
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        spec = payload.get("spec")
        if not spec:
            self.logger.warning("fenixd", "spec_delete 请求缺少 spec，忽略")
            return
        # 时效分档（code-review item 225b38618faf）：与 scheduling_kick /
        # approve_push 等兄弟车道同判据同阈值（经 _signal_created_is_stale）——
        # daemon 停机期间积压的旧删除信号重启后仅消费不执行（先停后删属破坏性
        # 动作，不对旧请求重放）；created 缺失/非法保守按陈旧处理
        created = payload.get("created")
        if self._signal_created_is_stale(created):
            self.logger.warning(
                "fenixd",
                f"spec_delete 陈旧信号（created={created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不执行删除: "
                f"spec='{spec}'（积压旧请求，如仍需删除请在 dashboard 重新发起）",
            )
            return

        self.logger.info(
            "fenixd",
            f"消费 SPEC 删除信号：spec='{spec}'，stopping="
            f"{payload.get('stopping', 0)}，source={payload.get('source', 'dashboard')}",
        )
        from core.dashboard.data.admin_actions import (
            SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS,
            running_run_ids_for_spec,
        )

        # 停止回调：对该 spec 全部在跑 run 逐个 cancel_run（只设旗标，
        # 微秒级——终止由各 run 属主线程在轮询环内执行）
        def _stop_running(run_ids):
            for rid in run_ids:
                try:
                    self.agent_runner.cancel_run(
                        rid, reason="spec 删除（先停后删）", by="admin")
                except Exception as e:
                    self.logger.warning(
                        "fenixd",
                        f"spec_delete 停止 run {rid} 失败: {e}",
                    )

        if self._admin_executor is None:
            # admin.workers=0 同步回退（逃生门，对齐 _submit_admin_run）：保持
            # 既有主循环内执行语义；同步完成无重叠窗口，不置去重旗标、不计池
            # 统计（_is_idle 对 executor=None 本就视为空闲）。
            try:
                result = self._soft_delete_with_bounded_wait(
                    spec, _stop_running, SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS)
                if result is not None and result.get("ok") is False:
                    self.logger.warning(
                        "fenixd",
                        f"spec_delete 停止/删除未完成 spec='{spec}'："
                        f"{result.get('error') or result}（不重写信号，用户可重试）",
                    )
            except Exception as e:
                self.logger.error(
                    "fenixd",
                    f"spec_delete 消费异常 spec='{spec}'（不重写信号）: {e}",
                )
            return

        # 派发即置位、worker finally 复位（对齐 _evolution_in_flight）：主循环
        # 是唯一置位者，check-then-set 无并发写者。submit 前先递增 submitted
        # （对齐 _submit_admin_run / code-review item 5786fd76ad49：worker 可
        # 领跑收尾先递增 completed/failed，在飞推导转负），被拒回滚——删除的
        # 60s 有界等待 MUST 计入 _is_idle 的池在途维度，避免删除等待期间被
        # stale-code 自愈误判空闲。
        self._spec_delete_in_flight = True
        with self._admin_pool_lock:
            stats = dict(self._admin_pool_stats)
            stats["submitted"] += 1
            self._admin_pool_stats = stats
        try:
            self._admin_executor.submit(
                self._spec_delete_worker,
                spec, _stop_running, SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS)
        except RuntimeError as e:
            with self._admin_pool_lock:
                stats = dict(self._admin_pool_stats)
                stats["submitted"] -= 1
                self._admin_pool_stats = stats
            self._spec_delete_in_flight = False
            self.logger.error(
                "fenixd",
                f"spec_delete 投递被拒绝 spec='{spec}': {e}"
                "（不重写信号，用户可重试）",
            )
            return
        queued = stats["submitted"] - stats["completed"] - stats["failed"]
        self.logger.info(
            "fenixd",
            f"spec_delete 已投递后台（spec='{spec}'，"
            f"已提交 {stats['submitted']}，排队中 {queued}）",
        )

    def _soft_delete_with_bounded_wait(self, spec, stop_callback, total_timeout: float):
        """先停后删的有界等待实现（add-freeze-stop-inflight-agents 5.3）。

        以 running_run_ids_for_spec 轮询在跑 run（末行非终态，含
        frozen-terminated），总超时上限 total_timeout；全部终止后调
        dashboard_data.soft_delete_spec 完成删除。超时未终止 → 记 WARNING
        并返回失败（信号已消费不重写，避免无限循环）。

        Returns: soft_delete_spec 的删除结果 dict；等待超时返回
        {"ok": False, "error": ...}。
        """
        from core.dashboard.data import (
            running_run_ids_for_spec,
            soft_delete_spec,
        )
        import time as _time

        proot = PROJECT_ROOT
        deadline = _time.time() + max(1.0, float(total_timeout))
        try:
            # 停止回调先发（对当前在跑 run 逐个 cancel_run）
            stop_callback(running_run_ids_for_spec(proot, spec))
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"spec_delete 停止回调异常 spec='{spec}': {e}（有界等待仍继续）",
            )
        # 有界等待终态：轮询 running_run_ids_for_spec 直到该 spec 无在跑 run
        while _time.time() < deadline:
            if not running_run_ids_for_spec(proot, spec):
                break
            _time.sleep(min(1.0, max(0.1, deadline - _time.time())))
        if running_run_ids_for_spec(proot, spec):
            self.logger.warning(
                "fenixd",
                f"spec_delete 等待超时 spec='{spec}'：仍有 run 未落终态，"
                f"放弃本轮删除（不重写信号）",
            )
            return {"ok": False, "error": "等待超时仍有 run 未终止"}
        # 全部终止 → 软删除（stop_callback 已由 signal 消费方在停止阶段执行，
        # 此处不再传——避免二次 stop；直接调用保持既有删除语义）
        return soft_delete_spec(proot, spec)

    def _spec_delete_worker(self, spec, stop_callback, total_timeout: float):
        """spec_delete 后台 worker 体（code-review item dc0563435ba5）。

        在 _admin_executor 线程内执行「先停后删」全程：最长
        SPEC_DELETE_STOP_WAIT_TOTAL_SECONDS 的终态轮询不再占用主循环，
        admin_invoke / cancel_run / scheduling_kick / approve_push /
        code_review / regression 等信号车道与周期检查不受阻塞。对齐
        _admin_run_worker 的 catch-all 纪律——单次删除异常不得带病退出线程；
        去重旗标 MUST 在 finally 复位（漏复位会让后续 spec_delete 请求被
        去重门永久吞掉）；completed/failed 收口保证 submitted ≥
        completed + failed（_is_idle 池在途推导不失真）。
        """
        ok = False
        try:
            result = self._soft_delete_with_bounded_wait(
                spec, stop_callback, total_timeout)
            if result is not None and result.get("ok") is False:
                self.logger.warning(
                    "fenixd",
                    f"spec_delete 停止/删除未完成 spec='{spec}'："
                    f"{result.get('error') or result}（不重写信号，用户可重试）",
                )
            else:
                ok = True
        except Exception as e:  # noqa: BLE001 — worker 兜底，防线程带病退出
            self.logger.error(
                "fenixd",
                f"spec_delete 消费异常 spec='{spec}'（不重写信号）: {e}",
            )
        finally:
            self._spec_delete_in_flight = False
            with self._admin_pool_lock:
                self._admin_pool_stats["completed" if ok else "failed"] += 1
        if ok:
            self.logger.info("fenixd", f"spec_delete 删除完成（spec='{spec}'）")

    # ── 手动触发 code-review 文件信号消费（add-code-review-agent-and-quality-tab D1）──

    def _singleflight_lock(self, monitor_attr: str, fallback_attr: str) -> threading.Lock:
        """单飞置位/复位共用的锁单点（code-review item d51f639c500c）。

        优先取 ``admin_monitor`` 的锁；缺失（fallback 路径）时回落本实例的
        惰性 fallback 锁——经 ``_SINGLEFLIGHT_FALLBACK_GUARD`` 双检创建，
        进程内唯一。置位与复位 MUST 都经本方法取锁：旧实现置位端在 lock
        缺失时用 ``self._code_review_fallback_lock``，复位端却直取
        ``admin_monitor._code_review_lock``——fallback 路径下该属性缺失时
        finally 抛 AttributeError 遮蔽 worker 结果（或标志留在 True 永不复位）。
        """
        monitor = self.admin_monitor
        if monitor is not None:
            lock = getattr(monitor, monitor_attr, None)
            if lock is not None:
                return lock
        lock = getattr(self, fallback_attr, None)
        if lock is None:
            with _SINGLEFLIGHT_FALLBACK_GUARD:
                lock = getattr(self, fallback_attr, None)
                if lock is None:
                    lock = threading.Lock()
                    setattr(self, fallback_attr, lock)
        return lock

    # 手动触发判定结果的中文文案（add-code-review-trigger-ack 1.2/1.4，
    # 对齐 CODE_FIX_RESULT_MESSAGES 先例）：reason slug → 面向用户的 message
    CODE_REVIEW_RESULT_MESSAGES = {
        "started": "审查已受理，正在启动（文件收集/排队中），请稍候",
        "already_running": "已有审查在跑，请等当前审查完成后再试",
        "daemon_not_running": "daemon 未运行，审查信号无人消费已丢弃，请先启动 daemon",
        "daemon_unmanaged": "daemon 未受 supervisor 托管，审查信号无人消费已丢弃",
        "invalid_payload": "审查触发信号内容非法，本次触发已丢弃",
        "manifest_empty": "没有可审查的文件（manifest 为空），本次审查未执行",
        "manifest_error": "审查文件清单收集失败，本次审查未执行（详见 daemon 日志）",
        "submit_error": "审查任务投递失败，本次审查未执行（详见 daemon 日志）",
        # item 3213135bc86f：停机积压旧信号（requested_at 超时效阈值）仅消费不执行
        "stale_created": "审查触发信号已过期未执行（积压超过 1 小时，可能为停机残留），如仍需审查请重新发起",
    }

    def _write_code_review_request_result(self, requested_at, status, reason,
                                          message=None):
        """原子写回 code-review 手动触发判定结果（add-code-review-trigger-ack 1.2）。

        薄封装：写侧原子性集中在 core.code_review.write_request_result
        （同目录 tmp + os.replace），本方法只补 PROJECT_ROOT 与 logger 传参。
        无论判定结果如何都落盘（dropped/failed 不再静默丢信号）；写失败由
        写工具记日志，不影响本消费流程控制流。
        """
        from core.code_review import write_request_result

        if message is None:
            message = self.CODE_REVIEW_RESULT_MESSAGES.get(reason)
            if message is None and status == "started":
                # 受理回执以 reason=None 落盘（历史契约：started 不带 reason，
                # 结果文件消费方/测试断言 reason is None）——按 status 回退取
                # 文案，避免文案表 started 条目成死条目、message 恒落「未知」
                # 兜底误导排障（code-review item 9570a9f752c2）。
                message = self.CODE_REVIEW_RESULT_MESSAGES.get("started")
            if message is None:
                message = f"审查触发判定：{reason or '未知'}"
        write_request_result(
            PROJECT_ROOT, requested_at, status, reason, message,
            logger=self.logger,
        )

    def _check_code_review_requests(self):
        """主循环每轮扫描 code-review 手动触发文件信号并投递后台执行。

        dashboard 的 POST /api/code-review/run 会原子写入
        .fenix/code_review_request.json（含 scope: "full"|"window"、
        requested_at）；本方法在主循环（1s 粒度）中检测其存在：读取→删除→
        校验 hosting_state → 构造 run 参数 → 投递后台 worker 池。

        判定结果回链（add-code-review-trigger-ack 1.2-1.4）：所有丢弃/失败
        分支——payload 非法、hosting_state 守卫拒绝、单飞已在跑、manifest
        收集异常/为空、投递异常——MUST 全部原子写回
        .fenix/code_review_request_result.json（{requested_at, status,
        reason, message, finished_at}），不再只记日志静默丢信号；投递成功落
        started（requested_at 回链供前端只认本次触发）。

        消费方守卫（task 4.4/设计 D1）：daemon 未运行或 hosting_state ==
        unmanaged 时信号无人消费，会永久滞留并在 daemon 下次启动时被消费成
        一次用户并未请求的审查——POST 端点已前置拦截（400/409），此处
        二次校验防御性兜底（如信号文件被绕过写入）。

        单飞：已有 code-review run 在跑 → 忽略请求并记录。

        时效分档（code-review item 3213135bc86f）：requested_at 与 admin_invoke /
        code_fix / regression_fix 等兄弟车道同判据同阈值（经
        _signal_created_is_stale）——daemon 停机期间积压的旧审查请求重启后仅
        消费、落 stale_created 结果，不投递 full/window LLM 审查（昂贵动作
        不对旧请求重放）；requested_at 缺失/非法保守按陈旧处理。

        消费走 _consume_request_file 原子模式（code-review item
        0e1eafada5d6）：先 rename 占位再读（payload 非法/损坏一律已消费返回
        None），消灭「先 unlink 后 payload.get」丢请求形态与 read-unlink
        窗口竞态。
        """
        from core.fenix_session import hosting_state

        req_path = PROJECT_ROOT / ".fenix" / "code_review_request.json"
        # 「信号在场但 payload 非法」探测（add-code-review-trigger-ack 1.2）：
        # _consume_request_file 对「无信号」与「损坏/非 dict payload」都返回
        # None（前者是每轮稀疏常态）——文件在场却读不出合法 payload → 落
        # invalid_payload 结果，不再静默丢信号。item 94618d6567ee：消费期 IO
        # 异常（磁盘满/权限等）同样返回 None 且信号未被消费，经 outcome 归因
        # 出参区分——IO 异常不落 invalid_payload 结果（那会把「触发信号内容
        # 非法」误展示给用户、误导排障方向），仅记日志待下轮自愈重试。
        outcome = {}
        payload = self._consume_request_file(req_path, outcome=outcome)
        if payload is None:
            kind = outcome.get("kind")
            if kind == "payload":
                self.logger.warning(
                    "fenixd",
                    "code_review 触发信号 payload 非法/损坏，信号已消费并落 "
                    "invalid_payload 结果",
                )
                self._write_code_review_request_result(
                    None, "dropped", "invalid_payload")
            elif kind == "io":
                # 主循环约 1s 一轮巡检：IO 异常下信号留盘待下轮重试，磁盘满/
                # 权限等持久故障期间同一信号的 IO 告警会无限刷屏（item
                # 974d06dfad47）。按信号文件身份（ino+mtime_ns+size）去重：
                # 同一条未消费信号只告警首次；文件被重写/重建（新触发）或故障
                # 恢复后再次故障时身份变化，重新告警（对齐 supervisor drift
                # latest_signal 去重 / _heal_block_reason 状态沿触发先例）。
                # stat 亦失败（极端权限场景）时无法建身份，保留逐轮告警以不
                # 静默丢信号。
                ident = None
                try:
                    st = req_path.stat()
                    ident = (st.st_ino, st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
                if ident is not None and ident != getattr(
                    self, "_code_review_io_identity", None
                ):
                    if ident is not None:
                        self._code_review_io_identity = ident
                    # [fenix-ignore:15471b956c32] IO 告警已按信号身份(ino/mtime_ns/size)去重，同一未消费信号仅告警首次，持久故障不再逐轮刷屏（item 974d06dfad47 落地）
                    self.logger.warning(
                        "fenixd",
                        "code_review 触发信号消费遭遇 IO 异常（信号未消费、留盘待"
                        "下轮重试），不落 invalid_payload 结果",
                    )
                elif ident is None:
                    # code-review item 244e1731ebbf：stat 亦失败（极端权限场景）
                    # 时无法建身份做去重——按上方注释口径保留逐轮告警，不静默
                    # 丢信号（持久 IO+stat 双故障期间信号留盘重试但对用户完全
                    # 不可见，与注释宣称相矛盾）
                    self.logger.warning(
                        "fenixd",
                        "code_review 触发信号消费遭遇 IO 异常且信号文件 stat 亦"
                        "失败（信号未消费、留盘待下轮重试），无法建身份去重，"
                        "保留逐轮告警",
                    )
            return

        # requested_at 提前提取（回链用）：守卫拒绝/单飞拒绝/投递成功/失败的
        # 落盘都需回链信号 requested_at，前端据此只认本次触发的结果
        requested_at = payload.get("requested_at", "")

        scope = str(payload.get("scope") or "window")
        if scope not in ("full", "window"):
            scope = "window"

        # 时效分档（code-review item 3213135bc86f）：与 admin_invoke / code_fix /
        # regression_fix 等兄弟车道同判据同阈值（经 _signal_created_is_stale）——
        # daemon 停机期间积压的旧审查请求重启后仅消费、落 stale_created 结果，
        # 不投递 full/window LLM 审查（昂贵动作不对旧请求重放）；requested_at
        # 缺失/非法保守按陈旧处理
        if self._signal_created_is_stale(requested_at):
            self.logger.warning(
                "fenixd",
                f"code_review 陈旧信号（requested_at={requested_at}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不投递"
                f"（停机积压旧请求，如仍需审查请在 dashboard 重新发起）",
            )
            self._write_code_review_request_result(
                requested_at, "dropped", "stale_created")
            return

        # 守卫：daemon 未运行或 unmanaged 时信号无人消费。hosting_state 探测
        # 异常（读 /proc 或 pid 文件抖动，code-review item 832fa99b8eeb）不按
        # stopped 丢弃——本消费方即 daemon，守卫目标（防「信号写了没人消费」）
        # 已天然满足，异常时放行而非按未托管拒绝，亦不落 daemon_not_running
        # 的误导回执（对照 stale 自愈同型探测按未托管跳过重启的「宁紧勿松」，
        # 本处守卫方向相反）
        hs = None
        try:
            hs = hosting_state(PROJECT_ROOT)
        except Exception:
            pass
        if hs in ("stopped", "unmanaged"):
            self.logger.warning(
                "fenixd",
                f"code_review 信号被丢弃：daemon 状态为 {hs}（信号无人消费，"
                "与 approve_push 同判据），用户可能看到端点已返回拒绝但信号仍被"
                "写入的窗口态",
            )
            # 守卫拒绝落 dropped 结果（add-code-review-trigger-ack 1.2）：
            # reason 区分 daemon_not_running / daemon_unmanaged
            self._write_code_review_request_result(
                requested_at, "dropped",
                "daemon_not_running" if hs == "stopped" else "daemon_unmanaged")
            return

        # 单飞：已有 code-review run 在跑
        # （判定+置位在锁内原子完成，防 admin 巡检线程与主循环线程双线程
        # 同时通过单飞判定导致同一 run_id 被覆盖。置位/复位统一经
        # _singleflight_lock 取同一把锁——item d51f639c500c）
        lock = self._singleflight_lock("_code_review_lock", "_code_review_fallback_lock")

        def _in_flight_check_and_set() -> bool:
            """原子检查并置位单飞标志；返回 True 表示「已有在途」应跳过。

            code-review item cfdf9a6819a8：旧实现在 lock 缺失时直接裸跑
            ``_check_set_locked``（无任何同步），docstring 却声称「判定+置位在锁内
            原子完成」——保证静默降级而非显式失败。改为 lock 缺失时回落到本实例的
            私有锁（经 _singleflight_lock 单点惰性创建，进程内唯一），并记一条
            DEBUG 说明降级。
            """
            with lock:
                return _check_set_locked()

        def _check_set_locked() -> bool:
            if self.admin_monitor is not None and self.admin_monitor._code_review_in_flight:
                return True
            running = list(getattr(self.agent_runner, "_running_agents", None) or {})
            if any(str(rid).startswith("code-review-") for rid in running):
                if self.admin_monitor is not None:
                    self.admin_monitor._code_review_in_flight = True
                return True
            if self.admin_monitor is not None:
                self.admin_monitor._code_review_in_flight = True
            return False

        if _in_flight_check_and_set():
            self.logger.info("fenixd", "code_review 手动触发被忽略：已有审查在跑")
            # 单飞拒绝落 dropped 结果（add-code-review-trigger-ack 1.3）：
            # 不再只记 info 静默丢信号；旗标置位发生在 _in_flight_check_and_set
            # 锁内，落盘不改变既有置位/复位顺序
            self._write_code_review_request_result(
                requested_at, "dropped", "already_running")
            return

        self.logger.info(
            "fenixd",
            f"消费 code-review 手动触发信号：scope={scope}, requested_at={requested_at}",
        )

        def _worker():
            from core.code_review import compute_window, collect_manifest
            from core.config import ConfigLoader

            try:
                try:
                    if scope == "full":
                        manifest = collect_manifest(PROJECT_ROOT, "full", None)
                        review_kind = "manual_full"
                        window_start = None
                    else:
                        window_start, _ = compute_window(PROJECT_ROOT)
                        manifest = collect_manifest(PROJECT_ROOT, "window", window_start)
                        review_kind = "manual_window"
                except Exception as e:
                    # manifest 收集失败落 failed（add-code-review-trigger-ack
                    # 1.4，design D2）：不再只记 error 静默丢信号
                    self.logger.error("fenixd", f"code_review manifest 收集异常: {e}")
                    self._write_code_review_request_result(
                        requested_at, "failed", "manifest_error")
                    return
                # 上限截断
                cr_cfg = ConfigLoader.get_code_review_config(self.config)
                max_files = cr_cfg.get("max_files", 500)
                if max_files > 0 and len(manifest) > max_files:
                    manifest = manifest[:max_files]
                if not manifest:
                    self.logger.info("fenixd", f"code_review 手动触发：manifest 为空（scope={scope}），跳过")
                    self._write_code_review_request_result(
                        requested_at, "failed", "manifest_empty")
                    return
                result = self.agent_runner.run_code_review(
                    manifest, review_kind=review_kind,
                    window_start=window_start, scope=scope,
                )
                self.logger.info(
                    "fenixd",
                    f"code-review 手动审查完成：run_id={result.run_id}, "
                    f"inserted={result.inserted}, updated={result.updated}, "
                    f"resolved={result.resolved}, shards={result.shards}"
                    + (f", error={result.error}" if result.error else ""),
                )
                # ── 429 限流重派意图消费（evo-add-code-review-ratelimit-resume
                # 2.1/2.2）── 手动车道与周期车道（admin_monitor._worker）同源
                # 消费：复用同一 admin_monitor 实例的计数与 Timer 句柄
                # （_schedule_ratelimit_redispatch 内部读写
                # _code_review_ratelimit_redispatches / _code_review_redispatch_timer），
                # 手动+周期共享上限 1——防双车道叠加各耗一次重派额。300 秒冷却
                # 延迟重投递与单飞让位语义均在 admin_monitor 侧既有实现，此处
                # 只上交意图（与周期 worker 同一调用形态）。
                ratelimit_intent = getattr(result, "ratelimit_redispatch", None)
                if ratelimit_intent:
                    mon = self.admin_monitor
                    if mon is None:
                        # fallback 宿主（admin_monitor 未装配）：意图记日志放弃
                        # 并保持告警可见——run jsonl 已由 runner 侧标注
                        # type=ratelimit_redispatch（告警面板取证可见），不静默丢弃。
                        self.logger.warning(
                            "fenixd",
                            f"code-review 手动审查死于 429 限流（run {result.run_id}），"
                            "admin_monitor 未装配（fallback），重派意图放弃"
                            "——run jsonl 已标注 ratelimit_redispatch 可取证",
                        )
                    else:
                        try:
                            mon._schedule_ratelimit_redispatch(
                                manifest=manifest,
                                review_kind=review_kind,
                                window_start=window_start,
                                scope=scope,
                                intent=ratelimit_intent,
                            )
                        except Exception as se:  # noqa: BLE001 — 排程失败不吞 run 终态
                            self.logger.error(
                                "fenixd",
                                f"code-review 手动通道 429 重派排程失败: {se}",
                            )
            except Exception as e:
                # 兜底（manifest 失败已在上方分支落盘；run_code_review 执行
                # 异常不回写结果——design D1：结果文件不承载 run 终态）
                self.logger.error("fenixd", f"code_review 手动审查异常: {e}")

        def _worker_with_flag():
            try:
                _worker()
            finally:
                # 复位与置位同锁（item d51f639c500c）：经 _singleflight_lock
                # 取锁，fallback 路径不再直取 admin_monitor._code_review_lock
                #（缺失时 AttributeError 会遮蔽 worker 结果且漏复位）。
                if self.admin_monitor is not None:
                    with self._singleflight_lock(
                        "_code_review_lock", "_code_review_fallback_lock"
                    ):
                        self.admin_monitor._code_review_in_flight = False

        try:
            if self._admin_executor is not None:
                # 投递成功即受理（add-code-review-trigger-ack 1.4）：落 started，
                # 前端凭 requested_at 回链从「等结果」进入「等启动」段。
                # 受理回执 MUST 先于 submit 落盘（验证打回 BUG-01）：线程池
                # worker 可领跑收尾——快速失败分支（manifest 为空/收集异常）
                # 若先落盘 failed、随后主线程才回写 started，failed 三态会被
                # 受理回执覆盖，前端把失败误显示为「正在启动」。对齐无池兜底
                # 路径「先受理后执行」的既有顺序；submit 抛异常由 except 分支
                # 补落 failed/submit_error（后写覆盖，终态仍正确）。
                self._write_code_review_request_result(requested_at, "started", None)
                self._admin_executor.submit(_worker_with_flag)
            else:
                # 无池兜底（同步执行）：受理先于执行落盘；run 终态不回写结果
                # 文件（design D1），执行完毕后结果仍停留 started
                self._write_code_review_request_result(requested_at, "started", None)
                _worker_with_flag()
        except Exception as e:
            if self.admin_monitor is not None:
                with self._singleflight_lock(
                    "_code_review_lock", "_code_review_fallback_lock"
                ):
                    self.admin_monitor._code_review_in_flight = False
            self.logger.error("fenixd", f"code_review 手动审查投递失败: {e}")
            # 投递失败落 failed（add-code-review-trigger-ack 1.4）：不再只记
            # error 静默丢信号；上方单飞复位逻辑保持不变（落盘不改控制流）
            self._write_code_review_request_result(
                requested_at, "failed", "submit_error")

    def _check_regression_requests(self):
        """主循环每轮扫描 regression 手动触发文件信号并投递后台执行。

        dashboard 的 POST /api/regression/run 会原子写入
        .fenix/regression_request.json（含 requested_at）；本方法在
        主循环（1s 粒度）中检测其存在：读取→删除→校验 hosting_state →
        校验 verify.yaml regression 段 → 单飞 → 投递后台 worker 池。

        消费方守卫（对齐 _check_code_review_requests）：daemon 未运行或
        hosting_state == unmanaged 时信号无人消费；已有回归在跑时单飞
        忽略请求（不排队、不并发），且单飞在飞判定前置到消费之前作只读
        去重门——在飞期间新请求留盘待下轮消费，不静默丢请求（code-review
        item 11654f7b26bf）。信号文件在框架根 PROJECT_ROOT
        （单项目自托管形态，MUST NOT 按多项目 registry 逐项目扫描）。

        消费走 _consume_request_file 原子模式（code-review item
        0e1eafada5d6）：先 rename 占位再读（payload 非法/损坏一律已消费返回
        None），消灭「先 unlink 后 payload.get」丢请求形态与 read-unlink
        窗口竞态。

        时效分档（code-review item 117044e0ae4a）：requested_at 与
        approve_push / code_fix 同判据同阈值（经 _signal_created_is_stale）
        ——daemon 停机期间积压的旧手动回归信号重启后仅消费不执行（warning
        留痕、明示积压旧请求）；本车道时间戳字段为 requested_at（writer 契约），
        缺失/非法保守按陈旧处理。
        """
        from core.fenix_session import hosting_state

        req_path = PROJECT_ROOT / ".fenix" / "regression_request.json"
        # 去重门（code-review item 11654f7b26bf，对齐 spec_delete 的 item
        # dc0563435ba5 先例）：单飞在飞判定放在消费**之前**且只读不置位——
        # 回归在飞期间新请求留在盘上，worker 收尾（finally 复位
        # _regression_in_flight）后下一轮再消费，不再「请求已被消费却因单飞
        # 被拒、又无结果回执文件」地静默丢请求（本车道无 code_review 那样的
        # 结果回执链路）。置位仍只发生在消费后的 _in_flight_check_and_set
        # 锁内——此处若置位，信号缺席的常态轮次会误置位把车道锁死。在飞期间
        # 主循环每轮静默让路不记日志（对齐 spec_delete，防刷屏）
        if self.admin_monitor is not None and self.admin_monitor._regression_in_flight:
            return
        if any(
            str(rid).startswith("regression-")
            for rid in list(getattr(self.agent_runner, "_running_agents", None) or {})
        ):
            return
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        # 时效分档（item 117044e0ae4a）：与 approve_push / code_fix 同判据
        # 同阈值，停机积压的旧手动回归重启后不派发全量回归；时间戳字段为
        # requested_at（writer 契约），缺失/非法保守按陈旧处理
        created = payload.get("requested_at")
        if self._signal_created_is_stale(created):
            self.logger.warning(
                "fenixd",
                f"regression 陈旧信号（requested_at={created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不执行回归"
                f"（停机积压旧请求，如仍需执行请在 dashboard 重新发起）",
            )
            return

        # 守卫：daemon 未运行或 unmanaged 时信号无人消费。hosting_state 探测
        # 异常不按 stopped 丢弃（同 code_review 车道，code-review item
        # 832fa99b8eeb）：本消费方即 daemon，守卫目标已天然满足，异常时放行
        hs = None
        try:
            hs = hosting_state(PROJECT_ROOT)
        except Exception:
            pass
        if hs in ("stopped", "unmanaged"):
            self.logger.warning(
                "fenixd",
                f"regression 信号被丢弃：daemon 状态为 {hs}（信号无人消费，"
                "与 code_review 同判据），用户可能看到端点已返回拒绝但信号仍被"
                "写入的窗口态",
            )
            return

        # 校验项目 verify.yaml 的 regression 段存在且有效（无效/缺失 →
        # 丢弃信号并记 WARNING，MUST NOT 派发空跑）
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(PROJECT_ROOT, logger=self.logger)
        if contract is None or contract.regression is None:
            self.logger.warning(
                "fenixd",
                "regression 信号被丢弃：项目未配置全量回归"
                "（verify.yaml regression 段缺失或无效）",
            )
            return
        spec = contract.regression

        # 单飞：已有回归在跑 → 忽略请求（不排队、不并发）。置位/复位统一经
        # _singleflight_lock 取同一把锁（item d51f639c500c，同 code-review 路径）
        lock = self._singleflight_lock("_regression_lock", "_regression_fallback_lock")

        def _in_flight_check_and_set() -> bool:
            """原子检查并置位回归单飞标志；返回 True 表示「已有在途」应跳过。"""
            with lock:
                return _check_set_locked()

        def _check_set_locked() -> bool:
            if self.admin_monitor is not None and self.admin_monitor._regression_in_flight:
                return True
            running = list(getattr(self.agent_runner, "_running_agents", None) or {})
            if any(str(rid).startswith("regression-") for rid in running):
                if self.admin_monitor is not None:
                    self.admin_monitor._regression_in_flight = True
                return True
            if self.admin_monitor is not None:
                self.admin_monitor._regression_in_flight = True
            return False

        if _in_flight_check_and_set():
            self.logger.info("fenixd", "regression 手动触发被忽略：已有回归在跑")
            return

        requested_at = payload.get("requested_at", "")
        self.logger.info(
            "fenixd",
            f"消费 regression 手动触发信号：requested_at={requested_at}",
        )

        # scope=issues 分支（add-regression-issues-rerun 2.2，D2）：定向子集
        # 回归——消费时点从最近快照计算 failures+long_tests 的 nodeid 并集
        # （映射依赖 exec_root 在盘测试文件探测，且快照可能在信号滞留窗口内
        # 被覆盖，消费时点计算才新鲜）。fail-closed：映射失败 / 结果空 →
        # WARNING 留痕并按全量派发（请求不丢，宁可慢跑不静默漏跑）；
        # 无 scope / 未知 scope 按既有全量路径（行为逐字节不变）。
        subset_nodeids = None
        if payload.get("scope") == "issues":
            from core.code_fix import map_snapshot_issues_to_nodeids
            from core.regression import read_result

            try:
                snapshot = read_result(PROJECT_ROOT)
                nodeids, mapped = map_snapshot_issues_to_nodeids(
                    snapshot, PROJECT_ROOT
                )
            except Exception as e:  # noqa: BLE001 — 读快照/映射异常兜底回全量
                nodeids, mapped = [], False
                self.logger.warning(
                    "fenixd",
                    f"定向子集计算异常（{e}），回退全量回归",
                )
            if mapped and nodeids:
                subset_nodeids = nodeids
                self.logger.info(
                    "fenixd",
                    f"定向子集回归：{len(nodeids)} 例"
                    "（快照 failures+long_tests 并集去重）",
                )
            elif mapped:
                self.logger.warning(
                    "fenixd",
                    "定向子集为空（快照无异常用例），回退全量回归",
                )
            else:
                self.logger.warning(
                    "fenixd",
                    "定向子集不可用（快照条目缺 classname 或无法映射为 "
                    "nodeid，如存量旧快照/非 pytest 形态），回退全量回归",
                )

        def _worker():
            try:
                if subset_nodeids:
                    result = self.agent_runner.run_regression(
                        spec, reason="manual", subset_nodeids=subset_nodeids
                    )
                else:
                    result = self.agent_runner.run_regression(
                        spec, reason="manual"
                    )
                self.logger.info(
                    "fenixd",
                    f"回归完成：run_id={result.run_id}, status={result.status}"
                    + (f", error={result.error}" if result.error else ""),
                )
            except Exception as e:
                self.logger.error("fenixd", f"回归手动执行异常: {e}")

        def _worker_with_flag():
            try:
                _worker()
            finally:
                # 复位与置位同锁（item d51f639c500c）：经 _singleflight_lock
                # 取锁，fallback 路径不再直取 admin_monitor._regression_lock。
                if self.admin_monitor is not None:
                    with self._singleflight_lock(
                        "_regression_lock", "_regression_fallback_lock"
                    ):
                        self.admin_monitor._regression_in_flight = False

        try:
            if self._admin_executor is not None:
                self._admin_executor.submit(_worker_with_flag)
            else:
                _worker_with_flag()
        except Exception as e:
            if self.admin_monitor is not None:
                with self._singleflight_lock(
                    "_regression_lock", "_regression_fallback_lock"
                ):
                    self.admin_monitor._regression_in_flight = False
            self.logger.error("fenixd", f"回归手动执行投递失败: {e}")

    # ── 手动「立即自动修复」信号消费（add-code-fix-manual-trigger 3.1）──

    # 判定 reason → 用户可见中文文案（一处收口）：前端只渲染 message、不再
    # 各自翻译 reason；未登记 reason 走兜底模板。
    CODE_FIX_RESULT_MESSAGES = {
        "dispatched": "已投递一批自动修复，可在进度卡片查看进展",
        "already_running": "已有自动修复批次在跑，请等当前批完成后再试",
        "no_open_items": "当前没有待修复的 open 问题",
        "regression_contract_missing": "回归契约缺失（verify.yaml 尚未起草），按 fail-closed 拒绝投递",
        "regression_section_missing": "verify.yaml 缺 regression 段，按 fail-closed 拒绝投递",
        "orchestrator_missing": "自动修复编排器未装配，无法投递（daemon 初始化异常或版本过旧）",
        "dispatch_prepare_error": "自动修复投递前置异常，本批未投递（详见 daemon 日志）",
        "dispatch_error": "自动修复投递失败，本批未投递（详见 daemon 日志）",
        "dispatch_exception": "自动修复消费异常，本批未投递（详见 daemon 日志）",
        "disabled": "自动修复开关处于关闭状态",
        # item 6cc24b51f6b9：停机积压旧信号（created 超时效阈值）仅消费不执行
        "stale_created": "触发信号已过期未执行（积压超过 1 小时，可能为停机残留），如仍需修复请重新发起",
    }

    def _write_code_fix_request_result(self, result_path, request_created, triggered,
                                       reason, message=None):
        """原子写回手动触发判定结果文件（同目录 mkstemp + fsync + os.replace，
        防半写被前端读到）。

        无论 triggered 与否都落盘（task 3.1）；写失败仅记日志——结果文件写不进
        属基础设施异常，无更好的用户反馈通道。
        """
        if message is None:
            message = self.CODE_FIX_RESULT_MESSAGES.get(
                reason, f"自动修复触发判定：{reason or '未知'}")
        payload = {
            "request_created": request_created,
            "triggered": bool(triggered),
            "reason": reason,
            "message": message,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        # mkstemp 原子写（code-review item 660dcac62fd3，对齐 _write_preserve_sidecar
        # / _write_restart_history 惯例）：固定名 .tmp 中转在写入中途 SIGKILL 时
        # 会在 .fenix 残留零字节 tmp（直至下次成功写才被清理），改用同目录
        # mkstemp 随机名消除固定名残留窗口（亦免未来第二写者同名互踩）。
        tmp_path = None
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_str = tempfile.mkstemp(
                prefix=f".{result_path.name}.", suffix=".tmp",
                dir=str(result_path.parent),
            )
            tmp_path = Path(tmp_str)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_str, str(result_path))
        except OSError as e:
            self.logger.error("fenixd", f"code_fix 手动触发结果写入失败: {e}")
            # 失败路径清掉残留 tmp，防 .fenix 堆积零字节临时文件（replace 成功
            # 后 tmp 已不存在，无需清理；对齐 core/code_review
            # .write_request_result 同型写路径的清理口径，item e61c4efcdbc4）。
            if tmp_path is not None:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass

    def _check_code_fix_requests(self):
        """主循环每轮扫描手动「立即自动修复」文件信号并消费（task 3.1）。

        dashboard 的 POST /api/code-review/fix-run 原子写入
        ``.fenix/code_fix_request.json``（含 source、created）；本方法在主循环
        （1s 粒度）中检测其存在：原子消费 → 经
        ``getattr(agent_runner, "_code_fix_orchestrator", None)`` 取编排器 →
        以 ``override_enabled=True``（手动即临时授权：绕过 enabled 总开关，
        单飞/无 open 条目/失败保留/回归契约 fail-closed 守卫原样）调
        ``checkpoint()`` → 无论 triggered 与否原子写结果文件
        ``.fenix/code_fix_request_result.json``（``{request_created, triggered,
        reason, message, finished_at}``，``request_created`` 回链信号 created）。

        对齐 _check_code_review_requests：编排器未装配不静默（落
        orchestrator_missing 结果）；checkpoint 抛异常落 dispatch_exception
        结果而非静默丢信号。

        消费走 _consume_request_file 原子模式（code-review item
        69fdd0ab526e）：先 rename 占位再读，消灭「先读后删」窗口内 dashboard
        重写新请求被 unlink 一并误删而从未被处理的丢请求形态（与 admin_invoke /
        approve_push / code_review / regression 四条已迁移车道同口径）。

        时效分档（code-review item 6cc24b51f6b9）：created 与 scheduling_kick /
        approve_push 同判据同阈值（经 _signal_created_is_stale）——daemon 停机
        期间积压的旧手动修复信号重启后仅消费、落 stale_created 结果，不投递
        checkpoint（手动授权语义锚定点击时刻）；created 缺失/非法保守按陈旧处理。
        """
        req_path = PROJECT_ROOT / ".fenix" / "code_fix_request.json"
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        request_created = str(payload.get("created") or "")
        result_path = PROJECT_ROOT / ".fenix" / "code_fix_request_result.json"
        self.logger.info("fenixd", f"消费 code-fix 手动触发信号：created={request_created}")

        # 时效分档（item 6cc24b51f6b9）：与 scheduling_kick / approve_push
        # 同判据同阈值，停机积压的旧触发重启后不投递 checkpoint，仅落
        # stale_created 结果（下游可辨认）；单飞等守卫不受影响
        if self._signal_created_is_stale(payload.get("created")):
            self.logger.warning(
                "fenixd",
                f"code-fix 陈旧信号（created={request_created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不投递"
                f"（停机积压旧请求，如仍需修复请在 dashboard 重新发起）",
            )
            self._write_code_fix_request_result(
                result_path, request_created, False, "stale_created")
            return

        # 编排器未装配不静默：落 orchestrator_missing 结果，用户可见明确原因
        orchestrator = getattr(self.agent_runner, "_code_fix_orchestrator", None)
        if orchestrator is None:
            self.logger.warning(
                "fenixd", "code-fix 编排器未装配，手动触发信号落 orchestrator_missing 结果")
            self._write_code_fix_request_result(
                result_path, request_created, False, "orchestrator_missing")
            return

        try:
            res = orchestrator.checkpoint(override_enabled=True)
        except Exception as e:  # noqa: BLE001 — 消费端兜底：异常也 MUST 落结果不静默
            self.logger.error("fenixd", f"code-fix 手动触发消费异常: {e}")
            self._write_code_fix_request_result(
                result_path, request_created, False, "dispatch_exception")
            return

        triggered = bool(res.get("triggered"))
        reason = str(res.get("reason") or "")
        if triggered:
            self.logger.info(
                "fenixd", f"code-fix 手动触发已投递一批（request_created={request_created}）")
        else:
            self.logger.info("fenixd", f"code-fix 手动触发被拒：reason={reason}")
        self._write_code_fix_request_result(result_path, request_created, triggered, reason)

    # ── 手动「自动修复回归问题」信号消费（add-regression-auto-fix 3.1）──

    # 判定 reason → 用户可见中文文案：在 code-fix 手动触发的文案表基础上
    # 收敛 regression 车道特有 reason（dispatched 文案指向台账转入语义；
    # snapshot_missing 为本车道新增兜底）。
    REGRESSION_FIX_RESULT_MESSAGES = {
        **CODE_FIX_RESULT_MESSAGES,
        "dispatched": "已把回归问题转入修复台账并投递一批自动修复，可在质量页签进度卡片查看进展",
        "snapshot_missing": "最近一次回归快照缺失或不可解析，无法定位回归问题（请先执行一次全量回归，或稍后重试）",
    }

    @staticmethod
    def _read_regression_output_excerpt(proot, snapshot, limit: int = 500) -> str:
        """预读快照 ``output`` 字段指向的产物文件尾部（3.1，供超时条目摘要）。

        快照 ``output`` 为相对项目根的产物路径（junit XML；超时中止时是
        部分产物）。读取失败/缺失/非文本一律安全兜底置空——摘要拿不到
        MUST NOT 阻塞转换与投递。
        """
        try:
            rel = str(snapshot.get("output") or "").strip()
            if not rel:
                return ""
            path = Path(proot) / rel
            if not path.is_file():
                return ""
            # 摘要只需末尾 limit 字符，产物（junit XML）可达数十 MB：二进制
            # seek 从尾部回退读取（limit*4 字节，覆盖 UTF-8 最坏 4 字节/字的
            # 余量），避免整文件驻留内存。
            with path.open("rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - limit * 4))
                text = f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        return text[-limit:] if len(text) > limit else text

    def _check_regression_fix_requests(self):
        """主循环每轮扫描手动「自动修复回归问题」文件信号并消费（3.1）。

        dashboard 的 POST /api/regression/fix 原子写入
        ``.fenix/regression_fix_request.json``（含 source=regression_fix、
        created）；本方法在主循环（1s 粒度）中检测其存在，与
        ``_check_code_fix_requests`` 同构：

        原子消费 → 读 PROJECT_ROOT 下 ``.fenix/regression/last-run.json``
        （与编排器及既有 ``_check_regression_requests`` 同根；信号 query
        project 仅作受理校验，不参与消费定位；缺失/损坏 → 落
        snapshot_missing 结果不继续，design D5：消费端读快照以当下为准）
        → 预读快照 output 字段指向的日志文件尾部 500 字（读取失败置空）
        → ``convert_regression_snapshot_to_findings`` + ``upsert_findings``
        （review_id=``regression-fix-<created>``，review_kind=``regression_fix``，
        已核实 upsert_findings 对 review_kind 仅透传存储、无枚举校验）
        + ``reopen_regression_items``（复发条目重开）→ 编排器
        ``checkpoint(override_enabled=True)``（单飞/无 open 条目/失败保留/
        回归契约 fail-closed 守卫原样）→ 无论结果原子写
        ``.fenix/regression_fix_request_result.json``（``request_created``
        回链信号 created）。

        兜底不静默：编排器未装配落 orchestrator_missing（此时尚未入账）；
        消费异常落 dispatch_exception（此时转换可能已入账——design D6：
        checkpoint 拒绝/异常不回滚台账，在飞链下一批 select_batch 自然
        吸收，回链如实返回 reason）。

        时效分档（code-review item 6cc24b51f6b9）：created 与 code_fix /
        approve_push 车道同判据同阈值（经 _signal_created_is_stale）——停机
        积压旧信号重启后仅消费、落 stale_created 结果，不转换入账、不投递
        checkpoint（手动授权语义锚定点击时刻）；created 缺失/非法保守按陈旧处理。
        """
        from core.code_fix import (
            convert_regression_snapshot_to_findings,
            regression_findings_fingerprints,
            reopen_regression_items,
        )
        from core.code_review import upsert_findings
        from core.regression import read_result

        req_path = PROJECT_ROOT / ".fenix" / "regression_fix_request.json"
        payload = self._consume_request_file(req_path)
        if payload is None:
            return

        request_created = str(payload.get("created") or "")
        result_path = PROJECT_ROOT / ".fenix" / "regression_fix_request_result.json"
        self.logger.info(
            "fenixd", f"消费 regression-fix 手动触发信号：created={request_created}")

        # 时效分档（item 6cc24b51f6b9）：与 code_fix / approve_push 同判据
        # 同阈值，停机积压的旧触发重启后不转换入账、不投递 checkpoint，仅落
        # stale_created 结果（下游可辨认）；须在快照转换入账之前分档
        if self._signal_created_is_stale(payload.get("created")):
            self.logger.warning(
                "fenixd",
                f"regression-fix 陈旧信号（created={request_created}）超过 "
                f"{SCHEDULING_KICK_STALE_THRESHOLD_SECONDS}s 阈值，不转换入账"
                f"不投递（停机积压旧请求，如仍需修复请在 dashboard 重新发起）",
            )
            self._write_result_message(
                result_path, request_created, False, "stale_created",
                self.REGRESSION_FIX_RESULT_MESSAGES)
            return

        # 编排器未装配不静默（且 MUST NOT 先入账再落结果——入账前置检查）
        orchestrator = getattr(self.agent_runner, "_code_fix_orchestrator", None)
        if orchestrator is None:
            self.logger.warning(
                "fenixd", "code-fix 编排器未装配，regression-fix 信号落 orchestrator_missing 结果")
            self._write_result_message(
                result_path, request_created, False, "orchestrator_missing",
                self.REGRESSION_FIX_RESULT_MESSAGES)
            return

        try:
            snapshot = read_result(PROJECT_ROOT)
            status = str(snapshot.get("status") or "") if isinstance(snapshot, dict) else ""
            if status in ("", "never_run", "parse_error"):
                self.logger.warning(
                    "fenixd", f"regression-fix 快照缺失/损坏（status={status or 'unknown'}），"
                    "落 snapshot_missing 结果")
                self._write_result_message(
                    result_path, request_created, False, "snapshot_missing",
                    self.REGRESSION_FIX_RESULT_MESSAGES)
                return
            output_excerpt = self._read_regression_output_excerpt(PROJECT_ROOT, snapshot)
            findings = convert_regression_snapshot_to_findings(
                snapshot, output_excerpt=output_excerpt)
            if findings:
                upsert_findings(
                    PROJECT_ROOT, findings,
                    review_id=f"regression-fix-{request_created}",
                    review_kind="regression_fix",
                )
                reopen_regression_items(
                    PROJECT_ROOT, regression_findings_fingerprints(findings))
            res = orchestrator.checkpoint(override_enabled=True)
        except Exception as e:  # noqa: BLE001 — 消费端兜底：异常也 MUST 落结果不静默
            self.logger.error("fenixd", f"regression-fix 手动触发消费异常: {e}")
            self._write_result_message(
                result_path, request_created, False, "dispatch_exception",
                self.REGRESSION_FIX_RESULT_MESSAGES)
            return

        triggered = bool(res.get("triggered"))
        reason = str(res.get("reason") or "")
        if triggered:
            self.logger.info(
                "fenixd",
                f"regression-fix 手动触发已转换入账并投递一批（request_created={request_created}）")
        else:
            # checkpoint 拒绝（如 already_running）如实回传 reason 且不回滚台账：
            # 转换后的条目由在飞链下一批 select_batch 自然吸收（design D6）
            self.logger.info("fenixd", f"regression-fix 手动触发被拒：reason={reason}")
        self._write_result_message(
            result_path, request_created, triggered, reason,
            self.REGRESSION_FIX_RESULT_MESSAGES)

    def _write_result_message(self, result_path, request_created, triggered,
                              reason, messages):
        """按车道文案表落触发判定结果文件（复用 _write_code_fix_request_result）。"""
        message = messages.get(reason, f"回归修复触发判定：{reason or '未知'}")
        self._write_code_fix_request_result(
            result_path, request_created, triggered, reason, message=message)

    # ── 框架自进化检查点（add-framework-self-evolution 5.x） ────────

    @staticmethod
    def _evolution_framework_root() -> Path:
        """FRAMEWORK_ROOT，与 prompt_builder 同式推导（design D1）。"""
        from core.agent_runner.prompt_builder import FRAMEWORK_ROOT

        return FRAMEWORK_ROOT

    def _check_evolution_checkpoint(self) -> None:
        """自进化检查点（5.1-5.4）：周期保留清理 → 就绪扫描 → 单飞判定 → 派发。

        节拍由主循环计时器驱动（复用 admin.interval_minutes，缺省 5 分钟）。
        流程：
        0. 周期保留清理（evo-item-retention-doc-tracking D4）：通过宿主守卫
           后、单飞判定前执行 prune_items——清理不因分析 run 在途而跳过，
           独立 try/except（异常仅记日志，不影响后续派发与主循环）；
        1. 宿主守卫（5.2）：PROJECT_ROOT.resolve() != FRAMEWORK_ROOT → 整套
           不启用，仅首次判定记一条 INFO 日志（不刷屏）；
        2. 单飞：_evolution_in_flight 或 _running_agents 中已有 evo- run →
           本轮不派发，就绪项目留待下一检查点（D3「就绪即入队」）；
        3. 就绪扫描：registry 项目 → scan_ready_projects（MUST NOT 等待其他
           项目到齐）→ 全部就绪项目的 todo.md 解析出待分析条目（含 id），
           max_items_per_run 截断；
        4. 派发：无在途则立刻以队列中全部就绪项目启动一次分析 run（同一
           run 拿到多份 todo.md）。
        检查点整体 try/except 包裹（5.4：异常记 ERROR，MUST NOT 中断主循环；
        registry 读取失败同样在此捕获）。
        """
        try:
            # 5.2 宿主守卫：非自托管部署（PROJECT_ROOT != FRAMEWORK_ROOT）下
            # 本能力整体不启用（日志一次，不刷屏）
            if PROJECT_ROOT.resolve() != self._evolution_framework_root():
                if not self._evolution_host_guard_logged:
                    self._evolution_host_guard_logged = True
                    self.logger.info(
                        "fenixd",
                        "框架自进化未启用：PROJECT_ROOT != FRAMEWORK_ROOT"
                        f"（{PROJECT_ROOT} != {self._evolution_framework_root()}）",
                    )
                return

            # 第 0 步：周期保留清理（D4——在宿主守卫之后、单飞判定之前执行，
            # 清理不因分析 run 在途而跳过；独立 try/except 隔离失败）
            try:
                from core.evolution import prune_items

                pruned = prune_items(PROJECT_ROOT)
                if pruned.get("deleted", 0) > 0 or pruned.get("failed", 0) > 0:
                    detail_tail = ""
                    if pruned.get("details"):
                        detail_tail = "；详情: " + " | ".join(
                            f"{d.get('id')}: {d.get('error')}" for d in pruned["details"]
                        )
                    self.logger.info(
                        "fenixd",
                        f"自进化条目保留清理：total {pruned.get('total')}，"
                        f"kept {pruned.get('kept')}，deleted {pruned.get('deleted')}，"
                        f"failed {pruned.get('failed')}" + detail_tail,
                    )
            except Exception as e:
                self.logger.error("fenixd", f"自进化条目保留清理失败（不影响后续派发）: {e}")

            # 单飞判定（spec「分析 run 在途的判定基于 daemon 内部活跃 run 状态」）
            if self._evolution_in_flight:
                return
            running = list(getattr(self.agent_runner, "_running_agents", None) or {})
            if any(str(rid).startswith("evo-") for rid in running):
                # 在途 run（含派发-登记窗口未覆盖的情形）→ 留到下一检查点。
                # MUST NOT 置 _evolution_in_flight（code-review item d99cb1ec5477）：
                # 该标记的本意是「本检查点已 submit worker、由 worker 的 finally
                # 复位」。此处从未 submit，旧实现却置位 True——若该 evo- run 由
                # 其它路径产出（如 admin 派发）且长期挂着，标记将**永久**为 True，
                # 后续自进化检查点全部在这些短路，自进化静默停摆。此处仅记录日志
                # （下轮仍会因 run 在途再次跳过），不污染单飞标记。
                self.logger.info("fenixd", "自进化分析 run 在途，就绪项目留待下一检查点")
                return

            from core.dashboard.registry import Registry
            from core.evolution import (
                scan_ready_projects,
                parse_todo_entries,
                select_pending_entries,
                known_ids,
            )

            registry = Registry()
            projects = registry.discover()
            ready = scan_ready_projects(projects, PROJECT_ROOT)
            if not ready:
                return

            # 汇总全部就绪项目的待分析条目（带 project），max_items_per_run 截断
            pending: list = []
            # known_ids 在本检查点周期内不变（循环体只读不写 items.jsonl），
            # 循环外单次读取，避免每个就绪项目重复解析全量 items.jsonl
            known = known_ids(PROJECT_ROOT)
            for proj in ready:
                entries = parse_todo_entries(proj.get("todo_md") or "")
                for entry in entries:
                    entry["project"] = proj.get("name") or proj.get("path")
                batch = select_pending_entries(entries, known, 10**6)
                pending.extend(batch)
            se_cfg = ConfigLoader.get_self_evolution_config(self.config)
            limit = int(se_cfg["max_items_per_run"])
            if limit > 0:
                pending = pending[:limit]
            if not pending:
                return

            # 单飞标记与派发（水位推进快照时刻 = 派发时刻，见 _evolution_worker）
            self._evolution_in_flight = True
            snapshot_at = datetime.now(timezone.utc).isoformat()
            try:
                if self._admin_executor is not None:
                    self._admin_executor.submit(self._evolution_worker, ready, pending, snapshot_at)
                else:
                    self._evolution_worker(ready, pending, snapshot_at)
            except Exception as e:
                self._evolution_in_flight = False
                self.logger.error("fenixd", f"自进化分析 run 派发失败: {e}")
        except Exception as e:
            self.logger.error("fenixd", f"Evolution checkpoint failed: {e}")

    def _evolution_warn(self, message: str) -> None:
        """写一条自进化 admin WARNING 告警（escalation major 级，不阻塞）。"""
        try:
            if self.admin_store is not None:
                self.admin_store.append(
                    {
                        "kind": ESCALATION,
                        "severity": "major",
                        "signal_type": "self-evolution",
                        "spec": None,
                        "description": message,
                    }
                )
        except Exception as e:
            self.logger.warning("fenixd", f"自进化 admin 告警写入失败（降级）: {e}")

    def _evolution_worker(
        self, ready_projects: list, pending_entries: list, snapshot_at: str
    ) -> None:
        """worker 线程执行分析 run + 落地 + 自动接受 + 水位推进（5.3/5.4）。

        - 分析 run 成功落地后：auto_accept 为真 → 5.3 对本轮 pending 自动接受
          （decided_by=auto）；为假 → 保持 pending 等待用户；
        - 水位推进仅在 run 成功落地后发生，且使用派发时捕获的 snapshot_at
          （MUST NOT 落地时取 now()，避免漏掉 run 执行期间新写入的条目）；
        - 分析 run 失败 → WARNING 告警（含 run_id 与原因），水位不推进
          （下一检查点自动重试）；
        - 每轮成功落地记 INFO（就绪项目、条目数、草稿数、接受数、失败数）。
        """
        try:
            result = self.agent_runner.run_evolution(ready_projects, pending_entries)
            if result.success:
                from core.evolution import auto_accept_pending, advance_watermark

                se_cfg = ConfigLoader.get_self_evolution_config(self.config)
                accepted = 0
                if se_cfg["auto_accept"]:
                    try:
                        summary = auto_accept_pending(
                            PROJECT_ROOT, self.state_machine, spec_run_at=se_cfg.get("spec_run_at")
                        )
                        accepted = summary.get("accepted", 0)
                    except Exception as e:
                        self.logger.error("fenixd", f"自动接受流程异常（条目保持 pending）: {e}")
                else:
                    accepted = result.accepted
                # 水位推进：仅成功落地后，用 run 启动快照时刻
                advance_errors = 0
                for proj in ready_projects:
                    try:
                        advance_watermark(
                            PROJECT_ROOT, proj.get("name"), snapshot_at, result.run_id
                        )
                    except Exception as e:
                        advance_errors += 1
                        self.logger.warning("fenixd", f"自进化水位推进失败 {proj.get('name')}: {e}")
                self.logger.info(
                    "fenixd",
                    f"自进化分析 run {result.run_id} 落地完成："
                    f"就绪 {len(ready_projects)} 项目，条目 "
                    f"{result.items_ingested}，草稿 {result.drafts}，"
                    f"接受 {accepted}，失败 {advance_errors}"
                    + (f"（降级: {result.degraded}）" if result.degraded else ""),
                )
            else:
                reason = result.error or "未知原因"
                self._evolution_warn(f"自进化分析 run {result.run_id} 失败: {reason}")
                self.logger.error(
                    "fenixd",
                    f"自进化分析 run {result.run_id} 失败（水位不推进）: {reason}",
                )
        except Exception as e:
            # 5.4：检查点整体 try/except（异常记 ERROR，不中断主循环/其它任务）
            self._evolution_warn(f"自进化分析 run 异常: {e}")
            self.logger.error("fenixd", f"自进化分析 run 异常: {e}")
        finally:
            self._evolution_in_flight = False

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
        # submit 前先递增 submitted（code-review item 5786fd76ad49）：旧时序在
        # submit 返回后才计数——worker 可在其间领跑并先递增 completed/failed，
        # 在飞推导式 submitted - completed - failed 转负：_is_idle() 误报空闲
        # （喂给 stale-code 自重启决策），shutdown 的 _dropped 计数低估。先增
        # 后投、被拒回滚，保证任意瞬间 submitted ≥ completed + failed。
        with self._admin_pool_lock:
            stats = dict(self._admin_pool_stats)
            stats["submitted"] += 1
            self._admin_pool_stats = stats
        try:
            self._admin_executor.submit(self._admin_run_worker, signal)
        except RuntimeError as e:
            with self._admin_pool_lock:
                stats = dict(self._admin_pool_stats)
                stats["submitted"] -= 1
                self._admin_pool_stats = stats
            self.logger.error(
                "fenixd",
                f"Administrator 处置投递被拒绝（SPEC {spec}）：{e}",
            )
            self._record_failed_admin_disposition(spec, f"投递被拒绝：{e}")
            return False
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
            self.admin_store.append(
                {
                    "kind": DISPOSITION,
                    "status": "failed",
                    "signal_type": "manual-intervention",
                    "spec": spec,
                    "admin_run_id": None,
                    "description": f"手动唤起 Administrator 处理 SPEC {spec} 时出错：{reason}",
                    "result": "failed",
                }
            )
        except Exception:  # noqa: BLE001 — 落痕失败不影响主流程
            pass

    def _sweep_stale_admin_dispositions(self):
        """清理超时的残留处置状态实例文件（tasks 1.3）。

        run 异常中断（daemon 被杀等）时 .fenix/admin_disposition-<run_id>.json
        可能残留；无功能影响（每个实例按 run_id 读写），但会无限累积。旧全局
        文件 admin_disposition.json 已不再读写（无写入方、mtime 必然陈旧），
        与实例文件并入同一 candidates 列表按同一 24h mtime 阈值清理——首次
        清扫即满足阈值（code-review item e76f0a7ed092：legacy 并非「存在即
        清理」，同样受 24h 阈值约束）。
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

    def _shutdown_drain_seconds(self) -> float:
        """停机排水窗口基线（admin.shutdown_drain_seconds，缺省 1800，0=现行快速停机）。

        interrupt-recovery-preserve D1：非法值（负/非数字/非有限）回退缺省；0
        显式回退现行快速停机（不排水、不保全）。接受整值/浮点（测试以小数值
        构造排水超时路径，避免真等整秒；生产配置仍为整数秒）。

        add-pipeline-throughput-governance D3：restart_request 触发的在飞 run
        排水等待上限改由 ``_run_drain_max_seconds``（agents.run_drain_max_seconds，
        缺省 60，MUST ≤ 本值）单源提供；本方法保留为 supervisor 一致性自检与
        既有语义的基线读取方。
        """
        raw = ConfigLoader.get(self.config, "admin.shutdown_drain_seconds", 1800)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            self.logger.error(
                "fenixd",
                f"admin.shutdown_drain_seconds 非法（应为非负数值）: {raw!r}，回退 1800",
            )
            return 1800
        if value < 0:
            return 1800
        if not math.isfinite(value):
            # .nan/.inf 是 YAML 合法标量、float() 不报错：nan 令后续比较恒
            # False（supervisor SIGKILL 窗口自检静默失效），inf 则恒真告警——
            # 按非法值同款路径回退缺省并留痕。
            self.logger.error(
                "fenixd",
                f"admin.shutdown_drain_seconds 非法（应为非负有限数值）: {raw!r}，回退 1800",
            )
            return 1800
        return value

    def _run_drain_max_seconds(self, planned: bool = False) -> float:
        """restart 排水窗口上限（agents.run_drain_max_seconds，缺省 60）。

        add-pipeline-throughput-governance D3：专管 restart_request 触发的在飞
        run 排水等待；常规停机语义不变。单源经
        ``ConfigLoader.get_run_drain_max_seconds``。缺省组合下重启到新
        daemon 就绪无 1800s 级空等。

        planned-restart-drain D1：``planned=True``（restart_request 在场）时豁免
        shutdown=0 夹紧，改受 supervisor SIGKILL 等待−收口余量上界约束——
        shutdown_drain_seconds: 0 的快速停机联动仅作用于非规划性关停。
        """
        return ConfigLoader.get_run_drain_max_seconds(self.config, planned=planned)

    def _drain_set_inventory(self) -> tuple:
        """排水集合清单（在飞 run 与车道名二元组）——planned-restart-drain C。

        车道登记 API 为本 SPEC 新增，旧测试替身/第三方 runner 可能缺该方法，
        按空集容错（车道清单缺报不阻塞排水流程）。
        """
        if not self.agent_runner:
            return [], []
        running = self.agent_runner.running_run_ids()
        lanes_getter = getattr(self.agent_runner, "running_lane_ids", None)
        lanes = list(lanes_getter()) if callable(lanes_getter) else []
        return running, lanes

    def _drain_log_waiting(self) -> list:
        """排水开始日志 + 等待的 run 清单（interrupt-recovery-preserve 4.3）。

        planned-restart-drain C：排水集合清单扩展为「在飞 run + 车道名」双段
        留痕；返回值仍为 run 清单（checkpoint 广播数对比的既有契约不变）。
        """
        running, lanes = self._drain_set_inventory()
        if running or lanes:
            self.logger.info(
                "fenixd",
                f"Drain: waiting for running agents to finish: runs={running}, "
                f"lanes={lanes}",
            )
        else:
            self.logger.info("fenixd", "Drain: no running agents to wait for")
        return running

    def _check_supervisor_drain_consistency(self) -> None:
        """启动自检：supervisor 存在性 + 排水窗口一致性（fix-supervisor-hosting-chain D4）。

        拆为两项独立判定：
          A. supervisor 存在性——无条件执行（与 admin.shutdown_drain_seconds
             取值无关，drain=0 的项目也必须检测）。不存在 → logger WARNING +
             经 AdminStore 落一条 severity: major 的 supervisor_missing escalation
             告警（描述含「restart_request 不会被消费」，recommended_action 指引
             经 Dashboard「安装托管」或 /fenix-setup 恢复托管）；同一未处置告警
             去重不重复追加。
          B. drain 一致性——仅 drain > 0 时比对（supervisor 的 SIGKILL 等待窗口
             必须覆盖排水窗口，否则排水期被强杀截断）。drain <= 0 只跳过该项。
        """
        drain_seconds = self._shutdown_drain_seconds()

        # ── A. supervisor 存在性（无条件） ──────────────────────────────
        try:
            from core.fenix_session import supervisor_running

            supervisor_alive = supervisor_running(PROJECT_ROOT)
        except Exception:
            supervisor_alive = False  # /proc 不可读等：按不存在告警，宁紧勿松
        if not supervisor_alive:
            warn = (
                "未受 supervisor 托管：项目根下无活跃 supervisor 进程"
                "（bin/fenixd_supervisor.py），restart_request 不会被消费"
            )
            self.logger.warning("fenixd", warn)
            try:
                if self.pm_engine is not None:
                    self.pm_engine._append_project_log(f"⚠️ {warn}")
            except Exception:
                pass
            try:
                if self.admin_store is not None:
                    # 同类型未处置告警去重（不重复追加）
                    if self.admin_store.unhandled_for(None, "supervisor_missing") is None:
                        self.admin_store.append(
                            {
                                "kind": ESCALATION,
                                "signal_type": "supervisor_missing",
                                "spec": None,
                                "severity": "major",
                                "description": (
                                    "本项目 daemon 未受 supervisor 托管，restart_request "
                                    "不会被消费（supervisor 缺失）"
                                ),
                                "evidence": "fenixd 启动自检：项目根下无活跃 supervisor 进程",
                                "action_taken": "fenixd 启动自检发现托管缺失，升级人工",
                                "recommended_action": (
                                    "经 Dashboard 项目页「安装托管」或 /fenix-setup "
                                    "恢复 supervisor 托管"
                                ),
                            }
                        )
            except Exception as e:
                self.logger.warning(
                    "fenixd", f"supervisor_missing 告警写入失败（non-blocking）: {e}"
                )

        # ── B. drain 一致性（仅 drain > 0） ─────────────────────────────
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
            # code-review item d7ea0b9c5270：解析成功但顶层非 dict（null/[]/
            # 字符串等，部分写入或手工编辑）时旧判定整段静默跳过，恰是排水
            # 窗口可能被 SIGKILL 截断需告警的场景。并入既有「按未上报处理」
            # 告警分支并归一为 {}，再进 sigkill_wait/漂移判定。
            if not isinstance(data, dict):
                warnings.append(
                    f"supervisor runtime 顶层非对象（{type(data).__name__}）——"
                    f"按未上报处理，建议重启 supervisor 刷新上报"
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
                        f"（注意：supervisor 仅读项目级 .fenix/config.yaml 的 "
                        f"admin.shutdown_drain_seconds，该值只配在用户级 "
                        f"~/.fenix/config.yaml 时须同步写入项目级配置，重启无效）"
                    )
                # started_at 与 daemon_started 漂移判定（残留自旧进程）
                daemon_started = PROJECT_ROOT / ".fenix" / "daemon_started"
                drift_error = None
                try:
                    runtime_dt = parse_ts(str(data.get("started_at") or ""))
                    daemon_dt = parse_ts(
                        daemon_started.read_text(encoding="utf-8").strip()
                    )
                    runtime_ts = runtime_dt.timestamp() if runtime_dt else 0.0
                    daemon_ts = daemon_dt.timestamp() if daemon_dt else 0.0
                    if (
                        runtime_ts
                        and daemon_ts
                        and daemon_ts - runtime_ts > SUPERVISOR_RUNTIME_DRIFT_SECONDS
                    ):
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
        # PROJECT_LOG 追加窗口去重（evo-supervisor-drift-log-dedup 1.2）：
        # drain 一致性警告在每次 daemon 启动自检都会重新产出同一组 supervisor
        # 异常告警，高频提交下生命周期快速轮换、PROJECT_LOG 逐次刷屏。写入前
        # 查持久化 admin 告警存储：SUPERVISOR_LOG_DEDUP_MINUTES 窗口内已有同键
        # （supervisor_runtime_drift 族）记录则跳过追加（框架日志仍逐条落，
        # 被抑制的只是 PROJECT_LOG 追加）；未命中则照常追加，并写入一条
        # warning 级去重标记（写入即 mark_handled，不进人工告警队列），使去重
        # 状态跨重启存活。判定为族级粗粒度：窗口内不同子类异常不单独成条。
        # admin_store 不可用或读写异常时降级为照常追加（保持现状行为），不因
        # 去重机制引入静默丢日志。对齐 stale_code 通道窗口去重先例。
        suppressed = False
        dedup_tracked = False
        if warnings:
            try:
                if self.admin_store is not None:
                    recent = self.admin_store.latest_signal(
                        None, "supervisor_runtime_drift", SUPERVISOR_LOG_DEDUP_MINUTES
                    )
                    dedup_tracked = True
                    if recent is not None:
                        suppressed = True
                        self.logger.info(
                            "fenixd",
                            f"supervisor 漂移告警窗口去重命中："
                            f"{SUPERVISOR_LOG_DEDUP_MINUTES} 分钟内已有同信号记录"
                            f"（created {recent.get('created')}），跳过 PROJECT_LOG 追加"
                            f"（{len(warnings)} 条仅留框架日志）",
                        )
            except Exception as e:
                dedup_tracked = False
                self.logger.warning(
                    "fenixd",
                    f"supervisor 告警去重状态不可用，降级为照常追加 PROJECT_LOG"
                    f"（non-blocking）: {e}",
                )
        for w in warnings:
            self.logger.warning("fenixd", w)
            if suppressed:
                continue
            try:
                if self.pm_engine is not None:
                    self.pm_engine._append_project_log(f"⚠️ {w}")
            except Exception:
                pass
        if dedup_tracked and not suppressed:
            try:
                # spec MUST 为 None：latest_signal 的 spec=None 查询只匹配
                # spec=None 记录，标记带 spec 值会使窗口判定永不命中、去重
                # 静默失效。warning 级不在 HUMAN_SEVERITIES，写入即自动处置
                # （对齐 stale_code 记录语义），不进人工横幅/待处理队列。
                rec = self.admin_store.append(
                    {
                        "kind": ESCALATION,
                        "signal_type": "supervisor_runtime_drift",
                        "spec": None,
                        "severity": "warning",
                        "description": (
                            "supervisor 异常族告警已追加 PROJECT_LOG，"
                            f"{SUPERVISOR_LOG_DEDUP_MINUTES} 分钟内重启 daemon "
                            "不再重复追加"
                        ),
                        "evidence": "；".join(warnings)[:500],
                        "action_taken": "已追加 PROJECT_LOG 并写入去重标记（窗口去重）",
                        "recommended_action": "重启 supervisor 使排水窗口与上报刷新生效",
                    }
                )
                if not severity_needs_human(rec.get("severity")):
                    self.admin_store.mark_handled(rec["id"])
            except Exception as e:
                self.logger.warning(
                    "fenixd", f"supervisor 告警去重标记写入失败（non-blocking）: {e}"
                )

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
                # 两种日志口径（code-review item 67c551e85f1c）：无 spec 绑定
                # 车道（code-review/regression/code-fix/evo/self-review）的
                # run_id 解析不出 spec 属预期形态，info 留痕跳过；前缀表之外
                # 的解析失败仍按 warning 留痕——可能是绑 spec 但前缀表未覆盖
                # 的命名（admin-/planner-/impl-ocr- 等），须人工确认而非静默
                # 跳过保全。
                if str(run_id).startswith(_RUN_ID_NO_SPEC_PREFIXES):
                    self.logger.info(
                        "fenixd",
                        f"Preserve: run_id '{run_id}' 属无 spec 绑定车道 — skip",
                    )
                else:
                    self.logger.warning(
                        "fenixd",
                        f"Preserve: cannot parse spec from run_id '{run_id}' — skip",
                    )
                continue
            entry = self.state_machine.read_one(spec) or {}
            branch = entry.get("branch")
            worktree = ""
            if not branch and self.worktree_manager:
                # 首轮在飞 run：STATE `branch` 未写（run 未到终态）→ 回落
                # worktree_manager 的 spec → worktree 事实查询（git 真相，
                # 不依赖重启即失的内存表），取在册 worktree 与其分支。
                resolved = self.worktree_manager.find_worktree_by_spec(spec)
                if resolved is not None:
                    branch, worktree = resolved[1], str(resolved[0])
                    seen_wt.add(str(resolved[0]))
            if branch and self.worktree_manager:
                wt = self.worktree_manager.find_worktree_path(branch)
                worktree = str(wt) if wt else worktree
                if wt:
                    seen_wt.add(str(wt))
            ahead = _ahead_commit_count(branch) if branch else 0
            entries.append(
                {
                    "spec": spec,
                    "run_id": run_id,
                    "branch": branch or "",
                    "worktree": worktree,
                    "ahead_commits": ahead,
                    "reason": reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
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

    def _build_remerge_callback(self):
        """恢复期 re-merge-back 收口回调（fix-recovery-branch-anchor D4/4.2 接线）。

        返回 ``callable(spec_name) -> None``：对成功 re-merge 的 spec 执行
        PMEngine 侧收口副作用（对齐 dispatch repair re-merge 成功路径）——
        ``_clear_dispatch_conflict`` / ``_sync_task_progress`` /
        ``_reconcile_impl_budget`` / ``consume_legacy``。state_machine 无
        pm_engine 引用（仅注释提及模块名），故由 fenixd 注入。
        """

        def _cb(spec_name: str) -> None:
            # 锁冲突计数清零（recovery 侧无锁操作，零值写回即可）
            try:
                self.pm_engine._clear_dispatch_conflict(spec_name)
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"remerge 收口 _clear_dispatch_conflict 失败 '{spec_name}'" f"（非阻塞）: {e}",
                )
            try:
                self.pm_engine._sync_task_progress(spec_name)
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"remerge 收口 _sync_task_progress 失败 '{spec_name}'" f"（非阻塞）: {e}",
                )
            try:
                self.pm_engine._reconcile_impl_budget(spec_name)
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"remerge 收口 _reconcile_impl_budget 失败 '{spec_name}'" f"（非阻塞）: {e}",
                )
            try:
                if self.worktree_manager:
                    self.worktree_manager.consume_legacy(spec_name)
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"remerge 收口 consume_legacy 失败 '{spec_name}'（非阻塞）: {e}",
                )

        return _cb

    def _build_human_alert_callback(self):
        """恢复期冻结人工升级告警回调（fix-blocked-freeze-classification D4/1.2 接线）。

        返回 ``callable(spec_name, signal_type, severity, description, evidence,
        recommended_action) -> None``：经 ``pm_engine._send_human_escalation_alert``
        写入 human-escalation-alerts store。``state_machine`` 无 ``pm_engine``
        引用，发送由 fenixd 注入（与 ``_build_remerge_callback`` 同型注入模式）。

        ``pm_engine`` 未就绪时回退 ``None``——恢复路径退回静默冻结并打审计
        ERROR（helper 内），MUST NOT 掩盖。
        """
        pm = getattr(self, "pm_engine", None)
        if pm is None:
            self.logger.warning(
                "fenixd",
                "人工升级告警回调构造跳过：pm_engine 未就绪（恢复路径将"
                "退回静默冻结，helper 内记审计 ERROR）",
            )
            return None

        def _cb(
            spec_name: str,
            signal_type: str,
            severity: str,
            description: str,
            evidence: str,
            recommended_action: str,
        ) -> None:
            try:
                self.pm_engine._send_human_escalation_alert(
                    spec_name=spec_name,
                    signal_type=signal_type,
                    severity=severity,
                    description=description,
                    evidence=evidence,
                    recommended_action=recommended_action,
                )
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"恢复期冻结人工升级告警发送失败 '{spec_name}'"
                    f"（signal_type={signal_type}，非阻塞）: {e}",
                )

        return _cb

    def _preserve_implementing_specs(self, reason: str) -> list:
        """按 STATE 中 ``implementing`` spec 驱动的保全（fix-recovery-branch-anchor D5/5.2）。

        与 ``_preserve_interrupted_runs``（run_id 驱动）互补：后者只在排水超时
        （``remaining`` 非空）时触发；本方法在排水结束后只要仍存在收口未完成的
        ``implementing`` spec 即保全——事故形态（``remaining == []`` 但 repair
        worktree 仍在册）下旧调用点永不执行、sidecar 从未写、保护集退化为空集。

        - spec 集来源：STATE 全部 ``implementing`` spec（``get_by_status``）；
        - ``run_id`` 取该 spec 的 STATE ``implementer_run``（D1 落地后 run 成功
          即非空），缺失时留空串——无生产消费者（WIP checkpoint 与保护集
          构造只读 spec/worktree），空值无副作用；MUST NOT 回退
          ``_spec_from_run_id`` 反查（会把「STATE 无 implementer_run」的形态
          重新排除在外）；
        - worktree 取在册记录（``find_worktrees_by_spec`` 全量，不因歧义丢失；
          每个在册 worktree 各追加一条保全条目并全量并入返回值，code-review
          item a368f2d36516）；
        - 条目并入既有 sidecar（不覆盖，先读后写）。

        Returns: 新增保全条目的 worktree 路径列表（供保护集 / WIP checkpoint）。
        """
        entries = list(_read_preserve_sidecar())
        seen_wt = {e.get("worktree") for e in entries if e.get("worktree")}
        added_wt: list = []
        try:
            implementing = self.state_machine.get_by_status("implementing")
        except Exception as e:
            self.logger.warning(
                "fenixd",
                f"Preserve (spec-driven): STATE 读取失败——降级仅既有保全 " f"（非阻塞）: {e}",
            )
            return []
        for spec, entry in implementing:
            run_id = entry.get("implementer_run") or ""
            branch = entry.get("branch") or ""
            worktrees: list = []
            try:
                if self.worktree_manager:
                    worktrees = self.worktree_manager.find_worktrees_by_spec(spec)
            except Exception as e:
                self.logger.warning(
                    "fenixd",
                    f"Preserve (spec-driven): 在册 worktree 查询失败 " f"'{spec}'（非阻塞）: {e}",
                )
                worktrees = []
            if not worktrees and branch and self.worktree_manager:
                wt = self.worktree_manager.find_worktree_path(branch)
                if wt:
                    worktrees = [str(wt)]
            ahead = _ahead_commit_count(branch) if branch else 0
            # 每个「在册 worktree」各追加一条保全条目并全量并入返回值
            # （code-review item a368f2d36516）：旧实现只取 worktrees[0]，
            # 同一 spec 同时存在 impl- 与 repair- 两个在册 worktree 时，
            # 第二个既不写入 sidecar 也不进 WIP checkpoint 提交集合——
            # 锚点 A「中断时刻分支必有可恢复提交」只对首个 worktree 成立。
            # 条目结构不变，消费方（_wip_checkpoint_preserved_worktrees 的
            # worktree→spec 映射、保护集来源 (b)）按条目逐条读取，天然兼容。
            if not worktrees:
                worktrees = [""]
            for worktree in worktrees:
                worktree = str(worktree)
                if worktree and worktree not in seen_wt:
                    seen_wt.add(worktree)
                    added_wt.append(worktree)
                entries.append(
                    {
                        "spec": spec,
                        "run_id": run_id,
                        "branch": branch,
                        "worktree": worktree,
                        "ahead_commits": ahead,
                        "reason": reason,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            self.logger.warning(
                "fenixd",
                f"Preserving implementing spec '{spec}' (branch "
                f"'{branch or 'none'}', worktrees="
                f"{[wt for wt in worktrees if wt] or ['none']}, "
                f"ahead={ahead})",
            )
        if not _write_preserve_sidecar(entries):
            self.logger.warning(
                "fenixd",
                f"Preserve sidecar write failed (non-blocking) — "
                f"{len(entries)} entry/ies not persisted",
            )
        return sorted(added_wt)

    def _wip_checkpoint_preserved_worktrees(self, preserved_wts: list) -> None:
        """锚点 A（add-impl-wip-checkpoint D2）：排水超时收口静默窗口的 WIP 提交。

        在 ``wait_for_running_agents()`` 之后（所有在飞 agent 进程已死、
        worktree 静默可证明）、``cleanup_orphans`` 之前调用，对保全集每个
        worktree 执行一次 ``fenix(wip): checkpoint drain-preserve <spec>``
        提交——使中断时刻分支必有可恢复提交（ahead ≥ 1），下一 daemon 的
        ``_recovery_preserve_spec`` 保留续做判定自然命中，不再降级清空重建。

        空变更（git status --porcelain 为空）跳过；git 操作 15s 超时；任何
        失败仅 WARNING 留痕不阻塞收口（D6，与 _preserve_interrupted_runs
        同风格的尽力而为保全）。
        """
        if not preserved_wts:
            return
        # 以 sidecar 为 worktree → spec 映射源（_preserve_interrupted_runs
        # 刚写入，进程内存条目与落盘一致；读失败按「无映射」跳过提交）。
        wt_to_spec = {
            e.get("worktree"): e.get("spec")
            for e in _read_preserve_sidecar()
            if e.get("worktree") and e.get("spec")
        }
        for wt in preserved_wts:
            spec = wt_to_spec.get(str(wt)) or ""
            try:
                commit_wip_checkpoint(
                    wt,
                    spec or "unknown",
                    ANCHOR_DRAIN_PRESERVE,
                    self.logger,
                )
            except Exception as e:
                # 兜底：helper 理论上不抛，防御性捕获保证收口序列不被打断
                self.logger.warning(
                    "fenixd",
                    f"WIP checkpoint (drain-preserve) failed for '{wt}': " f"{e} — non-blocking",
                )

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
                rest = rid[len(prefix) + 1 :]
                # 车道复合前缀（code-review item cb8408ba09ec）：impl-ocr-<spec>-<ts>
                # （core/agent_runner/maintenance_runs._unique_impl_ocr_run_id 的
                # 实际命名）按 impl 剥离后第二段是保留字「ocr」（车道名）而非
                # spec——若放行，末段纯数字即「解析成功」，误产出脏 spec 名
                # 「ocr-<spec>」：调用方既不走 warning 留痕，还会用错误 spec 写
                # branch/worktree 全空的保全条目。此处返回 None 交由调用方
                # （_preserve_interrupted_runs）按 warning 留痕、提示人工确认。
                if prefix == "impl" and rest.split("-", 1)[0] == "ocr":
                    return None
                break
        else:
            return None
        # attempt 后缀剥离 MUST 只匹配尾部 `-a<digits>`（code-review item
        # 8c50a8d93441）：旧实现用 `if "-a" in rest: rest.rsplit("-a", 1)[0]`，
        # spec 名本身含 "-a"（my-app-fix、fix-a-b）时会在错误的 '-a' 处切分，
        # 得到 "my" 之类的错误 spec 名——排水保全 sidecar / 中断恢复续做均依赖
        # 该解析。用正则尾部锚定，且允许多段 attempt（与 runner._normalize_run_id
        # 的 (?:-a\d+|-r\d+)+$ 口径一致）。
        rest = re.sub(r"(?:-a\d+|-r\d+)+$", "", rest)
        parts = rest.rsplit("-", 1)
        if len(parts) == 2 and parts[0] and parts[1].isdigit():
            return parts[0]
        return None

    def shutdown(self):
        """Graceful shutdown。

        启动期信号安全（code-review item 9badfd92b4f9）：main() 在
        ``daemon.initialize()`` **之前**注册 SIGTERM/SIGINT handler，而
        initialize 内才设置 ``self.logger``/``self.config``。若信号落在启动
        窗口内，此处 ``self.logger.info(...)`` 会抛 AttributeError——但
        ``_shutdown_started`` 已置 True，此后每次信号都在守卫处直接返回，
        进程永久卡死（既不退出也不再响应）。故先做 logger 判空，并在日志
        缺失时用 stderr 兜底；置位顺序保持「守卫先于副作用」，但副作用本身
        全部做 None 安全。
        """
        if self._shutdown_started:
            return
        self._shutdown_started = True

        def _safe_log(level, msg):
            # 启动窗口信号安全（code-review item c94df33874ea）：docstring 承诺
            # 副作用全部 None-safe，但旧实现只有首条日志受守卫——非 drain 分支
            # debug、worktree_manager 清理日志、收尾 "fenixd stopped" 等仍直接
            # 调 self.logger，启动窗口（initialize 未完成）信号进入时抛
            # AttributeError，击穿 stderr 回退与 sys.exit(0)。全部后续日志统一
            # 经本助手：logger 缺失时回退 stderr。
            if self.logger is not None:
                getattr(self.logger, level)("fenixd", msg)
            else:
                sys.stderr.write(f"fenixd: {msg}\n")

        if self.logger is not None:
            self.logger.info("fenixd", "Shutting down...")
        else:
            sys.stderr.write("fenixd: shutdown during startup (logger not ready)\n")
        self.running = False

        # 关闭期间禁止派发新 agent（fix-admin-self-heal）：
        # 否则 wait_for_running_agents 等待期间 dispatcher 持续起新 agent，
        # 造成「杀一个又起一个」的关闭死循环
        if self.pm_engine:
            self.pm_engine.shutting_down = True
        if self.agent_runner:
            # shutdown 守卫信号源（shutdown-interrupted guard）：runner attempt
            # 循环据此区分「框架主动终止」与「网关瞬断」——不误判、不排僵尸
            # 原地重试、不污染瞬断熔断计数。
            self.agent_runner.shutting_down = True

        # 收口加速（fix-supervisor-hosting-chain 验证修复 BUG-01）：admin 线程
        # 大部时间睡在 interval_minutes 轮询中，join(5) 纯白等 5s——与 event_bus
        # 两线程 join 累加使非计划 SIGTERM 快速停机实测 10s+，逼近 dashboard
        # stop/install 端点 30s 超时线并击穿 12s「安装托管」等待窗。线程为
        # daemon 线程（进程退出由 OS 回收），join 仅作「放过当前轮」宽容窗。
        if self._admin_thread:
            self._admin_thread.join(timeout=2)
        # Administrator worker 池优雅关闭（fix-admin-run-blocks-mainloop tasks 2.3）：
        # 取消排队中任务、不等待在途处置——在途 run 由 pending disposition 标记
        # 可追溯，其 claude 子进程随后被 wait_for_running_agents 终止（interrupted
        # 标记 → 巡检按已知中断终结 pending，不升级人工）。
        if self._admin_executor is not None:
            # cancel_futures=True 会静默丢弃「已被池接受但尚未开跑」的处置
            # （code-review item f9b054acb529）：那些 future 永不进入
            # _admin_run_worker/_execute_admin_disposition，因此不会写 pending 或
            # failed disposition 记录——而请求文件已被 _check_admin_invoke_requests
            # 删除。处置前先核算「已提交但未完成」的数量并以日志留痕。
            # 口径说明（code-review item 931b7ac6aa1e）：submitted-completed-failed
            # ＝排队（未开跑）＋在途（执行中）的混合，池统计只有三计数器无法拆分；
            # wait=False 不等在途收尾，shutdown 后同一差值不变——故对同一数字只发
            # 下面这一条按事实描述的日志，不再分别断言「全部未开跑被取消」与
            # 「全部在途」这种互斥口径。
            try:
                with self._admin_pool_lock:
                    _stats_before = dict(self._admin_pool_stats)
                _dropped = max(
                    0,
                    _stats_before["submitted"]
                    - _stats_before["completed"]
                    - _stats_before["failed"],
                )
                self._admin_executor.shutdown(wait=False, cancel_futures=True)
                if _dropped:
                    _safe_log(
                        "warning",
                        f"Admin worker pool 关闭：至多 {_dropped} 条已提交未完成的处置"
                        f"（含排队与在途，池统计无法区分）：其中排队者已被取消、未写入"
                        f" disposition 记录（如需重放请核对运维记录中缺失的条目）；"
                        f"在途者由 pending disposition 标记可追溯",
                    )
            except Exception as e:
                _safe_log("error", f"Admin worker pool shutdown failed: {e}")
        if self.event_bus:
            self.event_bus.stop()

        # ── 规划性重启排水（interrupt-recovery-preserve D1/D4）──
        # restart_request 在册 = 规划性重启（supervisor 协议唯一信号源）→ 排水
        # 模式：禁新派发（shutting_down + admin 池/event_bus 已停）+ 等待在跑 run
        # 自然终态（上限 shutdown_drain_seconds，缺省 1800）；到期仍有在跑 run →
        # 先写 sidecar 保全，再走现行 terminate 收口。非计划 SIGTERM
        # （restart_request 不在册）或 drain=0 时行为逐字节不变（快速 terminate，
        # 无保全）。
        planned_restart = (PROJECT_ROOT / ".fenix" / "restart_request").exists()
        # add-pipeline-throughput-governance D3：restart 排水窗口改由
        # agents.run_drain_max_seconds（缺省 60）单源提供——治「排水窗口本身
        # 过长」（缺省 1800s 而在飞 run 多数不会窗内自行收尾，重启白等半小时）。
        # planned-restart-drain D1：规划性重启豁免 shutdown=0 快速停机夹紧，
        # 窗口单源按 planned 分叉取值；常规停机语义不受影响。
        drain_seconds = self._run_drain_max_seconds(planned=planned_restart)
        preserved_wts: list = []
        if planned_restart and drain_seconds > 0 and self.agent_runner:
            wait_list = self._drain_log_waiting()
            # graceful-restart-drain：排水等待前向每个在飞 run 广播一次
            # checkpoint 信号（写 run 控制旗标即返回，不阻塞排水等待，不产生
            # 新增失败终态）。广播清单计入排水日志留痕。
            # 广播 API 与车道登记 API 同为本期新增：未提供该方法的 runner 实现
            # （旧测试替身/第三方）按无 checkpoint 广播（0/0）容错继续排水，
            # 不在 _shutdown_started 之后中断收口序列。
            _broadcast_checkpoint = getattr(
                self.agent_runner, "broadcast_restart_checkpoint", None
            )
            checkpointed: list = []
            if callable(_broadcast_checkpoint):
                try:
                    checkpointed = _broadcast_checkpoint()
                except Exception as e:
                    # 广播失败不中断收口序列（与下方 _terminate_lanes 同款容
                    # 错）：记 error 后按无 checkpoint 广播（0/0）继续排水。
                    _safe_log(
                        "error",
                        f"Checkpoint broadcast on planned restart failed: {e}",
                    )
            _, drain_lanes = self._drain_set_inventory()
            _safe_log(
                "info",
                f"Drain: planned restart, drain window {drain_seconds}s, "
                f"waiting runs: {wait_list}, lanes: {drain_lanes}, "
                f"checkpoint broadcast: {len(checkpointed)}/{len(wait_list)}",
            )
            start_ts = time.time()
            remaining = self.agent_runner.drain_wait(timeout=drain_seconds)
            _safe_log(
                "info",
                f"Drain finished after {time.time() - start_ts:.0f}s, "
                f"remaining runs: {remaining}",
            )
            if remaining:
                # 排水超时：先保全再 terminate（sidecar 先于 terminate）
                preserved_wts = self._preserve_interrupted_runs(remaining, "drain timeout")
            # ── sidecar 触发条件放宽（fix-recovery-branch-anchor D5/5.2）──
            # 排水结束后仍存在收口未完成的 implementing spec 时同样保全
            # （run_id 驱动的 drain timeout 路径只覆盖「remaining 非空」，
            # 事故形态 remaining==[] 时旧调用点永不执行，repair worktree
            # 仍在 git worktree list 注册中却被 cleanup_orphans 误删）。
            # spec 驱动独立于 run_id，run_id 取该 spec 的 STATE implementer_run
            # （D1 落地后 run 成功即非空），缺失时留空串（无生产消费者）。
            spec_preserved = self._preserve_implementing_specs(
                "drain finished, spec-driven preserve"
            )
            preserved_wts.extend(spec_preserved)
        else:
            if planned_restart and drain_seconds <= 0:
                # planned-restart-drain C：规划性重启但排水窗口为 0（agents.
                # run_drain_max_seconds 显式禁用/夹紧为 0）——在飞工作将不经
                # 排水直接 terminate，WARNING 留痕窗口取值与排水集合清单。
                inv_runs, inv_lanes = self._drain_set_inventory()
                _safe_log(
                    "warning",
                    f"Drain: planned restart but drain window is 0s "
                    f"(agents.run_drain_max_seconds disabled) — in-flight work "
                    f"will be terminated without drain; drain set: "
                    f"runs={inv_runs}, lanes={inv_lanes}",
                )
            _safe_log(
                "debug",
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
            # planned-restart-drain B/D3：登记车道进程（ocr 等）有序终止收口——
            # SIGTERM → 短宽限 → SIGKILL，并等车道线程落终态（bounded），
            # 车道产物/serving worktree 不再被当无主回收。登记 API 为本 SPEC
            # 新增：未提供该 API 的 runner 实现（旧测试替身/第三方）按无车道
            # 处理，行为不变。
            _terminate_lanes = getattr(
                self.agent_runner, "terminate_lane_processes", None
            )
            if callable(_terminate_lanes):
                try:
                    lanes_done = _terminate_lanes()
                    if lanes_done:
                        _safe_log(
                            "info",
                            f"Lane processes terminated on shutdown: {lanes_done}",
                        )
                except Exception as e:
                    _safe_log(
                        "error", f"Lane process termination on shutdown failed: {e}"
                    )
            # add-impl-wip-checkpoint（锚点 A / D2）：所有在飞 agent 进程已死、
            # worktree 静默可证明，在 cleanup_orphans 之前对保全集 worktree 逐个
            # WIP 提交——中断时刻分支必有可恢复提交（ahead ≥ 1），下一 daemon
            # _recovery_preserve_spec 保留续做判定自然命中，不再降级清空重建。
            # 失败仅 WARNING 留痕，不阻塞后续 _v2_stop_all 和 cleanup_orphans（D6）。
            self._wip_checkpoint_preserved_worktrees(preserved_wts)
            # add-worktree-test-server（D2 关闭回收）：agent 收尾后回收全部在册 dev-server，
            # 释放端口，避免遗留进程占用。
            try:
                self.agent_runner._v2_stop_all()
            except Exception as e:
                _safe_log("error", f"V2 dev-server cleanup on shutdown failed: {e}")
        if self.worktree_manager:
            # 清理协调（D6 + fix-preserve-chain-first-round-gap D3）：保全在册
            # worktree 传入保护集，禁止清理与保全互删。sidecar 历史条目 worktree
            # 为空串（首轮在飞 run 的旧保全条目）时，以该 spec 的事实查询回落补入
            # 在册 worktree —— 保护集 MUST NOT 因 sidecar 字段为空而放行清理
            # （宁可多保不删：下轮 orphan 清理仍会重新评估）。
            # 来源 (c)（fix-recovery-branch-anchor D5/5.1）：STATE 全部
            # implementing spec 的**全部**在册 worktree——不依赖 sidecar 是否
            # 写入（事故形态 sidecar 从未写、保护集退化为空集）。
            protected = set(preserved_wts)
            src_b_count = 0
            try:
                for e in _read_preserve_sidecar():
                    if e.get("worktree"):
                        protected.add(str(e["worktree"]))
                        src_b_count += 1
                    elif e.get("spec"):
                        resolved = self.worktree_manager.find_worktree_by_spec(e["spec"])
                        if resolved is not None:
                            protected.add(str(resolved[0]))
                            src_b_count += 1
            except Exception:
                pass  # 保护集构造失败按「仅 preserved_wts」处理，不阻塞停机
            src_c_count = 0
            try:
                implementing = self.state_machine.get_by_status("implementing")
                for spec, _entry in implementing:
                    # 全量在册 worktree（find_worktrees_by_spec，不因歧义返回
                    # None）——同一 spec 存在多个在册 worktree 时全部加入保护集
                    try:
                        wt_paths = self.worktree_manager.find_worktrees_by_spec(spec)
                    except Exception:
                        wt_paths = []
                    if not wt_paths:
                        # 兜底：单值查询（历史形态）
                        resolved = self.worktree_manager.find_worktree_by_spec(spec)
                        if resolved is not None:
                            wt_paths = [str(resolved[0])]
                    for wp in wt_paths:
                        if wp not in protected:
                            protected.add(wp)
                            src_c_count += 1
            except Exception as e:
                # 来源 (c) 构造失败：WARNING 且至少保留 sidecar 来源，
                # MUST NOT 使保护集静默退化为空集（tasks 5.3）
                _safe_log(
                    "warning",
                    f"来源 (c) 保护集构造失败——保留 sidecar 来源（非阻塞）: {e}",
                )
            # 保护集构成日志（tasks 5.4）：各来源条目数可事后归因
            _safe_log(
                "info",
                f"cleanup_orphans 保护集构成：来源 (a) drain 保全 "
                f"{len(preserved_wts)} 项；来源 (b) sidecar {src_b_count} 项；"
                f"来源 (c) implementing spec {src_c_count} 项；保护集合计 "
                f"{len(protected)} 个 worktree",
            )
            self.worktree_manager.cleanup_orphans(protected=protected)

        _safe_log("info", "fenixd stopped")
        # code-review item ecc6fd4d27ad：仅在无在途异常时以 0 干净退出。
        # start() 的 while 主循环包在 try/except KeyboardInterrupt/finally 中，
        # finally 调本方法——若主循环抛出非 KeyboardInterrupt 异常，此处的
        # 无条件 sys.exit(0) 会在 finally 内抛 SystemExit 替换在途异常
        # （SystemExit 非 Exception，main() 的 except Exception 捕获不到），
        # FATAL 日志不打、失败被伪造成退出码 0。有在途异常时跳过 sys.exit，
        # 让原异常继续传播给 main() 记 FATAL 并以退出码 1 结束。
        # 信号处理器路径（SIGTERM/SIGINT → 本方法）在主循环正常执行点进入、
        # 无在途异常 → 仍走 sys.exit(0)，行为不变；启动窗口信号同理。
        if sys.exc_info()[0] is None:
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
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        # 锁文件不可用（.fenix 只读、daemon.lock 残留为同名目录等）：main() 在
        # 任何 try 块之前直接调本函数，不接住就以裸 traceback 退出——按入口
        # 路径守卫同款 FATAL 单行提示原因并以非零码干净退出。
        print(
            f"FATAL: 无法打开 daemon 单实例锁文件 {lock_path}: {e}，本实例退出",
            file=sys.stderr,
        )
        sys.exit(1)
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
    # 入口路径守卫：FENIX_DIR 必须解析为项目内 .fenix/（正常启动经 .fenix/fenixd.py
    # 软链）。直接跑仓库根实体 fenixd.py 时 __file__ 不跟随软链，FENIX_DIR 解析为
    # 仓库根 → PROJECT_ROOT 退化为上级目录（曾致 /root/.fenix/ 幻影状态目录、
    # 仓库根散落 0 字节 daemon.lock/fenixd.log，自省与排障双双被误导）。
    # 守卫置于 main() 内：模块级 import fenixd（test_config.py 等按路径直载）
    # 不触发。放在单实例锁之前，错误启动不污染锁文件。
    if FENIX_DIR.name != ".fenix":
        print(
            f"FATAL: fenixd.py 必须经项目的 .fenix/fenixd.py 软链启动"
            f"（当前 __file__ 解析为 {FENIX_DIR}，FENIX_DIR 不是 .fenix/）。\n"
            f"正确启动方式：cd <项目根> && python3 .fenix/fenixd.py",
            file=sys.stderr,
        )
        sys.exit(1)
    _acquire_singleton_lock()
    daemon = FenixDaemon()

    # add-adjudication-alert-narrative：装配告警叙事 LLM 通道（模块级注入点，
    # 生产=既有 claude -p spawn 单发通道）。注入点未装配时叙事模块整体惰性
    # （零调用）——测试进程因此天然不触网关，无需各自显式豁免。
    # 同时注入项目根作 claude 子进程 spawn cwd（同 agent_runner spawn 口径，
    # code-review 672decf84c0d）。
    from core.adjudication_narrative import (
        default_channel,
        set_channel,
        set_project_root,
    )

    set_project_root(str(PROJECT_ROOT))
    set_channel(default_channel)

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
