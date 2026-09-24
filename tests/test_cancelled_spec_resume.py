"""add-cancelled-spec-resume-action 单测：取消保持态 SPEC 的界面恢复动作。

覆盖（tasks 5.1/5.2）：
- 命中：保留分支续做复位（STATE 落点逐字段断言 + kick 文件存在）
- 降级：共享判定运行过且不通过 → degraded 普通重派（锚点清空、无 _recovery_resume）
- 非保持态幂等拒绝（STATE 零变更）；冻结拒绝；终态拒绝
- 负例①：STATE 文本写作 `_cancelled_hold: False`（大写 F，同存量条目）时
  归一化读值为 False（摘要字段源）且动作幂等拒绝——防裸真值判定回归
- 负例②：WorktreeManager 构造失败时动作拒绝、STATE 逐字段零变更
  （MUST NOT 降级清锚点）
"""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard.data.admin_actions import resume_cancelled_spec
from core.dashboard.data.state import normalize_bool_flag, parse_state
from core.state_machine import StateMachine

CANCEL_ERR = "run 被人工取消：测试原因"


def _git(repo: Path, *args: str) -> str:
    """在 repo 下执行 git，返回 stdout（失败即抛）。"""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _mk_repo(tmpdir: Path) -> Path:
    """构造带 main + fenix/<spec>-x（领先一提交）的 git 仓库。"""
    repo = tmpdir
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    _git(repo, "checkout", "-b", "fenix/s1-x")
    (repo / "work.txt").write_text("wip", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "wip on preserved branch")
    _git(repo, "checkout", "main")
    return repo


def _mk_sm(tmpdir: Path) -> StateMachine:
    proot = tmpdir
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    return StateMachine(proot / ".fenix" / "STATE.md", MagicMock())


def _mk_spec(sm: StateMachine, name: str, status: str = "implementing",
             **extra) -> None:
    sm.add_spec(name, {"priority": 5})
    if status != "drafted":
        sm.transition(name, "ready")
        sm.transition(name, "implementing")
    updates: dict = {"error": CANCEL_ERR, "_cancelled_hold": True}
    updates.update(extra)
    sm.update_spec(name, updates)


def _mock_wm(branch: str = "fenix/s1-x"):
    """构造可用的 WorktreeManager 替身（resolve_resume_site 三态可用）。"""
    wm = MagicMock()
    wm.find_worktree_by_spec.return_value = None
    wm.find_branches_by_spec.return_value = []
    wm.resolve_resume_site.return_value = ("/tmp/wt-s1", branch)
    return wm


class ResumeCancelledSpecHitTest(unittest.TestCase):
    """命中：保留分支续做复位。"""

    def test_resume_writes_recovery_resume_and_kicks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x",
                     implementer_run="impl-a1", tester_run="test-a1")
            # 陈旧计数：恢复后必须归零（防误读/误熔断）
            sm.update_spec("s1", {
                "_retry_count": 2, "_merge_streak": 3,
                "_redispatch_same_cause_streak": 4,
            })
            kick_dir = repo / ".fenix" / "scheduling_kick"
            with patch("core.worktree_manager.WorktreeManager",
                       return_value=_mock_wm()):
                result = resume_cancelled_spec(repo, "s1")
            self.assertTrue(result["ok"], result)
            self.assertFalse(result.get("degraded"))
            self.assertEqual(result["spec"], "s1")
            entry = sm.read_one("s1")
            self.assertEqual(entry["status"], "ready")
            self.assertEqual(entry["branch"], "fenix/s1-x")
            self.assertIs(entry["_recovery_resume"], True)
            self.assertIs(entry["_cancelled_hold"], False)
            self.assertEqual(entry["implementer_run"], "impl-a1")
            self.assertIsNone(entry["tester_run"])
            # STATE.md 文本表往返：数字字段归一为字符串，取值断言经 int 归一
            self.assertEqual(int(entry["_retry_count"]), 0)
            # null 值经 STATE 文本往返为 "null" 字面量（_ 前缀键不在
            # StateParser null 归一化表），语义断言按空值白名单容错
            self.assertIn(entry["_merge_fp"], (None, "null", ""))
            self.assertEqual(int(entry["_merge_streak"]), 0)
            self.assertEqual(int(entry["_redispatch_same_cause_streak"]), 0)
            self.assertIn(entry["_redispatch_cause_fp"], (None, "null", ""))
            self.assertIn("resume preserved branch", entry["error"])
            self.assertIn("implementing", entry["error"])
            # 即时唤醒：scheduling_kick 信号文件存在
            self.assertTrue((kick_dir / "s1.json").exists())


