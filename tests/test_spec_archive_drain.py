"""evo-spec-changes-archive-drain 专项测试。

覆盖 specs/spec-archive-drain/spec.md 五条规则：

- R1 阈值排水：50/50 饱和态可触发，单轮排水至阈值下（50→49 归档 1 条）；
- R2 时效归档：终态 + verification-report.md + 目录 mtime 滞留 ≥ 72h，
  3 天边界（<72h 不归档 / ≥72h 归档，STATE 路径）；
- R3 孤儿接管：同判据经 archive_spec 孤儿形态入参归档
  （archived_by=auto-orphan，不写 STATE/清单条目），其余孤儿仅盘点；
- R4 每日滞留盘点：24h 去重，①报告+滞留≥3天 / ②孤儿（无条件）/
  ③终态无报告 三类入清单；
- R5 安全边界：非终态活跃目录、无报告目录不被误归档；
- auto_threshold=0 禁用全部自动归档动作（backfill 与盘点信号不受约束）。
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from core.dashboard.data import spec_archive
from core.dashboard.data.state import parse_archived_state, parse_state


class _CaptureLogger:
    """duck-type (component, message) 签名 logger，捕获 _archive_log 出口记录。"""

    def __init__(self):
        self.records = []

    def info(self, component, msg):
        self.records.append(("info", msg))

    def warning(self, component, msg):
        self.records.append(("warning", msg))


class SpecArchiveDrainTestBase(unittest.TestCase):
    """公共夹具：临时项目根 + STATE/目录/配置写手 + 盘点水位重置。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.root = Path(self.tmpdir)
        (self.root / ".fenix").mkdir(parents=True)
        (self.root / "spec" / "changes").mkdir(parents=True)
        # 每日盘点 24h 去重水位是模块级状态：逐用例重置，保证「首次调用必触发」
        spec_archive._daily_audit_last_ts = 0.0

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        spec_archive._daily_audit_last_ts = 0.0

    def _add_spec(self, name, *, report=False, age_seconds=None):
        """在 changes/ 建目录，可选写验证报告并把目录 mtime 拨到 now-age。"""
        d = self.root / "spec" / "changes" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.md").write_text("# t\n", encoding="utf-8")
        if report:
            (d / "verification-report.md").write_text(
                "# verification report\n", encoding="utf-8")
        if age_seconds is not None:
            ts = time.time() - age_seconds
            os.utime(d, (ts, ts))
        return d

    def _write_state(self, specs: dict):
        """specs: {name: {"status": ..., "updated": ...}}；孤儿目录不写条目。"""
        lines = ["# Fenix Project State", "", "## Specs", ""]
        for name, entry in specs.items():
            lines += [
                f"### {name}",
                f"- status: {entry['status']}",
                f"- updated: {entry.get('updated', '2026-01-01T00:00:00+00:00')}",
                "",
            ]
        (self.root / ".fenix" / "STATE.md").write_text(
            "\n".join(lines), encoding="utf-8")

    def _set_threshold(self, threshold: int):
        (self.root / ".fenix" / "config.yaml").write_text(
            f"project:\n  name: t\narchive:\n  auto_threshold: {threshold}\n",
            encoding="utf-8")

    def _check(self, logger=None):
        from core.config import ConfigLoader
        return spec_archive.auto_archive_check(
            self.root, ConfigLoader.resolve_config(self.root), logger)


# ── R1 阈值饱和排水 ──────────────────────────────────────────────────────

class TestThresholdSaturationDrain(SpecArchiveDrainTestBase):
    """>= 阈值即触发；50/50 饱和态单轮排水 1 条至阈值下。"""

    def test_saturation_50_of_50_triggers_and_drains_to_below(self):
        """计数恰等于阈值 50（旧 > 语义恒不触发的冻结点）→ 触发并排水 1 条。"""
        specs = {}
        for i in range(50):
            name = f"sat-{i:02d}"
            # updated 升序：sat-00 最久（分钟位递增，均为合法 ISO 时刻）
            specs[name] = {
                "status": "done",
                "updated": f"2026-01-01T00:{i:02d}:00+00:00",
            }
        self._write_state(specs)
        for name in specs:
            self._add_spec(name)
        self._set_threshold(50)

        r = self._check()
        # 50 >= 50 → 触发，排水至低于阈值需 1 条（49 < 50 收敛）
        self.assertEqual(r["archived"], 1)
        self.assertEqual(r["target_count"], 1)
        self.assertEqual(r["total_terminal_unarchived"], 50)
        remaining = sorted(
            p.name for p in (self.root / "spec" / "changes").iterdir())
        self.assertEqual(len(remaining), 49)
        # updated 升序最久的 sat-00 先归档
        self.assertNotIn("sat-00", remaining)
        self.assertIn("sat-01", remaining)
        # 台账：条目迁出至归档清单，archived_by=auto
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["sat-00"].get("archived_by"), "auto")
        self.assertNotIn("sat-00", parse_state(self.root))
        # 时效归档不误伤（新目录无报告）
        self.assertEqual(r["age_archived"], 0)
        self.assertEqual(r["orphan_archived"], 0)

    def test_second_round_below_threshold_no_action(self):
        """排水后 49 < 50：第二轮无排水动作（稳态水位附近小幅波动）。"""
        specs = {
            f"sat-{i:02d}": {
                "status": "done",
                "updated": f"2026-01-01T00:{i:02d}:00+00:00",
            }
            for i in range(50)
        }
        self._write_state(specs)
        for name in specs:
            self._add_spec(name)
        self._set_threshold(50)
        self._check()
        r2 = self._check()
        self.assertEqual(r2["archived"], 0)
        self.assertEqual(r2["target_count"], 0)
        self.assertEqual(
            len(list((self.root / "spec" / "changes").iterdir())), 49)


