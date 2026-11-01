"""add-distill-run-artifacts 1.2：蒸馏批 run 产物单测。

覆盖 specs/distill-run-artifacts「蒸馏批次产出 run 产物」Requirement 全部
Scenario：

- 批成功 → 产物末行 ``type=result``、首行 started 带 timestamp、
  run_id 归属 knowledge-distiller、spec 段=归档目录名；
- spawn 失败 give_up → 末行 ``type=error`` 带 reason、classify_run 判 error；
- 多修正轮 → 同产物行数递增（started + 每轮 round 行）且终态判定不变；
- 产物目录/写入 OSError 注入 → 蒸馏 result/台账行为与无产物形态完全一致
  （fail-open，无异常外泄）；
- 一批多归档 → run_id 中段取首归档名、开始行 ``archived`` 含全名单。

运行：python3 -m pytest tests/test_knowledge_distill_run_artifacts.py -q
"""

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_runner.run_files import (
    infer_run_agent_type,
    run_spec_part,
)
from core.dashboard.data.runs import RUN_STALE_SECONDS, classify_run
from core.knowledge import DistillManager
from test_knowledge import (
    GOOD_PAGE,
    KNOWLEDGE_DIR,
    STAMP,
    KnowledgeTestBase,
    _FakeProc,
)


