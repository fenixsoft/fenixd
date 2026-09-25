"""路由地图生成协议测试（add-planner-efficiency：planner-route-map）。

覆盖 spec 全部 Scenario：
- 生成器存在时 planner 前生成地图（生成触发、条目含 文件:行号 出处）；
- HEAD 键控复用：HEAD 未变跳过生成器，HEAD 变更重生成；
- prompt 注入措辞为「索引非穷尽 + 取证义务」；
- fail-open：无生成器/生成器失败不阻塞验证管线；
- 静态地图兼容：主树 `.fenix/route-map.md` 注入；
- 生成器自检：覆盖差异告警（差 ≥30% 输出 warning）。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.runner import (
    ROUTE_MAP_REL,
    ensure_route_map,
)
from test_agent_runner import FakeLogger, make_runner
from test_agent_prompt_files import _mk_spec_dir


def _git(wt: Path, *args: str) -> str:
    """在 worktree 内执行 git 命令，返回 stdout。"""
    res = subprocess.run(
        ["git", "-C", str(wt), *args],
        capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, f"git {args} 失败: {res.stderr}"
    return res.stdout.strip()


def _init_git_repo(wt: Path) -> str:
    """把目录初始化为 git 仓库并做首提交，返回 HEAD。"""
    wt.mkdir(parents=True, exist_ok=True)
    _git(wt, "init", "-q")
    _git(wt, "config", "user.email", "t@example.com")
    _git(wt, "config", "user.name", "tester")
    (wt / ".gitignore").write_text(".fenix/\n", encoding="utf-8")
    (wt / "hello.txt").write_text("hello\n", encoding="utf-8")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "init")
    return _git(wt, "rev-parse", "HEAD")


def _write_generator(wt: Path, exit_code: int = 0,
                     counter_path: Path | None = None,
                     output: str = "# 地图\n- `/api/x` (app.py:1)\n") -> Path:
    """写入一个计数器递增的生成器脚本。"""
    gen = wt / "bin"
    gen.mkdir(parents=True, exist_ok=True)
    lines = [
        "#!/usr/bin/env python3",
        "import sys, pathlib",
        "wt = pathlib.Path(sys.argv[1])",
    ]
    if counter_path is not None:
        lines.append(f"p = pathlib.Path({str(counter_path)!r})")
        lines.append("p.parent.mkdir(parents=True, exist_ok=True)")
        lines.append("p.write_text(str(int(p.read_text()) + 1) if p.exists() else '1')")
    lines.append(f"print({output!r})")
    lines.append(f"sys.exit({exit_code})")
    gen_path = gen / "gen-route-map.py"
    gen_path.write_text("\n".join(lines), encoding="utf-8")
    gen_path.chmod(0o755)
    return gen_path


# ── 生成触发 / HEAD 复用 / HEAD 变更重生成 ───────────────────────────


class TestGenerationTrigger:
    """Scenario: 生成器存在时 planner 前生成地图。"""

    def test_generator_exists_writes_map(self, tmp_path):
        wt = tmp_path / "wt"
        counter = tmp_path / "counter.txt"
        _init_git_repo(wt)
        _write_generator(wt, counter_path=counter)
        logger = FakeLogger()
        out = ensure_route_map(wt, wt, logger)
        assert out is not None
        assert out == wt / ROUTE_MAP_REL
        assert out.is_file()
        content = out.read_text(encoding="utf-8")
        assert "/api/x" in content
        assert "app.py:1" in content  # 条目自带 文件:行号 出处
        assert int(counter.read_text()) == 1

    def test_no_generator_fail_open(self, tmp_path):
        wt = tmp_path / "wt"
        _init_git_repo(wt)
        logger = FakeLogger()
        assert ensure_route_map(wt, wt, logger) is None
        assert not (wt / ROUTE_MAP_REL).exists()

    def test_generator_failure_fail_open(self, tmp_path):
        wt = tmp_path / "wt"
        _init_git_repo(wt)
        fake = FakeLogger()
        _write_generator(wt, exit_code=3)
        assert ensure_route_map(wt, wt, fake) is None
        assert not (wt / ROUTE_MAP_REL).exists()

    def test_generator_timeout_fail_open(self, tmp_path, monkeypatch):
        wt = tmp_path / "wt"
        _init_git_repo(wt)
        fake = FakeLogger()
        gen = _write_generator(wt)

        def _hang(*a, **k):
            raise subprocess.TimeoutExpired(cmd="gen", timeout=60)

        monkeypatch.setattr(subprocess, "run", _hang)
        assert ensure_route_map(wt, wt, fake, timeout=5) is None
        assert not (wt / ROUTE_MAP_REL).exists()


class TestHeadReuse:
    """Scenario: replan 循环不重复生成 / HEAD 变更后重生成。"""

    def test_unchanged_head_skips_generator(self, tmp_path):
        wt = tmp_path / "wt"
        counter = tmp_path / "counter.txt"
        _init_git_repo(wt)
        _write_generator(wt, counter_path=counter)
        logger = FakeLogger()
        ensure_route_map(wt, wt, logger)
        ensure_route_map(wt, wt, logger)  # HEAD 未变 → 复用
        assert int(counter.read_text()) == 1  # 生成器只跑了一次

    def test_changed_head_regenerates(self, tmp_path):
        wt = tmp_path / "wt"
        counter = tmp_path / "counter.txt"
        _init_git_repo(wt)
        _write_generator(wt, counter_path=counter)
        logger = FakeLogger()
        ensure_route_map(wt, wt, logger)
        # 修改源码重新提交 → HEAD 变更 → 重新生成
        (wt / "hello.txt").write_text("hello2\n", encoding="utf-8")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-q", "-m", "change")
        ensure_route_map(wt, wt, logger)
        assert int(counter.read_text()) == 2


def _planner_prompt(proot, wt_path=None):
    """构建 planner-plan prompt（缺省无项目附加提示词目录，纯路由地图注入）。"""
    runner = make_runner(proot)
    return runner._prompt_builder._build_prompt("demo", "planner-plan", wt_path=wt_path)


# ── prompt 注入措辞（索引非穷尽 + 取证义务）──────────────────────────


class TestPromptInjection:
    """Scenario: 注入后保留独立取证许可证。"""

    def test_worktree_map_injected_with_wording(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        wt = proot / "wt"
        _init_git_repo(wt)
        _write_generator(wt, output="# 地图\n- `/api/login` (app.py:10)\n")
        ensure_route_map(wt, proot, FakeLogger())
        prompt = _planner_prompt(proot, wt_path=wt)
        assert "路由地图" in prompt
        assert "/api/login" in prompt
        assert "已知入口索引、非穷尽清单" in prompt
        # 取证义务提醒：地图外仍须自行源码取证
        assert "仍须自行源码取证" in prompt
        assert "app.py:10" in prompt

    def test_planner_judge_not_injected(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        wt = proot / "wt"
        _init_git_repo(wt)
        _write_generator(wt)
        ensure_route_map(wt, proot, FakeLogger())
        runner = make_runner(proot)
        prompt = runner._prompt_builder._build_prompt(
            "demo", "planner-judge", wt_path=wt)
        assert "路由地图" not in prompt

    def test_no_map_zero_injection(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = _planner_prompt(proot, wt_path=None)
        assert "路由地图" not in prompt


# ── 静态地图兼容（主树 .fenix/route-map.md）───────────────────────────


class TestStaticMap:
    """Scenario: 静态地图被注入（无生成器/生成失败但有主树静态图）。"""

    def test_static_map_injected_when_no_worktree_map(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        static = proot / ROUTE_MAP_REL
        static.parent.mkdir(parents=True, exist_ok=True)
        static.write_text("# 静态地图\n- `/static/route` (main.py:3)\n",
                          encoding="utf-8")
        prompt = _planner_prompt(proot, wt_path=proot / "nope")
        assert "路由地图" in prompt
        assert "/static/route" in prompt
        assert "已知入口索引、非穷尽清单" in prompt

    def test_static_map_zero_injection_when_absent(self, tmp_path):
        proot = tmp_path / "proj"
        _mk_spec_dir(proot, "demo")
        prompt = _planner_prompt(proot, wt_path=proot / "nope")
        assert "路由地图" not in prompt


# ── 框架接入点 scaffold（_execute_agent_inner planner 分支 hook）─────


class TestRunnerIntegration:
    """生成 hook 在 planner worktree 就绪后触发（fail-open 不阻塞派发）。"""

    def test_ensure_planner_route_map_no_worktree_is_noop(self, tmp_path):
        runner = make_runner(tmp_path / "proj")
        runner.worktree_manager = type(
            "WM", (), {"find_implementer_worktree": lambda self, s: None})()
        assert runner.ensure_planner_route_map("demo") is None

    def test_ensure_planner_route_map_with_worktree(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        wt = proot / "claude-wt"
        _init_git_repo(wt)
        counter = tmp_path / "counter.txt"
        _write_generator(wt, counter_path=counter)
        runner = make_runner(proot)
        runner.worktree_manager = type(
            "WM", (), {"find_implementer_worktree": lambda self, s: wt})()
        out = runner.ensure_planner_route_map("demo")
        assert out is not None
        assert (wt / ROUTE_MAP_REL).is_file()
        assert int(counter.read_text()) == 1
        # 再次调用（HEAD 未变）复用
        runner.ensure_planner_route_map("demo")
        assert int(counter.read_text()) == 1


# ── 生成器参考实现自检（bin/gen-route-map.py）────────────────────────


class TestGeneratorSelfCheck:
    """Scenario: 覆盖差异告警（差 ≥30% 输出 warning，不阻塞产出）。"""

    @staticmethod
    def _run_generator(root: Path) -> str:
        gen = Path(__file__).resolve().parent.parent / "bin" / "gen-route-map.py"
        res = subprocess.run(
            [sys.executable, str(gen), str(root)],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0, res.stderr
        return res.stdout

    def test_generator_emits_entries_with_file_line(self, tmp_path):
        """dashboard 参考实现：server.py 路由表条目含 `文件:行号` 出处。"""
        root = tmp_path / "root"
        server = root / "core" / "dashboard"
        server.mkdir(parents=True)
        (server / "server.py").write_text(
            'def _handle_api(self, path, query):\n'
            '    if path == "/api/projects":\n'
            '        return self._api_projects()\n',
            encoding="utf-8",
        )
        out = self._run_generator(root)
        assert "/api/projects" in out
        assert "server.py:" in out  # 出处含 文件:行号

    def test_generator_emits_static_footer_wording(self, tmp_path):
        root = tmp_path / "root"
        (root / "core" / "dashboard").mkdir(parents=True)
        (root / "core" / "dashboard" / "server.py").write_text(
            'def _handle_api(self, path):\n'
            '    if path == "/api/x":\n'
            '        pass\n',
            encoding="utf-8",
        )
        out = self._run_generator(root)
        assert "已知入口索引、非穷尽清单" in out

    def test_generator_self_check_warns_on_coverage_gap(self, tmp_path):
        """启发式候选（grep 全量 /api/ 出现）显著高于解析条目数 → warning。"""
        root = tmp_path / "root"
        server = root / "core" / "dashboard"
        server.mkdir(parents=True)
        # 大量 /api/ 字符串出现在生成器不匹配的方法中（如 docstring/非 path== 分支）
        lines = ["def _handle_api(self, path, query):"]
        for i in range(30):
            lines.append(f'    self._log("/api/unparseable-{i}")')
        lines.append('    if path == "/api/one":')
        lines.append("        pass")
        (server / "server.py").write_text("\n".join(lines), encoding="utf-8")
        out = self._run_generator(root)
        assert "覆盖自检" in out
        assert "≥30%" in out

class TestRepoCoverageRegression:
    """本仓覆盖回归（refactor-giant-classes D4 task 4.6）。

    路由迁入 `routes/` 子包 + 表驱动后，gen-route-map 扫描源同步为
    routes/ 子包全文件 + server.py——对本仓生成地图条目数不得少于
    迁移前（迁移前 server.py 的 _handle_api 系列分支约 20+ API 路由）。

    断言：本仓生成的地图含 ≥15 条 API 路由（重构前 server.py 的
    `path == "/api/..."` 分支数），且 routes/base.py 表驱动条目被收录。
    条目数减少 = 扫描源同步失败（静默退化）。
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def _run(self) -> str:
        gen = self.REPO_ROOT / "bin" / "gen-route-map.py"
        res = subprocess.run(
            [sys.executable, str(gen), str(self.REPO_ROOT)],
            capture_output=True, text=True, timeout=60,
        )
        assert res.returncode == 0, res.stderr
        return res.stdout

    def test_repo_api_entries_not_reduced(self):
        """本仓地图 API 条目数 ≥ 迁移前基线（15 条），表驱动条目被收录。"""
        out = self._run()
        api_lines = [
            l for l in out.splitlines()
            if l.startswith("- `") and ("[GET]" in l or "[POST]" in l or "[DELETE]" in l)
        ]
        # 迁移前 server.py _handle_api/_handle_api_post/_handle_api_delete
        # 的 `path == "/api/..."` 分支：GET 18 + POST 27 + DELETE 2 = 47。
        # 表驱动路由表收录后应保持 ≥15（宽松下限，防扫描源同步退化）。
        assert len(api_lines) >= 15, (
            f"本仓 API 路由条目仅 {len(api_lines)}（<15）："
            "gen-route-map 扫描源未同步 routes/ 子包表驱动路由表？"
        )
        # 表驱动路由表的精确条目被收录（routes/base.py 主源）
        assert any('`/api/projects`' in l for l in api_lines), (
            "表驱动路由 /api/projects 未收录——scan_server_routes 未读 routes/base.py？"
        )
        assert any('`/api/spec-freeze`' in l for l in api_lines), (
            "表驱动路由 /api/spec-freeze 未收录——POST 表扫描失败？"
        )

    def test_regex_table_entries_captured_with_raw_string(self):
        """routes/base.py 表驱动 regex 条目（含 raw-string 形态）被收录。

        code-review item 1fd7cf361e88：条目正则此前不兼容 r"..." 前缀，
        全部 regex 条目落入 skipped、地图只余 exact 条目。
        """
        base = self.REPO_ROOT / "core" / "dashboard" / "routes" / "base.py"
        patterns = re.findall(
            r'\(\s*"regex",\s*r?"([^"]+)"', base.read_text(encoding="utf-8")
        )
        assert patterns, "routes/base.py 无 regex 条目（用例前提失效）"
        out = self._run()
        # 生成器展示口径：regex pattern 取 ^/ 前缀、去 ^ 截 $（如
        # r"^/api/specs/([^/]+)$" → `/api/specs/([^/]+)`）
        missing = [
            p for p in patterns
            if f"`{p.lstrip('^').split('$')[0]}`" not in out
        ]
        assert not missing, f"regex 表驱动条目未被收录: {missing}"
