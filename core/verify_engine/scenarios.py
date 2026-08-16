"""
scenarios.py — 测试场景数据结构定义与校验

定义了 TestStep、Assertion、TestScenario 三个核心数据类，
以及场景加载/校验/序列化逻辑。
"""

from dataclasses import dataclass, field
from typing import Optional


# ── 常量 ──────────────────────────────────────────────────────────

VALID_ACTIONS = {"click", "type", "clear", "select", "scroll", "hover", "wait", "navigate", "drag", "contextmenu", "seed", "dialog"}

VALID_ASSERTIONS = {
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

ASSERTION_LAYERS = {
    "element_visible": 1, "element_count": 1, "element_not_exist": 1,
    "element_focused": 1, "element_enabled": 1,
    "no_click_interception": 2, "no_overlap": 2, "in_viewport": 2, "z_index_order": 2,
    "text_match": 3, "text_contains": 3, "attribute_match": 3,
    "no_console_error": 3, "no_network_error": 3, "no_auth_error": 3, "dom_structure": 3,
    "no_overflow": 4, "alignment": 4,
}

# 需要选择器的断言类型（不需要的：text_contains / no_console_error / no_network_error / no_auth_error）
ASSERTIONS_REQUIRING_SELECTOR = VALID_ASSERTIONS - {
    "text_contains", "no_console_error", "no_network_error", "no_auth_error",
}

# 需要target选择器的操作
ACTIONS_REQUIRING_TARGET = {"click", "type", "clear", "select", "scroll", "drag", "contextmenu", "seed"}


# ── 数据类 ────────────────────────────────────────────────────────

@dataclass
class TestStep:
    """单个测试操作步骤。

    Attributes:
        action: 操作类型（click/type/clear/select/scroll/wait/navigate/dialog）
        target: CSS选择器（优先data-testid，其次语义选择器）
        value: 输入值（type/select/navigate/dialog使用）
        screenshot: 操作后是否截图
        description: 人类可读描述
        dialog: 点击触发的浏览器对话框处理（accept | dismiss）
    """
    action: str
    target: str = ""
    value: str = ""
    screenshot: bool = False
    description: str = ""
    dialog: str = ""

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
    """
    id: str
    description: str = ""
    steps: list[TestStep] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    visual_baseline: str = ""
    depends_on: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        """验证场景定义的合法性，返回错误列表。

        空列表表示场景定义完全合法。
        """
        errors: list[str] = []

        # 检查 scenario ID
        if not self.id or not self.id.strip():
            errors.append("场景ID不能为空")

        # 检查步骤
        for i, step in enumerate(self.steps):
            if step.action not in VALID_ACTIONS:
                errors.append(
                    f"场景'{self.id}'步骤{i}: 未知操作 '{step.action}'，"
                    f"支持: {', '.join(sorted(VALID_ACTIONS))}"
                )
            if step.action in ACTIONS_REQUIRING_TARGET and not step.target:
                errors.append(
                    f"场景'{self.id}'步骤{i}: 操作 '{step.action}' 需要 target 选择器"
                )

        # 检查断言
        for i, a in enumerate(self.assertions):
            if a.type not in VALID_ASSERTIONS:
                errors.append(
                    f"场景'{self.id}'断言{i}: 未知类型 '{a.type}'，"
                    f"支持: {', '.join(sorted(VALID_ASSERTIONS))}"
                )
            if a.type in ASSERTIONS_REQUIRING_SELECTOR and not a.selector:
                errors.append(
                    f"场景'{self.id}'断言{i}: 类型 '{a.type}' 需要 selector"
                )

        return errors

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "assertions": [a.to_dict() for a in self.assertions],
        }
        if self.visual_baseline:
            d["visual_baseline"] = self.visual_baseline
        if self.depends_on:
            d["depends_on"] = self.depends_on
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TestScenario":
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            steps=[TestStep.from_dict(s) for s in d.get("steps", [])],
            assertions=[Assertion.from_dict(a) for a in d.get("assertions", [])],
            visual_baseline=d.get("visual_baseline", ""),
            depends_on=d.get("depends_on", []),
        )


# ── 场景加载 ──────────────────────────────────────────────────────

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

    scenarios: list[TestScenario] = []
    all_errors: list[str] = []

    for i, item in enumerate(raw):
        try:
            scenario = TestScenario.from_dict(item)
            errors = scenario.validate()
            if errors:
                all_errors.extend(errors)
            scenarios.append(scenario)
        except Exception as e:
            all_errors.append(f"场景[{i}]解析失败: {e}")

    if all_errors:
        raise ValueError(
            f"场景文件包含 {len(all_errors)} 个错误:\n" +
            "\n".join(f"  - {e}" for e in all_errors)
        )

    return scenarios


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
