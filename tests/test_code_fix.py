"""test_code_fix.py — 自动修复车道（add-code-review-auto-fix）核心逻辑测试

覆盖：
- 1.3: get_code_review_fix_config 缺省/非法值回退矩阵；code-fix 在
  KNOWN_AGENT_TYPES 中。
- 4.2: mark_resolved 命中/不误伤/空列表/并发写。
- 5.9: 编排核心（守卫矩阵、select_batch、进度读写、activation_id、接线）。
- 6.5: run_code_fix 产物硬门、out 解析、run_id 撞名退避、模型链、门面注册。
- 7.4: 激活接线。
- 8.4: 进度 API。
- 10.4: 配置读写。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录。
"""

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# /tmp 可能被外部清扫进程周期性清空（2026-09-19 实测）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root() -> Path:
    """建一个带 .fenix/code-review 目录的临时项目根。"""
    td = Path(_mkdtemp("cfix-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_items(project_root, records):
    """按 item_id 排序写 items.jsonl（对齐 core.code_review 的落盘形态）。"""
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


# ── 1.3 配置回退矩阵 ───────────────────────────────────────────────


class TestCodeReviewFixConfig(unittest.TestCase):
    def test_defaults_when_section_missing(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_fix_config({})
        self.assertEqual(cfg, {"enabled": False, "batch_size": 20})
        cfg2 = ConfigLoader.get_code_review_fix_config({"admin": {}})
        self.assertEqual(cfg2, {"enabled": False, "batch_size": 20})
        # 段非 dict 视为缺省
        cfg3 = ConfigLoader.get_code_review_fix_config({"admin": {"code_review_fix": "x"}})
        self.assertEqual(cfg3, {"enabled": False, "batch_size": 20})

    def test_invalid_batch_size_falls_back(self):
        from core.config import ConfigLoader

        for bad in (0, -3, True, "20", 20.5, None):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"enabled": True, "batch_size": bad}}}
            )
            self.assertEqual(cfg["batch_size"], 20, f"batch_size={bad!r} 应回退 20")
            self.assertTrue(cfg["enabled"])

    def test_invalid_enabled_falls_back(self):
        from core.config import ConfigLoader

        for bad in ("true", 1, 0, [], {}):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"enabled": bad}}}
            )
            self.assertFalse(cfg["enabled"], f"enabled={bad!r} 应回退 False")

    def test_valid_values_kept(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_fix_config(
            {"admin": {"code_review_fix": {"enabled": True, "batch_size": 30}}}
        )
        self.assertEqual(cfg, {"enabled": True, "batch_size": 30})

    def test_code_fix_in_known_agent_types(self):
        from core.config import ConfigLoader

        self.assertIn("code-fix", ConfigLoader.KNOWN_AGENT_TYPES)
        # 与 code-review 同处登记（紧邻既有 code-review）
        self.assertIn("code-review", ConfigLoader.KNOWN_AGENT_TYPES)


# ── 2.6/2.7 code-fix agent 注册与提示词 ────────────────────────────


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_runner(project_root):
    """构造最小 AgentRunner（__new__ 绕过 __init__，对齐 test_agent_runner.make_runner）。"""
    from core.agent_runner import runner as runner_mod

    r = runner_mod.AgentRunner.__new__(runner_mod.AgentRunner)
    r.config = {}
    r.worktree_manager = None
    r.state_machine = None
    r.project_root = Path(project_root)
    r.logger = _FakeLogger()
    r._running_agents = {}
    return r


class TestCodeFixAgentRegistration(unittest.TestCase):
    def test_infer_run_agent_type(self):
        from core.agent_runner.run_files import infer_run_agent_type

        self.assertEqual(infer_run_agent_type("code-fix-123"), ("code-fix", "123"))
        # code-review- 不错配 code-fix（前缀无子串冲突）
        self.assertEqual(infer_run_agent_type("code-review-100"), ("code-review", "100"))
        self.assertEqual(infer_run_agent_type("code-fix-100"), ("code-fix", "100"))

    def test_agent_prompt_files_contains_mapping(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES

        self.assertIn("code-fix", AGENT_PROMPT_FILES)
        self.assertEqual(AGENT_PROMPT_FILES["code-fix"], "code-fix.md")
        # 框架根 agents/code-fix.md 存在
        from pathlib import Path
        agents_dir = Path(__file__).resolve().parent.parent / "agents"
        self.assertTrue((agents_dir / "code-fix.md").is_file())

    def test_build_prompt_fills_items_outpath(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES
        from core.agent_runner.run_files import infer_run_agent_type

        proot = _make_project_root()
        runner = _make_runner(proot)
        detail = {
            "items": [
                {
                    "item_id": "item-1",
                    "file": "core/a.py",
                    "line": 3,
                    "severity": "major",
                    "category": "correctness",
                    "title": "t",
                    "description": "d",
                    "suggestion": "s",
                }
            ],
            "out_path": str(proot / ".fenix" / "code-review" / "fix-out-abc.jsonl"),
            "worktree": str(proot),
        }
        prompt = runner._build_prompt("runner", "code-fix", detail)
        self.assertIn("item-1", prompt)
        self.assertIn("core/a.py", prompt)
        self.assertIn(str(proot / ".fenix" / "code-review" / "fix-out-abc.jsonl"), prompt)

    def test_build_prompt_no_detail_no_crash(self):
        """_build_prompt("code-fix") 无 detail 时不得抛异常（test_agent_prompt_files 参数化）。"""
        proot = _make_project_root()
        runner = _make_runner(proot)
        prompt = runner._build_prompt("runner", "code-fix")
        # 占位符被缺省回退填充，无残留大括号占位符
        for token in ("{items}", "{out_path}", "{worktree}"):
            self.assertNotIn(token, prompt)
        self.assertIn(str(proot / ".fenix" / "code-review"), prompt)

    def test_template_first_line_fillable(self):
        """模板首行 MUST 可被 _fill_placeholders 处理（test_agent_prompt_files 断言）。"""
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES

        proot = _make_project_root()
        runner = _make_runner(proot)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["code-fix"]).read_text(
            encoding="utf-8")
        first = template.splitlines()[0]
        filled = runner._prompt_builder._fill_placeholders(first, "code-fix", "demo", None)
        self.assertTrue(filled.startswith(first.replace("{spec_name}", "demo")))


if __name__ == "__main__":
    unittest.main()


# ── 3.3 回归锁根参数 ────────────────────────────────────────────────


class TestRegressionLockRoot(unittest.TestCase):
    def _spec(self):
        from core.verify_contract import RegressionSpec

        return RegressionSpec(cmd="true", output=".fenix/regression/junit.xml")

    def test_suite_lock_default_root(self):
        from core.regression import _LOCK_FILE_REL, _SuiteLock

        proot = _make_project_root()
        lock = _SuiteLock(proot)
        self.assertEqual(
            lock._lock_path, Path(proot) / _LOCK_FILE_REL
        )

    def test_run_regression_lock_root_anchors_lock_file(self):
        """lock_root=<main> 时锁文件在 main/.fenix/full-suite.lock，cwd 仍为 project_root。"""
        import core.regression as reg

        wt = _make_project_root()   # 执行根（worktree 模拟）
        main = _make_project_root()  # 锁根（主树模拟）
        result = reg.run_regression(wt, self._spec(), lock_root=main)
        # cmd=true 不产出 JUnit XML → parse_error/failed 均可，但锁一定在 main
        self.assertIn(result.get("status"), ("parse_error", "failed", "passed", "timeout"))
        self.assertTrue((main / ".fenix" / "full-suite.lock").exists(),
                        "锁文件 MUST 落在 lock_root")
        self.assertFalse((wt / ".fenix" / "full-suite.lock").exists(),
                         "锁文件 MUST NOT 落在执行根（worktree）")

    def test_run_regression_default_lock_root_unchanged(self):
        """缺省 lock_root=None 时锁路径与改动前一致（project_root 下）。"""
        import core.regression as reg

        proot = _make_project_root()
        reg.run_regression(proot, self._spec())
        self.assertTrue((proot / ".fenix" / "full-suite.lock").exists())

    def test_facade_passes_project_root_and_lock_root(self):
        """门面两参数透传到 run_and_write_regression（monkeypatch 捕获）。"""
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        wt = _make_project_root()
        runner = _make_runner(proot)
        captured = {}

        def fake_raw(exec_root, spec, logger=None, lock_root=None):
            captured["exec_root"] = exec_root
            captured["lock_root"] = lock_root
            return {"status": "passed", "total": 1, "duration_seconds": 0}

        with mock.patch("core.regression.run_and_write_regression", fake_raw):
            mr.run_regression(runner, self._spec(), project_root=wt, lock_root=proot)
        self.assertEqual(captured["exec_root"], wt)
        self.assertEqual(captured["lock_root"], proot)

    def test_facade_defaults_fall_back(self):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        runner = _make_runner(proot)
        captured = {}

        def fake_raw(exec_root, spec, logger=None, lock_root=None):
            captured["exec_root"] = exec_root
            captured["lock_root"] = lock_root
            return {"status": "passed"}

        with mock.patch("core.regression.run_and_write_regression", fake_raw):
            mr.run_regression(runner, self._spec())
        self.assertEqual(captured["exec_root"], proot)  # 回落 runner.project_root
        self.assertIsNone(captured["lock_root"])  # 回落 None（→ run_regression 内回落 project_root）


# ── 4.2 mark_resolved 台账核销 ───────────────────────────────────────


class TestMarkResolved(unittest.TestCase):
    def test_marks_multiple_and_skips_missing(self):
        from core.code_review import mark_resolved, read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "b": _item("b"),
            "c": _item("c"),
        })
        hit = mark_resolved(proot, ["a", "c", "missing-id"])
        self.assertEqual(hit, 2)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["c"]["status"], "resolved")
        self.assertEqual(items["b"]["status"], "open")  # 未命中不误伤

    def test_empty_list_safe(self):
        from core.code_review import mark_resolved

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self.assertEqual(mark_resolved(proot, []), 0)
        self.assertEqual(mark_resolved(proot, ["a", "a"]), 1)  # 幂等：重复 id 只命中一次

    def test_concurrent_writes_do_not_lose_records(self):
        """并发 mark_resolved 不丢条目（复用台账并发测试形态：flock + 原子替换）。"""
        from core.code_review import mark_resolved, read_items

        proot = _make_project_root()
        records = {f"i{n}": _item(f"i{n}") for n in range(20)}
        _write_items(proot, records)
        groups = [[f"i{n}" for n in range(k, 20, 4)] for k in range(4)]
        threads = [
            threading.Thread(target=mark_resolved, args=(proot, g)) for g in groups
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        items = read_items(proot)
        self.assertEqual(len(items), 20, "并发写不得丢条目")
        self.assertTrue(all(r["status"] == "resolved" for r in items.values()))


# ── 5.1/5.2/5.9 编排核心：进度、选批、守卫矩阵 ────────────────────────


class TestProgressIO(unittest.TestCase):
    def test_read_progress_missing_returns_default(self):
        from core.code_fix import FIX_PROGRESS_DEFAULT, read_progress

        proot = _make_project_root()
        self.assertEqual(read_progress(proot), FIX_PROGRESS_DEFAULT)

    def test_read_progress_corrupt_returns_default(self):
        from core.code_fix import read_progress

        proot = _make_project_root()
        (proot / ".fenix" / "code-review" / "fix-progress.json").write_text(
            "{not json", encoding="utf-8")
        self.assertEqual(read_progress(proot)["phase"], "idle")

    def test_write_progress_atomic_merge(self):
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        write_progress(proot, running=True, phase="fixing", total=10, done=3,
                       activation_id="act-1")
        write_progress(proot, done=5)  # 未传字段保留
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 5)
        self.assertEqual(prog["total"], 10)
        self.assertEqual(prog["phase"], "fixing")
        self.assertEqual(prog["activation_id"], "act-1")


