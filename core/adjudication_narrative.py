"""core.adjudication_narrative — 转人工裁决告警的四段式调查叙事（upgrade-narrative-to-investigation）。

裁决贵在及时：告警若不自解释，决策者每次「先找人问清楚」都在拉长冻结窗口。
本模块为告警生成人类可读的**四段式调查叙事**（发生了什么 / 调查结论 /
为什么需要你决策 / 决策选项），基于采集到的验证材料给出根因判断，让决策者
读完叙事即可裁决、无需再另行询问。

相对 add-adjudication-alert-narrative（三段白话转述）的升级（本 SPEC）：
- **调查能力**：验证族信号生成前按标准产物路径采集结构化验证材料
  （verification-report.md / report.json / verdict_stability.json /
  fail_history.json）注入 prompt【验证材料】段，指令从「翻译技术串」升级为
  「基于材料给出根因判断并引用具体证据」；
- **异步补叙**：告警以机械文案**立即落盘**（叙事零阻塞），落盘后后台生成，
  完成原子补写侧车 ``.fenix/admin_alerts_narrative/<alert_id>.json``（读侧
  按 alert_id 合并渲染）——admin_alerts.json 记录本体不可变，侧车承载补叙；
- **可靠性**：超时缺省 60→180s、至多 2 次尝试；连续失败熔断（3 次失败冷却
  1 小时，冷却期零调用，跳过的告警写终态侧车防「调查生成中」假态悬挂）。

接线点（覆盖全部桶 2 转人工裁决告警）：
- ``pm_engine._send_human_escalation_alert``（core/pm_engine/family.py）——全部
  ESCALATION 告警的共同写入口（预算耗尽/升级闸门/评审两族/judge 重跑上限/
  同因重派熔断/恢复期回调均汇聚于此）；
- 两个旁路 choices 附带点：``core/worktree_manager/mergeback.py`` 的
  build_artifact_paths_missing 与 ``core/agent_runner/token_budget.py`` 的
  token_budget。旁路点复用本模块，MUST NOT 各自内联第二套 prompt/生成逻辑。

设计契约（design D1-D5）：
- **纯增强**：叙事只经侧车补叙，description/evidence/recommended_action/
  choices/trigger 任一既有字段的结构化语义零感知（alert-resolve、闭环判定、
  Administrator 处置不受影响；人工已处置 handled 后补叙照常落盘——历史
  完整性优先）；
- **fail-open**：LLM 异常/超时/空输出/结构校验失败 → 告警已以机械文案落盘
  不受影响、logger.warning 留痕、写终态侧车，绝不抛出穿透发射链路——叙事
  是增强，不是门禁；
- **LLM 通道**：模块级注入点（:func:`set_channel`），生产=既有 claude -p spawn
  通道单发（禁传 ``--max-tokens-budget`` 类危险旗标），测试=假通道，测试 MUST
  NOT 真调网关；不直连网关 HTTP——避免第二套凭据/UA/代理面；
- **模型回退链**：``admin.narrative_model`` → ``admin.agent_model`` → 框架默认
  （两者皆空时不传 ``--model``，用 CLI/网关默认模型）；
- **配置口径**：pm_engine 既有口径 ``ConfigLoader.get_admin_config(config).get(...)``
  （先例 family.py:563）；MUST NOT 反向导入 dashboard data 层私有助手
  ``_cached_config_value``；热更新经 daemon 主循环 ``_maybe_reload_config``
  每轮刷新 ``self.config`` 生效（fenixd.py:865）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.proc_utils import guard_killpg
from core.signals import validate_scheduling_kick_spec

# 日志组件名（logger.warning(component, message) 口径）
COMPONENT = "adjudication_narrative"

# 四段固定段落标题（D3）：顺序固定。生成后机械校验齐全（且顺序不倒置），
# 缺失视为本次生成失败走兜底——旧三段输出判失败是故意的（三段输出意味着
# 模型没读到新指令，落机械文案比落半截调查更诚实）。
REQUIRED_SECTIONS: tuple = ("发生了什么", "调查结论", "为什么需要你决策", "决策选项")

# admin.narrative_timeout_seconds 缺省（与 ConfigLoader.get_admin_config 单源；
# 60→180：网关 stall 实测 p90≈55s、max≈188s，60s 把长尾全判死；异步化后超时
# 成本不再落在告警路径上，放宽无副作用）
DEFAULT_TIMEOUT_SECONDS = 180

# 验证族信号注册表（task 1.1「注册表内显式列出」）：这些信号的告警生成前
# 按标准产物路径采集【验证材料】。judge/verdict/verify/scenario 改道与闸门
# 族的判定依据全部沉淀在 spec 验证产物里（design D1 本证：调查结论所需事实
# ——验证报告、判定轮次、失败演进——都在标准产物里）；注册表外信号（评审族/
# 预算族/旁路信号等）无对应产物，段跳过、叙事按既有机械字段生成（兼容）。
VERIFY_FAMILY_SIGNALS = frozenset(
    {
        # judge 重跑/轮次上限族
        "judge_rerun_cap",
        "judge_round_rerun_cap",
        # 验证闸门与预算族
        "verify_fail_escalation",
        "verify_env_blocked",
        "verify_uniform_failure",
        "verify_redo_exhausted",
        "verify_contract_missing",
        # 判定（verdict）族
        "verdict_result_unreadable",
        "verdict_evidence_invalid",
        "verdict_dedup_resynthesis_exhausted",
        # 场景改道族
        "scenario_defect_reroute_exhausted",
        "scenario_defect_reroute_stoploss",
        # 无结论循环
        "inconclusive_loop",
    }
)

# 叙事生成前采集的【验证材料】总上下文预算（字符，task 1.1）：分段截断限制
# 提示注入面体量（design Risks「材料注入的提示注入面」）
_NARRATIVE_CONTEXT_MAX_CHARS = 16384

# 裸 stdlib 日志通道（同 core/config.py、core/code_review.py 等先例）：daemon
# Logger 往 "fenixd" 根日志器挂 handler，fenixd.* 子日志器记录随之落入 daemon
# 日志文件——供 default_channel 失败时留痕 CLI 侧真实报错（stderr 尾部）。
_logger = logging.getLogger("fenixd.adjudication_narrative")

# 失败留痕的 stderr 尾部截断长度（code-review 1692f5b23b83）
_STDERR_TAIL_CHARS = 500

# 叙事正文整体预算（字符，code-review d1ec8fd1687f）：_validate_structure 只校验
# 四段标题齐全且顺序不倒置、不约束总长——模型失控输出（或被提示注入诱导复述
# 上下文）会把超长文本原样写进侧车随告警落盘，拖累告警列表渲染与落盘体积。
# 按字符计而非 UTF-8 字节（同 hook_engine D6 审计截断口径），量级对齐仓库 8KB
# 惯例（regression.py _PROGRESS_TAIL_BYTES=8192）。
_NARRATIVE_MAX_CHARS = 8192

# 段省略标记（超预算段砍尾后附于段尾，同 hook_engine 截断先例形态）
_NARRATIVE_TRUNCATION_MARK = "\n…（截断）"

# 首段标题前前导文本的压缩标记（见 _clip_narrative）——其字符开销须与省略
# 标记一样参与单段预算预扣，否则四段全截断时整体可超 _NARRATIVE_MAX_CHARS
# （code-review 97f75ae0e759）
_NARRATIVE_LEADING_MARK = "…\n"
_LEADING_MARK_CHARS = len(_NARRATIVE_LEADING_MARK)

# 单段截断预算：整体预算均摊四段并预扣各省略标记开销，另预扣每截断段 1 字节
# 段界换行（保下一段标题行首锚定，见 _clip_narrative）与前导标记开销
# _LEADING_MARK_CHARS——截断后整体 ≤ _NARRATIVE_MAX_CHARS
_NARRATIVE_SECTION_MAX_CHARS = (
    _NARRATIVE_MAX_CHARS
    - (len(_NARRATIVE_TRUNCATION_MARK) + 1) * len(REQUIRED_SECTIONS)
    - _LEADING_MARK_CHARS
) // len(REQUIRED_SECTIONS)

# 单段验证材料预算：【验证材料】总预算均摊四产物段并预扣段头与截断标记开销
_MATERIAL_SECTION_MAX_CHARS = max(
    (_NARRATIVE_CONTEXT_MAX_CHARS - 256) // 4, 256
)

# 四段标题锚定正则（与 _validate_structure 同形态 ^##<空白><标题>，MULTILINE
# 逐行锚定）：截断分段边界用（随 REQUIRED_SECTIONS 单源更新）
_SECTION_HEAD_RE = re.compile(
    "^##[ \t]*(?:" + "|".join(re.escape(h) for h in REQUIRED_SECTIONS) + ")",
    re.MULTILINE,
)

# ── 侧车补叙（task 3.2）─────────────────────────────────

# 侧车目录（项目根相对）：admin_alerts.json 记录本体不可变，补叙/终态侧车
# 同构同目录，读侧按 alert_id 合并无差别消费（design D2）
SIDECAR_DIRNAME = "admin_alerts_narrative"

# 后台补叙至多尝试次数（task 3.2：2 次封顶防重试风暴，熔断器是第二道闸）
_MAX_ATTEMPTS = 2

# 2 次尝试全败的终态侧车文案（机械说明，model=null——失败告警 MUST NOT 以
# narrative_pending 悬挂「调查生成中」假态）
GENERATION_FAILED_TEXT = "调查未能生成（连续超时/生成失败，已放弃重试）。"

# 熔断生效期跳过生成的终态侧车文案
BREAKER_SKIP_TEXT = "调查未能生成（叙事连续失败熔断中，冷却期跳过生成）。"

# ── 连续失败熔断器（task 4.1，design D4）────────────────

# 连续失败阈值：达此值熔断生效
BREAKER_THRESHOLD = 3

# 熔断冷却窗口（秒）：1 小时，与 escalation_cooldown_minutes 缺省量级对齐
BREAKER_COOLDOWN_SECONDS = 3600

# claude 子进程 spawn 工作目录注入点（code-review 672decf84c0d）：生产=
# fenixd main() 装配通道时一并传项目根；未装配回退系统临时目录。
_project_root: Optional[str] = None

# LLM 通道签名：channel(prompt, model, timeout) -> str | None
# （返回 None 或抛异常均按失败兜底处理）。模块级注入点（D2）：生产不注入、
# 用缺省 claude -p 通道；测试注入假通道，MUST NOT 真调网关。锁保护读写——
# 告警发射点分布在 daemon 多个线程，注册/清理与调用并发安全。
_channel_lock = threading.Lock()
_channel: Optional[Callable[[str, Optional[str], float], Optional[str]]] = None

# 熔断器进程内状态（design D4：不持久化——daemon 重启即复位，可接受）。
# 锁保护：发射点分布在 daemon 多个线程。
_breaker_lock = threading.Lock()
_breaker_fail_streak = 0
_breaker_open_until = 0.0  # time.monotonic() 时刻；0=未熔断

# 在飞后台补叙线程登记（wait_pending_narrative 联编/测试等待用；线程结束
# 自摘——生产不调用等待函数，登记集不增长）
_active_lock = threading.Lock()
_active_threads: set = set()


def set_channel(channel: Optional[Callable[[str, Optional[str], float], Optional[str]]]) -> None:
    """注入 LLM 通道（生产不调用=用缺省 claude -p 单发通道；测试注入假通道）。"""
    global _channel
    with _channel_lock:
        _channel = channel


def reset_channel() -> None:
    """恢复缺省通道（测试收尾清理用）。"""
    set_channel(None)


def set_project_root(path: Optional[str]) -> None:
    """注入 claude 子进程 spawn 工作目录（生产=fenixd main() 装配通道时传项目根）。"""
    global _project_root
    with _channel_lock:
        _project_root = path


def reset_breaker() -> None:
    """复位熔断器状态（测试隔离用；生产进程内状态随失败/成功自然演进）。"""
    global _breaker_fail_streak, _breaker_open_until
    with _breaker_lock:
        _breaker_fail_streak = 0
        _breaker_open_until = 0.0


def wait_pending_narrative(timeout: float = 30.0) -> bool:
    """等待全部在飞后台补叙线程结束（联编/测试确定性等待用，生产不调用）。

    返回是否全部在超时内结束（True=无残留）。
    """
    deadline = time.monotonic() + timeout
    with _active_lock:
        threads = list(_active_threads)
    for t in threads:
        remaining = max(deadline - time.monotonic(), 0.0)
        t.join(remaining)
    with _active_lock:
        return len(_active_threads) == 0


def _stderr_tail(err: Optional[str]) -> str:
    """stderr 尾部截断摘录（≤_STDERR_TAIL_CHARS；空 stderr 返回空串）。"""
    text = (err or "").strip()
    return text[-_STDERR_TAIL_CHARS:] if text else ""


def _resolve_spawn_cwd() -> str:
    """claude 子进程工作目录：项目根优先，未装配回退系统临时目录。

    同 agent_runner 既有 spawn 口径（runner.py / maintenance_runs.py 均显式传
    cwd）——claude CLI 把 cwd 当工作目录解析项目 CLAUDE.md/settings/会话状态，
    不显式钉住则叙事上下文随 daemon 启动目录漂移；daemon 以裸进程从非项目
    目录（如 /）启动时继承目录还可能不受信/不可写（code-review 672decf84c0d）。
    """
    with _channel_lock:
        root = _project_root
    return str(root) if root else tempfile.gettempdir()


def _kill_process_group(proc: subprocess.Popen) -> None:
    """超时清扫：先对整组 SIGTERM 给短暂优雅窗口，未退再 SIGKILL 整组。

    子进程经 ``start_new_session=True`` 独立成组（pgid==pid），超时只杀直接
    子进程会留下派生的孙进程孤儿继续占端口/内存（同仓库有界 spawn 惯例：
    knowledge._kill_process_group、bin/test_for.py run_bounded、hook_engine、
    verify_contract）。killpg 失败（进程组已退出）静默吞掉；末尾弃管道收割
    直接子进程，不留僵尸、不让逃出进程组的孙进程悬挂管道
    （knowledge.py code-review 44d833e20470 教训）。

    SIGKILL 补刀不以直接子进程超时为前提（code-review item 72a90eb6cb2e，
    对齐 core/regression.py 同名实现）：无论直接子进程是否在窗口内退出，
    都探活整组（killpg(pgid, 0)），组内仍有成员（忽略 SIGTERM 的孙进程）
    即升级 SIGKILL 补刀。
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = None  # 进程组已不存在（直接子进程已消亡），仅剩管道清理尾巴
    # 击杀最后一跳经自保护守卫（add-killpg-self-guard）：pgid 已解析直传；
    # 守卫拒绝（自身组/非正 pgid）＝组不可投递，与组已不存在同样跳过探活补刀。
    if pgid is not None and not guard_killpg(
        pgid,
        signal.SIGTERM,
        caller="adjudication_narrative._kill_process_group",
        resolve=False,
    ):
        pgid = None
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # 直接子进程退出 ≠ 组内已清：探活整组，仍有成员（忽略 SIGTERM 的孙
    # 进程）则 SIGKILL 补刀；ProcessLookupError ＝ 组已清空，静默即可。
    # pgid 复用上方捕获的值——wait 收尸后 getpgid(proc.pid) 会因进程
    # 消失而失效。
    if pgid is not None:
        try:
            os.killpg(pgid, 0)
        except (ProcessLookupError, OSError):
            pgid = None  # 组已清空，无需 SIGKILL 补刀
        else:
            guard_killpg(
                pgid,
                signal.SIGKILL,
                caller="adjudication_narrative._kill_process_group",
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


def default_channel(prompt: str, model: Optional[str], timeout: float) -> Optional[str]:
    """生产 LLM 通道：既有 claude -p spawn 通道做一次非交互单发（D2）。

    - 提示词经 stdin 传入（同 agent_runner._run_agent 口径：不走 argv——
      argv 全文驻留 /proc/<pid>/cmdline，且单参数受 ARG_MAX 约束）；
    - 仅解析到模型时传 ``--model``；缺省（None）用 CLI/网关默认模型（即
      「框架默认」档）；
    - MUST NOT 传 ``--max-tokens-budget`` 类危险旗标（fenixd 实测 7/8 failed
      禁传项）；
    - 超时/子进程缺失/非零退出/空输出一律返回 None，失败语义由调用方统一
      fail-open 兜底（本函数不重试——尝试次数由调用方调度层保证）；
      非零退出/空输出时 stderr 尾部（≤500 字符）经模块 logger 留痕，CLI 侧
      真实报错（模型名非法、凭据失效、配额不足等）可诊断；
    - spawn 显式传 cwd（:func:`set_project_root` 注入的项目根，未装配回退
      系统临时目录），同 agent_runner 既有 spawn 口径——叙事生成上下文不随
      daemon 启动目录漂移；
    - 超时经独立进程组（``start_new_session=True``）先 SIGTERM 后 SIGKILL
      收整组（:func:`_kill_process_group`，同 knowledge.py 范式），不留派生
      孙进程孤儿。
    """
    cmd = ["claude", "-p"]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            cwd=_resolve_spawn_cwd(),
        )
    except OSError:
        return None
    try:
        out, err = proc.communicate(prompt, timeout=max(float(timeout), 1.0))
    except (subprocess.TimeoutExpired, OSError):
        _kill_process_group(proc)
        return None
    if proc.returncode != 0:
        tail = _stderr_tail(err)
        _logger.warning(
            "叙事 claude -p 非零退出（code=%s）：%s",
            proc.returncode,
            tail or "stderr 为空",
        )
        return None
    if not (out or "").strip():
        tail = _stderr_tail(err)
        if tail:
            _logger.warning("叙事 claude -p 输出为空，stderr 尾部：%s", tail)
        return None
    return out.strip()


