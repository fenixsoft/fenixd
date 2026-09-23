"""
Tests for Dashboard server API functionality.

Split from test_dashboard.py as part of refactor-test-structure.
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 共享夹具已收敛至 tests/conftest.py（make_project / _TestServer / server_fx）
from conftest import _TestServer, make_project  # noqa: E402

from core.dashboard import data as dash_data
from core.dashboard.registry import Registry
from core.dashboard.server import find_free_port


# ── server.py ─────────────────────────────────────────────────────────
# 注：静态服务能力（GET / 服务 index.html、umi.*.js 资产命中）不在此单测——
# 用例曾硬依赖 gitignored 构建产物 core/dashboard/static/dist/，裸 worktree
# （code-fix 批回归）必假失败，每批白烧一轮重试（2026-09-23 第 3~9 批实证）。
# 该语义由验证链 serve 实例冒烟覆盖（prepare 构建 dist → serve 起真实实例）。
class TestServerAPI:
    def test_api_projects(self, server_fx):
        proot, srv = server_fx
        status, data = srv.get("/api/projects")
        assert status == 200
        assert data["projects"][0]["name"] == "proj-a"
        assert data["projects"][0]["spec_count"] == 2

    def test_api_overview(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/overview")
        assert status == 200
        assert data["totals"]["spec_count"] == 2
        assert data["totals"]["active_runs"] == 1
        assert data["totals"]["status_counts"]["testing"] == 1

    def test_api_specs(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        specs = data["specs"]
        names = {s["name"] for s in specs}
        assert "myspec" in names and "otherspec" in names
        for s in specs:
            assert "created" in s
            assert "updated" in s
        spec_names_order = [s["name"] for s in specs]
        assert spec_names_order.index("otherspec") < spec_names_order.index("myspec")

    def test_api_spec_detail(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs/myspec?project=proj-a")
        assert status == 200
        assert data["status"] == "testing"
        assert len(data["tasks"]) == 2
        assert len(data["scenarios"]) == 2
        assert len(data["bugs"]) >= 1
        assert len(data["screenshots"]) == 1
        assert len(data["runs"]) == 2
        assert data["verify_progress"]["total"] == 3

    def test_api_spec_doc(self, server_fx):
        proot, srv = server_fx
        (proot / "spec" / "changes" / "myspec" / "proposal.md").write_text(
            "# 背景\n\n- 列表项\n", encoding="utf-8"
        )
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=proposal")
        assert status == 200
        assert data["found"] is True
        assert "背景" in data["content"]
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=design")
        assert status == 200
        assert data == {"found": False, "content": "", "project": "proj-a", "spec": "myspec", "doc": "design"}
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=myspec&doc=readme")
        assert status == 400
        status, _ = srv.get("/api/spec-doc?project=proj-a&spec=ghost&doc=proposal")
        assert status == 404
        status, data = srv.get("/api/spec-doc?project=proj-a&spec=../../etc/passwd&doc=proposal")
        assert status == 404
        status, _ = srv.get("/api/spec-doc?project=ghost&spec=myspec&doc=proposal")
        assert status == 400

    def test_api_run(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/runs/impl-myspec-1780000000?project=proj-a")
        assert status == 200
        assert data["status"] == "done"
        assert data["events"][-1]["type"] == "result"

    def test_api_events(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/events?project=proj-a&minutes=10")
        assert status == 200
        assert len(data["events"]) == 1

    def test_unknown_project(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=ghost")
        assert status == 200
        assert data["specs"] == []

    def test_screenshot_served(self, server_fx):
        _, srv = server_fx
        status, ctype, body = srv.get("/screenshots/proj-a/myspec/fail.png", raw=True)
        assert status == 200
        assert ctype == "image/png"

    def test_screenshot_path_traversal_blocked(self, server_fx):
        proot, srv = server_fx
        status, _, _ = srv.get(
            "/screenshots/proj-a/myspec/../../../STATE.md", raw=True
        )
        assert status in (403, 404)
        status, _, _ = srv.get("/screenshots/ghost/myspec/fail.png", raw=True)
        assert status in (403, 404)

    def test_corrupt_progress_does_not_500(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "verify-progress" / "myspec.json").write_text(
            "{{{{ corrupted", encoding="utf-8"
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/specs/myspec?project=proj-a")
            assert status == 200
            assert data["verify_progress"]["error"] == "corrupt"
            status, data = srv.get("/api/overview")
            assert status == 200
        finally:
            srv.stop()

    def test_binds_localhost_only(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}], "scan_dirs": []})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            assert srv.httpd.server_address[0] in ("127.0.0.1", "localhost")
        finally:
            srv.stop()

    def test_find_free_port_probes_upward(self):
        occupied = find_free_port(20100)
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", occupied))
            s.listen(1)
            free = find_free_port(occupied)
            assert free != occupied


class TestSpecSchedulingAPI:
    """定时拾取 / 冻结配置路由（add-spec-scheduling-controls，同款夹具）。

    夹具 make_project：myspec=testing（非终态）、otherspec=done（终态）。
    """

    def test_start_after_set_and_reload(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["start_after"] == "2026-09-07T01:00:00+00:00"
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") == "2026-09-07T01:00:00+00:00"

    def test_start_after_null_clears(self, server_fx):
        proot, srv = server_fx
        srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": None},
        )
        assert status == 200
        assert body["start_after"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None

    def test_start_after_invalid_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "明天早上"},
        )
        assert status == 400
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None  # STATE 不变

    def test_start_after_terminal_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=otherspec",
            {"value": "2026-09-07T01:00:00+00:00"},
        )
        assert status == 403
        entry = dash_data.parse_state(proot)["otherspec"]
        assert entry.get("start_after") is None

    @pytest.fixture()
    def frozen_spec(self, server_fx):
        """已冻结 myspec 的 server（freeze-config 组共享前置，原各用例首行 freeze）。"""
        proot, srv = server_fx
        status, _ = srv.post("/api/spec-freeze?project=proj-a&spec=myspec")
        assert status == 200
        yield proot, srv

    def test_freeze_config_permanent(self, frozen_spec):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "permanent"},
        )
        assert status == 200
        assert body["mode"] == "permanent"
        assert body["frozen_until"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "blocked"
        assert entry.get("frozen_until") is None

    def test_freeze_config_scheduled(self, frozen_spec):
        proot, srv = frozen_spec
        until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "scheduled", "until": until},
        )
        assert status == 200
        assert body["unfrozen"] is False
        assert body["frozen_until"] == until
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "blocked"  # 冻结态保持
        assert entry.get("frozen_until") == until

    def test_freeze_config_scheduled_past_immediate_unfreeze(self, frozen_spec):
        proot, srv = frozen_spec
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "scheduled", "until": past},
        )
        assert status == 200
        assert body["unfrozen"] is True
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "testing"  # 恢复原状态
        assert entry.get("frozen_until") is None  # 不残留

    def test_freeze_config_unfreeze(self, frozen_spec):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "unfreeze"},
        )
        assert status == 200
        assert body["unfrozen"] is True
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("status") == "testing"
        assert entry.get("error") is None

    @pytest.mark.parametrize("payload", [
        {"mode": "bogus"},                          # 非法 mode
        {"mode": "scheduled", "until": "下周一"},    # 非法 until
    ])
    def test_freeze_config_invalid_payload_rejected(self, frozen_spec, payload):
        proot, srv = frozen_spec
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            payload,
        )
        assert status == 400

    def test_freeze_config_non_frozen_rejected(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-freeze-config?project=proj-a&spec=myspec",
            {"mode": "permanent"},
        )
        assert status == 409


class TestSpecManualActivationAPI:
    """手工激活（add-spec-manual-activation D4/D5）：/api/spec-activate +
    /api/spec-start-after 的哨兵 manual 写侧。

    夹具 make_project：myspec=testing（非终态）、otherspec=done（终态）。
    """

    def _set_manual(self, srv, spec="myspec"):
        status, body = srv.post_json(
            f"/api/spec-start-after?project=proj-a&spec={spec}",
            {"value": "manual"},
        )
        assert status == 200
        assert body["start_after"] == "manual"

    def test_start_after_manual_writes_sentinel(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "manual"},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["start_after"] == "manual"
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") == "manual", (
            "哨兵 manual 经 STATE.md 持久化（未折叠/未拒绝）")
        # 设为待激活不写唤醒信号（暂停调度，不是恢复调度）
        assert not (proot / ".fenix" / "scheduling_kick" / "myspec.json").exists()

    def test_start_after_manual_case_insensitive(self, server_fx):
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec",
            {"value": "MANUAL"},
        )
        assert status == 200
        assert body["start_after"] == "manual"
        assert dash_data.parse_state(proot)["myspec"].get("start_after") == "manual"

    def test_activate_success(self, server_fx):
        proot, srv = server_fx
        self._set_manual(srv, "myspec")
        status, body = srv.post("/api/spec-activate?project=proj-a&spec=myspec")
        assert status == 200
        assert body["ok"] is True
        assert body["spec"] == "myspec"
        assert body["start_after"] is None
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None
        req = proot / ".fenix" / "scheduling_kick" / "myspec.json"
        assert req.exists(), "激活动作必须写唤醒信号"
        import json as _json
        payload = _json.loads(req.read_text(encoding="utf-8"))
        assert payload["spec"] == "myspec"

    def test_activate_not_pending_rejected(self, server_fx):
        proot, srv = server_fx
        # myspec 无 start_after（非 manual）→ 非待激活
        status, body = srv.post("/api/spec-activate?project=proj-a&spec=myspec")
        assert status == 200
        assert body["ok"] is False
        assert "并非待激活态" in (body.get("reason") or "")
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None, "STATE 零变更"
        assert not (proot / ".fenix" / "scheduling_kick" / "myspec.json").exists()

    def test_activate_unknown_spec_404(self, server_fx):
        _, srv = server_fx
        status, _ = srv.post("/api/spec-activate?project=proj-a&spec=ghost")
        assert status == 404

    def test_activate_unknown_project_404(self, server_fx):
        _, srv = server_fx
        status, _ = srv.post("/api/spec-activate?project=ghost&spec=myspec")
        assert status == 404

    def test_activate_terminal_403(self, server_fx):
        proot, srv = server_fx
        # 终态 otherspec 即使被置 manual（绕过写侧终态拒绝）也不可激活
        self.sm_update = None  # 直接经 data 层写（服务端只读校验）
        from core.dashboard.data import set_spec_start_after as sset
        r = sset(proot, "otherspec", "manual")
        assert r.get("terminal") is True, "终态写侧本就拒绝 manual"
        status, body = srv.post("/api/spec-activate?project=proj-a&spec=otherspec")
        assert status == 403
        entry = dash_data.parse_state(proot)["otherspec"]
        assert entry.get("start_after") is None

    # ── fix-scheduling-kick-single-slot 多槽位 / 诚实回报（task 6.2/6.3）──

    @staticmethod
    def _add_spec(proot, name, status="ready"):
        """向项目 STATE.md 追加一个非终态 spec（make_project 夹具只有 testing/done 两个）。"""
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(name, {"priority": 3, "status": status, "depends_on": None})

    def test_clear_two_specs_both_signals_exist(self, server_fx):
        """连续清空两个 SPEC 的 start_after：两次响应均 ok:true，两信号文件并存。

        锁死本次事故形态（fix-scheduling-kick-single-slot）：单槽位下第二个清空的
        唤醒信号被丢弃，本用例断言目录形态下两 SPEC 信号文件同时存在。
        """
        proot, srv = server_fx
        self._add_spec(proot, "spec-b", status="ready")
        import json as _json
        from core.dashboard.data import set_spec_start_after
        for sp in ("myspec", "spec-b"):
            set_spec_start_after(proot, sp, "2026-09-30T00:00:00+00:00")
        status1, body1 = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec", {"value": None})
        status2, body2 = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=spec-b", {"value": None})
        assert status1 == 200 and status2 == 200
        assert body1["ok"] is True and body2["ok"] is True
        assert "warning" not in body1, "信号成功写出时无 warning"
        kdir = proot / ".fenix" / "scheduling_kick"
        assert kdir.is_dir(), "信号目录已创建"
        files = sorted(p.name for p in kdir.glob("*.json"))
        assert files == ["myspec.json", "spec-b.json"], (
            f"两个 SPEC 的信号文件必须并存（原事故形态：第二个被丢弃），实际 {files}")

    def test_clear_start_after_write_failure_warning(self, server_fx, monkeypatch):
        """信号写入失败 → 响应带非空 warning 且 start_after 已为 null（task 6.2）。"""
        proot, srv = server_fx
        from core.dashboard.data import admin_actions
        import json as _json
        def _fail_write(project_root, spec):
            return {"ok": False, "file": None, "error": "simulated disk full"}
        monkeypatch.setattr(admin_actions, "write_scheduling_kick", _fail_write)
        status, body = srv.post_json(
            "/api/spec-start-after?project=proj-a&spec=myspec", {"value": None})
        assert status == 200, "start_after 已成功置 null，请求本身成功"
        assert body["ok"] is True
        assert body["start_after"] is None
        warning = body.get("warning")
        assert warning, "信号写出失败时必须带非空 warning"
        assert "即时唤醒信号写入失败" in warning
        assert "下次扫描" in warning
        assert "30" in warning, "文案含缺省周期数（schedule.poll_interval_minutes 缺省 30）"
        # start_after 确实已置 null
        entry = dash_data.parse_state(proot)["myspec"]
        assert entry.get("start_after") is None

    def test_activate_two_manual_specs_both_signals(self, server_fx):
        """连续激活两个 manual SPEC：两信号文件并存，无 409/丢弃（task 6.3）。"""
        proot, srv = server_fx
        self._add_spec(proot, "spec-b", status="ready")
        from core.dashboard.data import set_spec_start_after
        for sp in ("myspec", "spec-b"):
            r = set_spec_start_after(proot, sp, "manual")
            assert r["ok"], f"{sp} 置 manual 失败"
        status1, body1 = srv.post("/api/spec-activate?project=proj-a&spec=myspec")
        status2, body2 = srv.post("/api/spec-activate?project=proj-a&spec=spec-b")
        assert status1 == 200 and status2 == 200, "两次激活都成功（无 409）"
        assert body1["ok"] is True and body2["ok"] is True
        kdir = proot / ".fenix" / "scheduling_kick"
        files = sorted(p.name for p in kdir.glob("*.json"))
        assert files == ["myspec.json", "spec-b.json"], (
            f"两次激活的信号文件并存（无丢弃），实际 {files}")

    def test_activate_write_failure_warning(self, server_fx, monkeypatch):
        """激活时信号写出失败 → 响应带非空 warning（task 3.2 同款透传）。"""
        proot, srv = server_fx
        self._set_manual(srv, "myspec")
        from core.dashboard.data import admin_actions
        def _fail_write(project_root, spec):
            return {"ok": False, "file": None, "error": "simulated disk full"}
        monkeypatch.setattr(admin_actions, "write_scheduling_kick", _fail_write)
        status, body = srv.post("/api/spec-activate?project=proj-a&spec=myspec")
        assert status == 200
        assert body["ok"] is True
        assert body["start_after"] is None
        warning = body.get("warning")
        assert warning, "激活信号写出失败时必须带非空 warning"
        assert "即时唤醒信号写入失败" in warning

    def test_activate_cli_honest_report_on_write_failure(self, server_fx, monkeypatch, capsys):
        """信号写出失败时 cmd_activate 不输出「立即进入调度」且 exit 0（task 6.9）。"""
        proot, _ = server_fx
        from core.dashboard.data import set_spec_start_after
        r = set_spec_start_after(proot, "myspec", "manual")
        assert r["ok"]
        import bin.fenix_cli as cli_mod
        from core.dashboard.data import admin_actions
        def _fail_write(project_root, spec):
            return {"ok": False, "file": None, "error": "simulated disk full"}
        monkeypatch.setattr(admin_actions, "write_scheduling_kick", _fail_write)
        class Args:
            spec = "myspec"
            project = str(proot)
        try:
            cli_mod.cmd_activate(Args())
        except SystemExit as exc:
            assert exc.code == 0, "start_after 已成功置 null，退出码仍为 0"
        out = capsys.readouterr().out
        assert "立即进入调度" not in out, "信号失败时不得宣称「立即进入调度」"
        assert "即时唤醒" in out or "下次扫描" in out


class TestSpecDependsOnSummary:
    """列表摘要 depends_on 字段（add-spec-manual-activation D12）。

    反例必测：STATE.md 的 `- depends_on: null` 解析回字面量字符串 "null"
    （该字段未登记在解析器 null→None 归一化键表），摘要 MUST 归一化为 null，
    否则前端「前置依赖」tag 全线误标。
    """

    def test_specs_summary_includes_depends_on(self, server_fx):
        _, srv = server_fx
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        for s in data["specs"]:
            assert "depends_on" in s, "列表摘要 MUST 暴露 depends_on"
            # 夹具 STATE.md 均为 `depends_on: null` → 摘要须为 None 而非 "null"
            assert s["depends_on"] is None, (
                f"{s['name']} 的 depends_on 应为 None（字面量 'null' 必须归一化），"
                f"实际 {s['depends_on']!r}")

    def test_depends_on_with_value_exposes_normalized_text(self, server_fx):
        proot, srv = server_fx
        # 直接改 STATE.md：my spec 声明依赖 otherspec
        state = (proot / ".fenix" / "STATE.md")
        (proot / ".fenix" / ".STATE.md.bak").write_bytes(state.read_bytes())
        new_state = state.read_text(encoding="utf-8").replace(
            "### myspec\n- status: testing",
            "### myspec\n- status: ready",
        ).replace(
            "- depends_on: null\n",
            "- depends_on: otherspec\n",
            1,
        )
        state.write_text(new_state, encoding="utf-8")
        # 索引被 STATE 变化自然失效（state_changed → idx={} 重建），无需重启服务
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        by_name = {s["name"]: s for s in data["specs"]}
        assert by_name["myspec"]["depends_on"] == "otherspec", (
            "有依赖的 spec 摘要透出规范化后的名称串")

    def test_entry_sig_keys_contains_depends_on(self):
        from core.dashboard.data.summary import _ENTRY_SIG_KEYS
        assert "depends_on" in _ENTRY_SIG_KEYS, (
            "depends_on 必须纳入摘要索引指纹，否则依赖变化不使索引失效")

    def test_summary_index_invalidated_on_depends_change(self, server_fx):
        """依赖变化必须使摘要索引失效（_ENTRY_SIG_KEYS 含 depends_on 的端到端验证）。"""
        from core.dashboard.data.summary import SummaryIndex
        proot, _ = server_fx
        idx = SummaryIndex()
        first = {s["name"]: s for s in idx.get(proot)}
        state = (proot / ".fenix" / "STATE.md")
        new_state = state.read_text(encoding="utf-8").replace(
            "- depends_on: null\n",
            "- depends_on: otherspec\n",
            1,
        )
        state.write_text(new_state, encoding="utf-8")
        second = {s["name"]: s for s in idx.get(proot)}
        assert first["myspec"].get("depends_on") is None
        assert second["myspec"].get("depends_on") == "otherspec", (
            "depends_on 变化未使索引失效（tag 滞后）")


class TestProjectLifecycleAPI:
    """管理端点：start/stop/delete（mock tmux，验证返回、错误路径、SSE 广播）。"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_start_stop_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/projects/ghost/start")
            assert status == 400 and body["error"]
            status, body = srv.post("/api/projects/ghost/stop")
            assert status == 400 and body["error"]
            status, body = srv.delete("/api/projects/ghost")
            assert status == 400 and body["error"]
        finally:
            srv.stop()

    def test_start_stop_delete_flow_with_mocked_tmux(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        started, stopped, deleted = [], [], []
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: started.append(root) or {"ok": True, "session": "s1", "already": False})
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root: stopped.append(root) or {"ok": True, "session": "s1", "was_running": True})

        try:
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is True
            assert body["session"] == "s1"
            assert str(proot) in started
            status, body = srv.post("/api/projects/proj-a/stop")
            assert status == 200 and body["ok"] is True
            assert str(proot) in stopped
            status, body = srv.delete("/api/projects/proj-a")
            assert status == 200 and body["ok"] is True
            assert reg.is_ignored(str(proot))
            names = {p["name"] for p in reg.discover()}
            assert "proj-a" not in names
        finally:
            srv.stop()

    def test_lifecycle_tmux_error_returns_ok_false_not_500(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: (_ for _ in ()).throw(RuntimeError("tmux gone")))
        try:
            status, body = srv.post("/api/projects/proj-a/start")
            assert status == 200 and body["ok"] is False and "tmux gone" in body["error"]
        finally:
            srv.stop()

    def test_restart_writes_restart_request_signal(self, tmp_path, monkeypatch):
        """restart 走 supervisor 优雅重启协议：写 .fenix/restart_request 文件信号，
        不直接调用 start/stop_daemon。"""
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)

        lifecycle_calls = []
        monkeypatch.setattr("core.dashboard.server.start_daemon",
                            lambda root: lifecycle_calls.append(("start", root)) or {"ok": True})
        monkeypatch.setattr("core.dashboard.server.stop_daemon",
                            lambda root: lifecycle_calls.append(("stop", root)) or {"ok": True})

        try:
            status, body = srv.post("/api/projects/proj-a/restart")
            assert status == 200 and body["ok"] is True
            assert (proot / ".fenix" / "restart_request").exists(), \
                "restart 必须写 restart_request 信号（supervisor 优雅重启协议）"
            assert lifecycle_calls == [], "restart 不应直接调用 start/stop_daemon"
        finally:
            srv.stop()

    def test_restart_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/projects/ghost/restart")
            assert status == 400 and body["error"]
        finally:
            srv.stop()