class TestSelectBatch(unittest.TestCase):
    def test_orders_by_first_seen_at_and_caps_batch_size(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "old": _item("old", first_seen_at="2026-01-01T00:00:00Z"),
            "mid": _item("mid", first_seen_at="2026-02-01T00:00:00Z"),
            "new": _item("new", first_seen_at="2026-03-01T00:00:00Z"),
            "resolved": _item("resolved", status="resolved"),
            "ignored": _item("ignored", status="ignored"),
        })
        batch = select_batch(proot, 2)
        self.assertEqual([r["item_id"] for r in batch], ["old", "mid"])

    def test_missing_first_seen_falls_back_to_item_id(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {"b": _item("b"), "a": _item("a")})
        batch = select_batch(proot, 10)
        self.assertEqual([r["item_id"] for r in batch], ["a", "b"])

    def test_excludes_failed_batch_items(self):
        from core.code_fix import record_failed_batch, select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        record_failed_batch(proot, ["a"], "/tmp/wt-kept")
        batch = select_batch(proot, 10)
        self.assertEqual([r["item_id"] for r in batch], ["b"])

    def test_release_failed_batch_restores_selection(self):
        from core.code_fix import record_failed_batch, release_failed_batch, select_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        record_failed_batch(proot, ["a"], "/tmp/wt-kept")
        self.assertEqual(select_batch(proot, 10), [])
        released = release_failed_batch(proot, ["a"])
        self.assertEqual(released, 1)
        self.assertEqual([r["item_id"] for r in select_batch(proot, 10)], ["a"])

    def test_corrupt_failed_file_treated_as_empty(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        (proot / ".fenix" / "code-review" / "fix-failed.json").write_text(
            "garbage", encoding="utf-8")
        self.assertEqual(len(select_batch(proot, 10)), 1)


def _make_git_repo() -> Path:
    """构造带一个初始提交的临时 git 仓（模拟 worktree）。"""
    repo = Path(_mkdtemp("cfix-wt-"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
        cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo, check=True, capture_output=True)
    return repo


class _FakeWM:
    """fake worktree_manager：create/merge_back/cleanup 记录调用。"""

    def __init__(self, create_result="git"):
        self.create_calls = []
        self.merge_calls = []
        self.cleanup_calls = []
        self._create_result = create_result  # "git" | None

    def create(self, spec_name, agent_type="implementer"):
        self.create_calls.append((spec_name, agent_type))
        if self._create_result is None:
            return None
        return _make_git_repo()

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        import types as _t
        return _t.SimpleNamespace(success=True, error="")

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))