# ── R2/R3 时效归档 3 天边界（目录 mtime 72h） ────────────────────────────

class TestAgeBoundary(SpecArchiveDrainTestBase):
    """<72h 不归档 / ≥72h 归档；STATE 路径与孤儿路径同判据分流。"""

    def test_state_path_72h_boundary(self):
        """终态+报告：71h 保留 / 73h 归档（archived_by=auto 迁出清单）。"""
        self._write_state({
            "age-young": {"status": "pushed",
                          "updated": "2026-01-01T00:00:00+00:00"},
            "age-old": {"status": "pushed",
                        "updated": "2026-01-02T00:00:00+00:00"},
        })
        self._add_spec("age-young", report=True, age_seconds=71 * 3600)
        self._add_spec("age-old", report=True, age_seconds=73 * 3600)
        self._set_threshold(10)  # 2 < 10：R1 不接管，隔离 R2 时效行为

        r = self._check()
        self.assertEqual(r["archived"], 0)
        self.assertEqual(r["age_archived"], 1)
        changes = self.root / "spec" / "changes"
        self.assertTrue((changes / "age-young").is_dir())
        self.assertFalse((changes / "age-old").is_dir())
        manifest = parse_archived_state(self.root)
        self.assertEqual(manifest["age-old"].get("archived_by"), "auto")
        self.assertNotIn("age-young", manifest)
        self.assertNotIn("age-old", parse_state(self.root))

    def test_orphan_path_72h_boundary(self):
        """孤儿+报告：71h 仅盘点 / 73h 经孤儿形态归档（auto-orphan 溯源）。"""
        self._write_state({"keep-active": {"status": "implementing"}})
        self._add_spec("keep-active")  # 活跃在途，任何规则不接管
        self._add_spec("orphan-young", report=True, age_seconds=71 * 3600)
        self._add_spec("orphan-old", report=True, age_seconds=73 * 3600)
        self._set_threshold(10)
        log = _CaptureLogger()

        r = self._check(logger=log)
        self.assertEqual(r["orphan_archived"], 1)
        self.assertEqual(r["age_archived"], 0)
        changes = self.root / "spec" / "changes"
        self.assertTrue((changes / "orphan-young").is_dir())
        self.assertFalse((changes / "orphan-old").is_dir())
        # 孤儿形态：不写 STATE/清单条目（design 决策 6）
        self.assertNotIn("orphan-old", parse_state(self.root))
        self.assertNotIn("orphan-old", parse_archived_state(self.root))
        # 归档台账溯源：archived_by=auto-orphan 随日志与返回值留痕
        self.assertTrue(any(
            "orphan-old" in m and "auto-orphan" in m
            for _lv, m in log.records))
        # 盘点清单：未满足条件的孤儿（71h）仍被 ② 无条件列示
        self.assertIn("orphan-young", r["audit"]["stale_dirs"])
        self.assertNotIn("keep-active", r["audit"]["stale_dirs"])

    def test_orphan_no_report_only_audited(self):
        """孤儿无报告：永不归档，仅入每日盘点清单（R3 分流保守侧）。"""
        self._write_state({})
        self._add_spec("orphan-nr", age_seconds=73 * 3600)
        self._set_threshold(10)

        r = self._check()
        self.assertEqual(r["orphan_archived"], 0)
        self.assertEqual(r["age_archived"], 0)
        self.assertTrue(
            (self.root / "spec" / "changes" / "orphan-nr").is_dir())
        self.assertIn("orphan-nr", r["audit"]["stale_dirs"])


# ── R5 安全边界：不误归档 ────────────────────────────────────────────────

