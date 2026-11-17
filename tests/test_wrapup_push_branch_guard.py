"""evo-wrapup-push-branch-guard 测试：推送目标回归守护 + tip 前进断言 + 启动对账。

覆盖（对应 tasks.md 3.1 四场景）：
- master 检出项目推送目标为 master（既有 ``_resolve_push_target_branch``
  解析的行为级回归守护，分支解析机制本身不重写）；
- Everything up-to-date 空转推送不标 pushed 且告警单条（不进退避、不写
  error、不升级 push_failed）；
- tip 前进正常收口（推送后远端 tip 前进 → pushed 落定）；
- 启动对账输出本地基分支领先远端的提交数（启动日志 + get_health_summary
  聚合面）。

git 交互用真实临时仓（含本地 bare remote），tip 断言走真实 ls-remote——
mock 掉被测断言＝后端契约零覆盖，故仅对推送收口外围（归档/分支尽力/项目
日志/升级信号/蒸馏）打桩。
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.state_machine import (
    PUSH_ATTEMPTS_FIELD,
    PUSH_BACKOFF_NEXT_RETRY_AT_FIELD,
    StateMachine,
)


def git(repo: Path, *args) -> subprocess.CompletedProcess:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {args} failed: {res.stderr}"
    return res


def init_git_repo(repo: Path, branch: str = "main", initial_files: dict = None) -> str:
    """初始化 git 仓库（指定默认分支 + 初始提交），返回当前分支名。"""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", branch)
    git(repo, "config", "user.name", "fenix-test")
    git(repo, "config", "user.email", "fenix-test@example.com")
    for rel, content in (initial_files or {}).items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    if initial_files:
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "initial")
    return git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip()


def make_bare_remote(base: Path) -> Path:
    """建本地 bare remote 并返回其路径（tip 断言真实 ls-remote/push 的最小远端）。"""
    bare = base / "origin.git"
    git(base, "init", "-q", "--bare", str(bare))
    return bare


def bare_remote_sha(bare: Path, ref: str) -> str | None:
    """读 bare remote 上指定引用的 SHA（对账远端 tip 是否真实前进）。"""
    res = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True, text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else None


class FakeLogger:
    def __init__(self):
        self.debugs = []
        self.infos = []
        self.warnings = []
        self.errors = []

    def debug(self, *a, **k):
        self.debugs.append(a)

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        self.errors.append(a)

    def warn_texts(self):
        return [" ".join(str(x) for x in w) for w in self.warnings]

    def info_texts(self):
        return [" ".join(str(x) for x in w) for w in self.infos]


def build_engine(proot: Path, config: dict = None):
    """构造最小 PMEngine（真实 state_machine + MagicMock agent_runner）。"""
    from core.pm_engine import PMEngine

    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    logger = FakeLogger()
    sm = StateMachine(proot / ".fenix" / "STATE.md", logger)
    engine = PMEngine(sm, MagicMock(), config or {}, proot, logger)
    return engine, sm, logger


def isolate_push_periphery(engine):
    """隔离推送收口外围链路（tip 断言与 git push 走真实链路）。"""
    engine._resolve_push_branch = MagicMock(return_value="fenix/spec-a")
    engine._push_branch_best_effort = MagicMock()
    engine._archive_auto_commit = MagicMock()
    engine._append_project_log = MagicMock()
    engine._signal_push_failed = MagicMock()


# ════════════════════════════════════════════════════════════════════
# 场景 1：master 检出项目推送 master（解析回归守护）
# ════════════════════════════════════════════════════════════════════


class TestMasterCheckoutPushesMaster(unittest.TestCase):
    """master 检出（无本地 main 工作流）项目：收尾推送目标为 master，
    推送后 origin/master tip 前进、远端无 main——锁定既有解析行为不回退。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.branch = init_git_repo(self.tmpdir, branch="master", initial_files={
            "README.md": "x\n",
        })
        self.assertEqual(self.branch, "master")
        self.bare = make_bare_remote(self.tmpdir)
        git(self.tmpdir, "remote", "add", "origin", str(self.bare))
        # 本地基分支领先远端一个提交（推送须真实前进 tip 才收口）
        (self.tmpdir / "work.txt").write_text("wrapup\n", encoding="utf-8")
        git(self.tmpdir, "add", "-A")
        git(self.tmpdir, "commit", "-q", "-m", "wrapup work")
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)
        isolate_push_periphery(self.engine)
        self.sm.add_spec("spec-a", {"status": "done", "branch": "fenix/spec-a"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_master_checkout_pushes_master(self):
        local_sha = git(self.tmpdir, "rev-parse", "refs/heads/master").stdout.strip()
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertTrue(ok)
        # 推送目标为 master：远端 master tip 前进至本地 SHA
        self.assertEqual(bare_remote_sha(self.bare, "refs/heads/master"), local_sha)
        # 远端无 main（未发生 main 硬编码回退）
        self.assertIsNone(bare_remote_sha(self.bare, "refs/heads/main"))
        # spec 落 pushed 终态
        self.assertEqual(self.sm.read_one("spec-a")["status"], "pushed")
        # 日志表达解析目标分支（非 main-first 文案）
        infos = self.logger.info_texts()
        self.assertTrue(any("Pushing master" in t for t in infos), infos)
        self.assertTrue(
            any("Target-branch push succeeded" in t for t in infos), infos)


# ════════════════════════════════════════════════════════════════════
# 场景 2：空转推送不标 pushed 且告警单条
# ════════════════════════════════════════════════════════════════════


class TestUpToDateNoTipAdvance(unittest.TestCase):
    """推送返回成功但远端 tip 未前进：不标记 pushed 终态、发一条空转告警
    （含本地/远端 tip），零 error、零退避记账、零 push_failed 升级。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        init_git_repo(self.tmpdir, branch="main", initial_files={"README.md": "x\n"})
        self.bare = make_bare_remote(self.tmpdir)
        git(self.tmpdir, "remote", "add", "origin", str(self.bare))
        # 本地与远端完全一致（approve_push 时 push 必空转 up-to-date）
        git(self.tmpdir, "push", "-q", "origin", "main")
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)
        isolate_push_periphery(self.engine)
        self.sm.add_spec("spec-a", {"status": "done", "branch": "fenix/spec-a"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_up_to_date_not_pushed_single_warning(self):
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertFalse(ok, "空转推送不得计成功")
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "done", "空转不得标记 pushed 终态")
        self.assertIsNone(entry.get("error"), "空转不是失败，不得写 error")
        self.assertIsNone(entry.get(PUSH_ATTEMPTS_FIELD), "空转不进退避记账")
        self.assertIsNone(entry.get(PUSH_BACKOFF_NEXT_RETRY_AT_FIELD))
        self.engine._signal_push_failed.assert_not_called()
        # 单条空转告警（含本地/远端 tip 提示）
        uptodate_warns = [
            w for w in self.logger.warn_texts() if "推送目标无新内容" in w
        ]
        self.assertEqual(len(uptodate_warns), 1, uptodate_warns)
        self.assertIn("up-to-date", uptodate_warns[0])
        self.assertIn("ref=main", uptodate_warns[0])

    def test_up_to_date_repeat_stays_done(self):
        """重复进入（人工重推）：空转结果稳定，状态不漂移、告警逐次单条。"""
        self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertEqual(self.sm.read_one("spec-a")["status"], "done")
        self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertEqual(self.sm.read_one("spec-a")["status"], "done")
        uptodate_warns = [
            w for w in self.logger.warn_texts() if "推送目标无新内容" in w
        ]
        self.assertEqual(len(uptodate_warns), 2, "每次尝试各一条告警")


# ════════════════════════════════════════════════════════════════════
# 场景 3：tip 前进正常收口
# ════════════════════════════════════════════════════════════════════


class TestTipAdvanceNormalCloseout(unittest.TestCase):
    """推送后远端 tip 前进：按现有流程标记 pushed 并收口（行为无回退）。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        init_git_repo(self.tmpdir, branch="main", initial_files={"README.md": "x\n"})
        self.bare = make_bare_remote(self.tmpdir)
        git(self.tmpdir, "remote", "add", "origin", str(self.bare))
        git(self.tmpdir, "push", "-q", "origin", "main")
        # 本地基分支领先远端一个提交 → 推送真实前进
        (self.tmpdir / "work.txt").write_text("wrapup\n", encoding="utf-8")
        git(self.tmpdir, "add", "-A")
        git(self.tmpdir, "commit", "-q", "-m", "wrapup work")
        self.engine, self.sm, self.logger = build_engine(self.tmpdir)
        isolate_push_periphery(self.engine)
        self.sm.add_spec("spec-a", {"status": "done", "branch": "fenix/spec-a"})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tip_advance_marks_pushed(self):
        local_sha = git(self.tmpdir, "rev-parse", "refs/heads/main").stdout.strip()
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertTrue(ok)
        entry = self.sm.read_one("spec-a")
        self.assertEqual(entry["status"], "pushed")
        self.assertIsNone(entry.get("error"))
        # 远端 tip 真实前进至本地 SHA
        self.assertEqual(bare_remote_sha(self.bare, "refs/heads/main"), local_sha)
        # 零空转告警（tip 确实前进）
        self.assertEqual(
            [w for w in self.logger.warn_texts() if "推送目标无新内容" in w], [])
        infos = self.logger.info_texts()
        self.assertTrue(
            any("Target-branch push succeeded" in t for t in infos), infos)

    def test_tip_advance_new_remote_branch(self):
        """远端分支新建形态（基线缺席、推送后在）同样算 tip 前进。"""
        local_sha = git(self.tmpdir, "rev-parse", "refs/heads/main").stdout.strip()
        # 换挂一个全新空 bare remote（refs 全空 → 推送新建 main）
        fresh_bare = self.tmpdir / "origin-fresh.git"
        git(self.tmpdir, "init", "-q", "--bare", str(fresh_bare))
        git(self.tmpdir, "remote", "set-url", "origin", str(fresh_bare))
        ok = self.engine.approve_push("spec-a", distill=lambda p, n: None)
        self.assertTrue(ok, "远端分支新建（None→SHA）应判 tip 前进")
        self.assertEqual(self.sm.read_one("spec-a")["status"], "pushed")
        self.assertEqual(bare_remote_sha(fresh_bare, "refs/heads/main"), local_sha)


# ════════════════════════════════════════════════════════════════════
# 场景 4：启动对账输出领先数
# ════════════════════════════════════════════════════════════════════


class TestStartupBaseBranchAheadReconcile(unittest.TestCase):
    """daemon 启动（PMEngine 构造）对本地基分支相对远端的领先提交数对账：
    领先 N>0 时 WARNING 输出领先数与分支名（启动日志 + get_health_summary
    聚合面）；领先 0 时 INFO 留痕。"""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_repo(self, ahead_commits: int) -> Path:
        """建仓 + bare remote 并推平，再本地领先 ahead_commits 个提交。"""
        proot = self.tmpdir / f"proj-ahead-{ahead_commits}"
        init_git_repo(proot, branch="main", initial_files={"README.md": "x\n"})
        bare = make_bare_remote(proot)
        git(proot, "remote", "add", "origin", str(bare))
        git(proot, "push", "-q", "origin", "main")
        for i in range(ahead_commits):
            (proot / f"ahead-{i}.txt").write_text(f"{i}\n", encoding="utf-8")
            git(proot, "add", "-A")
            git(proot, "commit", "-q", "-m", f"ahead {i}")
        return proot

    def test_ahead_gap_exposed_on_startup(self):
        """领先缺口启动即暴露：WARNING 含领先数与分支名，聚合面同消费。"""
        proot = self._make_repo(ahead_commits=2)
        engine, sm, logger = build_engine(proot)
        self.assertEqual(
            engine._base_branch_ahead, {"branch": "main", "ahead": 2, "error": None})
        warns = logger.warn_texts()
        self.assertTrue(
            any("启动基分支对账" in w and "领先" in w and "2 个提交" in w
                and "main" in w for w in warns),
            warns,
        )
        # 聚合面（get_health_summary）消费领先数
        summary = engine.get_health_summary()
        self.assertIn("领先远端 2 提交", summary)

    def test_zero_ahead_info_not_warning(self):
        """领先 0：INFO 留痕对账已跑，不告警、聚合面不追加领先段。"""
        proot = self._make_repo(ahead_commits=0)
        engine, sm, logger = build_engine(proot)
        self.assertEqual(engine._base_branch_ahead["ahead"], 0)
        self.assertEqual(
            [w for w in logger.warn_texts() if "启动基分支对账" in w], [])
        self.assertTrue(
            any("领先 0 提交" in t for t in logger.info_texts()),
            logger.info_texts(),
        )
        self.assertNotIn("领先远端", engine.get_health_summary())

    def test_no_remote_fail_open(self):
        """无 remote 仓库：对账 fail-open（领先数不可知），不阻断构建。"""
        proot = self.tmpdir / "proj-no-remote"
        init_git_repo(proot, branch="main", initial_files={"README.md": "x\n"})
        engine, sm, logger = build_engine(proot)
        info = engine._base_branch_ahead
        self.assertIsNotNone(info)
        self.assertIsNone(info["ahead"], "rev-list 对远端引用缺失应留不可知")
        self.assertIsNotNone(info["error"])
