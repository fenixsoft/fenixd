"""reporting.py — ReportBuilder：项目报告/日报/pushable specs（refactor-core-packages 阶段 6）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；
组件内非自有状态/方法的 self.X 一律改写为 self._pm.X，保住门面
实例上的测试补丁缝与跨组件调用路径。

"""

from datetime import datetime, timezone
import re

from core.state_machine import (
    PUSH_ATTEMPTS_FIELD,
    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD,
)


def _coerce_int(value):
    """宽松 int 转换：缺失/非法（含经 STATE.md 往返的 str/None）回 None。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_push_backoff_marker(error_text):
    """从 error 文本摘取 push 退避截止标记并返回 unix 时间戳；无标记回 None。

    读侧回退解析与 clear_spec_error 过渡期摘取共用的单一实现（防词形
    漂移）。标记约定：``[push_backoff next_retry_at=<unix_ts>]``。
    """
    m = re.search(r"\[push_backoff next_retry_at=(\d+)\]", str(error_text or ""))
    return _coerce_int(m.group(1)) if m else None


def extract_push_attempts_marker(error_text):
    """从 error 文本摘取 push 连续重试计数标记并返回 int；无标记回 None。

    标记约定：``[push_attempts=N]``。共用约定同 extract_push_backoff_marker。
    """
    m = re.search(r"\[push_attempts=(\d+)\]", str(error_text or ""))
    return _coerce_int(m.group(1)) if m else None


class ReportBuilder:
    """项目报告组件（门面 PMEngine 的组合组件）。"""

    def __init__(self, pm):
        self._pm = pm  # 门面回引（design D3 规则 3：组件 → 门面 单向）

    def generate_report(self) -> str:
        """Generate a project status report."""
        all_specs = self._pm.state_machine.read_all()

        if not all_specs:
            return "📋 No SPECs yet. Create one with /fenix:new"

        # Count by status
        counts = {}
        for entry in all_specs.values():
            s = entry.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1

        lines = [
            f"## Fenix Project Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "### Summary",
        ]

        status_icons = {
            "drafted": "📝",
            "ready": "📌",
            "implementing": "🔨",
            "implemented": "🧪",
            "testing": "🔍",
            "verified": "✅",
            "bug-found": "🐛",
            "done": "🎯",
            "pushed": "🚀",
        }

        for name, entry in sorted(all_specs.items(), key=lambda x: x[1].get("priority", 999)):
            status = entry.get("status", "unknown")
            icon = status_icons.get(status, "❓")
            priority = entry.get("priority", "?")
            lines.append(f"- {icon} **{name}** (P{priority}): {status}")

        lines.append("")
        lines.append("### Stats")
        lines.append(f"- Total: {len(all_specs)}")
        for status, count in sorted(counts.items()):
            icon = status_icons.get(status, "❓")
            lines.append(f"- {icon} {status}: {count}")

        return "\n".join(lines)

    def generate_daily_report(self):
        """Generate daily report and append to PROJECT_LOG.md（.fenix/ 下）."""
        report = self._pm.generate_report()

        log_path = self._pm.project_root / ".fenix" / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{report}\n")

        self._pm.logger.info("pm_engine", "Daily report generated")

    def get_pushable_specs(self):
        """Get all done SPECs awaiting push approval."""
        return self._pm.state_machine.get_by_status("done")

    @staticmethod
    def _is_push_backoffed(spec: dict) -> bool:
        """判断 spec 是否在 push 退避期内（专用字段优先，error 文本标记回退）。

        双源约定（code-review item bbba88d8e6af）：退避标记原先仅寄居 error
        文本，Dashboard「清除错误」整段清 error 时连根抹掉 → 退避期归零、
        自动 push 从零重新起算。字段化后：写侧（engine._handle_push_failure）
        专用字段 + error 文本双活写入；本读侧专用字段优先，缺字段（存量
        spec）回退文本解析，现状行为不变。设计原则（D3）：退避期内 recovery
        重放直接跳过，不发 push 命令。
        """
        next_retry = _coerce_int(spec.get(PUSH_BACKOFF_NEXT_RETRY_AT_FIELD))
        if next_retry is None:
            next_retry = extract_push_backoff_marker(spec.get("error") or "")
        if next_retry is None:
            return False
        try:
            return float(next_retry) > datetime.now(timezone.utc).timestamp()
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _get_push_retry_count(spec: dict) -> int:
        """提取 push 连续重试次数（专用字段优先，error 文本标记回退）。

        双源约定同 _is_push_backoffed（code-review item bbba88d8e6af）：
        存量 spec 无专用字段时按文本 `[push_attempts=N]` 解析（现状不变），
        两源皆缺回 0。
        """
        attempts = _coerce_int(spec.get(PUSH_ATTEMPTS_FIELD))
        if attempts is None:
            attempts = extract_push_attempts_marker(spec.get("error") or "")
        return attempts if attempts is not None else 0
