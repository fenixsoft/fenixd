"""定向重试轮单测（add-codefix-targeted-retry 4.1-4.5）。

覆盖：
- 4.1 首轮全量回归 passed → 零定向轮（现状路径零变化）
- 4.2 首轮失败 k 例 → 定向轮子集回归只执行 k 例、passed → 合回核销
- 4.3 修测试路径：``fix_scope=test`` 标注落产物行（编排透传不丢弃）
- 4.4 耗尽 3 轮 → 现场即弃（档案含 branch/tip_sha/最后一轮明细引用、
  worktree 清理、链继续）
- 4.5 非 pytest 命令或映射失败 → 回退全量重试（fail-closed）

另覆盖配套纯函数：junit → nodeid 映射（1.1/1.2，classname 主导、file 属性
仅存在时校验、歧义 fail-closed）与门面子集命令替换（2.1，取代既有收集
位置参数、MUST NOT 尾部追加）。
"""

import json
import subprocess
import tempfile
import types
import unittest
from pathlib import Path


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix)


def _make_project_root() -> Path:
    td = Path(_mkdtemp("cfix-tr-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _make_git_repo() -> Path:
    """构造带一个初始提交的临时 git 仓（模拟 worktree，与 test_code_fix 同型）。"""
    repo = Path(_mkdtemp("cfix-tr-wt-"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
        cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


def _write_items(project_root, records):
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
    )
    path.write_text(content, encoding="utf-8")


def _item(item_id, status="open", first_seen_at=None, **extra):
    rec = {"item_id": item_id, "status": status, "file": f"core/{item_id}.py",
           "line": 1, "severity": "major", "category": "correctness",
           "title": f"title {item_id}", "description": f"desc {item_id}",
           "suggestion": f"sug {item_id}", "fingerprint": f"fp-{item_id}"}
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    rec.update(extra)
    return rec


def _write_verify_yaml(proot: Path):
    body = (
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
        "regression:\n"
        "  cmd: \"python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml\"\n"
        "  output: \".fenix/regression/junit.xml\"\n"
    )
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


_CFG_ON = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}


class _FakeLogger:
    def info(self, component, msg, *a, **k):
        pass

    def warning(self, component, msg, *a, **k):
        pass

    def error(self, component, msg, *a, **k):
        pass


class _FakeWM:
    """fake worktree_manager：create 建真 git 仓并预置 tests/test_x.py 夹具。"""

    def __init__(self):
        self.create_calls = []
        self.merge_calls = []
        self.cleanup_calls = []

    def create(self, spec_name, agent_type="implementer"):
        self.create_calls.append((spec_name, agent_type))
        repo = _make_git_repo()
        # 模拟被修项目的测试模块（nodeid 映射的存在性判定需要）
        tests = repo / "tests"
        tests.mkdir(exist_ok=True)
        (tests / "test_x.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        (repo / ".fenix" / "regression").mkdir(parents=True, exist_ok=True)
        return repo

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        return types.SimpleNamespace(success=True, error="")

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))


class _FakeRunner:
    """fake AgentRunner：回归状态/失败明细按调用序供给，记录子集传参。"""

    def __init__(self, project_root, regression_statuses=None, failure_sets=None,
                 out_statuses=None):
        self.project_root = Path(project_root)
        self.logger = _FakeLogger()
        self._running_agents = {}
        self.worktree_manager = _FakeWM()
        self.config = {}
        self.fix_calls = []           # (worktree, n_items, failure_summary, run_id)
        self.regression_calls = []    # (project_root, lock_root)
        self.subset_calls = []        # 每次 run_regression 的 subset_nodeids（或 None）
        self.regression_statuses = regression_statuses or ["passed"]
        self.failure_sets = failure_sets or []
        self.out_statuses = out_statuses or []
        self._reg_no = 0
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-fake-{self._run_no}"
        self.fix_calls.append((str(worktree_root), len(items), failure_summary, rid))
        statuses = self.out_statuses[self._run_no - 1] \
            if self._run_no - 1 < len(self.out_statuses) else (
                self.out_statuses[-1] if self.out_statuses else ["fixed"])
        rows = []
        for idx, it in enumerate(items):
            row = {"item_id": it["item_id"],
                   "status": statuses[idx % len(statuses)] if statuses else "fixed",
                   "file": it.get("file", "")}
            extra = (self.out_statuses_extra or {}).get(idx) \
                if getattr(self, "out_statuses_extra", None) else None
            if extra:
                row.update(extra)
            rows.append(row)
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        if any(r["status"] == "fixed" for r in rows):
            (Path(worktree_root) / f"touched-{rid}.txt").write_text(
                "fix", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                cwd=worktree_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "-m", f"fix-{rid}"], cwd=worktree_root, check=True, capture_output=True)
        return types.SimpleNamespace(
            run_id=rid, success=True,
            fixed=sum(1 for r in rows if r["status"] == "fixed"),
            skipped=sum(1 for r in rows if r["status"] == "skipped"),
            error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None, lock_root=None,
                       subset_nodeids=None):
        self._reg_no += 1
        self.regression_calls.append((str(project_root), str(lock_root)))
        self.subset_calls.append(list(subset_nodeids) if subset_nodeids else None)
        status = self.regression_statuses[min(
            self._reg_no - 1, len(self.regression_statuses) - 1)]
        failures = self.failure_sets[min(
            self._reg_no - 1, len(self.failure_sets) - 1)] if self.failure_sets else []
        return types.SimpleNamespace(
            run_id=f"regression-fake-{self._reg_no}",
            status=status, snapshot={"failures": failures}, error="")


