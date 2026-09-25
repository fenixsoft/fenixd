"""liveness.py — LivenessSupervisor：attempt 存活探测/活性快照/LLM 判活/超时监督/优雅等待（refactor-core-packages 阶段 3）。

状态同迁（design D3 规则 1）：_extension_baselines 随组件迁移；门面经 property 委托保持原路径可用。

"""

from pathlib import Path
# tool_result 事件识别单一真源（design D1：禁止在真源之外再次硬编码事件类型比较），
# 本模块经类内 staticmethod 别名委托复用（与 runner.py 同型），不保留本地副本。
from core.agent_runner.latency import _entry_is_tool_result
from core.agent_runner.run_files import append_run_error, append_run_line, run_spec_part
from datetime import datetime, timezone
import json
import subprocess
import time

# 优雅退出时对每个在跑 agent 的 SIGTERM 缓冲窗口（秒）。daemon 收到关闭信号后对所有
# 在跑 agent 发 SIGTERM，等此窗口让其收尾（关会话/flush 输出）；窗口结束仍未退出的
# 用 SIGKILL 兜底。取 claude 收尾所需量级，模块级常量便于测试注入短值。
# 见 spec agent-shutdown-interrupt：总关闭时长需压到 ≪ supervisor 60s SIGKILL 窗口。
AGENT_TERMINATE_GRACE_SECONDS = 10

# ── attempt 存活探测 / 超时活性监督（improve-run-lifecycle-governance）──────
# 进程扫描不可用时，run 流文件 mtime 在该窗口内视为 attempt 仍在活动（D4 回退判据）。
LIVE_ATTEMPT_STREAM_WINDOW_SECONDS = 120
# 超时监督默认值（D3）：单源定义于 core.config（supervision-timeout-config-consistency，
# 与 supervision_floor 派生共用，禁止两处各自手写常数）；本模块 import 后 re-export，
# 保持 ``from core.agent_runner.liveness import SUPERVISION_DEFAULTS`` 路径可用。
from core.config import SUPERVISION_DEFAULTS  # noqa: E402
# 活性判定 LLM 单轮调用的超时秒数（D2）：judge 卡死不能拖住监督循环
JUDGE_TIMEOUT_SECONDS = 120
# 活性快照 last_output 片段截断字符数（D1）
LIVENESS_SNIPPET_CHARS = 400

# ── 挂起判别常量（fix-run-hang-amplification D1）──────────────────────────
# 基于 fix-root-init-import-shadow 事故实证：
# - 后台调用（pytest）输出文件停在 0–22 字节，Agent 轮询数小时；
# - 同期心跳 349 条 vs 实质结果 130 条，窗口内零实质事件守卫被打穿。
# HANG_BLOCKED_CALL_SECONDS：单个后台调用被阻塞等待的时长阈值。
# 事故中 pytest 子进程死循环产出 I/O 44-60GB，阻塞持续 >10 分钟。
HANG_BLOCKED_CALL_SECONDS = 300
# HANG_ZERO_GROWTH_WINDOW_SECONDS：输出文件零增长需持续的窗口。
# 事故中后台任务输出文件数小时零增长（0-22 字节）。
HANG_ZERO_GROWTH_WINDOW_SECONDS = 300
# HANG_MIN_TOOL_COMPLETIONS：窗口内工具完成数下限（低于此视为无进展）。
# 事故窗口内工具完成数低，但心跳大量涌入。取 3 作为最小有效产出阈值。
HANG_MIN_TOOL_COMPLETIONS = 3

# ── mtime 新鲜度判定的三处同型点处置（fix-orphan-ready-recovery-liveness D5）──
# 「mtime 新鲜 ⇒ 进程仍活着」这一谬误在框架里有三处实现。本次只修第 1 处，
# 另两处按证据与归属分别处置，MUST NOT 静默忽略：
#
# ① 本处（_stream_recent → has_live_attempt）：判定对象 = 孤儿 ready 恢复前
#    的存活探针回退判据；已修——末行终态即判非存活。
#
# ② worktree_manager._latest_stream_mtime（→ has_active_worktree / refresh_locks
#    的「无进程但流新鲜 → 保守持锁」分支）：判定对象 = worktree 锁活性判定；
#    本次未命中（daemon 重启后内存锁表为空，has_active_worktree 走进程表分支
#    并正确返回 False）；且该分支的保守语义防的是「误释放锁 → 双派发」，收紧
#    影响面远超本次事故证据支持的范围，书面 defer。
#    ▸ 两处判定的交互（勿误以为彼此独立）：本处修好后，_on_spec_ready（engine.py:359-
#    372）对「在册陈旧锁 + 终态末行 + 挂锁流新鲜」的 SPEC 会由「静默跳过 live
#    attempt」变为「锁冲突 → 进退避 → 退避耗尽可能 dispatch_stalled 升级」；
#    因②的 STALE_LOCK_IDLE_SECONDS（1800s）远长于本处 120s 判活窗口，该升级
#    路径在修复前同样存在（仅延后 120 秒），本 SPEC 不因此扩面，但②的承接方需
#    知悉该形态会显性化为告警。
#
# ③ admin_monitor._has_recent_spec_run（→ spec_is_undriven → orphaned_state）：
#    判定对象 = 5 分钟监视周期的 undriven 信号；本次未命中（覆盖 implementing/
#    testing，与本次 ready 形态互补且已足够快）；判定口径已被在飞的
#    evo-orphaned-state-probe-calibration 占用，同批修改会造成两个 SPEC 撞同一
#    函数，书面 defer 给该 SPEC 承接。

# ── 启动终态补写扫描（fix-daemon-lifecycle-races D1）──────────────────────
# run jsonl 的终态事件类型（对齐 runner.py _run_was_interrupted 与
# admin_monitor.py _run_has_interrupted_marker 的判定口径）：
# result=自然完成, interrupted=daemon shutdown, error=进程异常终止,
# cancelled=人工取消, frozen-terminated=spec 冻结终止。任一类型出现即视为
# run 已终结。
# add-freeze-stop-inflight-agents D2：frozen-terminated 为写侧权威，必须同时
# 登记进 core/dashboard/data/runs.py::_RUN_TERMINAL_STATUS_MAP（读侧映射）——
# 两侧同步义务：缺写侧该 run 不会被清扫器/在跑判定终结；缺读侧 dashboard
# 永远把该 run 判成 running。
# add-timeline-gate-failure-display D4：gate-blocked 同承两侧同步义务——它是
# 门禁失败终止本次 attempt 的写侧终态（runner.py _append_gate_blocked），MUST
# 同时登记读侧 _RUN_TERMINAL_STATUS_MAP：缺写侧则末行 gate-blocked 的文件在
# 在跑判定（running_run_ids_for_spec / soft_delete_spec）里永被判为「在跑」，
# 刚被门禁拦下的 SPEC 删除/归档被误拦（无进程可停 → 有界等待超时后删除失败，
# add-freeze-stop-inflight-agents 同款事故形态）。
# ⚠️ 与 superseded **故意排除**（见 _file_tail_is_terminal 注释）不矛盾：
# gate-blocked 写在 attempt 终止之后，该文件再无写入者（重试在新 sub_run_id
# 文件），把它判终态正确；superseded 写在退避 sleep 之前、其窗口内没有别的
# 文件代表该 run，排除正是为了防退避窗口双派发。两者差异 MUST NOT 被「统一
# 口径」抹平。
RUN_TERMINAL_EVENT_TYPES = frozenset(
    {
        "result",
        "interrupted",
        "error",
        "cancelled",
        "frozen-terminated",
        "gate-blocked",
    }
)

