"""
_evidence.py — 证据处理共享工具（cli_runner / api_runner 单一实现）

证据 64KB 截断（_truncate）与 {env:VAR} 插值（_interpolate_env）原为
cli_runner 与 api_runner 的逐字副本（仅靠两侧 docstring 互注「同源同
口径」防漂移），提取为单一实现，两 Runner 由此引用，杜绝口径分叉。
"""

import re

_EVIDENCE_LIMIT = 64 * 1024  # 证据 64KB 截断上限


def _truncate(text: str) -> tuple:
    """证据截断：超过 64KB（UTF-8 字节口径）截断并带截断标记。返回 (截断后文本, truncated)。"""
    if text is None:
        return "", False
    # 按编码后字节数截断（与「64KB」声明同口径；中文等多字节输出按字符数
    # 比较会漏截）；errors="ignore" 丢弃尾部被切半的多字节序列，不出非法 UTF-8
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > _EVIDENCE_LIMIT:
        return encoded[:_EVIDENCE_LIMIT].decode("utf-8", errors="ignore"), True
    return text, False


def _interpolate_env(value: str, env: dict) -> str:
    """{env:VAR} 插值：未命中的占位符原样保留（防静默改写）。"""
    if not isinstance(value, str) or "{env:" not in value:
        return value

    def _repl(m):
        return env.get(m.group(1), m.group(0))

    return re.sub(r"\{env:([^}]+)\}", _repl, value)