"""add-deliverable-declaration-triage PR1：晋升 lint 存在性校验回归测试。

覆盖（spec.md「晋升 lint 存在性校验」四个 Scenario + fail-open）：
1. modify 路径不存在被拦（违规消息含路径与「必须存在」语义）
2. new 路径唯一 basename 命中判疑似笔误（消息给出疑似目标路径）
3. 多命中与零命中放行（不拦截，矛盾交由派发处方与守卫终审层兜底）
4. reference 路径不存在被拦（reference 语义即既有引用）
5. lint 自身故障 fail-open + basename 工具排除清单与确定性排序

PR2（spec.md「派发前声明现实处方注入」三个 Scenario）：
6. 疑似笔误候选随任务书注入（提示词含候选与 deliverable-dispute 登记约定）
7. 无声明段不注入（prompt 与现状逐字节一致）
8. 干跑异常不阻塞派发（快照为 None，派发照常）

PR3（judge run 范式）：
9. dispute-judge agent 类型注册解析 + run 文件前缀归属

PR4（spec.md「守卫缺件 LLM 终审」「裁决机械执行与审计留痕」）：
10. 缺件触发终审而非立即打回（终审期间 spec blocked + run_id 注明）
11. judge 失败/JSON 不合法等价 unclear（转人工）
12. typo 裁决自动修正声明并放行（审计落 diff）
13. reference 裁决软化校验
14. unclear 裁决转人工
15. 防洗白：actual_path 也缺失仍打回
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunResult, AgentRunner
from core.deliverables import (
    _BASENAME_EXCLUDE_DIRS,
    extract_declared,
    extract_declared_entries,
    lint_declared,
    match_basename_in_tree,
    replace_declared_path,
    soften_declared_kind,
)
from core.pm_engine import PMEngine
from core.state_machine import StateMachine


def _mk_tasks_md(spec_dir: Path, yaml_block: str) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n",
        encoding="utf-8",
    )


class _LintFixture(unittest.TestCase):
    """lint_declared 纯函数夹具：临时主树 + 临时 spec 目录。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tree(self, rel_path: str, content: str = "x") -> Path:
        p = self.pr / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


class TestLintModifyReferenceExistence(_LintFixture):
    """规则 3：modify/reference 路径在主树必须存在。"""

    def test_modify_missing_blocked(self):
        """spec.md Scenario「modify 路径不存在被拦」。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: modify\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/verification.py", violations[0])
        self.assertIn("必须存在", violations[0])

    def test_reference_missing_blocked(self):
        """spec.md Scenario「reference 路径不存在被拦」。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: third-party/manifest.json\n  kind: reference\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("third-party/manifest.json", violations[0])
        self.assertIn("必须存在", violations[0])

    def test_modify_reference_existing_pass(self):
        """modify/reference 指向既有文件 → 放行。"""
        self.write_tree("core/data.py")
        self.write_tree("third-party/manifest.json")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: third-party/manifest.json\n  kind: reference\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_mixed_entries_only_missing_reported(self):
        """多条目混合：仅缺者被报，存在者不误报。"""
        self.write_tree("core/true.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/true.py\n  kind: modify\n"
                     "- path: core/ghost.py\n  kind: modify\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/ghost.py", violations[0])
        self.assertNotIn("core/true.py", violations[0])