class _FakeRunner:
    """fake AgentRunner：记录 run_code_fix / run_regression 调用。"""

    def __init__(self, project_root, fix_statuses=None, regression_statuses=None,
                 create_result="git"):
        self.project_root = Path(project_root)
        self.logger = _FakeLogger()
        self._running_agents = {}
        self.worktree_manager = _FakeWM(create_result)
        self.config = {}
        self.fix_calls = []          # (worktree, n_items, failure_summary)
        self.regression_calls = []   # (project_root, lock_root)
        self.fix_statuses = fix_statuses  # 每 run 的行状态列表列表，如 [["fixed"],["fixed"]]
        self.regression_statuses = regression_statuses or ["passed"]
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-fake-{self._run_no}"
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        statuses = None
        if self.fix_statuses is not None:
            statuses = self.fix_statuses[(self._run_no - 1) % len(self.fix_statuses)] \
                if self._run_no - 1 < len(self.fix_statuses) else self.fix_statuses[-1]
        rows = []
        for idx, it in enumerate(items):
            status = (statuses[idx % len(statuses)] if statuses else "fixed")
            rows.append({"item_id": it["item_id"], "status": status,
                         "file": it.get("file", "")})
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        # 模拟 agent 提交（零有效修复守卫的 git 侧判据）
        if any(r["status"] == "fixed" for r in rows):
            (Path(worktree_root) / f"touched-{rid}.txt").write_text("fix", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                cwd=worktree_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "-m", f"fix-{rid}"],
                cwd=worktree_root, check=True, capture_output=True)
        import types as _t
        fixed = sum(1 for r in rows if r["status"] == "fixed")
        skipped = sum(1 for r in rows if r["status"] == "skipped")
        return _t.SimpleNamespace(run_id=rid, success=True, fixed=fixed,
                                  skipped=skipped, error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None, lock_root=None):
        self.regression_calls.append((str(project_root), str(lock_root)))
        status = self.regression_statuses[min(
            len(self.regression_calls) - 1, len(self.regression_statuses) - 1)]
        import types as _t
        return _t.SimpleNamespace(status=status, snapshot={"failures": [
            {"classname": "tests.test_x", "name": "test_a", "message": "boom"}]},
            error="")


def _write_verify_yaml(proot: Path, with_regression=True):
    body = (
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
    )
    if with_regression:
        body += (
            "regression:\n"
            "  cmd: \"true\"\n"
            "  output: \".fenix/regression/junit.xml\"\n"
        )
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


_CFG_ON = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}


class _RealCfgRunner(_FakeRunner):
    """对齐真实 AgentRunner 的配置读取：``config`` 为**根**形态，``_get_config``
    按嵌套键路径返回**子段**（真实 runner 即 `ConfigLoader.get(self.config, key)`）。
    """

    def _get_config(self, key, default=None):
        from core.config import ConfigLoader

        return ConfigLoader.get(self.config, key, default)


