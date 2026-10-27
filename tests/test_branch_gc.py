"""tests/test_branch_gc.py — 已合并分支 GC（add-merged-branch-gc）。

覆盖三块：
1. 配置解析（tasks 1.3）：worktree.branch_gc 两键缺省/透传/非法回退/节非 dict 容错；
2. GC 判定与执行（tasks 2.5）：四条件齐备删除、宽限期内保留、未合并不删且计数、
   活跃 spec 豁免（含 testing/reviewing 等）、worktree 占用跳过、GC 关闭零动作、
   单分支 -d 失败不中断、解析失败分支跳过、零删除静默、legacy 登记分支跳过；
3. 端到端冒烟（tasks 4.2）：一轮清扫只删「已合并+超期」分支，日志计数与场景一致。
"""

from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import ConfigLoader
from core.state_machine import StateMachine
from core.worktree_manager import WorktreeManager


# ── 本地测试基建（与 test_interrupt_recovery_preserve 同款形态） ─────────────


class FakeLogger:
    def __init__(self):
        self.records: list = []

    def _rec(self, level, component, msg):
        self.records.append((level, component, msg))

    def info(self, component, msg, context=None):
        self._rec("info", component, msg)

    def warning(self, component, msg, context=None):
        self._rec("warning", component, msg)

    def error(self, component, msg, context=None):
        self._rec("error", component, msg)


def git(root: Path, *args, check=True, env_extra=None):
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, env=env,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path, main_branch: str = "main") -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")
    git(root, "branch", "-M", main_branch)


def backdated(root: Path, days_ago: float) -> str:
    """days_ago 天前的 git 日期串（GIT_*_DATE 可解析形态）。"""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S %z")