# ── 运行期悬空 run 清扫（add-runtime-run-sweeper D2）──────────────────────
# 三重判据之流停阈值：run jsonl mtime 停更 ≥ 该秒数且不在在飞注册表、尾部
# 无终态事件 → 判为悬空并补写 interrupted 终态。任何存活写入者（主线程轮询环、
# stderr/stdout 读线程）都会持续刷新 mtime，故 mtime 冷却是「无写入者」的可靠
# 信号。取值 1800s = 3 × judge_window(600s)（SUPERVISION_DEFAULTS）：活性监督
# 判停滞窗口的 3 倍，保证监督续期路径（每轮 extension 也会写 timeout_extension
# 事件刷新 mtime）先于清扫器动作；最坏检测延迟 = 阈值 + 扫描周期（periodic
# scan 默认 30 分钟 ≈ 60 分钟），对比事故 12.3h 悬空。
RUNTIME_SWEEP_IDLE_SECONDS = 1800


def _file_has_terminal_event(run_file: Path) -> bool:
    """读 run jsonl 逐行判定尾部是否已有终态事件（运行期/启动清扫共享口径）。

    终态口径 = ``RUN_TERMINAL_EVENT_TYPES``（result/interrupted/error/cancelled/frozen-terminated/gate-blocked，以常量为准），
    两种清扫 MUST 复用本 helper，不得各自实现解析逻辑（runtime-run-sweep
    「与启动清扫口径一致」Requirement）。损坏 JSON 行跳过不阻断；
    文件不可读（OSError）视为无终态事件。
    """
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("type") in RUN_TERMINAL_EVENT_TYPES:
                    return True
    except OSError:
        return False
    return False


# 尾读字节窗口（fix-orphan-ready-recovery-liveness D2）：按字节窗口 seek 读末行，
# 窗口首行是上一行的残段必须丢弃；窗口内无完整行时回退全量逐行读。64KB 与
# dashboard _READ_RUN_TAIL_WINDOW 同量级，覆盖常规产物尾部（result 终态行 4KB+）。
_TAIL_READ_WINDOW = 64 * 1024


def _line_is_terminal(line: str) -> bool:
    """判单行文本是否为终态事件（解析失败 → False，fail-open 到「非终态」）。

    ``line`` 已 strip 非空；JSON 损坏 / 解析结果非 dict / type 不在终态集合 →
    False。保守侧是**不误杀在跑的 run**——把活 run 判死会导致双派发。
    """
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        return False
    return isinstance(entry, dict) and entry.get("type") in RUN_TERMINAL_EVENT_TYPES


def _last_line_is_terminal_full(run_file: Path) -> bool:
    """全量逐行读，判**末条非空行**是否为终态（尾读窗口回退分支）。

    空文件 / 文件不可读（OSError）→ False（fail-open）。
    """
    last = ""
    try:
        with run_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = line
    except OSError:
        return False
    if not last:
        return False
    return _line_is_terminal(last)


def _file_tail_is_terminal(run_file: Path) -> bool:
    """判 run jsonl 文件**末条非空行**是否已是终态事件（fix-orphan-ready-recovery-liveness 1.1）。

    本助手判**末行**、``_file_has_terminal_event`` 判**全文件是否出现过**终态事件，
    语义不同、不可互相替换：出现终态后 run 仍可能继续（interrupted 之后 error
    追加、result 之后 superseded 序列真实存在），存活判据要的是「末行终态即 run
    已明确终结」的后置不变量口径（对齐 dashboard classify_run 只看末行）。

    终态口径 = ``RUN_TERMINAL_EVENT_TYPES``（result/interrupted/error/cancelled/frozen-terminated/gate-blocked，以常量为准），
    复用框架单一真源，不另立集合。**superseded 不在终态集合内**——它是原地重试
    弃置旧产物文件的标记，run 在新 sub_run_id 文件继续，把其视为终结会造成原地
    重试退避窗口内的双派发。

    失败方向固定为 fail-open（= 仍视为存活）：文件不可读 / 空文件 / 末行损坏
    不可解析 / 末条事件非 dict → 一律返回 False。

    读取范式照 ``core/dashboard/data/runs.py`` ``_read_run_lines`` 自实现（本包
    不反向 import core.dashboard.*，design D2）：先按字节窗口 seek 尾部读，窗口
    首行是上一行残段必须丢弃；窗口内无完整行（末行超窗）时回退全量逐行读。
    """
    try:
        size = run_file.stat().st_size
    except OSError:
        return False
    if size <= 0:
        return False
    if size <= _TAIL_READ_WINDOW:
        return _last_line_is_terminal_full(run_file)
    try:
        with run_file.open("rb") as f:
            f.seek(-_TAIL_READ_WINDOW, 2)
            raw = f.read()
    except OSError:
        return False
    text = raw.decode("utf-8", errors="replace")
    # 窗口首行是从字节窗口切入的上一行残段，必须丢弃（见 _read_run_lines 注释）
    lines = [ln for ln in text.split("\n")[1:] if ln.strip()]
    if not lines:
        # 窗口内无完整行（末行超窗）→ 回退全量逐行读
        return _last_line_is_terminal_full(run_file)
    return _line_is_terminal(lines[-1])


