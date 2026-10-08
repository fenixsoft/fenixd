"""liveness.py — LivenessSupervisor：attempt 存活探测/活性快照/LLM 判活/超时监督/优雅等待（refactor-core-packages 阶段 3）。

状态同迁（design D3 规则 1）：_extension_baselines 随组件迁移；门面经 property 委托保持原路径可用。

"""

from pathlib import Path
# tool_result 事件识别单一真源（design D1：禁止在真源之外再次硬编码事件类型比较），
# 本模块经类内 staticmethod 别名委托复用（与 runner.py 同型），不保留本地副本。
from core.timelib import from_epoch
from core.agent_runner.latency import _entry_is_tool_result
from core.agent_runner.run_files import (
    append_run_line,
    run_spec_part,
    strip_run_id_suffixes,
)
from datetime import datetime, timezone
import json
import logging
import os
import signal
import subprocess
import time

# 本模块无 pm 依赖的模块级函数（如 sweep_runs_without_terminal_state）的失败
# 留痕通道：走裸 logging.getLogger（同 run_files.py archive_spec_runs 的
# code-review item 23e672c8f873 可观测口径），不经 pm.logger——启动清扫在
# AgentRunner 组件之外被 fenixd.py 直接调用，无门面可回引。
_logger = logging.getLogger("fenixd.agent_runner.liveness")

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
from core.proc_utils import guard_killpg  # noqa: E402
# 活性判定 LLM 单轮调用的超时秒数（D2）：judge 卡死不能拖住监督循环
JUDGE_TIMEOUT_SECONDS = 120
# 活性快照 last_output 片段截断字符数（D1）
LIVENESS_SNIPPET_CHARS = 400

# ── run 死亡归因结构化标记（code-review item 44703a4ffce6）────────────────
# 监督死亡判定点（_supervision_deadline_action）在每个 kill 决策上输出结构化
# ``death_kind``；run 终态错误文本组装时（runner 轮询环 timeout_error）经
# death_kind_marker 转成稳定机器标记 ``[death-kind:<kind>]`` 随文本透传
# （与 [signal-kill: …] 同一错误文本标记惯例）。消费端
# pm_engine/budget._is_exemptable_reason 优先读该标记判豁免、reason 关键词
# 匹配仅作历史数据回退——监督文案换词 / error 粘贴含关键词日志片段不再
# 静默翻转豁免口径。
# supervision = 监督主动终止（墙钟/续期用尽/停滞判死，确实消耗整份预算）；
# infra = 基础设施性终止（如监督流不可读的证据缺失，走豁免口径）。
DEATH_KIND_SUPERVISION = "supervision"
DEATH_KIND_INFRA = "infra"


