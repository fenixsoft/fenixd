"""code_review_routes.py — code-review（周期性代码审查）routes（add-code-review-agent-and-quality-tab）。

承载 9 个端点：
- GET  /api/code-review/items      （query project、可选 status）→ 台账列表
- GET  /api/code-review/progress   （query project）→ 运行进度
- GET  /api/code-review/fix-progress（query project）→ 自动修复进度（add-code-review-auto-fix）
- POST /api/code-review/run        （query ?project=<name> + body {scope}）→ 写手动触发信号
- POST /api/code-review/fix-run    （query project）→ 写手动「立即自动修复」信号（add-code-fix-manual-trigger）
- GET  /api/code-review/fix-run-result（query project）→ 只读手动触发判定结果（add-code-fix-manual-trigger）
- GET  /api/code-review/run-result （query project）→ 只读审查触发受理判定结果（add-code-review-trigger-ack）
- POST /api/code-review/generate-spec（body {project, item_ids, start_after?}）→ 生成修复 SPEC
- POST /api/code-review/items/status（body {project, item_id, status}）→ 人工状态流转

端点 handler 走既有 mixin 形态（self._json / self._error / _read_json_body）。
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from core.dashboard import data as dashboard_data

logger = logging.getLogger("fenixd.dashboard.code_review_routes")

# 手动触发信号文件（daemon 主循环经 fenixd._check_code_review_requests 消费）。
# 与 admin_invoke_request / cancel_run_request / approve_push_request 同属
# 「dashboard 原子写 → daemon 主循环消费」文件信号族。
CODE_REVIEW_REQUEST = ".fenix/code_review_request.json"

# 手动「立即自动修复」信号与判定结果文件（add-code-fix-manual-trigger）。
# 信号由 daemon 主循环经 fenixd._check_code_fix_requests 消费；结果文件由
# 消费端原子写回，GET fix-run-result 只读透传。
CODE_FIX_REQUEST = ".fenix/code_fix_request.json"
CODE_FIX_REQUEST_RESULT = ".fenix/code_fix_request_result.json"

# 受理窗口新鲜度阈值（add-code-review-trigger-ack 2.3 / design D3）：回链
# 结果 finished_at 距今超过该秒数即视为陈旧，窗口守卫放行——run 结束后结果
# 文件仍停留 started，不判新鲜会把「已跑完」永久误判为「排队中」锁死触发。
CODE_REVIEW_ACK_WINDOW_SECONDS = 900


def _parse_iso_utc(value):
    """容错解析 ISO8601 时刻为 aware UTC datetime；非法/空返回 None。

    兼容尾缀 ``Z`` 与无时区的 naive 值（后者按 UTC 解释——全链约定 UTC，
    design D6）。解析失败返回 None（调用方 fail-open 放行，链路终点是
    daemon 侧落结果文件的显式反馈，无静默路径）。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _review_id_epoch(review_id):
    """从 review_id（``code-review-<epoch>[-<n>]``）提取内嵌 epoch；无则 None。

    与 core.code_review._latest_review_run 同款解析（epoch 后可跟多个退避
    ``-<n>`` 段，取首个 9~10 位数字段）。
    """
    m = re.search(r"(\d{9,10})(?:-\d+)*$", str(review_id or ""))
    return int(m.group(1)) if m else None


# os.link(2) 在部分文件系统上根本不可用（网络挂载/容器卷/Windows 非 NT
# 挂载等），报错即这组 errno——此时降级为 O_CREAT|O_EXCL 直接独占创建
# 轮询路径（见 _write_signal_exclusive 回退分支，item 85f9732c331b）。
_LINK_UNSUPPORTED_ERRNOS = frozenset(
    {errno.EPERM, errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL}
)


class _SignalWriteError(Exception):
    """信号文件独占写失败（FileExistsError 之外的失败，调用方映射 500）。"""


