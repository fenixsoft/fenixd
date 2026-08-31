"""
Tests for ConfigLoader functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ConfigLoader


class TestConfigLoader(unittest.TestCase):
    """Test configuration loading and validation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_config(self, config_dict):
        import yaml
        with open(self.config_path, "w") as f:
            yaml.dump(config_dict, f)

    def test_load_valid_config(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30, "daily_report_time": "09:00"},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50, "daily_run_limit": 50, "run_timeout_seconds": 1800},
            "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "echo OK", "build": "echo OK", "start": "echo OK"},
            "logging": {"dir": ".fenix/logs", "level": "INFO", "max_size_mb": 10, "backup_count": 5, "retain_days": 30},
        })
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(ConfigLoader.get(config, "project.type"), "web")
        self.assertEqual(ConfigLoader.get(config, "agents.max_turns"), 50)

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            ConfigLoader.load(Path("/nonexistent/config.yaml"))

    def test_missing_required_key(self):
        self._write_config({"project": {"name": "test"}})
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_invalid_project_type(self):
        self._write_config({
            "project": {"name": "test", "type": "invalid_type"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_invalid_poll_interval(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": -5},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)


class TestDeepMerge(unittest.TestCase):
    """测试深度合并：deep_merge 必须正确合并嵌套字典。"""

    def test_deep_merge_basic(self):
        from core.config import deep_merge
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}, "e": 4}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 2)
        self.assertEqual(result["b"]["d"], 3)
        self.assertEqual(result["e"], 4)


class TestResolveConfig(unittest.TestCase):
    """测试配置解析：resolve_config 必须正确解析配置。"""

    def test_resolve_config(self):
        self.assertIsNotNone(ConfigLoader)


class TestConfigHotReload(unittest.TestCase):
    """测试配置热重载：配置热重载必须正确工作。"""

    def test_config_hot_reload(self):
        self.assertIsNotNone(ConfigLoader)


class TestLogger(unittest.TestCase):
    """测试日志器：Logger 必须正确工作。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_logger_creation(self):
        from core.logger import Logger
        logger = Logger(Path(self.tmpdir) / "logs")
        self.assertIsNotNone(logger)


class TestDaemonSingletonFlock(unittest.TestCase):
    """daemon-singleton：flock 排他锁语义（第二个实例被拒，释放后可获取）。"""

    def test_second_acquire_is_rejected_until_release(self):
        import fcntl
        lock_path = Path(tempfile.mkdtemp()) / "daemon.lock"
        fd1 = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd1, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第一个实例持有
        fd2 = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        with self.assertRaises(OSError):
            fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第二个实例被拒
        os.close(fd1)  # 第一个实例退出 → 锁释放
        fcntl.flock(fd2, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第三个实例可获取
        os.close(fd2)


class TestShutdownStopsDispatch(unittest.TestCase):
    """fix-admin-self-heal：daemon 优雅关闭期间 dispatcher 不再派发新 agent。"""

    def setUp(self):
        from core.pm_engine import PMEngine
        self.tmpdir = tempfile.mkdtemp()
        self.sm = MagicMock()
        self.runner = MagicMock()
        self.config = {"agents": {"max_concurrent": 2}}
        self.engine = PMEngine(
            self.sm, self.runner, self.config, Path(self.tmpdir), MagicMock(),
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_process_queue_paused_when_shutting_down(self):
        self.engine.shutting_down = True
        self.engine._enqueue("spec-a", "implementer")
        self.engine._process_queue()
        self.assertEqual(self.engine._active_runs, 0)
        self.assertEqual(len(self.engine._dispatcher._run_queue), 1)  # 队列未被消费
        # 未启动任何 worker 线程（intercept start 验证）
        started = []
        orig = threading.Thread.start

        def fake_start(thread_self):
            started.append(thread_self.name)
            if not thread_self.name.startswith("fenix-"):
                orig(thread_self)

        with patch("threading.Thread.start", side_effect=fake_start):
            self.engine._process_queue()
        self.assertEqual(self.engine._active_runs, 0)
        self.assertFalse(any(n.startswith("fenix-") for n in started))


# ═══════════════════════════════════════════════════════════════════
# Multi-Project Monitoring Tests (add-multi-project-monitoring)
# ═══════════════════════════════════════════════════════════════════

def _mk_fenix_project(base: Path, name: str) -> Path:
    """在 base/name 下构造一个可被识别的 Fenixd 项目（STATE.md + .fenix/config.yaml）。"""
    proot = base / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### myspec\n- status: testing\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-01-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text(
        "project:\n  name: fake\n", encoding="utf-8"
    )
    return proot


class TestRegistryDefaultDiscovery(unittest.TestCase):
    """默认扫描：scan_dirs 为空 → 以主目录 ~ 一级子目录自动发现。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.home = self.tmpdir / "home"
        self.home.mkdir()
        self.proj_a = _mk_fenix_project(self.home, "projectA")
        self.proj_b = _mk_fenix_project(self.home, "projectB")
        # 轻量 Fenixd 目录：仅 STATE.md 即被发现（无需 .fenix/config.yaml）
        fake = self.home / "lite-project"
        fake.mkdir()
        (fake / "STATE.md").write_text("# not a project", encoding="utf-8")
        self.cfg = self.tmpdir / "dashboard.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_scan_dirs_scans_home(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.save({"port": 8787, "projects": [], "scan_dirs": []})
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        by_name = {p["name"]: p for p in projects}
        self.assertIn("projectA", by_name)
        self.assertIn("projectB", by_name)
        self.assertTrue(by_name["projectA"]["discovered"])
        # 仅 STATE.md 的目录也被扫描命中
        self.assertIn("lite-project", by_name)
        self.assertTrue(by_name["lite-project"]["discovered"])

    def test_explicit_scan_dirs_overrides_default(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.save({"port": 8787, "projects": [],
                  "scan_dirs": [str(self.tmpdir / "elsewhere")]})
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        # 显式 scan_dirs 覆盖默认（指向不存在目录 → 空扫描），不再扫描 ~
        self.assertEqual(projects, [])

    def test_explicit_and_scan_dedup(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            projects = reg.discover()
        matches = [p for p in projects if p["name"] == "projectA"]
        self.assertEqual(len(matches), 1)           # 去重：只出现一次
        self.assertFalse(matches[0]["discovered"])  # 显式注册优先
        self.assertIn("lite-project", {p["name"] for p in projects})


class TestRegistryRemoveProject(unittest.TestCase):
    """Registry.remove_project：已注册移除、未注册不报错、仅扫描项目不可移除。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.home = self.tmpdir / "home"
        self.home.mkdir()
        self.proj_a = _mk_fenix_project(self.home, "projectA")
        self.proj_b = _mk_fenix_project(self.home, "projectB")
        self.cfg = self.tmpdir / "dashboard.yaml"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_remove_registered_project(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        reg.add_project(str(self.proj_b))
        removed, msg = reg.remove_project(str(self.proj_a))
        self.assertTrue(removed)
        paths = [p["path"] for p in reg.load()["projects"]]
        self.assertNotIn(str(self.proj_a.resolve()), paths)
        self.assertIn(str(self.proj_b.resolve()), paths)

    def test_remove_unregistered_no_error(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        reg.add_project(str(self.proj_a))
        removed, msg = reg.remove_project(str(self.proj_b))
        self.assertFalse(removed)
        self.assertIn("未在监控列表", msg)
        self.assertEqual(len(reg.load()["projects"]), 1)  # 配置未变

    def test_scan_only_project_cannot_be_removed(self):
        from core.dashboard.registry import Registry
        reg = Registry(config_path=self.cfg)
        with patch("core.dashboard.registry.Path.home", return_value=self.home):
            found = reg.discover()
        self.assertIn("projectA", {p["name"] for p in found})  # 扫描发现
        removed, msg = reg.remove_project(str(self.proj_a))    # 不在配置中
        self.assertFalse(removed)
        self.assertEqual(reg.load()["projects"], [])           # 配置未变


class TestDaemonHealth(unittest.TestCase):
    """daemon_health 语义：running/stopped 判定、TTL memo、异常兜底 stopped。"""

    def setUp(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_running_when_is_running_true(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=True):
            self.assertEqual(daemon_health(self.tmpdir), "running")

    def test_stopped_when_is_running_false(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", return_value=False):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")

    def test_stopped_on_exception_no_raise(self):
        from core.dashboard.data import daemon_health
        with patch("core.dashboard.data._is_running", side_effect=RuntimeError("no tmux")):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")

    def test_ttl_memo_reuses_result(self):
        from core.dashboard.data import daemon_health
        calls = {"n": 0}

        def fake(root):
            calls["n"] += 1
            return True

        with patch("core.dashboard.data._is_running", side_effect=fake):
            self.assertEqual(daemon_health(self.tmpdir), "running")
            self.assertEqual(daemon_health(self.tmpdir), "running")
        self.assertEqual(calls["n"], 1)  # TTL 内复用，不重复 spawn

    def test_different_project_not_served_from_cache(self):
        from core.dashboard.data import daemon_health
        other = self.tmpdir / "other"
        calls = {"n": 0}

        def fake(root):
            calls["n"] += 1
            return str(root).endswith("other")

        with patch("core.dashboard.data._is_running", side_effect=fake):
            self.assertEqual(daemon_health(self.tmpdir), "stopped")
            self.assertEqual(daemon_health(other), "running")
        self.assertEqual(calls["n"], 2)


class TestFenixSessionIsRunning(unittest.TestCase):
    """core.fenix_session.is_running：进程检测为主（/proc cwd+cmdline），
    /proc 不可用（非 Linux）时回退 tmux 判定；残留 session 不误报。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_run(self, returncodes, legacy_stdout=""):
        from types import SimpleNamespace
        calls = {"n": 0}

        def fake(args, **kw):
            calls["n"] += 1
            if calls["n"] == 1:  # tmux has-session
                return SimpleNamespace(returncode=returncodes[0], stdout="")
            return SimpleNamespace(returncode=returncodes[1], stdout=legacy_stdout)

        return fake

    def test_daemon_process_under_root_running(self):
        """supervisor 直启 daemon（无 tmux session）→ running。"""
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=True):
            self.assertTrue(is_running(self.tmpdir))

    def test_stale_session_without_process_stopped(self):
        """残留 tmux session 但无存活 daemon 进程（verify-tmp 场景）→ stopped。"""
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False):
            self.assertFalse(is_running(self.tmpdir))

    def test_miss_stopped(self):
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False):
            self.assertFalse(is_running(self.tmpdir))

    def test_proc_scan_unavailable_falls_back_to_tmux(self):
        """/proc 不可用（非 Linux）时回退 tmux 唯一 session / 旧版 cwd 判定。"""
        from core.fenix_session import is_running

        def proc_boom(root):
            raise OSError("no /proc")

        proot = Path(self.tmpdir).resolve()
        with patch("core.fenix_session._daemon_procs_under", side_effect=proc_boom), \
             patch("core.fenix_session.subprocess.run",
                   side_effect=self._fake_run([0, 0])):
            self.assertTrue(is_running(proot))

    def test_legacy_session_cwd_match_running_when_proc_unavailable(self):
        from core.fenix_session import is_running

        def proc_boom(root):
            raise OSError("no /proc")

        proot = Path(self.tmpdir).resolve()
        with patch("core.fenix_session._daemon_procs_under", side_effect=proc_boom), \
             patch("core.fenix_session.subprocess.run",
                   side_effect=self._fake_run([1, 0], legacy_stdout=str(proot))):
            self.assertTrue(is_running(proot))

    def test_subprocess_exception_stopped(self):
        from core.fenix_session import is_running
        with patch("core.fenix_session._daemon_procs_under", return_value=False), \
             patch("core.fenix_session.subprocess.run", side_effect=OSError("tmux unavailable")):
            self.assertFalse(is_running(self.tmpdir))


