"""core.dashboard.data.state — STATE.md 基础解析（state 组）。

refactor-dashboard-data-module D3 分组：本模块承载 state 职责域。
"""

import re
from pathlib import Path


# 布尔标记归一口径（add-cancelled-spec-resume-action D1 单点）：
# 与下方 parse_state 对 frozen/_cancelled_hold 的归一化逐字一致，供
# 摘要字段与恢复动作对「未经 parse_state 的原始值」防御式复用。
BOOL_FLAG_VALUES = ("true", "1", "yes")


def normalize_bool_flag(v) -> bool:
    """布尔标记归一读值：bool 直接判定，文本按小写白名单。

    STATE.md 序列化 Python 字面量（`- _cancelled_hold: False`），文本
    `False` 是真值字符串——裸 bool() 会把每条带该字段的非保持 SPEC 判成
    保持态。MUST NOT 用裸真值判定读 frozen / _cancelled_hold。
    """
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in BOOL_FLAG_VALUES


def parse_state(project_root) -> dict:
    """解析项目 STATE.md，返回 {spec_name: {key: value}}。"""
    state_path = Path(project_root) / ".fenix" / "STATE.md"
    if not state_path.exists():
        return {}
    specs = {}
    current_name = None
    current_entry = {}
    try:
        for line in state_path.read_text(encoding="utf-8").split("\n"):
            m = re.match(r"^###\s+(.+)$", line)
            if m:
                if current_name and current_entry and "status" in current_entry:
                    specs[current_name] = current_entry
                current_name = m.group(1).strip()
                current_entry = {}
                continue
            m = re.match(r"^-\s+([a-z_]+):\s*(.*)$", line)
            if m and current_name:
                key = m.group(1)
                val = m.group(2).strip()
                if key == "priority":
                    try:
                        val = int(val)
                    except ValueError:
                        val = 999
                elif key == "impl_run_budget_override":
                    try:
                        val = int(val)
                    except ValueError:
                        val = None
                elif key in ("frozen", "_cancelled_hold"):
                    # 冻结标记归一到真布尔（fix：结构化冻结识别）。STATE.md 是
                    # 文本表，`frozen: False` 不归一即得真值字符串 'False'——
                    # 用真值判定会把每一条普通 blocked 都误判为冻结态。
                    # _cancelled_hold（add-cancelled-spec-resume-action D1）：
                    # 取消保持标记同口径归一——存量条目序列化为
                    # `- _cancelled_hold: False`（Python 字面量），不归一即
                    # 真值字符串，摘要字段与恢复动作会把非保持 SPEC 误判为
                    # 取消保持态。
                    val = normalize_bool_flag(val)
                elif val.lower() in ("null", "none", ""):
                    val = None
                current_entry[key] = val
        if current_name and current_entry and "status" in current_entry:
            specs[current_name] = current_entry
    except (OSError, UnicodeDecodeError):
        pass
    return specs