def _get_channel() -> Optional[Callable[[str, Optional[str], float], Optional[str]]]:
    with _channel_lock:
        return _channel


def _ctx_get(ctx: Any, name: str, default: Any = None) -> Any:
    """宿主侧上下文取值：映射键与属性两种形态统一（pm_engine / WorktreeManager /
    显式 dict 三类调用方）。"""
    if isinstance(ctx, dict):
        return ctx.get(name, default)
    return getattr(ctx, name, default)


def _warn(ctx: Any, message: str) -> None:
    """fail-open 留痕：宿主 logger.warning（缺 logger 时静默，绝不抛出）。"""
    logger = _ctx_get(ctx, "logger")
    if logger is None:
        return
    try:
        logger.warning(COMPONENT, message)
    except Exception:
        pass


def _resolve_admin_config(ctx: Any) -> Dict[str, Any]:
    """按 pm_engine 既有口径读 admin 段（先例 family.py:563）。

    ctx 自带 config（pm_engine.config）时直接用；旁路宿主（如 WorktreeManager）
    无 config 属性时从 ``<project_root>/.fenix/config.yaml`` fail-open 现读。
    读取经 ``ConfigLoader.get_admin_config``（含 narrative_* 三键的类型归一），
    任何异常回空 dict（= 全缺省 + 开关缺省 true）。
    """
    try:
        from core.config import ConfigLoader

        config = _ctx_get(ctx, "config")
        if config is None:
            project_root = _ctx_get(ctx, "project_root")
            if project_root is None:
                return {}
            config = ConfigLoader.load(Path(project_root) / ".fenix" / "config.yaml")
        if not isinstance(config, dict):
            return {}
        admin = ConfigLoader.get_admin_config(config)
        return admin if isinstance(admin, dict) else {}
    except Exception:
        return {}


