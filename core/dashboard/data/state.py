"""core.dashboard.data.state — STATE.md 基础解析（state 组）。

refactor-dashboard-data-module D3 分组：本模块承载 state 职责域。
"""

import re
from pathlib import Path


# 布尔标记归一口径（add-cancelled-spec-resume-action D1 单点）：
# 与下方 _parse_state_text 对 frozen/_cancelled_hold 的归一化逐字一致，供
# 摘要字段与恢复动作对「未经 parse_state 的原始值」防御式复用。
BOOL_FLAG_VALUES = ("true", "1", "yes")

# 归档清单文件名（add-archive-state-migration D1）：已迁出 STATE.md 条目的
# 唯一居所，格式与 STATE.md 相同，与 core/state_machine.py 的
# ARCHIVE_MANIFEST_FILENAME 同源（此处复制常量避免叶子模块反向依赖
# state_machine 包循环；两处 MUST 同步修改）。
STATE_ARCHIVE_BASENAME = "STATE.archive.md"


def normalize_bool_flag(v) -> bool:
    """布尔标记归一读值：bool 直接判定，文本按小写白名单。

    STATE.md 序列化 Python 字面量（`- _cancelled_hold: False`），文本
    `False` 是真值字符串——裸 bool() 会把每条带该字段的非保持 SPEC 判成
    保持态。MUST NOT 用裸真值判定读 frozen / _cancelled_hold。
    """
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in BOOL_FLAG_VALUES


def _parse_state_text(text: str) -> dict:
    """STATE.md 同格式文本的条目解析公共循环（add-archive-state-migration 1.2）。

    ``parse_state``（活跃 STATE.md）与 ``parse_archived_state``（归档清单）
    共用同一套 `### <name>` + `- key: value` 解析与类型归一，保证两文件
    读侧口径零漂移。返回 {spec_name: {key: value}}；无 status 的小节丢弃
    （与既有 parse_state 行为一致）。
    """
    specs = {}
    current_name = None
    current_entry = {}
    for line in text.split("\n"):
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            if current_name and current_entry and "status" in current_entry:
                specs[current_name] = current_entry
            current_name = m.group(1).strip()
            current_entry = {}
            continue
        # 键名允许小写字母/下划线/数字（与 core/state_machine.py 同口径），
        # 支持 _token_warn_80 等带数字的内部字段；原有键名均不含数字，
        # 放宽不影响既有解析。
        m = re.match(r"^-\s+([a-z_][a-z0-9_]*):\s*(.*)$", line)
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
    return specs


def _read_state_like(project_root, basename: str) -> dict:
    """读取 .fenix/<basename> 并按 STATE.md 同格式解析；缺失/读失败返回空 dict。"""
    path = Path(project_root) / ".fenix" / basename
    if not path.exists():
        return {}
    try:
        return _parse_state_text(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return {}


def parse_state(project_root) -> dict:
    """解析项目 STATE.md，返回 {spec_name: {key: value}}。"""
    return _read_state_like(project_root, "STATE.md")


def parse_archived_state(project_root) -> dict:
    """解析归档清单 .fenix/STATE.archive.md，返回 {spec_name: {key: value}}。

    add-archive-state-migration 1.2：清单文件不存在时视为空清单（返回空
    dict，不报错）——读侧与迁出侧均以「缺失 = 空」为常态分支。
    """
    return _read_state_like(project_root, STATE_ARCHIVE_BASENAME)
