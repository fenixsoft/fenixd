"""spec_mode.py — SPEC 执行模式读取器（add-fast-track-mode / D2）。

读取 ``spec/changes/<spec>/.spec.yaml`` 的 ``mode`` 字段：

  - ``fast-track``：快速路径——单个 agent run 全包（实现 → 场景设计 → 验证 → 判定）
  - ``full``（缺省）：完整模式——现有多 Agent 分段流水线

读取侧容错（design D2）：字段缺失 / 值非法 / 文件不存在 / 解析失败，
一律返回 ``"full"``——存量 spec 零迁移，行为与引入本能力之前完全一致。

纯函数模块（仅依赖 yaml 与命名契约单源 core.spec_naming，后者 stdlib-only
不回指本模块、无循环障碍），daemon 派发路径与 Dashboard data 层共用。
"""

import yaml
from pathlib import Path

from core.spec_naming import validate_spec_name

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
        解析失败均返回 ``"full"``（读侧容错，不抛异常）。``spec_name`` 未通过
        spec_naming.validate_spec_name 命名契约（含空值、路径成分、NUL 字节、
        非 str 类型、非 kebab-case 形态、超 200 字节）时同样返回 ``"full"``。
    """
    if validate_spec_name(spec_name) is not None:
        # 命名守卫复用 spec_naming 单源（item d71d640e2ef1，勿另立同值副本）：
        # kebab-case 白名单天然覆盖旧黑名单的全部拒绝面——空值、``.``、``..``、
        # 路径分隔符均不匹配 ^[a-z][a-z0-9]*(-[a-z0-9]+)*$，NUL 字节亦然（不
        # 在 [a-z0-9-] 内，无须额外保留黑名单分支），由此守住「防止拼接过
        # spec/changes 越界读其他目录」与「NUL 会让 stat()/resolve() 抛
        # ValueError（embedded null byte，except OSError 兜不住）」两条既有
        # 防线；单源还额外拦下 'Fix_Foo'、'.foo'、超 200 字节等旧黑名单放过、
        # 能走到 stat/read 的输入。非 str 入参（int/list 等）会让成员测试抛
        # TypeError、lone surrogate 会让文件名编码抛 UnicodeEncodeError，均在
        # 单源入口先拒绝（类型防御口径对齐 item aa0fdc867986）。不合法一律
        # 按读侧容错返回缺省模式，行为契约不变。
        return DEFAULT_SPEC_MODE
    yaml_path = Path(project_root) / "spec" / "changes" / spec_name / ".spec.yaml"
    try:
        st = yaml_path.stat()
        key = (str(yaml_path.resolve()), st.st_mtime_ns, st.st_size)
    except OSError:
        # resolve() 在祖先目录符号链接成环（ELOOP）等罕见 FS 异常下自身也会抛
        # OSError，兜底退回原始路径作缓存键，保证读侧容错「不抛异常」契约。
        # 该哨兵键与文件真实状态无关联，一旦落缓存便同键永久命中、无法自愈
        # （如 EACCES 事后修复仍会返回过期模式），故 key=None 表示本次只计算
        # 不读写缓存——下次调用重新 stat，与键取自真实 stat 的路径同享自愈性。
        key = None
    if key is not None:
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
    if key is not None:
        if len(_SPEC_MODE_CACHE) > _SPEC_MODE_CACHE_MAX:
            _SPEC_MODE_CACHE.clear()
        _SPEC_MODE_CACHE[key] = mode
    return mode


def is_fast_track(project_root, spec_name: str) -> bool:
    """便捷判定：spec 是否走快速路径。"""
    return read_spec_mode(project_root, spec_name) == "fast-track"