def _failure(classname, name, message="boom", **extra):
    f = {"classname": classname, "name": name, "file": "",
         "line": 0, "time": 0.0, "kind": "failure", "message": message}
    f.update(extra)
    return f


class TestMapJunitFailuresToNodeids(unittest.TestCase):
    """junit 失败用例 → nodeid 映射（1.1/1.2，D1：classname 主导、fail-closed）。"""

    def test_module_level_function(self):
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        items, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x", "test_a")], exec_root=root)
        self.assertTrue(ok)
        self.assertEqual(items, [{"nodeid": "tests/test_x.py::test_a", "summary": "boom"}])

    def test_class_chain_appended(self):
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        items, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x.TestFoo", "test_bar")], exec_root=root)
        self.assertTrue(ok)
        self.assertEqual(items[0]["nodeid"], "tests/test_x.py::TestFoo::test_bar")

    def test_missing_file_attr_is_expected_not_failure(self):
        """pytest junitxml 不产 file 属性属预期形态，MUST NOT 因此判映射失败。"""
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        f = _failure("tests.test_x", "test_a")
        f.pop("file")
        items, ok = cf._map_junit_failures_to_nodeids([f], exec_root=root)
        self.assertTrue(ok)
        self.assertEqual(items[0]["nodeid"], "tests/test_x.py::test_a")

    def test_file_attr_mismatch_fails(self):
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        _, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x", "test_a", file="tests/other.py")], exec_root=root)
        self.assertFalse(ok, "file 属性存在且与重构不一致 → 映射失败")

    def test_module_file_missing_fails_closed(self):
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))  # 无 tests/test_x.py
        _, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x", "test_a")], exec_root=root)
        self.assertFalse(ok)

    def test_ambiguous_boundaries_fail_closed(self):
        """tests/test_x.py 与 tests/test_x/TestFoo.py 并存 → 歧义判失败。"""
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests" / "test_x").mkdir(parents=True)
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        (root / "tests" / "test_x" / "TestFoo.py").write_text("x=1", encoding="utf-8")
        _, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x.TestFoo", "test_bar")], exec_root=root)
        self.assertFalse(ok)

    def test_missing_classname_fails(self):
        import core.code_fix as cf

        _, ok = cf._map_junit_failures_to_nodeids([_failure("", "test_a")])
        self.assertFalse(ok)

    def test_non_python_form_fails_with_exec_root(self):
        """Java 形态 classname 在执行根模式下无对应模块文件 → fail-closed。

        （生产路径编排侧恒传 worktree 为 exec_root；无 exec_root 的启发式
        模式对大小写混合段无法判定，由文件存在性兜底。）
        """
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        _, ok = cf._map_junit_failures_to_nodeids(
            [_failure("com.example.SomeSuite", "testA")], exec_root=root)
        self.assertFalse(ok)

    def test_any_failure_unmapped_fails_whole_set(self):
        """子集 MUST 覆盖全部失败用例：任一失败 → 整体判失败（fail-closed）。"""
        import core.code_fix as cf

        root = Path(_mkdtemp("cfix-map-"))
        (root / "tests").mkdir()
        (root / "tests" / "test_x.py").write_text("x=1", encoding="utf-8")
        _, ok = cf._map_junit_failures_to_nodeids(
            [_failure("tests.test_x", "test_a"), _failure("tests.missing", "test_b")],
            exec_root=root)
        self.assertFalse(ok)


