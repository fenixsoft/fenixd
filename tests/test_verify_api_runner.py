"""ApiRunner 测试（add-verify-multi-kind-runner PR2）。

覆盖 spec verify-runner-engine / multi-kind-scenario-model：
  - http_request 步骤（method/url/headers 插值/body/命名捕获/as）
  - sse_connect 步骤（窗口收集）
  - URL origin 全量改写（路径保留）
  - 断言 response 字段引用命名捕获（缺省=最近一次）
  - 连接失败类=环境候选（探针失联 → blocked-env）
  - 证据 64KB 截断
  - 词表校验与 jsonschema 依赖验收
  - 契约形态反推（纯 cli 短路 / 含 web-api 无 serve 打回）
"""

import asyncio
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine.api_runner import ApiRunner, rewrite_origin
from core.verify_engine.scenarios import TestScenario as Scenario
from core.verify_engine.env_gate import (
    finalize_scenario_status, is_connection_error_candidate,
)
from core.verify_engine.engine import VerifyEngine
from core.verify_engine import runner as runner_module


# ── 本地测试 HTTP 服务夹具 ─────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    """最小 REST 服务：GET /api/specs、POST /api/create、GET /api/stream(SSE)。"""

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if self.path.startswith("/api/stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for i in range(3):
                self.wfile.write(
                    b"data: {\"tick\": %d}\n\n" % i)
                self.wfile.flush()
            return
        if self.path.startswith("/api/specs"):
            body = json.dumps({"data": {"id": "x1", "items": [1, 2, 3]}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Custom", "hello")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        body = json.dumps({"ok": True, "echo": json.loads(raw or b"{}")}).encode()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


class _LocalServer:
    """本地测试 HTTP 服务（serve_forever 守护线程）。"""

    def __init__(self):
        self._httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{self.port}"
        self._t = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._t.start()

    def close(self):
        self._httpd.shutdown()
        self._httpd.server_close()


def _start_server():
    srv = _LocalServer()
    return srv


# ── URL origin 改写 ────────────────────────────────────────────────

class TestRewriteOrigin(unittest.TestCase):
    def test_origin_rewrite_keeps_path(self):
        self.assertEqual(
            rewrite_origin("http://stale-host:9999/api/specs",
                           "http://127.0.0.1:54321"),
            "http://127.0.0.1:54321/api/specs",
        )

    def test_rewrite_keeps_query_and_fragment(self):
        self.assertEqual(
            rewrite_origin("http://stale:1/p?q=2#f", "http://127.0.0.1:9"),
            "http://127.0.0.1:9/p?q=2#f",
        )

    def test_rewrite_bare_origin(self):
        self.assertEqual(
            rewrite_origin("http://stale:1", "http://127.0.0.1:9"),
            "http://127.0.0.1:9",
        )

    def test_no_base_url_noop(self):
        url = "http://stale:1/api"
        self.assertEqual(rewrite_origin(url, ""), url)


# ── ApiRunner 执行 ─────────────────────────────────────────────────

class TestApiRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = _start_server()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def _runner(self):
        r = ApiRunner("spec-a", Path(tempfile.mkdtemp()), logger=None, config={})
        r.base_url = self.srv.base_url
        return r

    def _tmp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp

    def test_multi_request_named_capture(self):
        """多请求流：POST(as:create) 后 GET，断言 response:create 命中 POST 响应。"""
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "flow", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "POST", "url": f"{self.srv.base_url}/api/create",
                 "body": '{"name": "n"}', "body_type": "json", "as": "create"},
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs"},
            ],
            "assertions": [
                {"type": "status_code", "expected": 201, "response": "create"},
                {"type": "status_code", "expected": 200},
                {"type": "json_path", "path": "echo.name", "expected": "n", "response": "create"},
                {"type": "json_path", "path": "data.id", "expected": "x1"},
            ],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "pass", result)
        for a in result["assertion_results"]:
            self.assertTrue(a["pass"], a)

    def test_url_origin_rewrite_at_execution(self):
        """场景写 stale 地址，实际请求打到本次实例（origin 改写，路径保留）。"""
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "rewrite", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": "http://stale-host:9999/api/specs"},
            ],
            "assertions": [{"type": "status_code", "expected": 200}],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "pass")
        step = result["step_results"][0]
        self.assertTrue(step["success"], step)
        self.assertEqual(step["url"], f"{self.srv.base_url}/api/specs")

    def test_headers_env_interpolation(self):
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "hdr", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs",
                 "headers": {"X-Test": "{env:MY_TEST_VAR}"}},
            ],
            "assertions": [{"type": "status_code", "expected": 200}],
        })
        with mock.patch.dict("os.environ", {"MY_TEST_VAR": "hello-world"}, clear=False):
            result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "pass", result)

    def test_sse_connect_collects_events(self):
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "sse", "kind": "api",
            "steps": [
                {"action": "sse_connect", "url": f"{self.srv.base_url}/api/stream",
                 "duration": 2, "as": "events"},
            ],
            "assertions": [
                {"type": "sse_event_count", "min": 2},
                {"type": "sse_event_matches", "expected": "tick"},
            ],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "pass", result)
        self.assertGreaterEqual(result["step_results"][0]["events"], 2)

    def test_latency_layer4_warning_only(self):
        """仅第 4 层断言失败 → warning（非 fail）。"""
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "l4", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs"},
            ],
            "assertions": [
                {"type": "status_code", "expected": 200},
                {"type": "latency_under", "expected": -1},  # 必然失败（第4层）
            ],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "warning")

    def test_layer3_failure_is_fail(self):
        """第 3 层 json_path 断言失败 → fail（进入 product-bug 归因管道）。"""
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "l3", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs"},
            ],
            "assertions": [{"type": "json_path", "path": "data.id", "expected": "WRONG"}],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "fail")

    def test_connection_failure_is_env_candidate(self):
        """连接失败类=环境候选：不判产品缺陷，探针失联 → blocked-env。"""
        r = ApiRunner("spec-a", Path(tempfile.mkdtemp()), logger=None, config={})
        r.base_url = "http://127.0.0.1:1"  # 必然失联
        sc = Scenario.from_dict({
            "id": "down", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": "http://stale:1/api"},
            ],
            "assertions": [{"type": "status_code", "expected": 200}],
        })
        result = asyncio.run(r.execute(sc))
        self.assertEqual(result["status"], "fail")
        self.assertTrue(is_connection_error_candidate(result), result)
        # 探针失联 → 候选降级 blocked-env
        self.assertEqual(finalize_scenario_status(result, probe_healthy=False),
                         "blocked-env")
        # 探针健康 → 维持 fail
        self.assertEqual(finalize_scenario_status(result, probe_healthy=True), "fail")

    def test_evidence_truncated_64kb(self):
        """证据 64KB 截断：超长响应体带截断标记，报告不膨胀。"""
        r = ApiRunner("spec-a", Path(tempfile.mkdtemp()), logger=None, config={})
        # 构造 100KB 响应体（本地 fixture 不返回超长体，改用纯 runner 捕获检查）
        from core.verify_engine.api_runner import _truncate
        body = "x" * (100 * 1024)
        t, truncated = _truncate(body)
        self.assertTrue(truncated)
        self.assertLessEqual(len(t), 64 * 1024)

    def test_unknown_assertion_rejected(self):
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "bad", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs"},
            ],
            "assertions": [{"type": "text_match", "selector": ".x"}],
        })
        result = asyncio.run(r.execute(sc))
        # 词表校验在验收期拒绝（TextScenario.validate → runner.validate）
        errs = r.validate(sc)
        self.assertTrue(any("未知类型" in e for e in errs), errs)

    def test_json_schema_dependency_validated(self):
        """jsonschema 断言验收：库可用则合法；缺失则报错打回。"""
        from core.verify_engine.api_assertions import json_schema_available
        r = self._runner()
        sc = Scenario.from_dict({
            "id": "schema", "kind": "api",
            "steps": [
                {"action": "http_request", "method": "GET", "url": f"{self.srv.base_url}/api/specs"},
            ],
            "assertions": [{"type": "json_schema",
                            "schema": {"type": "object", "required": ["data"]}}],
        })
        if json_schema_available():
            self.assertEqual(r.validate(sc), [])
        else:
            self.assertTrue(any("jsonschema" in e for e in r.validate(sc)))

    def test_probe_env_uses_contract_base_url(self):
        """api 探针：对契约 base_url 做就绪探测（场景 URL 失联也不阻碍）。"""
        r = ApiRunner("spec-a", Path(tempfile.mkdtemp()), logger=None, config={})
        r.base_url = self.srv.base_url
        probe = asyncio.run(r.probe_env([]))
        self.assertTrue(probe["healthy"], probe)
        r2 = ApiRunner("spec-a", Path(tempfile.mkdtemp()), logger=None, config={})
        r2.base_url = "http://127.0.0.1:1"
        probe2 = asyncio.run(r2.probe_env([]))
        self.assertFalse(probe2["healthy"], probe2)


