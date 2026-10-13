"""harness/protocol.py — agent harness 进程边界协议与数据类（add-harness-adapter-layer 1.1）。

协议边界放在进程边界（母设计 D1 / ADR-271）：``SpawnSpec`` 进（argv/env/stdin
载荷，可直接驱动 subprocess.Popen）、归一化事件出（run jsonl 以 claude
stream-json 形状为唯一 canon，读侧 8+ 模块零改动）。

依赖方向（design D8）：本包只依赖 stdlib 与既有纯工具模块，MUST NOT import
runner/event_bus/admin_monitor 等消费侧模块——防循环 import，也防 8438 行
runner 抽取误伤共享运行态；消费侧（proc_utils / event_bus / admin_monitor /
dashboard 等）单向 import 本包工厂取 process_patterns。

lane 语义（design D6）：五处一次性 spawn 点的 argv/stdin 形态差异（judge 走
``--output-format json``、autodraft/describe 走 argv 传 prompt、主车道走 stdin
传 prompt）全部是 :class:`SpawnRequest` 的**数据**而非 adapter 分支代码——
换 harness 只换 adapter。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ── prompt 传输形态（SpawnRequest.prompt_transport 取值）──────────────────
# stdin（缺省）：prompt 经 stdin 管道传入——argv 全文驻留 /proc/<pid>/cmdline
# （同机用户经 ps 可见 spec 上下文等敏感内容），且单参数受 ARG_MAX 约束；
# argv：prompt 作为位置参数进 argv（architecture autodraft / project describe
# 现状形态，收编时逐字节保持）。
PROMPT_TRANSPORT_STDIN = "stdin"
PROMPT_TRANSPORT_ARGV = "argv"

# ── env 构造口径（SpawnRequest.env_mode 取值）────────────────────────────
# agent-run：主车道口径——os.environ 副本 + env_overrides 合并 + ANTHROPIC_
# AUTH_TOKEN 清理 + FENIX_RUN_PROJECT_ROOT/FENIX_RUN_WORKTREE +
# CLAUDE_CODE_ENABLE_TODO_TOOLS 注入（与原 _run_claude 逐字节等价）；
# clean：一次性 spawn 口径——os.environ 副本剔除 agent-run 专用键
#（AGENT_RUN_BANNED_ENV_KEYS，core.agent_env_keys 单一来源）；
# inherit：完整继承不传 env（叙事通道现状——Popen 不带 env 参数）。
ENV_MODE_AGENT_RUN = "agent-run"
ENV_MODE_CLEAN = "clean"
ENV_MODE_INHERIT = "inherit"


@dataclass
class SpawnRequest:
    """一次 agent 子进程 spawn 的请求描述。

    车道与一次性 spawn 的全部形态差异（prompt 传输形态、output-format、
    model、cwd、timeout、resume、env 口径、主树 verify-progress 注入等）都是
    本类的字段；adapter 按字段值确定性产出 :class:`SpawnSpec`，对同一请求
    逐字节稳定（快照测试 test_harness_claude_snapshot.py 锁定）。
    """

    prompt: str
    cwd: str
    # prompt 传输形态（缺省 stdin，主车道与多数一次性 spawn 现状）
    prompt_transport: str = PROMPT_TRANSPORT_STDIN
    # --output-format 取值；None = 不传该 flag（叙事通道/project describe 现状）
    output_format: Optional[str] = "stream-json"
    # --model 显式传递；None = 不传（用 CLI/网关默认档）
    model: Optional[str] = None
    # --resume 会话续跑；None = 全新会话
    resume_session_id: Optional[str] = None
    # --settings 显式路径；None = agent-run 口径由 adapter 按 project_root 推导
    #（.fenix/agent-settings.json 存在才注入），一次性 spawn 不注入
    settings_path: Optional[str] = None
    # --permission-mode；None = 不传（叙事通道/project describe 现状）
    permission_mode: Optional[str] = None
    # 额外 argv 追加段（当前 claude 平移无消费方，为 SPEC-3 dsh 预留扩展位）
    extra_args: List[str] = field(default_factory=list)
    # env 覆盖（Provider 路由：ANTHROPIC_BASE_URL/API_KEY/MODEL、
    # CLAUDE_CONFIG_DIR、v2 dev-server 注入等）
    env_overrides: Dict[str, str] = field(default_factory=dict)
    # env 构造口径（见模块头三常量说明）
    env_mode: str = ENV_MODE_AGENT_RUN
    # 项目根（agent-run 口径注入 FENIX_RUN_PROJECT_ROOT、--add-dir verify-progress
    # 与 --settings 推导的锚点；一次性 spawn 场景传 spawn 载体根）
    project_root: str = ""
    # 是否以 --add-dir 注入工作目录本身（agent-run 主车道恒 True——模型在
    # cwd 之外读文件的授权通道；五处一次性 spawn 现状均不传，False）
    add_dir_cwd: bool = False
    # 主树 verify-progress 目录是否注入 --add-dir（车道化注入 fix-impl-code-
    # review-writepath D2：verifier/planner/fast-track/dispute-judge/administrator
    # 等车道为 True，implementer/repair/spec-review 为 False）。车道集合知识
    # 留在 runner 侧（_NO_MAIN_TREE_VERIFY_PROGRESS_LANES），harness 包不感知
    # 车道词表（design D8）。
    add_main_tree_verify_progress: bool = False
    # 单次运行轮次上限（daemon 侧强制语义：claude CLI 无 --max-turns flag，
    # 由 runner 轮询环统计 assistant 事件数强制；adapter MUST NOT 把它映射进
    # argv——快照测试锁定）。仅作请求描述随行，供 adapter/监督面读取。
    max_turns: Optional[int] = None
    # 期望超时（秒；None = 不限）。run_one_shot 据此设 communicate timeout；
    # 主车道轮询环自带监督，此字段仅描述。
    timeout: Optional[float] = None
    # 显式 env 键值对覆盖 env_mode 产物（优先级最高；当前无消费方，预留）
    strict_env: Optional[Dict[str, str]] = None


@dataclass
class SpawnSpec:
    """adapter 产出的进程边界规格：可直接驱动 subprocess.Popen。

    claude 平移等价性（spec「claude 平移字节级等价」）：对同一 SpawnRequest，
    平移前后的 argv 序列、env 字典（含清除键）、stdin 载荷逐字节相等。
    """

    argv: List[str]
    env: Optional[Dict[str, str]]
    # prompt 经 stdin 传入的载荷；None = prompt 走 argv（或调用方自带 stdin 通道）
    stdin_payload: Optional[str]
    cwd: str
    text: bool = True
    # 显式 UTF-8 + replace（主车道现状：管道解码不随 daemon locale 漂移）；
    # None = Popen 缺省（locale 决定，叙事通道现状逐字节保持）
    encoding: Optional[str] = "utf-8"
    errors: str = "replace"
    # 独立进程组启动（超时/清场经 killpg 整组收割）
    start_new_session: bool = True


@dataclass
class HarnessCapabilities:
    """harness 能力对账卡（SPEC-2 fenix-dsh Bundle 侧依赖本结构对账）。

    字段全部为 str/bool/list[str] 纯 JSON 类型，:meth:`to_dict` 产物可被
    json.dumps 直接序列化（协议 Scenario「HarnessCapabilities 可 json.dumps
    序列化」；新字段 MUST 保持该性质）。
    """

    name: str
    # 是否支持 stream-json 逐行事件流（run jsonl canon 形状的前提）
    stream_json_output: bool
    # 是否支持 --resume 会话续跑
    resume_supported: bool
    # 是否支持隔离 settings 落盘（CLAUDE_CONFIG_DIR + settings.json）
    isolated_settings_supported: bool
    # 轮次上限强制位置："daemon-side"（claude 现状）| "cli-flag" | "unsupported"
    max_turns_enforcement: str
    # agent 进程识别 patterns（argv[0] basename 集，proc_utils 消费）
    process_patterns: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """纯 JSON dict（json.dumps 往返无损）。"""
        return dataclasses.asdict(self)


# ── stderr 分类词表（classify_stderr 返回值）──────────────────────────────
# cli_noise：CLI 启动期诊断噪声行（``[claude-code:*]``，与死因无关）
# unrecognized_model：拒模型诊断行（噪声的子集，经
#   ProviderCircuit.classify_unrecognized_model_error 委托判别——保持 runner
#   既有委托接入形态）
# generic：其余 stderr 行（真实死因素材）
STDERR_CLASS_CLI_NOISE = "cli_noise"
STDERR_CLASS_UNRECOGNIZED_MODEL = "unrecognized_model"
STDERR_CLASS_GENERIC = "generic"


class HarnessAdapter:
    """harness adapter 协议（typing.Protocol 语义的结构化契约）。

    七个协议成员（spec「HarnessAdapter 协议」）：name / build_spawn_spec /
    normalize_event / classify_stderr / extract_result / process_patterns /
    capabilities。用显式方法集而非 typing.Protocol 类的原因：协议成员完整性
    测试（task 1.2）以 isinstance 协议结构比对最直观，且 isinstance 检查对
    「少实现一个成员」的 adapter 在运行期即可判（fail-fast 优于运行到一半
    AttributeError）。子类 MUST 全量实现，缺成员由测试与运行期双路拦截。

    member 定义（详见 spec delta agent-harness-adapter）：
    - name: harness 标识（与 agent.harness 配置值一致，如 "claude"）
    - build_spawn_spec(req) -> SpawnSpec：进程边界入侧唯一入口
    - normalize_event(raw) -> list | None：harness 原生事件 → canon 事件列表
      （claude 为恒等映射；None/[] = 该事件不落盘，如遥测噪音）
    - classify_stderr(line) -> str：stderr 单行分类（词表见上方三常量）
    - extract_result(events, exit_code=None) -> dict：终态 result 提取
      （output/turns/session_id/usage_info/归因字段）
    - process_patterns() -> list[str]：agent 进程 argv[0] 识别 patterns
    - capabilities() -> HarnessCapabilities：能力对账卡
    """

    name: str = ""

    def build_spawn_spec(self, req: SpawnRequest) -> SpawnSpec:  # pragma: no cover
        raise NotImplementedError

    def normalize_event(self, raw: Any) -> Optional[List[Dict[str, Any]]]:  # pragma: no cover
        raise NotImplementedError

    def classify_stderr(self, line: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def extract_result(
        self, events: Sequence[Any], exit_code: Optional[int] = None
    ) -> Dict[str, Any]:  # pragma: no cover
        raise NotImplementedError

    def process_patterns(self) -> List[str]:  # pragma: no cover
        raise NotImplementedError

    def worktree_pgrep_patterns(self, spec_name: str) -> List[str]:  # pragma: no cover
        """worktree 存活 pgrep -f patterns（admin_monitor/event_bus 消费）。

        spec 规定的七成员之外的扩展成员（「至少包含」）：admin_monitor
        _pgrep_live_worktree 的车道前缀 pattern 由 adapter 供给，消费侧零
        硬编码。 """
        raise NotImplementedError

    def capabilities(self) -> HarnessCapabilities:  # pragma: no cover
        raise NotImplementedError


# 协议成员清单（协议完整性测试 task 1.2 与运行期结构校验共用此单源）
HARNESS_ADAPTER_MEMBERS = (
    "name",
    "build_spawn_spec",
    "normalize_event",
    "classify_stderr",
    "extract_result",
    "process_patterns",
    "capabilities",
)
