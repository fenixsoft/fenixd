"""验证契约（.fenix/verify.yaml）测试：加载/构建/静态服务/BASE_URL 注入/双 scope。"""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    DEFAULT_DEPS_MODE,
    ReadyProbe,
    StaticVerifyServer,
    load_verify_contract,
    probe_ready,
    provision_worktree_node_modules,
    resolve_deps_mode,
    rewrite_scenarios_origin,
    run_prepare_steps,
)

FULL_CONTRACT = """
prepare:
  - run: touch built.txt
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
  timeout: 30
"""


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _get(url: str, timeout: float = 3.0):
    return urllib.request.urlopen(url, timeout=timeout).status


class TestLoadContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_verify_contract(self.tmp))

    def test_legacy_layout_root_yaml_warns_and_returns_none(self):
        """旧布局守卫：.fenix 实体目录 + verify.yaml 留在项目根（洗白事故根因形态）——告警并按无契约回退。"""
        _write(self.tmp, "verify.yaml", FULL_CONTRACT)
        (self.tmp / ".fenix").mkdir(parents=True, exist_ok=True)
        logger = MagicMock()
        self.assertIsNone(load_verify_contract(self.tmp, logger=logger))
        self.assertTrue(logger.warning.called)
        self.assertIn("旧布局", str(logger.warning.call_args))

    def test_legacy_layout_symlink_still_loads_root_file(self):
        """.fenix 为自引用符号链接的历史布局：.fenix/verify.yaml 经链接解析到根文件，正常加载不告警。"""
        (self.tmp / "verify.yaml").write_text(FULL_CONTRACT, encoding="utf-8")
        (self.tmp / ".fenix").symlink_to(self.tmp, target_is_directory=True)
        logger = MagicMock()
        c = load_verify_contract(self.tmp, logger=logger)
        self.assertIsNotNone(c)
        self.assertFalse(logger.warning.called)

    def test_invalid_yaml_returns_none(self):
        _write(self.tmp, ".fenix/verify.yaml", "prepare: [unclosed")
        self.assertIsNone(load_verify_contract(self.tmp))

    def test_deps_mode_parsed_and_invalid_ignored(self):
        """verify.yaml deps_mode：合法值入契约；非法值告警并忽略（落 config/默认）。"""
        _write(self.tmp, ".fenix/verify.yaml", FULL_CONTRACT + "deps_mode: hardlink\n")
        self.assertEqual(load_verify_contract(self.tmp).deps_mode, "hardlink")
        logger = MagicMock()
        _write(self.tmp, ".fenix/verify.yaml", FULL_CONTRACT + "deps_mode: bogus\n")
        c2 = load_verify_contract(self.tmp, logger=logger)
        self.assertEqual(c2.deps_mode, "")
        self.assertTrue(logger.warning.called)

    def test_full_contract_parsed_with_defaults(self):
        _write(self.tmp, ".fenix/verify.yaml", FULL_CONTRACT)
        c = load_verify_contract(self.tmp)
        self.assertIsNotNone(c)
        self.assertEqual(len(c.prepare), 1)
        self.assertEqual(c.prepare[0].run, "touch built.txt")
        self.assertEqual(c.serve.kind, "static")
        self.assertEqual(c.serve.root, "site")
        self.assertEqual(c.ready.expect, 200)
        self.assertEqual(c.ready.timeout, 30)


