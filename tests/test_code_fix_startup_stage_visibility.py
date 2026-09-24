"""test_code_fix_startup_stage_visibility.py — code-fix 启动阶段显示
（add-code-fix-startup-stage-visibility）

覆盖 tasks 3.1 全部 Scenario：
- 激活域四分支（fixing+零行激活 / retrying+零行激活 / out 有行短路 null /
  running 非 true 置 null）+ phase 不在激活域；
- 末行映射五形态（system→会话初始化中、assistant thinking/text→模型分析
  分组中、assistant tool_use→正在执行 <工具名>、文件缺失→等待 agent 进程
  启动、末行非 JSON→null）+ system 遥测子类型（task_started）→处理中；
- birth time 缺失退化 waited_minutes=null、birth 在场时为 int；
- write_progress 剥离断言（合成值不落盘）；
- 全程不抛异常（转录读异常 / stat 异常均 fail-open null，不炸 read_progress）；
- Dashboard 转导层透传（startup_stage 外泄、内部索引不外泄）。

夹具全部落 tmp 目录（仓库内 gitignored .history/tmp，对齐
tests/test_code_fix.py 既有口径），MUST NOT 触真实 `.fenix/`。
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP)))


def _make_project_root() -> Path:
    td = _mkdtemp("cfixss-")
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_progress_raw(project_root, **fields):
    path = Path(project_root) / ".fenix" / "code-review" / "fix-progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")


def _write_transcript(project_root, run_id, lines):
    """按 agent 侧追加形态写转录文件（lines 元素为 dict 或非法行字符串）。"""
    path = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = [
        json.dumps(ln, ensure_ascii=False) if isinstance(ln, dict) else str(ln)
        for ln in lines
    ]
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def _write_out(worktree, run_id, rows):
    out = Path(worktree) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def _running_progress(proot, run_id="code-fix-2000", phase="fixing", worktree=None):
    _write_progress_raw(
        proot,
        running=True,
        phase=phase,
        total=10,
        done=0,
        batch_no=1,
        worktree=str(worktree or proot / "wt"),
        run_id=run_id,
        batch_total=3,
    )


# ── 激活域四分支 ──────────────────────────────────────────────────────


class ActivationDomain(unittest.TestCase):
    def test_fixing_zero_rows_activated(self):
        """spec Scenario「run 转录文件缺失」：fixing+零行+转录缺失 → 等待短语。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot)
        prog = read_progress(proot)
        self.assertEqual(
            prog["startup_stage"],
            {"stage": "等待 agent 进程启动", "waited_minutes": None},
        )

    def test_retrying_zero_rows_activated(self):
        """激活域含 retrying（重试轮编排已刷新 run_id，D5 天然正确）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot, run_id="code-fix-rt9", phase="retrying")
        _write_transcript(proot, "code-fix-rt9", [{"type": "system", "subtype": "init"}])
        stage = read_progress(proot)["startup_stage"]
        self.assertEqual(stage["stage"], "会话初始化中")

    def test_out_rows_short_circuit_null(self):
        """spec Scenario「out 出现有效行」：startup_stage 收敛 null、条级接管。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = proot / "wt"
        _running_progress(proot)
        _write_transcript(proot, "code-fix-2000", [{"type": "system", "subtype": "init"}])
        _write_out(wt, "code-fix-2000", [{"item_id": "a", "status": "fixed"}])
        prog = read_progress(proot)
        self.assertIsNone(prog["startup_stage"])
        self.assertEqual(prog["item_done"], 1, "条级计数优先")

    def test_not_running_null(self):
        """running 非 true → 置 null（即使批上下文与转录全在场）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(proot, "code-fix-2000", [{"type": "system", "subtype": "init"}])
        _write_progress_raw(
            proot, running=False, phase="fixing",
            worktree=str(proot / "wt"), run_id="code-fix-2000",
        )
        self.assertIsNone(read_progress(proot)["startup_stage"])

    def test_phase_outside_domain_null(self):
        """phase 不在 {fixing, retrying}（如 regressing/merging）→ null。"""
        from core.code_fix import read_progress

        for phase in ("selecting", "regressing", "merging", "blocked"):
            with self.subTest(phase=phase):
                proot = _make_project_root()
                _running_progress(proot, phase=phase)
                _write_transcript(
                    proot, "code-fix-2000", [{"type": "system", "subtype": "init"}]
                )
                self.assertIsNone(read_progress(proot)["startup_stage"])

    def test_default_state_carries_null_key(self):
        """缺省态恒带键且为 null（不出现「键缺失」形态，task 1.2）。"""
        from core.code_fix import FIX_PROGRESS_DEFAULT, read_progress

        self.assertIsNone(FIX_PROGRESS_DEFAULT["startup_stage"])
        self.assertIn("startup_stage", read_progress(_make_project_root()))


# ── 末行映射（D2）─────────────────────────────────────────────────────


class LastLineMapping(unittest.TestCase):
    def _stage_of(self, proot, run_id="code-fix-2000"):
        from core.code_fix import read_progress

        return read_progress(proot)["startup_stage"]

    def test_system_init_subtypes_session_init(self):
        """system 初始化子类型（init/hook_started/hook_response）→ 会话初始化中。"""
        for subtype in ("init", "hook_started", "hook_response"):
            with self.subTest(subtype=subtype):
                proot = _make_project_root()
                _running_progress(proot)
                _write_transcript(
                    proot, "code-fix-2000", [{"type": "system", "subtype": subtype}]
                )
                self.assertEqual(self._stage_of(proot)["stage"], "会话初始化中")

    def test_system_telemetry_subtypes_processing(self):
        """system 遥测子类型（task_started 等 mid-run）→ agent 启动处理中。"""
        for subtype in ("task_started", "task_progress", "background_tasks_changed"):
            with self.subTest(subtype=subtype):
                proot = _make_project_root()
                _running_progress(proot)
                _write_transcript(
                    proot, "code-fix-2000", [{"type": "system", "subtype": subtype}]
                )
                self.assertEqual(self._stage_of(proot)["stage"], "agent 启动处理中")

    def test_assistant_thinking_and_text_analyzing(self):
        """assistant thinking / text → 模型分析分组中。"""
        for btype in ("thinking", "text"):
            with self.subTest(btype=btype):
                proot = _make_project_root()
                _running_progress(proot)
                _write_transcript(proot, "code-fix-2000", [
                    {"type": "assistant", "message": {"content": [{"type": btype}]}},
                ])
                self.assertEqual(self._stage_of(proot)["stage"], "模型分析分组中")

    def test_assistant_tool_use_with_name(self):
        """assistant tool_use → 正在执行 <工具名>。"""
        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(proot, "code-fix-2000", [
            {"type": "assistant", "message": {"content": [
                {"type": "thinking"},
                {"type": "tool_use", "name": "Edit"},
            ]}},
        ])
        self.assertEqual(self._stage_of(proot)["stage"], "正在执行 Edit")

    def test_other_event_types_processing(self):
        """user / stderr / 未知形态 → agent 启动处理中。"""
        for last in (
            {"type": "user", "message": {}},
            {"type": "stderr", "line": "noise"},
            {"type": "mysterious"},
        ):
            with self.subTest(type=last.get("type")):
                proot = _make_project_root()
                _running_progress(proot)
                _write_transcript(proot, "code-fix-2000", [last])
                self.assertEqual(self._stage_of(proot)["stage"], "agent 启动处理中")

    def test_last_line_not_json_null(self):
        """spec Scenario「转录文件损坏或不可解析」：末行非 JSON → null
        （MUST NOT 伪造阶段文案）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(proot, "code-fix-2000", [
            {"type": "system", "subtype": "init"},
            "garbage-not-json{",
        ])
        self.assertIsNone(read_progress(proot)["startup_stage"])

    def test_uses_last_line_not_earlier(self):
        """阶段取自末行：早前行不影响判定（末行遥测覆盖早前 init）。"""
        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(proot, "code-fix-2000", [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "text"}]}},
            {"type": "system", "subtype": "task_started"},
        ])
        self.assertEqual(self._stage_of(proot)["stage"], "agent 启动处理中")

    def test_tail_window_reads_large_transcript(self):
        """末行在大文件尾部（超 4KB 窗口、64KB 窗口内）仍可截读：阶段正确。"""
        proot = _make_project_root()
        _running_progress(proot)
        path = proot / ".fenix" / "runs" / "code-fix-2000.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        padding = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"x": "p" * 50_000}}]}})
        path.write_text(padding + "\n" + "\n", encoding="utf-8")
        self.assertEqual(self._stage_of(proot)["stage"], "正在执行 Write")

    def test_oversized_last_line_fails_open_null(self):
        """末行超截读窗口（截断片段不可解析）→ fail-open null，不炸。"""
        proot = _make_project_root()
        _running_progress(proot)
        path = proot / ".fenix" / "runs" / "code-fix-2000.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        padding = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write", "input": {"x": "p" * 200_000}}]}})
        path.write_text(padding + "\n" + "\n", encoding="utf-8")
        self.assertIsNone(self._stage_of(proot))


