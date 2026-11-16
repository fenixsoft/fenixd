"""code-fix 合并门纯标记提交保全（evo-fix-code-fix-merge-gate-marker-loss）。

覆盖四场景组：纯标记批放行合回（TS ``<!-- -->`` 形态〔对照 00162a0 实例〕与
Python ``#`` 形态）、混合批反例（含「删实质代码+贴标记」穿透反例）弃件留证、
全批 ignored 收尾路径同治、零行为变化回归（fixed>0 合回 / commits=0 零产物
拒合回 / 可修复形态 salvage 三路径）。

git 层行为用真仓驱动（同 test_code_fix_mergeback_conflict_salvage 先例）：
``_MarkerWM`` 继承真实 ``WorktreeManager``（merge_back 预演闸/真合并/cleanup
全为生产代码），仅 create() 换成最小真 worktree 建树。形态核查本体由生产
代码（``_batch_marker_review``）承担，测试在编排层出题。

「留痕先于清理」（design D3）的顺序断言在 cleanup 钩子内即时快照
``.fenix/admin_alerts.json``：清理执行时刻弃件告警已在盘 = 顺序成立。
"""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.admin_store import AdminStore
from core.worktree_manager import WorktreeManager

DISCARD_SIGNAL = "code_fix_batch_discarded"


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
    """记录级日志捕获器（注记文案断言用）。"""

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


def _make_marker_root():
    """带 .fenix 结构的真 git 项目根（master 主干、identity、运行时忽略）。

    预置被测源文件基线（src/app.ts、src/util.py）：纯标记出题要求「在既有
    文件上插入标记行」——新文件整文件均为新增行，形态核查判混合属正确行为。
    """
    td = Path(tempfile.mkdtemp(prefix="cfix-marker-"))
    (td / ".fenix" / "code-review").mkdir(parents=True)
    (td / ".gitignore").write_text(".fenix/\n_wts/\n", encoding="utf-8")
    (td / "README.md").write_text("base\n", encoding="utf-8")
    (td / "src").mkdir()
    (td / "src" / "app.ts").write_text(BASE_TS, encoding="utf-8")
    (td / "src" / "util.py").write_text(BASE_PY, encoding="utf-8")
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


# 被测源文件基线内容（worktree 建树自 master，fixer 在其上贴标记/改动）。
BASE_TS = "const a = 1;\nconst b = 2;\n"
BASE_PY = "def f():\n    return 1\n"


class _MarkerWM(WorktreeManager):
    """真实 WorktreeManager，仅替换 create() 与 cleanup() 取证钩子。"""

    def __init__(self, proot):
        super().__init__(base_dir=proot / "_wts", project_root=proot, logger=None)
        self.create_calls = []
        self.cleanup_calls = []
        self.branch_names = []
        # 顺序取证（D3）：cleanup 执行时刻弃件告警是否已在盘。
        self.alert_present_at_cleanup = None
        self._n = 0

    def _discard_alert_on_disk(self) -> bool:
        path = self.project_root / ".fenix" / "admin_alerts.json"
        if not path.exists():
            return False
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — 取证钩子读失败按不在盘
            return False
        if isinstance(records, dict):
            records = records.get("records") or records.get("alerts") or []
        return any(
            isinstance(r, dict) and r.get("signal_type") == DISCARD_SIGNAL
            for r in records if isinstance(r, dict)
        )

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

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))
        if self.alert_present_at_cleanup is None:
            self.alert_present_at_cleanup = self._discard_alert_on_disk()
        super().cleanup(wt_path, success=success)


class _MarkerRunner:
    """code-fix runner 替身：run_code_fix 按组落文件/提交/产物行。

    plan：组列表，每组 ``{"files": {路径: 内容}, "rows": [产物行]}``；
    ``commit=False``（类级）时不提交（commits=0 / salvage 出题用）。
    缺省（plan 空）全批一组，产物行由 ``skip_reasons`` 生成。
    """

    def __init__(self, proot, plan=None, skip_reasons=("false_positive",),
                 commit=True):
        self.project_root = Path(proot)
        self.logger = _CapLogger()
        self.config = {}
        self.worktree_manager = None
        self.plan = plan or []
        self.skip_reasons = list(skip_reasons)
        self.commit = commit
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-marker-{self._run_no}"
        groups = self.plan or [{
            "items": [it["item_id"] for it in items],
            "files": {},
        }]
        rows = []
        for g in groups:
            for rel, content in (g.get("files") or {}).items():
                p = Path(worktree_root) / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")
            if self.commit:
                ids = g.get("items") or [it["item_id"] for it in items]
                msg = ("fix: 修复 code-review 台账条目（code-fix batch）\n\n"
                       "items: " + ", ".join(ids) + "\n")
                _commit_all(worktree_root, msg)
            rows.extend(g.get("rows") or [])
        if not rows:
            for i, it in enumerate(items):
                reason = self.skip_reasons[
                    min(i, len(self.skip_reasons) - 1)
                ]
                rows.append({"item_id": it["item_id"], "status": "skipped",
                             "skip_reason": reason, "file": ""})
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8",
        )
        fixed = sum(1 for r in rows if r.get("status") == "fixed")
        return SimpleNamespace(run_id=rid, success=True, fixed=fixed,
                               skipped=len(rows) - fixed, error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None,
                       lock_root=None, subset_nodeids=None):
        return SimpleNamespace(status="passed", snapshot={"failures": []},
                               error="")