class TestPrepareSteps(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_success_and_cwd_honored(self):
        _write(self.tmp, "v3/pkg.json", "{}")
        from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
        c = VerifyContract(
            prepare=[PrepareStep(run="touch built.txt", cwd="v3")],
            serve=ServeSpec(kind="static", root="v3"), ready=ReadyProbe())
        self.assertIsNone(run_prepare_steps(c, self.tmp))
        self.assertTrue((self.tmp / "v3" / "built.txt").exists())

    def test_failure_returns_step_error(self):
        from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
        c = VerifyContract(
            prepare=[PrepareStep(run="false")],
            serve=ServeSpec(kind="static", root="."), ready=ReadyProbe())
        err = run_prepare_steps(c, self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("第 1 步", err)


class TestStaticVerifyServer(unittest.TestCase):
    def test_serves_root_and_stops(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        _write(tmp, "index.html", "hello")
        srv = StaticVerifyServer(tmp)
        self.assertEqual(_get(f"{srv.base_url}/index.html"), 200)
        srv.stop()
        with self.assertRaises(Exception):
            _get(f"{srv.base_url}/index.html", timeout=2)


class TestRewriteOrigin(unittest.TestCase):
    def test_rewrites_all_origins_keeps_paths(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        scenarios = tmp / "test_scenarios.json"
        scenarios.write_text(json.dumps([
            {"steps": [{"action": "navigate",
                        "value": "http://localhost:8787/#/overview"}]},
        ]), encoding="utf-8")
        n = rewrite_scenarios_origin(scenarios, "http://127.0.0.1:19099")
        self.assertEqual(n, 1)
        data = json.loads(scenarios.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["steps"][0]["value"],
                         "http://127.0.0.1:19099/#/overview")

    def test_missing_file_zero(self):
        self.assertEqual(rewrite_scenarios_origin(Path("/nonexistent.json"), "x"), 0)


class TestProvisionNodeModules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_hardlink_mode_shares_inode(self):
        """hardlink 模式：os.link 副本与主树共享 inode（不占双倍空间）。"""
        _write(self.tmp, "main-tree/v3/package.json", "{}")
        src = (self.tmp / "main-tree" / "v3" / "node_modules" / "pkg")
        src.mkdir(parents=True)
        (src / "index.js").write_text("x", encoding="utf-8")
        _write(self.tmp, "wt/v3/package.json", "{}")
        linked = provision_worktree_node_modules(
            self.tmp / "wt", self.tmp / "main-tree", ["v3"], mode="hardlink")
        self.assertEqual(linked, ["v3"])
        wt_file = self.tmp / "wt" / "v3" / "node_modules" / "pkg" / "index.js"
        self.assertTrue(wt_file.exists())
        self.assertEqual(wt_file.stat().st_ino, (src / "index.js").stat().st_ino)

    def test_hardlink_falls_back_to_npm_without_main_tree(self):
        """hardlink 模式主树无 node_modules → 自动降级 prefer-offline（npm ci）。"""
        _write(self.tmp, "wt/v3/package.json", "{}")
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)

            class R:
                returncode = 0
            return R()

        with patch("core.verify_contract.subprocess.run",
                        side_effect=fake_run):
            linked = provision_worktree_node_modules(
                self.tmp / "wt", self.tmp / "main-tree", ["v3"], mode="hardlink")
        self.assertEqual(linked, ["v3"])
        self.assertEqual(calls[0][:2], ["npm", "ci"])

    def test_prefer_offline_runs_npm_ci(self):
        _write(self.tmp, "wt/v3/package.json", "{}")
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)

            class R:
                returncode = 0
            return R()

        with patch("core.verify_contract.subprocess.run",
                        side_effect=fake_run):
            linked = provision_worktree_node_modules(
                self.tmp / "wt", self.tmp / "main-tree", ["v3"],
                mode="prefer-offline")
        self.assertEqual(linked, ["v3"])
        self.assertIn("--prefer-offline", calls[0])

    def test_skips_existing_and_missing(self):
        _write(self.tmp, "main-tree/v3/package.json", "{}")
        (self.tmp / "main-tree" / "v3" / "node_modules").mkdir(parents=True)
        _write(self.tmp, "wt/v3/package.json", "{}")
        (self.tmp / "wt" / "v3" / "node_modules").mkdir()
        _write(self.tmp, "wt/no-pkg/index.html", "x")
        linked = provision_worktree_node_modules(
            self.tmp / "wt", self.tmp / "main-tree", ["v3", "no-pkg"],
            mode="hardlink")
        self.assertEqual(linked, [])

    def test_resolve_deps_mode_precedence(self):
        """deps_mode 解析优先级：verify.yaml > config > 默认。"""
        self.assertEqual(resolve_deps_mode(None, None), DEFAULT_DEPS_MODE)
        self.assertEqual(resolve_deps_mode(None, "hardlink"), "hardlink")
        contract = _mk_contract([])  # deps_mode 未指定
        self.assertEqual(resolve_deps_mode(contract, "hardlink"), "hardlink")
        contract.deps_mode = "prefer-offline"
        self.assertEqual(resolve_deps_mode(contract, "hardlink"),
                         "prefer-offline")


def _mk_contract(prepare):
    from core.verify_contract import PrepareStep, VerifyContract, ReadyProbe, ServeSpec
    return VerifyContract(
        prepare=[PrepareStep(run=p) for p in prepare],
        serve=ServeSpec(kind="static", root="site"), ready=ReadyProbe())


class TestEnsureAppReachableScopes(unittest.TestCase):
    """_ensure_app_reachable 集成：static 两类 scope 的构建/服务/改写链路。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()
        self.logger = MagicMock()

    def _mk_engine(self, config=None):
        from test_inplace_bug_repair import _mk_engine
        engine, _ = _mk_engine(self.tmp, self.logger, config)
        return engine

    def _scenarios(self):
        p = self.tmp / ".fenix" / "verify-progress" / "spec-a" / "test_scenarios.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([
            {"steps": [{"action": "navigate",
                        "value": "http://localhost:59999/v3/dist/"}]},
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

    def test_main_scope_builds_serves_rewrites(self):
        """方案 1：prepare 构建产物 → 主树起服务 → 场景 origin 改写 → 探针通过。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: mkdir -p site && touch site/index.html\n"
               "serve:\n  kind: static\n  root: site\n")
        self._scenarios()
        engine = self._mk_engine()
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertTrue(reachable, note)
        self.assertIn("主树", note)
        data = json.loads((self.tmp / ".fenix" / "verify-progress" / "spec-a"
                           / "test_scenarios.json").read_text(encoding="utf-8"))
        self.assertNotIn("localhost:59999",
                         data[0]["steps"][0]["value"], "场景 origin 应被改写")
        self.assertTrue((self.tmp / "site" / "index.html").exists(),
                        "prepare 应已执行")

    def test_worktree_scope_prepares_in_serving_worktree(self):
        """方案 2：serving worktree 内构建 + 服务，场景改写指向 worktree 实例。"""
        self._init_repo_with_site()
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo built > site/built.txt\n"
               "serve:\n  kind: static\n  root: site\n")
        self._scenarios()
        engine = self._mk_engine(config={"verify": {"static_scope": "worktree"}})
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertTrue(reachable, note)
        self.assertIn("worktree", note)
        serving = list((self.tmp / ".fenix" / "verify-serving").glob("spec-a-*"))
        self.assertEqual(len(serving), 1)
        self.assertTrue((serving[0] / "site" / "built.txt").exists(),
                        "prepare 应在 worktree 内执行")
        data = json.loads((self.tmp / ".fenix" / "verify-progress" / "spec-a"
                           / "test_scenarios.json").read_text(encoding="utf-8"))
        self.assertNotIn("localhost:59999", data[0]["steps"][0]["value"])

    def test_command_worktree_scope_launches_full_stack(self):
        """command + worktree：serving worktree 内 prepare、以 worktree 为 cwd
        启动真实服务进程，场景 origin 改写指向该实例，探针通过、可停止。"""
        from core.verify_contract import _find_free_port
        self._init_repo_with_site()
        port = _find_free_port()
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo built > site/built.txt\n"
               "serve:\n"
               "  kind: command\n"
               f"  cmd: python3 -m http.server {port} --bind 127.0.0.1\n"
               f"  port: {port}\n"
               "ready:\n  url: /\n  expect: 200\n  timeout: 20\n")
        self._scenarios()
        engine = self._mk_engine(config={"verify": {"static_scope": "worktree"}})
        try:
            reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
            self.assertTrue(reachable, note)
            self.assertIn("命令 worktree", note)
            serving = list((self.tmp / ".fenix" / "verify-serving").glob("spec-a-*"))
            self.assertEqual(len(serving), 1)
            self.assertTrue((serving[0] / "site" / "built.txt").exists(),
                            "prepare 应在 worktree 内执行")
            data = json.loads((self.tmp / ".fenix" / "verify-progress" / "spec-a"
                               / "test_scenarios.json").read_text(encoding="utf-8"))
            self.assertNotIn("localhost:59999", data[0]["steps"][0]["value"])
        finally:
            entry = engine._verification.__dict__.get(
                "_contract_static_servers", {}).get("spec-a")
            if entry:
                entry["server"].stop()

    def test_no_contract_falls_back_to_commands_start(self):
        """无契约：维持旧行为（无 commands.start → 不可达 + 说明）。"""
        self._scenarios()
        engine = self._mk_engine()
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("commands.start", note)


