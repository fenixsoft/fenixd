"""core/agent_runner/harness — agent harness 适配层（add-harness-adapter-layer）。

包内结构（ADR-271）：

- :mod:`.protocol` — 进程边界协议与数据类（SpawnRequest/SpawnSpec/
  HarnessCapabilities、HarnessAdapter 协议（spec 七成员 + 扩展成员
  worktree_pgrep_patterns，同收 HARNESS_ADAPTER_MEMBERS 单源）、分类词表）
- :mod:`.claude_adapter` — claude CLI adapter（现状全量平移，字节级等价）
- :mod:`.dsh_adapter` — dsh headless 通道 adapter（DshAdapter 经 DshEventProjector
  把 dsh 事件流投影为 claude stream-json canon 形状；含部署参数装配
  DshAdapterConfig 与 dispatch 前置健康检查 check_health）
- :mod:`.one_shot` — 一次性 spawn 收编入口 run_one_shot

依赖方向（design D8）：本包只依赖 stdlib 与既有纯工具模块，MUST NOT import
runner/event_bus/admin_monitor 等消费侧模块；消费侧单向 import 本包。

公共入口：

- :func:`resolve_adapter` — harness 名 → adapter 实例（claude/dsh 双通道；
  dsh 的就绪性由 dispatch 前置健康检查 fail-fast 把关）
- :func:`set_current_adapter` / :func:`get_current_adapter` — 进程级当前
  adapter 持有（daemon 装配点注入一次；消费侧 proc_utils/event_bus/
  admin_monitor/fenix_dashboard 经 :func:`current_process_patterns` /
  :func:`current_worktree_pgrep_patterns` 取识别 patterns，未注入时惰性
  回落 claude——即变更前行为，零行为变化）
"""

from __future__ import annotations

import logging
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
from core.agent_runner.harness.dsh_adapter import (
    DSH_DEFAULT_PROFILE,
    DshAdapter,
    DshAdapterConfig,
    DshSpawnConfigError,
    HarnessHealthError,
)

_logger = logging.getLogger("fenixd.agent_runner.harness")

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
    # dsh_adapter（add-dsh-adapter-integration）
    "DSH_DEFAULT_PROFILE",
    "DshAdapter",
    "DshAdapterConfig",
    "DshSpawnConfigError",
    "HarnessHealthError",
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
# dsh 已由 add-dsh-adapter-integration 部署 DshAdapter，保存与生效同词表）
VALID_HARNESS_VALUES = ("claude", "dsh")


class HarnessNotDeployedError(RuntimeError):
    """harness 已配置但 adapter 未部署（历史形态：SPEC-1 期间 agent.harness=dsh
    触发；add-dsh-adapter-integration 注册 DshAdapter 后工厂不再抛出，保留类与
    runner 侧防御性 catch 供未来未部署通道复用）。"""


def _dsh_str_param(config: Dict[str, Any], key: str) -> str:
    """dsh 部署参数读取归一化（resolve_adapter 三键共用）：仅字符串采纳。

    ConfigLoader.get 不做类型归一化：未配置（None）/空串/纯空白静默兜底
    空串（由调用方落各自缺省，既有行为）；非字符串类型误写（如 123/true/
    非空列表）经 ``str()`` 会变成 ``"123"``/``"True"``/``"['a']"`` 垃圾值
    流入 spawn 参数，dsh 健康检查或 spawn 报错携带该值时易误判为配置
    「被改过」——故 WARNING 告警（口径同 get_harness 非法值「回退+告警」
    的配置面容错）并回退空串。
    """
    from core.config import ConfigLoader

    raw = ConfigLoader.get(config, key, None)
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    _logger.warning(
        "dsh 部署参数 %s 类型误写：%r（应为字符串）；按空值兜底缺省", key, raw)
    return ""


def resolve_adapter(harness: str, config: Optional[Dict[str, Any]] = None) -> HarnessAdapter:
    """harness 名 → adapter 实例（工厂唯一入口）。

    - ``claude`` → :class:`ClaudeAdapter`（现状平移，行为零变化）
    - ``dsh`` → :class:`DshAdapter`（add-dsh-adapter-integration 5.1 注册，
      解除 SPEC-1 的 fail-fast；部署参数 agent.dsh_profile/agent.dsh_home
      经 config 装配，健康检查在 dispatch 前置段执行——本工厂不做 IO 探测，
      保持纯函数语义）
    - 其余值：调用方（ConfigLoader.get_harness）负责先归一化；本工厂对未知
      值 fail-fast（ValueError），不做静默回退
    """
    if harness == "claude":
        return ClaudeAdapter()
    if harness == "dsh":
        from core.config import ConfigLoader

        cfg = config or {}
        # 部署参数：agent.dsh_profile（缺省 Bundle README 约定名）/ agent.dsh_home
        # （缺省空=继承进程环境；DSH_HOME 隔离部署由此键指定）/ agent.dsh_api
        # （线协议：provider 链 baseurl 为 Anthropic 兼容形态时须配
        # anthropic-messages；缺省空=openai-completions）。归一口径见
        # _dsh_str_param：未配置/空串静默兜底缺省，非字符串类型误写告警回退。
        profile = _dsh_str_param(cfg, "agent.dsh_profile")
        dsh_home = _dsh_str_param(cfg, "agent.dsh_home")
        dsh_api = _dsh_str_param(cfg, "agent.dsh_api")
        return DshAdapter(DshAdapterConfig(
            profile=profile or DSH_DEFAULT_PROFILE, dsh_home=dsh_home,
            api=dsh_api))
    raise ValueError(f"不支持的 harness 值：{harness!r}（合法值 {VALID_HARNESS_VALUES}）")


def resolve_adapter_from_config(config: Optional[Dict[str, Any]]) -> HarnessAdapter:
    """从 config 读 agent.harness 并解析 adapter（归一化语义在 ConfigLoader）。

    ConfigLoader.get_harness 负责「缺省 claude / 非法值回退+告警」；dsh 经
    注册的 DshAdapter 返回（部署参数随 config 装配），健康检查由 dispatch
    前置段消费 adapter 的 check_health 扩展成员。
    """
    from core.config import ConfigLoader

    return resolve_adapter(ConfigLoader.get_harness(config or {}), config)


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
