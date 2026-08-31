"""reporting.py — ReportBuilder：项目报告/日报/pushable specs（refactor-core-packages 阶段 6）。

SPEC 状态经门面回引 self._pm.state_machine（design D3 规则 3）；
组件内非自有状态/方法的 self.X 一律改写为 self._pm.X，保住门面
实例上的测试补丁缝与跨组件调用路径。

"""

from datetime import datetime, timezone
import re


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

        for name, entry in sorted(all_specs.items(),
                                   key=lambda x: x[1].get("priority", 999)):
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
        """Generate daily report and append to PROJECT_LOG.md."""
        report = self._pm.generate_report()

        log_path = self._pm.project_root / "PROJECT_LOG.md"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n\n---\n\n{report}\n")

        self._pm.logger.info("pm_engine", "Daily report generated")


    def get_pushable_specs(self):
        """Get all done SPECs awaiting push approval."""
        return self._pm.state_machine.get_by_status("done")


    @staticmethod
    def _is_push_backoffed(spec: dict) -> bool:
        """判断 spec 是否在 push 退避期内（error 含 next_retry_at 且未到期）。

        退避标记约定：error 文本中包含 `[push_backoff next_retry_at=<unix_ts>]`。
        设计原则（D3）：退避期内 recovery 重放直接跳过，不发 push 命令。
        """
        error = spec.get("error") or ""
        m = re.search(r"\[push_backoff next_retry_at=(\d+)\]", error)
        if not m:
            return False
        try:
            return float(m.group(1)) > datetime.now(timezone.utc).timestamp()
        except (TypeError, ValueError):
            return False


    @staticmethod
    def _get_push_retry_count(spec: dict) -> int:
        """从 error 文本中提取 push 连续重试次数。"""
        error = spec.get("error") or ""
        m = re.search(r"\[push_attempts=(\d+)\]", error)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                pass
        return 0