class TestDistillRunArtifacts(KnowledgeTestBase):
    """批生命周期产物：成功/失败/修正轮/OSError fail-open/多归档。"""

    def _git_init(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("commit", "-q", "--allow-empty", "-m", "init")

    def _manager(self, on_spawn, returncode=0, max_fix_rounds=2):
        mgr = DistillManager(max_fix_rounds=max_fix_rounds)

        def spawn(cmd, cwd, env=None):
            on_spawn(cmd, cwd)
            return _FakeProc(returncode)

        mgr._spawn = spawn
        return mgr

    def _spawn_writer(self, versions):
        """按轮次写不同产物的 fake spawn（与 tests/test_knowledge.py 同款）。"""
        state = {"round": 0}

        def on_spawn(cmd, cwd, env=None):
            rnd = min(state["round"], len(versions) - 1)
            state["round"] += 1
            for rel, text in versions[rnd].items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")

        return on_spawn

    def _prompt(self):
        return GOOD_PAGE.format(
            archive=self._archive_name(), today=date.today().isoformat()
        )

    def _index(self):
        return (
            f"# 知识真相源\n{STAMP}\n\n## 能力域\n\n"
            "| 能力域 | 简介 | 能力数量 | 更新时间 |\n"
            "| --- | --- | --- | --- |\n"
            "| [pickup](domains/pickup/_domain.md) | 拣选 | 1 | 2026-09-29 15:02 |\n"
        )

    def _domain(self):
        return (
            f"# 拣选域\n{STAMP}\n\n| 能力页 | 简介 | 更新时间 |\n"
            "| --- | --- | --- |\n"
            "| [定时拣选](scheduled-spec-pickup.md) | 按周期拣选 | 2026-09-29 15:02 |\n"
        )

    def _good_versions(self):
        return {
            f"{KNOWLEDGE_DIR}/index.md": self._index(),
            f"{KNOWLEDGE_DIR}/domains/pickup/_domain.md": self._domain(),
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md": self._prompt(),
        }

    def _artifact_path(self):
        runs = self.root / ".fenix" / "runs"
        files = sorted(runs.glob("knowledge-distiller-*.jsonl"))
        self.assertEqual(len(files), 1, f"蒸馏产物应恰一个，实际 {files}")
        return files[0]

    @staticmethod
    def _lines(path):
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    # ── Scenario: 批成功产物落盘 ─────────────────────────────────────

    def test_success_batch_artifact_terminal_result(self):
        self._git_init()
        mgr = self._manager(self._spawn_writer([self._good_versions()]))
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        artifact = self._artifact_path()
        stem = artifact.stem
        # run_id 形态：knowledge-distiller-<归档名>-<Unix秒>
        self.assertTrue(stem.startswith(f"knowledge-distiller-{self._archive_name()}-"))
        self.assertRegex(stem, r"-\d{9,10}\Z")
        lines = self._lines(artifact)
        # 首行：带 timestamp 的开始事件行（archived 全名单）
        self.assertEqual(lines[0]["type"], "started")
        self.assertIn("timestamp", lines[0])
        self.assertEqual(lines[0]["archived"], [self._archive_name()])
        # 末行：result 终态
        self.assertEqual(lines[-1]["type"], "result")
        self.assertEqual(classify_run(lines), "done")
        # 读侧归属：agent_type=knowledge-distiller、spec 段=归档目录名
        self.assertEqual(infer_run_agent_type(stem)[0], "knowledge-distiller")
        self.assertEqual(run_spec_part(stem), self._archive_name())

    # ── Scenario: 批失败写 error 终态 ────────────────────────────────

    def test_spawn_fail_gives_error_terminal(self):
        self._git_init()
        mgr = self._manager(lambda cmd, cwd: None, returncode=1)
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertFalse(result["ok"])
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "error")
        # error 行携带失败原因摘要（与 result["error"] 同源）
        self.assertTrue(lines[-1].get("error"))
        self.assertIn("非零退出", lines[-1]["error"])
        self.assertEqual(classify_run(lines), "error")

    # ── Scenario: 多修正轮行数递增、终态判定不变 ─────────────────────

    def test_fix_rounds_rows_grow_terminal_stable(self):
        self._git_init()
        bad = {
            f"{KNOWLEDGE_DIR}/domains/pickup/scheduled-spec-pickup.md":
                self._prompt().replace("rev=1", "rev=notanint"),
        }
        versions = [bad, self._good_versions()]
        mgr = self._manager(self._spawn_writer(versions))
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["rounds"], 2)
        lines = self._lines(self._artifact_path())
        # started + 每轮一条 round 行 + 终态 result
        self.assertEqual(
            [l["type"] for l in lines], ["started", "round", "round", "result"]
        )
        self.assertEqual(lines[1]["rounds"], 1)
        self.assertEqual(lines[2]["rounds"], 2)
        # 行数随修正轮递增，终态判定不被中间行改变
        self.assertEqual(lines[-1]["type"], "result")
        self.assertEqual(classify_run(lines), "done")

    # ── Scenario: 产物写失败不阻断蒸馏（OSError 注入，fail-open）─────

    def test_open_oserror_fail_open_result_and_ledger_identical(self):
        """产物创建/开始行 OSError → 蒸馏 result 与台账行为和无产物形态一致。"""
        self._git_init()
        mgr = self._manager(self._spawn_writer([self._good_versions()]))
        with mock.patch(
            "core.knowledge.append_run_line", side_effect=OSError("disk full")
        ):
            result = mgr._run_batch(self.root, [self._archive_name()])
        # 结果形态与无产物形态完全一致（成功提交、轮数、台账清除）
        self.assertTrue(result["ok"])
        self.assertEqual(result["rounds"], 1)
        self.assertTrue(result["commit"])
        self.assertEqual(mgr.pending(self.root), 0)  # pending 台账无滞留
        todo = (self.root / ".fenix" / "todo.md")
        self.assertFalse(todo.exists() and "knowledge-distill 重试" in todo.read_text(encoding="utf-8"))

    def test_terminal_oserror_fail_open_no_raise(self):
        """终态行 OSError → finally 收口自身不抛，蒸馏 error result 照常返回。"""
        self._git_init()
        mgr = self._manager(lambda cmd, cwd: None, returncode=1)
        with mock.patch(
            "core.knowledge.append_run_error", side_effect=OSError("disk full")
        ):
            result = mgr._run_batch(self.root, [self._archive_name()])  # 不抛
        self.assertFalse(result["ok"])
        self.assertIn("非零退出", result["error"])
        # 台账（todo.md 重试条目）与无产物形态一致
        todo = (self.root / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("knowledge-distill", todo)

    def test_batch_exception_writes_error_terminal(self):
        """批中途异常 → 终态 error 行收口后原样上抛（不留断尾 stale 窗口）。"""
        self._git_init()
        mgr = self._manager(lambda cmd, cwd: None, returncode=0)
        with mock.patch(
            "core.knowledge.validate_knowledge",
            side_effect=RuntimeError("validate boom"),
        ):
            with self.assertRaises(RuntimeError):
                mgr._run_batch(self.root, [self._archive_name()])
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "error")
        self.assertIn("validate boom", lines[-1]["error"])
        # 断尾兜底对照：非异常路径若缺终态行只会靠 stale（RUN_STALE_SECONDS）
        # 停更兜底——异常路径由 error 终态行收口，无需等待
        self.assertGreater(RUN_STALE_SECONDS, 0)

    # ── Scenario: 一批多归档 → run_id 中段首归档名 + archived 全名单 ──

    def test_multi_archive_first_name_in_run_id_and_started_line(self):
        a1 = self._archive_name()
        a2 = self._archive_name() + "-2"
        (self.root / "spec" / "archive" / a2).mkdir(parents=True, exist_ok=True)
        self._git_init()
        # 失败批（give_up 路径）即可锁定 run_id 形态与开始行名单，无需构造
        # 多归档合法知识树
        mgr = self._manager(lambda cmd, cwd: None, returncode=1)
        result = mgr._run_batch(self.root, [a1, a2])
        self.assertFalse(result["ok"])
        artifact = self._artifact_path()
        self.assertTrue(artifact.stem.startswith(f"knowledge-distiller-{a1}-"))
        lines = self._lines(artifact)
        self.assertEqual(lines[0]["archived"], [a1, a2])
        self.assertEqual(lines[-1]["type"], "error")


if __name__ == "__main__":
    unittest.main()
