"""验证前置预检门测试（verify-preflight-gate + planner-contract-findings）。

覆盖：
1. resolve_entry_path——serve.cmd 脚本入口机械解析（D1 纯函数，各形态）；
2. entry_preflight_error——入口缺失 fail-fast 错误串（含候选提示）；
3. selfcheck_contract_light——消费期轻量自证 mtime 快照门（D2）；
4. scan_contract / write_contract_findings——planner 出题期契约只读检查（D4）；
5. _contract_findings_section——admin 处置 prompt 情报段注入（零注入/有情报）。
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_contract import (
    entry_preflight_error,
    resolve_entry_path,
    selfcheck_contract_light,
)


def _write(root: Path, rel: str, content: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _bump_mtime(path: Path, ns: int = 1_000_000):
    """显式把文件 mtime 前进若干纳秒（替代 time.sleep 等真实时钟）。"""
    st = path.stat()
    path.touch()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + ns))


class TestResolveEntryPath(unittest.TestCase):
    """resolve_entry_path：脚本入口机械解析（D1 纯函数，零 IO）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_CLEANUP, self.tmp)

    def test_node_single_script(self):
        self.assertEqual(
            resolve_entry_path("node dist/server.js", self.tmp),
            (self.tmp / "dist/server.js").resolve())

    def test_node_with_flags(self):
        """flag 参数（--inspect 等）后取第一个非 flag 参数为入口。"""
        self.assertEqual(
            resolve_entry_path("node --inspect=9229 dist/app.js", self.tmp),
            (self.tmp / "dist/app.js").resolve())

    def test_nodejs_and_tsx_runtimes(self):
        self.assertEqual(
            resolve_entry_path("nodejs server.mjs", self.tmp),
            (self.tmp / "server.mjs").resolve())
        self.assertEqual(
            resolve_entry_path("tsx src/main.ts", self.tmp),
            (self.tmp / "src/main.ts").resolve())

    def test_deno_run_subcommand(self):
        """deno 必须带 run 子命令：入口在子命令之后。"""
        self.assertEqual(
            resolve_entry_path("deno run --allow-net server.ts", self.tmp),
            (self.tmp / "server.ts").resolve())

    def test_bun_run_script_is_package_script(self):
        """bun run <script>：script 可能是 package.json 脚本名，保守跳过。"""
        self.assertIsNone(resolve_entry_path("bun run dev", self.tmp))

    def test_composite_command_skipped(self):
        """复合命令（&&/管道）保守放行（零误杀）。"""
        self.assertIsNone(resolve_entry_path("npm run build && node x.js", self.tmp))
        self.assertIsNone(resolve_entry_path("node a.js | node b.js", self.tmp))
        self.assertIsNone(resolve_entry_path("cd web && node server.js; echo done", self.tmp))

    def test_non_node_runtime_skipped(self):
        self.assertIsNone(resolve_entry_path("python -m http.server", self.tmp))
        self.assertIsNone(resolve_entry_path("npm run dev", self.tmp))
        self.assertIsNone(resolve_entry_path("gunicorn app:app", self.tmp))

    def test_shlex_failure_skipped(self):
        """引号不配对：shlex 解析失败 → None（跳过预检）。"""
        self.assertIsNone(resolve_entry_path('node "unclosed path.js', self.tmp))

    def test_inline_code_flags_skipped(self):
        """node -e / --eval 内联代码形态：无文件入口，跳过。"""
        self.assertIsNone(resolve_entry_path('node -e "console.log(1)"', self.tmp))
        self.assertIsNone(resolve_entry_path('node --eval "x=1"', self.tmp))

    def test_runner_only_no_entry(self):
        """只有 flag 没有入口（node --version 等）→ None。"""
        self.assertIsNone(resolve_entry_path("node --version", self.tmp))

    def test_empty_or_blank_cmd(self):
        self.assertIsNone(resolve_entry_path("", self.tmp))
        self.assertIsNone(resolve_entry_path("   ", self.tmp))


def _CLEANUP(d):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


