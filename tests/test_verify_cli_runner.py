"""CliRunner 测试（add-verify-multi-kind-runner PR3）。

覆盖 spec multi-kind-scenario-model「CLI 词表与执行语义」语义矩阵：
  - 非零退出码不误判步骤失败（exit_code 断言仲裁）
  - 超时=步骤失败（fail）+ 进程组强杀
  - 信号死亡=error（不进 product-bug 管道）
  - argv 二进制不存在=error
  - 输出 64KB 截断
  - FENIX_VERIFY_BASE_URL/PORT 自动注入且框架值优先
  - file_exists / file_content / json_output / dir_contains 断言
  - 混合场景集跨 kind depends_on 调度（引擎级）
  - 纯 cli 场景集零浏览器（引擎级）
"""

import asyncio
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.verify_engine.api_runner import _truncate as _api_truncate
from core.verify_engine.cli_runner import CliRunner, _truncate
from core.verify_engine.scenarios import TestScenario as Scenario
from core.verify_engine.engine import VerifyEngine
from core.verify_engine.web_runner import WebRunner


def _tmp_project():
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".fenix").mkdir(parents=True, exist_ok=True)
    return tmp


@pytest.mark.parametrize("truncate", [_api_truncate, _truncate], ids=["api", "cli"])
def test_truncate_shared_semantics(truncate):
    """证据截断共享语义（api/cli 两 runner 同规格）：超 64KB 截断带标记且不超限，短文本原样。"""
    body = "x" * (100 * 1024)
    t, truncated = truncate(body)
    assert truncated is True
    assert len(t) <= 64 * 1024
    assert truncate("short")[1] is False


