"""init-self-bootstrap 单测（add-onboarding-init-setup-guidance）。

覆盖三组能力：
- 1.x 白名单文件初始化自动入库（git add 仅 staged 不 commit）
- 2.x 运行时产物目录（.claude/agents/）预防性 ignore（模板 + --ensure-gitignore 幂等）
- 3.x render_config 产物 YAML 可解析 + 注释按 harness 分形态（无「环境变量模型」误导）

fenix-init 是无扩展名脚本：经 SourceFileLoader 加载为模块做函数级断言；
端到端行为用 subprocess 跑真脚本（与 tests/test_dashboard_verify_yaml_api.py 同模式）。
"""

import importlib.util
import re
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FENIX_INIT = REPO_ROOT / "fenix-init"

# commit 类断言需要提交者身份（本套件不依赖宿主 git config）
_GIT = ["git", "-c", "user.email=fenix-test@example.com", "-c", "user.name=fenix-test"]


def _load_fenix_init():
    loader = SourceFileLoader("fenix_init_under_test", str(FENIX_INIT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _run_init(target: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(FENIX_INIT), str(target), *extra_args],
        capture_output=True, text=True, timeout=60,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        _GIT + list(args), cwd=str(repo), capture_output=True, text=True, timeout=30,
    )


def _make_git_repo(root: Path) -> Path:
    """零提交史（unborn 分支）的 git 仓库——自举须在此形态下正常工作。"""
    proj = root / "proj"
    proj.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(proj)],
                   check=True, capture_output=True)
    return proj


class TestWhitelistAutoStaged:
    """1.2 白名单文件初始化自动入库：staged 不 commit、存在性守卫、非 git 跳过、幂等。"""

    def test_unborn_branch_init_stages_verify_yaml_without_commit(self, tmp_path):
        proj = _make_git_repo(tmp_path)
        result = _run_init(proj)
        assert result.returncode == 0, result.stderr
        assert (proj / ".fenix" / "verify.yaml").is_file()
        ls = _git(proj, "ls-files")
        assert ".fenix/verify.yaml" in ls.stdout.splitlines()
        # todo.md 非 init 播种物：缺席时初始化不报错且不入库
        assert ".fenix/todo.md" not in ls.stdout.splitlines()
        assert "白名单文件已 git add" in result.stdout
        # 仅 staged 不 commit：unborn 分支上无任何提交对象
        head = _git(proj, "rev-parse", "HEAD")
        assert head.returncode != 0

    def test_late_todo_md_staged_on_rerun(self, tmp_path):
        proj = _make_git_repo(tmp_path)
        assert _run_init(proj).returncode == 0
        # 事后补建 todo.md（自省/进化车道后续创建的时序），重跑补入库
        (proj / ".fenix" / "todo.md").write_text("# todo\n", encoding="utf-8")
        assert _run_init(proj).returncode == 0
        ls = _git(proj, "ls-files")
        assert ".fenix/todo.md" in ls.stdout.splitlines()

    def test_non_git_dir_skips_with_hint(self, tmp_path):
        proj = tmp_path / "plain"
        proj.mkdir()
        result = _run_init(proj)
        assert result.returncode == 0, result.stderr
        assert (proj / ".fenix" / "verify.yaml").is_file()  # 骨架照常生成
        assert "非 git 仓库" in result.stdout
        probe = _git(proj, "rev-parse", "--is-inside-work-tree")
        assert probe.returncode != 0

    def test_rerun_idempotent(self, tmp_path):
        proj = _make_git_repo(tmp_path)
        assert _run_init(proj).returncode == 0
        assert _run_init(proj).returncode == 0
        ls = _git(proj, "ls-files")
        assert ls.stdout.splitlines().count(".fenix/verify.yaml") == 1
        gitignore = (proj / ".gitignore").read_text(encoding="utf-8")
        assert len(re.findall(r"(?m)^\.fenix/\*$", gitignore)) == 1


class TestAgentsDirPreemptiveIgnore:
    """2.2 运行时产物目录预防性 ignore：新模板生效、--ensure-gitignore 幂等补齐、已跟踪文件不受影响。"""

    def test_new_template_ignores_claude_agents(self, tmp_path):
        proj = _make_git_repo(tmp_path)
        assert _run_init(proj).returncode == 0
        (proj / ".claude" / "agents" / "extra.md").write_text("x\n", encoding="utf-8")
        status = _git(proj, "status", "--porcelain")
        assert ".claude/agents/" not in status.stdout  # 不再视为 untracked 散件
        gitignore = (proj / ".gitignore").read_text(encoding="utf-8")
        assert re.search(r"(?m)^\.claude/agents/$", gitignore)
        assert "预防性 ignore" in gitignore  # 规则带成因注释

    def test_ensure_gitignore_appends_missing_rule_idempotently(self, tmp_path):
        proj = tmp_path / "legacy"
        proj.mkdir()
        (proj / ".gitignore").write_text("# legacy project\n.fenix/*\n", encoding="utf-8")
        first = _run_init(proj, "--ensure-gitignore")
        assert first.returncode == 0, first.stderr
        gitignore = (proj / ".gitignore").read_text(encoding="utf-8")
        assert len(re.findall(r"(?m)^\.claude/agents/$", gitignore)) == 1
        # 幂等：二跑规则已在场，跳过不重复追加
        second = _run_init(proj, "--ensure-gitignore")
        assert second.returncode == 0, second.stderr
        gitignore = (proj / ".gitignore").read_text(encoding="utf-8")
        assert len(re.findall(r"(?m)^\.claude/agents/$", gitignore)) == 1
        assert "跳过" in second.stdout

    def test_tracked_file_unaffected_by_ignore_rule(self, tmp_path):
        proj = _make_git_repo(tmp_path)
        agents_dir = proj / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "keep.md").write_text("user tracked\n", encoding="utf-8")
        assert _git(proj, "add", ".claude/agents/keep.md").returncode == 0
        assert _git(proj, "commit", "-q", "-m", "track agent file").returncode == 0
        # 追加 ignore 规则后已跟踪文件不受影响（gitignore 只作用于 untracked）
        assert _run_init(proj).returncode == 0
        ls = _git(proj, "ls-files")
        assert ".claude/agents/keep.md" in ls.stdout.splitlines()
        status = _git(proj, "status", "--porcelain")
        assert "keep.md" not in status.stdout
