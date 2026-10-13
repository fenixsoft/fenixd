"""
add-evolution-subagent-wait-ceiling：evolution 车道后台子代理等待上限治理测试。

背景（evo-1791048570）：自进化复核 run 把每条条目的核查派给后台子代理后结束
回合，CLI 按 600 秒后台等待上限（CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS，
缺省 600000ms）强杀仍在跑的子代理，产物 json 与 .parts 分片零落盘，整任务
重跑双倍消耗。

按任务组织：
- TestEvolutionBgWaitCeilingEnvInjection（任务 4.1）：run_evolution 组装的
  env_overrides 含 CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS="0"，对照车道
  （run_self_review）组装的 env_overrides 不含该键
- TestEvolutionBgWaitCeilingAttribution（任务 4.2）：契约缺失失败时的
  600 秒上限归因嗅探——含签名 reason 附上限归因、无签名维持原文案
- TestBgWaitCeilingSniffHelper（任务 3.1/4.2 配套）：嗅探辅助函数直接单测
  （只认 stderr 行、引用形态不误判、转录不可读静默跳过）
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from core.agent_runner.maintenance_runs import (
    run_evolution,
    run_self_review,
    _evolution_bg_wait_ceiling_hit,
)


class _RecordingRunner:
    """最小 duck-typed runner 替身：记录 _run_agent 收到的 env_overrides。

    与 test_self_evolution._FakeEvolutionRunner 同型，但显式列出
    run_evolution / run_self_review 实际触达的门面依赖（不继承
    AgentRunner，避免隐式继承面漂移掩盖缺件）。_run_agent 不写产物文件
    ——契约缺失走 read_contract 的 ContractError 失败路径，供归因断言。
    """

    def __init__(self, proot: Path, claude_fn=None):
        self.project_root = Path(proot)
        self.logger = None
        self.calls = []
        self._claude_fn = claude_fn

    def _build_prompt(self, spec_name, agent_type, detail=None, wt_path=None):
        return "fake prompt"

    def _get_agent_model_assignment(self, agent_type):
        return None

    def _get_admin_model(self):
        return "DEFAULT_MODEL"

    def _get_config(self, key, default=None):
        return default

    def _run_agent(self, prompt, cwd, run_id, model_override=None,
                    env_overrides=None, resume_session_id=None,
                    max_turns=None, spec_name=None, agent_type=None):
        self.calls.append({
            "run_id": run_id,
            "env_overrides": dict(env_overrides or {}),
            "spec_name": spec_name,
        })
        if self._claude_fn is not None:
            return self._claude_fn(run_id)
        return "", 1, "session-1", {"input_tokens": 0, "output_tokens": 0}

    def _extract_usage_info(self, result_event):
        return {"input_tokens": 0, "output_tokens": 0}

    def _accumulate_evolution_tokens(self, run_id, usage_info):
        pass

    def _accumulate_self_review_tokens(self, date_str, usage_info):
        pass

    def _delete_evolution_out(self, out_path):
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _clear_self_review_out(self, out_path):
        pass

    def _delete_self_review_out(self, out_path):
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _read_self_review_out(self, out_path):
        return {}


class TestEvolutionBgWaitCeilingEnvInjection(unittest.TestCase):
    """任务 4.1：等待上限归零 env 仅注入 evolution 车道。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "runs").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_evolution_lane_injects_wait_ceiling_zero(self):
        """run_evolution 组装的 env_overrides 含该键且值为 "0"。"""
        runner = _RecordingRunner(self.proot)
        result = run_evolution(runner, [], [])
        self.assertTrue(runner.calls, "应发起 run 调用")
        env = runner.calls[0]["env_overrides"]
        self.assertEqual(
            env.get("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"), "0")
        # 本替身不写产物：契约缺失按失败落地（用例只关心 env 组装）
        self.assertFalse(result.success)

    def test_injection_survives_provider_assignment_path(self):
        """有 provider 分配（_apply_provider_env 改写同一 dict）时键仍在。"""

        class _AssignedRunner(_RecordingRunner):
            def _get_agent_model_assignment(self, agent_type):
                if agent_type == "self-review":
                    return [({"name": "p1", "baseurl": "http://x",
                              "apikey": "k"}, "m1")]
                return None

            def _ensure_agent_config_dir(self, provider_name,
                                         provider_model=""):
                d = self.project_root / ".fenix" / "cc" / provider_name
                d.mkdir(parents=True, exist_ok=True)
                return d

            def _write_lane_provider_marker(self, *a, **k):
                pass

        runner = _AssignedRunner(self.proot)
        run_evolution(runner, [], [])
        self.assertEqual(
            runner.calls[0]["env_overrides"][
                "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"],
            "0",
        )

    def test_control_lane_self_review_does_not_inject(self):
        """对照车道（self-review）组装的 env_overrides 不含该键。"""
        runner = _RecordingRunner(self.proot)
        run_self_review(runner, "2026-10-05", "daily summary")
        self.assertTrue(runner.calls, "应发起 run 调用")
        env = runner.calls[0]["env_overrides"]
        self.assertNotIn("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", env)
        self.assertEqual(runner.calls[0]["spec_name"], "self-review")


