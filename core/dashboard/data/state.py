"""core.dashboard.data.state — STATE.md 基础解析（state 组）。

refactor-dashboard-data-module D3 分组：本模块承载 state 职责域。
"""

import re
from pathlib import Path


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
                elif key == "frozen":
                    # 冻结标记归一到真布尔（fix：结构化冻结识别）。STATE.md 是
                    # 文本表，`frozen: False` 不归一即得真值字符串 'False'——
                    # 用真值判定会把每一条普通 blocked 都误判为冻结态。
                    val = val.strip().lower() in ("true", "1", "yes")
                elif val.lower() in ("null", "none", ""):
                    val = None
                current_entry[key] = val
        if current_name and current_entry and "status" in current_entry:
            specs[current_name] = current_entry
    except (OSError, UnicodeDecodeError):
        pass
    return specs
