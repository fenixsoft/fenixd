"""spec_mode.py — SPEC 执行模式读取器（add-fast-track-mode / D2）。

读取 ``spec/changes/<spec>/.spec.yaml`` 的 ``mode`` 字段：

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

# 签名缓存（dashboard-spec-summary-index D4）：按 (真实路径, mtime_ns, size) 缓存，
# 命中不重读文件与 YAML 解析；写路径不维护显式失效（写后 mtime 已变，自然失效，
# 与 data._RUN_TASK_CACHE 同模式）。有界：超出上限整体清空（防写频繁时旧键残留无界增长）。
# 已知窗口（接受现状）：键取自 stat、内容取自其后的 read_text，两步之间若文件被改写
# 且改写后 (mtime_ns, size) 恰好与旧值一致（如 cp -p 回灌同尺寸内容），新内容会记在
# 旧键下、同键命中返回过期模式——概率极低，且下一次真实 mtime 变化即自愈；读后复核
# 只能把窗口缩小到 read→复核 stat 之间而无法消除，故不做复核，仅在此标注该窗口。
_SPEC_MODE_CACHE: dict = {}
_SPEC_MODE_CACHE_MAX = 2048


def read_spec_mode(project_root, spec_name: str) -> str:
    """读取 spec 的执行模式，缺省/非法一律返回 ``"full"``。

    Args:
        project_root: 项目根路径（str 或 Path）。
        spec_name: SPEC 名称（kebab-case，spec/changes/<spec>/ 目录名）。

    Returns:
        ``"fast-track"`` 或 ``"full"``。文件缺失 / 无 mode 字段 / 值非法 /
        解析失败均返回 ``"full"``（读侧容错，不抛异常）。``spec_name`` 含
        路径成分（空值、``.``、``..``、路径分隔符或 NUL 字节）时同样返回
        ``"full"``。
    """
    if (
        not spec_name
        or spec_name == "."
        or "/" in spec_name
        or ".." in spec_name
        or "\0" in spec_name
    ):
        # 保守拒绝路径成分：防止名称拼接过 spec/changes 越界读到其他目录；
        # NUL 字节则会让 stat()/resolve() 抛 ValueError（embedded null byte，
        # 非 OSError，except OSError 兜不住），同样在入口拒绝以守住「不抛异常」契约。
        return DEFAULT_SPEC_MODE
    yaml_path = Path(project_root) / "spec" / "changes" / spec_name / ".spec.yaml"
    try:
        st = yaml_path.stat()
        key = (str(yaml_path.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        # resolve() 在祖先目录符号链接成环（ELOOP）等罕见 FS 异常下自身也会抛
        # OSError，兜底退回原始路径作缓存键，保证读侧容错「不抛异常」契约。
        key = (str(yaml_path), None)
    cached = _SPEC_MODE_CACHE.get(key)
    if cached is not None:
        return cached
    mode = DEFAULT_SPEC_MODE
    if yaml_path.is_file():
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            data = None
        if isinstance(data, dict) and data.get("mode") in VALID_SPEC_MODES:
            mode = data["mode"]
    if len(_SPEC_MODE_CACHE) > _SPEC_MODE_CACHE_MAX:
        _SPEC_MODE_CACHE.clear()
    _SPEC_MODE_CACHE[key] = mode
    return mode


def is_fast_track(project_root, spec_name: str) -> bool:
    """便捷判定：spec 是否走快速路径。"""
    return read_spec_mode(project_root, spec_name) == "fast-track"