class TestOrchestratorDaemonConfigPath(unittest.TestCase):
    """daemon 装配形态（config=None）MUST 读到根 config 下的段（生产回归锁）。

    回归锁：`_get_config` 回落原先直接把 `runner._get_config("admin.code_review_fix")`
    的**子段**交给 `ConfigLoader.get_code_review_fix_config`，而该读取器的契约是
    **根 config**（内部 `config.get("admin")`）→ 子段里无 `admin` 键 → 判定段缺失
    → 恒返回缺省 `enabled=False`。fenixd.py 是唯一走 `config=None` 的调用点，故
    设置页开关打开后整条自动修复车道静默失效（两路激活都经 checkpoint）。
    既有测试均显式传根形态 config，覆盖不到这条 daemon 路径。
    """

    def test_daemon_enabled_reads_root_config(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 50}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        cfg = orch._get_config()
        self.assertTrue(cfg["enabled"],
                        "config=None（daemon）MUST 读根 config 下的段，"
                        "不得因子段/根形态错配恒判 disabled")
        self.assertEqual(cfg["batch_size"], 50)

    def test_daemon_disabled_reads_root_config(self):
        """反向锁：根 config 段关闭时 MUST 仍判 disabled（不得恒真/硬编码）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": False}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        self.assertFalse(orch._get_config()["enabled"])

    def test_daemon_checkpoint_no_longer_disabled(self):
        """端到端：daemon 形态 + 根 config 开启 → checkpoint MUST NOT 返回 disabled。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        self.assertNotEqual(orch.checkpoint().get("reason"), "disabled")


class TestOrchestratorGuards(unittest.TestCase):
    def test_disabled_zero_action(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        self.assertEqual(runner.fix_calls, [])
        self.assertFalse((proot / ".fenix" / "code-review" / "fix-progress.json").exists(),
                         "开关关闭 MUST NOT 写进度")

    def test_already_running_in_flight_agent(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner._running_agents = {"code-fix-123": object()}
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "already_running"})

    def test_no_open_items(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "no_open_items"})
        self.assertEqual(runner.fix_calls, [])

    def test_regression_contract_missing_blocks_and_signals(self):
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.admin_store import AdminStore

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        # 不写 verify.yaml → 契约整体缺失
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "regression_contract_missing"})
        self.assertEqual(runner.fix_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "regression_contract_missing")
        store = AdminStore(proot, logger=None)
        types = [r.get("signal_type") for r in store.read_all()]
        self.assertIn("verify_contract_missing", types)

    def test_regression_section_missing_blocks_and_signals(self):
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.admin_store import AdminStore

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot, with_regression=False)  # 契约有效仅缺段
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "regression_section_missing"})
        self.assertEqual(runner.fix_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "regression_section_missing")
        store = AdminStore(proot, logger=None)
        types = [r.get("signal_type") for r in store.read_all()]
        self.assertIn("verify_regression_missing", types)
        self.assertNotIn("verify_contract_missing", types,
                         "MUST NOT 写 verify_contract_missing（会重写有效契约）")

    def test_normal_dispatch_full_chain(self):
        """正常链：分批 → 回归 → 合回 → 核销 → cleanup → 自驱动下一批 → 收尾。

        batch_size=2、3 条 open → 2 批；total 全程 3（不倒退）；done=3。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items
        from core.config import ConfigLoader

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 2}}}
        self.assertTrue(ConfigLoader.get_code_review_fix_config(cfg)["enabled"])
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        res = orch.checkpoint()  # 无 executor → 同步跑完整条链
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 2, "3 条 batch_size=2 → 2 批")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 2)
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 2)
        self.assertTrue(all(s for _, s in runner.worktree_manager.cleanup_calls),
                        "成功批 cleanup(success=True)")
        items = read_items(proot)
        self.assertTrue(all(r["status"] == "resolved" for r in items.values()),
                        f"全部核销: {[(k, v['status']) for k, v in items.items()]}")
        prog = read_progress(proot)
        self.assertEqual(prog["total"], 3)
        self.assertEqual(prog["done"], 3)
        self.assertEqual(prog["batch_no"], 2)
        self.assertFalse(prog["running"])
        # 回归调用：执行根=worktree、锁根=主树
        for exec_root, lock_root in runner.regression_calls:
            self.assertNotEqual(exec_root, str(proot), "执行根 MUST 为 worktree")
            self.assertEqual(lock_root, str(proot), "锁根 MUST 为主树")

    def test_activation_id_total_preserved_across_chain(self):
        """同链再投递不重置 total（D8：total 为激活链起点的 open 快照）。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {
            k: _item(k, first_seen_at=f"2026-0{i}-01T00:00:00Z")
            for i, k in enumerate(["a", "b", "c"], start=1)
        })
        _write_verify_yaml(proot)
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        orch.checkpoint()
        prog = read_progress(proot)
        self.assertEqual(prog["total"], 3, "链内 total 不随 open 缩小而重置")
        self.assertEqual(prog["done"], 3)
        self.assertEqual(prog["activation_id"], "see-above") if False else None
        self.assertTrue(prog["activation_id"], "链身份已持久化")

    def test_worktree_create_failed_no_dispatch(self):
        """create() 返回 None → 不派 run、不合回、进度 failed、条目保持 open。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, create_result=None)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(runner.fix_calls, [])
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "worktree_create_failed")
        self.assertEqual(read_items(proot)["a"]["status"], "open")

    def test_zero_effective_fix_rejects_merge(self):
        """产物行全 skipped → 不合回、不核销、reason=no_effective_fix。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)  # 有效 regression 段（零有效修复守卫在回归通过后判定）
        runner = _FakeRunner(proot, fix_statuses=[["skipped", "skipped"]])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [], "零有效修复 MUST NOT 合回")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "open")
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "no_effective_fix")

    def test_regression_failed_twice_discards_and_keeps_worktree(self):
        """两次回归均失败 → 不合回、不核销、保留 worktree（不 cleanup）、失败集合跳过。"""
        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress, select_batch)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "failed"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        self.assertEqual(runner.worktree_manager.cleanup_calls, [],
                         "失败批 MUST NOT cleanup（保留现场）")
        self.assertEqual(len(runner.fix_calls), 2, "首次失败后重试一次")
        self.assertTrue(runner.fix_calls[1][2], "重试 prompt 注入失败用例摘要")
        items = read_items(proot)
        self.assertTrue(all(r["status"] == "open" for r in items.values()))
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertIn("regression_failed_twice", prog["reason"])
        # 失败批落盘 + 下轮跳过
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a", "b"})
        self.assertEqual(select_batch(proot, 10), [], "失败集合条目被跳过")
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("release_failed_batch", todo)

    def test_regression_retry_then_pass_merges(self):
        """首次回归失败、重试后通过 → 正常合回核销。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "passed"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 1)

    def test_retry_fixed_items_are_resolved_by_union(self):
        """重试轮各自 fixed 的条目按两轮产物**并集**核销（只读首次 run 会漏）。

        回归锁：ocr 审查发现——重试轮写独立的 ``fix-out-<retry_run_id>.jsonl``，
        仅读首次 run 的产物会把「重试才修复」的条目合回主树却仍留 open，
        下轮被反复重派。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        # 首次：a fixed / b skipped；重试：a skipped / b fixed
        runner = _FakeRunner(
            proot,
            fix_statuses=[["fixed", "skipped"], ["skipped", "fixed"]],
            regression_statuses=["failed", "passed"],
        )
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "首次回归失败后重试一次")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["b"]["status"], "resolved",
                         "重试轮才修复的条目也必须核销（并集口径）")
        self.assertEqual(read_progress(proot)["done"], 2)

    def test_retry_run_failed_cleans_up_without_failed_set(self):
        """重试 run 失败（第二次回归未跑）→ 不入失败保留集合，cleanup 释放锁。

        回归锁：ocr 审查发现——原实现把「重试 run 失败」记进
        ``fix-failed.json``（该文件语义是「两次回归均失败」）且不 cleanup，
        令 spec 锁永久占用（后续 create() 恒 None，车道首批后即死），
        同时把很可能是一次性失败的条目永久排除出选批。
        """
        from types import SimpleNamespace

        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "failed"])
        real_fix = runner.run_code_fix
        calls = {"n": 0}

        def flaky_fix(worktree_root, items, run_id=None, failure_summary=""):
            calls["n"] += 1
            if calls["n"] == 2:  # 重试 run 直接失败（产物硬门）
                return SimpleNamespace(run_id="code-fix-retry", success=False,
                                       fixed=0, skipped=0, error="重试产物缺失",
                                       output="")
            return real_fix(worktree_root, items, run_id=run_id,
                            failure_summary=failure_summary)

        runner.run_code_fix = flaky_fix
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        self.assertTrue(runner.worktree_manager.cleanup_calls,
                        "重试 run 失败也必须释放 spec 锁")
        self.assertEqual(read_items(proot)["a"]["status"], "open")
        self.assertEqual(load_failed_batches(proot), [],
                         "run 失败 ≠ 两次回归均失败，MUST NOT 入失败保留集合")
        prog = read_progress(proot)
        self.assertIn("regression_retry_run_failed", prog["reason"])

    def test_agent_run_failed_cleans_up_and_retries_later(self):
        """run 失败（产物硬门）→ 不合回不核销，cleanup 释放锁，条目保持 open。"""
        from types import SimpleNamespace

        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)

        def failing_fix(worktree_root, items, run_id=None, failure_summary=""):
            return SimpleNamespace(run_id="code-fix-x", success=False, fixed=0,
                                   skipped=0, error="产物缺失", output="")

        runner.run_code_fix = failing_fix
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        self.assertTrue(runner.worktree_manager.cleanup_calls, "agent 失败也要释放锁")
        self.assertEqual(read_items(proot)["a"]["status"], "open")
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertIn("agent_run_failed", prog["reason"])


