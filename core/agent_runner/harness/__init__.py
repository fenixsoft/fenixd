"""core/agent_runner/harness — agent harness 适配层（add-harness-adapter-layer）。

包内结构（ADR-271）：

- :mod:`.protocol` — 进程边界协议与数据类（SpawnRequest/SpawnSpec/
  HarnessCapabilities、HarnessAdapter 七成员协议、分类词表）
- :mod:`.claude_adapter` — claude CLI adapter（现状全量平移，字节级等价）
- :mod:`.one_shot` — 一次性 spawn 收编入口 run_one_shot

依赖方向（design D8）：本包只依赖 stdlib 与既有纯工具模块，MUST NOT import
runner/event_bus/admin_monitor 等消费侧模块；消费侧单向 import 本包。

公共入口：

- :func:`resolve_adapter` — harness 名 → adapter 实例（dsh 未部署阶段
  fail-fast）
- :func:`set_current_adapter` / :func:`get_current_adapter` — 进程级当前
  adapter 持有（daemon 装配点注入一次；消费侧 proc_utils/event_bus/
  admin_monitor/fenix_dashboard 经 :func:`current_process_patterns` /
  :func:`current_worktree_pgrep_patterns` 取识别 patterns，未注入时惰性
  回落 claude——即变更前行为，零行为变化）
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from core.agent_runner.harness.protocol import (
    ENV_MODE_AGENT_RUN,
    ENV_MODE_CLEAN,
    ENV_MODE_INHERIT,
    HARNESS_ADAPTER_MEMBERS,
    PROMPT_TRANSPORT_ARGV,
    PROMPT_TRANSPORT_STDIN,
    STDERR_CLASS_CLI_NOISE,
    STDERR_CLASS_GENERIC,
    STDERR_CLASS_UNRECOGNIZED_MODEL,
    HarnessAdapter,
    HarnessCapabilities,
    SpawnRequest,
    SpawnSpec,
)
from core.agent_runner.harness.claude_adapter import (
    ISOLATED_SETTINGS_SCHEMA_VERSION,
    ClaudeAdapter,
    build_env,
    build_isolated_settings,
    ensure_agent_config_dir,
)

__all__ = [
    # protocol
    "ENV_MODE_AGENT_RUN",
    "ENV_MODE_CLEAN",
    "ENV_MODE_INHERIT",
    "HARNESS_ADAPTER_MEMBERS",
    "PROMPT_TRANSPORT_ARGV",
    "PROMPT_TRANSPORT_STDIN",
    "STDERR_CLASS_CLI_NOISE",
    "STDERR_CLASS_GENERIC",
    "STDERR_CLASS_UNRECOGNIZED_MODEL",
    "HarnessAdapter",
    "HarnessCapabilities",
    "SpawnRequest",
    "SpawnSpec",
    # claude_adapter
    "ClaudeAdapter",
    "ISOLATED_SETTINGS_SCHEMA_VERSION",
    "build_env",
    "build_isolated_settings",
    "ensure_agent_config_dir",
    # 工厂与进程级持有
    "VALID_HARNESS_VALUES",
    "HarnessNotDeployedError",
    "resolve_adapter",
    "resolve_adapter_from_config",
    "set_current_adapter",
    "get_current_adapter",
    "current_process_patterns",
    "current_worktree_pgrep_patterns",
]

# agent.harness 合法值（config 校验/settings_routes/config_admin 三处共用单源；
# dsh 由 add-dsh-adapter-integration 部署 adapter 后才可保存生效）
VALID_HARNESS_VALUES = ("claude", "dsh")


class HarnessNotDeployedError(RuntimeError):
    """harness 已配置但 adapter 未部署（当前仅 agent.harness=dsh 触发）。"""


def resolve_adapter(harness: str) -> HarnessAdapter:
    """harness 名 → adapter 实例（工厂唯一入口）。

    - ``claude`` → :class:`ClaudeAdapter`（现状平移，行为零变化）
    - ``dsh`` → :exc:`HarnessNotDeployedError`，错误信息含「dsh adapter 未部署」
      ——spec harness-config「dsh 值 fail-fast（本阶段）」：MUST NOT 静默回退
      claude 代跑
    - 其余值：调用方（ConfigLoader.get_harness）负责先归一化；本工厂对未知
      值 fail-fast（ValueError），不做静默回退
    """
    if harness == "claude":
        return ClaudeAdapter()
    if harness == "dsh":
        raise HarnessNotDeployedError(
            "dsh adapter 未部署（add-dsh-adapter-integration 交付）；"
            "请将 agent.harness 改回 claude"
        )
    raise ValueError(f"不支持的 harness 值：{harness!r}（合法值 {VALID_HARNESS_VALUES}）")


def resolve_adapter_from_config(config: Optional[Dict[str, Any]]) -> HarnessAdapter:
    """从 config 读 agent.harness 并解析 adapter（归一化语义在 ConfigLoader）。

    ConfigLoader.get_harness 负责「缺省 claude / 非法值回退+告警」；dsh 在
    这里经 resolve_adapter fail-fast。
    """
    from core.config import ConfigLoader

    return resolve_adapter(ConfigLoader.get_harness(config or {}))


# ── 进程级当前 adapter 持有 ──────────────────────────────────────────────
# daemon/独立进程入口（fenixd.py main、bin/fenix_dashboard、一次性 spawn 载体）
# 装配时注入一次；此后消费侧只读。锁仅护「检查-注入」竞态，读取路径无锁
# （Python 属性读原子）。
_current_adapter: Optional[HarnessAdapter] = None
_current_adapter_lock = threading.Lock()


def set_current_adapter(adapter: HarnessAdapter) -> None:
    """注入进程级当前 adapter（daemon 装配点调用；重复注入以最后一次为准）。"""
    global _current_adapter
    with _current_adapter_lock:
        _current_adapter = adapter


def get_current_adapter() -> HarnessAdapter:
    """取进程级当前 adapter；未注入时惰性回落 claude adapter。

    回落语义即「变更前行为」（全仓只有 claude 一种 harness），保证四处识别
    消费点在本 SPEC 交付后、装配点接线前的任何中间状态都与现状一致。
    """
    global _current_adapter
    adapter = _current_adapter
    if adapter is not None:
        return adapter
    with _current_adapter_lock:
        if _current_adapter is None:
            _current_adapter = ClaudeAdapter()
        return _current_adapter


def current_process_patterns() -> List[str]:
    """当前 harness 的 agent 进程识别 patterns（proc_utils/fenix_dashboard 消费）。"""
    return get_current_adapter().process_patterns()


def current_worktree_pgrep_patterns(spec_name: str) -> List[str]:
    """当前 harness 的 worktree 存活 pgrep patterns（admin_monitor/event_bus 消费）。"""
    return get_current_adapter().worktree_pgrep_patterns(spec_name)
