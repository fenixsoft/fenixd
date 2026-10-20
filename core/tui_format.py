"""core.tui_format — TUI 报告脚本共享的展示层格式化助手。

bin/fenix_status.py 与 bin/fenix_process.py（/fenix-status、/fenix-process
数据源）共用的时长/时间戳格式化单点（code-review item 50a1202e3e91：此前
_fmt_dur/_local_ts 在两个脚本各持一份，小时段补零口径漂移 2h05m vs 2h5m，
同一 SPEC 时长在两份报告里显示不一致，修口径须改多处）。
"""

from core.timelib import fmt_display


def local_ts(iso_str, fmt="%H:%M:%S"):
    """UTC ISO → 本地时区显示（日志层全 UTC 写入，展示层转本地）。

    默认 fmt 与回退切片 [:19] 是既有展示契约（test_cli_time_display 钉死）；
    需要日期的调用点显式传 fmt="%m-%d %H:%M"。

    前置约定：日志层写入的 UTC 串一律带时区后缀（Z / ±HH:MM）。底层
    timelib.parse_ts 对无偏移的 naive 串按本地时区解读（非转换）——若日志层
    写出裸 UTC 形态会原样当本地墙钟展示、产生静默时区错位（code-review
    3dd0dd9c9c7d 注记）。
    """
    # SPEC-B 批⑤：渲染边界统一走 timelib.fmt_display（解析内核 parse_ts
    # 单源不变）；解析失败仍走既有 [:19] 切片回退——fmt_display 渲染层
    # fail-soft 返回空串，此处转译为既有展示契约的 [:19] 回退；None/空串
    # 直接返回空串，不让 str(None)[:19] 的字面量「None」冒充时间戳。
    out = fmt_display(iso_str, fmt)
    if out:
        return out
    if not iso_str:
        return ""
    return str(iso_str)[:19]


def fmt_dur(seconds) -> str:
    """秒数 → 紧凑时长（30s / 5m / 2h5m / 1d5h0m）；非正数或非法输入返回空串。

    截断口径：浮点秒数经 int() 向零截断而非四舍五入（599.9s → 9m），展示层
    可接受的近似（code-review 96d3d80c773d 注记）。
    """
    try:
        s = int(seconds or 0)
    except (TypeError, ValueError, OverflowError):
        return ""
    if s <= 0:
        return ""
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    # 时长格式全段不补零；小时/天级一律展开全部下级单位（整点也补 0m，
    # 如 2h5m、1d5h0m、1h0m——两条分支对零分钟口径一致，item 4c89b35d41ce）
    if s < 86400:
        return f"{s // 3600}h{(s % 3600) // 60}m"
    return f"{s // 86400}d{(s % 86400) // 3600}h{(s % 3600) // 60}m"
