"""evo-whitelist-tracked-patrol 单测（tasks.md 3.1）。

白名单脱落巡检端到端覆盖（tests/test_stray_untrack_remediation.py 双断言
口径同款——「不误伤/不漏报」）：
- 不误报：tracked 白名单文件（`!` 放行且在索引中）与真散件不触发新信号；
- 不漏报：放行文件被移出索引（git rm --cached 场景）后必报 major，且该
  放行项不计入 untracked 散件计数（既有豁免语义不变，两流互不污染）；
- 去重：同指纹重复盘点不重复唤起；内容演化（新指纹）再报；指纹消失
  （恢复入库）注册表自动复位，同指纹再现可再报；
- 登记：admin_monitor 三表登记完备 + 落盘记录满足摄取门前提（「项目名=」
  与「文件清单(N):」段可解析）+ 摄取唤起端到端（项目名解析清单漏加即
  落空的源码注释点名坑）。
"""

import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from core.admin_store import AdminStore, SIGNAL, evidence_project
from core.worktree_manager.stray_wip import (
    WHITELIST_UNTRACKED_SIGNAL_TYPE,
    MainTreeStrayWipSweeper,
)

# /tmp 可能被外部清扫进程周期性清空（test_maintree_stray_wip_sweep 同款
# 规避）。统一用仓库内 .history/tmp（gitignored），MUST NOT 改写全局
# tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP)))


def _git(*args, cwd, check=True):
    r = subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(cwd), check=check, capture_output=True, text=True,
    )
    return r.stdout


def _status(repo) -> str:
    return _git("status", "--porcelain", cwd=repo)


def _make_repo() -> Path:
    """主树仓：.fenix 白名单约定（.fenix/* 整体忽略 + verify.yaml 放行）。

    - ``.fenix/verify.yaml`` 已入库基线且被 ``!`` 规则放行（白名单健康态
      原型——放行即声明入库意图，tracked 态不应触发任何信号）；
    - ``keep.txt`` 全场无改动（反例对照）；
    - 仓级提交身份（c-bot）与 `_git` 旗标身份刻意错开——会话归因候选②按
      「仓级配置身份 ≈ 近窗提交身份」判命中，两身份一致会把 tracked 散件
      误归因为交互会话（吞掉 tracked 流路径，干扰双流对账断言）。
    """
    repo = _mkdtemp("stray-wl-") / "proj"
    repo.mkdir(parents=True)
    _git("init", "-q", cwd=repo)
    _git("config", "user.email", "config-bot@example.com", cwd=repo)
    _git("config", "user.name", "config-bot", cwd=repo)
    (repo / ".gitignore").write_text(
        ".fenix/*\n!.fenix/verify.yaml\n", encoding="utf-8"
    )
    (repo / "keep.txt").write_text("keep", encoding="utf-8")
    (repo / ".fenix").mkdir()
    (repo / ".fenix" / "verify.yaml").write_text(
        "verify: baseline\n", encoding="utf-8"
    )
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def _drop_from_index(repo: Path, rel: str = ".fenix/verify.yaml") -> None:
    """白名单脱落场景（proposal 实证形态）：移出索引、盘上副本保持 untracked。"""
    subprocess.run(
        ["git", "rm", "--cached", "-q", rel],
        cwd=str(repo), check=True, capture_output=True,
    )


def _whitelist_alerts(repo) -> list:
    """whitelist_untracked 告警记录（read_all 倒序返回 → 本列表最新在前）。"""
    return [
        r
        for r in AdminStore(repo).read_all()
        if r.get("kind") == SIGNAL
        and r.get("signal_type") == WHITELIST_UNTRACKED_SIGNAL_TYPE
    ]


