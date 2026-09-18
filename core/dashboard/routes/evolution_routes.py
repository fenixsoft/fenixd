"""evolution_routes.py — H7 evolution suggestions（refactor-giant-classes D1/D3/D5）。

原为 DashboardHandler 的路由方法（`core/dashboard/server.py`），
原样搬移为 mixin（方法体零改动）。

D3 patch 缝隙：`FRAMEWORK_ROOT` 常量仍定义在 `core.dashboard.server`
命名空间（测试 `monkeypatch.setattr(server_mod, "FRAMEWORK_ROOT", ...)`
patch 该命名空间属性）——本模块调用点 MUST 经 `core.dashboard.server`
命名空间**延迟解析**（不得顶部 import 绑定常量），否则重绑不生效。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.dashboard import data as dashboard_data
from core.dashboard.registry import Registry


class H7EvolutionRoutesMixin:
    """H7 evolution suggestions（design D1 表 C H7）。"""

    @staticmethod
    def _evolution_state_machine():
        """框架根 StateMachine（accept_item 注册用；惰性构造，无缓存需求）。"""
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        from core.state_machine import StateMachine

        return StateMachine(_server_mod.FRAMEWORK_ROOT / ".fenix" / "STATE.md", None)


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
            self._error(400, "缺少 item_id 参数")
            return
        result = dashboard_data.read_evolution_analysis(_server_mod.FRAMEWORK_ROOT, item_id)
        if result.get("not_found"):
            self._error(404, f"条目不存在: {item_id}")
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
            self._error(400, "缺少 item_id 参数")
            return
        if not doc:
            self._error(400, "缺少 doc 参数（proposal|design|tasks|spec）")
            return
        result = dashboard_data.read_evolution_draft(_server_mod.FRAMEWORK_ROOT, item_id, doc)
        if result.get("invalid_doc"):
            self._error(400, f"非法 doc 参数（应为 proposal|design|tasks|spec）: {doc}")
            return
        if result.get("not_found"):
            self._error(404, f"条目不存在: {item_id}")
            return
        self._json(result)


    def _api_evolution_accept(self):
        """POST /api/evolution/accept — body {item_id, start_after?} → 执行接受路径。

        成功返回 200 + {ok, status, spec_name}；缺参 400；未知条目 404。
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
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            self._error(400, "缺少 item_id 参数")
            return
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
                    self._error(400, f"start_after 非法（应为 UTC ISO8601 / manual）: {raw_start_after!r}")
                    return
                start_after = raw_start_after
        from core.evolution import accept_item

        try:
            result = accept_item(
                item_id,
                _server_mod.FRAMEWORK_ROOT,
                self._evolution_state_machine(),
                decided_by="manual",
                start_after=start_after,
            )
        except Exception as e:  # noqa: BLE001 —— 端点不因内部异常 500 崩溃
            self._error(500, f"接受失败: {e}")
            return
        if result.get("status") is None and result.get("error"):
            self._error(404, result["error"])
            return
        if not result.get("ok"):
            # 状态不允许 / 提交失败：200 + 错误信息（前端刷新回真实状态）
            self._json(result)
            return
        self._json(result)


    def _api_evolution_reject(self):
        """POST /api/evolution/reject — body {item_id} → 执行拒绝路径。

        成功返回 200 + {ok, status}；缺参 400；未知条目 404。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            self._error(400, "缺少 item_id 参数")
            return
        from core.evolution import reject_item

        try:
            result = reject_item(item_id, _server_mod.FRAMEWORK_ROOT)
        except Exception as e:  # noqa: BLE001
            self._error(500, f"拒绝失败: {e}")
            return
        if result.get("status") is None and result.get("error"):
            self._error(404, result["error"])
            return
        self._json(result)


    def _api_evolution_delete(self):
        """POST /api/evolution/delete — body {item_id} → 删除该条目（硬删）。

        成功返回 200 + {ok, status}；缺参 400；未知条目 404。
        硬删语义：记录移出 items.jsonl 且不写墓碑，todo.md 中同名记录会在下一轮
        分析 run 重新入库（前端确认弹窗已向用户明示）。
        """
        from core.dashboard import server as _server_mod  # noqa: E402 — D3 缝隙
        body = self._read_json_body()
        if body is None:
            return
        item_id = body.get("item_id")
        if not isinstance(item_id, str) or not item_id:
            self._error(400, "缺少 item_id 参数")
            return
        from core.evolution import delete_item

        try:
            result = delete_item(item_id, _server_mod.FRAMEWORK_ROOT)
        except Exception as e:  # noqa: BLE001
            self._error(500, f"删除失败: {e}")
            return
        if result.get("status") is None and result.get("error"):
            self._error(404, result["error"])
            return
        self._json(result)


    def _api_evolution_clear_todo(self):
        """POST /api/evolution/clear-todo — 清空**所有项目**的 .fenix/todo.md。

        全局动作，不接受 project 参数（逐个清理所有 discover 到且存在的项目）。
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
        for proj in self.server.registry.discover() or []:
            if not isinstance(proj, dict) or not proj.get("exists"):
                continue
            name = proj.get("name") or proj.get("path") or "?"
            path = proj.get("path")
            if not path:
                skipped.append({"project": name, "reason": "项目路径缺失"})
                continue
            result = clear_todo(path)
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

    # ── POST API ────────────────────────────────────────────


