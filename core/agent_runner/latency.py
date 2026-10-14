"""
latency.py — run 级 API 延迟统计纯函数（refactor-agent-runner-module D4）。

从 runner.py 拆出的模块级延迟统计纯函数与常量，供在线（_run_agent 流式循环
旁路）与事后（bin/analyze_run_latency.py）共用同一套口径：
对事件序列 `tool_result → 下一个 assistant` 间隔采样为 API 往返样本，再计算
直方图摘要（轮数/中位/p90/max/长尾>60s 计数与占比）。纯读侧，不改变流式事件
处理时序。

本模块 MUST NOT `import runner`（D4）：`_default_ts_parser` 自带等价实现
（数值 timestamp 直通；ISO 字符串走 ``timelib.parse_ts`` 解析——SPEC-B 批②
收拢单源，naive（无时区）按本地时区解读（timelib 唯一 naive 策略，与
runner.py `AgentRunner._parse_event_timestamp` 同口径）；缺失/异常返回
None——两解析器行为逐字段一致，由契约测试锁定）；runner.py 保留同名模块级
函数并一行委托。
"""

from core.timelib import parse_ts

# 长尾阈值：样本 > 该值（秒）计为一次 stall（run-latency-observability D1）。
# 随消费者同迁本模块（D4 / D2b 规则 3）：latency_stats 读取本模块常量，避免
# 回引 runner 造成循环 import。runner.py re-export 维持既有导入路径。
LATENCY_STALL_SECONDS = 60.0

# run 期内单次 API 往返样本的 WARNING 阈值（evo-add-api-stall-observability
# 1.1）：在飞采样点（_run_agent 流式循环旁路）对超过该值的单次样本在完成
# 时点即时打一条 WARNING（期内逐次现场），纯记录、不触发任何干预。
#
# 语义分离（勿合并）：
# - 与 LATENCY_STALL_SECONDS（上方，统计口径：深扫行、run 末摘要、
#   stall_ratio 分母均依赖）互不改写——改它会破坏历史可比性；
# - 与 runner.py 既有 RUN_STALL_ROUND_SECONDS = 120.0（run-stop-loss 判停
#   判据一的样本计入线）**同值不同义**：一个是期内告警线（本常量，纯读侧
#   记录），一个是判停计入线（行为面）。严禁合并、复用或互相引用——合并
#   即把告警线改动泄漏成判停行为变更。
STALL_ROUND_WARN_SECONDS = 120.0

# 单轮停滞升级线（evo-api-stall-signal-grading 1.1）：单轮 API 往返样本超过
# 该值（秒）时，无论是否连续，直接按 WARNING-escalated 分级告警（120-300 秒
# 的孤立单轮降级 INFO 只计数）。独立声明、不并入上方同值不同义常量组——
# 本常量是分级线（信号降噪面），与统计线/告警线/判停线语义互不相干；
# modules contract 测试锁三既有常量同源，新常量不在其列。
STALL_ROUND_ESCALATE_SECONDS = 300.0


def classify_round_stall(streak: int, round_seconds: float) -> str:
    """单轮停滞信号分级纯函数（evo-api-stall-signal-grading 1.1）。

    规则（优先级从高到低）：
    - ``round_seconds > STALL_ROUND_ESCALATE_SECONDS``（300s）→
      ``"warning-escalated"``（单轮超限，无论连续与否都打 WARNING）；
    - ``streak >= 2``（连续第 2 轮及以上停滞）→ ``"warning"``；
    - 其余（孤立的单轮 120-300 秒）→ ``"info"``（只计数、不打 WARNING）。

    纯函数：不做 I/O、不读全局状态。``streak`` 口径由调用方计得——连续 =
    相邻样本逐个 >STALL_ROUND_WARN_SECONDS（遇 ≤120s 样本重置计数），发射点
    从 latency_state["samples"] 尾部回溯计数。

    Args:
        streak: 含当前轮在内的连续停滞轮数（当前轮已 >120s 时 ≥1）。
        round_seconds: 当前轮 API 往返秒数（调用方已保证 >120s 才进入分级）。

    Returns: ``"info"`` | ``"warning"`` | ``"warning-escalated"``。
    """
    if round_seconds > STALL_ROUND_ESCALATE_SECONDS:
        return "warning-escalated"
    if streak >= 2:
        return "warning"
    return "info"


