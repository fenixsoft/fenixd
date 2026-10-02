"""evo-inflight-spec-amendment-watch 3.2：admin_monitor 周期扫描在飞修订检测测试。

覆盖：
  3.2: 实现 run 在飞 + 主树 spec 修订 → 一个扫描周期内告警（spec_amendment_inflight，
        severity=major、evidence 含修订提交与指纹）、同指纹不重复成条、
        主树又落新修订（提交集变化）→ 新指纹允许再次成条；
  对照: run 不在飞（无 run 写活动且无存活进程）/ 状态非 implementing /
        分支锚点缺失 → 不检测不告警；分支不存在 → 静默跳过不报错；
  注册: kind 进 SIGNAL_SEVERITY / SIGNAL_RECOMMENDATION / STORED_SIGNAL_TYPES
        （severity=major、处置文案指向等实现收尾后补修订或经 repair 合并）。
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.admin_monitor import (
    SIGNAL_RECOMMENDATION,
    SIGNAL_SEVERITY,
    STORED_SIGNAL_TYPES,
    AdminMonitor,
    _has_recent_spec_run,
)
from core.admin_store import AdminStore
from tests.helpers import FakeLogger
from test_worktree_merge_guard import git, init_repo


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


def _amended_repo(tmp_path, spec: str = "evo-a"):
    """构造 repo：分支在 merge-base 后改 shared.py+spec 目录勾选，主树随后
    提交 spec 目录修订（在飞修订）。返回 (root, branch, amend_short)。"""
    root = tmp_path / "proj"
    init_repo(root)
    spec_dir = root / "spec" / "changes" / spec
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text("tasks\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"[fenix] spec {spec} base")
    base_sha = git(root, "rev-parse", "HEAD").stdout.strip()
    branch = f"fenix/{spec}-1700000020"
    git(root, "checkout", "-q", "-b", branch)
    (root / "shared.py").write_text("BRANCH-VERSION\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("- [x] t1\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"[fenix] branch {branch}")
    git(root, "checkout", "-q", base_sha)
    # 框架外在飞修订：主树直接提交 spec 目录改动
    (spec_dir / "design.md").write_text("amended out-of-band\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "[fenix] spec amendment out-of-band")
    amend_short = git(root, "rev-parse", "--short", "HEAD").stdout.strip()
    return root, branch, amend_short


def _touch_run(root: Path, spec: str) -> Path:
    """写入在飞实现 run 文件（新鲜 mtime，_has_recent_spec_run 判活依据）。"""
    runs_dir = root / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    p = runs_dir / f"impl-{spec}-1700000020.jsonl"
    p.write_text(
        json.dumps({"type": "assistant", "message": {"content": []}}) + "\n",
        encoding="utf-8",
    )
    return p


def _mk_monitor(root: Path, specs: dict) -> AdminMonitor:
    mon = AdminMonitor(
        {},
        FakeSM(specs),
        root,
        FakeLogger(),
        store=AdminStore(root, FakeLogger()),
        agent_runner=None,
    )
    return mon


def _impl_specs(root: Path, branch: str, spec: str = "evo-a") -> dict:
    return {
        spec: {"status": "implementing", "branch": branch, "implementer_run": f"impl-{spec}-1"},
    }


class TestPeriodicAmendmentDetection:
    """3.2: run 在飞 + 主树修订 → 一个扫描周期内告警；同指纹不重复。"""

    def test_inflight_run_with_amendment_alerts(self, tmp_path):
        """实现 run 在飞 + 主树 spec 修订 → 本轮扫描即产 spec_amendment_inflight 信号。"""
        root, branch, amend_short = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        assert _has_recent_spec_run(root, "evo-a", time.time(), 120)
        mon = _mk_monitor(root, _impl_specs(root, branch))

        signals = mon._detect_spec_amendment_inflight(
            mon.state_machine.read_all(), time.time()
        )

        assert len(signals) == 1, f"应恰一条在飞修订信号: {signals}"
        sig = signals[0]
        assert sig["signal_type"] == "spec_amendment_inflight"
        assert sig["spec"] == "evo-a"
        assert sig["severity"] == "major"
        assert amend_short in sig["evidence"]
        assert "指纹=" in sig["evidence"]
        assert "相撞" in sig["description"]

    def test_detection_via_full_scan_cycle(self, tmp_path):
        """经 _detect 主扫描入口（周期巡检同路）→ 信号在本轮出现。"""
        root, branch, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        mon = _mk_monitor(root, _impl_specs(root, branch))
        now = time.time()

        signals = mon._detect(mon.state_machine.read_all(), now)

        types = [s["signal_type"] for s in signals]
        assert "spec_amendment_inflight" in types, f"周期扫描应含在飞修订信号: {types}"

    def test_same_fingerprint_not_repeated(self, tmp_path):
        """同 spec+修订提交集合 → 同指纹，下一扫描周期不重复成条（不逐轮轰炸）。"""
        root, branch, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        specs = _impl_specs(root, branch)
        mon = _mk_monitor(root, specs)

        first = mon._detect_spec_amendment_inflight(specs, time.time())
        second = mon._detect_spec_amendment_inflight(specs, time.time() + 1)

        assert len(first) == 1
        assert second == [], "同指纹 MUST NOT 重复成条"

    def test_new_amendment_commit_refires(self, tmp_path):
        """主树又落新修订 → 提交集变化 → 新指纹允许再次成条（相撞风险升级提醒）。"""
        root, branch, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        specs = _impl_specs(root, branch)
        mon = _mk_monitor(root, specs)

        first = mon._detect_spec_amendment_inflight(specs, time.time())
        # 第二个框架外修订提交（提交集变化）
        spec_dir = root / "spec" / "changes" / "evo-a"
        (spec_dir / "proposal.md").write_text("amended again\n", encoding="utf-8")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "[fenix] second amendment")
        second = mon._detect_spec_amendment_inflight(specs, time.time() + 1)

        assert len(first) == 1
        assert len(second) == 1, "新修订（新指纹）应再次成条"
        assert second[0]["evidence"] != first[0]["evidence"]


class TestSilentSkip:
    """对照：run 不在飞 / 状态不符 / 分支缺失 → 不检测不告警、不报错。"""

    def test_no_active_run_not_detected(self, tmp_path):
        """run 不在飞（无 run 文件写活动且无存活进程）→ 不检测不告警。"""
        root, branch, _ = _amended_repo(tmp_path)
        specs = _impl_specs(root, branch)  # 无 _touch_run
        mon = _mk_monitor(root, specs)

        signals = mon._detect_spec_amendment_inflight(specs, time.time())

        assert signals == []
        assert mon.store.read_all() == [], "不落任何告警记录"

    def test_non_implementing_status_not_detected(self, tmp_path):
        """状态非 implementing（如 testing/ready）→ 不检测。"""
        root, branch, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        specs = {"evo-a": {"status": "testing", "branch": branch}}
        mon = _mk_monitor(root, specs)

        assert mon._detect_spec_amendment_inflight(specs, time.time()) == []

    def test_missing_branch_anchor_silent(self, tmp_path):
        """分支锚点缺失 → 静默跳过（不猜测命名规则）。"""
        root, _, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        specs = {"evo-a": {"status": "implementing", "branch": None}}
        mon = _mk_monitor(root, specs)

        assert mon._detect_spec_amendment_inflight(specs, time.time()) == []

    def test_missing_branch_git_silent(self, tmp_path):
        """分支已清理（merge-base 失败）→ 静默跳过不报错。"""
        root, branch, _ = _amended_repo(tmp_path)
        _touch_run(root, "evo-a")
        specs = {"evo-a": {"status": "implementing", "branch": "fenix/ghost-1700000099"}}
        mon = _mk_monitor(root, specs)

        assert mon._detect_spec_amendment_inflight(specs, time.time()) == []


class TestKindRegistration:
    """kind 级别/处方表注册（2.1）：severity=major、处置文案指向补修订/repair。"""

    def test_severity_and_stored_types(self):
        assert SIGNAL_SEVERITY.get("spec_amendment_inflight") == "major"
        assert "spec_amendment_inflight" in STORED_SIGNAL_TYPES

    def test_recommendation_points_to_amend_or_repair(self):
        rec = SIGNAL_RECOMMENDATION.get("spec_amendment_inflight") or ""
        assert "补齐同一修订" in rec
        assert "repair" in rec

    def test_stored_signal_ingestible(self, tmp_path):
        """merge-back 侧直写的 SIGNAL 记录形态可落盘、未被拾取（可被
        _detect_family_explosion 摄取循环捞出，不石沉大海）。"""
        from core.admin_store import SIGNAL as KIND_SIGNAL

        root, _, _ = _amended_repo(tmp_path)
        store = AdminStore(root, FakeLogger())
        written = store.append(
            {
                "kind": KIND_SIGNAL,
                "signal_type": "spec_amendment_inflight",
                "spec": "evo-a",
                "severity": "major",
                "description": "d",
                "evidence": "e",
                "recommended_action": "r",
            }
        )
        assert written is not None, "记录应落盘（下限保护不拒正常形态）"
        recs = [r for r in store.read_all() if r.get("signal_type") == "spec_amendment_inflight"]
        assert len(recs) == 1
        assert not recs[0].get("escalated"), "新记录未被拾取，可被摄取循环捞出"