class TestConfigSyncFromUserAPI:
    """POST /api/config/sync-from-user：把用户级 page 页签受管键覆盖写入项目级。"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_sync_writes_project_config_and_echoes(self, tmp_path, monkeypatch):
        import yaml
        proot = make_project(tmp_path)
        user_dir = tmp_path / "user-fenix"
        user_dir.mkdir()
        with open(user_dir / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"gates": {"promote_mode": "manual", "approve_mode": "auto"}}, f)
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "approval"})
            assert status == 200 and body["saved"] is True
            assert body["synced"] == {"gates": {"promote_mode": "manual", "approve_mode": "auto"}}
            proj_cfg = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
            assert proj_cfg["gates"]["promote_mode"] == "manual"
        finally:
            srv.stop()

    def test_sync_unknown_page_returns_400(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        user_dir = tmp_path / "user-fenix"
        user_dir.mkdir()
        monkeypatch.setattr("core.dashboard.data.USER_CONFIG_PATH", user_dir / "config.yaml")

        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "bogus"})
            assert status == 400 and "未知页面标识" in body["error"]
        finally:
            srv.stop()

    def test_sync_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=ghost",
                          {"page": "approval"})
            assert status == 400 and body["error"]
        finally:
            srv.stop()


class TestConfigClearPageKeysAPI:
    """POST /api/config/sync-from-user action=clear：删除项目级 page 页签受管键。

    清空后项目级不再显式覆盖这些键，用户级/默认值自然生效（sources 回 "user"）。
    """

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def _write_project_config(self, proot, data):
        import yaml
        with open(proot / ".fenix" / "config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)

    def test_clear_removes_page_keys_and_preserves_others(self, tmp_path, monkeypatch):
        import yaml
        proot = make_project(tmp_path)
        self._write_project_config(proot, {
            "project": {"name": "fake"},
            "gates": {"promote_mode": "manual", "approve_mode": "manual", "custom_keep": 1},
            "llm": {"providers": [{"name": "p1", "baseurl": "https://x", "apikey": "k", "model": "m"}]},
            "agents": {"max_concurrent": 3},
        })
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "approval", "action": "clear"})
            assert status == 200 and body["saved"] is True
            # cleared 只含实际删除的键（spec_review_mode / start_after_scope 原本就没配）
            assert body["cleared"] == {"gates": {"promote_mode": "manual", "approve_mode": "manual"}}
            proj_cfg = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
            # 受管键删除；非受管键 custom_keep 保留（section 未删空不移除）
            assert proj_cfg["gates"] == {"custom_keep": 1}
            # 其它 section 不受影响
            assert proj_cfg["llm"]["providers"][0]["name"] == "p1"
            assert proj_cfg["agents"]["max_concurrent"] == 3
            assert proj_cfg["project"]["name"] == "fake"
            # 生效视图 sources：被清空键回落用户级
            assert body["sources"].get("gates.promote_mode") == "user"
        finally:
            srv.stop()

    def test_clear_removes_emptied_section(self, tmp_path, monkeypatch):
        import yaml
        proot = make_project(tmp_path)
        # archive 段只有受管键 auto_threshold：清空后整段消失
        self._write_project_config(proot, {"archive": {"auto_threshold": 10}})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "misc", "action": "clear"})
            assert status == 200
            proj_cfg = yaml.safe_load((proot / ".fenix" / "config.yaml").read_text(encoding="utf-8"))
            assert "archive" not in proj_cfg
        finally:
            srv.stop()

    def test_clear_without_project_config_is_noop(self, tmp_path, monkeypatch):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "config.yaml").unlink()
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "approval", "action": "clear"})
            assert status == 200 and body["cleared"] is None
        finally:
            srv.stop()

    def test_clear_unknown_page_returns_400(self, tmp_path):
        proot = make_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "bogus", "action": "clear"})
            assert status == 400 and "未知页面标识" in body["error"]
        finally:
            srv.stop()

    def test_clear_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=ghost",
                          {"page": "approval", "action": "clear"})
            assert status == 400 and body["error"]
        finally:
            srv.stop()

    def test_clear_broken_project_config_returns_400(self, tmp_path):
        proot = make_project(tmp_path)
        (proot / ".fenix" / "config.yaml").write_text("{unbalanced", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post_json("/api/config/sync-from-user?project=proj-a",
                          {"page": "approval", "action": "clear"})
            assert status == 400 and "读取" in body["error"]
        finally:
            srv.stop()


class TestProjectDescribeAPI:
    """测试 /api/project/describe 端点"""

    def _make_server(self, tmp_path, registry):
        return _TestServer(registry, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_describe_unknown_project_returns_400(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/project/describe?project=ghost")
            assert status == 400 and body["error"] == "unknown project"
        finally:
            srv.stop()

    def test_describe_project_not_found_returns_404(self, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(tmp_path / "nonexistent")}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = self._make_server(tmp_path, reg)
        try:
            status, body = srv.post("/api/project/describe?project=proj-a")
            assert status == 404 and body["error"] == "project not found"
        finally:
            srv.stop()

    def test_describe_prompt_contains_project_identity(self, server_fx, monkeypatch):
        """prompt 必须携带项目名与路径，否则 README 主题重叠的项目（如 fenix-desktop
        与 fenixd）会生成彼此的简介。"""
        proot, srv = server_fx
        (proot / "README.md").write_text(
            "# 同一个框架\n这是两个不同项目共用的说明文案。", encoding="utf-8"
        )

        mock_result = type('MockResult', (), {'returncode': 0, 'stdout': '简介', 'stderr': ''})()
        captured = {}

        def fake_run(args, **kwargs):
            captured['args'] = args
            return mock_result

        monkeypatch.setattr("subprocess.run", fake_run)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200 and body["ok"] is True
        prompt = captured['args'][2]  # ["claude", "-p", prompt]
        assert "proj-a" in prompt, "prompt 未包含项目名"
        assert str(proot) in prompt, "prompt 未包含项目路径"

    def test_describe_success_with_readme(self, server_fx, monkeypatch):
        proot, srv = server_fx
        # 创建 README.md
        (proot / "README.md").write_text("# 测试项目\n这是一个测试项目，用于演示功能。", encoding="utf-8")

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个由测试生成的项目简介，用于验证 describe 接口功能。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200
        assert body["ok"] is True
        assert "description" in body
        assert body["description"] == "这是一个由测试生成的项目简介，用于验证 describe 接口功能。"

        # 验证配置已写入
        config_path = proot / ".fenix" / "config.yaml"
        assert config_path.exists()
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        assert config["project"]["description"] == "这是一个由测试生成的项目简介，用于验证 describe 接口功能。"

    def test_describe_success_without_readme(self, server_fx, monkeypatch):
        proot, srv = server_fx
        # 不创建 README.md，创建 package.json 作为 fallback
        (proot / "package.json").write_text('{"name": "test-project", "version": "1.0.0"}', encoding="utf-8")

        # Mock subprocess.run
        mock_result = type('MockResult', (), {
            'returncode': 0,
            'stdout': '这是一个基于 package.json 生成的项目简介。',
            'stderr': ''
        })()
        monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: mock_result)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200
        assert body["ok"] is True
        assert body["description"] == "这是一个基于 package.json 生成的项目简介。"

    @pytest.mark.parametrize("mock_kind,expected_frag", [
        ("timeout", "超时"),
        ("nonzero", "非零退出码"),
        ("empty", "为空"),
    ])
    def test_describe_error_returns_error_and_keeps_config(self, server_fx, monkeypatch, mock_kind, expected_frag):
        """超时 / 非零退出码 / 空输出 → 200 + error 且不写 description。"""
        import subprocess
        proot, srv = server_fx
        (proot / "README.md").write_text("# 测试项目", encoding="utf-8")

        if mock_kind == "timeout":
            def mock_run(*args, **kwargs):
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)
        elif mock_kind == "nonzero":
            mock_result = type('MockResult', (), {
                'returncode': 1, 'stdout': '', 'stderr': 'Error: Claude CLI failed'})()
            mock_run = lambda *args, **kwargs: mock_result
        else:  # empty
            mock_result = type('MockResult', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
            mock_run = lambda *args, **kwargs: mock_result
        monkeypatch.setattr("subprocess.run", mock_run)

        status, body = srv.post("/api/project/describe?project=proj-a")
        assert status == 200
        assert "error" in body
        assert expected_frag in body["error"]

        # 验证配置未被修改
        config_path = proot / ".fenix" / "config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        assert "description" not in config.get("project", {})

    # ── verify-yaml-autodraft tests ──────────────────────────────────────────

    def test_autodraft_unknown_project_returns_404(self, server_fx):
        """未知项目 404，不写任何信号。"""
        _, srv = server_fx
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=nonexistent",
            {"overwrite": False},
        )
        assert status == 404
        assert body.get("error") == "project not found"

    def test_autodraft_missing_contract_dispatches_signal(self, server_fx):
        """契约缺失 → dispatched + 信号落盘含 source 标注。"""
        proot, srv = server_fx
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert status == 200
        assert body["ok"] is True
        assert body["status"] == "dispatched"
        assert "AI 起草请求" in body["message"]
        # 检查信号落盘
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        signals = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(signals) == 1
        sig = signals[0]
        assert sig["source"] == "ui-manual"
        assert sig["spec"] is None
        assert sig["overwrite"] is False
        assert "项目名=proj-a" in sig["evidence"]

    def test_autodraft_valid_contract_no_overwrite_skipped(self, server_fx):
        """契约有效无 overwrite → skipped 且零信号。"""
        proot, srv = server_fx
        # 写入有效契约
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert status == 200
        assert body["status"] == "skipped"
        assert "契约已有效" in body["message"]
        # 检查零信号
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        signals = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(signals) == 0

    def test_autodraft_valid_contract_with_overwrite_dispatches(self, server_fx):
        """契约有效带 overwrite → dispatched + 写入 verify_contract_redraft 信号。"""
        proot, srv = server_fx
        # 写入有效契约
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        status, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        assert body["status"] == "dispatched"
        # 检查信号落盘：覆盖重起草改写 verify_contract_redraft，不再旁路 missing
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        missing = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        assert len(redraft) == 1
        assert len(missing) == 0
        sig = redraft[0]
        assert sig["overwrite"] is True
        assert sig["source"] == "ui-manual"
        assert "项目名=proj-a" in sig["evidence"]
        assert "覆盖确认=是" in sig["evidence"]

    def test_autodraft_redraft_signal_severity_major(self, server_fx):
        """redraft 信号 severity=major（与 SPEC Requirement 一致）。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        sig = next(r for r in records if r.get("signal_type") == "verify_contract_redraft")
        assert sig["severity"] == "major"

    def test_autodraft_inflight_dedup_no_duplicate_write(self, server_fx):
        """在途去重：同类型未消费信号已存在 → 二次触发不落盘 + message 注明在途。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        # 第一次触发：写入 redraft 信号
        _, body1 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body1["status"] == "dispatched"
        # 第二次触发：在途信号存在 → 不重复写，message 含在途提示
        status, body2 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        assert body2["status"] == "dispatched"
        assert "已有在途" in body2["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(redraft) == 1, "同类型在途信号存在时不得重复落盘"

    def test_autodraft_handled_signal_does_not_suppress(self, server_fx):
        """已消费（handled）信号不抑制新触发 → 正常写入新信号。"""
        proot, srv = server_fx
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        # 第一次触发落盘
        srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        # 模拟 Administrator 已处置：把该信号标记 handled
        alerts_path = proot / ".fenix" / "admin_alerts.json"
        import json as _json
        records = _json.loads(alerts_path.read_text(encoding="utf-8"))
        for rec in records:
            if rec.get("signal_type") == "verify_contract_redraft":
                rec["handled"] = True
        alerts_path.write_text(
            _json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # 再次触发：handled 不抑制 → 新信号落盘
        _, body = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body["status"] == "dispatched"
        assert "已有在途" not in body["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(redraft) == 2, "已 handled 信号不抑制新触发"

    def test_autodraft_missing_inflight_does_not_suppress_redraft(self, server_fx):
        """异类型互不抑制：missing 在途不挡 redraft。"""
        proot, srv = server_fx
        # 无契约触发 → missing 信号落盘（在途）
        _, body1 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": False},
        )
        assert body1["status"] == "dispatched"
        # 契约被修正为可解析 + 用户确认覆盖 → redraft 信号正常落盘
        (proot / ".fenix" / "verify.yaml").write_text(
            "prepare:\n  - run: echo ok\nserve:\n  kind: command\n  cmd: echo serve\n",
            encoding="utf-8",
        )
        _, body2 = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert body2["status"] == "dispatched"
        assert "已有在途" not in body2["message"]
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        missing = [r for r in records if r.get("signal_type") == "verify_contract_missing"]
        redraft = [r for r in records if r.get("signal_type") == "verify_contract_redraft"]
        assert len(missing) == 1
        assert len(redraft) == 1, "missing 在途不得抑制 redraft"

    def test_autodraft_signal_record_completeness(self, server_fx):
        """信号记录字段完整性：signal_type/source/overwrite/evidence 项目名。"""
        proot, srv = server_fx
        status, _ = srv.post_json(
            "/api/verify-yaml-autodraft?project=proj-a",
            {"overwrite": True},
        )
        assert status == 200
        from core.admin_store import AdminStore
        store = AdminStore(proot)
        records = store.read_all()
        sig = next(r for r in records if r.get("signal_type") == "verify_contract_missing")
        # 字段完整性
        assert sig["signal_type"] == "verify_contract_missing"
        assert sig["source"] == "ui-manual"
        assert sig["overwrite"] is True
        assert "项目名=proj-a" in sig["evidence"]
        assert sig["spec"] is None
        assert sig["kind"] == "signal"


# ── SPEC 人工晋升（add-draft-promotion-gate D4/D5） ──────────────────
class TestSpecPromoteAPI:
    """POST /api/spec-promote：drafted → ready 人工晋升。"""

    def _make_drafted_project(self, tmp_path, spec_name="draft-spec"):
        """构造含 drafted spec 的项目（复用 make_project 后改状态）。"""
        proot = make_project(tmp_path, name="proj-a")
        # 添加一个 drafted spec
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "drafted"})
        # 创建 spec 目录与 tasks.md（声明段合法）
        (proot / "spec" / "changes" / spec_name).mkdir(parents=True, exist_ok=True)
        (proot / "spec" / "changes" / spec_name / "tasks.md").write_text(
            "## 1. 阶段一\n\n- [x] 1.1 任务一\n", encoding="utf-8"
        )
        return proot

    def test_promote_success(self, tmp_path):
        """成功晋升：drafted → reviewing（default auto 分流，无 .spec.yaml 保守进入评审）。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["next_status"] == "reviewing"
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_promote_never_mode_goes_ready(self, tmp_path):
        """spec_review_mode: never → 跳过评审直通 ready（全通道恢复旧行为）。"""
        proot = self._make_drafted_project(tmp_path)
        # 写入项目配置（never 模式）
        (proot / ".fenix" / "config.yaml").write_text(
            "gates:\n  spec_review_mode: never\n", encoding="utf-8"
        )
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is True
            assert body.get("next_status") == "ready"
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "ready"
        finally:
            srv.stop()

    def test_promote_not_found(self, tmp_path):
        """spec 不存在 → 404。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, _ = srv.post("/api/spec-promote?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_promote_unknown_project(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, _ = srv.post("/api/spec-promote?project=ghost&spec=draft-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_promote_non_drafted_rejected(self, tmp_path):
        """非 drafted 状态拒绝：spec 保持原状态且 STATE 不变更。"""
        proot = self._make_drafted_project(tmp_path)
        # 先把 draft-spec 晋升为 ready
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.transition("draft-spec", "ready")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
            assert status == 200
            assert body["ok"] is False
            assert "ready" in body["reason"]
            entry = dash_data.parse_state(proot)["draft-spec"]
            assert entry["status"] == "ready"  # 状态不变更
        finally:
            srv.stop()

    def test_promote_lint_violation_writes_state_error(self, tmp_path):
        """lint 违规：返回 violations，STATE error 写入，SPEC 停留 drafted。"""
        proot = self._make_drafted_project(tmp_path)
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            # Mock promote_drafted to return violations（直接注入违规，避免依赖 lint 实现）
            import core.dashboard.data as dash_data
            original_fn = dash_data.promote_spec
            def mock_promote(pr, sn):
                return {"ok": False, "found": True, "violations": ["bad path declaration"]}
            dash_data.promote_spec = mock_promote
            try:
                status, body = srv.post("/api/spec-promote?project=proj-a&spec=draft-spec")
                assert status == 200
                assert body["ok"] is False
                assert body["violations"] == ["bad path declaration"]
            finally:
                dash_data.promote_spec = original_fn
        finally:
            srv.stop()


# ── SPEC 重新评审 API（add-spec-review-gate 4.5 / 7.8） ──────────────

class TestSpecReReviewAPI:
    """POST /api/spec-re-review：评审相关 blocked → reviewing 重新评审。"""

    def _make_blocked_project(self, tmp_path, spec_name="blocked-spec",
                              error="spec-review-rejected: 方向性风险"):
        """构造含评审相关 blocked spec 的项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "blocked", "error": error})
        return proot

    def _server(self, tmp_path, proot):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_re_review_success(self, tmp_path):
        """评审相关 blocked → 重新评审成功（blocked → reviewing）。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 200
            assert body["ok"] is True
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_re_review_spec_not_found(self, tmp_path):
        """spec 不存在 → 404。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, _ = srv.post("/api/spec-re-review?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_re_review_project_not_found(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_blocked_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, _ = srv.post("/api/spec-re-review?project=ghost&spec=blocked-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_re_review_non_review_blocked_rejected(self, tmp_path):
        """非评审前缀 blocked（如熔断）→ 400 + 明确原因，状态不变。"""
        proot = self._make_blocked_project(tmp_path, error="merge-breaker: 熔断")
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 400
            assert "评审" in body["error"]
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "blocked"
        finally:
            srv.stop()

    def test_re_review_frozen_rejected(self, tmp_path):
        """冻结态 blocked → 400 拒绝（冻结保护双层之一）。"""
        proot = self._make_blocked_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("blocked-spec", {"frozen": True})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 400
            assert "冻结" in body["error"]
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["frozen"] is True
            assert entry["status"] == "blocked"
        finally:
            srv.stop()

    def test_re_review_incomplete_prefix_allowed(self, tmp_path):
        """spec-review-incomplete: 前缀同样可重新评审（两类 blocked 均开放）。"""
        proot = self._make_blocked_project(tmp_path,
                                            error="spec-review-incomplete: 结果文件缺失")
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=blocked-spec")
            assert status == 200
            assert body["ok"] is True
            entry = dash_data.parse_state(proot)["blocked-spec"]
            assert entry["status"] == "reviewing"
        finally:
            srv.stop()

    def test_re_review_non_blocked_state_rejected(self, tmp_path):
        """非 blocked 状态（ready/drafted）→ 400 拒绝（开放条件要求状态为 blocked）。
        代办：Agent 场景按状态枚举全表列置——评审开放条件四类拒绝（非 blocked /
        非评审前缀 / 冻结 / 幂等重复调用）在 TestReReviewConditions 已覆盖单元层，
        此处验证 HTTP 层对非 blocked 的拒绝语义。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("ready-spec", {"status": "ready"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-re-review?project=proj-a&spec=ready-spec")
            assert status == 400
            assert body["error"]
            assert dash_data.parse_state(proot)["ready-spec"]["status"] == "ready"
        finally:
            srv.stop()


# ── SPEC 审批推送 API（add-spec-approve-push-modal Task 5.2/5.3） ────

class TestSpecTaskReflowAPI:
    """POST /api/spec-task-reflow：task-gap 滞留 verified SPEC 回炉的 HTTP 语义。

    fix-impl-tasks-completion-gate D8/7.2：错误语义对齐 spec-error-clear /
    spec-freeze-config 家族（project/spec 404、拒绝返回明确原因、成功 ok:true）。
    """

    def _make_verified_taskgap_project(self, tmp_path, spec_name="stuck-spec"):
        """构造含 verified + task-gap error 的 spec 项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {
            "status": "verified",
            "error": "task-gap:未完成任务：4.5、5.1",
        })
        return proot

    def _server(self, tmp_path, proot):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_reflow_success(self, tmp_path):
        """合规形态（verified + task-gap 前缀 + 未冻结）→ ok:true、status=ready。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["status"] == "ready"
            entry = dash_data.parse_state(proot)["stuck-spec"]
            assert entry["status"] == "ready"
            assert entry["error"] in (None, "")
        finally:
            srv.stop()

    def test_reflow_project_404(self, tmp_path):
        """project 不存在 → 404。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=nope&spec=stuck-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_reflow_spec_404(self, tmp_path):
        """spec 不存在 → 404（不产生状态写入）。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=ghost")
            assert status == 404
            assert "not found" in body.get("error", "").lower() or \
                "not found" in body.get("message", "").lower()
        finally:
            srv.stop()

    def test_reflow_non_verified_rejected(self, tmp_path):
        """非 verified 状态 → 明确拒绝原因（status 不变）。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"status": "ready"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "当前状态为 'ready'" in body["reason"]
            assert dash_data.parse_state(proot)["stuck-spec"]["status"] == "ready"
        finally:
            srv.stop()

    def test_reflow_error_not_task_gap_rejected(self, tmp_path):
        """verified 但 error 非 task-gap 前缀 → 明确拒绝原因。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"error": "spec-review-rejected: x"})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "task-gap" in body["reason"]
        finally:
            srv.stop()

    def test_reflow_frozen_rejected(self, tmp_path):
        """冻结态 → 明确拒绝原因。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.update_spec("stuck-spec", {"frozen": True})
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200
            assert body["ok"] is False
            assert "冻结" in body["reason"]
        finally:
            srv.stop()

    def test_reflow_idempotent_second_call_rejected(self, tmp_path):
        """幂等重复调用：第二次（已复位 ready）→ 拒绝且无重复日志。"""
        proot = self._make_verified_taskgap_project(tmp_path)
        srv = self._server(tmp_path, proot)
        try:
            status, body = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status == 200 and body["ok"] is True
            log_path = proot / ".fenix" / "PROJECT_LOG.md"
            log_before = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            status2, body2 = srv.post("/api/spec-task-reflow?project=proj-a&spec=stuck-spec")
            assert status2 == 200
            assert body2["ok"] is False
            log_after = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            assert log_after == log_before
        finally:
            srv.stop()