class _WmProbe:
    """WorktreeManager 探针壳：混入盘点所需 mixin（真实实现，非替身）。

    test_stray_untrack_remediation._WmProbe 同款装配（sweep 依赖
    _main_tree_lock、_list_dirty_tracked_files 与 identify_wip_occupant）。
    """

    from core.worktree_manager.mergeback import G4MergebackMixin as _G4
    from core.worktree_manager.queries import G8QueryMixin as _G8
    from core.worktree_manager.stash_guard import G6StashGuardMixin as _G6

    class Inner(_G4, _G6, _G8):
        def __init__(self, root):
            self.project_root = Path(root)
            self._main_tree_lock = threading.Lock()

    def __init__(self, root):
        self.impl = self.Inner(root)

    def __getattr__(self, name):
        return getattr(self.impl, name)


def _make_sweeper(repo) -> MainTreeStrayWipSweeper:
    cfg = {"admin": {"maintree_stray_wip_grace_minutes": 0.0}}
    return MainTreeStrayWipSweeper(repo, _WmProbe(repo), config=cfg)


class TestWhitelistPatrolDetection(unittest.TestCase):
    """白名单脱落检测流：不误报 / 不漏报 / 去重与复位（tasks.md 3.1）。"""

    def test_tracked_whitelist_and_real_stray_no_false_positive(self):
        """健康态不误报：tracked 白名单文件不触发新信号，真散件仍走散件流。"""
        repo = _make_repo()
        (repo / "build.log").write_text("stray\n", encoding="utf-8")  # 真散件
        before = _status(repo)
        sw = _make_sweeper(repo)
        r = sw.sweep()
        # 白名单流：放行且 tracked（索引含该路径）→ clean，零告警
        self.assertEqual(r["whitelist_untracked"]["status"], "clean")
        self.assertEqual(r["whitelist_untracked"]["files"], [])
        self.assertEqual(_whitelist_alerts(repo), [])
        # 散件流：真散件照常计数；tracked 白名单文件不被裹挟进散件清单
        # （negation 豁免语义不变，两流互不污染）
        self.assertEqual(r["untracked"]["files"], ["build.log"])
        self.assertNotIn(".fenix/verify.yaml", r["untracked"]["files"])
        self.assertEqual(_status(repo), before)  # 零触碰

    def test_index_removal_fires_and_not_counted_as_stray(self):
        """不漏报：放行文件移出索引后必报 major，且不计入散件计数。"""
        repo = _make_repo()
        _drop_from_index(repo)
        before = _status(repo)
        sw = _make_sweeper(repo)
        r = sw.sweep()
        w = r["whitelist_untracked"]
        self.assertEqual(w["status"], "alerted")
        self.assertEqual(w["files"], [".fenix/verify.yaml"])
        self.assertEqual(w["count"], 1)
        # 必报且不计入散件：untracked 键不出现（放行项豁免语义不变——
        # 白名单文件不是散件，本流是加法不是改法）
        self.assertNotIn("untracked", r)
        alerts = _whitelist_alerts(repo)
        self.assertEqual(len(alerts), 1)
        rec = alerts[0]
        self.assertEqual(rec["severity"], "major")
        # 处置建议二选一（恢复入库 或 删除放行规则）
        self.assertIn("git add", rec["recommended_action"])
        self.assertIn("删除", rec["recommended_action"])
        self.assertEqual(_status(repo), before)  # 零触碰

    def test_same_fingerprint_one_shot_and_registry_reset_on_recovery(self):
        """同指纹一次性；内容演化新指纹再报；恢复入库注册表复位、再现再报。"""
        repo = _make_repo()
        _drop_from_index(repo)
        sw = _make_sweeper(repo)
        r1 = sw.sweep()
        self.assertEqual(r1["whitelist_untracked"]["status"], "alerted")
        self.assertEqual(len(_whitelist_alerts(repo)), 1)
        # 同指纹重复盘点不重复唤起（同 sweeper 实例——注册表是进程内存态）
        r2 = sw.sweep()
        self.assertEqual(r2["whitelist_untracked"]["status"], "recorded")
        self.assertEqual(len(_whitelist_alerts(repo)), 1)
        # 内容演化 → 新指纹 → 再报（同集合内容级判定，演化不被旧指纹吞掉）
        (repo / ".fenix" / "verify.yaml").write_text(
            "verify: evolved\n", encoding="utf-8"
        )
        r3 = sw.sweep()
        self.assertEqual(r3["whitelist_untracked"]["status"], "alerted")
        self.assertNotEqual(
            r3["whitelist_untracked"]["fingerprint"],
            r1["whitelist_untracked"]["fingerprint"],
        )
        self.assertEqual(len(_whitelist_alerts(repo)), 2)
        # 恢复入库（git add 回索引）→ 脱落消失，注册表自动复位
        _git("add", ".fenix/verify.yaml", cwd=repo)
        r4 = sw.sweep()
        self.assertEqual(r4["whitelist_untracked"]["status"], "clean")
        self.assertEqual(sw._whitelist_registry, {})
        # 同一脱落形态再现（同内容同指纹）→ 复位后可再报（未被旧
        # escalated_at 拖住）
        _drop_from_index(repo)
        r5 = sw.sweep()
        self.assertEqual(r5["whitelist_untracked"]["status"], "alerted")
        self.assertEqual(len(_whitelist_alerts(repo)), 3)

    def test_ls_files_gate_filters_indexed_released_paths(self):
        """ls-files 求交门：放行但在索引中的路径不构成脱落候选（判定自洽）。"""
        repo = _make_repo()
        sw = _make_sweeper(repo)
        # keep.txt 未被 .gitignore 放行，此处构造 detail 使其命中放行规则：
        # 若无 ls-files 求交门，该 tracked 路径会被误判为脱落候选
        entries = sw._whitelist_untracked_entries(
            ["keep.txt"], {"keep.txt": "!keep.txt"}
        )
        self.assertEqual(entries, [])
        # detail 不可用 → 放弃本流（None，调用方按保守不告警处置）
        self.assertIsNone(sw._whitelist_untracked_entries(["keep.txt"], None))

    def test_check_ignore_failure_keeps_whitelist_flow_abandoned(self):
        """check-ignore 明细不可用 → 白名单流放弃（abandoned），不告警。"""
        repo = _make_repo()
        _drop_from_index(repo)
        sw = _make_sweeper(repo)
        w = sw._whitelist_signal([".fenix/verify.yaml"], None)
        self.assertEqual(w["status"], "abandoned")
        self.assertEqual(_whitelist_alerts(repo), [])
        self.assertEqual(sw._whitelist_registry, {})


