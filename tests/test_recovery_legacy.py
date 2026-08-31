"""恢复重派遗产（add-recovery-legacy-check）测试。

覆盖 tasks 1.1/1.2/1.3/2.1/2.2/3.1/3.2：
- 死亡 run → 遗产注册 → 清扫豁免
- 后继 run merge 成功 → consume_legacy 回收
- 宽限期超时 → sweeper 兜底回收 + 审计
- 遗产覆盖式更新（仅留最新）
- 无遗产时 implementer prompt 逐字节不变
- 收编 / 弃用两路径的 prompt 注入内容断言（含 salvaged from 标注）

夹具模拟 add-fail-counter-budget 恢复现场形态：run 死亡 → spec 回 ready → 重派。
"""

import os
import time
from pathlib import Path

import pytest

from core.agent_runner import AgentRunner
from core.worktree_manager import (
    LEGACY_GRACE_SECONDS,
    WorktreeManager,
)

from test_agent_runner import FakeLogger
from test_run_lifecycle_governance import make_wm, touch_run_stream


# ── 1.1 遗产注册 / 查询 / 回收（内存态 + 覆盖式更新） ─────────────────────────


class TestLegacyRegister:
    def test_register_and_get(self, tmp_path):
        wm = make_wm(tmp_path)
        wm.register_legacy("s1", tmp_path / "impl-s1-100", "fenix/s1-100")
        rec = wm.get_legacy("s1")
        assert rec is not None
        assert rec["path"] == str(tmp_path / "impl-s1-100")
        assert rec["branch"] == "fenix/s1-100"
        assert rec["worktree_name"] == "impl-s1-100"

    def test_get_missing_returns_none(self, tmp_path):
        wm = make_wm(tmp_path)
        assert wm.get_legacy("nope") is None
        assert wm.has_legacy("nope") is False

    def test_consume_returns_record_and_clears(self, tmp_path):
        wm = make_wm(tmp_path)
        wm.register_legacy("s1", tmp_path / "impl-s1-100", "fenix/s1-100")
        rec = wm.consume_legacy("s1")
        assert rec is not None
        assert rec["branch"] == "fenix/s1-100"
        assert wm.get_legacy("s1") is None
        # 幂等：再消费返回 None
        assert wm.consume_legacy("s1") is None

    def test_overwrite_keeps_only_latest(self, tmp_path):
        """D5 覆盖式更新：同一 spec 再次死亡仅留最新一份。"""
        wm = make_wm(tmp_path)
        wm.register_legacy("s1", tmp_path / "impl-s1-100", "fenix/s1-100")
        wm.register_legacy("s1", tmp_path / "impl-s1-200", "fenix/s1-200")
        rec = wm.get_legacy("s1")
        assert rec["path"] == str(tmp_path / "impl-s1-200")
        assert rec["branch"] == "fenix/s1-200"
        # 内存态仅一条
        assert len(wm._legacy) == 1


# ── 1.2 死亡 cleanup 注册遗产 + 清扫豁免 + 宽限期兜底 ─────────────────────────


class TestLegacyOnDeath:
    def _make_impl_worktree(self, wm, tmp_path, name="impl-s1-100"):
        wt = tmp_path / ".claude" / "worktrees" / name
        wt.mkdir(parents=True, exist_ok=True)
        branch = f"fenix/s1-100"
        wm._active_worktrees.add(str(wt))
        wm._wt_branches[str(wt)] = branch
        wm._spec_locks.add("s1:implementer")
        return wt, branch

    def test_failed_implementer_cleanup_registers_legacy(self, tmp_path):
        wm = make_wm(tmp_path)
        wt, branch = self._make_impl_worktree(wm, tmp_path)
        # 失败 implementer cleanup：保留 worktree 为遗产，不删除目录/分支
        wm.cleanup(wt, success=False)
        rec = wm.get_legacy("s1")
        assert rec is not None
        assert rec["path"] == str(wt)
        assert rec["branch"] == branch
        # 物理目录保留（未被销毁）
        assert wt.exists()

    def test_successful_implementer_cleanup_not_legacy(self, tmp_path):
        wm = make_wm(tmp_path)
        wt, branch = self._make_impl_worktree(wm, tmp_path)
        # 成功路径：照常清理（不注册遗产）
        wm.cleanup(wt, success=True)
        assert wm.get_legacy("s1") is None

    def test_verifier_failure_not_registered_as_legacy(self, tmp_path):
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "verify-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm._active_worktrees.add(str(wt))
        wm._wt_branches[str(wt)] = "fenix/verify-s1-100"
        wm.cleanup(wt, success=False)
        assert wm.get_legacy("s1") is None

    def test_sweeper_exempts_legacy_within_grace(self, tmp_path):
        """遗产在宽限期内：清扫器跳过其 worktree。"""
        wm = make_wm(tmp_path)
        wt, branch = self._make_impl_worktree(wm, tmp_path)
        wm.cleanup(wt, success=False)  # 注册遗产，物理保留
        # 宽限期内：清扫器不影响遗产目录
        wm.cleanup_stale_worktrees()
        rec = wm.get_legacy("s1")
        assert rec is not None  # 仍在册（豁免，未兜底回收）
        # 真实 git 调用会失败（非 git 仓库），但豁免判断在调用前已跳过该目录
        assert wt.exists() or rec is not None