class TestLintNewBasenameTriage(_LintFixture):
    """规则 4：new 路径唯一 basename 命中判疑似笔误；零/多命中放行。"""

    def test_new_unique_basename_hit_blocked(self):
        """spec.md Scenario「new 路径唯一 basename 命中判疑似笔误」。"""
        self.write_tree("core/pm_engine/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("core/verification.py", violations[0])
        self.assertIn("疑似笔误", violations[0])
        self.assertIn("core/pm_engine/verification.py", violations[0])

    def test_new_zero_hit_pass(self):
        """零命中：无同名 basename 文件 → 放行（交由后续层兜底）。"""
        self.write_tree("core/pm_engine/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/brand_new_module.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_new_multiple_hits_pass(self):
        """多命中：basename 在仓库命中多个文件 → 放行（语义矛盾交 LLM 层）。"""
        self.write_tree("core/a/verification.py")
        self.write_tree("core/b/verification.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/verification.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_new_existing_path_pass(self):
        """new 路径在主树已存在（与规则 3 同检）→ 不拦（design Non-Goal）。"""
        self.write_tree("core/new_mod.py")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/new_mod.py\n  kind: new\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])


class TestLintFailOpen(_LintFixture):
    """fail-open 保持：lint 自身故障放行，无声明段行为不变。"""

    def test_unreadable_tasks_md_fails_open(self):
        """tasks.md 为目录（read_text 抛 OSError）→ 放行晋升。"""
        tasks = self.spec_dir / "tasks.md"
        tasks.mkdir(parents=True, exist_ok=True)
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_no_deliverables_section_passes(self):
        """无声明段（存量 spec）→ 不拦（start is None 早退路径未触碰）。"""
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_missing_tasks_md_passes(self):
        self.assertEqual(
            lint_declared(self.pr / "spec/changes/ghost", self.pr), [])


class TestMatchBasenameInTree(_LintFixture):
    """1.1 工具函数：basename 精确匹配 + 排除清单 + 确定性排序。"""

    def test_basename_exact_match(self):
        self.write_tree("core/pm_engine/verification.py")
        self.write_tree("tests/test_verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits, ["core/pm_engine/verification.py"])

    def test_exclude_dirs_skipped(self):
        """排除清单目录（.git/node_modules/dist/.fenix/__pycache__）不参与命中。"""
        for d in _BASENAME_EXCLUDE_DIRS:
            self.write_tree(f"{d}/verification.py")
        self.write_tree("core/pm_engine/verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits, ["core/pm_engine/verification.py"])

    def test_multiple_hits_deterministic_order(self):
        self.write_tree("core/z/verification.py")
        self.write_tree("core/a/verification.py")
        hits = match_basename_in_tree(self.pr, "core/verification.py")
        self.assertEqual(hits,
                         ["core/a/verification.py", "core/z/verification.py"])

    def test_empty_path_no_hit(self):
        self.assertEqual(match_basename_in_tree(self.pr, ""), [])

    def test_nonexistent_root_returns_empty(self):
        self.assertEqual(
            match_basename_in_tree("/nonexistent_xyz_123", "verification.py"),
            [])


class _FakeLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


# ── PR2 派发前声明现实处方注入 ─────────────────────────────────────────────

class TestDeclaredRealityInjection(unittest.TestCase):
    """prompt_builder 声明现实快照注入：候选注入/无声明段跳过/干跑异常放行。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = _FakeLogger()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.wm = mock.MagicMock()
        self.wm.get_legacy.return_value = None  # 无遗产：legacy 段零注入
        self.runner = AgentRunner.__new__(AgentRunner)
        self.runner.logger = self.logger
        self.runner.state_machine = self.sm
        self.runner.project_root = self.project_root
        self.runner.worktree_manager = self.wm

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec(self, name, tasks_text):
        spec_dir = self.project_root / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir

    def write_tree(self, rel_path: str, content: str = "x") -> Path:
        p = self.project_root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def build_prompt(self, spec_name="s1") -> str:
        return self.runner._prompt_builder._build_prompt(spec_name, "implementer")

    def test_suspected_typo_candidate_injected(self):
        """spec.md Scenario「疑似笔误候选随任务书注入」。"""
        self.write_tree("core/pm_engine/verification.py")
        self.write_spec("s1",
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/verification.py\n  kind: new\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 新建 `core/verification.py`\n")
        prompt = self.build_prompt()
        self.assertIn("声明清单 × 仓库现实", prompt)
        self.assertIn("core/verification.py", prompt)
        self.assertIn("core/pm_engine/verification.py", prompt)
        self.assertIn("deliverable-dispute", prompt)
        self.assertIn("不得静默改变交付落点", prompt)

    def test_existing_modify_marked_as_target(self):
        """存在的 modify 路径标注为修改目标（快照存在性=true）。"""
        self.write_tree("core/data.py")
        self.write_spec("s1",
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 扩展 `core/data.py`\n")
        prompt = self.build_prompt()
        self.assertIn("声明清单 × 仓库现实", prompt)
        self.assertIn("core/data.py", prompt)
        self.assertIn("主树存在", prompt)
        self.assertNotIn("疑似声明笔误", prompt)

    def test_no_declared_section_no_injection(self):
        """spec.md Scenario「无声明段不注入」：prompt 与现状逐字节一致。"""
        self.write_spec("s1", "# Tasks\n\n- [ ] 1.1 写 `core/foo.py`\n")
        prompt = self.build_prompt()
        # 注入段的独有标题/文案不得出现（模板自带 deliverable-dispute 约定不计）
        self.assertNotIn("声明清单 × 仓库现实", prompt)
        self.assertNotIn("疑似声明笔误", prompt)
        self.assertNotIn("不得静默改变交付落点", prompt)

    def test_dry_run_exception_does_not_block_dispatch(self):
        """spec.md Scenario「干跑异常不阻塞派发」：spec 目录缺失 → 快照 None。"""
        # ghost spec 目录不存在：_build_prompt 不抛、无注入，派发照常
        prompt = self.runner._prompt_builder._build_prompt("ghost", "implementer")
        self.assertNotIn("声明清单 × 仓库现实", prompt)

    def test_snapshot_read_failure_returns_none(self):
        """spec 目录读取失败（tasks.md 为目录）→ 快照 None，注入跳过。"""
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        (spec_dir / "tasks.md").mkdir(parents=True, exist_ok=True)
        self.assertIsNone(
            self.runner._prompt_builder._declared_reality_snapshot("s1"))
        prompt = self.build_prompt()
        self.assertNotIn("声明清单 × 仓库现实", prompt)


# ── extract_declared_entries（处方快照条目级解析） ─────────────────────────

class TestExtractDeclaredEntries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.spec_dir = self.tmpdir / "spec"
        self.spec_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tasks(self, text):
        (self.spec_dir / "tasks.md").write_text(text, encoding="utf-8")

    def test_entries_preserve_kind_per_item(self):
        """条目级 path+kind 保序返回；reference 条目不丢失。"""
        self.write_tasks(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n"
            "- path: core/new_mod.py\n  kind: new\n"
            "- path: .fenix/config.yaml\n  kind: reference\n```\n"
        )
        entries = extract_declared_entries(self.spec_dir)
        self.assertEqual(entries, [
            {"path": "core/data.py", "kind": "modify"},
            {"path": "core/new_mod.py", "kind": "new"},
            {"path": ".fenix/config.yaml", "kind": "reference"},
        ])

    def test_extract_declared_consistent_with_entries(self):
        """extract_declared 归类与 entries 解析一致（复用同源）。"""
        self.write_tasks(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: core/data.py\n  kind: modify\n"
            "- path: .fenix/config.yaml\n  kind: reference\n```\n"
        )
        entries = extract_declared_entries(self.spec_dir)
        typed = extract_declared(self.spec_dir)
        self.assertEqual(
            [e["path"] for e in entries if e["kind"] in ("new", "modify")],
            typed["deliverables"])
        self.assertEqual(
            [e["path"] for e in entries if e["kind"] == "reference"],
            typed["references"])

    def test_absent_section_returns_none(self):
        self.write_tasks("# Tasks\n\n- [ ] 1.1 写 `core/foo.py`\n")
        self.assertIsNone(extract_declared_entries(self.spec_dir))


# ── PR3 judge run 范式：agent 注册 + 前缀归属 ───────────────────────────────

class TestDisputeJudgeRegistration(unittest.TestCase):
    """dispute-judge agent 类型注册解析（3.2）：白名单 + 提示词加载 + 占位符。"""

    def setUp(self):
        from test_agent_runner import make_runner
        self.tmpdir = Path(tempfile.mkdtemp())
        self.proot = self.tmpdir / "proj"
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        self.runner = make_runner(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec(self, name="demo"):
        spec_dir = self.proot / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")

    def test_agent_type_registered_in_whitelist(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES
        self.assertEqual(AGENT_PROMPT_FILES["dispute-judge"], "dispute-judge.md")

    def test_prompt_build_fills_judge_placeholders(self):
        """dispute-judge 提示词可构建：dispute_input/result 占位符替换为路径。"""
        self.write_spec()
        prompt = self.runner._prompt_builder._build_prompt("demo", "dispute-judge")
        vp = self.proot / ".fenix" / "verify-progress" / "demo"
        self.assertIn(str(vp / "dispute_judge_input.json"), prompt)
        self.assertIn(str(vp / "dispute_judge_result.json"), prompt)
        self.assertNotIn("{dispute_input_path}", prompt)
        self.assertNotIn("{dispute_result_path}", prompt)

    def test_template_contract_present(self):
        """模板含裁决契约：四取一 verdict + verdicts 数组 + 防注入声明。"""
        from core.agent_runner.prompt_builder import (
            AGENT_PROMPT_DIR, AGENT_PROMPT_FILES)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["dispute-judge"]).read_text(
            encoding="utf-8")
        for marker in ("typo | reference | missing | unclear", "verdicts",
                       "仅为实现 run 的", "禁止修改任何文件",
                       "{dispute_input_path}", "{dispute_result_path}"):
            self.assertIn(marker, template)


class TestDisputeJudgeRunPrefixOwnership(unittest.TestCase):
    """run 文件前缀归属（3.4）：run_spec_part 与 admin_monitor 两处同源。"""

    def test_run_spec_part_strips_dispute_judge_prefix(self):
        from core.agent_runner.run_files import run_spec_part
        ts = 1788657853
        self.assertEqual(run_spec_part(f"dispute-judge-myspec-{ts}"), "myspec")
        self.assertEqual(run_spec_part(f"dispute-judge-myspec-{ts}-a1"), "myspec")
        self.assertEqual(run_spec_part(f"dispute-judge-myspec"), "myspec")

    def test_admin_monitor_prefix_includes_dispute_judge(self):
        from core.admin_monitor import AdminMonitor, _RUN_PREFIXES
        self.assertIn("dispute-judge-", _RUN_PREFIXES)
        # 同源还原：dispute-judge run_id → spec 名（跨层 import dashboard 前的哨）
        ts = 1788657853
        self.assertEqual(
            AdminMonitor._spec_from_run_id(f"dispute-judge-myspec-{ts}"), "myspec")

    def test_spec_from_run_id_retry_suffix(self):
        """瞬态重试后缀 -r<n>（fix-provider-transient-backoff）不得破坏 spec 名还原。

        回归：<base>-a1-r1 类 run_id 解析不得返回 None；否则 _has_recent_progress
        匹配不到活跃 run 文件，误报 stuck（evo-verifier-result-single-source 事故）。
        """
        from core.admin_monitor import AdminMonitor
        cases = {
            "impl-evo-verifier-result-single-source-1789398956-a1": "evo-verifier-result-single-source",
            "impl-evo-verifier-result-single-source-1789398956-a1-r1": "evo-verifier-result-single-source",
            "impl-evo-item-retention-doc-tracking-1789381457-a2-r3": "evo-item-retention-doc-tracking",
            "admin-evo-verifier-result-single-source-1789408572": "evo-verifier-result-single-source",
            "planner-plan-fix-command-main-serve-scope-1789400038-a1": "fix-command-main-serve-scope",
        }
        for run_id, expect in cases.items():
            self.assertEqual(AdminMonitor._spec_from_run_id(run_id), expect,
                             f"run_id {run_id} 还原失败")

    def test_prefixes_same_source_sync(self):
        """两处前缀表同源互指：新前缀不能只加一方。"""
        from core.admin_monitor import _RUN_PREFIXES
        from core.agent_runner.run_files import run_spec_part
        ts = 1788657853
        for prefix in _RUN_PREFIXES:
            if not prefix.endswith("-"):
                continue
            sample = f"{prefix}myspec-{ts}"
            self.assertEqual(run_spec_part(sample), "myspec",
                             f"前缀 {prefix} 未同步到 run_files.run_spec_part")


# ── PR4 守卫 LLM 终审与裁决机械执行 ────────────────────────────────────────

class TestReplaceDeclaredPath(unittest.TestCase):
    """声明段确定性文本操作：typo path 修正（含同名去重）+ reference 软化。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.spec_dir = Path(self.tmpdir) / "spec"
        self.spec_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_tasks(self, yaml_block):
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "\n```\n\n## 1. 分组\n\n- [ ] 1.1 do it\n",
            encoding="utf-8",
        )

    def test_replace_path_in_declared_entry(self):
        self.write_tasks("- path: core/verification.py\n  kind: new\n")
        diff = replace_declared_path(self.spec_dir, "core/verification.py",
                                     "core/pm_engine/verification.py")
        self.assertIn("core/verification.py", diff["before"])
        self.assertIn("core/pm_engine/verification.py", diff["after"])
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertNotIn("core/verification.py", text)
        self.assertIn("- path: core/pm_engine/verification.py", text)

    def test_replace_dedup_when_actual_path_declared(self):
        """同名 actual_path 条目已存在 → 删除 element 条目（去重）。"""
        self.write_tasks(
            "- path: core/verification.py\n  kind: new\n"
            "- path: core/pm_engine/verification.py\n  kind: new\n")
        replace_declared_path(self.spec_dir, "core/verification.py",
                              "core/pm_engine/verification.py")
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertEqual(text.count("core/pm_engine/verification.py"), 1)
        self.assertNotIn("core/verification.py", text)

    def test_replace_missing_entry_raises(self):
        self.write_tasks("- path: core/data.py\n  kind: new\n")
        with self.assertRaises(ValueError):
            replace_declared_path(self.spec_dir, "core/ghost.py", "core/x.py")

    def test_soften_kind_to_reference(self):
        self.write_tasks("- path: .fenix/config.yaml\n  kind: new\n")
        diff = soften_declared_kind(self.spec_dir, ".fenix/config.yaml")
        self.assertIn("kind: new", diff["before"])
        self.assertIn("kind: reference", diff["after"])
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: reference", text)
        self.assertNotIn("kind: new", text)

    def test_soften_missing_entry_raises(self):
        self.write_tasks("- path: core/data.py\n  kind: new\n")
        with self.assertRaises(ValueError):
            soften_declared_kind(self.spec_dir, "core/ghost.py")


class TestDisputeAuditStore(unittest.TestCase):
    """dispute 审计流（4.5）：独立 jsonl、裁决 JSON 全文、diff、run id、时间戳。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / ".fenix").mkdir(exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_append_and_read_roundtrip(self):
        from core.admin_store import DisputeAuditStore
        store = DisputeAuditStore(self.tmpdir, None)
        store.append({
            "spec": "s1",
            "trigger_run_id": "impl-s1-123-a1",
            "judge_run_id": "dispute-judge-s1-456",
            "verdicts": [{"element": "core/verification.py", "verdict": "typo"}],
            "diff": {"core/verification.py": {"before": "- path: x", "after": "- path: y"}},
        })
        store.append({"spec": "s2", "verdicts": []})
        records = store.read_all()
        self.assertEqual(len(records), 2)
        rec = records[-1]  # 顺序：最新的在前，s1 先写 → 数组尾
        self.assertEqual(rec["kind"], "dispute-audit")
        self.assertEqual(rec["trigger_run_id"], "impl-s1-123-a1")
        self.assertEqual(rec["verdicts"][0]["verdict"], "typo")
        self.assertIn("created", rec)
        # 时间戳为 UTC ISO 格式（datetime.now(timezone.utc) 以 +00:00 结尾）
        self.assertTrue(rec["created"].endswith("+00:00")
                        or rec["created"].endswith("Z"))

    def test_corrupt_lines_skipped(self):
        from core.admin_store import DisputeAuditStore
        store = DisputeAuditStore(self.tmpdir, None)
        store.audit_path.write_text("{broken json\n"
                                    + '{"spec": "s1"}\n', encoding="utf-8")
        records = store.read_all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["spec"], "s1")


class _AdjudicationFixture(unittest.TestCase):
    """真实 StateMachine + mock runner，驱动 _adjudicate_deliverable_missing。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.project_root = self.tmpdir
        (self.project_root / ".fenix").mkdir(exist_ok=True)
        self.logger = _FakeLogger()
        self.sm = StateMachine(self.project_root / ".fenix" / "STATE.md",
                               self.logger)
        self.runner = mock.MagicMock()
        self.runner.worktree_manager = mock.MagicMock()
        self.config = {}
        self.engine = PMEngine(self.sm, self.runner, self.config,
                               self.project_root, self.logger)
        self.wm = self.runner.worktree_manager
        # 守卫存在性检查默认缺失（MagicMock 真值会假放行缺件）
        self.wm.file_exists_on_branch.return_value = False
        self.sm.add_spec("s1", {"priority": 5})
        self.sm.transition("s1", "ready")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def write_spec_dir(self, tasks_text):
        spec_dir = self.project_root / "spec" / "changes" / "s1"
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / "tasks.md").write_text(tasks_text, encoding="utf-8")
        return spec_dir

    def make_result(self, branch="fenix/s1", run_id="impl-s1-1-a1"):
        return AgentRunResult(run_id, "s1", "implementer",
                              success=True, duration_seconds=1.0, branch=branch)

    def write_judge_result(self, verdicts, status="success"):
        vp = self.project_root / ".fenix" / "verify-progress" / "s1"
        vp.mkdir(parents=True, exist_ok=True)
        (vp / "dispute_judge_result.json").write_text(
            json.dumps({"status": status, "verdicts": verdicts},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def stub_judge_run(self, judge_result=None, state_assert=None):
        """mock run_dispute_judge；state_assert 在 run 执行时刻校验 spec 状态。"""

        def fake_run(spec_name, judge_input, run_id=None):
            if state_assert:
                state_assert(spec_name, judge_input, run_id)
            if judge_result is None:
                return AgentRunResult(run_id or "dispute-judge-s1-1", "s1",
                                      "dispute-judge", success=True,
                                      duration_seconds=1.0)
            return judge_result

        self.runner.run_dispute_judge = fake_run


_DECL_TASKS = (
    "# Tasks\n\n## Deliverables\n\n```yaml\n"
    "- path: core/verification.py\n  kind: new\n```\n"
    "## 1. 分组\n\n- [ ] 1.1 新建 `core/verification.py`\n"
)


class TestAdjudicateTerminalReview(_AdjudicationFixture):
    """终审四 Scenario（spec.md「守卫缺件 LLM 终审」）。"""

    def test_missing_triggers_judge_and_blocks_until_result(self):
        """Scenario「缺件触发终审而非立即打回」：run 执行时刻 spec 已 blocked
        且 error 含 judge run id（阻断重派竞态）；输入含缺件路径。"""
        self.write_spec_dir(_DECL_TASKS)
        seen_state = {}

        def assert_during_run(spec_name, judge_input, run_id):
            entry = self.sm.read_one(spec_name)
            seen_state["status"] = entry["status"]
            seen_state["error"] = entry["error"]
            seen_state["run_id"] = run_id
            # 输入含缺件路径与 basename 候选
            self.assertEqual(
                [m["path"] for m in judge_input["missing"]],
                ["core/verification.py"])
            self.assertEqual(
                judge_input["missing"][0]["candidates"],
                ["core/pm_engine/verification.py"])
            self.assertIn("spec_context", judge_input)

        self.write_judge_result([
            {"element": "core/verification.py", "verdict": "typo",
             "actual_path": "core/pm_engine/verification.py",
             "reasoning": "basename 唯一命中", "confidence": "high"},
        ])
        self.stub_judge_run(state_assert=assert_during_run)
        # 主树有唯一 basename 候选；修正后守卫重跑时 actual_path 存在
        (self.project_root / "core" / "pm_engine").mkdir(parents=True,
                                                         exist_ok=True)
        (self.project_root / "core" / "pm_engine" / "verification.py"
         ).write_text("x", encoding="utf-8")
        self.wm.file_exists_on_branch.side_effect = (
            lambda branch, path: path == "core/pm_engine/verification.py")

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), {"findings": []},
            ["core/verification.py"])

        self.assertEqual(outcome["action"], "proceed")
        self.assertEqual(seen_state["status"], "blocked")
        self.assertIn("LLM 终审进行中", seen_state["error"])
        self.assertIn(seen_state["run_id"], seen_state["error"])
        # 不立即打回：未重派 implementer
        self.assertEqual(self.engine._dispatcher._run_queue, [])

    def test_judge_failure_or_invalid_json_equiv_unclear(self):
        """Scenario「judge 失败等价 unclear」：run 失败 / 结果 status 非 success
        （无合法 verdicts）→ 全部等价 unclear，转人工（失败形态参数化）。"""
        cases = {
            "run-failed": None,
            "result-not-success": "write-error-result",
        }
        for mode, marker in cases.items():
            with self.subTest(mode=mode):
                self.write_spec_dir(_DECL_TASKS)
                if marker is None:
                    # 形态 1：judge run 本身失败（无合法结果落盘）
                    self.stub_judge_run(judge_result=AgentRunResult(
                        "dispute-judge-s1-1", "s1", "dispute-judge",
                        success=False, duration_seconds=1.0, error="boom"))
                else:
                    # 形态 2：run 成功但结果 JSON status 非 success
                    self.write_judge_result([], status="error")
                    self.stub_judge_run()

                outcome = self.engine._adjudicate_deliverable_missing(
                    "s1", self.make_result(), None, ["core/verification.py"])

                self.assertEqual(outcome["action"], "handled")
                entry = self.sm.read_one("s1")
                self.assertEqual(entry["status"], "blocked")
                self.assertIn("待人工裁决", entry["error"])

    def test_unclear_verdict_blocks_human(self):
        """Scenario「unclear 裁决转人工」：spec 保持 blocked，error 用人工裁决话术。"""
        self.write_spec_dir(_DECL_TASKS)
        self.write_judge_result([
            {"element": "core/verification.py", "verdict": "unclear",
             "actual_path": None, "reasoning": "多候选取舍不下",
             "confidence": "low"},
        ])
        self.stub_judge_run()

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), None, ["core/verification.py"])

        self.assertEqual(outcome["action"], "handled")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "blocked")
        self.assertIn("unclear", entry["error"])
        self.assertIn("待人工裁决", entry["error"])
        # 不自动重派
        self.assertEqual(self.engine._dispatcher._run_queue, [])


