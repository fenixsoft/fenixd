"""severity 分级门限（evo-add-codefix-severity-batch-gate 3.1）测试。

覆盖任务 3.1 九类场景：
1. 混合严重度选批分流（major 以上当日批，minor/info 挂起）；
2. regression- 来源条目豁免门限；
3. deferred 跨周批晋级（minor_batch_cadence 窗口到期整组放行）；
4. deferred 期间同指纹合并（既有 upsert 行为回归，不新增立项路径）；
5. severity 升档晋级（重复发现刷到达门限档位清标记按当日批处置）；
6. 链末批判定含挂起集时不计 skipped/lost（is_chain_last_batch 同口径）；
7. 挂起台账与 WIP-defer 台账（fix-deferred.json/_deferred_item_ids）互不串扰；
8. 非法配置回退缺省（major / 7 并告警）；
9. 门限配为最低档 info 时与现状零差异。

注：spec delta 场景「配置写入 min_immediate_severity: critical（非 severity
词表值）→ 回退 major」的括号注记与 design.md §5 相矛盾——design 实测词表为
四档 critical|major|minor|info，critical 属词表内合法档位。本组按 design 以
真正词表外值（high/blocker/非字符串等）验证回退语义，并显式断言 critical
合法保留（测试 test_invalid_min_severity_falls_back / test_valid_min_severity_kept）。
"""

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root() -> Path:
    """建一个带 .fenix/code-review 目录的临时项目根。"""
    td = Path(_mkdtemp("sevgate-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_items(project_root, records):
    """按 item_id 排序写 items.jsonl（对齐 core.code_review 的落盘形态）。"""
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
    )
    path.write_text(content, encoding="utf-8")


def _item(item_id, status="open", first_seen_at=None, **extra):
    rec = {"item_id": item_id, "status": status, "file": f"{item_id}/{item_id}.py",
           "line": 1, "severity": "major", "category": "correctness",
           "title": f"title {item_id}", "description": f"desc {item_id}",
           "suggestion": f"sug {item_id}", "fingerprint": f"fp-{item_id}"}
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    rec.update(extra)
    return rec


def _iso_offset(days=0, seconds=0):
    """相对当前 UTC 时刻偏移的 ISO8601（挂起锚/首见时间注入用）。"""
    return (
        datetime.now(timezone.utc) + timedelta(days=days, seconds=seconds)
    ).isoformat()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo)] + list(args),
                          capture_output=True, text=True)