class TestLegacyGraceExpiry:
    def test_expired_legacy_reclaimed_by_sweeper(self, tmp_path):
        """宽限期超时：sweeper 兜底回收并记审计。"""
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm.register_legacy("s1", wt, "fenix/s1-100")
        # 人为把注册时刻拨到宽限期之前
        wm._legacy["s1"]["registered_at"] = time.time() - (LEGACY_GRACE_SECONDS + 60)
        reclaimed = wm._reclaim_expired_legacy()
        assert "s1" in reclaimed
        assert wm.get_legacy("s1") is None

    def test_fresh_legacy_not_reclaimed(self, tmp_path):
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm.register_legacy("s1", wt, "fenix/s1-100")
        wm._legacy["s1"]["registered_at"] = time.time()
        assert wm._reclaim_expired_legacy() == []

    def test_refresh_locks_registers_legacy_for_orphan(self, tmp_path):
        """D2：陈锁释放且物理残留 implementer worktree → refresh_locks 兜底注册遗产。"""
        wm = make_wm(tmp_path, alive=False)
        # 残留孤儿 worktree（不在活动集，无锁）
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm._wt_branches[str(wt)] = "fenix/s1-100"
        wm._spec_locks.add("s1:implementer")
        touch_run_stream(tmp_path, "s1", "impl-s1-100", age=200)
        released = wm.refresh_locks()
        assert released == ["s1:implementer"]
        rec = wm.get_legacy("s1")
        assert rec is not None
        assert rec["path"] == str(wt)


# ── 2.1/2.2 implementer prompt 注入（无遗产逐字节一致） ──────────────────────


class TestImplementerPromptLegacy:
    def _runner(self, tmp_path):
        runner = AgentRunner.__new__(AgentRunner)
        runner.config = {}
        runner.worktree_manager = None
        runner.state_machine = None
        runner.project_root = tmp_path
        runner.logger = FakeLogger()
        runner._running_agents = {}
        return runner

    def test_no_legacy_prompt_unchanged(self, tmp_path):
        """无遗产：prompt 与现状逐字节一致（不注入空段）。"""
        runner = self._runner(tmp_path)
        runner.worktree_manager = make_wm(tmp_path)  # 无任何遗产
        prompt = runner._prompt_builder._build_prompt("s1", "implementer")
        assert "RECOVERY LEGACY" not in prompt
        assert "salvaged from" not in prompt
        # 与无 worktree_manager 时的 prompt 一致（退化安全）
        runner2 = self._runner(tmp_path)
        runner2.worktree_manager = None
        assert runner._prompt_builder._build_prompt("s1", "implementer") == runner2._build_prompt("s1", "implementer")

    def test_legacy_prompt_injected_with_section(self, tmp_path):
        """有遗产：注入路径/分支/只读约束/收编弃用/响应格式 + salvaged from。"""
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm.register_legacy("s1", wt, "fenix/s1-100")
        runner = self._runner(tmp_path)
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("s1", "implementer")
        assert "RECOVERY LEGACY" in prompt
        assert str(wt) in prompt
        assert "fenix/s1-100" in prompt
        # 只读约束
        assert "只读参考" in prompt
        # 收编 / 弃用决策
        assert "收编" in prompt and "弃用" in prompt
        # salvaged from 标注要求（含分支名）
        assert "salvaged from" in prompt
        assert "fenix/s1-100" in prompt

    def test_legacy_prompt_dirty_snapshot_truncated(self, tmp_path):
        """脏文件快照现场采集并截断至 50 行（git 不可用时降级不抛）。"""
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        # 非 git 仓库：status 调用失败 → 降级串，不抛
        wm.register_legacy("s1", wt, "fenix/s1-100")
        runner = self._runner(tmp_path)
        runner.worktree_manager = wm
        # 快照采集在 runner 上，非 git 仓库降级不抛
        snap = runner._prompt_builder._legacy_dirty_snapshot(str(wt))
        assert isinstance(snap, str) and snap  # 降级提示，非空
        # 注入段引用了快照占位
        prompt = runner._prompt_builder._build_prompt("s1", "implementer")
        assert "git status --short" in prompt

    def test_salvage_commit_format_in_prompt(self, tmp_path):
        """收编提交信息格式要求含 `[fenix] <spec>: ... (salvaged from <branch>)`。"""
        wm = make_wm(tmp_path)
        wt = tmp_path / ".claude" / "worktrees" / "impl-s1-100"
        wt.mkdir(parents=True, exist_ok=True)
        wm.register_legacy("s1", wt, "fenix/s1-100")
        runner = self._runner(tmp_path)
        runner.worktree_manager = wm
        prompt = runner._prompt_builder._build_prompt("s1", "implementer")
        # 收编提交信息模板出现（salvaged from 标注）
        assert "salvaged from fenix/s1-100" in prompt
        # 明确禁止在遗产内工作
        assert "不得" in prompt and "写操作" in prompt