class TestOverrideEnabled(unittest.TestCase):
    """checkpoint(override_enabled=True) 临时授权语义（add-code-fix-manual-trigger 1.2）。

    手动触发绕过总开关，但其余守卫（单飞 / 无 open 条目 / 失败保留 / 回归
    契约 fail-closed）原样生效；不传参的两路后台激活形态在 enabled=false
    下仍不投递（现状逐字节一致）。
    """

    def test_override_dispatches_when_disabled(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertTrue(res["triggered"], "开关关闭 + 手动临时授权 MUST 仍投递这一批")
        self.assertEqual(len(runner.fix_calls), 1)

    def test_override_still_respects_already_running(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner._running_agents = {"code-fix-123": object()}
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": False, "reason": "already_running"})
        self.assertEqual(runner.fix_calls, [])

    def test_override_still_respects_regression_contract_missing(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        # 不写 verify.yaml → 回归契约整体缺失；fail-closed 不因手动触发放宽
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": False, "reason": "regression_contract_missing"})
        self.assertEqual(runner.fix_calls, [])

    def test_default_no_override_disabled_still_blocks(self):
        """两路后台激活形态（不传参）在 enabled=false 下仍不投递（现状不变）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        self.assertEqual(runner.fix_calls, [])
        self.assertFalse((proot / ".fenix" / "code-review" / "fix-progress.json").exists(),
                         "开关关闭（未授权）MUST NOT 写进度")


class TestConcurrentCheckpoint(unittest.TestCase):
    def test_two_concurrent_checkpoints_dispatch_once(self):
        """两路并发到同一 checkpoint → 至多一次投递（单飞锁）。"""
        import types as _t

        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        started = threading.Event()
        release = threading.Event()

        class _SlowRunner(_FakeRunner):
            def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
                started.set()
                release.wait(timeout=10)
                return super().run_code_fix(worktree_root, items, run_id=run_id,
                                            failure_summary=failure_summary)

        runner = _SlowRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        results = {}

        def _call(tag):
            results[tag] = orch.checkpoint()

        t1 = threading.Thread(target=_call, args=("t1",))
        t1.start()
        self.assertTrue(started.wait(timeout=5), "批 worker 未启动")
        t2 = threading.Thread(target=_call, args=("t2",))
        t2.start()
        t2.join(timeout=10)
        release.set()
        t1.join(timeout=10)
        dispatched = [r["reason"] for r in results.values() if r.get("triggered")]
        blocked = [r["reason"] for r in results.values() if not r.get("triggered")]
        self.assertEqual(len(runner.fix_calls), 1, "至多一次投递")
        self.assertEqual(dispatched, ["dispatched"])
        self.assertIn("already_running", blocked)


# ── 6.5 run_code_fix 执行函数 ────────────────────────────────────────


def _make_exec_runner(proot, run_claude):
    runner = _make_runner(proot)
    runner._get_agent_model_assignment = lambda t: None
    runner._get_admin_model = lambda: "admin-model"
    runner._run_claude = run_claude
    return runner


def _write_out(opath, rows):
    opath.parent.mkdir(parents=True, exist_ok=True)
    with opath.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestRunCodeFix(unittest.TestCase):
    def test_artifact_gate_missing_out(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()  # out 落 worktree 侧
        calls = {}

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            calls["cwd"] = cwd
            calls["spec_name"] = kw.get("spec_name")
            calls["agent_type"] = kw.get("agent_type")
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        items = [_item("a")]
        result = run_code_fix(runner, wt, items)
        self.assertFalse(result.success)
        self.assertIn("产物", result.error)
        self.assertEqual(calls["cwd"], wt, "agent cwd MUST 为 worktree")
        self.assertEqual(calls["spec_name"], "code-review-fix")
        self.assertEqual(calls["agent_type"], "code-fix")

    def test_artifact_gate_zero_valid_rows(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, ["garbage-not-json", ""])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        result = run_code_fix(runner, wt, [_item("a")])
        self.assertFalse(result.success)
        self.assertIn("零有效行", result.error)

    def test_out_parsing_counts(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [
                {"item_id": "a", "status": "fixed", "file": "x.py"},
                {"item_id": "b", "status": "fixed", "file": "y.py"},
                {"item_id": "c", "status": "skipped", "file": "z.py"},
            ])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        result = run_code_fix(runner, wt, [_item("a"), _item("b"), _item("c")])
        self.assertTrue(result.success)
        self.assertEqual(result.fixed, 2)
        self.assertEqual(result.skipped, 1)

    def test_unique_run_id_backoff(self):
        from unittest import mock

        from core.agent_runner.maintenance_runs import _unique_code_fix_run_id

        proot = _make_project_root()
        runner = _make_runner(proot)
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            first = _unique_code_fix_run_id(runner)
        self.assertEqual(first, "code-fix-1000")
        # 撞名：预建同名产物文件 → 退避 -1
        (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "code-review" / "fix-out-code-fix-1000.jsonl").write_text(
            "{}", encoding="utf-8")
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            second = _unique_code_fix_run_id(runner)
        self.assertEqual(second, "code-fix-1000-1")
        # 在飞 run 同名 → 再退避
        runner._running_agents = {"code-fix-1000-1": object()}
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            third = _unique_code_fix_run_id(runner)
        self.assertEqual(third, "code-fix-1000-2")

    def test_model_chain_falls_back_to_code_review(self):
        """模型链：code-fix 缺配置时落 code-review 级（env 与 code-review 一致）。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        captured = {}

        provider = {
            "name": "prov-a", "baseurl": "http://gw", "apikey": "k",
            "env": {"X_EXTRA": "1"},
        }

        def assignment(agent_type):
            return [(provider, "model-for-review")] if agent_type == "code-review" else None

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            captured["env"] = env
            captured["model"] = model
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = assignment
        runner._get_admin_model = lambda: "admin-model"
        runner._ensure_agent_config_dir = lambda name, model: "/tmp/cfgdir"
        runner._run_claude = fake_claude
        result = run_code_fix(runner, wt, [_item("a")])
        self.assertTrue(result.success)
        self.assertEqual(captured["env"]["ANTHROPIC_BASE_URL"], "http://gw")
        self.assertEqual(captured["env"]["ANTHROPIC_MODEL"], "model-for-review")
        self.assertEqual(captured["env"]["X_EXTRA"], "1")
        self.assertEqual(captured["model"], "model-for-review")

    def test_model_chain_prefers_code_fix(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        captured = {}

        def assignment(agent_type):
            table = {
                "code-fix": [({"name": "p-fix", "baseurl": "http://fix",
                                "apikey": "k", "env": {}}, "model-fix")],
                "code-review": [({"name": "p-rev", "baseurl": "http://rev",
                                   "apikey": "k", "env": {}}, "model-rev")],
            }
            return table.get(agent_type)

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            captured["model"] = model
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = assignment
        runner._get_admin_model = lambda: "admin-model"
        runner._ensure_agent_config_dir = lambda name, model: "/tmp/cfgdir"
        runner._run_claude = fake_claude
        run_code_fix(runner, wt, [_item("a")])
        self.assertEqual(captured["model"], "model-fix", "显式 code-fix 配置优先")

    def test_forwarder_registered_and_not_in_execute_agent(self):
        import inspect

        from core.agent_runner.runner import AgentRunner

        self.assertIn("run_code_fix", AgentRunner._FORWARDER_REGISTRY)
        src = inspect.getsource(AgentRunner._execute_agent)
        self.assertNotIn("run_code_fix", src,
                         "code-fix MUST NOT 走 _execute_agent（不占 spec 维度预算）")

    def test_failure_summary_injected_into_prompt(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        prompts = []

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            prompts.append(prompt)
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        run_code_fix(runner, wt, [_item("a")], failure_summary="status=failed\n- t::x: boom")
        self.assertIn("上一轮回归失败用例", prompts[0])
        self.assertIn("boom", prompts[0])


# ── 7.4 激活接线 ─────────────────────────────────────────────────────


class _CheckpointRecorder:
    def __init__(self):
        self.calls = 0

    def checkpoint(self):
        self.calls += 1
        return {"triggered": False, "reason": "recorded"}


class TestActivationWiring(unittest.TestCase):
    def _run_review(self, proot, inserted, recorder):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "m"
        runner._code_fix_orchestrator = recorder

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"file": "core/a.py", "findings": [
                    {"file": "core/a.py", "title": "t", "severity": "major",
                     "category": "correctness", "line": 1, "description": "d",
                     "suggestion": "s"},
                ]}) + "\n")
            return ("done", 1, "sid", {})

        runner._run_claude = fake_claude
        with mock.patch.object(mr, "_accumulate_code_review_tokens",
                               lambda *a, **k: None), \
             mock.patch.object(mr, "upsert_findings",
                               lambda *a, **k: {"inserted": inserted, "updated": 0}):
            result = mr.run_code_review(runner, ["core/a.py"], "scheduled")
        return result

    def test_review_finish_triggers_checkpoint_when_inserted(self):
        proot = _make_project_root()
        recorder = _CheckpointRecorder()
        result = self._run_review(proot, inserted=3, recorder=recorder)
        self.assertTrue(result.success)
        self.assertEqual(recorder.calls, 1, "inserted>0 且成功落账 → 触发一次 checkpoint")

    def test_review_zero_insert_no_trigger(self):
        proot = _make_project_root()
        recorder = _CheckpointRecorder()
        result = self._run_review(proot, inserted=0, recorder=recorder)
        self.assertTrue(result.success)
        self.assertEqual(recorder.calls, 0, "零产出 MUST NOT 激活")

    def test_review_checkpoint_exception_does_not_fail_review(self):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "m"

        class _Boom:
            def checkpoint(self):
                raise RuntimeError("boom")

        runner._code_fix_orchestrator = _Boom()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"file": "core/a.py", "findings": [
                    {"file": "core/a.py", "title": "t", "severity": "major",
                     "category": "correctness", "line": 1, "description": "d",
                     "suggestion": "s"},
                ]}) + "\n")
            return ("done", 1, "sid", {})

        runner._run_claude = fake_claude
        with mock.patch.object(mr, "_accumulate_code_review_tokens",
                               lambda *a, **k: None), \
             mock.patch.object(mr, "upsert_findings",
                               lambda *a, **k: {"inserted": 5, "updated": 0}):
            result = mr.run_code_review(runner, ["core/a.py"], "scheduled")
        self.assertTrue(result.success, "checkpoint 异常 MUST NOT 使审查 run 失败")

    def test_full_scan_without_orchestrator_no_crash(self):
        import types as _t

        from core.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus.logger = _FakeLogger()
        bus.state_machine = _t.SimpleNamespace(read_all=lambda: {})
        bus._dispatch_changes = lambda specs: None
        bus.pm_engine = _t.SimpleNamespace(check_blockers=lambda: None)
        # 未装配 code_fix_orchestrator → 不抛异常
        bus._run_full_scan_body()

    def test_full_scan_calls_checkpoint(self):
        import types as _t

        from core.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus.logger = _FakeLogger()
        bus.state_machine = _t.SimpleNamespace(read_all=lambda: {})
        bus._dispatch_changes = lambda specs: None
        bus.pm_engine = _t.SimpleNamespace(check_blockers=lambda: None)
        recorder = _CheckpointRecorder()
        bus.code_fix_orchestrator = recorder
        bus._run_full_scan_body()
        self.assertEqual(recorder.calls, 1)


