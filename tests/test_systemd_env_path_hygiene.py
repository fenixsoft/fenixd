"""tests/test_systemd_env_path_hygiene.py — add-dispatch-precheck-true-fallback 任务 3.4

PATH 卫生链路（core/systemd_hosting.py + bin/migrate_to_systemd.py）：
- 3.1 捕获期基线并集：最小 PATH → 按序补齐尾部并在候选稿头部留痕；完整 PATH →
  逐字节不变（apply_path_baseline 恒等、无留痕头）。
- 3.2 unit 模板保底行：render_project_unit 恒含 ``Environment=PATH=<基线>``。
- 2.4 落盘侧幂等：append_env_path_dirs 二次调用零追加。
- 3.3 迁移摘要：dry-run 与正式捕获都在 plan 出「PATH 卫生：完整/补齐」结论行。
"""
import importlib.util
from pathlib import Path

import pytest

from core import systemd_hosting as sh

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_migrate_module():
    spec = importlib.util.spec_from_file_location(
        "fenix_migrate_to_systemd", str(REPO_ROOT / "bin" / "migrate_to_systemd.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load_migrate_module()

# 最小 PATH：只含普通目录，缺 ~/.local/bin 与 /usr/local/bin 两类基线目录
MINIMAL_PATH = "/usr/bin:/bin"


@pytest.fixture()
def minimal_env():
    # HOME 键在场（fix-push-credential-env-and-retry-rearm 3.1 并列基线后，
    # 「已含 HOME 时 PATH 语境产物逐字节不变」的断言前提）
    return {"A": "1", "PATH": MINIMAL_PATH, "HOME": "/fixture/home", "CLAUDE_PID": "9"}


@pytest.fixture()
def complete_env():
    return {
        "A": "1",
        "PATH": ":".join(sh.PATH_BASELINE_DIRS),
        "HOME": "/fixture/home",
        "CLAUDE_PID": "9",
    }


# ---------------------------------------------------------------------------
# 3.1 基线并集：补齐 / 恒等
# ---------------------------------------------------------------------------


class TestApplyPathBaseline:
    def test_missing_dirs_appended_in_baseline_order(self, minimal_env):
        healed, appended = sh.apply_path_baseline(minimal_env)
        # 缺失目录按基线序并入尾部，已有顺序保持在前
        assert healed["PATH"] == MINIMAL_PATH + ":" + ":".join(
            d for d in sh.PATH_BASELINE_DIRS if d not in MINIMAL_PATH.split(":")
        )
        assert appended == [d for d in sh.PATH_BASELINE_DIRS if d not in MINIMAL_PATH.split(":")]
        assert healed["A"] == "1"

    def test_complete_path_is_identity(self, complete_env):
        healed, appended = sh.apply_path_baseline(complete_env)
        assert healed == complete_env
        assert appended == []

    def test_missing_path_key_gets_full_baseline(self):
        healed, appended = sh.apply_path_baseline({"A": "1"})
        assert healed["PATH"] == ":".join(sh.PATH_BASELINE_DIRS)
        assert appended == list(sh.PATH_BASELINE_DIRS)

    def test_path_baseline_missing_detects_only_missing(self):
        assert sh.path_baseline_missing(MINIMAL_PATH) == [
            d for d in sh.PATH_BASELINE_DIRS if d not in MINIMAL_PATH.split(":")
        ]
        assert sh.path_baseline_missing(":".join(sh.PATH_BASELINE_DIRS)) == []


# ---------------------------------------------------------------------------
# 3.1 候选稿留痕：补齐有据、完整无头
# ---------------------------------------------------------------------------


class TestRenderEnvFileNote:
    def test_complete_path_render_has_no_note_header(self, complete_env):
        text = sh.render_env_file(sh.filter_session_identity(complete_env))
        first_line = text.splitlines()[0]
        assert "PATH" not in first_line
        assert f"PATH={complete_env['PATH']}" in text

    def test_appended_dirs_get_note_header(self, minimal_env):
        healed, appended = sh.apply_path_baseline(minimal_env)
        text = sh.render_env_file(sh.filter_session_identity(healed), path_note=appended)
        lines = text.splitlines()
        # 头部留痕：已追加清单 + 原因说明，PATH 行带尾部追加
        assert any("追加尾部" in ln and "、".join(appended) in ln for ln in lines[:6])
        assert any("原因" in ln for ln in lines[:6])
        assert f"PATH={healed['PATH']}" in text


# ---------------------------------------------------------------------------
# 3.1 捕获集成：capture_env_candidate 出补齐稿
# ---------------------------------------------------------------------------


class TestCaptureCandidateIntegration:
    def test_minimal_path_candidate_extended_with_note(self, monkeypatch, tmp_path, minimal_env):
        monkeypatch.setattr(sh, "read_process_env", lambda pid: minimal_env)
        target = tmp_path / "systemd.env"
        path_report: list = []
        keys = sh.capture_env_candidate(4242, target, path_report=path_report)
        candidate = Path(f"{target}{sh.ENV_CANDIDATE_SUFFIX}")
        text = candidate.read_text(encoding="utf-8")
        assert "PATH" in keys
        assert path_report == [d for d in sh.PATH_BASELINE_DIRS if d not in MINIMAL_PATH.split(":")]
        assert any("追加尾部" in ln for ln in text.splitlines()[:6])
        assert "A=1" in text
        assert "CLAUDE_PID" not in text  # 会话身份过滤不受补齐影响

    def test_complete_path_candidate_byte_identical_no_note(
        self, monkeypatch, tmp_path, complete_env
    ):
        monkeypatch.setattr(sh, "read_process_env", lambda pid: complete_env)
        target = tmp_path / "systemd.env"
        path_report: list = []
        sh.capture_env_candidate(4242, target, path_report=path_report)
        assert path_report == []
        expected = sh.render_env_file(sh.filter_session_identity(complete_env))
        candidate = Path(f"{target}{sh.ENV_CANDIDATE_SUFFIX}")
        assert candidate.read_text(encoding="utf-8") == expected


# ---------------------------------------------------------------------------
# 2.4 落盘侧幂等：append_env_path_dirs
# ---------------------------------------------------------------------------


class TestAppendEnvPathDirs:
    def _write_env(self, tmp_path, text):
        env_file = tmp_path / "systemd.env"
        env_file.write_text(text, encoding="utf-8")
        return env_file

    def test_append_missing_dirs(self, tmp_path):
        env_file = self._write_env(tmp_path, "FOO=1\nPATH=/usr/bin:/bin\n")
        appended = sh.append_env_path_dirs(
            env_file, [str(tmp_path / "toolbin"), "/usr/local/bin"]
        )
        assert appended == [str(tmp_path / "toolbin"), "/usr/local/bin"]
        text = env_file.read_text(encoding="utf-8")
        assert "FOO=1" in text
        assert f"PATH=/usr/bin:/bin:{tmp_path / 'toolbin'}:/usr/local/bin" in text

    def test_second_call_is_noop(self, tmp_path):
        env_file = self._write_env(tmp_path, "PATH=/usr/bin\n")
        dirs = ["/usr/local/bin"]
        assert sh.append_env_path_dirs(env_file, dirs) == dirs
        first = env_file.read_text(encoding="utf-8")
        assert sh.append_env_path_dirs(env_file, dirs) == []
        assert env_file.read_text(encoding="utf-8") == first

    def test_file_without_path_line_gets_one(self, tmp_path):
        env_file = self._write_env(tmp_path, "FOO=1\n")
        appended = sh.append_env_path_dirs(env_file, ["/usr/local/bin"])
        assert appended == ["/usr/local/bin"]
        text = env_file.read_text(encoding="utf-8")
        assert "PATH=/usr/local/bin" in text
        assert "FOO=1" in text


# ---------------------------------------------------------------------------
# 3.2 unit 模板保底行
# ---------------------------------------------------------------------------


class TestRenderProjectUnitFallbackPath:
    def test_unit_contains_baseline_path_line(self, tmp_path):
        text = sh.render_project_unit(tmp_path)
        path_lines = [ln for ln in text.splitlines() if ln.startswith("Environment=PATH=")]
        assert len(path_lines) == 1
        value = path_lines[0].split("=", 1)[1]
        for baseline_dir in sh.PATH_BASELINE_DIRS:
            assert baseline_dir in value
        assert "~" not in value  # 已 expanduser，systemd 直读无需展开


# ---------------------------------------------------------------------------
# 3.3 迁移摘要结论行
# ---------------------------------------------------------------------------


class TestMigratePathConclusion:
    def _stage1(self, monkeypatch, tmp_path, env):
        proot = tmp_path / "proj"
        proot.mkdir()
        froot = tmp_path / "fw"
        froot.mkdir()
        monkeypatch.setattr(mig, "_project_hosting_pid", lambda p: 4242)
        monkeypatch.setattr(sh, "read_process_env", lambda pid: env)
        monkeypatch.setattr(sh, "find_framework_dashboard_pid", lambda: None)
        return mig.stage1_write_units_and_env(proot, froot, dry_run=True)

    def test_dry_run_reports_completion_line(self, monkeypatch, tmp_path, complete_env):
        result = self._stage1(monkeypatch, tmp_path, complete_env)
        assert result["ok"]
        assert any("PATH 卫生：完整" in ln for ln in result["plan"])

    def test_dry_run_reports_repair_line_with_missing_dirs(
        self, monkeypatch, tmp_path, minimal_env
    ):
        result = self._stage1(monkeypatch, tmp_path, minimal_env)
        assert result["ok"]
        repair_lines = [ln for ln in result["plan"] if "PATH 卫生：补齐" in ln]
        assert len(repair_lines) == 1
        assert "/usr/local/bin" in repair_lines[0]

    def test_execute_capture_reports_repair_and_writes_candidate(
        self, monkeypatch, tmp_path, minimal_env
    ):
        proot = tmp_path / "proj"
        proot.mkdir()
        froot = tmp_path / "fw"
        froot.mkdir()
        monkeypatch.setattr(mig, "_project_hosting_pid", lambda p: 4242)
        monkeypatch.setattr(sh, "read_process_env", lambda pid: minimal_env)
        monkeypatch.setattr(sh, "find_framework_dashboard_pid", lambda: None)
        written = []
        monkeypatch.setattr(
            sh, "write_unit_file", lambda unit, text: written.append(unit) or (tmp_path / unit)
        )
        result = mig.stage1_write_units_and_env(proot, froot, dry_run=False)
        assert result["ok"]
        assert any("PATH 卫生：补齐" in ln for ln in result["plan"])
        candidate = Path(f"{sh.project_env_file(proot)}{sh.ENV_CANDIDATE_SUFFIX}")
        assert candidate.exists()
        assert any("追加尾部" in ln for ln in candidate.read_text(encoding="utf-8").splitlines()[:6])


# ---------------------------------------------------------------------------
# HOME 基线（fix-push-credential-env-and-retry-rearm 3.1/3.2/3.3，与 PATH 并列）
# ---------------------------------------------------------------------------


class TestApplyHomeBaseline:
    def test_missing_home_patched_from_resolver(self, monkeypatch):
        env = {"A": "1", "PATH": MINIMAL_PATH}
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: "/resolved/home")
        healed, added = sh.apply_home_baseline(env)
        assert healed["HOME"] == "/resolved/home"
        assert added == "/resolved/home"
        assert healed["A"] == "1"  # 其余键不动

    def test_present_home_byte_identical(self):
        """已含非空 HOME → 原样返回（补齐值 None，无任何改写）。"""
        env = {"A": "1", "HOME": "/existing/home"}
        healed, added = sh.apply_home_baseline(env)
        assert healed is env
        assert added is None

    def test_empty_home_counts_as_missing(self, monkeypatch):
        env = {"HOME": ""}
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: "/resolved/home")
        healed, added = sh.apply_home_baseline(env)
        assert healed["HOME"] == "/resolved/home"
        assert added == "/resolved/home"

    def test_unresolvable_home_not_injected(self, monkeypatch):
        """三级解析全空 → 不注入 HOME（行为回退现状）、不抛异常。"""
        env = {"A": "1", "PATH": MINIMAL_PATH}
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: None)
        healed, added = sh.apply_home_baseline(env)
        assert "HOME" not in healed
        assert added is None

    def test_resolve_baseline_home_delegates_to_git_env(self):
        """resolve_baseline_home 经 core.git_env 单源取值（同源判定）。"""
        assert sh.resolve_baseline_home({"HOME": "/direct/home"}) == "/direct/home"


