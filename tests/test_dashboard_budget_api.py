"""add-spec-status-modal-budget API 测试（/api/spec-budget）。

覆盖 per-spec-impl-budget API Scenario 全分支：
- 200 设置/清除覆盖
- 400 缺键与非法值矩阵（0/11/字符串数字/浮点/bool/缺键）
- 404 spec 不存在 / 项目不存在
- 403 终态（done/pushed）拒绝
- STATE.md 只写覆盖属性、不动 _impl_run_budget_used
- spec_summary budget 字段随设置/清除联动
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conftest import _TestServer, make_project  # noqa: E402

from core.dashboard import data as dash_data  # noqa: E402
from core.dashboard.registry import Registry  # noqa: E402


class TestSpecBudgetAPI:
    """夹具 make_project：myspec=testing（非终态）、otherspec=done（终态）。"""

    def test_set_override_writes_and_effective(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=myspec",
            {"budget": 3},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["budget"] == 3
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("impl_run_budget_override") == 3

    def test_set_null_clears_override(self, server_fx):
        proot, srv = server_fx
        srv.post_json("/api/spec-budget?project=proj-a&spec=myspec", {"budget": 3})
        status, body = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=myspec",
            {"budget": None},
        )
        assert status == 200
        assert body["budget"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("impl_run_budget_override") is None

    @pytest.mark.parametrize("payload", [
        {"budget": 0},
        {"budget": 101},  # 超缺省上限 100（open-impl-budget-ceiling）
        {"budget": -1},
        {"budget": "5"},
        {"budget": True},
        {"budget": False},
        {"budget": 3.5},
        {},
    ])
    def test_invalid_budget_rejected_400(self, server_fx, payload):
        proot, srv = server_fx
        status, _ = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=myspec", payload)
        assert status == 400
        # STATE.md 不发生任何变化
        entry = dash_data.parse_state(proot)["myspec"]
        assert "impl_run_budget_override" not in entry

    def test_budget_11_now_accepted(self, server_fx):
        """open-impl-budget-ceiling：11 在旧上限(10)外，现缺省上限 100 内 → 接受。"""
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=myspec", {"budget": 11})
        assert status == 200
        assert body["budget"] == 11

    def test_spec_not_found_404(self, server_fx):
        _, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=nosuch", {"budget": 3})
        assert status == 404
        assert "not found" in (body.get("error") or "")

    def test_project_not_found_404(self, server_fx):
        _, srv = server_fx
        status, _ = srv.post_json(
            "/api/spec-budget?project=ghost&spec=myspec", {"budget": 3})
        assert status == 404

    def test_terminal_rejected_403(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=otherspec", {"budget": 3})
        assert status == 403
        entry = dash_data.parse_state(proot)["otherspec"]
        assert "impl_run_budget_override" not in entry
        assert entry.get("status") == "done"

    def test_override_does_not_touch_used(self, server_fx):
        proot, srv = server_fx
        # 预置 used=3（对账组件管辖字段，本 API 不得触碰）
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("myspec", {"_impl_run_budget_used": 3})
        status, _ = srv.post_json(
            "/api/spec-budget?project=proj-a&spec=myspec", {"budget": 8})
        assert status == 200
        entry = dash_data.parse_state(proot)["myspec"]
        assert int(entry.get("_impl_run_budget_used", 0)) == 3
        assert entry.get("impl_run_budget_override") == 8

    def test_specs_summary_budget_fields_follow(self, server_fx):
        proot, srv = server_fx
        # 先置覆盖
        srv.post_json("/api/spec-budget?project=proj-a&spec=myspec", {"budget": 8})
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        by_name = {s["name"]: s for s in data["specs"]}
        assert by_name["myspec"]["budget_override"] == 8
        assert by_name["myspec"]["budget_effective"] == 8
        assert by_name["myspec"]["budget_used"] == 0
        # 清除覆盖后恢复跟随全局
        srv.post_json("/api/spec-budget?project=proj-a&spec=myspec", {"budget": None})
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        by_name = {s["name"]: s for s in data["specs"]}
        assert by_name["myspec"]["budget_override"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])