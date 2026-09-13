"""
scenarios.py — 测试场景数据结构定义与校验

定义了 TestStep、Assertion、TestScenario 三个核心数据类，
以及场景加载/校验/序列化逻辑。
"""

from dataclasses import dataclass, field
from typing import Optional
import re


# ── schema 版本标记（frozen-scenario-schema-migration D2）──────────
# 当前场景文件 schema 版本号。写入端恒定写入；读侧按版本路由迁移：
# 无版本=旧 schema 走迁移，当前版本直通，未知版本走迁移尝试+字段差异报错。
SCHEMA_VERSION = 1


# ── 旧 schema 字段迁移（frozen-scenario-schema-migration D1/D2）────
# 冻结文件（frozen test_scenarios.json）可能以旧字段形态生成：
#   - cli run 步骤：value → command
#   - output_match 断言：value → expected
# 迁移仅对「目标字段缺失且旧字段存在」生效（新 schema 字段存在时零干扰）；
# 迁移后经既有校验；无法迁移（字段整体缺失）时在校验报错中附具体字段差异清单。

def migrate_scenario_schema(raw: list) -> list:
    """旧 schema 场景 dict 列表迁移（读侧预校验步骤）。

    识别旧字段形态并映射到新字段（仅当目标字段缺失时迁移，新字段存在零干扰）：
      - run 步骤（cli 场景，action == 'run'）：value → command
      - output_match 断言（type == 'output_match'）：value → expected

    返回迁移后的新列表（浅拷贝，原列表与各 dict 不变——读无副作用）。
    """
    migrated = []
    for item in raw:
        if isinstance(item, dict):
            migrated.append(_migrate_scenario_dict(item))
        else:
            migrated.append(item)
    return migrated


def _migrate_scenario_dict(d: dict) -> dict:
    """单条场景 dict 迁移：按需把旧字段映射到新字段（浅拷贝，原 dict 不变）。"""
    out = dict(d)
    steps = out.get("steps")
    if isinstance(steps, list):
        new_steps = []
        for s in steps:
            if isinstance(s, dict) and s.get("action") == "run":
                # cli run 旧字段：value → command（仅当 command 缺失时迁移）
                if "value" in s and "command" not in s:
                    s = {**s, "command": s["value"]}
            new_steps.append(s)
        out["steps"] = new_steps
    assertions = out.get("assertions")
    if isinstance(assertions, list):
        new_asserts = []
        for a in assertions:
            # output_match 断言旧字段：value → expected（仅当 expected 缺失时迁移）
            if (isinstance(a, dict)
                    and a.get("type") == "output_match"
                    and "value" in a
                    and "expected" not in a):
                a = {**a, "expected": a["value"]}
            new_asserts.append(a)
        out["assertions"] = new_asserts
    return out


def _schema_version_notes(raw: list) -> list[str]:
    """未知 schema_version 条目的路由说明（D2：未知版本走迁移尝试+差异报错）。

    返回人类可读注释列表（供 load_scenarios 在校验报错时附加版本上下文）。
    """
    notes = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        ver = item.get("schema_version")
        if ver is None:
            continue
        if ver != SCHEMA_VERSION:
            sid = item.get("id") or f"[{i}]"
            notes.append(
                f"场景'{sid}'声明未知 schema_version={ver!r}，已按旧 schema "
                f"迁移尝试，仍失败则以下为字段差异清单"
            )
    return notes


def prepare_scenarios_for_write(raw: list) -> list:
    """写端归一化（frozen-scenario-schema-migration 2.1）。

    场景补齐写回 / ``_scenarios_full.json`` 备份更新等写盘路径共用：
    旧 schema 字段先迁移（与读侧同源，``migrate_scenario_schema``），
    再恒定写入 ``schema_version`` 标记——写盘文件始终为当前 schema
    形态，读侧版本路由直通，不残留「旧字段 + 新版本号」的不一致组合。
    """
    return [
        {**d, "schema_version": SCHEMA_VERSION}
        if isinstance(d, dict) else d
        for d in migrate_scenario_schema(raw)
    ]


# ── 常量 ──────────────────────────────────────────────────────────
#
# 多形态验证（add-verify-multi-kind-runner）：场景 kind ∈ web/cli/api，
# 词表按 kind 组织为 per-kind 常量。**本文件是词表唯一权威源**——
# agents/planner-plan.md 只引用摘要并标注本文件为权威源（spec
# multi-kind-planning-guidance：防枚举双源漂移），词表扩展须先改这里。

