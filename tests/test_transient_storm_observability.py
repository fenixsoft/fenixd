"""evo-transient-storm-alert-context — 瞬断风暴告警上下文与自动核销单元测试。

覆盖 tasks：
- 2.1/2.3 触发时聚合清单构建（纯函数单测，design D4）
- 2.2 触发时日志与升级信号上下文注入聚合清单（对指纹归一化免疫）
- 3.1/3.2/3.3 熔断自然过期自动核销与幂等（handled/handled_by/resolve_note 审计）
- Requirement 4 场景：最新同类告警已处理时核销仍生效
- 4.2 既有瞬断语义回归（未达阈值不触发 / 单参调用零改动）
- 4.3 延迟过期解除不产生核销动作（无轮询/异步扫描）

design D4：聚合清单断言放纯函数单测；告警与核销断言用带临时 project_root 的
夹具（既有 _FakePM 的 project_root=None 会让告警写入即抛异常被吞、断言空转）。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.agent_runner.provider_circuit import (
    TRANSIENT_BREAK_ATTEMPT_LIST_LIMIT,
    ProviderCircuit,
    TransientAttempt,
)


class RecordingLogger:
    """记录型 logger（断言依赖 records；与 tests/test_provider_failover.py 同族）。"""

    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.records.append(("info", a[1] if len(a) > 1 else ""))

    def warning(self, *a, **k):
        self.records.append(("warning", a[1] if len(a) > 1 else ""))

    def error(self, *a, **k):
        self.records.append(("error", a[1] if len(a) > 1 else ""))

    def messages(self):
        return [m for _lvl, m in self.records]

    def has_error(self, text):
        return any(lvl == "error" and text in m for lvl, m in self.records)


class _FakePM:
    """带临时 project_root 的 PM 夹具（design D4：project_root=None 会让告警写入
    即抛异常被吞、断言空转）。_now() 为可控单调秒、_get_config 走 ConfigLoader。"""

    def __init__(self, project_root, logger=None, config=None):
        self.config = config or {}
        self.project_root = Path(project_root)
        self.logger = logger or RecordingLogger()
        self.now = 1000.0

    def _now(self):
        return self.now

    def _get_config(self, key, default=None):
        from core.config import ConfigLoader

        return ConfigLoader.get(self.config, key, default)


def _make_circuit(tmp_path, config=None, logger=None):
    pm = _FakePM(tmp_path, logger=logger, config=config)
    return ProviderCircuit(pm), pm


def _read_alerts(project_root):
    path = Path(project_root) / ".fenix" / "admin_alerts.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _write_alerts(project_root, records):
    path = Path(project_root) / ".fenix" / "admin_alerts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_iso(offset_minutes=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)).isoformat()


def _storm_record(alert_id, created_iso, handled=False, **extra):
    rec = {
        "kind": "escalation",
        "signal_type": "transient_break_storm",
        "spec": "global-transient",
        "created": created_iso,
        "handled": handled,
        "id": alert_id,
    }
    rec.update(extra)
    return rec


# ═══════════════════════════════════════════════════════════════════════════
# 2.1/2.3 触发时聚合清单（纯函数单测，不经 ProviderCircuit 接线）
# ═══════════════════════════════════════════════════════════════════════════

class TestAttemptSummary:
    """触发时构建窗口内 attempt 聚合列表 + 有界截断（design D2）。"""

    @staticmethod
    def _attempts(n, at_start=0.0):
        return [
            TransientAttempt(
                spec=f"spec-{i}", run_id=f"run-{i}",
                provider="inferaiapi.com", at=at_start + i,
            )
            for i in range(n)
        ]

    def test_summary_lists_meta_and_iso_at(self):
        """聚合清单含 run_id/spec/provider，at 为 ISO 时间戳。"""
        summary, truncated = ProviderCircuit._build_attempt_summary(
            self._attempts(1, at_start=1000.0)
        )
        assert truncated == 0
        assert len(summary) == 1
        item = summary[0]
        assert item["run_id"] == "run-0"
        assert item["spec"] == "spec-0"
        assert item["provider"] == "inferaiapi.com"
        parsed = datetime.fromisoformat(item["at"])  # ISO 可解析
        assert parsed.tzinfo is not None

    def test_summary_within_limit_no_truncation(self):
        """窗口内事件数不超上限 → 不截断。"""
        summary, truncated = ProviderCircuit._build_attempt_summary(
            self._attempts(5)
        )
        assert truncated == 0
        assert len(summary) == 5

    def test_summary_bounded_and_truncated(self):
        """清单有界（N=20）：超出时保留最近 limit 条、truncated=被略去条数。"""
        events = self._attempts(25, at_start=1000.0)
        summary, truncated = ProviderCircuit._build_attempt_summary(events)
        assert truncated == 5
        assert len(summary) == TRANSIENT_BREAK_ATTEMPT_LIST_LIMIT
        assert summary[0]["run_id"] == "run-5"     # 最新在后，略去最旧 5 条
        assert summary[-1]["run_id"] == "run-24"

    def test_summary_empty(self):
        """空事件列表 → 空清单、不截断。"""
        summary, truncated = ProviderCircuit._build_attempt_summary([])
        assert summary == []
        assert truncated == 0


# ═══════════════════════════════════════════════════════════════════════════
# 1.1/1.2 元信息记账（含已冻结早退分支同构）
# ═══════════════════════════════════════════════════════════════════════════

class TestAttemptMetaRecording:
    """瞬断记账记录 attempt 元信息；两处记账点同构（design D1）。"""

    def test_meta_recorded_on_trigger_path(self, tmp_path):
        """正常记账路径写入 TransientAttempt（spec/run_id/provider/at）。"""
        pc, pm = _make_circuit(tmp_path)
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1000,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com",
        )
        events = pc._transient_break_events["unrecognized model <model>"]
        assert len(events) == 1
        ev = events[0]
        assert isinstance(ev, TransientAttempt)
        assert ev.spec == "evo-a"
        assert ev.run_id == "run-a1"
        assert ev.provider == "inferaiapi.com"
        assert ev.at == 1000.0

    def test_frozen_branch_records_same_structure(self, tmp_path):
        """已冻结早退分支与正常路径同构记账：不产生混合元素、元信息保留
        （否则滑窗剔除 ``now - t`` 与 D2 聚合对混合元素取值失败）。"""
        pc, pm = _make_circuit(tmp_path)
        for i, t in enumerate([1000, 1100, 1200]):
            pc.record_transient_error(
                "unrecognized model deepseek-v4", now=t,
                spec=f"evo-{i}", run_id=f"run-{i}",
                provider="inferaiapi.com",
            )
        assert pc.is_global_transient_break(now=1200) is True
        # 冻结中再记账（早退分支）
        pc.record_transient_error(
            "unrecognized model deepseek-v5", now=1300,
            spec="evo-x", run_id="run-x1", provider="inferaiapi.com",
        )
        for events in pc._transient_break_events.values():
            assert all(isinstance(ev, TransientAttempt) for ev in events)
            assert all(ev.spec and ev.run_id and ev.provider for ev in events)
        # 到期后续触发：聚合清单仍可取（无混合类型报错）
        assert pc.is_global_transient_break(now=1900) is False
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=2400,
            spec="evo-y", run_id="run-y1", provider="inferaiapi.com",
        )
        summary, _truncated = ProviderCircuit._build_attempt_summary(
            pc._transient_break_events["unrecognized model <model>"]
        )
        assert all({"run_id", "spec", "provider", "at"} <= set(i) for i in summary)

    def test_window_slide_uses_at_timestamp(self, tmp_path):
        """滑窗剔除仍按时间戳（at）进行，行为不变。"""
        pc, pm = _make_circuit(tmp_path)
        pc.record_transient_error("unrecognized model deepseek-v4", now=0)
        pc.record_transient_error("unrecognized model deepseek-v4", now=100)
        # 第三次在窗口外（窗口 600s）：旧事件滑出，不达阈值
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=700) is False


# ═══════════════════════════════════════════════════════════════════════════
# 2.2 触发时聚合注入（日志 + 升级信号上下文）
# ═══════════════════════════════════════════════════════════════════════════

class TestTriggerAggregation:
    """触发全局熔断时 ERROR 日志与 transient_break_storm 上下文携带聚合清单。"""

    def test_trigger_injects_summary_into_log_and_alert(self, tmp_path):
        """ERROR 日志追加 failed attempts 清单；升级信号 evidence/description
        含 run_id/spec/provider（对指纹归一化免疫）。"""
        pc, pm = _make_circuit(tmp_path)
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1000,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com") is False
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1100,
            spec="evo-b", run_id="run-b1", provider="inferaiapi.com") is False
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1200,
            spec="evo-c", run_id="run-c1", provider="inferaiapi.com") is True
        # ERROR 日志含 failed attempts 聚合清单（design D2）
        assert pm.logger.has_error("failed attempts")
        assert any(
            "run-a1" in m and "inferaiapi.com" in m and "failed attempts" in m
            for m in pm.logger.messages()
        )
        # 升级信号上下文含聚合清单
        alerts = _read_alerts(pm.project_root)
        storms = [e for e in alerts if e.get("signal_type") == "transient_break_storm"]
        assert len(storms) == 1
        storm = storms[0]
        assert "failed_attempts" in storm["evidence"]
        for probe in ("run-a1", "run-b1", "run-c1", "inferaiapi.com"):
            assert probe in storm["evidence"]
        assert "attempt" in storm["description"]

    def test_below_threshold_no_trigger_no_alert(self, tmp_path):
        """未达阈值不触发（既有语义回归）：不写告警、不冻结。"""
        pc, pm = _make_circuit(tmp_path)
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1000,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1100,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        assert pc.is_global_transient_break(now=1100) is False
        assert _read_alerts(pm.project_root) == []

    def test_legacy_single_arg_call_without_meta(self, tmp_path):
        """既有单参形态调用（不含元信息）零改动：正常记账、元信息空串占位、
        不阻断熔断记账与告警写入。"""
        pc, pm = _make_circuit(tmp_path)
        assert pc.record_transient_error("unrecognized model deepseek-v4",
                                         now=1000) is False
        assert pc.record_transient_error("unrecognized model deepseek-v4",
                                         now=1100) is False
        assert pc.record_transient_error("unrecognized model deepseek-v4",
                                         now=1200) is True
        events = pc._transient_break_events["unrecognized model <model>"]
        assert all(ev.spec == "" and ev.run_id == "" and ev.provider == ""
                   for ev in events)
        alerts = _read_alerts(pm.project_root)
        assert len(alerts) == 1  # 告警正常写入，无崩溃


# ═══════════════════════════════════════════════════════════════════════════
# 3.x 熔断自然过期自动核销
# ═══════════════════════════════════════════════════════════════════════════

class TestExpiryAutoResolve:
    """过期自动核销：handled + handled_by + resolve_note 审计；幂等零写回。"""

    def _trigger_storm(self, pc):
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1000,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1100,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1200,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        alerts = _read_alerts(pc._pm.project_root)
        assert alerts and alerts[0].get("handled") is False

    def test_expiry_auto_resolves_alert(self, tmp_path):
        """熔断自然过期（dispatch resumed）→ 对应告警 handled=True +
        handled_by=auto-resolve + 核销原因「熔断自然过期」+ 聚合清单摘要留审计。"""
        pc, pm = _make_circuit(tmp_path)
        self._trigger_storm(pc)
        alert_id = _read_alerts(pm.project_root)[0]["id"]
        # 冷却 600s：1200+600=1800 到期
        assert pc.is_global_transient_break(now=1700) is True
        assert pc.is_global_transient_break(now=1801) is False
        records = {r["id"]: r for r in _read_alerts(pm.project_root)}
        resolved = records[alert_id]
        assert resolved["handled"] is True
        assert resolved["handled_by"] == "auto-resolve"
        assert "熔断自然过期" in resolved["resolve_note"]
        assert "failed_attempts" in resolved["resolve_note"]

    def test_repeated_expiry_idempotent_zero_write(self, tmp_path):
        """重复过期（无新告警、候选已核销）→ 零操作、零写回（mtime 不变）。"""
        pc, pm = _make_circuit(tmp_path)
        self._trigger_storm(pc)
        assert pc.is_global_transient_break(now=1801) is False  # 首次过期 → 核销
        alerts_path = pm.project_root / ".fenix" / "admin_alerts.json"
        before = alerts_path.read_text(encoding="utf-8")
        mtime_before = alerts_path.stat().st_mtime_ns
        # 第二轮触发：15 分钟节流抑制重复告警（不写第二条）→ 过期 → 零写回
        pc.record_transient_error("unrecognized model deepseek-v4", now=2000,
                                  spec="evo-a", run_id="run-a1",
                                  provider="inferaiapi.com")
        pc.record_transient_error("unrecognized model deepseek-v4", now=2100,
                                  spec="evo-a", run_id="run-a1",
                                  provider="inferaiapi.com")
        assert pc.record_transient_error(
            "unrecognized model deepseek-v4", now=2200,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com") is True
        # 第二次过期：latest_signal 命中已核销候选 → _latest_unhandled_storm
        # 无未处理者 → 零操作、零写回
        assert pc.is_global_transient_break(now=2801) is False
        assert alerts_path.read_text(encoding="utf-8") == before
        assert alerts_path.stat().st_mtime_ns == mtime_before

    def test_expiry_without_alert_zero_write(self, tmp_path):
        """无对应告警 → 零操作、零写回（不创建记录文件）。"""
        pc, pm = _make_circuit(tmp_path)
        alerts_path = pm.project_root / ".fenix" / "admin_alerts.json"
        assert not alerts_path.exists()
        # 直接设置熔断态（不经触发路径，避免产生告警）
        pc._transient_break_until = 1000.0
        pc._transient_break_events.setdefault("fp", []).append(
            TransientAttempt(spec="s", run_id="r", provider="p", at=900.0))
        assert pc.is_global_transient_break(now=1001) is False
        assert not alerts_path.exists()  # 零写回

    def test_expiry_candidate_handled_zero_operation(self, tmp_path):
        """窗口中只有已处理候选 → 核销跳过、零操作（内容与 mtime 均不变）。"""
        pc, pm = _make_circuit(tmp_path)
        _write_alerts(pm.project_root, [
            _storm_record("handled-1", _now_iso(), handled=True,
                          handled_by="auto-resolve"),
        ])
        alerts_path = pm.project_root / ".fenix" / "admin_alerts.json"
        before = alerts_path.read_text(encoding="utf-8")
        mtime_before = alerts_path.stat().st_mtime_ns
        pc._transient_break_until = 500.0
        assert pc.is_global_transient_break(now=600) is False
        assert alerts_path.read_text(encoding="utf-8") == before
        assert alerts_path.stat().st_mtime_ns == mtime_before
        record = _read_alerts(pm.project_root)[0]
        assert record["handled"] is True
        assert record.get("resolve_note") is None  # 未被改写

    def test_expiry_resolves_older_unhandled_behind_newer_handled(self, tmp_path):
        """Requirement 4 场景：窗口内较新已处理条目 + 较早未处理条目并存 →
        过期核销选中较早未处理者，MUST NOT 改写已处理条目。"""
        pc, pm = _make_circuit(tmp_path)
        _write_alerts(pm.project_root, [
            _storm_record("older-unhandled", _now_iso(-5), handled=False),
            _storm_record("newer-handled", _now_iso(), handled=True,
                          handled_by="auto-resolve"),
        ])
        pc._transient_break_until = 500.0
        assert pc.is_global_transient_break(now=600) is False
        records = {r["id"]: r for r in _read_alerts(pm.project_root)}
        # 较早未处理者被核销
        assert records["older-unhandled"]["handled"] is True
        assert records["older-unhandled"]["handled_by"] == "auto-resolve"
        assert "熔断自然过期" in records["older-unhandled"]["resolve_note"]
        # 较新已处理条目不被改写
        assert records["newer-handled"]["handled"] is True
        assert records["newer-handled"]["handled_by"] == "auto-resolve"
        assert records["newer-handled"].get("resolve_note") is None


# ═══════════════════════════════════════════════════════════════════════════
# 4.3 延迟过期解除不产生核销动作（无轮询/异步扫描）
# ═══════════════════════════════════════════════════════════════════════════

class TestDelayedExpiry:
    """冻结到期后无人查询熔断态 → 不产生核销动作（task 4.3）。

    本方案不做轮询/异步扫描——核销只内联在 is_global_transient_break 的过期
    分支（dispatch 闸门查询路径）。到期后无人查询的漏核销路径由
    admin_alerts.json 的 MAX_RECORDS=150 环形裁剪（core/admin_store.py:34,
    193-194）与人工/Dashboard 处置承接——本仓库不存在按时间的告警清理机制。
    """

    def test_delayed_expiry_no_polling_no_resolve(self, tmp_path):
        pc, pm = _make_circuit(tmp_path)
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1000,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1100,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        pc.record_transient_error(
            "unrecognized model deepseek-v4", now=1200,
            spec="evo-a", run_id="run-a1", provider="inferaiapi.com")
        alerts_path = pm.project_root / ".fenix" / "admin_alerts.json"
        before = alerts_path.read_text(encoding="utf-8")
        assert _read_alerts(pm.project_root)[0]["handled"] is False
        # 到期（until=1800、now=2000）但无人查询熔断态 → 无核销写回
        pm.now = 2000.0
        assert alerts_path.read_text(encoding="utf-8") == before
        assert _read_alerts(pm.project_root)[0]["handled"] is False
        # 首次闸门查询本身才触发过期核销
        assert pc.is_global_transient_break() is False
        assert _read_alerts(pm.project_root)[0]["handled"] is True