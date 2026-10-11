"""关键路径执行前陈旧代码预检测试（evo-add-key-path-stale-code-preflight 3.1）。

覆盖：
- 注册表三态：注册后查询跟随、未注册 fail-open、回调异常 fail-open、
  检测点推送值兜底（task 1.1）；
- daemon 转发接线：启动注册回调现场读 _code_stale、_update_stale_code_state
  检测点同步注册表（task 1.2）；
- 三个关键路径（收尾提交 / 蒸馏派发 / admin choice 执行）旗标置位时各产生
  一条 WARNING、restart_request 被创建，动作返回值与产物和不预检一致；
  已存在时不重复写不刷 mtime；旗标未置位时零新增副作用（task 2.1/2.2/2.3）；
- 蒸馏单条与批量路径各只产生一条预检 WARNING（dispatch 单汇聚点不重复
  插桩）。

restart_request 在所有用例中经 mock.patch.object 指向临时目录——用例绝不
触碰真实仓库的 .fenix/restart_request（supervisor 2s 轮询、命中即重启，
测试残留等于误杀生产 daemon）。路径锚点本身（daemon 仓库 .fenix）由
TestRegistryThreeStates.test_anchor_is_daemon_repo_fenix 以模块位置直证。

注册表不落第二份状态（无推送值兜底）：兜底形态会让 daemon 检测路径的
测试把陈旧推送值遗留在进程内，未注册语境的 fail-open 条款被破坏（实测
击穿 test_push_closeout_report_commit 的「零 WARNING」断言并写出真实
restart_request）。test_unregistered_daemon_detection_polls_nothing 锁定
该语义。
"""

import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fenixd as _fenixd_mod  # 模块级绑定真实文件模块（test_stale_code_selfheal 同款处方）
import core.knowledge as kn
from core import code_stale_flag
from core.knowledge import KNOWLEDGE_DIR, DistillManager

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

STALE_MARK = "代码陈旧"
SPEC = "key-path-stale-preflight-spec"
# import 期捕获的原始常量（用例内 patch 前的模块默认值，供锚点直证）
_PRISTINE_RESTART_REQUEST = code_stale_flag.RESTART_REQUEST


def _git(proot: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(proot), *args],
        env=GIT_ENV, capture_output=True, text=True, timeout=60,
    )


class _Proc0:
    """fake spawn 返回的进程替身（test_knowledge_distill_resume 同款）。"""

    pid = -1

    def __init__(self, returncode=0):
        self.returncode = returncode

    def communicate(self, prompt=None, timeout=None):
        return "", ""


class _RecordTap:
    """stdlib logging 收集器（context manager）：按子串过滤计数。

    零断言前提（assertLogs 至少一条才过）——「零新增副作用」类用例同样适用。
    """

    def __init__(self, logger_name: str):
        self._logger = logging.getLogger(logger_name)
        self.records: list = []
        self._handler = logging.Handler()
        self._handler.emit = lambda record: self.records.append(record)

    def __enter__(self):
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *exc):
        self._logger.removeHandler(self._handler)
        return False

    def matching(self, substr: str) -> list:
        return [r for r in self.records if substr in r.getMessage()]


