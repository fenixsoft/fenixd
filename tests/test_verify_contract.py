"""验证契约（.fenix/verify.yaml）测试：加载/构建/静态服务/BASE_URL 注入/双 scope。"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    StaticVerifyServer,
    load_verify_contract,
    probe_ready,
    provision_worktree_node_modules,
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
        self.addCallback = shutil.rmtree
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_file_returns_none(self):
        self.assertIsNone(load_verify_contract(self.tmp))

    def test_invalid_yaml_returns_none(self):
        _write(self.tmp, ".fenix/verify.yaml", "prepare: [unclosed")
        self.assertIsNone(load_verify_contract(self.tmp))

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

    def _contract(self, prepare):
        return load_verify_contract.__wrapped__ if False else _mk_contract(prepare)

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

    def test_links_missing_node_modules(self):
        _write(self.tmp, "main-tree/v3/package.json", "{}")
        (self.tmp / "main-tree" / "v3" / "node_modules").mkdir(parents=True)
        _write(self.tmp, "wt/v3/package.json", "{}")
        linked = provision_worktree_node_modules(
            self.tmp / "wt", self.tmp / "main-tree", ["v3"])
        self.assertEqual(linked, ["v3"])
        self.assertTrue((self.tmp / "wt" / "v3" / "node_modules").is_symlink())

    def test_skips_existing_and_missing(self):
        _write(self.tmp, "main-tree/v3/package.json", "{}")
        (self.tmp / "main-tree" / "v3" / "node_modules").mkdir(parents=True)
        _write(self.tmp, "wt/v3/package.json", "{}")
        (self.tmp / "wt" / "v3" / "node_modules").mkdir()
        _write(self.tmp, "wt/no-pkg/index.html", "x")
        linked = provision_worktree_node_modules(
            self.tmp / "wt", self.tmp / "main-tree", ["v3", "no-pkg"])
        self.assertEqual(linked, [])


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
        from core.state_machine import StateMachine
        sm = StateMachine(self.tmp / ".fenix" / "STATE.md", self.logger)
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

    def test_no_contract_falls_back_to_commands_start(self):
        """无契约：维持旧行为（无 commands.start → 不可达 + 说明）。"""
        self._scenarios()
        engine = self._mk_engine()
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("commands.start", note)
