"""code_review_routes.py — code-review（周期性代码审查）routes（add-code-review-agent-and-quality-tab）。

承载 9 个端点：
- GET  /api/code-review/items      （query project、可选 status）→ 台账列表
- GET  /api/code-review/progress   （query project）→ 运行进度
- GET  /api/code-review/fix-progress（query project）→ 自动修复进度（add-code-review-auto-fix）
- POST /api/code-review/run        （query ?project=<name> + body {scope}）→ 写手动触发信号
- POST /api/code-review/fix-run    （query project）→ 写手动「立即自动修复」信号（add-code-fix-manual-trigger）
- GET  /api/code-review/fix-run-result（query project）→ 只读手动触发判定结果（add-code-fix-manual-trigger）
- GET  /api/code-review/run-result （query project）→ 只读审查触发受理判定结果（add-code-review-trigger-ack）
- POST /api/code-review/generate-spec（query ?project=<name> + body {item_ids, start_after?}）→ 生成修复 SPEC
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

from core import timelib
from core.dashboard import data as dashboard_data
# 消费方守卫提升到共享模块（item fcadb893a1c8：regression run/fix 两端点
# 此前又各内联一份同构守卫）；本模块 re-import 保持
# ``code_review_routes._guard_hosting_state`` 属性路径可解析。
from core.dashboard.routes.hosting_guard import _guard_hosting_state

logger = logging.getLogger("fenixd.dashboard.routes.code_review_routes")

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

    兼容尾缀 ``Z``。解析内核收拢至 timelib.parse_ts
    （add-timelib-consolidation-layer 3.4）：naive（无时区，历史/外部人工
    写手）按**本地时区**解读——推翻本助手旧实现的 naive→UTC（design D6
    「全链约定 UTC」的字面口径），与全框架唯一 naive 策略一致
    （design D1：存量 naive 实测多为本地 now()）。解析失败返回 None
    （调用方 fail-open 放行，链路终点是 daemon 侧落结果文件的显式反馈，
    无静默路径）。
    """
    parsed = timelib.parse_ts(value)
    if parsed is None:
        return None
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
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            finally:
                # fdopen 失败路径显式关 fd（同上方 71d502440d3b 先例）；
                # close 失败不吞（item 885b6ebbff70）：交外层 except 统一
                # 清 req_path 并包装，与主路径异常契约一致，不再以裸
                # OSError 逃逸
                if f is not None:
                    f.close()
                else:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
        except Exception as wexc:
            # 回退路径写中途失败（含 close 失败）：轮询路径上的半写文件若
            # 残留，daemon 重启时会被误消费成一次用户并未请求的触发——
            # best effort 清掉后照常上报（fd 尚在内层 finally 关闭，unlink
            # 打开中的文件合法）
            try:
                os.unlink(str(req_path))
            except OSError:
                pass
            raise _SignalWriteError(str(wexc)) from wexc
    finally:
        # 链接成功/失败临时文件均无存在必要（成功后内容已由 link 名可见）
        try:
            os.unlink(str(tmp_path))
        except OSError:
            pass
    return str(req_path)


