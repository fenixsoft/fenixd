"""test_verify_serving_reclaim.py — .fenix/verify-serving/ 目录与 boot.log 生命周期回收。

fix-verify-serving-disk-reclaim：

- 5.1 保留判据矩阵：changes/archive 存活保留、登记在册保留、活进程保留、
  无法解析保留、6 位数字后缀 spec 正确解析、三重皆无回收
- 5.2 回收执行：git remove --force + prune 打桩、单条目失败继续、重复清扫幂等
- 5.3 boot.log 回收：无主删除 / 存活保留 / 登记/活进程/宽限期保留 /
  无法解析保留 / 状态文件保留
- 5.4 reclaim_verify_serving 返回结构（reclaimed/kept/boot_logs_reclaimed）
- 5.5 verify.serving_reclaim.enabled=false 时早退（不调 git、不删文件）
"""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.pm_engine.verification import serving_reclaim as sr
from core.pm_engine.verification.serving_reclaim import (
    RECLAIM_GRACE_SECONDS,
    has_live_process,
    is_registered_in_servers,
    is_spec_alive,
    parse_spec_from_worktree_name,
    reclaim_verify_serving,
)

OLD = time.time() - 7200  # 超宽限期（600s）的 mtime
_SR_MOD = "core.pm_engine.verification.serving_reclaim"
_SUBPROCESS_RUN = f"{_SR_MOD}.subprocess.run"


def _make_verify_serving(tmp_path, names):
    """建 .fenix/verify-serving/ 并放入名为 names 的旧 mtime 目录。"""
    serve_root = tmp_path / ".fenix" / "verify-serving"
    serve_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        d = serve_root / name
        d.mkdir()
        os.utime(d, (OLD, OLD))
    return serve_root


def _no_git(calls: list):
    """记录 subprocess.run 调用并返回成功（替代真实 git 调用）。"""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    return fake_run


# ── 5.1 判据矩阵 ────────────────────────────────────────────────────────────


class TestParseSpecName:
    """目录名 {spec}-{10 位时间戳} 解析。"""

    def test_parse_basic(self):
        assert parse_spec_from_worktree_name("fix-foo-1789587927") == "fix-foo"

    def test_parse_six_digit_suffix_spec(self):
        """spec 名自身含 6 位数字后缀，末段方为 10 位时间戳。"""
        assert (
            parse_spec_from_worktree_name(
                "evo-merge-back-wip-overlap-gate-575976-1789694112"
            )
            == "evo-merge-back-wip-overlap-gate-575976"
        )

    def test_parse_rejects_non_ts(self):
        assert parse_spec_from_worktree_name("add-foo-123") is None
        assert parse_spec_from_worktree_name("add-foo-12345678901") is None
        assert parse_spec_from_worktree_name("add-foo") is None
        assert parse_spec_from_worktree_name("-1789587927") is None


class TestIsSpecAlive:
    """判据 1：spec 存活于 changes / archive（归档等同存活）。"""

    def test_changes_existing_kept(self, tmp_path):
        (tmp_path / "spec" / "changes" / "fix-foo").mkdir(parents=True)
        assert is_spec_alive("fix-foo", tmp_path) is True

    def test_archive_existing_kept(self, tmp_path):
        (tmp_path / "spec" / "archive" / "2026-09-04-add-bar").mkdir(parents=True)
        assert is_spec_alive("add-bar", tmp_path) is True

    def test_archive_suffix_exact_match(self, tmp_path):
        """*-<spec> 全等后缀：spec=bar 不得误配 foobar 归档。"""
        (tmp_path / "spec" / "archive" / "2026-09-04-foobar").mkdir(parents=True)
        assert is_spec_alive("bar", tmp_path) is False
        assert is_spec_alive("foobar", tmp_path) is True

    def test_spec_absent(self, tmp_path):
        assert is_spec_alive("add-gone", tmp_path) is False


