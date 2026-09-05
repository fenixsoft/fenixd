"""test_verify_command_port.py — command 型验证端口注入（方案 A）+ 进程归属兜底（方案 B）。

事故回归背景（2026-09-05 add-merge-tree-rehearsal）：hint 端口被主树常驻
实例占用时，旧代码的「邻近上探 + 跳过启动前已监听端口」永远看不见自己
启动的实例（实例自绑 hint 被跳过 / 绑不上即退出），100% 假失败。修复后
框架分配空闲端口注入（{port} 占位符 + FENIX_VERIFY_PORT 环境变量），
实例永不与既有实例争抢端口。
"""

import json
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock

from core.verify_contract import _find_free_port, load_verify_contract


def _probe(url: str, timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "fenix-verify-probe"})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _dummy_http(port: int, directory: Path):
    """进程内假常驻实例（模拟主树 dashboard 占住 hint 端口）。"""
    handler = lambda *a, **kw: _QuietHandler(  # noqa: E731
        *a, directory=str(directory), **kw)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestCommandPortInjection(unittest.TestCase):
    """_ensure_app_reachable command+worktree 路径的端口注入与兜底发现。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()
        self.logger = MagicMock()

    def _mk_engine(self, config=None):
        from test_inplace_bug_repair import _mk_engine
        from core.state_machine import StateMachine
        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", self.logger)
        engine, _ = _mk_engine(self.tmp, self.logger, config)
        return engine

    def _scenarios(self, spec="spec-a"):
        p = (self.tmp / ".fenix" / "verify-progress" / spec
             / "test_scenarios.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([
            {"steps": [{"action": "navigate",
                        "value": "http://localhost:59999/"}]},
        ]), encoding="utf-8")
        return p

    def _git(self, *args):
        r = subprocess.run(["git", "-C", str(self.tmp), *args],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r

    def _init_repo_with_site(self):
        _write(self.tmp, "site/index.html", "fresh")
        self._git("init", "-q")
        self._git("config", "user.email", "t@fenix.local")
        self._git("config", "user.name", "T")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")

    def _contract_yaml(self, cmd: str, port_field=None, timeout=20):
        lines = ["serve:", "  kind: command", f"  cmd: {cmd}"]
        if port_field is not None:
            lines.append(f"  port: {port_field}")
        lines += ["ready:", "  url: /", "  expect: 200",
                  f"  timeout: {timeout}"]
        _write(self.tmp, ".fenix/verify.yaml", "\n".join(lines) + "\n")

    def _rewritten_url(self, spec="spec-a") -> str:
        data = json.loads(
            (self.tmp / ".fenix" / "verify-progress" / spec
             / "test_scenarios.json").read_text(encoding="utf-8"))
        return data[0]["steps"][0]["value"]

    def _stop_servers(self, engine, *specs):
        cache = engine._verification.__dict__.get(
            "_contract_static_servers", {})
        for s in specs:
            entry = cache.get(s)
            if entry:
                try:
                    entry["server"].stop()
                except Exception:
                    pass

    def test_incident_regression_occupied_hint_port(self):
        """事故回归：hint 端口被常驻实例占用，迁移后 cmd（{port}）不受影响。

        旧代码此场景 100% 假失败：实例绑不上 hint 即退出，或自绑 hint
        后被「跳过启动前已监听端口」的探测永远无视。迁移后实例起在框架
        分配的空闲端口上，常驻实例毫发无损（legacy port 字段并存不干扰）。
        """
        self._init_repo_with_site()
        hint = _find_free_port()
        resident = _dummy_http(hint, self.tmp)
        self.addCleanup(resident.server_close)
        self._contract_yaml(
            "python3 -m http.server {port} --bind 127.0.0.1",
            port_field=hint)
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        try:
            reachable, blocked, note = (
                engine._verification._ensure_app_reachable("spec-a"))
            self.assertTrue(reachable, note)
            url = self._rewritten_url()
            self.assertNotIn(f":{hint}/", url,
                             "场景不得指向被占 hint 端口")
            port = int(re.search(r":(\d+)/", url).group(1))
            self.assertTrue(_probe(f"http://127.0.0.1:{port}/"),
                            "注入端口实例应真实可达")
            self.assertTrue(_probe(f"http://127.0.0.1:{hint}/"),
                            "常驻实例应毫发无损")
        finally:
            self._stop_servers(engine, "spec-a")

    def test_unmigrated_cmd_occupied_port_fails_fast_with_diagnosis(self):
        """未迁移契约 + 端口被占：快速失败并给出可诊断报错（非盲等超时）。

        实例在硬编码端口上 EADDRINUSE 真的起不来——旧代码表现是 120s
        上探超时的模糊报错；新代码立即检出退出事实并指明修复方向。
        """
        self._init_repo_with_site()
        hint = _find_free_port()
        resident = _dummy_http(hint, self.tmp)
        self.addCleanup(resident.server_close)
        self._contract_yaml(
            f"python3 -m http.server {hint} --bind 127.0.0.1",
            port_field=hint)
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        reachable, blocked, note = (
            engine._verification._ensure_app_reachable("spec-a"))
        self.assertFalse(reachable)
        self.assertIn("退出", note)
        self.assertIn("FENIX_VERIFY_PORT", note)

    def test_placeholder_port_injection(self):
        """cmd 引用 {port} 占位符：实例起在框架分配的空闲端口上。"""
        self._init_repo_with_site()
        self._contract_yaml("python3 -m http.server {port} --bind 127.0.0.1")
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        try:
            reachable, blocked, note = (
                engine._verification._ensure_app_reachable("spec-a"))
            self.assertTrue(reachable, note)
            url = self._rewritten_url()
            self.assertNotIn("localhost:59999", url, "origin 应被改写")
            port = int(re.search(r":(\d+)/", url).group(1))
            self.assertTrue(_probe(f"http://127.0.0.1:{port}/"))
        finally:
            self._stop_servers(engine, "spec-a")

    def test_env_var_port_injection(self):
        """cmd 引用 $FENIX_VERIFY_PORT：环境变量注入通道等效可用。"""
        self._init_repo_with_site()
        self._contract_yaml(
            "python3 -m http.server $FENIX_VERIFY_PORT --bind 127.0.0.1")
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        try:
            reachable, blocked, note = (
                engine._verification._ensure_app_reachable("spec-a"))
            self.assertTrue(reachable, note)
            url = self._rewritten_url()
            port = int(re.search(r":(\d+)/", url).group(1))
            self.assertTrue(_probe(f"http://127.0.0.1:{port}/"))
        finally:
            self._stop_servers(engine, "spec-a")

    def test_ownership_discovery_finds_uninjected_instance(self):
        """方案 B 兜底：cmd 无视注入自绑固定端口（无 port 字段），进程归属
        发现仍能找到实例，验证继续（注：争抢副作用由迁移告警提示消除）。"""
        self._init_repo_with_site()
        fixed = _find_free_port()
        self._contract_yaml(
            f"python3 -m http.server {fixed} --bind 127.0.0.1")
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        try:
            reachable, blocked, note = (
                engine._verification._ensure_app_reachable("spec-a"))
            self.assertTrue(reachable, note)
            url = self._rewritten_url()
            port = int(re.search(r":(\d+)/", url).group(1))
            self.assertEqual(port, fixed, "应经进程归属发现自主端口")
        finally:
            self._stop_servers(engine, "spec-a")

    def test_failure_note_reports_exit_code(self):
        """实例启动即退出：报错区分「退出」并附 exit code 与注入提示。"""
        self._init_repo_with_site()
        self._contract_yaml("exit 7")
        self._scenarios()
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        reachable, blocked, note = (
            engine._verification._ensure_app_reachable("spec-a"))
        self.assertFalse(reachable)
        self.assertIn("退出", note)
        self.assertIn("7", note)
        self.assertIn("FENIX_VERIFY_PORT", note)

    def test_concurrent_specs_get_distinct_injected_ports(self):
        """并发验证隔离：同契约两个 spec 各起实例，注入端口互不相同。"""
        self._init_repo_with_site()
        self._contract_yaml("python3 -m http.server {port} --bind 127.0.0.1")
        self._scenarios("spec-a")
        self._scenarios("spec-b")
        engine = self._mk_engine(
            config={"verify": {"static_scope": "worktree"}})
        try:
            ra, _, na = engine._verification._ensure_app_reachable("spec-a")
            rb, _, nb = engine._verification._ensure_app_reachable("spec-b")
            self.assertTrue(ra, na)
            self.assertTrue(rb, nb)
            pa = int(re.search(r":(\d+)/", self._rewritten_url("spec-a")).group(1))
            pb = int(re.search(r":(\d+)/", self._rewritten_url("spec-b")).group(1))
            self.assertNotEqual(pa, pb, "并发实例端口必须隔离")
            self.assertTrue(_probe(f"http://127.0.0.1:{pa}/"))
            self.assertTrue(_probe(f"http://127.0.0.1:{pb}/"))
        finally:
            self._stop_servers(engine, "spec-a", "spec-b")


class TestMigrationWarning(unittest.TestCase):
    """契约加载迁移告警：cmd 未引用注入端口 → warning（不阻断）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()
        self.logger = MagicMock()

    def _load(self, cmd):
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: command\n"
               f"  cmd: {cmd}\n")
        return load_verify_contract(self.tmp, self.logger)

    def test_unreferenced_cmd_warns(self):
        contract = self._load("python3 app.py --serve --port 8787")
        self.assertIsNotNone(contract)
        warned = [str(c.args[1]) for c in self.logger.warning.call_args_list
                  if "FENIX_VERIFY_PORT" in str(c)]
        self.assertTrue(warned, "未引用注入端口的 cmd 应记迁移告警")

    def test_referenced_cmd_no_warning(self):
        self._load("python3 app.py --serve --port {port}")
        warned = [str(c) for c in self.logger.warning.call_args_list
                  if "FENIX_VERIFY_PORT" in str(c)]
        self.assertFalse(warned, "已引用注入端口不应告警")


if __name__ == "__main__":
    unittest.main()