def _make_repo() -> Path:
    """建一个带 core/a.py 等受控源码文件的临时 git 仓库（generate 用）。"""
    td = Path(_mkdtemp("sevgate-repo-"))
    repo = td / "proj"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    src = repo / "core"
    src.mkdir()
    (src / "a.py").write_text("x=1\n")
    (src / "b.py").write_text("y=2\n")
    (src / "c.py").write_text("z=3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    return repo


class _FakeSM:
    def __init__(self, names=None):
        self.names = set(names or [])

    def read_all(self):
        return {n: {} for n in self.names}

    def add_spec(self, name, entry):
        if name in self.names:
            return False
        self.names.add(name)
        return True


_GATE_DEFAULT = {"min_immediate_severity": "major", "minor_batch_cadence": 7}
_GATE_OFF = {"min_immediate_severity": "info", "minor_batch_cadence": 7}


class _UserConfigIsolated(unittest.TestCase):
    """用户级配置隔离基类：gate 磁盘解析路径（upsert/generate_fix_spec）不随
    宿主 ~/.fenix/config.yaml 漂移（test_default_echo 同款既定模式）。"""

    def setUp(self):
        super().setUp()
        proot = _make_project_root()
        self._isolate = proot / ".user-none"
        patchers = [
            patch("core.config.USER_CONFIG_DIR", self._isolate),
            patch("core.dashboard.data.USER_CONFIG_PATH",
                  self._isolate / "config.yaml"),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)


# ── 谓词纯函数 ────────────────────────────────────────────────────────


class TestSeverityGatePredicate(unittest.TestCase):
    """severity_gate_rank / severity_gate_open 谓词单元（单一函数口径）。"""

    def test_rank_order(self):
        from core.code_review import severity_gate_rank

        self.assertEqual(severity_gate_rank("info"), 0)
        self.assertEqual(severity_gate_rank("minor"), 1)
        self.assertEqual(severity_gate_rank("major"), 2)
        self.assertEqual(severity_gate_rank("critical"), 3)
        # 未知/缺失档位低于任何门限（fail-open 挂起，design §5）
        self.assertEqual(severity_gate_rank("weird"), -1)
        self.assertEqual(severity_gate_rank("high"), -1)
        self.assertEqual(severity_gate_rank(""), -1)
        self.assertEqual(severity_gate_rank(None), -1)

    def test_regression_category_exempt(self):
        from core.code_review import is_regression_finding

        self.assertTrue(is_regression_finding({"category": "regression-timeout"}))
        self.assertTrue(is_regression_finding({"category": "regression-long-test"}))
        self.assertFalse(is_regression_finding({"category": "correctness"}))
        self.assertFalse(is_regression_finding({}))

    def test_gate_open_meets_and_window(self):
        from core.code_review import severity_gate_open

        # 达门限：当日批
        self.assertTrue(severity_gate_open(_item("a"), _GATE_DEFAULT))
        self.assertTrue(severity_gate_open(_item("c", severity="critical"),
                                           _GATE_DEFAULT))
        # 低于门限且无锚（解析失败）→ 挂起
        self.assertFalse(severity_gate_open(_item("m", severity="minor"),
                                            _GATE_DEFAULT))
        # 低于门限但周批窗口到期（挂起锚 8 天前）→ 放行
        due = _item("m2", severity="info",
                    severity_deferred=True,
                    severity_deferred_since=_iso_offset(days=-8))
        self.assertTrue(severity_gate_open(due, _GATE_DEFAULT))
        # 窗口未到（6 天前 < 7 天）→ 仍挂起
        not_due = _item("m3", severity="minor",
                        severity_deferred=True,
                        severity_deferred_since=_iso_offset(days=-6))
        self.assertFalse(severity_gate_open(not_due, _GATE_DEFAULT))
        # 锚缺位回退 first_seen_at（存量条目零回填）
        legacy = _item("m4", severity="minor",
                       first_seen_at=_iso_offset(days=-9))
        self.assertTrue(severity_gate_open(legacy, _GATE_DEFAULT))
        # regression- 来源豁免：低档/未知档位均当日批
        self.assertTrue(severity_gate_open(
            _item("r1", severity="minor", category="regression-timeout"),
            _GATE_DEFAULT))
        self.assertTrue(severity_gate_open(
            _item("r2", severity="weird", category="regression-long-test"),
            _GATE_DEFAULT))
        # now_ts 注入时钟：窗口判定随注入值变化
        fresh = _item("m5", severity="minor",
                      severity_deferred_since=_iso_offset(days=-1))
        import time as _time

        self.assertFalse(severity_gate_open(fresh, _GATE_DEFAULT,
                                            now_ts=_time.time()))


# ── 配置回退（任务 1.1 / 场景「非法配置回退」）────────────────────────


class TestGateConfigFallback(_UserConfigIsolated):
    def test_invalid_min_severity_falls_back(self):
        from core.config import ConfigLoader

        for bad in ("high", "blocker", "MAJOR", 123, None, "", [], {}):
            # logger 名随包别名（fenixd.*）漂移，用根捕获 + 文案断言
            with self.assertLogs(level="WARNING") as cm:
                cfg = ConfigLoader.get_code_review_fix_config(
                    {"admin": {"code_review_fix": {
                        "min_immediate_severity": bad}}}
                )
            self.assertEqual(cfg["min_immediate_severity"], "major",
                             f"{bad!r} 应回退 major")
            self.assertTrue(
                any("min_immediate_severity" in m for m in cm.output),
                f"{bad!r} 应回退并留配置告警")

    def test_invalid_cadence_falls_back(self):
        from core.config import ConfigLoader

        for bad in (0, -3, True, "7", 2.5, None, []):
            with self.assertLogs(level="WARNING") as cm:
                cfg = ConfigLoader.get_code_review_fix_config(
                    {"admin": {"code_review_fix": {"minor_batch_cadence": bad}}}
                )
            self.assertEqual(cfg["minor_batch_cadence"], 7,
                             f"{bad!r} 应回退 7")
            self.assertTrue(
                any("minor_batch_cadence" in m for m in cm.output),
                f"{bad!r} 应回退并留配置告警")

    def test_valid_values_kept(self):
        from core.config import ConfigLoader

        # design §5 词表四档：critical|major|minor|info 均合法（spec delta
        # 场景把 critical 标为「非词表值」与其自身 design 矛盾，按 design）
        for good in ("critical", "major", "minor", "info"):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"min_immediate_severity": good}}}
            )
            self.assertEqual(cfg["min_immediate_severity"], good)
        for good in (1, 7, 30):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"minor_batch_cadence": good}}}
            )
            self.assertEqual(cfg["minor_batch_cadence"], good)

    def test_segment_normalizer_defaults_garbage(self):
        from core.code_review import severity_gate_from_config_segment

        self.assertEqual(severity_gate_from_config_segment({}), _GATE_DEFAULT)
        self.assertEqual(severity_gate_from_config_segment(None), _GATE_DEFAULT)
        self.assertEqual(
            severity_gate_from_config_segment(
                {"min_immediate_severity": "high", "minor_batch_cadence": -1}),
            _GATE_DEFAULT)
        # 测试替身 config 段未走读取器的形态同款兜底
        self.assertEqual(
            severity_gate_from_config_segment(
                {"min_immediate_severity": "minor", "minor_batch_cadence": 3}),
            {"min_immediate_severity": "minor", "minor_batch_cadence": 3})