class TestIsRegisteredInServers:
    """判据 2：目录绝对路径 ∈ servers.json 登记 worktree 字段（resolve 后全等）。"""

    def test_registered_path_kept(self, tmp_path):
        serve_root = _make_verify_serving(tmp_path, ["fix-foo-1789587927"])
        (serve_root / "servers.json").write_text(
            json.dumps(
                [
                    {
                        "pid": 1,
                        "port": 0,
                        "spec": "fix-foo",
                        "worktree": str(serve_root / "fix-foo-1789587927"),
                    }
                ]
            ),
            encoding="utf-8",
        )
        assert is_registered_in_servers(serve_root / "fix-foo-1789587927", tmp_path) is True

    def test_empty_worktree_entry_not_matched(self, tmp_path):
        """worktree 为空串的登记项 MUST NOT 参与匹配（register 未传 wt_path 即写空串）。"""
        serve_root = _make_verify_serving(tmp_path, ["fix-foo-1789587927"])
        (serve_root / "servers.json").write_text(
            json.dumps([{"pid": 1, "port": 0, "spec": "fix-foo", "worktree": ""}]),
            encoding="utf-8",
        )
        assert is_registered_in_servers(serve_root / "fix-foo-1789587927", tmp_path) is False

    def test_unregistered_path(self, tmp_path):
        serve_root = _make_verify_serving(tmp_path, ["fix-foo-1789587927"])
        assert is_registered_in_servers(serve_root / "fix-foo-1789587927", tmp_path) is False


class TestHasLiveProcess:
    """判据 3：/proc 有 argv/cwd 指向目录的活进程。"""

    def test_unrelated_dir_no_process(self, tmp_path):
        d = tmp_path / "unused-dir"
        d.mkdir()
        assert has_live_process(d) is False

    def test_directory_with_grace_fresh(self, tmp_path):
        """目录刚创建（宽限期内）→ 保留（判据 4）。"""
        serve_root = _make_verify_serving(tmp_path, ["fix-foo-1789587927"])
        fresh = serve_root / "add-recent-1789587927"
        fresh.mkdir()
        assert sr.is_within_grace_period(fresh) is True
        assert sr.is_within_grace_period(serve_root / "fix-foo-1789587927") is False


# ── 回收执行（目录维度） ─────────────────────────────────────────────────────


