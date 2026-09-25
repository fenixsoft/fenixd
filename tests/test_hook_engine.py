"""
tests/test_hook_engine.py — hook_engine 单元/集成测试（add-spec-hooks tasks 6.1）。

覆盖：
- 1.1/1.2 match_hooks 匹配矩阵（全局/spec/多消费者/enabled=false）
- 2.1–2.6 七动作核心行为（restart-daemon commit noop commit-push push webhook shell）
- 1.3 审计记录字段校验
- 1.5 失败告警写入 admin_store
"""
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.hook_engine import (
    HookEngine, match_hooks, read_hook_audit, render_message_template,
    validate_hook_entry, validate_hooks_config, DETAIL_LIMIT,
    STATUS_SUCCESS, STATUS_NOOP, STATUS_SKIPPED, STATUS_FAILURE,
)


def _audit_has(proot, hook_id, status=None, timeout=3.0):
    """轮询 hook 审计直到出现该 hook（可选 status）或超时。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for r in read_hook_audit(proot):
            if r.get("hook_id") == hook_id and (status is None or r.get("status") == status):
                return True
        time.sleep(0.05)
    return False


def _make_repo(tmpdir: Path) -> Path:
    """创建临时 git 仓库并做一次初始提交，返回项目根。"""
    proot = tmpdir / "proj"
    (proot / ".fenix").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proot, check=True)
    subprocess.run(["git", "config", "user.email", "test@fenix.dev"], cwd=proot, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=proot, check=True)
    (proot / "a.txt").write_text("hello")
    subprocess.run(["git", "add", "-A"], cwd=proot, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=proot, check=True)
    return proot


class TestValidateHooks(unittest.TestCase):
    """validate_hook_entry / validate_hooks_config 校验矩阵（tasks 1.1 / 4.2）。"""

    def test_valid_entries(self):
        ok = [
            {"id": "h1", "enabled": True, "events": ["done"], "action": "commit"},
            {"id": "h2", "events": ["blocked"], "action": "webhook", "url": "https://ex.com/h"},
            {"id": "h3", "events": ["ready", "done"], "action": "shell", "command": "echo ok"},
            {"id": "h4", "events": ["testing"], "action": "restart-daemon"},
            {"id": "h5", "events": ["verified"], "action": "push"},
            {"id": "h6", "events": ["done"], "action": "commit-push", "message": "hook: {spec}"},
            {"id": "h7", "events": ["blocked"], "action": "restart-dashboard", "target": "test-1"},
        ]
        for e in ok:
            self.assertIsNone(validate_hook_entry(e), msg=f"expected valid: {e}")

    def test_invalid_events_empty(self):
        self.assertIn("非空数组", validate_hook_entry({"events": [], "action": "commit"}))

    def test_invalid_events_bad_type(self):
        self.assertIn("非法事件类型", validate_hook_entry({"events": ["bad"], "action": "commit"}))

    def test_invalid_action(self):
        self.assertIn("action 非法", validate_hook_entry({"events": ["done"], "action": "nope"}))

    def test_webhook_no_url(self):
        self.assertIn("url", validate_hook_entry({"events": ["done"], "action": "webhook"}))

    def test_shell_no_command(self):
        self.assertIn("command", validate_hook_entry({"events": ["done"], "action": "shell"}))

    def test_not_dict(self):
        self.assertIn("对象", validate_hook_entry("bad"))

    def test_hooks_specs_not_object_rejected(self):
        """hooks.specs 顶层非对象（如列表）整体拒绝（dashboard 侧裁剪后补单元用例）。"""
        err = validate_hooks_config({"hooks": {"specs": ["s1"]}})
        self.assertIn("hooks.specs 必须为对象", err)

    def test_all_events_valid(self):
        from core.state_machine import SpecStatus
        for ev in SpecStatus.ALL:
            self.assertIsNone(validate_hook_entry({"events": [ev], "action": "commit"}), msg=ev)


class TestValidateHooksConfig(unittest.TestCase):
    def test_none_hooks(self):
        self.assertIsNone(validate_hooks_config({}))
        self.assertIsNone(validate_hooks_config({"hooks": None}))

    def test_valid_hooks_config(self):
        cfg = {"hooks": {"global": [{"events": ["done"], "action": "push"}],
                         "specs": {"s1": [{"events": ["blocked"], "action": "webhook", "url": "https://x.com"}]}}}
        self.assertIsNone(validate_hooks_config(cfg))

    def test_bad_global_entry(self):
        cfg = {"hooks": {"global": [{"events": ["done"], "action": "webhook"}]}}
        err = validate_hooks_config(cfg)
        self.assertIn("hooks.global[0]", err)
        self.assertIn("url", err)

    def test_bad_spec_entry(self):
        cfg = {"hooks": {"specs": {"s1": [{"events": ["done"], "action": "shell"}]}}}
        err = validate_hooks_config(cfg)
        self.assertIn("hooks.specs.s1[0]", err)
        self.assertIn("command", err)


class TestMatchHooks(unittest.TestCase):
    """match_hooks 事件匹配矩阵（tasks 1.2）。"""

    def setUp(self):
        self.config = {
            "hooks": {
                "global": [
                    {"id": "g1", "events": ["done"], "action": "restart-daemon"},
                    {"id": "g2", "events": ["done", "blocked"], "action": "commit"},
                    {"id": "g3", "events": ["ready"], "action": "push"},
                ],
                "specs": {
                    "s1": [
                        {"id": "s1a", "events": ["done"], "action": "commit-push"},
                    ],
                },
            }
        }

    def test_global_only(self):
        matched = match_hooks(self.config, "s2", "done")
        ids = [h["id"] for h, _ in matched]
        self.assertEqual(ids, ["g1", "g2"])

    def test_spec_and_global(self):
        matched = match_hooks(self.config, "s1", "done")
        ids = [h["id"] for h, _ in matched]
        self.assertEqual(ids, ["g1", "g2", "s1a"])
        scopes = [s for _, s in matched]
        self.assertEqual(scopes, ["global", "global", "spec"])

    def test_spec_only(self):
        matched = match_hooks(self.config, "s1", "blocked")
        ids = [h["id"] for h, _ in matched]
        self.assertEqual(ids, ["g2"])  # s1a not subscribed to blocked

    def test_no_match(self):
        self.assertEqual(match_hooks(self.config, "s1", "testing"), [])

    def test_disabled_included(self):
        """enabled=false 仍被匹配（由执行阶段记录 skipped）。"""
        cfg = {"hooks": {"global": [{"id": "d1", "enabled": False, "events": ["done"], "action": "commit"}]}}
        matched = match_hooks(cfg, "s1", "done")
        self.assertEqual([h["id"] for h, _ in matched], ["d1"])


class TestRenderTemplate(unittest.TestCase):
    def test_default_template(self):
        self.assertEqual(render_message_template("", "spec1", "done"), "[fenix] hook: spec1 done")

    def test_custom_template(self):
        out = render_message_template("[fenix] {spec} {event}", "my-spec", "blocked")
        self.assertEqual(out, "[fenix] my-spec blocked")

    def test_unknown_var_preserved(self):
        out = render_message_template("{spec}-{unknown}-{event}", "a", "b")
        self.assertEqual(out, "a-{unknown}-b")


class TestSevenActions(unittest.TestCase):
    """七动作核心行为测试（tasks 2.1–2.6）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = _make_repo(self.tmpdir)
        self.config = {"project": {"name": "test-proj"}, "hooks": {"global": [], "specs": {}}}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _eng(self, **overrides) -> HookEngine:
        cfg = {**self.config, **overrides}
        return HookEngine(self.proot, cfg, logger=MagicMock())

    # ── restart-daemon (2.1) ───────────────────────────────────────

    def test_restart_daemon_creates_file(self):
        eng = self._eng()
        # fix-supervisor-hosting-chain D4：写 restart_request 前校验 supervisor
        # 存在；测试环境无真实 supervisor，patch 为在跑以验证写入路径
        with mock.patch("core.fenix_session.supervisor_running", return_value=True):
            ok, detail = eng._action_restart_daemon()
        self.assertTrue(ok, detail)
        self.assertIn("restart_request", detail)
        self.assertTrue((self.proot / ".fenix" / "restart_request").exists())

    # ── commit (2.2) ───────────────────────────────────────────────

    def test_commit_noop_when_clean(self):
        eng = self._eng()
        status, detail = eng._action_commit({"events": ["done"], "action": "commit"}, "s1", "done")
        self.assertEqual(status, STATUS_NOOP)
        self.assertIn("无变更", detail)

    def test_commit_success_with_change(self):
        # fix-hook-commit-pathsweep：缺省仅提交收口产物路径（spec/ 等），
        # 工作区无关根目录文件不再被卷入
        spec_dir = self.proot / "spec" / "changes" / "s1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("change")
        (self.proot / "new.txt").write_text("unrelated")
        eng = self._eng()
        status, detail = eng._action_commit({"events": ["done"], "action": "commit"}, "s1", "done")
        self.assertEqual(status, STATUS_SUCCESS)
        self.assertIn("已提交", detail)
        res = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(self.proot),
                             capture_output=True, text=True)
        self.assertIn("[fenix] hook: s1 done", res.stdout)

    def test_commit_custom_message(self):
        spec_dir = self.proot / "spec" / "changes" / "add-x"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("y")
        eng = self._eng()
        cfg = {"events": ["done"], "action": "commit", "message": "feat({spec}): {event}"}
        status, _ = eng._action_commit(cfg, "add-x", "done")
        self.assertEqual(status, STATUS_SUCCESS)
        log = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(self.proot),
                             capture_output=True, text=True)
        self.assertIn("feat(add-x): done", log.stdout)

    # ── push (2.3) ─────────────────────────────────────────────────

    def test_push_no_remote_fails(self):
        eng = self._eng()
        status, detail = eng._action_push()
        self.assertEqual(status, STATUS_FAILURE)
        self.assertIn("push 失败", detail)

    def test_push_success_bare_remote(self):
        bare = self.tmpdir / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=str(self.proot), check=True)
        subprocess.run(["git", "push", "-uq", "origin", "main"], cwd=str(self.proot), check=True)
        eng = self._eng()
        status, detail = eng._action_push()
        self.assertEqual(status, STATUS_SUCCESS, detail)

    def test_commit_push_commit_noop_push_success(self):
        bare = self.tmpdir / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
        subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=str(self.proot), check=True)
        subprocess.run(["git", "push", "-uq", "origin", "main"], cwd=str(self.proot), check=True)
        eng = self._eng()
        cfg = {"events": ["done"], "action": "commit-push"}
        status, detail = eng._action_commit_push(cfg, "s1", "done")
        self.assertEqual(status, STATUS_SUCCESS)
        self.assertIn("commit noop", detail)

    def test_commit_push_failure_on_push(self):
        eng = self._eng()
        (self.proot / "t.txt").write_text("v")
        status, detail = eng._action_commit_push({"events": ["done"], "action": "commit-push"}, "s1", "done")
        self.assertEqual(status, STATUS_FAILURE)
        self.assertIn("本地提交保留", detail)

    # ── webhook (2.5) ──────────────────────────────────────────────

    def test_webhook_2xx_success(self):
        class H(BaseHTTPRequestHandler):
            body = None
            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                type(self).body = self.rfile.read(n)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            def log_message(self, *a): pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True); t.start()
        try:
            eng = self._eng()
            cfg = {"events": ["done"], "action": "webhook", "url": f"http://127.0.0.1:{port}/cb"}
            status, detail = eng._action_webhook(cfg, "s1", "verified", "done", {})
            self.assertEqual(status, STATUS_SUCCESS)
            payload = json.loads(H.body)
            self.assertEqual(payload["spec"], "s1")
            self.assertEqual(payload["event"], "done")
            self.assertEqual(payload["project"], "test-proj")
            self.assertEqual(payload["from_status"], "verified")
        finally:
            srv.shutdown(); srv.server_close()

    def test_webhook_non_2xx_fails(self):
        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(500)
                self.end_headers()
            def log_message(self, *a): pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True); t.start()
        try:
            eng = self._eng()
            cfg = {"events": ["done"], "action": "webhook", "url": f"http://127.0.0.1:{port}/cb"}
            status, _ = eng._action_webhook(cfg, "s1", "verified", "done", {})
            self.assertEqual(status, STATUS_FAILURE)
        finally:
            srv.shutdown(); srv.server_close()

    def test_webhook_timeout_fails(self):
        eng = self._eng()
        # 连接不存在的端口 → timeout → failure
        cfg = {"events": ["done"], "action": "webhook", "url": "http://127.0.0.1:19999/x", "timeout_seconds": 1}
        status, detail = eng._action_webhook(cfg, "s1", "verified", "done", {})
        self.assertEqual(status, STATUS_FAILURE)
        self.assertIn("失败", detail)

    # ── shell (2.6) ────────────────────────────────────────────────

    def test_shell_env_injection(self):
        eng = self._eng()
        cfg = {"events": ["done"], "action": "shell", "command": "echo $FENIX_HOOK_EVENT-$FENIX_HOOK_SPEC > $FENIX_HOOK_PROJECT_ROOT/out.txt"}
        status, _ = eng._action_shell(cfg, "s1", "verified", "done", {})
        self.assertEqual(status, STATUS_SUCCESS)
        out = (self.proot / "out.txt").read_text().strip()
        self.assertEqual(out, "done-s1")

    def test_shell_timeout_fails(self):
        eng = self._eng()
        cfg = {"events": ["done"], "action": "shell", "command": "sleep 30", "timeout_seconds": 1}
        status, detail = eng._action_shell(cfg, "s1", "verified", "done", {})
        self.assertEqual(status, STATUS_FAILURE)
        self.assertIn("超时", detail)

    def test_shell_nonzero_exit_fails(self):
        eng = self._eng()
        cfg = {"events": ["done"], "action": "shell", "command": "exit 1"}
        status, detail = eng._action_shell(cfg, "s1", "verified", "done", {})
        self.assertEqual(status, STATUS_FAILURE)
        self.assertIn("退出码 1", detail)