class TestAdjudicateMechanicalExecution(_AdjudicationFixture):
    """裁决机械执行（spec.md「裁决机械执行与审计留痕」）。

    typo 归宿的声明修正与守卫重跑放行由 worker 全链路版覆盖
    （TestTriageChainSelfCheck.test_layer3_typo_fix_merges_after_guard_repass），
    此处不再重复直驱用例；「action == proceed」契约并入审计用例断言。
    """

    def test_reference_verdict_softens(self):
        """Scenario「reference 裁决软化校验」：kind → reference，转软校验放行。"""
        tasks = (
            "# Tasks\n\n## Deliverables\n\n```yaml\n"
            "- path: .fenix/config.yaml\n  kind: new\n```\n"
            "## 1. 分组\n\n- [ ] 1.1 写 `.fenix/config.yaml`\n"
        )
        self.write_spec_dir(tasks)
        self.write_judge_result([
            {"element": ".fenix/config.yaml", "verdict": "reference",
             "actual_path": None,
             "reasoning": "运行时写入目标（被管项目配置）", "confidence": "high"},
        ])
        self.stub_judge_run()
        # 软化后该路径转 references 软校验：即便分支不存在也不缺件
        self.wm.file_exists_on_branch.return_value = False

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), None, [".fenix/config.yaml"])

        self.assertEqual(outcome["action"], "proceed")
        tasks_text = (self.project_root / "spec" / "changes" / "s1"
                      / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: reference", tasks_text)

    def test_anti_whitewash_actual_path_missing(self):
        """防洗白：typo 裁决但 actual_path 在分支不存在 → 仍按缺件打回重派。"""
        self.write_spec_dir(_DECL_TASKS)
        self.write_judge_result([
            {"element": "core/verification.py", "verdict": "typo",
             "actual_path": "core/pm_engine/verification.py",
             "reasoning": "唯一 basename 命中", "confidence": "high"},
        ])
        self.stub_judge_run()
        # actual_path 在分支也不存在 → 修正声明 ≠ 放行缺件
        self.wm.file_exists_on_branch.return_value = False

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), None, ["core/verification.py"])

        self.assertEqual(outcome["action"], "handled")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")  # 打回重派
        self.assertIn("交付物守卫", entry["error"])
        self.assertIn("core/pm_engine/verification.py", entry["error"])
        self.assertEqual(self.engine._dispatcher._run_queue[-1][1:3],
                         ("s1", "implementer"))
        # 遗产注册（供后继 run 收编）
        self.wm.register_legacy.assert_called_once()

    def test_audit_written_on_typo_execution(self):
        """Scenario「审计可复核」：裁决 JSON 全文 + diff + run id 落审计流；
        并断言 typo 执行后 action=proceed、声明段已机械修正。"""
        from core.admin_store import DisputeAuditStore
        self.write_spec_dir(_DECL_TASKS)
        verdicts = [
            {"element": "core/verification.py", "verdict": "typo",
             "actual_path": "core/pm_engine/verification.py",
             "reasoning": "唯一 basename 命中", "confidence": "high"},
        ]
        self.write_judge_result(verdicts)
        self.stub_judge_run()
        (self.project_root / "core" / "pm_engine").mkdir(parents=True,
                                                         exist_ok=True)
        (self.project_root / "core" / "pm_engine" / "verification.py"
         ).write_text("x", encoding="utf-8")
        self.wm.file_exists_on_branch.side_effect = (
            lambda branch, path: path == "core/pm_engine/verification.py")

        outcome = self.engine._adjudicate_deliverable_missing(
            "s1", self.make_result(), None, ["core/verification.py"])

        # 修正 + 守卫重跑通过 → proceed（调用方继续 merge 推进）
        self.assertEqual(outcome["action"], "proceed")
        tasks_text = (self.project_root / "spec" / "changes" / "s1"
                      / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- path: core/pm_engine/verification.py", tasks_text)
        self.assertNotIn("- path: core/verification.py", tasks_text)

        records = DisputeAuditStore(self.project_root, None).read_all()
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["spec"], "s1")
        self.assertEqual(rec["trigger_run_id"], "impl-s1-1-a1")
        self.assertIn("dispute-judge-s1-", rec["judge_run_id"])
        self.assertEqual(rec["verdicts"], verdicts)
        diff = rec["diff"]["core/verification.py"]
        self.assertIn("core/verification.py", diff["before"])
        self.assertIn("core/pm_engine/verification.py", diff["after"])

    # missing 裁决的打回/重派归宿由 worker 全链路版覆盖：
    # TestTriageChainSelfCheck.test_layer3_missing_verdict_no_silent_merge
    # （status ready + 精准缺件清单 error + 重派 implementer + 不静默 merge）。


