"""spec_routes.py — H3 spec management。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.dashboard import data as dashboard_data
from core.dashboard.registry import Registry


class H3SpecRoutesMixin:
    """H3 spec management。"""

    def _api_specs(self, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project", "specs": []}
        if not project.get("exists"):
            return {"error": "project not found", "specs": []}
        proot = Path(project["path"])
        items = self.server.summary_index.get(proot)
        items.sort(key=lambda s: s.get("created") or "", reverse=True)
        return {"project": project["name"], "specs": items}


    def _api_spec_detail(self, spec: str, query) -> dict:
        project = self._project_from_query(query)
        if project is None:
            return {"error": "unknown project"}
        if not project.get("exists"):
            return {"error": "project not found"}
        proot = Path(project["path"])
        specs = dashboard_data.parse_state(proot)
        entry = specs.get(spec)
        if entry is None:
            return {"error": f"spec not found: {spec}", "project": project["name"]}
        detail = dashboard_data.spec_detail(proot, spec, entry)
        detail["project"] = project["name"]
        return detail


    def _api_spec_doc(self, query) -> dict:
        """GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>

        读取 SPEC 的 proposal.md / design.md / tasks.md 原文返回 {found, content}。
        - doc 非法 → 400
        - spec 非法 / 不在项目 STATE.md → 404（且不读取任何 changes 目录外文件）
        - 文件不存在 → 200 + {found: false, content: ""}
        """
        doc = query.get("doc", [None])[0]
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        # 文件缺失是常态分支，但 spec 必须真在项目 STATE.md 中（D2：仅未知 spec 才 404）
        proot = Path(project["path"])
        specs = dashboard_data.parse_state(proot)
        if spec not in specs:
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


    def _api_spec_error_clear(self, query) -> dict:
        """POST /api/spec-error-clear?project=<name>&spec=<name>

        在线清除 SPEC 的 error 字段（置空并原子写回 STATE.md）。
        - project 不存在 → 404
        - spec 非法 / 不在项目 STATE.md → 404
        - spec 处于冻结态 → 409「清除错误会连带解除冻结，请先解冻」
          （item babdab6b010b：对齐 freeze-config 家族 409 拒绝语义）
        - 成功 → 200 + {ok: true}；其余字段不受影响
        - 写回异常 → 500
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.clear_spec_error(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"clear spec error failed: {e}")
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        body = self._read_json_body()
        if body is None:
            return
        if "priority" not in body:
            self._error(400, "priority required in request body")
            return
        # bool 显式拒绝（与 spec-budget 端点同口径）——int(True) 会静默转 1 被当作 P1
        if isinstance(body["priority"], bool):
            self._error(400, "priority must be an integer between 1 and 9")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.set_spec_priority(proot, spec, body["priority"])
        except dashboard_data.InvalidPriority:
            self._error(400, "priority must be an integer between 1 and 9")
            return
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"set spec priority failed: {e}")
            return
        if not result.get("found"):
            self._error(404, f"spec not found: {spec}")
            return
        self._json(
            {"ok": True, "project": project["name"], "spec": spec, "priority": result["priority"]}
        )


    def _api_spec_freeze(self, query) -> dict:
        """POST /api/spec-freeze?project=<name>&spec=<name>

        人工冻结 SPEC：status→blocked，error 以「用户指令冻结：」开头
        （admin_monitor 认此模式为有意等待态，免超时误报）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 终态（done/pushed）→ 200 + {ok: true, frozen: false, error: 原因}
        - 成功 → 200 + {ok: true, frozen: true, stopped_agents: N}（N 为
          冻结时刻在跑 agent 计数，add-freeze-stop-inflight-agents BUG-01
          修复；前端据 >0 展示「已停止 N 个在跑 agent」提示）
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        try:
            result = dashboard_data.freeze_spec(Path(project["path"]), spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"freeze spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)


    def _api_spec_unfreeze(self, query) -> dict:
        """POST /api/spec-unfreeze?project=<name>&spec=<name>

        解冻 SPEC：恢复冻结前状态并清空 error；未冻结为幂等 no-op。
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        try:
            result = dashboard_data.unfreeze_spec(Path(project["path"]), spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"unfreeze spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or "spec not found")
            return
        self._json(result)


    def _api_spec_start_after(self, query) -> dict:
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
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
            self._error(500, f"set spec start_after failed: {e}")
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


    def _api_spec_activate(self, query) -> dict:
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.activate_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"activate spec failed: {e}")
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


    def _api_spec_resume(self, query) -> dict:
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.resume_cancelled_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写回异常不崩溃进程
            self._error(500, f"resume spec failed: {e}")
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


    def _api_spec_freeze_config(self, query) -> dict:
        """POST /api/spec-freeze-config?project=<name>&spec=<name>
        body: {"mode": "permanent"|"scheduled"|"unfreeze", "until": "<iso-utc>"?}

        冻结管理配置：永久 ↔ 定时解冻 ↔ 立即解冻。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - spec 未处于冻结态 → 409「冻结管理仅对冻结 spec 生效」
        - mode 非法 / scheduled 的 until 非法 ISO8601 → 400
        - 成功 → 200 + {ok: true, mode, frozen_until, unfrozen?}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
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
            self._error(500, f"configure spec freeze failed: {e}")
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


    def _api_spec_budget(self, query) -> dict:
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
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
            self._error(500, f"set spec budget failed: {e}")
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


    def _api_spec_archive(self, query) -> dict:
        """POST /api/spec-archive?project=<name>&spec=<name>

        归档终态 SPEC：把 spec/changes/<name>/ 移到 archive/YYYY-MM-DD-<name>/，
        STATE.md 条目原样保留（与 fenix_archive.py / fenix-archive skill 同语义）。
        - project 不存在 → 404
        - spec 不在 STATE.md → 404
        - 非终态（非 done/pushed）→ 403「仅终态可归档」
        - 目标已存在 → 409（不覆盖）
        - 已归档（活跃目录缺失）→ 409「已归档」
        - 成功 → 200 + {ok: true, from, to} + 记录项目活动事件（from→to）
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.archive_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：移动异常不崩溃进程
            self._error(500, f"archive spec failed: {e}")
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
        resp = {
            "ok": True,
            "project": project["name"],
            "spec": spec,
            "from": result["from"],
            "to": result["to"],
            "committed": result.get("committed", False),
        }
        if result.get("commit_warning"):
            resp["commit_warning"] = result["commit_warning"]
        self._json(resp)


    def _api_spec_promote(self, query) -> dict:
        """POST /api/spec-promote?project=<name>&spec=<name>

        人工晋升 drafted SPEC：调用共享晋升函数（软化+lint+transition ready）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 非 drafted → 200 + {ok: false, reason: ...}
        - lint 违规 → 200 + {ok: false, violations: [...]}
        - 成功 → 200 + {ok: true}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.promote_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：晋升异常不崩溃进程
            self._error(500, f"promote spec failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("error") or f"spec not found: {spec}")
            return
        self._json(result)


    def _api_spec_task_reflow(self, query) -> dict:
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.reflow_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：回炉异常不崩溃进程
            self._error(500, f"spec task reflow failed: {e}")
            return
        if not result.get("found"):
            self._error(404, result.get("reason") or f"spec not found: {spec}")
            return
        self._json(result)


    def _api_spec_re_review(self, query) -> dict:
        """POST /api/spec-re-review?project=<name>&spec=<name>

        重新评审 blocked SPEC：复核开放条件后执行 blocked → reviewing 并派发新评审
        （add-spec-review-gate D8：重新评审入口仅对 error 前缀 spec-review-* 且
        未冻结的 blocked SPEC 开放；不符合条件 STATE 零变更）。
        - project 不存在 → 404；spec 不在项目 STATE.md → 404
        - 不符合开放条件（非 blocked / 非评审前缀 / 冻结 / 转移失败）→ 400
          + {ok: false, error: 明确原因}
        - 成功 → 200 + {ok: true, project, spec}
        """
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.re_review_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：重新评审异常不崩溃进程
            self._error(500, f"re-review spec failed: {e}")
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        try:
            result = dashboard_data.request_spec_approve_push(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：写文件异常不崩溃进程
            self._error(500, f"spec approve push request failed: {e}")
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        proot = Path(project["path"])
        # ── 异步受理分支（add-freeze-stop-inflight-agents 5.1）──
        # 先取该 spec 的在跑 run：无在跑 → 既有同步软删除；有在跑 →
        # 写 spec_delete_request.json 信号立即返回受理（不阻塞等待终止）。
        try:
            running_ids = dashboard_data.running_run_ids_for_spec(proot, spec)
        except Exception as e:  # noqa: BLE001 兜底：在跑 run 读取异常不崩溃进程
            self._error(500, f"delete spec failed: {e}")
            return
        if running_ids:
            try:
                req = dashboard_data.request_spec_delete(
                    proot, spec, stopping=len(running_ids))
            except Exception as e:  # noqa: BLE001 兜底：信号写入异常不崩溃进程
                self._error(500, f"delete spec failed: {e}")
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
            self._error(500, f"delete spec failed: {e}")
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
        spec = query.get("spec", [None])[0]
        project = self._project_from_query(query)
        if project is None:
            self._error(404, "unknown project")
            return
        if not project.get("exists"):
            self._error(404, "project not found")
            return
        if not spec:
            self._error(404, "spec required")
            return
        # 用户提示词（可选，POST JSON body {prompt}）：v1 客户端不带 body 仍兼容
        prompt = None
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            content_length = 0
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
            self._error(500, f"admin invoke request failed: {e}")
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