# ── 混合严重度选批分流（场景 1）＋ 门限最低档零差异（场景 9）──────────


class TestMixedSeveritySplit(unittest.TestCase):
    def _ledger(self):
        return {
            "a": _item("a", first_seen_at="2026-10-01T00:00:00+00:00"),
            "m": _item("m", severity="minor",
                       first_seen_at="2026-10-02T00:00:00+00:00"),
            "i": _item("i", severity="info",
                       first_seen_at="2026-10-03T00:00:00+00:00"),
        }

    def test_below_gate_items_not_selected_but_stay_open(self):
        from core.code_fix import count_open_items, select_batch

        proot = _make_project_root()
        _write_items(proot, self._ledger())
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        self.assertEqual([r["item_id"] for r in batch], ["a"],
                         "当日批只纳入 major 以上条目")
        # minor/info 保持 open 且不计为 skipped/lost（仍占 open 池）
        self.assertEqual(count_open_items(proot), 3)

    def test_gate_none_keeps_legacy_behavior(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, self._ledger())
        batch = select_batch(proot, 20)
        self.assertEqual([r["item_id"] for r in batch], ["a", "m", "i"],
                         "无门限调用方零改动（向后兼容）")

    def test_lowest_tier_matches_legacy_zero_diff(self):
        """门限配为最低档 info：与无门限的既有行为零差异（可灰度回退）。"""
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, self._ledger())
        gated = select_batch(proot, 20, severity_gate=_GATE_OFF)
        legacy = select_batch(proot, 20)
        self.assertEqual(
            [r["item_id"] for r in gated], [r["item_id"] for r in legacy],
            "min_immediate_severity=info 时词表内档位全放行，空窗零差异")

    def test_unknown_severity_deferred_fail_open(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "u": _item("u", severity="high"),  # 词表外漂移值未归一（外部直写）
        })
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        self.assertEqual([r["item_id"] for r in batch], ["a"],
                         "code-review 来源未知档位按低于门限挂起（fail-open）")


# ── regression- 来源豁免（场景 2）─────────────────────────────────────