class ResumeCancelledSpecRebuildRealWmTest(unittest.TestCase):
    """BUG-01 回归：载体缺失（WT_REBUILDABLE）重建路径 × logger=None 构造。

    验证报告 api-resume-hit-rebuild-worktree 场景缺陷修复回归：dashboard 侧
    resume_cancelled_spec 以 logger=None 构造 WorktreeManager（与 unfreeze
    先例同型），而重建路径 create_worktree_on_branch 成功/失败分支均无条件
    调 self.logger——构造器缺 _NullLogger 兜底时 AttributeError 未捕获 →
    路由 500、STATE 零变更，续做功能完全不可用。本用例不 mock
    WorktreeManager：真实构造走完整重建链（保留分支在位、无在册 worktree）。
    """

    def test_rebuild_path_with_logger_none_wm_succeeds(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # _mk_repo：fenix/s1-x 领先 main 一提交，未建任何 worktree（载体缺失）
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x", implementer_run="impl-a1")
            result = resume_cancelled_spec(repo, "s1")
            self.assertTrue(result["ok"], result)
            self.assertFalse(result.get("degraded"))
            self.assertEqual(result["spec"], "s1")
            entry = sm.read_one("s1")
            self.assertEqual(entry["status"], "ready")
            self.assertEqual(entry["branch"], "fenix/s1-x")
            self.assertIs(entry["_recovery_resume"], True)
            # 重建的 worktree 真实在场（create_worktree_on_branch 真实执行）
            from core.worktree_manager import WorktreeManager
            wm = WorktreeManager(base_dir=repo / ".fenix", project_root=repo,
                                 logger=None)
            self.assertIsNotNone(wm.find_worktree_path("fenix/s1-x"))

    def test_create_worktree_on_branch_tolerates_logger_none(self):
        """直接单测构造器兜底：logger=None 构造后成功/失败分支均不崩。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            from core.worktree_manager import WorktreeManager
            wm = WorktreeManager(base_dir=repo / ".fenix", project_root=repo,
                                 logger=None)
            # 成功分支：info 留痕路径
            wt = wm.create_worktree_on_branch("s1", "fenix/s1-x")
            self.assertIsNotNone(wt)
            # 失败分支（分支不存在）：error 留痕路径，返回 None 不抛
            self.assertIsNone(wm.create_worktree_on_branch("s1", "fenix/no-such"))


class ResumeCancelledSpecDegradedTest(unittest.TestCase):
    """降级：共享判定运行过且不通过 → 普通全新重派。"""

    def test_degraded_resets_without_recovery_resume(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            # 无 branch 锚点 + 三层枚举均空 → 判定运行且不通过；
            # 预置陈旧计数（取消收尾刻意保留），断言降级重派同款清零。
            _mk_spec(sm, "s1", branch=None, implementer_run="impl-a1")
            sm.update_spec("s1", {
                "_retry_count": 2,
                "_merge_fp": "stale-fp",
                "_merge_streak": 1,
                "_redispatch_same_cause_streak": 2,
                "_redispatch_cause_fp": "stale-cause",
            })
            wm = _mock_wm()
            wm.find_branches_by_spec.return_value = []
            wm.resolve_resume_site.return_value = (None, None)
            with patch("core.worktree_manager.WorktreeManager",
                       return_value=wm):
                result = resume_cancelled_spec(repo, "s1")
            self.assertTrue(result["ok"], result)
            self.assertIs(result["degraded"], True)
            self.assertTrue(result.get("reason"))
            entry = sm.read_one("s1")
            self.assertEqual(entry["status"], "ready")
            self.assertIsNone(entry["branch"])
            self.assertIsNone(entry["implementer_run"])
            self.assertNotIn("_recovery_resume", entry)
            # 陈旧计数随降级清零（对齐 unfreeze 人工处置先例），防全新重派
            # 首几轮误触发同因熔断/合并告警。
            self.assertEqual(int(entry["_retry_count"]), 0)
            # null 值经 STATE 文本往返为 "null" 字面量（同命中分支断言口径）
            self.assertIn(entry["_merge_fp"], (None, "null", ""))
            self.assertEqual(int(entry["_merge_streak"]), 0)
            self.assertEqual(int(entry["_redispatch_same_cause_streak"]), 0)
            self.assertIn(entry["_redispatch_cause_fp"], (None, "null", ""))
            self.assertIs(entry["_cancelled_hold"], False)
            self.assertTrue((repo / ".fenix" / "scheduling_kick" / "s1.json").exists())


class ResumeCancelledSpecRefusalTest(unittest.TestCase):
    """拒绝语义：非保持态幂等拒绝 / 冻结 / 终态（STATE 零变更）。"""

    def test_non_hold_idempotent_refusal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x")
            sm.update_spec("s1", {"_cancelled_hold": False})
            before = (repo / ".fenix" / "STATE.md").read_text("utf-8")
            with patch("core.worktree_manager.WorktreeManager",
                       return_value=_mock_wm()):
                result = resume_cancelled_spec(repo, "s1")
            self.assertFalse(result["ok"])
            self.assertTrue(result["found"])
            self.assertIn("取消保持态", result["reason"])
            after = (repo / ".fenix" / "STATE.md").read_text("utf-8")
            self.assertEqual(before, after)

    def test_frozen_refusal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x")
            # is_spec_frozen 判据：status=blocked + 结构化 frozen 标记
            sm.update_spec("s1", {"status": "blocked", "frozen": True,
                                  "error": "用户指令冻结：原状态 implementing"})
            before = (repo / ".fenix" / "STATE.md").read_text("utf-8")
            with patch("core.worktree_manager.WorktreeManager",
                       return_value=_mock_wm()):
                result = resume_cancelled_spec(repo, "s1")
            self.assertFalse(result["ok"])
            self.assertIn("解冻", result["reason"])
            self.assertEqual(
                (repo / ".fenix" / "STATE.md").read_text("utf-8"), before)

    def test_terminal_refusal(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1")
            sm.update_spec("s1", {"status": "done"})
            before = (repo / ".fenix" / "STATE.md").read_text("utf-8")
            result = resume_cancelled_spec(repo, "s1")
            self.assertFalse(result["ok"])
            self.assertTrue(result.get("terminal"))
            self.assertEqual(
                (repo / ".fenix" / "STATE.md").read_text("utf-8"), before)

    def test_not_found(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            _mk_sm(repo)
            result = resume_cancelled_spec(repo, "nope")
            self.assertFalse(result["ok"])
            self.assertFalse(result["found"])


class ResumeCancelledSpecNegativeTest(unittest.TestCase):
    """tasks 5.2 两条负例。"""

    def test_negative_1_text_false_not_hold(self):
        """负例①：STATE 文本 `_cancelled_hold: False`（大写 F）不误标、不误纳。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x")
            # 手工把 STATE 写成存量条目形态：Python 字面量大写 F——裸真值
            # 判定（bool("False")==True）会把它误判为保持态并强置 ready。
            state_path = repo / ".fenix" / "STATE.md"
            text = state_path.read_text("utf-8")
            text = text.replace("- _cancelled_hold: false",
                                "- _cancelled_hold: False")
            text = text.replace("- _cancelled_hold: True",
                                "- _cancelled_hold: False")
            state_path.write_text(text, encoding="utf-8")
            # 归一化读值（摘要字段源）：False 文本 → False
            specs = parse_state(repo)
            self.assertIs(specs["s1"]["_cancelled_hold"], False)
            self.assertIs(normalize_bool_flag("False"), False)
            self.assertIs(normalize_bool_flag("true"), True)
            self.assertIs(normalize_bool_flag(True), True)
            # 动作幂等拒绝，STATE 零变更
            before = state_path.read_text("utf-8")
            with patch("core.worktree_manager.WorktreeManager",
                       return_value=_mock_wm()):
                result = resume_cancelled_spec(repo, "s1")
            self.assertFalse(result["ok"])
            self.assertIn("取消保持态", result["reason"])
            self.assertEqual(state_path.read_text("utf-8"), before)

    def test_negative_2_wm_unavailable_refusal(self):
        """负例②：WorktreeManager 构造失败 → fail-closed 拒绝，STATE 零变更。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = _mk_repo(Path(td))
            sm = _mk_sm(repo)
            _mk_spec(sm, "s1", branch="fenix/s1-x",
                     implementer_run="impl-a1")
            state_path = repo / ".fenix" / "STATE.md"
            before = state_path.read_text("utf-8")
            with patch("core.worktree_manager.WorktreeManager",
                       side_effect=RuntimeError("载体工具不可用")):
                result = resume_cancelled_spec(repo, "s1")
            self.assertFalse(result["ok"])
            self.assertIn("worktree 管理器不可用", result["reason"])
            # 逐字段零变更（未降级清锚点：branch/implementer_run 仍在）
            self.assertEqual(state_path.read_text("utf-8"), before)
            entry = sm.read_one("s1")
            self.assertEqual(entry["branch"], "fenix/s1-x")
            self.assertEqual(entry["implementer_run"], "impl-a1")
            self.assertIs(entry["_cancelled_hold"], True)
            self.assertNotIn("_recovery_resume", entry)
            # 未写唤醒信号
            self.assertFalse((repo / ".fenix" / "scheduling_kick").exists())


class ParseStateCancelledHoldNormalizationTest(unittest.TestCase):
    """tasks 2.3：parse_state 归一化表覆盖 _cancelled_hold。"""

    def test_parse_state_normalizes_cancelled_hold(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".fenix").mkdir(parents=True, exist_ok=True)
            (repo / ".fenix" / "STATE.md").write_text(
                "# State\n\n"
                "### s-true\n"
                "- status: implementing\n"
                "- _cancelled_hold: True\n"
                "\n"
                "### s-false\n"
                "- status: implementing\n"
                "- _cancelled_hold: False\n"
                "\n"
                "### s-missing\n"
                "- status: ready\n",
                encoding="utf-8",
            )
            specs = parse_state(repo)
            self.assertIs(specs["s-true"]["_cancelled_hold"], True)
            self.assertIs(specs["s-false"]["_cancelled_hold"], False)
            self.assertNotIn("_cancelled_hold", specs["s-missing"])


class ParseStateDigitKeyParsingTest(unittest.TestCase):
    """parse_state 字段键正则覆盖带数字下划线键（如 _token_warn_80）。

    仓内 STATE 条目确有带数字的键（admin_actions 复位
    `_token_warn_80`/`_token_alert_100`），键正则不含数字即被静默丢弃。
    """

    def test_digit_suffix_key_is_parsed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            (repo / ".fenix").mkdir(parents=True, exist_ok=True)
            (repo / ".fenix" / "STATE.md").write_text(
                "# State\n\n"
                "### s1\n"
                "- status: implementing\n"
                "- _token_warn_80: True\n"
                "- _token_alert_100: False\n",
                encoding="utf-8",
            )
            specs = parse_state(repo)
            # 断言点是键能被解析到（不静默丢弃）；parse_state 对 _ 前缀键
            # 保留原始字符串，勿用其断言真值
            self.assertIn("_token_warn_80", specs["s1"])
            self.assertIn("_token_alert_100", specs["s1"])
            self.assertEqual(specs["s1"]["_token_warn_80"], "True")
            self.assertEqual(specs["s1"]["_token_alert_100"], "False")


if __name__ == "__main__":
    unittest.main()
