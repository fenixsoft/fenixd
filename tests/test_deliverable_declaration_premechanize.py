"""add-declaration-premechanize PR1：不可交付模式分类器与软化编排回归测试。

覆盖（spec.md「晋升期机械软化」「lint 规则 6 仓库外路径」）：
1. _path_is_outside_root：~/ 展开越界、../ 越界、绝对路径越界判仓库外；
   仓库内相对/绝对路径不判；解析异常 fail-open 返回 False
2. classify_unsatisfiable：gitignored modify/new 命中；~ / ../ 仓库外命中；
   reference 恒 False；缺 path/kind False；非 git 目录 fail-open False
3. soften_unsatisfiable_declarations：
   - gitignored modify/new 条目软化 kind → reference
   - 仓库外 new/modify 条目软化
   - reference 条目不动、合法 new/modify 条目不动
   - 占位符/目录/疑似笔误 new 不命中软化（lint 照旧拒绝兜底）
   - 无声明段早退返回 []
   - 单条改写异常跳过该条记 warning 不中断，其余继续软化
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.deliverables import (
    _path_is_outside_root,
    classify_unsatisfiable,
    extract_declared_entries,
    lint_declared,
    soften_declared_kind,
    soften_unsatisfiable_declarations,
)
from core.pm_engine import PMEngine
from core.state_machine import StateMachine


def _git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def _mk_tasks_md(spec_dir: Path, yaml_block: str, with_header: bool = True) -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    text = ("# Tasks\n\n## Deliverables\n\n```yaml\n"
            + yaml_block + "\n```\n\n## 1. x\n\n- [ ] 1.1 do it\n")
    (spec_dir / "tasks.md").write_text(text, encoding="utf-8")


class PromotionTestMixin(unittest.TestCase):
    """StateMachine + PMEngine 基础夹具（PR2 晋升测试共用）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir) / "repo"
        self.pr.mkdir(parents=True, exist_ok=True)
        _git(self.pr, "init", "-q")
        _git(self.pr, "config", "user.email", "test@fenix.local")
        _git(self.pr, "config", "user.name", "Fenix Test")
        _git(self.pr, "config", "commit.gpgsign", "false")
        (self.pr / ".gitignore").write_text(
            "dist/\n.fenix/*\n!.fenix/keep.yaml\n", encoding="utf-8")
        (self.pr / ".fenix").mkdir(parents=True, exist_ok=True)
        from unittest.mock import MagicMock
        self.logger = MagicMock()
        self.sm = StateMachine(self.pr / ".fenix" / "STATE.md", self.logger)
        self.engine = PMEngine(self.sm, MagicMock(), {}, self.pr, self.logger)
        self.engine._on_spec_ready = MagicMock()
        self.spec_dir = self.pr / "spec" / "changes" / "demo"
        self.sm.add_spec("demo", {"priority": 5})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class _GitRepoFixture(unittest.TestCase):
    """临时 git 仓库夹具（gitignore 判定需要真实 git 仓库）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir) / "repo"
        self.pr.mkdir(parents=True, exist_ok=True)
        _git(self.pr, "init", "-q")
        _git(self.pr, "config", "user.email", "test@fenix.local")
        _git(self.pr, "config", "user.name", "Fenix Test")
        _git(self.pr, "config", "commit.gpgsign", "false")
        (self.pr / ".gitignore").write_text(
            "dist/\n.fenix/*\n!.fenix/keep.yaml\n", encoding="utf-8")
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        (self.pr / "core" / "modify_me.py").write_text("x", encoding="utf-8")
        (self.pr / "third-party").mkdir(parents=True, exist_ok=True)
        (self.pr / "third-party" / "manifest.json").write_text("x",
                                                               encoding="utf-8")
        _git(self.pr, "add", "-A")
        _git(self.pr, "commit", "-q", "-m", "base")
        self.spec_dir = self.pr / "spec" / "changes" / "demo"

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class TestPathIsOutsideRoot(unittest.TestCase):
    """_path_is_outside_root 纯函数判定。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pr = Path(self.tmpdir)
        self.root = self.pr / "repo"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_home_expansion_outside(self):
        # ~/x 展开到仓库外（本机家目录不在临时仓库内）
        self.assertTrue(_path_is_outside_root(self.root, ["~/x"]))

    def test_parent_escape_outside(self):
        self.assertTrue(_path_is_outside_root(self.root, ["../x"]))
        self.assertTrue(_path_is_outside_root(self.root, ["a/../../x"]))

    def test_absolute_outside(self):
        self.assertTrue(_path_is_outside_root(self.root, ["/etc/passwd"]))

    def test_inside_relative(self):
        self.assertFalse(_path_is_outside_root(self.root, ["core/foo.py"]))
        self.assertFalse(_path_is_outside_root(self.root, ["spec/x/y.md"]))

    def test_inside_absolute(self):
        self.assertFalse(_path_is_outside_root(self.root, [str(self.root)]))

    def test_fail_open_on_bad_path(self):
        # 解析异常（如空候选）fail-open 返回 False，不阻塞晋升
        self.assertFalse(_path_is_outside_root(self.root, []))


