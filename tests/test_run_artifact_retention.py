"""run-artifact-retention 能力测试（remove-auto-run-cleanup）。

覆盖：
1. run_spec_part：run_id → spec 名还原（impl/planner/admin 等前缀格式）。
2. archive_spec_runs：只移匹配文件、不匹配留顶层、返回移动数、目录缺失返回 0、
   同名去重以归档侧为准、单文件 OSError 记 warning 继续。
3. archive_change 集成：spec 归档联动 run 产物归档；runs 归档失败不阻断 change
   归档（fail-open，design D4）。
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# bin/ 下的独立脚本（fenix_archive.py）以模块方式导入以复用归档逻辑
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from core.agent_runner import run_files as run_files_mod
from core.agent_runner.run_files import archive_spec_runs, run_spec_part
from fenix_archive import archive_change


class TestRunSpecPart:
    def test_agent_prefixes_strip(self):
        ts = 1788424595
        assert run_spec_part(f"impl-myspec-{ts}-a1") == "myspec"
        assert run_spec_part(f"planner-plan-myspec-{ts}") == "myspec"
        assert run_spec_part(f"planner-judge-myspec-{ts}-a2") == "myspec"
        assert run_spec_part(f"planner-myspec-{ts}") == "myspec"
        assert run_spec_part(f"admin-myspec-{ts}") == "myspec"
        assert run_spec_part(f"verify-myspec-{ts}-a1") == "myspec"
        assert run_spec_part(f"test-myspec-{ts}") == "myspec"

    def test_spec_name_with_digits_kept(self):
        assert run_spec_part("impl-add-agent-123-1788424595-a1") == "add-agent-123"

    def test_no_timestamp_returns_stem(self):
        assert run_spec_part("impl-myspec") == "myspec"


class TestArchiveSpecRuns:
    def _make_runs(self, runs_dir: Path) -> None:
        runs_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "impl-myspec-1788424595-a1.jsonl",
            "planner-plan-myspec-1788424595-a1.jsonl",
            "admin-myspec-1788424595.jsonl",
            "impl-otherspec-1788424595-a1.jsonl",
        ):
            (runs_dir / name).write_text('{"type":"x"}\n', encoding="utf-8")

    def test_moves_only_matching_files(self, tmp_path):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        moved = archive_spec_runs(runs_dir, "myspec")
        assert moved == 3
        arc = runs_dir / "archive"
        for name in (
            "impl-myspec-1788424595-a1.jsonl",
            "planner-plan-myspec-1788424595-a1.jsonl",
            "admin-myspec-1788424595.jsonl",
        ):
            assert (arc / name).is_file()
            assert not (runs_dir / name).exists()
        # 不匹配的产物留在顶层
        assert (runs_dir / "impl-otherspec-1788424595-a1.jsonl").is_file()

    def test_missing_runs_dir_returns_zero(self, tmp_path):
        assert archive_spec_runs(tmp_path / ".fenix" / "runs", "myspec") == 0

    def test_duplicate_prefers_archive_copy(self, tmp_path):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        arc = runs_dir / "archive"
        arc.mkdir()
        # 归档副本已存在且内容不同 → 删除顶层副本，保留归档侧
        (arc / "impl-myspec-1788424595-a1.jsonl").write_text(
            '{"type":"archived"}\n', encoding="utf-8"
        )
        moved = archive_spec_runs(runs_dir, "myspec")
        assert moved == 3
        assert (
            arc / "impl-myspec-1788424595-a1.jsonl"
        ).read_text(encoding="utf-8") == '{"type":"archived"}\n'
        assert not (runs_dir / "impl-myspec-1788424595-a1.jsonl").exists()

    def test_single_file_oserror_warns_and_continues(self, tmp_path, caplog):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        # 制造单文件归档失败：顶层同名项是目录、archive/ 同名是文件，
        # rename(dir → file) 在 POSIX 上必然抛 OSError（与运行用户无关）。
        victim = runs_dir / "planner-plan-myspec-1788424595-a1.jsonl"
        victim.unlink()
        victim.mkdir()
        arc = runs_dir / "archive"
        arc.mkdir()
        (arc / "planner-plan-myspec-1788424595-a1.jsonl").write_text("x", encoding="utf-8")
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.run_files"):
            moved = archive_spec_runs(runs_dir, "myspec")
        assert moved == 2
        assert any("archive_spec_runs" in r.message for r in caplog.records)
        # 失败项留在顶层，其余正常归档
        assert victim.is_dir()


class TestArchiveChangeIntegration:
    def _make_project(self, root: Path, spec: str = "myspec") -> Path:
        (root / "spec" / "changes" / spec / "specs").mkdir(parents=True)
        (root / "spec" / "changes" / spec / "proposal.md").write_text("# p", encoding="utf-8")
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        for name in (
            f"impl-{spec}-1788424595-a1.jsonl",
            f"planner-plan-{spec}-1788424595-a1.jsonl",
            f"admin-{spec}-1788424595.jsonl",
            "impl-otherspec-1788424595-a1.jsonl",
        ):
            (runs_dir / name).write_text('{"type":"x"}\n', encoding="utf-8")
        return root

    def test_archive_moves_spec_runs_into_archive(self, tmp_path):
        root = self._make_project(tmp_path / "proj")
        result = archive_change(root, "myspec")
        archived_change = (
            root / "spec" / "archive"
            / f"{date.today().isoformat()}-myspec"
        )
        assert archived_change.is_dir()
        assert (archived_change / "proposal.md").is_file()
        assert result["runs_archived"] == 3
        arc = root / ".fenix" / "runs" / "archive"
        assert (arc / "impl-myspec-1788424595-a1.jsonl").is_file()
        assert (arc / "planner-plan-myspec-1788424595-a1.jsonl").is_file()
        assert (arc / "admin-myspec-1788424595.jsonl").is_file()
        assert (root / ".fenix" / "runs" / "impl-otherspec-1788424595-a1.jsonl").is_file()

    def test_runs_archive_failure_fail_open(self, tmp_path, monkeypatch):
        root = self._make_project(tmp_path / "proj")

        def boom(*a, **kw):
            raise OSError("simulated runs archive failure")

        monkeypatch.setattr(run_files_mod, "archive_spec_runs", boom)
        result = archive_change(root, "myspec")
        # change 目录归档主流程不受影响
        archived_change = (
            root / "spec" / "archive"
            / f"{date.today().isoformat()}-myspec"
        )
        assert (archived_change / "proposal.md").is_file()
        assert "simulated runs archive failure" in result["runs_archive_warning"]
        assert "runs_archived" not in result

    def test_import_error_fail_open(self, tmp_path, monkeypatch):
        import builtins

        root = self._make_project(tmp_path / "proj")
        real_import = builtins.__import__

        def fake_import(name, *a, **kw):
            if name == "core.agent_runner.run_files":
                raise ImportError("no core here")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = archive_change(root, "myspec")
        assert "no core here" in result["runs_archive_warning"]
        archived_change = (
            root / "spec" / "archive"
            / f"{date.today().isoformat()}-myspec"
        )
        assert (archived_change / "proposal.md").is_file()
