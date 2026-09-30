"""core.dashboard.data._logutil — 数据组共享的日志兜底出口。

「logger 实例优先（fenixd Logger），缺省打印 stderr」的同款兜底逻辑曾在
runs.py（_retention_log）与 spec_archive.py（_archive_log）逐字重复内联
（code-review item e57bb78b236c）；收敛到此处单源，出口行为演进只改一处。
"""

import sys


def fallback_log(logger, level: str, msg: str) -> None:
    """logger 实例优先：按 level 调用（异常吞掉），缺省打印 stderr。"""
    if logger is not None:
        try:
            getattr(logger, level)("fenixd", msg)
        except Exception:
            pass
    else:
        print(f"[fenixd] {msg}", file=sys.stderr)