class TestCliRunnerSemantics(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_project()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _runner(self):
        r = CliRunner("spec-a", self.tmp, logger=None, config={})
        r.base_url = "http://127.0.0.1:54321"
        return r

    def _exec(self, sc_dict):
        return asyncio.run(self._runner().execute(Scenario.from_dict(sc_dict)))

    def test_nonzero_exit_not_step_failure(self):
        """错误路径测试：退出码 1 不判步骤失败，exit_code 断言仲裁通过 → pass。"""
        r = self._exec({
            "id": "err", "kind": "cli",
            "steps": [{"action": "run", "command": "exit 1", "as": "e"}],
            "assertions": [{"type": "exit_code", "expected": 1}],
        })
        self.assertEqual(r["status"], "pass")
        self.assertTrue(r["step_results"][0]["success"])
        self.assertEqual(r["step_results"][0]["exit_code"], 1)

    def test_exit_code_mismatch_is_fail(self):
        r = self._exec({
            "id": "err2", "kind": "cli",
            "steps": [{"action": "run", "command": "exit 1"}],
            "assertions": [{"type": "exit_code", "expected": 0}],
        })
        self.assertEqual(r["status"], "fail")
        self.assertFalse(r["assertion_results"][0]["pass"])

    def test_timeout_is_step_failure(self):
        r = self._exec({
            "id": "to", "kind": "cli",
            "steps": [{"action": "run", "command": "sleep 10", "timeout": 0.5}],
            "assertions": [],
        })
        self.assertEqual(r["status"], "fail")
        self.assertEqual(r["step_results"][0]["error_type"], "timeout")
        self.assertIn("进程组", r["step_results"][0]["error"])

    def test_signal_death_is_error(self):
        r = self._exec({
            "id": "segv", "kind": "cli",
            "steps": [{"action": "run", "command": [
                "python3", "-c",
                "import os, signal; os.kill(os.getpid(), signal.SIGSEGV)"]}],
            "assertions": [],
        })
        self.assertEqual(r["status"], "error")
        self.assertEqual(r["step_results"][0].get("signal"), 11)

    def test_missing_binary_is_error(self):
        r = self._exec({
            "id": "nob", "kind": "cli",
            "steps": [{"action": "run", "command": ["/nonexistent/bin/xyz"]}],
            "assertions": [],
        })
        self.assertEqual(r["status"], "error")

    def test_env_injection_framework_priority(self):
        """FENIX_VERIFY_* 自动注入且框架值优先（场景声明被覆盖）。"""
        r = self._exec({
            "id": "env", "kind": "cli",
            "steps": [{"action": "run", "command": "echo $FENIX_VERIFY_PORT",
                       "as": "e",
                       "env": {"FENIX_VERIFY_PORT": "8787"}}],
            "assertions": [
                {"type": "output_match", "expected": "54321", "mode": "contains"},
            ],
        })
        self.assertEqual(r["status"], "pass", r)

    def test_env_interpolation_env_var(self):
        """env 值支持 {env:VAR} 插值。"""
        with mock.patch.dict("os.environ", {"CLI_TEST_TOKEN": "tok-123"}, clear=False):
            r = self._exec({
                "id": "iv", "kind": "cli",
                "steps": [{"action": "run", "command": "echo $MY_TOKEN", "as": "e",
                           "env": {"MY_TOKEN": "{env:CLI_TEST_TOKEN}"}}],
                "assertions": [
                    {"type": "output_match", "expected": "tok-123", "mode": "contains"},
                ],
            })
        self.assertEqual(r["status"], "pass", r)

    def test_output_match_streams_and_modes(self):
        r = self._exec({
            "id": "om", "kind": "cli",
            "steps": [{"action": "run", "command": "echo out; echo err >&2", "as": "o"}],
            "assertions": [
                {"type": "output_match", "stream": "stdout", "expected": "out", "mode": "contains"},
                {"type": "output_match", "stream": "stderr", "expected": "err", "mode": "contains"},
                {"type": "output_match", "stream": "combined", "expected": "out", "mode": "contains"},
                {"type": "output_match", "stream": "stdout", "expected": "^out$", "mode": "regex"},
                {"type": "output_match", "stream": "stdout", "expected": "NOPE", "mode": "contains", "negate": True},
            ],
        })
        self.assertEqual(r["status"], "pass", r["assertion_results"])

    def test_file_assertions(self):
        (self.tmp / "out.json").write_text('{"data": {"id": "x1"}}', encoding="utf-8")
        r = self._exec({
            "id": "fs", "kind": "cli",
            "steps": [
                {"action": "run", "command": "touch created.txt"},
                {"action": "run", "command": [
                    "python3", "-c",
                    "import json; print(json.dumps({'data': {'id': 'x1'}}))"],
                 "as": "gen"},
            ],
            "assertions": [
                {"type": "file_exists", "path": "created.txt"},
                {"type": "file_exists", "path": "nope.txt", "exists": False},
                {"type": "file_content", "path": "out.json", "expected": "x1"},
                {"type": "json_output", "step": "gen", "path": "data.id", "expected": "x1"},
                {"type": "dir_contains", "glob": "*.txt", "min": 1, "max": 3},
            ],
        })
        self.assertEqual(r["status"], "pass", r["assertion_results"])

    def test_file_assertions_reject_non_string_path_glob(self):
        """非字符串 path/glob 显式类型拦截（与 json_output 的类型拦截同口径），
        不静默 str() 归一成字面量路径把场景编写缺陷误归因为文件缺失。"""
        asserter = CliRunner("spec-a", self.tmp, logger=None, config={}).asserter
        results = asyncio.run(asserter.run({}, [
            {"type": "file_exists", "path": 5},
            {"type": "file_content", "path": 5, "expected": "x"},
            {"type": "dir_contains", "glob": 5},
        ]))
        self.assertFalse(results[0]["pass"])
        self.assertIn("path 须为字符串", results[0]["error"])
        self.assertFalse(results[1]["pass"])
        self.assertIn("path 须为字符串", results[1]["error"])
        self.assertFalse(results[2]["pass"])
        self.assertIn("glob 须为字符串", results[2]["error"])

    def test_named_step_reference(self):
        """断言 step 字段引用命名结果（缺省=最近一次）。"""
        r = self._exec({
            "id": "named", "kind": "cli",
            "steps": [
                {"action": "run", "command": "echo first", "as": "first"},
                {"action": "run", "command": "echo second"},
            ],
            "assertions": [
                # 引用命名结果 first（非最近一次 second）
                {"type": "output_match", "step": "first", "expected": "first", "mode": "contains"},
                # 缺省=最近一次 → second
                {"type": "output_match", "expected": "second", "mode": "contains"},
            ],
        })
        self.assertEqual(r["status"], "pass", r["assertion_results"])

    def test_large_json_stdout_parsed_before_evidence_truncation(self):
        """>64KB stdout 的 json_output 断言用完整输出解析（先解析后截断）。

        回归：曾先 `_truncate` 再 `json.loads`，截断体非法 JSON →
        json_output 必然假失败（harness 缺陷）。尾部字段证明完整解析。
        """
        r = self._exec({
            "id": "bigjson", "kind": "cli",
            "steps": [
                {"action": "run", "command": [
                    "python3", "-c",
                    "import json; print(json.dumps({'pad': 'x' * 131072,"
                    " 'deep': {'mark': 'tail-value'}}))"],
                 "as": "gen"},
            ],
            "assertions": [
                # 尾部字段（超出 64KB 窗口）——只有完整解析才命中
                {"type": "json_output", "step": "gen", "path": "deep.mark",
                 "expected": "tail-value"},
            ],
        })
        self.assertEqual(r["status"], "pass", r["assertion_results"])

    def test_large_stdout_evidence_still_truncated(self):
        """证据纪律不变：>64KB stdout 仍截断到 64KB 并带截断标记。"""
        r = self._exec({
            "id": "bigev", "kind": "cli",
            "steps": [
                {"action": "run", "command": [
                    "python3", "-c", "print('x' * 131072)"], "as": "big"},
            ],
            "assertions": [{"type": "exit_code", "expected": 0}],
        })
        self.assertEqual(r["status"], "pass", r["assertion_results"])
        self.assertIn("截断 64KB", r["step_results"][0]["detail"])


# ── 引擎级：混合场景集跨 kind depends_on ──────────────────────────

class TestEngineCliDispatch(unittest.TestCase):
    def setUp(self):
        self.tmp = _tmp_project()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _engine(self):
        return VerifyEngine("spec-a", self.tmp, mock.MagicMock(), {})

    def test_mixed_cli_web_depends_on(self):
        """cli 场景生成文件 → web 场景断言（跨 kind depends_on 顺序编排）。"""
        import time
        ts = str(int(time.time()))
        scenarios = [
            Scenario.from_dict({
                "id": "gen", "kind": "cli",
                "steps": [{"action": "run",
                           "command": f"echo payload > marker-{ts}.txt",
                           "as": "gen"}],
                "assertions": [
                    {"type": "file_exists", "path": f"marker-{ts}.txt"},
                ],
            }),
            Scenario.from_dict({
                "id": "web1", "depends_on": ["gen"],
                "steps": [{"action": "navigate", "value": "http://127.0.0.1:9"}],
                "assertions": [],
            }),
        ]
        web_execute = AsyncMock(return_value={
            "scenario_id": "web1", "description": "", "kind": "web",
            "status": "pass", "step_results": [], "assertion_results": [],
            "visual_results": [], "screenshots": [],
        })
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()), \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()), \
                mock.patch.object(WebRunner, "execute", new=web_execute):
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertTrue((self.tmp / f"marker-{ts}.txt").exists())
        # depends_on 保证 cli 先于 web 执行
        self.assertEqual(web_execute.await_count, 1)

    def test_pure_cli_no_browser(self):
        """纯 cli 场景集：不 setup web runner（零浏览器）。"""
        scenarios = [
            Scenario.from_dict({
                "id": "c1", "kind": "cli",
                "steps": [{"action": "run", "command": "true"}],
                "assertions": [{"type": "exit_code", "expected": 0}],
            }),
        ]
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()) as web_setup, \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()) as web_td:
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))
        web_setup.assert_not_called()
        web_td.assert_not_called()
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertNotIn("web", engine._runners)
        self.assertIsNone(engine.browser)

    def test_cli_layer3_failure_is_fail(self):
        """CLI 第 3 层断言失败 → fail（进入 product-bug 归因管道）。"""
        scenarios = [
            Scenario.from_dict({
                "id": "c1", "kind": "cli",
                "steps": [{"action": "run", "command": "echo real", "as": "o"}],
                "assertions": [
                    {"type": "output_match", "expected": "expected-not-there"},
                ],
            }),
        ]
        engine = self._engine()
        report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["failed"], 1)

    def test_engine_rejects_cross_vocab_step(self):
        """验收门 per-kind 接线：web 词表步骤出现在 cli 场景 → 打回，带词表速查。"""
        scenarios = [
            Scenario.from_dict({
                "id": "bad", "kind": "cli",
                "steps": [{"action": "click", "target": ".x"}],
                "assertions": [],
            }),
        ]
        engine = self._engine()
        report = asyncio.run(engine.run(scenarios))
        self.assertTrue(report.get("env_error"))
        self.assertIn("支持: run", report["env_error"])
        # 验收失败不执行任何场景
        self.assertEqual(report["summary"]["total"], 0)

    def test_report_carries_kind_and_empty_evidence(self):
        """report.json scenarios 透传 kind；cli/api 的 screenshots/visual_results 恒空。"""
        scenarios = [
            Scenario.from_dict({
                "id": "c1", "kind": "cli",
                "steps": [{"action": "run", "command": "true"}],
                "assertions": [{"type": "exit_code", "expected": 0}],
            }),
            Scenario.from_dict({
                "id": "w1",
                "steps": [{"action": "navigate", "value": "http://127.0.0.1:9"}],
                "assertions": [],
            }),
        ]
        web_execute = AsyncMock(return_value={
            "scenario_id": "w1", "description": "", "kind": "web",
            "status": "pass", "step_results": [], "assertion_results": [],
            "visual_results": [], "screenshots": [],
        })
        with mock.patch.object(WebRunner, "setup", new=AsyncMock()), \
                mock.patch.object(WebRunner, "teardown", new=AsyncMock()), \
                mock.patch.object(WebRunner, "execute", new=web_execute):
            engine = self._engine()
            report = asyncio.run(engine.run(scenarios))
        kinds = {sc["scenario_id"]: sc.get("kind") for sc in report["scenarios"]}
        self.assertEqual(kinds, {"c1": "cli", "w1": "web"})
        cli_sc = next(s for s in report["scenarios"] if s["scenario_id"] == "c1")
        self.assertEqual(cli_sc["screenshots"], [])
        self.assertEqual(cli_sc["visual_results"], [])
        # summary 口径不变（blocked-env 仍计入 warning）
        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["passed"], 2)