class TestRegressionExemption(unittest.TestCase):
    def test_regression_items_exempt_in_mixed_batch(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "r": _item("r", severity="minor", category="regression-timeout",
                       first_seen_at="2026-10-01T00:00:00+00:00"),
            "m": _item("m", severity="minor",
                       first_seen_at="2026-10-02T00:00:00+00:00"),
        })
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        self.assertEqual([r["item_id"] for r in batch], ["r"],
                         "regression- 来源条目照常进入当日批，仅 minor 挂起")
        # 未知档位的 regression 条目同样豁免（「未知档位按低于门限」不作用
        # 于回归来源，design §2）
        _write_items(proot, {
            "r": _item("r", severity="medium", category="regression-timeout"),
        })
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        self.assertEqual([r["item_id"] for r in batch], ["r"])


# ── 周批晋级（场景 3）＋ 批完成后标记清除 ─────────────────────────────


class TestWeeklyPromotion(_UserConfigIsolated):
    def test_window_due_promotes_whole_group(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "m1": _item("m1", severity="minor",
                        severity_deferred=True,
                        severity_deferred_since=_iso_offset(days=-8)),
            "m2": _item("m2", severity="info",
                        severity_deferred=True,
                        severity_deferred_since=_iso_offset(days=-3)),
        })
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        # 整组放行：任一挂起条目窗口到期 → 全部 deferred 条目进批
        self.assertEqual(
            sorted(r["item_id"] for r in batch), ["m1", "m2"],
            "距首个 severity_deferred_since 达 cadence 天整组放行")

    def test_mark_in_spec_clears_marker(self):
        from core.code_review import (_mark_in_spec, read_items,
                                      SEVERITY_DEFERRED_FIELD,
                                      SEVERITY_DEFERRED_SINCE_FIELD)

        proot = _make_project_root()
        _write_items(proot, {
            "m1": _item("m1", severity="minor",
                        severity_deferred=True,
                        severity_deferred_since=_iso_offset(days=-8)),
        })
        _mark_in_spec(proot, ["m1"], "fix-cr-x")
        rec = read_items(proot)["m1"]
        self.assertEqual(rec["status"], "in_spec")
        self.assertIsNone(rec.get(SEVERITY_DEFERRED_FIELD),
                          "立项即清挂起标记（批完成后标记清除）")
        self.assertIsNone(rec.get(SEVERITY_DEFERRED_SINCE_FIELD))

    def test_mark_resolved_clears_marker(self):
        from core.code_review import mark_resolved, read_items

        proot = _make_project_root()
        _write_items(proot, {
            "m1": _item("m1", severity="minor",
                        severity_deferred=True,
                        severity_deferred_since=_iso_offset(days=-8)),
        })
        hit = mark_resolved(proot, ["m1"])
        self.assertEqual(hit, 1)
        rec = read_items(proot)["m1"]
        self.assertEqual(rec["status"], "resolved")
        self.assertIsNone(rec.get("severity_deferred"))
        self.assertIsNone(rec.get("severity_deferred_since"))


# ── deferred 期间同指纹合并 + severity 升档晋级（场景 4/5）────────────