class TestAudit(unittest.TestCase):
    """审计记录字段校验（tasks 1.3）+ 启用前不记录审计。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = self.tmpdir / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        self.config = {"project": {"name": "a"}, "hooks": {"global": [], "specs": {}}}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_audit_record_fields(self):
        eng = HookEngine(self.proot, self.config, logger=MagicMock())
        eng._audit("s1", "done", "verified", "done", "h1", "commit",
                    "global", STATUS_SUCCESS, "ok", 1.23)
        recs = read_hook_audit(self.proot)
        self.assertEqual(len(recs), 1)
        r = recs[0]
        self.assertEqual(r["spec"], "s1")
        self.assertEqual(r["event"], "done")
        self.assertEqual(r["from_status"], "verified")
        self.assertEqual(r["to_status"], "done")
        self.assertEqual(r["hook_id"], "h1")
        self.assertEqual(r["action"], "commit")
        self.assertEqual(r["scope"], "global")
        self.assertEqual(r["status"], STATUS_SUCCESS)
        self.assertEqual(r["detail"], "ok")
        self.assertIn("ts", r)
        self.assertGreaterEqual(r["duration_ms"], 0)

    def test_read_audit_spec_filter(self):
        eng = HookEngine(self.proot, self.config, logger=MagicMock())
        eng._audit("s1", "done", None, "done", "h1", "commit", "global", STATUS_SUCCESS, "ok", 1)
        eng._audit("s2", "blocked", None, "blocked", "h2", "push", "spec", STATUS_SUCCESS, "ok", 2)
        recs = read_hook_audit(self.proot, spec="s1")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["spec"], "s1")

    def test_read_audit_limit(self):
        eng = HookEngine(self.proot, self.config, logger=MagicMock())
        for i in range(5):
            eng._audit(f"s{i}", "done", None, "done", f"h{i}", "commit", "global", STATUS_SUCCESS, "ok", 1)
        recs = read_hook_audit(self.proot, limit=2)
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["hook_id"], "h4")


class TestFailureAlert(unittest.TestCase):
    """失败产生站内告警（task 1.5）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = self.tmpdir / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        self.config = {"project": {"name": "a"}, "hooks": {"global": [], "specs": {}}}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_failure_writes_alert(self):
        from core.admin_store import AdminStore
        store = AdminStore(self.proot)
        eng = HookEngine(self.proot, self.config, logger=MagicMock(), admin_store=store)
        eng._alert_failure("s1", "done", "shell", "spec", "bad cmd")
        alerts = json.loads((self.proot / ".fenix" / "admin_alerts.json").read_text())
        hook_fail = [a for a in alerts if a.get("signal_type") == "hook_failure"]
        self.assertTrue(hook_fail, "hook_failure alert not found")
        self.assertEqual(hook_fail[0]["severity"], "major")
        self.assertIn("s1", hook_fail[0]["description"])
        self.assertIn("shell", hook_fail[0]["description"])