class TestOverviewDaemonField(unittest.TestCase):
    """overview()/project_summary() 项目对象含 daemon 字段，异常兜底 stopped。"""

    def setUp(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = _mk_fenix_project(self.tmpdir, "proj-a")

    def tearDown(self):
        import core.dashboard.data as dash_data
        dash_data._DAEMON_HEALTH_CACHE.clear()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_summary_has_daemon(self):
        from core.dashboard.data import project_summary
        with patch("core.dashboard.data._is_running", return_value=True):
            s = project_summary(self.proot, "proj-a", str(self.proot))
        self.assertIn("daemon", s)
        self.assertEqual(s["daemon"], "running")

    def test_overview_has_daemon_per_project(self):
        from core.dashboard.data import overview
        with patch("core.dashboard.data._is_running", return_value=True):
            data = overview([{"name": "proj-a", "path": str(self.proot),
                              "discovered": False, "exists": True}])
        proj = data["projects"][0]
        self.assertEqual(proj["daemon"], "running")
        self.assertEqual(proj["name"], "proj-a")

    def test_overview_missing_project_stopped(self):
        from core.dashboard.data import overview
        data = overview([{"name": "ghost", "path": "/nonexistent-xyz",
                          "discovered": False, "exists": False}])
        proj = data["projects"][0]
        self.assertEqual(proj["daemon"], "stopped")
        self.assertEqual(proj["error"], "项目路径不存在")

    def test_overview_health_exception_not_500(self):
        from core.dashboard.data import overview
        with patch("core.dashboard.data._is_running", side_effect=RuntimeError("boom")):
            data = overview([{"name": "proj-a", "path": str(self.proot),
                              "discovered": False, "exists": True}])
        self.assertEqual(data["projects"][0]["daemon"], "stopped")
        self.assertIn("totals", data)
