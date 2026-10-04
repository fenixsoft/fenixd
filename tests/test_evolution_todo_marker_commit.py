"""evo-add-todo-marker-commit-on-write：todo.md 标记写后即时提交。

覆盖三个规定场景（tasks 2.1）：
- tracked 项目写后产生恰一个含 .fenix/todo.md 的提交且工作区对该文件干净；
- untracked 项目（含目录非 git 仓库）跳过提交且不报错；
- 提交失败（index.lock 竞争）降级为留痕，不抛错、不回滚写入。

另覆盖批末合并提交（tasks 1.3）：ingest_item 批量路径不逐条提交，由
``commit_todo_marker`` 对一轮涉及的项目各合并提交一次。
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.evolution import (  # noqa: E402
    commit_todo_marker,
    ingest_item,
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


@pytest.mark.parametrize("kwargs", [{"project_name": "ghost"}, {}])
def test_commit_todo_marker_unresolvable_project(monkeypatch, kwargs):
    """名称解析失败（未注册）/ 未提供项目参数：返回 False 且不抛错。"""
    monkeypatch.setattr(
        "core.evolution._resolve_project_path_by_name", lambda name: None
    )
    assert commit_todo_marker(**kwargs) is False
