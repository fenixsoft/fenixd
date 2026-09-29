"""run-artifact-retention 能力测试（remove-auto-run-cleanup + fix-run-cleanup-attach-spec-archive）。

覆盖：
1. run_spec_part：run_id → spec 名还原（impl/planner/admin 等前缀格式）。
2. archive_spec_runs（fix-run-cleanup-attach-spec-archive D1：升级为清理）：
   只删匹配文件（顶层与 archive/ 归档副本两处）、其他 SPEC 产物零影响、
   返回清理数、目录缺失返回 0、逐文件删日志可查、单文件 OSError 记 warning 继续。
3. archive_change 集成：spec 归档联动 run 产物清理；runs 清理失败不阻断 change
   归档（fail-open，design D4）。
"""

import logging
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

    def test_removes_only_matching_files(self, tmp_path):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        cleaned = archive_spec_runs(runs_dir, "myspec")
        assert cleaned == 3
        arc = runs_dir / "archive"
        for name in (
            "impl-myspec-1788424595-a1.jsonl",
            "planner-plan-myspec-1788424595-a1.jsonl",
            "admin-myspec-1788424595.jsonl",
        ):
            # 清理语义：顶层删除且不产生归档副本（fix-run-cleanup-attach-spec-archive）
            assert not (runs_dir / name).exists()
            assert not (arc / name).exists()
        # 不匹配的产物留在顶层
        assert (runs_dir / "impl-otherspec-1788424595-a1.jsonl").is_file()

    def test_top_and_archive_copies_both_removed(self, tmp_path):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        arc = runs_dir / "archive"
        arc.mkdir()
        # 同 SPEC 的归档副本（含异 run_id 的历史归档）一并删除
        (arc / "verify-myspec-1788424595-a1.jsonl").write_text('{"type":"archived"}\n', encoding="utf-8")
        (arc / "impl-myspec-1788424595-a1.jsonl").write_text('{"type":"archived"}\n', encoding="utf-8")
        # 其他 SPEC 的归档副本保持原样
        (arc / "impl-bar-1788424595-a1.jsonl").write_text('{"type":"bar"}\n', encoding="utf-8")
        cleaned = archive_spec_runs(runs_dir, "myspec")
        assert cleaned == 5  # 顶层 3 + 归档副本 2
        assert not (arc / "verify-myspec-1788424595-a1.jsonl").exists()
        assert not (arc / "impl-myspec-1788424595-a1.jsonl").exists()
        assert (arc / "impl-bar-1788424595-a1.jsonl").is_file(), "其他 SPEC 产物零影响"
        assert not (runs_dir / "impl-myspec-1788424595-a1.jsonl").exists()

    def test_missing_runs_dir_returns_zero(self, tmp_path):
        assert archive_spec_runs(tmp_path / ".fenix" / "runs", "myspec") == 0

    def test_deletion_logged_per_file(self, tmp_path, caplog):
        """spec.md Scenario：清理逐文件记日志（两处各一条删除记录可审计）。"""
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        arc = runs_dir / "archive"
        arc.mkdir()
        (arc / "verify-myspec-1788424595-a1.jsonl").write_text("x", encoding="utf-8")
        with caplog.at_level("INFO", logger="fenixd.agent_runner.run_files"):
            cleaned = archive_spec_runs(runs_dir, "myspec")
        assert cleaned == 4
        del_msgs = [
            r.message
            for r in caplog.records
            if r.levelno == logging.INFO and "归档清理" in r.message
        ]
        assert len(del_msgs) == 4
        assert any("impl-myspec-1788424595-a1.jsonl" in m for m in del_msgs)
        assert any("verify-myspec-1788424595-a1.jsonl" in m for m in del_msgs)

    def test_single_file_oserror_warns_and_continues(self, tmp_path, caplog):
        runs_dir = tmp_path / ".fenix" / "runs"
        self._make_runs(runs_dir)
        # 制造单文件删除失败：顶层同名项是目录，unlink(dir) 在 POSIX 上必然抛
        # OSError（与运行用户无关）。
        victim = runs_dir / "planner-plan-myspec-1788424595-a1.jsonl"
        victim.unlink()
        victim.mkdir()
        with caplog.at_level("WARNING", logger="fenixd.agent_runner.run_files"):
            cleaned = archive_spec_runs(runs_dir, "myspec")
        assert cleaned == 2
        assert any("archive_spec_runs" in r.message for r in caplog.records)
        # 失败项留在原处，其余正常清理
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

    def test_archive_cleans_spec_runs(self, tmp_path):
        root = self._make_project(tmp_path / "proj")
        result = archive_change(root, "myspec")
        archived_change = (
            root / "spec" / "archive"
            / f"{date.today().isoformat()}-myspec"
        )
        assert archived_change.is_dir()
        assert (archived_change / "proposal.md").is_file()
        # runs_archived 键沿用（调用方 fail-open 记数，键名兼容），值为清理数
        assert result["runs_archived"] == 3
        arc = root / ".fenix" / "runs" / "archive"
        for name in (
            "impl-myspec-1788424595-a1.jsonl",
            "planner-plan-myspec-1788424595-a1.jsonl",
            "admin-myspec-1788424595.jsonl",
        ):
            assert not (root / ".fenix" / "runs" / name).exists()
            assert not (arc / name).exists(), "清理语义：不再产生归档副本"
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