class TestClassifyUnsatisfiable(_GitRepoFixture):
    """classify_unsatisfiable：确定性不可交付模式识别。"""

    def test_gitignored_modify_true(self):
        entry = {"path": "core/dashboard/static/dist/index.html",
                 "kind": "modify"}
        self.assertTrue(classify_unsatisfiable(entry, self.pr))

    def test_gitignored_new_true(self):
        entry = {"path": "dist/index.html", "kind": "new"}
        self.assertTrue(classify_unsatisfiable(entry, self.pr))

    def test_outside_root_true(self):
        with mock.patch("core.deliverables._path_is_outside_root",
                        return_value=True):
            entry = {"path": "~/x.md", "kind": "new"}
            self.assertTrue(classify_unsatisfiable(entry, self.pr))

    def test_reference_always_false(self):
        # reference 是软化终点，恒不被分类为不可交付
        with mock.patch("core.deliverables._path_is_gitignored",
                        return_value=True):
            entry = {"path": "dist/index.html", "kind": "reference"}
            self.assertFalse(classify_unsatisfiable(entry, self.pr))

    def test_missing_fields_false(self):
        self.assertFalse(classify_unsatisfiable({}, self.pr))
        self.assertFalse(classify_unsatisfiable({"path": "x.py"}, self.pr))
        self.assertFalse(classify_unsatisfiable({"kind": "new"}, self.pr))

    def test_clean_declaration_false(self):
        entry = {"path": "core/data.py", "kind": "modify"}
        self.assertFalse(classify_unsatisfiable(entry, self.pr))
        entry = {"path": "core/new_thing.py", "kind": "new"}
        self.assertFalse(classify_unsatisfiable(entry, self.pr))


class TestSoftenUnsatisfiableDeclarations(_GitRepoFixture):
    """soften_unsatisfiable_declarations 编排。"""

    def read_tasks(self):
        return (self.spec_dir / "tasks.md").read_text(encoding="utf-8")

    def test_gitignored_modify_and_new_softened(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n"
                     "- path: .fenix/secret.json\n"
                     "  kind: new\n")
        softened = soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        self.assertEqual(
            softened,
            [
                {"element": "core/dashboard/static/dist/index.html",
                 "kind_before": "modify", "kind_after": "reference",
                 "reason": "gitignored"},
                {"element": ".fenix/secret.json",
                 "kind_before": "new", "kind_after": "reference",
                 "reason": "gitignored"},
            ],
        )
        text = self.read_tasks()
        self.assertIn("kind: reference", text)
        # 非 kind 行不受影响、tasks.md 其余内容保留
        self.assertIn("## 1. x", text)
        self.assertIn("- [ ] 1.1 do it", text)

    def test_outside_root_softened(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: ~/configs/app.yaml\n  kind: new\n"
                     "- path: core/data.py\n  kind: modify\n")
        softened = soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        self.assertEqual(
            softened,
            [{"element": "~/configs/app.yaml",
              "kind_before": "new", "kind_after": "reference",
              "reason": "outside-root"}],
        )
        text = self.read_tasks()
        # 只有 ~ 条目被软化，仓库内数据条目不动
        self.assertIn("- path: ~/configs/app.yaml\n  kind: reference", text)
        self.assertIn("- path: core/data.py\n  kind: modify", text)

    def test_reference_and_clean_untouched(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: dist/index.html\n  kind: reference\n"
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: core/new_thing.py\n  kind: new\n")
        softened = soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        self.assertEqual(softened, [])
        text = self.read_tasks()
        self.assertIn("dist/index.html\n  kind: reference", text)

    def test_placeholder_directory_false_soften_not_touched(self):
        # 占位符/目录/疑似笔误 new 属于规则 1/2/4 形态：不软化（lint 拒绝兜底）
        dist = self.pr / "core/dashboard/static/dist"
        (dist / "index.html").write_text("x", encoding="utf-8")
        # 主树有 verifcation.py（拼错），声明 src/verifcation.py（正确 basename
        # 但不存在的目录）→ 规则 4 basename 唯一命中判疑似笔误
        (self.pr / "verifcation.py").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/<spec_name>.py\n  kind: new\n"
                     "- path: core/dashboard/static/dist\n  kind: modify\n"
                     "- path: src/verifcation.py\n  kind: new\n")
        softened = soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        self.assertEqual(softened, [])
        text = self.read_tasks()
        # 无任何 kind: reference 注入（软化对这三条零命中）
        self.assertNotIn("kind: reference", text)
        # lint 照旧拒绝（规则 1 占位符 / 规则 2 目录 / 规则 4 疑似笔误各一）
        violations = lint_declared(self.spec_dir, self.pr)
        vjoint = "\n".join(violations)
        self.assertIn("占位符", vjoint)
        self.assertIn("目录", vjoint)
        self.assertIn("疑似笔误", vjoint)

    def test_no_declared_section_early_exit(self):
        # 无声明段（含 tasks.md 无 Deliverables 段）→ 早退返回 []
        self.spec_dir.mkdir(parents=True, exist_ok=True)
        (self.spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. x\n\n- [ ] 1.1 do it\n", encoding="utf-8")
        self.assertEqual(
            soften_unsatisfiable_declarations(self.spec_dir, self.pr), [])
        # 无 tasks.md 同样早退
        (self.spec_dir / "tasks.md").unlink()
        self.assertEqual(
            soften_unsatisfiable_declarations(self.spec_dir, self.pr), [])

    def test_single_entry_failure_skipped_continues(self):
        # 单条软化异常：跳过该条记 warning，其余条目继续软化
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n"
                     "- path: .fenix/secret.json\n"
                     "  kind: new\n")
        calls = {"n": 0}

        def flaky(spec_dir, element):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("concurrent rewrite")
            return soften_declared_kind(spec_dir, element)

        with mock.patch("core.deliverables.soften_declared_kind", flaky):
            softened = soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        # 只有失败的一条被跳过（dist 条目），.fenix 条目软化成功
        self.assertEqual(
            softened,
            [{"element": ".fenix/secret.json",
              "kind_before": "new", "kind_after": "reference",
              "reason": "gitignored"}],
        )
        text = self.read_tasks()
        self.assertIn("- path: .fenix/secret.json\n  kind: reference", text)
        # 被跳过条目 kind 保留 modify（交由 lint 兜底）
        self.assertIn("core/dashboard/static/dist/index.html\n  kind: modify",
                      text)
        # 被跳过条目仍命中 lint 规则 5（gitignored 拒绝兜底）
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertTrue(any("gitignore" in v for v in violations))