class TestEndToEndDispatch(unittest.TestCase):
    """dispatch 全链：EventBus → 匹配 → 审计/告警/动作（tasks 1.2–1.5, 2.1–2.6）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = _make_repo(self.tmpdir)
        self.config = {"project": {"name": "t"}, "hooks": {
            "global": [{"id": "g1", "enabled": True, "events": ["done"], "action": "restart-daemon"}],
            "specs": {"s1": [{"id": "s1a", "enabled": False, "events": ["done"], "action": "commit"}]},
        }}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dispatch_fires_all_matches(self):
        eng = HookEngine(self.proot, self.config, logger=MagicMock())
        # fix-supervisor-hosting-chain D4：restart-daemon 写请求前校验 supervisor
        # 存在；测试环境无真实 supervisor，patch 为在跑以验证全链成功语义
        with mock.patch("core.fenix_session.supervisor_running", return_value=True):
            eng.dispatch("s1", "verified", "done", {})
            self.assertTrue(_audit_has(self.proot, "g1"))
            self.assertTrue(_audit_has(self.proot, "s1a"))
        recs = read_hook_audit(self.proot)
        statuses = {r["hook_id"]: r["status"] for r in recs}
        self.assertEqual(statuses["g1"], STATUS_SUCCESS)
        self.assertEqual(statuses["s1a"], STATUS_SKIPPED)
        self.assertTrue((self.proot / ".fenix" / "restart_request").exists())

    def test_failure_dispatch_writes_alert(self):
        self.config["hooks"]["global"].append(
            {"id": "g2", "enabled": True, "events": ["done"], "action": "webhook",
             "url": "http://127.0.0.1:19999/x", "timeout_seconds": 1})
        eng = HookEngine(self.proot, self.config, logger=MagicMock())
        eng.dispatch("s1", "verified", "done", {})
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not (
                self.proot / ".fenix" / "admin_alerts.json").exists():
            time.sleep(0.05)
        alerts = json.loads((self.proot / ".fenix" / "admin_alerts.json").read_text())
        hook_fail = [a for a in alerts if a.get("signal_type") == "hook_failure"]
        self.assertTrue(hook_fail)
        self.assertIn("hook 动作失败", hook_fail[0]["description"])

    def test_dispatch_no_matching_hooks_no_audit_file(self):
        cfg = {"project": {"name": "t"}, "hooks": {"global": [], "specs": {}}}
        eng = HookEngine(self.proot, cfg, logger=MagicMock())
        eng.dispatch("s1", "verified", "testing", {})
        audit_file = self.proot / ".fenix" / "hook_audit.jsonl"
        self.assertFalse(audit_file.exists())


class TestAllDoneEvent(unittest.TestCase):
    """「全部 SPEC 完成」项目级事件（fix-hook-all-specs-done）。

    语义：任一 spec 状态迁移到 done/pushed 时，若 STATE 中全部 spec 均处于
    成功终态（done/pushed，与前端 PRIORITY_TERMINAL 同口径），以 event=all-done
    触发全局 hook——供用户在项目级 hook 界面挂 restart-daemon，获得
    「全部 SPEC 自然收口后」的安全重启点（替代不可靠的排水窗口等待）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True)
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", self.tmpdir], check=False))

    def _write_state(self, statuses):
        lines = ["# Fenix Project State", "", "## Specs", ""]
        for name, st in statuses.items():
            lines += [f"### {name}", f"- status: {st}", ""]
        (self.proot / ".fenix" / "STATE.md").write_text(
            "\n".join(lines), encoding="utf-8")

    def _engine(self):
        cfg = {"hooks": {"global": [
            {"id": "g-all", "events": ["all-done"], "action": "restart-daemon"},
        ], "specs": {}}}
        return HookEngine(self.proot, cfg, logger=None, admin_store=MagicMock())

    @staticmethod
    def _wait_for(cond, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.05)
        return False

    def test_validate_accepts_all_done(self):
        self.assertIsNone(validate_hook_entry(
            {"events": ["all-done"], "action": "restart-daemon"}))
        self.assertIsNone(validate_hooks_config(
            {"global": [{"id": "x", "events": ["all-done"],
                         "action": "restart-daemon"}], "specs": {}}))

    def test_match_global_scope_only(self):
        """all-done 是项目级事件：仅全局 hook 匹配，spec 级订阅被忽略。"""
        cfg = {"hooks": {
            "global": [{"id": "g1", "events": ["all-done"], "action": "restart-daemon"}],
            "specs": {"s1": [{"id": "s1a", "events": ["all-done"],
                              "action": "commit"}]},
        }}
        matched = match_hooks(cfg, "*", "all-done")
        self.assertEqual([(h["id"], s) for h, s in matched], [("g1", "global")])

    def test_fires_when_all_specs_terminal(self):
        self._write_state({"spec-a": "done", "spec-b": "pushed"})
        engine = self._engine()
        # fix-supervisor-hosting-chain D4：restart-daemon 消费方校验——测试环境
        # 无真实 supervisor，patch 为在跑以验证 all-done 触发成功路径
        with mock.patch("core.fenix_session.supervisor_running", return_value=True):
            engine.dispatch("spec-b", "testing", "pushed", {})
            self.assertTrue(self._wait_for(
                lambda: (self.proot / ".fenix" / "restart_request").exists()),
                "全部 SPEC 终态后未触发 all-done hook（restart_request 未写入）")
        audit = [a for a in read_hook_audit(self.proot) if a.get("event") == "all-done"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["status"], STATUS_SUCCESS)
        self.assertEqual(audit[0]["scope"], "global")

    def test_not_fired_while_any_spec_active(self):
        self._write_state({"spec-a": "implementing", "spec-b": "pushed"})
        engine = self._engine()
        engine.dispatch("spec-b", "testing", "pushed", {})
        # 非全员终态 → 不评估 all-done，dispatch 内无并发线程，同步断言即可
        self.assertFalse((self.proot / ".fenix" / "restart_request").exists(),
                         "仍有进行中 spec 时不应触发 all-done")
        self.assertEqual([a for a in read_hook_audit(self.proot)
                          if a.get("event") == "all-done"], [])

    def test_not_fired_while_spec_blocked(self):
        self._write_state({"spec-a": "blocked", "spec-b": "pushed"})
        engine = self._engine()
        engine.dispatch("spec-b", "testing", "pushed", {})
        self.assertFalse((self.proot / ".fenix" / "restart_request").exists())

    def test_fires_once_until_spec_leaves_terminal(self):
        """全员终态期间去重只发一次；任一 spec 离开终态后复位可再发。

        每次迁移前先改 STATE（对齐真实时序：状态机先落盘、EventBus 再派发）。
        """
        self._write_state({"spec-a": "done", "spec-b": "testing"})
        engine = self._engine()
        # ① spec-b: testing → pushed，全员终态 → 发
        self._write_state({"spec-a": "done", "spec-b": "pushed"})
        engine.dispatch("spec-b", "testing", "pushed", {})
        self.assertTrue(self._wait_for(lambda: len(
            [a for a in read_hook_audit(self.proot)
             if a.get("event") == "all-done"]) == 1))
        # ② spec-b: done → pushed（STATE 已是 pushed，a/b 均终态）→ 去重不发
        engine.dispatch("spec-b", "done", "pushed", {})
        # 去重路径不派发线程，同步断言
        self.assertEqual(len([a for a in read_hook_audit(self.proot)
                              if a.get("event") == "all-done"]), 1)
        # ③ 打回：spec-b pushed → implementing → 复位去重标志
        self._write_state({"spec-a": "done", "spec-b": "implementing"})
        engine.dispatch("spec-b", "pushed", "implementing", {})
        # 复位路径（非终态迁移）不派发线程，同步断言
        self.assertEqual(len([a for a in read_hook_audit(self.proot)
                              if a.get("event") == "all-done"]), 1)
        # ④ 再收口：spec-b implementing → pushed → 再发
        self._write_state({"spec-a": "done", "spec-b": "pushed"})
        engine.dispatch("spec-b", "implementing", "pushed", {})
        self.assertTrue(self._wait_for(lambda: len(
            [a for a in read_hook_audit(self.proot)
             if a.get("event") == "all-done"]) == 2))