class TestContractFormReverseInference(unittest.TestCase):
    """契约形态按场景集 kind 反推（add-verify-multi-kind-runner PR2）：
    纯 cli 场景集跳过 serve/ready（不回退 commands.start）；含 web/api 必须。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()
        self.logger = MagicMock()

    def _mk_engine(self, config=None):
        from test_inplace_bug_repair import _mk_engine
        engine, _ = _mk_engine(self.tmp, self.logger, config)
        return engine

    def _scenarios(self, scenarios):
        p = self.tmp / ".fenix" / "verify-progress" / "spec-a" / "test_scenarios.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
        return p

    def test_pure_cli_skips_serve_and_prepare_fails_is_env_gate(self):
        """纯 cli：serve 全省；契约 prepare 失败仍是环境门。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: \"exit 1\"\nserve:\n  kind: static\n  root: site\n")
        self._scenarios([{"id": "c1", "kind": "cli",
                          "steps": [{"action": "run", "command": "true"}],
                          "assertions": []}])
        engine = self._mk_engine()
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("prepare 失败", note)

    def test_mixed_api_cli_requires_serve(self):
        """混合集（api+cli）：serve 必需，缺失时明确错误打回。"""
        self._scenarios([
            {"id": "a1", "kind": "api",
             "steps": [{"action": "http_request", "method": "GET",
                        "url": "http://stale:1/api"}], "assertions": []},
            {"id": "c1", "kind": "cli",
             "steps": [{"action": "run", "command": "true"}], "assertions": []},
        ])
        engine = self._mk_engine()
        engine._get_config = MagicMock(return_value="")
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("serve", note)
        self.assertIn("api", note)


