"""DshAdapter —— dsh headless 通道的 harness adapter（add-dsh-adapter-integration）。

契约源（SPEC-2 真机探针结论，实现 MUST 与其对账）：

- ``dsh-bundle/docs/probe-findings.md``：事件流字段表、stderr 错误码表、
  usage 形态（``status step_end`` 携带 ``{inputTokens, outputTokens,
  totalTokens}`` 每步一条，``final`` 不携带，累计值由消费方对 step_end
  求和 → ``usage_source: available``）、截断边界（单值 8 KiB / 整行
  32 KiB，``truncated: true`` 事件级标记，``final.text`` 不截断）。
- ``dsh-bundle/tests/fixtures/headless-events.jsonl``：投影层契约测试源。

CLI 形态（dsh 0.2.0-rc.2 实测）：``dsh --profile <p> --patch <yml> headless
--json [app-args...]``；任务经 stdin（无位置参数时）；NDJSON 事件流
``session`` 开头 / ``final`` 结尾 / ``error`` 无 final；exit 0=完成 1=中止；
``--session-id`` 为严格采纳语义（未知 id → error 事件秒挂），因此全新会话
MUST NOT 传该 flag，仅 resume 传真实 dsh session id（``session-<uuid>``，
来自 session 事件投影）。

design 决策落点（spec/changes/add-dsh-adapter-integration/design.md）：

- D1 投影层是 adapter 职责：:class:`DshEventProjector` 把 dsh 事件流投影为
  claude stream-json canon 形状（run jsonl 读侧零改动）；
- D2 stderr 分类接口化：dsh 错误码经 :func:`~core.agent_runner.provider_circuit.translate_dsh_error_text`
  改写为 claude 形状文本后走既有分类器（熔断/瞬断/记账治理零改动）；
- D3 session：fenixd 侧记账键 ``fenix-<run_id>``（session.py），dsh 侧真实
  session id 由 session 事件回报；采纳失败回退新会话重跑；
- D4 max_turns daemon 侧强制（dsh 无该 flag，与 claude 同语义）；
- D5 健康检查白名单钉版本（本模块常量，随 dsh-bundle README 版本表走代码）；
- D7 banned env 扩充在 dsh 通道内完成（agent_env_keys dsh 口径）。

本模块是全仓唯一允许出现 dsh 硬编码知识（CLI 名、事件形状、错误码表）的
位置（tasks.md 7.2 grep 核查口径）；runner/prompts 等经 duck-typing 协议
扩展位（event_projector/harness_notes/is_resume_dead_error）消费，不感知
dsh 字面。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .protocol import (
    ENV_MODE_AGENT_RUN,
    ENV_MODE_CLEAN,
    ENV_MODE_INHERIT,
    STDERR_CLASS_CLI_NOISE,
    STDERR_CLASS_GENERIC,
    STDERR_CLASS_UNRECOGNIZED_MODEL,
    HarnessCapabilities,
    SpawnRequest,
    SpawnSpec,
    default_worktree_pgrep_patterns,
)

# ── 部署常量（design D5：白名单不做配置键，随 Bundle README 版本表走代码）──

#: dsh 版本白名单（dsh-bundle README 版本兼容表当前钉 release）。
DSH_VERSION_WHITELIST = ("0.2.0-rc.2",)

#: Bundle 挂载的 dsh profile 名（dsh-bundle/README.md 部署段约定的自定义
#: profile；shipped 模板名（headless 等）被 CLI 禁止作为自定义 profile 目标，
#: 实测 fail-loud「profile "headless" is shipped and cannot be a custom
#: profile target」）。可用配置键 ``agent.dsh_profile`` 覆盖。
DSH_DEFAULT_PROFILE = "fenix"

#: headless app 名。**禁止进入 argv**：``--profile <p>`` 已完成 app 选择，
#: argv 里的裸 ``headless`` 会被 headless 应用的启动器解析为任务 positional
#: （dsh 契约：positional 存在即不读 stdin，prompt 载荷被整体忽略）——
#: 模型收到的任务文本变成字面单词 "headless"（2026-10-14 真实验收 run4
#: 实证：implementer/verifier/judge 三车道全部答非所问）。保留本常量仅作
#: 此陷阱的注记锚点；正确形态见 build_spawn_spec。
DSH_APP_NAME = "headless"

#: patch 渲染的路由名（README：路由名任取，渲染为 llm-pi-ai providers 键）。
DSH_ROUTE_PROVIDER_NAME = "fenix-dsh"

#: 凭据桥接环境变量名：provider 链 apikey 经该变量交 dsh（patch 的
#: ``apiKeyEnv`` 指名它；运行时未导出 → dsh MISSING_CREDENTIAL，不进熔断）。
DSH_API_KEY_ENV = "FENIX_DSH_PROVIDER_API_KEY"

#: patch 保留期（秒）：按龄回收阈值。patch 只在 dsh 启动首秒被读取，
#: 3600s 是读取窗的数千倍安全边际；残留上界 ≈ 保留期 × spawn 速率。
DSH_PATCH_RETENTION_SECONDS = 3600.0

#: ``--dump-config`` 产物中判定 Bundle 已挂载的标记（fenix-model-config
#: 插件条目 id，由 link 安装的 fenix-dsh-bundle 注入）。
DSH_BUNDLE_MOUNT_MARKER = "fenix-model-config"

#: ``--dump-config`` 产物中判定 headless 运行时已挂载的标记（required 启动
#: 条目 ``headless-runner``，由 ``@deepseek-ai/dsh-headless`` bundle 注入）。
#: 实测（2026-10-13）：全新 home 的 ``plugin add`` 只登记 dsh-base，缺
#: headless bundle 时该条目缺席、headless 命令在 loader.await() 静默永等
#: （零 stdout/stderr、零 LLM 请求的空转 hang）——健康门必须当场拦下。
DSH_HEADLESS_ENTRY_MARKER = "headless-runner"

# ── dsh 采纳失败判别（design D3：fail-loud → 新会话重跑回退）──────────────

#: dsh ``--session-id`` 采纳失败的错误文本签名（探针实测未知 id 形态；
#: 被持有 refuse / cwd 不符拒绝同属 fail-loud 家族，按「session」+「not」
#: 宽松兜底判别，误判代价仅是多走一次新会话回退）。runner 经 duck-typing
#: 消费（is_resume_dead_error），claude 通道既有判定零改动。
DSH_SESSION_ADOPT_DEAD_MARKER = "does not exist; omit --session-id"

#: resume 采纳失败的宽松兜底正则（held/refus/cwd-mismatch 分支——错误文本
#: 签名未逐字实测（探针仅覆盖未知 id），命中面较宽：任何同时含「session」
#: 词干与否定词的无关错误也会判 resume 死，误判代价仅是新会话回退重跑一次
#: （可接受）。探针下次覆盖这三类错误文本后，把实测签名收进常量表并收窄
#: 本正则；tests/test_harness_dsh_adapter.py::TestSessionBinding 已锚定当前
#: 兜底行为，收窄时同步改写锚点。
DSH_SESSION_ADOPT_FALLBACK_PATTERN = (
    r"session\b.*\b(not exist|does not exist|held|refus|mismatch)"
)

# ── init 事件工具表（probe-findings「工具注册面补充」逐字对账）────────────

#: dsh session → init 投影携带的工具表（Bundle Task 工具族 + 24 原生工具）。
#: run_task_track 以工具名判别 TaskCreate/TaskUpdate 进度，表内容 MUST 与
#: Bundle 实际注册一致（Bundle 版本升级时随探针重录）。
DSH_INIT_TOOLS: Tuple[str, ...] = (
    # fenix-dsh-bundle 注册的 Task 工具族
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    # dsh 原生 24 工具（probe-findings.md L80-82）
    "bash",
    "create_goal",
    "edit",
    "exit_plan_mode",
    "get_goal",
    "glob",
    "grep",
    "interrupt_agent",
    "job_kill",
    "job_list",
    "job_output",
    "list_agents",
    "read",
    "read_image",
    "send_message",
    "skill",
    "subagent",
    "subagent_fork",
    "todo_write",
    "update_goal",
    "web_fetch",
    "web_search",
    "workflow",
    "write",
)


class DshSpawnConfigError(Exception):
    """dsh spawn 前置配置不满足（provider 链三要素缺失等）——fail-fast，
    不代跑、不回退 claude（spec「MUST NOT 静默回退 claude」）。"""


class HarnessHealthError(Exception):
    """dispatch 前置健康检查不通过（未装/版本不符/Bundle 未挂载）——
    错误信息 MUST 含修复指引（spec「错误信息含修复指引」）。"""


def _yaml_scalar(value: str) -> str:
    """标量渲染为 YAML 安全形态（JSON 字符串字面量是合法 YAML 标量）。"""
    return json.dumps(str(value), ensure_ascii=False)


def render_model_patch_yaml(
    model: str,
    base_url: str,
    api_key_env: str,
    provider_name: str = DSH_ROUTE_PROVIDER_NAME,
    api: str = "",
) -> str:
    """渲染 ``--patch`` 模型三要素覆盖文件（dsh-bundle/README.md 部署段形状）。

    Bundle 的 fenix-model-config 插件校验 ``config.model`` 四字段
    （provider/baseURL/apiKeyEnv/model）显式非空，缺失即 apply 期抛错
    （fail-fast 链）；渲染是单向的：patch 覆盖后 providers/默认模型全部由
    该服务铺开——绝不回退 dsh 默认档（spec「MUST NOT 依赖 dsh 默认档」）。
    ``api`` 非空时追加渲染线协议字段（pi-ai api 类型，如
    ``anthropic-messages``）；空则不渲染，Bundle 端缺省
    ``openai-completions``。
    """
    lines = [
        "# fenixd DshAdapter 自动生成（每次 spawn 重写）：Bundle 模型三要素显式渲染。",
        "# 改模型只改 fenixd provider 链分配（_get_agent_model_assignment），勿手改本文件。",
        "- id: fenix-model-config",
        "  config:",
        "    model:",
        f"      provider: {_yaml_scalar(provider_name)}",
        f"      baseURL: {_yaml_scalar(base_url)}",
        f"      apiKeyEnv: {_yaml_scalar(api_key_env)}",
        f"      model: {_yaml_scalar(model)}",
    ]
    if api:
        lines.append(f"      api: {_yaml_scalar(api)}")
    return "\n".join(lines) + "\n"


# ── 投影层（design D1 + 可观测性三件套）──────────────────────────────────

#: 逐类型收到/投影/忽略计数的类型词表（投影表全键；未知类型落入
#: ``unknown_type`` 坏事件统计，不进本词表）。
DSH_EVENT_TYPES = (
    "session",
    "status",
    "text",
    "thinking",
    "tool_call",
    "tool_result",
    "final",
    "error",
)

#: 坏事件分类词表（spec「坏事件分类统计」三分类 + 合法 JSON 形状不符单列）。
DSH_BAD_EVENT_KINDS = (
    "json_parse_failed",     # 行级 JSON 解析失败（非合法 JSON）
    "json_shape_mismatch",   # 合法 JSON 但非 dict（标量/数组，形状不符）
    "unknown_type",          # 未知事件类型（忽略+计数，不中断流）
    "over_limit_truncated",  # 超 8KiB/32KiB 截断（truncated: true 透传）
)


class DshEventProjector:
    """dsh NDJSON 事件流 → claude stream-json canon 形状的有状态投影器。

    有状态的原因：usage 需对 step_end 逐条求和（探针结论：final 不携带
    usage）、num_turns 由 turn_end 计数、session_id 需从 session 事件留存
    供 final 投影回填。adapter 单例共享，本对象按 run 实例化
    （DshAdapter.event_projector(run_id, run_dir)），生命周期 = 一次 run 的
    读环。

    可观测性三件套（spec「新采集链路可观测性」，与功能交付同批）：
    - 原始事件 dump：采集输入原样落盘 run 目录旁路文件
      ``<run_id>.dsh-events.jsonl``（含解析失败的原始行，取证现场完整）；
    - 逐级计数：各事件类型 收到/投影/忽略（:meth:`metrics`）；
    - 坏事件分类：json_parse_failed / json_shape_mismatch / unknown_type
      / over_limit_truncated。
    计数与统计经 :meth:`metrics` 交 runner 落 run_metrics 结构化日志
    （MUST NOT 仅散落 print）。
    """

    def __init__(self, run_id: str, run_dir: str = "") -> None:
        self.run_id = run_id
        # 原始事件 dump 旁路文件（run 目录旁路 = 与 run.jsonl 同目录不同名）。
        # 打开失败不阻断投影（观测是旁路职责）：落 None 后 dump 静默跳过。
        self._dump_path: Optional[Path] = None
        self._dump_fh = None
        if run_dir:
            try:
                run_dir_path = Path(run_dir)
                run_dir_path.mkdir(parents=True, exist_ok=True)
                self._dump_path = run_dir_path / f"{run_id}.dsh-events.jsonl"
                self._dump_fh = self._dump_path.open("a", encoding="utf-8")
            except OSError:
                self._dump_path = None
                self._dump_fh = None
        # 投影状态
        self.session_id: Optional[str] = None
        self.turn_count = 0
        self.usage_input_tokens = 0
        self.usage_output_tokens = 0
        self.usage_observed = False   # 是否见到过携带 usage 的 step_end
        # 逐级计数：各类型 收到/投影/忽略
        self.received: Dict[str, int] = {t: 0 for t in DSH_EVENT_TYPES}
        self.projected: Dict[str, int] = {t: 0 for t in DSH_EVENT_TYPES}
        self.ignored: Dict[str, int] = {t: 0 for t in DSH_EVENT_TYPES}
        self.received_unknown = 0
        # 坏事件分类统计
        self.bad_events: Dict[str, int] = {k: 0 for k in DSH_BAD_EVENT_KINDS}

    # ── 采集入口 ──────────────────────────────────────────────────────

    def ingest(self, line: str, entry: Any) -> List[Dict[str, Any]]:
        """消费一行 stdout：返回投影后的事件列表（可为空 = 全忽略）。

        ``entry`` 为该行 JSON 解析产物（解析失败传 None——原始行仍入 dump，
        坏事件计 json_parse_failed）。claude 读环的既有行为（``entry`` 非法
        即 continue）由「返回空列表」等价表达，读侧零改动。
        """
        self._dump_raw_line(line)
        if not isinstance(entry, dict):
            if entry is None:
                # 解析失败：行不是合法 JSON（code-review d0e9cb6acb88：与
                # 形状不符区分口径，别把合法 JSON 行混进解析失败统计）。
                self.bad_events["json_parse_failed"] += 1
            else:
                # 形状不符：合法 JSON 标量/数组（如 [1,2]），解析并未失败，
                # 单列一类计入统计（消费方兼容：验收判定按「非零即失败」
                # 读键值，报告渲染按 .get 兜底，词表键集合经测试对账）。
                self.bad_events["json_shape_mismatch"] += 1
            return []
        ev_type = entry.get("type")
        if ev_type not in self.received:
            # 未知类型：忽略+计数，MUST NOT 中断流（spec 投影需求）
            self.received_unknown += 1
            self.bad_events["unknown_type"] += 1
            return []
        self.received[ev_type] += 1
        projected = self._project(entry)
        if projected:
            self.projected[ev_type] += 1
        else:
            self.ignored[ev_type] += 1
        return projected

    def _dump_raw_line(self, line: str) -> None:
        if self._dump_fh is None:
            return
        try:
            self._dump_fh.write(line.rstrip("\n") + "\n")
            self._dump_fh.flush()
        except (OSError, ValueError):
            pass

    def close(self) -> None:
        """读环结束时关闭 dump 句柄（幂等）。"""
        if self._dump_fh is not None:
            try:
                self._dump_fh.close()
            except OSError:
                pass
            self._dump_fh = None

    # ── 投影表（probe-findings 事件字段表逐键对账）────────────────────

    def _project(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        ev_type = entry.get("type")
        handler = {
            "session": self._project_session,
            "status": self._project_status,
            "text": self._project_text,
            "thinking": self._project_thinking,
            "tool_call": self._project_tool_call,
            "tool_result": self._project_tool_result,
            "final": self._project_final,
            "error": self._project_error,
        }.get(ev_type)
        if handler is None:
            # 词表漂移兜底（code-review item 6babd9c1790d）：DSH_EVENT_TYPES 与
            # 本表两份人工同步，未来追加类型漏配 handler 时该类型已过 ingest 的
            # received 判定，精确取键会以 KeyError 冲出 stdout 读线程——此处
            # 复用 unknown_type 坏事件路径（计数 + 返回空列表）兜底，不中断流。
            self.received_unknown += 1
            self.bad_events["unknown_type"] += 1
            return []
        return handler(entry)

    def _with_truncated(
        self, entry: Dict[str, Any], out: Dict[str, Any]
    ) -> Dict[str, Any]:
        """``truncated`` 标记透传 + 坏事件超限截断计数（spec 投影需求）。"""
        if entry.get("truncated"):
            out["truncated"] = True
            self.bad_events["over_limit_truncated"] += 1
        return out

    def _project_session(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """session → init（session_id+tools）：run_task_track 消费 init 的
        tools 表判别 Task 工具族，session_id 供 --resume 续跑。"""
        self.session_id = entry.get("sessionId") or None
        init = {
            "type": "system",
            "subtype": "init",
            "session_id": self.session_id,
            "cwd": entry.get("cwd") or "",
            "tools": list(DSH_INIT_TOOLS),
            "harness": "dsh",
        }
        return [self._with_truncated(entry, init)]

    def _project_status(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """status 四相位：turn_start/step_start 忽略；step_end 累计 usage；
        turn_end 计数 num_turns，reason.kind=error 投影为终态 error 行
        （保证「无 final 收场」也在投影层可终判，任务 2.4）。"""
        phase = entry.get("phase")
        if phase == "step_end":
            # usage 判型降级（防御粒度对齐 reason/err 的 isinstance 守卫）：
            # 真值非 dict（list/str/int，版本漂移/流畸形）按无 usage 处理，
            # 不让单事件异常穿透 ingest 杀死 stdout 读线程。
            usage = entry.get("usage")
            if not isinstance(usage, dict):
                usage = {}
            self.usage_input_tokens += _to_int(usage.get("inputTokens"))
            self.usage_output_tokens += _to_int(usage.get("outputTokens"))
            if usage:
                self.usage_observed = True
            return []
        if phase == "turn_end":
            self.turn_count += 1
            reason = entry.get("reason") or {}
            if isinstance(reason, dict) and reason.get("kind") == "error":
                err = reason.get("error") or {}
                message = (
                    err.get("message")
                    if isinstance(err, dict)
                    else None
                ) or json.dumps(reason, ensure_ascii=False)
                code = err.get("code") if isinstance(err, dict) else None
                rendered = f"dsh turn_end error: {message}"
                if code:
                    rendered = f"dsh: {code}: {message}"
                return [
                    {
                        "type": "error",
                        "error": rendered,
                        "exit_code": 1,
                        "harness": "dsh",
                    }
                ]
            return []
        # turn_start / step_start：进度噪音，读侧无消费方
        return []

    def _project_text(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """text → assistant text block（整段下发 = 单 assistant 事件）。"""
        text = entry.get("text")
        if not isinstance(text, str):
            return []
        out = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }
        return [self._with_truncated(entry, out)]

    def _project_thinking(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """thinking → assistant thinking block（探针 mock 未触发该事件，
        字段按 text 同族 ``text`` 防御解析；形状对齐 claude thinking block）。"""
        text = entry.get("text") or entry.get("thinking")
        if not isinstance(text, str):
            return []
        out = {
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": text}]},
        }
        return [self._with_truncated(entry, out)]

    def _project_tool_call(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """tool_call → assistant tool_use block（callId/tool/input →
        id/name/input，probe 结论同形映射）。"""
        call_id = entry.get("callId")
        tool = entry.get("tool")
        if not call_id or not tool:
            return []
        out = {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool,
                        # 判型降级对齐 usage 的 isinstance 守卫（非 dict 真值归 {}）。
                        "input": entry.get("input")
                        if isinstance(entry.get("input"), dict)
                        else {},
                    }
                ]
            },
        }
        return [self._with_truncated(entry, out)]

    def _project_tool_result(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """tool_result → user tool_result block；status=error 物化为
        is_error=True（拦截/失败同样成事件，probe 结论）。"""
        call_id = entry.get("callId")
        if not call_id:
            return []
        is_error = entry.get("status") == "error"
        result = entry.get("result")
        content = result if isinstance(result, str) else json.dumps(
            result, ensure_ascii=False
        ) if result is not None else ""
        out = {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": content,
                        "is_error": is_error,
                    }
                ]
            },
        }
        return [self._with_truncated(entry, out)]

    def _project_final(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """final → result 终态：output/num_turns/session_id/usage 形状；
        usage 按 step_end 求和（可得）或 usage_source: unavailable 降级
        （不伪造数值）；reason.kind=error 物化为 is_error + error 子型。"""
        reason = entry.get("reason") or {}
        is_error = isinstance(reason, dict) and reason.get("kind") == "error"
        text = entry.get("text")
        usage_source = "available" if self.usage_observed else "unavailable"
        out: Dict[str, Any] = {
            "type": "result",
            "subtype": "error_during_execution" if is_error else "success",
            "is_error": is_error,
            "result": text if isinstance(text, str) else "",
            "num_turns": self.turn_count,
            "session_id": self.session_id,
            # usage 形状对齐 SessionTracker._extract_usage_info 四数值键；
            # cost_usd 恒 None（dsh 无成本回传，不伪造）。
            "usage": {
                "input_tokens": self.usage_input_tokens,
                "output_tokens": self.usage_output_tokens,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cost_usd": None,
            },
            "usage_source": usage_source,
        }
        if is_error and isinstance(reason, dict):
            err = reason.get("error") or {}
            message = (
                err.get("message") if isinstance(err, dict) else None
            ) or json.dumps(reason, ensure_ascii=False)
            out["error"] = message
        # final.text 不截断（probe 结论）——无 truncated 透传面
        return [out]

    def _project_error(self, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """error → error 终态（append_run_error 同族形状：error 为 str）。
        探针形态：``{"type":"error","message":...}``（--session-id 采纳
        失败等）；结构化形态 ``{"type":"error","error":{code,message}}``。
        code 拼进口径串（``dsh: <code>: <message>``，与 _project_status
        turn_end 错误分支同口径）供 stderr 分类/circuit 归因——丢码即
        归因退化（BUG-02）。"""
        message = entry.get("message")
        err = entry.get("error")
        code = None
        if isinstance(err, dict):
            code = err.get("code")
            if message is None:
                message = err.get("message")
        elif isinstance(err, str):
            message = err
        if code is None:
            code = entry.get("code")
        rendered = message if isinstance(message, str) and message else (
            json.dumps(entry, ensure_ascii=False)
        )
        if code:
            rendered = f"dsh: {code}: {rendered}"
        return [
            {
                "type": "error",
                "error": rendered,
                "exit_code": 1,
                "harness": "dsh",
            }
        ]

    # ── 可观测性出口 ─────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        """run_metrics 结构化日志载荷（逐级计数 + 坏事件分类 + dump 路径）。"""
        return {
            "harness": "dsh",
            "events_received": dict(self.received),
            "events_projected": dict(self.projected),
            "events_ignored": dict(self.ignored),
            "events_received_unknown": self.received_unknown,
            "bad_events": dict(self.bad_events),
            "raw_event_dump": (
                str(self._dump_path) if self._dump_path is not None else None
            ),
        }


def _to_int(value: Any) -> int:
    """容错整数化（口径与 SessionTracker._extract_usage_info 助手一致：
    假值兜底 0；inf 经 OverflowError 一并入捕）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


