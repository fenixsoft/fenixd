"""
evo-supervisor-drift-log-dedup 回归测试。

覆盖（与 tasks.md 一一对应）：
- Task 1.2 / 2.1：supervisor drain 一致性检查 PROJECT_LOG 追加窗口去重
  - 窗口内第二次启动不重复追加 PROJECT_LOG（框架日志仍逐条落，抑制留痕）
  - 超窗后新周期照常成条并写入新的去重标记（warning 级、写入即 handled）
  - admin_store 缺失 / latest_signal 读写异常时降级为照常追加（保持现状）
"""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

# 模块级 import（test_supervisor_hosting.py 同款处方）：直接绑定守护脚本模块
# fenixd.py，供用例在测试执行期使用。
import fenixd as _fenixd_mod
import core.fenix_session as fenix_session
from core.admin_store import AdminStore


def _make_daemon(tmp_path, monkeypatch, name):
    """装配最小 daemon：drain>0 + runtime 文件缺失 → drain 一致性警告必产出。

    runtime 缺失分支不读 daemon_started、不依赖任何时间戳，判定确定性最高。
    """
    proot = tmp_path / name
    (proot / ".fenix" / "logs").mkdir(parents=True, exist_ok=True)
    d = _fenixd_mod.FenixDaemon()
    d.config = {}
    d.logger = mock.MagicMock()
    d.pm_engine = mock.MagicMock()
    d.admin_store = AdminStore(proot, d.logger)
    monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
    monkeypatch.setattr(d, "_shutdown_drain_seconds", lambda: 1800)
    monkeypatch.setattr(fenix_session, "supervisor_running", lambda root=None: True)
    return d, proot


def _project_log_texts(d):
    return [str(c.args[0]) for c in d.pm_engine._append_project_log.call_args_list]


def _markers(store):
    return [
        a
        for a in store.read_all()
        if a.get("signal_type") == "supervisor_runtime_drift"
    ]


def _backdate_markers(store, minutes):
    """把去重标记记录的 created 回拨 minutes 分钟，模拟窗口过期。

    admin_alerts.json 为裸记录数组（新记录在末尾）；标记为 escalation、
    不带 last_seen，latest_signal 窗口锚点即 created。
    """
    records = json.loads(store.alerts_path.read_text(encoding="utf-8"))
    old = (
        datetime.now(timezone.utc) - timedelta(minutes=minutes)
    ).isoformat()
    n = 0
    for rec in records:
        if rec.get("signal_type") == "supervisor_runtime_drift":
            rec["created"] = old
            rec.pop("last_seen", None)
            n += 1
    store.alerts_path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return n


class TestSupervisorDriftLogDedup:
    def test_window_hit_skips_project_log_append(self, tmp_path, monkeypatch):
        """窗口内第二次启动：PROJECT_LOG 不再追加，框架日志仍逐条落（R1/R2）。"""
        d, _proot = _make_daemon(tmp_path, monkeypatch, "proj-hit")
        d._check_supervisor_drain_consistency()  # 首次启动
        texts = _project_log_texts(d)
        assert len(texts) == 1
        assert "supervisor 未上报 SIGKILL 等待窗口" in texts[0]
        markers = _markers(d.admin_store)
        assert len(markers) == 1
        marker = markers[0]
        assert marker["severity"] == "warning"
        assert marker["spec"] is None
        assert marker["handled"] is True  # 写入即 mark_handled，不进人工队列

        # 窗口内第二次「启动」：新 daemon 实例共享同一 admin_alerts.json
        d2, _ = _make_daemon(tmp_path, monkeypatch, "proj-hit")
        d2._check_supervisor_drain_consistency()
        assert len(_project_log_texts(d2)) == 0  # PROJECT_LOG 不再刷屏
        assert len(_markers(d2.admin_store)) == 1  # 不重复写标记
        warn_texts = [str(c) for c in d2.logger.warning.call_args_list]
        # 框架日志不受影响，被抑制的只是 PROJECT_LOG 追加
        assert any(
            "supervisor 未上报 SIGKILL 等待窗口" in w for w in warn_texts
        )
        info_texts = [str(c) for c in d2.logger.info.call_args_list]
        assert any("窗口去重命中" in w for w in info_texts)

    def test_window_expiry_appends_again_and_writes_new_marker(
        self, tmp_path, monkeypatch
    ):
        """超窗后新周期：照常成条并写入新的去重标记（R3）。"""
        d, _proot = _make_daemon(tmp_path, monkeypatch, "proj-expiry")
        d._check_supervisor_drain_consistency()
        assert len(_project_log_texts(d)) == 1
        assert _backdate_markers(d.admin_store, 61) == 1  # > 60 分钟窗口

        d2, _ = _make_daemon(tmp_path, monkeypatch, "proj-expiry")
        d2._check_supervisor_drain_consistency()
        assert len(_project_log_texts(d2)) == 1  # 新周期照常成条
        markers = _markers(d2.admin_store)
        assert len(markers) == 2  # 新的去重标记已写入
        assert all(m.get("handled") for m in markers)
        # 最新的标记 created 在窗口内（未被回拨）
        latest = max(m["created"] for m in markers)
        assert datetime.fromisoformat(latest) > (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        )

    def test_admin_store_missing_degrades_to_append(self, tmp_path, monkeypatch):
        """admin_store 缺失：降级为照常追加 PROJECT_LOG（R4，保持现状行为）。"""
        d, _proot = _make_daemon(tmp_path, monkeypatch, "proj-degrade")
        d.admin_store = None
        d._check_supervisor_drain_consistency()
        texts = _project_log_texts(d)
        assert len(texts) == 1
        assert "supervisor 未上报 SIGKILL 等待窗口" in texts[0]
        warn_texts = [str(c) for c in d.logger.warning.call_args_list]
        assert any("supervisor 未上报" in w for w in warn_texts)

    def test_latest_signal_error_degrades_to_append(self, tmp_path, monkeypatch):
        """latest_signal 读写异常：降级为照常追加并留 warning（R4）。"""
        d, _proot = _make_daemon(tmp_path, monkeypatch, "proj-err")
        d.admin_store.latest_signal = mock.MagicMock(
            side_effect=RuntimeError("alerts io boom")
        )
        d._check_supervisor_drain_consistency()
        assert len(_project_log_texts(d)) == 1  # 不因去重机制丢日志
        warn_texts = [str(c) for c in d.logger.warning.call_args_list]
        assert any("去重状态不可用" in w for w in warn_texts)
