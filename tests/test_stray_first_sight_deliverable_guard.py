"""fix-review-disposition-stray-channel 单测（tasks.md 3.1）。

覆盖：
- 豁免面（1.1）：``spec/changes/<name>/`` untracked 首现——evidence 无
  ``gitignore草案:`` 且含交付物注记、recommended_action 建议提交入库且
  不含 .gitignore 追加指引；首现提示本身保留（prompted，提醒人工提交
  的信号价值仍在）；``spec`` 根目录形态同样豁免
- 回归锚（1.1）：普通运行时产物目录（``build-foo/``）首现草案行为与
  现行逐字一致（description / recommended_action 全文相等断言）
- 收尾面（2.1）：三态——有变更提交且 porcelain 复查为净；无变更不产
  提交（HEAD 与提交计数不动）；git 抛错 / 非 git 仓仅 WARNING 且结果
  文件路径照常返回（硬门放行语义不变）；spec 名形态守卫
"""

import json
import logging
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner.prompt_builder import spec_review_result_path
from core.agent_runner.result_gate import (
    _check_agent_result_artifact,
    commit_spec_review_docs,
)
from core.admin_store import AdminStore, SIGNAL
from core.worktree_manager.stray_wip import (
    UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
)
from tests.helpers import FakeLogger

# ── 豁免面共用工装（test_stray_first_sight_prevention 同款装配）──────────


def _git(*args, cwd, check=True):
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )


def _make_repo(ignore_rules: str = ".fenix/*\n!.fenix/verify.yaml\n") -> Path:
    """主树仓：a/b.tsx 已提交；.gitignore 可定制（判据现场）。"""
    repo = tmp_basetemp_dir("deliverable-guard-scene-")
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=repo)
    (repo / "a.tsx").write_text("base", encoding="utf-8")
    (repo / "b.tsx").write_text("base", encoding="utf-8")
    (repo / ".gitignore").write_text(ignore_rules, encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def tmp_basetemp_dir(prefix: str) -> Path:
    """/tmp 可能被外部清扫进程周期性清空（first-sight 同款规避）：
    basetemp 落仓库 .history/tmp（gitignored）。"""
    base = Path(__file__).resolve().parent.parent / ".history" / "tmp"
    base.mkdir(parents=True, exist_ok=True)
    import tempfile

    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(base))) / "proj"


def _make_sweeper(repo, grace=30.0) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": grace}}
    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg, logger=None)


class _WmProbe:
    """WorktreeManager 探针壳（test_stray_first_sight_prevention 同款装配）。"""

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = __import__("threading").Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _write_strays(repo, names):
    for n in names:
        p = repo / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"stray {n}\n", encoding="utf-8")


def _first_sight_alerts(repo) -> list:
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == UNTRACKED_FIRST_SIGHT_SIGNAL_TYPE
    ]


# ── 收尾面共用工装（test_spec_review_artifact_gate 同款最小 runner）──────


def _make_git_review_repo() -> Path:
    """带本地身份的评审主树仓（收尾钩子的 git commit 无 -c 注入，须仓级身份）。"""
    repo = _make_repo()
    _git("config", "user.email", "fenix-review@example.com", cwd=repo)
    _git("config", "user.name", "fenix-review", cwd=repo)
    return repo


def _make_runner(repo: Path) -> AgentRunner:
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = repo
    runner.logger = FakeLogger()
    runner._running_agents = {}
    (repo / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    return runner


def _write_review_result(repo: Path, spec: str, status: str) -> Path:
    path = spec_review_result_path(repo, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"status": status, "spec": spec}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _porcelain(repo: Path, pathspec: str) -> str:
    r = subprocess.run(
        ["git", "status", "--porcelain", "--", pathspec],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout


def _head_and_count(repo: Path) -> tuple:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True,
    ).stdout.strip()
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(repo),
        capture_output=True, text=True,
    ).stdout.strip()
    return head, int(count)


# ── 豁免面（1.1）────────────────────────────────────────────────────