def commit_file(root: Path, rel: str, content: str, msg: str, date: str | None = None):
    """在当前分支写文件并 commit（date 非空时回拨提交时间）。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    git(root, "add", "-A")
    env_extra = {}
    if date:
        env_extra["GIT_AUTHOR_DATE"] = date
        env_extra["GIT_COMMITTER_DATE"] = date
    git(root, "commit", "-q", "-m", msg, env_extra=env_extra)


def merged_branch(root: Path, branch: str, days_ago: float, merge: bool = True) -> None:
    """从 main 建分支、回拨时间提交，默认 ff 合并回 main（--merged 口径成立）。

    MUST 始终从 main 分叉：上一条未合并分支创建后 HEAD 停在其上，若从当前
    HEAD 分叉，后续分支会包含未合并提交并被 ff 合并进 main，令「未合并」
    场景失真（前序提交随之变为 main 可达）。
    """
    git(root, "checkout", "-q", "main")
    git(root, "checkout", "-q", "-b", branch)
    commit_file(root, "feat.py", f"{branch}\n", f"[fenix] {branch}", date=backdated(root, days_ago))
    if merge:
        git(root, "checkout", "-q", "main")
        git(root, "merge", "-q", "--ff-only", branch)


def branch_names(root: Path) -> set:
    res = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return {ln.strip() for ln in res.stdout.splitlines() if ln.strip()}


def make_wm(root: Path, *, base_dir: Path | None = None, logger=None, **gc_kwargs) -> WorktreeManager:
    base = base_dir if base_dir is not None else root / ".claude" / "worktrees"
    return WorktreeManager(
        base, root, logger or FakeLogger(),
        process_scanner=lambda spec: False,
        **gc_kwargs,
    )


def make_state(root: Path, specs: dict) -> StateMachine:
    state_path = root / ".fenix" / "STATE.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    sm = StateMachine(state_path, FakeLogger())
    for name, entry in specs.items():
        sm.add_spec(name, entry)
    return sm


def gc_info_logs(logger: FakeLogger) -> list:
    return [m for lv, _c, m in logger.records if lv == "info" and "Merged branch GC" in m]


# ── 1. 配置解析（tasks 1.3） ────────────────────────────────────────────────


class TestBranchGcConfig:
    def test_missing_section_defaults(self):
        """缺省节（worktree / branch_gc 任一层缺）→ 默认 True/7 生效。"""
        assert ConfigLoader.get_branch_gc_config({}) == {"enabled": True, "retention_days": 7}
        assert ConfigLoader.get_branch_gc_config({"worktree": {}}) == {
            "enabled": True, "retention_days": 7,
        }

    def test_legal_values_passthrough(self):
        """合法值透传：enabled False + retention_days 3。"""
        cfg = {"worktree": {"branch_gc": {"enabled": False, "retention_days": 3}}}
        assert ConfigLoader.get_branch_gc_config(cfg) == {
            "enabled": False, "retention_days": 3,
        }

    @pytest.mark.parametrize("bad", [0, -1, -7, "5", None, True, False, 7.5])
    def test_retention_days_invalid_falls_back(self, bad):
        """retention_days=0/负数/字符串/None/bool/非整值浮点 → 回退默认 7。"""
        cfg = {"worktree": {"branch_gc": {"retention_days": bad}}}
        assert ConfigLoader.get_branch_gc_config(cfg)["retention_days"] == 7

    def test_retention_days_whole_float_accepted(self):
        """整值浮点按整数接受（与 _normalize_int_value / stale_code_selfheal 同口径）。"""
        cfg = {"worktree": {"branch_gc": {"retention_days": 14.0}}}
        assert ConfigLoader.get_branch_gc_config(cfg)["retention_days"] == 14

    @pytest.mark.parametrize("bad", [1, "false", None])
    def test_enabled_invalid_falls_back_true(self, bad):
        """enabled 非布尔（int/字符串/None）→ 回退缺省 True。"""
        cfg = {"worktree": {"branch_gc": {"enabled": bad}}}
        assert ConfigLoader.get_branch_gc_config(cfg)["enabled"] is True

    def test_non_dict_section_degrades(self):
        """节非 dict（列表/标量）容错：不抛异常、按缺省生效。"""
        assert ConfigLoader.get_branch_gc_config({"worktree": {"branch_gc": [1]}}) == {
            "enabled": True, "retention_days": 7,
        }
        assert ConfigLoader.get_branch_gc_config({"worktree": {"branch_gc": "on"}}) == {
            "enabled": True, "retention_days": 7,
        }

    def test_non_dict_worktree_degrades(self):
        """worktree 整段非 dict：不抛异常、按缺省生效。"""
        assert ConfigLoader.get_branch_gc_config({"worktree": []}) == {
            "enabled": True, "retention_days": 7,
        }

    def test_constructor_guard_rejects_bad_retention(self):
        """构造端直传非法 retention_days 时兜底回退 7（不放大脏值）。"""
        wm = make_wm(Path(__file__).parent, branch_gc_retention_days=0)
        assert wm._branch_gc_retention_days == 7
        assert wm._branch_gc_enabled is True


# ── 2. GC 判定与执行（tasks 2.5） ───────────────────────────────────────────


class TestBranchGcJudgement:
    def test_four_conditions_met_branch_deleted(self, tmp_path):
        """四条件齐备：已合并 + tip 超期 + 无 worktree + spec 非活跃 → 删除成功。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-old-feature-1787000000", days_ago=10)
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert "fenix/add-old-feature-1787000000" in stats["deleted"]
        assert "fenix/add-old-feature-1787000000" not in branch_names(root)

    def test_grace_period_branch_kept(self, tmp_path):
        """已合并但 tip 在宽限期内（3 天 < 7 天）→ 本轮不删。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-fresh-feature-1787000001", days_ago=3)
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert stats["grace_period"] == 1
        assert "fenix/add-fresh-feature-1787000001" in branch_names(root)

    def test_unmerged_branch_never_deleted(self, tmp_path):
        """未合并分支（无论多旧）不删且计数。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-wip-feature-1787000002", days_ago=100, merge=False)
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert stats["unmerged"] == 1
        assert "fenix/add-wip-feature-1787000002" in branch_names(root)

    def test_active_spec_branches_exempt(self, tmp_path):
        """活跃状态集（implementing/implemented/testing/reviewing/ready+_recovery_resume/
        blocked+frozen_hold）的已合并超期分支全部豁免；done spec 的分支正常回收。"""
        root = tmp_path / "repo"
        init_repo(root)
        cases = {
            "fenix/spec-impl-1001": {"status": "implementing"},
            "fenix/spec-done2-1002": {"status": "implemented"},
            "fenix/spec-testing-1003": {"status": "testing"},
            "fenix/spec-review-1004": {"status": "reviewing"},
            "fenix/spec-ready-1005": {"status": "ready", "_recovery_resume": True},
            "fenix/spec-frozen-1006": {
                "status": "blocked", "frozen": True, "_frozen_hold": True,
            },
            # 非活跃：done 状态的 spec 其已合并超期分支照常回收
            "fenix/spec-archived-1007": {"status": "done"},
        }
        for br in cases:
            merged_branch(root, br, days_ago=30)
        make_state(root, {
            name.split("/")[1].rsplit("-", 1)[0]: entry
            for name, entry in cases.items()
        })
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        # done spec 分支被回收，六个活跃豁免全保留
        assert stats["deleted"] == ["fenix/spec-archived-1007"]
        assert stats["active_spec"] == 6
        names = branch_names(root)
        for br in list(cases)[:-1]:
            assert br in names, f"活跃 spec 分支 {br} 必须豁免"

    def test_plain_ready_without_resume_not_exempt(self, tmp_path):
        """ready 无 _recovery_resume 标记 → 不属活跃集（与守卫 (i) 语义对齐）。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/spec-plain-ready-1008", days_ago=30)
        make_state(root, {"spec-plain-ready": {"status": "ready"}})
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == ["fenix/spec-plain-ready-1008"]

    def test_worktree_checkout_skip(self, tmp_path):
        """分支被 worktree checkout（fast-track 保留复用形态）→ 跳过且无删除报错。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/fast-track-spec-1009", days_ago=30)
        wt_dir = tmp_path / "carrier"
        git(root, "worktree", "add", "-q", str(wt_dir), "fenix/fast-track-spec-1009")
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert stats["worktree_checkout"] == 1
        assert "fenix/fast-track-spec-1009" in branch_names(root)
        # 收尾：清掉测试 worktree 注册，不污染共享对象库
        git(root, "worktree", "remove", "--force", str(wt_dir))

    def test_unparseable_branch_skipped(self, tmp_path):
        """前缀命中但 spec 名解析失败（末段非时间戳）→ 宁漏勿误跳过。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/notimestamp", days_ago=30)
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert stats["unparseable"] == 1
        assert "fenix/notimestamp" in branch_names(root)

    def test_non_fenix_namespace_branch_ignored(self, tmp_path):
        """非前缀家族分支（外部 release-* 等）不进 GC 视野。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "release-1.2", days_ago=365)
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert "release-1.2" in branch_names(root)

    def test_legacy_registered_branch_skipped(self, tmp_path):
        """在册 recovery legacy 登记引用的分支跳过（删除留给 legacy 兜底回收链）。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/legacy-spec-1010", days_ago=30)
        wm = make_wm(root)
        # 分支模式遗产登记（path 为空，仅 branch 字段引用）
        wm.register_legacy("legacy-spec", "", "fenix/legacy-spec-1010")
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert stats["legacy"] == 1
        assert "fenix/legacy-spec-1010" in branch_names(root)

    def test_gc_disabled_zero_action_and_silent(self, tmp_path):
        """enabled=false：整个环节跳过、零动作且无日志。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-old-feature-1787000000", days_ago=10)
        logger = FakeLogger()
        wm = make_wm(root, logger=logger, branch_gc_enabled=False)
        assert wm._gc_merged_branches() is None
        assert "fenix/add-old-feature-1787000000" in branch_names(root)
        assert gc_info_logs(logger) == []
        # 全量清扫入口同样零动作（分支保留）
        (root / ".claude" / "worktrees").mkdir(parents=True, exist_ok=True)
        wm.cleanup_stale_worktrees()
        assert "fenix/add-old-feature-1787000000" in branch_names(root)
        assert gc_info_logs(logger) == []

    def test_single_delete_failure_continues(self, tmp_path):
        """单分支 -d 失败（并发 checkout 拒绝形态）：记录明细后继续其余分支。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/doomed-spec-1011", days_ago=30)
        merged_branch(root, "fenix/survivor-spec-1012", days_ago=30)
        real_run = subprocess.run
        doomed = "fenix/doomed-spec-1011"

        def flaky_run(cmd, *a, **k):
            if (
                isinstance(cmd, list) and cmd[:1] == ["git"]
                and "branch" in cmd and "-d" in cmd and cmd[-1] == doomed
            ):
                return subprocess.CompletedProcess(
                    cmd, 1, stdout="",
                    stderr=f"error: branch '{doomed}' not fully merged / checked out",
                )
            return real_run(cmd, *a, **k)

        logger = FakeLogger()
        wm = make_wm(root, logger=logger)
        with patch("core.worktree_manager.subprocess.run", side_effect=flaky_run):
            stats = wm._gc_merged_branches()
        assert stats["deleted"] == ["fenix/survivor-spec-1012"]
        assert stats["failed"] == [doomed]
        assert "fenix/survivor-spec-1012" not in branch_names(root)
        assert doomed in branch_names(root)
        warns = [m for lv, _c, m in logger.records if lv == "warning" and doomed in m]
        assert warns, "单分支失败必须留 WARNING 明细"

    def test_zero_deletion_silent(self, tmp_path):
        """零删除静默：仅有未合并/宽限期内分支时不产日志。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-wip-1787000002", days_ago=100, merge=False)
        merged_branch(root, "fenix/add-fresh-1787000003", days_ago=2)
        logger = FakeLogger()
        wm = make_wm(root, logger=logger)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == []
        assert gc_info_logs(logger) == []

    def test_master_base_repo_gc_works(self, tmp_path):
        """master 基线仓库（无 main）：resolve_base_branch 回退基线不使 GC 整轮失效。"""
        root = tmp_path / "repo"
        init_repo(root, main_branch="master")
        git(root, "checkout", "-q", "-b", "fenix/add-on-master-1013")
        commit_file(root, "feat.py", "X\n", "[fenix] on master", date=backdated(root, 30))
        git(root, "checkout", "-q", "master")
        git(root, "merge", "-q", "--ff-only", "fenix/add-on-master-1013")
        wm = make_wm(root)
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == ["fenix/add-on-master-1013"]
        assert stats["base_branch"] == "master"

    def test_custom_prefix_namespace_scanned(self, tmp_path):
        """配置 implement_branch_prefix 非 fenix：扫描并集进视野；但非 fenix
        命名空间分支 _spec_from_branch 解析失败 → 按宁漏勿误跳过不删
        （design 决策 5：仅漏删，无误删）。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/created-side-1014", days_ago=30)
        merged_branch(root, "acme/configured-side-1015", days_ago=30)
        wm = make_wm(root, implement_branch_prefix="acme")
        stats = wm._gc_merged_branches()
        assert stats["deleted"] == ["fenix/created-side-1014"]
        assert stats["unparseable"] == 1
        assert "acme/configured-side-1015" in branch_names(root)


class TestBranchGcSweepIntegration:
    def test_gc_not_skipped_by_base_dir_early_return(self, tmp_path):
        """base_dir 不存在时 early-return 不吞 GC（tasks 2.1 挂载点要求）。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-old-feature-1787000000", days_ago=10)
        missing_base = root / ".claude" / "worktrees"  # 刻意不创建
        wm = make_wm(root, base_dir=missing_base)
        assert not missing_base.exists()
        wm.cleanup_stale_worktrees()
        assert "fenix/add-old-feature-1787000000" not in branch_names(root)

    def test_gc_non_blocking_on_scan_failure(self, tmp_path):
        """GC 整体异常（--merged 扫描失败）按清扫环节同口径 non-blocking 兜底：
        降级 WARNING、不抛穿 cleanup_stale_worktrees。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-old-feature-1787000000", days_ago=10)
        (root / ".claude" / "worktrees").mkdir(parents=True, exist_ok=True)
        real_run = subprocess.run

        def broken_merged_run(cmd, *a, **k):
            if isinstance(cmd, list) and "--merged=" in " ".join(cmd):
                return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: bad revision")
            return real_run(cmd, *a, **k)

        logger = FakeLogger()
        wm = make_wm(root, logger=logger)
        with patch("core.worktree_manager.subprocess.run", side_effect=broken_merged_run):
            # MUST NOT 抛穿
            wm.cleanup_stale_worktrees()
        warns = [m for lv, _c, m in logger.records if lv == "warning" and "Merged branch GC failed" in m]
        assert warns, "GC 整体异常必须降级 WARNING 留痕"
        assert "fenix/add-old-feature-1787000000" in branch_names(root)


# ── 3. 端到端冒烟（tasks 4.2） ───────────────────────────────────────────────


class TestEndToEndSmoke:
    def test_sweep_round_deletes_only_expired_merged(self, tmp_path):
        """一轮清扫：构造「已合并+超期」「已合并+宽限期内」「未合并」三条分支，
        仅第一条被删，日志计数与场景一致。"""
        root = tmp_path / "repo"
        init_repo(root)
        merged_branch(root, "fenix/add-expired-feature-1787000000", days_ago=10)   # 应删
        merged_branch(root, "fenix/add-grace-feature-1787000001", days_ago=3)      # 保留
        merged_branch(root, "fenix/add-unmerged-feature-1787000002", days_ago=100, merge=False)  # 保留
        logger = FakeLogger()
        wm = make_wm(root, logger=logger)
        wm.cleanup_stale_worktrees()
        names = branch_names(root)
        assert "fenix/add-expired-feature-1787000000" not in names, "已合并+超期分支必须被回收"
        assert "fenix/add-grace-feature-1787000001" in names, "宽限期内分支必须保留"
        assert "fenix/add-unmerged-feature-1787000002" in names, "未合并分支必须保留"
        logs = gc_info_logs(logger)
        assert len(logs) == 1, "有删除时恰一条结构化日志"
        line = logs[0]
        assert "deleted=1" in line
        assert "fenix/add-expired-feature-1787000000" in line
        assert "grace_period=1" in line
        assert "unmerged=1" in line