class TestEntryPreflightError(unittest.TestCase):
    """entry_preflight_error：入口存在性判定 + 候选提示（D1）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_CLEANUP, self.tmp)

    def _mk_contract(self, cmd: str):
        _write(self.tmp, ".fenix/verify.yaml",
               f"serve:\n  kind: command\n  cmd: {cmd}\n")

    def test_entry_exists_passes(self):
        _write(self.tmp, "dist/server.js", "x")
        self.assertIsNone(
            entry_preflight_error("node dist/server.js", self.tmp))

    def test_entry_missing_fails_with_path(self):
        err = entry_preflight_error("node dist/server.js", self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("入口存在性预检失败", err)
        self.assertIn("dist/server.js", err)

    def test_entry_missing_with_candidate_index_js(self):
        """同名目录下 index.js 候选提示（add-web-ui 事故修复路径）。"""
        _write(self.tmp, "dist/server/index.js", "x")
        err = entry_preflight_error("node dist/server.js", self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("dist/server/index.js 存在", err)

    def test_entry_missing_with_same_dir_js_candidate(self):
        _write(self.tmp, "app/helper.js", "x")
        err = entry_preflight_error("node app/entry.js", self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("app/helper.js 存在", err)

    def test_composite_command_passes(self):
        self.assertIsNone(
            entry_preflight_error("npm run build && node x.js", self.tmp))
        self.assertIsNone(entry_preflight_error("python -m x", self.tmp))

    def test_entry_resolved_but_none_returned_after_existing(self):
        """入口存在时 resolve 出路径亦放行（None）。"""
        _write(self.tmp, "server.js", "x")
        self.assertIsNone(entry_preflight_error("node server.js", self.tmp))


class TestSelfcheckContractLight(unittest.TestCase):
    """selfcheck_contract_light：消费期轻量自证 mtime 快照门（D2）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_CLEANUP, self.tmp)
        self.check_path = (self.tmp / ".fenix" / "verify-serving"
                           / "contract_selfcheck.json")

    def _mk_contract(self, yaml: str):
        _write(self.tmp, ".fenix/verify.yaml", yaml)

    def test_no_contract_returns_none(self):
        self.assertIsNone(selfcheck_contract_light(self.tmp))

    def test_mtime_snapshot_hit_skips_second_round(self):
        """首轮自证写快照；契约 mtime 未变 → 次轮零开销命中。

        快照仅在鉴别力自检实际执行（base_url 非空）且通过后落盘
        （item c8b16b879684），probe 打桩免起实例。
        """
        _write(self.tmp, "static/index.html", "<h1>x</h1>")
        self._mk_contract("serve:\n  kind: static\n  root: static\n")
        with mock.patch("core.verify_contract.probe_ready", return_value=(True, "ok")):
            self.assertIsNone(selfcheck_contract_light(self.tmp, base_url="http://127.0.0.1:1"))
        self.assertTrue(self.check_path.is_file())
        # 快照命中：次轮直接放行，不再发起鉴别力自检（probe 零调用）
        with mock.patch("core.verify_contract.probe_ready", return_value=(True, "ok")) as probe:
            self.assertIsNone(selfcheck_contract_light(self.tmp, base_url="http://127.0.0.1:1"))
        probe.assert_not_called()

    def test_mtime_change_triggers_reselfcheck(self):
        """改契约内容（mtime 变化）→ 强制重新自证，不写坏快照。

        首轮快照需鉴别力自检实际执行（base_url 非空 + probe 打桩）才落盘。
        """
        _write(self.tmp, "static/index.html", "<h1>x</h1>")
        self._mk_contract("serve:\n  kind: static\n  root: static\n")
        with mock.patch("core.verify_contract.probe_ready", return_value=(True, "ok")):
            self.assertIsNone(selfcheck_contract_light(self.tmp, base_url="http://127.0.0.1:1"))
        old_mtime = (self.tmp / ".fenix" / "verify.yaml").stat().st_mtime_ns
        self._mk_contract("serve:\n  kind: static\n  root: missing_dir\n")
        # 写后显式把 mtime 推到明显不同于快照的值（os.utime，不真实 sleep；
        # 内核 mtime 粒度可能把两次紧邻写入折到同一 tick，故必须写在 _mk_contract 之后）
        _bump_mtime(self.tmp / ".fenix" / "verify.yaml", ns=1_000_000_000)
        err = selfcheck_contract_light(self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("serve.root 不存在", err)
        # 失败不写快照（保持旧 mtime）→ 下轮 mtime 仍落后，自动重证
        self.assertTrue(self.check_path.is_file())
        snap = json.loads(self.check_path.read_text(encoding="utf-8"))
        self.assertEqual(snap["mtime_ns"], old_mtime)

    def test_static_root_missing_reports(self):
        self._mk_contract("serve:\n  kind: static\n  root: no_such\n")
        err = selfcheck_contract_light(self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("serve.root 不存在", err)

    def test_command_empty_cmd_reports(self):
        self._mk_contract("serve:\n  kind: command\n  cmd: \"\"\n")
        err = selfcheck_contract_light(self.tmp)
        self.assertIsNotNone(err)
        self.assertIn("cmd 为空", err)

    def test_static_valid_writes_snapshot(self):
        """静态合法且鉴别力自检实际执行 → 落快照；无实例的通过路径不落。

        快照落盘门（item c8b16b879684）：base_url 为空时通过也不落快照，
        避免该契约代际内永久旁路鉴别力自检。
        """
        _write(self.tmp, "site/index.html", "x")
        self._mk_contract("serve:\n  kind: static\n  root: site\n")
        self.assertIsNone(selfcheck_contract_light(self.tmp))
        self.assertFalse(self.check_path.is_file())  # 无实例：不落快照
        with mock.patch("core.verify_contract.probe_ready", return_value=(True, "ok")):
            self.assertIsNone(selfcheck_contract_light(self.tmp, base_url="http://127.0.0.1:1"))
        self.assertTrue(self.check_path.is_file())
        snap = json.loads(self.check_path.read_text(encoding="utf-8"))
        self.assertIn("mtime_ns", snap)

    def test_ready_probe_only_when_instance(self):
        """base_url 非空时走 ready 鉴别力自检；探针失败 → 错误串。"""
        _write(self.tmp, "site/index.html", "x")
        self._mk_contract(
            "serve:\n  kind: static\n  root: site\n"
            "ready:\n  url: /\n  expect: 200\n  timeout: 1\n")
        # 无实例地址 → 跳过 ready 自检（不起实例）
        self.assertIsNone(selfcheck_contract_light(self.tmp))
        # 更新契约内容并把 mtime 推到明显不同于快照的值以强制重新自证
        self._mk_contract(
            "serve:\n  kind: static\n  root: site\n"
            "ready:\n  url: /\n  expect: 200\n  timeout: 1\n")
        _bump_mtime(self.tmp / ".fenix" / "verify.yaml", ns=1_000_000_000)
        # 有实例地址但探针失败 → 自证失败（不写快照）
        err = selfcheck_contract_light(self.tmp, base_url="http://127.0.0.1:1")
        self.assertIsNotNone(err)
        self.assertIn("ready", err)


class TestScanContract(unittest.TestCase):
    """scan_contract：出题期契约只读一致性检查（D4 三规则）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_CLEANUP, self.tmp)

    def _mk_contract(self, cmd: str):
        _write(self.tmp, ".fenix/verify.yaml",
               f"serve:\n  kind: command\n  cmd: {cmd}\n")

    def test_no_contract_empty(self):
        from core.verify_engine.scenario_static_check import scan_contract
        self.assertEqual(scan_contract(self.tmp), [])

    def test_non_command_contract_empty(self):
        _write(self.tmp, "site/index.html", "x")
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: static\n  root: site\n")
        from core.verify_engine.scenario_static_check import scan_contract
        self.assertEqual(scan_contract(self.tmp), [])

    def test_entry_missing_rule(self):
        """serve_entry_missing：入口不存在（high）。"""
        self._mk_contract("node dist/server.js")
        from core.verify_engine.scenario_static_check import scan_contract
        findings = scan_contract(self.tmp)
        rules = {f["rule_id"]: f for f in findings}
        self.assertIn("serve_entry_missing", rules)
        self.assertEqual(rules["serve_entry_missing"]["severity"], "high")
        self.assertTrue(
            rules["serve_entry_missing"]["evidence"],
            "证据应含候选提示")

    def test_entry_vs_start_mismatch_rule(self):
        """serve_entry_vs_start_mismatch：serve 入口 ≠ start script 入口（info）。"""
        _write(self.tmp, "dist/server/index.js", "x")
        _write(self.tmp, "dist/server.js", "x")  # serve 入口真实存在
        self._mk_contract("node dist/server.js {port}")
        _write(self.tmp, "package.json",
               json.dumps({"scripts": {"start": "node dist/server/index.js"}}))
        from core.verify_engine.scenario_static_check import scan_contract
        findings = scan_contract(self.tmp)
        rules = {f["rule_id"]: f for f in findings}
        self.assertIn("serve_entry_vs_start_mismatch", rules)
        m = rules["serve_entry_vs_start_mismatch"]
        self.assertEqual(m["severity"], "info")
        self.assertIn("dist/server/index.js", m["evidence"])

    def test_no_port_injection_rule(self):
        """serve_entry_no_port_injection：cmd 无 {port}/$FENIX_VERIFY_PORT（info）。"""
        _write(self.tmp, "dist/server.js", "x")
        self._mk_contract("node dist/server.js")
        from core.verify_engine.scenario_static_check import scan_contract
        findings = scan_contract(self.tmp)
        rules = {f["rule_id"]: f for f in findings}
        self.assertIn("serve_entry_no_port_injection", rules)
        self.assertEqual(rules["serve_entry_no_port_injection"]["severity"], "info")
        # cmd 引用 {port} → 无该 finding
        _write(self.tmp, ".fenix/verify.yaml",
               "serve:\n  kind: command\n  cmd: node dist/server.js {port}\n")
        findings2 = scan_contract(self.tmp)
        self.assertNotIn(
            "serve_entry_no_port_injection",
            {f["rule_id"] for f in findings2})

    def test_healthy_contract_no_findings(self):
        """契约正确（入口存在 + start 一致 + {port} 注入）→ 空 findings。"""
        _write(self.tmp, "dist/server.js", "x")
        self._mk_contract("node dist/server.js {port}")
        _write(self.tmp, "package.json",
               json.dumps({"scripts": {"start": "node dist/server.js"}}))
        from core.verify_engine.scenario_static_check import scan_contract
        self.assertEqual(scan_contract(self.tmp), [])

    def test_write_contract_findings_overwrites(self):
        """write_contract_findings 覆盖写 contract_findings.json。"""
        from core.verify_engine.scenario_static_check import (
            write_contract_findings,
        )
        write_contract_findings(self.tmp, "spec-x", [
            {"rule_id": "serve_entry_no_port_injection", "severity": "info",
             "message": "m", "evidence": "e"},
        ])
        p = (self.tmp / ".fenix" / "verify-progress" / "spec-x"
             / "contract_findings.json")
        self.assertTrue(p.is_file())
        data = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        # 空 findings 覆盖写为空数组
        write_contract_findings(self.tmp, "spec-x", [])
        data2 = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(data2, [])


class TestContractFindingsSection(unittest.TestCase):
    """_contract_findings_section：admin 处置 prompt 情报段注入（D4）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_CLEANUP, self.tmp)
        from core.agent_runner.prompt_builder import PromptBuilder
        self.builder = PromptBuilder(SimpleNamespace(project_root=self.tmp))

    def _mk_findings(self, spec_name: str, findings: list):
        p = (self.tmp / ".fenix" / "verify-progress" / spec_name
             / "contract_findings.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")

    def test_missing_findings_zero_injection(self):
        self.assertEqual(self.builder._contract_findings_section("spec-x"), "")

    def test_empty_findings_zero_injection(self):
        self._mk_findings("spec-x", [])
        self.assertEqual(self.builder._contract_findings_section("spec-x"), "")

    def test_corrupt_findings_zero_injection(self):
        p = (self.tmp / ".fenix" / "verify-progress" / "spec-x"
             / "contract_findings.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        self.assertEqual(self.builder._contract_findings_section("spec-x"), "")

    def test_findings_rendered_with_evidence_and_caveat(self):
        self._mk_findings("spec-x", [{
            "rule_id": "serve_entry_missing", "severity": "high",
            "message": "入口不存在: /p/dist/server.js",
            "evidence": "入口存在性预检失败: /p/dist/server.js 不存在（候选: ...）",
        }])
        section = self.builder._contract_findings_section("spec-x")
        self.assertIn("契约静态检查情报", section)
        self.assertIn("serve_entry_missing", section)
        self.assertIn("high", section)
        self.assertIn("evidence", section)
        self.assertIn("机械检出", section)
        self.assertIn("修正契约是你的职责", section)


if __name__ == "__main__":
    unittest.main()