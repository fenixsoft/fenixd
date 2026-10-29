"""harness/claude_adapter.py — claude CLI harness adapter（add-harness-adapter-layer 2.x）。

「平移不是重写」（design D3）：命令构造、隔离 settings（原
``AgentRunner._build_isolated_settings``/``_ensure_agent_config_dir``）、env
路由与 banned env 清理（原 ``_run_claude`` 5676-5746 段与
core.agent_env_keys 消费点）整体平移进本模块，对同一 SpawnRequest 产出与
平移前逐字节相等的 SpawnSpec（快照测试 test_harness_claude_snapshot.py
以平移前金样本锁定）。``_run_claude`` 的「有意单体」注记由本模块替代其
命令构造职能后解除。

依赖方向（design D8）：本模块只依赖 stdlib 与既有纯工具模块
（core.agent_env_keys / core.agent_runner.session / core.agent_runner.
provider_circuit——后两者惰性 import），MUST NOT import runner/event_bus/
admin_monitor。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.agent_env_keys import AGENT_RUN_BANNED_ENV_KEYS
from core.agent_runner.harness.protocol import (
    ENV_MODE_AGENT_RUN,
    ENV_MODE_CLEAN,
    ENV_MODE_INHERIT,
    PROMPT_TRANSPORT_ARGV,
    PROMPT_TRANSPORT_STDIN,
    STDERR_CLASS_CLI_NOISE,
    STDERR_CLASS_UNRECOGNIZED_MODEL,
    STDERR_CLASS_GENERIC,
    HarnessAdapter,
    HarnessCapabilities,
    SpawnRequest,
    SpawnSpec,
    default_worktree_pgrep_patterns,
)

__all__ = [
    "ClaudeAdapter",
    "build_isolated_settings",
    "ensure_agent_config_dir",
    "ISOLATED_SETTINGS_SCHEMA_VERSION",
]


# fix-agent-lane-efficiency D1：隔离 settings.json 内容版本标记（原
# AgentRunner.ISOLATED_SETTINGS_SCHEMA_VERSION 单点平移）。旧版本（无 env
# 子代理模型映射）settings.json 在已部署机器上已存在（ensure_agent_config_dir
# 现行「marker 已存在即 return」会永不重建）——实现版本标记 + 内容不匹配时
# 原子重写，使新映射在存量隔离目录上也生效。
ISOLATED_SETTINGS_SCHEMA_VERSION = 2


def build_isolated_settings(
    project_root: Path | str, provider_model: str = "", config: Optional[dict] = None
) -> dict:
    """构造隔离 settings.json：enabledPlugins / hooks / env 子代理模型映射。

    原迹：AgentRunner._build_isolated_settings（spec D2/D3），除 self 依赖
    收敛为显式参数（project_root/config）外逐行平移。从 ~/.claude/settings.json
    复制 enabledPlugins（缺省 superpowers）。hooks 从 .fenix/agent-settings.json
    复制（PreToolUse block-image-read）。不复制宿主 ~/.claude/settings.json 的
    env 模型名映射——那属于 cc-switch 网关、对直连 Provider 无用且有毒化子代
    理解析的风险（如陈旧 hy3）。Provider 的 ANTHROPIC_MODEL/BASE_URL/API_KEY
    经进程 env 注入。

    provider_model（直连 Provider 车道）非空时，额外注入一段**按该 provider
    重算**的 env 模型映射——CLAUDE_CODE_SUBAGENT_MODEL 与
    ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL 均映射到 provider 自身模型，
    取值优先级为 agents.subagent_model_override（非空）→ provider_model。这使
    子代理 tier 解析永不回落到宿主 cc-switch 的官方模型名（直连 Provider 无此
    模型 → model_not_found 404）。provider_model 为空（未分配 provider，走默认
    网关）时不写任何 env——该路径行为与变更前逐字节一致。
    """
    settings: Dict[str, Any] = {}
    source: Dict[str, Any] = {}
    home_settings = Path.home() / ".claude" / "settings.json"
    try:
        if home_settings.is_file():
            loaded = json.loads(home_settings.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                source = loaded
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # 非法 UTF-8 字节（磁盘损坏/外部工具误写）与坏 JSON 同路降级为空
        # source（口径对齐 admin_store._read_unlocked）。
        source = {}

    plugins = source.get("enabledPlugins")
    if isinstance(plugins, dict) and plugins:
        settings["enabledPlugins"] = plugins
    else:
        settings["enabledPlugins"] = {"superpowers@claude-plugins-official": True}

    agent_settings = Path(project_root) / ".fenix" / "agent-settings.json"
    if agent_settings.is_file():
        try:
            loaded = json.loads(agent_settings.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("hooks"), dict):
                settings["hooks"] = loaded["hooks"]
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            pass

    if provider_model:
        # provider 作用域内重建的子代理模型映射（非复制宿主 cc-switch 映射）。
        # 取值优先级：agents.subagent_model_override（非空）→ provider 自身 model。
        from core.config import ConfigLoader as _CLSubagentModel

        cfg = config or {}
        subagent_model = (
            _CLSubagentModel.get_subagent_model_override(cfg)
            or provider_model
        )
        settings["env"] = {
            "CLAUDE_CODE_SUBAGENT_MODEL": subagent_model,
            "ANTHROPIC_DEFAULT_OPUS_MODEL": subagent_model,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": subagent_model,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": subagent_model,
        }
    return settings


# fenixd. 可传播层级（对齐 one_shot.py；core/ 禁止裸 getLogger(__name__)）。
# 隔离配置写失败是不向上抛的降级语义，无留痕则运维无法察觉 agent 以缺
# hooks/模型映射的降级配置运行（code-review item e207cc39ba4b）。
logger = logging.getLogger("fenixd.agent_runner.harness.claude_adapter")


def ensure_agent_config_dir(
    project_root: Path | str,
    provider_name: str,
    provider_model: str = "",
    config: Optional[dict] = None,
) -> Path:
    """按需生成并返回 Provider 的隔离配置目录（spec D1/D2/D5）。

    原迹：AgentRunner._ensure_agent_config_dir，除 self 依赖收敛为显式参数
    外逐行平移（含 mkstemp 原子写与 symlink 补建两条 code-review 修复）。

    目录：<project_root>/.fenix/agent-config/<provider_name>/，含 settings.json
    与指向 ~/.claude 的 skills/plugins symlink（源目录不存在则跳过，优雅降级）。
    幂等：settings.json 已存在且内容与将写入内容一致（含 schema 版本标记）则
    跳过重建；存在旧版/内容不匹配时原子重写（tempfile + os.replace，保留既有
    symlink）。并发首次创建由原子 mkdir + temp+rename 写文件兜底。
    """
    project_root = Path(project_root)
    cfg_dir = project_root / ".fenix" / "agent-config" / provider_name
    marker = cfg_dir / "settings.json"
    settings = build_isolated_settings(project_root, provider_model, config)
    settings["_schema_version"] = ISOLATED_SETTINGS_SCHEMA_VERSION
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # 不向上抛的降级语义不变，但按 e207cc39ba4b 同口径 WARNING 留痕：
        # 目录缺席时 settings.json 与 skills/plugins symlink 均无从谈起。
        logger.warning(
            "ensure_agent_config_dir: 隔离配置目录创建失败"
            "（agent 以降级配置运行，无 hooks/模型映射/symlink）: %s", e,
        )
        return cfg_dir

    def _write_atomic() -> None:
        # mkstemp 生成唯一临时文件（固定 .settings.tmp 在并发首建/重写时交错
        # 截断写坏 settings.json），与 _copyback_run_result 的 _write_atomic
        # 同款手法。
        fd, tmp_name = tempfile.mkstemp(
            prefix=".settings.", suffix=".tmp", dir=str(cfg_dir))
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(settings, ensure_ascii=False, indent=2))
                # code-review item 161e36c1913c：replace 前刷缓冲并 fsync，
                # 与 admin_store._write_unlocked 原子写模式对齐，掉电时
                # settings.json 不以空/部分内容经 rename 落位。
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, marker)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    # symlink 补建提取为小函数，marker 已存在的两条早退 return 路径同样执行
    # ——首次创建时建链失败（OSError 被吞）或事后被清理的隔离目录借此自愈，
    # 子代理能力不再静默降级。
    def _ensure_symlinks() -> None:
        # 幂等：源目录不存在则跳过（优雅降级）；链接已在则不重建
        for name in ("skills", "plugins"):
            src = Path.home() / ".claude" / name
            dst = cfg_dir / name
            try:
                if src.is_dir() and not dst.exists():
                    dst.symlink_to(src, target_is_directory=True)
            except OSError:
                pass

    if marker.is_file():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing == settings:
                _ensure_symlinks()
                return cfg_dir
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # 非 UTF-8 字节（外部误写/磁盘损坏）与坏 JSON 同路降级：内容视为
            # 不匹配走下方原子重写路径（口径对齐 build_isolated_settings 与
            # admin_store._read_unlocked），不向 agent run 构造链上抛。
            pass
        # 内容不匹配（旧版无 env / 用户改过 / 损坏）→ 原子重写（幂等陷阱处置）
        try:
            _write_atomic()
        except OSError as e:
            # 不向上抛的降级语义不变，但 WARNING 留痕（code-review item
            # e207cc39ba4b）：settings.json 缺失/停留旧版意味着 PreToolUse
            # hook（block-image-read）与子代理模型映射全部缺席
            logger.warning(
                "ensure_agent_config_dir: 隔离 settings.json 重写失败"
                "（agent 以降级配置运行，无 hooks/模型映射）: %s", e,
            )
        _ensure_symlinks()
        return cfg_dir

    try:
        _write_atomic()
    except OSError as e:
        logger.warning(
            "ensure_agent_config_dir: 隔离 settings.json 首建失败"
            "（agent 以降级配置运行，无 hooks/模型映射）: %s", e,
        )

    _ensure_symlinks()
    return cfg_dir


def _claude_settings_path(project_root: Path | str) -> Optional[str]:
    """agent 专用 settings 注入路径：.fenix/agent-settings.json 存在才返回。

    原迹：_run_claude 5737-5742（PreToolUse hook：阻止 Read 图片文件等——
    模型不支持图像输入，读截图会把图片送进对话导致 400 整轮失败）。不存在
    返回 None（不注入，行为不变）。
    """
    p = Path(project_root) / ".fenix" / "agent-settings.json"
    return str(p) if p.exists() else None


def build_env(req: SpawnRequest) -> Optional[Dict[str, str]]:
    """按 SpawnRequest.env_mode 构造子进程 env（三种口径，见 protocol 常量）。

    - agent-run：主车道口径，与原 _run_claude 5675-5703 逐字节等价——
      os.environ 副本 + env_overrides 合并（Provider 覆盖生效时清除继承的
      ANTHROPIC_AUTH_TOKEN）+ FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE +
      CLAUDE_CODE_ENABLE_TODO_TOOLS 注入；
    - clean：一次性 spawn 口径——os.environ 副本剔除 agent-run 专用键
      （AGENT_RUN_BANNED_ENV_KEYS 单一口径）；
    - inherit：返回 None（Popen 不传 env，完整继承——叙事通道现状）。
    """
    # 未知 env_mode fail-fast（code-review item 0e2abeaf2b12，与
    # build_spawn_spec 的 prompt_transport 校验同口径）：分支结构会使未知值
    # 静默落入末尾 agent-run 主车道，向本应 clean/inherit 口径的一次性 spawn
    # 注入 FENIX_RUN_* 等 agent-run 专用键（跨车道上下文污染）。
    if req.env_mode not in (ENV_MODE_INHERIT, ENV_MODE_CLEAN, ENV_MODE_AGENT_RUN):
        raise ValueError(
            f"不支持的 env_mode 值：{req.env_mode!r}"
            f"（合法值：{ENV_MODE_INHERIT!r}/{ENV_MODE_CLEAN!r}/{ENV_MODE_AGENT_RUN!r}）"
        )
    if req.env_mode == ENV_MODE_INHERIT:
        return None
    if req.env_mode == ENV_MODE_CLEAN:
        env = os.environ.copy()
        # agent-run 专用上下文键不进一次性 spawn 子进程环境（单一口径）
        for key in AGENT_RUN_BANNED_ENV_KEYS:
            env.pop(key, None)
        if req.env_overrides:
            # 覆写键按**键自身**再过同一剔除口径（对齐 dsh 侧
            # is_dsh_banned_env_key 的 BUG-01 修复形态）：否则覆写字典
            # 可把剔除键回灌进一次性子进程环境。
            env.update(
                {
                    key: value
                    for key, value in req.env_overrides.items()
                    if key not in AGENT_RUN_BANNED_ENV_KEYS
                }
            )
        return env
    # ── ENV_MODE_AGENT_RUN（主车道）────────────────────────────────────
    env = os.environ.copy()
    if req.env_overrides:
        env.update(req.env_overrides)
        # Provider 覆盖生效时清除继承的 ANTHROPIC_AUTH_TOKEN（如 supervisor/tmux
        # 环境里残留的火山 ark token）。claude-code 认证时 AUTH_TOKEN 优先于
        # API_KEY，残留 token 会让请求以错误的 Bearer 认证打到 Provider → 401。
        if "ANTHROPIC_API_KEY" in req.env_overrides:
            env.pop("ANTHROPIC_AUTH_TOKEN", None)

    # worktree 隔离纵深（2026-09-08 skill 基路径锚定事故）：把项目根与本次
    # worktree 交给 PreToolUse 守卫 hook（block-main-tree-write.py），拦截
    # 「skill 注入的主树绝对路径被模型锚定为项目根」导致的写主树。无 worktree
    # 的 run（cwd == 项目根）置空，hook 全放行、行为不变。
    env["FENIX_RUN_PROJECT_ROOT"] = str(req.project_root)
    env["FENIX_RUN_WORKTREE"] = (
        str(req.cwd) if str(req.cwd) != str(req.project_root) else ""
    )

    # 任务清单工具显式启用（2026-09-15 原地修复）。claude CLI 2.1.272 起把
    # TaskCreate/TaskUpdate/TaskGet/TaskList 收窄为「仅第一方模型默认提供」，
    # 网关模型不再默认注入——需 CLAUDE_CODE_ENABLE_TODO_TOOLS=1 显式 opt-in。
    # 整套 run-progress 链路全部依赖该工具族；统一注入对该族工具「不适用」的
    # 第一方模型无副作用（本就默认提供）。
    env["CLAUDE_CODE_ENABLE_TODO_TOOLS"] = "1"
    return env


class ClaudeAdapter(HarnessAdapter):
    """claude CLI harness adapter（ADR-271：现状全量平移，行为零变化）。"""

    name = "claude"

    # ── 进程边界入侧 ──────────────────────────────────────────────────
    def build_spawn_spec(self, req: SpawnRequest) -> SpawnSpec:
        """SpawnRequest → SpawnSpec（argv/env/stdin 逐字节确定性）。

        argv 形态（平移自 _run_claude 5719-5746 与五处一次性 spawn 点现状）::

            claude -p [<prompt>]
                    [--output-format stream-json --verbose]   # stream-json 必带 --verbose
                    [--output-format <fmt>]                   # 一次性 json 单发等
                    [--add-dir <cwd>]                         # 主车道
                    [--permission-mode <mode>]
                    [--add-dir <主树 verify-progress>]        # 车道化注入（runner 决定）
                    [--settings <agent-settings.json>]        # agent-run 口径存在才注入
                    [--model <model>] [--resume <session_id>]

        prompt 经 stdin 传入（transport=stdin，缺省）：argv 全文驻留
        /proc/<pid>/cmdline，且单参数受 ARG_MAX 约束；transport=argv 保持
        autodraft/describe 现状形态（prompt 紧随 -p）。
        """
        # 未知 prompt_transport fail-fast（与 resolve_adapter 对未知 harness
        # 同口径）：静默落 None 会让 prompt 既不进 argv 也不进 stdin，子进程
        # 以空输入启动（claude -p 挂起等待 stdin 或空跑）。
        if req.prompt_transport not in (
            PROMPT_TRANSPORT_STDIN, PROMPT_TRANSPORT_ARGV
        ):
            raise ValueError(
                f"不支持的 prompt_transport 值：{req.prompt_transport!r}"
                f"（合法值：{PROMPT_TRANSPORT_STDIN!r}/{PROMPT_TRANSPORT_ARGV!r}）"
            )
        argv: List[str] = ["claude", "-p"]
        if req.prompt_transport == PROMPT_TRANSPORT_ARGV:
            argv.append(req.prompt)
        if req.output_format == "stream-json":
            # claude CLI 要求: --print + --output-format=stream-json 必须带 --verbose
            argv += ["--output-format", "stream-json", "--verbose"]
        elif req.output_format:
            argv += ["--output-format", req.output_format]
        if req.add_dir_cwd:
            argv += ["--add-dir", str(req.cwd)]
        if req.permission_mode:
            argv += ["--permission-mode", req.permission_mode]
        if req.add_main_tree_verify_progress:
            progress_dir = (
                Path(req.project_root) / ".fenix" / "verify-progress"
                if req.project_root
                else Path(".fenix") / "verify-progress"
            )
            argv += ["--add-dir", str(progress_dir)]
        if req.env_mode == ENV_MODE_AGENT_RUN:
            settings_path = req.settings_path
            if settings_path is None and req.project_root:
                settings_path = _claude_settings_path(req.project_root)
            if settings_path:
                argv += ["--settings", settings_path]
        if req.model:
            argv += ["--model", req.model]
        if req.resume_session_id:
            argv += ["--resume", req.resume_session_id]
        if req.extra_args:
            argv += list(req.extra_args)

        stdin_payload = (
            req.prompt if req.prompt_transport == PROMPT_TRANSPORT_STDIN else None
        )
        return SpawnSpec(
            argv=argv,
            env=build_env(req),
            stdin_payload=stdin_payload,
            cwd=str(req.cwd),
        )

    # ── 事件归一化 ────────────────────────────────────────────────────
    def normalize_event(self, raw: Any) -> Optional[List[Dict[str, Any]]]:
        """claude stream-json → canon 事件（恒等映射）。

        唯一非恒等分支：system/thinking_tokens 遥测噪音不落盘（原 _run_claude
        读线程内联 ``continue`` 的平移，fix-fenix-token-waste——占旧转录 ~75%
        的纯噪音）。其余事件原样透传，run jsonl 落盘内容与现状逐字节一致
        （ADR-271：claude stream-json 为 canon 形状，读侧零改动）。
        """
        if (
            isinstance(raw, dict)
            and raw.get("type") == "system"
            and raw.get("subtype") == "thinking_tokens"
        ):
            return []
        if isinstance(raw, dict):
            return [raw]
        # 非 dict（含 None）丢弃、不透传裸类型：与 dsh_adapter.normalize_event
        # 的丢弃语义对齐，canon 事件恒为 dict（注解 Optional[List[Dict]]）。
        return []

    # ── stderr 分类 ───────────────────────────────────────────────────
    def classify_stderr(self, line: str) -> str:
        """stderr 单行分类（现状两条口径的组合平移）。

        - 归因口径：unrecognized_model 判别保持经
          ``ProviderCircuit.classify_unrecognized_model_error`` 委托的接入
          形态（原 runner.py:725 类级别名转发同源）；
        - 降噪口径（_denoise_stderr D5）：``[claude-code:*]`` 前缀族整体属
          CLI 启动期诊断噪声，其中命中拒模型判别的归 unrecognized_model 子类。

        降噪只影响 error 文本拼装，run jsonl 的 stderr 原始事件行保持不过滤
        （取证现场完整）。
        """
        from core.agent_runner.provider_circuit import (
            ProviderCircuit,
            is_cli_stderr_noise,
        )

        if not line:
            return STDERR_CLASS_GENERIC
        if ProviderCircuit.classify_unrecognized_model_error(line):
            return STDERR_CLASS_UNRECOGNIZED_MODEL
        # _denoise_stderr 降噪口径：`^[claude-code:` 前缀族（含
        # is_cli_stderr_noise 判别入口，语义只定义在 provider_circuit 一处）
        if line.startswith("[claude-code:") or is_cli_stderr_noise(line):
            return STDERR_CLASS_CLI_NOISE
        return STDERR_CLASS_GENERIC

    # ── 终态 result 提取 ──────────────────────────────────────────────
    def extract_result(
        self, events: Sequence[Any], exit_code: Optional[int] = None
    ) -> Dict[str, Any]:
        """从终态 result 事件提取 output/turns/session_id/usage（现状行为平移）。

        原迹：_run_claude 6847-6951 收口段 + SessionTracker._extract_usage_info。
        events 传入本 run 观测到的终态 result 事件（0 或 1 个；reader 线程
        残留存活时调用方传空列表=unobserved 口径，与现状「跳过 last_result
        消费」同形）。返回 dict 键::

            observed        是否有可消费的 result 事件（False = unobserved）
            output          result 文本（无 result 时 ""）
            turns           num_turns（无 result/缺键时 0）
            session_id      会话 id（无 result 时 None）
            usage_info      SessionTracker.extract_usage_info 产物（unobserved
                            时四数值键 0 + unobserved=True 观测兜底）
            is_error/subtype/api_error_status/result_text
                            rc==0 伪装成功检测与异常归因素材（原样透传字段）
        """
        from core.agent_runner.session import SessionTracker

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
                "usage_info": SessionTracker.extract_usage_info(None),
                "is_error": False,
                "subtype": "success",
                "api_error_status": None,
                "result_text": "",
            }
        return {
            "observed": True,
            "output": last.get("result") or "",
            "turns": last.get("num_turns", 0),
            "session_id": last.get("session_id"),
            "usage_info": SessionTracker.extract_usage_info(last),
            "is_error": last.get("is_error", False),
            "subtype": last.get("subtype", "success"),
            "api_error_status": last.get("api_error_status"),
            "result_text": str(last.get("result") or ""),
        }

    # ── 进程识别（task 5.1 泛化源）────────────────────────────────────
    def process_patterns(self) -> List[str]:
        """agent 进程 argv[0] 识别 patterns（basename 集，与现状全等）。

        消费方：proc_utils.is_claude_process（清扫豁免锚点）、
        bin/fenix_dashboard.get_active_agents（活跃 agent 面板）。
        """
        return ["claude", "claude.exe"]

    def worktree_pgrep_patterns(self, spec_name: str) -> List[str]:
        """worktree 存活 pgrep -f patterns（admin_monitor/event_bus 消费）。

        与现状全等（admin_monitor._pgrep_live_worktree 平移）：三个车道前缀
        任一命中即判存活；构造单一来源为
        :func:`default_worktree_pgrep_patterns`（与 dsh 通道同构，演进只改
        一处）。前缀互撞的 cmdline 子串误判按既有处置记录 defer
        （fix-robustness-edge-cases 1.1），本平移不改判定语义。
        """
        return default_worktree_pgrep_patterns(spec_name)

    # ── 能力对账卡 ────────────────────────────────────────────────────
    def capabilities(self) -> HarnessCapabilities:
        return HarnessCapabilities(
            name=self.name,
            stream_json_output=True,
            resume_supported=True,
            isolated_settings_supported=True,
            max_turns_enforcement="daemon-side",
            process_patterns=self.process_patterns(),
        )
