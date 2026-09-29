"""
Tests for STATE.md 条目迁出与归档清单（add-archive-state-migration）。

覆盖：
- 迁出原语 StateMachine.evict_spec（原子两步、幂等、清单失败不丢条目）
- 三条归档路径收口（auto / ui / cli）归档成功即迁出、被拒不迁出
- 读侧双源（is_spec_archived / /api/specs 合并 / evo 撞名）
- 存量回填（backfill_archived_entries）与软删除清单兼容
"""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conftest import _TestServer  # noqa: E402

from core.dashboard.data import (  # noqa: E402
    SummaryIndex,
    archive_spec,
    auto_archive_check,
    backfill_archived_entries,
    is_spec_archived,
    parse_archived_state,
    parse_state,
    soft_delete_spec,
)
from core.state_machine import StateMachine  # noqa: E402


def _write_state(root: Path, specs: dict) -> Path:
    """构造最小 STATE.md。specs: {name: {"status": ...}}；_dir=False 时建目录。"""
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    (root / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    lines = ["# Fenix Project State", "", "## Specs", ""]
    for name, entry in specs.items():
        entry = dict(entry)
        if entry.pop("_dir", True):
            (root / "spec" / "changes" / name).mkdir(exist_ok=True)
        lines += [
            f"### {name}",
            f"- status: {entry['status']}",
            f"- priority: {entry.get('priority', 5)}",
            f"- created: {entry.get('created', '2026-01-01T00:00:00+00:00')}",
            f"- updated: {entry.get('updated', '2026-01-02T00:00:00+00:00')}",
            "- error: null",
            "- depends_on: null",
            "",
        ]
    (root / ".fenix" / "STATE.md").write_text("\n".join(lines), encoding="utf-8")
    return root


def _sm(root: Path) -> StateMachine:
    return StateMachine(root / ".fenix" / "STATE.md")


# ── 1.3 迁出原语 ──────────────────────────────────────────────────────


class TestEvictSpec(unittest.TestCase):
    """evict_spec：迁出/幂等/清单失败不丢条目/首迁创建/活跃流转不触碰清单。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        _write_state(self.root, {"spec-a": {"status": "pushed"},
                                 "spec-b": {"status": "done"}})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_evict_moves_entry_to_manifest(self):
        r = _sm(self.root).evict_spec("spec-a", archived_by="ui")
        self.assertTrue(r["ok"])
        self.assertTrue(r["found"])
        self.assertTrue(r["archived_at"])
        # 活跃条目消失，他条目不受影响
        active = parse_state(self.root)
        self.assertNotIn("spec-a", active)
        self.assertIn("spec-b", active)
        # 清单含该条目 + 溯源字段，原字段保留
        manifest = parse_archived_state(self.root)
        self.assertIn("spec-a", manifest)
        self.assertEqual(manifest["spec-a"]["status"], "pushed")
        self.assertEqual(manifest["spec-a"]["archived_by"], "ui")
        self.assertTrue(manifest["spec-a"]["archived_at"])

    def test_manifest_missing_first_evict_creates_and_parse_empty(self):
        # 清单缺失 → 解析返回空 dict 不报错
        self.assertEqual(parse_archived_state(self.root), {})
        self.assertFalse((self.root / ".fenix" / "STATE.archive.md").exists())
        r = _sm(self.root).evict_spec("spec-a", archived_by="cli")
        self.assertTrue(r["ok"])
        path = self.root / ".fenix" / "STATE.archive.md"
        self.assertTrue(path.exists())
        self.assertIn("spec-a", parse_archived_state(self.root))

    def test_evict_idempotent(self):
        sm = _sm(self.root)
        self.assertTrue(sm.evict_spec("spec-a", archived_by="ui")["ok"])
        path = self.root / ".fenix" / "STATE.archive.md"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        r = sm.evict_spec("spec-a", archived_by="ui")
        # 重复迁出：未找到语义，清单不变，不报错
        self.assertFalse(r["found"])
        self.assertFalse(r["ok"])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_evict_manifest_write_failure_keeps_entry(self):
        from unittest.mock import patch

        sm = _sm(self.root)
        with patch.object(StateMachine, "_upsert_archive_entry_locked",
                          side_effect=OSError("simulated manifest write failure")):
            r = sm.evict_spec("spec-a", archived_by="ui")
        self.assertFalse(r["ok"])
        self.assertTrue(r["found"])
        self.assertIn("simulated manifest write failure", r["error"])
        # STATE.md 条目原样保留（不丢条目）
        self.assertIn("spec-a", parse_state(self.root))
        # 清单未被创建
        self.assertEqual(parse_archived_state(self.root), {})

    def test_evict_state_rewrite_failure_keeps_entry_in_state(self):
        """STATE.md 重写失败 → 条目留活跃（清单已有副本，无害双源中间态）。"""
        from unittest.mock import patch

        sm = _sm(self.root)
        with patch.object(StateMachine, "_write_all_locked",
                          side_effect=OSError("simulated state rewrite failure")):
            r = sm.evict_spec("spec-a", archived_by="ui")
        self.assertFalse(r["ok"])
        self.assertIn("spec-a", parse_state(self.root))
        # 清单已有副本（回填下一轮收敛）
        self.assertIn("spec-a", parse_archived_state(self.root))

    def test_evict_non_terminal_rejected(self):
        (self.root / ".fenix" / "STATE.md").write_text(
            "# Fenix Project State\n\n## Specs\n\n"
            "### spec-x\n- status: implementing\n- updated: 2026-01-02T00:00:00+00:00\n",
            encoding="utf-8",
        )
        r = _sm(self.root).evict_spec("spec-x", archived_by="backfill")
        self.assertFalse(r["ok"])
        self.assertTrue(r["found"])
        self.assertIn("仅终态", r["error"])
        self.assertIn("spec-x", parse_state(self.root))
        self.assertEqual(parse_archived_state(self.root), {})

    def test_evict_invalid_archived_by_rejected(self):
        with self.assertRaises(ValueError):
            _sm(self.root).evict_spec("spec-a", archived_by="hand-mv")
        # STATE 与清单均不变
        self.assertIn("spec-a", parse_state(self.root))
        self.assertEqual(parse_archived_state(self.root), {})

    def test_active_transition_does_not_touch_manifest(self):
        sm = _sm(self.root)
        self.assertTrue(sm.evict_spec("spec-a", archived_by="ui")["ok"])
        path = self.root / ".fenix" / "STATE.archive.md"
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        # 活跃 SPEC 状态流转（update_spec 全量重写 STATE.md）不得触碰清单
        self.assertTrue(sm.update_spec("spec-b", {"updated": "2026-06-01T00:00:00+00:00"}))
        self.assertIn("spec-b", parse_state(self.root))
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_remove_archived_entry_removes_section(self):
        sm = _sm(self.root)
        sm.evict_spec("spec-a", archived_by="ui")
        sm.evict_spec("spec-b", archived_by="backfill")
        self.assertTrue(sm.remove_archived_entry("spec-a"))
        manifest = parse_archived_state(self.root)
        self.assertNotIn("spec-a", manifest)
        self.assertIn("spec-b", manifest)
        # 幂等：再移除返回 False
        self.assertFalse(sm.remove_archived_entry("spec-a"))


# ── 2.1/2.4 三条归档路径收口 ──────────────────────────────────────────


class TestThreeArchivePaths(unittest.TestCase):
    """ui / auto / cli 三路径归档成功即迁出；被拒不迁出。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ui_archive_evicts(self):
        _write_state(self.root, {"spec-ui": {"status": "pushed"}})
        result = archive_spec(self.root, "spec-ui")
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("state_evicted"))
        self.assertNotIn("spec-ui", parse_state(self.root))
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["spec-ui"]["archived_by"], "ui")

    def test_ui_archive_evict_failure_degrades_to_warning(self):
        """迁出失败降级 evict_warning，不改 ok 语义、不回滚移动。"""
        from unittest.mock import patch

        _write_state(self.root, {"spec-w": {"status": "done"}})
        with patch.object(StateMachine, "evict_spec",
                          side_effect=OSError("simulated evict failure")):
            result = archive_spec(self.root, "spec-w")
        self.assertTrue(result["ok"])
        self.assertIn("simulated evict failure", result["evict_warning"])
        # 目录已移动（不回滚）、条目留在 STATE.md（待回填）
        self.assertFalse((self.root / "spec" / "changes" / "spec-w").is_dir())
        self.assertIn("spec-w", parse_state(self.root))
        self.assertEqual(parse_archived_state(self.root), {})

    def test_auto_archive_evicts_with_auto_by(self):
        _write_state(self.root, {
            "auto-1": {"status": "done", "updated": "2026-01-01T00:00:00+00:00"},
            "auto-2": {"status": "done", "updated": "2026-01-02T00:00:00+00:00"},
            "keep": {"status": "done", "updated": "2026-01-03T00:00:00+00:00"},
        })
        (self.root / ".fenix" / "config.yaml").write_text(
            "project:\n  name: t\narchive:\n  auto_threshold: 1\n", encoding="utf-8")
        from core.config import ConfigLoader

        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        # 阈值 1、3 条终态未归档 → 归档最久 2 条，keep 保留（1 ≤ 阈值）
        self.assertEqual(r["archived"], 2)
        active = parse_state(self.root)
        self.assertNotIn("auto-1", active)
        self.assertNotIn("auto-2", active)
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["auto-1"]["archived_by"], "auto")
        self.assertEqual(manifest["auto-2"]["archived_by"], "auto")
        self.assertIn("keep", active)

    def test_archive_rejected_does_not_evict(self):
        """目标已存在（conflict）与非终态被拒：STATE 与清单均不变。"""
        _write_state(self.root, {"spec-c": {"status": "pushed"},
                                 "spec-n": {"status": "implementing"}})
        tgt = self.root / "spec" / "archive" / f"{date.today().isoformat()}-spec-c"
        tgt.mkdir(parents=True)
        r1 = archive_spec(self.root, "spec-c")
        self.assertFalse(r1["ok"])
        r2 = archive_spec(self.root, "spec-n")
        self.assertFalse(r2["ok"])
        active = parse_state(self.root)
        self.assertIn("spec-c", active)
        self.assertIn("spec-n", active)
        self.assertEqual(parse_archived_state(self.root), {})

    def test_cli_archive_evicts_with_cli_by(self):
        _write_state(self.root, {"spec-s": {"status": "pushed"}})
        script = Path(__file__).resolve().parent.parent / "bin" / "fenix_archive.py"
        s = importlib.util.spec_from_file_location("fenix_archive_migration", script)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
        result = mod.archive_change(self.root, "spec-s")
        self.assertIn("state_evicted", result)
        self.assertTrue(result.get("state_evicted"))
        self.assertNotIn("spec-s", parse_state(self.root))
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["spec-s"]["archived_by"], "cli")

    def test_cli_archive_without_state_entry_ok(self):
        """STATE 无条目（手工创建目录）→ 归档成功 + 说明性字段，不报错。"""
        (self.root / "spec" / "changes" / "handmade").mkdir(parents=True)
        (self.root / "spec" / "changes" / "handmade" / "tasks.md").write_text(
            "# T", encoding="utf-8")
        script = Path(__file__).resolve().parent.parent / "bin" / "fenix_archive.py"
        s = importlib.util.spec_from_file_location("fenix_archive_migration2", script)
        mod = importlib.util.module_from_spec(s)
        s.loader.exec_module(mod)
        result = mod.archive_change(self.root, "handmade")
        self.assertIn("from", result)  # 归档移动成功
        self.assertFalse(result.get("state_evicted"))
        self.assertTrue(result.get("state_evict_note"))
        self.assertEqual(parse_archived_state(self.root), {})


