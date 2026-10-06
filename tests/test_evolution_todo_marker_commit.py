"""evo-add-todo-marker-commit-on-write：todo.md 标记写后即时提交。

覆盖三个规定场景（tasks 2.1）：
- tracked 项目写后产生恰一个含 .fenix/todo.md 的提交且工作区对该文件干净；
- untracked 项目（含目录非 git 仓库）跳过提交且不报错；
- 提交失败（index.lock 竞争）降级为留痕，不抛错、不回滚写入。

另覆盖批末合并提交（tasks 1.3）：ingest_item 批量路径不逐条提交，由
``commit_todo_marker`` 对一轮涉及的项目各合并提交一次。

evo-evolution-accept-marker-batching：自动接受批路径同范式——
auto_accept_pending 逐条 defer、批末对本项目恰一枚合并提交且消息附条目 id
明细；dashboard 手动单条接受（缺省开关）保持写后即时提交不回归。
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.evolution import (  # noqa: E402
    accept_item,
    auto_accept_pending,
    commit_todo_marker,
    draft_dir,
    ingest_item,
    upsert_item,
    write_todo_marker,
)

SAMPLE = (
    "## 2026-09-13\n\n"
    "### 浪费\n"
    "- **问题甲**\n"
    "  - 影响：i1\n"
    "  - 证据：e1\n"
    "  - 调查评估：a1\n"
    "  - 建议：s1\n\n"
    "### 可改进\n"
    "- **问题乙**\n"
    "  - 影响：i2\n"
    "  - 证据：e2\n"
    "  - 调查评估：a2\n"
    "  - 建议：s2\n"
)

ITEM = {
    "project": "proj",
    "date_section": "2026-09-13",
    "section": "浪费",
    "title": "问题甲",
    "impact": "i1",
    "evidence": "e1",
    "analysis": "a1",
    "suggestion": "s1",
    "verdict": {
        "worth_spec": True,
        "problem_exists": "yes",
        "suggestion_sound": "yes",
        "rationale": "r",
    },
}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30
    )


def _tracked_repo(tmp_path: Path) -> Path:
    """带 tracked ``.fenix/todo.md`` 初始提交的最小 git 仓库。

    不配置 remote：push 自然失败降级 WARNING（与消费项目 push 故障同路径），
    commit 仍产生、函数仍报成功。
    """
    repo = tmp_path / "proj"
    (repo / ".fenix").mkdir(parents=True)
    (repo / ".fenix" / "todo.md").write_text(SAMPLE, encoding="utf-8")
    assert _git(repo, "init", "-q").returncode == 0
    _git(repo, "config", "user.name", "Fenix Test")
    _git(repo, "config", "user.email", "test@fenix.local")
    _git(repo, "add", "--", ".fenix/todo.md")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _commit_count(repo: Path) -> int:
    out = _git(repo, "rev-list", "--count", "--all").stdout.strip()
    return int(out) if out.isdigit() else 0


def _todo_commit_count(repo: Path) -> int:
    """仅统计触碰 ``.fenix/todo.md`` 的提交数。

    accept 路径另有 spec/changes 立项提交（逐条一次，属立项语义不属标记
    噪声），断言标记提交数必须按 pathspec 过滤，不能用全量提交数。
    """
    out = _git(repo, "rev-list", "--count", "HEAD", "--", ".fenix/todo.md").stdout.strip()
    return int(out) if out.isdigit() else 0


def _head_files(repo: Path) -> list:
    out = _git(repo, "show", "--pretty=format:", "--name-only", "HEAD").stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


class TestTrackedCommit:
    """场景一：tracked 项目写后恰一枚提交、工作区干净。"""

    def test_write_produces_single_commit_and_clean_worktree(self, tmp_path):
        repo = _tracked_repo(tmp_path)
        base = _commit_count(repo)

        assert write_todo_marker(ITEM, project_path=repo) is True

        # 恰一枚新提交，且仅含 .fenix/todo.md
        assert _commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        subject = _git(repo, "log", "-1", "--pretty=%s").stdout.strip()
        assert subject.startswith("[fenix] evolution: 自进化标记回写 ")
        # 工作区对该文件干净（滞留盘点不再看到该指纹）
        status = _git(repo, "status", "--porcelain", "--", ".fenix/todo.md").stdout
        assert status.strip() == ""

    def test_pathspec_does_not_absorb_unrelated_staged(self, tmp_path):
        """commit 带 pathspec：索引里并发暂存的其他内容不被卷入并外泄。"""
        repo = _tracked_repo(tmp_path)
        (repo / "README.md").write_text("并发暂存的自动化产物", encoding="utf-8")
        assert _git(repo, "add", "--", "README.md").returncode == 0

        assert write_todo_marker(ITEM, project_path=repo) is True

        assert _head_files(repo) == [".fenix/todo.md"]
        staged = _git(repo, "status", "--porcelain").stdout
        assert "README.md" in staged


class TestUntrackedSkip:
    """场景二：untracked 项目跳过提交且不报错。"""

    def test_untracked_todo_skips_commit(self, tmp_path):
        repo = tmp_path / "proj"
        (repo / ".fenix").mkdir(parents=True)
        (repo / ".fenix" / "todo.md").write_text(SAMPLE, encoding="utf-8")
        assert _git(repo, "init", "-q").returncode == 0
        # todo.md 未被 git 跟踪（仓库尚无任何提交）
        base = _commit_count(repo)

        # 写入成功、跳过提交、不报错
        assert write_todo_marker(ITEM, project_path=repo) is True
        assert _commit_count(repo) == base
        assert "自进化" in (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")

    def test_non_git_dir_skips_commit_without_error(self, tmp_path):
        proj = tmp_path / "plain"
        (proj / ".fenix").mkdir(parents=True)
        (proj / ".fenix" / "todo.md").write_text(SAMPLE, encoding="utf-8")

        # 目录非 git 仓库（ls-files 非零退出）：同视为未 tracked，不抛错
        assert write_todo_marker(ITEM, project_path=proj) is True


class TestCommitFailureDegrade:
    """场景三：提交失败降级留痕，不抛错、不回滚写入。"""

    def test_index_lock_competition_degrades_without_raise(self, tmp_path):
        repo = _tracked_repo(tmp_path)
        base = _commit_count(repo)
        # 模拟并发 git 进程持有的 index.lock 在场
        (repo / ".git" / "index.lock").write_text("", encoding="utf-8")

        assert write_todo_marker(ITEM, project_path=repo) is True

        # 无新提交，但写入不回滚
        assert _commit_count(repo) == base
        assert "自进化" in (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")

    def test_push_failure_degrades_but_commit_stays(self, tmp_path):
        """push 失败（无 remote）降级 WARNING：commit 已产生、函数仍报成功。"""
        repo = _tracked_repo(tmp_path)
        base = _commit_count(repo)

        assert write_todo_marker(ITEM, project_path=repo) is True
        assert _commit_count(repo) == base + 1


class TestBatchMergedCommit:
    """tasks 1.3：ingest_item 批量路径不逐条提交，批末按项目合并提交一次。"""

    def test_ingest_batch_defers_commit_to_orchestrator(self, tmp_path, monkeypatch):
        repo = _tracked_repo(tmp_path)
        # ingest_item 的标记回写按条目 project 名经 registry 解析（MUST NOT
        # 显式传 project_path），单测内把解析器钉到临时仓库
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        base = _commit_count(repo)
        analyzed = dict(
            ITEM,
            title="问题甲",
            verdict={
                "worth_spec": False,
                "problem_exists": "yes",
                "suggestion_sound": "partial",
                "rationale": "r",
            },
        )

        assert ingest_item(analyzed, repo) == "analyzed"
        assert ingest_item(
            dict(analyzed, title="问题乙", section="可改进", impact="i2",
                 evidence="e2", analysis="a2", suggestion="s2"),
            repo,
        ) == "analyzed"

        # 批量路径逐条写标记但不逐条提交（避免提交风暴）
        assert _commit_count(repo) == base

        # 编排层批末合并提交：两条标记收进恰一枚提交
        assert commit_todo_marker(project_path=repo) is True
        assert _commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        text = (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert text.count("自进化：") == 2

    def test_ingest_pending_batch_defers_commit(self, tmp_path, monkeypatch):
        """pending 分支同属批量路径（BUG-01 回归点）：逐条不提交，批末合并。"""
        repo = _tracked_repo(tmp_path)
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        # 走到 pending 分支：草稿落盘与 lint 均通过（stub 掉真实物化，
        # 聚焦提交开关行为本身）
        monkeypatch.setattr(
            "core.evolution.materialize_draft",
            lambda item, proot: (Path(proot) / "spec" / "changes" / "evo-fake", None),
        )
        monkeypatch.setattr("core.evolution.lint_draft", lambda d, proot: [])
        base = _commit_count(repo)

        assert ingest_item(ITEM, repo) == "pending"
        assert ingest_item(
            dict(ITEM, title="问题乙", section="可改进", impact="i2",
                 evidence="e2", analysis="a2", suggestion="s2"),
            repo,
        ) == "pending"

        # pending 逐条写标记但不逐条提交
        assert _commit_count(repo) == base

        # 编排层批末合并提交：两条 pending 标记收进恰一枚提交
        assert commit_todo_marker(project_path=repo) is True
        assert _commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        text = (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert text.count("自进化：") == 2

    def test_merged_commit_noop_when_nothing_changed(self, tmp_path):
        """无未提交改动时批末提交为良性 no-op，不报错。"""
        repo = _tracked_repo(tmp_path)
        base = _commit_count(repo)

        assert commit_todo_marker(project_path=repo) is False
        assert _commit_count(repo) == base

    def test_batch_commit_skips_non_git_project(self, tmp_path):
        proj = tmp_path / "plain"
        (proj / ".fenix").mkdir(parents=True)
        (proj / ".fenix" / "todo.md").write_text(SAMPLE, encoding="utf-8")

        # 非 git 仓库：合并提交跳过且不抛错
        assert commit_todo_marker(project_path=proj) is False


class TestAutoAcceptBatchMergedCommit:
    """evo-evolution-accept-marker-batching：接受批批末恰一枚合并提交。"""

    def _seed_pending(self, repo: Path, eid: str, title: str, spec_name: str, section: str) -> None:
        """建一条 pending 条目 + 草稿目录（标题须命中 todo.md 既有条目）。"""
        upsert_item(repo, {
            "id": eid, "project": "proj", "date_section": "2026-09-13",
            "section": section, "title": title, "impact": "i", "evidence": "e",
            "analysis": "a", "suggestion": "s",
            "verdict": {"worth_spec": True, "problem_exists": "yes",
                        "suggestion_sound": "yes", "rationale": "r"},
            "analysis_md": "md",
            "spec": {"name": spec_name, "capability": "evo-test",
                     "proposal_md": "# P", "design_md": "# D",
                     "spec_md": "# S",
                     "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n"},
            "spec_summary": "", "degraded": None,
            "created_at": "2026-09-13T00:00:00Z", "decided_at": None,
            "decided_by": None, "spec_name": None,
            "violations": None, "draft_failed_reason": None,
            "status": "pending",
        })
        d = draft_dir(repo, eid)
        d.mkdir(parents=True)
        (d / "proposal.md").write_text("p", encoding="utf-8")

    def test_auto_accept_batch_produces_single_commit_with_ids(self, tmp_path, monkeypatch):
        """场景：一批接受 N（≥2）条 → 恰一枚 todo.md 提交且消息含 id 明细。"""
        repo = _tracked_repo(tmp_path)
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        self._seed_pending(repo, "aaaa1111aaaa", "问题甲", "batch-a", "浪费")
        self._seed_pending(repo, "bbbb2222bbbb", "问题乙", "batch-b", "可改进")
        base = _todo_commit_count(repo)

        summary = auto_accept_pending(repo, None)

        assert summary == dict(summary, total=2, accepted=2, failed=0)
        # 逐条 defer + 批末合并：标记翻转只收进恰一枚提交（spec/changes
        # 立项提交逐条一次但按 pathspec 限定，不触碰 todo.md）
        assert _todo_commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        body = _git(repo, "log", "-1", "--pretty=%B").stdout
        assert "- aaaa1111aaaa" in body
        assert "- bbbb2222bbbb" in body
        assert body.startswith("[fenix] evolution: 自进化标记回写 ")
        text = (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")
        assert text.count("自进化：") == 2

    def test_auto_accept_empty_batch_skips_batch_commit(self, tmp_path, monkeypatch):
        """批内无可接受条目（含全部失败）：不调批末合并提交（良性 no-op 免日志）。"""
        repo = _tracked_repo(tmp_path)
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        base = _commit_count(repo)

        summary = auto_accept_pending(repo, None)

        assert summary["total"] == 0
        assert _commit_count(repo) == base

    def test_defer_commit_switch_writes_without_commit(self, tmp_path, monkeypatch):
        """defer_commit=True：标记落写但不逐条提交，批末合并补一枚带明细的提交。"""
        repo = _tracked_repo(tmp_path)
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        self._seed_pending(repo, "cccc3333cccc", "问题甲", "defer-a", "浪费")
        base = _todo_commit_count(repo)

        result = accept_item(
            "cccc3333cccc", repo, None, decided_by="auto", defer_commit=True
        )

        assert result["ok"] is True
        # 逐条 defer：写后无 todo.md 提交
        assert _todo_commit_count(repo) == base
        # 批末合并提交：恰一枚，消息附条目 id 明细
        assert commit_todo_marker(
            project_path=repo,
            message_suffix="接受条目（1 条）:\n- cccc3333cccc",
        ) is True
        assert _todo_commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        assert "- cccc3333cccc" in _git(repo, "log", "-1", "--pretty=%B").stdout

    def test_manual_single_accept_still_commits_immediately(self, tmp_path, monkeypatch):
        """场景：dashboard 手动单条接受（缺省 defer_commit=False）维持写后即时提交。"""
        repo = _tracked_repo(tmp_path)
        monkeypatch.setattr(
            "core.evolution._resolve_project_path_by_name", lambda name: repo
        )
        self._seed_pending(repo, "d4d4d4d4d4d4", "问题甲", "manual-a", "浪费")
        base = _todo_commit_count(repo)

        # 与 evolution_routes 手动端点同形态调用（不传 defer_commit）
        result = accept_item("d4d4d4d4d4d4", repo, None, decided_by="manual")

        assert result["ok"] is True
        assert _todo_commit_count(repo) == base + 1
        assert _head_files(repo) == [".fenix/todo.md"]
        msg = _git(repo, "log", "-1", "--pretty=%B").stdout
        assert msg.startswith("[fenix] evolution: 自进化标记回写 ")
        # 缺省单条路径消息不带条目 id 明细正文（形态与既有行为一致）
        assert "d4d4d4d4d4d4" not in msg


@pytest.mark.parametrize("kwargs", [{"project_name": "ghost"}, {}])
def test_commit_todo_marker_unresolvable_project(monkeypatch, kwargs):
    """名称解析失败（未注册）/ 未提供项目参数：返回 False 且不抛错。"""
    monkeypatch.setattr(
        "core.evolution._resolve_project_path_by_name", lambda name: None
    )
    assert commit_todo_marker(**kwargs) is False
