"""path_safety.py — verify-progress 写盘路径成分净化（跨模块共用口径）。

engine / judge_files / scenario_static_check 拼接 ``.fenix/verify-progress``
下的写盘路径前统一套用本净化：spec_name 含 ``/``、``\\`` 或 NUL 时经
f-string 拼接会写到预期目录之外（正常 kebab-case spec 目录名不受影响）。
实现唯一（原 engine._safe_component 下沉，code-review items baf2a275da81 /
7e764b3f6b50），保证各处口径一致；本模块只依赖标准库，不引入反向依赖。
"""

from __future__ import annotations

import re


def safe_component(name: str) -> str:
    """净化单个路径成分：分隔符（``/`` 与 ``\\``）与 NUL 替换为下划线。"""
    return re.sub(r"[\\/\x00]", "_", str(name))