class TestRenderEnvFileHomeNote:
    def test_home_note_written_when_patched(self, tmp_path):
        env = {"A": "1", "PATH": MINIMAL_PATH, "HOME": "/resolved/home"}
        text = sh.render_env_file(env, home_note="/resolved/home")
        assert "HOME 卫生" in text
        assert "HOME=/resolved/home" in text
        assert "HOME=/resolved/home" in text.splitlines()[-len(env):] or any(
            ln == "HOME=/resolved/home" for ln in text.splitlines()
        )

    def test_no_home_note_byte_identical(self):
        """home_note=None（已含 HOME）→ 产物与无 HOME 机制时逐字节一致。"""
        env = {"A": "1", "PATH": MINIMAL_PATH, "HOME": "/existing/home"}
        assert sh.render_env_file(env, home_note=None) == sh.render_env_file(env)


class TestCaptureCandidateHomeIntegration:
    def test_missing_home_candidate_patched_with_note(self, monkeypatch, tmp_path):
        env = {"A": "1", "PATH": MINIMAL_PATH}  # 无 HOME
        monkeypatch.setattr(sh, "read_process_env", lambda pid: env)
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: "/resolved/home")
        target = tmp_path / "systemd.env"
        home_report: list = []
        keys = sh.capture_env_candidate(4242, target, home_report=home_report)
        candidate = Path(f"{target}{sh.ENV_CANDIDATE_SUFFIX}")
        text = candidate.read_text(encoding="utf-8")
        assert "HOME" in keys
        assert home_report == ["/resolved/home"]
        assert any("HOME 卫生" in ln for ln in text.splitlines()[:8])
        assert any(ln == "HOME=/resolved/home" for ln in text.splitlines())

    def test_present_home_candidate_byte_identical(self, monkeypatch, tmp_path, complete_env):
        """已含 HOME → 候选稿产物逐字节一致、home_report 空、无留痕头。"""
        monkeypatch.setattr(sh, "read_process_env", lambda pid: complete_env)
        target = tmp_path / "systemd.env"
        home_report: list = []
        sh.capture_env_candidate(4242, target, home_report=home_report)
        assert home_report == []
        expected = sh.render_env_file(sh.filter_session_identity(complete_env))
        candidate = Path(f"{target}{sh.ENV_CANDIDATE_SUFFIX}")
        assert candidate.read_text(encoding="utf-8") == expected
        assert "HOME 卫生" not in expected


