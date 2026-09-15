"""
Tests for SPEC 归档能力（add-spec-archive）。

覆盖 data.py::archive_spec / spec_summary.archived（归档判定，无独立
is_spec_archived 断言）/ record_project_event 与 server.py::POST
/api/spec-archive 端点，以及 daemon 自动归档（auto_archive_check）与
配置校验（archive.auto_threshold）。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard import data as dash_data
from core.dashboard.data import (
    archive_spec, parse_state, record_project_event,
    spec_summary,
)


def _make_project(root: Path, specs: dict) -> Path:
    """构造最小可用项目：.fenix/STATE.md + spec/changes/<name>/ 目录。

    specs: {name: {"status": ..., "updated": ...}}
    """
    (root / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, entry in specs.items():
        (root / "spec" / "changes" / name).mkdir(exist_ok=True)
        lines.append(f"### {name}")
        lines.append(f"- status: {entry['status']}")
        lines.append(f"- updated: {entry.get('updated', '2026-01-01T00:00:00+00:00')}")
        lines.append("")
    (root / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")
    return root


class TestArchiveSpec(unittest.TestCase):
    """archive_spec：终态成功 / 非终态拒绝 / 目标存在不覆盖 / 不存在报错 / 已归档幂等。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_archive_terminal_success(self):
        _make_project(self.root, {"spec-a": {"status": "done"}})
        (self.root / "spec" / "changes" / "spec-a" / "tasks.md").write_text(
            "# T", encoding="utf-8")
        result = archive_spec(self.root, "spec-a")
        self.assertTrue(result["ok"])
        self.assertTrue(result["found"])
        self.assertTrue(result["to"].endswith("spec-a"))
        self.assertIn("archive", result["to"])
        # 目录已移动
        self.assertFalse((self.root / "spec" / "changes" / "spec-a").is_dir())
        archive_dir = self.root / "spec" / "archive"
        archived = next(archive_dir.iterdir())
        self.assertTrue(archived.is_dir())
        self.assertTrue((archived / "tasks.md").exists())
        # STATE.md 条目原样保留
        self.assertIn("spec-a", parse_state(self.root))

    def test_archive_pushed_success(self):
        _make_project(self.root, {"spec-b": {"status": "pushed"}})
        result = archive_spec(self.root, "spec-b")
        self.assertTrue(result["ok"])
        self.assertIn("spec-b", parse_state(self.root))

    def test_archive_non_terminal_rejected(self):
        _make_project(self.root, {"spec-x": {"status": "implementing"}})
        result = archive_spec(self.root, "spec-x")
        self.assertFalse(result["ok"])
        self.assertTrue(result["found"])
        self.assertIn("仅终态", result["error"])
        # 目录与 STATE.md 均不变
        self.assertTrue((self.root / "spec" / "changes" / "spec-x").is_dir())
        self.assertIn("spec-x", parse_state(self.root))

    def test_archive_target_exists_no_overwrite(self):
        _make_project(self.root, {"spec-c": {"status": "pushed"}})
        tgt = (self.root / "spec" / "archive"
               / f"{date.today().isoformat()}-spec-c")
        tgt.mkdir(parents=True)
        (tgt / "keep.txt").write_text("keep", encoding="utf-8")
        result = archive_spec(self.root, "spec-c")
        self.assertFalse(result["ok"])
        self.assertIn("已存在", result["error"])
        self.assertTrue((self.root / "spec" / "changes" / "spec-c").is_dir())
        self.assertEqual((tgt / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_archive_nonexistent_spec(self):
        _make_project(self.root, {})
        result = archive_spec(self.root, "ghost")
        self.assertFalse(result["ok"])
        self.assertFalse(result["found"])

    def test_archive_already_archived(self):
        _make_project(self.root, {"spec-d": {"status": "done"}})
        # 目录缺失即视为已归档（与 CLI skill 手动归档同态）
        import shutil
        shutil.rmtree(self.root / "spec" / "changes" / "spec-d")
        result = archive_spec(self.root, "spec-d")
        self.assertFalse(result["ok"])
        self.assertTrue(result["found"])
        self.assertIn("已归档", result["error"])

    def _make_runs(self, root: Path, spec: str) -> Path:
        """造 runs 顶层产物：3 个属于 spec、1 个属于他 spec。"""
        runs_dir = root / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            f"impl-{spec}-1788424595-a1.jsonl",
            f"planner-plan-{spec}-1788424595-a1.jsonl",
            f"admin-{spec}-1788424595.jsonl",
            "impl-otherspec-1788424595-a1.jsonl",
        ):
            (runs_dir / name).write_text('{"type":"x"}\n', encoding="utf-8")
        return runs_dir

    def test_archive_also_archives_spec_runs(self):
        """归档 SPEC 时其 run 产物同批移入 runs/archive/（与 CLI 归档路径同源）。

        回归（remove-auto-run-cleanup 漏挂）：archive_spec 是 daemon 自动归档
        （auto_archive_check）与 Dashboard 界面归档（POST /api/spec-archive）
        共用的入口，此前只搬 spec 目录、没接 archive_spec_runs——run 归档挂钩
        只接在 bin/fenix_archive.py::archive_change 一条路上，导致 SPEC 早已
        归档而产物永久滞留 runs 顶层（实证：138 个已归档 SPEC 中 127 个的产物
        仍留在顶层）。
        """
        _make_project(self.root, {"spec-r": {"status": "pushed"}})
        runs_dir = self._make_runs(self.root, "spec-r")
        result = archive_spec(self.root, "spec-r")
        self.assertTrue(result["ok"])
        self.assertEqual(result["runs_archived"], 3)
        arc = runs_dir / "archive"
        for name in (
            "impl-spec-r-1788424595-a1.jsonl",
            "planner-plan-spec-r-1788424595-a1.jsonl",
            "admin-spec-r-1788424595.jsonl",
        ):
            self.assertTrue((arc / name).is_file(), f"{name} 未归档")
            self.assertFalse((runs_dir / name).exists(), f"{name} 仍滞留顶层")
        # 他 spec 产物不受影响
        self.assertTrue((runs_dir / "impl-otherspec-1788424595-a1.jsonl").is_file())

    def test_archive_spec_runs_failure_fail_open(self):
        """runs 归档失败不阻断 change 归档主流程（fail-open，告警字段留痕）。"""
        from unittest import mock
        _make_project(self.root, {"spec-f": {"status": "done"}})
        runs_dir = self._make_runs(self.root, "spec-f")
        with mock.patch.object(dash_data, "archive_spec_runs",
                               side_effect=OSError("simulated runs archive failure")):
            result = archive_spec(self.root, "spec-f")
        # change 目录归档主流程不受影响
        self.assertTrue(result["ok"])
        archived = next((self.root / "spec" / "archive").iterdir())
        self.assertTrue(archived.is_dir())
        self.assertIn("simulated runs archive failure",
                      result["runs_archive_warning"])
        self.assertNotIn("runs_archived", result)
        # 产物原样留在顶层，未丢失
        self.assertTrue((runs_dir / "impl-spec-f-1788424595-a1.jsonl").is_file())


class TestArchivedFlag(unittest.TestCase):
    """spec_summary.archived：目录存在 / 目录缺失 / CLI 归档后条目保留。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        _make_project(self.root, {
            "active-spec": {"status": "done"},
            "arch-spec": {"status": "done"},
        })

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_active_dir_not_archived(self):
        specs = parse_state(self.root)
        self.assertFalse(spec_summary(self.root, "active-spec", specs["active-spec"])["archived"])

    def test_missing_dir_archived(self):
        import shutil
        shutil.rmtree(self.root / "spec" / "changes" / "arch-spec")
        specs = parse_state(self.root)
        self.assertTrue(spec_summary(self.root, "arch-spec", specs["arch-spec"])["archived"])

    def test_after_archive_api_flag(self):
        archive_spec(self.root, "active-spec")
        specs = parse_state(self.root)
        self.assertTrue(spec_summary(self.root, "active-spec", specs["active-spec"])["archived"])
        # 条目仍在 STATE.md
        self.assertIn("active-spec", specs)


class TestRecordProjectEvent(unittest.TestCase):
    """record_project_event：写入 fenixd.log，get_recent_events 可读。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_event_written_and_readable(self):
        record_project_event(self.root, "dashboard",
                             "Spec 'x' 已归档: /a → /b",
                             context={"spec": "x", "from": "/a", "to": "/b"})
        events = dash_data.get_recent_events(self.root, minutes=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message"], "Spec 'x' 已归档: /a → /b")
        self.assertEqual(events[0]["context"]["spec"], "x")
        self.assertEqual(events[0]["component"], "dashboard")


# ── 配置：archive.auto_threshold（core/config.py + dashboard data） ───

class TestAutoArchiveThresholdConfig(unittest.TestCase):
    """配置校验合法/非法回落、深合并用户级/项目级优先级、写回与回显。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read_valid(self):
        from core.dashboard.data import read_effective_config, write_config
        r = write_config(self.root, {"archive": {"auto_threshold": 30}})
        self.assertTrue(r["ok"])
        self.assertEqual(read_effective_config(self.root)["archive"]["auto_threshold"], 30)

    def test_invalid_write_ignored(self):
        from core.dashboard.data import read_effective_config, write_config
        write_config(self.root, {"archive": {"auto_threshold": 30}})
        # 负值被 _deep_merge_managed 白名单过滤（保留原配置）
        r = write_config(self.root, {"archive": {"auto_threshold": -5}})
        self.assertTrue(r["ok"])
        self.assertEqual(read_effective_config(self.root)["archive"]["auto_threshold"], 30)

    def test_effective_helper_defaults_and_fallback(self):
        from core.config import ConfigLoader
        # 缺省 → 50
        self.assertEqual(ConfigLoader.effective_auto_archive_threshold({}), 50)
        # 0 合法（禁用）
        self.assertEqual(ConfigLoader.effective_auto_archive_threshold({"archive": {"auto_threshold": 0}}), 0)
        # 负值/布尔/非整数 → 回落 50
        for bad in (-3, True, "50", 2.5):
            self.assertEqual(
                ConfigLoader.effective_auto_archive_threshold({"archive": {"auto_threshold": bad}}), 50,
                f"{bad!r} should fall back to 50",
            )

    def test_effective_helper_on_disk_invalid(self):
        from core.config import ConfigLoader
        (self.root / ".fenix" / "config.yaml").write_text(
            "archive:\n  auto_threshold: -3\n", encoding="utf-8")
        self.assertEqual(
            ConfigLoader.effective_auto_archive_threshold(ConfigLoader.resolve_config(self.root)), 50)

    def test_deep_merge_user_project_priority(self):
        from core.config import deep_merge
        merged = deep_merge(
            {"archive": {"auto_threshold": 5}},
            {"archive": {"auto_threshold": 8}},
        )
        self.assertEqual(merged["archive"]["auto_threshold"], 8)

    def test_dashboard_echo_falls_back_on_invalid_disk_value(self):
        from core.dashboard.data import read_effective_config
        (self.root / ".fenix" / "config.yaml").write_text(
            "archive:\n  auto_threshold: abc\n", encoding="utf-8")
        self.assertEqual(read_effective_config(self.root)["archive"]["auto_threshold"], 50)


# ── 自动归档检查（auto_archive_check，Task 4） ───────────────────────────

class TestAutoArchiveCheck(unittest.TestCase):
    """超阈值归档最久 / 未超不动 / 0 禁用 / 单条失败不阻塞 / 非终态与已归档不计入。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True)
        (self.root / "spec" / "changes").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_project(self, specs: dict):
        """specs: {name: {"status": ..., "updated": ...}}"""
        for name, entry in specs.items():
            (self.root / "spec" / "changes" / name).mkdir(exist_ok=True)
        lines = ["# Fenix Project State", "", "## Specs", ""]
        for name, entry in specs.items():
            lines += [f"### {name}", f"- status: {entry['status']}",
                      f"- updated: {entry['updated']}", ""]
        (self.root / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")

    def _set_threshold(self, threshold: int):
        (self.root / ".fenix" / "config.yaml").write_text(
            f"project:\n  name: t\narchive:\n  auto_threshold: {threshold}\n",
            encoding="utf-8")

    def test_archive_oldest_when_over_threshold(self):
        self._write_project({
            "a": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"},
            "b": {"status": "done", "updated": "2026-01-02T00:00:00+00:00"},
            "c": {"status": "done", "updated": "2026-01-03T00:00:00+00:00"},
            "d": {"status": "done", "updated": "2026-01-04T00:00:00+00:00"},
        })
        self._set_threshold(2)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["archived"], 2)
        self.assertFalse((self.root / "spec" / "changes" / "a").is_dir())
        self.assertFalse((self.root / "spec" / "changes" / "b").is_dir())
        self.assertTrue((self.root / "spec" / "changes" / "c").is_dir())
        self.assertTrue((self.root / "spec" / "changes" / "d").is_dir())
        self.assertIn("a", parse_state(self.root))  # STATE.md preserved

    def test_no_action_under_threshold(self):
        self._write_project({
            "x": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"},
        })
        self._set_threshold(5)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["archived"], 0)
        self.assertTrue((self.root / "spec" / "changes" / "x").is_dir())

    def test_threshold_zero_disabled(self):
        self._write_project({"y": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"}})
        self._set_threshold(0)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["archived"], 0)
        self.assertEqual(r["threshold"], 0)

    def test_single_failure_skip_continues(self):
        """目标已存在（conflict）→ 跳过该条，其余照常归档。"""
        from datetime import date
        self._write_project({
            "f1": {"status": "pushed", "updated": "2026-01-01T00:00:00+00:00"},
            "f2": {"status": "pushed", "updated": "2026-01-02T00:00:00+00:00"},
            "f3": {"status": "pushed", "updated": "2026-01-03T00:00:00+00:00"},
        })
        # 预置 f1 的归档目标（模拟同日已归档）
        conflict = self.root / "spec" / "archive" / f"{date.today().isoformat()}-f1"
        conflict.mkdir(parents=True)
        (conflict / "sentinel.txt").write_text("keep", encoding="utf-8")
        self._set_threshold(1)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["archived"], 1)
        self.assertEqual(r["skipped"], 1)
        # f1 不动（冲突），f2 归档
        self.assertTrue((self.root / "spec" / "changes" / "f1").is_dir())
        self.assertFalse((self.root / "spec" / "changes" / "f2").is_dir())

    def test_non_terminal_and_archived_not_counted(self):
        """implementing 与已归档（目录缺失）的 SPEC 不计入终态数量。"""
        self._write_project({
            "n1": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"},
            "n2": {"status": "implementing", "updated": "2026-01-02T00:00:00+00:00"},
            "n3": {"status": "pushed", "updated": "2026-01-03T00:00:00+00:00"},
            "n4": {"status": "done", "updated": "2026-01-04T00:00:00+00:00"},
        })
        # n1 已归档（目录缺失）
        import shutil
        shutil.rmtree(self.root / "spec" / "changes" / "n1")
        self._set_threshold(3)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        # counted: n3(done), n4(done) = 2. n1 excluded (dir missing), n2 excluded (implementing)
        self.assertEqual(r["total_terminal_unarchived"], 2)
        self.assertEqual(r["archived"], 0)  # 2 ≤ 3, no action