# ── 3.1/3.4 读侧双源 ─────────────────────────────────────────────────


class TestReadSideDualSource(unittest.TestCase):
    """is_spec_archived 双源判定与 evo 撞名并入清单键集。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_spec_archived_after_evict(self):
        # _dir=False：目录已随归档移走（本原语只迁条目，不移目录）
        _write_state(self.root, {"arch-e": {"status": "done", "_dir": False}})
        _sm(self.root).evict_spec("arch-e", archived_by="backfill")
        # 已迁出（活跃 STATE 无条目、目录缺失）仍判已归档
        self.assertTrue(is_spec_archived(self.root, "arch-e"))
        # 未注册名不误判
        self.assertFalse(is_spec_archived(self.root, "ghost"))

    def test_is_spec_archived_active_short_circuit(self):
        _write_state(self.root, {"live": {"status": "implementing"}})
        self.assertFalse(is_spec_archived(self.root, "live"))

    def test_evo_candidate_conflicts_with_manifest(self):
        from core.evolution import resolve_spec_name

        # _dir=False：排除活跃目录命中，专测清单条目触发的撞名。
        # evo 候选名带 evo- 前缀，清单条目须同名（evo-other）才命中该检查。
        _write_state(self.root, {"evo-other": {"status": "done", "_dir": False}})
        _sm(self.root).evict_spec("evo-other", archived_by="backfill")
        got = resolve_spec_name("other", "abc123", self.root, None)
        self.assertEqual(got, "evo-other-abc123")


class TestSummaryCacheDirExistence(unittest.TestCase):
    """BUG-01 回归：SummaryIndex 缓存签名须含活跃目录存在性。

    夹具先写 STATE.md、后建目录（仅含不入签名文件 proposal.md）的窗口里
    首建索引，archived 以「目录缺失+条目在活跃」算成 True 入缓存；目录重建
    后若其余签名零变化，陈旧 True 永不重算 → 前端未归档视图丢行/已归档视图
    反向多行（web-ui-archive-evict-archived-view 实证）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @staticmethod
    def _by_name(items):
        return {s["name"]: s for s in items}

    def test_dir_late_creation_invalidates_archived_cache(self):
        # 目录缺失窗口：条目在活跃 STATE → archived=True 入缓存
        _write_state(self.root, {"late-dir": {"status": "pushed", "_dir": False}})
        idx = SummaryIndex()
        first = self._by_name(idx.get(self.root))
        self.assertTrue(first["late-dir"]["archived"])

        # 目录重建且仅含不入签名文件（proposal.md）——BUG-01 触发时序
        late = self.root / "spec" / "changes" / "late-dir"
        late.mkdir(parents=True)
        (late / "proposal.md").write_text("# 探针\n", encoding="utf-8")
        second = self._by_name(idx.get(self.root))
        self.assertFalse(second["late-dir"]["archived"])

    def test_dir_removal_invalidates_archived_cache(self):
        # 反向：目录存在 archived=False，目录移除后须重算为 True（中间态幽灵）
        _write_state(self.root, {"gone-dir": {"status": "done"}})
        idx = SummaryIndex()
        first = self._by_name(idx.get(self.root))
        self.assertFalse(first["gone-dir"]["archived"])

        shutil.rmtree(self.root / "spec" / "changes" / "gone-dir")
        second = self._by_name(idx.get(self.root))
        self.assertTrue(second["gone-dir"]["archived"])