def _collect_state_entry(ctx: Any, project_root: Any, spec: str) -> Optional[dict]:
    """fail-open 采集 STATE 条目（status/error/frozen 供 prompt 白话转述）。

    宿主自带 state_machine（pm_engine）时走 read_one；旁路宿主按惯例路径
    ``.fenix/STATE.md`` 经 StateParser 解析。读不到（spec 为空/解析失败）就
    不带——prompt 输入全部 fail-open 采集（D3）。
    """
    if not spec:
        return None
    sm = _ctx_get(ctx, "state_machine")
    if sm is not None:
        try:
            return sm.read_one(spec)
        except Exception:
            return None
    if project_root is None:
        return None
    try:
        from core.state_machine import StateParser

        entries = StateParser.parse(Path(project_root) / ".fenix" / "STATE.md")
        return entries.get(spec)
    except Exception:
        return None


def _collect_report_path(project_root: Any, spec: str) -> Optional[str]:
    """fail-open 采集验证报告路径存在性（report_gate 同一惯例路径）。"""
    if not spec or project_root is None:
        return None
    if validate_scheduling_kick_spec(spec) is not None:
        # spec 名须为 kebab-case 白名单形态才能拼进产物路径（与 verify-progress
        # 读侧防御口径对齐），含 .. 等成分的越界值按不存在处理
        return None
    try:
        path = Path(project_root) / ".fenix" / "verify-progress" / spec / "report.json"
        return str(path) if path.exists() else None
    except Exception:
        return None