class TestSpecApprovePushAPI:
    """POST /api/spec-approve-push：done SPEC 审批推送的 HTTP 全分支语义。"""

    def _make_done_project(self, tmp_path, spec_name="done-spec"):
        """构造含 done spec 的项目。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec(spec_name, {"status": "done"})
        return proot

    def _server_for(self, proot, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_approve_push_success_200(self, tmp_path, monkeypatch):
        """成功：200 + {ok: true, project, spec, created}。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：消费方判据升级为托管态（managed）——
        # 测试环境无真实 supervisor，patch 托管态以验证成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 200
            assert body["ok"] is True
            assert body["project"] == "proj-a"
            assert body["spec"] == "done-spec"
            assert isinstance(body["created"], str)
        finally:
            srv.stop()

    def test_approve_push_spec_not_found_404(self, tmp_path, monkeypatch):
        """spec 不存在 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=ghost")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_unknown_project_404(self, tmp_path, monkeypatch):
        """project 不存在 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=ghost&spec=done-spec")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_non_done_ready_403(self, tmp_path, monkeypatch):
        """status=ready → 403，文案含「仅 done 状态可审批推送」与当前状态。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("ready-spec", {"status": "ready"})
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=ready-spec")
            assert status == 403
            assert "仅 done 状态可审批推送" in body["error"]
            assert "ready" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_pushed_403(self, tmp_path, monkeypatch):
        """status=pushed → 403，文案含「已推送」。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        from core.state_machine import StateMachine
        sm = StateMachine(proot / ".fenix" / "STATE.md", None)
        sm.add_spec("pushed-spec", {"status": "pushed"})
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=pushed-spec")
            assert status == 403
            assert "已推送" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_daemon_down_409(self, tmp_path, monkeypatch):
        """daemon 未运行 → 409，文案含「daemon 未运行」。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: False)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 409
            assert "daemon 未运行" in body["error"]
        finally:
            srv.stop()

    def test_approve_push_conflict_409(self, tmp_path, monkeypatch):
        """已有未消费信号 → 409 冲突。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：消费方判据升级为托管态，成功路径须
        # 托管态为 managed（测试环境无真实 supervisor）
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status1, body1 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status1 == 200
            assert body1["ok"] is True
            status2, body2 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status2 == 409
            assert "已有进行中的审批推送请求" in body2["error"]
        finally:
            srv.stop()

    def test_approve_push_body_keys_aligned_with_budget(self, tmp_path, monkeypatch):
        """响应体键断言对齐 budget/promote API 测试风格：ok/project/spec 三键必须存在。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：托管态 managed 才走成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status == 200
            assert "ok" in body
            assert "project" in body
            assert "spec" in body
            assert "created" in body
        finally:
            srv.stop()

    def test_approve_push_missing_spec_query_404(self, tmp_path, monkeypatch):
        """缺少 spec query 参数 → 404。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/spec-approve-push?project=proj-a")
            assert status == 404
        finally:
            srv.stop()

    def test_approve_push_idempotent_two_calls_second_409(self, tmp_path, monkeypatch):
        """Task 5.3：连续两次调用（中间不消费）→ 第二次 409。"""
        proot = self._make_done_project(tmp_path)
        monkeypatch.setattr(dash_data, "_is_running", lambda p: True)
        # fix-supervisor-hosting-chain D8：托管态 managed 才走成功写入路径
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status1, _ = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status1 == 200
            status2, body2 = srv.post("/api/spec-approve-push?project=proj-a&spec=done-spec")
            assert status2 == 409
            assert body2["error"]
        finally:
            srv.stop()