class _PreflightBase(unittest.TestCase):
    """公共夹具：注册表隔离 + restart_request 重定向到临时目录。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.req_path = Path(self.tmpdir) / "restart_request"
        code_stale_flag.unregister()
        self._req_patch = mock.patch.object(
            code_stale_flag, "RESTART_REQUEST", self.req_path
        )
        self._req_patch.start()

    def tearDown(self):
        self._req_patch.stop()
        code_stale_flag.unregister()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_req(self):
        stat = self.req_path.stat()
        return (
            self.req_path.read_text(encoding="utf-8"),
            stat.st_mtime_ns,
        )


# ── task 1.1：注册表三态与 request_restart 单元行为 ───────────────────


class TestRegistryThreeStates(_PreflightBase):
    def test_unregistered_fail_open(self):
        """未注册（pytest/冷启动窗口）返回「不陈旧」，零副作用。"""
        self.assertFalse(code_stale_flag.is_stale())
        self.assertFalse(self.req_path.exists())

    def test_register_query_follows_state(self):
        """注册后查询返回当前陈旧态，翻假后返回假。"""
        code_stale_flag.register(lambda: True)
        self.assertTrue(code_stale_flag.is_stale())
        code_stale_flag.register(lambda: False)
        self.assertFalse(code_stale_flag.is_stale())

    def test_unregister_returns_to_fail_open(self):
        """注销即回 fail-open；未注册语义不受任何先前注册/查询历史影响。"""
        code_stale_flag.register(lambda: True)
        self.assertTrue(code_stale_flag.is_stale())
        code_stale_flag.unregister()
        self.assertFalse(code_stale_flag.is_stale())
        self.assertFalse(self.req_path.exists())

    def test_callback_exception_fail_open(self):
        def _boom():
            raise RuntimeError("判定通道故障")

        code_stale_flag.register(_boom)
        self.assertFalse(code_stale_flag.is_stale())

    def test_register_non_callable_rejected(self):
        with self.assertRaises(TypeError):
            code_stale_flag.register(True)

    def test_callback_reads_live_no_io(self):
        """回调现场读（注册一次、值随源更新），查询不触碰文件系统。"""
        state = {"stale": True}
        code_stale_flag.register(lambda: state["stale"])
        self.assertTrue(code_stale_flag.is_stale())
        state["stale"] = False
        self.assertFalse(code_stale_flag.is_stale())
        self.assertFalse(self.req_path.exists())

    def test_anchor_is_daemon_repo_fenix(self):
        """路径锚点 = daemon 仓库 .fenix/restart_request（模块位置推导）。

        与 fenixd.py 的 FENIX_DIR 同源 ⇒ 与 supervisor 侧 RESTART_REQUEST
        同一文件；不随被管项目 project_root 漂移（用例内重定向仅为本测
        隔离，见模块 docstring）。断言取 import 期原值（补丁前捕获）。
        """
        self.assertEqual(
            _PRISTINE_RESTART_REQUEST,
            Path(code_stale_flag.__file__).absolute().parent.parent
            / ".fenix"
            / "restart_request",
        )
        self.assertEqual(code_stale_flag.DAEMON_ROOT, _fenixd_mod.FENIX_DIR)

    # ── request_restart 单元行为（三个插入点共用的同款语义）──────────

    def test_request_restart_not_stale_zero_side_effect(self):
        code_stale_flag.register(lambda: False)
        logs: list = []
        self.assertFalse(
            code_stale_flag.request_restart(logs.append, "某动作")
        )
        self.assertEqual(logs, [])
        self.assertFalse(self.req_path.exists())

    def test_request_restart_creates_file_and_warns_once(self):
        code_stale_flag.register(lambda: True)
        logs: list = []
        self.assertTrue(code_stale_flag.request_restart(logs.append, "某动作"))
        self.assertEqual(len(logs), 1)
        self.assertIn(STALE_MARK, logs[0])
        self.assertIn("已写入", logs[0])
        self.assertIn("请求重启", logs[0])
        content, _mtime = self._read_req()
        # 写入格式与既有自愈 touch 一致（ISO 时间戳行，supervisor 只看存在性）
        datetime.fromisoformat(content.strip().replace("\n", ""))
        # 幂等：第二次仍只告警一次、不重复写
        mtime1 = self.req_path.stat().st_mtime_ns
        logs.clear()
        self.assertTrue(code_stale_flag.request_restart(logs.append, "某动作"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(self.req_path.stat().st_mtime_ns, mtime1)

    def test_request_restart_existing_not_rewritten(self):
        """已存在不重复写、不刷 mtime（与自愈「重启在途不重复写入」一致）。"""
        self.req_path.parent.mkdir(parents=True, exist_ok=True)
        self.req_path.write_text("existing-marker\n", encoding="utf-8")
        old_stat = self.req_path.stat()
        os.utime(self.req_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns - 10**9))
        frozen = self._read_req()

        code_stale_flag.register(lambda: True)
        logs: list = []
        self.assertTrue(code_stale_flag.request_restart(logs.append, "某动作"))
        self.assertEqual(self._read_req(), frozen)
        self.assertEqual(len(logs), 1)
        self.assertIn(STALE_MARK, logs[0])
        self.assertIn("重启在途", logs[0])
        self.assertIn("不重复写入", logs[0])

    def test_request_restart_write_failure_not_raised(self):
        """写失败（.fenix 被文件占位）只降级说明，不向关键路径抛异常。"""
        (Path(self.tmpdir) / ".fenix").write_text("not a dir", encoding="utf-8")
        blocked = Path(self.tmpdir) / ".fenix" / "restart_request"
        code_stale_flag.register(lambda: True)
        logs: list = []
        with mock.patch.object(code_stale_flag, "RESTART_REQUEST", blocked):
            self.assertTrue(code_stale_flag.request_restart(logs.append, "某动作"))
        self.assertEqual(len(logs), 1)
        self.assertIn("请求重启失败", logs[0])

    def test_request_restart_log_channel_failure_swallowed(self):
        code_stale_flag.register(lambda: True)

        def _boom(_msg):
            raise RuntimeError("日志通道故障")

        self.assertTrue(code_stale_flag.request_restart(_boom, "某动作"))

    def test_concurrent_readers_writers_smoke(self):
        """注册线程（写：覆盖回调）与车道线程（读：查询）并发无异常（锁语义
        冒烟；daemon 侧等价形态 = 检测线程重注册/车道线程查询）。"""
        errors: list = []
        flip = {"v": False}

        def _writer():
            try:
                for _ in range(400):
                    flip["v"] = not flip["v"]
                    code_stale_flag.register(lambda: flip["v"])
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        def _reader():
            try:
                for _ in range(400):
                    code_stale_flag.is_stale()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        code_stale_flag.register(lambda: flip["v"])
        threads = [threading.Thread(target=_writer) for _ in range(2)]
        threads += [threading.Thread(target=_reader) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        self.assertFalse(any(t.is_alive() for t in threads))


# ── task 1.2：daemon 启动注册与检测点同步 ─────────────────────────────


def _bare_daemon(tmp: Path):
    """构造「尚未 initialize」的 FenixDaemon 裸对象（selfheal 测试同款）。"""
    daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
    daemon._code_stale = False
    daemon._code_files = [tmp / "fenixd.py"]
    daemon._code_baseline_ns = 1
    daemon.logger = mock.MagicMock()
    daemon.admin_store = None
    return daemon


class TestFenixdForwarding(_PreflightBase):
    def test_startup_registration_reads_live_flag(self):
        daemon = _bare_daemon(Path(self.tmpdir))
        daemon._register_code_stale_flag()
        self.assertFalse(code_stale_flag.is_stale())
        daemon._code_stale = True
        self.assertTrue(code_stale_flag.is_stale())
        daemon._code_stale = False
        self.assertFalse(code_stale_flag.is_stale())

    def test_detect_point_syncs_registry(self):
        """_update_stale_code_state 检测点把重算结果同步进注册表（注册即镜像：
        回调直读 self._code_stale，检测点重算即时可见；既有判定/告警行为不因
        转发改变）。"""
        daemon = _bare_daemon(Path(self.tmpdir))
        daemon._register_code_stale_flag()
        with mock.patch.object(
            _fenixd_mod, "code_files_changed_since", return_value=True
        ):
            daemon._update_stale_code_state()
        self.assertTrue(code_stale_flag.is_stale())
        self.assertTrue(daemon._code_stale)

        with mock.patch.object(
            _fenixd_mod, "code_files_changed_since", return_value=False
        ):
            daemon._update_stale_code_state()
        self.assertFalse(code_stale_flag.is_stale())
        self.assertFalse(daemon._code_stale)

    def test_unregistered_daemon_detection_polls_nothing(self):
        """未注册语境（裸 daemon/替身）检测点重算对注册表零外溢：查询严格
        fail-open 返回不陈旧（SPEC fail-open 条款，防跨测试进程内污染）。"""
        daemon = _bare_daemon(Path(self.tmpdir))
        with mock.patch.object(
            _fenixd_mod, "code_files_changed_since", return_value=True
        ):
            daemon._update_stale_code_state()
        self.assertTrue(daemon._code_stale)
        self.assertFalse(code_stale_flag.is_stale())

    def test_detection_error_keeps_last_value(self):
        """检测本身异常时旗标保持上次值（回调直读属性未被改写），不抛异常。"""
        daemon = _bare_daemon(Path(self.tmpdir))
        daemon._register_code_stale_flag()
        daemon._code_stale = True
        with mock.patch.object(
            _fenixd_mod,
            "code_files_changed_since",
            side_effect=RuntimeError("stat 爆炸"),
        ):
            daemon._update_stale_code_state()
        self.assertTrue(code_stale_flag.is_stale())


# ── task 2.1：verification-report 收尾提交预检 ────────────────────────


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class TestEngineWrapupPreflight(_PreflightBase):
    """装配沿用 test_push_closeout_report_commit 同款（真实 PMEngine +
    隔离 push 内部链路），临时项目根为独立 git 仓库。"""

    def setUp(self):
        super().setUp()
        from core.state_machine import StateMachine

        self.project_root = Path(self.tmpdir) / "proj"
        self.project_root.mkdir(parents=True)
        self._git("init", "-q")
        for args in (
            ("config", "user.email", "fenix-test@example.com"),
            ("config", "user.name", "fenix-test"),
            ("config", "commit.gpgsign", "false"),
        ):
            self._git(*args)
        (self.project_root / "README.md").write_text("test repo\n", encoding="utf-8")
        self._git("add", "--", "README.md")
        self._git("commit", "-q", "-m", "init")
        (self.project_root / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
        self._git("add", "--", ".gitignore")
        self._git("commit", "-q", "-m", "gitignore")
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = mock.MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger
        )
        self.sm.add_spec(SPEC, {"status": "done", "branch": f"fenix/{SPEC}"})
        from core.pm_engine import PMEngine

        self.engine = PMEngine(
            self.sm, mock.MagicMock(), {}, self.project_root, self.logger
        )
        self.archive_calls = []
        self.engine._is_push_backoffed = mock.MagicMock(return_value=False)
        self.engine._resolve_push_branch = mock.MagicMock(return_value=f"fenix/{SPEC}")
        self.engine._push_branch_best_effort = mock.MagicMock()
        self.engine._archive_auto_commit = lambda: self.archive_calls.append(1)
        self.engine._append_project_log = mock.MagicMock()
        self.engine._git_push_ref = mock.MagicMock(return_value=(True, ""))
        self.report_rel = f"spec/changes/{SPEC}/verification-report.md"

    def _git(self, *args):
        return _git(self.project_root, *args)

    def _write_report(self):
        path = self.project_root / self.report_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("## 结论：✅ 通过\n\npush 收口报告。\n", encoding="utf-8")

    def _warn_texts(self):
        return [
            str(c.args[1]) if len(c.args) >= 2 else str(c)
            for c in self.logger.warning.call_args_list
        ]

    def test_stale_warns_creates_request_action_unchanged(self):
        """陈旧时：一条 WARNING + restart_request 被创建，收尾产物不变。"""
        self._write_report()
        code_stale_flag.register(lambda: True)

        ok = self.engine.approve_push(SPEC)

        self.assertTrue(ok)
        self.assertEqual((self.sm.read_one(SPEC) or {}).get("status"), "pushed")
        # 报告照常入库（预检不改变产物）
        subject = self._git("log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, f"[fenix] {SPEC}: verification-report 入库")
        files = [
            line
            for line in self._git("show", "--name-only", "--format=").stdout.splitlines()
            if line.strip()
        ]
        self.assertEqual(files, [self.report_rel])
        self.assertEqual(self.archive_calls, [1])
        # 预检恰好一条 WARNING，restart_request 落在 daemon 侧（重定向路径）
        stale_warns = [t for t in self._warn_texts() if STALE_MARK in t]
        self.assertEqual(len(stale_warns), 1)
        self.assertIn("verification-report 收尾提交", stale_warns[0])
        self.assertIn("请求重启", stale_warns[0])
        self.assertTrue(self.req_path.exists())

    def test_fresh_zero_new_side_effects(self):
        """新鲜（未注册同口径）：无新增预检日志、无新文件写入，收尾照常。"""
        self._write_report()

        ok = self.engine.approve_push(SPEC)

        self.assertTrue(ok)
        self.assertEqual((self.sm.read_one(SPEC) or {}).get("status"), "pushed")
        self.assertEqual(
            [t for t in self._warn_texts() if STALE_MARK in t], []
        )
        self.assertFalse(self.req_path.exists())

    def test_existing_request_not_rewritten(self):
        self._write_report()
        self.req_path.write_text("existing-marker\n", encoding="utf-8")
        frozen = self._read_req()
        code_stale_flag.register(lambda: True)

        ok = self.engine.approve_push(SPEC)

        self.assertTrue(ok)
        self.assertEqual(self._read_req(), frozen)
        stale_warns = [t for t in self._warn_texts() if STALE_MARK in t]
        self.assertEqual(len(stale_warns), 1)
        self.assertIn("重启在途", stale_warns[0])


# ── task 2.2：知识蒸馏派发预检（单汇聚点）─────────────────────────────


@unittest.skipIf(shutil.which("git") is None, "git 不可用")
class TestKnowledgeDispatchPreflight(_PreflightBase):
    N1 = "2026-10-12-alpha-spec"
    N2 = "2026-10-12-beta-spec"

    def setUp(self):
        super().setUp()
        self.root = Path(self.tmpdir) / "proj"
        (self.root / ".fenix" / "logs").mkdir(parents=True)
        # 项目级 config 固定 knowledge.enabled: true（不随用户级配置漂移）
        (self.root / ".fenix" / "config.yaml").write_text(
            "knowledge:\n  enabled: true\n", encoding="utf-8"
        )
        (self.root / KNOWLEDGE_DIR).mkdir(parents=True, exist_ok=True)
        for name in (self.N1, self.N2):
            (self.root / "spec" / "archive" / name).mkdir(parents=True)
        for cmd in (
            ("init", "-q"),
            ("config", "user.name", "t"),
            ("config", "user.email", "t@t"),
            ("add", "--", "."),
            ("commit", "-q", "-m", "init"),
        ):
            _git(self.root, *cmd)
        self.cfg = {"knowledge": {"enabled": True}}
        self.mgr = DistillManager(spawn=lambda cmd, cwd: _Proc0(returncode=0))

    def _wait_workers_done(self, mgr) -> bool:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if not any(w.is_alive() for w in mgr._workers.values()):
                return True
            time.sleep(0.05)
        return not any(w.is_alive() for w in mgr._workers.values())

    def _stale_warn_count(self, fn):
        with _RecordTap("fenixd.knowledge") as tap:
            result = fn()
        return result, tap.matching(STALE_MARK)

    def test_mgr_dispatch_single_warning_and_request(self):
        """DistillManager.dispatch 单点：一条 WARNING + restart_request 创建，
        入队返回值不变。"""
        code_stale_flag.register(lambda: True)
        result, warns = self._stale_warn_count(
            lambda: self.mgr.dispatch(self.root, [self.N1])
        )
        self.assertEqual(result, {"dispatched": True, "queued": [self.N1]})
        self.assertEqual(len(warns), 1)
        self.assertIn("知识蒸馏派发", warns[0].getMessage())
        self.assertIn("请求重启", warns[0].getMessage())
        self.assertTrue(self.req_path.exists())
        self.assertTrue(self._wait_workers_done(self.mgr))

    def test_single_entry_one_warning_via_funnel(self):
        """dispatch_distill（单条）恰好一条预检 WARNING（不与 dispatch 重复）。"""
        code_stale_flag.register(lambda: True)
        result, warns = self._stale_warn_count(
            lambda: kn.dispatch_distill(
                self.root, self.N1, self.cfg, dispatcher=self.mgr
            )
        )
        self.assertTrue(result["dispatched"])
        self.assertEqual(len(warns), 1)
        self.assertTrue(self._wait_workers_done(self.mgr))

    def test_batch_entry_one_warning_via_funnel(self):
        """dispatch_distill_batch（批量）同样恰好一条预检 WARNING。"""
        code_stale_flag.register(lambda: True)
        result, warns = self._stale_warn_count(
            lambda: kn.dispatch_distill_batch(
                self.root, [self.N1, self.N2], self.cfg, dispatcher=self.mgr
            )
        )
        self.assertTrue(result["dispatched"])
        self.assertEqual(len(warns), 1)
        self.assertTrue(self.req_path.exists())
        self.assertTrue(self._wait_workers_done(self.mgr))

    def test_fresh_zero_new_side_effects(self):
        """旗标未置位：零预检日志、零新文件，派发照常。"""
        result, warns = self._stale_warn_count(
            lambda: self.mgr.dispatch(self.root, [self.N1])
        )
        self.assertEqual(result["dispatched"], True)
        self.assertEqual(warns, [])
        self.assertFalse(self.req_path.exists())
        self.assertTrue(self._wait_workers_done(self.mgr))


# ── task 2.3：admin choice 执行预检 ──────────────────────────────────


class TestAdminChoicePreflight(_PreflightBase):
    def _make_monitor(self):
        from core.admin_monitor import AdminMonitor

        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True, exist_ok=True)
        self.logger = mock.MagicMock()
        return AdminMonitor(
            {},
            mock.MagicMock(),  # state_machine（本路径不触达）
            self.proot,
            self.logger,
            store=mock.MagicMock(),
        )

    def _disp(self):
        return SimpleNamespace(
            choice_id="retry-review", spec=SPEC, actions_taken="处置依据"
        )

    def _execute(self, mon, exec_mock):
        import core.dashboard.data.admin_actions as admin_actions

        with mock.patch.object(
            admin_actions, "execute_adjudication_choice", exec_mock
        ):
            return mon._apply_choice_execution(
                {"spec": SPEC, "signal_type": "daemon_errors"}, self._disp()
            )

    def _warn_texts(self):
        return [
            str(c.args[1]) if len(c.args) >= 2 else str(c)
            for c in self.logger.warning.call_args_list
        ]

    def test_stale_warns_creates_request_action_unchanged(self):
        mon = self._make_monitor()
        code_stale_flag.register(lambda: True)
        exec_mock = mock.MagicMock(return_value={"ok": True, "action": "x", "error": None})

        result = self._execute(mon, exec_mock)

        # 执行结果原样透传（_apply_choice_execution 附带 steps 留痕键不属预检）
        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "x")
        self.assertIsNone(result["error"])
        self.assertEqual(exec_mock.call_count, 1)
        # project_root 指向非 daemon 仓库目录：restart_request 仍走 daemon 侧
        # 锚点（本用例重定向的临时路径），绝不写 project_root 下的 .fenix
        self.assertFalse((self.proot / ".fenix" / "restart_request").exists())
        self.assertTrue(self.req_path.exists())
        stale_warns = [t for t in self._warn_texts() if STALE_MARK in t]
        self.assertEqual(len(stale_warns), 1)
        self.assertIn("admin 处置 choice 执行", stale_warns[0])
        self.assertIn("请求重启", stale_warns[0])

    def test_fresh_zero_new_side_effects(self):
        mon = self._make_monitor()
        exec_mock = mock.MagicMock(return_value={"ok": True, "action": "x", "error": None})

        result = self._execute(mon, exec_mock)

        self.assertTrue(result["ok"])
        self.assertEqual(exec_mock.call_count, 1)
        self.assertEqual([t for t in self._warn_texts() if STALE_MARK in t], [])
        self.assertFalse(self.req_path.exists())

    def test_empty_choice_id_not_preflighted(self):
        """choice_id 为空 → 提前返回 None（预检同样不触发、零副作用）。"""
        mon = self._make_monitor()
        code_stale_flag.register(lambda: True)
        disp = SimpleNamespace(choice_id="", spec=SPEC, actions_taken="")

        result = mon._apply_choice_execution({"spec": SPEC}, disp)

        self.assertIsNone(result)
        self.assertFalse(self.req_path.exists())
        self.assertEqual([t for t in self._warn_texts() if STALE_MARK in t], [])


if __name__ == "__main__":
    unittest.main()