# ── 场景执行根隔离（fix-verify-cli-cwd-isolation）───────────────────

class TestScenarioRootIsolation(unittest.TestCase):
    """场景执行根（scenario_root）隔离：CLI 步骤缺省 cwd 落验证树而非主树。"""

    def setUp(self):
        self.main_root = _tmp_project()   # 模拟主树
        self.scenario_root = _tmp_project()  # 模拟 serving worktree
        self.addCleanup(shutil.rmtree, self.main_root, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.scenario_root, ignore_errors=True)

    def test_seed_write_falls_to_scenario_root(self):
        """双根隔离：无显式 cwd 的 CLI 步骤，seed 写入落 scenario_root，主树零污染。"""
        engine = VerifyEngine(
            "spec-seed", self.main_root, logger=None, config={},
            scenario_root=self.scenario_root,
        )
        scenarios = [
            Scenario.from_dict({
                "id": "seed-write", "kind": "cli",
                "steps": [
                    # seed 型步骤：相对路径写入 .fenix/STATE.md 和 spec/changes/xxx/tasks.md
                    {"action": "run",
                     "command": "mkdir -p .fenix && echo 'state' > .fenix/STATE.md && "
                                "mkdir -p spec/changes/test-spec && "
                                "echo 'tasks' > spec/changes/test-spec/tasks.md"},
                ],
                "assertions": [
                    {"type": "exit_code", "expected": 0},
                ],
            }),
        ]
        report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["passed"], 1)

        # 写入落在 scenario_root
        self.assertTrue((self.scenario_root / ".fenix" / "STATE.md").exists())
        self.assertTrue((self.scenario_root / "spec" / "changes" / "test-spec" / "tasks.md").exists())

        # 主树零污染
        self.assertFalse((self.main_root / ".fenix" / "STATE.md").exists())
        self.assertFalse((self.main_root / "spec" / "changes" / "test-spec" / "tasks.md").exists())

    def test_no_scenario_root_fallback_to_project_root(self):
        """无 scenario_root 时，CLI 步骤缺省 cwd 回退到 project_root（行为不变）。"""
        engine = VerifyEngine(
            "spec-fallback", self.main_root, logger=None, config={},
            scenario_root=None,
        )
        scenarios = [
            Scenario.from_dict({
                "id": "fallback", "kind": "cli",
                "steps": [
                    {"action": "run", "command": "echo 'hello' > output.txt"},
                ],
                "assertions": [
                    {"type": "exit_code", "expected": 0},
                    {"type": "file_exists", "path": "output.txt"},
                ],
            }),
        ]
        report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["passed"], 1)
        # 文件落主树
        self.assertTrue((self.main_root / "output.txt").exists())
        # scenario_root 不受影响
        self.assertFalse((self.scenario_root / "output.txt").exists())

    def test_bookkeeping_stays_on_main_root(self):
        """引擎簿记路径（verify-progress）仍指向主树 project_root，不随 scenario_root 改变。"""
        engine = VerifyEngine(
            "spec-book", self.main_root, logger=None, config={},
            scenario_root=self.scenario_root,
        )
        scenarios = [
            Scenario.from_dict({
                "id": "book", "kind": "cli",
                "steps": [{"action": "run", "command": "true"}],
                "assertions": [{"type": "exit_code", "expected": 0}],
            }),
        ]
        report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["passed"], 1)

        # 进度文件应写在主树
        progress_path = (
            self.main_root / ".fenix" / "verify-progress" / "spec-book.json"
        )
        self.assertTrue(progress_path.exists(),
                        f"进度文件应写在主树: {progress_path}")

        # scenario_root 无进度文件
        wt_progress = (
            self.scenario_root / ".fenix" / "verify-progress" / "spec-book.json"
        )
        self.assertFalse(wt_progress.exists(),
                         f"进度文件不应写在 scenario_root: {wt_progress}")

    def test_explicit_cwd_resolves_relative_to_scenario_root(self):
        """显式 cwd 相对路径解析到 scenario_root（worktree 轮语义）。

        注意：file_exists 断言的 path 相对验证树根（scenario_root），
        而非 cwd。步骤在 cwd 中创建的文件，断言需用 cwd/文件名 匹配。
        """
        # 在 scenario_root 创建子目录
        sub = self.scenario_root / "mydir"
        sub.mkdir(parents=True, exist_ok=True)

        engine = VerifyEngine(
            "spec-cwd", self.main_root, logger=None, config={},
            scenario_root=self.scenario_root,
        )
        scenarios = [
            Scenario.from_dict({
                "id": "cwd-relative", "kind": "cli",
                "steps": [
                    {"action": "run", "command": "echo 'ok' > result.txt", "cwd": "mydir"},
                ],
                "assertions": [
                    {"type": "exit_code", "expected": 0},
                    # 文件在 mydir/result.txt（cwd相对），断言 path 需相对验证树根
                    {"type": "file_exists", "path": "mydir/result.txt"},
                ],
            }),
        ]
        report = asyncio.run(engine.run(scenarios))
        self.assertEqual(report["summary"]["passed"], 1)
        # 文件落在 scenario_root/mydir/
        self.assertTrue((sub / "result.txt").exists())


if __name__ == "__main__":
    unittest.main()