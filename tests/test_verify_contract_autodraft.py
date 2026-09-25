"""validate_contract 测试：契约校验入口的三段验证、valid 判定、CLI 退出码。"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    ReadyProbe,
    ServeSpec,
    StaticVerifyServer,
    ValidateResult,
    load_verify_contract,
    probe_ready,
    run_prepare_steps,
    validate_contract,
)


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


FULL_CONTRACT = """
prepare:
  - run: touch built.txt
serve:
  kind: static
  root: site
ready:
  url: /
  expect: 200
  timeout: 5
"""


class TestValidateContract(unittest.TestCase):
    """validate_contract 核心逻辑测试。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_missing_contract_returns_invalid(self):
        """契约文件不存在 → valid=False，prepare_error 说明文件不存在。"""
        result = validate_contract(self.tmp)
        self.assertFalse(result.valid)
        self.assertFalse(result.prepare_ok)
        self.assertIn("不存在", result.prepare_error)

    def test_invalid_yaml_returns_invalid(self):
        """YAML 解析失败 → valid=False。"""
        _write(self.tmp, ".fenix/verify.yaml", "prepare: [unclosed")
        result = validate_contract(self.tmp)
        self.assertFalse(result.valid)
        self.assertIn("解析失败", result.prepare_error)

    def test_valid_contract_three_pass(self):
        """健康契约：prepare/serve/ready 三段全通过。"""
        _write(self.tmp, ".fenix/verify.yaml", FULL_CONTRACT)
        _write(self.tmp, "site/index.html", "hello")
        result = validate_contract(self.tmp)
        self.assertTrue(result.valid, f"valid should be True: {result.serve_error} {result.ready_error}")
        self.assertTrue(result.prepare_ok)
        self.assertTrue(result.serve_ok)
        self.assertTrue(result.serve_ran)
        self.assertTrue(result.ready_ok)
        self.assertEqual(result.prepare_steps_run, 1)
        self.assertEqual(result.serve_kind, "static")

    def test_prepare_failure_still_valid(self):
        """prepare 脚本失败 → prepare_ok=False，但 valid=True（契约结构有效）。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: \"exit 1\"\nserve:\n  kind: static\n  root: site\n")
        result = validate_contract(self.tmp)
        self.assertTrue(result.valid)  # 契约结构有效（YAML 正确 + serve 段合法）
        self.assertFalse(result.prepare_ok)
        # prepare 失败跳过 serve 段 → serve 从未实际启动（item 3d9623096956）
        self.assertFalse(result.serve_ran)
        self.assertIn("第 1 步", result.prepare_error)

    def test_serve_root_not_exist_still_valid(self):
        """serve.root 不存在 → serve_ok=False，但 valid=True（契约结构有效）。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: static\n  root: nonexistent\n")
        result = validate_contract(self.tmp)
        self.assertTrue(result.valid)  # 契约结构有效（YAML 正确 + serve 段合法）
        self.assertFalse(result.serve_ok)
        self.assertIn("不存在", result.serve_error)

    def test_serve_kind_invalid_returns_invalid(self):
        """serve.kind 非法 → valid=False。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: bogus\n  root: site\n")
        result = validate_contract(self.tmp)
        self.assertFalse(result.valid)
        self.assertFalse(result.serve_ok)
        self.assertIn("非法", result.serve_error)

    def test_pure_cli_no_serve_is_valid(self):
        """纯 cli 场景集无 serve 段也合法（valid=True）。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo ok\n")
        result = validate_contract(self.tmp)
        self.assertTrue(result.valid)
        self.assertTrue(result.prepare_ok)
        self.assertTrue(result.serve_ok)
        self.assertTrue(result.ready_ok)

    def test_spa_fallback_vacuity_check_fails(self):
        """SPA fallback 无鉴别力探针 → ready_ok=False，valid=False。"""
        # 启动一个 SPA fallback 服务器（任意路径回同一 HTML）
        class FallbackHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body><div id=root></div></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), FallbackHandler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]

        # 测试 probe_ready 的鉴别力自检
        ok, note = probe_ready(
            f"http://127.0.0.1:{port}",
            ReadyProbe(url="/", expect=200, timeout=3))
        self.assertFalse(ok)
        self.assertIn("无鉴别力", note)