def death_kind_marker(kind: str) -> str:
    """run 死亡归因结构化标记的单源格式（词表与 reason 文案演化解耦）。

    生产：runner 轮询环按 kill 决策携带的 ``death_kind`` 追加进终态错误文本；
    消费：budget._is_exemptable_reason 优先匹配该标记。
    """
    return f"[death-kind:{kind}]"

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
# 窗口起点位于行中间时首段是上一行的残段必须丢弃（起点前一字节恰为换行则首段
# 是完整一行，保留，code-review item b89929148e58）；末行不完整（窗口末字节非
# 换行 = 末行跨窗）或窗口内无完整行时回退全量逐行读。64KB 与
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
    起点位于行中间时首段是上一行残段必须丢弃（起点前一字节恰为换行 = 起点恰落
    行边界，首段是完整一行须保留，code-review item b89929148e58）；末行不完整
    （窗口末字节非换行 = 末行跨窗被截断）或窗口内无完整行时回退全量逐行读——
    回退方向保守，拿不准一律回退全量读。
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
            # 多读窗口起点前一字节（code-review item b89929148e58）：该字节是
            # 换行 ⇒ 起点恰落行边界，首段是完整一行不得误丢；非换行 ⇒ 首段是
            # 从上一行中间切入的残段，必须丢弃（对齐 admin_monitor
            # _run_terminal_status 的 item 190881dd0168 边界判定范式）。
            f.seek(-(_TAIL_READ_WINDOW + 1), 2)
            raw = f.read()
    except OSError:
        return False
    starts_mid_line = raw[:1] != b"\n"
    text = raw[1:].decode("utf-8", errors="replace")
    # 窗口末字节非换行 ⇒ 末行被窗口末端截断（末行超窗或正在写入），窗口内任何
    # 行都替代不了真实末行——若不回退，lines[-1] 是末行残段，JSON 解析失败会被
    # fail-open 成「非终态」，已终态 run 被误判存活一个监督周期。回退全量读
    # （append_run_line 保证每行以 \n 收尾，静止文件末字节必为换行）。
    if not text.endswith("\n"):
        return _last_line_is_terminal_full(run_file)
    segments = text.split("\n")
    if starts_mid_line:
        # 窗口首行是从字节窗口切入的上一行残段，必须丢弃（见 _read_run_lines 注释）
        segments = segments[1:]
    lines = [ln for ln in segments if ln.strip()]
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
    except OSError as e:
        # 扫描失败与「目录不存在」同返回 [] 且上游只汇报补写成功清单——失败路径
        # 零留痕会让悬空 run 静默等到运行期清扫器兜底（code-review item
        # 2ac8fc286ebf），记 WARNING 使该形态可观测（对齐 run_files.archive_spec_runs）。
        _logger.warning(
            "sweep_runs_without_terminal_state: 扫描 %s 失败（本轮零补写）: %s", runs_dir, e
        )
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
        except OSError as e:
            # 单文件补写失败不再静默 pass（同上 item 2ac8fc286ebf）：跳过该文件
            # 继续处理其余文件，WARNING 留痕——悬空 run 要等运行期清扫器
            # （≥1800s 流停 + 扫描周期）才被兜底，失败须可追溯。
            _logger.warning(
                "sweep_runs_without_terminal_state: 补写 %s 失败（跳过，留待运行期"
                "清扫兜底）: %s",
                run_file,
                e,
            )
            continue
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
        # 终态回收：_supervision_deadline_action 每轮判定清理已不在当前
        # background_calls 集合内的 task_id 条目（历史 run 残留）。
        self._output_tracking: dict = {}

    def sweep_dangling_runs(self) -> list:
        """运行期悬空 run 清扫（add-runtime-run-sweeper 1.3）：daemon 存活期间
        周期性（每轮 periodic scan）扫描 runs 目录，对满足三重判据（AND，缺一
        不扫、判据不过不打开读取）的 run 文件补写 interrupted 终态：

        ① run_id 不在 ``_running_agents`` 注册表（键 = 文件 stem，直接成员判定）
           —— 在飞保护，权威源；
        ② mtime 停更 ≥ ``RUNTIME_SWEEP_IDLE_SECONDS`` —— 流停保护，先行短路
           免读文件（任何存活写入者都会刷新 mtime）；
        ③ ``_file_has_terminal_event`` 为 False（锁外预判，见下方临界区注释）
           —— 全文件从未出现过终态事件
           （「全文件任一行」口径：历史上任一位置出现过终态即不补写，与
           ``_file_tail_is_terminal`` 的末行口径语义不同——如 result 之后追加
           superseded 的原地重试悬空文件，其尾部永久非终态，但按本口径不补写，
           读侧末行口径的在跑判定会持续把它当未终结 run，属已知的保守侧取舍）。

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
            # code-review c1dd6ddcdae0：planner 节流（runner._planner_throttle_acquire）
            # 以 base run_id 预生成 <run_id>.jsonl 并在等待期写心跳，attempt 启动后以
            # <run_id>-a1.jsonl 落盘并注册 _running_agents（键=attempt run_id），base
            # 文件自此无写入——其 stem 与注册表键不同形，仅 mtime 停更越阈就会被误补
            # interrupted。经 run_files.strip_run_id_suffixes（后缀剥离唯一解析
            # 来源，1.2 约束，与 _normalize_run_id 同口径）剥离 -a<n>/-r<n> 后缀，
            # 归一化后的 base 键命中注册表归一化键集合 → 该 run 仍存活，跳过补写
            # 与「悬空 run」告警。幂等：无后缀键归一后为自身，覆盖原精确成员判定。
            base_stem = strip_run_id_suffixes(stem)
            # 注册表会被 run 收尾线程并发 pop，先取快照避免迭代中 dict 变化
            if base_stem in {
                strip_run_id_suffixes(key)
                for key in list(self._pm._running_agents)
            }:
                continue
            # 判据 ②：流停保护，先行短路免读
            try:
                idle_seconds = int(now - run_file.stat().st_mtime)
            except OSError:
                continue
            if idle_seconds < RUNTIME_SWEEP_IDLE_SECONDS:
                continue
            # 判据 ③ 预判在锁外（code-review item 970e0bb113fd）：全文件逐行读
            # 对长转录（可达 MB 级）是慢操作，持 _run_finalize_lock 做全量扫描会
            # 显著延长临界区、阻塞正常收尾路径（runner.py finally 段的注册表
            # pop 需同一把锁才能弹出并落终态）。预判口径不变（仍是判据 ③ 的
            # 「全文件从未出现终态事件」，出现过 → 入缓存，后续轮次零读取）；
            # 锁内改做一次 _file_tail_is_terminal 尾读窗口短复核（64KB 有界），
            # 兜住预判与取锁之间收尾线程完成「pop → result 落盘」的窗口——
            # 末行已终态即让位既有收尾，不补写（防 interrupted 插到 result
            # 之后成为文件末行）。
            if _file_has_terminal_event(run_file):
                self._terminal_verified.add(stem)
                continue
            # 锁内成员复核 + 尾读短复核 + 补写整体持 _run_finalize_lock（code-review
            # item 7947bc50ea39）：runner.py finally 段的顺序是「pop 注册表（持
            # 本锁）→ run_metrics 追加 → result 终态落盘」，pop 之后、终态落盘
            # 之前注册表已无该键且文件 mtime 尚未刷新——若三判据与补写在锁外
            # 自由交错，interrupted 可追加到 result 之后成为文件末行，成功 run
            # 被读侧末行口径（classify_run/_file_tail_is_terminal）判成
            # interrupted（同 183ded7b526a 已修事故形态）。对齐
            # wait_for_running_agents 的临界区协议：若 run 线程尚未 pop，pop 被
            # 本锁挡到追加之后（其 result 严格后序，末行仍是 result）；若 pop
            # 已先行，锁内成员复核与终态复核使补写让位于既有收尾。锁内只做
            # 单文件终态短复核与追加，glob/mtime 与判据 ③ 全文件读等慢速扫描
            # 留在锁外，不与正常收尾路径长互斥。
            with self._pm._run_finalize_lock:
                # 成员复核（判据 ① 锁内重做）：判据 ① 快照取自锁外，取 snapshot
                # 到本临界区之间注册表可能已变化，以锁内快照为追加前的最终判据
                if base_stem in {
                    strip_run_id_suffixes(key)
                    for key in list(self._pm._running_agents)
                }:
                    continue
                # 锁内终态短复核（末行口径，尾读窗口有界读）：预判后、取锁前
                # 收尾线程可能已落 result/error 等终态，末行终态即让位
                if _file_tail_is_terminal(run_file):
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
        # code-review item f17a6512bf05：按本轮 glob 到的现存文件集合对缓存做
        # 差集修剪——run 产物会被保留清理（runs_retention_check）移入 archive/ 或
        # 删除，被清理文件的 stem 残留缓存只是语义噪音，daemon 数周不重启时集合
        # 无界累积。仅按 stem 字符串修剪，在飞文件（不入缓存）与刚入缓存的条目
        # 均在本轮 files 内、不受影响；若与并发 sweep 交错，最坏多读一轮文件，
        # 无正确性影响。
        self._terminal_verified &= {f.stem for f in files}
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
             （``worktrees/{impl,verify,repair}-<spec>-<ts>``）→ 存活；
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

        pgrep 二进制缺失（FileNotFoundError）时提前返回 False，由流新鲜度回退
        判定；单前缀瞬时故障（超时/OSError）只跳过该前缀继续扫描其余前缀，
        全部前缀均不可用时才落到底部 return False——不因单前缀瞬时超时把整体
        判定放大为漏扫。

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
        # 前缀集与 admin_monitor._pgrep_live_worktree 及 _stream_recent 对齐
        # （repair 与 orphaned-state-probe-calibration 1.4 同款）：repair 通道
        # worktree 目录名 repair-<spec>-<ts>（run_spec_part 经 RUN_ID_AGENT_PREFIXES
        # 识别 repair- 前缀，下方全等守卫照常生效）。repair claude 进程长工具执行
        # 期内可数分钟不写流，漏扫会让 has_live_attempt 误判无存活子进程，
        # auto-recovery / 孤儿 ready 白名单对仍在修复中的 spec 重置状态。
        for prefix in ("impl", "verify", "repair"):
            pattern = f"worktrees/{prefix}-{spec_name}-"
            try:
                res = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except FileNotFoundError:
                # pgrep 二进制缺失：其余前缀必然同样失败，提前返回 False，
                # 由 has_live_attempt 的流新鲜度回退判定（保留提前返回路径）
                return False
            except (subprocess.SubprocessError, OSError) as e:
                # 单前缀瞬时故障（如 timeout=5 超时）只跳过本前缀继续扫描其余
                # 车道，不放大为整体漏扫：repair claude 进程长工具执行期可数
                # 分钟不写流（见上方前缀集注释），impl 前缀一次瞬时超时即整体
                # return False 会让 has_live_attempt 对仍在修复中的 spec 误判
                # 无存活子进程，auto-recovery / 孤儿 ready 白名单随后重置状态。
                # 与 _stream_recent 的单前缀 glob 失败 continue 口径一致；全部
                # 前缀均失败自然落到函数末尾 return False。
                self._pm.logger.debug(
                    "agent_runner",
                    f"_pgrep_live_attempt scan failed for prefix '{prefix}' of "
                    f"'{spec_name}', skipping: {e}",
                )
                continue
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
        # code-review item 3348be8101c3：补入 planner-judge-/dispute-judge- 判官
        # 车道（与 _run_stream_alive 的 per-run 口径对齐）——判官范式不创建
        # worktree（cwd=主树），_pgrep_live_attempt 的 worktrees/ 前缀扫描天然
        # 扫不到判官进程，本流判据是判官 run 在飞的唯一兜底；两前缀均已在
        # run_files.RUN_ID_AGENT_PREFIXES 登记，下方 run_spec_part 全等守卫照常
        # 生效，防 spec 名互为前缀时误延期。
        for prefix in ("impl", "verify", "spec-review", "repair", "planner-judge", "dispute-judge"):
            try:
                paths = list(runs_dir.glob(f"{prefix}-{spec_name}-*.jsonl"))
            except OSError as e:
                # 单前缀 glob 失败（瞬时 I/O 异常）只跳过本前缀继续扫描其余车道，
                # 不短路整体判定：此处若 return False，impl 前缀一失败就跳过
                # 其余五个前缀的存活检查，has_live_attempt 对仍有存活子进程的
                # spec 误判「无存活 attempt」，调用方会重置状态（误判 False 比
                # 误判 True 更重）。与下方 p.stat() 的 OSError continue 口径
                # 一致；全部前缀均失败自然落到函数末尾 return False。
                self._pm.logger.debug(
                    "agent_runner",
                    f"_stream_recent glob failed for prefix '{prefix}' of "
                    f"'{spec_name}': {e}",
                )
                continue
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
        # 判据 2：进程表（in-process 注册表）为真相；判定异常记 WARNING 后
        # fail-open 继续判据 3（流文件判定），不落入判据 4 的 stale 终局——
        # 进程表读不出既不等于评审在飞，也不等于 run 已终态
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
            f"{from_epoch(new_deadline).isoformat()}",
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

        无时间戳的行（stderr 兜底行等）仅以文件 mtime 参与 in_window 窗口归属
        判定，stderr 兜底行不计入实质事件——纯 stderr 活跃流（mtime 新鲜）在
        _supervision_deadline_action 的零实质事件守卫下仍会被判停滞终止，这是
        预期语义：I/O 增长不算进展（fix-run-hang-amplification 口径），心跳 /
        兜底输出不构成「推进中」的证据。
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
        # 文件 mtime 循环外 stat 一次缓存（code-review 72341c32f432）：无时间戳行的
        # 窗口回退判定复用同一值，避免数千条 stderr 兜底行触发数千次冗余 stat 系统调用
        # （监督循环内反复执行会造成 I/O 放大）。
        try:
            file_mtime = run_file.stat().st_mtime
        except OSError:
            file_mtime = None
        try:
            # [fenix-ignore:bdf0d3a6d878] 全量口径被下游语义依赖：background_calls 须提取远早于判定窗口的 task_started（零产出短路按「长阻塞时长」判定，尾读窗口会破坏），total_events/tool_counts 亦进 judge 提示词；增量游标须处理任意 now 实参与文件截断回退，监督判死路径改动风险大于 info 级收益
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
                    # 事件是否落在判定窗口内（无时间戳回退缓存的文件 mtime）
                    if ts is None:
                        in_window = file_mtime is not None and file_mtime >= cutoff
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
                        # message 为非 dict 载荷（字符串/列表等真值）时不调 .get，
                        # 防 AttributeError 逸出被误归因为 run thread crashed
                        # （同 result_gate.py 的「转录损坏不抛异常」防御口径）。
                        msg = entry.get("message")
                        content = msg.get("content") if isinstance(msg, dict) else None
                        for block in content or []:
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
        # 先置 None（code-review item 241dd5ccd41c）：下方外层 except 兜底清场
        # 据此区分「Popen 自身失败（子进程组未建立，无可清理）」与「communicate
        # 等后置异常（start_new_session 子进程组已在跑，必须清场）」。
        proc: subprocess.Popen | None = None
        try:
            # 提示词经 stdin 管道传入（对齐 runner._run_claude 的约定）：argv
            # 全文驻留 /proc/<pid>/cmdline（同机用户可读 judge 上下文），且超长
            # prompt 受 ARG_MAX 约束会以 E2BIG 直接失败。"-p" 不带位置参数时
            # claude CLI 从 stdin 读提示词；Popen + communicate(input=) 写完即关
            # 写端并经 communicate 并发收发，超时/返回码/输出解析语义不变。
            # start_new_session=True（code-review item d916fd3aa78b）：judge 超时
            # 是预期路径（每轮 deadline 可触发，且 _judge_liveness 还会减半重试
            # 一次），裸 subprocess.run 超时只 SIGKILL 直接子进程，claude 派生的
            # node/shell 孙进程每次超时都残留为孤儿（与既往孤儿进程误报事故同
            # 形态）。经独立进程组启动，超时整组清场（下方 TimeoutExpired 分支），
            # 对齐 core/adjudication_narrative._kill_process_group 的同型实现。
            cmd = ["claude", "-p", "--output-format", "json"]
            model = self._pm._get_admin_model()
            if model:
                cmd += ["--model", model]
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self._pm.project_root),
                start_new_session=True,
            )
            try:
                res_stdout, res_stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                # 超时整组清场：先整组 SIGTERM 给短暂优雅窗口，未退再 SIGKILL
                # 整组，末尾收割直接子进程并弃管道——不留僵尸、不让逃出进程组
                # 的孙进程悬挂管道。击杀最后一跳经自保护守卫（add-killpg-
                # self-guard）：start_new_session 下 pgid==pid，组长 pid 直传
                # （resolve=False）；守卫拒绝（自身组/非正 pgid）与组已退出
                # 同样静默吞掉。
                guard_killpg(
                    proc.pid,
                    signal.SIGTERM,
                    caller="liveness._judge_liveness_once",
                    resolve=False,
                )
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    guard_killpg(
                        proc.pid,
                        signal.SIGKILL,
                        caller="liveness._judge_liveness_once",
                        resolve=False,
                    )
                try:
                    proc.wait(timeout=10)  # 收割 SIGKILL 后的子进程，不留僵尸
                except subprocess.TimeoutExpired:
                    pass
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:  # noqa: BLE001 — 清扫路径绝不抛出
                        pass
                return {
                    "verdict": "stagnant",
                    "evidence": (
                        f"liveness judge unavailable: judge timed out after "
                        f"{timeout}s (claude process group terminated)"
                    ),
                }
            text = res_stdout or ""
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
                    f"(rc={proc.returncode}) {(res_stderr or '')[:160]}"
                ),
            }
        except Exception as e:
            # code-review item 241dd5ccd41c：非超时异常路径的兜底清场。上方
            # TimeoutExpired 分支有整组清场，但 communicate 抛非超时异常（如
            # 管道 OSError）时 judge 已由 start_new_session 独立成组——不补
            # 击杀会让整组 claude 进程无监督继续运行并消耗 LLM 配额，且 proc
            # 永不被 wait（僵尸）。与超时分支同型的兜底：SIGKILL 整组 + 有界
            # wait 收割 + 关管道，清扫路径失败一律静默吞掉，stagnant 证据
            # 语义不变。
            if proc is not None:
                try:
                    guard_killpg(
                        proc.pid,
                        signal.SIGKILL,
                        caller="liveness._judge_liveness_once",
                        resolve=False,
                    )
                except Exception:  # noqa: BLE001 — 清扫路径绝不抛出
                    pass
                try:
                    proc.wait(timeout=5)  # 收割直接子进程，不留僵尸
                except Exception:  # noqa: BLE001 — 清扫路径绝不抛出
                    pass
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except Exception:  # noqa: BLE001 — 清扫路径绝不抛出
                        pass
            return {"verdict": "stagnant", "evidence": f"liveness judge unavailable: {e}"}

    @staticmethod
    def _parse_verdict_json(text: str) -> dict | None:
        """从模型输出中提取 ``{"verdict": ...}`` JSON 对象；找不到返回 None。

        code-review d5b753a6d878：边界定位改用 ``json.JSONDecoder.raw_decode``
        从每个 ``{`` 起点尝试完整解析，不做裸括号深度计数——深度计数不感知
        字符串字面量，合法 JSON 的 evidence 文本含不成对 ``{``/``}``（如
        「Step {1 of 2」）时深度无法归零或切出非法子串，json.loads 失败被整体
        判为「judge 输出不可解析」，触发 judge 通道减半重试后 fail-closed 返回
        stagnant，误杀实际 advancing 的 run。raw_decode 由 JSON 词法器处理字符串
        转义，字面量内括号不影响对象边界；起点处非合法 JSON（真残缺输出）→
        换下一起点，全部失败返回 None（原提取语义不变）。
        """
        if not text:
            return None
        decoder = json.JSONDecoder()
        start = text.find("{")
        while start != -1:
            try:
                obj, _end = decoder.raw_decode(text, start)
            except json.JSONDecodeError:
                start = text.find("{", start + 1)
                continue
            if isinstance(obj, dict) and obj.get("verdict") in (
                "advancing",
                "stagnant",
            ):
                return obj
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
                # enabled 等 bool 键严格归一（对齐 ConfigLoader._supervision_settings
                # 的同名归一，code-review item 6b032f4596e5）：bool(value) 会把
                # 引号串 "false" 判 True（监督被静默保持开启且无日志线索）、把
                # 0 判禁用而校验层判启用——同一段配置两口径结论相反。非 bool 打
                # WARNING 回退缺省，与 config 层口径一致。
                if isinstance(value, bool):
                    cfg[key] = value
                else:
                    self._pm.logger.warning(
                        "agent_runner",
                        f"Invalid timeout_supervision.{key}={value!r} — keeping default "
                        f"{default}",
                    )
                    cfg[key] = default
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
        self, snapshot: dict, now: float | None = None
    ) -> "str | None":
        """「可观测零产出」确定性短路判定（fix-run-hang-amplification 1.4/1.5）。

        仅当以下三者**同时**成立时返回判定证据文本（调用方直接 kill、MUST NOT
        调用 judge LLM）：
          1. 窗口内被阻塞等待的后台调用时长 ≥ ``HANG_BLOCKED_CALL_SECONDS``；
          2. 该后台调用关联的输出文件**可观测**且大小零增长 ≥
             ``HANG_ZERO_GROWTH_WINDOW_SECONDS``（跨采样记忆判定）；
          3. 窗口内 ``tool_completions_in_window`` < ``HANG_MIN_TOOL_COMPLETIONS``。

        code-review item 5b1eb553f47c：``background_calls`` 只由 task_started /
        TaskOutput 事件写入，全仓无后台任务完成事件的消费点（完成态不可建立），
        故补第 4 道守卫——仅当 ``started_at`` 与输出文件 mtime **同落当前判定
        窗口**（``snapshot["window_seconds"]``）内才参与短路；否则视为已完成的
        历史后台调用（其「阻塞时长」只是墙钟年龄、输出零增长只是文件定型），
        不得据此误杀进入合法低频工具阶段（收尾写总结、长分析等：窗口内有实质
        事件但完成数 < 3）的 run。

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
        # 判定窗口不可知（snapshot 非经 _liveness_snapshot 构造）→ 下方同窗校验
        # 无从建立，MUST NOT 短路（回退 LLM 判定路径，fail-open 不误杀）。
        try:
            window_seconds = float(snapshot.get("window_seconds") or 0.0)
        except (TypeError, ValueError):
            window_seconds = 0.0
        if window_seconds <= 0:
            return None
        window_cutoff = now - window_seconds
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
            # item 5b1eb553f47c 同窗校验（一）：started_at 落在当前判定窗口之外
            # → 历史后台调用（大概率早已完成），不参与短路。
            if started_at < window_cutoff:
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
            # item 5b1eb553f47c 同窗校验（二）：输出文件 mtime 亦须落在当前判定
            # 窗口内——早已定型的历史输出文件满足「零增长」只说明任务已结束，
            # 不说明本 run 仍被其阻塞。
            if mtime is not None and mtime < window_cutoff:
                continue
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
        *,
        remaining_tasks: int | None = None,
        impl_scale: int | None = None,
        turn_count: int | None = None,
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

        evo-add-impl-wallclock-budget-sizing 2.1：``remaining_tasks``（剩余
        未勾选任务数，调用点由 runner 经 parse_tasks_md 同源取数传入）与
        ``impl_scale``（run 启动点总规模分，estimate_spec_scale 单点）为
        纯观测/档位入参，均不新增/改写本矩阵的判定分支——remaining_tasks
        只随 extend/kill evidence 与返回字段携带供复盘归因；impl_scale 只
        参与下方 impl 车道档位抬升（幂等入参，禁止以 remaining_tasks 回算）。
        两参缺省 None（门面委托/既有直调兼容），None 等价「不抬升、观测
        unavailable」，行为与引入前逐位一致。

        evo-add-admin-run-wrapup-contract 1.2：``turn_count``（assistant 轮次
        计数，调用点从轮询环 turn_count[0] 传入）只作收尾宽限的折算入参——
        「宽限轮数 × 近期平均每轮墙钟（elapsed/turn_count）」；缺省 None 时
        以 extension_seconds 作每轮代理口径。仅消费于 max_extensions 用满
        分支的一次性收尾宽限发放（见下方该分支注记）。

        Returns: {"action": "extend"|"kill", "reason", "extension_seconds"?,
                  "extension_index"?, "evidence", "settings", "remaining_tasks"}
        """
        sup = self._supervision_settings()
        evidence = ""

        def _annotated(ev: str) -> str:
            # 剩余工作量观测（evo-add-impl-wallclock-budget-sizing 2.1）：
            # extend/kill evidence 统一携带 remaining_tasks（与轮数路径
            # _turn_limit_action 的 _annotated 同型）；只进 evidence/返回
            # 字段、不进 reason——budget._is_exemptable_reason 按 reason
            # 子串匹配豁免口径（"extension budget exhausted" 仍不可豁免），
            # reason 文案改动会误改豁免判定。
            parts = [ev] if ev else []
            parts.append(
                "remaining_tasks="
                + ("unavailable" if remaining_tasks is None
                   else str(remaining_tasks)))
            return " | ".join(parts)

        if not sup["enabled"]:
            return {
                "action": "kill",
                "death_kind": DEATH_KIND_SUPERVISION,
                "reason": "run timeout reached (supervision disabled)",
                "evidence": _annotated(evidence),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
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
        # ── impl 车道墙钟预算 sizing（evo-add-impl-wallclock-budget-sizing 1.2）──
        # 泛化上方 fast-track higher 档先例到 implementer 车道：按 run 启动
        # 同源总规模（estimate_spec_scale 单点，runner 在 run 启动点一次解析
        # 后经 impl_scale 传入）抬升续期预算 max_extensions。生效序（对齐
        # _impl_turn_budget 的 override > 推算 > base）：STATE 覆盖键
        # impl_wallclock_extension_override（正整数，只抬不压）> 规模推算
        # （lifted_max_extensions_for_scale，enabled 门控）> base。逐 deadline
        # 判定的档位推导幂等——impl_scale 为同一入参，MUST NOT 以
        # remaining_tasks 回算（剩余数随推进递减，逐次重算会回撤已抬档位，
        # 使 extensions_used ≥ 回撤后 max_extensions 触发伪击杀）。
        # impl_scale=None（非实现车道/解析回退/既有直调）不抬升，行为与引入
        # 前逐位一致。absolute_max_seconds 封顶语义不变：sizing 只扩续期预算，
        # 下方 floor 派生传抬升后的实际预算（与 fast-track 加成同机制协同）。
        if agent_type == "implementer" and spec_name:
            try:
                from core.fast_track_result import (
                    get_impl_wallclock_sizing_config,
                    lifted_max_extensions_for_scale,
                )
                _wc_cfg = get_impl_wallclock_sizing_config(
                    getattr(self._pm, "config", None))
                _wc_override = None
                _ov_fn = getattr(
                    self._pm, "_impl_wallclock_extension_override", None)
                if callable(_ov_fn):
                    _wc_override = _ov_fn(spec_name)
                if _wc_override is not None:
                    _wc_target = max(max_extensions, int(_wc_override))
                elif _wc_cfg.get("enabled") and impl_scale is not None:
                    _wc_target = lifted_max_extensions_for_scale(
                        max_extensions, int(impl_scale), _wc_cfg)
                else:
                    _wc_target = max_extensions
                if _wc_target != max_extensions:
                    max_extensions = _wc_target
                    self._pm.logger.info(
                        "agent_runner",
                        f"impl wallclock sizing: max_extensions "
                        f"increased to {max_extensions} for '{spec_name}' "
                        f"(override={_wc_override}, scale={impl_scale})",
                    )
            except Exception as e:
                self._pm.logger.warning(
                    "agent_runner",
                    f"impl wallclock sizing failed for '{spec_name}' "
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
        # ── 已发放收尾宽限的 absolute_max 一次性抬升（1.2）────────────────
        # 发放的宽限窗口必须真实可用：floor 派生下 max_extensions 用满点已
        # 贴近 absolute_max，若不抬升，branch 2（总墙钟上限）会在下一次
        # deadline 判定把宽限窗口整体截断，墙钟侧宽限形同虚设。抬升量 =
        # 已发放宽限秒数（随发放标记落共享状态 _turn_branch_state[run_id]
        # 的 wrapup_grace_seconds；无标记/读不到即 0——既有 run 逐位不变）。
        # 总墙钟仍有界：absolute_max + 一次性宽限，无周期性续抬入口
        #（发放标记防重复，同一 run 至多抬一次）。
        _grace_state_entry = getattr(self._pm, "_wrapup_grace_state_entry", None)
        if callable(_grace_state_entry):
            try:
                _grace_lift = float(
                    (_grace_state_entry(run_id) or {}).get(
                        "wrapup_grace_seconds") or 0.0)
            except Exception as e:
                # 容错口径与上方 fast-track 预检/impl wallclock sizing 对齐
                #（code-review item 3bc2f44ed013）：门面异常全捕降级为 0，
                # 不让替身缺属性/配置段结构异常等沿监督判定主路径向上冒泡
                self._pm.logger.warning(
                    "agent_runner",
                    f"wrapup grace state entry read failed for run "
                    f"'{run_id}' — keeping absolute_max unchanged: {e}",
                )
                _grace_lift = 0.0
            if _grace_lift > 0:
                absolute_max += _grace_lift
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
                "death_kind": DEATH_KIND_SUPERVISION,
                "reason": (
                    f"absolute_max_seconds cap reached ({int(absolute_max)}s, "
                    f"extensions_used={extensions_used})"
                ),
                "evidence": _annotated(evidence),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        if extensions_used >= max_extensions:
            # ── 一次性收尾宽限（evo-add-admin-run-wrapup-contract 1.2）──
            # 墙钟末次扩容点：非实现车道且 run 内自建任务全部 completed 的
            # run，先于既有击杀发放一次性收尾宽限——与轮数侧共用同一配置
            # 开关键（agents.wrapup_grace）与「是否已发放」状态（标记落
            # runner._wrapup_grace_state_entry 单点）。发放量按秒折算：
            # 宽限轮数 × 该 run 近期平均每轮墙钟（elapsed/turn_count；
            # turn_count 不可用以 extension_seconds 作每轮代理），clamp 见
            # WRAPUP_GRACE_MIN/MAX_SECONDS。发放经门面单点
            # _wrapup_grace_grant；门面不可用（最小门面/测试替身缺方法）
            # 或发放条件不满足 → 走既有击杀路径，行为与引入前逐位一致。
            # reason/evidence 语义：发放走 extend（reason 新文案不进豁免
            # 判定）；未发放的 kill reason 串逐字保留 "extension budget
            # exhausted" 子串（budget.py _is_exemptable_reason 按子串匹配
            # 判不可豁免，evo-add-impl-wallclock-budget-sizing 决策 5 复核
            # 口径）；宽限观测只进 evidence。
            _grace_seconds = None
            _grant_fn = getattr(self._pm, "_wrapup_grace_grant", None)
            if callable(_grant_fn):
                try:
                    _avg_turn = (
                        (now - started_at) / turn_count
                        if turn_count else extension_seconds)
                    _grant = _grant_fn(
                        agent_type, run_id, run_file, spec_name,
                        avg_turn_seconds=_avg_turn)
                    if isinstance(_grant, dict) and _grant.get("seconds"):
                        _grace_seconds = float(_grant["seconds"])
                except Exception as e:
                    # 容错口径与同函数 fast-track 预检/impl wallclock sizing
                    # 对齐（code-review item 3bc2f44ed013）：门面异常全捕并
                    # WARNING 留痕，_grace_seconds=None 落既有击杀路径
                    #（注释承诺的「门面不可用 → 走既有击杀路径」对任意异常
                    # 类型成立），不让非数值类异常沿监督主路径冒泡。
                    self._pm.logger.warning(
                        "agent_runner",
                        f"wrapup grace grant facade failed for "
                        f"'{spec_name or 'unknown'}' ({run_id}) — falling "
                        f"back to existing kill path: {e}",
                    )
                    _grace_seconds = None
            if _grace_seconds and _grace_seconds > 0:
                return {
                    "action": "extend",
                    "extension_seconds": _grace_seconds,
                    "extension_index": extensions_used,
                    "reason": "wrapup grace granted (final wrap-up window)",
                    "evidence": _annotated(
                        f"wrapup_grace: one-time wrapup window "
                        f"{int(_grace_seconds)}s (lane '{agent_type}', "
                        f"run-created tasks all completed)"),
                    "settings": sup,
                    "remaining_tasks": remaining_tasks,
                }
            return {
                "action": "kill",
                "death_kind": DEATH_KIND_SUPERVISION,
                # reason 串原样保留 "extension budget exhausted" 子串
                # （budget.py _is_exemptable_reason 按子串匹配判不可豁免，
                # evo-add-impl-wallclock-budget-sizing 决策 5 复核口径）；
                # remaining_tasks 只进 evidence/返回字段。
                "reason": (f"extension budget exhausted " f"({extensions_used}/{max_extensions})"),
                "evidence": _annotated(evidence),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        window = max(30.0, float(sup["judge_window"]))
        snapshot = self._liveness_snapshot(run_file, window)
        if not snapshot.get("stream_available"):
            # code-review 709297545d7e：读取失败（OSError，如 fd 耗尽/权限抖动）可能
            # 只是瞬时不可读，与「窗口内零实质事件」的确认停滞是两回事——先重试一次
            # 快照，避免一次瞬时 I/O 抖动终止一个本可被判 advancing 续期的 run
            # （对齐 _line_is_terminal/_file_tail_is_terminal 的 fail-open 不误杀口径）。
            snapshot = self._liveness_snapshot(run_file, window)
        evidence = self._summarize_snapshot(snapshot)
        if not snapshot.get("stream_available"):
            # 重试仍不可读：证据缺失 ≠ 确认停滞，reason 不再冒用 stagnant 文案
            # （budget._is_exemptable_reason 按 "stagnant" 判不可豁免，读取失败属
            # 基础设施性证据缺失，走豁免口径），WARNING 留痕便于复盘定位真实根因。
            self._pm.logger.warning(
                "agent_runner",
                f"run stream unavailable after retry, killing {spec_name or 'unknown'} "
                f"({run_id}): {run_file}",
            )
            return {
                "action": "kill",
                "death_kind": DEATH_KIND_INFRA,
                "reason": "run stream unavailable: liveness snapshot unreadable after retry",
                "evidence": _annotated(evidence),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        # 后台调用追踪条目终态回收（code-review item 11679dc4d275）：
        # _output_tracking 只在 size/mtime 不可观测时 pop，后台调用正常完成
        # （输出文件定型、run 收尾）后其 task_id 条目永久留存，daemon 长生命
        # 周期下随历史 run 无界累积。借每轮监督判定机会，把已不在当前 run
        # background_calls 集合内的条目清掉（与 _extension_baselines 的流新鲜
        # 度自清理同思路）；_zero_output_assessment 只消费本 snapshot 的
        # background_calls，清理其不涉及的条目不影响本轮判定。
        _live_calls = snapshot.get("background_calls") or {}
        for _stale_task_id in [
            tid for tid in self._output_tracking if tid not in _live_calls
        ]:
            self._output_tracking.pop(_stale_task_id, None)
        # 1.2 fix-run-hang-amplification：零事件守卫按**实质事件**判定——
        # ``events_in_window`` 现只计数实质事件（assistant/user 含 tool_result/result），
        # 心跳（tool_progress）不再计入进度证据，守卫不再被心跳恒久打穿。
        if (
            snapshot.get("last_event_age") is None
            or snapshot["last_event_age"] > window
            or snapshot.get("events_in_window", 0) == 0
        ):
            return {
                "action": "kill",
                "death_kind": DEATH_KIND_SUPERVISION,
                "reason": "stagnant: zero substantive run events within judge window",
                "evidence": _annotated(evidence),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        # 1.4/1.5/1.7「可观测零产出」确定性短路：三条件同时成立 → 直接 kill，
        # MUST NOT 调用 judge LLM。证据标注为启发式「零产出」判定（含输出文件
        # 路径与零增长区间），并写入被监督 run 的 jsonl 供审计。
        zero_output = self._zero_output_assessment(snapshot, now)
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
                "death_kind": DEATH_KIND_SUPERVISION,
                "reason": f"stagnant: {zero_output}",
                "evidence": _annotated(evidence + " | " + zero_output),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        verdict = (judge or self._judge_liveness)(snapshot, spec_name, run_id)
        if verdict.get("verdict") == "advancing":
            return {
                "action": "extend",
                "extension_seconds": extension_seconds,
                "extension_index": extensions_used + 1,
                "reason": "judged advancing",
                "evidence": _annotated(str(verdict.get("evidence") or "")[:400]),
                "settings": sup,
                "remaining_tasks": remaining_tasks,
            }
        return {
            "action": "kill",
            "death_kind": DEATH_KIND_SUPERVISION,
            "reason": "judged stagnant",
            "evidence": _annotated(str(verdict.get("evidence") or "")[:400]),
            "settings": sup,
            "remaining_tasks": remaining_tasks,
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

        总终止时长有上界（≈ grace + 5s 收割上限），不随 agent 数量线性增长，
        确保 daemon 在 supervisor 60s 窗口内退出（code-review item
        f2b28f960fde：收尾收割循环对 D state 等不可中断进程的逐个等待受整体
        deadline 约束，不再 5s×N 无界叠加）。

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
                            # 与启动/运行期两处清扫的 interrupted 补写对齐：
                            # append_run_line 原样序列化不自动补时间戳，
                            # 下游按事件 timestamp 做时序/时效判定时不可缺位
                            "timestamp": datetime.now(timezone.utc).isoformat(),
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

        # 收割所有子进程，避免僵尸进程。code-review item f2b28f960fde：逐 agent
        # 串行 wait(timeout=5) 在 D state / 未随进程组退出的进程上可叠加 5N 秒，
        # 突破 grace 乃至 supervisor 60s SIGKILL 窗口——改为整体 deadline 有界
        # 等待（grace + 5s 上限），逐 agent 只等剩余额度；额度耗尽后不再等待，
        # 注册表照常 pop（残留进程的僵尸回收交由内核/init 兜底，不阻塞关闭）。
        harvest_deadline = time.time() + grace + 5
        for name, proc in list(self._pm._running_agents.items()):
            remaining = harvest_deadline - time.time()
            if remaining > 0:
                try:
                    proc.wait(timeout=min(5, remaining))
                except subprocess.TimeoutExpired:
                    pass
                except Exception:  # pragma: no cover - 防御性
                    pass
            self._pm._running_agents.pop(name, None)
