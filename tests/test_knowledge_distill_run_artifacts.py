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
import threading
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent_runner.run_files import (
    append_run_line as _real_append_line,
    infer_run_agent_type,
    run_spec_part,
)
from core.dashboard.data.runs import (
    RUN_STALE_SECONDS,
    _is_run_archivable,
    classify_run,
    get_runs,
    runs_retention_check,
)
from core.knowledge import DistillManager
from test_knowledge import (
    GOOD_PAGE,
    KNOWLEDGE_DIR,
    STAMP,
    KnowledgeTestBase,
    _FakeProc,
)


class _StdoutProc(_FakeProc):
    """带 stdout 的 fake spawn 产物（工作总结数据源验证用）。"""

    def __init__(self, stdout, returncode=0):
        super().__init__(returncode)
        self._stdout = stdout

    def communicate(self, prompt=None, timeout=None):
        return self._stdout, ""


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

    def _manager_with_stdout(self, on_spawn, stdout, returncode=0):
        """spawn 替身返回带 stdout 的产物（终态行总结字段验证用）。"""
        mgr = DistillManager(max_fix_rounds=2)

        def spawn(cmd, cwd, env=None):
            on_spawn(cmd, cwd)
            return _StdoutProc(stdout, returncode)

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

    # ── Scenario: 主蒸馏成功且 agent 输出总结（终态行带 result 字段）──

    def test_success_batch_terminal_line_carries_summary(self):
        self._git_init()
        stdout = (
            "## 工作总结\n\n- 蒸馏能力页：scheduled-spec-pickup\n"
            "- 修订规则：拣选周期 rev+1\n\nKNOWLEDGE_DISTILL_DONE\n"
        )
        expected = (
            "## 工作总结\n\n- 蒸馏能力页：scheduled-spec-pickup\n"
            "- 修订规则：拣选周期 rev+1"
        )
        mgr = self._manager_with_stdout(
            self._spawn_writer([self._good_versions()]), stdout
        )
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], expected)
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "result")
        # 终态行 result 字段 = stdout 剥标记后的文本（读侧契约字段名 result）
        self.assertEqual(lines[-1]["result"], expected)
        self.assertNotIn("KNOWLEDGE_DISTILL_DONE", lines[-1]["result"])

    # ── Scenario: stdout 空/仅标记行 → fail-open 不写 result 键 ──────

    def test_empty_stdout_no_result_key_batch_ok(self):
        self._git_init()
        # _FakeProc.communicate 恒返回 ("", "")——stdout 空形态
        mgr = self._manager(self._spawn_writer([self._good_versions()]))
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertTrue(result["ok"])
        self.assertNotIn("summary", result)
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "result")
        self.assertNotIn("result", lines[-1])

    def test_marker_only_stdout_no_result_key_batch_ok(self):
        self._git_init()
        mgr = self._manager_with_stdout(
            self._spawn_writer([self._good_versions()]),
            "KNOWLEDGE_DISTILL_DONE\n",
        )
        result = mgr._run_batch(self.root, [self._archive_name()])
        # 仅标记行 → 总结剥空 → 不写键，批成功与台账行为不受影响
        self.assertTrue(result["ok"])
        self.assertNotIn("summary", result)
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "result")
        self.assertNotIn("result", lines[-1])

    # ── Scenario: 失败路径不携带总结 ─────────────────────────────────

    def test_spawn_fail_batch_terminal_no_summary(self):
        self._git_init()
        mgr = self._manager_with_stdout(
            lambda cmd, cwd: None, "这段总结不该出现", returncode=1
        )
        result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertFalse(result["ok"])
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "error")
        self.assertNotIn("result", lines[-1])
        self.assertNotIn(
            "这段总结不该出现", json.dumps(lines[-1], ensure_ascii=False)
        )

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