class TestVerifyContractMissingSignal(unittest.TestCase):
    """verify_contract_missing 信号写入与回归保护。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()

    def _mk_engine(self, config=None):
        from test_inplace_bug_repair import _mk_engine
        engine, _ = _mk_engine(self.tmp, MagicMock(), config)
        return engine

    def _scenarios(self, scenarios):
        p = self.tmp / ".fenix" / "verify-progress" / "spec-a" / "test_scenarios.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
        return p

    def test_contract_missing_writes_signal(self):
        """契约缺失时写入 verify_contract_missing 信号。"""
        self._scenarios([{"id": "w1", "kind": "web",
                          "steps": [{"action": "navigate",
                                     "value": "http://localhost:59999/"}],
                          "assertions": []}])
        engine = self._mk_engine()
        engine._get_config = MagicMock(return_value="")
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("已派发 Administrator 起草验证契约", note)
        # 验证信号已写入
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.tmp)
        signals = [r for r in store.read_all()
                   if r.get("kind") == SIGNAL
                   and r.get("signal_type") == "verify_contract_missing"
                   and r.get("spec") == "spec-a"]
        self.assertEqual(len(signals), 1)
        self.assertIn("parse_error=否", signals[0].get("evidence", ""))

    def test_prepare_failure_no_signal(self):
        """prepare 失败不产生 verify_contract_missing 信号（回归保护）。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: \"exit 1\"\nserve:\n  kind: static\n  root: site\n")
        self._scenarios([{"id": "w1", "kind": "web",
                          "steps": [{"action": "navigate",
                                     "value": "http://localhost:59999/"}],
                          "assertions": []}])
        engine = self._mk_engine()
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("prepare 失败", note)
        # 验证信号未写入
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.tmp)
        signals = [r for r in store.read_all()
                   if r.get("kind") == SIGNAL
                   and r.get("signal_type") == "verify_contract_missing"]
        self.assertEqual(len(signals), 0)

    def test_parse_error_detected(self):
        """契约解析失败时 parse_error 标注为「是」。"""
        _write(self.tmp, ".fenix/verify.yaml", "prepare: [unclosed")
        self._scenarios([{"id": "w1", "kind": "web",
                          "steps": [{"action": "navigate",
                                     "value": "http://localhost:59999/"}],
                          "assertions": []}])
        engine = self._mk_engine()
        engine._get_config = MagicMock(return_value="")
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("已派发 Administrator 起草验证契约", note)
        # 验证信号已写入且 parse_error=是
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.tmp)
        signals = [r for r in store.read_all()
                   if r.get("kind") == SIGNAL
                   and r.get("signal_type") == "verify_contract_missing"
                   and r.get("spec") == "spec-a"]
        self.assertEqual(len(signals), 1)
        self.assertIn("parse_error=是", signals[0].get("evidence", ""))


class _FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)

    def update_spec(self, name, updates):
        return True

    def hasattr_update(self):
        return True


class _FakeRunner:
    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        from core.agent_runner import AdminDisposition
        return AdminDisposition(
            run_id="admin-redraft-1",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：复核现有契约有效；结果：按授权重起草。",
        )