class TestRegistrationAndIngestion(unittest.TestCase):
    """三表登记完备性与摄取唤起端到端（防「落 store 无人摄取」静默落空）。"""

    def test_three_tables_registered(self):
        """SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES 三处。"""
        from core.admin_monitor import (
            SIGNAL_RECOMMENDATION,
            SIGNAL_SEVERITY,
            STORED_SIGNAL_TYPES,
        )

        self.assertIn(WHITELIST_UNTRACKED_SIGNAL_TYPE, SIGNAL_SEVERITY)
        self.assertEqual(
            SIGNAL_SEVERITY[WHITELIST_UNTRACKED_SIGNAL_TYPE], "major"
        )
        # 对齐 maintree_untracked_stray_escalated 先例（severity 同级）
        self.assertEqual(
            SIGNAL_SEVERITY[WHITELIST_UNTRACKED_SIGNAL_TYPE],
            SIGNAL_SEVERITY["maintree_untracked_stray_escalated"],
        )
        rec = SIGNAL_RECOMMENDATION.get(WHITELIST_UNTRACKED_SIGNAL_TYPE, "")
        self.assertTrue(rec.strip())
        # 文案写明机制与二选一处置
        self.assertIn("negation 放行即声明入库意图", rec)
        self.assertIn("git add", rec)
        self.assertIn("删除", rec)
        self.assertIn(WHITELIST_UNTRACKED_SIGNAL_TYPE, STORED_SIGNAL_TYPES)

    def test_alert_record_ingestible_shape(self):
        """落盘记录满足摄取门前提：kind=SIGNAL、证据带「项目名=」与清单段。"""
        repo = _make_repo()
        _drop_from_index(repo)
        _make_sweeper(repo).sweep()
        recs = _whitelist_alerts(repo)
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        self.assertEqual(rec["signal_type"], WHITELIST_UNTRACKED_SIGNAL_TYPE)
        # evidence 以「项目名=」开头（_detect_family_explosion 无 spec 形态
        # 按该字段解析，未解析出 spec 的记录会被丢弃）
        self.assertTrue((rec.get("evidence") or "").startswith("项目名="))
        self.assertEqual(evidence_project(rec["evidence"]), "proj")
        # 清单段可解析（parse_stray_wip_manifest 同段级口径）
        from core.dashboard.data.admin_actions import parse_stray_wip_manifest

        self.assertEqual(
            parse_stray_wip_manifest(rec["evidence"]),
            [".fenix/verify.yaml"],
        )
        # 放行规则快照随 evidence 下发（人工处置免二次考古 .gitignore）
        self.assertIn("放行规则: .fenix/verify.yaml=!.fenix/verify.yaml", rec["evidence"])

    def test_ingestion_resolves_project_and_invokes(self):
        """摄取唤起端到端：项目名解析清单收录本类型——漏加则 spec=None 记录
        被丢弃、唤起静默落空（源码注释点名的同款坑，本测试钉住）。"""
        from core.admin_monitor import AdminMonitor

        store = _IngestStoreStub([
            {
                "kind": SIGNAL,
                "signal_type": WHITELIST_UNTRACKED_SIGNAL_TYPE,
                "spec": None,
                "severity": "major",
                "description": "白名单文件脱落",
                "evidence": (
                    "项目名=proj; first_seen=2026-10-09T00:00:00Z; "
                    "文件清单(1): .fenix/verify.yaml; "
                    "放行规则: .fenix/verify.yaml=!.fenix/verify.yaml"
                ),
                "recommended_action": "二选一处置",
            }
        ])
        mon = AdminMonitor(
            {}, _MonitorSMStub({}), Path(_mkdtemp("stray-wl-mon-")),
            _FakeMonitorLogger(),
            store=store, agent_runner=mock.MagicMock(),
        )
        with mock.patch.object(
            mon, "_invoke_administrator", return_value=None,
        ) as invoke:
            raw = mon._detect_family_explosion()
        self.assertEqual(len(raw), 1, "脱落记录应被摄取（项目名解析出 spec）")
        self.assertEqual(raw[0]["signal_type"], WHITELIST_UNTRACKED_SIGNAL_TYPE)
        self.assertEqual(raw[0]["spec"], "proj")
        self.assertEqual(len(store.escalated), 1)
        self.assertEqual(invoke.call_count, 1)
        # 二次摄取不重复（已 escalated）
        self.assertEqual(mon._detect_family_explosion(), [])


class _IngestStoreStub:
    """AdminStore 轻量替身：记录 append/mark_escalated 调用（摄取测试用）。

    test_maintree_stray_wip_sweep._IngestStoreStub 同款。
    """

    def __init__(self, records):
        self.records = [dict(r, id=f"rec-{i}") for i, r in enumerate(records)]
        self.escalated = []

    def read_all(self):
        return [dict(r) for r in self.records]

    def mark_escalated(self, alert_id):
        self.escalated.append(alert_id)
        for r in self.records:
            if r.get("id") == alert_id:
                r["escalated"] = True
                return True
        return False


class _MonitorSMStub:
    """AdminMonitor 测试用最小 StateMachine 替身（read_one 返回 status 条目）。"""

    def __init__(self, statuses=None):
        self._statuses = statuses or {}

    def read_one(self, spec):
        return {"status": self._statuses.get(spec, "")}


class _FakeMonitorLogger:
    def info(self, tag, msg, extra=None):
        pass

    def warning(self, tag, msg, extra=None):
        pass


if __name__ == "__main__":
    unittest.main()
