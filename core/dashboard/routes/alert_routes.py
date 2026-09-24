"""alert_routes.py — H6 alerts/admin-activities。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D5 约定：各组方法采用 mixin 模式，DashboardHandler 继承各组 mixin。
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from core.dashboard import data as dashboard_data

logger = logging.getLogger("fenixd.dashboard.alert_routes")

# alert-resolve 复合序列的 per-alert 串行化锁（code-review item 3c57cd9db3e8）：
# handler 跑在 ThreadingHTTPServer（最多 64 并发线程）上，而「handled 快照检查 →
# 执行映射动作 → mark handled」是复合序列，AdminStore 的锁/flock 只串行化单次
# 写入——两个同告警并发 POST（如双击）可同时通过检查、把动作执行两遍
#（double abandon / force_advance / raise_budget 预算翻两倍）并落重复
# DISPOSITION 留痕。dashboard 为单进程，进程内 per-alert_id 锁即足够：
# 同告警的第二请求阻塞到第一请求完成 mark 后再读快照，命中 409 不重复执行。
_ADJUDICATION_LOCKS_GUARD = threading.Lock()
_ADJUDICATION_LOCKS: dict = {}


def _adjudication_lock(alert_id: str) -> threading.Lock:
    """按 alert_id 取（懒建）进程内互斥锁；字典只在告警裁决时增长，量级有限。"""
    with _ADJUDICATION_LOCKS_GUARD:
        lock = _ADJUDICATION_LOCKS.get(alert_id)
        if lock is None:
            lock = threading.Lock()
            _ADJUDICATION_LOCKS[alert_id] = lock
        return lock


class H6AlertRoutesMixin:
    """H6 alerts/admin-activities。"""

    def _api_alerts(self, query) -> dict:
        """读取 Administrator 告警。

        ?project=<name> → 该项目全部告警/处置记录 + 摘要；
        缺省 → 跨项目聚合所有未处理升级告警（供顶部横幅），并附已解决
        告警（resolved，add-alert-auto-resolve D5 视图分组用）。

        错误契约为**有意 200**：?project 指向不存在/未就绪项目时返回
        ``{"error": "project not found"}`` 字典（HTTP 仍 200）——适配函数
        ``_get_alerts`` 是 ``_json(返回值)`` 包裹式，此处若改 ``self._error``
        直写会叠加第二响应（keep-alive 污染，同 base.py _get_prompts 注记），
        且 200+error 形态已被 test_api_alerts_unknown_project 钉住。与写路径
        （_api_alert_handled/_api_alert_resolve 的 _error(4xx) 直写）约定不同，
        本读路径调用方按 body.error 判错（前端 AlertBanner 即 ``if (!d.error)``）。
        """
        project_name = query.get("project", [None])[0]
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                return {"error": "project not found"}
            proot = Path(project["path"])
            return {
                "project": project["name"],
                "alerts": dashboard_data.get_alerts(proot),
                "summary": dashboard_data.alerts_summary(proot),
            }

        projects_out = []
        all_unhandled = []
        all_resolved = []
        total = 0
        for p in self.server.projects():
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具项目告警为验证噪音，不进人工聚合
            if not p.get("exists"):
                continue
            proot = Path(p["path"])
            summary = dashboard_data.alerts_summary(proot)
            projects_out.append({"name": p["name"], **summary})
            total += summary["unhandled_count"]
            for a in dashboard_data.get_unhandled_alerts(proot):
                item = dict(a)
                item["project"] = p["name"]
                all_unhandled.append(item)
            # add-alert-auto-resolve D5：已解决告警随横幅 payload 下发，
            # 前端折叠为「已解决 (N)」区（按 handled_by 区分自动解决/人工处理）
            for a in dashboard_data.get_resolved_alerts(proot):
                item = dict(a)
                item["project"] = p["name"]
                all_resolved.append(item)
        all_unhandled.sort(key=lambda a: a.get("created", ""), reverse=True)
        all_resolved.sort(key=lambda a: a.get("handled_at") or a.get("created") or "", reverse=True)
        return {
            "total_unhandled": total,
            "projects": projects_out,
            "alerts": all_unhandled,
            "resolved": all_resolved,
        }


    def _api_admin_activities(self, query) -> dict:
        """读取 Administrator 活动记录（运维记录时间线）。

        ?project=<name> → 该项目全部处置活动（未处理升级关联置顶）；
        带 ?spec=<name> → 仅返回该 SPEC 相关记录（add-admin-invoke-dialog，
        服务端过滤）；缺省 → 跨项目聚合，按项目分组返回。

        错误契约同 _api_alerts（**有意 200**）：?project 不存在/未就绪时返回
        ``{"error": "project not found"}`` 字典——适配函数
        ``_get_admin_activities`` 为 _json 包裹式，不能改 self._error 直写
        （会双重写响应），调用方按 body.error 判错。
        """
        project_name = query.get("project", [None])[0]
        spec_name = query.get("spec", [None])[0]
        if project_name:
            project = self.server.project_by_name(project_name)
            if project is None or not project.get("exists"):
                return {"error": "project not found"}
            proot = Path(project["path"])
            return {
                "project": project["name"],
                "spec": spec_name or "",
                "activities": dashboard_data.get_admin_activities(proot, spec=spec_name),
            }

        projects_out = []
        for p in self.server.projects():
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具项目处置记录不进人工聚合视图
            if not p.get("exists"):
                continue
            acts = dashboard_data.get_admin_activities(Path(p["path"]), spec=spec_name)
            for a in acts:
                a["project"] = p["name"]
            projects_out.append({"name": p["name"], "activities": acts})
        return {"projects": projects_out}


    def _api_alert_handled(self, alert_id: str, query) -> None:
        """标记某条告警为已处理；成功后广播让前端横幅刷新。

        kind 分派在 ``mark_alert_handled``（ESCALATION→mark_handled，
        SIGNAL→mark_signal_handled）：不可裁决 SIGNAL 记录（alert-resolve
        400 文案指引本路径，code-review item 08f4820799eb）亦可经此闭环。
        注解 ``-> None``：全部路径经 ``self._error``/``self._json`` 直写
        响应、不返回值（code-review item dc1b749f1743）。
        """
        project = self._project_from_query(query)
        if project is None:
            self._error(400, "unknown project")
            return
        if not project.get("exists"):
            self._error(400, "project not found")
            return
        if not alert_id:
            self._error(400, "missing alert id")
            return
        # 与 alert-resolve 共用同一把 per-alert 锁（code-review item 459f38a3f141）：
        # mark 若不持锁，可在 resolve 持锁通过 409 快照检查、正执行映射动作的窗口
        # 内插入把告警标记 handled，令 resolve 仍把动作执行完——「已 handled 告警
        # 不执行动作」的不变量被破坏。收敛到同锁后两个方向均串行化：本路径先抢到
        # 锁则 resolve 后读快照命中 409；resolve 先完成则本路径 mark 幂等返回
        # False（404 如实上报）。mark_alert_handled 内部只走 store 级锁，无重入。
        with _adjudication_lock(alert_id):
            if not dashboard_data.mark_alert_handled(Path(project["path"]), alert_id):
                self._error(404, "alert not found or already handled")
                return
        try:
            self.server.sse_hub.broadcast(
                {
                    "project": project["name"],
                    "type": "alerts",
                    "summary": dashboard_data.alerts_summary(Path(project["path"])),
                }
            )
        except Exception as e:
            # 广播失败留痕（code-review item 95ab3853f55d）：旧 `except: pass`
            # 把（含 payload 形态错误等编程错误的）一切失败静默吞掉，持续失败的
            # 广播无迹可查。降级为 WARNING 不阻断已成功的处置动作。
            logger.warning("SSE 广播失败（告警已处置，横幅可能滞后）: %s", e)
        self._json({"ok": True, "id": alert_id})


    def _api_alert_resolve(self, query) -> None:
        """POST /api/alert-resolve — 人工裁决一次选择完成处置闭环（4.1）。

        body ``{project, alert_id, choice_id, note?}``。按序：
        (1) 校验告警存在且未 handled，按 alert ``signal_type`` 从注册表校验
        ``choice_id`` 合法（记录内 choices 优先，缺失回退注册表；不可裁决
        信号合法集为空 → 直接 400，不放行执行器的注册表级反查）；(2) 执行
        choice 映射动作（``execute_adjudication_choice`` 共享执行器）；(3)
        标记告警 handled（ESCALATION 走 ``mark_handled``，SIGNAL 走
        ``mark_signal_handled``）并落 DISPOSITION 处置留痕（choice_id/note/
        动作步骤摘要）；(4) SSE 广播刷新横幅。

        (1)→(3) 全程持有 per-alert 进程内锁（code-review item 3c57cd9db3e8）：
        handler 跑在 ThreadingHTTPServer 上，store 锁只串行化单次写入，不锁
        复合序列——不串行化则同告警并发 POST 可双双通过 handled 快照检查、
        把动作执行两遍。任一步失败返回结构化错误且不标记 handled；已执行的
        前序动作在错误信息中如实报告（不做虚假回滚声明）。注解 ``-> None``：
        全部路径经 ``self._error``/``self._json`` 直写响应、不返回值
        （code-review item 5df694db80ea）。
        """
        project_name = (query.get("project", [None])[0]) or None
        body = self._read_json_body()
        if body is None:
            return
        alert_id = str(body.get("alert_id") or "").strip()
        choice_id = str(body.get("choice_id") or "").strip()
        note = str(body.get("note") or "")
        if not project_name:
            project_name = str(body.get("project") or "").strip()
        if not project_name:
            self._error(400, "missing project")
            return
        project = self.server.project_by_name(project_name)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        if not alert_id or not choice_id:
            self._error(400, "alert_id and choice_id are required")
            return
        proot = Path(project["path"])

        from core.admin_store import AdminStore, DISPOSITION, SIGNAL
        from core.dashboard.data.adjudication_choices import choices_for

        # check(handled 快照)→execute→mark 全程串行化（见 docstring）
        with _adjudication_lock(alert_id):
            store = AdminStore(proot, logger)
            alert = next((r for r in store.read_all() if r.get("id") == alert_id), None)
            if alert is None:
                self._error(404, "alert not found")
                return
            if alert.get("handled"):
                self._error(409, "alert already handled（不重复执行动作）")
                return

            signal_type = str(alert.get("signal_type") or "")
            spec = str(alert.get("spec") or "")
            # choice 合法性：记录内 choices 优先（发射点快照），缺失回退注册表。
            # 合法集为空（不可裁决信号：桶 0/自愈类、signal_type 缺失——
            # choices_for() 返回空元组且记录无快照）→ 直接 400 拒绝（code-review
            # item 14b854aeccf9）：此前的空集直通会让 execute_adjudication_choice
            # 的注册表级反查接受任意已注册 choice_id（含 abandon/force_advance/
            # skip_review_gate 等破坏性动词）执行到本告警 spec 上，与端点契约相悖。
            record_choices = alert.get("choices") or choices_for(signal_type)
            valid_ids = [c.get("id") for c in record_choices if isinstance(c, dict)]
            if not valid_ids:
                self._error(
                    400,
                    f"该告警不可人工裁决（signal_type={signal_type or '缺失'}，无合法 "
                    "choice 集）：知情/自愈类信号请用「标记已处理」完成处置",
                )
                return
            if choice_id not in valid_ids:
                legal = "、".join(
                    f"{c.get('id')}({c.get('label')})"
                    for c in record_choices
                    if isinstance(c, dict)
                )
                self._error(400, f"非法 choice_id '{choice_id}'，该信号合法选项：{legal}")
                return

            # 执行映射动作（共享执行器：与 Administrator 处置消费同一路径）
            try:
                result = dashboard_data.execute_adjudication_choice(
                    proot, spec, choice_id, note=note, signal_type=signal_type
                )
            except Exception as e:  # 动作执行异常：不标记 handled，如实报告
                logger.exception("alert-resolve 动作执行异常 alert=%s", alert_id)
                self._error(500, f"动作执行异常: {e}（告警保持未处理，可重试裁决）")
                return
            steps = result.get("steps") or []
            if not result.get("ok"):
                self._error(
                    400,
                    f"{result.get('error') or '动作未成功执行'}"
                    + (f"（已执行步骤：{'；'.join(steps)}）" if steps else "")
                    + "（告警保持未处理，可调整后重试）",
                )
                return

            # handled 标记：kind 差异约定（ESCALATION→mark_handled，
            # SIGNAL→mark_signal_handled 直接更新 handled 字段）
            marked = (
                store.mark_signal_handled(alert_id)
                if alert.get("kind") == SIGNAL
                else store.mark_handled(alert_id)
            )

            # 处置留痕：DISPOSITION 记录（choice_id/note/动作步骤摘要，
            # 对 dashboard admin 活动区可见，作为裁决审计轨迹）
            disposition_logged = False
            try:
                store.append(
                    {
                        "kind": DISPOSITION,
                        "signal_type": signal_type or None,
                        "spec": spec or None,
                        "severity": alert.get("severity"),
                        "description": alert.get("description"),
                        "action_taken": "；".join(steps),
                        "result": "success",
                        "recommended_action": "",
                        "summary": f"人工裁决 {choice_id}（{result.get('action')}）"
                        + (f"：{note}" if note else ""),
                        "choice_id": choice_id,
                        "note": note,
                        "source": "alert-resolve",
                        "error": "",
                    }
                )
                disposition_logged = True
            except Exception as e:
                # 留痕失败不回滚已执行的动作与 handled 标记，如实告知
                #（结果经 disposition_logged 下发，前端不再假称「留痕已写入」，
                # code-review item 896c7e54dafd）
                logger.warning("alert-resolve 处置留痕写入失败 alert=%s: %s", alert_id, e)

        try:
            self.server.sse_hub.broadcast(
                {
                    "project": project["name"],
                    "type": "alerts",
                    "summary": dashboard_data.alerts_summary(proot),
                }
            )
        except Exception as e:
            logger.warning("SSE 广播失败（告警已处置，横幅可能滞后）: %s", e)
        self._json(
            {
                "ok": True,
                "id": alert_id,
                "choice_id": choice_id,
                "action": result.get("action"),
                "steps": steps,
                "marked": bool(marked),
                "disposition_logged": disposition_logged,
                "note": note,
            }
        )

    def _api_alerts_clear(self):
        """清理所有事件：把全部项目未处理升级告警标记为已处理；逐项目广播刷新横幅。

        与 `_api_alerts` / `_api_admin_activities` 一致地**跳过 fixture 项目**
        （code-review item cb7a35748089）：夹具告警为验证噪音、本就不进人工聚合
        视图，但旧实现仍对其 mark_all_alerts_handled 并广播其摘要——用户「清理
        可见横幅」会静默改写隐藏的夹具状态，且破坏夹具 reset 契约（夹具告警
        只应经 bin/fixture_scheduling_showcase.py --reset 复位）。
        """
        cleared = 0
        for p in self.server.projects():
            if p.get("fixture"):
                continue  # fixture-project-governance：夹具告警只经 --reset 复位
            if not p.get("exists"):
                continue
            proot = Path(p["path"])
            # 与 _api_alert_handled / alert-resolve 同一 per-alert 锁口径
            # （code-review item 05bbe3368891）：mark_all_alerts_handled 内部
            # 只走 store 级锁，可在 resolve 持锁通过 409 快照检查、正执行映射
            # 动作的窗口内把告警插入标记 handled，令 resolve 仍把 abandon/
            # force_advance 等动作执行完（不变量见 _api_alert_handled 处注释）。
            # 先取未处理告警 id，逐个持 _adjudication_lock 后再标记：本路径先
            # 抢到锁则 resolve 后读快照命中 409 不执行动作；resolve 先完成则
            # mark 幂等返回 False 不计数。
            for alert in dashboard_data.get_unhandled_alerts(proot):
                alert_id = str(alert.get("id") or "")
                if not alert_id:
                    continue
                with _adjudication_lock(alert_id):
                    if dashboard_data.mark_alert_handled(proot, alert_id):
                        cleared += 1
            try:
                self.server.sse_hub.broadcast(
                    {
                        "project": p["name"],
                        "type": "alerts",
                        "summary": dashboard_data.alerts_summary(proot),
                    }
                )
            except Exception as e:
                # 广播失败留痕（code-review item 95ab3853f55d），同 _api_alert_handled。
                logger.warning(
                    "SSE 广播失败（告警已清理，横幅可能滞后）: %s", e
                )
        self._json({"ok": True, "cleared": cleared})