# ── PR5 行为自检：声明笔误 spec 三层干跑（tasks 5.2） ──────────────────────

class TestTriageChainSelfCheck(_AdjudicationFixture):
    """构造「声明笔误 spec」干跑 implementer 收工全链路，确认归宿无静默放行。

    三层中的前两层不再在此重复干跑（同夹具同断言，单点覆盖即可）：
      - 第一层：晋升 lint 拒唯一 basename 命中 → TestLintNewBasenameTriage；
      - 第二层：派发处方含候选与 dispute 登记约定 → TestDeclaredRealityInjection。
    本类聚焦第三层：构造缺件驱动 implementer worker 全链路终审——
      - missing 裁决 → 打回重派（不静默合并）；
      - typo 修正且 actual_path 存在 → 守卫重跑通过 → 正常合并推进。
    """

    TYPO_DECL = (
        "# Tasks\n\n## Deliverables\n\n```yaml\n"
        "- path: core/verification.py\n  kind: new\n```\n"
        "## 1. 分组\n\n- [ ] 1.1 新建 `core/verification.py`\n"
    )

    def _make_typo_main_tree(self):
        (self.project_root / "core" / "pm_engine").mkdir(parents=True,
                                                         exist_ok=True)
        (self.project_root / "core" / "pm_engine" / "verification.py"
         ).write_text("# engine\n", encoding="utf-8")

    def _drive_worker_chain(self, verdicts, status="success",
                            file_exists=None):
        """装配并驱动 implementer worker：成功收工 + 缺件 → 终审 → 裁决执行。"""
        from types import SimpleNamespace
        self.write_spec_dir(self.TYPO_DECL)
        self._make_typo_main_tree()
        self.runner.run_implementer.return_value = SimpleNamespace(
            success=True, run_id="impl-s1-1-a1", branch="fenix/s1",
            error=None, worktree_dirty=[], duration_seconds=1.0,
        )
        self.engine._read_implementer_result = mock.MagicMock(
            return_value={"status": "success", "findings": []})
        self.write_judge_result(verdicts, status=status)
        self.stub_judge_run()
        if file_exists is not None:
            self.wm.file_exists_on_branch.side_effect = file_exists
        # proceed 路径 merge 兼容（(bool, str) 解包）
        self.runner.worktree_manager.merge_back_from_branch.return_value = (True, "")
        # 吸收 worker finally 的重派派发（避免后台线程链式再跑）
        self.engine._process_queue = mock.MagicMock()
        self.engine._run_agent_worker("s1", "implementer", 5)

    def test_layer3_missing_verdict_no_silent_merge(self):
        """第三层·missing：缺件终审后打回重派，绝不静默合并推进。"""
        self._drive_worker_chain([
            {"element": "core/verification.py", "verdict": "missing",
             "actual_path": None, "reasoning": "实现未落地", "confidence": "high"},
        ])
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "ready")  # 打回重派而非 implemented
        self.assertIn("交付物守卫", entry["error"])
        # 打回 error 带精准缺件清单
        self.assertIn("core/verification.py", entry["error"])
        # merge 未被调用（未静默放行）
        self.runner.worktree_manager.merge_back_from_branch.assert_not_called()
        self.assertEqual(self.engine._dispatcher._run_queue[-1][1:3],
                         ("s1", "implementer"))

    def test_layer3_typo_fix_merges_after_guard_repass(self):
        """第三层·typo：修正声明 + 守卫重跑通过 → 正常合并推进（放行 merge）。"""
        self._drive_worker_chain([
            {"element": "core/verification.py", "verdict": "typo",
             "actual_path": "core/pm_engine/verification.py",
             "reasoning": "唯一 basename 命中", "confidence": "high"},
        ], file_exists=lambda branch, path: path == "core/pm_engine/verification.py")
        entry = self.sm.read_one("s1")
        self.assertEqual(entry["status"], "implemented")  # 守卫放行后正常合并
        self.runner.worktree_manager.merge_back_from_branch.assert_called_once()
        # 声明段已修正为实际路径
        tasks_text = (self.project_root / "spec" / "changes" / "s1"
                      / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("- path: core/pm_engine/verification.py", tasks_text)
        # verifier 已排队（merge 后既有推进路径）
        self.assertEqual(self.engine._dispatcher._run_queue[-1][1:3],
                         ("s1", "verifier"))


if __name__ == "__main__":
    unittest.main(verbosity=2)