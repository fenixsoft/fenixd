"""code_review_routes.py — code-review（周期性代码审查）routes（add-code-review-agent-and-quality-tab）。

承载 5 个端点：
- GET  /api/code-review/items      （query project、可选 status）→ 台账列表
- GET  /api/code-review/progress   （query project）→ 运行进度
- POST /api/code-review/run        （body {project, scope}）→ 写手动触发信号
- POST /api/code-review/fix-run    （query project）→ 写手动「立即自动修复」信号（add-code-fix-manual-trigger）
- GET  /api/code-review/fix-run-result（query project）→ 只读手动触发判定结果（add-code-fix-manual-trigger）
- POST /api/code-review/generate-spec（body {project, item_ids, start_after?}）→ 生成修复 SPEC
- POST /api/code-review/items/status（body {project, item_id, status}）→ 人工状态流转

端点 handler 走既有 mixin 形态（self._json / self._error / _read_json_body）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.dashboard import data as dashboard_data

# 手动触发信号文件（daemon 主循环经 fenixd._check_code_review_requests 消费）。
# 与 admin_invoke_request / cancel_run_request / approve_push_request 同属
# 「dashboard 原子写 → daemon 主循环消费」文件信号族。
CODE_REVIEW_REQUEST = ".fenix/code_review_request.json"

# 手动「立即自动修复」信号与判定结果文件（add-code-fix-manual-trigger）。
# 信号由 daemon 主循环经 fenixd._check_code_fix_requests 消费；结果文件由
# 消费端原子写回，GET fix-run-result 只读透传。
CODE_FIX_REQUEST = ".fenix/code_fix_request.json"
CODE_FIX_REQUEST_RESULT = ".fenix/code_fix_request_result.json"


class H11CodeReviewRoutesMixin:
    """H11 code-review（design D1 表 C H11）。"""

    def _coded_error(self, status: int, msg: str, code: str) -> None:
        """带稳定机器可读 ``code`` 的错误响应。

        code-review item fbdb437a22a0：前端控制流按业务错误码分支，不依赖
        中文消息子串（措辞改动不再静默落入通用错误分支）。先例：H12
        regression mixin 同名 helper（item 934af264345f），错误码经
        ApiError.code 承载。
        """
        self._json({"error": msg, "code": code}, status)

    def _api_code_review_items(self, query):
        """GET /api/code-review/items?project=<name>[&status=open,in_spec]

        返回 ``{items: [...]}``（按 severity 排序，默认仅 open）。缺项目 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        statuses = None
        raw = query.get("status", [None])[0]
        if raw:
            statuses = [s.strip() for s in raw.split(",") if s.strip()]
        items = dashboard_data.read_code_review_items(str(project["path"]), statuses=statuses)
        self._json({"items": items})

    def _api_code_review_progress(self, query):
        """GET /api/code-review/progress?project=<name>

        返回 ``{running, review_id, review_kind, total, done, current}``。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_code_review_progress(str(project["path"])))

    def _api_code_review_fix_progress(self, query):
        """GET /api/code-review/fix-progress?project=<name>（task 8.2）

        自动修复进度只读端点（无副作用）：返回
        ``{running, phase, total, done, current, batch_no, reason,
        activation_id}``。项目不存在 → 404；进度文件缺失 → 缺省态（MUST
        NOT 500，形态对齐 _api_code_review_progress）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_code_review_fix_progress(str(project["path"])))

    def _api_code_review_run(self, query):
        """POST /api/code-review/run — body {project, scope: "full"|"window"}

        写 ``.fenix/code_review_request.json`` 文件信号 → daemon 主循环消费
        （不直接同步跑审查）。

        - 项目不存在 → 404
        - 已有审查在跑（progress.running）→ 409「已有审查在进行中」
          （code=code_review_running）
        - 消费方守卫：daemon 未受 supervisor 托管（hosting_state ==
          "unmanaged"）→ 409 明确拒绝（对齐 request_spec_approve_push——
          信号无人消费会永久滞留并在 daemon 下次启动时被消费成一次用户并未
          请求的审查）；stopped → 400「daemon 未运行」。
        - 受理 → 200 + {ok, scope, requested_at}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        scope = body.get("scope") or "window"
        if scope not in ("full", "window"):
            self._error(400, f"非法 scope（应为 full 或 window）: {scope!r}")
            return
        proot = Path(project["path"])

        # 运行中守卫（基于产物终态判定，见 core.code_review.read_progress——
        # 已取消/已停机的 run 必须判 running=false，否则 409 恒真锁死后续触发）
        progress = dashboard_data.read_code_review_progress(str(proot))
        if progress.get("running"):
            self._coded_error(409, "已有审查在进行中", "code_review_running")
            return

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push）
        from core.fenix_session import hosting_state as _hosting_state

        try:
            state = _hosting_state(str(proot))
        except Exception as exc:
            # 判定异常按未运行兜底，宁拒勿假放行；降级可观测（item 0d1ba0c6efc0）
            state = "stopped"
            _log = getattr(self, "logger", None)
            if _log is not None:
                _log.warning(
                    "code_review_routes",
                    f"hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: {exc!r}",
                )
        if state == "unmanaged":
            self._error(
                409,
                "本项目 daemon 未受 supervisor 托管，审查信号不会被消费。"
                "经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
            )
            return
        if state != "managed":
            self._error(400, "daemon 未运行，请先启动 daemon")
            return

        # 原子创建信号文件（O_CREAT|O_EXCL 独占创建，code-review item d3c1d2ef4a88）：
        # ThreadingHTTPServer 最多 64 并发线程，旧实现的 `exists()` 检查与随后的
        # `os.replace` 非原子——两个并发 POST 可同时通过检查，后者的 replace 会
        # 静默覆盖前者的信号（或覆盖一条已存在未消费的请求），丢失一次用户触发。
        # 独占创建成功即胜出；FileExistsError → 409（已有未消费请求）。
        created = datetime.now(timezone.utc).isoformat()
        # 键名与消费者契约一致（fenixd._check_code_review_requests 读
        # requested_at；item 117af27b759a：写 created 使 daemon 恒记空时间戳）
        payload = {"scope": scope, "source": "dashboard", "requested_at": created}
        req_path = proot / CODE_REVIEW_REQUEST
        req_path.parent.mkdir(parents=True, exist_ok=True)

        # 先填内容、再原子挂到轮询路径（code-review item 502bc934c4c6）：旧实现
        # O_CREAT|O_EXCL 直接创建轮询路径、之后才 json.dump——daemon 1s 主循环
        # tick 落在创建与填充之间的空窗会读到空/半写文件并 unlink 之，用户触发
        # 静默丢失。改为三步：
        #   1. 写同目录唯一临时文件（同目录保证 link 原子性），完整 JSON + fsync；
        #   2. os.link(2) 原子挂到轮询路径——目标已存在抛 FileExistsError，
        #      保留 item d3c1d2ef4a88 的独占创建语义（并发第二 POST → 409）；
        #   3. 消费者要么看不到文件、要么看到完整 JSON，空窗不复存在。
        tmp_path = (
            req_path.parent / f".{req_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        )
        try:
            fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except OSError:
            self._error(500, "审查触发信号写入失败")
            return
        try:
            # fdopen 失败路径显式关 fd（code-review item 71d502440d3b，先例
            # regression_routes item 655c860e2e6e）：fdopen() 自身抛错时裸 fd
            # 未被包装也无人关闭（with 的 close 只在 fdopen 成功后才生效）——
            # 请求线程描述符泄漏。改为显式接管：f 为 None（fdopen 未成功）时
            # 兜底 os.close；成功后统一经 finally close（等价 with 语义）。
            f = None
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        except Exception:
            # 写中途失败：清掉临时文件（轮询路径尚未创建，无半写残留可误消费）
            try:
                os.unlink(str(tmp_path))
            except OSError:
                pass
            self._error(500, "审查触发信号写入失败")
            return
        try:
            os.link(str(tmp_path), str(req_path))
        except FileExistsError:
            self._coded_error(409, "已有未消费的审查触发请求（请稍后重试）",
                              "code_review_request_pending")
            return
        except OSError:
            self._error(500, "审查触发信号写入失败")
            return
        finally:
            # 链接成功/失败临时文件均无存在必要（成功后内容已由 link 名可见）
            try:
                os.unlink(str(tmp_path))
            except OSError:
                pass
        self._json({"ok": True, "scope": scope, "requested_at": created})

    def _api_code_review_fix_run(self, query):
        """POST /api/code-review/fix-run — query ?project=<name>（task 2.1）

        手动「立即自动修复」：写 ``.fenix/code_fix_request.json`` 文件信号 →
        daemon 主循环消费（``fenixd._check_code_fix_requests`` 以
        ``override_enabled=True`` 临时授权调 checkpoint——手动即临时授权，
        开关关闭也投递这一批）。

        - 项目不存在 → 404
        - 消费方守卫（hosting_state 判据，对齐 _api_code_review_run）：
          daemon 未受 supervisor 托管（unmanaged）→ 409 明确拒绝（信号无人
          消费会永久滞留并在 daemon 下次启动时被消费成一次用户并未请求的
          修复）；stopped → 400「daemon 未运行」。
        - 受理前预删旧结果文件：防止上一轮残留判定被前端误当本次反馈
          （与 request_created 回链双重防御）。
        - 受理 → 200 + {ok, requested_at}；O_CREAT|O_EXCL 独占创建，
          FileExistsError → 409（并发第二次 POST 或上一信号尚未被消费）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push）
        from core.fenix_session import hosting_state as _hosting_state

        try:
            state = _hosting_state(str(proot))
        except Exception as exc:
            # 判定异常按未运行兜底，宁拒勿假放行；降级可观测（item 0d1ba0c6efc0）
            state = "stopped"
            _log = getattr(self, "logger", None)
            if _log is not None:
                _log.warning(
                    "code_review_routes",
                    f"hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: {exc!r}",
                )
        if state == "unmanaged":
            self._error(
                409,
                "本项目 daemon 未受 supervisor 托管，修复信号不会被消费。"
                "经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
            )
            return
        if state != "managed":
            self._error(400, "daemon 未运行，请先启动 daemon")
            return

        # 预删旧结果文件（残留判定 MUST NOT 被前端当本次反馈；删除失败不阻塞受理）
        result_path = proot / CODE_FIX_REQUEST_RESULT
        try:
            result_path.unlink()
        except OSError:
            pass

        # 原子创建信号文件（O_CREAT|O_EXCL 独占创建，对齐 _api_code_review_run）
        created = datetime.now(timezone.utc).isoformat()
        payload = {"source": "dashboard", "created": created}
        req_path = proot / CODE_FIX_REQUEST
        req_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(req_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            self._coded_error(409, "已有未消费的修复触发请求（请稍后重试）",
                              "fix_run_request_pending")
            return
        except OSError:
            self._error(500, "修复触发信号写入失败")
            return
        try:
            # fdopen 失败路径显式关 fd（code-review item 71d502440d3b，同
            # _api_code_review_run 修法）：fdopen() 自身抛错时裸 fd 无人关闭。
            f = None
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        except Exception:
            # 写中途失败：清掉半写文件，避免残留被 daemon 误消费
            try:
                os.unlink(str(req_path))
            except OSError:
                pass
            self._error(500, "修复触发信号写入失败")
            return
        self._json({"ok": True, "requested_at": created})

    def _api_code_review_fix_run_result(self, query):
        """GET /api/code-review/fix-run-result?project=<name>（task 2.2）

        手动触发判定结果只读透传：返回 daemon 消费端写回的
        ``.fenix/code_fix_request_result.json`` 内容（``{request_created,
        triggered, reason, message, finished_at}``）。文件缺失/损坏 → 缺省态
        ``{}``（MUST NOT 500，形态对齐 _api_code_review_fix_progress）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_code_fix_request_result(str(project["path"])))

    def _api_code_review_generate_spec(self, query):
        """POST /api/code-review/generate-spec — body {project, item_ids: [...]}

        body 可选 ``start_after``（三态，与 `set_spec_start_after` 同源口径）：
        - 缺省 / null / 空串 → 立即执行
        - ``"manual"`` → 待激活（哨兵，永不到期）
        - ISO8601 → 定时拾取
        非法值 400（不落盘、条目状态不变）。

        调 ``core.code_review.generate_fix_spec`` 把选中问题机械合成修复 SPEC。

        返回 ``{ok, spec_name, skipped, error, start_after}``；成功把条目置 in_spec。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        item_ids = body.get("item_ids")
        if not isinstance(item_ids, list) or not all(isinstance(i, str) for i in item_ids):
            self._error(400, "item_ids 必须为字符串数组")
            return
        if not item_ids:
            self._error(400, "item_ids 不能为空")
            return
        from core.code_review import _normalize_start_after, generate_fix_spec

        start_after = body.get("start_after")
        ok_sa, normalized_sa, sa_err = _normalize_start_after(start_after)
        if not ok_sa:
            self._error(400, sa_err)
            return

        proot = Path(project["path"])
        try:
            result = generate_fix_spec(
                str(proot), self._code_review_state_machine(proot), item_ids, normalized_sa
            )
        except Exception as e:  # noqa: BLE001 —— 端点不因内部异常 500 崩溃
            # 不外泄裸异常文本（code-review item 5268c8ebc625）：generate_fix_spec
            # 会做文件写入/git commit/lint，失败属预期而非异常态；裸 `{e}` 会把内部
            # 路径/栈信息透给 HTTP 客户端。与 _api_code_review_items_status 同款
            # 泛化文案（详情经服务端日志留痕）。
            self._error(500, "生成修复 SPEC 失败（详见服务端日志）")
            return
        if not result.get("ok"):
            self._error(400, result.get("error") or "生成修复 SPEC 失败")
            return
        self._json(result)

    def _api_code_review_items_status(self, query):
        """POST /api/code-review/items/status — body {project, item_id, status}

        人工状态流转（ignored 忽略 / open 清除归属），经
        ``core.code_review.set_item_status``（仅 open/ignored 可人工置入）。

        返回 ``{ok, item_id, status, error}``。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        status = body.get("status")
        if not isinstance(item_id, str) or not item_id:
            self._error(400, "item_id required")
            return
        if status not in ("open", "ignored"):
            self._error(400, f"status 仅支持 open/ignored（人工可置状态）: {status!r}")
            return
        from core.code_review import set_item_status

        proot = Path(project["path"])
        try:
            result = set_item_status(str(proot), item_id, status)
        except Exception as e:  # noqa: BLE001
            # 不外泄裸异常文本（code-review item c74cd0e8859d）：`{e}` 会把
            # 内部路径/细节透给 HTTP 客户端，与 _api_code_review_generate_spec
            # 已声明的泛化文案策略同款（本文件同款 logger 兜底模式）——
            # 细节降级经服务端日志留痕，客户端收通用消息。
            _log = getattr(self, "logger", None)
            if _log is not None:
                _log.warning(
                    "code_review_routes",
                    f"状态流转异常（item_id={item_id}）: {type(e).__name__}: {e}",
                )
            self._error(500, "状态流转失败（详见服务端日志）")
            return
        if not result.get("ok"):
            self._error(400, result.get("error") or "状态流转失败")
            return
        self._json(result)

    # ── 辅助 ──────────────────────────────────────────────

    @staticmethod
    def _code_review_state_machine(project_path):
        """目标**项目**的 StateMachine（generate_fix_spec 注册用；惰性构造）。

        code-review item 62e84785cd28：旧实现固定返回 FRAMEWORK_ROOT 下
        `.fenix/STATE.md` 的 StateMachine——多项目监控部署下会把生成的修复 SPEC
        注册到**框架根** STATE，目标项目 daemon 读不到该 spec、永不晋升。改为指向
        目标项目路径（单项目/框架自托管部署下二者一致，行为不变）。
        """
        from core.state_machine import StateMachine, project_state_logger

        # 跨进程写入者 MUST 注入真实 logger（fix-state-atomicity-and-selfheal-restart
        # 1.3/D2）：generate_fix_spec 经 add_spec 写 STATE，无 logger 构造会静默。
        return StateMachine(
            Path(project_path) / ".fenix" / "STATE.md",
            project_state_logger(project_path),
        )