VALID_KINDS = {"web", "cli", "api"}

# ── web 词表（存量内容，行为不变）────────────────────────────

WEB_ACTIONS = {
    "click", "type", "clear", "select", "scroll", "hover", "wait",
    "navigate", "drag", "contextmenu", "seed", "dialog", "mock_api",
}

WEB_ASSERTIONS = {
    # 第1层：元素存在性（确定性，0误判）
    "element_visible", "element_count", "element_not_exist",
    "element_focused", "element_enabled",
    # 第2层：交互可用性（确定性，0误判）
    "no_click_interception", "no_overlap", "in_viewport", "z_index_order",
    # 第3层：内容正确性（确定性，0误判）
    "text_match", "text_contains", "attribute_match",
    "no_console_error", "no_network_error", "no_auth_error", "dom_structure",
    # 第4层：布局完整性（启发式，需阈值）
    "no_overflow", "alignment",
}

WEB_ASSERTION_LAYERS = {
    "element_visible": 1, "element_count": 1, "element_not_exist": 1,
    "element_focused": 1, "element_enabled": 1,
    "no_click_interception": 2, "no_overlap": 2, "in_viewport": 2, "z_index_order": 2,
    "text_match": 3, "text_contains": 3, "attribute_match": 3,
    "no_console_error": 3, "no_network_error": 3, "no_auth_error": 3, "dom_structure": 3,
    "no_overflow": 4, "alignment": 4,
}

# ── cli 词表（spec multi-kind-scenario-model：CLI 词表与执行语义）────────
# 仅 run 一种步骤；6 种断言。无第 2 层（交互可用性是 DOM 概念）。

CLI_ACTIONS = {"run"}

CLI_ASSERTIONS = {
    # 第1层：存在性/状态（确定性，0误判）
    "exit_code", "file_exists", "dir_contains",
    # 第3层：内容正确性（确定性，0误判）
    "output_match", "file_content", "json_output",
}

CLI_ASSERTION_LAYERS = {
    "exit_code": 1, "file_exists": 1, "dir_contains": 1,
    "output_match": 3, "file_content": 3, "json_output": 3,
}

# ── api 词表（spec multi-kind-scenario-model：API 词表与响应捕获）──────
# http_request 通常一致；sse_connect 为流式（复杂度高时 fast-follow）。
# 无第 2 层。

API_ACTIONS = {"http_request", "sse_connect"}

API_ASSERTIONS = {
    # 第1层：存在性/状态（确定性，0误判）
    "status_code", "sse_event_count",
    # 第3层：内容正确性（确定性，0误判）
    "json_path", "response_header", "body_contains", "json_schema",
    "sse_event_matches",
    # 第4层：启发式阈值（失败=warning，需上下文判定）
    "latency_under",
}

API_ASSERTION_LAYERS = {
    "status_code": 1, "sse_event_count": 1,
    "json_path": 3, "response_header": 3, "body_contains": 3,
    "json_schema": 3, "sse_event_matches": 3,
    "latency_under": 4,
}

# ── 按 kind 词表索引（权威源）──────────────────────────────────

KIND_ACTIONS = {"web": WEB_ACTIONS, "cli": CLI_ACTIONS, "api": API_ACTIONS}
KIND_ASSERTIONS = {"web": WEB_ASSERTIONS, "cli": CLI_ASSERTIONS, "api": API_ASSERTIONS}
KIND_ASSERTION_LAYERS = {
    "web": WEB_ASSERTION_LAYERS,
    "cli": CLI_ASSERTION_LAYERS,
    "api": API_ASSERTION_LAYERS,
}

# ── 向后兼容别名（存量引用不变）────────────────────────────────
# web→VALID_ACTIONS：潜在别名与集合方法共存，避免库外引用断裂。

VALID_ACTIONS = WEB_ACTIONS

VALID_ASSERTIONS = WEB_ASSERTIONS

ASSERTION_LAYERS = {
    **WEB_ASSERTION_LAYERS, **CLI_ASSERTION_LAYERS, **API_ASSERTION_LAYERS,
}

# 需要选择器的断言类型（web 语义；CLI/API 断言不含 selector 概念）
ASSERTIONS_REQUIRING_SELECTOR = VALID_ASSERTIONS - {
    "text_contains", "no_console_error", "no_network_error", "no_auth_error",
}