class TestDeliverableFirstSightExemption:
    def test_spec_changes_dir_prompted_without_gitignore_draft(self):
        """spec/changes/<name>/ 首现：提示照发，无草案行、含交付物注记，
        recommended_action 建议提交入库而非追加 .gitignore。"""
        repo = _make_repo()
        # 锚定 spec/ 与 spec/changes 为 tracked（真实形态：其他 spec 已入库），
        # 使归组根目录取 spec/changes/demo-proposal（spec/ 前缀分支）。
        seed = repo / "spec" / "changes" / "old-spec"
        seed.mkdir(parents=True)
        (seed / "proposal.md").write_text("seed\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "seed spec", cwd=repo)
        _write_strays(repo, [
            "spec/changes/demo-proposal/proposal.md",
            "spec/changes/demo-proposal/design.md",
        ])
        r = _make_sweeper(repo).sweep()
        fs = r["untracked"]["first_sight"]
        # 首现提示本身保留（提醒人工提交的信号价值仍在）
        assert fs["status"] == "prompted"
        assert fs["dirs"] == ["spec/changes/demo-proposal"]
        alerts = _first_sight_alerts(repo)
        assert len(alerts) == 1
        rec = alerts[0]
        evidence = rec.get("evidence") or ""
        action = rec.get("recommended_action") or ""
        description = rec.get("description") or ""
        # 草案行已不存在：任何按 recommended_action 的处置都不可能把
        # 交付物目录写进 .gitignore
        assert "gitignore草案:" not in evidence
        assert "交付物注记: spec/ 交付物目录不应 ignore，应提交入库" in evidence
        assert "目录集合=spec/changes/demo-proposal" in evidence
        # description 条件化：建议提交入库，无 .gitignore 指引
        assert "仅建议核对归属后提交入库" in description
        assert ".gitignore" not in description
        # recommended_action 条件化：提交入库/迁出，不含追加指引
        assert ".gitignore" not in action
        assert "提交入库" in action
        assert "迁出 spec/" in action
        assert "追加至" not in action

    def test_spec_root_dir_also_exempt(self):
        """全 spec 树未跟踪时归组根目录为 ``spec``（== "spec" 形态）：
        同样豁免草案，仅交付物注记。"""
        repo = _make_repo()
        _write_strays(repo, ["spec/changes/fresh-proposal/proposal.md"])
        r = _make_sweeper(repo).sweep()
        fs = r["untracked"]["first_sight"]
        assert fs["status"] == "prompted"
        assert fs["dirs"] == ["spec"]
        evidence = (_first_sight_alerts(repo)[0]).get("evidence") or ""
        assert "gitignore草案:" not in evidence
        assert "交付物注记: spec/ 交付物目录不应 ignore，应提交入库" in evidence

    def test_runtime_dir_draft_behavior_unchanged(self):
        """回归锚：普通运行时产物目录（build-foo/）草案行为与现行逐字一致。"""
        repo = _make_repo()
        _write_strays(repo, ["build-foo/a.log", "build-foo/b.log"])
        r = _make_sweeper(repo).sweep()
        fs = r["untracked"]["first_sight"]
        assert fs["status"] == "prompted"
        assert fs["dirs"] == ["build-foo"]
        rec = _first_sight_alerts(repo)[0]
        evidence = rec.get("evidence") or ""
        # 草案行 + 成因注释逐字在位
        assert "gitignore草案: build-foo/" in evidence
        assert (
            "gitignore草案: build-foo/（成因注释: 主树 untracked 散件首现"
            "自动起草：运行时产物目录，2 个未跟踪 entry（" in evidence
        )
        assert "滞留，预防性 ignore 后不再产生散件告警）" in evidence
        # description / recommended_action 与现行全文逐字一致（回归锚）
        assert rec.get("description") == (
            "主树 untracked 散件首现提示（周期盘点，info 级只提示不处置）："
            "目录型产物集合 build-foo 首次出现 2 个 untracked entry。"
            "同目录仅提示一次（集合内容增长不重提示），目录消失复位后"
            "再现视为新首现；本提示不启动升级时钟、不派生任何自动处置，"
            "仅建议预防性 ignore"
        )
        assert rec.get("recommended_action") == (
            "建议面（info 级只提示不处置，不唤起人工）：人工核对目录归属后，"
            "将 evidence 中 gitignore 草案行（含成因注释）追加至 .gitignore"
            "（预防性 ignore，一行消除该目录后续散件告警），或将默认落盘"
            "路径移出仓库树/挪入证据落位目录 .fenix/verify-evidence/<spec>/；"
            "本提示不自动执行 ignore 动作（ignore 仍走既有裁决执行器或人工）。"
            "同目录仅提示一次，目录消失复位后再现视为新首现"
        )


# ── 收尾面（2.1）────────────────────────────────────────────────────


class TestSpecReviewDocsFinalizeCommit:
    def test_dirty_spec_dir_committed_and_clean_after(self):
        """有变更：单目录提交，porcelain 复查为净，提交信息注明评审成文。"""
        repo = _make_git_review_repo()
        proposal = repo / "spec" / "changes" / "demo-repair" / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("# demo-repair\n", encoding="utf-8")
        _write_review_result(repo, "demo-repair", "repaired")
        runner = _make_runner(repo)
        head_before, count_before = _head_and_count(repo)
        err = _check_agent_result_artifact(runner, "demo-repair", "spec-review")
        # 结果文件硬门照常放行
        assert err is None
        head_after, count_after = _head_and_count(repo)
        assert count_after == count_before + 1
        assert head_after != head_before
        # porcelain 复查为净：untracked 散件已收口
        assert _porcelain(repo, "spec/changes/demo-repair") == ""
        # 提交信息注明评审成文（形态对齐 arbiter 先例）
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%B"], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout
        assert "spec-review 评审成文留痕收尾提交" in msg
        assert "demo-repair" in msg
        # 提交内容为单目录
        files = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"], cwd=str(repo),
            capture_output=True, text=True,
        ).stdout.split()
        assert files == ["spec/changes/demo-repair/proposal.md"]
        # 结果文件未被收尾动作触碰
        assert _write_review_result(repo, "demo-repair", "repaired").exists()

    def test_clean_spec_dir_no_empty_commit(self):
        """无变更：porcelain 空即跳过，不产空提交（幂等）。"""
        repo = _make_git_review_repo()
        seed = repo / "spec" / "changes" / "demo-approved" / "proposal.md"
        seed.parent.mkdir(parents=True)
        seed.write_text("# demo-approved\n", encoding="utf-8")
        _git("add", "-A", cwd=repo)
        _git("commit", "-q", "-m", "seed demo-approved", cwd=repo)
        _write_review_result(repo, "demo-approved", "approved")
        runner = _make_runner(repo)
        head_before, count_before = _head_and_count(repo)
        err = _check_agent_result_artifact(runner, "demo-approved", "spec-review")
        assert err is None
        head_after, count_after = _head_and_count(repo)
        assert count_after == count_before
        assert head_after == head_before

    def test_rejected_without_docs_dir_noop(self):
        """rejected 未触碰成文目录（目录不存在）：零动作、硬门照常放行。"""
        repo = _make_git_review_repo()
        _write_review_result(repo, "demo-rejected", "rejected")
        runner = _make_runner(repo)
        head_before, count_before = _head_and_count(repo)
        err = _check_agent_result_artifact(runner, "demo-rejected", "spec-review")
        assert err is None
        _, count_after = _head_and_count(repo)
        assert count_after == count_before

    def test_git_error_warning_and_gate_unchanged(self, caplog):
        """git 抛错：仅 WARNING，结果文件硬门照常放行（返回 None）、退出
        路径不变，工作区未被半途改动收口。"""
        repo = _make_git_review_repo()
        proposal = repo / "spec" / "changes" / "demo-boom" / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("# demo-boom\n", encoding="utf-8")
        _write_review_result(repo, "demo-boom", "approved")
        runner = _make_runner(repo)
        with caplog.at_level(
            logging.WARNING, logger="fenixd.agent_runner.result_gate"
        ):
            with mock.patch(
                "core.agent_runner.result_gate.subprocess.run",
                side_effect=OSError("boom"),
            ):
                err = _check_agent_result_artifact(
                    runner, "demo-boom", "spec-review")
        assert err is None  # 结果文件路径语义照常（硬门放行）
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "成文留痕收尾提交失败" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "demo-boom" in warnings[0].getMessage()
        # 未提交：散件仍在（best-effort 失败不留半途状态）
        assert _porcelain(repo, "spec/changes/demo-boom") != ""

    def test_git_status_failure_warning_and_gate_unchanged(self, caplog):
        """git status 失败（rc!=0，如主树非 git 仓/锁异常形态）：仅 WARNING
        留痕、结果文件硬门照常放行（返回 None）、退出路径不变。"""
        repo = _make_git_review_repo()
        proposal = repo / "spec" / "changes" / "demo-nongit" / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("# demo-nongit\n", encoding="utf-8")
        _write_review_result(repo, "demo-nongit", "approved")
        runner = _make_runner(repo)
        probe_fail = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="",
            stderr="fatal: not a git repository",
        )
        with caplog.at_level(
            logging.WARNING, logger="fenixd.agent_runner.result_gate"
        ):
            with mock.patch(
                "core.agent_runner.result_gate.subprocess.run",
                return_value=probe_fail,
            ):
                err = _check_agent_result_artifact(
                    runner, "demo-nongit", "spec-review")
        assert err is None  # 结果文件路径语义照常（硬门放行）
        warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "成文留痕收尾" in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "git status 失败" in warnings[0].getMessage()
        assert "demo-nongit" in warnings[0].getMessage()

    def test_commit_direct_call_three_states(self):
        """直接契约：commit_spec_review_docs 三态返回值（True/False 跳过）。"""
        repo = _make_git_review_repo()
        # 有变更 → True
        proposal = repo / "spec" / "changes" / "demo-direct" / "proposal.md"
        proposal.parent.mkdir(parents=True)
        proposal.write_text("# demo-direct\n", encoding="utf-8")
        assert commit_spec_review_docs(repo, "demo-direct") is True
        assert _porcelain(repo, "spec/changes/demo-direct") == ""
        # 再调（porcelain 空）→ False 幂等跳过
        assert commit_spec_review_docs(repo, "demo-direct") is False
        # 目录缺失 → False 零动作
        assert commit_spec_review_docs(repo, "demo-missing") is False
        # spec 名形态守卫（路径注入面）→ False 零动作
        assert commit_spec_review_docs(repo, "../evil") is False
        assert commit_spec_review_docs(repo, "a/b") is False
        assert commit_spec_review_docs(repo, "") is False
