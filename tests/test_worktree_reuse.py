"""worktree 继承（fast-track 打回重派复用）单测。

覆盖 keep_for_reuse / create() 认领 / 继承语义 / 失效回退 / 宽限期回收：
  1. keep 后下轮 fast-track create 复用同一目录同一分支（含已提交成果继承）
  2. 复用遗产失效（目录被回收）→ 回退全新创建
  3. implementer/planner 族认领保留遗产（fix-provider-transient-backoff D3：
     认领通道扩展到全 agent_type，transient 终态保留现场下轮继承）
  4. reuse 遗产纳入宽限期兜底回收（复用 legacy 清扫机制）
  5. 成功收尾 cleanup 后认领痕迹清除（prompt 不再误注入继承说明）
基于真实 git 仓库 fixture（与 test_worktree_merge_guard 同构）。
"""

import subprocess
import time
from pathlib import Path

import pytest

from core.worktree_manager import WorktreeManager

from test_agent_runner import FakeLogger


def git(root: Path, *args, check=True):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@fenix.local")
    git(root, "config", "user.name", "Fenix Test")
    git(root, "config", "commit.gpgsign", "false")
    (root / "shared.py").write_text("BASE\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] base")


def make_wm(root: Path) -> WorktreeManager:
    base = root / ".claude" / "worktrees"
    base.mkdir(parents=True, exist_ok=True)
    return WorktreeManager(base, root, FakeLogger())


