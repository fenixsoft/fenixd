"""log_adapter.py — 标准 logging.Logger → fenixd (component, message) 签名适配器。

fenixd 车道内部日志接口是 core.logger.Logger 的双参签名
``info(component, message)``；测试缺省兜底与手工激活路径拿到的是标准
``logging.Logger``，需经本适配器转接（component 会被当消息、message 当
位置参数，message 含 ``%`` 时还会格式化报错）。

此前 core/regression.py 与 core/knowledge_backfill.py 各自维护一份同名
``_StdLoggerAdapter`` 且签名语义已漂移（regression 版对多余参数告警丢弃、
knowledge_backfill 版严格两参多传即 TypeError），同名不同语义的复制粘贴
使后续修日志行为时容易只改一处造成两车道分叉。现收口到本单点实现，
由参数选择形态（code-review item 205eef6ee458）。
"""

import logging
import sys


class StdLoggerAdapter:
    """标准 ``logging.Logger`` → fenixd ``(component, message)`` 签名适配。

    多余参数两形态（strict 选择）：

    - ``strict=False``（缺省，regression 形态）：调用方若按 core.logger.Logger
      签名传第三位 context dict（或标准 logging 风格的格式化参数），本桥无法
      承载——此前 ``*a/**kw`` 静默吞掉，排查时日志缺字段且无任何提示；现降级
      记一条 WARNING 暴露误用后丢弃（code-review item 02713b6883fb）。
    - ``strict=True``（knowledge_backfill 形态）：严格双参签名，多传即
      TypeError。

    ``message_format`` 为 component/message 的落盘模板；两车道既有输出格式
    不同（regression ``[component] message``、knowledge_backfill
    ``component: message``），按原样保留，避免收口顺带改写日志行为。

    方法面覆盖 core.logger.Logger 全部五方法（debug/info/warning/error/
    exception），车道代码按 core.logger.Logger 签名调用不会 AttributeError
    （code-review item dbee0be8a91b）；``exception`` 语义对齐 core.logger.
    Logger.exception——except 块外不落「NoneType: None」伪堆栈。
    """

    def __init__(
        self,
        std_logger: logging.Logger,
        *,
        strict: bool = False,
        message_format: str = "[%s] %s",
    ):
        self._std = std_logger
        self._strict = strict
        self._fmt = message_format

    def _warn_dropped(self, component, a, kw):
        # 告警直接走标准 logger 且只传 %s 格式化参数，不经本适配器分派，
        # 不会经被丢弃的参数路径递归
        self._std.warning(
            "std logger 适配：日志调用携带未支持的第 3+ 位位置参数/关键字参数"
            "（fenix context dict），已丢弃 logger=%s component=%r"
            " positional=%d keyword=%d",
            getattr(self._std, "name", "?"), component, len(a), len(kw),
        )

    def _check_extra(self, method: str, component, a: tuple, kw: dict) -> None:
        """多余参数分派：strict 抛 TypeError（保留两参签名语义），否则告警丢弃。"""
        if not (a or kw):
            return
        if self._strict:
            raise TypeError(
                f"{type(self).__name__}.{method}() 为严格双参签名"
                f"(component, message)，不接受多余的 {len(a)} 个位置参数/"
                f"{len(kw)} 个关键字参数"
            )
        self._warn_dropped(component, a, kw)

    def info(self, component, message, *a, **kw):
        self._check_extra("info", component, a, kw)
        self._std.info(self._fmt, component, message)

    def warning(self, component, message, *a, **kw):
        self._check_extra("warning", component, a, kw)
        self._std.warning(self._fmt, component, message)

    def error(self, component, message, *a, **kw):
        self._check_extra("error", component, a, kw)
        self._std.error(self._fmt, component, message)

    def debug(self, component, message, *a, **kw):
        self._check_extra("debug", component, a, kw)
        self._std.debug(self._fmt, component, message)

    def exception(self, component, message, *a, **kw):
        # 对齐 core.logger.Logger.exception：ERROR 级 + 当前异常堆栈经
        # std 通道落盘。except 块外 sys.exc_info() 为 (None, None, None)，
        # 传 exc_info=True 会让 stdlib Formatter 落「NoneType: None」伪堆栈，
        # 与 core.logger.Logger 同口径归一为 None。
        self._check_extra("exception", component, a, kw)
        exc = sys.exc_info()
        exc_info = exc if exc[0] is not None else None
        self._std.error(self._fmt, component, message, exc_info=exc_info)
