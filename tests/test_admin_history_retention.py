"""
tests/test_admin_history_retention.py — fix-observability-gaps 4.1 / 4.1a

验证：
- admin_state_history 保留窗 ≥24h（跨日状态历史可见，1h 窗下会被裁掉）
- 24h 窗提升后 flapping 检测（FLAPPING_WINDOW_MINUTES=10 自有窗口）输出不变
- changes 按时间裁剪、无条数上限（24h 量级可接受，不加上限）
"""

import json
import time
from pathlib import Path

from core.admin_monitor import AdminMonitor, FLAPPING_WINDOW_MINUTES


class _FakeSM:
    def __init__(self, specs: dict):
        self.specs = specs

    def read_one(self, name):
        return self.specs.get(name)


class _FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeStore:
    def append(self, *a, **k):
        pass

    def latest_signal(self, *a, **k):
        return None


def _make_monitor(tmp_path: Path, specs: dict, moves_ago_minutes: list[float]):
    """构造 AdminMonitor，并把历史文件预写为带指定时刻的 ready↔implementing 变化。"""
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        {},
        _FakeSM(specs),
        proot,
        _FakeLogger(),
        store=_FakeStore(),
        agent_runner=None,
    )
    now = time.time()
    changes = []
    for minutes_ago in sorted(moves_ago_minutes, reverse=True):
        status = "implementing" if len(changes) % 2 == 0 else "ready"
        changes.append([now - minutes_ago * 60, status])
    hist = proot / ".fenix" / "admin_state_history.json"
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text(json.dumps(
        {"spec-a": {"last_status": "implementing", "changes": changes}}),
        encoding="utf-8")
    return proot, mon, now


class TestHistoryRetentionWindow:
    def test_cross_day_history_retained(self, tmp_path):
        """23h 前（跨日，仍 <24h）的 ready↔implementing 变化在 24h 窗下仍保留。"""
        # 单条变化记录在 23h 前——24h 窗保留（旧 1h 窗会裁掉）
        proot, mon, now = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": ""},
        }, moves_ago_minutes=[23 * 60])
        specs = {"spec-a": {"status": "implementing"}}
        mon._update_history(specs, now)
        hist = proot / ".fenix" / "admin_state_history.json"
        data = json.loads(hist.read_text(encoding="utf-8"))
        changes = data["spec-a"]["changes"]
        assert len(changes) >= 1, "24h 内的历史不应被裁掉"

    def test_old_changes_trimmed_beyond_24h(self, tmp_path):
        """超过 24h 的历史变化在新状态变化时被裁剪（保留窗生效），24h 内保留。"""
        proot, mon, now = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": ""},
        }, moves_ago_minutes=[30 * 60, 5 * 60])
        # 触发状态变化（implementing→ready）以激活裁剪路径
        specs = {"spec-a": {"status": "ready"}}
        mon._update_history(specs, now)
        hist = proot / ".fenix" / "admin_state_history.json"
        data = json.loads(hist.read_text(encoding="utf-8"))
        changes = data["spec-a"]["changes"]
        # 30h 前被裁掉，5h 前保留（新 status=ready 追加的条目也在内）
        assert all(c[0] >= now - 24 * 60 * 60 for c in changes)
        assert any(c[0] >= now - 6 * 60 * 60 for c in changes)

    def test_no_cap_on_changes_count(self, tmp_path):
        """changes 只按时间裁剪、无条数上限：24h 内多条记录全部保留。"""
        # 24h 内 200 条变化（最坏量级）全部保留（无条数上限）
        proot, mon, now = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": ""},
        }, moves_ago_minutes=[0.01] * 200)
        specs = {"spec-a": {"status": "implementing"}}
        mon._update_history(specs, now)
        hist = proot / ".fenix" / "admin_state_history.json"
        data = json.loads(hist.read_text(encoding="utf-8"))
        assert len(data["spec-a"]["changes"]) >= 199, "24h 内多条记录不得被条数上限裁掉"

    def test_flapping_output_unchanged_after_window_raise(self, tmp_path):
        """24h 保留窗提升后，flapping 判定（10 分钟自有窗口）输出不变。"""
        # 10 分钟内 4 次切换（3 次转换）→ 触发 flapping
        proot, mon, now = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": ""},
        }, moves_ago_minutes=[8, 6, 4, 2])
        specs = {"spec-a": {"status": "implementing"}}
        # 先更新历史（把预写 changes 按 24h 窗裁剪——8 分钟内全在窗内）
        mon._update_history(specs, now)
        signals = mon._detect_flapping(specs, now)
        assert any(s.get("signal_type") == "flapping" and s.get("spec") == "spec-a"
                   for s in signals)

    def test_flapping_unchanged_quiet(self, tmp_path):
        """24h 窗提升不引入新 flapping：仅 1 次切换（10 分钟窗内）不触发。"""
        proot, mon, now = _make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": ""},
        }, moves_ago_minutes=[5])
        specs = {"spec-a": {"status": "implementing"}}
        mon._update_history(specs, now)
        signals = mon._detect_flapping(specs, now)
        assert not any(s.get("signal_type") == "flapping" for s in signals)