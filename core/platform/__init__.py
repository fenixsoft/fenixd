"""core.platform — 平台抽象层包（sys.platform 全库单点分发处）。

业务代码统一 ``from core.platform import api as pal`` 后经 pal 调用平台
能力；``sys.platform`` 判断在 core/ 全库仅本文件一处（静态守卫
tests/test_platform_guard.py 断言平台判断面零回潮，本包为唯一豁免）。

分发语义：win32 → ``core.platform.win32``（SPEC-2 占位后端）；其余平台
（linux 及一切非 Windows 形态）→ ``core.platform.linux``（既有行为逐字
平移的缺省后端）。选出的后端实现注入 ``core.platform.api`` 契约模块命名
空间——api 既是六组接口契约（Protocol + 异常）也是业务门面。
"""

import sys

# 先导入契约模块（异常类型 + Protocol 契约面），再按平台选后端——顺序保证
# linux/win32 内 `from core.platform.api import ...` 命中已初始化的子模块
from core.platform import api as _api

if sys.platform == "win32":
    from core.platform import win32 as _backend
else:
    from core.platform import linux as _backend

# 后端实现注入契约模块命名空间（api = 契约 + 门面；业务侧 pal.xxx 直达实现）
for _name in getattr(_backend, "__all__", ()):
    setattr(_api, _name, getattr(_backend, _name))

api = _api

__all__ = ["api"]