# ── 验证材料采集器（task 1.1，design D1）────────────────


def _clip_segment(text: str, budget: int) -> str:
    """单段材料截断：超预算砍尾附截断标记（标记计入预算——截断后整段 ≤ budget）。"""
    mark = "…（截断）"
    if len(text) <= budget:
        return text
    return text[: max(budget - len(mark), 1)].rstrip() + mark


def _read_text_material(path: Path, budget: int) -> Optional[str]:
    """fail-open 读文本材料（verification-report.md），缺失/损坏返回 None。"""
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return None
        return _clip_segment(text, budget)
    except Exception:
        return None


def _summarize_verify_report(path: Path) -> Optional[str]:
    """fail-open 摘要 report.json：summary + 失败/警告场景表（含 classification 分布）。"""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, dict):
            return None
        lines: list = []
        summary = data.get("summary")
        if isinstance(summary, dict):
            lines.append(
                "summary: " + json.dumps(summary, ensure_ascii=False, sort_keys=True)
            )
        scenarios = data.get("scenarios")
        if not isinstance(scenarios, list):
            scenarios = []
        bad = [
            s
            for s in scenarios
            if isinstance(s, dict) and str(s.get("status") or "").lower() not in ("pass", "passed")
        ]
        # classification 分布（含 unclassified 计数，同
        # infra_classify._scenario_classification_distribution 口径）
        counts: Dict[str, int] = {}
        for s in bad:
            cls = str(s.get("classification") or "").strip() or "unclassified"
            counts[cls] = counts.get(cls, 0) + 1
        if bad:
            dist = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
            lines.append(f"失败/警告场景 classification 分布：{dist}")
        shown = bad[:20]
        for s in shown:
            sid = str(s.get("scenario_id") or "?")
            status = str(s.get("status") or "?")
            cls = str(s.get("classification") or "").strip() or "unclassified"
            lines.append(f"- {sid}: status={status} classification={cls}")
        if len(bad) > len(shown):
            lines.append(f"（其余 {len(bad) - len(shown)} 条失败/警告场景略）")
        if not lines:
            return None
        return _clip_segment("\n".join(lines), _MATERIAL_SECTION_MAX_CHARS)
    except Exception:
        return None


def _summarize_verdict_stability(path: Path) -> Optional[str]:
    """fail-open 摘要 verdict_stability.json 判定轮次历史（状态序列）。"""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        rounds = data.get("rounds") if isinstance(data, dict) else None
        if not isinstance(rounds, list) or not rounds:
            return None
        lines = [f"判定轮次共 {len(rounds)} 轮（verdict_stability.json）："]
        for i, r in enumerate(rounds[:20], 1):
            if not isinstance(r, dict):
                continue
            status = str(r.get("status") or "?")
            failed = r.get("failed_ids")
            n_failed = len(failed) if isinstance(failed, list) else "?"
            at = str(r.get("at") or "")
            lines.append(f"- 第{i}轮: status={status} failed_ids={n_failed} at={at}")
        if len(rounds) > 20:
            lines.append(f"（其余 {len(rounds) - 20} 轮略）")
        return _clip_segment("\n".join(lines), _MATERIAL_SECTION_MAX_CHARS)
    except Exception:
        return None