# 需要target选择器的操作（web 语义；mock_api 的 target 为 URL 模式，seed 为 localStorage 键）
ACTIONS_REQUIRING_TARGET = {"click", "type", "clear", "select", "scroll", "drag", "contextmenu", "seed", "mock_api"}


# ── 数据类 ────────────────────────────────────────────────────────

@dataclass
class TestStep:
    """单个测试操作步骤。

    Attributes:
        action: 操作类型（web: click/type/clear/select/scroll/wait/navigate/
            dialog…；cli: run；api: http_request/sse_connect）
        target: CSS选择器（优先data-testid，其次语义选择器）
        value: 输入值（type/select/navigate/dialog使用）
        screenshot: 操作后是否截图
        description: 人类可读描述
        dialog: 点击触发的浏览器对话框处理（accept | dismiss）
        status: mock 响应状态码（mock_api 分支）
        prompt_text: prompt 对话框 accept 时提交的文本
        # cli run 字段
        command: 命令（字符串=shell / 列表=argv），见 prepare 解析约定
        cwd: 相对验证树根的工作目录
        env: 环境变量（值支持 {env:VAR} 插值）
        stdin: 注入标准输入
        timeout: 超时秒数（CLI 超时强杀=步骤失败；API 请求超时）
        as_: 命名结果（CLI run 命名输出；api http_request 命名响应，
            sse_connect 命名事件流）
        # api http_request / sse_connect 字段
        method: HTTP 方法（GET/POST/…）
        url: 绝对 URL（origin 由框架改写，路径保留）
        headers: 请求头（值支持 {env:VAR} 插值）
        body: 请求体
        body_type: 请求体类型（json/text）
        duration: sse_connect 收集窗口秒数
    """
    action: str
    target: str = ""
    value: str = ""
    screenshot: bool = False
    description: str = ""
    dialog: str = ""
    # admin 修 2026-08-29（族谱爆炸根因之一）：mock 响应状态码（409/500 分支
    # 场景必需）与 prompt 对话框提交文本。此前 TestStep 序列化丢弃这两个键，
    # 引擎侧 mock_api/click 拿不到，4xx/5xx 场景全部按 200 成功返回、prompt
    # 场景拿到空串 → 断言系统性伪失败。
    status: int = 0
    prompt_text: str = ""
    # 多形态验证字段（add-verify-multi-kind-runner）
    command: object = None  # str 或 list
    cwd: str = ""
    env: dict = field(default_factory=dict)
    stdin: str = ""
    timeout: float = 0.0
    as_: str = ""
    method: str = ""
    url: str = ""
    headers: dict = field(default_factory=dict)
    body: str = ""
    body_type: str = ""
    duration: float = 0.0

    def to_dict(self) -> dict:
        d: dict = {"action": self.action}
        if self.target:
            d["target"] = self.target
        if self.value:
            d["value"] = self.value
        if self.screenshot:
            d["screenshot"] = True
        if self.description:
            d["description"] = self.description
        if self.dialog:
            d["dialog"] = self.dialog
        if self.status:
            d["status"] = self.status
        if self.prompt_text:
            d["prompt_text"] = self.prompt_text
        if self.command not in (None, ""):
            d["command"] = self.command
        if self.cwd:
            d["cwd"] = self.cwd
        if self.env:
            d["env"] = self.env
        if self.stdin:
            d["stdin"] = self.stdin
        if self.timeout:
            d["timeout"] = self.timeout
        if self.as_:
            d["as"] = self.as_
        if self.method:
            d["method"] = self.method
        if self.url:
            d["url"] = self.url
        if self.headers:
            d["headers"] = self.headers
        if self.body:
            d["body"] = self.body
        if self.body_type:
            d["body_type"] = self.body_type
        if self.duration:
            d["duration"] = self.duration
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TestStep":
        return cls(
            action=d["action"],
            target=d.get("target", ""),
            value=d.get("value", ""),
            screenshot=d.get("screenshot", False),
            description=d.get("description", ""),
            dialog=d.get("dialog", ""),
            status=d.get("status", 0) or 0,
            prompt_text=d.get("prompt_text", "") or "",
            command=d.get("command"),
            cwd=d.get("cwd", ""),
            env=d.get("env") or {},
            stdin=d.get("stdin", ""),
            timeout=float(d.get("timeout") or 0),
            as_=d.get("as", ""),
            method=d.get("method", ""),
            url=d.get("url", ""),
            headers=d.get("headers") or {},
            body=d.get("body", ""),
            body_type=d.get("body_type", ""),
            duration=float(d.get("duration") or 0),
        )