def _write_signal_exclusive(req_path, payload):
    """三步原子写「dashboard → daemon」文件信号（run / fix-run 端点共用，
    item 422ae03395de 去重——此前 _api_code_review_run 与
    _api_code_review_fix_run 各复制一份约 60 行同构逻辑，同族竞态修复
    （如 link 不支持的文件系统回退）需同步改两处，易漂移）。

    - 原子创建信号文件（O_CREAT|O_EXCL 独占创建，code-review item
      d3c1d2ef4a88）：ThreadingHTTPServer 最多 64 并发线程，旧实现的
      ``exists()`` 检查 + ``os.replace`` 非原子——两个并发 POST 可同时通过
      检查，后者的 replace 会静默覆盖前者（或覆盖一条已存在未消费的请求），
      丢失一次用户触发。独占创建成功即胜出。
    - 先填内容、再原子挂到轮询路径（code-review item 502bc934c4c6）：旧实现
      O_CREAT|O_EXCL 直接创建轮询路径、之后才 json.dump——daemon 1s 主循环
      tick 落在创建与填充之间的空窗，消费端读到空/半写文件解析失败，用户
      触发静默丢失。三步：
        1. 写同目录唯一临时文件（同目录保证 link 原子性），完整 JSON + fsync；
        2. os.link(2) 原子挂到轮询路径——目标已存在抛 FileExistsError，保留
           独占创建语义（并发第二 POST 或上一信号尚未被消费）；
        3. 消费者要么看不到文件、要么看到完整 JSON，空窗不复存在。
      link 不支持的文件系统回退（errno 属 _LINK_UNSUPPORTED_ERRNOS，item
      85f9732c331b）：降级为 O_CREAT|O_EXCL 直接独占创建轮询路径、之后灌
      入完整内容——独占创建语义保留（目标已存在仍 FileExistsError → None），
      代价是创建与填充之间重现半写空窗，仅限该受限回退路径，正常文件系统
      仍走三步无空窗。

    返回：成功 → 信号轮询路径字符串；目标已存在（独占写失败）→ None。
    异常：其余失败（mkdir/os.open/写内容/os.link 的 OSError）抛
    _SignalWriteError。
    409/500 的错误码与文案差异由调用方映射，本函数不发响应。
    """
    try:
        req_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # 父目录创建失败（.fenix 不可建：只读盘/权限）与 os.open 同口径包装
        # （code-review item 512425623308）：裸 OSError 会穿透调用方的
        # except _SignalWriteError 分支，落到通用 500 兜底，客户端收不到
        # 「信号写入失败」的结构化文案。
        raise _SignalWriteError(str(exc)) from exc
    tmp_path = (
        req_path.parent / f".{req_path.name}.{os.getpid()}.{uuid4().hex}.tmp"
    )
    try:
        fd = os.open(str(tmp_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except OSError as exc:
        raise _SignalWriteError(str(exc)) from exc
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
    except Exception as exc:
        # 写中途失败：清掉临时文件（轮询路径尚未创建，无半写残留可误消费）
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
        raise _SignalWriteError(str(exc)) from exc
    try:
        os.link(str(tmp_path), str(req_path))
    except FileExistsError:
        # 独占创建语义下的败者（并发第二 POST / 上一信号未消费）→ None，
        # 由调用方映射各自的 409；finally 照常清临时文件
        return None
    except OSError as exc:
        if exc.errno not in _LINK_UNSUPPORTED_ERRNOS:
            raise _SignalWriteError(str(exc)) from exc
        # link 在该文件系统上根本不可用（item 85f9732c331b）：降级为
        # O_CREAT|O_EXCL 直接独占创建轮询路径再灌完整内容。独占创建语义
        # 保留（目标已存在仍 FileExistsError → None → 调用方 409）；代价
        # 是创建与填充之间重现半写空窗，仅限此受限回退路径可接受。
        try:
            fd = os.open(
                str(req_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644
            )
        except FileExistsError:
            return None
        except OSError as oexc:
            raise _SignalWriteError(str(oexc)) from oexc
        f = None
        try:
            f = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        except Exception as wexc:
            # 回退路径写中途失败：轮询路径上的半写文件若残留，daemon 重启
            # 时会被误消费成一次用户并未请求的触发——best effort 清掉后
            # 照常上报（fd 尚在 finally 关闭，unlink 打开中的文件合法）
            try:
                os.unlink(str(req_path))
            except OSError:
                pass
            raise _SignalWriteError(str(wexc)) from wexc
        finally:
            # fdopen 失败路径显式关 fd（同上方 71d502440d3b 先例）
            if f is not None:
                f.close()
            else:
                try:
                    os.close(fd)
                except OSError:
                    pass
    finally:
        # 链接成功/失败临时文件均无存在必要（成功后内容已由 link 名可见）
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
    return str(req_path)


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
        [&severity=major][&page=1&page_size=10]
        [&sort_by=severity|status][&sort_order=asc|desc]

        返回 ``{items: [...], total: N}``（默认 severity 升序，可选按
        severity/status 排序，默认仅 open）。``total`` 为过滤后总数（分页配
        套，2026-09-24 用户要求：台账 resolved 上千行不再一次全量拉取，表格
        分页改 server-side）。``page``/``page_size`` 均传才切片，缺省返回全量
        （向后兼容旧消费者）；非法值整组回退全量。severity 可选单值过滤（前端
        严重度下拉同样下沉 server-side）。sort_by/sort_order 与过滤/分页同层
        下发（2026-09-24）：前端两列排序 server-side 化配套，分页形态下客户端
        排序只重排当页 10 行；白名单外值回退默认排序（白名单映射见
        read_code_review_items）。
        缺项目 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        statuses = None
        raw = query.get("status", [None])[0]
        if raw:
            statuses = [s.strip() for s in raw.split(",") if s.strip()]
        severity = (query.get("severity", [None])[0] or "").strip() or None
        sort_by = (query.get("sort_by", [None])[0] or "").strip() or None
        sort_order = (query.get("sort_order", [None])[0] or "").strip() or None
        items = dashboard_data.read_code_review_items(
            str(project["path"]),
            statuses=statuses,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        if severity:
            items = [it for it in items if it.get("severity") == severity]
        total = len(items)

        def _page_int(name):
            raw = query.get(name, [None])[0]
            try:
                return int(raw)
            except (TypeError, ValueError):
                return None

        page, page_size = _page_int("page"), _page_int("page_size")
        if page is not None and page_size is not None and page >= 1 and 1 <= page_size <= 500:
            start = (page - 1) * page_size
            items = items[start : start + page_size]
        else:
            page = page_size = None
        self._json({"items": items, "total": total, "page": page, "page_size": page_size})

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
        """POST /api/code-review/run — query ?project=<name> + body {scope: "full"|"window"}

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

        # 二次全仓叠加防护（evo-add-code-review-ratelimit-resume 4.1，spec
        # 「Requirement: 二次全仓叠加防护」）：上一轮全仓审查未消化完（台账
        # open 条数超阈值）时，手动 full 触发回 409 确认态而非直接开跑——
        # 对齐 trigger-ack 409 三态回链先例（code_review_running/
        # code_review_ack_pending 同族，code 由 ApiError.code 承载）。阈值入
        # 配置（admin.code_review.manual_full_open_warn，缺省 30；显式 0 =
        # 关闭守卫）。未确认不派发：body 携带 confirm=true 的二次请求才放行。
        if scope == "full" and not bool(body.get("confirm")):
            from core.code_review import read_items as _cr_read_items
            from core.config import ConfigLoader as _ConfigLoader

            cfg = _ConfigLoader.get_code_review_config(
                dashboard_data.read_effective_config(str(proot)))
            open_warn = int(cfg.get("manual_full_open_warn") or 0)
            if open_warn > 0:
                open_count = sum(
                    1
                    for rec in _cr_read_items(str(proot)).values()
                    if isinstance(rec, dict) and rec.get("status") == "open"
                )
                if open_count > open_warn:
                    self._coded_error(
                        409,
                        f"台账仍有 {open_count} 条 open（超过确认阈值 "
                        f"{open_warn}），上一轮全仓审查可能未消化完。再次触发"
                        f"并携带 confirm=true 以确认开始新一轮全仓审查",
                        "code_review_open_backlog",
                    )
                    return

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
            logger.warning(
                "hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: %r", exc
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

        # 受理窗口守卫（add-code-review-trigger-ack 2.3，design D3）：信号已被
        # 上一触发消费（O_EXCL 守卫覆盖不到的空隙）、daemon 已受理（结果
        # started）但 run 尚未开始（progress.running=false，复用上方 running
        # 守卫的同一 progress 快照）且结果新鲜（finished_at 距今 ≤ 900s）且
        # 受理后尚无新 run 启动过（review_id 内嵌 epoch ≤ finished_at——run
        # 结束后结果文件仍停留 started，仅凭新鲜度会把窗口内合法重触发误判为
        # 「排队中」假 409）→ 409 稳定错误码，消灭窗口内第二次 POST 假受理
        # （今日会被 daemon 单飞静默丢弃）。守卫读结果与 run 实际启动之间存在
        # 竞态 → fail-open 到 daemon 单飞的显式拒绝并落结果（有反馈不留静默）。
        ack_result = dashboard_data.read_code_review_request_result(str(proot))
        if (str(ack_result.get("status") or "") == "started"
                and not progress.get("running")):
            finished_at = _parse_iso_utc(ack_result.get("finished_at"))
            if (finished_at is not None
                    and (datetime.now(timezone.utc) - finished_at).total_seconds()
                    <= CODE_REVIEW_ACK_WINDOW_SECONDS):
                epoch = _review_id_epoch(progress.get("review_id"))
                if epoch is None or epoch <= finished_at.timestamp():
                    self._coded_error(
                        409,
                        "审查已受理，正在启动（文件收集/排队中），请稍候",
                        "code_review_ack_pending",
                    )
                    return

        # 原子创建信号文件：三步独占写机制（写临时文件+fsync+os.link+finally
        # unlink，item d3c1d2ef4a88 / 502bc934c4c6）收口在共用辅助函数
        # _write_signal_exclusive（item 422ae03395de 去重）。独占创建成功即
        # 胜出；返回 None 表示 FileExistsError（已有未消费请求）→ 409。
        created = datetime.now(timezone.utc).isoformat()
        # 键名与消费者契约一致（fenixd._check_code_review_requests 读
        # requested_at；item 117af27b759a：写 created 使 daemon 恒记空时间戳）
        payload = {"scope": scope, "source": "dashboard", "requested_at": created}
        req_path = proot / CODE_REVIEW_REQUEST
        try:
            written = _write_signal_exclusive(req_path, payload)
        except _SignalWriteError:
            self._error(500, "审查触发信号写入失败")
            return
        if written is None:
            self._coded_error(409, "已有未消费的审查触发请求（请稍后重试）",
                              "code_review_request_pending")
            return
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
        - 受理后预删旧结果文件（仅信号 O_EXCL 独占创建且写入成功后，拒绝
          路径保留上一轮判定）：防止上一轮残留判定被前端误当本次反馈；删前
          校验 request_created，不误删消费端已写回的本次判定。
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
            logger.warning(
                "hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: %r", exc
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

        # 原子创建信号文件：三步独占写机制（写临时文件+fsync+os.link+finally
        # unlink，同族竞态 item 502bc934c4c6）与 _api_code_review_run 共用
        # _write_signal_exclusive（item 422ae03395de 去重）。独占创建成功即
        # 胜出；返回 None 表示 FileExistsError（并发第二 POST 或上一信号
        # 尚未被消费）→ 409。
        created = datetime.now(timezone.utc).isoformat()
        payload = {"source": "dashboard", "created": created}
        req_path = proot / CODE_FIX_REQUEST
        try:
            written = _write_signal_exclusive(req_path, payload)
        except _SignalWriteError:
            self._error(500, "修复触发信号写入失败")
            return
        if written is None:
            self._coded_error(409, "已有未消费的修复触发请求（请稍后重试）",
                              "fix_run_request_pending")
            return
        # 预删旧结果文件（残留判定 MUST NOT 被前端当本次反馈；删除失败不阻塞
        # 受理）。code-review item ac4182077d1f：仅在信号文件 O_EXCL 独占创建
        # 且完整写入成功（即受理路径）之后删除——预删若位于受理判定之前，
        # 409（信号槽被占）/500 拒绝路径会把上一轮判定一并删掉，前端轮询
        # fix-run-result 变成缺省空态，用户看到的上次反馈凭空消失。
        # item a4500c7dfb06：删前校验 request_created——daemon 1s tick 可能恰
        # 在 link 与 unlink 的间隙把本信号消费掉并原子写回本次判定
        # （request_created == created，回链自信号 created），无条件 unlink
        # 会把这份本次触发的结果误删。仅当结果文件确属上一轮（request_created
        # 早于 created）才删；文件缺失/损坏/不可解析时不可能属于本次，按上一
        # 残留处置（维持预删语义）。
        result_path = proot / CODE_FIX_REQUEST_RESULT
        try:
            with result_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            # item 532fa1df1b2d：合法非 object JSON（[]/null 等）无 .get，先判
            # 类型，非 dict 按上一轮残留处置（维持预删语义），勿让 AttributeError
            # 穿透端点。
            prev_created = (
                str(data.get("request_created") or "")
                if isinstance(data, dict)
                else ""
            )
            prev_dt = _parse_iso_utc(prev_created)
            created_dt = _parse_iso_utc(created)
            stale = created_dt is None or prev_dt is None or prev_dt < created_dt
        except (OSError, ValueError):
            stale = True
        if stale:
            try:
                result_path.unlink()
            except OSError:
                pass
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

    def _api_code_review_run_result(self, query):
        """GET /api/code-review/run-result?project=<name>
        （add-code-review-trigger-ack 2.2）

        手动触发审查的受理判定结果只读透传：返回 daemon 消费端写回的
        ``.fenix/code_review_request_result.json`` 内容（``{requested_at,
        status, reason, message, finished_at}``）。文件缺失/损坏 → 缺省态
        全 null 形态（MUST NOT 500，形态对齐 _api_code_review_fix_run_result）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_code_review_request_result(str(project["path"])))

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
            logger.warning(
                "生成修复 SPEC 异常（item_ids=%s）: %s: %s",
                item_ids, type(e).__name__, e
            )
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
            logger.warning(
                "状态流转异常（item_id=%s）: %s: %s", item_id, type(e).__name__, e
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