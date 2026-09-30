"""spec_routes.py — H3 spec management。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.dashboard import data as dashboard_data
from core.dashboard.registry import Registry

# fenixd. 层级字面量（tests/test_logger_no_bypass.py：core/ 禁 __name__ 旁路）
logger = logging.getLogger("fenixd.dashboard.routes.spec_routes")


def _spec_entry_with_archive_fallback(proot, spec: str) -> dict | None:
    """取 SPEC 条目：活跃 STATE.md 优先，归档清单回退（add-archive-state-migration D4）。

    条目已迁出（仅清单有）的已归档 SPEC 继续可进详情/读文档——文档与进度
    读取经既有 ``resolve_spec_dir`` 归档回退，不依赖活跃 STATE.md 条目。
    双源均无 → None（调用方维持 404 语义）。
    """
    entry = dashboard_data.parse_state(proot).get(spec)
    if entry is not None:
        return entry
    return dashboard_data.parse_archived_state(proot).get(spec)


def _internal_error(handler, msg: str, exc: BaseException) -> None:
    """端点级兜底 500 统一收口（code-review item 12bae0b2286c）。

    不内嵌裸异常文本——`{e}` 会把内部绝对路径/存储细节透给 HTTP 客户端，
    与 base 层 _handle 外层 500 策略对齐（item 1a2a0bd78662）：对外固定
    文案（msg 保留端点语境：哪个操作 failed），原始异常经 logger.exception
    （含 traceback）留服务端日志。
    """
    logger.exception("%s", msg, exc_info=exc)
    handler._error(500, msg)


class H3SpecRoutesMixin:
    """H3 spec management。"""

    def _spec_query_or_error(self, query):
        """本文件 spec 端点共用参数校验（code-review item de2b8b27864c）：
        「取 spec → _project_from_query → 未知项目 404 → 项目不存在 404 →
        缺 spec 404」原先在各端点内联逐字重复（16 个状态操作端点 +
        _api_spec_doc 共 17 处），收敛为单源防漂移。

        形态对照 project_routes._project_query_or_error：校验通过返回
        (project, spec)；任一失败已发送对应 404 响应并返回 None。缺参
        状态码口径与该助手（缺 project 400）不同——本文件全部端点对缺
        project/spec 均维持 404 既有契约（tests 按 404 语义消费），保持不变。
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return None
        if not project.get("exists"):
            self._error(404, "project not found")
            return None
        if not spec:
            self._error(404, "spec required")
            return None
        return project, spec

    def _api_specs(self, query) -> dict:
        # 未知/不存在项目维持 200 + {"error": ..., "specs": []}，不走本文件
        # 其余端点的 _error(404) 家族——这是有意的 v1 兼容契约，非遗漏：
        # tests/test_dashboard_api.py::test_unknown_project 钉死 200 + specs
        # 空表形状，v3 前端 list 页 load() 也按响应体 error 字段分支渲染，
        # 改 404 会同时破坏测试契约与前端消费形状（code-review item 81d9ba1b6aae）。
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project", "specs": []}
        if not project.get("exists"):
            return {"error": "project not found", "specs": []}
        proot = Path(project["path"])
        # 列表数据源 = 活跃 ∪ 归档清单（add-archive-state-migration 3.2/D4）：
        # 合并单点在 SummaryIndex.get()（活跃侧优先），本端点与 watcher SSE
        # 推送同源消费——清单条目 archived=true 并经 spec_summary 透传
        # archived_at/archived_by 溯源字段，「已归档」视图对迁出条目继续可见。
        items = self.server.summary_index.get(proot)
        items.sort(key=lambda s: s.get("created") or "", reverse=True)
        # 服务端分页（add-dashboard-paging-and-etag 2.2）：现有排序后切片；
        # 带 page 追加 total/page/page_size/has_more；缺省 page 响应零变化
        #（不追加任何字段，增量 patch 前端零改动可用）。
        page, page_size = self._parse_page_params(
            query.get("page", [None])[0],
            query.get("page_size", [None])[0],
            default_size=200,
            max_size=500,
        )
        if page is None:
            return {"project": project["name"], "specs": items}
        total = len(items)
        start = (page - 1) * page_size
        return {
            "project": project["name"],
            "specs": items[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": start + page_size < total,
        }


    def _api_spec_detail(self, spec: str, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        proot = Path(project["path"])
        # 条目已迁出（仅清单有）的已归档 SPEC 继续可进详情（清单回退，
        # add-archive-state-migration 3.2）
        entry = _spec_entry_with_archive_fallback(proot, spec)
        if entry is None:
            return {"error": f"spec not found: {spec}", "project": project["name"]}
        detail = dashboard_data.spec_detail(proot, spec, entry)
        detail["project"] = project["name"]
        return detail


    def _api_spec_doc(self, query) -> dict | None:
        """GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>

        读取 SPEC 的 proposal.md / design.md / tasks.md 原文返回 {found, content}。
        - doc 非法 → 400
        - spec 非法 / STATE、归档清单、归档目录均无命中 → 404（且不读取任何
          changes 目录外文件）
        - 文件不存在 → 200 + {found: false, content: ""}
        """
        doc = query.get("doc", [None])[0]
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        # 文件缺失是常态分支，但 spec 必须真在项目 STATE.md 或归档清单中
        # （D2：仅未知 spec 才 404；清单回退使已迁出 SPEC 的文档继续可读，
        # add-archive-state-migration 3.2）。双源均无时再以归档目录命中兜底：
        # 日期前缀旧归档与软删除墓碑（<spec>-<Unix秒>）本就无 STATE/清单条目，
        # 知识溯源链接以目录名原样引用（fix-archived-spec-doc-readback 契约，
        # tests test_api_spec_doc_archived_readback/_soft_deleted_tombstone）；
        # 越界防护由 _SPEC_NAME_RE + get_spec_doc 的目录内 containment 校验承担。
        proot = Path(project["path"])
        if _spec_entry_with_archive_fallback(proot, spec) is None and (
            dashboard_data.resolve_spec_dir(proot, spec) is None
        ):
            self._error(404, f"spec not found: {spec}")
            return
        try:
            result = dashboard_data.get_spec_doc(proot, spec, doc)
        except dashboard_data.InvalidSpecDoc:
            self._error(400, f"invalid doc: {doc}")
            return
        except dashboard_data.InvalidSpecName:
            self._error(404, f"invalid spec: {spec}")
            return
        self._json({**result, "project": project["name"], "spec": spec, "doc": doc})

    # ── SPEC 状态操作 ─────────────────────────────────────────────────


    def _api_spec_error_clear(self, query) -> dict | None:
        """POST /api/spec-error-clear?project=<name>&spec=<name>

        在线清除 SPEC 的 error 字段（置空并原子写回 STATE.md）。
        - project 不存在 → 404
        - spec 非法 / 不在项目 STATE.md → 404
        - spec 处于冻结态 → 409「清除错误会连带解除冻结，请先解冻」
          （item babdab6b010b：对齐 freeze-config 家族 409 拒绝语义）
        - 成功 → 200 + {ok: true}；其余字段不受影响
        - 写回异常 → 500
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.clear_spec_error(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "clear spec error failed", e)
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        if not result.get("ok"):
            # 冻结态拒绝（item babdab6b010b）：错误文案由数据层给出（提示先解冻）
            self._error(409, result.get("error") or "SPEC 处于冻结态，请先解冻")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec})


    def _api_spec_priority(self, query):
        """POST /api/spec-priority?project=<name>&spec=<name>  body: {"priority": N}

        设置 SPEC 优先级（1-9，P1 最高）。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404
        - body 缺 priority / 非法值（0、10、非整数）→ 400
        - 成功 → 200 + {ok: true, priority: N}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        body = self._read_json_body()
        if body is None:
            return
        if "priority" not in body:
            self._error(400, "priority required in request body")
            return
        # bool/浮点显式拒绝（与 spec-budget 端点同口径）——int(True) 会静默转 1
        # 被当作 P1，int(2.9) 会静默截断为 2；str 保留（数据层兼容可转 int 的 str）
        if isinstance(body["priority"], bool) or not isinstance(body["priority"], (int, str)):
            self._error(400, "priority must be an integer between 1 and 9")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_priority(proot, spec, body["priority"])
        except dashboard_data.InvalidPriority:
            self._error(400, "priority must be an integer between 1 and 9")
            return
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "set spec priority failed", e)
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        self._json(
            {"ok": True, "project": project["name"], "spec": spec, "priority": result["priority"]}
        )


    def _api_spec_freeze(self, query) -> dict | None:
        """POST /api/spec-freeze?project=<name>&spec=<name>

        人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头
        （admin_monitor 认此模式为有意等待态，免超时误报）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 200 + {ok: true, frozen: false, error: 原因}
        - 成功 → 200 + {ok: true, frozen: true, stopped_agents: N}（N 为
          冻结时刻在跑 agent 计数，add-freeze-stop-inflight-agents BUG-01
          修复；前端据 >0 展示「已停止 N 个在跑 agent」提示）
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        try:
            result = dashboard_data.freeze_spec(Path(project["path"]), spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "freeze spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)


    def _api_spec_unfreeze(self, query) -> dict | None:
        """POST /api/spec-unfreeze?project=<name>&spec=<name>

        解冻 SPEC：恢复冻结前状态并清空 error；未冻结为幂等 no-op。
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        try:
            result = dashboard_data.unfreeze_spec(Path(project["path"]), spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "unfreeze spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)


    def _api_spec_start_after(self, query) -> dict | None:
        """POST /api/spec-start-after?project=<name>&spec=<name>
        body: {"value": "<iso-utc>"|null|"manual"}

        设置/清除 SPEC 定时拾取时间（start_after，ISO8601 UTC 三态：
        - "manual"（哨兵，add-spec-manual-activation D5）→ 设为待激活
          （永不到期，须人工激活后方可被调度器拾取）
        - null → 清除定时（立即恢复调度）
        - ISO8601 → 定时（原语义）
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 403「终态不可设置定时拾取」
        - value 非法 ISO8601 → 400（STATE.md 不变）
        - 成功 → 200 + {ok: true, start_after: <iso|null|"manual">}
          清空时（start_after null）若即时唤醒信号写出失败，响应携带 warning
          （ok 仍为 true——start_after 已成功置 null，附告警供前端分支文案）
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        body = self._read_json_body()
        if body is None:
            return
        if "value" not in body:
            self._error(400, "value required in request body (ISO8601 UTC / null / manual)")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_start_after(proot, spec, body["value"])
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "set spec start_after failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可设置定时拾取")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "start_after 非法 ISO8601")
            return
        resp = {
            "ok": True,
            "project": project["name"],
            "spec": spec,
            "start_after": result.get("start_after"),
        }
        kick = result.get("scheduling_kick")
        if kick and not kick.get("ok"):
            # 信号写出失败：如实告知（D3），不无条件宣称「立即恢复调度」；
            # 周期数取 schedule.poll_interval_minutes 缺省 30（可配置键，措辞不硬编码承诺）
            resp["warning"] = (
                "已清除定时，但即时唤醒信号写入失败，将由下次扫描"
                "（缺省 ≤30 分钟，即 schedule.poll_interval_minutes）派发"
            )
        self._json(resp)


    def _api_spec_activate(self, query) -> dict | None:
        """POST /api/spec-activate?project=<name>&spec=<name>
        body: 无参

        激活待激活 SPEC（add-spec-manual-activation D4）：把 start_after 由
        哨兵 manual 置为 null 并即时唤醒派发（复用 scheduling_kick 信号）。
        错误语义对齐 freeze-config 家族：
        - project 缺失/不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 403「终态不可激活」
        - 非待激活（start_after 非 manual）→ 200 + {ok: false, reason}
          （STATE 零变更，幂等拒绝）
        - 成功 → 200 + {ok: true, spec, start_after: null}
          若即时唤醒信号写出失败，响应携带 warning（ok 仍为 true——start_after
          已成功置 null，附告警供前端分支文案）
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.activate_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "activate spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可激活")
            return
        if not result.get("ok"):
            # 非待激活：200 + reason（幂等拒绝，非请求错误）
            self._json(
                {
                    "ok": False,
                    "project": project["name"],
                    "spec": spec,
                    "reason": result.get("reason") or "该 SPEC 并非待激活态",
                }
            )
            return
        resp = {
            "ok": True,
            "project": project["name"],
            "spec": spec,
            "start_after": result.get("start_after"),
        }
        kick = result.get("scheduling_kick")
        if kick and not kick.get("ok"):
            # 信号写出失败：如实告知（D3），不无条件宣称「立即恢复调度」
            resp["warning"] = (
                "已激活，但即时唤醒信号写入失败，将由下次扫描"
                "（缺省 ≤30 分钟，即 schedule.poll_interval_minutes）派发"
            )
        self._json(resp)


    def _api_spec_resume(self, query) -> dict | None:
        """POST /api/spec-resume?project=<name>&spec=<name>
        body: 无参

        恢复取消保持态 SPEC（add-cancelled-spec-resume-action D1）：复位 ready
        并按保留分支续做（无可保留分支时降级全新重派），后写 scheduling_kick
        即时唤醒派发。错误语义对齐 spec-activate：
        - project 缺失/不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 403「终态不可恢复」
        - 冻结态 / 非取消保持态 / WorktreeManager 构造失败 → 200 +
          {ok: false, reason}（STATE 零变更，幂等拒绝）
        - 成功 → 200 + {ok: true, spec, degraded?, reason?, warning?}
          degraded=true 表示无可保留分支、已降级全新重派；warning 表示即时
          唤醒信号写出失败（STATE 已复位，将由下次扫描派发）
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.resume_cancelled_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "resume spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可恢复")
            return
        if not result.get("ok"):
            # 幂等拒绝（非取消保持态 / 冻结态 / wm 构造失败）：200 + reason
            self._json(
                {
                    "ok": False,
                    "project": project["name"],
                    "spec": spec,
                    "reason": result.get("reason") or "该 SPEC 并非取消保持态",
                }
            )
            return
        resp = {
            "ok": True,
            "project": project["name"],
            "spec": spec,
        }
        if result.get("degraded"):
            resp["degraded"] = True
        if result.get("reason"):
            resp["reason"] = result.get("reason")
        if result.get("warning"):
            resp["warning"] = result.get("warning")
        self._json(resp)


    def _api_spec_freeze_config(self, query) -> dict | None:
        """POST /api/spec-freeze-config?project=<name>&spec=<name>
        body: {"mode": "permanent"|"scheduled"|"unfreeze", "until": "<iso-utc>"?}

        冻结管理配置：永久 ↔ 定时解冻 ↔ 立即解冻。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - spec 未处于冻结态 → 409「冻结管理仅对冻结 spec 生效」
        - mode 非法 / scheduled 的 until 非法 ISO8601 → 400
        - 成功 → 200 + {ok: true, mode, frozen_until, unfrozen?}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        body = self._read_json_body()
        if body is None:
            return
        if "mode" not in body:
            self._error(400, "mode required in request body")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.configure_spec_freeze(
                proot, spec, body["mode"], body.get("until")
            )
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "configure spec freeze failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "非法请求")
            return
        if result.get("error") and not result.get("ok"):
            self._error(409, result.get("error"))
            return
        self._json(
            {
                "ok": True,
                "project": project["name"],
                "spec": spec,
                "mode": result.get("mode"),
                "frozen_until": result.get("frozen_until"),
                "unfrozen": result.get("unfrozen", False),
            }
        )


    def _api_spec_budget(self, query) -> dict | None:
        """POST /api/spec-budget?project=<name>&spec=<name>
        body: {"budget": <1..budget_max 整数|null>}

        设置/清除 SPEC 的实现尝试预算覆盖（impl_run_budget_override）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - body 缺 budget 键 / 非整数（bool/浮点/字符串数字）→ 400
        - 越界（0、超过 agents.impl_run_budget_max）→ 400
        - 终态（done/pushed）→ 403「终态不可设置预算覆盖」
        - 成功 → 200 + {ok: true, budget: <值|null>}（null 清除覆盖，恢复跟随全局）
        修改只写覆盖属性，不触碰 _impl_run_budget_used（对账组件管辖）。

        open-impl-budget-ceiling：上限改由 agents.impl_run_budget_max 决定
        （缺省 100），不再硬编码 10；set_spec_budget 内部做同源权威校验。
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        body = self._read_json_body()
        if body is None:
            return
        if "budget" not in body:
            self._error(400, "budget required in request body (int or null)")
            return
        budget = body["budget"]
        proot = Path(project["path"])
        # 非整数（含 bool、浮点、字符串数字）拒绝——null 合法（清除覆盖）
        if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int)):
            self._error(400, "budget must be an integer >= 1 (or null to clear)")
            return
        try:
            result = dashboard_data.set_spec_budget(proot, spec, budget)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            _internal_error(self, "set spec budget failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "终态不可设置预算覆盖")
            return
        if result.get("invalid"):
            self._error(400, result.get("error") or "budget out of range")
            return
        self._json(
            {"ok": True, "project": project["name"], "spec": spec, "budget": result.get("budget")}
        )


    def _api_spec_archive(self, query) -> dict | None:
        """POST /api/spec-archive?project=<name>&spec=<name>

        归档终态 SPEC：把 spec/changes/<name>/ 移到 archive/YYYY-MM-DD-<name>/，
        归档成功后 STATE.md 条目即迁出至归档清单（archived_by=ui，与
        fenix_archive.py / fenix-archive skill 同语义）；迁出失败降级为响应中
        的 evict_warning 告警字段，不回滚目录移动。
        - project 不存在 → 404
        - spec 不在 STATE.md → 404
        - 非终态（非 done/pushed）→ 403「仅终态可归档」
        - 目标已存在 → 409（不覆盖）
        - 已归档（活跃目录缺失）→ 409「已归档」
        - 成功 → 200 + {ok: true, from, to, state_evicted[, evict_warning]}
          + 记录项目活动事件（from→to）
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.archive_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：移动异常不崩溃进程
            _internal_error(self, "archive spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if not result.get("ok"):
            # 已归档或目标冲突 → 409，非终态拒绝也走这里（按数据层结构化标志分流，
            # 不依赖 error 展示文案）
            code = (
                409
                if result.get("conflict") or result.get("archived_already")
                else 403
            )
            self._error(code, result.get("error") or "归档失败")
            return
        # 归档成功 → 记录项目活动事件（归档动作 from→to，供活动页/概览展示）
        try:
            dashboard_data.record_project_event(
                proot,
                "dashboard",
                f"Spec '{spec}' 已归档: {result['from']} → {result['to']}",
                context={"spec": spec, "from": result["from"], "to": result["to"]},
            )
        except Exception:
            pass  # 写日志失败不阻断归档响应
        # 归档成功日志含迁出结果（add-archive-state-migration 2.2）
        logger.info(
            "spec archive: project=%s spec=%s to=%s evicted=%s evict_warning=%s",
            project["name"],
            spec,
            result["to"],
            result.get("state_evicted", False),
            result.get("evict_warning"),
        )
        resp = {
            "ok": True,
            "project": project["name"],
            "spec": spec,
            "from": result["from"],
            "to": result["to"],
            "committed": result.get("committed", False),
            # 迁出结果透传（2.2）：迁出成功为 True，失败降级为 evict_warning
            "state_evicted": result.get("state_evicted", False),
        }
        if result.get("evict_warning"):
            resp["evict_warning"] = result["evict_warning"]
        if result.get("commit_warning"):
            resp["commit_warning"] = result["commit_warning"]
        self._json(resp)


    def _api_spec_promote(self, query) -> dict | None:
        """POST /api/spec-promote?project=<name>&spec=<name>

        人工晋升 drafted SPEC：调用共享晋升函数（软化+lint+transition ready）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 非 drafted → 200 + {ok: false, reason: ...}
        - lint 违规 → 200 + {ok: false, violations: [...]}
        - 成功 → 200 + {ok: true}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.promote_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：晋升异常不崩溃进程
            _internal_error(self, "promote spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        self._json(result)


    def _api_spec_task_reflow(self, query) -> dict | None:
        """POST /api/spec-task-reflow?project=<name>&spec=<name>

        task-gap 滞留 verified SPEC 的人工回炉：把因 verified→done 任务完成度
        门禁（_task_completion_blocker）拦截而停在 verified 的 SPEC 复位为 ready，
        供 daemon 重新派发实现者承接剩余任务（fix-impl-tasks-completion-gate P1′/D8）。

        判定与执行收敛到 core/pm_engine/task_reflow.reflow_spec 单一实现点——
        本路由只做参数解析与结果呈现（CLI reflow 子命令同源，MUST NOT 复写判定）。

        错误语义对齐 spec-error-clear / spec-freeze-config / spec-budget 家族：
        - project 不存在 → 404；spec 不在 STATE.md → 404
        - 不满足开放条件（非 verified / error 非 task-gap 前缀 / 冻结态 / 幂等重复）
          → 200 + {ok: false, reason: <明确拒绝原因>}
        - 成功 → 200 + {ok: true, spec, status: "ready"}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.reflow_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：回炉异常不崩溃进程
            _internal_error(self, "spec task reflow failed", e)
            return
        if not result.get("found"):
            # 与家族同口径先读 error 键；reflow 数据层（admin_actions 包装 +
            # task_reflow 单一实现点，CLI 同源）not-found 契约键是 reason
            # （item fa27e47b8a4d），故保留 reason 兜底，不改数据层词表。
            self._error(
                404,
                result.get("error") or result.get("reason") or f"spec not found: {spec}",
            )
            return
        self._json(result)


    def _api_spec_re_review(self, query) -> dict | None:
        """POST /api/spec-re-review?project=<name>&spec=<name>

        重新评审 blocked SPEC：复核开放条件后执行 blocked → reviewing 并派发新评审
        （add-spec-review-gate D8：重新评审入口仅对 error 前缀 spec-review-* 且
        未冻结的 blocked SPEC 开放；不符合条件 STATE 零变更）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 不符合开放条件（非 blocked / 非评审前缀 / 冻结 / 转移失败）→ 400
          + {ok: false, error: 明确原因}
        - 成功 → 200 + {ok: true, project, spec}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.re_review_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：重新评审异常不崩溃进程
            _internal_error(self, "re-review spec failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if not result.get("ok"):
            self._error(400, result.get("error") or "重新评审条件不满足")
            return
        self._json({"ok": True, "project": project["name"], "spec": spec})


    def _api_spec_approve_push(self, query):
        """POST /api/spec-approve-push?project=<name>&spec=<name>

        审批推送 done SPEC：写入 .fenix/approve_push_request.json 文件信号，
        由 daemon 主循环下一轮（≤2s）拾取并调 pm_engine.approve_push 执行推送。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - daemon 未运行 → 409「daemon 未运行，请先启动 daemon」（信号无人消费）
        - 已有未消费信号 → 409「已有进行中的审批推送请求」
        - spec 非 done → 403（pushed 幂等无操作、其他状态非法，error 区分）
        - 成功 → 200 + {ok: true, project, spec, created}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_spec_approve_push(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            _internal_error(self, "spec approve push request failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if result.get("unmanaged"):
            # 先于 conflict 判定：托管链断了（unmanaged）与已有请求在途（conflict）
            # 是两种不同的失败，便于用户区分处置
            self._error(409, result.get("error") or "本项目 daemon 未受 supervisor 托管")
            return
        if result.get("daemon_down"):
            self._error(409, result.get("error") or "daemon 未运行，请先启动 daemon")
            return
        if result.get("conflict"):
            self._error(409, result.get("error") or "已有进行中的审批推送请求")
            return
        if result.get("terminal"):
            self._error(403, result.get("error") or "仅 done 状态可审批推送")
            return
        self._json(
            {"ok": True, "project": project["name"], "spec": spec, "created": result.get("created")}
        )


    def _api_spec_delete(self, query):
        """POST /api/spec-delete?project=<name>&spec=<name>

        软删除 SPEC：STATE.md 移除条目 + SPEC 目录移入 spec/archive。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404（幂等，不发文件操作）
        - spec 有进行中的运行（末行非终态判定，含 frozen-terminated）→
          异步受理：写 spec_delete_request.json 信号 → 202 受理结果
          {accepted: true, stopping: N}（daemon 消费：停 agent → 有界等待
          终态 → 软删除）；无在跑 agent 时保持既有同步软删除。
        - 托管态非 managed / 已有未消费信号 → 409（信号无人消费/重复受理）
        - 成功 → 200 + {ok: true, archived, archive_path}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        proot = Path(project["path"])
        # ── 异步受理分支（add-freeze-stop-inflight-agents 5.1）──
        # 先取该 spec 的在跑 run：无在跑 → 既有同步软删除；有在跑 →
        # 写 spec_delete_request.json 信号立即返回受理（不阻塞等待终止）。
        try:
            running_ids = dashboard_data.running_run_ids_for_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：在跑 run 读取异常不崩溃进程
            _internal_error(self, "delete spec failed", e)
            return
        if running_ids:
            try:
                req = dashboard_data.request_spec_delete(
                    proot, spec, stopping=len(running_ids))
            except Exception as e:  # noqa: BLE001 兜底：信号写入异常不崩溃进程
                _internal_error(self, "delete spec failed", e)
                return
            if req.get("unmanaged"):
                self._error(409, req.get("error") or "daemon 未托管")
                return
            if req.get("daemon_down"):
                self._error(409, req.get("error") or "daemon 未运行")
                return
            if req.get("conflict"):
                self._error(409, req.get("error") or "已有进行中的删除请求")
                return
            if not req.get("ok"):
                self._error(409, req.get("error") or "删除请求写入失败")
                return
            # 202 受理：请求已受理，正在停止 N 个进行中的 agent
            self._json(
                {
                    "ok": True,
                    "accepted": True,
                    "project": project["name"],
                    "spec": spec,
                    "stopping": len(running_ids),
                    "created": req.get("created"),
                },
                status=202,
            )
            return
        try:
            result = dashboard_data.soft_delete_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回/移动异常不崩溃进程
            _internal_error(self, "delete spec failed", e)
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        if result.get("running"):
            self._error(409, result.get("error") or "spec 有进行中的运行")
            return
        self._json(
            {
                "ok": True,
                "project": project["name"],
                "spec": spec,
                "archived": result.get("archived", False),
                "archive_path": result.get("archive_path"),
            }
        )


    def _api_spec_admin_invoke(self, query):
        """POST /api/spec-admin-invoke?project=<name>&spec=<name>

        手动唤起 Administrator：写入 .fenix/admin_invoke_request.json 文件信号，
        由 daemon 主循环下一轮扫描拾取并唤起。
        - project 不存在 → 404
        - spec 不在项目 STATE.md → 404
        - 已有未消费请求（进行中处置）→ 409「已有进行中的 Admin 处置」
        - 成功 → 200 + {ok: true, created}
        """
        resolved = self._spec_query_or_error(query)
        if resolved is None:
            return
        project, spec = resolved
        # 用户提示词（可选，POST JSON body {prompt}）：v1 客户端不带 body 仍兼容
        prompt = None
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            # 报文分帧已不可解析，且 _drain_remaining_request_body 里同一处
            # int() 同样失败得 remaining=0 跳过排空，客户端已发出的 body 字节
            # 会残留 keep-alive 连接被下一请求当请求行。比照
            # base._read_json_body（code-review item 8beb499acc56）置
            # close_connection=True 后按无 body 继续执行，让残留字节随连接
            # 关闭作废。
            content_length = 0
            # [fenix-ignore:1697e582073c] 防御写法正确，作为本文件可选 body 解析样板保留（溯源 8beb499acc56）
            self.close_connection = True
        if content_length > 0:
            body = self._read_json_body()
            if body is None:
                # _read_json_body 失败路径已自行 _error(400/413)，必须终止，
                # 否则继续执行会向同一 keep-alive 连接写第二个响应（与
                # _api_spec_priority 等端点的使用惯例对齐）
                return
            if isinstance(body, dict):
                raw = body.get("prompt")
                if raw is not None and not isinstance(raw, str):
                    self._error(400, "prompt must be a string")
                    return
                prompt = (raw or "").strip() or None
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_admin_invoke(proot, spec, prompt)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            _internal_error(self, "admin invoke request failed", e)
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        if result.get("conflict"):
            self._error(409, result.get("error") or "已有进行中的 Admin 处置")
            return
        self._json(
            {"ok": True, "project": project["name"], "spec": spec, "created": result.get("created")}
        )