class TestDeferredUpsertMerge(_UserConfigIsolated):
    def _finding(self, severity="minor", description="d"):
        return {
            "file": "core/a.py", "category": "perf", "title": "Slow loop",
            "severity": severity, "description": description,
            "suggestion": "s", "evidence": "e", "line": 1,
        }

    def test_deferred_item_upsert_merges_and_keeps_anchor(self):
        from core.code_review import read_items, upsert_findings

        proot = _make_project_root()
        r1 = upsert_findings(proot, [self._finding()], "code-review-1",
                             "scheduled")
        self.assertEqual(r1, {"inserted": 1, "updated": 0})
        items = read_items(proot)
        rec = next(iter(items.values()))
        self.assertEqual(rec["severity"], "minor")
        self.assertTrue(rec.get("severity_deferred"),
                        "低于门限条目首次落账即带挂起标记")
        since1 = rec.get("severity_deferred_since")
        self.assertTrue(since1)
        item_id = rec["item_id"]

        # 同指纹重复发现：既有 upsert 合并分支刷新而非新增（零新增立项路径）
        r2 = upsert_findings(proot, [self._finding(description="d2")],
                             "code-review-2", "scheduled")
        self.assertEqual(r2, {"inserted": 0, "updated": 1})
        items = read_items(proot)
        self.assertEqual(len(items), 1, "同指纹合并，不新增条目")
        rec2 = items[item_id]
        self.assertEqual(rec2["description"], "d2")
        self.assertEqual(rec2["last_seen_at"], rec2["reviewed_at"])
        self.assertTrue(rec2.get("severity_deferred"),
                        "deferred 期间重复发现保持挂起态")
        self.assertEqual(rec2.get("severity_deferred_since"), since1,
                         "周批窗口以首挂起时刻起算（重复发现不重置锚）")

    def test_severity_upgrade_promotes_to_daily_batch(self):
        from core.code_review import read_items, upsert_findings
        from core.code_fix import select_batch

        proot = _make_project_root()
        upsert_findings(proot, [self._finding()], "code-review-1", "scheduled")
        item_id = next(iter(read_items(proot)))
        self.assertEqual(
            select_batch(proot, 20, severity_gate=_GATE_DEFAULT), [],
            "minor 挂起期不进当日批")

        # 重复发现把 severity 刷到达门限档位 → 清标记 + 当日批处置
        upsert_findings(proot, [self._finding(severity="major")],
                        "code-review-2", "scheduled")
        rec = read_items(proot)[item_id]
        self.assertEqual(rec["severity"], "major")
        self.assertIsNone(rec.get("severity_deferred"),
                          "升档晋级清挂起标记")
        self.assertIsNone(rec.get("severity_deferred_since"))
        batch = select_batch(proot, 20, severity_gate=_GATE_DEFAULT)
        self.assertEqual([r["item_id"] for r in batch], [item_id],
                         "升档条目按当日批处置")

    def test_regression_source_never_marked(self):
        from core.code_review import read_items, upsert_findings

        proot = _make_project_root()
        finding = self._finding(severity="minor")
        finding["category"] = "regression-timeout"
        upsert_findings(proot, [finding], "code-review-1", "scheduled")
        rec = next(iter(read_items(proot).values()))
        self.assertIsNone(rec.get("severity_deferred"),
                          "regression- 来源豁免门限，不置挂起标记")

    def test_unknown_severity_marked_with_warning(self):
        from core.code_review import read_items, upsert_findings

        proot = _make_project_root()
        finding = self._finding(severity="high")
        # 模拟外部直写绕过归一的台账形态：upsert 写侧会归一 high→major，
        # 故直接注入未知档位验证告警分支（design §5 fail-open 挂起）
        finding["severity"] = "blocker"
        with self.assertLogs(level="WARNING") as cm:
            upsert_findings(proot, [finding], "code-review-1", "scheduled")
        self.assertTrue(
            any("severity" in m for m in cm.output), "未知档位留告警")
        rec = next(iter(read_items(proot).values()))
        self.assertTrue(rec.get("severity_deferred"))


# ── 链末批判定含挂起集（场景 6）＋ 双台账互不串扰（场景 7）────────────