class TestVerifyContractRedraftSignal(unittest.TestCase):
    """verify_contract_redraft 信号被 admin_monitor 摄取唤起 Administrator（4.2）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_redraft_signal_picked_up_and_admin_invoked(self):
        """未 escalated 的 redraft 信号被巡检拾取、按 evidence 提取项目名唤起。"""
        from core.admin_monitor import AdminMonitor, SIGNAL_RECOMMENDATION, STORED_SIGNAL_TYPES
        from core.admin_store import AdminStore, SIGNAL
        # 注册断言：类型已纳入 STORED_SIGNAL_TYPES（摄取管道一致）
        self.assertIn("verify_contract_redraft", STORED_SIGNAL_TYPES)
        # 指引区别于 missing 且含复核/显式授权语义
        rec = SIGNAL_RECOMMENDATION["verify_contract_redraft"]
        self.assertIn("复核现有契约有效性", rec)
        self.assertIn("用户已显式授权覆盖", rec)
        self.assertNotEqual(rec, SIGNAL_RECOMMENDATION["verify_contract_missing"])
        self.assertNotIn("起草 .fenix/verify.yaml 验证契约", rec.split("复核现有契约有效性")[0])

        store = AdminStore(self.tmp, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_contract_redraft",
            "spec": None,  # UI 手动触发：spec 留空，项目名从 evidence 提取
            "severity": "major",
            "description": "AI 起草验证契约请求（UI 手动触发）",
            "evidence": "项目名=fenixd; 覆盖确认=是",
            "source": "ui-manual",
            "overwrite": True,
        })
        runner = _FakeRunner()
        mon = AdminMonitor(
            {"admin": {"enabled": True}},
            _FakeSM({"fenixd": {"status": "testing"}}),
            self.tmp,
            _FakeLogger(),
            store=store,
            agent_runner=runner,
        )
        signals = mon.run_once()

        self.assertEqual(len(runner.calls), 1, "redraft 信号应唤起 Administrator 一次")
        call = runner.calls[0]
        self.assertEqual(call["signal_type"], "verify_contract_redraft")
        self.assertEqual(call["spec"], "fenixd", "项目名应从 evidence 提取")
        self.assertIn("复核现有契约有效性", call["recommended_action"])
        self.assertGreaterEqual(len(signals), 1)
        # 摄取后源记录已 escalated（同记录不反复唤起）
        self.assertTrue(all(
            r.get("escalated")
            for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "verify_contract_redraft"
        ))

    def test_redraft_signal_not_reinvoked_next_tick(self):
        """已 escalated 的 redraft 记录下一巡检不重复唤起。"""
        from core.admin_monitor import AdminMonitor
        from core.admin_store import AdminStore, SIGNAL
        store = AdminStore(self.tmp, _FakeLogger())
        rec = store.append({
            "kind": SIGNAL,
            "signal_type": "verify_contract_redraft",
            "spec": None,
            "severity": "major",
            "description": "AI 起草验证契约请求（UI 手动触发）",
            "evidence": "项目名=fenixd; 覆盖确认=是",
            "source": "ui-manual",
            "overwrite": True,
        })
        store.mark_escalated(rec["id"])
        runner = _FakeRunner()
        mon = AdminMonitor(
            {"admin": {"enabled": True}},
            _FakeSM({"fenixd": {"status": "testing"}}),
            self.tmp,
            _FakeLogger(),
            store=store,
            agent_runner=runner,
        )
        mon.run_once()
        self.assertEqual(len(runner.calls), 0, "已 escalated 记录不得反复唤起")


class TestPermissionBoundary(unittest.TestCase):
    """权限边界测试：有效契约不被覆盖，失效契约可修正。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_valid_contract_not_overwritten(self):
        """有效契约不被覆盖（权限边界）。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo ok\nserve:\n  kind: static\n  root: site\n")
        original_content = (self.tmp / ".fenix" / "verify.yaml").read_text()
        original_mtime = (self.tmp / ".fenix" / "verify.yaml").stat().st_mtime_ns

        result = validate_contract(self.tmp)
        self.assertTrue(result.valid)

        # 验证文件未被修改
        current_content = (self.tmp / ".fenix" / "verify.yaml").read_text()
        current_mtime = (self.tmp / ".fenix" / "verify.yaml").stat().st_mtime_ns
        self.assertEqual(original_content, current_content)
        self.assertEqual(original_mtime, current_mtime)

    def test_invalid_contract_can_be_fixed(self):
        """失效契约可修正（权限边界）。"""
        # 写入一个 serve.kind 非法的契约
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: bogus\n  root: site\n")
        result = validate_contract(self.tmp)
        self.assertFalse(result.valid)
        self.assertIn("非法", result.serve_error)

        # 修正契约
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: static\n  root: site\n")
        result2 = validate_contract(self.tmp)
        self.assertTrue(result2.valid)

    def test_cli_valid_contract_returns_zero(self):
        """CLI 对有效契约返回 exit 0。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo ok\nserve:\n  kind: static\n  root: site\n")
        _write(self.tmp, "site/index.html", "hello")

        import subprocess
        cli = Path(__file__).resolve().parent.parent / "bin" / "fenix_verify_contract.py"
        r = subprocess.run(
            [sys.executable, str(cli), str(self.tmp)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("通过", r.stdout)


class TestDraftFullFlow(unittest.TestCase):
    """起草收尾演练：契约落盘 → git 提交 → spec 状态复位 ready。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / ".fenix").mkdir()
        (self.tmp / ".fenix" / "runs").mkdir()
        (self.tmp / ".fenix" / "verify-progress" / "spec-a" / "screenshots").mkdir(parents=True)
        (self.tmp / "spec" / "changes" / "spec-a" / "specs").mkdir(parents=True)

    def _git(self, *args):
        import subprocess
        r = subprocess.run(["git", "-C", str(self.tmp), *args],
                           capture_output=True, text=True)
        return r

    def _init_repo(self):
        self._git("init", "-q")
        self._git("config", "user.email", "t@fenix.local")
        self._git("config", "user.name", "T")
        # 写入 STATE.md
        _write(self.tmp, ".fenix/STATE.md",
               "# Fenix Project State\n\n## Specs\n\n### spec-a\n"
               "- status: testing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
               "- updated: 2026-01-02T00:00:00+00:00\n- error: null\n- depends_on: null\n")
        self._git("add", "-A")
        self._git("commit", "-q", "-m", "base")

    def test_draft_commit_and_spec_reset(self):
        """契约落盘 → git 提交 → spec 状态复位 ready。"""
        self._init_repo()

        # 模拟起草：写入有效契约
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: echo ok\nserve:\n  kind: static\n  root: site\n")
        _write(self.tmp, "site/index.html", "hello")

        # 校验契约
        result = validate_contract(self.tmp)
        self.assertTrue(result.valid, f"契约应有效: {result.serve_error} {result.ready_error}")

        # git 提交
        self._git("add", ".fenix/verify.yaml")
        r = self._git("commit", "-q", "-m", "[fenix] admin: 起草验证契约 spec-a")
        self.assertEqual(r.returncode, 0, f"git commit 失败: {r.stderr}")

        # 验证提交存在
        log = self._git("log", "--oneline", "-1")
        self.assertIn("起草验证契约", log.stdout)

        # spec 状态复位 ready（模拟 Administrator 动作）
        state_path = self.tmp / ".fenix" / "STATE.md"
        state_content = state_path.read_text()
        # 将 testing 改为 ready
        state_content = state_content.replace("- status: testing", "- status: ready")
        state_path.write_text(state_content)

        # 验证状态已更新
        updated_state = state_path.read_text()
        self.assertIn("- status: ready", updated_state)
        self.assertNotIn("- status: testing", updated_state)

    def test_ready_timeout_returns_invalid(self):
        """ready 探针超时 → ready_ok=False，valid=False。"""
        # 启动一个不响应的服务器
        class NoResponseHandler(SimpleHTTPRequestHandler):
            def do_GET(self):
                # 永不响应
                pass

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), NoResponseHandler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]

        # 测试 probe_ready 超时
        ok, note = probe_ready(
            f"http://127.0.0.1:{port}",
            ReadyProbe(url="/", expect=200, timeout=2))
        self.assertFalse(ok)
        self.assertIn("超时", note)


class TestValidateContractCLI(unittest.TestCase):
    """fenix_verify_contract.py CLI 退出码测试。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cli = Path(__file__).resolve().parent.parent / "bin" / "fenix_verify_contract.py"

    def _run_cli(self, *args):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(self.cli), *args],
            capture_output=True, text=True, cwd=str(self.tmp))
        return r.returncode, r.stdout, r.stderr

    def test_missing_contract_exit_1(self):
        """契约不存在 → exit 1。"""
        code, out, err = self._run_cli(str(self.tmp))
        self.assertEqual(code, 1)
        self.assertIn("不存在", out + err)

    def test_valid_contract_exit_0(self):
        """健康契约 → exit 0。"""
        _write(self.tmp, ".fenix/verify.yaml", FULL_CONTRACT)
        _write(self.tmp, "site/index.html", "hello")
        code, out, err = self._run_cli(str(self.tmp))
        self.assertEqual(code, 0)
        self.assertIn("通过", out)

    def test_prepare_failure_exit_2(self):
        """prepare 失败 → exit 2。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "prepare:\n  - run: \"exit 1\"\nserve:\n  kind: static\n  root: site\n")
        code, out, err = self._run_cli(str(self.tmp))
        self.assertEqual(code, 2)
        self.assertIn("失败", out)
        # serve 段因 prepare 失败未启动，不得显示「✓ 通过」（item 3d9623096956）
        self.assertIn("未启动", out)
        self.assertNotIn("[serve]   ✓", out)

    def test_serve_failure_exit_3(self):
        """serve 失败 → exit 3。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: static\n  root: nonexistent\n")
        code, out, err = self._run_cli(str(self.tmp))
        self.assertEqual(code, 3)
        self.assertIn("失败", out)

    def test_invalid_serve_kind_exit_5(self):
        """serve.kind 非法 → exit 5。"""
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: bogus\n  root: site\n")
        code, out, err = self._run_cli(str(self.tmp))
        self.assertEqual(code, 5)
        self.assertIn("无效", out)