class TestProbeVacuityCheck(unittest.TestCase):
    """就绪探针鉴别力自检：探针响应与任意不存在路径一致 → 判无鉴别力。

    add-spec-hooks 白屏 env 事故防复发（2026-09-06）：SPA fallback 对任意
    路径同响应，探针通过≠就绪。自检异常 fail-open 不牵连主判定。
    """

    def _serve(self, handler_cls) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_vacuous_probe_rejected(self):
        """SPA fallback 形态：任意路径回同一 HTML → 探针通过但判就绪失败。"""

        class Fallback(SimpleHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body><div id=root></div></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        base = self._serve(Fallback)
        ok, note = probe_ready(base, ReadyProbe(url="/", expect=200, timeout=3))
        self.assertFalse(ok)
        self.assertIn("无鉴别力", note)
        self.assertIn("真实 API 端点", note)  # 处方给出现例

    def test_discriminating_probe_passes(self):
        """API 探针 + 404 fallback：探针与任意路径响应不同 → 正常通过。"""

        class Api(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/api/"):
                    body = b'{"projects":[]}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                else:
                    body = b""
                    self.send_response(404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        base = self._serve(Api)
        ok, note = probe_ready(
            base, ReadyProbe(url="/api/projects", expect=200, timeout=3))
        self.assertTrue(ok)
        self.assertIn("就绪探针通过", note)

    def test_vacuity_check_failure_fails_open(self):
        """自检请求异常 → 放行主判定（探针通过仍算通过），不牵连。"""
        resp = MagicMock()
        resp.status = 200
        resp.read.return_value = b"probe-body"
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        with patch("core.verify_contract.urlopen",
                   side_effect=[resp, OSError("self-check boom")]):
            ok, note = probe_ready(
                "http://127.0.0.1:1", ReadyProbe(url="/", expect=200, timeout=1))
        self.assertTrue(ok)
        self.assertIn("就绪探针通过", note)
