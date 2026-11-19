"""core.dashboard.data._logutil — 数据组共享的日志兜底出口与口径适配。

「logger 实例优先（fenixd Logger），缺省打印 stderr」的同款兜底逻辑曾在
runs.py（_retention_log）与 spec_archive.py（_archive_log）逐字重复内联
（code-review item e57bb78b236c）；收敛到此处单源，出口行为演进只改一处。
标准 logging → Fenix ``(tag, msg)`` 双参口径适配器同理收敛单源（见
TagLoggerAdapter，code-review item fa5e403e58d1）。
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
            if isinstance(logger, (logging.Logger, logging.LoggerAdapter)):
                getattr(logger, level)("fenixd %s", msg)
            else:
                getattr(logger, level)("fenixd", msg)
        except Exception as exc:
            # 兜底器自身失败（level 拼错、duck-type logger 缺方法等）也要可观测，
            # 连同原 msg 一并落到 stderr，避免整条记录被无声丢弃；
            # 这行输出自身同样防抛（极端下 sys.stderr 可能缺失），维持「绝不抛」契约。
            try:
                print(
                    f"[fenixd] log-fallback failed (level={level!r}): {exc!r}; msg={msg!r}",
                    file=sys.stderr,
                )
            except Exception:
                pass
    else:
        try:
            print(f"[fenixd] {msg}", file=sys.stderr)
        except Exception:
            pass


class TagLoggerAdapter:
    """标准 logging logger → Fenix ``(tag, msg)`` 双参口径适配（单源）。

    Fenix 形态消费方（worktree_manager.stash_guard 自愈骨架、
    core.admin_store.AdminStore 留痕路径等）以
    ``logger.warning("component", msg)`` 双参口径写日志；直传标准 logging
    logger 会把 tag 当格式串、msg 当 % 参数。此前 admin_stray_wip 内联
    _StashGuardTagLogger（仅 warning）与 admin_actions 内联
    _AdminStoreTagLogger（warning+error 带 *args）各自重复一份
    （code-review item fa5e403e58d1），收敛到此处：统一 ``*args`` 兼容
    签名，warning/error 两级别覆盖，第三个消费方直接导入复用。

    - ``*args`` 兼容吞掉第三参 extra（AdminStore.append_admin_final 以
      ``{"run_id", "spec"}`` 调用；固定双参签名遇三参调用会在消费方自身
      except 块内 TypeError，被外层吃成「写入失败（fail-closed）」固定
      文案、掩盖真实根因——code-review item 4bee533d3be5）。run_id/spec
      已在 msg 文本内，忽略 extra 不丢信息；
    - ``%s: %s`` 折回单参格式化：tag 与 msg 均作为 % 参数交由标准 logging
      渲染，两者含 %s 等字符时不产生格式化副作用。
    """

    def __init__(self, base):
        self._base = base

    def warning(self, tag, msg, *args):
        self._base.warning("%s: %s", tag, msg)

    def error(self, tag, msg, *args):
        self._base.error("%s: %s", tag, msg)