def sweep_runs_without_terminal_state(runs_dir: Path) -> list:
    """启动终态补写扫描：扫描 runs_dir 顶层 *.jsonl，对尾部无终态事件的
    run 文件追加 ``{"type": "interrupted", "reason": "startup terminal-state
    sweep"}`` 终态事件。

    仅在 daemon 启动期调用一次（AgentRunner 初始化后、任何派发前）；
    孤儿 claude 进程存活不阻塞补写——run 文件由 daemon 侧转写，孤儿
    进程不会再产生新事件。

    Returns: 被补写的文件列表 ``[(run_file_name_stem, Path), ...]``。
    """
    if not runs_dir.is_dir():
        return []
    patched = []
    try:
        files = list(runs_dir.glob("*.jsonl"))
    except OSError:
        return []
    for run_file in files:
        if _file_has_terminal_event(run_file):
            continue
        # 无终态事件——追加 interrupted 终态（O_APPEND 单行原子追加）
        try:
            append_run_line(
                run_file,
                {
                    "type": "interrupted",
                    "reason": "startup terminal-state sweep",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            patched.append((run_file.stem, run_file))
        except OSError:
            pass
    return patched


class LivenessSupervisor:
    """LivenessSupervisor组件（门面 AgentRunner 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

        # 超时监督续期基准注册表（improve-run-lifecycle-governance 3.2 / D3）：
        # {spec_name: {"baseline": epoch, "run_id": str, "extension": int,
        #              "deadline": epoch}}。agent_runner 每次超时续期时把 baseline
        # 顺延到续期时刻，pm_engine 的 stuck 检测读取该基准而非 STATE.md 的固定
        # updated 起点——否则刚被续期的长任务下一轮就被误判 stuck。
        # 无显式回收：get_extension_baseline 按流文件新鲜度自清理（run 结束后
        # 流停止增长即失效）。
        self._extension_baselines: dict[str, dict] = {}

        # 运行期清扫已验证终态缓存（add-runtime-run-sweeper 1.4）：文件 stem 集合。
        # 确认含终态事件或已被本清扫器补写的文件入缓存，后续轮次不再打开读取；
        # 在飞文件（注册表命中）不入缓存——其终态由 run 线程写入，入缓存会跳过
        # 后续验证。首轮全量建缓存，此后增量。
        self._terminal_verified: set[str] = set()

        # 后台调用输出文件跨采样追踪（fix-run-hang-amplification 1.5）：
        # {task_id: {"last_size": int, "last_change": float}}。
        # started_at/output_file 不入本表，权威存放处是 _liveness_snapshot
        # 的 background_calls。
        # deadline 多次到点时对同一后台调用的输出文件做增长判定——
        # 「可观测零产出」短路需要两个采样点间 size 零增长而非单点猜测。
        self._output_tracking: dict = {}

    def sweep_dangling_runs(self) -> list:
        """运行期悬空 run 清扫（add-runtime-run-sweeper 1.3）：daemon 存活期间
        周期性（每轮 periodic scan）扫描 runs 目录，对满足三重判据（AND，缺一
        不扫、判据不过不打开读取）的 run 文件补写 interrupted 终态：

        ① run_id 不在 ``_running_agents`` 注册表（键 = 文件 stem，直接成员判定）
           —— 在飞保护，权威源；
        ② mtime 停更 ≥ ``RUNTIME_SWEEP_IDLE_SECONDS`` —— 流停保护，先行短路
           免读文件（任何存活写入者都会刷新 mtime）；
        ③ ``_file_has_terminal_event`` 为 False —— 尾部无终态事件。

        安全性：result 终态只能由 run 线程的 finally 块写出；线程不在注册表 =
        该 run 的终态写入者已不可达，补写 interrupted 只把「框架已知的死亡」
        显式化，不销毁可恢复数据。派发/finally 窗口（µs–ms 级）因 mtime 新鲜
        被判据 ② 跳过。

        缓存：确认终态或已补写的 stem 入 ``_terminal_verified``，命中即跳过；
        在飞文件不入缓存。

        Returns: 被补写的文件列表 ``[(run_file_name_stem, Path), ...]``。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return []
        try:
            files = list(runs_dir.glob("*.jsonl"))
        except OSError:
            return []
        now = time.time()
        patched = []
        for run_file in files:
            stem = run_file.stem
            # 缓存命中：终态已确认/已补写，不打开读取
            if stem in self._terminal_verified:
                continue
            # 判据 ①：在飞保护（注册表命中 → 跳过且不入缓存）
            if stem in self._pm._running_agents:
                continue
            # 判据 ②：流停保护，先行短路免读
            try:
                idle_seconds = int(now - run_file.stat().st_mtime)
            except OSError:
                continue
            if idle_seconds < RUNTIME_SWEEP_IDLE_SECONDS:
                continue
            # 判据 ③：尾部无终态事件（含终态 → 入缓存，后续轮次零读取）
            if _file_has_terminal_event(run_file):
                self._terminal_verified.add(stem)
                continue
            # 三重判据全中——补写 interrupted 终态（O_APPEND 单行原子追加）
            try:
                append_run_line(
                    run_file,
                    {
                        "type": "interrupted",
                        "reason": "runtime terminal-state sweep",
                        "idle_seconds": max(0, idle_seconds),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except OSError:
                continue
            self._terminal_verified.add(stem)
            patched.append((stem, run_file))
        if patched:
            # 告警格式对齐启动清扫（fenixd.py 启动清扫 WARNING）
            self._pm.logger.warning(
                "agent_runner",
                f"Runtime terminal-state sweep: 补写 {len(patched)} 个悬空 "
                f"无终态 run 的 interrupted 终态: " + ", ".join(run_id for run_id, _ in patched),
            )
        return patched

    def has_live_attempt(self, spec_name: str) -> bool:
        """探测某 SPEC 是否仍有存活的 attempt 子进程（恢复一致性 D4 接口）。
        判定顺序：
          1. pgrep 进程表：cmdline 含该 spec 的 worktree 目录字面量
             （``worktrees/{impl,verify}-<spec>-<ts>``）→ 存活；
          2. 进程扫描不可用/未命中时，回退 run 流文件新鲜度：
             该 spec 任一 run jsonl 的 mtime < LIVE_ATTEMPT_STREAM_WINDOW_SECONDS
             视为仍在活动（resume 孤儿进程通常持续写流）。

        供 pm_engine auto-recovery 与 event_bus 孤儿 ready 白名单调用——
        有存活子进程时 MUST NOT 重置状态/清空跟踪字段。
        """
        try:
            # 经门面回引（design D3 规则 3）：测试在门面实例上替换
            # runner._pgrep_live_attempt 的补丁缝保持有效。
            if self._pm._pgrep_live_attempt(spec_name):
                return True
        except Exception as e:  # 扫描器异常一律走流新鲜度回退，不向上抛
            self._pm.logger.debug(
                "agent_runner",
                f"has_live_attempt process scan failed for '{spec_name}': {e}",
            )
        return self._stream_recent(spec_name, LIVE_ATTEMPT_STREAM_WINDOW_SECONDS)

    def _pgrep_live_attempt(self, spec_name: str) -> bool:
        """pgrep 匹配 cmdline 含该 spec worktree 目录字面量的进程。

        pgrep 不可用（缺失/超时/OSError）时返回 False，由流新鲜度回退判定。

        pgrep 命中后须逐 PID 复核归属：子串 pattern ``worktrees/{prefix}-<spec>-``
        在 spec 名互为前缀时会命中他 spec 的 worktree（``fix-auth`` 的 pattern
        可匹配 ``impl-fix-auth-2-<ts>`` 目录路径），不复核则他 spec 的进程持续
        把本 spec 判存活，auto-recovery 与孤儿 ready 恢复被挡。复核口径与
        ``_stream_recent`` 的 ``run_spec_part`` 全等守卫（范式源自 recovery.py）
        一致：从 ``/proc/<pid>/cmdline`` 提取 ``worktrees/`` 目录段，按
        ``run_spec_part`` 同款解析出 spec 段做全等比较，仅全等命中才判存活。
        ``/proc`` 读不到（进程刚退出/权限不足）的 PID 按命中保守处理——误判
        False 会把活进程的 spec 重置状态，比误判 True（多挡一轮恢复）更重。
        """
        for prefix in ("impl", "verify"):
            pattern = f"worktrees/{prefix}-{spec_name}-"
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (subprocess.SubprocessError, OSError):
                return False
            if res.returncode != 0 or not res.stdout.strip():
                continue
            for pid_str in res.stdout.split():
                try:
                    with open(f"/proc/{pid_str}/cmdline", "rb") as f:
                        argv = f.read().split(b"\0")
                except OSError:
                    # 进程刚退出/权限不足：无法排除归属，保守判存活
                    return True
                for arg in argv:
                    text = arg.decode("utf-8", "replace")
                    idx = text.find("worktrees/")
                    if idx < 0:
                        continue
                    dirname = text[idx + len("worktrees/") :].split("/", 1)[0]
                    if run_spec_part(dirname) == spec_name:
                        return True
        return False

    def _stream_recent(self, spec_name: str, seconds: int) -> bool:
        """该 spec 最新 run 流文件的 mtime 是否在 seconds 内且**末行非终态**。

        mtime 新鲜只证明「文件近期被写过」（有写活动），末行终态证明「run 已
        明确终结」（没有生命）——两条件取 AND 才是「有生命」的辅助判据。判据
        分层：resume 孤儿进程通常持续写流，故 mtime 新鲜 ≈ 进程还在；但框架
        主动 SIGTERM 杀掉的 run 也会留下新鲜的流（runner 收口补写 error 终态行），
        若不排除末行终态的文件，刚死的 run 会在 120s 窗口内把恢复挡在门外
        （fix-orphan-ready-recovery-liveness 事故：daemon 停机杀的 run 在重启后
        首轮恢复被误判 live child present，SPEC 空等一个扫描周期）。

        不可用（无 runs 目录 / 无匹配文件）→ False。文件不可读 / 末行解析失败
        经 ``_file_tail_is_terminal`` fail-open 到「非终态」→ 仍计为存活（保守
        侧不误杀在跑 run）。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        cutoff = time.time() - seconds
        # evo-spec-concurrency-flight-guard 0.1：在飞判定前缀覆盖 spec-review-/
        # repair-（评审/修复 run 同样「新鲜 + 末行非终态」判在飞）。扩展后
        # has_live_attempt / 孤儿 ready 恢复对「评审/修复 run 在飞」的 spec 一
        # 并视为有生命（不重置状态、不重复派发），与 D0 判定同口径。
        for prefix in ("impl", "verify", "spec-review", "repair"):
            try:
                paths = list(runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"))
            except OSError:
                return False
            for p in paths:
                # 精确归属守卫（范式见 recovery.py）：spec 名互为前缀时
                # glob 命中不得直接认定——fix-x 不得被 fix-x-y 的活跃流延期
                if run_spec_part(p.stem) != spec_name:
                    continue
                try:
                    if p.stat().st_mtime >= cutoff and not _file_tail_is_terminal(p):
                        return True
                except OSError:
                    continue
        return False

    def _run_stream_alive(self, run_id: str, seconds: int) -> bool:
        """该 run_id 的流文件是否「新鲜且末行非终态」（_stream_recent 同口径，per-run）。

        evo-spec-concurrency-flight-guard D0 第 3 条：与 ``_stream_recent`` 的
        「mtime 新鲜 AND 末行非终态」判定逐条同构，差异仅为判定对象是**单个
        run_id 的流文件**（``runs/<run_id>.jsonl``）而非按 spec 前缀扫描——
        D0 的 `reviewer_run` 是完整 run_id（``spec-review-<spec>-<ts>`` /
        ``repair-<spec>-<ts>``），天然覆盖这两类前缀，不另起前缀表。
        文件不存在/不可读经 ``_file_tail_is_terminal`` fail-open 到「非终态」时
        仍要求 mtime 新鲜才判存活（保守侧不误杀在跑 run，与 _stream_recent 一致）。
        """
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        if not runs_dir.is_dir():
            return False
        run_file = runs_dir / f"{run_id}.jsonl"
        try:
            if run_file.stat().st_mtime >= time.time() - seconds and not _file_tail_is_terminal(
                run_file
            ):
                return True
        except OSError:
            return False
        return False

    def reviewer_in_flight(
        self, spec_name: str, reviewer_run: str | None
    ) -> tuple[bool, str | None]:
        """D0 判定总则：「在飞评审 run」= ``_active_reviews`` 命中 或 reviewer_run 非空且该 run 尚在飞。

        分层判据（fix-spec-review-blocking-dispatch 3.1/3.2/3.6 扩展既有
        evo-spec-concurrency-flight-guard D0 分层；进程表为真相，流文件兜底，
        陈旧锚点 fail-open，对齐 spec/changes/evo-spec-concurrency-flight-guard/
        design.md D0）：

          0. ``_active_reviews`` 命中（经 pm_engine 门面 ``is_review_in_flight``
             查询，PMEngine __init__ 注入 ``_pm_engine_ref`` 回引——agent_runner
             不持 pm_engine，tasks 3.7 显式约定查询通路）→ ``(True, "queued")``。
             覆盖「评审条目已出队、四步链锚点尚未落盘」的窗口——期间进程表与
             流文件均判否，若落到陈旧锚点分支会诱导调用方清理锚点、放行并发派发。
             本前置判据 MUST 优先于判据 1 的空锚点短路（tasks 3.6）。
          1. ``reviewer_run`` 为空 → ``(False, None)``（无在飞评审）。
          2. ``running_run_ids()``（进程表为真相，评审 run 经 ``_run_claude``
             注册进 ``_running_agents``）含 ``reviewer_run`` → ``(True, "process")``。
          3. 该 run 流文件「新鲜且末行非终态」（``_run_stream_alive``，与
             ``_stream_recent`` 同口径，覆盖 spec-review-/repair- 前缀）
             → ``(True, "stream")``。
          4. 2、3 皆否 → **陈旧锚点**（run 已终态但结果未消费/历史残留）：
             ``(False, "stale")``——调用方 MUST 按「无在飞评审」放行并记 WARNING，
             交由既有恢复路径清理锚点（防自造死锁）。stale 语义收窄为「确无
             在飞评审」：``"queued"`` 判据已覆盖入队/出队窗口，不会把在飞
             误标为 stale（spec-concurrency-governance Scenario「陈旧锚点语义
             收窄」）。
          5. 判定过程异常 → fail-open ``(False, None)``（不新增死锁面，对齐
             engine.py:470-478 既有门控容错），异常详情记 WARNING 日志。

        Returns: ``(in_flight: bool, reason: str | None)``。reason 取值
        ``"queued"`` / ``"process"`` / ``"stream"``（在飞）、``"stale"``
        （陈旧锚点）、None（无）。
        """
        # 前置判据 0（fix-spec-review-blocking-dispatch 3.1/3.6）：`_active_reviews`
        # 命中即判在飞。查询经 PMEngine 门面 `is_review_in_flight`（回引 `_pm_engine_ref`
        # 在 PMEngine.__init__ 注入）；无回引（测试的瘦门面/CLI 构造）时跳过本判据，
        # 回到既有分层。判定异常 fail-open：发不起查询不等于「无在飞」，保守放行
        # 到既有分层继续（不落入 stale 终局）。
        pm_engine_ref = getattr(self._pm, "_pm_engine_ref", None)
        if pm_engine_ref is not None:
            try:
                if pm_engine_ref.is_review_in_flight(spec_name):
                    return True, "queued"
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner",
                    f"reviewer_in_flight 队列前置判据异常 '{spec_name}'"
                    f"（fail-open 继续既有分层）: {e}",
                )
        if not reviewer_run:
            return False, None
        # 判据 2：进程表（in-process 注册表；判据异常不回退到流判据的判定不成立，
        # 而是 fail-open 放行——进程表读不出不等于评审在飞）
        try:
            running = self._pm.running_run_ids() or []
            if reviewer_run in running:
                return True, "process"
        except Exception as e:
            self._pm.logger.warning(
                "agent_runner",
                f"reviewer_in_flight 进程表判定异常 '{spec_name}' "
                f"run={reviewer_run}（fail-open 继续流判据）: {e}",
            )
        # 判据 3：流文件新鲜 + 末行非终态（spec-review-/repair- 前缀天然覆盖）
        try:
            if self._run_stream_alive(reviewer_run, LIVE_ATTEMPT_STREAM_WINDOW_SECONDS):
                return True, "stream"
        except Exception as e:
            self._pm.logger.warning(
                "agent_runner",
                f"reviewer_in_flight 流判据异常 '{spec_name}' "
                f"run={reviewer_run}（fail-open 放行）: {e}",
            )
            # fail-open：流判据异常 ≠ 明确的「流不存活」，回到判据 5 的中性
            # 无在飞结论（不落入下方判据 4 的 stale 终局判定——stale 语义是
            # 「run 已终态」，与判据异常的事实不符，误标会诱导调用方清理锚点，
            # 反而放行真正的在飞评审并发派发，击穿本守卫）。
            return False, None
        # 判据 4：陈旧锚点（无存活进程、无新鲜非终态流）——放行由调用方执行
        return False, "stale"

    def note_run_extension(
        self, spec_name: str, run_id: str, extension_index: int, new_deadline: float
    ) -> None:
        """超时续期时登记该 spec 的新 stuck 检测基准（续期时刻）。

        pm_engine.check_blockers 的 stuck 计算通过 ``get_extension_baseline``
        读取该基准，使 stuck 起点随续期同步顺延——否则刚续期的长任务立刻被
        误判 stuck 并触发 auto-recovery（等于绕过整个监督机制）。
        """
        self._extension_baselines[spec_name] = {
            "baseline": time.time(),
            "run_id": run_id,
            "extension": int(extension_index),
            "deadline": float(new_deadline),
        }
        self._pm.logger.info(
            "agent_runner",
            f"Extension #{extension_index} noted for '{spec_name}' (run {run_id}) — "
            f"stuck baseline reset, new deadline "
            f"{datetime.fromtimestamp(new_deadline, timezone.utc).isoformat()}",
        )

    def get_extension_baseline(self, spec_name: str) -> float | None:
        """返回该 spec 的续期基准（epoch 秒）；无条目或 run 已结束返回 None。

        新鲜度自清理：关联 run 流文件已停止增长（超过 LIVE_ATTEMPT_STREAM_
        WINDOW_SECONDS）说明 run 已结束——基准随即失效并移除，调用方回退到
        既有 updated 起点（行为与无注册表时一致）。
        """
        entry = self._extension_baselines.get(spec_name)
        if not entry:
            return None
        run_id = entry.get("run_id") or ""
        run_file = self._pm.project_root / ".fenix" / "runs" / f"{run_id}.jsonl"
        try:
            mtime = run_file.stat().st_mtime
        except OSError:
            self._extension_baselines.pop(spec_name, None)
            return None
        if time.time() - mtime > LIVE_ATTEMPT_STREAM_WINDOW_SECONDS:
            self._extension_baselines.pop(spec_name, None)
            return None
        return float(entry.get("baseline") or 0.0)

    def _liveness_snapshot(
        self, run_file: Path, window_seconds: float, now: float | None = None
    ) -> dict:
        """run jsonl 活性快照（D1）：窗口内事件数、工具完成数、最后事件距今。

        判定要素（fix-run-hang-amplification D1 修订）：
        - ``events_in_window``：窗口内**实质事件**数（assistant / user 含 tool_result / result）；
        - ``substantive_events_in_window``：同上（语义别名，供 judge 与日志）；
        - ``heartbeats_in_window``：窗口内心跳数（tool_progress，MUST NOT 计入进度）；
        - ``tool_completions_in_window``：窗口内工具完成数（tool_result 事件数）；
        - ``tool_use`` / ``tool_counts``：assistant 消息中的工具调用计数；
        - ``last_event_age``：最后一个事件距今秒数（事件无时间戳时回退文件 mtime）；
        - ``last_output``：最后的 assistant 文本 / result 文本片段（截断）。

        分类规则（对齐 runner.py _entry_is_tool_result 口径）：
        - 实质事件：type == "assistant" / type == "user" 且 content 含 tool_result / type == "result"
        - 心跳：type == "tool_progress"
        - 工具完成：_entry_is_tool_result(entry) 为 True

        无时间戳的行（stderr 兜底行等）按「文件 mtime 在窗口内即计入实质事件」的口径
        处理，保证纯 stderr 流不会被误判为死流。
        """
        now = time.time() if now is None else now
        snapshot = {
            "run_file": str(run_file),
            "window_seconds": float(window_seconds),
            "total_events": 0,
            "events_in_window": 0,
            "substantive_events_in_window": 0,
            "heartbeats_in_window": 0,
            "tool_completions_in_window": 0,
            "tool_use": 0,
            "tool_counts": {},
            "last_event_age": None,
            "last_output": "",
            "stream_available": True,
            "background_calls": {},  # task_id -> {"output_file", "started_at"}
        }
        cutoff = now - max(0.0, window_seconds)
        try:
            with run_file.open(encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    snapshot["total_events"] += 1
                    ts = self._pm._parse_event_timestamp(entry)
                    # 事件分类计数（fix-run-hang-amplification D1）
                    etype = entry.get("type") or ""
                    is_heartbeat = etype == "tool_progress"
                    is_substantive = (
                        etype == "assistant"
                        or etype == "result"
                        or (etype == "user" and self._is_tool_result_event(entry))
                    )
                    is_tool_complete = self._is_tool_result_event(entry)
                    # 事件是否落在判定窗口内（无时间戳回退文件 mtime）
                    if ts is None:
                        try:
                            in_window = run_file.stat().st_mtime >= cutoff
                        except OSError:
                            in_window = False
                    else:
                        in_window = ts >= cutoff
                    # 窗口内分类计数：心跳与实质事件分别计数，MUST NOT 混淆
                    if in_window:
                        if is_heartbeat:
                            snapshot["heartbeats_in_window"] += 1
                        elif is_substantive:
                            snapshot["events_in_window"] += 1
                            snapshot["substantive_events_in_window"] += 1
                        if is_tool_complete:
                            snapshot["tool_completions_in_window"] += 1
                    if ts is not None and (
                        snapshot["last_event_age"] is None
                        or (now - ts) < snapshot["last_event_age"]
                    ):
                        snapshot["last_event_age"] = max(0.0, now - ts)
                    # 工具调用计数（assistant 消息中的 tool_use）
                    if etype == "assistant":
                        msg = entry.get("message") or {}
                        for block in msg.get("content") or []:
                            if not isinstance(block, dict):
                                continue
                            if block.get("type") == "tool_use":
                                snapshot["tool_use"] += 1
                                name = str(block.get("name") or "unknown")
                                snapshot["tool_counts"][name] = (
                                    snapshot["tool_counts"].get(name, 0) + 1
                                )
                            elif block.get("type") == "text":
                                text = str(block.get("text") or "").strip()
                                if text:
                                    snapshot["last_output"] = text
                    elif etype == "result":
                        text = str(entry.get("result") or "").strip()
                        if text:
                            snapshot["last_output"] = text
                    # 后台调用事件提取（task_started / TaskOutput，1.5）：
                    # task_started（含 system subtype=task_started）记录 task_id→output_file；
                    # TaskOutput（后台任务输出片段）补充关联 task_id 与 started_at。
                    _is_task_started = etype == "task_started" or (
                        etype == "system" and entry.get("subtype") == "task_started"
                    )
                    _is_task_output = etype in ("TaskOutput", "task_output")
                    if _is_task_started or _is_task_output:
                        _task_id = entry.get("task_id")
                        if _task_id:
                            _calls = snapshot["background_calls"]
                            _rec = _calls.get(_task_id)
                            if _rec is None:
                                _rec = {"output_file": None, "started_at": None}
                                _calls[_task_id] = _rec
                            if _is_task_started and entry.get("output_file"):
                                _rec["output_file"] = str(entry["output_file"])
                            if ts is not None and _rec.get("started_at") is None:
                                _rec["started_at"] = ts
        except OSError:
            snapshot["stream_available"] = False
            return snapshot

        if snapshot["last_event_age"] is None:
            # 全部事件无时间戳：以文件 mtime 作为最后活动时刻
            try:
                snapshot["last_event_age"] = max(0.0, now - run_file.stat().st_mtime)
            except OSError:
                snapshot["last_event_age"] = None
        snapshot["last_output"] = snapshot["last_output"][:LIVENESS_SNIPPET_CHARS]
        return snapshot

    # tool_result 事件识别委托 latency.py _entry_is_tool_result 单一真源
    # （design D1：不得在真源之外再次硬编码事件类型比较）；staticmethod 别名
    # 保持 self._is_tool_result_event 调用点与原方法名不变。
    _is_tool_result_event = staticmethod(_entry_is_tool_result)

    @staticmethod
    def _summarize_snapshot(snapshot: dict) -> str:
        """活性快照的证据摘要（供终止证据与日志，短小可读）。

        fix-run-hang-amplification D1：同时呈现实质事件数、工具完成数与心跳数，
        MUST NOT 只给一个混合的「事件数」——复盘可直接读出真进展 vs 心跳。
        """
        tools = snapshot.get("tool_counts") or {}
        tool_str = ",".join(f"{k}x{v}" for k, v in sorted(tools.items())) or "none"
        age = snapshot.get("last_event_age")
        return (
            f"events_in_window={snapshot.get('events_in_window')}, "
            f"substantive_events_in_window={snapshot.get('substantive_events_in_window')}, "
            f"tool_completions_in_window={snapshot.get('tool_completions_in_window')}, "
            f"heartbeats_in_window={snapshot.get('heartbeats_in_window')}, "
            f"total_events={snapshot.get('total_events')}, "
            f"tool_use={snapshot.get('tool_use')} ({tool_str}), "
            f"last_event_age={'n/a' if age is None else f'{age:.0f}s'}, "
            f"last_output={(snapshot.get('last_output') or '')[:160]}"
        )

    def _judge_liveness(self, snapshot: dict, spec_name: str | None, run_id: str) -> dict:
        """轻量 LLM 活性判定（D2）：单轮调用，输出 {verdict, evidence}。

        模型路由复用 Administrator 的兜底通道（DEFAULT_GATEWAY_MODEL），不落
        .fenix/runs 正式 run 文件——判定结论写回被监督 run 的 jsonl 与 daemon 日志。
        任何解析失败 / 异常都按 ``stagnant`` 处理，evidence 以
        ``liveness judge unavailable`` 开头（tasks 4.2 要求的可辨识证据）。

        per-agent-timeout-override 3.3：judge 子进程超时经
        ``agents.timeout_overrides.supervision-judge`` 配置（缺省回退 120s 常量），
        该值不参与 absolute_max 派生。

        code-review dc28989fcfa8：能走到本判定即 judge_window 内有实质事件
        （零事件守卫先行放行），故区分「judge 通道故障」与「确认停滞」——
        首判为 stagnant 且 evidence 以 ``liveness judge unavailable`` 开头
        （超时/非零退出/输出不可解析/异常）时，以减半超时短重试一次，重试
        仍故障才按原 fail-closed 语义返回 stagnant；judge 正常给出的 stagnant
        verdict 属「确认停滞」，不重试。返回值结构与 evidence 格式不变。
        """
        timeout = self._supervision_judge_timeout()
        verdict = self._judge_liveness_once(snapshot, spec_name, run_id, timeout)
        evidence = str(verdict.get("evidence") or "")
        if verdict.get("verdict") != "stagnant" or not evidence.startswith(
            "liveness judge unavailable"
        ):
            return verdict
        # judge 通道故障 ≠ 确认停滞：短重试一次（超时减半，≥15s 下限）再 fail-closed
        self._pm.logger.warning(
            "agent_runner",
            f"Liveness judge unavailable for {spec_name or 'unknown'} ({run_id}), "
            f"retrying once with {max(15.0, timeout / 2.0):.0f}s timeout: "
            f"{evidence[:160]}",
        )
        return self._judge_liveness_once(
            snapshot, spec_name, run_id, max(15.0, timeout / 2.0)
        )

    def _judge_liveness_once(
        self, snapshot: dict, spec_name: str | None, run_id: str, timeout: float
    ) -> dict:
        """单次 judge 调用（_judge_liveness 的尝试单元，自身不重试）。"""
        prompt = (
            "你是长时运行 agent 的活性监督判定器。根据以下 run 流统计快照，判断该"
            " agent 是在真实推进任务，还是已陷入停滞（空转、卡死、重复循环、无输出）。\n\n"
            f"SPEC: {spec_name or 'unknown'}\nRUN: {run_id}\n\n快照：\n"
            f"{json.dumps(snapshot, ensure_ascii=False)}\n\n"
            "只输出一个 JSON 对象，不要其它文字：\n"
            '{"verdict": "advancing|stagnant", "evidence": "简短判定依据（<=200字）"}\n'
            "判定口径（fix-run-hang-amplification D1 修订）：\n"
            "1. 窗口内有持续的新工具调用与工具结果（实质事件）且在推进/产出新内容 → advancing；\n"
            "2. 窗口内无实质事件（substantive_events_in_window == 0）→ stagnant；\n"
            "3. 心跳（heartbeats_in_window）与 I/O 增长 MUST NOT 单独构成 advancing 的"
            "充分依据——持续产出心跳事件仅表明进程仍存活，不代表任务推进；\n"
            "4. 同参数工具调用反复失败、长时间无新输出 → stagnant。"
        )
        try:
            cmd = ["claude", "-p", prompt, "--output-format", "json"]
            model = self._pm._get_admin_model()
            if model:
                cmd += ["--model", model]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self._pm.project_root),
            )
            text = res.stdout or ""
            try:
                payload = json.loads(text)
                if isinstance(payload, dict) and payload.get("result"):
                    text = str(payload["result"])
            except json.JSONDecodeError:
                pass
            verdict = self._parse_verdict_json(text)
            if verdict:
                return {
                    "verdict": verdict["verdict"],
                    "evidence": str(verdict.get("evidence") or "")[:400],
                }
            return {
                "verdict": "stagnant",
                "evidence": (
                    f"liveness judge unavailable: unparseable output "
                    f"(rc={res.returncode}) {(res.stderr or '')[:160]}"
                ),
            }
        except Exception as e:
            return {"verdict": "stagnant", "evidence": f"liveness judge unavailable: {e}"}

    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        """从模型输出中提取 ``{"verdict": ...}`` JSON 对象；找不到返回 None。"""
        if not text:
            return None
        start = text.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(obj, dict) and obj.get("verdict") in (
                            "advancing",
                            "stagnant",
                        ):
                            return obj
                        break
            start = text.find("{", start + 1)
        return None

    def _supervision_judge_timeout(self) -> float:
        """活性判定 judge 子进程超时（per-agent-timeout-override 3.3）。

        读取 ``agents.timeout_overrides.supervision-judge``（缺省回退 120 秒常量），
        该值不参与 absolute_max 派生。
        """
        from core.config import ConfigLoader

        return ConfigLoader.judge_timeout_seconds(self._pm.config)

    def _supervision_settings(self) -> dict:
        """超时监督配置（D3）：canonical ``agents.timeout_supervision``，回退旧顶层键。

        缺省取 SUPERVISION_DEFAULTS（enabled=true）；旧版顶层 ``timeout_supervision``
        （fix-stuck-threshold-unify 引入，enabled=false）作为回退开关仍然生效。
        """
        cfg = dict(SUPERVISION_DEFAULTS)
        sup = self._pm._get_config("agents.timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = self._pm._get_config("timeout_supervision", None)
        if not isinstance(sup, dict):
            sup = {}
        for key, default in cfg.items():
            value = sup.get(key)
            if value is None:
                continue
            if isinstance(default, bool):
                cfg[key] = bool(value)
                continue
            try:
                cfg[key] = type(default)(value)
            except (TypeError, ValueError):
                self._pm.logger.warning(
                    "agent_runner",
                    f"Invalid timeout_supervision.{key}={value!r} — keeping default " f"{default}",
                )
        return cfg

    def _output_zero_growth_seconds(self, task_id: str, size, now: float, mtime) -> float | None:
        """跨采样记忆输出文件 size，返回已零增长秒数（1.5）。

        - size/mtime 不可观测（无行路径/不可读）→ 返回 None 并移除追踪
          （「不可观测」情形 MUST NOT 短路，调用方据此走 LLM 路径）；
        - 首次观测：以文件 mtime（最后一次写入时刻）作为已知最后变化时点；
        - 后续采样：size 未变 → 零增长从上次已确认的变化时点继续；size 变化
          → 刚发生过产出，零增长重置为本采样时刻；
        - 若 mtime 晚于 know 的最后变化时点（文件被 touch 但 size 未变），
          以 mtime 为准（文件被写过即视为有产出信号）。
        """
        if size is None or mtime is None:
            self._output_tracking.pop(task_id, None)
            return None
        prev = self._output_tracking.get(task_id)
        zero_since = mtime
        if prev is not None:
            if prev.get("last_size") == size and prev.get("last_change") is not None:
                zero_since = prev["last_change"]
            elif prev.get("last_size") != size:
                zero_since = now  # size 变化 → 产出刚发生，重置零增长起点
            if mtime > zero_since:
                zero_since = mtime
        self._output_tracking[task_id] = {
            "last_size": size,
            "last_change": zero_since,
        }
        return max(0.0, now - zero_since)

    def _zero_output_assessment(
        self, run_file: Path, snapshot: dict, window_seconds: float, now: float | None = None
    ) -> "str | None":
        """「可观测零产出」确定性短路判定（fix-run-hang-amplification 1.4/1.5）。

        仅当以下三者**同时**成立时返回判定证据文本（调用方直接 kill、MUST NOT
        调用 judge LLM）：
          1. 窗口内被阻塞等待的后台调用时长 ≥ ``HANG_BLOCKED_CALL_SECONDS``；
          2. 该后台调用关联的输出文件**可观测**且大小零增长 ≥
             ``HANG_ZERO_GROWTH_WINDOW_SECONDS``（跨采样记忆判定）；
          3. 窗口内 ``tool_completions_in_window`` < ``HANG_MIN_TOOL_COMPLETIONS``。

        任一条件不成立（尤其输出文件不可观测）→ 返回 None（走既有 LLM 判定路径）。
        本判定基于「被等待的子进程」的可观测信号，不依赖转录形态——纯转录启发式
        分不清「挂起」与「合法慢」（design Context 方法论结论）。
        """
        now = time.time() if now is None else now
        if snapshot.get("tool_completions_in_window", 0) >= HANG_MIN_TOOL_COMPLETIONS:
            return None
        calls = snapshot.get("background_calls") or {}
        if not calls:
            return None
        for task_id, call in calls.items():
            output_file = call.get("output_file")
            started_at = call.get("started_at")
            if not output_file or started_at is None:
                continue  # 找不到关联输出文件 → 不可观测，不得短路
            try:
                blocked_seconds = now - float(started_at)
            except (TypeError, ValueError):
                continue
            if blocked_seconds < HANG_BLOCKED_CALL_SECONDS:
                continue
            path = Path(output_file)
            size = None
            mtime = None
            try:
                if path.is_file():
                    st = path.stat()
                    size = st.st_size
                    mtime = st.st_mtime
            except OSError:
                size = None
            zero_growth = self._output_zero_growth_seconds(task_id, size, now, mtime)
            if zero_growth is None or zero_growth < HANG_ZERO_GROWTH_WINDOW_SECONDS:
                continue
            return (
                f"heuristic zero-output: blocked task '{task_id}' "
                f"{int(blocked_seconds)}s watching '{output_file}' "
                f"(size={size}B), zero growth >= {int(zero_growth)}s, "
                f"tool_completions_in_window={snapshot.get('tool_completions_in_window')}"
            )
        return None

    def _supervision_deadline_action(
        self,
        run_file: Path,
        spec_name: str | None,
        run_id: str,
        started_at: float,
        extensions_used: int,
        judge=None,
        agent_type: str | None = None,
    ) -> dict:
        """deadline 到点后的监督决策（D3）：续期 or 终止，封闭矩阵。

        判定顺序（先硬上限后活性）：
          1. supervision 未启用 → 纯墙钟终止（现状行为）；
          2. 总墙钟 ≥ absolute_max_seconds（不低于 run_timeout + 续期总额，
             保证续期预算完整可用）→ 无条件终止；
          3. 已用满 max_extensions → 终止；
          4. judge_window 内零事件 → 跳过 LLM、直接判停滞终止；
          5. LLM 判定 advancing → 续期 extension_seconds；
          6. LLM 判定 stagnant（含 judge 不可用）→ 终止并保留证据。

        Returns: {"action": "extend"|"kill", "reason", "extension_seconds"?,
                  "extension_index"?, "evidence", "settings"}
        """
        sup = self._supervision_settings()
        evidence = ""
        if not sup["enabled"]:
            return {
                "action": "kill",
                "reason": "run timeout reached (supervision disabled)",
                "evidence": evidence,
                "settings": sup,
            }
        # per-agent-timeout-override 3.2：supervision 的 extension 总额与 absolute_max
        # 护栏按该 agent type 的生效超时派生（覆盖值参与），stuck 阈值派生保持全局默认
        # 值语义（见 effective_stuck_threshold_seconds，不随覆盖变化）。
        # float(None) 容错（code-review item bd14491bfae6）：门面委托路径返回
        # None（runner 不可用/异常被吞后 ConfigLoader 回退亦失败）时，裸 float()
        # 抛 TypeError 会让本函数——监督循环主路径——整段崩溃并向上冒泡。回退
        # run_timeout 默认值（与 config.RUN_TIMEOUT_FALLBACK_SECONDS 同源语义）。
        try:
            run_timeout = float(self._pm._effective_run_timeout(agent_type))
        except (TypeError, ValueError):
            from core.config import RUN_TIMEOUT_FALLBACK_SECONDS as _RT_FALLBACK

            run_timeout = float(_RT_FALLBACK)
        max_extensions = max(0, int(sup["max_extensions"]))
        # ── 规模预检 higher 档 extension 上限调整（add-fast-track-scale-precheck）──
        # fast-track spec 标记 _fast_track_scale_tier == "higher" 时，extension
        # 预算提高 2 次（默认 max_extensions 2 -> 4），使大任务面 spec 获得
        # 更充足超时预算（9000 + 4×1800 = 16200s = 4.5h）。
        if agent_type == "fast-track" and spec_name:
            try:
                entry = self._pm.state_machine.read_one(spec_name) or {}
                if entry.get("_fast_track_scale_tier") == "higher":
                    max_extensions += 2
                    self._pm.logger.info(
                        "agent_runner",
                        f"fast-track higher tier: max_extensions "
                        f"increased to {max_extensions} for '{spec_name}'",
                    )
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner",
                    f"fast-track scale tier precheck failed for '{spec_name}' "
                    f"— keeping default max_extensions={max_extensions}: {e}",
                )
        extension_seconds = max(1.0, float(sup["extension_seconds"]))
        # absolute_max 是总墙钟上限；配置偏小时抬到派生下限，否则续期预算会被总上限
        # 截断（语义矛盾）。下限由单一派生函数给出（supervision-timeout-config-consistency）：
        # floor = 生效超时 + 续期预算 × extension_seconds，与 config 校验层共用同一
        # 实现，禁止此处手写常数。传入该 agent 的实际预算（含 fast-track higher 档
        # 加成），运行时数值与改造前逐位一致（基础档 18600s / higher 档 22200s）。
        from core.config import ConfigLoader

        cfg = getattr(self._pm, "config", None)
        if not isinstance(cfg, dict):
            # 测试/最小门面未暴露 config：以已解析的生效超时与监督设置回构最小配置，
            # 保证 supervision_floor 派生结果与门面 _effective_run_timeout 一致
            # （缺省语义下 floor = run_timeout + max_extensions × extension_seconds）。
            cfg = {"agents": {"run_timeout_seconds": run_timeout, "timeout_supervision": dict(sup)}}
        floor_absolute_max = ConfigLoader.supervision_floor(
            cfg,
            agent_type=agent_type,
            extension_budget=max_extensions,
        )
        if floor_absolute_max is None:
            # 防御：supervision 显式关闭时本函数在首个短路（sup["enabled"]）已返回，
            # 两处读同一配置段，正常不会到达；此处兜底按零续期预算派生，保证不早于
            # run_timeout 截断（不得在此重新手写续期公式）。
            floor_absolute_max = run_timeout
        configured_abs_max = float(sup["absolute_max_seconds"])
        absolute_max = max(configured_abs_max, floor_absolute_max)
        if configured_abs_max < floor_absolute_max:
            # per-agent-timeout-override 3.2：生效超时（覆盖后）抬高 absolute_max 兜底时
            # ERROR 留痕（守护配置告警），每次 deadline 判定至多几次（续期轮次有界）。
            self._pm.logger.error(
                "agent_runner",
                f"supervision absolute_max_seconds({int(configured_abs_max)}s) 低于 "
                f"生效超时 {int(run_timeout)}s + 续期总额 {int(max_extensions)}×"
                f"{int(extension_seconds)}s = {int(floor_absolute_max)}s，"
                f"按 {int(floor_absolute_max)}s 兜底生效（agent_type={agent_type or 'default'}）",
            )
        now = time.time()
        if now - started_at >= absolute_max:
            return {
                "action": "kill",
                "reason": (
                    f"absolute_max_seconds cap reached ({int(absolute_max)}s, "
                    f"extensions_used={extensions_used})"
                ),
                "evidence": evidence,
                "settings": sup,
            }
        if extensions_used >= max_extensions:
            return {
                "action": "kill",
                "reason": (f"extension budget exhausted " f"({extensions_used}/{max_extensions})"),
                "evidence": evidence,
                "settings": sup,
            }
        window = max(30.0, float(sup["judge_window"]))
        snapshot = self._liveness_snapshot(run_file, window)
        evidence = self._summarize_snapshot(snapshot)
        # 1.2 fix-run-hang-amplification：零事件守卫按**实质事件**判定——
        # ``events_in_window`` 现只计数实质事件（assistant/user 含 tool_result/result），
        # 心跳（tool_progress）不再计入进度证据，守卫不再被心跳恒久打穿。
        if (
            not snapshot.get("stream_available")
            or snapshot.get("last_event_age") is None
            or snapshot["last_event_age"] > window
            or snapshot.get("events_in_window", 0) == 0
        ):
            return {
                "action": "kill",
                "reason": "stagnant: zero substantive run events within judge window",
                "evidence": evidence,
                "settings": sup,
            }
        # 1.4/1.5/1.7「可观测零产出」确定性短路：三条件同时成立 → 直接 kill，
        # MUST NOT 调用 judge LLM。证据标注为启发式「零产出」判定（含输出文件
        # 路径与零增长区间），并写入被监督 run 的 jsonl 供审计。
        zero_output = self._zero_output_assessment(run_file, snapshot, window, now)
        if zero_output:
            try:
                append_run_line(
                    run_file,
                    {
                        "type": "liveness_shortcut",
                        "kind": "zero_output_heuristic",
                        "evidence": zero_output,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except OSError as e:  # pragma: no cover - 留痕失败不得中断 kill 决策收口
                self._pm.logger.warning(
                    "agent_runner",
                    f"Failed to append zero_output_heuristic marker to {run_file}: {e}",
                )
            self._pm.logger.warning(
                "agent_runner",
                f"Liveness shortcut (heuristic zero-output) for {spec_name or 'unknown'} "
                f"({run_id}): {zero_output}",
            )
            return {
                "action": "kill",
                "reason": f"stagnant: {zero_output}",
                "evidence": evidence + " | " + zero_output,
                "settings": sup,
            }
        verdict = (judge or self._judge_liveness)(snapshot, spec_name, run_id)
        if verdict.get("verdict") == "advancing":
            return {
                "action": "extend",
                "extension_seconds": extension_seconds,
                "extension_index": extensions_used + 1,
                "reason": "judged advancing",
                "evidence": str(verdict.get("evidence") or "")[:400],
                "settings": sup,
            }
        return {
            "action": "kill",
            "reason": "judged stagnant",
            "evidence": str(verdict.get("evidence") or "")[:400],
            "settings": sup,
        }

    def wait_for_running_agents(self, timeout: int = AGENT_TERMINATE_GRACE_SECONDS):
        """优雅退出时终止全部在跑 agent（terminate 流程），不再逐 agent 等待完成。

        fix-graceful-shutdown-agents：原实现每 agent 最多等待 timeout（300s）串行叠加，
        叠加 supervisor 固定 60s SIGKILL 窗口必触发 kill -9，丢失在跑 agent 的 run 结果。

        新流程（D5 并行终止）：
          1. 对所有在跑 agent 立即发 SIGTERM（不等待完成）；
          2. 同步向各自 run 文件追加 interrupted 标记（标记 daemon 侧已知中断，
             与"疑似崩溃"区分，且不影响已 finalize 的完成 run）；
          3. 统一等待 ≤ grace 缓冲窗口（默认 10s），让 claude 收尾；
          4. 窗口结束仍未退出的 agent 用 SIGKILL 兜底。

        总终止时长恒 ≲ grace，不随 agent 数量线性增长，确保 daemon 在 supervisor 60s
        窗口内退出。

        Args:
            timeout: 缓冲窗口秒数（子类/测试可覆写短值避免真实等待）。
        """
        grace = max(0, timeout)
        running = list(self._pm._running_agents.items())
        if not running:
            return

        # 第一步：统一 SIGTERM，并行通知所有在跑 agent 收尾
        for name, proc in running:
            try:
                proc.terminate()  # SIGTERM：让 claude 关会话/flush 输出
                self._pm.logger.info("agent_runner", f"Sent SIGTERM to running agent: {name}")
            except ProcessLookupError:
                # 进程已退出（竞态），标记清理后跳过
                self._pm._running_agents.pop(name, None)
            except Exception as e:  # pragma: no cover - 防御性
                self._pm.logger.warning("agent_runner", f"SIGTERM failed for agent {name}: {e}")

        # 第二步：同步写入 interrupted 标记。running 快照到写入之间 run 线程可能已
        # 并发收尾（SIGTERM 令 claude 快速退出 → run 线程 finally 段 join 后先 pop
        # 注册表、再落 result 终态），故写入前双重复核，已明确终结的 run 跳过标记
        # （docstring 承诺"不影响已 finalize 的完成 run"）；下游按末行口径判定
        # （_file_tail_is_terminal/classify_run），对已落终态的文件追加 interrupted
        # 会覆盖成功/失败语义。两重复核兜住的窗口：① 注册表成员复核兜住 pop 已做、
        # result 未落盘的收尾段；② 末行终态复核兜住 error 终态已落盘但 run 线程仍
        # 在 join、尚未 pop 的窗口。code-review item 183ded7b526a：两条顺序复核与
        # 追加之间存在第三类交错——复核通过后、追加前 run 线程仍可完成「pop 注册表
        # + 落 result」，daemon 追加的 interrupted 成为文件末行，成功 run 被判成
        # interrupted。故成员复核、末行复核、追加三步整体持 _run_finalize_lock，
        # 与 run 线程收尾的注册表 pop（runner.py finally 段）互斥：pop 只能发生在
        # 本临界区之前（复核必不通过 → 跳过标记）或之后（result 严格后于 pop 落盘，
        # 必排在标记之后 → 末行仍是 result），任意交错下 docstring 承诺都成立。
        # 仍存活的 agent 照常写标记（design D2：标记由 daemon 侧同步写入，不依赖
        # agent 优雅退出）。读线程以 append 模式单行写入，O_APPEND 原子追加不破坏
        # JSONL 结构。
        runs_dir = self._pm.project_root / ".fenix" / "runs"
        for name, _proc in running:
            run_file = runs_dir / f"{name}.jsonl"
            try:
                with self._pm._run_finalize_lock:
                    if name not in self._pm._running_agents:
                        continue
                    if _file_tail_is_terminal(run_file):
                        continue
                    append_run_line(
                        run_file,
                        {
                            "type": "interrupted",
                            "reason": "daemon shutdown",
                            "by": "agent_runner",
                        },
                    )
            except Exception as e:  # pragma: no cover - run 文件写入失败不影响退出
                self._pm.logger.warning(
                    "agent_runner", f"Failed to write interrupted marker for {name}: {e}"
                )

        # 第三步 + 第四步：统一缓冲窗口，窗口内未退出者 SIGKILL 兜底
        if grace > 0:
            deadline = time.time() + grace
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                # run 线程收尾会并发 pop（runner.py），先取快照避免迭代中 dict 变化
                alive = [n for n, p in list(self._pm._running_agents.items()) if p.poll() is None]
                if not alive:
                    break
                time.sleep(min(0.2, remaining))
            # 缓冲窗口结束仍未退出的，强制 SIGKILL（标记已写入，不依赖优雅退出）
            for name, proc in list(self._pm._running_agents.items()):
                if proc.poll() is None:
                    self._pm.logger.warning(
                        "agent_runner", f"Agent did not exit within {grace}s, SIGKILL: {name}"
                    )
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    except Exception as e:  # pragma: no cover - 防御性
                        self._pm.logger.warning("agent_runner", f"SIGKILL failed for {name}: {e}")
        else:
            # grace=0：直接 SIGKILL 兜底
            for name, proc in list(self._pm._running_agents.items()):
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

        # 收割所有子进程，避免僵尸进程
        for name, proc in list(self._pm._running_agents.items()):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            except Exception:  # pragma: no cover - 防御性
                pass
            self._pm._running_agents.pop(name, None)