def _orch(proot, runner, cap, batch_size=10):
    from core.code_fix import CodeFixOrchestrator

    return CodeFixOrchestrator(
        runner, proot,
        config={"admin": {"code_review_fix": {
            "enabled": True, "batch_size": batch_size}}},
        logger=cap,
    )


def _setup(proot, ids):
    _write_items(proot, {i: _item(i, first_seen_at="2026-01-01T00:00:00Z")
                         for i in ids})
    _write_verify_yaml(proot)


def _discard_alerts(proot):
    return [
        r for r in AdminStore(proot).read_all()
        if r.get("signal_type") == DISCARD_SIGNAL
    ]


def _read_progress(proot):
    from core.code_fix import read_progress

    return read_progress(proot)


class TestMarkerOnlyBatchReleased(unittest.TestCase):
    """场景组一（task 2.1）：纯标记批放行合回，pending 条目入 chain_skipped。"""

    def _run_released(self, proot, marker_file, marker_line):
        _setup(proot, ("a", "b"))
        # a：误报（既有文件上插入标记行）；b：needs_human（不改动，保持 open）
        base = BASE_TS if marker_file.endswith(".ts") else BASE_PY
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {marker_file: base + marker_line + "\n"},
            "rows": [
                {"item_id": "a", "status": "skipped",
                 "skip_reason": "false_positive", "file": marker_file},
                {"item_id": "b", "status": "skipped",
                 "skip_reason": "needs_human", "file": ""},
            ],
        }])
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()
        return wm, cap, runner

    def test_html_comment_form_marker_released(self):
        """``<!-- -->`` 形态（对照 11-14 弃件 00162a0：TS 文件内 HTML 注释）。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        marker = "<!-- [fenix-ignore:aaaa1111bbbb] 误报：窗口有界 -->"
        wm, cap, runner = self._run_released(proot, "src/app.ts", marker)

        # 合回成功：标记进主树
        self.assertIn(marker, (proot / "src" / "app.ts").read_text(encoding="utf-8"))
        # pending 条目不核销不置终态：b 保持 open
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(items["b"]["status"], "open",
                         "pending 条目 MUST NOT 因批放行被核销或置终态")
        # 完成收尾（非失败）：cleanup success=True、worktree 已清理
        self.assertEqual(len(wm.cleanup_calls), 1)
        self.assertTrue(wm.cleanup_calls[0][1], "放行批 MUST 按 success 清理")
        self.assertFalse((wm.base_dir / "wt-1").exists())
        # 批级注记「产物已合并（纯标记）」
        self.assertTrue(
            any("产物已合并（纯标记）" in m for _, m in cap.lines), cap.lines)
        prog = _read_progress(proot)
        self.assertIn("b", prog.get("chain_skipped") or [],
                      "pending 条目 MUST 入 chain_skipped（下链重试语义）")
        # 无弃件告警（cleanup 快照时刻盘上无弃件告警）
        self.assertEqual(_discard_alerts(proot), [])
        self.assertFalse(wm.alert_present_at_cleanup)
        # 链终局 rollup 注记 marker_merged=1（链级字段随出账清零，rollup
        # 快照是权威对账面）
        rollup = prog.get("chain_rollup") or {}
        self.assertEqual(rollup.get("marker_merged"), 1,
                         f"rollup 注记缺失: {rollup}")
        self.assertEqual(rollup.get("marker_discarded") or [], [])

    def test_python_hash_form_marker_released(self):
        """``#`` 形态（Python 标记批）。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        marker = "# [fenix-ignore:aaaa1111bbbb] 误报：有上游去重"
        wm, cap, _ = self._run_released(proot, "src/util.py", marker)

        self.assertIn(marker, (proot / "src" / "util.py").read_text(encoding="utf-8"))
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(items["b"]["status"], "open")
        self.assertTrue(any("产物已合并（纯标记）" in m for _, m in cap.lines))
        self.assertEqual(
            (_read_progress(proot).get("chain_rollup") or {}).get("marker_merged"),
            1)
        self.assertEqual(_discard_alerts(proot), [])