# ── adapter 本体 ─────────────────────────────────────────────────────────


@dataclass
class DshAdapterConfig:
    """DshAdapter 部署参数（工厂从配置键装配；harness 包不读配置）。"""

    profile: str = DSH_DEFAULT_PROFILE
    dsh_home: str = ""
    dsh_bin: str = "dsh"
    #: 线协议（pi-ai api 类型：anthropic-messages / openai-completions 等）。
    #: 空 = 不渲染 api 行，Bundle 端缺省 openai-completions（向后兼容）。
    #: provider 链 baseurl 为 Anthropic 兼容形态（claude CLI 遗产，如
    #: bigmodel /api/anthropic）时须配 anthropic-messages，否则 OpenAI 形状
    #: 请求打到 Anthropic 端点即 TRANSPORT 断流（2026-10-14 验收实证）。
    api: str = ""


class DshAdapter:
    """dsh headless 通道 adapter（协议 7 成员 + 扩展成员）。

    扩展成员（duck-typing 消费，runner/prompt_builder 不感知 dsh 字面）：
    - ``event_projector(run_id, run_dir)``：有状态投影器工厂；
    - ``harness_notes()``：prompt {harness_notes} 注入文本；
    - ``is_resume_dead_error(text)``：--session-id 采纳失败判别；
    - ``check_health()``：dispatch 前置健康检查（版本白名单 + Bundle 挂载）。
    """

    def __init__(self, config: Optional[DshAdapterConfig] = None) -> None:
        self._config = config or DshAdapterConfig()
        # 本实例落盘的 patch 临时文件登记表 (path, monotonic 创建时刻)。
        # 回收按龄不按槽（见 _write_model_patch docstring：单槽回收在全局
        # adapter 单例 + 多车道并发派发下会互踩刚写未读的 patch）。
        self._patch_files: List[Tuple[str, float]] = []
        # 登记表读写锁：本 adapter 是全局单例 + 多车道并发派发，
        # _write_model_patch 的「筛存活→整表重赋→append」读改写序列
        # 无锁会互踩丢登记（登记丢失的 patch 失去按龄回收资格 → 泄漏）。
        self._patch_files_lock = threading.Lock()

    # ── 协议成员 ─────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "dsh"

    @property
    def profile(self) -> str:
        return self._config.profile

    @property
    def dsh_home(self) -> str:
        return self._config.dsh_home

    def build_spawn_spec(self, req: SpawnRequest) -> SpawnSpec:
        """SpawnRequest → SpawnSpec（spec「DshAdapter spawn 契约」）。

        argv ``dsh --profile <p> --patch <yml> --json [--session-id <id>]``
        （**不含裸任务词**：``--profile`` 即 app 选择，argv 里的裸
        ``headless`` 会被解析为任务 positional、令 stdin prompt 被忽略，
        见 DSH_APP_NAME 注记）；prompt 全文经 stdin 载荷；cwd=worktree；env
        段按 dsh 口径清除 ANTHROPIC_*/CLAUDE_* 防串扰键；模型经 Bundle
        patch 显式渲染（provider 链 name/baseurl/apikey/model），缺任一要素
        fail-fast（DshSpawnConfigError），绝不回退 dsh 默认档。

        provider 链三要素来源（runner 既有 Provider 路由的 env_overrides）：
        ANTHROPIC_BASE_URL → baseURL、ANTHROPIC_API_KEY → apikey（经
        ``FENIX_DSH_PROVIDER_API_KEY`` 桥接给 dsh）、req.model → model。
        """
        model = (req.model or "").strip()
        if not model:
            raise DshSpawnConfigError(
                "dsh 通道要求显式模型（SpawnRequest.model 为空）——模型经 "
                "Bundle 配置显式渲染，MUST NOT 依赖 dsh 默认档；请为该车道"
                "分配 provider 链（模型路由），或将 agent.harness 改回 claude"
            )
        base_url = (req.env_overrides.get("ANTHROPIC_BASE_URL") or "").strip()
        api_key = (req.env_overrides.get("ANTHROPIC_API_KEY") or "").strip()
        if not base_url or not api_key:
            raise DshSpawnConfigError(
                "dsh 通道要求显式 provider 链分配（baseurl/apikey/model 三要"
                "素由 fenixd provider 链渲染）：当前 SpawnRequest 缺 "
                "ANTHROPIC_BASE_URL 或 ANTHROPIC_API_KEY 覆盖——请为该车道配"
                "置模型路由（assignment），或将 agent.harness 改回 claude"
            )

        patch_path = self._write_model_patch(model=model, base_url=base_url)

        argv: List[str] = [
            self._config.dsh_bin,
            "--profile",
            self._config.profile,
            "--patch",
            patch_path,
            # 注意：此处 MUST NOT 插入裸 "headless"（DSH_APP_NAME 注记）——
            # 它会占用任务 positional 槽位，stdin prompt 被忽略。
            "--json",
        ]
        # --session-id 严格采纳语义：仅 resume 传真实 dsh session id；全新
        # 会话 MUST NOT 传（未知 id → error 事件秒挂，probe 实测）。
        if req.resume_session_id:
            argv += ["--session-id", str(req.resume_session_id)]
        argv += list(req.extra_args or [])

        env = self.build_env(req, api_key=api_key)
        return SpawnSpec(
            argv=argv,
            env=env,
            # prompt 全文经 stdin 载荷（headless 无位置参数时任务走 stdin）
            stdin_payload=req.prompt,
            cwd=str(req.cwd),
        )

    def _write_model_patch(self, model: str, base_url: str) -> str:
        """渲染模型三要素 patch 落系统临时目录（仓树外，stray-first-sight
        约束：不在 repo 树留运行时产物），返回路径。每次 spawn 新建；历史
        patch 按**龄**回收（超过 ``DSH_PATCH_RETENTION_SECONDS`` 才 unlink，
        best-effort，失败绝不阻断 spawn）——patch 只在 dsh 启动首秒被读取，
        保留期是读取窗的数千倍安全边际；早期「单槽 unlink 上一份」设计在
        全局 adapter 单例 + 多车道并发派发下会互踩刚写未读的 patch（
        2026-10-14 夹具 daemon 实证：implementer a1 ENOENT 秒死，attempt
        环重试兜住）。残留上界 ≈ 保留期 × spawn 速率，仍交系统 tmp 清理
        兜底。文件仅含模型三要素、无凭据。"""
        content = render_model_patch_yaml(
            model=model,
            base_url=base_url,
            api_key_env=DSH_API_KEY_ENV,
            api=self._config.api,
        )
        now = time.monotonic()
        # 锁内完成「筛存活→整表重赋」（与并发 append 互斥，杜绝基于旧
        # 快照的整表赋值覆盖掉其它车道刚登记的 patch）；unlink 不碰共享
        # 状态但随筛存顺带执行，锁内耗时为单个 unlink，可忽略。
        with self._patch_files_lock:
            survivors: List[Tuple[str, float]] = []
            for path, created in self._patch_files:
                if now - created < DSH_PATCH_RETENTION_SECONDS:
                    survivors.append((path, created))
                    continue
                try:
                    os.unlink(path)
                except OSError:
                    pass  # 已被系统 tmp 清理/进程重启，静默跳过
            self._patch_files = survivors
        fh = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".yml",
            prefix="fenix-dsh-model-",
            delete=False,
        )
        try:
            fh.write(content)
        except OSError:
            # 写失败（磁盘满等）：文件尚未进 _patch_files 登记表，按龄回收
            # 兜不到——best-effort 摘除后再上抛，避免空/半截 patch 永久
            # 残留系统 tmp（code-review cbf5c41bbad6）。
            try:
                os.unlink(fh.name)
            except OSError:
                pass
            raise
        finally:
            fh.close()
        with self._patch_files_lock:
            self._patch_files.append((fh.name, time.monotonic()))
        return fh.name

    def build_env(self, req: SpawnRequest, api_key: str = "") -> Optional[Dict[str, str]]:
        """按 env_mode 构造 dsh 子进程 env（口径对齐 claude_adapter.build_env，
        差异 = dsh banned 集 + 凭据桥接 + DSH_HOME）。

        - agent-run（主车道）：os.environ 副本 → dsh 防串扰剔除
          （ANTHROPIC_*/CLAUDE_* 前缀 + 显式键，agent_env_keys 单一口径）→
          非禁用的 env_overrides 透传 → FENIX_RUN_PROJECT_ROOT/WORKTREE 注入
          （Bundle 守卫依赖，probe-findings 第四节）→ 凭据桥接 → DSH_HOME；
        - clean：同上但无 FENIX_RUN_* 注入（一次性 spawn 口径）；
        - inherit：返回 None（Popen 完整继承；dsh 通道的防串扰由调用方自担，
          主车道不使用该口径）。

        注意：env_overrides 里的 ANTHROPIC_BASE_URL/ANTHROPIC_API_KEY 是
        provider 链的**渲染来源**（build_spawn_spec 已消费），MUST NOT 透传
        进 dsh 子进程环境（dsh banned 剔除口径覆盖）。
        """
        # 未知 env_mode fail-fast（与 claude_adapter.build_env 同口径）：
        # 分支结构会使未知值静默走「只剔 dsh banned、不剔
        # AGENT_RUN_BANNED_ENV_KEYS、也不注入 FENIX_RUN_*」的混合口径，
        # ambient 的 agent-run 专用键残留进本应 clean/inherit 口径的
        # 一次性 spawn 子进程（跨车道上下文污染）。
        if req.env_mode not in (ENV_MODE_INHERIT, ENV_MODE_CLEAN, ENV_MODE_AGENT_RUN):
            raise ValueError(
                f"不支持的 env_mode 值：{req.env_mode!r}"
                f"（合法值：{ENV_MODE_INHERIT!r}/{ENV_MODE_CLEAN!r}/{ENV_MODE_AGENT_RUN!r}）"
            )
        if req.env_mode == ENV_MODE_INHERIT:
            return None

        from core.agent_env_keys import (
            AGENT_RUN_BANNED_ENV_KEYS,
            dsh_banned_env_keys,
            is_dsh_banned_env_key,
        )

        env = os.environ.copy()
        banned = dsh_banned_env_keys(env)
        for key in banned:
            env.pop(key, None)
        if req.env_mode == ENV_MODE_CLEAN:
            # 一次性 spawn 口径（与 claude build_env clean 对齐）：agent-run
            # 专用上下文键不进子进程环境（单一口径来源）。
            for key in AGENT_RUN_BANNED_ENV_KEYS:
                env.pop(key, None)

        # 覆写键按**键自身**匹配 dsh banned 口径（is_dsh_banned_env_key），
        # 不按 ambient banned 清单成员判断——daemon 环境无 ANTHROPIC_* 键时
        # 清单为空，覆写的 ANTHROPIC_AUTH_TOKEN/ANTHROPIC_MODEL 会原样回灌
        # （BUG-01）。consumed 两键是 provider 链渲染来源，同样不透传。
        consumed = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")
        for key, value in (req.env_overrides or {}).items():
            if key in consumed or is_dsh_banned_env_key(key):
                continue
            env[key] = value

        if req.env_mode == ENV_MODE_AGENT_RUN:
            # worktree 隔离纵深：Bundle 守卫（guards.ts）按这两个键拦主树写
            env["FENIX_RUN_PROJECT_ROOT"] = str(req.project_root)
            env["FENIX_RUN_WORKTREE"] = (
                str(req.cwd) if str(req.cwd) != str(req.project_root) else ""
            )

        # 凭据桥接：provider 链 apikey → apiKeyEnv 指名变量（patch 渲染恒用
        # DSH_API_KEY_ENV）。clean 口径一次性 spawn 同样需要（dsh 无凭据即
        # MISSING_CREDENTIAL 秒挂）。
        if api_key:
            env[DSH_API_KEY_ENV] = api_key

        if self._config.dsh_home:
            env["DSH_HOME"] = str(self._config.dsh_home)
        return env

    def normalize_event(self, raw: Any) -> Optional[List[Dict[str, Any]]]:
        """无状态投影入口（协议成员）。

        dsh 的投影需要 per-run 状态（usage 求和/turn_end 计数），经
        :meth:`event_projector` 走有状态管线；本成员保留协议形态：读环未
        装配投影器时（不该发生——runner 对带 event_projector 的 adapter 恒
        走管线），把 dict 原样透传、非 dict 丢弃。
        """
        if isinstance(raw, dict):
            return [raw]
        return None

    def classify_stderr(self, line: str) -> str:
        """stderr 单行分类：dsh 错误码文本改写为 claude 形状后走既有判别
        （design D2——分类枚举与降噪口径零改动）。

        ``dsh: <code>: <message>`` / ``dsh: startup failed: …`` 中不命中
        错误码表的行（启动期诊断、MISSING_CREDENTIAL 等）不命中任何
        claude 判别 → generic（配置错误不入熔断，探针结论）。"""
        from core.agent_runner.provider_circuit import (
            ProviderCircuit,
            is_cli_stderr_noise,
            translate_dsh_error_text,
        )

        if not line:
            return STDERR_CLASS_GENERIC
        translated = translate_dsh_error_text(line)
        if ProviderCircuit.classify_unrecognized_model_error(translated):
            return STDERR_CLASS_UNRECOGNIZED_MODEL
        # dsh 无 [claude-code:*] 前缀族；is_cli_stderr_noise 对 dsh 行恒 False，
        # 保留调用形态与 claude 通道对齐（降噪口径单一来源）。
        if line.startswith("[claude-code:") or is_cli_stderr_noise(line):
            return STDERR_CLASS_CLI_NOISE
        return STDERR_CLASS_GENERIC

    def extract_result(
        self, events: Sequence[Any], exit_code: Optional[int] = None
    ) -> Dict[str, Any]:
        """终态 result 提取（键形状与 ClaudeAdapter.extract_result 全等）。

        usage 分支（spec「usage 降级标记」）：投影器已按 step_end 求和并落
        ``usage_source``（available/unavailable）；本成员原样透传 result 事件
        的 usage 与 usage_source，unavailable 时不伪造数值（usage 数值键保持
        求和产物或 0，cost_usd 恒 None），metrics 标记由 runner 消费。

        unobserved 分支取值与 claude 通道有意分歧（键形状全等、取值不同）：
        dsh 事件流契约「``final`` 结尾 / ``error`` 无 final」——无 result
        事件即异常终态，故 is_error=True、subtype=""；claude 通道无 result
        通常是强杀/超时的观测兜底而非失败确证（现状平移 is_error=False）。
        该方向由 test_unobserved_returns_zero_not_fabricated 锚定，防后续按
        「键形状全等」顺手统一改错归因。
        """
        last: Optional[Dict[str, Any]] = None
        for e in events:
            if isinstance(e, dict) and e.get("type") == "result":
                last = e
        if last is None:
            return {
                "observed": False,
                "output": "",
                "turns": 0,
                "session_id": None,
                "usage_info": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cost_usd": None,
                    "unobserved": True,
                    "usage_source": "unobserved",
                },
                "is_error": True,
                "subtype": "",
                "api_error_status": None,
                "result_text": "",
                "usage_source": "unobserved",
            }
        usage = last.get("usage") or {}
        usage_info = {
            "input_tokens": _to_int(usage.get("input_tokens")),
            "output_tokens": _to_int(usage.get("output_tokens")),
            "cache_creation_input_tokens": _to_int(
                usage.get("cache_creation_input_tokens")
            ),
            "cache_read_input_tokens": _to_int(
                usage.get("cache_read_input_tokens")
            ),
            "cost_usd": usage.get("cost_usd"),
            # usage 分支标记随 usage_info 流转（runner _log_run_metrics 按该键
            # 落 usage_source 指标；available=step_end 求和，unavailable=降级）
            "usage_source": last.get("usage_source") or "available",
        }
        return {
            "observed": True,
            "output": last.get("result") or "",
            "turns": _to_int(last.get("num_turns")),
            "session_id": last.get("session_id"),
            "usage_info": usage_info,
            "is_error": bool(last.get("is_error")),
            "subtype": last.get("subtype") or "",
            "api_error_status": last.get("api_error_status"),
            "result_text": last.get("result") or "",
            "usage_source": last.get("usage_source") or "available",
        }

    def process_patterns(self) -> List[str]:
        """agent 进程 argv[0] 识别 patterns（proc_utils 清扫豁免锚点 /
        dashboard 活跃 agent 面板消费）。"""
        return ["dsh", "dsh.exe"]

    def worktree_pgrep_patterns(self, spec_name: str) -> List[str]:
        """worktree 存活 pgrep -f patterns（与 claude 通道同构：构造单一
        来源为 :func:`default_worktree_pgrep_patterns`；run_id 段出现在
        argv 中由 ``-`` 连接，子串匹配语义与 admin_monitor 既有判定一致）。"""
        return default_worktree_pgrep_patterns(spec_name)

    def capabilities(self) -> HarnessCapabilities:
        """能力对账卡（probe-findings 判定）：

        - stream_json_output=True：``--json`` NDJSON 事件流（投影前提）；
        - resume_supported=True：``--session-id`` 采纳语义（严格但可用）；
        - isolated_settings_supported=False：无 CLAUDE_CONFIG_DIR 等价物，
          隔离经 DSH_HOME + 独立 profile 实现（部署侧职责）；
        - max_turns_enforcement="daemon-side"：CLI 无该 flag，与 claude 同
          由 runner 轮询环强制（design D4）；
        - 批内并行：spec Non-Goal（capabilities 如实声明，降级串行可接受
          ——并行判定由 runner 侧按 process_patterns/预算治理，本卡不新增
          字段）。
        """
        return HarnessCapabilities(
            name=self.name,
            stream_json_output=True,
            resume_supported=True,
            isolated_settings_supported=False,
            max_turns_enforcement="daemon-side",
            process_patterns=self.process_patterns(),
        )

    # ── 扩展成员（duck-typing 消费）──────────────────────────────────

    def event_projector(self, run_id: str, run_dir: str = "") -> DshEventProjector:
        """有状态投影器工厂（runner 读环按 getattr 探测装配）。"""
        return DshEventProjector(run_id, run_dir)

    def harness_notes(self) -> str:
        """prompt ``{harness_notes}`` 注入文本（design D6：dsh 注入 headless
        行为模型——无交互、stdin 喂入、产物以 result gate 为准；注入位形如
        「非交互派发（<本值>）下」，与 claude 原文 `` `claude -p` `` 同位替
        换，prompt 差异全部收敛在该替换位）。"""
        return (
            "`dsh headless --json`——任务经 stdin 喂入、无交互追问通道、"
            "产物以 result gate 校验为准"
        )

    def is_resume_dead_error(self, error_text: str) -> bool:
        """``--session-id`` 采纳失败判别（runner resume 回退路径 duck-typing
        消费；claude 通道既有「No conversation found」判定零改动）。"""
        if not error_text:
            return False
        if DSH_SESSION_ADOPT_DEAD_MARKER in error_text:
            return True
        # 被持有 refuse / cwd 不符拒绝：同属 fail-loud 家族，签名未逐字实测
        # （探针仅覆盖未知 id），按 session 否定语义宽松兜底（正则收进
        # DSH_SESSION_ADOPT_FALLBACK_PATTERN 常量，当前行为由单测锚定）。
        return bool(
            re.search(
                DSH_SESSION_ADOPT_FALLBACK_PATTERN,
                error_text,
                re.IGNORECASE,
            )
        )

    def session_bookkeeping_key(self, run_id: str) -> str:
        """fenixd 侧 session 记账键（单一来源 SessionTracker.dsh_session_key；
        runner 回退留痕经 duck-typing 消费，不感知 dsh 字面）。"""
        from core.agent_runner.session import SessionTracker

        return SessionTracker.dsh_session_key(run_id)

    # ── 健康检查（design D5）─────────────────────────────────────────

    def check_health(self, timeout: float = 20.0) -> None:
        """dispatch 前置健康检查：版本白名单 + Bundle 挂载探测。

        不满足抛 :class:`HarnessHealthError`（错误信息含修复指引）；通过则
        返回 None。MUST NOT 代跑（spec：检查不通过 dispatch 以错误失败）。
        """
        # 1) dsh 可用 + 版本白名单
        try:
            proc = subprocess.run(
                [self._config.dsh_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._health_env(),
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise HarnessHealthError(
                f"dsh 不可用（{e}）：请安装 dsh（npm install -g "
                f"@deepseek-ai/dsh@{DSH_VERSION_WHITELIST[0]}，详见 "
                f"dsh-bundle/README.md 部署段），或将 agent.harness 改回 claude"
            ) from e
        if proc.returncode != 0:
            raise HarnessHealthError(
                f"dsh --version 失败（exit {proc.returncode}）："
                f"{(proc.stderr or proc.stdout or '').strip()[:500]}——请安装"
                f" dsh（npm install -g @deepseek-ai/dsh@{DSH_VERSION_WHITELIST[0]}"
                f"），或将 agent.harness 改回 claude"
            )
        # 版本识别：取 stdout 首行；stdout 为空时回退 stderr 首行（CLI 惯例
        # 差异——版本走 stderr 的形态不该被误报成「版本不在白名单」，排障
        # 方向别被带偏；两通道皆空才落 version '' 分支）。首行可能带前缀
        # 文案/构建信息（如「dsh 0.2.0-rc.2」），整行精确比对对输出格式
        # 脆弱（code-review 6a1a3649e5d1）——改用正则从首行提取 semver
        # 形态再比对白名单：多候选时优先取白名单命中者（容忍行内含其它
        # 版本样数字段），提取不到 semver 则维持整行原样落白名单失败分支
        # （报错文案仍呈现原始现场）。
        first_line = ""
        for stream in (proc.stdout, proc.stderr):
            stripped = (stream or "").strip()
            if stripped:
                first_line = stripped.splitlines()[0].strip()
                break
        candidates = re.findall(r"\d+\.\d+\.\d+[-\w.]*", first_line)
        version = next(
            (c for c in candidates if c in DSH_VERSION_WHITELIST),
            candidates[0] if candidates else first_line,
        )
        if version not in DSH_VERSION_WHITELIST:
            raise HarnessHealthError(
                f"dsh 版本 {version!r} 不在兼容白名单 "
                f"{list(DSH_VERSION_WHITELIST)}（版本漂移会破坏事件投影契约）"
                f"——请安装 {' / '.join(DSH_VERSION_WHITELIST)}（npm install -g "
                f"@deepseek-ai/dsh@{DSH_VERSION_WHITELIST[0]}），或更新 "
                f"dsh-bundle 版本兼容表后同步本白名单；也可将 agent.harness "
                f"改回 claude"
            )
        # 2) Bundle 挂载探测：--dump-config 产物含 fenix-model-config 条目
        try:
            dump = subprocess.run(
                [
                    self._config.dsh_bin,
                    "--profile",
                    self._config.profile,
                    "--dump-config",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._health_env(),
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise HarnessHealthError(
                f"dsh 配置探测失败（{e}）：profile "
                f"{self._config.profile!r} 无法启动——按 dsh-bundle/README.md "
                f"部署段创建 Bundle 挂载 profile（dsh --profile "
                f"{self._config.profile} --from-default-profile headless 后 "
                f"plugin add link:<repo>/dsh-bundle），或将 agent.harness 改回 "
                f"claude"
            ) from e
        if dump.returncode != 0:
            raise HarnessHealthError(
                f"dsh profile {self._config.profile!r} 不存在或无法组合"
                f"（exit {dump.returncode}）：{(dump.stderr or '').strip()[:500]}"
                f"——按 dsh-bundle/README.md 部署段创建 Bundle 挂载 profile，"
                f"或将 agent.harness 改回 claude"
            )
        if DSH_BUNDLE_MOUNT_MARKER not in (dump.stdout or ""):
            raise HarnessHealthError(
                f"dsh profile {self._config.profile!r} 未挂载 fenix-dsh-bundle"
                f"（--dump-config 无 {DSH_BUNDLE_MOUNT_MARKER} 条目）：模型三"
                f"要素显式渲染与 Task 工具族均依赖 Bundle——按 "
                f"dsh-bundle/README.md 部署段以 link: 形态挂载（DSH_HOME 隔离"
                f"可用配置键 agent.dsh_home 指定），或将 agent.harness 改回 "
                f"claude"
            )
        # 3) headless 运行时在场：bundle 清单缺 @deepseek-ai/dsh-headless 时
        #    dump-config 组合树无 headless-runner 条目，headless 命令会在
        #    loader.await() 静默永等（不 fail-fast 就放出注定悬挂的 spawn）。
        if DSH_HEADLESS_ENTRY_MARKER not in (dump.stdout or ""):
            raise HarnessHealthError(
                f"dsh profile {self._config.profile!r} 未挂载 dsh-headless "
                f"运行时（--dump-config 无 {DSH_HEADLESS_ENTRY_MARKER} 条目）："
                f"headless 命令将静默永等——在 profile 的 "
                f"dsh.profile.bundles 清单补 @deepseek-ai/dsh-headless"
                f"（dsh plugin --profile {self._config.profile} add "
                f"@deepseek-ai/dsh-headless 或手工编辑 "
                f"$DSH_HOME/profiles/{self._config.profile}/package.json），"
                f"或将 agent.harness 改回 claude"
            )

    def _health_env(self) -> Dict[str, str]:
        """健康检查子进程 env（DSH_HOME 隔离透传）。"""
        env = os.environ.copy()
        if self._config.dsh_home:
            env["DSH_HOME"] = str(self._config.dsh_home)
        return env