class TestSoftenedTasksRemainValidDeclarations(_GitRepoFixture):
    """软化后（content 保留、kind 变更）整份 tasks.md 仍可被守卫解析。"""

    def test_extract_declared_entries_after_soften(self):
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n")
        soften_unsatisfiable_declarations(self.spec_dir, self.pr)
        entries = extract_declared_entries(self.spec_dir)
        self.assertEqual(
            entries,
            [{"path": "core/dashboard/static/dist/index.html",
              "kind": "reference"}],
        )


class TestPromotionSoftening(PromotionTestMixin):
    """add-declaration-premechanize PR2：晋升前软化接线。

    覆盖 tasks 2.4：
    1. gitignored modify 声明 spec 晋升后状态 ready 且 tasks.md 已软化
    2. 审计含 promotion-soften
    3. 占位符 spec 照旧 drafted+error
    4. 软化编排异常降级 warning（不卡死晋升）
    """

    def test_gitignored_modify_softened_promotes(self):
        """gitignored modify 声明 → 晋升前软化 → tasks.md 变 reference → ready。"""
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n")
        self.engine._on_spec_drafted("demo")
        # 状态应晋升到 ready（非 drafted+error）
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        # tasks.md 已软化为 reference
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: reference", text)
        self.assertIn("core/dashboard/static/dist/index.html", text)

    def test_audit_contains_promotion_soften(self):
        """审计记录包含 promotion-soften reasoning。"""
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n")
        self.engine._on_spec_drafted("demo")
        # 检查审计文件
        audit_path = self.pr / ".fenix" / "dispute_audits.jsonl"
        self.assertTrue(audit_path.exists(), "dispute_audits.jsonl 应被创建")
        with open(audit_path, encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        # 应至少有一条记录
        self.assertTrue(len(lines) >= 1, "应有审计记录")
        import json
        rec = json.loads(lines[0])
        self.assertEqual(rec.get("kind"), "dispute-audit")
        self.assertEqual(rec.get("spec"), "demo")
        verdicts = rec.get("verdicts", [])
        self.assertTrue(len(verdicts) >= 1, "verdicts 应非空")
        v0 = verdicts[0]
        self.assertEqual(v0.get("verdict"), "reference")
        self.assertTrue(
            v0.get("reasoning", "").startswith("promotion-soften:"),
            f"reasoning 应以 promotion-soften: 开头，实际: {v0.get('reasoning')}",
        )

    def test_placeholder_declaration_blocks_promotion(self):
        """占位符声明（规则 1）不软化 → drafted+error。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: .fenix/admin_disposition-<run_id>.json\n"
                     "  kind: reference\n")
        self.engine._on_spec_drafted("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted")
        self.assertIn("占位符", entry.get("error", ""))

    def test_soften_exception_does_not_block_promotion(self):
        """软化编排异常 → 降级 warning → lint 照旧执行（fail-safe）。"""
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n")
        with mock.patch(
            "core.deliverables.soften_unsatisfiable_declarations",
            side_effect=RuntimeError("boom"),
        ):
            self.engine._on_spec_drafted("demo")
        # 即使软化异常，lint 仍会拒绝 gitignored 声明
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "drafted")
        self.assertIn("gitignore", entry.get("error", ""))

    def test_outside_root_softened_promotes(self):
        """仓库外路径声明 → 软化 → ready。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: ~/configs/app.yaml\n  kind: new\n")
        self.engine._on_spec_drafted("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("kind: reference", text)
        self.assertIn("~/configs/app.yaml", text)

    def test_mixed_clean_and_softenable_promotes(self):
        """混合：一条需软化、一条合法 → 软化后两条均合法 → ready。"""
        dist = self.pr / "core/dashboard/static/dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/dashboard/static/dist/index.html\n"
                     "  kind: modify\n"
                     "- path: core/data.py\n  kind: modify\n")
        self.engine._on_spec_drafted("demo")
        entry = self.sm.read_one("demo")
        self.assertEqual(entry["status"], "ready")
        text = (self.spec_dir / "tasks.md").read_text(encoding="utf-8")
        self.assertIn("core/dashboard/static/dist/index.html\n  kind: reference",
                      text)
        self.assertIn("core/data.py\n  kind: modify", text)


class TestLintRule6OutsideRoot(_GitRepoFixture):
    """add-declaration-premechanize PR3：lint 规则 6 仓库外路径。

    覆盖 tasks 3.3：
    1. ~/x new 与 ../y modify 违规且消息含处方文案
    2. 仓库外 reference 放行
    3. 规则 5 与规则 6 并列共存不互相遮蔽
    """

    def test_new_home_expansion_violation(self):
        """~/x new → 规则 6 违规，消息含路径与处方文案。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: ~/x.md\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        self.assertEqual(len(violations), 1)
        self.assertIn("仓库外", violations[0])
        self.assertIn("~/x.md", violations[0])
        self.assertIn("reference", violations[0])

    def test_modify_parent_escape_violation(self):
        """../y modify → 规则 6 违规（仓库外），规则 3 也报（modify 路径不存在）。
        两个违规并列，消息均含路径。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: ../outside.md\n  kind: modify\n")
        violations = lint_declared(self.spec_dir, self.pr)
        vjoint = "\n".join(violations)
        # 至少有规则 6（仓库外）
        self.assertTrue(any("仓库外" in v for v in violations))
        # 同时规则 3 也会报（modify 路径在主树不存在）
        self.assertTrue(any("在主树不存在" in v for v in violations))

    def test_outside_root_reference_passes(self):
        """仓库外 reference（~/.claude/settings.json）→ 放行。"""
        _mk_tasks_md(self.spec_dir,
                     "- path: ~/.claude/settings.json\n  kind: reference\n")
        self.assertEqual(lint_declared(self.spec_dir, self.pr), [])

    def test_rule5_and_rule6_coexist(self):
        """gitignored 与仓库外并列共存：各自报违规不互相遮蔽。

        dist/index.html 是 gitignored（规则 5）；~/x.md 是仓库外（规则 6）。
        """
        dist = self.pr / "dist"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "index.html").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: dist/index.html\n  kind: modify\n"
                     "- path: ~/x.md\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        vjoint = "\n".join(violations)
        self.assertIn("gitignore", vjoint)
        self.assertIn("仓库外", vjoint)

    def test_inside_root_relative_passes(self):
        """仓库内相对路径 new/modify → 规则 6 不拦。"""
        (self.pr / "core").mkdir(parents=True, exist_ok=True)
        (self.pr / "core" / "data.py").write_text("x", encoding="utf-8")
        _mk_tasks_md(self.spec_dir,
                     "- path: core/data.py\n  kind: modify\n"
                     "- path: core/new_thing.py\n  kind: new\n")
        violations = lint_declared(self.spec_dir, self.pr)
        # 仓库内路径不触发规则 6
        self.assertFalse(any("仓库外" in v for v in violations))


if __name__ == "__main__":
    unittest.main()