# ── keep-alive 错误路径连接卫生（BUG-01 回归锁，refactor-giant-classes 修复轮） ──
class TestKeepAliveErrorPathHygiene:
    """keep-alive 连接复用下错误路径响应写序/请求体排空（BUG-01 回归锁）。

    验证场景 api-post-chain-spec-evolution / api-spec-detail-doc-error-paths
    在 httpx/http.client 连接复用（keep-alive）下暴露的两个缺陷：
    - POST handler 错误路径（project/spec 校验失败）未消费请求体 → 残留字节
      被同连接下一请求当请求行读取，解析为 ``{...}POST ...`` 非法命令 → 501；
    - ``_get_spec_doc`` 适配器对已自写 ``_error`` 的 handler 再包 ``_json(None)``
      → 双重响应残留 200+null 污染同连接下一请求。
    修复后同连接连续请求均返回正确状态且连接不脱同步（will_close=False）。
    """

    def test_post_error_paths_keep_alive_connection_clean(self, server_fx):
        """三个错误路径 POST 走同一 keep-alive 连接，均返回正确状态且不脱同步。"""
        _, srv = server_fx
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            steps = [
                ("/api/spec-error-clear", 404),
                ("/api/spec-error-clear?project=no-such-project-xyz&spec=x", 404),
                ("/api/evolution/reject", 400),
            ]
            for i, (path, expect) in enumerate(steps):
                body = b"{}"
                conn.request(
                    "POST", path, body=body,
                    headers={"Content-Type": "application/json",
                             "Content-Length": str(len(body))},
                )
                resp = conn.getresponse()
                data = resp.read()
                assert resp.status == expect, (
                    f"step{i+1} {path}: 期望{expect} 实际{resp.status} {data[:80]!r}"
                )
                assert resp.will_close is False, (
                    f"step{i+1} {path}: 连接被关闭/脱同步（残留 body 污染）"
                )
        finally:
            conn.close()

    def test_spec_doc_error_paths_keep_alive_no_double_write(self, server_fx):
        """GET spec-doc 错误路径单响应；同连接下一请求不被残留 200+null 污染。"""
        _, srv = server_fx
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            conn.request("GET", "/api/spec-doc")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 400
            assert b"unknown project" in data

            # 同连接第二请求：不得读到上一请求的双重写残留（200+null）
            conn.request("GET", "/api/spec-doc?project=no-such-project-xyz&spec=x&doc=proposal")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 400
            assert b"unknown project" in data

            # 连接仍健康：正常端点可用
            conn.request("GET", "/api/events?project=proj-a")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 200
        finally:
            conn.close()

    def test_spec_doc_success_path_keep_alive(self, server_fx):
        """成功路径 spec-doc 与错误路径交替走同连接，互不污染。"""
        proot, srv = server_fx
        (proot / "spec" / "changes" / "myspec" / "proposal.md").write_text(
            "# 背景\n\n- 列表项\n", encoding="utf-8"
        )
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=10)
        try:
            # 错误路径（未注册项目 → 400）
            conn.request("GET", "/api/spec-doc?project=no-such-project-xyz&spec=x&doc=proposal")
            resp = conn.getresponse()
            assert resp.status == 400
            resp.read()
            # 成功路径（同连接）
            conn.request("GET", "/api/spec-doc?project=proj-a&spec=myspec&doc=proposal")
            resp = conn.getresponse()
            data = resp.read()
            assert resp.status == 200
            assert "背景".encode("utf-8") in data
        finally:
            conn.close()