def _summarize_fail_history(path: Path) -> Optional[str]:
    """fail-open 摘要 fail_history.json 轮次演进（失败原因与场景收敛轨迹）。"""
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(data, list) or not data:
            return None
        lines = [f"验证失败轮次演进共 {len(data)} 轮（fail_history.json）："]
        for r in data[:20]:
            if not isinstance(r, dict):
                continue
            rnd = r.get("round", "?")
            cause = str(r.get("cause_type") or "?")
            fclass = str(r.get("failure_class") or "").strip()
            failed = r.get("failed_scenarios")
            ids = ",".join(str(x) for x in failed[:8]) if isinstance(failed, list) else "?"
            more = (
                f" 等{len(failed)}个" if isinstance(failed, list) and len(failed) > 8 else ""
            )
            suffix = f" failure_class={fclass}" if fclass else ""
            lines.append(f"- round={rnd}: cause={cause}{suffix} failed=[{ids}{more}]")
        if len(data) > 20:
            lines.append(f"（其余 {len(data) - 20} 轮略）")
        return _clip_segment("\n".join(lines), _MATERIAL_SECTION_MAX_CHARS)
    except Exception:
        return None


def _collect_verification_materials(
    project_root: Any, spec: str, signal_type: str
) -> Optional[str]:
    """按 signal_type 采集【验证材料】（task 1.1，design D1 主通道）。

    验证族信号从标准产物路径采集四段材料：
    - ``spec/changes/<spec>/verification-report.md`` 全文；
    - ``.fenix/verify-progress/<spec>/report.json`` summary + 失败/警告场景表
      （含 classification 分布）；
    - ``.fenix/verify-progress/<spec>/verdict_stability.json`` 判定轮次历史；
    - ``.fenix/verify-progress/<spec>/fail_history.json`` 失败轮次演进。

    全部 fail-open：任一文件缺失/损坏跳过该段；四段全空返回 None（prompt
    不带【验证材料】段，叙事按既有机械字段生成）。总预算 16K 分段截断
    （段界保留、截断标记标注）。非验证族信号直接返回 None（段跳过，与
    升级前行为兼容）。
    """
    if not spec or project_root is None:
        return None
    if signal_type not in VERIFY_FAMILY_SIGNALS:
        return None
    if validate_scheduling_kick_spec(spec) is not None:
        # spec 名须为 kebab-case 白名单形态才能拼进 spec/changes/<spec>/... 与
        # .fenix/verify-progress/<spec>/... 产物路径（与 verify-progress 读侧
        # 防御口径对齐），越界值按无材料处理
        return None
    root = Path(project_root)
    parts: list = []
    report_md = _read_text_material(
        root / "spec" / "changes" / spec / "verification-report.md",
        _MATERIAL_SECTION_MAX_CHARS,
    )
    if report_md:
        parts.append(f"[验证报告正文 verification-report.md]\n{report_md}")
    vp = root / ".fenix" / "verify-progress" / spec
    report_json = _summarize_verify_report(vp / "report.json")
    if report_json:
        parts.append(f"[场景结果 report.json]\n{report_json}")
    stability = _summarize_verdict_stability(vp / "verdict_stability.json")
    if stability:
        parts.append(f"[判定轮次 verdict_stability.json]\n{stability}")
    fail_hist = _summarize_fail_history(vp / "fail_history.json")
    if fail_hist:
        parts.append(f"[失败演进 fail_history.json]\n{fail_hist}")
    if not parts:
        return None
    # 总预算兜底：分段预算已保证 ≤16K，这里再收口一次（防御段头开销累积）
    return _clip_segment("\n\n".join(parts), _NARRATIVE_CONTEXT_MAX_CHARS)


def _resolve_model(admin_cfg: Dict[str, Any]) -> Optional[str]:
    """模型回退链（D2）：admin.narrative_model → admin.agent_model → 框架默认。

    返回 None 表示两键皆空，通道不传 ``--model``（用 CLI/网关默认模型）。
    """
    return (
        admin_cfg.get("narrative_model")
        or admin_cfg.get("agent_model")
        or None
    )


