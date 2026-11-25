"""update_routes.py — H18 更新面（add-auto-update 3.1）。

dashboard 更新状态 API 三路由（design D7）：读侧轮询 status.json、同步检查、
受理分离编排。引擎单源在 ``core/self_update.py``（检查）与
``core/self_update_apply.py``（应用编排分离进程）——本 mixin 只做 HTTP 面
适配，无第二份实现。

错误文案口径（对齐 settings_routes 既有纪律）：OSError 等内部细节不随响应
透出（可含服务器绝对路径），固定语境文案 + logger 留痕；check 的业务性失败
（远端查询双腿全败等）是**业务结果**而非 HTTP 错误——200 + error 字段回传，
与 _api_alerts「有意 200 契约」同型；apply 的 409 为并发受理冲突（带稳定
机器码 ``update-locked``，前端按 code 分支禁用按钮）。
"""

from __future__ import annotations

import logging

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.update_routes")


class H18UpdateRoutesMixin:
    """H18 self-update（add-auto-update 3.1，design D7 三路由）。"""

    def _api_update_status(self, q: dict) -> None:
        """GET /api/update/status：读框架级更新状态（缺文件 → never-checked 形态）。"""
        from core.self_update import STATUS_PATH, read_status

        st = read_status()
        if not st:
            # never-checked 形态：前端据此渲染「尚未检查」空态而非报错
            self._json({
                "checked": False,
                "status_path": str(STATUS_PATH.name),
                "framework": None,
                "plugins": None,
                "apply": None,
            })
            return
        self._json({"checked": True, **st})

    def _api_update_check_post(self, q: dict) -> None:
        """POST /api/update/check：同步单次检查并回写状态（复用引擎）。

        检查失败（网络/限流/双腿全败）是业务结果：200 + ok=false + 可读
        message（与状态文件 last_error 一致），前端据此刷新卡片失败态。
        """
        from core.self_update import run_check

        try:
            status = run_check("dashboard")
        except Exception:  # noqa: BLE001 — 引擎已知自吞，此处为防御性兜底
            logger.exception("update check crashed")
            self._error(500, "检查执行异常，请查看服务端日志")
            return
        if status.get("last_error"):
            self._json({"ok": False, "error": status["last_error"],
                        "status": status})
            return
        self._json({"ok": True, "status": status})

    def _api_update_apply_post(self, q: dict) -> None:
        """POST /api/update/apply：受理分离编排进程（进行中/锁占用 409）。"""
        from core.self_update_apply import spawn_apply

        try:
            result = spawn_apply(source="dashboard")
        except Exception:  # noqa: BLE001 — 受理面未知异常固定文案
            logger.exception("update apply spawn failed")
            self._error(500, "更新编排受理异常，请查看服务端日志")
            return
        if result.get("ok"):
            self._json({"ok": True, "pid": result.get("pid"),
                        "message": "更新编排已受理，进度见更新卡"})
            return
        if result.get("conflict"):
            # 稳定机器码（前端按 code 分支禁用按钮，不依赖文案子串）
            self._coded_error(409, result.get("error") or "更新编排已在进行中",
                              "update-locked")
            return
        # spawn 失败的 error 含异常原文（OSError 可含绝对路径），仅留痕不透出
        logger.error("update apply rejected: %s", result.get("error"))
        self._error(500, "更新编排受理失败，请查看服务端日志")