def iter_events(entries):
    """逐条 yield（兼容既有调用方传 list 或生成器）。"""
    yield from entries


def _default_ts_parser(entry: dict):
    """默认 timestamp 解析器（D4 修订版：latency.py 自带等价实现）。

    与 runner.py `AgentRunner._parse_event_timestamp` 行为逐字段一致：
    - 数值 timestamp（非布尔 int/float；bool 是 int 子类，显式排除以免
      True/False 直通成 epoch 1.0/0.0 秒样本）→ float 直通；
    - ISO 字符串 → ``timelib.parse_ts`` 的 epoch 秒（naive 无时区值按本地
      时区解读，timelib 唯一 naive 策略；SPEC-B 批②收拢单源）；
    - 缺失/解析异常 → None。
    """
    raw = entry.get("timestamp")
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    # SPEC-B 批②：解析内核收拢 parse_ts（唯一入口；失败返回 None 不抛）。
    # naive（无时区）解读跟齐读侧唯一策略（naive→本地）——与 runner.
    # _parse_event_timestamp（SPEC-A 4.2 已切 parse_ts）同口径，同一份
    # stream-json 转录两解析器不再各持一种 naive 策略。
    dt = parse_ts(str(raw))
    return dt.timestamp() if dt is not None else None


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

    本判定为延迟采样（``latency_samples_from_events`` / ``_run_agent`` 内联
    读侧）与流量活性（``_turn_traffic_active``）三处消费点的**单一真源**——
    不得在别处再次硬编码事件类型比较（design D1：根因即三处独立发散）。
    """
    if entry.get("type") == "tool_result":
        return True
    if entry.get("type") == "user":
        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        return isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
    return False


def latency_samples_from_events(entries, parser=None) -> list:
    """从事件序列提取 API 往返样本（tool_result → 下一个 assistant 间隔）。

    口径（design D3，与 2026-09-05 事故分析一致）：记录最近一个
    ``tool_result`` 事件（按 ``_entry_is_tool_result`` 统一识别——真实
    stream-json 转录以 ``user`` 事件包裹 ``tool_result`` content block
    承载，兼容顶层 ``tool_result`` 事件）的 timestamp，遇到下一个
    ``assistant`` 事件时两者之差 = 一次 API 往返样本；随后清空待配对的
    tool_result（一个样本只配对一次）。timestamp 缺失的事件不参与（跳过）：
    ``tool_result`` 缺 timestamp 时清空待配对点、丢弃该轮样本（不沿用更早
    的 tool_result 跨轮配对，以免样本区间被拉长而虚高）；``assistant`` 缺
    timestamp 时不产样本，待配对的 tool_result 保留给下一个 assistant。
    样本列表可空。差值 < 0（timestamp 非单调：转录乱序、时钟回拨等）视为
    无效测量，跳过不入样本（待配对 tool_result 仍清空，维持「一个样本只
    配对一次」），以免负样本污染下游 median/p90/max/stall_ratio 口径。

    Args:
        entries: 事件 dict 序列（list / 生成器）。
        parser: timestamp 解析函数（缺省 = 本模块 _default_ts_parser）。

    Returns: float 非负秒样本列表（含 >60s 长尾；顺序为事件到达序；
    timestamp 乱序产生的负差值已剔除）。
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
            else:
                # tool_result 缺 timestamp：本轮无法测量，清空待配对点、
                # 丢弃该轮样本（沿用更早的 tool_result 会跨轮错配、样本虚高；
                # 与下方负差值同取「无效测量不入样本」口径）。
                last_tool_result_ts = None
        elif etype == "assistant":
            ts = parser(e)
            if ts is not None and last_tool_result_ts is not None:
                delta = ts - last_tool_result_ts
                # 负差值 = timestamp 非单调（转录乱序/时钟回拨），非真实
                # API 往返，跳过不入样本；待配对 tool_result 仍清空，
                # 维持「一个样本只配对一次」。
                if delta >= 0:
                    samples.append(delta)
                last_tool_result_ts = None
    return samples