@dataclass
class Assertion:
    """单个断言定义。

    Attributes:
        type: 断言类型（对应 assertions.py 中的方法名）
        selector: 目标元素CSS选择器
        label: 人类可读标签（用于报告）
        expected: 期望值（text_match/attribute_match等使用）
        threshold: 阈值（overlap检测的容差等）
        layer: 断言层级（1-4），自动从 type 推导
        extra: 额外参数（如 compare_selector / operator / axis 等）
    """
    type: str
    selector: str = ""
    label: str = ""
    expected: str = ""
    threshold: float = 0.2
    extra: dict = field(default_factory=dict)

    @property
    def layer(self) -> int:
        return ASSERTION_LAYERS.get(self.type, 0)

    def to_dict(self) -> dict:
        d: dict = {"type": self.type}
        if self.selector:
            d["selector"] = self.selector
        if self.label:
            d["label"] = self.label
        if self.expected != "":
            d["expected"] = self.expected
        if self.threshold != 0.2:
            d["threshold"] = self.threshold
        d.update(self.extra)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Assertion":
        known_keys = {"type", "selector", "label", "expected", "threshold"}
        extra = {k: v for k, v in d.items() if k not in known_keys}
        return cls(
            type=d["type"],
            selector=d.get("selector", ""),
            label=d.get("label", ""),
            expected=d.get("expected", ""),
            threshold=d.get("threshold", 0.2),
            extra=extra,
        )


@dataclass
class TestScenario:
    """完整的测试场景。

    Attributes:
        id: 唯一标识（kebab-case）
        description: 人类可读中文描述
        steps: 操作步骤列表
        assertions: 断言列表
        visual_baseline: 视觉对比基线名称（可选，用于截图SSIM对比）
        depends_on: 依赖的场景ID列表（这些场景必须先执行完成）
        external_net_errors_ok: 场景是否允许「外部 API 网络类控制台错误」。
            涉及外部 API（如 timeapi.io / open-meteo）真实请求的场景置 True，
            no_console_error 断言将过滤 net::ERR_ 等网络层错误（视为环境因素），
            其余控制台错误（含签名/认证类）仍严格失败。
    """
    id: str
    description: str = ""
    steps: list[TestStep] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    visual_baseline: str = ""
    depends_on: list[str] = field(default_factory=list)
    external_net_errors_ok: bool = False
    # 场景 kind（web/cli/api，缺省 web）。kind 是场景级字段：混合 spec =
    # 场景集混排 + depends_on 跨 kind 编排；单场景内不混排步骤类型。
    kind: str = "web"
    # 场景级视口（admin 修 2026-09-07，fix-mobile-touch-disclosure 验证阻塞根因）。
    # 此前本模型无此字段，场景声明的 {"width":390,"height":844} 被 from_dict
    # 静默丢弃、browser.new_context 硬编码 1280×800 桌面视口——useIsMobile
    # 门控的移动端条件渲染（渐进披露等）在验证中永不出现，断言必然超时的
    # 伪失败被误判为产品缺陷。None = 沿用桌面缺省，存量场景行为不变。
    viewport: Optional[dict] = None

    def validate(self) -> list[str]:
        """验证场景定义的合法性，返回错误列表。

        按场景 kind 校验：web 用 web 词表（navigate 硬要求等存量规则），
        cli/api 用各自词表与必填字段。空列表表示场景定义完全合法。
        词表校验的权威源是本模块 per-kind 常量（KIND_ACTIONS /
        KIND_ASSERTIONS），planner 提示词只做摘要并标注此处为权威源。
        """
        return validate_scenario(self)

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "description": self.description,
            "kind": self.kind,
            # frozen-scenario-schema-migration D2：写入端恒定写 schema 版本标记，
            # 读侧按版本路由迁移（无版本=旧 schema 走迁移，当前版本直通）。
            "schema_version": SCHEMA_VERSION,
            "steps": [s.to_dict() for s in self.steps],
            "assertions": [a.to_dict() for a in self.assertions],
        }
        if self.visual_baseline:
            d["visual_baseline"] = self.visual_baseline
        if self.depends_on:
            d["depends_on"] = self.depends_on
        if self.external_net_errors_ok:
            d["external_net_errors_ok"] = True
        if self.viewport:
            d["viewport"] = self.viewport
        return d

    @staticmethod
    def _parse_viewport(raw) -> Optional[dict]:
        """顶层 viewport 字段解析：仅接受 {width:int, height:int} 正值，
        其余形态一律忽略（回退桌面缺省），不制造新的验收失败模式。"""
        if not isinstance(raw, dict):
            return None
        try:
            w, h = int(raw["width"]), int(raw["height"])
        except (KeyError, TypeError, ValueError):
            return None
        if w <= 0 or h <= 0 or w > 3840 or h > 2160:
            return None
        return {"width": w, "height": h}

    @classmethod
    def from_dict(cls, d: dict) -> "TestScenario":
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            steps=[TestStep.from_dict(s) for s in d.get("steps", [])],
            assertions=[Assertion.from_dict(a) for a in d.get("assertions", [])],
            visual_baseline=d.get("visual_baseline", ""),
            depends_on=d.get("depends_on", []),
            external_net_errors_ok=d.get("external_net_errors_ok", False),
            kind=d.get("kind", "web"),
            viewport=cls._parse_viewport(d.get("viewport")),
        )


