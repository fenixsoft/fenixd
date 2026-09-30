"""core.adjudication_narrative — 转人工裁决告警的三段式叙事辅助（add-adjudication-alert-narrative）。

裁决贵在及时：告警若不自解释，决策者每次「先找人问清楚」都在拉长冻结窗口。
本模块在告警落盘的同一时机经**一次轻量 LLM 调用**生成人类可读的三段式叙事
（发生了什么 / 为什么需要你决策 / 决策选项），以 ``narrative`` 字段并入告警记录。

接线点（覆盖全部桶 2 转人工裁决告警，spec「叙事覆盖全部转人工裁决告警」）：
- ``pm_engine._send_human_escalation_alert``（core/pm_engine/family.py）——全部
  ESCALATION 告警的共同写入口（预算耗尽/升级闸门/评审两族/judge 重跑上限/
  同因重派熔断/恢复期回调均汇聚于此）；
- 两个旁路 choices 附带点：``core/worktree_manager/mergeback.py`` 的
  build_artifact_paths_missing 与 ``core/agent_runner/token_budget.py`` 的
  token_budget。旁路点复用本模块，MUST NOT 各自内联第二套 prompt/生成逻辑。

设计契约（design D1-D6）：
- **纯增强**：narrative 只增不改，description/evidence/recommended_action/
  choices/trigger 任一既有字段的结构化语义零感知（alert-resolve、闭环判定、
  Administrator 处置不受影响）；
- **fail-open**：LLM 异常/超时/空输出/结构校验失败 → 告警照常以既有机械文案
  落盘（不写 narrative 字段）、logger.warning 留痕、至多一次尝试、绝不抛出
  穿透发射链路——叙事是增强，不是门禁；
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

import logging
import os
import re
import signal
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# 日志组件名（logger.warning(component, message) 口径）
COMPONENT = "adjudication_narrative"

# 三段固定段落标题（D3）：顺序固定。生成后机械校验齐全（且顺序不倒置），
# 缺失视为本次生成失败走兜底。
REQUIRED_SECTIONS: tuple = ("发生了什么", "为什么需要你决策", "决策选项")

# admin.narrative_timeout_seconds 缺省（与 ConfigLoader.get_admin_config 单源）
DEFAULT_TIMEOUT_SECONDS = 60

# 裸 stdlib 日志通道（同 core/config.py、core/code_review.py 等先例）：daemon
# Logger 往 "fenixd" 根日志器挂 handler，fenixd.* 子日志器记录随之落入 daemon
# 日志文件——供 default_channel 失败时留痕 CLI 侧真实报错（stderr 尾部）。
_logger = logging.getLogger("fenixd.adjudication_narrative")

# 失败留痕的 stderr 尾部截断长度（code-review 1692f5b23b83）
_STDERR_TAIL_CHARS = 500

# claude 子进程 spawn 工作目录注入点（code-review 672decf84c0d）：生产=
# fenixd main() 装配通道时一并传项目根；未装配回退系统临时目录。
_project_root: Optional[str] = None

# LLM 通道签名：channel(prompt, model, timeout) -> str | None
# （返回 None 或抛异常均按失败兜底处理）。模块级注入点（D2）：生产不注入、
# 用缺省 claude -p 通道；测试注入假通道，MUST NOT 真调网关。锁保护读写——
# 告警发射点分布在 daemon 多个线程，注册/清理与调用并发安全。
_channel_lock = threading.Lock()
_channel: Optional[Callable[[str, Optional[str], float], Optional[str]]] = None


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
    """
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        pass  # 进程组已不存在
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass  # 进程组已不存在
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

    - 提示词经 stdin 传入（同 agent_runner._run_claude 口径：不走 argv——
      argv 全文驻留 /proc/<pid>/cmdline，且单参数受 ARG_MAX 约束）；
    - 仅解析到模型时传 ``--model``；缺省（None）用 CLI/网关默认模型（即
      「框架默认」档）；
    - MUST NOT 传 ``--max-tokens-budget`` 类危险旗标（fenixd 实测 7/8 failed
      禁传项）；
    - 超时/子进程缺失/非零退出/空输出一律返回 None，失败语义由调用方统一
      fail-open 兜底（本函数不重试——「至多一次尝试」由调用方单次调用保证）；
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
    try:
        path = Path(project_root) / ".fenix" / "verify-progress" / spec / "report.json"
        return str(path) if path.exists() else None
    except Exception:
        return None


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
    """叙事硬超时（admin.narrative_timeout_seconds，缺省 60；下限 1s）。"""
    try:
        value = float(admin_cfg.get("narrative_timeout_seconds") or DEFAULT_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        value = float(DEFAULT_TIMEOUT_SECONDS)
    return max(value, 1.0)


# [fenix-ignore:36dd24a23b66] 建议的对冲已存在：展示层 alert-shared.tsx AlertNarrative 已显著标注「AI 生成·仅供参考·最终由你决定」且 AlertLines 同屏保留机械字段原文对照
def _build_prompt(entry: dict, state_entry: Optional[dict], report_path: Optional[str]) -> str:
    """组三段式 prompt（D3）：输入全部 fail-open 采集，读不到就不带。"""
    choices = entry.get("choices") or []
    choice_lines = []
    for c in choices:
        if not isinstance(c, dict):
            continue
        choice_lines.append(
            f"- id={c.get('id', '?')}｜label={c.get('label', '')}｜说明={c.get('desc', '')}"
        )
    lines = [
        "你在为一条「转人工裁决」告警撰写一段人类可读的三段式叙事，"
        "让决策者不查任何其他材料即可理解现状并做出裁决。",
        "",
        "【输出要求】",
        "1. 输出纯 Markdown，仅含以下三个段落，段落标题逐字固定且顺序不可变：",
        "## 发生了什么",
        "## 为什么需要你决策",
        "## 决策选项",
        "2. 「发生了什么」：把 description/evidence 中的技术串（如 "
        "failure_profile=round1:real-bugs; round3:repeat）翻译成因果白话，"
        "指明信号主体（哪个 spec、哪个闸门/机制、第几轮）。",
        "3. 「为什么需要你决策」：说明自动链已尝试的路径与停止原因"
        "（哪条计数器/预算/闸门到顶），以及放任自动继续的代价。",
        "4. 「决策选项」：对下方选项快照中的每个选项按 id 逐一给出一小节"
        "（形如 **<id>（<label>）**），解释含义、执行后果，并给出建议倾向；"
        "建议倾向 MUST 标注「仅供参考，最终由你决定」。",
        "5. 不要输出 JSON、不要添加其他段落或结语；材料里没有的信息不要编造。",
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
    return "\n".join(lines)


def _validate_structure(text: str) -> bool:
    """机械校验三段标题齐全且顺序不倒置（D3：缺失视为失败走兜底）。

    逐行按 ``^##<空白><标题>`` 形态锚定匹配（re.MULTILINE）：正文叙述句
    提前出现标题词不再顶替缺失标题骗过校验（code-review b90c2e93afe9）。
    空白用 ``[ \\t]*`` 而非 ``\\s*``——避免 ``\\s`` 吞换行把独立「##」行与
    下一行正文误拼成一个标题。
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


def build_narrative(
    ctx: Any,
    entry: dict,
    admin_cfg: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    """采集上下文 → 组三段式 prompt → 单次 LLM 调用 → 机械校验三段结构。

    失败（异常/超时/空输出/结构校验不过）返回 None 并 WARNING 留痕，
    MUST NOT 抛出、MUST NOT 重试（单次调用即「至多一次尝试」，D4）。

    通道未装配（生产 daemon 未注册 / 测试进程未注入假通道）时整体惰性：
    静默返回 None、零调用——单元测试进程因此天然不触网关（spec「测试
    MUST NOT 真调网关」由结构保证，不依赖用例自觉）。生产经 fenixd main()
    ``set_channel(default_channel)`` 装配。

    返回成功产物 ``{"text": <三段 Markdown>, "model": <实际模型>}``；
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
        prompt = _build_prompt(entry, state_entry, report_path)
        model = _resolve_model(admin_cfg)
        timeout = _resolve_timeout(admin_cfg)
        text = channel(prompt, model, timeout)
        if not isinstance(text, str) or not text.strip():
            _warn(
                ctx,
                f"叙事 LLM 输出为空/超时（signal={entry.get('signal_type')}, "
                f"spec={spec or '?'}），告警以机械文案落盘",
            )
            return None
        text = text.strip()
        if not _validate_structure(text):
            _warn(
                ctx,
                f"叙事三段结构校验失败（signal={entry.get('signal_type')}, "
                f"spec={spec or '?'}），告警以机械文案落盘",
            )
            return None
        return {"text": text, "model": model or "default"}
    except Exception as e:  # fail-open：叙事是增强不是门禁（D4）
        _warn(ctx, f"叙事生成异常（告警照常落盘）: {e}")
        return None


def attach_narrative(entry: dict, ctx: Any) -> None:
    """告警落盘前原位附加 ``narrative`` 字段（纯增强，失败静默回落）。

    - ``entry["choices"]`` 为空（桶 0 知情/自愈类）直接返回、零调用；
    - ``admin.narrative_enabled`` 为 false 零调用零延迟（行为与本模块落地前
      完全一致）；
    - 成功写 ``entry["narrative"] = {"text", "model", "at"}``（at 为 UTC ISO，
      与 AdminStore ``created`` 同口径）；
    - 任何失败不写该字段、logger.warning 留痕、绝不抛出穿透发射链路。
    """
    try:
        if not isinstance(entry, dict) or not entry.get("choices"):
            return
        admin_cfg = _resolve_admin_config(ctx)
        if not admin_cfg.get("narrative_enabled", True):
            return
        result = build_narrative(ctx, entry, admin_cfg)
        if not result:
            return
        entry["narrative"] = {
            "text": result["text"],
            "model": result["model"],
            "at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:  # fail-open：叙事是增强不是门禁（D4）
        _warn(ctx, f"叙事附加异常（告警照常落盘）: {e}")