class TestCodeFixRunAPI:
    """POST /api/code-review/fix-run + GET /api/code-review/fix-run-result
    （add-code-fix-manual-trigger task 5.1）HTTP 全分支语义。

    fix-run 写 ``.fenix/code_fix_request.json`` 文件信号（O_CREAT|O_EXCL 独
    占创建）由 daemon 消费；fix-run-result 只读透传判定结果文件，缺失返回
    缺省态 ``{}``（MUST NOT 500）。消费方守卫（hosting_state 判据）对齐
    POST /api/code-review/run。
    """

    _SIG = ".fenix/code_fix_request.json"
    _RESULT = ".fenix/code_fix_request_result.json"

    def _server_for(self, proot, tmp_path):
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        return _TestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")

    def test_fix_run_success_200_writes_signal(self, tmp_path, monkeypatch):
        """受理成功：200 + {ok, requested_at}，信号文件被创建（source/created）。"""
        import json as _json
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/code-review/fix-run?project=proj-a")
            assert status == 200
            assert body["ok"] is True
            assert isinstance(body["requested_at"], str)
            sig = proot / self._SIG
            assert sig.exists()
            payload = _json.loads(sig.read_text(encoding="utf-8"))
            assert payload["source"] == "dashboard"
            assert payload["created"] == body["requested_at"]
        finally:
            srv.stop()

    def test_fix_run_existing_signal_409_no_overwrite(self, tmp_path, monkeypatch):
        """残留/并发未消费信号 → 409，MUST NOT 覆盖已有信号。"""
        import json as _json
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        sig = proot / self._SIG
        sig.parent.mkdir(parents=True, exist_ok=True)
        sig.write_text(_json.dumps({"source": "dashboard", "created": "stale"}),
                       encoding="utf-8")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/code-review/fix-run?project=proj-a")
            assert status == 409
            assert "修复触发请求" in body["error"]
            # 原信号未被覆盖
            assert _json.loads(sig.read_text(encoding="utf-8"))["created"] == "stale"
        finally:
            srv.stop()

    def test_fix_run_unknown_project_404(self, tmp_path, monkeypatch):
        """项目不存在 → 404，不写信号。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/code-review/fix-run?project=ghost")
            assert status == 404
            assert not (proot / self._SIG).exists()
        finally:
            srv.stop()

    def test_fix_run_stopped_400(self, tmp_path, monkeypatch):
        """daemon stopped → 400「daemon 未运行」，不写信号。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "stopped")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/code-review/fix-run?project=proj-a")
            assert status == 400
            assert "daemon 未运行" in body["error"]
            assert not (proot / self._SIG).exists()
        finally:
            srv.stop()

    def test_fix_run_unmanaged_409(self, tmp_path, monkeypatch):
        """daemon 未受 supervisor 托管 → 409 明确文案，不写信号。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "unmanaged")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.post("/api/code-review/fix-run?project=proj-a")
            assert status == 409
            assert "未受 supervisor 托管" in body["error"]
            assert not (proot / self._SIG).exists()
        finally:
            srv.stop()

    def test_fix_run_predeletes_stale_result(self, tmp_path, monkeypatch):
        """受理前预删旧结果文件：陈旧残留判定 MUST NOT 被前端当本次反馈。"""
        import json as _json
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        monkeypatch.setattr("core.fenix_session.hosting_state", lambda p: "managed")
        result = proot / self._RESULT
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(_json.dumps({"request_created": "stale",
                                       "triggered": False, "reason": "no_open_items",
                                       "message": "旧", "finished_at": "stale"}),
                          encoding="utf-8")
        srv = self._server_for(proot, tmp_path)
        try:
            status, _ = srv.post("/api/code-review/fix-run?project=proj-a")
            assert status == 200
            assert not result.exists(), "受理成功 MUST 预删旧结果文件"
        finally:
            srv.stop()

    def test_fix_run_result_default_empty(self, tmp_path, monkeypatch):
        """结果文件缺失 → 200 缺省态 {}（MUST NOT 500）。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.get("/api/code-review/fix-run-result?project=proj-a")
            assert status == 200
            assert body == {}
        finally:
            srv.stop()

    def test_fix_run_result_passthrough(self, tmp_path, monkeypatch):
        """结果文件存在 → 内容原样透传（回链字段齐全）。"""
        import json as _json
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        result = proot / self._RESULT
        result.parent.mkdir(parents=True, exist_ok=True)
        payload = {"request_created": "2026-09-22T00:00:00+00:00",
                   "triggered": True, "reason": "dispatched",
                   "message": "已投递一批自动修复", "finished_at": "2026-09-22T00:00:01+00:00"}
        result.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.get("/api/code-review/fix-run-result?project=proj-a")
            assert status == 200
            assert body == payload
        finally:
            srv.stop()

    def test_fix_run_result_corrupt_returns_default(self, tmp_path, monkeypatch):
        """结果文件损坏 → 缺省态 {}（读侧 MUST NOT 500）。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        result = proot / self._RESULT
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text("{broken", encoding="utf-8")
        srv = self._server_for(proot, tmp_path)
        try:
            status, body = srv.get("/api/code-review/fix-run-result?project=proj-a")
            assert status == 200
            assert body == {}
        finally:
            srv.stop()

    def test_fix_run_result_unknown_project_404(self, tmp_path):
        """项目不存在 → 404（对齐其余 GET 端点形态）。"""
        proot = make_project(tmp_path, name="proj-a", otherspec=False)
        srv = self._server_for(proot, tmp_path)
        try:
            status, _ = srv.get("/api/code-review/fix-run-result?project=ghost")
            assert status == 404
        finally:
            srv.stop()


# ── runs.get_run_events 窗口切片（add-run-record-readability 4.5） ────
class TestRunTailWindow:
    """get_run_events offset_from_end 向前分页窗口：offset=0 等价现状、
    中段窗口、越界钳制、total_events 与 status 不受窗口影响。"""

    RUN_ID = "impl-window-test-1790000000"

    @staticmethod
    def _write_run(proot, n_events: int) -> Path:
        """写一条 n_events 条 status 心跳 + 1 条 result 终态的 run 流。"""
        import json

        run_file = proot / ".fenix" / "runs" / f"{TestRunTailWindow.RUN_ID}.jsonl"
        run_file.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps({"type": "system", "subtype": "status", "seq": i}, ensure_ascii=False)
            for i in range(n_events)
        ]
        lines.append(json.dumps({"type": "result", "result": "ok"}, ensure_ascii=False))
        run_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return run_file

    def test_offset_zero_equivalent_to_legacy_tail(self, tmp_path):
        proot = make_project(tmp_path)
        self._write_run(proot, 12)
        legacy = dash_data.get_run_events(proot, self.RUN_ID, tail=5)
        windowed = dash_data.get_run_events(proot, self.RUN_ID, tail=5, offset_from_end=0)
        assert windowed == legacy
        assert len(windowed["events"]) == 5
        assert windowed["events"][-1]["type"] == "result"

    def test_mid_window_slice(self, tmp_path):
        proot = make_project(tmp_path)
        self._write_run(proot, 10)
        # 全流 11 条（10 心跳 + 1 result）：窗口 [11-3-2, 11-2) = seq 6,7,8
        data = dash_data.get_run_events(proot, self.RUN_ID, tail=3, offset_from_end=2)
        assert [e["seq"] for e in data["events"]] == [6, 7, 8]
        assert data["total_events"] == 11

    def test_offset_clamps_beyond_stream_start(self, tmp_path):
        proot = make_project(tmp_path)
        self._write_run(proot, 4)
        # 越界：offset=100 → end 钳到 0，窗口为空
        data = dash_data.get_run_events(proot, self.RUN_ID, tail=3, offset_from_end=100)
        assert data["events"] == []
        assert data["total_events"] == 5
        # 半越界：offset=3, tail=100 → start 钳到 0，取流首 2 条
        data = dash_data.get_run_events(proot, self.RUN_ID, tail=100, offset_from_end=3)
        assert [e.get("seq") for e in data["events"] if "seq" in e] == [0, 1]
        # 负 offset 按 0 钳制（等价现状）
        data = dash_data.get_run_events(proot, self.RUN_ID, tail=2, offset_from_end=-5)
        assert len(data["events"]) == 2

    def test_status_and_total_unaffected_by_window(self, tmp_path):
        proot = make_project(tmp_path)
        self._write_run(proot, 7)
        full = dash_data.get_run_events(proot, self.RUN_ID, tail=1000)
        for offset in (0, 2, 5, 50):
            data = dash_data.get_run_events(proot, self.RUN_ID, tail=3, offset_from_end=offset)
            assert data["status"] == full["status"] == "done"
            assert data["total_events"] == full["total_events"] == 8
            assert data["exists"] is True

    def test_route_passes_offset_from_end(self, server_fx):
        proot, srv = server_fx
        # 缺省：既有响应不变（尾部 2 条，含 result 终态）
        status, data = srv.get("/api/runs/impl-myspec-1780000000?project=proj-a&tail=2")
        assert status == 200
        assert data["status"] == "done"
        assert data["total_events"] == 3
        assert data["events"][-1]["type"] == "result"
        # 透传 offset_from_end：跳过终态行，窗口止于心跳/正文事件
        status, data = srv.get(
            "/api/runs/impl-myspec-1780000000?project=proj-a&tail=2&offset_from_end=1"
        )
        assert status == 200
        assert data["total_events"] == 3
        assert data["events"][-1]["type"] == "assistant"
        assert data["events"][-1]["type"] != "result"
