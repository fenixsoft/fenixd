"""session_routes.py — H_SessionRoutesMixin（dashboard-live-session D3）。

项目级自由会话 REST 端点，沿用既有的 mixin + 表驱动路由模式。
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("fenixd.dashboard.session_routes")

# ── add-session-composer 1.2：files 端点模块常量（不新增受管配置键） ──────
SESSION_FILES_LIMIT = 5000           # 返回条数上限，超出截断
GIT_LS_FILES_TIMEOUT_SECONDS = 10    # git ls-files 子进程超时保护
# f6396e93c224：status 端点回传子进程 stderr 尾部行数上限（排障出口），
# 取环形缓冲 200 行的尾部，避免全量拖大响应。
SESSION_STDERR_TAIL_LIMIT = 50


class H_SessionRoutesMixin:
    """H_SessionRoutesMixin：会话 REST 端点。"""

    def _session_context(self, query, require_sm: bool = True):
        """统一「项目校验 + SessionManager 判空」样板。

        校验失败时已写好错误响应并返回 None；成功返回 (project, sm)。
        「无会话」分支语义各端点不同（JSON null / 404 / 幂等 ok），由端点
        自行处理；sm.get 带死会话清理副作用，故不在此统一取 session。

        require_sm=False（item 1c1dda2ca506）：只需项目路径、不消费 sm 的
        端点（files 补全）跳过 SessionManager 判空，sm 恒返回 None——
        无会话能力的部署形态（session_manager 未初始化）下，@ 文件补全
        不应被连带 500。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return None

        if not require_sm:
            return project, None

        from core.dashboard.session_manager import SessionManager
        sm: SessionManager = self.server.session_manager
        if sm is None:
            self._error(500, "session manager not initialized")
            return None

        return project, sm

    def _api_session_start(self, query):
        """POST /api/session/start?project=<name> → 创建（或复用存活）会话。

        这是唯一允许启动会话进程的端点。
        返回 {"session": {"id": sid, "started_at": ...}}
        """
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        try:
            session = sm.start(project["name"], project["path"])
        except Exception as exc:
            # 对外固定文案（code-review item a2fbd4f5d9dd）：{exc} 会把进程
            # 命令行/内部路径等细节透给 HTTP 客户端，与 base.py _handle_inner
            # 泛化文案策略同款——详情经 logger.exception 留服务端日志。
            logger.exception("会话启动失败（project=%s）", project["name"])
            self._error(500, "failed to start session")
            return

        self._json({
            "session": {
                "id": session.session_id,
                # code-review item 2e9b99afdf93：started_at 取会话创建时刻
                # （Session.started_at），非随活动漂移的 last_activity。
                "started_at": session.started_at,
            }
        })

    def _api_session_get(self, query):
        """GET /api/session?project=<name> → 会话状态 + 全量事件缓冲（只读）。

        无会话时返回 {"session": null, "events": [], "truncated": false}
        MUST NOT 借回读端点启动进程。
        """
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        session = sm.get(project["name"])
        if session is None:
            self._json({"session": None, "events": [], "truncated": False})
            return

        # code-review item 79d40459a39e：锁内快照——deque 迭代期间被读线程
        # 并发 append 会抛 RuntimeError(deque mutated during iteration)，快照
        # 与写端 append 共用 session.lock 互斥（写端四处 append 均已持锁）。
        # f6396e93c224：锁内同拍快照 stderr_tail 尾部——写端 _stderr_reader
        # append 已同锁互斥，防 deque mutated during iteration（同 79d40459a39e
        # 纪律）；随状态端点暴露子进程 stderr 排障出口（此前只写不读）。
        with session.lock:
            events = list(session.events)
            stderr_tail = list(session.stderr_tail)[-SESSION_STDERR_TAIL_LIMIT:]
        from core.dashboard.session_manager import SESSION_EVENT_BUFFER
        truncated = len(events) >= SESSION_EVENT_BUFFER
        self._json({
            "session": {
                "id": session.session_id,
                # code-review item 2e9b99afdf93：同 _api_session_start，取
                # Session.started_at（创建时刻），非 last_activity。
                "started_at": session.started_at,
            },
            "events": events,
            "truncated": truncated,
            "stderr_tail": stderr_tail,
        })

    def _api_session_send(self, query):
        """POST /api/session/send?project=<name> → body {"text": "..."} 发送用户文本。

        空/空白/非字符串 → 400；项目或会话缺失 → 404；会话态失败
        （SessionError 族：已退出/不存在）→ 400；意外异常 → 500；
        成功 → {"ok": true}
        """
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        session = sm.get(project["name"])
        if session is None:
            self._error(404, "session not found; POST /api/session/start first")
            return

        # 读 body 的 socket 层异常（断连/超时）不在此吞掉（code-review item
        # 50e309b27c09）：_read_json_body 对常规错误已自行写响应并返回 None，
        # 能逃逸的只剩 OSError，交由 _handle_inner 统一兜底（BrokenPipe 静默、
        # 其余 logger.exception + 未开始响应时补 500）优于静默无响应。
        body = self._read_json_body()
        if body is None:
            return  # _read_json_body 已写错误响应

        text = body.get("text")
        if not isinstance(text, str):
            # 类型防线（code-review item b82e10346495）：数字/布尔/dict/list
            # 等真值直接 400 参数错误，而非 .strip() 抛 AttributeError 被
            # _handle_inner 兜成 500。
            self._error(400, "text must be a string")
            return
        text = text.strip()
        if not text:
            self._error(400, "text is required and must not be blank")
            return

        # item 7033967e20db：send 的预期失败（会话不存在/进程已退出/空文本）
        # 均为 SessionError 族，属客户端可见的会话态/参数问题，维持 400；
        # 其余意外异常（SessionManager 内部状态故障等）按服务端内部错误对待，
        # 同 _api_session_start 返回 500 并 logger.exception 留完整堆栈，
        # 便于监控区分「会话态问题」与「服务端故障」。
        from core.dashboard.session_manager import SessionError

        try:
            sm.send(session.session_id, text)
        except SessionError as exc:
            # 对外固定文案（code-review item a2fbd4f5d9dd，同 _api_session_stop
            # 留痕写法）：不把 {exc} 透给 HTTP 客户端，详情留服务端日志。
            logger.warning(
                "会话发送失败（session=%s）: %s: %s",
                session.session_id,
                type(exc).__name__,
                exc,
            )
            self._error(400, "send failed")
            return
        except Exception:
            logger.exception("会话发送失败（session=%s）", session.session_id)
            self._error(500, "send failed")
            return

        self._json({"ok": True})

    def _api_session_stop(self, query):
        """POST /api/session/stop?project=<name> → 终止会话（幂等）。

        无会话时亦 200。
        """
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        session = sm.get(project["name"])
        if session is None:
            self._json({"ok": True})
            return

        try:
            sm.stop(session.session_id, "user")
        except Exception as e:
            # 失败留痕（code-review item 0b15e1177b43）：忽略优先语义下不改变
            # 幂等返回契约，但会话可能实际未终止，须可追查——静默吞掉会让
            # 前端 ok:true 掩盖真实故障。
            logger.warning(
                "会话终止失败（session=%s）: %s: %s",
                session.session_id,
                type(e).__name__,
                e,
            )

        self._json({"ok": True})

    # ── add-session-composer 1.2/1.3：补全数据源只读端点 ─────────────────

    def _list_project_files(self, project_path) -> list[str]:
        """D6：以注册路径为 cwd 跑 git ls-files 子进程，返回相对路径列表。

        一次拿 tracked + 未忽略 untracked（--exclude-standard 遵循 .gitignore）。
        非 git 仓库（returncode!=0）/子进程超时/git 不可执行（OSError）→ 空数组
        （200 语义，不 500，前端补全降级为无候选）。

        截断契约（code-review item 448e7c6898a6）：超上限 SESSION_FILES_LIMIT
        （5000）时静默截断——响应只是普通数组，不附 truncated 标记（与
        /api/session 的 events 端点显式回传 truncated 布尔不同）；补全消费方
        须按「候选可能不全」容忍，大仓库尾部文件进不了候选且无提示。
        """
        try:
            completed = subprocess.run(
                # -z：以 \0 结尾且不做路径引用（core.quotePath），非 ASCII
                # 文件名（如中文）不会被八进制转义成 "\344\270\255..." 形态，
                # 候选与磁盘真实文件名一致（code-review item dc821f2f58b6）
                ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                cwd=str(project_path),
                capture_output=True,
                text=True,
                # 显式 UTF-8：text=True 缺省按 locale 解码，非 UTF-8 locale
                # 下读非 ASCII 文件名抛 UnicodeDecodeError（ValueError 子类，
                # 逃逸下方 except 致 500，对齐 regression_routes 同款惯例）
                encoding="utf-8",
                errors="replace",
                timeout=GIT_LS_FILES_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "git ls-files 超时（cwd=%s），返回空列表", project_path
            )
            return []
        except OSError as exc:
            logger.warning(
                "git ls-files 无法执行（cwd=%s）: %s: %s",
                project_path,
                type(exc).__name__,
                exc,
            )
            return []
        if completed.returncode != 0:
            # 非 git 仓库（exit 128 "not a git repository"）等：200 + 空数组
            return []
        return [
            # -z 输出按 \0 切分（含换行文件名不再歧义），末尾空串过滤
            ln for ln in completed.stdout.split("\0") if ln
        ][:SESSION_FILES_LIMIT]

    def _api_session_files(self, query):
        """GET /api/session/files?project=<name> → 项目文件相对路径数组（只读）。

        供 @ 提及补全。project 校验复用 _session_context（缺参/未注册 404，
        与既有 _session_context 样板对未注册项目的口径一致）。本端点只消费
        项目路径、不消费 sm：require_sm=False 跳过 SessionManager 判空
        （item 1c1dda2ca506）——文件补全不依赖会话能力，session_manager
        未初始化的部署形态下不应连带 500。

        截断契约（code-review item 448e7c6898a6）：上限 SESSION_FILES_LIMIT
        （5000），超出静默截断，响应体不附 truncated 标记（响应保持普通
        数组形状；_json 助手不支持自定义响应头）。
        """
        context = self._session_context(query, require_sm=False)
        if context is None:
            return
        project, _sm = context
        self._json(self._list_project_files(project["path"]))

    def _api_session_commands(self, query):
        """GET /api/session/commands?project=<name> → init 缓存命令/skill（只读）。

        D7：数据源是 SessionManager 从会话 stdout init 事件缓存的数组，
        MUST NOT 自扫 skills 目录；无在飞会话或 init 未到返回两个空数组（200）。
        """
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        session = sm.get(project["name"])
        if session is None:
            self._json({"slash_commands": [], "skills": []})
            return

        self._json({
            "slash_commands": list(session.slash_commands),
            "skills": list(session.skills),
        })

    def _api_session_watch(self, query, watch):
        """POST/DELETE /api/session/watch?project=<name>&cid=<cid>。

        hub.watch(cid, sid) 或 hub.unwatch(cid, sid)。"""
        context = self._session_context(query)
        if context is None:
            return
        project, sm = context

        cid = query.get("cid", [None])[0]
        if not cid:
            self._error(400, "missing cid parameter")
            return

        session = sm.get(project["name"])
        if session is None:
            if watch:
                self._error(404, "session not found")
                return
            # unwatch 对死会话/无会话幂等成功（code-review item c41a3389171f）：
            # sm.get 带死会话清理副作用，Session 已从映射移除、订阅键
            # session_id 无从恢复，hub.discard 无从执行；该订阅随会话死亡
            # 已无意义（不再有定向事件），直接返回 ok——与 _api_run_watch
            # 的 unwatch 方向对齐（仅校验 project/cid，无运行级存在性
            # 校验），也避免前端关闭弹窗对死会话发 DELETE 收 404 打
            # console.error 污染 no_console_error 断言。残留的 watched_runs
            # 条目由连接断开时 hub.unregister 整连接清除兜底。
            self._json({"ok": True})
            return

        if watch:
            self.server.sse_hub.watch(cid, session.session_id)
        else:
            self.server.sse_hub.unwatch(cid, session.session_id)

        self._json({"ok": True})