class TestMixedBatchDiscarded(unittest.TestCase):
    """场景组二（task 2.2）：混合批不误放，弃件留证先于清理。"""

    def test_mixed_batch_rejected_with_trace_before_cleanup(self):
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a", "b"))
        marker = "# [fenix-ignore:aaaa1111bbbb] 误报"
        # 混合改动：a 贴标记（app.ts 纯标记行）+ 实质源码变更（core.py）+
        # 「删实质代码+贴标记」穿透反例（util.py：删 def f/return、只留标记）
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {
                "src/app.ts": BASE_TS + "<!-- [fenix-ignore:aaaa1111bbbb] 误报 -->\n",
                "src/core.py": "changed_real_code = 1\n",
                "src/util.py": marker + "\n",
            },
            "rows": [
                {"item_id": "a", "status": "skipped",
                 "skip_reason": "false_positive", "file": "src/app.ts"},
                {"item_id": "b", "status": "skipped",
                 "skip_reason": "needs_human", "file": ""},
            ],
        }])
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        # 不合回：实质变更与标记均不在主树（core.py 拒合回后本就不存在）
        core_p = proot / "src" / "core.py"
        self.assertTrue(
            not core_p.exists()
            or "changed_real_code" not in core_p.read_text(encoding="utf-8"))
        self.assertNotIn("fenix-ignore",
                         (proot / "src" / "app.ts").read_text(encoding="utf-8"))
        self.assertIn(BASE_PY, (proot / "src" / "util.py").read_text(encoding="utf-8"),
                      "「删实质代码+贴标记」反例 MUST NOT 放行")
        # 条目处置：a 置 ignored（LLM 硬出口）、b 保持 open 入 chain_skipped
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(items["b"]["status"], "open")
        prog = _read_progress(proot)
        self.assertIn("b", prog.get("chain_skipped") or [])
        # 弃件告警：完整 SHA + 非标记文件清单
        alerts = _discard_alerts(proot)
        self.assertEqual(len(alerts), 1, f"弃件告警缺失: {alerts}")
        evidence = alerts[0].get("evidence") or ""
        self.assertIn("a", evidence)
        self.assertIn("b", evidence)
        # app.ts 为纯标记改动，正确地不出现在非标记清单
        for f in ("src/core.py", "src/util.py"):
            self.assertIn(f, evidence, f"非标记文件清单缺 {f}: {evidence}")
        import re as _re
        shas = _re.findall(r"\b[0-9a-f]{40}\b", evidence)
        self.assertTrue(shas, f"告警 MUST 含被弃提交完整 SHA: {evidence}")
        # 告警 SHA 与被弃提交真实一致（分支已删，以链终局 rollup 对账）
        self.assertEqual(prog.get("chain_rollup", {}).get("marker_discarded"),
                         shas[:1], f"rollup 弃件注记缺失: {prog.get('chain_rollup')}")
        # 留痕先于清理（D3）：cleanup 执行时刻告警已在盘
        self.assertTrue(wm.alert_present_at_cleanup,
                        "弃件留痕 MUST 先于 _safe_cleanup")
        # 拒合回按失败清理
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), False)])
        # warning 文案附 commit id
        warns = cap.by_level("warning")
        self.assertTrue(any("弃件" in w and shas[0][:12] in w for w in warns),
                        warns)
        # 批级注记「产物已弃」入进度快照为瞬态（链收敛写点覆写），持久对账
        # 面已由上方 rollup marker_discarded + 告警 + warning 日志覆盖。

    def test_mixed_batch_all_ignored_still_traced(self):
        """全批 ignored + 混合批：完成收尾分支同样留痕，不再静默丢弃。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a",))
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {
                "src/app.ts": BASE_TS + "<!-- [fenix-ignore:aaaa1111bbbb] 误报 -->\n",
                "src/core.py": "changed_real_code = 1\n",
            },
            "rows": [
                {"item_id": "a", "status": "skipped",
                 "skip_reason": "false_positive", "file": "src/app.ts"},
            ],
        }])
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        # 不合回（混合批），但完成收尾（全批 ignored）
        core_p = proot / "src" / "core.py"
        self.assertTrue(
            not core_p.exists()
            or "changed_real_code" not in core_p.read_text(encoding="utf-8"))
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), True)])
        # 弃件留痕在盘、先于清理
        alerts = _discard_alerts(proot)
        self.assertEqual(len(alerts), 1, f"混合批残余产物 MUST 留痕: {alerts}")
        self.assertTrue(wm.alert_present_at_cleanup)
        import re as _re
        shas = _re.findall(r"\b[0-9a-f]{40}\b", alerts[0].get("evidence") or "")
        self.assertTrue(shas)
        self.assertIn("src/core.py", alerts[0].get("evidence"))
        self.assertEqual(
            _read_progress(proot).get("chain_rollup", {}).get("marker_discarded"),
            shas[:1])


class TestAllIgnoredMarkerOnly(unittest.TestCase):
    """场景组三（task 2.3）：全批 ignored + 纯标记提交先合回再收尾。"""

    def test_all_ignored_marker_only_merged_not_dropped(self):
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a",))
        marker = "# [fenix-ignore:aaaa1111bbbb] 不值得修：纯风格"
        # 既有文件上插入标记行（问题行上一行，写侧契约形态；非整文件替换）
        py_new = BASE_PY.replace(
            "def f():\n", f"def f():\n{marker}\n"
        )
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {"src/util.py": py_new},
            "rows": [
                {"item_id": "a", "status": "skipped",
                 "skip_reason": "false_positive", "file": "src/util.py"},
            ],
        }])
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        # 先合回再收尾：标记进主树（success 终态不丢产物）
        self.assertIn(marker, (proot / "src" / "util.py").read_text(encoding="utf-8"))
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), True)])
        # 完成（非失败）收尾 + 注记；无 pending 条目不进 chain_skipped
        prog = _read_progress(proot)
        self.assertTrue(
            any("产物已合并（纯标记）" in m and "纯标记提交合回成功" in m
                for _, m in cap.lines), cap.lines)
        self.assertEqual(_discard_alerts(proot), [])
        rollup = prog.get("chain_rollup") or {}
        self.assertEqual(rollup.get("marker_merged"), 1)
        self.assertEqual(rollup.get("marker_discarded") or [], [])


class TestZeroBehaviorRegression(unittest.TestCase):
    """场景组四（task 2.4）：fixed>0 / commits=0 / salvage 三路径行为不变。"""

    def test_fixed_batch_unchanged(self):
        """fixed>0 批：合回核销路径零变化（纯标记通道不介入）。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a",))
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {"src/fix.py": "def fixed():\n    return 42\n"},
            "rows": [
                {"item_id": "a", "status": "fixed", "file": "src/fix.py"},
            ],
        }])
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        self.assertIn("def fixed",
                      (proot / "src" / "fix.py").read_text(encoding="utf-8"))
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), True)])
        prog = _read_progress(proot)
        rollup = prog.get("chain_rollup") or {}
        self.assertEqual(rollup.get("marker_merged"), 0)
        self.assertEqual(rollup.get("marker_discarded") or [], [])
        self.assertEqual(_discard_alerts(proot), [])
        self.assertFalse(any("产物已合并（纯标记）" in m for _, m in cap.lines))

    def test_zero_commit_batch_unchanged(self):
        """commits=0 零产物批：拒合回语义零变化、不发弃件告警（10-16 形态）。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a", "b"))
        # 无文件改动、无提交（commit=False）；a 误报（no_marker 合法形态）、
        # b needs_human → pending 非空零产物拒合回
        runner = _MarkerRunner(proot, commit=True, skip_reasons=(
            "false_positive", "needs_human"))
        runner.plan = [{"items": ["a", "b"], "files": {}}]
        # 文件为空但 commit=True 会产生空提交——改为不提交且无改动
        runner.commit = False
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(items["b"]["status"], "open")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), False)])
        prog = _read_progress(proot)
        self.assertIn("b", prog.get("chain_skipped") or [])
        # 零产物批无被弃产物：不告警、rollup 无弃件注记
        self.assertEqual(_discard_alerts(proot), [])
        rollup = prog.get("chain_rollup") or {}
        self.assertEqual(rollup.get("marker_discarded") or [], [])
        self.assertEqual(rollup.get("marker_merged"), 0)

    def test_salvage_path_unchanged(self):
        """可修复形态 salvage：声明 fixed+零提交+工作区脏 → 兜底提交后照常合回。"""
        from core.code_review import read_items

        proot = _make_marker_root()
        _setup(proot, ("a",))
        runner = _MarkerRunner(proot, plan=[{
            "items": ["a"],
            "files": {"src/fix.py": "def fixed():\n    return 42\n"},
            "rows": [
                {"item_id": "a", "status": "fixed", "file": "src/fix.py"},
            ],
        }])
        runner.commit = False  # fixer 忘提交 → 搁浅形态
        wm = _MarkerWM(proot)
        runner.worktree_manager = wm
        cap = _CapLogger()
        _orch(proot, runner, cap).checkpoint()

        self.assertTrue(any("salvage 兜底提交" in m for _, m in cap.lines),
                        cap.lines)
        self.assertIn("def fixed",
                      (proot / "src" / "fix.py").read_text(encoding="utf-8"))
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(wm.cleanup_calls, [(str(wm.base_dir / "wt-1"), True)])
        self.assertEqual(_discard_alerts(proot), [])
        self.assertEqual(
            (_read_progress(proot).get("chain_rollup") or {}).get("marker_merged"),
            0)


if __name__ == "__main__":
    unittest.main()
