"""core.tui_format — TUI 报告脚本共享的展示层格式化助手。

bin/fenix_status.py 与 bin/fenix_process.py（/fenix-status、/fenix-process
数据源）共用的时长/时间戳格式化单点（code-review item 50a1202e3e91：此前
_fmt_dur/_local_ts 在两个脚本各持一份，小时段补零口径漂移 2h05m vs 2h5m，
同一 SPEC 时长在两份报告里显示不一致，修口径须改多处）。
"""

from datetime import datetime


def local_ts(iso_str, fmt="%H:%M:%S"):
    """UTC ISO → 本地时区显示（日志层全 UTC 写入，展示层转本地）。

    默认 fmt 与回退切片 [:19] 是既有展示契约（test_cli_time_display 钉死）；
    需要日期的调用点显式传 fmt="%m-%d %H:%M"。
    """
    try:
        return (
            datetime.fromisoformat(str(iso_str).replace("Z", "+00:00")).astimezone().strftime(fmt)
        )
    except Exception:
        return str(iso_str)[:19]


def fmt_dur(seconds) -> str:
    """秒数 → 紧凑时长（30s / 5m / 2h5m / 1d5h）；非正数或非法输入返回空串。"""
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if s <= 0:
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    # 时长格式全段不补零（与分钟/天级分支同一口径，如 2h5m、1d5h）
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60}m"
    return f"{s // 86400}d{(s % 86400) // 3600}h"
