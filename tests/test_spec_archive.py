"""
Tests for SPEC 归档能力（add-spec-archive）。

覆盖 data.py::archive_spec / is_spec_archived / spec_summary.archived /
record_project_event 与 server.py::POST /api/spec-archive 端点，以及
daemon 自动归档（auto_archive_check）与配置校验（archive.auto_threshold）。
"""
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.dashboard import data as dash_data
from core.dashboard.data import (
    archive_spec, is_spec_archived, parse_state, record_project_event,
    spec_summary,
)


def _make_project(root: Path, specs: dict) -> Path:
    """构造最小可用项目：.fenix/STATE.md + openspec/changes/<name>/ 目录。

    specs: {name: {"status": ..., "updated": ...}}
    """
    (root / "openspec" / "changes").mkdir(parents=True, exist_ok=True)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, entry in specs.items():
        (root / "openspec" / "changes" / name).mkdir(exist_ok=True)
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
        (self.root / "openspec" / "changes" / "spec-a" / "tasks.md").write_text(
            "# T", encoding="utf-8")
        result = archive_spec(self.root, "spec-a")
        self.assertTrue(result["ok"])
        self.assertTrue(result["found"])
        self.assertTrue(result["to"].endswith("spec-a"))
        self.assertIn("archive", result["to"])
        # 目录已移动
        self.assertFalse((self.root / "openspec" / "changes" / "spec-a").is_dir())
        archive_dir = self.root / "openspec" / "changes" / "archive"
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
        self.assertTrue((self.root / "openspec" / "changes" / "spec-x").is_dir())
        self.assertIn("spec-x", parse_state(self.root))

    def test_archive_target_exists_no_overwrite(self):
        _make_project(self.root, {"spec-c": {"status": "pushed"}})
        tgt = (self.root / "openspec" / "changes" / "archive"
               / f"{date.today().isoformat()}-spec-c")
        tgt.mkdir(parents=True)
        (tgt / "keep.txt").write_text("keep", encoding="utf-8")
        result = archive_spec(self.root, "spec-c")
        self.assertFalse(result["ok"])
        self.assertIn("已存在", result["error"])
        self.assertTrue((self.root / "openspec" / "changes" / "spec-c").is_dir())
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
        shutil.rmtree(self.root / "openspec" / "changes" / "spec-d")
        result = archive_spec(self.root, "spec-d")
        self.assertFalse(result["ok"])
        self.assertTrue(result["found"])
        self.assertIn("已归档", result["error"])


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
        shutil.rmtree(self.root / "openspec" / "changes" / "arch-spec")
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
        (self.root / "openspec" / "changes").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_project(self, specs: dict):
        """specs: {name: {"status": ..., "updated": ...}}"""
        for name, entry in specs.items():
            (self.root / "openspec" / "changes" / name).mkdir(exist_ok=True)
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
        self.assertFalse((self.root / "openspec" / "changes" / "a").is_dir())
        self.assertFalse((self.root / "openspec" / "changes" / "b").is_dir())
        self.assertTrue((self.root / "openspec" / "changes" / "c").is_dir())
        self.assertTrue((self.root / "openspec" / "changes" / "d").is_dir())
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
        self.assertTrue((self.root / "openspec" / "changes" / "x").is_dir())

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
        conflict = self.root / "openspec" / "changes" / "archive" / f"{date.today().isoformat()}-f1"
        conflict.mkdir(parents=True)
        (conflict / "sentinel.txt").write_text("keep", encoding="utf-8")
        self._set_threshold(1)
        from core.config import ConfigLoader
        from core.dashboard.data import auto_archive_check
        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["archived"], 1)
        self.assertEqual(r["skipped"], 1)
        # f1 不动（冲突），f2 归档
        self.assertTrue((self.root / "openspec" / "changes" / "f1").is_dir())
        self.assertFalse((self.root / "openspec" / "changes" / "f2").is_dir())

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
        shutil.rmtree(self.root / "openspec" / "changes" / "n1")
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
    (proot / "openspec" / "changes" / "done-spec").mkdir(parents=True)
    (proot / "openspec" / "changes" / "doing-spec").mkdir(parents=True)
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
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
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
        assert not (proot / "openspec" / "changes" / "done-spec").is_dir()
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
        assert (proot / "openspec" / "changes" / "doing-spec").is_dir()
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
        tgt = proot / "openspec" / "changes" / "archive" / f"{date.today().isoformat()}-done-spec"
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


if __name__ == "__main__":
    unittest.main()
