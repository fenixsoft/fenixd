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
        import json as _json

        from core.self_update import PROGRESS_PATH, STATUS_PATH, read_status

        st = read_status()
        if not st:
            # never-checked 形态：前端据此渲染「尚未检查」空态而非报错
            self._json({
                "checked": False,
                "status_path": str(STATUS_PATH.name),
                "framework": None,
                "plugins": None,
                "apply": None,
                "progress": None,
            })
            return
        self._json({"checked": True, **st,
                    "apply_stale": self._apply_running_stale(st.get("apply") or {}),
                    "progress": self._read_download_progress(
                        st.get("apply") or {}, PROGRESS_PATH, _json)})

    @staticmethod
    def _apply_running_stale(apply_state: dict) -> bool:
        """running 且最后活动超龄（编排进程疑似被硬杀未收尾）→ UI 提示可重触发。"""
        if apply_state.get("phase") != "running":
            return False
        from core.self_update_apply import apply_running_orphaned

        return apply_running_orphaned(apply_state)

    @staticmethod
    def _read_download_progress(apply_state: dict, progress_path, json_mod):
        """apply 进行中才透出下载进度（progress.json；异常面一律降级 None）。"""
        if apply_state.get("phase") not in ("queued", "running"):
            return None
        try:
            raw = json_mod.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or not raw.get("asset"):
            return None
        return raw

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

    def _api_update_mirror_get(self, q: dict) -> None:
        """GET /api/update/mirror：当前下载源 + 预设清单。

        读侧宽松（config 损坏回缺省镜像通道不阻断页面）；mirror 为空串 =
        显式官方直连，键缺失由 load_update_config 解析为缺省镜像（ghfast）。
        返回值过 ``normalize_mirror`` 归一（剥尾斜杠等），保证与预设 URL 逐字
        相等、前端 Radio 能命中预设——手工编辑过的 config（如带尾斜杠）否则
        会误显示成「自定义」；无法归一的垃圾值原样返回（如实显示为自定义）。
        """
        from core.self_update import (
            UPDATE_MIRROR_DEFAULT,
            UPDATE_MIRROR_PRESETS,
            load_update_config,
            normalize_mirror,
        )

        try:
            cfg = load_update_config()
            raw = cfg.mirror or ""
        except Exception:  # noqa: BLE001 — 配置损坏时回缺省镜像，logger 留痕
            logger.exception("update mirror config read failed")
            raw = UPDATE_MIRROR_DEFAULT
        mirror = normalize_mirror(raw)
        if mirror is None:
            mirror = raw
        self._json({"mirror": mirror, "presets": UPDATE_MIRROR_PRESETS})

    def _api_update_mirror_post(self, q: dict) -> None:
        """POST /api/update/mirror：切换下载源（写用户级 config.yaml）。

        校验单源 ``core.self_update.normalize_mirror``（非法值 400 +
        ``invalid-mirror`` 稳定机器码）；落盘单源 ``config_admin.
        write_update_mirror``（与设置页保存同锁，防并发重写互覆盖）。
        保存即对下一次「一键更新」生效（编排进程受理时读配置），无需重启。
        """
        from core.dashboard.data.config_admin import write_update_mirror
        from core.self_update import normalize_mirror

        body = self._read_json_body()
        if body is None:
            return  # 4xx 已写（非 JSON/超限），按 _read_json_body 契约直接返回
        mirror = body.get("mirror")
        normalized = normalize_mirror(
            mirror if isinstance(mirror, str) else None
        )
        if normalized is None:
            self._coded_error(
                400, "mirror 值非法：仅接受 https 主机前缀（可带 /https://github.com 尾巴）",
                "invalid-mirror")
            return
        try:
            result = write_update_mirror(normalized)
        except OSError:
            logger.exception("update mirror persist failed")
            self._error(500, "下载源配置写入失败，请查看服务端日志")
            return
        if not result.get("ok"):
            # error 可能含 yaml 异常原文（可含路径），留痕不透出；配置文件
            # 状态问题属用户可修复（手工修正 config.yaml），400 + 稳定机器码
            logger.error("update mirror persist rejected: %s", result.get("error"))
            self._coded_error(400, "用户级 config.yaml 状态异常，请先手工修正后再切换下载源",
                              "config-invalid")
            return
        self._json({"ok": True, "mirror": normalized})