# ── 8.4 进度 API ─────────────────────────────────────────────────────


class TestFixProgressAPI(unittest.TestCase):
    def _server(self, tmpdir):
        from conftest import _TestServer, make_project
        from core.dashboard.registry import Registry

        tmp = Path(tmpdir)
        proot = make_project(tmp, "proj-a")
        cfg = tmp / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp / "scan-empty")]})
        static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
        return _TestServer(reg, static), proot

    def test_default_state_when_no_progress_file(self):
        td = _mkdtemp("cfix-api-")
        server, _ = self._server(td)
        try:
            status, body = server.get("/api/code-review/fix-progress?project=proj-a")
            self.assertEqual(status, 200)
            self.assertEqual(body["running"], False)
            self.assertEqual(body["phase"], "idle")
            self.assertEqual(body["total"], 0)
            self.assertEqual(body["done"], 0)
        finally:
            server.httpd.shutdown()

    def test_returns_written_progress(self):
        from core.code_fix import write_progress

        td = _mkdtemp("cfix-api-")
        server, proot = self._server(td)
        try:
            write_progress(proot, running=True, phase="fixing", total=60, done=40,
                           batch_no=2, activation_id="act-1")
            status, body = server.get("/api/code-review/fix-progress?project=proj-a")
            self.assertEqual(status, 200)
            self.assertEqual(body["running"], True)
            self.assertEqual(body["phase"], "fixing")
            self.assertEqual(body["total"], 60)
            self.assertEqual(body["done"], 40)
            self.assertEqual(body["batch_no"], 2)
        finally:
            server.httpd.shutdown()

    def test_unknown_project_404(self):
        td = _mkdtemp("cfix-api-")
        server, _ = self._server(td)
        try:
            status, _body = server.get("/api/code-review/fix-progress?project=nope")
            self.assertEqual(status, 404)
        finally:
            server.httpd.shutdown()


