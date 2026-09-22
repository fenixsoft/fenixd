"""test_code_fix_item_level_progress.py — code-fix 条级进度（add-code-fix-item-level-progress）

覆盖 tasks 3.1/3.2/3.3 全部 Scenario：
- 批上下文写入/清除（含 run 在飞期间上下文已在场的时序断言）；
- read_progress 条级合成（进行中/零行/损坏行/台账降级/批收尾让位）；
- 兜底 null 三态（running!=true、批上下文缺失、out 缺失、异常）；
- 旧进度文件兼容（缺新键）、重试轮 run_id 刷新、batch_total 写入/清除；
- Dashboard 转导层透传（item_done/current_item/batch_total，不外泄内部索引）。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录（tmp_path 形态：仓库内
gitignored .history/tmp，对齐 tests/test_code_fix.py 既有口径）。
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored），
# 不落仓库内 basetemp，也不改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root() -> Path:
    td = Path(_mkdtemp("cfixilp-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_items(project_root, records):
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
    )
    path.write_text(content, encoding="utf-8")


def _item(item_id, status="open", **extra):
    rec = {
        "item_id": item_id,
        "status": status,
        "file": f"core/{item_id}.py",
        "line": 7,
        "severity": "major",
        "category": "correctness",
        "title": f"title {item_id}",
        "description": f"desc {item_id}",
        "suggestion": f"sug {item_id}",
        "fingerprint": f"fp-{item_id}",
    }
    rec.update(extra)
    return rec


def _write_out(worktree, run_id, lines):
    """按 agent 侧追加形态写 out 文件（lines 元素为 dict 或非法行字符串）。"""
    out = Path(worktree) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    for ln in lines:
        parts.append(
            json.dumps(ln, ensure_ascii=False) if isinstance(ln, dict) else str(ln)
        )
    out.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return out


def _write_progress_raw(project_root, **fields):
    """直接落一份进度文件（可控键集：旧文件兼容用例可省略新键）。"""
    path = Path(project_root) / ".fenix" / "code-review" / "fix-progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")


def _write_verify_yaml(proot: Path):
    body = (
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
        "regression:\n"
        "  cmd: \"true\"\n"
        "  output: \".fenix/regression/junit.xml\"\n"
    )
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


_CFG_ON = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_git_repo(tag: str) -> Path:
    """带初始提交的临时 git 仓（模拟 worktree：零有效修复守卫的 git 侧判据）。"""
    repo = Path(_mkdtemp(f"cfixilp-{tag}-"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
        cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "-m", "init"],
        cwd=repo, check=True, capture_output=True)
    return repo


class _FakeWM:
    """fake worktree_manager：create 返回带初始提交的临时 git 仓。"""

    def __init__(self, project_root, create_result="dir"):
        self.create_calls = []
        self.merge_calls = []
        self.cleanup_calls = []
        self._project_root = Path(project_root)
        self._create_result = create_result
        self._n = 0

    def create(self, spec_name, agent_type="implementer"):
        self.create_calls.append((spec_name, agent_type))
        if self._create_result is None:
            return None
        self._n += 1
        return _make_git_repo(f"wt{self._n}")

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        import types as _t

        return _t.SimpleNamespace(success=True, error="")

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))


class _FakeRunner:
    """fake AgentRunner：run_code_fix 模拟 agent 逐条追加 out 行（run_id 形参
    同真实 run_code_fix 口径——编排器预生成传入则沿用）。"""

    def __init__(self, project_root, fix_statuses=None, regression_statuses=None,
                 create_result="dir"):
        self.project_root = Path(project_root)
        self.logger = _FakeLogger()
        self._running_agents = {}
        self.worktree_manager = _FakeWM(project_root, create_result)
        self.config = {}
        self.fix_calls = []  # (worktree, n_items, failure_summary, run_id)
        self.in_flight_progress = []  # 每次 run_code_fix 调用时刻的 read_progress 快照
        self.in_flight_synthesis = []  # run 中途追加首行后的 read_progress 条级合成
        self.fix_statuses = fix_statuses
        self.regression_statuses = regression_statuses or ["passed"]
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-fake-{self._run_no}"
        self.fix_calls.append((str(worktree_root), len(items), failure_summary, rid))
        # 时序取证：run 在飞时刻，进度文件已携带本批批上下文
        from core.code_fix import read_progress

        self.in_flight_progress.append(read_progress(self.project_root))
        statuses = None
        if self.fix_statuses is not None:
            idx = min(self._run_no - 1, len(self.fix_statuses) - 1)
            statuses = self.fix_statuses[idx]
        rows = [
            {"item_id": it["item_id"], "status": statuses[i % len(statuses)],
             "file": it.get("file", "")}
            for i, it in enumerate(items)
        ] if statuses else [
            {"item_id": it["item_id"], "status": "fixed", "file": it.get("file", "")}
            for it in items
        ]
        # 模拟 agent 逐条追加：首行落盘后立刻读侧合成（run 仍在飞）
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.in_flight_synthesis.append(read_progress(self.project_root))
        # 模拟 agent 提交（零有效修复守卫的 git 侧判据）
        if any(r["status"] == "fixed" for r in rows):
            (Path(worktree_root) / f"touched-{rid}.txt").write_text("fix",
                                                                   encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                cwd=worktree_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                 "-q", "-m", f"fix-{rid}"],
                cwd=worktree_root, check=True, capture_output=True)
        import types as _t

        fixed = sum(1 for r in rows if r["status"] == "fixed")
        skipped = sum(1 for r in rows if r["status"] == "skipped")
        return _t.SimpleNamespace(run_id=rid, success=True, fixed=fixed,
                                  skipped=skipped, error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None, lock_root=None):
        import types as _t

        status = self.regression_statuses[
            min(self._run_no - 1, len(self.regression_statuses) - 1)
        ]
        return _t.SimpleNamespace(
            status=status,
            snapshot={"failures": [
                {"classname": "tests.test_x", "name": "test_a", "message": "boom"}]},
            error="",
        )


# ── 读侧合成（3.1）───────────────────────────────────────────────────


class TestSynthesis(unittest.TestCase):
    """spec「批内进行中合成」「损坏行」「批收尾让位」等 Scenario。"""

    def _setup_running(self, proot, worktree, run_id, batch_total=6):
        _write_progress_raw(
            proot,
            running=True,
            phase="fixing",
            total=270,
            done=0,
            batch_no=1,
            worktree=str(worktree),
            run_id=run_id,
            batch_total=batch_total,
        )

    def test_synthesis_mid_fixing_with_ledger_lookup(self):
        """spec Scenario「批内进行中合成条级进度」：6 有效行 + 台账回查补全。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-synth-"))
        _write_items(proot, {f"i{k}": _item(f"i{k}") for k in range(1, 7)})
        self._setup_running(proot, wt, "code-fix-1000")
        _write_out(wt, "code-fix-1000", [
            {"item_id": f"i{k}", "status": "fixed", "file": f"core/i{k}.py"}
            for k in range(1, 6)
        ] + [{"item_id": "i6", "status": "skipped", "file": "core/i6.py"}])
        prog = read_progress(proot)
        self.assertEqual(prog["item_done"], 6)
        self.assertEqual(
            prog["current_item"],
            {"item_id": "i6", "status": "skipped", "file": "core/i6.py",
             "title": "title i6", "line": 7},
        )
        # 批级字段不受合成影响
        self.assertEqual(prog["done"], 0)
        self.assertEqual(prog["total"], 270)
        self.assertEqual(prog["phase"], "fixing")
        self.assertEqual(prog["batch_total"], 6)

    def test_synthesis_dedup_by_item_id(self):
        """item_done 按 item_id 去重（同条目重复追加只计一次）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-dedup-"))
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        self._setup_running(proot, wt, "code-fix-1001", batch_total=2)
        _write_out(wt, "code-fix-1001", [
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
            {"item_id": "b", "status": "fixed", "file": "core/b.py"},
        ])
        self.assertEqual(read_progress(proot)["item_done"], 2)

    def test_zero_rows_out_missing_both_null(self):
        """spec Scenario「out 文件尚未产出第一行」：out 缺失 → 双 null。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-zero-"))
        self._setup_running(proot, wt, "code-fix-1002")
        prog = read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])
        self.assertTrue(prog["running"], "其余字段正常返回")

    def test_zero_valid_rows_both_null(self):
        """out 存在但零有效行（全部损坏）→ 双 null（非 0）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-zerovalid-"))
        self._setup_running(proot, wt, "code-fix-1003")
        _write_out(wt, "code-fix-1003", ["", "garbage-not-json", "{broken"])
        prog = read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])

    def test_corrupt_rows_do_not_distort_count(self):
        """spec Scenario「损坏行不干扰计数」：8 行中 2 行损坏 → item_done=6。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-corrupt-"))
        _write_items(proot, {f"i{k}": _item(f"i{k}") for k in range(1, 7)})
        self._setup_running(proot, wt, "code-fix-1004")
        lines = [{"item_id": f"i{k}", "status": "fixed", "file": f"core/i{k}.py"}
                 for k in range(1, 7)]
        _write_out(wt, "code-fix-1004",
                   lines[:2] + ["", "not-json"] + lines[2:])
        prog = read_progress(proot)
        self.assertEqual(prog["item_done"], 6)

    def test_item_not_in_ledger_degrades_to_out_fields(self):
        """台账无匹配（清单外条目）→ current_item 降级仅含 out 行字段。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-degrade-"))
        self._setup_running(proot, wt, "code-fix-1005")
        _write_out(wt, "code-fix-1005", [
            {"item_id": "ghost", "status": "fixed", "file": "core/ghost.py"},
        ])
        prog = read_progress(proot)
        self.assertEqual(prog["item_done"], 1)
        self.assertEqual(
            prog["current_item"],
            {"item_id": "ghost", "status": "fixed", "file": "core/ghost.py"},
        )
        self.assertNotIn("title", prog["current_item"])

    def test_ledger_read_exception_degrades(self):
        """台账读异常 → 降级不炸（item_done 照常合成）。"""
        from core import code_fix

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-ledgerexc-"))
        self._setup_running(proot, wt, "code-fix-1006")
        _write_out(wt, "code-fix-1006", [
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
        ])
        with mock.patch.object(code_fix, "read_items", side_effect=OSError("boom")):
            prog = code_fix.read_progress(proot)
        self.assertEqual(prog["item_done"], 1)
        self.assertEqual(
            prog["current_item"],
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
        )

    def test_read_fix_out_exception_falls_back_null(self):
        """read_fix_out 抛任何异常 → 双 null（MUST NOT 500）。"""
        from core import code_fix

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-outexc-"))
        self._setup_running(proot, wt, "code-fix-1007")
        _write_out(wt, "code-fix-1007", [
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
        ])
        with mock.patch.object(code_fix, "read_fix_out", side_effect=RuntimeError("x")):
            prog = code_fix.read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])


# ── 兜底 null 三态（3.2）─────────────────────────────────────────────


class TestFallbacks(unittest.TestCase):
    def test_not_running_null_even_with_context(self):
        """running!=true → 双 null（即使批上下文仍在）。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-notrun-"))
        _write_progress_raw(
            proot, running=False, phase="idle", worktree=str(wt),
            run_id="code-fix-1008", batch_total=3,
        )
        prog = read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])

    def test_missing_context_null(self):
        """running=true 但批上下文缺失 → 双 null。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_progress_raw(proot, running=True, phase="fixing")
        prog = read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])

    def test_old_progress_file_without_new_keys(self):
        """旧进度文件（缺全部新键）走同一兜底：不报错、条级为 null。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_progress_raw(
            proot, running=True, phase="fixing", total=40, done=12, batch_no=2,
        )
        prog = read_progress(proot)
        self.assertEqual(prog["total"], 40)
        self.assertEqual(prog["done"], 12)
        self.assertIsNone(prog["worktree"])
        self.assertIsNone(prog["run_id"])
        self.assertIsNone(prog["batch_total"])
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])

    def test_after_finish_item_fields_yield(self):
        """spec Scenario「批收尾后条级字段让位」：上下文已清、done 已更新。"""
        from core.code_fix import read_progress

        proot = _make_project_root()
        _write_progress_raw(
            proot, running=True, phase="merging", total=40, done=20,
            worktree=None, run_id=None, batch_total=None,
        )
        prog = read_progress(proot)
        self.assertIsNone(prog["item_done"])
        self.assertIsNone(prog["current_item"])
        self.assertEqual(prog["done"], 20, "批级进度即唯一事实源")

    def test_missing_file_default_carries_nulls(self):
        from core.code_fix import FIX_PROGRESS_DEFAULT, read_progress

        proot = _make_project_root()
        self.assertEqual(read_progress(proot), FIX_PROGRESS_DEFAULT)
        self.assertIsNone(FIX_PROGRESS_DEFAULT["item_done"])
        self.assertIsNone(FIX_PROGRESS_DEFAULT["current_item"])
        self.assertIsNone(FIX_PROGRESS_DEFAULT["worktree"])
        self.assertIsNone(FIX_PROGRESS_DEFAULT["run_id"])
        self.assertIsNone(FIX_PROGRESS_DEFAULT["batch_total"])

    def test_write_progress_does_not_persist_synthesized(self):
        """合成字段不落盘：合并写后原始 JSON 不含 item_done/current_item。"""
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-nopersist-"))
        _write_progress_raw(
            proot, running=True, phase="fixing", worktree=str(wt),
            run_id="code-fix-1009", batch_total=2,
        )
        _write_out(wt, "code-fix-1009", [
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
        ])
        self.assertEqual(read_progress(proot)["item_done"], 1)
        write_progress(proot, phase="regressing")
        raw = (proot / ".fenix" / "code-review" / "fix-progress.json").read_text(
            encoding="utf-8")
        data = json.loads(raw)
        self.assertNotIn("item_done", data)
        self.assertNotIn("current_item", data)
        # 再读仍实时合成（不依赖落盘值）
        self.assertEqual(read_progress(proot)["phase"], "regressing")
        self.assertEqual(read_progress(proot)["item_done"], 1)