class TestVerifyRegressionMissingSignal(unittest.TestCase):
    """verify_regression_missing 信号注册 + admin_monitor 摄取唤起 Administrator。

    场景：契约有效但缺 regression 段（信号现由 code_fix 验证撞墙/周期检查点等
    非 UI 生产者写入——设置页「质量」页签的「AI 自动生成」已改同步起草，不再
    写信号）→ 巡检按 evidence 项目名解析唤起 Administrator，仅补 regression 段。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_signal_registered_and_recommendation_semantics(self):
        """注册断言：类型纳入摄取管道、severity major、指引含「仅补段」语义。"""
        from core.admin_monitor import (
            SIGNAL_RECOMMENDATION,
            SIGNAL_SEVERITY,
            STORED_SIGNAL_TYPES,
        )

        self.assertIn("verify_regression_missing", STORED_SIGNAL_TYPES)
        self.assertEqual(SIGNAL_SEVERITY["verify_regression_missing"], "major")
        rec = SIGNAL_RECOMMENDATION["verify_regression_missing"]
        self.assertIn("仅补 regression 段", rec)
        self.assertIn("MUST NOT 改动", rec)
        # 指引区别于整契约起草（missing）与覆盖重起草（redraft）
        self.assertNotEqual(rec, SIGNAL_RECOMMENDATION["verify_contract_missing"])
        self.assertNotEqual(rec, SIGNAL_RECOMMENDATION["verify_contract_redraft"])

    def test_signal_picked_up_and_admin_invoked(self):
        """未 escalated 的 regression_missing 信号被巡检拾取、按 evidence 提取项目名唤起。"""
        from core.admin_monitor import AdminMonitor
        from core.admin_store import AdminStore, SIGNAL

        store = AdminStore(self.tmp, _FakeLogger())
        store.append({
            "kind": SIGNAL,
            "signal_type": "verify_regression_missing",
            "spec": None,  # UI 手动触发：spec 留空，项目名从 evidence 提取
            "severity": "major",
            "description": "AI 补写 regression 段请求（UI 手动触发）",
            "evidence": "项目名=fenixd",
            "source": "ui-manual",
        })
        runner = _FakeRunner()
        mon = AdminMonitor(
            {"admin": {"enabled": True}},
            _FakeSM({"fenixd": {"status": "testing"}}),
            self.tmp,
            _FakeLogger(),
            store=store,
            agent_runner=runner,
        )
        signals = mon.run_once()

        self.assertEqual(len(runner.calls), 1, "regression_missing 信号应唤起 Administrator 一次")
        call = runner.calls[0]
        self.assertEqual(call["signal_type"], "verify_regression_missing")
        self.assertEqual(call["spec"], "fenixd", "项目名应从 evidence 提取")
        self.assertIn("仅补 regression 段", call["recommended_action"])
        self.assertGreaterEqual(len(signals), 1)
        # 摄取后源记录已 escalated（同记录不反复唤起）
        self.assertTrue(all(
            r.get("escalated")
            for r in store.read_all()
            if r.get("kind") == SIGNAL
            and r.get("signal_type") == "verify_regression_missing"
        ))


if __name__ == "__main__":
    unittest.main()