def _resolve_timeout(admin_cfg: Dict[str, Any]) -> float:
    """叙事硬超时（admin.narrative_timeout_seconds，缺省 180；下限 1s）。"""
    try:
        value = float(admin_cfg.get("narrative_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        value = float(DEFAULT_TIMEOUT_SECONDS)
    return max(value, 1.0)


def _format_facts(facts: Any) -> str:
    """facts 结构化字段转文本（task 1.2）：dict 按键展开，其余 JSON 序列化。"""
    if isinstance(facts, dict):
        lines = []
        for k, v in facts.items():
            if isinstance(v, str):
                lines.append(f"- {k}: {v}")
            else:
                try:
                    lines.append(f"- {k}: {json.dumps(v, ensure_ascii=False)}")
                except Exception:
                    lines.append(f"- {k}: {v}")
        return "\n".join(lines)
    try:
        return json.dumps(facts, ensure_ascii=False, indent=2)
    except Exception:
        return str(facts)


# [fenix-ignore:36dd24a23b66] 建议的对冲已存在：展示层 alert-shared.tsx AlertNarrative 已显著标注「AI 生成·仅供参考·最终由你决定」且 AlertLines 同屏保留机械字段原文对照
def _build_prompt(
    entry: dict,
    state_entry: Optional[dict],
    report_path: Optional[str],
    materials: Optional[str] = None,
    facts: Any = None,
) -> str:
    """组四段式调查 prompt（D3）：输入全部 fail-open 采集，读不到就不带。"""
    choices = entry.get("choices") or []
    choice_lines = []
    for c in choices:
        if not isinstance(c, dict):
            continue
        choice_lines.append(
            f"- id={c.get('id', '?')}｜label={c.get('label', '')}｜说明={c.get('desc', '')}"
        )
    lines = [
        "你在为一条「转人工裁决」告警撰写一段人类可读的四段式调查叙事，"
        "让决策者不查任何其他材料即可理解现状、知道根因并做出裁决。",
        "",
        "【输出要求】",
        "1. 输出纯 Markdown，仅含以下四个段落，段落标题逐字固定且顺序不可变：",
        "## 发生了什么",
        "## 调查结论",
        "## 为什么需要你决策",
        "## 决策选项",
        "2. 「发生了什么」：把 description/evidence 中的技术串（如 "
        "failure_profile=round1:real-bugs; round3:repeat）翻译成因果白话，"
        "指明信号主体（哪个 spec、哪个闸门/机制、第几轮）。",
        "3. 「调查结论」：基于【验证材料】与【补充事实】给出根因判断，"
        "MUST 引用具体证据（计数器/预算/环境事实）；材料内有据可依的因果"
        "推断必须给出；材料不足以定位时明确写「材料不足以定位」，并给出"
        "建议查证路径（查哪个文件/哪个计数器）；材料外的事实不得编造。",
        "4. 「为什么需要你决策」：说明自动链已尝试的路径与停止原因"
        "（哪条计数器/预算/闸门到顶），以及放任自动继续的代价。",
        "5. 「决策选项」：对下方选项快照中的每个选项按 id 逐一给出一小节"
        "（形如 **<id>（<label>）**），解释含义、执行后果，并给出建议倾向；"
        "建议倾向 MUST 标注「仅供参考，最终由你决定」。",
        "6. 不要输出 JSON、不要添加其他段落或结语。",
        "",
        "【告警信息】",
        f"- signal_type: {entry.get('signal_type', '')}",
        f"- spec: {entry.get('spec', '') or '（无）'}",
        f"- severity: {entry.get('severity', '')}",
        f"- 描述(description): {entry.get('description', '')}",
        f"- 证据(evidence): {entry.get('evidence', '') or '（无）'}",
        f"- 建议动作(recommended_action): {entry.get('recommended_action', '') or '（无）'}",
        "- 选项快照(choices):",
    ]
    if choice_lines:
        lines.extend(choice_lines)
    else:
        lines.append("  - （空）")
    lines.append("【状态条目（STATE.md，可能缺失）】")
    if isinstance(state_entry, dict):
        for key in ("status", "error", "frozen"):
            if key in state_entry and state_entry.get(key) not in (None, ""):
                lines.append(f"- {key}: {state_entry.get(key)}")
    else:
        lines.append("- （未采集到）")
    lines.append("【验证报告】")
    if report_path:
        lines.append(f"- 存在：{report_path}")
    else:
        lines.append("- （缺失或 spec 无验证报告）")
    if materials:
        lines.append("【验证材料】")
        lines.append(materials)
    if facts:
        lines.append("【补充事实】")
        lines.append(_format_facts(facts))
    return "\n".join(lines)


def _validate_structure(text: str) -> bool:
    """机械校验四段标题齐全且顺序不倒置（D3：缺失视为失败走兜底）。

    逐行按 ``^##<空白><标题>`` 形态锚定匹配（re.MULTILINE）：正文叙述句
    提前出现标题词不再顶替缺失标题骗过校验（code-review b90c2e93afe9）。
    空白用 ``[ \\t]*`` 而非 ``\\s*``——避免 ``\\s`` 吞换行把独立「##」行与
    下一行正文误拼成一个标题。旧三段输出（缺「调查结论」段）判失败走兜底
    ——不兼容旧输出是故意的（design D3）。
    """
    if not text:
        return False
    positions = []
    for head in REQUIRED_SECTIONS:
        m = re.search(rf"^##[ \t]*{re.escape(head)}", text, re.MULTILINE)
        if m is None:
            return False
        positions.append(m.start())
    return positions == sorted(positions)


def _clip_narrative(text: str) -> str:
    """超长叙事截断（code-review d1ec8fd1687f）：整体预算 _NARRATIVE_MAX_CHARS。

    以四段标题为段界均摊预算、逐段砍尾附省略标记——标题行始终保留，四段
    结构与顺序不变，不破坏 _validate_structure 已验证的结构与下游按 ``^## ``
    标题的分段渲染。重复标题等病态形态下仅认前 len(REQUIRED_SECTIONS) 个
    匹配为段界，多余重复标题归入末段正文一并受预算约束；标题前前导文本
    （指令要求仅含四段，正常输出无）不占段落预算、压缩为单行省略标记。
    仅在结构校验通过后调用（段界缺失的防御性兜底整体砍尾）。永不抛出。
    """
    if len(text) <= _NARRATIVE_MAX_CHARS:
        return text
    starts = [m.start() for m in _SECTION_HEAD_RE.finditer(text)]
    if len(starts) < len(REQUIRED_SECTIONS):
        # 防御性兜底（不应发生——调用前已过 _validate_structure）
        return text[:_NARRATIVE_MAX_CHARS].rstrip() + _NARRATIVE_TRUNCATION_MARK
    starts = starts[: len(REQUIRED_SECTIONS)]
    bounds = starts + [len(text)]
    pieces: list = []
    if starts[0] > 0:
        pieces.append(_NARRATIVE_LEADING_MARK)
    for i in range(len(REQUIRED_SECTIONS)):
        seg = text[starts[i] : bounds[i + 1]]
        if len(seg) > _NARRATIVE_SECTION_MAX_CHARS:
            seg = seg[:_NARRATIVE_SECTION_MAX_CHARS].rstrip() + _NARRATIVE_TRUNCATION_MARK
            if i < len(REQUIRED_SECTIONS) - 1:
                # 省略标记收尾不带换行——不补一行，下一段标题（## x）会失去
                # 行首锚定，_validate_structure 的 ^## MULTILINE 匹配随之失真
                seg += "\n"
        pieces.append(seg)
    return "".join(pieces)


# ── 熔断器（task 4.1，design D4）────────────────────────


def _breaker_gate() -> bool:
    """熔断生效判定：生效返回 True（调用方跳过生成、零调用零延迟）。

    冷却到期时在此解除（WARNING 留痕）并放行本次尝试——解除只发生在这里
    （有新告警触发尝试时），无后台定时器。
    """
    global _breaker_open_until
    with _breaker_lock:
        if _breaker_open_until <= 0:
            return False
        if time.monotonic() < _breaker_open_until:
            return True
        # 冷却到期：解除熔断，恢复尝试（计数保留——恢复后仍失败会立即再熔断）
        _breaker_open_until = 0.0
    _logger.warning(
        "叙事熔断冷却结束（%d 秒），恢复生成尝试", BREAKER_COOLDOWN_SECONDS
    )
    return False


def _breaker_record_failure() -> None:
    """记录一次生成失败（超时/空输出/结构校验失败/异常）。

    连续失败达 BREAKER_THRESHOLD → 熔断生效 BREAKER_COOLDOWN_SECONDS，
    WARNING 留痕。冷却期内零调用故无「期间成功」复位路径（design D4）。
    """
    global _breaker_fail_streak, _breaker_open_until
    with _breaker_lock:
        _breaker_fail_streak += 1
        if _breaker_open_until > 0:
            return  # 已熔断（防御：熔断期正常零调用）
        if _breaker_fail_streak >= BREAKER_THRESHOLD:
            _breaker_open_until = time.monotonic() + BREAKER_COOLDOWN_SECONDS
            _logger.warning(
                "叙事连续失败 %d 次，熔断生效（冷却 %d 秒；期内新告警跳过生成、"
                "写终态侧车）",
                _breaker_fail_streak,
                BREAKER_COOLDOWN_SECONDS,
            )


def _breaker_record_success() -> None:
    """记录一次生成成功：清零连续失败计数（design D4 复位语义）。"""
    global _breaker_fail_streak
    with _breaker_lock:
        _breaker_fail_streak = 0


def build_narrative(
    ctx: Any,
    entry: dict,
    admin_cfg: Optional[Dict[str, Any]] = None,
    facts: Any = None,
) -> Optional[Dict[str, str]]:
    """采集上下文 → 组四段式 prompt → 单次 LLM 调用 → 机械校验四段结构。

    失败（异常/超时/空输出/结构校验不过）返回 None 并 WARNING 留痕，
    MUST NOT 抛出。每次调用即「至多一次尝试」——2 次尝试由调度层
    （:func:`schedule_narrative` 的后台线程循环）保证。失败/成功同时驱动
    连续失败熔断器（task 4.1）。

    通道未装配（生产 daemon 未注册 / 测试进程未注入假通道）时整体惰性：
    静默返回 None、零调用、零熔断计数——单元测试进程因此天然不触网关
    （spec「测试 MUST NOT 真调网关」由结构保证，不依赖用例自觉）。生产经
    fenixd main() ``set_channel(default_channel)`` 装配。

    返回成功产物 ``{"text": <四段 Markdown>, "model": <实际模型>}``；
    模型未显式配置时记 ``"default"``（通道未传 ``--model``）。
    """
    try:
        channel = _get_channel()
        if channel is None:
            return None
        if admin_cfg is None:
            admin_cfg = _resolve_admin_config(ctx)
        spec = entry.get("spec") or ""
        project_root = _ctx_get(ctx, "project_root")
        state_entry = _collect_state_entry(ctx, project_root, spec)
        report_path = _collect_report_path(project_root, spec)
        materials = _collect_verification_materials(
            project_root, spec, entry.get("signal_type") or ""
        )
        prompt = _build_prompt(
            entry, state_entry, report_path, materials=materials, facts=facts
        )
        model = _resolve_model(admin_cfg)
        timeout = _resolve_timeout(admin_cfg)
        text = channel(prompt, model, timeout)
        if not isinstance(text, str) or not text.strip():
            _breaker_record_failure()
            _warn(
                ctx,
                f"叙事 LLM 输出为空/超时（signal={entry.get('signal_type')}, "
                f"spec={spec or '?'}），告警以机械文案落盘",
            )
            return None
        text = text.strip()
        if not _validate_structure(text):
            _breaker_record_failure()
            _warn(
                ctx,
                f"叙事四段结构校验失败（signal={entry.get('signal_type')}, "
                f"spec={spec or '?'}），告警以机械文案落盘",
            )
            return None
        # 超长输出截断（code-review d1ec8fd1687f）：四段标题结构保留，
        # 防止失控输出把侧车 JSON 撑爆
        text = _clip_narrative(text)
        _breaker_record_success()
        return {"text": text, "model": model or "default"}
    except Exception as e:  # fail-open：叙事是增强不是门禁（D4）
        _breaker_record_failure()
        _warn(ctx, f"叙事生成异常（告警照常落盘）: {e}")
        return None


# ── 侧车读写（task 3.2/3.3/3.4）─────────────────────────


def _safe_alert_id(alert_id: Any) -> str:
    """alert_id 收窄为安全文件名成分（uuid4().hex[:12] 恒通过，防御人工拼装）。"""
    return re.sub(r"[^A-Za-z0-9_-]", "", str(alert_id or ""))[:64]


def _sidecar_dir(project_root: Any) -> Path:
    return Path(project_root) / ".fenix" / SIDECAR_DIRNAME


def write_narrative_sidecar(
    project_root: Any, alert_id: str, text: str, model: Optional[str]
) -> bool:
    """原子写一条叙事侧车 ``<dir>/<alert_id>.json``（task 3.2）。

    结构 ``{"alert_id", "text", "model", "at"}``（at 为 UTC ISO，与 AdminStore
    ``created`` 同口径）；mkstemp + os.replace 原子落位（并发读者要么看到
    旧态要么看到完整新态，无半截 JSON）。目录不存在即建；终态侧车（补叙
    失败/熔断跳过）与补叙侧车同构同目录、model=None 区分。写失败 WARNING
    留痕返回 False，绝不抛出（告警本体已落盘，不受影响）。
    """
    aid = _safe_alert_id(alert_id)
    if not aid:
        return False
    try:
        d = _sidecar_dir(project_root)
        d.mkdir(parents=True, exist_ok=True)
        payload = {
            "alert_id": aid,
            "text": text,
            "model": model,
            "at": datetime.now(timezone.utc).isoformat(),
        }
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".narrative-", suffix=".tmp")
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            with f:
                json.dump(payload, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, d / f"{aid}.json")
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        finally:
            # fdopen 自身抛错时 with 未绑定文件、裸 fd 无人关闭——daemon 长
            # 生命周期内描述符泄漏，兜底 os.close（对齐 item cbb57806fbfd 口径，
            # item bad97ae2edc3）。
            if f is None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        try:
            dfd = os.open(d, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
        return True
    except OSError as e:
        _logger.warning("叙事侧车写入失败（alert=%s）: %s", aid, e)
        return False


def load_narrative_sidecars(project_root: Any) -> Dict[str, dict]:
    """读目录下全部叙事侧车，返回 ``{alert_id: payload}``（task 3.3 读侧用）。

    损坏侧车跳过（fail-open，不阻断告警列表渲染）；目录缺失返回 {}。
    """
    try:
        d = _sidecar_dir(project_root)
        entries = sorted(d.glob("*.json"))
    except OSError:
        return {}
    out: Dict[str, dict] = {}
    for p in entries:
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and data.get("alert_id"):
                out[str(data["alert_id"])] = data
        except Exception:
            continue  # 损坏/半截侧车跳过
    return out


def delete_narrative_sidecars(project_root: Any, alert_ids: Any) -> int:
    """级联删除告警对应的叙事侧车（task 3.4 清理路径用）。

    逐个 unlink：不存在的 id 静默跳过；单文件删除失败记入 WARNING 汇总、
    继续其余——删除失败不阻断清理主流程（残留侧车渲染按 alert_id 匹配
    不到即忽略，无害，design Risks「侧车孤儿」）。返回成功删除数。
    """
    if not alert_ids:
        return 0
    # 入口固化一次（code-review item df08d9ca5f54）：失败汇总的总数统计与
    # 循环共用同一列表——调用方传生成器/迭代器时，耗尽后再 list() 恒为空，
    # WARNING 文案会误报「N/0」。
    ids = list(alert_ids)
    try:
        d = _sidecar_dir(project_root)
    except Exception:
        return 0
    deleted = 0
    errors: list = []
    for aid in ids:
        name = _safe_alert_id(aid)
        if not name:
            continue
        try:
            (d / f"{name}.json").unlink()
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError as e:
            errors.append(f"{name}: {e}")
        except Exception as e:  # 防御：路径被目录占位等病态形态
            errors.append(f"{name}: {e}")
    if errors:
        _logger.warning(
            "叙事侧车级联删除部分失败（%d/%d）：%s",
            len(errors),
            len(ids),
            "; ".join(errors[:5]),
        )
    return deleted


def _narrative_worker(
    alert_id: str,
    entry: dict,
    ctx: Any,
    admin_cfg: Dict[str, Any],
    facts: Any,
    project_root: Any,
) -> None:
    """后台补叙线程体（task 3.1/3.2）：至多 2 次尝试 → 补叙/终态侧车。

    人工已处置（handled）不检查——补叙照常落盘（历史完整性优先，处置
    流程不受影响，spec「异步补叙」Requirement）。任何异常兜底写终态侧车，
    绝不让失败告警悬挂「调查生成中」假态。
    """
    try:
        result: Optional[Dict[str, str]] = None
        breaker_skip = False
        for _attempt in range(_MAX_ATTEMPTS):
            if _breaker_gate():
                # 尝试间隙熔断生效：立即放弃（冷却期零调用）
                breaker_skip = True
                result = None
                break
            result = build_narrative(ctx, entry, admin_cfg, facts=facts)
            if result:
                break
        if result:
            write_narrative_sidecar(
                project_root, alert_id, result["text"], result["model"]
            )
        else:
            text = BREAKER_SKIP_TEXT if breaker_skip else GENERATION_FAILED_TEXT
            write_narrative_sidecar(project_root, alert_id, text, None)
            _warn(
                ctx,
                f"叙事{'熔断生效跳过' if breaker_skip else f'{_MAX_ATTEMPTS} 次尝试均失败'}"
                f"，已写终态侧车（alert={alert_id}）",
            )
    except Exception as e:  # 兜底：绝不悬挂假态、绝不穿透
        _warn(ctx, f"后台补叙异常（告警已落盘不受影响）: {e}")
        try:
            write_narrative_sidecar(project_root, alert_id, GENERATION_FAILED_TEXT, None)
        except Exception:
            pass
    finally:
        with _active_lock:
            _active_threads.discard(threading.current_thread())


def schedule_narrative(
    alert_id: str,
    entry: dict,
    ctx: Any,
    facts: Any = None,
) -> Optional[threading.Thread]:
    """告警落盘后调度后台补叙（task 3.1/3.2）——本函数零 LLM 调用零阻塞。

    调用契约：``store.append`` 已返回落地记录（alert_id 取返回记录的
    ``id``，MUST NOT 依赖发射点 entry 预先持有 id）；告警本体已以机械文案
    立即落盘，本函数只负责把叙事生成挪到后台线程。

    - ``entry["choices"]`` 为空（桶 0 知情/自愈类）直接返回、零线程；
    - ``admin.narrative_enabled`` 为 false 零线程（行为与本模块落地前完全
      一致，熔断器同时被旁路——整体关闭优先）；
    - 通道未装配（测试进程未注入假通道）整体惰性：零线程、零侧车；
    - 熔断生效期：零调用零延迟，同步写终态侧车（机械说明、model=null），
      失败告警不以 narrative_pending 悬挂「调查生成中」假态；
    - 正常路径：启动 daemon 线程（:func:`_narrative_worker`，至多 2 次尝试
      → 补叙/终态侧车），返回线程对象（测试 ``wait_pending_narrative``
      等待用）；任何调度异常 WARNING 留痕、绝不抛出穿透发射链路。
    """
    try:
        if not alert_id or not isinstance(entry, dict) or not entry.get("choices"):
            return None
        admin_cfg = _resolve_admin_config(ctx)
        if not admin_cfg.get("narrative_enabled", True):
            return None
        if _get_channel() is None:
            return None
        project_root = _ctx_get(ctx, "project_root")
        if _breaker_gate():
            write_narrative_sidecar(project_root, alert_id, BREAKER_SKIP_TEXT, None)
            _warn(ctx, f"叙事熔断生效，跳过生成并写终态侧车（alert={alert_id}）")
            return None
        t = threading.Thread(
            target=_narrative_worker,
            args=(alert_id, entry, ctx, admin_cfg, facts, project_root),
            daemon=True,
            name=f"narrative-{_safe_alert_id(alert_id)}",
        )
        try:
            with _active_lock:
                _active_threads.add(t)
            t.start()
        except BaseException:
            # start 失败（线程数耗尽等）时 worker 的 finally 自摘永不执行，
            # 未启动线程残留登记集会让 wait_pending_narrative 对其 join 抛
            # RuntimeError——先摘牌再上抛，保持外层 fail-open 吞异常语义不变
            # （item b98a4502183a）。
            with _active_lock:
                _active_threads.discard(t)
            raise
        return t
    except Exception as e:  # fail-open：叙事是增强不是门禁
        _warn(ctx, f"叙事调度异常（告警已落盘不受影响）: {e}")
        return None