class TestChainLastBatchAndLedgerIndependence(unittest.TestCase):
    def test_deferred_items_do_not_block_chain_last(self):
        from core.code_fix import is_chain_last_batch, read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "m": _item("m", severity="minor", severity_deferred=True,
                       severity_deferred_since=_iso_offset(days=-1)),
        })
        # 带门限：挂起条目不阻链末批判定（本批判定排除口径与选批门限同口径）
        self.assertTrue(
            is_chain_last_batch(proot, ["a"], severity_gate=_GATE_DEFAULT),
            "剩余条目全部挂起 → 本批即末批，挂起不计 skipped/lost")
        # 挂起条目仍为 open（未被误判为 lost/skipped 而终态化）
        self.assertEqual(read_items(proot)["m"]["status"], "open")
        # 无门限（向后兼容调用方）：minor 仍可被选中 → 非末批（旧口径不变）
        self.assertFalse(is_chain_last_batch(proot, ["a"]))

    def test_severity_markers_do_not_touch_wip_defer_ledger(self):
        from core.code_fix import (_deferred_item_ids, load_deferred_batches,
                                   record_deferred_batch, select_batch)
        from core.code_review import severity_deferred_open_ids

        proot = _make_project_root()
        # severity 挂起集在档：WIP-defer 台账保持空
        _write_items(proot, {
            "m": _item("m", severity="minor", severity_deferred=True,
                       severity_deferred_since=_iso_offset(days=-1)),
            "w": _item("w"),
        })
        self.assertEqual(load_deferred_batches(proot), [],
                         "severity 挂起标记 MUST NOT 写入 fix-deferred.json")
        self.assertEqual(_deferred_item_ids(proot), set(),
                         "severity 挂起不进 WIP-defer 排除集")

        # WIP-defer 台账条目在档：不改变 severity 门限的放行判定（两机制
        # 不共载体、不共放行判据）
        record_deferred_batch(
            proot, ["w"], fixed_ids=["w"],
            worktree=str(proot / "wt"), branch="fenix/w", tip_sha="deadbeef")
        self.assertEqual(_deferred_item_ids(proot), {"w"})
        self.assertEqual(
            severity_deferred_open_ids(proot, gate=_GATE_DEFAULT), {"m"},
            "WIP-defer 台账不影响 severity 挂起集判定")
        # 选批排除：w 经 WIP 台账排除（由调用方传 exclude_ids），
        # m 经 severity 门限排除——两排除面各司其职
        batch = select_batch(proot, 20, exclude_ids={"w"},
                             severity_gate=_GATE_DEFAULT)
        self.assertEqual(batch, [])


# ── 双入口同门：generate_fix_spec 候选层（场景：手工通道绕过被拒）──────


class TestGenerateFixSpecSameGate(_UserConfigIsolated):
    def setUp(self):
        super().setUp()
        self.repo = _make_repo()
        self.sm = _FakeSM()
        from core.code_review import upsert_findings

        upsert_findings(self.repo, [
            {"file": "core/a.py", "category": "correctness", "title": "None deref",
             "severity": "major", "description": "d", "suggestion": "s",
             "evidence": "e", "line": 1},
            {"file": "core/b.py", "category": "perf", "title": "Slow loop",
             "severity": "minor", "description": "d", "suggestion": "s",
             "evidence": "e", "line": 2},
            {"file": "core/c.py", "category": "style", "title": "Long func",
             "severity": "info", "description": "d", "suggestion": "s",
             "evidence": "e", "line": 3},
        ], "code-review-1", "manual_full")

    def _ids(self):
        from core.code_review import read_items

        return {it["file"]: iid for iid, it in read_items(self.repo).items()}

    def test_pure_minor_info_trigger_rejected_with_reason(self):
        """纯 minor/info 手工触发：空批处理并说明原因（双入口同门）。"""
        from core.code_review import generate_fix_spec

        ids = self._ids()
        res = generate_fix_spec(
            self.repo, self.sm, [ids["core/b.py"], ids["core/c.py"]])
        self.assertFalse(res["ok"], res)
        self.assertEqual(res["spec_name"], None)
        self.assertEqual(
            {s["reason"] for s in res["skipped"]}, {"severity_deferred"})
        self.assertIn("min_immediate_severity", res["error"])
        self.assertIn("minor_batch_cadence", res["error"])
        # 条目保持 open 未被误终态化
        from core.code_review import read_items

        items = read_items(self.repo)
        self.assertEqual(items[ids["core/b.py"]]["status"], "open")
        self.assertEqual(items[ids["core/c.py"]]["status"], "open")

    def test_mixed_selection_only_gate_passing_candidates(self):
        from core.code_review import generate_fix_spec, read_items

        ids = self._ids()
        res = generate_fix_spec(
            self.repo, self.sm,
            [ids["core/a.py"], ids["core/b.py"], ids["core/c.py"]])
        self.assertTrue(res["ok"], res)
        skipped = {s["item_id"]: s["reason"] for s in res["skipped"]}
        self.assertEqual(skipped.get(ids["core/b.py"]), "severity_deferred")
        self.assertEqual(skipped.get(ids["core/c.py"]), "severity_deferred")
        tasks_text = (
            self.repo / "spec" / "changes" / res["spec_name"] / "tasks.md"
        ).read_text(encoding="utf-8")
        self.assertIn("core/a.py", tasks_text)
        self.assertNotIn("core/b.py", tasks_text)
        items = read_items(self.repo)
        self.assertEqual(items[ids["core/a.py"]]["status"], "in_spec")
        self.assertEqual(items[ids["core/b.py"]]["status"], "open")

    def test_window_due_minor_passes_same_gate(self):
        """周批窗口到期：同一谓词放行（两入口无漂移）。"""
        from core.code_review import _mark_in_spec, generate_fix_spec, read_items

        # 手工把 minor 条目挂起锚回拨 8 天（窗口到期）
        proot = self.repo
        path = proot / ".fenix" / "code-review" / "items.jsonl"
        records = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["severity"] in ("minor", "info"):
                rec["severity_deferred"] = True
                rec["severity_deferred_since"] = _iso_offset(days=-8)
            records[rec["item_id"]] = rec
        _write_items(proot, records)

        ids = self._ids()
        res = generate_fix_spec(
            self.repo, self.sm, [ids["core/b.py"], ids["core/c.py"]])
        self.assertTrue(res["ok"], res)
        items = read_items(self.repo)
        self.assertEqual(items[ids["core/b.py"]]["status"], "in_spec")
        # 立项即清挂起标记
        self.assertIsNone(items[ids["core/b.py"]].get("severity_deferred"))
        _mark_in_spec  # 语义由上一断言覆盖（_mark_in_spec 内清标记）

    def test_project_config_lowest_tier_allows_minor(self):
        """门限配为最低档（项目级配置）：minor 触发可生成（零差异回退路径）。"""
        cfg = self.repo / ".fenix" / "config.yaml"
        cfg.write_text(
            "admin:\n"
            "  code_review_fix:\n"
            "    min_immediate_severity: info\n",
            encoding="utf-8")
        from core.code_review import generate_fix_spec

        ids = self._ids()
        res = generate_fix_spec(
            self.repo, self.sm, [ids["core/b.py"], ids["core/c.py"]])
        self.assertTrue(res["ok"], res)