# ── 3.2/3.4 API 合并清单条目 ─────────────────────────────────────────


def _make_api_project(tmp_path):
    """API 夹具项目：活跃 done-spec + 将被迁出的 arch-spec（含文档）。"""
    proot = tmp_path / "proj-mig"
    (proot / ".fenix" / "logs").mkdir(parents=True)
    (proot / "spec" / "changes" / "done-spec").mkdir(parents=True)
    (proot / "spec" / "changes" / "arch-spec").mkdir(parents=True)
    (proot / "spec" / "changes" / "arch-spec" / "tasks.md").write_text(
        "# T\n\n## 1. 阶段一\n\n- [x] 1.1 a\n", encoding="utf-8")
    (proot / "spec" / "changes" / "arch-spec" / "proposal.md").write_text(
        "# Proposal\n\n迁移后仍可读\n", encoding="utf-8")
    (proot / ".fenix" / "STATE.md").write_text(
        "# Fenix Project State\n\n## Specs\n\n"
        "### done-spec\n- status: pushed\n- priority: 1\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-02-02T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n\n"
        "### arch-spec\n- status: pushed\n- priority: 2\n"
        "- created: 2026-01-01T00:00:00+00:00\n- updated: 2026-02-01T00:00:00+00:00\n"
        "- error: null\n- depends_on: null\n",
        encoding="utf-8",
    )
    (proot / ".fenix" / "config.yaml").write_text(
        "project:\n  name: fake\n", encoding="utf-8")
    return proot