# ── server.py POST /api/spec-archive 端点 ─────────────────────────────

import pytest
from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, find_free_port


def _make_archive_project(tmp_path, name="proj-a"):
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True)
    (proot / "spec" / "changes" / "done-spec").mkdir(parents=True)
    (proot / "spec" / "changes" / "doing-spec").mkdir(parents=True)
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### done-spec\n- status: pushed\n- priority: 1\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n\n"
        "### doing-spec\n- status: implementing\n- priority: 2\n- created: 2026-01-01T00:00:00+00:00\n"
        "- updated: 2026-02-02T00:00:00+00:00\n- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text("project:\n  name: fake\n", encoding="utf-8")
    return proot


class _TestServer:
    def __init__(self, registry, static_dir):
        self.port = find_free_port(20300)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        import threading
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()

    def _req(self, method, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path):
        return self._req("POST", path)

    def get(self, path):
        return self._req("GET", path)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def archive_server(tmp_path):
    proot = _make_archive_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _TestServer(reg, Path(__file__).resolve().parent.parent / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestSpecArchiveAPI:
    def test_archive_terminal_success(self, archive_server):
        proot, srv = archive_server
        status, body = srv.post("/api/spec-archive?project=proj-a&spec=done-spec")
        assert status == 200
        assert body["ok"] is True
        assert body["to"].endswith("done-spec")
        assert "archive" in body["to"]
        # 目录移动 + STATE.md 保留
        assert not (proot / "spec" / "changes" / "done-spec").is_dir()
        assert "done-spec" in parse_state(proot)
        # 活动事件已写日志
        events = dash_data.get_recent_events(proot, minutes=10)
        assert any("done-spec" in e.get("message", "") and "归档" in e.get("message", "")
                   for e in events)

    def test_archive_non_terminal_403(self, archive_server):
        proot, srv = archive_server
        status, body = srv.post("/api/spec-archive?project=proj-a&spec=doing-spec")
        assert status == 403
        assert "仅终态" in body["error"]
        # 目录与 STATE.md 不变
        assert (proot / "spec" / "changes" / "doing-spec").is_dir()
        assert "doing-spec" in parse_state(proot)

    def test_archive_unknown_spec_404(self, archive_server):
        _, srv = archive_server
        status, body = srv.post("/api/spec-archive?project=proj-a&spec=ghost")
        assert status == 404

    def test_archive_unknown_project_404(self, archive_server):
        _, srv = archive_server
        status, body = srv.post("/api/spec-archive?project=ghost&spec=done-spec")
        assert status == 404

    def test_archive_conflict_target_exists_409(self, archive_server):
        proot, srv = archive_server
        tgt = proot / "spec" / "archive" / f"{date.today().isoformat()}-done-spec"
        tgt.mkdir(parents=True)
        status, body = srv.post("/api/spec-archive?project=proj-a&spec=done-spec")
        assert status == 409
        assert "已存在" in body["error"]

    def test_archive_then_list_archived_flag(self, archive_server):
        proot, srv = archive_server
        status, _ = srv.post("/api/spec-archive?project=proj-a&spec=done-spec")
        assert status == 200
        status, data = srv.get("/api/specs?project=proj-a")
        assert status == 200
        by_name = {s["name"]: s for s in data["specs"]}
        assert by_name["done-spec"]["archived"] is True
        assert by_name["doing-spec"]["archived"] is False


# ── 归档自动提交（commit_archive_move：移动后立即提交，pathspec 限定） ──

class TestArchiveAutoCommit(unittest.TestCase):
    """归档移动后自动提交：git 仓库内产生 [fenix] archive 提交；
    非 git 仓库 fail-open 不阻断归档；pathspec 限定不吞无关修改。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        # 隔离全局/系统 git 配置（identity、hooks），仓库级 config 在 fixture 内显式设置
        self.git_env = {**os.environ,
                        "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_CONFIG_SYSTEM": "/dev/null"}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git(self, *args) -> str:
        r = subprocess.run(["git", "-C", str(self.root), *args],
                           env=self.git_env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"git {args} failed: {r.stderr}")
        return r.stdout

    def _make_git_project(self, name="spec-a"):
        """构造已入库的最小 git 项目：spec/changes/<name>/ 已跟踪提交。"""
        _make_project(self.root, {name: {"status": "pushed"}})
        (self.root / "spec" / "changes" / name / "tasks.md").write_text("# T", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.name", "test")
        self._git("config", "user.email", "test@example.com")
        self._git("add", "--", "spec")
        self._git("commit", "-q", "-m", "init")
        return name

    def _move_to_archive(self, name) -> Path:
        src = self.root / "spec" / "changes" / name
        target = self.root / "spec" / "archive" / f"{date.today().isoformat()}-{name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        return Path(shutil.move(str(src), str(target)))

    def test_commit_after_move_message_and_pathspec(self):
        from core.archive_commit import commit_archive_move
        name = self._make_git_project()
        target = self._move_to_archive(name)
        r = commit_archive_move(self.root, name, target)
        self.assertTrue(r["committed"])
        self.assertTrue(r["commit"])
        self.assertIsNone(r["warning"])
        self.assertEqual(self._git("log", "-1", "--format=%s").strip(),
                         f"[fenix] archive: {name} 归档入库")
        # 提交内容 = 恰好两条归档路径（changes 删除侧 + archive 新增侧）
        stat = self._git("show", "--name-only", "--no-renames", "--format=")
        touched = {ln.strip() for ln in stat.splitlines() if ln.strip()}
        self.assertEqual(touched, {
            f"spec/changes/{name}/tasks.md",
            f"spec/archive/{target.name}/tasks.md",
        })
        self.assertEqual(self._git("ls-files", f"spec/archive/{target.name}").strip(),
                         f"spec/archive/{target.name}/tasks.md")

    def test_commit_does_not_sweep_unrelated_changes(self):
        from core.archive_commit import commit_archive_move
        name = self._make_git_project()
        # 无关 spec 的已跟踪未提交修改 + 未跟踪文件，均不得被卷入归档提交
        other = self.root / "spec" / "changes" / "other"
        other.mkdir()
        (other / "notes.md").write_text("v1", encoding="utf-8")
        self._git("add", "--", "spec/changes/other/notes.md")
        self._git("commit", "-q", "-m", "other")
        (other / "notes.md").write_text("v2", encoding="utf-8")
        (self.root / "spec" / "changes" / "loose.md").write_text("u", encoding="utf-8")
        target = self._move_to_archive(name)
        r = commit_archive_move(self.root, name, target)
        self.assertTrue(r["committed"])
        status = self._git("status", "--porcelain")
        self.assertIn("other/notes.md", status)
        self.assertIn("loose.md", status)

    def test_commit_with_untracked_changes_side(self):
        """spec 目录从未入库（changes 侧无跟踪删除）→ 仍提交 archive 新增侧。"""
        from core.archive_commit import commit_archive_move
        _make_project(self.root, {"spec-u": {"status": "done"}})
        (self.root / "spec" / "changes" / "spec-u" / "tasks.md").write_text("# T", encoding="utf-8")
        self._git("init", "-q")
        self._git("config", "user.name", "test")
        self._git("config", "user.email", "test@example.com")
        self._git("commit", "-q", "--allow-empty", "-m", "init")
        target = self._move_to_archive("spec-u")
        r = commit_archive_move(self.root, "spec-u", target)
        self.assertTrue(r["committed"])
        self.assertEqual(self._git("ls-files", f"spec/archive/{target.name}").strip(),
                         f"spec/archive/{target.name}/tasks.md")

    def test_non_git_project_fail_open(self):
        from core.archive_commit import commit_archive_move
        _make_project(self.root, {"spec-a": {"status": "done"}})
        (self.root / "spec" / "changes" / "spec-a" / "tasks.md").write_text("# T", encoding="utf-8")
        target = self._move_to_archive("spec-a")
        r = commit_archive_move(self.root, "spec-a", target)
        self.assertFalse(r["committed"])
        self.assertIsNone(r["commit"])
        self.assertTrue(r["warning"])

    def test_archive_spec_commits_in_git_project(self):
        name = self._make_git_project(name="spec-g")
        result = archive_spec(self.root, name)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("committed"))
        self.assertIsNone(result.get("commit_warning"))
        self.assertIn(f"{name} 归档入库", self._git("log", "-1", "--format=%s"))

    def test_archive_spec_non_git_still_ok_with_warning(self):
        _make_project(self.root, {"spec-h": {"status": "pushed"}})
        (self.root / "spec" / "changes" / "spec-h" / "tasks.md").write_text("# T", encoding="utf-8")
        result = archive_spec(self.root, "spec-h")
        self.assertTrue(result["ok"])
        self.assertFalse(result.get("committed"))
        self.assertTrue(result.get("commit_warning"))

    def test_fenix_archive_script_commits_in_git_project(self):
        import importlib.util
        script = Path(__file__).resolve().parent.parent / "bin" / "fenix_archive.py"
        s = importlib.util.spec_from_file_location("fenix_archive_mod", script)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
        name = self._make_git_project(name="spec-s")
        result = mod.archive_change(self.root, name)
        self.assertTrue(result.get("committed"))
        self.assertIn(f"{name} 归档入库", self._git("log", "-1", "--format=%s"))


if __name__ == "__main__":
    unittest.main()
