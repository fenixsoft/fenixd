"""path_safety.py — verify-progress 写盘路径成分净化（跨模块共用口径）。

engine / judge_files / scenario_static_check 拼接 ``.fenix/verify-progress``
下的写盘路径前统一套用本净化：spec_name 含 ``/``、``\\``、NUL 或为
``.`` / ``..`` 等纯点成分时经 f-string 拼接会写到预期目录之外
（正常 kebab-case spec 目录名不受影响）。
实现唯一（原 engine._safe_component 下沉，code-review items baf2a275da81 /
7e764b3f6b50），保证各处口径一致；本模块只依赖标准库，不引入反向依赖。
"""

from __future__ import annotations

import re


# 单成分字节上限（文件系统每成分 255 字节，预留 ``.json`` / ``_<seq>.png`` /
# ``report-<run_id>.json`` 等后缀空间）；超长按 UTF-8 字符边界安全截断，
# 防异常超长 spec 名拼出超限成分令 mkdir/open 抛 OSError（进度与报告静默缺失）。
_MAX_COMPONENT_BYTES = 200


def safe_component(name: str) -> str:
    """净化单个路径成分：分隔符（``/`` 与 ``\\``）与控制字符（含 NUL，
    ``\\x00-\\x1f`` 与 DEL）替换为下划线；剥除空白后为空或全由 ``.`` 组成
    的成分（含 ``.`` / ``..``）归一为下划线，避免拼接后逃出预期目录
    （code-review item b2c8a1c36121）。产出再截断到 ``_MAX_COMPONENT_BYTES``
    字节——只在多字节字符中间截断时回退到字符边界，正常 kebab-case 名
    不受影响。读写两侧路径同走本函数，截断口径天然一致。
    """
    stripped = str(name).strip()
    if not stripped or not stripped.strip("."):
        return "_"
    cleaned = re.sub(r"[\\/\x00-\x1f\x7f]", "_", stripped)
    encoded = cleaned.encode("utf-8", errors="ignore")[:_MAX_COMPONENT_BYTES]
    while encoded:
        try:
            return encoded.decode("utf-8") or "_"
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return "_"