class H11CodeReviewRoutesMixin:
    """H11 code-review（design D1 表 C H11）。"""

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

        # [fenix-ignore:9d2d4a1e7622] 已豁免的分页语义变体：服务端分页参数
        # 解析单源为 H0BaseMixin._parse_page_params（core/dashboard/routes/
        # base.py），但其语义是逐参独立修复（page 在场非法回退 1、
        # page_size 超限截到 max_size、单参在场即分页）。本端点契约（见上
        # docstring，向后兼容旧消费者）是 page/page_size 均传且均合法才切片，
        # 任一缺席/非法整组回退全量、响应恒带 page/page_size 键（回退为
        # None），且上限 500 为硬拒而非截断——迁移单源会改写这三处既有
        # 语义，故保留内联解析并在此登记豁免。
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

        # 运行中守卫（基于产物终态判定，见 core.code_review.read_progress——
        # 已取消/已停机的 run 必须判 running=false，否则 409 恒真锁死后续触发）。
        # 先于 backlog 守卫（item 09161dffa0ee）：审查进行中台账条目会被陆续
        # 写成 open，running 与超阈值常同时成立——若 backlog 守卫先行，首步
        # 回 code_review_open_backlog 并提示「confirm 后开跑」，用户照做后仍
        # 被本守卫以 code_review_running 拒绝；running 在前使运行中请求恒返回
        # 更准确的状态码。
        progress = dashboard_data.read_code_review_progress(str(proot))
        if progress.get("running"):
            self._coded_error(409, "已有审查在进行中", "code_review_running")
            return

        # 二次全仓叠加防护（evo-add-code-review-ratelimit-resume 4.1，spec
        # 「Requirement: 二次全仓叠加防护」）：上一轮全仓审查未消化完（台账
        # open 条数超阈值）时，手动 full 触发回 409 确认态而非直接开跑——
        # 对齐 trigger-ack 409 三态回链先例（code_review_running/
        # code_review_ack_pending 同族，code 由 ApiError.code 承载）。阈值入
        # 配置（admin.code_review.manual_full_open_warn，缺省 30；显式 0 =
        # 关闭守卫）。未确认不派发：body 携带 confirm=true 的二次请求才放行。
        # 严格只认布尔 true：任意非空字符串（如 "false"）真值为真会绕过确认闸门
        if scope == "full" and body.get("confirm") is not True:
            from core.code_review import read_items as _cr_read_items
            from core.config import ConfigLoader as _ConfigLoader

            cfg = _ConfigLoader.get_code_review_config(
                dashboard_data.read_effective_config(str(proot)))
            # [fenix-ignore:4e4096f96e4a] 配置源 get_code_review_config 已无条件校验该键（非 int/bool/负数回退 30）且恒以 int 返回，此 int() 不会抛 ValueError
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

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push；
        # item 13d53dcd5440 提取 _guard_hosting_state 与 fix-run 共用）
        guard = _guard_hosting_state(proot, "审查信号")
        if guard is not None:
            self._error(*guard)
            return

        # 受理窗口守卫（add-code-review-trigger-ack 2.3，design D3）：信号已被
        # 上一触发消费（O_EXCL 守卫覆盖不到的空隙）、daemon 已受理（结果
        # started）但 run 尚未开始（progress.running=false，复用上方 running
        # 守卫的同一 progress 快照）且结果新鲜（finished_at 距今 ≤ 900s）且
        # 受理后尚无新 run 启动过（review_id 内嵌 epoch 整秒小于 finished_at
        # 整秒值——run 结束后结果文件仍停留 started，仅凭新鲜度会把窗口内合法
        # 重触发误判为「排队中」假 409；item 5dbef178f679：同粒度整秒比较，
        # 受理与 run 启动同秒即视为已启动）→ 409 稳定错误码，消灭窗口内第二次
        # POST 假受理。守卫读结果与 run 实际启动之间存在竞态 → fail-open 到
        # daemon 单飞的显式拒绝并落结果（有反馈不留静默）。
        ack_result = dashboard_data.read_code_review_request_result(str(proot))
        if (str(ack_result.get("status") or "") == "started"
                and not progress.get("running")):
            finished_at = _parse_iso_utc(ack_result.get("finished_at"))
            if (finished_at is not None
                    and (datetime.now(timezone.utc) - finished_at).total_seconds()
                    <= CODE_REVIEW_ACK_WINDOW_SECONDS):
                epoch = _review_id_epoch(progress.get("review_id"))
                # item 5dbef178f679：epoch 是 run_id 内嵌的秒级截断值，而
                # finished_at 含亚秒——跨粒度直接比 ≤ 会把「受理与 run 启动
                # 落在同一秒」误判为未启动（X ≤ X.2），窗口内合法重触发被假
                # 409 挡到 15 分钟自然过期。finished_at 取整秒同粒度比较：
                # epoch 严格小于才判「受理后尚无新 run 启动」（保守拒绝方向
                # 不变，同秒启动即视为已启动放行）。
                if epoch is None or epoch < int(finished_at.timestamp()):
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
        # requested_at；item 117af27b759a：旧实现误写 created 键使 daemon
        # 恒记空时间戳，现已改写 requested_at）
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

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push；
        # item 13d53dcd5440 提取 _guard_hosting_state 与 run 端点共用）
        guard = _guard_hosting_state(proot, "修复信号")
        if guard is not None:
            self._error(*guard)
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
        created_dt = _parse_iso_utc(created)

        def _result_stale():
            """读结果文件并判是否属上一轮残留（request_created 早于 created）。

            item 532fa1df1b2d：合法非 object JSON（[]/null 等）无 .get，先判
            类型，非 dict 按上一轮残留处置（维持预删语义），勿让 AttributeError
            穿透端点。文件缺失/损坏/不可解析时不可能属于本次，按上一残留处置。
            """
            try:
                with result_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return True
            prev_created = (
                str(data.get("request_created") or "")
                if isinstance(data, dict)
                else ""
            )
            prev_dt = _parse_iso_utc(prev_created)
            return created_dt is None or prev_dt is None or prev_dt < created_dt

        stale = _result_stale()
        if stale:
            # item 832ef25ae234：unlink 前重读复核——首读与 unlink 之间有窗口，
            # daemon 1s tick 恰在此间隙消费刚写入的信号并原子 replace 本次判定
            # （request_created == created）时，按首读到的上一轮旧内容执行的
            # unlink 会把本次触发的判定误删（前端轮询变缺省空态、反馈丢失）。
            # 双读仍判 stale（文件已消失/内容已换新均不成立）才删；删除失败
            # 不阻塞受理。
            stale = _result_stale()
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
        """POST /api/code-review/generate-spec?project=<name> — body {item_ids: [...]}

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