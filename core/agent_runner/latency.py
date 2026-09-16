"""
latency.py — run 级 API 延迟统计纯函数（refactor-agent-runner-module D4）。

从 runner.py 拆出的模块级延迟统计纯函数与常量，供在线（_run_claude 流式循环
旁路）与事后（bin/analyze_run_latency.py）共用同一套口径：
对事件序列 `tool_result → 下一个 assistant` 间隔采样为 API 往返样本，再计算
直方图摘要（轮数/中位/p90/max/长尾>60s 计数与占比）。纯读侧，不改变流式事件
处理时序。

本模块 MUST NOT `import runner`（D4）：`_default_ts_parser` 自带等价实现
（数值 timestamp 直通；ISO 字符串按
``datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()`` 解析；
缺失/异常返回 None——与 runner.py `AgentRunner._parse_event_timestamp` 现行为
逐字段一致，由契约测试锁定）；runner.py 保留同名模块级函数并一行委托。
"""

from datetime import datetime

# 长尾阈值：样本 > 该值（秒）计为一次 stall（run-latency-observability D1）。
# 随消费者同迁本模块（D4 / D2b 规则 3）：latency_stats 读取本模块常量，避免
# 回引 runner 造成循环 import。runner.py re-export 维持既有导入路径。
LATENCY_STALL_SECONDS = 60.0


def iter_events(entries):
    """逐条 yield（兼容既有调用方传 list 或生成器）。"""
    yield from entries


def _default_ts_parser(entry: dict):
    """默认 timestamp 解析器（D4 修订版：latency.py 自带等价实现）。

    与 runner.py `AgentRunner._parse_event_timestamp` 行为逐字段一致：
    - 数值 timestamp（int/float）→ float 直通；
    - ISO 字符串 → ``datetime.fromisoformat(str(raw).replace("Z", "+00:00"))``
      的 epoch 秒；
    - 缺失/解析异常 → None。
    """
    raw = entry.get("timestamp")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _entry_is_tool_result(entry: dict) -> bool:
    """统一识别 stream-json 流转录中的 tool_result 事件（tool-result-stream-detection）。

    真实 ``claude -p --output-format stream-json`` 转录**从不**产生顶层
    ``type == "tool_result"`` 事件（窗口内 12 条实测转录顶层 tool_result
    0/12）：工具结果一律以 ``type == "user"`` 事件承载，包裹在
    ``message.content[]`` 中 ``{"type": "tool_result", ...}`` 的 content
    block 内。判定语义：

    - ``type == "tool_result"`` → True（**兼容层**：存量合成测试 / 旧形态转录；
      真实数据不产生该形态，注释留证非死代码）；
    - ``type == "user"`` 且 ``message.content`` 为列表且含至少一个
      ``{"type": "tool_result", ...}`` block → True（真实形态）；
    - 其余（``message.content`` 为字符串、仅含 ``text`` block 的 ``user``
      事件如 skill 加载消息、``assistant``/``system``/``result``/``stderr``
      等）→ False，杜绝假样本/假流量。

    本判定为延迟采样（``latency_samples_from_events`` / ``_run_claude`` 内联
    读侧）与流量活性（``_turn_traffic_active``）三处消费点的**单一真源**——
    不得在别处再次硬编码事件类型比较（design D1：根因即三处独立发散）。
    """
    if entry.get("type") == "tool_result":
        return True
    if entry.get("type") == "user":
        content = entry.get("message", {}).get("content")
        return isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content)
    return False


def latency_samples_from_events(entries, parser=None) -> list:
    """从事件序列提取 API 往返样本（tool_result → 下一个 assistant 间隔）。

    口径（design D3，与 2026-09-05 事故分析一致）：记录最近一个
    ``tool_result`` 事件（按 ``_entry_is_tool_result`` 统一识别——真实
    stream-json 转录以 ``user`` 事件包裹 ``tool_result`` content block
    承载，兼容顶层 ``tool_result`` 事件）的 timestamp，遇到下一个
    ``assistant`` 事件时两者之差 = 一次 API 往返样本；随后清空待配对的
    tool_result（一个样本只配对一次）。timestamp 缺失的事件不参与（跳过），
    样本列表可空。

    Args:
        entries: 事件 dict 序列（list / 生成器）。
        parser: timestamp 解析函数（缺省 = 本模块 _default_ts_parser）。

    Returns: float 秒样本列表（含 >60s 长尾；顺序为事件到达序）。
    """
    if parser is None:
        parser = _default_ts_parser
    samples: list = []
    last_tool_result_ts: float | None = None
    for e in iter_events(entries):
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        if _entry_is_tool_result(e):
            ts = parser(e)
            if ts is not None:
                last_tool_result_ts = ts
        elif etype == "assistant":
            ts = parser(e)
            if ts is not None and last_tool_result_ts is not None:
                samples.append(ts - last_tool_result_ts)
                last_tool_result_ts = None
    return samples


def latency_stats(samples) -> dict:
    """把 API 往返样本压缩为直方图摘要（空样本安全返回全 0 键）。

    Returns: {"rounds": int, "median": float|None, "p90": float|None,
              "max": float|None, "stalls": int, "stall_ratio": float}
        rounds 为样本数（=有 timestamps 的 API 往返轮数）；stalls 为
        >60s 长尾样本数；stall_ratio = stalls/rounds（0 样本为 0）。
    """
    n = len(samples)
    base = {"rounds": n, "median": None, "p90": None, "max": None,
            "stalls": 0, "stall_ratio": 0.0}
    if n == 0:
        return base
    ordered = sorted(samples)
    base["median"] = _percentile(ordered, 0.5)
    base["p90"] = _percentile(ordered, 0.9)
    base["max"] = ordered[-1]
    base["stalls"] = sum(1 for s in samples if s > LATENCY_STALL_SECONDS)
    base["stall_ratio"] = base["stalls"] / n
    return base


def _percentile(ordered: list, q: float) -> float:
    """已排序列表的线性插值分位数（q∈[0,1]）。"""
    if not ordered:
        return 0.0
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def format_latency_summary(run_id: str, stats: dict) -> str:
    """把摘要渲染为日志行（设计示例同款口径）。

    ``run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s,
    stalls>60s=15 (26%)``。无样本时标注 0 rounds（中性可诊断文案——该 run
    无 API 往返样本；「真空跑」与「解析器失明」由延迟观测自检 WARNING 区分，
    这里不得归因于输入文件/旧转录）。
    """
    if stats.get("rounds", 0) <= 0:
        return f"run {run_id}: 0 rounds（无 API 往返样本）"
    med = stats.get("median") or 0
    p90 = stats.get("p90") or 0
    mx = stats.get("max") or 0
    stalls = stats.get("stalls") or 0
    ratio = (stats.get("stall_ratio") or 0) * 100
    return (
        f"run {run_id}: {stats['rounds']} rounds, "
        f"median {med:.1f}s, p90 {p90:.1f}s, max {mx:.1f}s, "
        f"stalls>60s={stalls} ({ratio:.0f}%)"
    )