# ── 契约形态反推（serve/ready）────────────────────────────────────

class TestServeReverseInference(unittest.TestCase):
    """纯 cli 场景集短路 / 含 web-api 无 serve 打回。"""

    def _mk(self):
        from test_inplace_bug_repair import _mk_engine
        tmp = Path(tempfile.mkdtemp())
        (tmp / ".fenix").mkdir()
        logger = mock.MagicMock()
        engine, _ = _mk_engine(tmp, logger, {})
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp, engine

    def _write_scenarios(self, tmp, scenarios):
        p = tmp / ".fenix" / "verify-progress" / "spec-a" / "test_scenarios.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(scenarios, ensure_ascii=False), encoding="utf-8")
        return p

    def test_pure_cli_skips_serve(self):
        tmp, engine = self._mk()
        self._write_scenarios(tmp, [{
            "id": "c1", "kind": "cli",
            "steps": [{"action": "run", "command": "true"}], "assertions": [],
        }])
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertTrue(reachable)
        self.assertIn("纯 cli", note)

    def test_pure_cli_does_not_fallback_commands_start(self):
        """纯 cli + config 定义 commands.start：不拉起服务（无人消费的实例不启动）。"""
        tmp, engine = self._mk()
        self._write_scenarios(tmp, [{
            "id": "c1", "kind": "cli",
            "steps": [{"action": "run", "command": "true"}], "assertions": [],
        }])
        engine._get_config = mock.MagicMock(return_value="echo 'started'")
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertTrue(reachable)
        self.assertIn("纯 cli", note)

    def test_web_api_without_serve_rejected(self):
        """含 api 场景 + 无 serve/commands.start → 明确错误打回 plan。"""
        tmp, engine = self._mk()
        self._write_scenarios(tmp, [{
            "id": "a1", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://stale:1/api"}], "assertions": [],
        }])
        engine._get_config = mock.MagicMock(return_value="")
        reachable, blocked, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("serve", note)
        self.assertIn("api", note)

    def test_api_scenario_url_probe_source(self):
        """api http_request URL 参与可达性探测（非 navigate 场景不被跳过）。"""
        tmp, engine = self._mk()
        self._write_scenarios(tmp, [{
            "id": "a1", "kind": "api",
            "steps": [{"action": "http_request", "method": "GET",
                       "url": "http://127.0.0.1:1/api"}], "assertions": [],
        }])
        engine._get_config = mock.MagicMock(return_value="")
        reachable, _, note = engine._verification._ensure_app_reachable("spec-a")
        self.assertFalse(reachable)
        self.assertIn("serve", note)


if __name__ == "__main__":
    unittest.main()