class TestEvolutionBgWaitCeilingAttribution(unittest.TestCase):
    """任务 4.2：契约缺失失败时转录 stderr 签名的上限归因。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "runs").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _stderr_line(text):
        return json.dumps({"type": "stderr", "line": text},
                          ensure_ascii=False)

    def _claude_killed_by_ceiling(self, run_id):
        """模拟 CLI 侧 completed（退出码 0）但子代理被 600 秒上限击杀：
        转录尾部落签名 stderr 行，产物 json 与 .parts 零落盘。"""
        transcript = self.proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        transcript.write_text(
            "\n".join([
                json.dumps({"type": "assistant", "line": "子代理已全部派发"},
                           ensure_ascii=False),
                self._stderr_line(
                    "Background tasks still running after 600s: "
                    "Task(9125), Task(9126)"),
            ]) + "\n",
            encoding="utf-8",
        )
        return "", 1, "session-1", {"input_tokens": 0, "output_tokens": 0}

    def test_missing_contract_with_signature_attributes_ceiling(self):
        """产物缺失且转录含 600 秒签名 → reason 附上限归因文案。"""
        runner = _RecordingRunner(
            self.proot, claude_fn=self._claude_killed_by_ceiling)
        result = run_evolution(runner, [], [])
        self.assertFalse(result.success)
        self.assertIn("产物文件未写出", result.error)
        self.assertIn("600 秒", result.error)
        self.assertIn("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", result.error)
        self.assertIn("子代理半成品随 run 作废", result.error)

    def test_missing_contract_without_signature_keeps_reason(self):
        """产物缺失但转录无签名 → reason 维持原文案，不附上限归因。"""

        def _claude_clean(run_id):
            return "", 1, "session-1", {"input_tokens": 0, "output_tokens": 0}

        runner = _RecordingRunner(self.proot, claude_fn=_claude_clean)
        result = run_evolution(runner, [], [])
        self.assertFalse(result.success)
        self.assertTrue(result.error.startswith("产物文件未写出"),
                        result.error)
        self.assertNotIn("600 秒", result.error)
        self.assertNotIn("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", result.error)

    def test_quoted_signature_in_transcript_not_attributed(self):
        """签名仅以引用形态出现在 assistant/user 记录（非 stderr 行）→
        不误判为击杀（evo-1791134863 实测 19 处引用 vs 真 stderr 1 条）。"""
        quoted = "Background tasks still running after 600s"

        def _claude_quoted(run_id):
            transcript = self.proot / ".fenix" / "runs" / f"{run_id}.jsonl"
            transcript.write_text(
                "\n".join([
                    json.dumps({"type": "assistant",
                                "line": f"历史上出现过 {quoted}"},
                               ensure_ascii=False),
                    json.dumps({"type": "user",
                                "line": f"{quoted} 是什么"},
                               ensure_ascii=False),
                ]) + "\n",
                encoding="utf-8",
            )
            return "", 1, "session-1", {"input_tokens": 0,
                                        "output_tokens": 0}

        runner = _RecordingRunner(self.proot, claude_fn=_claude_quoted)
        result = run_evolution(runner, [], [])
        self.assertFalse(result.success)
        self.assertNotIn("CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS", result.error)


class TestBgWaitCeilingSniffHelper(unittest.TestCase):
    """嗅探辅助函数（模块级，供不经完整 run_evolution 装配直接单测）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "runs").mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _runner(self):
        return _RecordingRunner(self.proot)

    def _write_transcript(self, run_id, lines):
        p = self.proot / ".fenix" / "runs" / f"{run_id}.jsonl"
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_signature_in_stderr_line_hits(self):
        self._write_transcript("evo-1", [
            json.dumps({"other": 1}),
            json.dumps({"type": "stderr", "line":
                        "Background tasks still running after 600s: "
                        "Task(9125)"}),
        ])
        self.assertTrue(_evolution_bg_wait_ceiling_hit(self._runner(), "evo-1"))

    def test_signature_case_insensitive(self):
        self._write_transcript("evo-1", [
            json.dumps({"type": "stderr", "line":
                        "BACKGROUND TASKS STILL RUNNING AFTER 600S"}),
        ])
        self.assertTrue(_evolution_bg_wait_ceiling_hit(self._runner(), "evo-1"))

    def test_signature_quoted_in_non_stderr_lines_not_misjudged(self):
        self._write_transcript("evo-1", [
            json.dumps({"type": "assistant", "line":
                        "复核 600s 条目时引用了 Background tasks still "
                        "running after 600s"}),
            json.dumps({"type": "user", "line":
                        "Background tasks still running after 600s 是什么"}),
        ])
        self.assertFalse(
            _evolution_bg_wait_ceiling_hit(self._runner(), "evo-1"))

    def test_missing_transcript_silently_skipped(self):
        """转录不可读（缺失）→ False，不影响原失败路径。"""
        self.assertFalse(
            _evolution_bg_wait_ceiling_hit(self._runner(), "evo-none"))

    def test_corrupt_stderr_line_skipped_others_still_scanned(self):
        """单行损坏跳过，不阻塞其余 stderr 行的嗅探。"""
        self._write_transcript("evo-1", [
            '{"type": "stderr", "line": not-json',
            json.dumps({"type": "stderr", "line":
                        "Background tasks still running after 600s"}),
        ])
        self.assertTrue(_evolution_bg_wait_ceiling_hit(self._runner(), "evo-1"))

    def test_stderr_line_without_signature_no_hit(self):
        self._write_transcript("evo-1", [
            json.dumps({"type": "stderr", "line": "xcrun: error: invalid"}),
        ])
        self.assertFalse(_evolution_bg_wait_ceiling_hit(self._runner(), "evo-1"))


if __name__ == "__main__":
    unittest.main()