class TestNeverArchiveGuard(SpecArchiveDrainTestBase):
    """非终态活跃目录与无报告目录不被误归档，仅盘点暴露。"""

    def test_non_terminal_with_old_report_not_archived(self):
        """implementing + 报告 + 超期：R5 永不归档，盘点 ① 暴露。"""
        self._write_state({"wip-old": {"status": "implementing"}})
        self._add_spec("wip-old", report=True, age_seconds=73 * 3600)
        self._set_threshold(10)

        r = self._check()
        self.assertEqual(r["age_archived"], 0)
        self.assertEqual(r["archived"], 0)
        self.assertTrue(
            (self.root / "spec" / "changes" / "wip-old").is_dir())
        self.assertNotIn("wip-old", parse_archived_state(self.root))
        self.assertIn("wip-old", r["audit"]["stale_dirs"])

    def test_terminal_without_report_not_archived(self):
        """终态无报告 + 超期：R1 低于阈值不接管、R2 无报告不接管 → 盘点 ③。"""
        self._write_state({"nr-old": {"status": "done"}})
        self._add_spec("nr-old", age_seconds=73 * 3600)
        self._set_threshold(10)  # 1 < 10：R1 不触发

        r = self._check()
        self.assertEqual(r["archived"], 0)
        self.assertEqual(r["age_archived"], 0)
        self.assertTrue(
            (self.root / "spec" / "changes" / "nr-old").is_dir())
        self.assertIn("nr-old", r["audit"]["stale_dirs"])

    def test_active_dir_without_report_untouched(self):
        """无报告的活跃目录（不论终态与否）不被时效归档误伤。"""
        self._write_state({
            "fresh-done": {"status": "done"},
            "fresh-wip": {"status": "verifying"},
        })
        self._add_spec("fresh-done", age_seconds=1)
        self._add_spec("fresh-wip", age_seconds=1)
        self._set_threshold(10)

        r = self._check()
        self.assertEqual(r["age_archived"], 0)
        self.assertEqual(r["orphan_archived"], 0)
        self.assertTrue(
            (self.root / "spec" / "changes" / "fresh-done").is_dir())
        self.assertTrue(
            (self.root / "spec" / "changes" / "fresh-wip").is_dir())


# ── R4 每日滞留盘点：24h 去重 ────────────────────────────────────────────

class TestDailyAuditDedup(SpecArchiveDrainTestBase):
    """盘点信号 24h 去重：首轮发一条 INFO，24h 内不重发。"""

    def test_audit_fires_once_within_24h(self):
        self._write_state({"dup-1": {"status": "done"}})
        self._add_spec("dup-1", age_seconds=73 * 3600)
        self._set_threshold(10)
        log = _CaptureLogger()

        r1 = self._check(logger=log)
        self.assertTrue(r1["audit"]["fired"])
        self.assertIn("dup-1", r1["audit"]["stale_dirs"])
        first = [m for _lv, m in log.records if "每日滞留盘点" in m]
        self.assertEqual(len(first), 1)
        # 一条信号列全三类标记（dup-1：③终态无报告 + ①报告…不成立 → 仅 ③）
        self.assertIn("③终态无报告", first[0])

        r2 = self._check(logger=log)  # 300s 节拍第二轮：24h 去重窗口内
        self.assertFalse(r2["audit"]["fired"])
        self.assertEqual(r2["audit"]["stale_dirs"], [])
        again = [m for _lv, m in log.records if "每日滞留盘点" in m]
        self.assertEqual(len(again), 1)  # 仍只有首条


# ── auto_threshold=0：禁用全部自动归档动作，backfill 与盘点不受约束 ───────

class TestThresholdZeroDisabled(SpecArchiveDrainTestBase):
    """threshold=0 语义：R1/R2/R3 全禁用；backfill 照跑、盘点信号照发。"""

    def test_zero_disables_all_auto_archive_actions(self):
        self._write_state({
            "zero-aged": {"status": "done",
                          "updated": "2026-01-01T00:00:00+00:00"},
            # 无活跃目录的终态条目 → backfill 迁出对象
            "z-old": {"status": "pushed",
                      "updated": "2026-01-02T00:00:00+00:00"},
        })
        self._add_spec("zero-aged", report=True, age_seconds=73 * 3600)
        self._add_spec("zero-orphan", report=True, age_seconds=73 * 3600)
        self._set_threshold(0)

        r = self._check()
        self.assertEqual(r["threshold"], 0)
        # R1/R2/R3 全禁用：终态+报告+超期与孤儿+报告+超期均原地保留
        self.assertEqual(r["archived"], 0)
        self.assertEqual(r["age_archived"], 0)
        self.assertEqual(r["orphan_archived"], 0)
        self.assertEqual(r["target_count"], 0)
        changes = self.root / "spec" / "changes"
        self.assertTrue((changes / "zero-aged").is_dir())
        self.assertTrue((changes / "zero-orphan").is_dir())
        # backfill 不受开关约束：z-old（终态无目录）仍迁出
        self.assertEqual(r["backfill"]["evicted"], 1)
        self.assertIn("z-old", parse_archived_state(self.root))
        self.assertNotIn("z-old", parse_state(self.root))
        # 盘点信号不受开关约束：①报告+滞留≥3天 / ②孤儿 均列示
        self.assertTrue(r["audit"]["fired"])
        self.assertIn("zero-aged", r["audit"]["stale_dirs"])
        self.assertIn("zero-orphan", r["audit"]["stale_dirs"])


if __name__ == "__main__":
    unittest.main()