class TestApplyPytestSubset(unittest.TestCase):
    """门面子集命令替换（2.1，D2）：取代既有收集位置参数，MUST NOT 尾部追加。"""

    def test_shell_cmd_targets_replaced_flags_kept(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        out = _apply_pytest_subset(
            "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml",
            ["tests/test_x.py::test_a", "tests/test_x.py::TestFoo::test_b"],
        )
        self.assertEqual(
            out,
            "python3 -m pytest tests/test_x.py::test_a "
            "tests/test_x.py::TestFoo::test_b -q --junit-xml=.fenix/regression/junit.xml",
        )

    def test_argv_cmd_replaced(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        out = _apply_pytest_subset(
            ["python3", "-m", "pytest", "tests/", "-q"],
            ["tests/test_x.py::test_a"],
        )
        self.assertEqual(out, ["python3", "-m", "pytest", "tests/test_x.py::test_a", "-q"])

    def test_multiple_targets_collapsed(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        out = _apply_pytest_subset(
            "pytest tests/ tests2/ -q", ["tests/test_x.py::test_a"])
        self.assertEqual(out, "pytest tests/test_x.py::test_a -q",
                         "多收集目标应全被取代（并集语义下多目标=全量退化）")

    def test_value_option_args_not_treated_as_targets(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        out = _apply_pytest_subset(
            "pytest tests/ -k 'foo or bar' -q", ["tests/test_x.py::test_a"])
        self.assertEqual(
            out, "pytest tests/test_x.py::test_a -k 'foo or bar' -q",
            "带值选项（-k 及其值）逐字保留，仅收集目标被取代")

    def test_non_pytest_cmd_returns_none(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        self.assertIsNone(_apply_pytest_subset(
            "npm test -- --junit", ["tests/test_x.py::test_a"]))
        self.assertIsNone(_apply_pytest_subset(
            ["go", "test", "./..."], ["tests/test_x.py::test_a"]))

    def test_no_targets_returns_none(self):
        """无既有收集位置参数 → 无法以「取代」语义注入，fail-closed 回退全量。"""
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        self.assertIsNone(_apply_pytest_subset("pytest -q", ["tests/test_x.py::test_a"]))

    def test_shell_operators_return_none(self):
        from core.agent_runner.maintenance_runs import _apply_pytest_subset

        self.assertIsNone(_apply_pytest_subset(
            "pytest tests/ -q | tee out.log", ["tests/test_x.py::test_a"]))


class TestFacadeSubsetRegression(unittest.TestCase):
    """run_regression 门面 subset_nodeids 透传（2.1）：替换生效或 fail-closed。"""

    def _spec(self, cmd):
        from core.verify_contract import RegressionSpec

        return RegressionSpec(
            cmd=cmd, output=".fenix/regression/junit.xml",
            timeout_seconds=600,
        )

    class _Runner:
        project_root = Path("/tmp")
        logger = None

    def _capture(self, cmd):
        """捕获门面传给 run_and_write_regression 的 spec.cmd。

        门面对 run_and_write_regression 是函数内 import（每次调用从
        core.regression 取当前对象），故 patch core.regression 侧。
        """
        import core.regression as reg_mod
        import core.agent_runner.maintenance_runs as mr
        captured = {}
        orig = reg_mod.run_and_write_regression

        def fake(root, spec, logger=None, lock_root=None):
            captured["cmd"] = spec.cmd
            captured["root"] = root
            captured["lock_root"] = lock_root
            return {"status": "passed", "cmd": str(spec.cmd)}

        reg_mod.run_and_write_regression = fake
        try:
            mr.run_regression(
                self._Runner(), self._spec(cmd), reason="code-fix",
                project_root="/wt", lock_root="/main",
                subset_nodeids=["tests/test_x.py::test_a"])
        finally:
            reg_mod.run_and_write_regression = orig
        return captured

    def test_subset_replaces_targets(self):
        captured = self._capture(
            "python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml")
        self.assertIn("tests/test_x.py::test_a", captured["cmd"])
        self.assertNotIn("tests/ ", captured["cmd"] + " ")  # 目录收集目标已消失
        self.assertIn("-q", captured["cmd"])
        # 执行根与锁根透传语义逐字不变
        self.assertEqual(captured["root"], "/wt")
        self.assertEqual(captured["lock_root"], "/main")

    def test_non_pytest_falls_back_to_full(self):
        captured = self._capture("npm test -- --junit")
        self.assertEqual(captured["cmd"], "npm test -- --junit",
                         "非 pytest 形态忽略子集跑全量（fail-closed）")


class TestTargetedRetryLoop(unittest.TestCase):
    """编排级定向轮循环（4.1-4.5）。"""

    def _orch(self, runner, proot, **cfg_extra):
        from core.code_fix import CodeFixOrchestrator

        cfg = {"admin": {"code_review_fix": dict(_CFG_ON["admin"]["code_review_fix"],
                                                 **cfg_extra)}}
        return CodeFixOrchestrator(runner, proot, config=cfg, logger=None)

    def test_first_pass_zero_targeted_rounds(self):
        """4.1：首轮全量回归 passed → 零定向轮（现状路径零变化）。"""
        from core.code_fix import read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["passed"])
        self._orch(runner, proot).checkpoint()
        self.assertEqual(len(runner.fix_calls), 1, "仅首轮 run")
        self.assertEqual(len(runner.regression_calls), 1, "仅首轮回归")
        self.assertEqual(runner.subset_calls, [None], "MUST NOT 传子集")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1, "合回一次")
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 1)
        self.assertNotIn("定向重试", prog.get("current") or "")

    def test_first_fail_subset_regression_then_merge(self):
        """4.2：首轮失败 k 例 → 定向轮子集回归只执行 k 例、passed → 合回核销。"""
        from core.code_fix import read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        fails = [_failure("tests.test_x", "test_a"),
                 _failure("tests.test_x.TestFoo", "test_bar")]
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed", "passed"],
            failure_sets=[fails],
        )
        self._orch(runner, proot).checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "首轮 + 1 个定向轮")
        self.assertEqual(len(runner.regression_calls), 2)
        # 子集 = 首轮失败集（k=2 例，nodeid 经 classname 主导重构）
        self.assertEqual(
            runner.subset_calls,
            [None, ["tests/test_x.py::test_a", "tests/test_x.py::TestFoo::test_bar"]],
        )
        # 定向轮注入累计明细（nodeid + 摘要）
        injected = runner.fix_calls[1][2]
        self.assertIn("tests/test_x.py::test_a", injected)
        self.assertIn("boom", injected)
        self.assertIn("MUST NOT", injected, "注入文本带只修失败相关的硬指令")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1, "合回一次")
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        self.assertEqual(read_progress(proot)["done"], 1)
        # 明细结构化落盘（1.1）：首轮回归非 passed 时一份、文件名含该轮回归 run_id
        detail = proot / ".fenix" / "code-review" / "fix-reg-failures-regression-fake-1.json"
        self.assertTrue(detail.is_file())
        payload = json.loads(detail.read_text(encoding="utf-8"))
        self.assertEqual(payload["source_run_id"], "regression-fake-1")
        self.assertFalse(payload["fallback_full"])
        self.assertEqual(
            [i["nodeid"] for i in payload["items"]],
            ["tests/test_x.py::test_a", "tests/test_x.py::TestFoo::test_bar"],
        )

    def test_fix_scope_test_marked_on_out_row(self):
        """4.3：修测试路径——产物行 ``fix_scope=test`` 标注经编排读取透传保留。"""
        from core.code_fix import read_fix_out, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed", "passed"],
            failure_sets=[[_failure("tests.test_x", "test_a")]],
        )
        # 定向轮产物行带 fix_scope=test（agent 判定为测试自身缺陷）
        runner.out_statuses_extra = {0: {"fix_scope": "test"}}
        self._orch(runner, proot).checkpoint()
        retry_run_id = runner.fix_calls[1][3]
        rows = read_fix_out(runner.worktree_manager.merge_calls[0], retry_run_id)
        self.assertEqual(rows[0].get("fix_scope"), "test", "标注随产物行透传（审计可用）")
        # 标注不影响核销：fix 条目照常 resolved
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        self.assertEqual(read_progress(proot)["done"], 1)

    def test_exhausted_rounds_discard_with_detail_ref(self):
        """4.4：耗尽 3 轮 → 现场即弃（档案含 branch/tip_sha/最后一轮明细引用）。"""
        from core.code_fix import (load_failed_batches, read_progress,
                                   write_fix_reg_failures)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        fails = [_failure("tests.test_x", "test_a")]
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed", "failed", "failed", "failed", "passed"],
            failure_sets=[fails],
            out_statuses=[["fixed"]],
        )
        # batch_size=1：批 a 耗尽现场即弃后，链继续推进批 b（b 照常核销）
        self._orch(runner, proot, batch_size=1).checkpoint()
        # 缺省 targeted_retry_max=3：批 a = 首轮 + 3 定向轮（4 run/4 回归），
        # 链继续 → 批 b 首轮通过（第 5 次 run/回归）
        self.assertEqual(len(runner.fix_calls), 5)
        self.assertEqual(len(runner.regression_calls), 5)
        self.assertEqual(runner.subset_calls,
                         [None] + [["tests/test_x.py::test_a"]] * 3 + [None])
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1,
                         "仅批 b 合回；批 a 耗尽现场即弃 MUST NOT 合回")
        self.assertEqual(read_items(proot)["a"]["status"], "open", "条目保持 open")
        # 现场即弃：批 a cleanup（success=False）；批 b 成功收尾（success=True）
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 2)
        self.assertFalse(runner.worktree_manager.cleanup_calls[0][1])
        self.assertTrue(runner.worktree_manager.cleanup_calls[1][1])
        self.assertEqual(read_items(proot)["b"]["status"], "resolved")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        rec = failed[0]
        self.assertEqual(rec["reason"], "regression_failed_twice")
        self.assertTrue(rec["branch"])
        self.assertTrue(rec["tip_sha"])
        # 最后一轮明细引用：文件名含最后一轮回归 run_id 且文件已落盘
        self.assertTrue(rec.get("detail_ref"), "档案 MUST 含最后一轮明细引用")
        self.assertIn("fix-reg-failures-regression-fake-4.json", rec["detail_ref"])
        self.assertTrue((proot / rec["detail_ref"]).is_file())
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertIn("下轮自动重试", prog["current"])

    def test_map_failure_falls_back_to_full_regression(self):
        """4.5：映射失败（classname 非 Python 模块形态）→ 回退全量重试。"""
        from core.code_fix import read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed", "passed"],
            failure_sets=[[_failure("com.example.Suite", "testA")]],
        )
        self._orch(runner, proot).checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "首轮 + 定向轮")
        # 映射失败 → subset_nodeids=None（回退全量，fail-closed）
        self.assertEqual(runner.subset_calls, [None, None])
        # 明细落盘置 fallback_full 标记（1.2）
        detail = proot / ".fenix" / "code-review" / "fix-reg-failures-regression-fake-1.json"
        self.assertTrue(detail.is_file())
        payload = json.loads(detail.read_text(encoding="utf-8"))
        self.assertTrue(payload["fallback_full"])
        # 定向轮仍合回核销（全量重试通过 = 回归门通过）
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 1)

    def test_targeted_retry_max_config_bounds_rounds(self):
        """配置生效：targeted_retry_max=2 → 耗尽 2 轮（1 首轮+2 定向轮）。"""
        from core.code_fix import load_failed_batches

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed"],
            failure_sets=[[_failure("tests.test_x", "test_a")]],
        )
        self._orch(runner, proot, targeted_retry_max=2).checkpoint()
        self.assertEqual(len(runner.fix_calls), 3, "1 首轮 + 2 定向轮")
        self.assertEqual(len(runner.regression_calls), 3)
        self.assertEqual(load_failed_batches(proot)[0]["item_ids"], ["a"])


if __name__ == "__main__":
    unittest.main()