# ── 11.1 端到端装配预演（全新进程）────────────────────────────────────


class TestEndToEndSmoke(unittest.TestCase):
    def test_fresh_process_import_and_orchestrator(self):
        """全新 Python 进程 import + 构造 + 守卫断言（无需真实 daemon/agent）。"""
        code = r"""
import json, sys, tempfile
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

import core.code_fix
import core.config
import core.dashboard.data.code_review
# routes 直接 import 会撞 static_routes↔server 的既有循环导入（server.py:164
# ← static_routes.py:16），经 server 入口加载后（完成双向注册）再直接 import。
import core.dashboard.server
import core.dashboard.routes.code_review_routes
assert core.dashboard.routes.code_review_routes.H11CodeReviewRoutesMixin is not None

from core.code_fix import CodeFixOrchestrator, read_progress

td = Path(tempfile.mkdtemp(prefix="cfix-smoke-", dir=str(root / ".history" / "tmp")))
(td / ".fenix" / "code-review").mkdir(parents=True)

class FakeRunner:
    project_root = td
    def _get_config(self, key, default=None):
        return {}

# enabled=false → disabled
orch = CodeFixOrchestrator(FakeRunner(), td, config={"admin": {}}, logger=None)
assert orch.checkpoint() == {"triggered": False, "reason": "disabled"}, "disabled"

# enabled=true + 无 verify.yaml → regression_contract_missing + blocked 进度
(td / ".fenix" / "code-review" / "items.jsonl").write_text(
    json.dumps({"item_id": "a", "status": "open", "file": "x.py", "line": 1,
                "severity": "major", "category": "correctness", "title": "t",
                "description": "d", "suggestion": "s"}) + "\n", encoding="utf-8")
orch2 = CodeFixOrchestrator(FakeRunner(), td,
                            config={"admin": {"code_review_fix": {"enabled": True}}},
                            logger=None)
res = orch2.checkpoint()
assert res == {"triggered": False, "reason": "regression_contract_missing"}, res
prog = read_progress(td)
assert prog["phase"] == "blocked", prog
assert prog["reason"] == "regression_contract_missing", prog
print("SMOKE_OK")
"""
        repo_root = Path(__file__).resolve().parent.parent
        (repo_root / ".history" / "tmp").mkdir(parents=True, exist_ok=True)
        out = subprocess.run(
            [sys.executable, "-c", code, str(repo_root)],
            capture_output=True, text=True, timeout=120)
        self.assertIn("SMOKE_OK", out.stdout, f"stderr: {out.stderr[-2000:]}")