# ── per-kind 场景验收校验 ─────────────────────────────────────────
# 各 Runner 的 validate 委托本函数（WebRunner/CliRunner/ApiRunner 一致入口，
# 词表权威源唯一）。验收错误消息带「支持: …」词表速查（spec
# multi-kind-planning-guidance 打回路径：plan 侧无需查询源码即可修正）。


def _supported_actions(kind: str) -> str:
    return ", ".join(sorted(KIND_ACTIONS.get(kind, set())))


def _supported_assertions(kind: str) -> str:
    return ", ".join(sorted(KIND_ASSERTIONS.get(kind, set())))


def _validate_web(scenario: TestScenario) -> list[str]:
    """web 词表校验（存量规则，navigate 硬要求 + target/selector 必填）。"""
    errors: list[str] = []

    for i, step in enumerate(scenario.steps):
        if step.action not in WEB_ACTIONS:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 未知操作 '{step.action}'，"
                f"支持: {_supported_actions('web')}"
            )
        if step.action in ACTIONS_REQUIRING_TARGET and not step.target:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 操作 '{step.action}' 需要 target 选择器"
            )

    for i, a in enumerate(scenario.assertions):
        if a.type not in WEB_ASSERTIONS:
            errors.append(
                f"场景'{scenario.id}'断言{i}: 未知类型 '{a.type}'，"
                f"支持: {_supported_assertions('web')}"
            )
        if a.type in ASSERTIONS_REQUIRING_SELECTOR and not a.selector:
            errors.append(
                f"场景'{scenario.id}'断言{i}: 类型 '{a.type}' 需要 selector"
            )

    # navigate URL 验收（2026-08-28：相对路径导致浏览器白屏、整轮断言全灭）
    nav_steps = [s for s in scenario.steps if s.action == "navigate"]
    if not nav_steps:
        errors.append(
            f"场景'{scenario.id}'缺少 navigate 步骤"
            f"（web 场景必须以绝对 URL 打开被测页面）"
        )
    for i, step in enumerate(scenario.steps):
        if step.action == "navigate" and not re.match(
            r"^https?://\S+$", (step.value or "").strip()
        ):
            errors.append(
                f"场景'{scenario.id}'步骤{i}: navigate URL 必须为绝对地址"
                f"（http://或https://开头，含主机与端口），收到 '{step.value}'"
                f"——相对路径会被验收拒绝并退回 plan 阶段"
            )
    return errors