class TestReclaimExecution:
    """判据矩阵端到端 + git 调用语义。"""

    def test_changes_existing_kept_and_absent_reclaimed(self, tmp_path):
        """spec 在 changes → 保留；三重皆无 → 回收。"""
        (tmp_path / "spec" / "changes" / "fix-foo").mkdir(parents=True)
        serve_root = _make_verify_serving(
            tmp_path, ["fix-foo-1789587927", "add-gone-1789587928"]
        )
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "fix-foo-1789587927" in result["kept"]
        assert "add-gone-1789587928" in result["reclaimed"]
        # 只对无主目录调 git worktree remove
        remove_calls = [c for c in calls if c[:3] == ["git", "-C", str(tmp_path)] and "remove" in c]
        assert len(remove_calls) == 1
        assert str(serve_root / "add-gone-1789587928") in remove_calls[0]

    def test_archive_existing_kept(self, tmp_path):
        """spec 已归档（归档等同存活）→ 保留。"""
        (tmp_path / "spec" / "archive" / "2026-09-04-add-bar").mkdir(parents=True)
        serve_root = _make_verify_serving(tmp_path, ["add-bar-1788528914"])
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-bar-1788528914" in result["kept"]
        assert result["reclaimed"] == []
        assert serve_root.joinpath("add-bar-1788528914").is_dir()

    def test_unparseable_dir_kept(self, tmp_path):
        """目录名不符合 {spec}-{10 位时间戳} → 无法判定归属，fail-safe 保留。"""
        serve_root = _make_verify_serving(tmp_path, ["add-foo-123", "random-dir"])
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-foo-123" in result["kept"]
        assert "random-dir" in result["kept"]
        assert result["reclaimed"] == []

    def test_registered_dir_kept(self, tmp_path):
        """spec 已消失但 servers.json 仍登记 → 保留（登记优先于回收）。"""
        serve_root = _make_verify_serving(tmp_path, ["add-baz-1788583057"])
        (serve_root / "servers.json").write_text(
            json.dumps(
                [{"pid": 1, "port": 0, "spec": "add-baz",
                  "worktree": str(serve_root / "add-baz-1788583057")}]
            ),
            encoding="utf-8",
        )
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-baz-1788583057" in result["kept"]
        assert result["reclaimed"] == []

    def test_live_process_kept(self, tmp_path):
        """无活进程判定 false 且其余判据皆无时回收；有活进程 → 保留。"""
        serve_root = _make_verify_serving(tmp_path, ["add-gone-1788583057"])
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=True), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-gone-1788583057" in result["kept"]
        assert result["reclaimed"] == []

    def test_recent_dir_kept_by_grace(self, tmp_path):
        """mtime 在宽限期内（防并发创建竞态）→ 保留。"""
        serve_root = tmp_path / ".fenix" / "verify-serving"
        serve_root.mkdir(parents=True)
        (serve_root / "add-fresh-1788583057").mkdir()
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-fresh-1788583057" in result["kept"]
        assert result["reclaimed"] == []

    def test_six_digit_suffix_spec_full_flow(self, tmp_path):
        """目名含 6 位数字后缀 + 10 位时间戳 → 按正确 spec 判定存活（归档命中）。"""
        d = "evo-merge-back-wip-overlap-gate-575976-1789694112"
        (tmp_path / "spec" / "archive" / "2026-09-10-evo-merge-back-wip-overlap-gate-575976").mkdir(
            parents=True
        )
        _make_verify_serving(tmp_path, [d])
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert d in result["kept"]
        assert result["reclaimed"] == []

    def test_remove_all_three_absent_dir(self, tmp_path):
        """spec / 登记 / 活进程三重皆无且超宽限 → 回收（git remove --force + prune）。"""
        serve_root = _make_verify_serving(tmp_path, ["add-baz-1788583057"])
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-baz-1788583057" in result["reclaimed"]
        git_calls = [c for c in calls if c[0] == "git"]
        # remove --force + prune 各一次
        assert any("remove" in c and "--force" in c for c in git_calls)
        assert any("prune" in c for c in git_calls)

    def test_single_entry_failure_does_not_block(self, tmp_path):
        """单条目 git 失败记 WARNING 并继续处理其余条目。"""
        serve_root = _make_verify_serving(
            tmp_path, ["add-gone-1-1788583057", "add-gone-2-1788583058"]
        )
        logger = MagicMock()

        def fake_run(cmd, **kw):
            if any("add-gone-1" in str(t) for t in cmd):
                raise RuntimeError("git worktree remove failed")
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with patch(_SUBPROCESS_RUN, side_effect=fake_run), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=logger)
        assert "add-gone-1-1788583057" not in result["reclaimed"]
        assert "add-gone-2-1788583058" in result["reclaimed"]
        # 失败的条目记 WARNING（含「回收 serving worktree 失败」字样）并继续
        warning_calls = [c for c in logger.warning.call_args_list if c.args[0] == "serving_reclaim"]
        assert warning_calls, "MUST 记 warning"
        assert any("回收 serving worktree 失败" in c.args[1] for c in warning_calls)

    def test_repeated_sweep_idempotent(self, tmp_path):
        """连续两次清扫：第一次回收后目录消失，第二次安全空转零 git 调用。"""
        serve_root = _make_verify_serving(tmp_path, ["add-gone-1788583057"])
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "remove" in cmd:
                for t in cmd:
                    if str(serve_root / "add-gone-1788583057") in t and t != "remove":
                        shutil.rmtree(t, ignore_errors=True)
            return subprocess.CompletedProcess(cmd, 0, b"", b"")

        with patch(_SUBPROCESS_RUN, side_effect=fake_run), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            r1 = reclaim_verify_serving(tmp_path, logger=None)
            first_call_count = len(calls)
            r2 = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-gone-1788583057" in r1["reclaimed"]
        assert r2["reclaimed"] == []
        assert len(calls) == first_call_count  # 无新 git 调用

    def test_state_files_untouched(self, tmp_path):
        """回收 MUST NOT 触碰 servers.json / servers.json.lock / contract_selfcheck.json。"""
        (tmp_path / "spec" / "changes" / "fix-foo").mkdir(parents=True)
        serve_root = _make_verify_serving(
            tmp_path, ["fix-foo-1789587927", "add-gone-1789587928"]
        )
        (serve_root / "servers.json").write_text("[]", encoding="utf-8")
        (serve_root / "servers.json.lock").write_text("", encoding="utf-8")
        (serve_root / "contract_selfcheck.json").write_text("{}", encoding="utf-8")
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            reclaim_verify_serving(tmp_path, logger=None)
        assert (serve_root / "servers.json").exists()
        assert (serve_root / "servers.json.lock").exists()
        assert (serve_root / "contract_selfcheck.json").exists()


