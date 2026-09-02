"""openspec_mode.py — SPEC 执行模式读取器（add-fast-track-mode / D2）。

读取 ``openspec/changes/<spec>/.openspec.yaml`` 的 ``mode`` 字段：

  - ``fast-track``：快速路径——单个 agent run 全包（实现 → 场景设计 → 验证 → 判定）
  - ``full``（缺省）：完整模式——现有多 Agent 分段流水线

读取侧容错（design D2）：字段缺失 / 值非法 / 文件不存在 / 解析失败，
一律返回 ``"full"``——存量 spec 零迁移，行为与引入本能力之前完全一致。

纯函数模块，无外部依赖（仅 yaml），daemon 派发路径与 Dashboard data 层共用。
"""

import yaml
from pathlib import Path

# 合法模式取值
VALID_SPEC_MODES = ("fast-track", "full")

# 缺省模式
DEFAULT_SPEC_MODE = "full"


def read_spec_mode(project_root, spec_name: str) -> str:
    """读取 spec 的执行模式，缺省/非法一律返回 ``"full"``。

    Args:
        project_root: 项目根路径（str 或 Path）。
        spec_name: SPEC 名称（kebab-case，openspec/changes/<spec>/ 目录名）。

    Returns:
        ``"fast-track"`` 或 ``"full"``。文件缺失 / 无 mode 字段 / 值非法 /
        解析失败均返回 ``"full"``（读侧容错，不抛异常）。
    """
    yaml_path = (
        Path(project_root) / "openspec" / "changes" / spec_name / ".openspec.yaml"
    )
    if not yaml_path.is_file():
        return DEFAULT_SPEC_MODE
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return DEFAULT_SPEC_MODE
    if not isinstance(data, dict):
        return DEFAULT_SPEC_MODE
    mode = data.get("mode")
    if mode not in VALID_SPEC_MODES:
        return DEFAULT_SPEC_MODE
    return mode


def is_fast_track(project_root, spec_name: str) -> bool:
    """便捷判定：spec 是否走快速路径。"""
    return read_spec_mode(project_root, spec_name) == "fast-track"