class _MigrationServer(_TestServer):
    """复用 conftest _TestServer，仅换端口段避免与并行用例冲突。"""

    def __init__(self, registry, static_dir):
        from core.dashboard.server import DashboardHTTPServer, find_free_port
        import threading

        self.port = find_free_port(20400)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), registry, static_dir)
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()


@pytest.fixture()
def migration_server(tmp_path):
    proot = _make_api_project(tmp_path)
    cfg = tmp_path / "dashboard.yaml"
    from core.dashboard.registry import Registry

    reg = Registry(config_path=cfg)
    reg.save({"port": 8787, "projects": [{"name": "proj-mig", "path": str(proot)}],
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _MigrationServer(
        reg, Path(__file__).resolve().parent.parent / "core" / "dashboard" / "static")
    yield proot, srv
    srv.stop()


class TestApiSpecsMergedManifest:
    """/api/specs 合并清单条目：已归档视图可见、字段齐全、双源不重复行。"""

    def test_evicted_spec_visible_with_traceability(self, migration_server):
        proot, srv = migration_server
        status, body = srv.post("/api/spec-archive?project=proj-mig&spec=arch-spec")
        assert status == 200
        assert body["state_evicted"] is True
        status, data = srv.get("/api/specs?project=proj-mig")
        assert status == 200
        by_name = {s["name"]: s for s in data["specs"]}
        # 已迁出条目仍在列表且 archived=true、溯源字段齐全
        assert "arch-spec" in by_name
        row = by_name["arch-spec"]
        assert row["archived"] is True
        assert row["archived_by"] == "ui"
        assert row["archived_at"]
        assert row["status"] == "pushed"
        # 活跃条目不误标
        assert by_name["done-spec"]["archived"] is False
        assert by_name["done-spec"]["archived_by"] is None

    def test_double_source_single_row_active_wins(self, migration_server):
        """迁出失败中间态（双源并存）→ 单行、活跃侧字段优先。"""
        proot, srv = migration_server
        # 手工构造双源并存：清单有小节 + 活跃 STATE 仍保留条目
        sm = StateMachine(proot / ".fenix" / "STATE.md")
        entry = dict(sm.read_one("arch-spec"))
        entry["archived_at"] = "2026-03-01T00:00:00+00:00"
        entry["archived_by"] = "ui"
        sm._upsert_archive_entry_locked("arch-spec", entry)
        status, data = srv.get("/api/specs?project=proj-mig")
        assert status == 200
        rows = [s for s in data["specs"] if s["name"] == "arch-spec"]
        assert len(rows) == 1
        # 活跃侧优先：无溯源字段（活跃条目无该键）
        assert rows[0]["archived_at"] is None

    def test_evicted_detail_and_doc_readable(self, migration_server):
        proot, srv = migration_server
        status, _ = srv.post("/api/spec-archive?project=proj-mig&spec=arch-spec")
        assert status == 200
        # 详情可进（读自归档目录）
        status, detail = srv.get("/api/specs/arch-spec?project=proj-mig")
        assert status == 200
        assert detail.get("name") == "arch-spec"
        assert detail.get("tasks")  # 任务清单可读（parse_tasks 列表非空）
        # 文档可读（resolve_spec_dir 归档回退）
        status, doc = srv.get(
            "/api/spec-doc?project=proj-mig&spec=arch-spec&doc=proposal")
        assert status == 200
        assert doc["found"] is True
        assert "迁移后仍可读" in doc["content"]

    def test_overview_counts_active_only(self, migration_server):
        proot, srv = migration_server
        status, _ = srv.post("/api/spec-archive?project=proj-mig&spec=arch-spec")
        assert status == 200
        status, ov = srv.get("/api/overview")
        assert status == 200
        proj = next(p for p in ov["projects"] if p["name"] == "proj-mig")
        # 统计只算活跃：迁出条目不计入
        assert proj["spec_count"] == 1


# ── 4.1-4.4 存量回填与软删除 ─────────────────────────────────────────


class TestBackfill(unittest.TestCase):
    """回填批量迁出 / 幂等 / 非终态孤儿保留 / 阈值 0 仍执行。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backfill_evicts_orphans(self):
        _write_state(self.root, {
            "old-1": {"status": "pushed", "_dir": False},
            "old-2": {"status": "done", "_dir": False},
            "live": {"status": "done"},
            "wip": {"status": "implementing", "_dir": False},
        })
        r = backfill_archived_entries(self.root)
        self.assertEqual(r["scanned"], 3)
        self.assertEqual(r["evicted"], 2)
        self.assertEqual(r["nonterminal_skipped"], 1)
        active = parse_state(self.root)
        self.assertNotIn("old-1", active)
        self.assertNotIn("old-2", active)
        self.assertIn("live", active)
        self.assertIn("wip", active)  # 非终态孤儿保留
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["old-1"]["archived_by"], "backfill")
        self.assertEqual(manifest["old-2"]["archived_by"], "backfill")

    def test_backfill_idempotent_second_round_zero(self):
        _write_state(self.root, {"old-a": {"status": "done", "_dir": False}})
        r1 = backfill_archived_entries(self.root)
        self.assertEqual(r1["evicted"], 1)
        r2 = backfill_archived_entries(self.root)
        self.assertEqual(r2["scanned"], 0)
        self.assertEqual(r2["evicted"], 0)
        # 清单无重复条目
        manifest = parse_archived_state(self.root)
        self.assertEqual(list(manifest.keys()), ["old-a"])

    def test_backfill_inside_auto_archive_check_when_threshold_zero(self):
        """阈值 0：阈值归档禁用，回填仍执行（先回填后阈值归档）。"""
        _write_state(self.root, {"z-old": {"status": "pushed", "_dir": False}})
        (self.root / ".fenix" / "config.yaml").write_text(
            "project:\n  name: t\narchive:\n  auto_threshold: 0\n", encoding="utf-8")
        from core.config import ConfigLoader

        r = auto_archive_check(self.root, ConfigLoader.resolve_config(self.root))
        self.assertEqual(r["threshold"], 0)
        self.assertEqual(r["archived"], 0)
        self.assertEqual(r["backfill"]["evicted"], 1)
        self.assertNotIn("z-old", parse_state(self.root))
        self.assertIn("z-old", parse_archived_state(self.root))


class TestSoftDeleteManifestCompat(unittest.TestCase):
    """软删除：清单条目 found 判定 + 双源清理。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_soft_delete_manifest_only_entry(self):
        _write_state(self.root, {"m-only": {"status": "done"}})
        _sm(self.root).evict_spec("m-only", archived_by="ui")
        r = soft_delete_spec(self.root, "m-only")
        self.assertTrue(r["found"])
        self.assertIsNone(r["error"])
        # 清单小节已清
        self.assertNotIn("m-only", parse_archived_state(self.root))

    def test_soft_delete_double_source_cleans_both(self):
        _write_state(self.root, {"dual": {"status": "done"}})
        sm = _sm(self.root)
        entry = dict(sm.read_one("dual"))
        entry["archived_at"] = "2026-03-01T00:00:00+00:00"
        entry["archived_by"] = "ui"
        sm._upsert_archive_entry_locked("dual", entry)  # 双源并存中间态
        r = soft_delete_spec(self.root, "dual")
        self.assertTrue(r["found"])
        self.assertIsNone(r["error"])
        self.assertNotIn("dual", parse_state(self.root))
        self.assertNotIn("dual", parse_archived_state(self.root))

    def test_soft_delete_unknown_still_not_found(self):
        _write_state(self.root, {"x": {"status": "done"}})
        r = soft_delete_spec(self.root, "ghost")
        self.assertEqual(r, {"found": False})


if __name__ == "__main__":
    unittest.main()