# ── waited_minutes（birth time 口径）──────────────────────────────────


class WaitedMinutes(unittest.TestCase):
    @staticmethod
    def _fake_stat(birth):
        """按路径分派的 os.stat 替身：仅转录文件返回受控 stat，其余走真。"""
        real_stat = __import__("os").stat

        def wrapper(p, *a, **k):
            if "code-fix-2000.jsonl" in str(p):
                if isinstance(birth, Exception):
                    raise birth
                return SimpleNamespace(st_birthtime=birth, st_size=10)
            return real_stat(p, *a, **k)

        return wrapper

    def _activated(self, proot):
        _running_progress(proot)
        _write_transcript(
            proot, "code-fix-2000", [{"type": "system", "subtype": "init"}]
        )

    def test_birth_present_int_minutes(self):
        """birth 在场 → waited_minutes 为 int（125 秒前 → 2 分钟）。"""
        import os as _os

        from core.code_fix import read_progress

        proot = _make_project_root()
        self._activated(proot)
        with mock.patch.object(
            _os, "stat", self._fake_stat(time.time() - 125)
        ):
            stage = read_progress(proot)["startup_stage"]
        self.assertEqual(stage["waited_minutes"], 2)

    def test_birth_missing_none(self):
        """stat 无 st_birthtime（Linux ext4 常态）→ null，阶段短语保留。"""
        import os as _os

        from core.code_fix import read_progress

        proot = _make_project_root()
        self._activated(proot)
        with mock.patch.object(_os, "stat", self._fake_stat(None)):
            stage = read_progress(proot)["startup_stage"]
        self.assertIsNone(stage["waited_minutes"])
        self.assertEqual(stage["stage"], "会话初始化中")

    def test_stat_oserror_fail_open_null(self):
        """D3：转录 stat OSError → 整体置 null（MUST NOT 抛异常）。"""
        import os as _os

        from core.code_fix import read_progress

        proot = _make_project_root()
        self._activated(proot)
        with mock.patch.object(
            _os, "stat", self._fake_stat(OSError("stat failed"))
        ):
            self.assertIsNone(read_progress(proot)["startup_stage"])

    def test_missing_file_waited_null(self):
        """转录文件缺失 → 等待短语 + waited null（spawn→首事件窗口）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot)
        stage = read_progress(proot)["startup_stage"]
        self.assertEqual(stage["stage"], "等待 agent 进程启动")
        self.assertIsNone(stage["waited_minutes"])


# ── 容错与落盘纪律 ────────────────────────────────────────────────────


class FaultToleranceAndPersistence(unittest.TestCase):
    def test_transcript_read_exception_null_no_raise(self):
        """末行读取/解析抛任何异常 → null 且不炸 read_progress（D3 硬要求）。"""
        from core import code_fix
        from core.code_fix import read_progress

        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(
            proot, "code-fix-2000", [{"type": "system", "subtype": "init"}]
        )
        with mock.patch.object(
            code_fix, "_last_transcript_line", side_effect=RuntimeError("boom")
        ):
            prog = read_progress(proot)
        self.assertIsNone(prog["startup_stage"])
        self.assertEqual(prog["phase"], "fixing", "主进度不受影响")

    def test_write_progress_strips_synthesized(self):
        """write_progress 剥离 startup_stage：合成快照不落盘（对齐 item_done）。"""
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(
            proot, "code-fix-2000", [{"type": "system", "subtype": "init"}]
        )
        self.assertIsNotNone(read_progress(proot)["startup_stage"])
        write_progress(proot, current="第 1 批修复中")
        raw = json.loads(
            (proot / ".fenix" / "code-review" / "fix-progress.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("startup_stage", raw)
        self.assertNotIn("item_done", raw)
        # 再读仍实时合成（不依赖落盘值）
        self.assertIsNotNone(read_progress(proot)["startup_stage"])

    def test_dashboard_transduction_passthrough(self):
        """数据层零改动复核（task 1.2）：startup_stage 自然透出、内部索引不外泄。"""
        from core.dashboard.data.code_review import read_code_review_fix_progress

        proot = _make_project_root()
        _running_progress(proot)
        _write_transcript(
            proot, "code-fix-2000", [{"type": "system", "subtype": "hook_started"}]
        )
        data = read_code_review_fix_progress(proot)
        self.assertEqual(data["startup_stage"]["stage"], "会话初始化中")
        self.assertNotIn("worktree", data)
        self.assertNotIn("run_id", data)

    def test_progress_file_without_new_key(self):
        """旧进度文件（无 startup_stage 键）→ 读侧补键不报错；激活条件成立
        时照常合成（键缺失形态 MUST NOT 出现），离开激活域时为 null。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_progress_raw(
            proot, running=True, phase="regressing", total=5, done=1,
            worktree=str(proot / "wt"), run_id="code-fix-old",
        )
        self.assertIsNone(read_progress(proot)["startup_stage"])
        _write_progress_raw(
            proot, running=True, phase="fixing", total=5, done=1,
            worktree=str(proot / "wt"), run_id="code-fix-old",
        )
        prog = read_progress(proot)
        self.assertIn("startup_stage", prog)
        self.assertEqual(
            prog["startup_stage"],
            {"stage": "等待 agent 进程启动", "waited_minutes": None},
        )


if __name__ == "__main__":
    unittest.main()