class TestDistillBatchHeartbeat(KnowledgeTestBase):
    """fix-distill-observation-gaps 2.2：蒸馏批心跳保活。

    覆盖 specs/distill-observation-fixes「蒸馏批心跳保活」Requirement 全部
    Scenario：

    - 长跑批（spawn 阻塞超 stale 阈值档位）→ 产物出现非终态心跳行、读侧判
      running 非 stale、retention 可归档判定 False（不被提前移出活跃目录）；
    - 批收尾终态行成为末行（classify_run 判 done/error 正确，心跳不扰终态）；
    - 心跳追加 OSError → 静默放弃本轮，批行为与无心跳形态一致；
    - 产物创建 fail-open（run_file=None）→ 不启动心跳线程；
    - 批异常路径线程不留存活。

    时间注入：替身 spawn 阻塞（Event 等待）模拟长跑，``_DISTILL_HEARTBEAT_SECONDS``
    打小值令心跳在测试时窗内真实落盘；读侧 stale 判定按真实墙钟 mtime——
    心跳行持续刷新 mtime 即「停更未超时」的真实证明。
    """

    HB_INTERVAL = 0.05  # 心跳间隔注入值（秒）：测试时窗内必落多行

    def _git_init(self):
        self._git("init", "-q")
        self._git("config", "user.name", "t")
        self._git("config", "user.email", "t@t")
        self._git("commit", "-q", "--allow-empty", "-m", "init")

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

    @staticmethod
    def _try_lines(path):
        """并发读产物（写侧持续 append）：半行窗口容忍，读失败返回 None 重试。"""
        try:
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (json.JSONDecodeError, OSError):
            return None

    def _wait_heartbeat(self, artifact, timeout=10.0):
        """轮询直至产物出现心跳行（阻塞 spawn 期间的心跳落盘），返回行列表。"""
        deadline = time.time() + timeout
        lines = None
        while time.time() < deadline:
            lines = self._try_lines(artifact) if artifact.exists() else None
            if lines and any(l.get("type") == "heartbeat" for l in lines):
                return lines
            time.sleep(0.02)
        self.fail(f"阻塞 spawn 期间产物未出现心跳行：{lines}")

    def _hb_thread_alive(self):
        return any(
            th.name == "distill-run-heartbeat" for th in threading.enumerate()
        )

    def _blocking_spawn(self, started, release, returncode=0):
        """替身 spawn：阻塞在 release 事件上模拟超 stale 阈值的长跑。"""

        def spawn(cmd, cwd, env=None):
            started.set()
            release.wait(timeout=30)
            return _FakeProc(returncode)

        return spawn

    # ── Scenario: 长跑批不被判 stale ─────────────────────────────────

    def test_long_spawn_heartbeat_running_not_stale_retention_holds(self):
        self._git_init()
        started, release = threading.Event(), threading.Event()
        mgr = DistillManager(max_fix_rounds=0)
        # 失败批（returncode=1）即可覆盖 give_up 路径的 error 终态收口
        mgr._spawn = self._blocking_spawn(started, release, returncode=1)
        box = {}

        def batch():
            box["result"] = mgr._run_batch(self.root, [self._archive_name()])

        with mock.patch(
            "core.knowledge._DISTILL_HEARTBEAT_SECONDS", self.HB_INTERVAL
        ):
            t = threading.Thread(target=batch)
            t.start()
            self.assertTrue(started.wait(timeout=10))
            artifact = self._artifact_path()
            lines = self._wait_heartbeat(artifact)
            self.assertEqual(lines[0]["type"], "started")
            # 末行心跳非终态 → 读侧判 running 非 stale（真实墙钟 mtime 新鲜）
            self.assertEqual(lines[-1]["type"], "heartbeat")
            self.assertEqual(classify_run(lines), "running")
            rows = get_runs(self.root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "running")
            self.assertNotEqual(rows[0]["status"], "stale")
            # retention 可归档判定 False：running 且停更未超时不移出活跃目录
            self.assertFalse(_is_run_archivable(artifact))
            retention = runs_retention_check(self.root)
            self.assertEqual(retention["moved"], 0)
            self.assertTrue(artifact.exists())
            release.set()
            t.join(timeout=30)
        self.assertFalse(t.is_alive())
        # 失败批 result 形态与无心跳口径一致
        result = box["result"]
        self.assertFalse(result["ok"])
        # 批收尾 error 终态行成为末行（覆盖心跳行的 running 判定）
        lines = self._lines(artifact)
        self.assertEqual(lines[-1]["type"], "error")
        self.assertTrue(any(l["type"] == "heartbeat" for l in lines))
        self.assertEqual(classify_run(lines), "error")
        # 线程生命周期严格限于批执行窗口：收尾后不留存活
        self.assertFalse(self._hb_thread_alive())

    # ── Scenario: 终态覆盖心跳（done 路径）────────────────────────────

    def test_terminal_result_last_over_heartbeats_done(self):
        self._git_init()
        started, release = threading.Event(), threading.Event()

        def spawn(cmd, cwd, env=None):
            started.set()
            release.wait(timeout=30)
            # 释放后写合法知识页 → 正常提交收口 result 终态
            for rel, text in self._good_versions().items():
                p = Path(cwd) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            return _FakeProc(0)

        mgr = DistillManager(max_fix_rounds=0)
        mgr._spawn = spawn
        with mock.patch(
            "core.knowledge._DISTILL_HEARTBEAT_SECONDS", self.HB_INTERVAL
        ):
            t = threading.Thread(
                target=lambda: mgr._run_batch(self.root, [self._archive_name()])
            )
            t.start()
            self.assertTrue(started.wait(timeout=10))
            self._wait_heartbeat(self._artifact_path())
            release.set()
            t.join(timeout=30)
        self.assertFalse(t.is_alive())
        lines = self._lines(self._artifact_path())
        # 行形态：started + 心跳*/round*/终态 result（终态行 MUST 为末行；
        # round 与心跳的相对顺序随线程时序浮动，不作强断言）
        self.assertEqual(lines[0]["type"], "started")
        self.assertEqual(lines[-1]["type"], "result")
        self.assertTrue(any(l["type"] == "heartbeat" for l in lines))
        self.assertTrue(any(l["type"] == "round" for l in lines))
        self.assertEqual(classify_run(lines), "done")
        self.assertFalse(self._hb_thread_alive())

    # ── Scenario: 心跳写失败不阻断批 ─────────────────────────────────

    def test_heartbeat_oserror_fail_open_batch_identical(self):
        """心跳追加 OSError → 静默放弃本轮，批行为与无心跳形态完全一致。"""
        self._git_init()
        started, release = threading.Event(), threading.Event()
        def raising_append(run_file, entry):
            if entry.get("type") == "heartbeat":
                raise OSError("产物目录不可写")
            return _real_append_line(run_file, entry)

        mgr = DistillManager(max_fix_rounds=0)

        def spawn(cmd, cwd, env=None):
            started.set()
            release.wait(timeout=30)
            return _FakeProc(1)  # 失败批：error 终态照写

        mgr._spawn = spawn
        with mock.patch(
            "core.knowledge.append_run_line", side_effect=raising_append
        ):
            with mock.patch(
                "core.knowledge._DISTILL_HEARTBEAT_SECONDS", self.HB_INTERVAL
            ):
                t = threading.Thread(
                    target=lambda: mgr._run_batch(self.root, [self._archive_name()])
                )
                t.start()
                self.assertTrue(started.wait(timeout=10))
                # 阻塞期间心跳多轮 OSError 全部静默（等待 > 若干间隔无异常外泄）
                time.sleep(self.HB_INTERVAL * 6)
                release.set()
                t.join(timeout=30)
        self.assertFalse(t.is_alive())
        lines = self._lines(self._artifact_path())
        # 心跳行全部写失败 → 产物无 heartbeat 行；started/round/error 形态
        # 与无心跳批完全一致
        self.assertFalse(any(l["type"] == "heartbeat" for l in lines))
        self.assertEqual(
            [l["type"] for l in lines], ["started", "round", "error"]
        )
        self.assertEqual(classify_run(lines), "error")

    # ── 产物创建 fail-open（run_file=None）不启动心跳线程 ─────────────

    def test_open_fail_no_heartbeat_thread(self):
        self._git_init()
        mgr = DistillManager(max_fix_rounds=0)
        mgr._spawn = lambda cmd, cwd, env=None: _FakeProc(1)
        with mock.patch(
            "core.knowledge.append_run_line", side_effect=OSError("disk full")
        ):
            result = mgr._run_batch(self.root, [self._archive_name()])
        self.assertFalse(result["ok"])
        self.assertIn("非零退出", result["error"])
        # 产物创建 fail-open（run_file=None）→ 心跳线程未启动（无残留）；
        # 产物文件仅 touch 空壳、零事件行（started 行写入即失败，无心跳行）
        runs = self.root / ".fenix" / "runs"
        files = list(runs.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_text(encoding="utf-8"), "")
        self.assertFalse(self._hb_thread_alive())

    # ── 批异常路径线程不留存活 ────────────────────────────────────────

    def test_batch_exception_no_lingering_heartbeat_thread(self):
        self._git_init()
        mgr = DistillManager(max_fix_rounds=0)
        mgr._spawn = lambda cmd, cwd, env=None: _FakeProc(0)
        with mock.patch(
            "core.knowledge.validate_knowledge",
            side_effect=RuntimeError("validate boom"),
        ):
            with self.assertRaises(RuntimeError):
                mgr._run_batch(self.root, [self._archive_name()])
        lines = self._lines(self._artifact_path())
        self.assertEqual(lines[-1]["type"], "error")
        self.assertIn("validate boom", lines[-1]["error"])
        self.assertFalse(self._hb_thread_alive())


if __name__ == "__main__":
    unittest.main()