class TestAllDoneRestartOnce(unittest.TestCase):
    """one-shot 重启 hook（hook-restart-once）。

    all-done → restart-daemon 触发成功后写 .fenix/hook_cleanup_request.json
    清理标记；daemon 重启（HookEngine 重新实例化）时启动清扫自动摘除该
    hook——项目级/用户级 config.yaml 分别处理，内存视图同步过滤。
    """

    PROJECT_HOOKS = {
        "hooks": {
            "global": [
                {"id": "h-alldone1", "enabled": True, "events": ["all-done"],
                 "action": "restart-daemon"},
                {"id": "h-keep", "events": ["done"], "action": "commit"},
            ],
            "specs": {
                "s1": [{"id": "h-spec1", "events": ["blocked"],
                        "action": "webhook", "url": "http://x/"}],
            },
        }
    }

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = _make_repo(self.tmpdir)
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", self.tmpdir], check=False))
        # 用户级配置常量必须 patch（用户级配置敏感测试约定，禁触真实 ~/.fenix）
        self.user_dir = self.tmpdir / "fake-home-fenix"
        self.user_dir.mkdir(parents=True)
        p = patch("core.config.USER_CONFIG_DIR", self.user_dir)
        p.start()
        self.addCleanup(p.stop)
        self.marker = self.proot / ".fenix" / "hook_cleanup_request.json"
        self.proj_cfg = self.proot / ".fenix" / "config.yaml"
        self.user_cfg = self.user_dir / "config.yaml"

    def _write_proj_cfg(self):
        self.proj_cfg.write_text(
            "# Fenix 配置文件\n# 头注释应被清扫保留\n\n"
            "hooks:\n"
            "  global:\n"
            "  - id: h-alldone1\n"
            "    enabled: true\n"
            "    events:\n"
            "    - all-done\n"
            "    action: restart-daemon\n"
            "  - id: h-keep\n"
            "    events:\n"
            "    - done\n"
            "    action: commit\n"
            "  specs:\n"
            "    s1:\n"
            "    - id: h-spec1\n"
            "      events:\n"
            "      - blocked\n"
            "      action: webhook\n"
            "      url: http://x/\n",
            encoding="utf-8")

    def _write_user_cfg(self):
        self.user_cfg.write_text(
            "hooks:\n"
            "  global:\n"
            "  - id: h-ualldone\n"
            "    events:\n"
            "    - all-done\n"
            "    action: restart-daemon\n",
            encoding="utf-8")

    def _engine(self):
        cfg = {"hooks": {
            "global": [
                {"id": "h-alldone1", "enabled": True, "events": ["all-done"],
                 "action": "restart-daemon"},
                {"id": "h-keep", "events": ["done"], "action": "commit"},
            ],
            "specs": {"s1": [{"id": "h-spec1", "events": ["blocked"],
                              "action": "webhook", "url": "http://x/"}]},
        }}
        return HookEngine(self.proot, cfg, logger=MagicMock())

    def test_fire_writes_cleanup_marker(self):
        eng = self._engine()
        # fix-supervisor-hosting-chain D4：restart-daemon 消费方校验——测试环境
        # 无真实 supervisor，patch 为在跑以验证 one-shot 清理标记成功路径
        with mock.patch("core.fenix_session.supervisor_running", return_value=True):
            eng._execute_action(
                {"id": "h-alldone1", "events": ["all-done"],
                 "action": "restart-daemon"},
                "global", "*", None, "all-done", {})
        self.assertTrue((self.proot / ".fenix" / "restart_request").exists())
        data = json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertEqual(data["hook_ids"], ["h-alldone1"])
        audit = [a for a in read_hook_audit(self.proot)
                 if a.get("event") == "all-done"]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["status"], STATUS_SUCCESS)
        self.assertIn("one-shot", audit[0]["detail"])

    def test_fire_non_alldone_no_marker(self):
        """普通 done 事件触发的 restart-daemon 不写清理标记（保持常驻）。"""
        eng = self._engine()
        eng._execute_action(
            {"id": "h-r", "events": ["done"], "action": "restart-daemon"},
            "global", "s1", "testing", "done", {})
        self.assertFalse(self.marker.exists())

    def test_marker_merges_ids(self):
        """多个 all-done 重启 hook 并发触发时 ids 合并不互吞。"""
        eng = self._engine()
        self.marker.write_text(
            json.dumps({"ts": "t0", "hook_ids": ["h-a"]}), encoding="utf-8")
        self.assertIsNone(eng._mark_restart_cleanup("h-b"))
        data = json.loads(self.marker.read_text(encoding="utf-8"))
        self.assertEqual(sorted(data["hook_ids"]), ["h-a", "h-b"])

    def test_consume_on_engine_init_removes_hook(self):
        """重启后首个 HookEngine 实例化即清扫：两级配置 + 内存视图 + 删标记。"""
        self._write_proj_cfg()
        self._write_user_cfg()
        self.marker.write_text(json.dumps(
            {"ts": "t0", "hook_ids": ["h-alldone1", "h-ualldone"]}),
            encoding="utf-8")
        eng = self._engine()
        # 标记已消费
        self.assertFalse(self.marker.exists())
        # 项目级：h-alldone1 摘除，h-keep / h-spec1 保留，头注释保留
        text = self.proj_cfg.read_text(encoding="utf-8")
        self.assertNotIn("h-alldone1", text)
        self.assertIn("h-keep", text)
        self.assertIn("h-spec1", text)
        self.assertTrue(text.startswith("# Fenix 配置文件"))
        # 用户级：h-ualldone 摘除
        utext = self.user_cfg.read_text(encoding="utf-8")
        self.assertNotIn("h-ualldone", utext)
        # 内存视图同步过滤
        ids = [h["id"] for h in eng.config["hooks"]["global"]]
        self.assertNotIn("h-alldone1", ids)
        self.assertIn("h-keep", ids)
        self.assertEqual(eng.config["hooks"]["specs"]["s1"][0]["id"], "h-spec1")

    def test_consume_noop_without_marker(self):
        """无标记时启动不清动配置。"""
        self._write_proj_cfg()
        self._engine()
        self.assertIn("h-alldone1", self.proj_cfg.read_text(encoding="utf-8"))

    def test_consume_unknown_ids_noop_on_files(self):
        """标记里的 id 已不在配置（重复消费/手工移除）：文件不动，标记删除。"""
        self._write_proj_cfg()
        self.marker.write_text(
            json.dumps({"ts": "t0", "hook_ids": ["h-gone"]}), encoding="utf-8")
        eng = self._engine()
        self.assertFalse(self.marker.exists())
        self.assertIn("h-alldone1", self.proj_cfg.read_text(encoding="utf-8"))
        self.assertIn("h-alldone1", [h["id"] for h in eng.config["hooks"]["global"]])


if __name__ == "__main__":
    unittest.main()
