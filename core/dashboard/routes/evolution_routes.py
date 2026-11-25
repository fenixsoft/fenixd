"""evolution_routes.py — H7 evolution suggestions（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D3 patch 缝隙：`FRAMEWORK_ROOT` 常量仍定义在 `core.dashboard.server`
命名空间（测试 `monkeypatch.setattr(server_mod, "FRAMEWORK_ROOT", ...)`
patch 该命名空间属性）——本模块调用点 MUST 经 `core.dashboard.server`
命名空间**延迟解析**（不得顶部 import 绑定常量），否则重绑不生效。
"""

from __future__ import annotations

import logging
import threading
import time

from core.dashboard import data as dashboard_data

logger = logging.getLogger("fenixd.dashboard.routes.evolution_routes")

# item 0fd61150e50b：accept/reject/delete 三端点共用守卫骨架的动作级哨兵——
# 动作闭包已自行写响应（accept 的 start_after 非法 400）时返回它，助手据此收工。
# 不用 None 表达「已响应」：动作结果恒为 dict，返回 None 的路径须继续走助手内
# 的 result 判定，与去重前各端点的行为逐点一致。
_EVOLUTION_ACTION_RESPONDED = object()

# 进程内 accept 异步任务注册表（2026-11-16 批量同意超时事故引入）：item_id →
# {phase: 'running'|'done', started_at, finished_at, result}。单条 accept 含
# copytree + git 提交 + STATE 注册，慢时 >30s——客户端（经 frp 隧道）30s 超时
# 或 502 后真实结局不可知。异步化后 POST 立即返回 {queued}，前端轮询
# accept-status 到终态，每次 HTTP 交互都短，且必然拿到真实结局。仅本进程
# 内存活（单进程 ThreadingHTTPServer，无跨进程共享诉求）；done 条目超 TTL
# 在下次入队时机会性清理，running 条目超 _ACCEPT_JOB_RUNNING_TIMEOUT_SEC
# 机会性降级为 done + 超时失败（防 flock 挂死态永久 already_running）。
# 防重入：同条目 running 期间再入队返回
# already_running（不叠加第二个 worker）。
_ACCEPT_JOBS: dict = {}
_ACCEPT_JOBS_LOCK = threading.Lock()
_ACCEPT_JOBS_TTL_SEC = 3600.0
# code-review item d2d08f4308a3：running 条目超时兜底阈值。正常单条 accept
# 慢时 >30s（copytree + git 提交 + STATE 注册，git 子命令各带 30s timeout），
# 这里取 10 分钟保守值——远超正常完成时长，只兜住 accept_item 内 items.jsonl
# 写路径 flock 自阻塞（无超时，core/evolution.py _with_lock）被持锁方长期
# 不释放导致的无限期挂死。
_ACCEPT_JOB_RUNNING_TIMEOUT_SEC = 600.0


def _demote_stale_running_accept_jobs_locked() -> None:
    """running accept 条目的超时兜底（code-review item d2d08f4308a3）。

    _ACCEPT_JOBS 的 TTL 机会性清理只覆盖 done 条目，running 条目此前没有
    任何超时兜底：_run_accept_job 仅在 accept_item 返回/抛异常时置终态，
    而 items.jsonl 写路径的 flock 自阻塞无超时——持锁方长期不释放会让后台
    线程无限期挂死，同 item_id 恒 already_running、accept-status 恒 running，
    仅进程重启可解。这里把超龄 running 条目降级为 done + 显式超时失败，
    轮询方拿到终态可重试；仍在跑的线程最终完成时只认 phase==running——
    未重入队场景降级自然失效（真实结局被丢弃，可重试），已重入队场景其
    真实结局允许覆盖新条目（同为该条目 accept_item 的真实结局，幂等）。

    调用方 MUST 已持 _ACCEPT_JOBS_LOCK；本函数只降级不删除（删除仍走
    done 条目的 TTL 机会性清理）。
    """
    now = time.time()
    for key in [
        key
        for key, job in _ACCEPT_JOBS.items()
        if job.get("phase") == "running"
        and now - (job.get("started_at") or now) > _ACCEPT_JOB_RUNNING_TIMEOUT_SEC
    ]:
        stale = _ACCEPT_JOBS[key]
        stale["phase"] = "done"
        stale["finished_at"] = now
        stale["result"] = {
            "ok": False,
            "status": None,
            "spec_name": None,
            "error": "后台接受任务超时（可能被文件锁长期阻塞），请重试",
        }