def _validate_cli(scenario: TestScenario) -> list[str]:
    """cli 词表校验：仅 run 步骤 + CLI 断言必填字段。

    run 步骤必填 command（字符串=shell/列表=argv）；cwd 相对验证树根、
    env 值支持 {env:VAR} 插值、stdin/timeout/as 可选。断言必填字段见
    spec multi-kind-scenario-model「CLI 词表与执行语义」。
    """
    errors: list[str] = []

    for i, step in enumerate(scenario.steps):
        if step.action not in CLI_ACTIONS:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 未知操作 '{step.action}'，"
                f"支持: {_supported_actions('cli')}"
            )
            continue
        if not step.command:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: run 步骤必须提供 command"
                f"（字符串=经 shell 执行；列表=argv 直接执行）"
            )

    for i, a in enumerate(scenario.assertions):
        if a.type not in CLI_ASSERTIONS:
            errors.append(
                f"场景'{scenario.id}'断言{i}: 未知类型 '{a.type}'，"
                f"支持: {_supported_assertions('cli')}"
            )
            continue
        if a.type in ("file_exists", "file_content", "json_output",
                      "dir_contains"):
            if a.type == "dir_contains":
                path_or_glob = a.extra.get("glob")
            else:
                path_or_glob = a.extra.get("path")
            if not path_or_glob:
                field = "path" if a.type != "dir_contains" else "glob"
                errors.append(
                    f"场景'{scenario.id}'断言{i}: 类型 '{a.type}' 需要 {field}"
                )
        if a.type in ("output_match", "file_content") and not a.expected:
            errors.append(
                f"场景'{scenario.id}'断言{i}: {a.type} 需要 expected"
            )
        if a.type == "json_output":
            if not a.extra.get("step"):
                errors.append(
                    f"场景'{scenario.id}'断言{i}: json_output 需要 step"
                    f"（指定解析哪个命名结果的 stdout）"
                )
            if not a.extra.get("path"):
                errors.append(
                    f"场景'{scenario.id}'断言{i}: json_output 需要 path"
                )
    return errors


def _validate_api(scenario: TestScenario) -> list[str]:
    """api 词表校验：http_request/sse_connect 步骤 + API 断言必填字段。

    http_request 必填 method/url（绝对 URL，origin 由框架改写）；断言必填
    字段见 spec multi-kind-scenario-model「API 词表与响应捕获」。
    """
    errors: list[str] = []

    for i, step in enumerate(scenario.steps):
        if step.action not in API_ACTIONS:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 未知操作 '{step.action}'，"
                f"支持: {_supported_actions('api')}"
            )
            continue
        if step.action == "http_request":
            if not step.method:
                errors.append(
                    f"场景'{scenario.id}'步骤{i}: http_request 必须提供 method"
                )
            if not step.url:
                errors.append(
                    f"场景'{scenario.id}'步骤{i}: http_request 必须提供 url"
                    f"（绝对 URL，origin 由框架改写）"
                )
        elif step.action == "sse_connect":
            if not step.url:
                errors.append(
                    f"场景'{scenario.id}'步骤{i}: sse_connect 必须提供 url"
                )

    for i, a in enumerate(scenario.assertions):
        if a.type not in API_ASSERTIONS:
            errors.append(
                f"场景'{scenario.id}'断言{i}: 未知类型 '{a.type}'，"
                f"支持: {_supported_assertions('api')}"
            )
            continue
        if a.type == "status_code" and a.expected in ("", None):
            errors.append(
                f"场景'{scenario.id}'断言{i}: status_code 需要 expected"
            )
        if a.type == "json_path" and not a.extra.get("path"):
            errors.append(
                f"场景'{scenario.id}'断言{i}: json_path 需要 path"
            )
        if a.type == "response_header" and not a.extra.get("header"):
            errors.append(
                f"场景'{scenario.id}'断言{i}: response_header 需要 header"
            )
        if a.type == "body_contains" and not a.expected:
            errors.append(
                f"场景'{scenario.id}'断言{i}: body_contains 需要 expected"
            )
        if a.type == "json_schema" and not a.extra.get("schema"):
            errors.append(
                f"场景'{scenario.id}'断言{i}: json_schema 需要 schema"
            )
        if a.type == "latency_under" and a.expected in ("", None):
            errors.append(
                f"场景'{scenario.id}'断言{i}: latency_under 需要 expected"
                f"（毫秒上限）"
            )
        if a.type == "sse_event_count" and a.extra.get("min") is None:
            errors.append(
                f"场景'{scenario.id}'断言{i}: sse_event_count 需要 min（下限）"
            )
        if a.type == "sse_event_matches" and not a.expected:
            errors.append(
                f"场景'{scenario.id}'断言{i}: sse_event_matches 需要 expected"
            )
    return errors