class TestWorktreeReuse:
    def test_keep_then_create_reuses_same_worktree(self, tmp_path):
        """keep 后下轮 fast-track create 认领同一目录同一分支，成果继承。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        assert wt1 is not None
        branch1 = wm.get_branch_name(wt1)

        # 模拟 agent 在 worktree 内的实现成果（提交 + 未提交现场）
        (wt1 / "core" / "feat.py").parent.mkdir(parents=True, exist_ok=True)
        (wt1 / "core" / "feat.py").write_text("IMPL\n", encoding="utf-8")
        git(wt1, "add", "-A")
        git(wt1, "commit", "-q", "-m", "[fenix] demo: impl")
        (wt1 / "core" / "wip.py").write_text("WIP\n", encoding="utf-8")

        # 打回保留
        wm.keep_for_reuse("demo", wt1)
        assert wt1.exists(), "打回后目录必须保留"
        assert git(root, "rev-parse", "--verify", branch1).returncode == 0
        assert not [k for k in wm._spec_locks if k.startswith("demo")], "锁已释放"
        rec = wm.get_reuse_record("demo")
        assert rec is None or rec.get("path") == str(wt1)

        # 下轮派发：认领同一目录同一分支
        wt2 = wm.create("demo", "fast-track")
        assert wt2 is not None and Path(wt2) == Path(wt1)
        assert wm.get_branch_name(wt2) == branch1
        # 继承：已提交成果与未提交现场都在
        assert (wt2 / "core" / "feat.py").read_text(encoding="utf-8") == "IMPL\n"
        assert (wt2 / "core" / "wip.py").exists()

        # 成功收尾：cleanup 后目录移除（分支保留），认领痕迹清除
        wm.cleanup(wt2, success=True)
        assert not wt2.exists()
        assert wm.get_reuse_record("demo") is None

    def test_invalid_reuse_record_falls_back_to_fresh(self, tmp_path, monkeypatch):
        """复用遗产已失效（目录被回收）→ 丢弃记录、回退全新创建。"""
        import core.worktree_manager as _wm_mod
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        branch1 = wm.get_branch_name(wt1)
        wm.keep_for_reuse("demo", wt1)
        # 模拟宽限期回收：目录与分支都被清掉
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force",
                        str(wt1)], capture_output=True)
        git(root, "branch", "-D", branch1)

        # worktree 目录名含秒级时间戳：注入推进 5s 的时钟保证新建目录名不同于
        # wt1（原实现 sleep(1.1) 等真实跨秒，慢且脆）。
        future = time.time() + 5
        monkeypatch.setattr(_wm_mod.time, "time", lambda: future)
        wt2 = wm.create("demo", "fast-track")
        assert wt2 is not None and Path(wt2) != Path(wt1), "失效遗产应回退新建"
        assert wm.get_reuse_record("demo") is None or \
            wm.get_reuse_record("demo").get("path") == str(wt2)

    def test_implementer_claims_reuse_record(self, tmp_path):
        """认领通道扩展到 implementer（fix-provider-transient-backoff D3/task 3.3）。

        旧语义「复用仅限 fast-track、implementer 自有遗产收编」已废止：transient
        终态保留的遗产对同 spec 下轮任意 implementer 族派发可见，同一目录同一
        分支继承现场。
        """
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        wm.keep_for_reuse("demo", wt1)

        wt2 = wm.create("demo", "implementer")
        assert wt2 is not None and Path(wt2) == Path(wt1), \
            "implementer 应回认领保留的复用遗产（D3 task 3.3）"
        assert wm.get_branch_name(wt2) == wm.get_branch_name(wt1), \
            "认领须落在同一分支（继承现场）"

    def test_reuse_record_reclaimed_after_grace(self, tmp_path):
        """reuse 遗产走 legacy 同一宽限期兜底回收，目录与分支一并清除。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        wt1 = wm.create("demo", "fast-track")
        branch1 = wm.get_branch_name(wt1)
        wm.keep_for_reuse("demo", wt1)

        reclaimed = wm._reclaim_expired_legacy(now=__import__("time").time() + 10_000)
        assert "demo" in reclaimed
        assert not wt1.exists()
        assert wm.get_reuse_record("demo") is None
        assert git(root, "rev-parse", "--verify", branch1, check=False).returncode != 0

    def test_keep_for_reuse_idempotent_across_redispatch_cycles(self, tmp_path):
        """打回→复用→再打回→再复用 循环稳定（覆盖式更新，不膨胀）。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        for round_no in range(3):
            wt = wm.create("demo", "fast-track")
            assert wt is not None
            wm.keep_for_reuse("demo", wt)
            assert len(wm._legacy) == 1, "覆盖式更新，遗产链不膨胀"
            assert wt.exists()


# ── 3a（todo 09-04 失误#3）：跨 attempt / 预置 worktree 复用前存在性校验 ──

def _exec_runner(proot: Path):
    """构造可跑 _execute_agent 的最小 AgentRunner（依赖全部 stub）。"""
    from unittest.mock import MagicMock
    from core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"max_retries": 3}}
    runner.project_root = proot
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    runner.logger = FakeLogger()
    runner.state_machine = None
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    runner._cancel_meta = {}
    runner._last_model_used = None
    wm = MagicMock()
    wm.create.return_value = proot / "wt-fresh"
    wm.get_branch_name.return_value = "fenix/fresh"
    runner.worktree_manager = wm
    # implementer 产物硬门 stub：本文件覆盖 worktree 复用/失效回退语义，与实现
    # 产物完成度正交。fix-impl-tasks-completion-gate（2026-09-14 df8dd94c）给
    # implementer 加了 worktree 内 .fenix-run-result.json 硬门，而这里 _run_agent
    # mock 不落结果文件 → 硬门判失败 → AgentArtifactGateError 退避重试，重试途中
    # 写 .fenix/runs/ 产物又因夹具未建该目录 FileNotFoundError（本测试的既有红灯）。
    runner._check_agent_result_artifact = MagicMock(return_value=None)
    runner._run_agent = MagicMock(return_value=(
        "ok", 1, "sess-1",
        {"input_tokens": 0, "output_tokens": 0,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
         "cost_usd": None}))
    runner._spec_is_frozen = lambda name: False
    runner._cancel_is_requested = lambda rid: False
    runner._cancel_clear = lambda rid: None
    runner._check_daily_limit = lambda: None
    runner._get_agent_model_assignment = lambda at: []
    runner._record_daily_provider_attempt = lambda p: None
    runner._write_provider_marker = lambda *a, **k: None
    runner._v2_launch_for_worktree = lambda p: None
    runner._v2_inject_env = lambda p: {}
    runner._v2_stop_for_worktree = lambda p: None
    runner._build_prompt = lambda *a, **k: "prompt"
    runner._resumable_session_id = lambda *a, **k: None
    runner._extract_usage_info = lambda x: {"input_tokens": 0, "output_tokens": 0,
                                            "cost_usd": None}
    runner._record_instant_fail = lambda *a, **k: None
    runner._extract_session_id = lambda p: None
    runner._accumulate_token_usage = lambda *a, **k: None
    runner._record_verify_progress_tokens = lambda *a, **k: None
    runner._reset_instant_fail = lambda *a, **k: None
    runner._should_give_up_before_retry = lambda *a, **k: False
    return runner


class TestStaleWorktreeValidation:
    """attempt 间隙 worktree 被恢复清理/孤儿回收删除后，盲复用会以
    [Errno 2] 秒挂白烧一次重试额度（09-04 add-run-cancel 实证）。
    复用前必须校验存在性：implementer/fast-track 失效即改走新建；
    repair 载体失效显式失败交还调度层重新解析（repair 语义要求在
    实现分支内修复，不能换新分支）。"""

    def test_stale_worktree_falls_back_to_fresh_create(self, tmp_path):
        runner = _exec_runner(tmp_path)
        stale = tmp_path / "gone-wt"  # 不存在
        result = runner._execute_agent(
            "spec-a", "implementer", "impl-spec-a-1", pre_wt_path=stale)
        assert result.success is True
        runner.worktree_manager.create.assert_called_once_with(
            "spec-a", "implementer")
        # claude 的 cwd 是新建 worktree，而非失效路径
        assert runner._run_agent.call_args.args[1] == tmp_path / "wt-fresh"

    def test_repair_stale_worktree_fails_fast(self, tmp_path):
        runner = _exec_runner(tmp_path)
        stale = tmp_path / "gone-repair-wt"
        result = runner._execute_agent(
            "spec-r", "repair", "repair-spec-r-1",
            pre_wt_path=stale, conflict_summary={})
        assert result.success is False
        assert "repair worktree" in result.error
        # 不烧重试额度：不派发 claude、不新建 worktree（repair 不能换分支）
        runner._run_agent.assert_not_called()
        runner.worktree_manager.create.assert_not_called()

    def test_valid_worktree_still_reused(self, tmp_path):
        """真实 worktree 按原语义复用（校验不得误伤正常路径）。"""
        runner = _exec_runner(tmp_path)
        real = tmp_path / "real-wt"
        init_repo(real)
        result = runner._execute_agent(
            "spec-v", "repair", "repair-spec-v-1",
            pre_wt_path=real, conflict_summary={})
        assert result.success is True
        runner.worktree_manager.create.assert_not_called()
        assert runner._run_agent.call_args.args[1] == real



def _write_spec_tasks(root, text):
    """写主树 spec tasks.md（gap_from_result 需要任务 id 清单）。"""
    d = root / "spec" / "changes" / "demo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.md").write_text(text, encoding="utf-8")


HUMAN_GATE_TASKS = (
    "# Tasks\n\n## 1. 实现\n\n- [x] 1.1 任务一\n- [x] 1.2 任务二\n"
    "## 7. 收尾\n\n- [ ] 7.3 门控\n"
)

class TestPartialNonConvergentInheritance:
    """fix-redispatch-loop-governance 4.3：partial 非收敛形态的成果继承链。

    runner 成功路径对 partial 且收敛不成立的 run 保留 worktree（_finalize_success
    内 cleanup 之前判定）；下一轮 implementer create 经 _take_reusable_worktree
    认领同一目录同一分支（继承已提交成果与未提交现场），MUST NOT 新建 worktree。
    """

    def test_partial_non_convergent_keep_then_implementer_reuses(self, tmp_path):
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)

        _write_spec_tasks(root, HUMAN_GATE_TASKS)
        wt1 = wm.create("demo", "implementer")
        branch1 = wm.get_branch_name(wt1)
        # 成果（提交 + 未提交现场）
        (wt1 / "core" / "feat.py").parent.mkdir(parents=True, exist_ok=True)
        (wt1 / "core" / "feat.py").write_text("IMPL\n", encoding="utf-8")
        git(wt1, "add", "-A")
        git(wt1, "commit", "-q", "-m", "[fenix] demo: impl")
        (wt1 / "core" / "wip.py").write_text("WIP\n", encoding="utf-8")

        from test_agent_runner import make_runner
        runner = make_runner(root)

        # partial 非收敛结果文件 → keep 判据成立
        (wt1 / ".fenix-run-result.json").write_text(
            '{"status": "partial", "spec": "demo",'
            ' "completed_tasks": ["1.1", "1.2"], "unfinished": []}',
            encoding="utf-8",
        )
        assert runner._should_keep_worktree_for_partial("demo", wt1) is True
        wm.keep_for_reuse("demo", wt1)
        assert wt1.exists(), "partial 非收敛保留后目录必须存在"

        # 下一轮 implementer 认领同一目录同一分支
        wt2 = wm.create("demo", "implementer")
        assert wt2 is not None and Path(wt2) == Path(wt1)
        assert wm.get_branch_name(wt2) == branch1
        assert (wt2 / "core" / "feat.py").read_text(encoding="utf-8") == "IMPL\n"
        assert (wt2 / "core" / "wip.py").exists()

    def test_partial_convergent_cleanup_semantics_unchanged(self, tmp_path):
        """收敛形态不保留：正常成功路径 cleanup(success=True) 语义不变。"""
        root = tmp_path / "repo"
        init_repo(root)
        wm = make_wm(root)
        _write_spec_tasks(root, HUMAN_GATE_TASKS)
        wt1 = wm.create("demo", "implementer")
        (wt1 / ".fenix-run-result.json").write_text(
            '{"status": "partial", "spec": "demo",'
            ' "completed_tasks": ["1.1", "1.2"],'
            ' "unattainable": [{"task": "7.3", "reason": "门控"}]}',
            encoding="utf-8",
        )
        from test_agent_runner import make_runner
        runner = make_runner(root)
        branch1 = wm.get_branch_name(wt1)
        assert runner._should_keep_worktree_for_partial("demo", wt1) is False
        wm.cleanup(wt1, success=True)
        assert not wt1.exists(), "收敛形态走既有 cleanup（目录清理、分支保留）"
        assert git(root, "rev-parse", "--verify", branch1).returncode == 0