class TestRenderProjectUnitHomeFallback:
    def test_unit_contains_home_fallback_line(self, tmp_path):
        text = sh.render_project_unit(tmp_path)
        home_lines = [ln for ln in text.splitlines() if ln.startswith("Environment=HOME=")]
        # 宿主解析器可解析（root 宿主恒可）→ 恰一行保底
        assert len(home_lines) == 1
        value = home_lines[0].split("=", 1)[1]
        assert value  # 非空

    def test_home_fallback_precedes_env_file_line(self, tmp_path):
        """保底行在 EnvironmentFile 之前（systemd 后读覆盖语义不变）。"""
        text = sh.render_project_unit(tmp_path)
        lines = text.splitlines()
        home_idx = next(i for i, ln in enumerate(lines) if ln.startswith("Environment=HOME="))
        envfile_idx = next(i for i, ln in enumerate(lines) if ln.startswith("EnvironmentFile="))
        assert home_idx < envfile_idx

    def test_unit_omits_home_line_when_unresolvable(self, monkeypatch, tmp_path):
        """三级解析全空 → 不写保底行（无值可写，fail-open）。"""
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: None)
        text = sh.render_project_unit(tmp_path)
        assert not any(ln.startswith("Environment=HOME=") for ln in text.splitlines())


class TestMigrateHomeConclusion:
    """3.3 迁移摘要 HOME 卫生结论行（与 PATH 结论并列）。"""

    def _stage1(self, monkeypatch, tmp_path, env):
        proot = tmp_path / "proj"
        proot.mkdir()
        froot = tmp_path / "fw"
        froot.mkdir()
        monkeypatch.setattr(mig, "_project_hosting_pid", lambda p: 4242)
        monkeypatch.setattr(sh, "read_process_env", lambda pid: env)
        monkeypatch.setattr(sh, "find_framework_dashboard_pid", lambda: None)
        return mig.stage1_write_units_and_env(proot, froot, dry_run=True)

    def test_dry_run_complete_home(self, monkeypatch, tmp_path):
        env = {"A": "1", "PATH": MINIMAL_PATH, "HOME": "/src/home"}
        result = self._stage1(monkeypatch, tmp_path, env)
        assert result["ok"]
        assert any("HOME 卫生：完整" in ln for ln in result["plan"])

    def test_dry_run_missing_home_reports_patched_value(self, monkeypatch, tmp_path):
        env = {"A": "1", "PATH": MINIMAL_PATH}  # 无 HOME
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: "/resolved/home")
        result = self._stage1(monkeypatch, tmp_path, env)
        assert result["ok"]
        repair = [ln for ln in result["plan"] if "HOME 卫生：补齐" in ln]
        assert len(repair) == 1
        assert "/resolved/home" in repair[0]

    def test_execute_capture_reports_home_conclusion(self, monkeypatch, tmp_path):
        env = {"A": "1", "PATH": MINIMAL_PATH}  # 无 HOME
        monkeypatch.setattr(sh, "resolve_baseline_home", lambda e=None: "/resolved/home")
        proot = tmp_path / "proj"
        proot.mkdir()
        froot = tmp_path / "fw"
        froot.mkdir()
        monkeypatch.setattr(mig, "_project_hosting_pid", lambda p: 4242)
        monkeypatch.setattr(sh, "read_process_env", lambda pid: env)
        monkeypatch.setattr(sh, "find_framework_dashboard_pid", lambda: None)
        monkeypatch.setattr(
            sh, "write_unit_file", lambda unit, text: tmp_path / unit
        )
        result = mig.stage1_write_units_and_env(proot, froot, dry_run=False)
        assert result["ok"]
        assert any("HOME 卫生：补齐 /resolved/home" in ln for ln in result["plan"])
        candidate = Path(f"{sh.project_env_file(proot)}{sh.ENV_CANDIDATE_SUFFIX}")
        assert "HOME=/resolved/home" in candidate.read_text(encoding="utf-8")
