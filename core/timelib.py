"""timelib — 全框架唯一时间原语模块（add-timelib-consolidation-layer 1.1）。

零第三方依赖。分层约定（spec「分层时区约定」冻结）：

- **存储与计算层一律 aware UTC**：持久化字段（jsonl/STATE.md/台账/知识库
  机器字段）经 ``to_storage`` 序列化（ISO UTC、``Z`` 后缀）；窗口、时效、
  排序等时间运算一律在 aware 值上进行。
- **本地时区只出现在渲染边界**：CLI 展示（``fmt_display``）、knowledge
  真相源盖戳、浏览器 dayjs 前端；以及调度语义边界（``HH:MM`` 人类时刻
  配置，进入计算前转 aware UTC，SPEC-B 承接）。
- 浏览器前端 dayjs 本地渲染与 ``verify_engine/browser.py`` 的
  ``timezone_id``（playwright 语义）不在本约定管辖范围。

naive 唯一策略（定调 2026-09-30）：``parse_ts`` 对无时区后缀的输入**统一
按系统本地时区解读**。依据：存量 naive 数据实测多数产自本地 ``now()``
（self_review 字段、外部/人工 marker、剥时区写入链），机器时区固定
Asia/Shanghai 无 DST、无换算陷阱。任何模块 MUST NOT 自行实现第二种
naive 解读；存量违例以 ``tests/test_timelib_guard.py`` 白名单登记
（SPEC-B 逐批迁移并收缩白名单承接）。

API（6 函数契约冻结，SPEC-B 只许 ADDITIONAL 扩展，不破坏本契约）：

- ``now_utc() -> datetime``            aware UTC 当前时间
- ``now_local() -> datetime``          aware 本地时区当前时间
- ``parse_ts(value) -> datetime|None``  唯一解析入口（ISO/``Z``/naive/纯日期）
- ``from_epoch(ts) -> datetime``       epoch 秒 → aware UTC
- ``to_storage(dt) -> str``            写侧唯一序列化（ISO UTC、``Z`` 后缀）
- ``fmt_display(value, fmt) -> str``   渲染边界：datetime | ISO 串 → 本地人读串
"""

from datetime import datetime, timezone

__all__ = [
    "now_utc",
    "now_local",
    "parse_ts",
    "from_epoch",
    "to_storage",
    "fmt_display",
]


def now_utc() -> datetime:
    """aware UTC 当前时间（等价 ``datetime.now(timezone.utc)``）。"""
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    """aware 本地时区当前时间（等价 ``datetime.now().astimezone()``）。"""
    return datetime.now().astimezone()


def parse_ts(value):
    """唯一时间戳解析入口；失败返回 None（house 容错风格，不抛异常）。

    接受 ISO 字符串：``Z`` 后缀（含小写 ``z``）、``±HH:MM`` 偏移、无偏移
    naive（按**本地时区**解读——唯一策略，见模块 docstring）、纯日期串
    （``YYYY-MM-DD``，本地零点）。``None``/非字符串/空串/非法串返回 None。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # 仅剥离结尾一个 Z（ISO 8601 UTC 标记；replace 全量替换会误伤串中其他
    # "Z" 字符）。Python 3.10 的 fromisoformat 不认 Z，显式归一 +00:00。
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # naive → 本地 aware（astimezone() 的 naive 语义：视作系统本地时区）
        dt = dt.astimezone()
    return dt


def from_epoch(ts: float) -> datetime:
    """epoch 秒 → aware UTC（替代裸 ``fromtimestamp()`` 的本地时区歧义）。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def to_storage(dt: datetime) -> str:
    """写侧唯一序列化：ISO UTC、``Z`` 后缀结尾。

    任一 aware datetime（UTC 或本地）都折算到同一 UTC 时刻；naive 输入按
    本地时区解读（与 ``parse_ts`` 唯一策略一致）。本地 ``2026-09-30 10:33
    +08:00`` 序列化为 ``2026-09-30T02:33:00Z``。
    """
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fmt_display(value, fmt="%Y-%m-%d %H:%M:%S") -> str:
    """渲染边界转换：datetime 或 ISO 字符串 → 本地时区人读串。

    aware 值折算到本地时区；naive 值视作已是本地墙钟。解析失败/不支持的
    类型返回空串（渲染层 fail-soft，调用方直接展示或走自身兜底）。
    """
    if isinstance(value, str):
        dt = parse_ts(value)
    elif isinstance(value, datetime):
        dt = value
    else:
        dt = None
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone().strftime(fmt)