# ── 5.3 boot.log 回收 ────────────────────────────────────────────────────────


class TestBootLogReclaim:
    def test_orphan_boot_log_reclaimed(self, tmp_path):
        """spec 不在 changes/archive 且无在飞 → 删除。"""
        serve_root = _make_verify_serving(tmp_path, [])
        gone_log = serve_root / "add-gone-boot.log"
        gone_log.write_text("x", encoding="utf-8")
        os.utime(gone_log, (OLD, OLD))
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-gone-boot.log" in result["boot_logs_reclaimed"]
        assert not (serve_root / "add-gone-boot.log").exists()

    def test_live_spec_boot_log_kept(self, tmp_path):
        """spec 存活（changes）→ 保留。"""
        (tmp_path / "spec" / "changes" / "evo-merge-back-wip-overlap-gate-575976").mkdir(
            parents=True
        )
        serve_root = _make_verify_serving(tmp_path, [])
        (serve_root / "evo-merge-back-wip-overlap-gate-575976-boot.log").write_text(
            "x", encoding="utf-8"
        )
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "evo-merge-back-wip-overlap-gate-575976-boot.log" not in result["boot_logs_reclaimed"]
        assert (serve_root / "evo-merge-back-wip-overlap-gate-575976-boot.log").exists()

    def test_archive_spec_boot_log_kept(self, tmp_path):
        """spec 已归档（归档等同存活）→ 保留。"""
        (tmp_path / "spec" / "archive" / "2026-09-04-add-bar").mkdir(parents=True)
        serve_root = _make_verify_serving(tmp_path, [])
        (serve_root / "add-bar-boot.log").write_text("x", encoding="utf-8")
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-bar-boot.log" not in result["boot_logs_reclaimed"]
        assert (serve_root / "add-bar-boot.log").exists()

    def test_boot_log_with_in_flight_run_kept(self, tmp_path):
        """spec 不在 changes/archive 但无在飞逻辑为真（is_spec_in_flight）→ 保留。"""
        # spec 不存在（get_gone）但 is_spec_in_flight 返回 True → 保留
        serve_root = _make_verify_serving(tmp_path, [])
        (serve_root / "get-gone-boot.log").write_text("x", encoding="utf-8")
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(
                tmp_path, logger=None, is_spec_in_flight=lambda s: s == "get-gone"
            )
        assert "get-gone-boot.log" not in result["boot_logs_reclaimed"]
        assert (serve_root / "get-gone-boot.log").exists()

    def test_boot_log_with_registered_worktree_kept(self, tmp_path):
        """spec 已消失但 servers.json 仍登记同名 worktree → 保留（与目录回收同口径）。"""
        serve_root = _make_verify_serving(tmp_path, ["add-baz-1788583057"])
        (serve_root / "servers.json").write_text(
            json.dumps(
                [{"pid": 1, "port": 0, "spec": "add-baz",
                  "worktree": str(serve_root / "add-baz-1788583057")}]
            ),
            encoding="utf-8",
        )
        baz_log = serve_root / "add-baz-boot.log"
        baz_log.write_text("x", encoding="utf-8")
        os.utime(baz_log, (OLD, OLD))
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-baz-boot.log" not in result["boot_logs_reclaimed"]
        assert baz_log.exists()

    def test_boot_log_with_live_process_kept(self, tmp_path):
        """孤儿进程仍在写（spec serving worktree 有活进程）→ 保留。"""
        serve_root = _make_verify_serving(tmp_path, ["add-orphan-1788583057"])
        orphan_log = serve_root / "add-orphan-boot.log"
        orphan_log.write_text("x", encoding="utf-8")
        os.utime(orphan_log, (OLD, OLD))
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=True), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-orphan-boot.log" not in result["boot_logs_reclaimed"]
        assert orphan_log.exists()

    def test_fresh_boot_log_kept_by_grace(self, tmp_path):
        """新建死 spec 的 boot.log 未过宽限期 → 保留（宽限期缓冲）。"""
        serve_root = _make_verify_serving(tmp_path, [])
        (serve_root / "add-fresh-boot.log").write_text("x", encoding="utf-8")
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert "add-fresh-boot.log" not in result["boot_logs_reclaimed"]
        assert (serve_root / "add-fresh-boot.log").exists()

    def test_unparseable_state_files_kept(self, tmp_path):
        """无法解析归属 / 顶层状态文件 → 保留（fail-safe）。"""
        serve_root = _make_verify_serving(tmp_path, [])
        (serve_root / "servers.json").write_text("[]", encoding="utf-8")
        (serve_root / "contract_selfcheck.json").write_text("{}", encoding="utf-8")
        (serve_root / "random.txt").write_text("x", encoding="utf-8")
        (serve_root / "boot.log").write_text("x", encoding="utf-8")  # 无 spec 前缀
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert result["boot_logs_reclaimed"] == []
        assert (serve_root / "servers.json").exists()
        assert (serve_root / "contract_selfcheck.json").exists()
        assert (serve_root / "random.txt").exists()
        assert (serve_root / "boot.log").exists()