def validate_scenario(scenario: TestScenario) -> list[str]:
    """按场景 kind 分派 per-kind 词表校验（Runner.validate 与
    TestScenario.validate 的公共入口，词表权威源唯一）。"""
    errors: list[str] = []
    if not scenario.id or not scenario.id.strip():
        errors.append("场景ID不能为空")
    if scenario.kind not in VALID_KINDS:
        errors.append(
            f"场景'{scenario.id}'未知 kind '{scenario.kind}'，"
            f"支持: {', '.join(sorted(VALID_KINDS))}"
        )
        return errors
    if scenario.kind == "web":
        errors.extend(_validate_web(scenario))
    elif scenario.kind == "cli":
        errors.extend(_validate_cli(scenario))
    elif scenario.kind == "api":
        errors.extend(_validate_api(scenario))
    return errors


# ── 场景加载 ──────────────────────────────────────────────────────

def validate_scenario_dicts(raw: list) -> list[str]:
    """结构校验场景 dict 列表（scenario-write-schema-gate 单一来源）。

    读端 ``load_scenarios`` 与全部写端（planner 产物收编、补齐写回、
    ``save_scenario_set``、``_scenarios_full.json`` 备份更新）共用同一
    校验：输入 dict 列表，逐条经 ``TestScenario.from_dict`` +
    ``validate()`` 校验，返回逐条错误清单。空列表表示全部合法；本函数
    不抛异常，拒绝/剔除策略由调用方决定。

    frozen-scenario-schema-migration D1：校验前先做读侧旧 schema 迁移
    （value→command / value→expected，仅目标字段缺失时生效），与
    ``load_scenarios`` 版本路由后的形态一致——迁移零干扰新 schema 路径。

    Args:
        raw: 场景 dict 列表。

    Returns:
        错误清单（人类可读，含场景 id / 下标定位）；全部合法时为空列表。
    """
    if not isinstance(raw, list):
        return [f"场景数据格式错误: 期望数组，实际为 {type(raw).__name__}"]
    # 旧 schema 前置迁移（读侧同样靠本函数做最终校验，迁移须先于校验执行；
    # 迁移为幂等操作，load_scenarios 已迁移时此处零干扰）
    raw = migrate_scenario_schema(raw)
    all_errors: list[str] = []
    for i, item in enumerate(raw):
        try:
            scenario = TestScenario.from_dict(item)
            errors = scenario.validate()
            if errors:
                all_errors.extend(errors)
        except Exception as e:
            all_errors.append(f"场景[{i}]解析失败: {e}")
    return all_errors


def load_scenarios(filepath) -> list[TestScenario]:
    """从JSON文件加载场景列表，并校验合法性。

    Args:
        filepath: test_scenarios.json 的路径（Path 对象或字符串）

    Returns:
        TestScenario 列表

    Raises:
        ValueError: 场景文件格式错误或场景定义不合法
    """
    import json
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"场景文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError(f"场景文件格式错误: 期望JSON数组，实际为 {type(raw).__name__}")

    # ── schema 版本路由迁移（frozen-scenario-schema-migration D2）──
    # 无版本字段 → 旧 schema 走迁移（value→command / value→expected）；
    # 当前版本 → 迁移天然零干扰（目标字段已存在，直通语义）；
    # 未知版本 → 仍走迁移尝试，校验失败时附版本上下文与字段差异清单。
    version_notes = _schema_version_notes(raw)
    raw = migrate_scenario_schema(raw)

    # 读端校验与写端 schema 门同源（fix-frozen-scenario-orphan-reservoir D1）：
    # 校验逻辑提取为 validate_scenario_dicts 独立可调用，此处调用它（行为零变化，
    # 报错格式「场景文件包含 N 个错误」不变）。
    all_errors = validate_scenario_dicts(raw)
    if all_errors:
        # 迁移后仍失败 → 报字段级差异清单（场景 id/下标/缺失字段），不吞为
        # 笼统 corrupt：admin 处置（frozen-scenario-schema-migration 1.2）
        # 可凭差异清单精准修复冻结文件。
        detail = "\n".join(f"  - {e}" for e in all_errors)
        if version_notes:
            detail += "\n" + "\n".join(f"  # {n}" for n in version_notes)
        raise ValueError(
            f"场景文件包含 {len(all_errors)} 个错误:\n" + detail
        )

    return [TestScenario.from_dict(item) for item in raw]


def save_scenarios(scenarios: list[TestScenario], filepath) -> None:
    """将场景列表序列化为JSON文件。

    Args:
        scenarios: TestScenario 列表
        filepath: 目标文件路径
    """
    import json
    from pathlib import Path

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [s.to_dict() for s in scenarios]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
