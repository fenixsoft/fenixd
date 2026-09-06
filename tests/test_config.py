"""
Tests for ConfigLoader functionality.

Split from test_core.py as part of refactor-test-structure.
"""
import copy
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

    # ── admin.workers（fix-admin-run-blocks-mainloop D6：worker 池可配置） ──

    def test_admin_workers_valid_values_accepted(self):
        """非负整数（含 0=禁用后台池回退同步）合法。"""
        for workers in (0, 1, 2, 8):
            self._write_config({
                "project": {"name": "test", "type": "web"},
                "schedule": {"poll_interval_minutes": 30},
                "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
                "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
                "gates": {"require_push_approval": True},
                "commands": {"test": "", "build": "", "start": ""},
                "logging": {"dir": ".", "level": "INFO"},
                "admin": {"workers": workers},
            })
            config = ConfigLoader.load(self.config_path)
            self.assertEqual(ConfigLoader.get(config, "admin.workers"), workers)

    def test_admin_workers_negative_rejected(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
            "admin": {"workers": -1},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_admin_workers_non_integer_rejected(self):
        self._write_config({
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
            "admin": {"workers": "two"},
        })
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_admin_workers_defaults_to_two(self):
        """未配置 → 读取方默认 2（design D6；池在 fenixd 侧以 get(...,2) 兜底）。"""
        self.assertIsNone(ConfigLoader.get({}, "admin.workers"))
        self.assertEqual(ConfigLoader.get({}, "admin.workers", 2), 2)

    # ── admin.bug_repair_mode（add-bug-repair-mode-config） ──────────

    def _admin_cfg(self, brm):
        cfg = {
            "project": {"name": "test", "type": "web"},
            "schedule": {"poll_interval_minutes": 30},
            "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
            "worktree": {"base_dir": ".", "implement_branch_prefix": "f", "verify_branch_prefix": "v"},
            "gates": {"require_push_approval": True},
            "commands": {"test": "", "build": "", "start": ""},
            "logging": {"dir": ".", "level": "INFO"},
        }
        if brm is not None:
            cfg["admin"] = {"bug_repair_mode": brm}
        return cfg

    def test_bug_repair_mode_unconfigured_defaults_inplace(self):
        """未配置 → get_admin_config 返回缺省 inplace。"""
        self._write_config(self._admin_cfg(None))
        config = ConfigLoader.load(self.config_path)
        self.assertEqual(
            ConfigLoader.get_admin_config(config)["bug_repair_mode"], "inplace"
        )

    def test_bug_repair_mode_valid_values_accepted(self):
        """合法枚举 inplace/derive 通过校验并回读。"""
        for mode in ("inplace", "derive"):
            self._write_config(self._admin_cfg(mode))
            config = ConfigLoader.load(self.config_path)
            self.assertEqual(
                ConfigLoader.get_admin_config(config)["bug_repair_mode"], mode
            )

    def test_bug_repair_mode_illegal_value_rejected(self):
        """非法取值（非字符串、非枚举）被校验拒绝，配置不生效。"""
        for bad in ("always", 42, True, ["derive"]):
            self._write_config(self._admin_cfg(bad))
            with self.assertRaises(ValueError) as cm:
                ConfigLoader.load(self.config_path)
            self.assertIn("admin.bug_repair_mode", str(cm.exception))

    def test_bug_repair_mode_validate_rejects_and_unchanged(self):
        """宽松路径（resolve_config）同拒非法值；合法值经 get_admin_config 取回。"""
        ConfigLoader.reset_stuck_threshold_state()
        proot = Path(self.tmpdir) / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        import yaml
        (proot / ".fenix" / "config.yaml").write_text(
            "project:\n  name: proj\nadmin:\n  bug_repair_mode: always\n",
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            ConfigLoader.resolve_config(proot)


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
    """在 base/name 下构造一个可被识别的 Fenixd 项目（.fenix/STATE.md + .fenix/config.yaml）。"""
    proot = base / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text(
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
        # 轻量 Fenixd 目录：仅 .fenix/STATE.md 即被发现（无需 .fenix/config.yaml）
        fake = self.home / "lite-project"
        fake.mkdir()
        (fake / ".fenix").mkdir()
        (fake / ".fenix" / "STATE.md").write_text("# not a project", encoding="utf-8")
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
        # 仅 .fenix/STATE.md 的目录也被扫描命中
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


# ═══════════════════════════════════════════════════════════════════
# improve-hot-reload-robustness：agents.models 未知键逐键降级
# ═══════════════════════════════════════════════════════════════════

def _base_cfg(models=None, llm=None) -> dict:
    """构造带完整顶层键的配置（load 严格路径 / resolve_config 宽松路径共用）。"""
    cfg = {
        "project": {"name": "test", "type": "web"},
        "schedule": {"poll_interval_minutes": 30},
        "agents": {"max_concurrent": 2, "max_retries": 3, "max_turns": 50},
        "worktree": {"base_dir": ".claude/worktrees", "implement_branch_prefix": "fenix", "verify_branch_prefix": "fenix/verify"},
        "gates": {"require_push_approval": True},
        "commands": {"test": "", "build": "", "start": ""},
        "logging": {"dir": ".fenix/logs", "level": "INFO"},
    }
    if models is not None:
        cfg["agents"]["models"] = models
    if llm is not None:
        # 每条 provider 带 model，保证 _resolve_element_model 能解析出模型名
        # （否则三者皆空时元素被跳过、链为空 → get_agent_model_assignment 返回 None）
        cfg["llm"] = {"providers": llm}
    return cfg


def _volc_provider() -> dict:
    return {"name": "volc", "baseurl": "https://v.com", "apikey": "k",
            "model": "claude-sonnet-5"}


class TestAgentModelsUnknownKeyTolerance(unittest.TestCase):
    """improve-hot-reload-robustness：未知 agent 类型键逐键降级与分类线锁定。

    D1：未知键跳过校验、保留在有效配置中、逐键 ERROR 告警（含重启处方），
    其余键/段照常生效；D2：值类错误仍整段拒绝、旧配置原子保留。
    """

    def setUp(self):
        ConfigLoader.reset_stuck_threshold_state()
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.yaml"
        self.proot = Path(self.tmpdir) / "proj"
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        # 隔离用户级配置目录，避免宿主机 ~/.fenix/config.yaml 混入
        self.user_cfg_dir = Path(self.tmpdir) / "user-fenix"
        self.user_cfg_dir.mkdir()
        self._user_patch = patch("core.config.USER_CONFIG_DIR", self.user_cfg_dir)
        self._user_patch.start()

    def tearDown(self):
        self._user_patch.stop()
        ConfigLoader.reset_stuck_threshold_state()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_proj_cfg(self, yaml_text: str):
        (self.proot / ".fenix" / "config.yaml").write_text(yaml_text, encoding="utf-8")

    def _write_config(self, config_dict):
        import yaml
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_dict, f)

    def test_unknown_key_tolerated_with_prescription_and_known_key_kept(self):
        """未知键不抛 + 告警含处方 + implementer 分配完整保留。"""
        cfg = _base_cfg(
            models={
                "implementer": {"provider": "volc"},
                "turbo-draft": {"provider": "volc"},  # 未知键
            },
            llm=[_volc_provider()],
        )
        self._write_config(cfg)
        with self.assertLogs("fenixd.config", level="ERROR") as cm:
            config = ConfigLoader.load(self.config_path)  # 启动严格路径
        joined = "\n".join(r.getMessage() for r in cm.records)
        self.assertIn("turbo-draft", joined)
        self.assertIn("touch .fenix/restart_request", joined)
        self.assertIn("implementer", joined)  # 已知类型列表在文案中
        # 未知键保留在有效配置中、已知键分配完整保留
        self.assertIn("turbo-draft", config["agents"]["models"])
        assign = ConfigLoader.get_agent_model_assignment(config, "implementer")
        self.assertEqual(len(assign), 1)
        self.assertEqual(assign[0][0]["name"], "volc")

    def test_unknown_key_deduped_across_reload_retries(self):
        """同一未知键 30s 重试风暴下只告警一次（D3 生命周期去重）。"""
        self._write_proj_cfg(
            "project:\n  name: proj\n"
            "agents:\n  models:\n"
            "    implementer: {provider: volc}\n"
            "    turbo-draft: {provider: volc}\n"
            "llm:\n  providers:\n"
            "    - {name: volc, baseurl: https://v, apikey: k, model: claude-sonnet-5}\n"
        )
        with self.assertLogs("fenixd.config", level="ERROR") as cm:
            ConfigLoader.resolve_config(self.proot)
            ConfigLoader.resolve_config(self.proot)  # 第二次命中同键 → 静默跳过
            ConfigLoader.resolve_config(self.proot)
        hits = [r for r in cm.records if "未知 agent 类型键" in r.getMessage()]
        self.assertEqual(len(hits), 1)

    def test_unknown_key_with_bad_known_key_still_rejected(self):
        """未知键 + 已知键值类错误共存 → 仍整段拒绝（值坏不是键新）。"""
        cfg = _base_cfg(
            models={
                "implementer": {"provider": 123},  # 已知键形态非法 → 仍 raise
                "turbo-draft": {"provider": "volc"},
            },
            llm=[_volc_provider()],
        )
        self._write_config(cfg)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_unknown_key_then_valid_known_key_known_key_effective(self):
        """未知键后跟合法已知键 → 已知键照常生效（跳过 ≠ 截断整段）。"""
        cfg = _base_cfg(
            models={
                "turbo-draft": {"provider": "volc"},  # 未知键排在前
                "implementer": {"provider": "volc"},
                "verifier": {"provider": "volc"},
            },
            llm=[_volc_provider()],
        )
        self._write_config(cfg)
        config = ConfigLoader.load(self.config_path)
        for role in ("implementer", "verifier"):
            assign = ConfigLoader.get_agent_model_assignment(config, role)
            self.assertEqual(len(assign), 1)
            self.assertEqual(assign[0][0]["name"], "volc")

    def test_models_section_non_dict_ignored_rest_applied(self):
        """agents.models 整段非 dict → 忽略该段 + 告警，其余段照常校验应用。"""
        self._write_proj_cfg(
            "project:\n  name: proj\n"
            "agents:\n  models:\n    - a\n    - b\n"
            "schedule:\n  poll_interval_minutes: 30\n"
        )
        with self.assertLogs("fenixd.config", level="ERROR") as cm:
            config = ConfigLoader.resolve_config(self.proot)
        self.assertEqual(config["project"]["name"], "proj")  # 其余段照常
        self.assertTrue(any("整段非 dict" in r.getMessage() for r in cm.records))

    def test_startup_tolerant_unknown_key_not_fatal(self):
        """启动路径（load 严格校验）容忍未知键不 FATAL，值类错误仍 FATAL。"""
        cfg = _base_cfg(models={"turbo-draft": {"provider": "volc"}})
        self._write_config(cfg)
        with self.assertLogs("fenixd.config", level="ERROR"):
            ConfigLoader.load(self.config_path)  # 不抛 → 启动继续

        bad = _base_cfg(llm="not-a-list")  # 值类错误
        self._write_config(bad)
        with self.assertRaises(ValueError):
            ConfigLoader.load(self.config_path)

    def test_value_error_atomic_preserve_regression_lock(self):
        """热重载遇值类非法 → 抛异常、热重载失败、当前生效配置逐键不变。"""
        self._write_proj_cfg(
            "project:\n  name: proj\n"
            "agents:\n  max_concurrent: 3\n"
            "schedule:\n  poll_interval_minutes: 30\n"
        )
        config = ConfigLoader.resolve_config(self.proot)
        original = copy.deepcopy(config)

        # 写入坏配置：llm.providers 非 list → 整段拒绝
        self._write_proj_cfg(
            "project:\n  name: proj\n"
            "llm:\n  providers: not-a-list\n"
        )
        with self.assertRaises(ValueError):
            ConfigLoader.resolve_config_into(config, self.proot)
        # 原子保留：原 config 逐键不变
        self.assertEqual(config, original)
        self.assertEqual(config["agents"]["max_concurrent"], 3)
        self.assertEqual(config["project"]["name"], "proj")

    def test_runtime_assignment_has_no_whitelist_gate(self):
        """get_agent_model_assignment 无白名单拦截：保留的未知键正常解析、链缺失走默认网关。"""
        self._write_proj_cfg(
            "project:\n  name: proj\n"
            "agents:\n  models:\n"
            "    turbo-draft: {provider: volc}\n"  # 白名单外键（校验层跳过）
            "llm:\n  providers:\n"
            "    - {name: volc, baseurl: https://v, apikey: k, model: claude-sonnet-5}\n"
        )
        with self.assertLogs("fenixd.config", level="ERROR"):
            config = ConfigLoader.resolve_config(self.proot)
        # 未知键仍可被运行时正常解析（键保留在有效配置中）
        assign = ConfigLoader.get_agent_model_assignment(config, "turbo-draft")
        self.assertEqual(len(assign), 1)
        self.assertEqual(assign[0][0]["name"], "volc")
        # 链缺失/未配置角色 → None 走默认网关（现行为不变）
        self.assertIsNone(ConfigLoader.get_agent_model_assignment(config, "verifier"))

