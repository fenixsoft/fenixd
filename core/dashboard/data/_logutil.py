"""core.dashboard.data._logutil — 数据组共享的日志兜底出口。

「logger 实例优先（fenixd Logger），缺省打印 stderr」的同款兜底逻辑曾在
runs.py（_retention_log）与 spec_archive.py（_archive_log）逐字重复内联
（code-review item e57bb78b236c）；收敛到此处单源，出口行为演进只改一处。
"""

import logging
import sys


def fallback_log(logger, level: str, msg: str) -> None:
    """logger 实例优先：按 level 调用（异常吞掉），缺省打印 stderr。

    兼容两类 logger：
    - core.logger.Logger 及同款 (component, message) 签名的 duck-type 对象
      （如测试 _FakeLogger）：按 fenixd 私有约定 ``warning(component, msg)`` 调用；
    - 标准库 logging.Logger：退化为其原生单参形态 ``warning("fenixd %s", msg)``。
      若对 std logger 套用 (component, message) 双参约定，``"fenixd" % (msg,)``
      渲染会在 handler 内部抛 TypeError——该异常发生在 logging 框架内，
      except Exception 捕获不到，整条记录被静默丢弃。
    """
    if logger is not None:
        try:
            if isinstance(logger, logging.Logger):
                getattr(logger, level)("fenixd %s", msg)
            else:
                getattr(logger, level)("fenixd", msg)
        except Exception:
            pass
    else:
        print(f"[fenixd] {msg}", file=sys.stderr)