def latency_stats(samples) -> dict:
    """把 API 往返样本压缩为直方图摘要（空样本安全返回全 0 键）。

    口径：负样本（timestamp 非单调的无效测量，见
    ``latency_samples_from_events``）先剔除再统计——rounds/stalls/
    stall_ratio 均基于同一非负有效样本集，stall_ratio 分母 = 有效样本数，
    语义自洽（在线旁路 runner._run_agent 内联采样亦经本函数收口）。

    Returns: {"rounds": int, "median": float|None, "p90": float|None,
              "max": float|None, "stalls": int, "stall_ratio": float}
        rounds 为有效（非负）样本数（=有 timestamps 的 API 往返轮数）；
        stalls 为 >60s 长尾样本数；stall_ratio = stalls/rounds（0 样本为 0）。
    """
    # 兜底剔除负样本：直接喂入的裸样本（如在线旁路内联采样）也去无效测量。
    valid = [s for s in samples if s >= 0]
    n = len(valid)
    base = {"rounds": n, "median": None, "p90": None, "max": None, "stalls": 0, "stall_ratio": 0.0}
    if n == 0:
        return base
    ordered = sorted(valid)
    base["median"] = _percentile(ordered, 0.5)
    base["p90"] = _percentile(ordered, 0.9)
    base["max"] = ordered[-1]
    base["stalls"] = sum(1 for s in valid if s > LATENCY_STALL_SECONDS)
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


def format_latency_summary(run_id: str, stats: dict, grade_counts: dict | None = None) -> str:
    """把摘要渲染为日志行（设计示例同款口径）。

    ``run planner-plan-xxx-a1: 58 rounds, median 3.2s, p90 78s, max 185s,
    stalls>60s=15 (26%)``。无样本时标注 0 rounds（中性可诊断文案——该 run
    无 API 往返样本；「真空跑」与「解析器失明」由延迟观测自检 WARNING 区分，
    这里不得归因于输入文件/旧转录）。

    ``grade_counts``（evo-api-stall-signal-grading 1.2）：可选分级计数
    ``{"warning": int, "info": int}``（warning 桶含 warning 与
    warning-escalated 两级信号，info 桶为降级只计数的孤立单轮）；传入时在
    行尾追加 ``, warning=N info=M``（既有 stalls>60s 口径不变；不传则行形态
    与历史逐字节一致——bin/analyze_run_latency.py 等无分级上下文的调用方
    零改动）。
    """
    if stats.get("rounds", 0) <= 0:
        return f"run {run_id}: 0 rounds（无 API 往返样本）"
    med = stats.get("median") or 0
    p90 = stats.get("p90") or 0
    mx = stats.get("max") or 0
    stalls = stats.get("stalls") or 0
    ratio = (stats.get("stall_ratio") or 0) * 100
    line = (
        f"run {run_id}: {stats['rounds']} rounds, "
        f"median {med:.1f}s, p90 {p90:.1f}s, max {mx:.1f}s, "
        f"stalls>{LATENCY_STALL_SECONDS:.0f}s={stalls} ({ratio:.0f}%)"
    )
    if grade_counts is not None:
        line += (
            f", warning={int(grade_counts.get('warning') or 0)}"
            f" info={int(grade_counts.get('info') or 0)}"
        )
    return line