# ── checkpoint 纯挂起收敛（链收敛对账：不计 skipped/lost）──────────────


class TestCheckpointSeverityConverged(unittest.TestCase):
    def _cfg(self):
        # night_quiet_window=off：测试与每日静默窗（04:15-04:45）解耦
        return {"admin": {"code_review_fix": {
            "enabled": True, "batch_size": 20, "night_quiet_window": "off"}}}

    def test_pure_deferred_converges_as_idle_not_blocked(self):
        from core.code_fix import (CodeFixOrchestrator, read_progress,
                                   write_progress)

        proot = _make_project_root()
        _write_items(proot, {
            "m": _item("m", severity="minor"),
        })

        class _Runner:
            project_root = None
            logger = None
            config = {}
            _running_agents = {}
            fix_calls = []

            def _get_config(self, key, default=None):
                return self.config.get(key, default)

        runner = _Runner()
        runner.project_root = proot
        orch = CodeFixOrchestrator(runner, proot, config=self._cfg(),
                                   logger=None)
        # 制造 live 链（收敛写点仅在链在档时落盘）
        write_progress(proot, running=True, activation_id="act-sev-1",
                       done=0, total=1, batch_no=1)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "no_open_items"})
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "idle",
                         "纯挂起收敛＝健康等待态，非 blocked")
        self.assertEqual(prog["reason"], "severity_deferred")
        self.assertIn("挂起至周批窗口", prog["current"])
        self.assertIn("minor_batch_cadence=7", prog["current"])
        self.assertEqual(prog["running"], False)
        self.assertIsNone(prog.get("worktree"))
        self.assertEqual(runner.fix_calls, [], "挂起态 MUST NOT 派批")


if __name__ == "__main__":
    unittest.main()