# ── 5.4 返回结构 ─────────────────────────────────────────────────────────────


class TestReturnStructure:
    def test_full_structure_and_counts(self, tmp_path):
        """返回 {reclaimed, kept, boot_logs_reclaimed} 且计数正确。"""
        (tmp_path / "spec" / "changes" / "fix-foo").mkdir(parents=True)
        serve_root = _make_verify_serving(
            tmp_path, ["fix-foo-1789587927", "add-gone-1789587928", "add-gone-1789587929"]
        )
        gone_log = serve_root / "add-gone-boot.log"
        gone_log.write_text("x", encoding="utf-8")
        os.utime(gone_log, (OLD, OLD))
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            result = reclaim_verify_serving(tmp_path, logger=None)
        assert set(result.keys()) == {"reclaimed", "kept", "boot_logs_reclaimed"}
        assert result["kept"] == ["fix-foo-1789587927"]
        assert len(result["reclaimed"]) == 2
        assert "add-gone-1789587928" in result["reclaimed"]
        assert "add-gone-1789587929" in result["reclaimed"]
        assert result["boot_logs_reclaimed"] == ["add-gone-boot.log"]

    def test_missing_serve_root_empty_result(self, tmp_path):
        """无 .fenix/verify-serving/ 目录 → 空结果（不报错）。"""
        result = reclaim_verify_serving(tmp_path, logger=None)
        assert result == {"reclaimed": [], "kept": [], "boot_logs_reclaimed": []}

    def test_reclaim_logs_counts(self, tmp_path):
        """清扫输出含回收数量的日志（可观测性）。"""
        serve_root = _make_verify_serving(tmp_path, ["add-gone-1788583057"])
        logger = MagicMock()
        calls = []
        with patch(_SUBPROCESS_RUN, side_effect=_no_git(calls)), \
             patch.object(sr, "has_live_process", return_value=False), \
             patch.object(sr, "is_registered_in_servers", return_value=False):
            reclaim_verify_serving(tmp_path, logger=logger)
        logger.info.assert_any_call(
            "serving_reclaim", "serving 回收完成：reclaimed=1，kept=0，boot_logs_reclaimed=0"
        )


# ── 5.5 开关早退 ─────────────────────────────────────────────────────────────


class TestSwitchEarlyExit:
    def test_disabled_skips_git_and_deletes(self, tmp_path):
        """verify.serving_reclaim.enabled=false → 早退：不调 git、不删任何条目。"""
        serve_root = _make_verify_serving(tmp_path, ["add-gone-1788583057"])
        (serve_root / "add-gone-boot.log").write_text("x", encoding="utf-8")
        logger = MagicMock()
        with patch(_SUBPROCESS_RUN) as fake_run, \
             patch.object(sr, "has_live_process", return_value=False) as fake_live, \
             patch.object(sr, "is_registered_in_servers", return_value=False) as fake_reg:
            result = reclaim_verify_serving(tmp_path, logger=logger, reclaim_enabled=False)
        fake_run.assert_not_called()
        assert result == {"reclaimed": [], "kept": [], "boot_logs_reclaimed": []}
        assert (serve_root / "add-gone-1788583057").is_dir()
        assert (serve_root / "add-gone-boot.log").exists()