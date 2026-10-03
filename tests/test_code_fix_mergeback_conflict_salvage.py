"""合回冲突定向救回（evo-add-codefix-mergeback-conflict-salvage 3.1）。

覆盖七场景：真冲突→rebase 成功救回（不整批入档案）、rebase 仍冲突→非冲突
组 cherry-pick 回收、冲突组条目入档案计 fail_count、救回发生在 cleanup 前
分支可用、defer 路径不触发救回、回收集二次回归仍不过→放弃回收整批兜底、
旧契约批无 items: 清单→保守整批兜底。

git 层行为（merge-tree 预演真冲突 / rebase 冲突 / cherry-pick / 真合并）用
真仓驱动：``_SalvageWM`` 继承真实 ``WorktreeManager``（merge_back 预演闸、
``rehearsal_conflict_paths``、``merge_back_from_branch``、cleanup 全为生产
代码），仅 create() 换成最小真 worktree 建树、merge_back 可按脚本注入预演
形态冲突/wip 阻断（「预演检出真冲突但 rebase 可解」的编排形态——冲突检测
本体由 mergeback 侧生产代码承担，S2 系列场景的首调合回走全真路径）。

主树前移时序对齐生产（冲突提交在链生命周期内落地）：main_advance 在
run_code_fix 钩子内提交到主树——批 worktree 建树先于该提交，合回时分支才
与主树真冲突（若建树前移则分支为 HEAD 后代、合并幂等成功，构不成冲突）。
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.worktree_manager import WorktreeManager
from core.worktree_manager.types import MergeConflictInfo


def _git(cwd, *args, check=False):
    res = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True,
    )
    if check and res.returncode != 0:
        raise AssertionError(f"git {args} failed: {res.stderr}")
    return res


def _commit_all(cwd, message):
    _git(cwd, "add", "-A", check=True)
    _git(cwd, "commit", "-q", "-m", message, check=True)


class _CapLogger:
    """记录级日志捕获器（救回各阶段留痕断言用）。"""

    def __init__(self):
        self.lines = []

    def _rec(self, level):
        def _log(tag, msg):
            self.lines.append((level, str(msg)))
        return _log

    def __getattr__(self, name):
        return self._rec(name)

    def by_level(self, level):
        return [m for lv, m in self.lines if lv == level]


def _make_salvage_root():
    """带 .fenix 结构的真 git 项目根（master 主干、identity、运行时忽略）。"""
    td = Path(tempfile.mkdtemp(prefix="cfix-salvage-"))
    (td / ".fenix" / "code-review").mkdir(parents=True)
    (td / ".gitignore").write_text(".fenix/\n_wts/\n", encoding="utf-8")
    (td / "README.md").write_text("base\n", encoding="utf-8")
    _git(td, "init", "-q", "-b", "master")
    _git(td, "config", "user.email", "t@t")
    _git(td, "config", "user.name", "t")
    _commit_all(td, "init")
    return td


def _write_items(project_root, records):
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(records[k], ensure_ascii=False) + "\n"
                for k in sorted(records)),
        encoding="utf-8",
    )


def _item(item_id, status="open", first_seen_at=None, **extra):
    rec = {"item_id": item_id, "status": status,
           "file": f"{item_id}/{item_id}.py", "line": 1, "severity": "major",
           "category": "correctness", "title": f"title {item_id}",
           "description": f"desc {item_id}", "suggestion": f"sug {item_id}",
           "fingerprint": f"fp-{item_id}"}
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    rec.update(extra)
    return rec


def _write_verify_yaml(proot: Path):
    (proot / ".fenix" / "verify.yaml").write_text(
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
        "regression:\n"
        "  cmd: \"true\"\n"
        "  output: \".fenix/regression/junit.xml\"\n",
        encoding="utf-8",
    )


class _SalvageWM(WorktreeManager):
    """真实 WorktreeManager，仅替换 create/注入 merge_back 脚本。"""

    def __init__(self, proot):
        super().__init__(base_dir=proot / "_wts", project_root=proot, logger=None)
        self.script = []
        self.scripted_paths = ["shared.txt"]
        self.create_calls = []
        self.merge_calls = []
        self.from_branch_calls = []
        self.cleanup_calls = []
        self.release_calls = []
        self.branch_names = []
        self._n = 0

    def create(self, spec_name, agent_type="code-fix"):
        self.create_calls.append((spec_name, agent_type))
        self._n += 1
        branch = f"fenix/{spec_name}-{self._n}"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self.base_dir / f"wt-{self._n}"
        res = _git(self.project_root, "worktree", "add", "-b", branch,
                   str(path), "master")
        if res.returncode != 0:
            return None
        self.branch_names.append(branch)
        self._active_worktrees.add(str(path))
        self._wt_branches[str(path)] = branch
        return path

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        act = self.script.pop(0) if self.script else "real"
        if act == "conflict":
            # 预演闸检出的语义冲突返回形态（mergeback.py 生产代码同型）；
            # 底层 git 态由 main_advance 保证 rebase 可解（S1 编排形态）。
            return MergeConflictInfo(
                False,
                "Semantic merge conflicts detected by pre-merge rehearsal (1 path(s))",
                conflict_paths=list(self.scripted_paths),
                has_semantic_conflict=True, rehearsed=True,
            )
        if act == "wip":
            return MergeConflictInfo(
                False, "wip gate blocked", wip_overlap=["shared.txt"],
                wip_gate_blocked=True,
            )
        return super().merge_back(wt_path)

    def merge_back_from_branch(self, branch):
        self.from_branch_calls.append(branch)
        return super().merge_back_from_branch(branch)

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))
        super().cleanup(wt_path, success=success)

    def release_spec_lock(self, spec_name, agent_type="code-fix"):
        self.release_calls.append((spec_name, agent_type))
        return super().release_spec_lock(spec_name, agent_type)


class _SalvageRunner:
    """code-fix runner 替身：run_code_fix 按脚本提交组、run_regression 按序返回。

    plan：每 run 一个组列表，每组 ``{"files": {路径: 内容}, "items": [id…]}``：
    逐组一次提交、body 带 ``items:`` 清单（``no_items=True`` 时省略——旧契约
    形态）；``main_advance``（可选）在派 run 前把给定文件提交到主树（生产时序：
    链生命周期内基线前移）。缺省（plan 空）全批一组一次提交。
    """

    def __init__(self, proot, plan=None, regression_statuses=("passed",)):
        self.project_root = Path(proot)
        self.logger = _CapLogger()
        self.config = {}
        self.worktree_manager = None  # 由用例注入 _SalvageWM
        self._running_agents = {}
        self.plan = plan or []
        self.regression_statuses = list(regression_statuses)
        self.fix_calls = []
        self.regression_calls = []       # (project_root, lock_root)
        self.branch_alive_at_regression = []
        self.master_tips = []            # main_advance 后的主树 tip
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-salvage-{self._run_no}"
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        groups = self.plan[(self._run_no - 1) % len(self.plan)] if self.plan else None
        if groups is None:
            groups = [{"items": [it["item_id"] for it in items]}]
        # 链生命周期内基线前移（生产时序）：主树在批 run 在飞期间前进
        for g in groups:
            adv = g.get("main_advance") or {}
            for rel, content in adv.items():
                p = Path(self.project_root) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            if adv:
                _commit_all(self.project_root, "main advance")
                self.master_tips.append(
                    _git(self.project_root, "rev-parse", "master").stdout.strip()
                )
        rows = []
        for g in groups:
            for rel, content in (g.get("files") or {}).items():
                p = Path(worktree_root) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            ids = g.get("items") or []
            if g.get("no_items"):
                msg = "fix: 修复 code-review 台账条目（code-fix batch）\n"
            else:
                msg = ("fix: 修复 code-review 台账条目（code-fix batch）\n\n"
                       "items: " + ", ".join(ids) + "\n")
            _commit_all(worktree_root, msg)
            rows.extend({"item_id": i, "status": "fixed", "file": ""} for i in ids)
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
        return SimpleNamespace(run_id=rid, success=True, fixed=len(rows),
                               skipped=0, error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None,
                       lock_root=None, subset_nodeids=None):
        self.regression_calls.append((str(project_root), str(lock_root)))
        wt = Path(project_root)
        # 救回时序取证：回归执行点批分支引用必须仍可用（cleanup 未发生）
        head = _git(wt, "rev-parse", "HEAD")
        self.branch_alive_at_regression.append(
            wt.exists() and head.returncode == 0 and bool(head.stdout.strip())
        )
        status = self.regression_statuses[
            min(len(self.regression_calls) - 1, len(self.regression_statuses) - 1)
        ]
        return SimpleNamespace(
            status=status,
            snapshot={"failures": [
                {"classname": "t", "name": "x", "message": "boom"}]},
            error="",
        )


def _orch(proot, runner, cap, batch_size=10):
    from core.code_fix import CodeFixOrchestrator

    return CodeFixOrchestrator(
        runner, proot,
        config={"admin": {"code_review_fix": {
            "enabled": True, "batch_size": batch_size}}},
        logger=cap,
    )


def _setup(proot, ids=("a",)):
    _write_items(proot, {i: _item(i, first_seen_at="2026-01-01T00:00:00Z")
                         for i in ids})
    _write_verify_yaml(proot)


def _finals(cap):
    return [m for _, m in cap.lines if "救回终局" in m]


class TestRebaseSalvageSuccess(unittest.TestCase):
    """场景一：真冲突 → rebase 成功救回（不整批入档案）。"""

    def test_rebase_success_salvages_whole_batch(self):
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a",))
        wm = _SalvageWM(proot)
        wm.script = ["conflict"]  # 首次合回：预演检出真冲突
        runner = _SalvageRunner(
            proot,
            plan=[[{"files": {"feat_a.txt": "a-fix\n"}, "items": ["a"],
                    "main_advance": {"master_note.txt": "note\n"}}]],
            regression_statuses=["passed", "passed"],
        )
        runner.worktree_manager = wm
        cap = _CapLogger()
        orch = _orch(proot, runner, cap)
        orch.checkpoint()

        self.assertEqual(len(wm.merge_calls), 2, "救回 MUST 重走合回")
        self.assertEqual(len(runner.regression_calls), 2, "救回 MUST 重跑批回归")
        self.assertTrue(all(runner.branch_alive_at_regression),
                        "救回回归执行点批分支引用 MUST 可用（cleanup 未发生）")
        branch = wm.branch_names[0]
        self.assertEqual(
            _git(proot, "merge-base", "--is-ancestor",
                 runner.master_tips[0], branch).returncode,
            0, "救回 rebase 后批分支 MUST 包含基线新提交")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved", "整批救回 MUST 正常出账")
        self.assertEqual(load_failed_batches(proot), [],
                         "救回成功 MUST NOT 入失败档案")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), True)])
        finals = _finals(cap)
        self.assertTrue(any("整批救回" in m for m in finals), finals)


class TestCherryPickRecovery(unittest.TestCase):
    """场景二/三：rebase 仍冲突 → 非冲突组回收；冲突组条目入档案计 fail_count。"""

    def _plan(self):
        return [[
            {"files": {"mod_a.txt": "a-fix\n"}, "items": ["a"]},
            {"files": {"shared.txt": "l1\nl2-batch\nl3\n"}, "items": ["b"]},
            {"files": {"mod_c.txt": "c-fix\n"}, "items": ["c"]},
        ]]

    def _run(self, proot, runner, cap):
        wm = _SalvageWM(proot)  # 无脚本：首调合回由真 merge-tree 预演检出真冲突
        runner.worktree_manager = wm
        _orch(proot, runner, cap).checkpoint()
        return wm

    def test_non_conflict_groups_recovered_conflict_group_archived(self):
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a", "b", "c"))
        # 主树前移在 run 钩子内（生产时序）；冲突组触碰 shared.txt
        runner = _SalvageRunner(
            proot, plan=self._plan(), regression_statuses=["passed", "passed"])
        runner.plan[0][1]["main_advance"] = {"shared.txt": "l1\nl2-main\nl3\n"}
        cap = _CapLogger()
        wm = self._run(proot, runner, cap)

        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved", "非冲突组 a MUST 回收出账")
        self.assertEqual(items["c"]["status"], "resolved", "非冲突组 c MUST 回收出账")
        self.assertEqual(items["b"]["status"], "open", "仍冲突组条目 MUST 保持 open")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"b"})
        self.assertEqual(failed[0]["fail_count"], 1, "仍冲突组 MUST 计 fail_count")
        self.assertEqual(failed[0]["reason"], "merge_back_conflict")
        self.assertTrue(failed[0]["branch"] and failed[0]["tip_sha"])
        # 承载分支真合并：非冲突组改动随救回进入主树，冲突文件保持主树版本
        self.assertTrue((proot / "mod_a.txt").exists())
        self.assertTrue((proot / "mod_c.txt").exists())
        self.assertIn("l2-main", (proot / "shared.txt").read_text(encoding="utf-8"))
        # 注：真 merge_back 内部委托 merge_back_from_branch（多态），首调合回
        # 本身就会记 1 次；回收出账对应的是其后新增的承载分支那一次。
        self.assertEqual(len(wm.from_branch_calls), 2,
                         "回收出账 MUST 经承载分支合回（首次 + 承载）")
        carrier = wm.from_branch_calls[-1]
        self.assertTrue(carrier.startswith(wm.branch_names[0]),
                        "承载分支 MUST 由批分支派生")
        self.assertNotEqual(carrier, wm.branch_names[0])
        finals = _finals(cap)
        self.assertTrue(any("部分回收" in m for m in finals), finals)

    def test_conflict_group_fail_count_increments_across_records(self):
        """预存失败档案的同条目集再次入档 MUST 复用记录递增（既有预算语义）。"""
        from core.code_fix import load_failed_batches, record_failed_batch
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a", "b", "c"))
        record_failed_batch(proot, ["b"], None, reason="merge_back_conflict",
                            branch="old", tip_sha="old")
        runner = _SalvageRunner(
            proot, plan=self._plan(), regression_statuses=["passed", "passed"])
        runner.plan[0][1]["main_advance"] = {"shared.txt": "l1\nl2-main\nl3\n"}
        wm = self._run(proot, runner, _CapLogger())

        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"b"})
        self.assertEqual(failed[0]["fail_count"], 2,
                         "同条目集再入档 MUST 递增 fail_count")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["c"]["status"], "resolved")
        self.assertTrue((proot / "mod_a.txt").exists())


class TestDeferPathNoSalvage(unittest.TestCase):
    """场景四：wip_gate_blocked defer 零预算路径 MUST NOT 触发救回。"""

    def test_wip_gate_blocked_defers_without_salvage(self):
        from core.code_fix import (load_deferred_batches, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a",))
        wm = _SalvageWM(proot)
        # 两次 wip 阻断：首次批收尾 + 链边界 defer 消费路径重试（既有语义）
        wm.script = ["wip", "wip"]
        runner = _SalvageRunner(
            proot,
            plan=[[{"files": {"mod_a.txt": "a-fix\n"}, "items": ["a"]}]],
            regression_statuses=["passed"],
        )
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        deferred = load_deferred_batches(proot)
        self.assertEqual(len(deferred), 1, "wip 阻断 MUST 走 defer 台账")
        self.assertEqual(deferred[0]["defer_count"], 2,
                         "链边界重试仍被阻断 MUST 计 defer_count")
        self.assertEqual(load_failed_batches(proot), [],
                         "defer 零预算 MUST NOT 入失败档案")
        self.assertEqual(read_items(proot)["a"]["status"], "open")
        self.assertEqual(len(runner.regression_calls), 1,
                         "defer 路径 MUST NOT 触发救回回归")
        self.assertEqual(len(wm.merge_calls), 2,
                         "defer 路径仅首调 + defer 重试，MUST NOT 有救回合回")
        self.assertEqual(wm.cleanup_calls, [], "defer 保留现场 MUST NOT cleanup")
        self.assertTrue(wm.release_calls, "defer MUST 放锁")
        self.assertEqual(read_progress(proot)["reason"], "wip_gate_blocked")
        self.assertFalse([m for m in cap.by_level("info") if "救回开始" in m],
                         "defer 路径 MUST NOT 触发救回")


class TestRecoveryRegressionFailFallback(unittest.TestCase):
    """场景五：回收集二次回归仍不过 → 放弃回收，整批兜底入档案。"""

    def test_recovery_regression_fail_abandons_recovery(self):
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a", "b", "c"))
        runner = _SalvageRunner(
            proot,
            plan=[[{"files": {"mod_a.txt": "a\n"}, "items": ["a"]},
                   {"files": {"shared.txt": "l1\nl2-batch\nl3\n"}, "items": ["b"],
                    "main_advance": {"shared.txt": "l1\nl2-main\nl3\n"}},
                   {"files": {"mod_c.txt": "c\n"}, "items": ["c"]}]],
            regression_statuses=["passed", "failed"],
        )
        wm = _SalvageWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a", "b", "c"},
                         "放弃回收 MUST 整批兜底入档案")
        self.assertEqual(failed[0]["reason"], "merge_back_conflict")
        items = read_items(proot)
        self.assertTrue(all(items[i]["status"] == "open" for i in ("a", "b", "c")))
        self.assertEqual(
            [c for c in wm.from_branch_calls if c != wm.branch_names[0]],
            [], "回归不过 MUST NOT 走承载分支合回")
        self.assertIn("l2-main", (proot / "shared.txt").read_text(encoding="utf-8"))
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), False)])
        finals = _finals(cap)
        self.assertTrue(any("兜底全弃" in m for m in finals), finals)
        # 批分支已还原：legacy 保留现场 checkout 回批分支
        wt = wm.base_dir / "wt-1"
        self.assertTrue(wt.exists(),
                        "cleanup(success=False) MUST 保留现场（legacy）")
        self.assertEqual(
            _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(),
            wm.branch_names[0], "救回放弃 MUST 把 worktree 还原回批分支")


class TestOldContractConservativeFallback(unittest.TestCase):
    """场景六：旧契约批无 items: 清单 → 保守整批兜底（不做无据归属）。"""

    def test_no_items_body_archives_whole_batch(self):
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_salvage_root()
        _setup(proot, ("a", "b", "c"))
        runner = _SalvageRunner(
            proot,
            plan=[[{"files": {"mod_a.txt": "a\n"}, "items": ["a"],
                    "no_items": True},
                   {"files": {"shared.txt": "l1\nl2-batch\nl3\n"}, "items": ["b"],
                    "no_items": True,
                    "main_advance": {"shared.txt": "l1\nl2-main\nl3\n"}},
                   {"files": {"mod_c.txt": "c\n"}, "items": ["c"],
                    "no_items": True}]],
            regression_statuses=["passed", "passed"],
        )
        wm = _SalvageWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        # 回收合回照常发生（救回计算力不浪费），出账保守：全部入档案
        self.assertEqual(len(wm.from_branch_calls), 2,
                         "首次合回 + 承载分支合回（真 merge_back 内部委托多态记账）")
        self.assertTrue((proot / "mod_a.txt").exists())
        items = read_items(proot)
        self.assertTrue(all(items[i]["status"] == "open" for i in ("a", "b", "c")))
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a", "b", "c"},
                         "旧契约批 MUST 保守整批入档案（不做无据归属）")
        finals = _finals(cap)
        self.assertTrue(
            any("部分回收" in m and "resolved 候选 0 条" in m for m in finals),
            finals)


class TestRehearsalConflictPaths(unittest.TestCase):
    """task 1.2：冲突文件集查询（真 merge-tree 预演，生产代码直测）。"""

    def test_conflict_branch_reports_paths(self):
        proot = _make_salvage_root()
        wm = WorktreeManager(base_dir=proot / "_wts", project_root=proot,
                             logger=None)
        wt = proot / "_wts" / "probe"
        wt.mkdir(parents=True)
        _git(proot, "worktree", "add", "-b", "fenix/probe", str(wt), "master")
        (wt / "shared.txt").write_text("l1\nl2-batch\nl3\n", encoding="utf-8")
        _commit_all(wt, "batch side")
        (proot / "shared.txt").write_text("l1\nl2-main\nl3\n", encoding="utf-8")
        _commit_all(proot, "main side")

        self.assertEqual(wm.rehearsal_conflict_paths("fenix/probe"),
                         ["shared.txt"])

    def test_clean_branch_reports_empty(self):
        proot = _make_salvage_root()
        wm = WorktreeManager(base_dir=proot / "_wts", project_root=proot,
                             logger=None)
        wt = proot / "_wts" / "probe"
        wt.mkdir(parents=True)
        _git(proot, "worktree", "add", "-b", "fenix/probe", str(wt), "master")
        (wt / "other.txt").write_text("x\n", encoding="utf-8")
        _commit_all(wt, "unrelated")

        self.assertEqual(wm.rehearsal_conflict_paths("fenix/probe"), [])


class TestCleanupOrdering(unittest.TestCase):
    """场景补充：救回发生在 cleanup 前，批分支引用全程可用。"""

    def test_branch_alive_through_salvage_regression(self):
        proot = _make_salvage_root()
        _setup(proot, ("a",))
        wm = _SalvageWM(proot)
        wm.script = ["conflict"]
        runner = _SalvageRunner(
            proot,
            plan=[[{"files": {"feat_a.txt": "a\n"}, "items": ["a"],
                    "main_advance": {"master_note.txt": "note\n"}}]],
            regression_statuses=["passed", "passed"],
        )
        runner.worktree_manager = wm
        _orch(proot, runner, _CapLogger()).checkpoint()

        self.assertEqual(len(runner.regression_calls), 2)
        self.assertEqual(runner.regression_calls[1][0],
                         str(wm.base_dir / "wt-1"),
                         "救回回归执行根 MUST 仍是批 worktree")
        self.assertTrue(runner.branch_alive_at_regression[1],
                        "救回回归执行点 MUST 仍在 cleanup 之前（分支可用）")
        self.assertEqual(len(wm.cleanup_calls), 1)
        self.assertEqual(wm.cleanup_calls[0][1], True)


if __name__ == "__main__":
    unittest.main()