class H7EvolutionRoutesMixin:
    """H7 evolution suggestions（design D1 表 C H7）。"""

    @staticmethod
    def _evolution_state_machine():
        """框架根 StateMachine（accept_item 注册用；惰性构造，无缓存需求）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.state_machine import StateMachine, project_state_logger

        # 跨进程写入者 MUST 注入真实 logger（fix-state-atomicity-and-selfheal-restart
        # 1.3/D2）：accept_item 经 add_spec 写 STATE，无 logger 构造会静默。
        return StateMachine(
            _server_mod.FRAMEWORK_ROOT / ".fenix" / "STATE.md",
            project_state_logger(_server_mod.FRAMEWORK_ROOT),
        )


    def _evolution_item_action(self, action_fn, *, error_message, log_message,
                               error_key=None, item_missing_key=None):
        """accept/reject/delete 三 POST 端点共用的守卫骨架（item 0fd61150e50b 去重）。

        手法对齐 hosting_guard._guard_hosting_state 先例——守卫规则变化（错误码
        调整、新增参数校验、异常兜底）单点同修，调用方只留动作与文案：
        读 JSON body（``_read_json_body`` 失败已自行写 400/413 并返回 None）→
        item_id 类型校验 400 → try/except 泛化 500 → status 为 None 且 error
        时 404 → 200 + result JSON。

        ``action_fn(item_id, body)`` 承载各端点动作，动作所需额外参数（框架根、
        状态机、start_after）经闭包捕获；动作已自行写响应时返回
        ``_EVOLUTION_ACTION_RESPONDED`` 哨兵。``error_message``/``log_message``
        为 500 泛化文案与异常日志文案——三端点仅「接受/拒绝/删除」一词之差。

        不外泄裸异常文本（code-review item 1f7996c07aa7）：裸 ``{e}`` 会把内部
        路径/存储细节透给 HTTP 客户端，与 code_review_routes 已确立的泛化文案
        策略同款——细节降级经服务端日志留痕。
        """
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, "缺少 item_id 参数", key=item_missing_key)
            return
        try:
            result = action_fn(item_id, body)
        except Exception:  # noqa: BLE001 —— 端点不因内部异常 500 崩溃
            logger.exception(log_message, item_id)
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(500, error_message, key=error_key)
            return
        if result is _EVOLUTION_ACTION_RESPONDED:
            return
        if result.get("status") is None and result.get("error"):
            self._error(404, result["error"])
            return
        self._json(result)


    def _api_evolution_items(self, query):
        """GET /api/evolution/items?project=<可选> — 建议改进项摘要列表（倒序）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        project = (query.get("project") or [None])[0] or None
        self._json(
            {
                "items": dashboard_data.read_evolution_items(
                    _server_mod.FRAMEWORK_ROOT, project_filter=project
                ),
            }
        )


    def _api_evolution_analysis(self, query):
        """GET /api/evolution/analysis?item_id=<id> — 返回分析结论全文。

        缺参/未知 item_id → 400/404（MUST NOT 读取任何文件）。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        item_id = (query.get("item_id") or [None])[0]
        if not item_id:
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, "缺少 item_id 参数", key="error.evo_item_id_missing")
            return
        result = dashboard_data.read_evolution_analysis(_server_mod.FRAMEWORK_ROOT, item_id)
        if result.get("not_found"):
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(404, f"条目不存在: {item_id}", key="error.evo_item_not_found",
                        item_id=item_id)
            return
        self._json(result)


    def _api_evolution_draft(self, query):
        """GET /api/evolution/draft?item_id=<id>&doc=<proposal|design|tasks|spec>

        读取草稿文档返回 ``{found, content}``；doc 非法 → 400（MUST NOT 读取
        草稿目录之外的任何文件）；item_id 未知 → 404；草稿缺失 → 200 +
        found:false。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        item_id = (query.get("item_id") or [None])[0]
        doc = (query.get("doc") or [None])[0]
        if not item_id:
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, "缺少 item_id 参数", key="error.evo_item_id_missing")
            return
        if not doc:
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, "缺少 doc 参数（proposal|design|tasks|spec）",
                        key="error.evo_doc_missing")
            return
        result = dashboard_data.read_evolution_draft(_server_mod.FRAMEWORK_ROOT, item_id, doc)
        if result.get("invalid_doc"):
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, f"非法 doc 参数（应为 proposal|design|tasks|spec）: {doc}",
                        key="error.evo_doc_invalid", doc=doc)
            return
        if result.get("not_found"):
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(404, f"条目不存在: {item_id}", key="error.evo_item_not_found",
                        item_id=item_id)
            return
        self._json(result)


    def _api_evolution_accept(self):
        """POST /api/evolution/accept — body {item_id, start_after?, async?, retry?}

        同步模式（缺省，``async`` 缺失/假值——向后兼容，测试与既有调用方
        零改动）：执行接受路径，成功返回 200 + {ok, status, spec_name}；
        缺参 400；未知条目 404。状态不允许/提交失败也返回 200 + 错误体
        （成败由 ok 字段表达，前端据此刷新回真实状态）。

        异步模式（``async: true``，2026-11-16 批量同意超时事故引入）：立即
        返回 200 + {queued: true, item_id}，接受动作转入后台 daemon 线程，
        前端经 GET /api/evolution/accept-status 轮询到终态。单条 accept 慢时
        >30s（git 提交 + STATE 注册），同步模式下客户端 30s 超时或 frp 隧道
        502 后真实结局不可知——前端会把「响应丢了」误报成失败，用户重试又
        撞幂等分支，界面与台账真相脱节。异步模式消灭长请求，且客户端必然
        拿到真实结局。

        ``retry: true``（与 async 正交）：draft_failed 条目原地重入（锁内清
        失败原因置回 pending 后走正常接受链，accept_item
        ``allow_draft_failed_retry``）——失败明细「重试」按钮专用；缺省
        False 保持 draft_failed 幂等返回。

        人工「同意」= accept_item(decided_by="manual")（自动接受是 daemon
        检查点经 3.7 的另一条路径，二者共用同一实现，design D6）。

        ``start_after``（可选）取值三态：
        - null/缺失 → 立项后立即执行（原行为）
        - UTC ISO8601 字符串 → 定时拾取（原语义）
        - ``"manual"``（add-spec-manual-activation D5）→ 立项即为待激活
          （永不到期，须人工激活后方可被调度器拾取）
        本次执行时刻由调用方（设置页弹窗，按 ``self_evolution.spec_run_at`` 配置
        预填并可临时改）决定，端点不做配置解释；格式非法 400。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.evolution import accept_item

        def _run_accept_job(item_id, start_after, retry, sm):
            # 后台线程：只跑 accept_item（写台账/git/STATE），不触 HTTP 响应
            # 通道；异常兜底为统一错误体（与同步 500 泛化文案同款，细节经
            # 服务端日志留痕）。
            try:
                result = accept_item(
                    item_id,
                    _server_mod.FRAMEWORK_ROOT,
                    sm,
                    decided_by="manual",
                    start_after=start_after,
                    allow_draft_failed_retry=retry,
                )
            except Exception:  # noqa: BLE001 —— 后台线程异常落为终态结果
                logger.exception("异步接受建议项异常（item_id=%s）", item_id)
                result = {
                    "ok": False,
                    "status": None,
                    "spec_name": None,
                    "error": "接受失败（详见服务端日志）",
                }
            with _ACCEPT_JOBS_LOCK:
                job = _ACCEPT_JOBS.get(item_id)
                if job is not None and job.get("phase") == "running":
                    job["phase"] = "done"
                    job["finished_at"] = time.time()
                    job["result"] = result

        def _enqueue_accept(item_id, start_after, retry, sm):
            with _ACCEPT_JOBS_LOCK:
                # 先机会性降级超时 running 条目（item d2d08f4308a3）：否则
                # 挂死条目会让下面的防重入检查恒 already_running，重试永远
                # 进不来
                _demote_stale_running_accept_jobs_locked()
                existing = _ACCEPT_JOBS.get(item_id)
                if existing is not None and existing.get("phase") == "running":
                    # 同条目已有在跑任务：不叠加第二个 worker（items.jsonl
                    # flock CAS 本会串行化，但提前拦截省一次白等）
                    return {"queued": True, "item_id": item_id, "already_running": True}
                now = time.time()
                # 机会性清理 TTL 过期的 done 条目（量级=本轮已接受条目数）
                for k in [
                    k
                    for k, v in _ACCEPT_JOBS.items()
                    if v.get("phase") == "done"
                    and now - (v.get("finished_at") or now) > _ACCEPT_JOBS_TTL_SEC
                ]:
                    del _ACCEPT_JOBS[k]
                _ACCEPT_JOBS[item_id] = {
                    "phase": "running",
                    "started_at": now,
                    "finished_at": None,
                    "result": None,
                }
            try:
                threading.Thread(
                    target=_run_accept_job,
                    args=(item_id, start_after, retry, sm),
                    name=f"evolution-accept-{item_id[:8]}",
                    daemon=True,
                ).start()
            except Exception as exc:  # noqa: BLE001 — 系统线程资源耗尽等 RuntimeError
                # code-review item 1e8b81200af6/1da036b54859：start() 抛异常若放
                # 任逃逸，上面已注册的 running 条目无人回滚——同 item_id 之后恒
                # already_running、accept-status 恒 running 且永无终态，直到进程
                # 重启。口径对齐 architecture_routes.refresh（item 1295fb028cb4）
                # 的「终态落盘再释放」范式：先在锁内置 done 终态（带 error 结果，
                # 轮询方可拿到显式失败），异常细节降级服务端日志，响应体只留
                # 固定文案。
                logger.warning(
                    f"异步接受任务线程启动失败（item_id={item_id}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )
                with _ACCEPT_JOBS_LOCK:
                    job = _ACCEPT_JOBS.get(item_id)
                    if job is not None and job.get("phase") == "running":
                        job["phase"] = "done"
                        job["finished_at"] = time.time()
                        job["result"] = {
                            "ok": False,
                            "status": None,
                            "spec_name": None,
                            "error": "后台接受任务线程启动失败，请重试",
                        }
                # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
                self._error(500, "后台接受任务线程启动失败，请重试",
                            key="error.evo_accept_thread_failed")
                return _EVOLUTION_ACTION_RESPONDED
            return {"queued": True, "item_id": item_id, "already_running": False}

        def _accept(item_id, body):
            raw_start_after = body.get("start_after")
            start_after = None
            if raw_start_after not in (None, ""):
                if isinstance(raw_start_after, str) and raw_start_after.strip().lower() == "manual":
                    # D5 哨兵分支：立项即为待激活（经 accept_item 原样落入 entry，
                    # parse_utc 不参与——哨兵不是时间）
                    start_after = "manual"
                else:
                    from core.state_machine import parse_utc  # 时间解析单点（design D6）

                    if not isinstance(raw_start_after, str) or parse_utc(raw_start_after) is None:
                        # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
                        self._error(400, f"start_after 非法（应为 UTC ISO8601 / manual）: {raw_start_after!r}",
                                    key="error.evo_start_after_invalid",
                                    value=repr(raw_start_after))
                        return _EVOLUTION_ACTION_RESPONDED
                    start_after = raw_start_after
            retry = bool(body.get("retry"))
            if body.get("async"):
                # [fenix-ignore:abbfd5e74b27] 预检与入队间的 check-then-act 竞态属良性（后台终态错误可经 accept-status 显式反馈），维持现状仅作记录
                # 轻量存在性预检（读台账，无副作用）：未知条目直接 404，
                # 不留一个注定失败的 running 任务在注册表里
                from core.evolution import read_items

                if item_id not in read_items(_server_mod.FRAMEWORK_ROOT):
                    return {"ok": False, "status": None, "spec_name": None, "error": f"条目不存在: {item_id}"}
                sm = self._evolution_state_machine()
                return _enqueue_accept(item_id, start_after, retry, sm)
            return accept_item(
                item_id,
                _server_mod.FRAMEWORK_ROOT,
                self._evolution_state_machine(),
                decided_by="manual",
                start_after=start_after,
                allow_draft_failed_retry=retry,
            )

        self._evolution_item_action(
            _accept,
            error_message="接受失败（详见服务端日志）",
            log_message="接受建议项异常（item_id=%s）",
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            error_key="error.evo_accept_failed",
            item_missing_key="error.evo_item_id_missing",
        )


    def _api_evolution_accept_status(self, query):
        """GET /api/evolution/accept-status?item_id=<id> — 异步接受任务状态轮询。

        返回 {phase: running|done, started_at, finished_at, result}；result
        为 accept_item 的 {ok, status, spec_name, error}（running 期为 null）。
        无任务记录（未入队/进程重启后）→ 404——前端据此可安全回退同步刷新。
        """
        item_id = (query.get("item_id") or [None])[0]
        if not item_id:
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            self._error(400, "缺少 item_id 参数", key="error.evo_item_id_missing")
            return
        with _ACCEPT_JOBS_LOCK:
            # 机会性降级超时 running 条目（item d2d08f4308a3）：让轮询方在
            # 后台线程挂死时也能拿到显式终态失败，而非恒 running
            _demote_stale_running_accept_jobs_locked()
            job = _ACCEPT_JOBS.get(item_id)
            if job is None:
                # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
                self._error(404, f"该条目没有进行中或已完成的接受任务: {item_id}",
                            key="error.evo_no_active_accept", item_id=item_id)
                return
            snapshot = {
                "phase": job.get("phase"),
                "started_at": job.get("started_at"),
                "finished_at": job.get("finished_at"),
                "result": dict(job.get("result") or {}),
            }
        self._json(snapshot)


    def _api_evolution_reject(self):
        """POST /api/evolution/reject — body {item_id} → 执行拒绝路径。

        成功返回 200 + {ok, status}；缺参 400；未知条目 404。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.evolution import reject_item

        self._evolution_item_action(
            lambda item_id, _body: reject_item(item_id, _server_mod.FRAMEWORK_ROOT),
            error_message="拒绝失败（详见服务端日志）",
            log_message="拒绝建议项异常（item_id=%s）",
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            error_key="error.evo_reject_failed",
            item_missing_key="error.evo_item_id_missing",
        )


    def _api_evolution_delete(self):
        """POST /api/evolution/delete — body {item_id} → 删除该条目（硬删）。

        成功返回 200 + {ok, status}；缺参 400；未知条目 404。
        硬删语义：记录移出 items.jsonl 且不写墓碑，todo.md 中同名记录会在下一轮
        分析 run 重新入库（前端确认弹窗已向用户明示）。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.evolution import delete_item

        self._evolution_item_action(
            lambda item_id, _body: delete_item(item_id, _server_mod.FRAMEWORK_ROOT),
            error_message="删除失败（详见服务端日志）",
            log_message="删除建议项异常（item_id=%s）",
            # add-framework-i18n-zh-en 4.4：文案经消息目录，按 Accept-Language 展开
            error_key="error.evo_delete_failed",
            item_missing_key="error.evo_item_id_missing",
        )


    def _api_evolution_clear_todo(self):
        """POST /api/evolution/clear-todo — 清空**所有项目**的 .fenix/todo.md。

        全局动作，不接受 project 参数（逐个清理所有 discover 到且存在的项目）。
        与 alerts/clear 同口径跳过 fixture 项目（code-review item cb7a35748089 /
        item 402b8696e70a）：夹具的 todo.md 属夹具状态，只应经 --reset 复位，
        全局清理 MUST NOT 静默改写。经 self.server.projects() 遍历（TTL 缓存
        与发现异常兜底），不直连 registry.discover()。
        清空范围仅限 todo.md：MUST NOT 触碰 items.jsonl / 草稿 / 水位，故下方
        条目列表不受影响。不代提交 git（各项目 todo.md 的提交由每日自省负责）。

        逐项目结果分三类返回，单个项目失败 MUST NOT 中断其余：
        ``{ok, cleared: [项目名], skipped: [{project, reason}], failed: [{project, error}]}``。
        ``ok`` 表示「没有任何项目失败」（全部跳过亦为 True）。
        """
        from core.evolution import clear_todo

        cleared: list = []
        skipped: list = []
        failed: list = []
        for proj in self.server.projects() or []:
            if proj.get("fixture"):
                continue  # fixture-project-governance：夹具 todo 只经 --reset 复位
            if not proj.get("exists"):
                continue
            name = proj.get("name") or proj.get("path") or "?"
            path = proj.get("path")
            if not path:
                skipped.append({"project": name, "reason": "项目路径缺失"})
                continue
            try:
                result = clear_todo(path)
            except Exception:  # noqa: BLE001 —— 单项目异常计入 failed，不中断其余项目
                # 不外泄裸异常文本（code-review item 1f7996c07aa7），同 accept 端点：
                # 泛化文案 + 服务端 logger.exception 留痕（逐条细节见日志）。
                logger.exception("清空 todo.md 异常（project=%s）", name)
                failed.append({"project": name, "error": "清空失败（详见服务端日志）"})
                continue
            if result.get("error"):
                failed.append({"project": name, "error": result["error"]})
            elif not result.get("existed"):
                skipped.append({"project": name, "reason": "无 todo.md"})
            else:
                cleared.append(name)
        self._json(
            {
                "ok": not failed,
                "cleared": cleared,
                "skipped": skipped,
                "failed": failed,
            }
        )