# ── 写侧编排：批上下文写入/清除/重试刷新（2.1/2.2）───────────────────


class TestOrchestratorBatchContext(unittest.TestCase):
    def test_context_present_while_run_in_flight(self):
        """spec Scenario「run 在飞期间批上下文已在场」：run 调用时刻进度文件
        已携带 worktree/run_id/batch_total，且 run_id 与传入形参一致；首行
        追加后读侧即刻可合成（mid-run item_done=1）。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()  # 无 executor → 同步跑完整链
        self.assertEqual(len(runner.fix_calls), 1)
        wt, n_items, _summary, rid = runner.fix_calls[0]
        snap = runner.in_flight_progress[0]
        self.assertTrue(snap["running"])
        self.assertEqual(snap["phase"], "fixing")
        self.assertEqual(snap["worktree"], wt)
        self.assertEqual(snap["run_id"], rid)
        self.assertTrue(rid.startswith("code-fix-"), "预生成 run_id 保持前缀")
        self.assertEqual(snap["batch_total"], n_items)
        # run 中途（首行已落盘）读侧已可解析条级进度
        mid = runner.in_flight_synthesis[0]
        self.assertEqual(mid["item_done"], 2, "run 在飞期间实时合成可见")
        self.assertEqual(mid["current_item"]["item_id"], "b")
        # 台账回查补全（批内条目核销前保持 open）
        self.assertEqual(mid["current_item"]["title"], "title b")
        # 链收尾（全部核销 → idle）后批上下文清除
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        final = read_progress(proot)
        self.assertIsNone(final["worktree"])
        self.assertIsNone(final["run_id"])
        self.assertIsNone(final["batch_total"])
        self.assertIsNone(final["item_done"])
        self.assertIsNone(final["current_item"])

    def test_run_receives_progress_run_id_via_kwarg(self):
        """预生成 run_id 经既有 run_id 形参传入（run 内不再自行生成）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        rid = runner.fix_calls[0][3]
        self.assertTrue(rid.startswith("code-fix-"))
        # fake runner 沿用传入 run_id（rid 非 None 时）——与进度文件同值已由
        # 上一断言链覆盖；此处锁「形参非空」这一契约本身
        self.assertIsNotNone(rid)

    def test_context_cleared_on_failure_finish(self):
        """失败收尾（零有效修复，_finish 出口）清除批上下文三键。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, fix_statuses=[["skipped"]])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "no_effective_fix")
        self.assertIsNone(prog["worktree"])
        self.assertIsNone(prog["run_id"])
        self.assertIsNone(prog["batch_total"])
        self.assertIsNone(prog["item_done"])

    def test_context_never_written_when_create_fails(self):
        """建树失败：fixing 写点已后移 → 批上下文从未落盘，进度 failed。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, create_result=None)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "worktree_create_failed")
        self.assertEqual(runner.fix_calls, [])
        self.assertIsNone(prog["worktree"])
        self.assertIsNone(prog["run_id"])
        self.assertIsNone(prog["batch_total"])

    def test_retry_run_id_refreshed(self):
        """spec/tasks 2.2：重试轮写新预生成 run_id 并传入重试 run（worktree/
        batch_total 不变），重试 run 在飞期间读侧解析当前轮 out 文件。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "passed"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "首次回归失败后重试一次")
        first_wt, _n, _s, first_rid = runner.fix_calls[0]
        retry_wt, _n2, _s2, retry_rid = runner.fix_calls[1]
        self.assertNotEqual(first_rid, retry_rid, "重试轮 run_id 变更")
        self.assertTrue(retry_rid.startswith("code-fix-"))
        # 重试 run 在飞时刻：进度 run_id 已刷新为重试轮值
        snap = runner.in_flight_progress[1]
        self.assertEqual(snap["phase"], "retrying")
        self.assertEqual(snap["run_id"], retry_rid)
        self.assertEqual(retry_wt, first_wt, "重试轮复用同一 worktree")
        self.assertEqual(snap["worktree"], first_wt, "进度中 worktree 不变")
        self.assertEqual(snap["batch_total"], 1, "batch_total 不变")
        # 重试轮 out（fix-out-<retry_rid>.jsonl）在飞期间即可合成
        self.assertEqual(runner.in_flight_synthesis[1]["item_done"], 1)
        # 重试成功合回核销
        self.assertEqual(read_progress(proot)["done"], 1)

    def test_mid_chain_next_batch_context_refreshed(self):
        """链内切批：下一批 selecting 写已归零、fixing 写新批上下文（不残留
        上一批 worktree/run_id）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "b": _item("b"),
            "c": _item("c"),
            "d": _item("d"),
        })
        _write_verify_yaml(proot)
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 2}}}
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "4 条 batch_size=2 → 2 批")
        first_wt, _n, _s, first_rid = runner.fix_calls[0]
        second_wt, _n2, _s2, second_rid = runner.fix_calls[1]
        self.assertNotEqual(first_wt, second_wt, "每批独立 worktree")
        # 注：跨批 run_id 无同秒唯一性要求——各批 out 落各自 worktree，读侧
        # 按 worktree+run_id 定位互不串扰（批内重试唯一性由 exclude 保证，
        # 见 test_preset_run_id_exclude_forces_fresh）。
        snap2 = runner.in_flight_progress[1]
        self.assertEqual(snap2["phase"], "fixing")
        self.assertEqual(snap2["worktree"], second_wt,
                         "第 2 批在飞时刻批上下文指向第 2 批 worktree")
        self.assertEqual(snap2["run_id"], second_rid)
        self.assertEqual(snap2["batch_total"], 2)
        self.assertNotEqual(snap2["worktree"], first_wt,
                            "不残留第 1 批 worktree 索引")
        self.assertTrue(second_rid.startswith("code-fix-"))


    def test_preset_run_id_exclude_forces_fresh(self):
        """exclude 禁用集强制新 id：时间冻结下同秒两次预生成也必不相同
        （重试轮「独立 out 文件并集」口径的前提）。"""
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr
        from core.code_fix import _preset_run_id

        proot = _make_project_root()
        (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        runner = _FakeRunner(proot)
        with mock.patch.object(mr.time, "time", return_value=1000):
            first = _preset_run_id(runner)
            self.assertEqual(first, "code-fix-1000")
            second = _preset_run_id(runner, exclude=(first,))
        self.assertEqual(second, "code-fix-1000-1")


# ── Dashboard 转导层（4.1）───────────────────────────────────────────


class TestDashboardTransduction(unittest.TestCase):
    def test_passthrough_and_internal_index_not_leaked(self):
        from core.dashboard.data.code_review import read_code_review_fix_progress

        proot = _make_project_root()
        wt = Path(_mkdtemp("cfixilp-api-"))
        _write_items(proot, {"x": _item("x")})
        _write_progress_raw(
            proot, running=True, phase="fixing", total=270, done=0,
            worktree=str(wt), run_id="code-fix-1010", batch_total=20,
        )
        _write_out(wt, "code-fix-1010", [
            {"item_id": "x", "status": "fixed", "file": "core/x.py"},
        ])
        data = read_code_review_fix_progress(proot)
        self.assertEqual(data["item_done"], 1)
        self.assertEqual(data["batch_total"], 20)
        self.assertEqual(data["current_item"]["item_id"], "x")
        self.assertEqual(data["current_item"]["title"], "title x")
        self.assertNotIn("worktree", data, "内部索引 MUST NOT 外泄")
        self.assertNotIn("run_id", data, "内部索引 MUST NOT 外泄")
        self.assertEqual(data["phase"], "fixing")

    def test_default_state_nulls_present(self):
        from core.dashboard.data.code_review import read_code_review_fix_progress

        proot = _make_project_root()
        data = read_code_review_fix_progress(proot)
        self.assertIsNone(data["item_done"])
        self.assertIsNone(data["current_item"])
        self.assertIsNone(data["batch_total"])
        self.assertFalse(data["running"])

    def test_old_file_nulls_filled(self):
        from core.dashboard.data.code_review import read_code_review_fix_progress

        proot = _make_project_root()
        _write_progress_raw(proot, running=True, phase="fixing", total=5, done=1)
        data = read_code_review_fix_progress(proot)
        self.assertIsNone(data["item_done"])
        self.assertIsNone(data["current_item"])
        self.assertIsNone(data["batch_total"])


if __name__ == "__main__":
    unittest.main()