# ── 10.4 配置读写（admin.code_review_fix 受管键）──────────────────────


class TestCodeReviewFixConfigAdmin(unittest.TestCase):
    """admin.code_review_fix 受管键：登记 / sources / 回显 / 写读 / 非法拒绝（task 10.1/10.4）。"""

    def test_source_keys_registered(self):
        from core.dashboard.data import _SOURCE_KEYS

        self.assertIn("admin.code_review_fix", _SOURCE_KEYS)

    def test_sync_page_keys_contains_section(self):
        from core.dashboard.data.config_admin import _SYNC_PAGE_KEYS

        self.assertIn("code_review_fix", _SYNC_PAGE_KEYS["quality"].get("admin", []))

    def test_default_echo(self):
        from unittest import mock

        from core.dashboard.data import read_config, read_effective_config

        proot = _make_project_root()
        # 用户级 config.yaml 随部署环境漂移（本机真实部署已显式配置
        # code_review_fix.enabled=true）——patch 双常量锁定缺省回显：
        # 门面 USER_CONFIG_PATH（dashboard 读侧）+ core.config.USER_CONFIG_DIR
        # （resolve_config 合并读侧），与 test_fenix_tui_reports 同款。
        with mock.patch("core.dashboard.data.USER_CONFIG_PATH",
                        proot / "user-config-absent.yaml"), \
             mock.patch("core.config.USER_CONFIG_DIR",
                        proot / ".user-fenix-absent"):
            rc = read_config(proot)
            self.assertEqual(rc["code_review_fix"], {"enabled": False, "batch_size": 20})
            self.assertEqual(rc["sources"]["admin.code_review_fix"], "user")
            eff = read_effective_config(proot)
            self.assertEqual(eff["code_review_fix"], {"enabled": False, "batch_size": 20})

    def test_write_read_roundtrip(self):
        from core.dashboard.data import read_config, write_config

        proot = _make_project_root()
        r = write_config(proot, {"code_review_fix": {"enabled": True, "batch_size": 30}})
        self.assertIsNone(r.get("error"), r)
        rc = read_config(proot)
        self.assertEqual(rc["code_review_fix"], {"enabled": True, "batch_size": 30})
        self.assertEqual(rc["sources"]["admin.code_review_fix"], "project")

    def test_invalid_batch_size_rejected_no_half_write(self):
        from core.dashboard.data import read_config, write_config

        proot = _make_project_root()
        # 先写一个合法值
        r = write_config(proot, {"code_review_fix": {"enabled": True, "batch_size": 30}})
        self.assertIsNone(r.get("error"))
        # 非法 batch_size → 拒绝且不半写
        for bad in (0, -3, True, "20"):
            r = write_config(proot, {"code_review_fix": {"batch_size": bad}})
            self.assertIsNotNone(r.get("error"), f"batch_size={bad!r} MUST 拒绝")
            self.assertIn("positive integer", r["error"])
        # enabled 非 bool → 拒绝
        r = write_config(proot, {"code_review_fix": {"enabled": "yes"}})
        self.assertIsNotNone(r.get("error"))
        self.assertIn("boolean", r["error"])
        # 落盘值保持原值（不半写）
        rc = read_config(proot)
        self.assertEqual(rc["code_review_fix"], {"enabled": True, "batch_size": 30})
