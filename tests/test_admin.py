"""admin_store / admin_monitor / run_administrator / Dashboard alerts API 测试。

对应 spec/changes/add-administrator-agent 的 tasks 4.1-4.3。
"""

import json
import os
import re
import threading
import time
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.admin_store import AdminStore, SIGNAL, ESCALATION, DISPOSITION
from core.admin_monitor import AdminMonitor
from core.agent_runner import AdminDisposition, AgentRunner
from core.agent_runner.runner import admin_disposition_path
from core.dashboard.registry import Registry
from core.dashboard.server import DashboardHTTPServer, find_free_port
from tests.helpers import FakeLogger, utcnow_iso, iso_ago


# ── 辅助 ────────────────────────────────────────────────

# FakeLogger / utcnow_iso / iso_ago 收编至 tests/helpers.py（原为本文件与
# 多个测试文件逐字节相同的副本）。


class FakeSM:
    def __init__(self, specs: dict):
        self._specs = specs

    def read_all(self):
        return self._specs

    def read_one(self, name):
        return self._specs.get(name)


class FakeRunner:
    def __init__(self):
        self.calls = []

    def run_administrator(self, signal):
        self.calls.append(signal)
        return AdminDisposition(
            run_id="admin-test-1",
            spec=signal.get("spec"),
            success=True,
            problem=signal.get("description", ""),
            actions_taken="测试处置",
            result="resolved",
            summary="诊断结论：测试困境；处置时间线：测试处置；结果：已解决。",
        )


def make_runs(proot: Path, entries: list):
    """写入 run 产物文件；entries: [(run_id, terminal)]，terminal in (error/done/running)。"""
    runs_dir = proot / ".fenix" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for run_id, terminal in entries:
        lines = []
        if terminal == "error":
            lines.append({"type": "system", "subtype": "init"})
            lines.append({"type": "error", "message": "boom", "num_turns": 3})
        elif terminal == "done":
            lines.append({"type": "system", "subtype": "init"})
            lines.append({"type": "result", "result": "完成", "num_turns": 3})
        else:  # running
            lines.append({"type": "assistant",
                          "message": {"content": [{"type": "text", "text": "..."}]}})
        (runs_dir / f"{run_id}.jsonl").write_text(
            "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in lines),
            encoding="utf-8",
        )


def make_monitor(tmp_path, specs: dict, config=None, runner=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    mon = AdminMonitor(
        config or {},
        FakeSM(specs),
        proot,
        FakeLogger(),
        store=AdminStore(proot, FakeLogger()),
        agent_runner=runner,
    )
    return proot, mon


def disposition_path_from_prompt(prompt: str) -> Path:
    """从 administrator 提示词中提取按 run 注入的处置实例文件路径。

    fix-admin-run-blocks-mainloop：提示词 MUST 指向 .fenix/admin_disposition-<run_id>.json
    （而非旧全局 .fenix/admin_disposition.json），Admin 按提示词写入后 runner
    读到的才是自身结果。
    """
    m = re.search(r"(/[^\s()）]*/\.fenix/admin_disposition-[^)\s）]+\.json)", prompt)
    assert m, f"提示词未注入实例处置路径：{prompt[:300]}"
    return Path(m.group(1))


def wait_for_event(evt: threading.Event, timeout: float = 5.0):
    """等待 worker 线程完成（超时断言，避免测试静默挂起/假通过）。"""
    assert evt.wait(timeout), "worker 未在超时内完成处置"


def make_admin_runner_stub(proot: Path, *, fake_run_claude=None,
                           admin_model: str = "claude-sonnet-5",
                           assignment_fn=None) -> AgentRunner:
    """run_administrator 测试共用的最小 AgentRunner 替身（绕过真实 __init__）。

    原 TestRunAdministrator 内 10 条测试逐条复制同一 8-10 行桩链
    （project_root/logger/_get_config/_get_admin_model/_get_agent_model_assignment/
    _prompt_builder._build_prompt），收编为此 helper。
    assignment_fn：_get_agent_model_assignment 替身（默认恒 None，即未分配 provider）。
    """
    runner = AgentRunner.__new__(AgentRunner)
    runner.project_root = proot
    runner.logger = FakeLogger()
    runner._get_config = lambda key, default=None: default
    runner._get_admin_model = lambda: admin_model
    runner._get_agent_model_assignment = assignment_fn or (lambda agent_type: None)
    runner._prompt_builder._build_prompt = lambda *a, **k: "prompt"
    if fake_run_claude is not None:
        runner._run_claude = fake_run_claude
    return runner


def _fake_admin_writes_payload(payload: dict):
    """构造模拟 Admin 按提示词注入的实例路径写处置文件的 _run_claude 替身。"""
    def fake(prompt, cwd, run_id, model_override, env_overrides, max_turns,
             spec_name=None, agent_type=None):
        admin_disposition_path(cwd, run_id).write_text(
            json.dumps(payload), encoding="utf-8")
        return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                     "cost_usd": 0.0}
    return fake


def _jline(ts_min_ago=None, **fields):
    """构造 fenixd.log 单行 JSON 事件；ts_min_ago=None 表示缺 timestamp。"""
    ev = {"level": "ERROR", "component": "fenixd", "message": "boom"}
    if ts_min_ago is not None:
        ev["timestamp"] = iso_ago(ts_min_ago)
    ev.update(fields)
    return json.dumps(ev, ensure_ascii=False)


# ── 4.2 admin_store 读写 + 标记已处理 ───────────────────



class TestAdminStore:
    def test_append_fills_defaults(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        rec = store.append({"kind": ESCALATION, "description": "x"})
        assert rec["id"]
        assert rec["created"]
        assert rec["handled"] is False
        assert rec["handled_at"] is None
        assert rec["severity"] == "major"
        assert rec["spec"] is None

    def test_append_serializes_non_string_evidence(self, tmp_path):
        """evidence 契约是字符串：写入口把 dict/list 序列化为 JSON 串。

        回归 fix-alert-evidence-render-crash：stash_pop_conflict 直发结构化
        evidence dict，前端 React 直接渲染对象崩溃（首页白屏）。
        序列化落在存储边界，读侧（Dashboard API / prompt 注入 / 冷却去重）拿到的
        evidence 恒为 str 或 None。
        """
        store = AdminStore(tmp_path, FakeLogger())
        rec = store.append({
            "kind": SIGNAL, "signal_type": "stash_pop_conflict",
            "evidence": {"conflict_files": ["core/a.py"], "stash_kept": False},
        })
        assert isinstance(rec["evidence"], str), "写入口应把 dict evidence 序列化"
        assert "core/a.py" in rec["evidence"]
        # 落地文件（读侧权威源）同样为字符串
        on_disk = json.loads(
            (tmp_path / ".fenix" / "admin_alerts.json").read_text(encoding="utf-8"))
        assert isinstance(on_disk[0]["evidence"], str)

    def test_append_preserves_string_and_missing_evidence(self, tmp_path):
        """字符串 evidence 原样保留；缺省 evidence 仍为 None（不序列化为 "null"）。"""
        store = AdminStore(tmp_path, FakeLogger())
        rec_str = store.append({"kind": SIGNAL, "evidence": "纯文本证据"})
        assert rec_str["evidence"] == "纯文本证据"
        rec_none = store.append({"kind": SIGNAL})
        assert rec_none["evidence"] is None

    def test_read_all_heals_legacy_dict_evidence(self, tmp_path):
        """存量（修复前落盘）的结构化 evidence 在读侧被归一为字符串。

        写入口修复只能挡住新写入；已在 admin_alerts.json 里的 dict evidence
        仍会让 Dashboard API 下发对象、前端首页白屏，故读侧同样归一，
        存量记录一次读即自愈。
        """
        apath = tmp_path / ".fenix" / "admin_alerts.json"
        apath.parent.mkdir(parents=True, exist_ok=True)
        apath.write_text(json.dumps([{
            "kind": ESCALATION, "id": "legacy1", "handled": False,
            "signal_type": "stash_pop_conflict",
            "evidence": {"conflict_files": ["core/x.py"], "stash_kept": True},
        }]), encoding="utf-8")
        store = AdminStore(tmp_path, FakeLogger())
        recs = store.read_all()
        assert isinstance(recs[0]["evidence"], str), "读侧应归一存量 dict evidence"
        assert "core/x.py" in recs[0]["evidence"]
        # unhandled() 走同一读路径，同样归一
        assert isinstance(store.unhandled()[0]["evidence"], str)

    def test_read_all_newest_first(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "description": "first"})
        time.sleep(0.01)
        store.append({"kind": ESCALATION, "signal_type": "stuck", "description": "second"})
        recs = store.read_all()
        assert len(recs) == 2
        assert recs[0]["description"] == "second"  # 最新的在前

    def test_unhandled_only_escalations(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck"})
        esc = store.append({"kind": ESCALATION, "signal_type": "stuck"})
        store.append({"kind": DISPOSITION, "signal_type": "stuck"})
        un = store.unhandled()
        assert len(un) == 1
        assert un[0]["id"] == esc["id"]

    def test_mark_handled(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        esc = store.append({"kind": ESCALATION, "signal_type": "stuck"})
        assert store.mark_handled(esc["id"]) is True
        assert store.unhandled() == []
        recs = store.read_all()
        assert recs[0]["handled"] is True
        assert recs[0]["handled_at"]
        # 重复标记返回 False
        assert store.mark_handled(esc["id"]) is False

    def test_mark_handled_ignores_non_escalation(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        sig = store.append({"kind": SIGNAL, "signal_type": "stuck"})
        assert store.mark_handled(sig["id"]) is False

    def test_concurrent_append_across_threads(self, tmp_path):
        """AdminStore 跨线程使用：worker 池并行追加 + 主线程读取不丢不损
        （fix-admin-run-blocks-mainloop tasks 4.3：文件锁与线程亲和无关）。"""
        store = AdminStore(tmp_path, FakeLogger())
        workers_count, per_worker = 4, 10
        errors = []

        def append_many(idx):
            try:
                for i in range(per_worker):
                    store.append({
                        "kind": DISPOSITION,
                        "status": "pending",
                        "spec": f"spec-{idx}",
                        "admin_run_id": f"admin-spec-{idx}-{i}",
                        "description": f"worker {idx} run {i}",
                    })
            except Exception as e:  # noqa: BLE001 — 线程内失败收集后统一断言
                errors.append(e)

        threads = [threading.Thread(target=append_many, args=(i,))
                   for i in range(workers_count)]
        # 主线程并发读取（模拟 dashboard watcher / 巡检同时读）
        stop = threading.Event()
        read_snapshots = []

        def read_while_writing():
            while not stop.is_set():
                try:
                    read_snapshots.append(len(store.read_all()))
                except Exception as e:  # noqa: BLE001
                    errors.append(e)
                    return
                time.sleep(0.001)

        reader = threading.Thread(target=read_while_writing)
        for t in threads:
            t.start()
        reader.start()
        for t in threads:
            t.join(timeout=10)
        stop.set()
        reader.join(timeout=5)

        assert errors == []
        recs = store.read_all()
        assert len(recs) == workers_count * per_worker
        # 追加内容互不覆盖（每条 id 唯一）
        assert len({r["id"] for r in recs}) == workers_count * per_worker
        # 读取过程始终得到合法 JSON 记录列表（无半截写）
        assert all(isinstance(n, int) for n in read_snapshots)

    def test_mark_all_handled(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "s1"})
        store.append({"kind": ESCALATION, "signal_type": "flapping", "spec": "s2"})
        store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"})  # 非升级不处理
        assert store.mark_all_handled() == 2
        assert store.unhandled() == []
        assert all(r["handled"] for r in store.read_all() if r["kind"] == ESCALATION)
        # 幂等：再次调用返回 0
        assert store.mark_all_handled() == 0

    def test_latest_signal_within_window(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"})
        assert store.latest_signal("s1", "stuck", 15) is not None
        assert store.latest_signal("s1", "stuck", 0) is None        # 冷却关闭
        assert store.latest_signal("s2", "stuck", 15) is None       # 其它 spec
        assert store.latest_signal(None, "stuck", 15) is None       # 该信号带 spec，不匹配 daemon 级

    def test_latest_signal_old_record_ignored(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1",
                      "created": iso_ago(60)})  # append 保留显式 created
        assert store.latest_signal("s1", "stuck", 15) is None

    def test_corrupt_file_returns_empty(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": SIGNAL, "signal_type": "stuck"})
        (tmp_path / ".fenix" / "admin_alerts.json").write_text("not json{", encoding="utf-8")
        assert store.read_all() == []
        assert store.unhandled() == []

    def test_unhandled_for_matches_spec_and_type(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "s1"})
        assert store.unhandled_for("s1", "stuck") is not None
        assert store.unhandled_for("s2", "stuck") is None
        assert store.unhandled_for("s1", "flapping") is None

    def test_append_trims_to_max_records(self, tmp_path):
        """任何写回自动裁剪：只保留最近 MAX_RECORDS 条，最旧的被删。"""
        from core.admin_store import MAX_RECORDS
        store = AdminStore(tmp_path, FakeLogger())
        for i in range(MAX_RECORDS + 10):
            store.append({"kind": SIGNAL, "description": f"#{i}"})
        records = store.read_all()
        assert len(records) == MAX_RECORDS
        descs = {r["description"] for r in records}
        assert "#0" not in descs and "#9" not in descs  # 最旧 10 条被裁
        assert f"#{MAX_RECORDS + 9}" in descs           # 最新一条在

    def test_no_trim_below_limit(self, tmp_path):
        store = AdminStore(tmp_path, FakeLogger())
        for i in range(20):
            store.append({"kind": SIGNAL, "description": f"#{i}"})
        assert len(store.read_all()) == 20

    # ── admin-signal-consolidation D1：merge_signal 状态沉淀 ──────

    def test_merge_signal_creates_record_with_hash_and_last_seen(self, tmp_path):
        """首见：merge_signal 创建带 status_hash/last_seen 的记录（return is_new）。"""
        store = AdminStore(tmp_path, FakeLogger())
        rec, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "blocked_stuck", "spec": "s1",
            "severity": "critical", "escalated": True,
        }, "hash-1")
        assert is_new is True
        assert rec["status_hash"] == "hash-1"
        assert rec["last_seen"] == rec["created"]  # 首见 last_seen == first_seen
        assert rec["escalated"] is True
        records = store.read_all()
        assert len(records) == 1
        assert records[0]["status_hash"] == "hash-1"

    def test_merge_signal_unchanged_state_updates_last_seen_only(self, tmp_path):
        """状态未变：同 (spec, signal_type, status_hash) 仅刷 last_seen，保留
        id/created(=first_seen)/escalated，不新增记录。"""
        store = AdminStore(tmp_path, FakeLogger())
        rec1, _ = store.merge_signal({
            "kind": SIGNAL, "signal_type": "blocked_stuck", "spec": "s1",
            "escalated": True,
        }, "hash-1")
        rec2, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "blocked_stuck", "spec": "s1",
            "escalated": True,
        }, "hash-1")
        assert is_new is False
        assert rec2["id"] == rec1["id"]                    # 不改写 id
        assert rec2["created"] == rec1["created"]          # created=first_seen 保留
        assert rec2["escalated"] is True                   # escalated 保留/升级
        assert rec2["last_seen"] >= rec1["last_seen"]      # last_seen 刷新
        records = store.read_all()
        assert len(records) == 1

    def test_merge_signal_state_change_creates_new_record(self, tmp_path):
        """状态变化（status_hash 不同）→ 新建记录。"""
        store = AdminStore(tmp_path, FakeLogger())
        store.merge_signal({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"}, "hash-1")
        rec2, is_new = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"}, "hash-2")
        assert is_new is True
        assert rec2["status_hash"] == "hash-2"
        assert len(store.read_all()) == 2

    def test_merge_signal_different_spec_or_type_creates_new(self, tmp_path):
        """不同 spec 或 signal_type 不合并。"""
        store = AdminStore(tmp_path, FakeLogger())
        store.merge_signal({"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"}, "hash-1")
        store.merge_signal({"kind": SIGNAL, "signal_type": "stuck", "spec": "s2"}, "hash-1")
        store.merge_signal({"kind": SIGNAL, "signal_type": "flapping", "spec": "s1"}, "hash-1")
        assert len(store.read_all()) == 3

    def test_merge_signal_never_merges_escalation_or_disposition(self, tmp_path):
        """kind=escalation / disposition 不参与合并（id 是闭环锚点）。"""
        store = AdminStore(tmp_path, FakeLogger())
        esc = store.append({
            "kind": ESCALATION, "signal_type": "stuck", "spec": "s1"})
        disp = store.append({
            "kind": DISPOSITION, "signal_type": "stuck", "spec": "s1"})
        rec, is_new = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "stuck", "spec": "s1"}, "hash-1")
        assert is_new is True
        assert rec["id"] != esc["id"]
        records = store.read_all()
        assert len(records) == 3
        # escalation/disposition 未被改写（无 status_hash/last_seen 追加）
        esc_now = next(r for r in records if r["kind"] == ESCALATION)
        disp_now = next(r for r in records if r["kind"] == DISPOSITION)
        assert "status_hash" not in esc_now and "last_seen" not in esc_now
        assert "status_hash" not in disp_now and "last_seen" not in disp_now

    def test_merge_signal_never_merges_stored_signal_types(self, tmp_path):
        """「写入即待唤起」记录（pm_engine 直接 append、按 id 摄取 mark_escalated）
        不参与合并：无 status_hash 天然不命中，即使 (spec, signal_type) 相同。"""
        store = AdminStore(tmp_path, FakeLogger())
        stored = store.append({
            "kind": SIGNAL, "signal_type": "family_explosion", "spec": "s1",
            "escalated": False,
        })
        rec, is_new = store.merge_signal(
            {"kind": SIGNAL, "signal_type": "family_explosion", "spec": "s1"},
            "hash-1")
        assert is_new is True
        assert rec["id"] != stored["id"]
        records = store.read_all()
        assert len(records) == 2
        stored_now = next(r for r in records if r["id"] == stored["id"])
        assert stored_now["escalated"] is False           # 未被合并改写
        assert "last_seen" not in stored_now

    def test_merge_signal_escalated_monotonic_upgrade(self, tmp_path):
        """escalated 只允许单调升级（False→True，绝不 True→False）。"""
        store = AdminStore(tmp_path, FakeLogger())
        # 节流沉淀创建 escalated=False 记录 → 唤起分支合并升级为 True
        rec1, _ = store.merge_signal({
            "kind": SIGNAL, "signal_type": "stuck", "spec": "s1", "escalated": False}, "h")
        rec2, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "stuck", "spec": "s1", "escalated": True}, "h")
        assert is_new is False
        assert rec2["escalated"] is True
        # 已 escalated=True 的记录不被节流分支（incoming False）回退
        rec3, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "stuck", "spec": "s1", "escalated": False}, "h")
        assert is_new is False
        assert rec3["escalated"] is True
        assert len(store.read_all()) == 1

    def test_merge_signal_spec_none_daemon_consolidates(self, tmp_path):
        """spec=None daemon 级信号按声明口径沉淀：同 (None, signal_type, hash)
        仅一条记录（spec.md R1「回退判据或显式排除二者择一」——实现采用回退判据）。"""
        store = AdminStore(tmp_path, FakeLogger())
        rec1, _ = store.merge_signal({
            "kind": SIGNAL, "signal_type": "daemon_errors", "spec": None}, "daemon-hash")
        rec2, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "daemon_errors", "spec": None}, "daemon-hash")
        assert is_new is False
        assert rec2["id"] == rec1["id"]
        assert len(store.read_all()) == 1

    # ── admin-signal-consolidation：latest_signal 窗口锚点 max(created,last_seen) ──

    def test_latest_signal_anchor_covers_last_seen(self, tmp_path):
        """沉淀后 created 停在首次、last_seen 持续刷新：跨越 cooldown 窗口仍命中节流。"""
        store = AdminStore(tmp_path, FakeLogger())
        # 首见 60 分钟前（以显式 created 模拟历史记录），随后同状态合并刷 last_seen
        store.append({
            "kind": SIGNAL, "signal_type": "blocked_stuck", "spec": "s1",
            "created": iso_ago(60), "last_seen": iso_ago(60),
            "status_hash": "h",
        })
        rec, is_new = store.merge_signal({
            "kind": SIGNAL, "signal_type": "blocked_stuck", "spec": "s1"}, "h")
        assert is_new is False
        hit = store.latest_signal("s1", "blocked_stuck", 15)
        assert hit is not None                  # created 60m 前但 last_seen 在窗口内
        assert hit["id"] == rec["id"]

    def test_latest_signal_no_last_seen_uses_created(self, tmp_path):
        """无 last_seen 的历史记录仍按 created 判定（本特性前写入 / escalation 等）。"""
        store = AdminStore(tmp_path, FakeLogger())
        store.append({
            "kind": SIGNAL, "signal_type": "stuck", "spec": "s1",
            "created": iso_ago(60)})            # 无 last_seen
        assert store.latest_signal("s1", "stuck", 15) is None
        assert store.latest_signal("s1", "stuck", 61) is not None

    @pytest.mark.parametrize(
        "signal_type,spec,window",
        [
            pytest.param("dispatch_stalled", "s1", 60,
                         id="dispatch_stalled"),
            pytest.param("instant_fail_storm", "s1", 15,
                         id="instant_fail_storm"),
            pytest.param("transient_break_storm", "global-transient", 60,
                         id="transient_break_storm"),
            pytest.param("verify_fail_escalation", "s1", 60,
                         id="verify-alert"),
        ],
    )
    def test_latest_signal_external_call_sites_semantics(
            self, tmp_path, signal_type, spec, window):
        """既有外部调用点（dispatch_stalled / instant_fail_storm /
        transient_break_storm / verify 告警）语义不变：escalation 记录无
        last_seen 字段，窗口判定维持按 created——窗口内命中、窗口外不命中。"""
        store = AdminStore(tmp_path, FakeLogger())
        store.append({"kind": ESCALATION, "signal_type": signal_type, "spec": spec})
        assert store.latest_signal(spec, signal_type, window) is not None
        assert store.latest_signal(spec, signal_type, 0) is None


# ── 4.1 admin_monitor 检测规则 ──────────────────────────

class TestAdminMonitorDetection:
    def test_repeated_failures(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        make_runs(proot, [
            ("impl-spec-a-1780000001", "error"),
            ("impl-spec-a-1780000002", "error"),
            ("impl-spec-a-1780000003", "error"),
            ("impl-spec-a-1780000000", "done"),  # 成功 run 不计数
        ])
        signals = mon.run_once()
        sig = next((s for s in signals if s["signal_type"] == "repeated_failures"), None)
        assert sig is not None
        assert sig["spec"] == "spec-a"

    def test_repeated_failures_below_threshold(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        make_runs(proot, [
            ("impl-spec-a-1780000001", "error"),
            ("impl-spec-a-1780000002", "error"),
        ])
        signals = mon.run_once()
        assert all(s["signal_type"] != "repeated_failures" for s in signals)

    def test_flapping(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        # 预写历史：10 分钟窗口内 4 次 ready↔implementing 变更（3 次切换）
        hist = proot / ".fenix" / "admin_state_history.json"
        hist.parent.mkdir(parents=True, exist_ok=True)
        base = time.time()
        changes = [
            [base - 500, "ready"], [base - 400, "implementing"],
            [base - 300, "ready"], [base - 200, "implementing"],
        ]
        hist.write_text(json.dumps(
            {"spec-a": {"last_status": "implementing", "changes": changes}}), encoding="utf-8")
        signals = mon.run_once()
        assert any(s["signal_type"] == "flapping" for s in signals)

    def test_stuck(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},  # 200 分钟（>160min stuck 缺省回退阈值）无进展
        })
        signals = mon.run_once()
        assert any(s["signal_type"] == "stuck" for s in signals)

    def test_stuck_skipped_with_recent_progress(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        })
        make_runs(proot, [("impl-spec-a-1780000000", "running")])  # 最近有 run 活动
        signals = mon.run_once()
        assert all(s["signal_type"] != "stuck" for s in signals)

    def test_merge_streak(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "ready", "updated": utcnow_iso(), "_merge_streak": 3},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},  # 触发检测前置条件
        })
        signals = mon.run_once()
        assert any(s["signal_type"] == "merge_streak" for s in signals)

    def test_blocked_stuck(self, tmp_path):
        """blocked 超时未处理 → 唤起 admin（fix-admin-self-heal）。

        显式钉冷却 15 分钟：阈值=max(cooldown,15) 与全局默认解耦（默认现为 60），
        夹具 40 分钟前的 blocked 只对钉值有意义。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(40)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},  # 触发检测前置条件
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        signals = mon.run_once()
        assert any(s["signal_type"] == "blocked_stuck" for s in signals)

    def test_blocked_recent_not_detected(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": utcnow_iso()},  # 刚 blocked
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        })
        signals = mon.run_once()
        assert all(s["signal_type"] != "blocked_stuck" for s in signals)

    def test_blocked_frozen_not_detected(self, tmp_path):
        """人为冻结（error 前缀 'frozen:'）的 blocked spec 不触发 blocked_stuck。

        冻结是等待家族收敛的有意状态，updated 不推进；真实停滞仍由
        stuck/repeated_failures 等规则覆盖（admin-fix-improve-failover 误报循环）。
        """
        proot, mon = make_monitor(tmp_path, {
            "spec-frozen": {
                "status": "blocked",
                "updated": iso_ago(125),
                "error": "frozen: 与 fix#2（已实现待验证）重复；验证通过后解冻",
            },
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        })
        signals = mon.run_once()
        assert all(s["signal_type"] != "blocked_stuck" for s in signals)

    def test_blocked_user_pause_not_detected(self, tmp_path):
        """用户指令暂停（error 含「用户指令暂停」，未必带 frozen: 前缀）不触发 blocked_stuck。

        人工写入的暂停文案是有意等待态（2026-08-30 v2-acceptance-suite 误报），
        updated 不推进；超时唤起只会形成重复误报。
        """
        proot, mon = make_monitor(tmp_path, {
            "spec-paused": {
                "status": "blocked",
                "updated": iso_ago(125),
                "error": "用户指令暂停：治理类修复 SPEC（1-6 改进项）优先完成后再解冻",
            },
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        })
        signals = mon.run_once()
        assert all(s["signal_type"] != "blocked_stuck" for s in signals)

    def test_blocked_user_freeze_not_detected(self, tmp_path):
        """用户指令冻结（「用户指令冻结：…」，无 frozen: 前缀）不触发 blocked_stuck。

        人工冻结文案用词在暂停/冻结间漂移（2026-08-30 v2-acceptance-suite 二次
        误报：error='用户指令冻结：等 v2-config-page 完成后人工验证再放行'），
        豁免按「用户指令」子串识别，覆盖两种及未来变体。
        """
        proot, mon = make_monitor(tmp_path, {
            "spec-frozen": {
                "status": "blocked",
                "updated": iso_ago(125),
                "error": "用户指令冻结：等 v2-config-page 完成后人工验证再放行",
            },
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        })
        signals = mon.run_once()
        assert all(s["signal_type"] != "blocked_stuck" for s in signals)

    # ── daemon-error-escalation：指纹复现升级新口径（触发矩阵）─────────
    #
    # 原 8 条独立测试共用同一夹具（写日志行 → run_once → 断言触发与否），
    # 审查合并为参数化矩阵。原 test_daemon_errors（两条同指纹 ERROR 中夹 INFO
    # 仍触发的口径回归）与 test_daemon_errors_signal_wording_new_semantics
    # （文案断言）分别与 TestDaemonErrorEscalationTiming::
    # test_next_inspection_produces_critical_signal 的场景/断言重复，已并入该
    # 超集测试（文案+severity 在彼处断言）。

    @pytest.mark.parametrize(
        "log_lines,expect_triggered",
        [
            # 单条错误不触发升级（防抖：单次瞬时不足复现）
            pytest.param([_jline(0.1)], False, id="single-error-not-triggered"),
            # 两条不同错误各 1 次（message 骨架不同）→ 指纹不同、不聚合升级
            pytest.param([_jline(0.4, message="provider timeout"),
                          _jline(0.1, message="merge conflict")],
                         False, id="distinct-errors-not-aggregated"),
            # 同指纹相隔 8 分钟（>5min 上限）→ 孤立抖动不触发
            pytest.param([_jline(8.2), _jline(0.2)], False,
                         id="gap-8min-not-triggered"),
            # 同指纹第 1 次出现在 11 分钟前（超出 10 分钟窗口）、第 2 次当前 → 不触发
            # （窗口滑动自然过期，恢复无需显式清零）
            pytest.param([_jline(11.0), _jline(0.1)], False,
                         id="first-outside-window-not-triggered"),
            # message 内嵌变量（run_id/时间戳）不同但归一化后指纹相同 → 复现成立
            pytest.param([_jline(0.4, message="run 1780000001 failed at 2026-09-05T02:00:00Z"),
                          _jline(0.1, message="run 1780000002 failed at 2026-09-05T02:00:30Z")],
                         True, id="embedded-variables-normalized"),
            # 日志含 traceback 原文等非 JSON 行：不崩溃，该行按 raw 归一化回退参与指纹统计
            pytest.param(["Traceback (most recent call last):",
                          '  File "/app/runner.py", line 42, in run',
                          _jline(0.4), _jline(0.1)],
                         True, id="non-json-line-fallback"),
            # 两条一模一样的非 JSON raw 行 → raw 指纹复现 2 次 → 触发（容错方向）
            pytest.param(['  File "/app/runner.py", line 42, in run',
                          '  File "/app/runner.py", line 42, in run'],
                         True, id="raw-repetition-triggers"),
            # 缺 timestamp 的重复 ERROR → 计同指纹复现 2 次触发（fail-closed 不丢告警）
            pytest.param([_jline(None), _jline(None)], True,
                         id="missing-timestamp-fail-closed"),
        ],
    )
    def test_daemon_errors_trigger_matrix(self, tmp_path, log_lines,
                                          expect_triggered):
        """daemon-error-escalation 新口径触发矩阵。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        log_dir = proot / ".fenix" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "fenixd.log").write_text(
            "".join(l + "\n" for l in log_lines), encoding="utf-8")
        signals = mon.run_once()
        if expect_triggered:
            assert any(s["signal_type"] == "daemon_errors" for s in signals)
        else:
            assert all(s["signal_type"] != "daemon_errors" for s in signals)

    def test_healthy_no_signal(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        make_runs(proot, [("impl-spec-a-1780000000", "running")])
        signals = mon.run_once()
        assert signals == []

    def test_no_in_progress_skips(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "done", "updated": utcnow_iso()},
        })
        make_runs(proot, [("impl-spec-a-1780000001", "error")])
        signals = mon.run_once()
        assert signals == []

    def test_disabled_monitor_no_action(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, config={"admin": {"enabled": False}})
        assert mon.enabled is False
        assert mon.run_once() == []


# ── 4.1 节流 / 冷却 ─────────────────────────────────────

class TestAdminMonitorThrottle:
    @pytest.mark.parametrize(
        "scenario",
        [
            pytest.param("stuck", id="stuck"),
            pytest.param("daemon_errors", id="daemon_errors"),
        ],
    )
    def test_throttle_prevents_repeated_invoke(self, tmp_path, scenario):
        """同信号在冷却窗口内：第二次巡检只记录、不再唤起。

        stuck 与 daemon_errors 升级路径同口径（原 test_daemon_errors_cooldown_no_reinvoke
        并入本矩阵，覆盖升级触发后冷却期内同 signal_type 再次满足升级条件的场景）。
        """
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {
                "status": "implementing",
                "updated": utcnow_iso() if scenario == "daemon_errors" else iso_ago(200),
            },
        }, runner=runner)
        if scenario == "daemon_errors":
            log_dir = proot / ".fenix" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "fenixd.log").write_text(
                json.dumps({"level": "ERROR", "component": "fenixd", "message": "boom"}) + "\n"
                + json.dumps({"level": "ERROR", "component": "fenixd", "message": "boom"}) + "\n",
                encoding="utf-8",
            )
        mon.run_once()
        assert len(runner.calls) == 1
        # 同信号在冷却窗口（15 分钟）内：第二次满足升级条件但节流，仅记录、不再唤起
        mon.run_once()
        assert len(runner.calls) == 1

    def test_unhandled_escalation_suppresses_invoke(self, tmp_path):
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner)
        mon.store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a"})
        mon.run_once()
        assert runner.calls == []

    def test_no_runner_escalates(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=None)
        mon.run_once()
        un = mon.store.unhandled()
        assert len(un) == 1
        assert un[0]["kind"] == ESCALATION
        assert un[0]["recommended_action"]

    def test_disposition_recorded_after_invoke(self, tmp_path):
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner)
        mon.run_once()
        kinds = [r["kind"] for r in mon.store.read_all()]
        assert DISPOSITION in kinds
        disp = next(r for r in mon.store.read_all() if r["kind"] == DISPOSITION)
        assert disp["result"] == "resolved"
        assert disp["admin_run_id"] == "admin-test-1"

    def test_disposition_recorded_with_summary(self, tmp_path):
        """_invoke_administrator 把 disp.summary 透传到 admin_alerts.json 的处置记录。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner)
        mon.run_once()
        disp = next(r for r in mon.store.read_all() if r["kind"] == DISPOSITION)
        assert disp["summary"] == "诊断结论：测试困境；处置时间线：测试处置；结果：已解决。"


# ── admin-signal-consolidation：状态沉淀 + 悬置 ≥2h 强制升级 ──

class TestSignalConsolidation:
    """同 (spec, signal_type) 同 status_hash 状态沉淀；blocked 悬置 ≥2h 强制升级。

    对应 spec/changes/evo-admin-signal-consolidation tasks 1.3 / 2.1 / 2.2 / 2.3。
    """

    def _signal_records(self, mon):
        return [r for r in mon.store.read_all() if r.get("kind") == SIGNAL]

    def _escalation_records(self, mon):
        return [r for r in mon.store.read_all() if r.get("kind") == ESCALATION]

    def test_unchanged_state_single_record_no_reinvoke(self, tmp_path):
        """状态未变且持续多轮巡检：不新增记录、不重复唤起 Administrator
        （重叠验收场景「状态未变且持续多轮巡检、跨越 cooldown 窗口后不重复唤起」）。
        """
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.run_once()
        last_seen_1 = self._signal_records(mon)[0]["last_seen"]
        mon.run_once()
        mon.run_once()
        assert len(runner.calls) == 1                       # 只唤起一次
        records = self._signal_records(mon)
        assert len(records) == 1                            # 只沉淀一条记录
        assert records[0]["status_hash"]
        assert records[0]["last_seen"] >= last_seen_1       # 同状态续报仅刷 last_seen

    def test_state_change_creates_new_record(self, tmp_path):
        """spec 状态（error 字段并入 status_hash）变化 → 新建记录。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.run_once()
        # error 变化改变 status_hash（stuck 检测不依赖 error 字段，仍会触发）
        mon.state_machine._specs["spec-a"]["error"] = "changed root cause"
        mon.run_once()
        assert len(runner.calls) == 1                       # 冷却内节流不重唤起
        sig_hashes = {r["status_hash"] for r in self._signal_records(mon)}
        assert len(sig_hashes) == 2                         # 两个不同状态各一条
        assert len(self._signal_records(mon)) == 2

    def test_daemon_spec_none_signal_consolidates_by_fingerprint(self, tmp_path):
        """spec=None daemon 级信号（daemon_errors）按声明口径沉淀：同指纹仅一条
        记录、不重复唤起；不同指纹 → 不同 status_hash → 新记录。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        log_dir = proot / ".fenix" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "fenixd.log"

        def esp(msg):
            return json.dumps({"level": "ERROR", "component": "fenixd",
                               "message": msg}) + "\n"

        log_file.write_text(esp("boom") + esp("boom"), encoding="utf-8")
        mon.run_once()
        log_file.write_text(esp("boom") + esp("boom"), encoding="utf-8")
        mon.run_once()
        records = self._signal_records(mon)
        assert len(records) == 1                            # 同指纹合并为一条
        assert records[0]["spec"] is None
        assert len(runner.calls) == 1                       # 不重复唤起

        # 不同错误指纹 → 新记录（但冷却内不重唤起）
        log_file.write_text(esp("different boom") + esp("different boom"),
                            encoding="utf-8")
        mon.run_once()
        assert len(self._signal_records(mon)) == 2
        assert len(runner.calls) == 1

    def test_9_5h_stalled_replay_two_records_single_invoke(self, tmp_path):
        """add-web-ui 事故重放：blocked 悬置 9.5h 重放 → 信号记录 ≤2 条
        （初次 + 强制升级）、不重复唤起 Administrator、不产生升级风暴。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(9.5 * 60)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        for _ in range(5):                                  # 每分钟巡检 × 5 轮重放
            mon.run_once()
        assert len(runner.calls) == 1                       # Administration 只唤起一次
        assert len(self._signal_records(mon)) == 1          # 信号沉淀为一条（last_seen 续刷）
        escalations = self._escalation_records(mon)
        assert len(escalations) == 1                        # 强制升级恰一条（受未处理约束）
        esc = escalations[0]
        assert esc["severity"] == "critical"
        assert "570" in str(esc.get("evidence"))            # 注明悬置时长（分钟）
        assert esc["signal_type"] == "blocked_stuck"
        # 升级记录注明悬置时长与首次触发时间（evidence 含 updated 与信号首见）
        assert "updated=" in str(esc.get("evidence"))
        assert "信号首见" in str(esc.get("evidence"))

    def test_blocked_under_2h_no_forced_escalation(self, tmp_path):
        """blocked 悬置 <2h：不触发强制升级（仅正常唤起一次）。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(90)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.run_once()
        assert len(runner.calls) == 1
        assert self._escalation_records(mon) == []

    def test_unhandled_escalation_suppresses_forced(self, tmp_path):
        """未处理升级存在时不新增（防升级风暴）。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(600)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.store.append({"kind": ESCALATION, "signal_type": "blocked_stuck",
                          "spec": "spec-a", "severity": "critical"})
        for _ in range(3):
            mon.run_once()
        assert len(runner.calls) == 0                       # 未处理升级压制唤起
        assert len(self._escalation_records(mon)) == 1      # 不新增强制升级

    def test_handled_then_reescalate_when_still_stalled(self, tmp_path):
        """人工 handled 后状态仍悬置且 ≥2h → 可再次升级（每次人工处理后至多一条）。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "blocked", "updated": iso_ago(600)},
            "spec-b": {"status": "implementing", "updated": utcnow_iso()},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.run_once()
        assert len(self._escalation_records(mon)) == 1      # 首轮强制升级
        mon.run_once()                                      # 未处理 → 不新增
        assert len(self._escalation_records(mon)) == 1
        # 人工处理首条升级
        esc_id = self._escalation_records(mon)[0]["id"]
        assert mon.store.mark_handled(esc_id) is True
        mon.run_once()                                      # 仍悬置 ≥2h → 再次升级
        assert len(self._escalation_records(mon)) == 2
        assert len(runner.calls) == 1                       # 始终不重复唤起 Administrator

    def test_non_stalled_signal_no_forced_escalation(self, tmp_path):
        """非悬置类信号（stuck）悬置 >2h 不触发强制升级（范围不外溢）。"""
        runner = FakeRunner()
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(9 * 60)},
        }, runner=runner, config={"admin": {"escalation_cooldown_minutes": 15}})
        mon.run_once()
        mon.run_once()
        # stuck 走正常唤起 + 冷却沉淀路径，绝无强制升级写入口
        assert len(runner.calls) == 1
        assert self._escalation_records(mon) == []
        assert len(self._signal_records(mon)) == 1


class TestEscalationClosedOnFinalDisposition:
    """run 落最终 disposition 后关闭其名下未处理 escalation（孤儿看护误报残留治理）。

    孤儿看护在处置进行中误判 pending 超时会落同 admin_run_id 的 escalation；
    run 正常完成后无人关闭它——dashboard 处置卡片永久显示「需人工决策」，
    与 result=resolved 矛盾，且 unhandled_for 节流会压制该 spec 后续同型告警。
    """

    @staticmethod
    def _preset_orphan_escalation(mon):
        mon.store.append({
            "kind": ESCALATION, "signal_type": "manual-intervention",
            "spec": "spec-a", "severity": "critical",
            "admin_run_id": "admin-test-1",
            "description": "Administrator 处置中断（误报）",
        })

    @staticmethod
    def _escalations(store):
        return [r for r in store.read_all() if r.get("kind") == ESCALATION]

    def test_resolved_disposition_closes_orphan_escalation(self, tmp_path):
        runner = FakeRunner()  # result="resolved"
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=runner)
        self._preset_orphan_escalation(mon)
        mon.run_once()
        esc = self._escalations(mon.store)
        assert len(esc) == 1
        assert esc[0]["handled"] is True
        assert esc[0].get("resolve_note")  # 闭环留痕

    def test_failed_disposition_keeps_escalation_open(self, tmp_path):
        """处置失败（result=failed）保守保留 escalation——人工仍需知情。"""
        class FailedRunner:
            def run_administrator(self, signal):
                return AdminDisposition(
                    run_id="admin-test-1", spec=signal.get("spec"),
                    success=False, problem="", actions_taken="",
                    result="failed", error="cli boom", summary="",
                )

        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=FailedRunner())
        self._preset_orphan_escalation(mon)
        mon.run_once()
        esc = self._escalations(mon.store)
        assert len(esc) == 1
        assert esc[0]["handled"] is False

    def test_escalated_disposition_closes_stale_but_leaves_new(self, tmp_path):
        """admin 主动升级：旧的同 run 误报 escalation 关闭，新裁决告警保持未处理。"""
        class EscalatingRunner:
            def run_administrator(self, signal):
                return AdminDisposition(
                    run_id="admin-test-1", spec=signal.get("spec"),
                    success=True, problem="", actions_taken="无法自主处置",
                    result="escalated", escalate=True,
                    recommended_action="请人工决策", summary="",
                )

        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": iso_ago(200)},
        }, runner=EscalatingRunner())
        self._preset_orphan_escalation(mon)
        mon.run_once()
        esc = self._escalations(mon.store)
        assert len(esc) == 2
        by_desc = {e["description"]: e for e in esc}
        stale = by_desc["Administrator 处置中断（误报）"]
        fresh = next(e for e in esc if e is not stale)
        assert stale["handled"] is True
        assert fresh["handled"] is False  # admin 裁决接棒，需人工决策


# ── run_administrator：处置文件读取 + 陈旧清理 ──────────

class TestRunAdministrator:
    def test_run_administrator_writes_pending_disposition(self, tmp_path):
        """唤起前落 pending disposition，保证 admin 被杀也有记录（fix-admin-self-heal）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(proot, fake_run_claude=fake_run_claude)
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        recs = AdminStore(proot, FakeLogger()).read_all()
        pendings = [r for r in recs if r.get("kind") == DISPOSITION and r.get("status") == "pending"]
        assert len(pendings) == 1
        assert pendings[0]["spec"] == "spec-a"
        assert pendings[0]["admin_run_id"].startswith("admin-spec-a-")

    def test_orphaned_pending_escalates(self, tmp_path):
        """pending disposition 超时无最终结果 → 升级人工（admin 被 kill 场景）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        # 把 created 改成 20 分钟前（超过 cooldown 15m）
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1
        assert "处置中断" in esc[0]["description"]

    def test_orphaned_pending_with_interrupted_marker_resolved_no_escalation(self, tmp_path):
        """run 含 interrupted 标记 + pending 超时 → 终结且不升级人工（已知 daemon 中断）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")

        # 写入含 interrupted 标记的 run 文件（agent_runner 关闭时写入）
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "runs" / "admin-spec-a-1.jsonl").write_text(
            json.dumps({"type": "assistant", "message": {"content": []}}) + "\n"
            + json.dumps({"type": "interrupted", "reason": "daemon shutdown",
                          "by": "agent_runner"}) + "\n",
            encoding="utf-8",
        )

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 0  # 不升级人工
        # 应追加 interrupted 终结记录
        assert any(r.get("admin_run_id") == "admin-spec-a-1"
                   and (r.get("status") or r.get("result")) == "interrupted"
                   for r in recs)

    def test_orphaned_pending_without_marker_escalates(self, tmp_path):
        """run 无 interrupted 标记（文件缺失）→ 维持升级兜底。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-2",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        # 不写 run 文件 → 无证据 → 升级兜底

        mon._recover_orphaned_dispositions()

        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1  # 升级人工
        # 升级同时追加终结记录（防循环告警）
        assert any(r.get("admin_run_id") == "admin-spec-a-2"
                   and (r.get("status") or r.get("result")) == "escalated"
                   for r in recs)

    def test_orphaned_pending_marker_preempts_re_escalation(self, tmp_path):
        """interrupted 终结后下轮巡检不再处理（终结即 final，去重）。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-3",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
        (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "runs" / "admin-spec-a-3.jsonl").write_text(
            json.dumps({"type": "interrupted", "reason": "daemon shutdown",
                        "by": "agent_runner"}) + "\n",
            encoding="utf-8",
        )

        mon._recover_orphaned_dispositions()  # 第一次：终结不升级
        mon._recover_orphaned_dispositions()  # 第二次：已终结，跳过
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 0
        interrupted = [r for r in recs if (r.get("status") or r.get("result")) == "interrupted"]
        assert len(interrupted) == 1  # 终结只发生一次

    def test_pending_with_final_result_not_escalated(self, tmp_path):
        """有最终结果的 pending 不升级。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-x"})
        store.append({"kind": DISPOSITION, "status": "done", "result": "resolved",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-x"})
        mon._recover_orphaned_dispositions()
        recs = store.read_all()
        assert not any(r.get("kind") == ESCALATION for r in recs)

    def test_escalated_orphan_not_re_escalated(self, tmp_path):
        """孤儿升级人工后不再重复升级（升级即终结，避免循环告警）。

        回归：add-hierarchical-config 孤儿 run 因升级不终结 pending，escalation
        被 handled 后每次巡检又生成新升级，导致同一条告警反复出现。
        """
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        store = AdminStore(proot, FakeLogger())
        rec = store.append({
            "kind": DISPOSITION, "status": "pending", "result": "pending",
            "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "admin-spec-a-1",
        })
        alerts = json.loads((proot / ".fenix" / "admin_alerts.json").read_text())
        for r in alerts:
            if r["id"] == rec["id"]:
                r["created"] = iso_ago(20)
        (proot / ".fenix" / "admin_alerts.json").write_text(json.dumps(alerts), encoding="utf-8")

        mon._recover_orphaned_dispositions()
        # 模拟人工已处理该升级（handled 后 unhandled_for 节流失效，循环 bug 触发点）
        esc = [r for r in store.read_all() if r.get("kind") == ESCALATION]
        assert len(esc) == 1
        assert store.mark_handled(esc[0]["id"]) is True
        mon._recover_orphaned_dispositions()  # 再次巡检：不得重复升级
        recs = store.read_all()
        esc = [r for r in recs if r.get("kind") == ESCALATION]
        assert len(esc) == 1  # 升级只发生一次
        # 升级应终结 pending：同 run 存在非 pending 记录
        rid = rec["admin_run_id"]
        assert any(r.get("admin_run_id") == rid and (r.get("status") or r.get("result")) != "pending"
                   for r in recs)

    def test_restart_request_failure_escalates(self, tmp_path):
        """restart_request 过期未清除 → 重启失败 → 升级人工。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        rr = proot / ".fenix" / "restart_request"
        rr.parent.mkdir(parents=True, exist_ok=True)
        rr.write_text("restart", encoding="utf-8")
        os.utime(rr, (time.time() - 60 * 30, time.time() - 60 * 30))  # 30 分钟前
        result = mon._detect_restart_failure(time.time())
        assert result == ["restart_failed"]
        recs = AdminStore(proot, FakeLogger()).read_all()
        assert any(r.get("kind") == ESCALATION and r.get("signal_type") == "restart_failed"
                   for r in recs)

    def test_restart_request_fresh_not_escalated(self, tmp_path):
        """restart_request 刚发出（窗口内）不升级。"""
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        rr = proot / ".fenix" / "restart_request"
        rr.parent.mkdir(parents=True, exist_ok=True)
        rr.write_text("restart", encoding="utf-8")  # mtime = now
        assert mon._detect_restart_failure(time.time()) == []

    def test_clear_stale_disposition(self, tmp_path):
        """清理指定实例的处置文件（按 run 路径参数化，不再用固定文件名）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        disp_path = proot / ".fenix" / "admin_disposition-admin-spec-a-1.json"
        disp_path.write_text(json.dumps({"spec": "old", "result": "stale"}), encoding="utf-8")
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner.logger = FakeLogger()
        runner._clear_admin_disposition(disp_path)
        assert not disp_path.exists()

    def test_run_administrator_reads_disposition(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = make_admin_runner_stub(
            proot,
            # Admin 按提示词注入的实例路径写入（而非旧全局文件）
            fake_run_claude=_fake_admin_writes_payload({
                "spec": "spec-a",
                "problem": "卡死",
                "actions_taken": ["kill", "reset"],
                "result": "resolved",
                "escalate": False,
            }))
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.success is True
        assert disp.actions_taken == "kill\nreset"
        assert disp.result == "resolved"
        assert disp.escalate is False
        assert disp.spec == "spec-a"

    def test_run_administrator_passes_summary(self, tmp_path):
        """admin_disposition 的 summary 透传到 AdminDisposition（叙述总结）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        summary = "根因是工作树状态陈旧；已清理并重新调度；无需人工介入。"
        runner = make_admin_runner_stub(
            proot,
            fake_run_claude=_fake_admin_writes_payload({
                "spec": "spec-a",
                "problem": "卡死",
                "actions_taken": ["clean", "reset"],
                "result": "resolved",
                "escalate": False,
                "summary": summary,
            }))
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.summary == summary

    def test_run_administrator_summary_default_empty(self, tmp_path):
        """旧处置文件无 summary → AdminDisposition.summary 为空字符串（不报错）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = make_admin_runner_stub(
            proot,
            fake_run_claude=_fake_admin_writes_payload({
                "spec": "spec-a", "result": "resolved",
            }))
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.summary == ""

    def test_read_admin_disposition_summary_normalized(self, tmp_path):
        """_read_admin_disposition 把列表/非字符串 summary 归一化为字符串。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        disp_path = proot / ".fenix" / "admin_disposition-admin-spec-a-1.json"
        runner = AgentRunner.__new__(AgentRunner)
        runner.project_root = proot
        runner.logger = FakeLogger()

        # 列表 → 用换行符拼接（每条独立一行，design D5）
        disp_path.write_text(json.dumps({
            "summary": ["诊断：根因是构建缓存损坏", "处置：清理缓存", "结果：恢复"],
        }), encoding="utf-8")
        assert runner._read_admin_disposition(disp_path)["summary"] == "诊断：根因是构建缓存损坏\n处置：清理缓存\n结果：恢复"

        # 缺失 → 空字符串
        disp_path.write_text(json.dumps({"actions_taken": "x"}), encoding="utf-8")
        assert runner._read_admin_disposition(disp_path)["summary"] == ""

        # 非字符串 → str 化
        disp_path.write_text(json.dumps({"summary": 123}), encoding="utf-8")
        assert runner._read_admin_disposition(disp_path)["summary"] == "123"

        # 损坏文件 → 空 dict（调用方兜底）
        disp_path.write_text("not json{", encoding="utf-8")
        assert runner._read_admin_disposition(disp_path) == {}

    def test_run_administrator_failure_falls_back(self, tmp_path):
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        def failing_run_claude(*a, **k):
            raise RuntimeError("claude 崩溃")

        runner = make_admin_runner_stub(proot, fake_run_claude=failing_run_claude)
        disp = runner.run_administrator(
            {"spec": "spec-a", "signal_type": "stuck", "description": "卡死"})
        assert disp.success is False
        assert disp.result == "failed"
        assert "claude 崩溃" in disp.error
        # 失败时无处置文件 → 用信号详情兜底
        assert disp.problem == "卡死"

    def test_run_administrator_injects_provider_env_when_assigned(self, tmp_path):
        """agents.models.administrator 已分配 → --model 用分配模型并注入 provider env（直连）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        captured = {}
        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            captured["model"] = model_override
            captured["env"] = env_overrides
            admin_disposition_path(cwd, run_id).write_text(
                json.dumps({"spec": "spec-a", "result": "resolved"}), encoding="utf-8")
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(
            proot,
            fake_run_claude=fake_run_claude,
            assignment_fn=lambda agent_type: [
                ({"name": "volc", "baseurl": "https://v.com", "apikey": "sk-v"},
                 "deepseek-v4-flash"),
            ] if agent_type == "administrator" else None)
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert captured["model"] == "deepseek-v4-flash"
        assert captured["env"]["ANTHROPIC_BASE_URL"] == "https://v.com"
        assert captured["env"]["ANTHROPIC_API_KEY"] == "sk-v"
        assert captured["env"]["ANTHROPIC_MODEL"] == "deepseek-v4-flash"
        assert "CLAUDE_CONFIG_DIR" in captured["env"]

    def test_run_administrator_legacy_fallback_when_unassigned(self, tmp_path):
        """未分配 administrator → 走 admin.agent_model → 默认网关，不注入 provider env。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        captured = {}
        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            captured["model"] = model_override
            captured["env"] = env_overrides
            admin_disposition_path(cwd, run_id).write_text(
                json.dumps({"spec": "spec-a", "result": "resolved"}), encoding="utf-8")
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(
            proot, fake_run_claude=fake_run_claude, admin_model="claude-opus-4")
        runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert captured["model"] == "claude-opus-4"
        assert "ANTHROPIC_BASE_URL" not in captured["env"]
        assert "ANTHROPIC_API_KEY" not in captured["env"]

    def test_prompt_uses_instance_path_not_legacy(self, tmp_path):
        """提示词写入路径为按 run 注入的实例文件，且 Admin 按提示词写入后 runner
        读到的是自身结果（tasks 1.2 / 5.5）。走真实 prompt_builder。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        prompts = []

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            prompts.append(prompt)
            # 模拟 Admin 按提示词注入的路径写入
            disposition_path_from_prompt(prompt).write_text(json.dumps({
                "spec": "spec-a", "problem": "注入链路", "result": "resolved",
            }), encoding="utf-8")
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(proot, fake_run_claude=fake_run_claude)
        # 本测试特例：恢复真实 prompt_builder（helper 默认桩掉 _build_prompt）
        del runner.__dict__["_prompt_builder_instance"]
        disp = runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})

        assert len(prompts) == 1
        prompt = prompts[0]
        # 中途持久化 + 最终写入两处都指向实例路径；旧全局路径不再出现
        assert prompt.count(".fenix/admin_disposition-") == 2
        assert "admin_disposition.json" not in prompt
        injected = admin_disposition_path(proot, disp.run_id).name
        assert prompt.count(injected) == 2
        # runner 读到的是写入自身实例文件的结果
        assert disp.result == "resolved"
        assert disp.problem == "注入链路"

    def test_instance_file_deleted_after_run(self, tmp_path):
        """run 结束读取自身 disposition 后清理实例文件（tasks 1.3）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            disp_path = admin_disposition_path(cwd, run_id)
            disp_path.write_text(json.dumps({"result": "resolved"}), encoding="utf-8")
            assert disp_path.exists()
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(proot, fake_run_claude=fake_run_claude)
        disp = runner.run_administrator({"spec": "spec-a", "signal_type": "stuck"})
        assert disp.result == "resolved"
        assert not admin_disposition_path(proot, disp.run_id).exists()

    def test_parallel_runs_use_isolated_disposition_files(self, tmp_path):
        """并行多实例：各自实例文件独立读写，互不覆盖（tasks 5.3 / spec 隔离场景）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        seen_paths = []
        started = threading.Barrier(2)
        release = threading.Event()

        def fake_run_claude(prompt, cwd, run_id, model_override, env_overrides, max_turns, spec_name=None, agent_type=None):
            disp_path = admin_disposition_path(cwd, run_id)
            seen_paths.append(disp_path)
            started.wait(timeout=10)          # 两个 run 同时在场
            release.wait(timeout=5)           # 同时保持文件存在，制造互踩窗口
            idx = spec_name.split("-")[-1]
            disp_path.write_text(json.dumps({
                "spec": f"spec-{idx}",
                "problem": f"问题-{idx}",
                "result": "resolved",
            }), encoding="utf-8")
            return "output", 5, "sess", {"input_tokens": 0, "output_tokens": 0,
                                         "cost_usd": 0.0}

        runner = make_admin_runner_stub(proot, fake_run_claude=fake_run_claude)
        results = {}

        def run_once(idx):
            results[idx] = runner.run_administrator(
                {"spec": f"spec-{idx}", "signal_type": "stuck"})

        threads = [threading.Thread(target=run_once, args=(i,)) for i in (1, 2)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        release.set()
        for t in threads:
            t.join(timeout=10)

        assert len(seen_paths) == 2
        # 实例文件互不相同（按 run_id 分离）
        assert seen_paths[0] != seen_paths[1]
        # 各实例读到的是自己的结果（spec 兜底用信号 spec，problem 用自身文件内容）
        assert results[1].problem == "问题-1"
        assert results[2].problem == "问题-2"
        # 两个实例文件都已清理
        assert all(not p.exists() for p in seen_paths)


# ── 4.3 Dashboard alerts API ────────────────────────────

class _AlertTestServer:
    def __init__(self, reg, static_dir):
        self.port = find_free_port(30000)
        self.httpd = DashboardHTTPServer(("127.0.0.1", self.port), reg, static_dir)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def post(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("POST", path)
            resp = conn.getresponse()
            body = resp.read()
            return resp.status, json.loads(body)
        finally:
            conn.close()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def alerts_fx(tmp_path):
    proot = tmp_path / "proj-alerts"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    store = AdminStore(proot, FakeLogger())
    store.append({"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a",
                  "severity": "critical", "description": "卡死"})
    store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "spec-a",
                  "description": "已处置"})
    store.append({"kind": ESCALATION, "signal_type": "flapping", "spec": "spec-b",
                  "severity": "major", "description": "抖动"})
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787,
              "projects": [{"name": "proj-alerts", "path": str(proot)}],
              # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, store, srv
    srv.stop()


@pytest.fixture()
def activities_fx(tmp_path):
    """运维记录 API 测试数据：排序/置顶/缺 summary 降级。"""
    proot = tmp_path / "proj-act"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
    store = AdminStore(proot, FakeLogger())
    # 旧记录：无 summary（降级测试），时间最早
    store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "spec-old",
                  "action_taken": "清理缓存", "result": "resolved", "escalate": False,
                  "created": iso_ago(60)})
    # 新记录：有 summary，时间最晚
    store.append({"kind": DISPOSITION, "signal_type": "flapping", "spec": "spec-new",
                  "action_taken": "重置状态", "result": "resolved", "escalate": False,
                  "summary": "诊断结论：状态机空转；处置：重置；结果：恢复。",
                  "created": iso_ago(10)})
    # 升级关联：disposition escalate + 未处理 escalation 同 admin_run_id（应置顶）
    store.append({"kind": DISPOSITION, "signal_type": "merge_streak", "spec": "spec-esc",
                  "action_taken": "尝试清理", "result": "escalated", "escalate": True,
                  "summary": "诊断结论：merge 冲突无法自动解决；需人工决策。",
                  "admin_run_id": "admin-spec-esc-1", "created": iso_ago(30)})
    esc = store.append({"kind": ESCALATION, "signal_type": "merge_streak", "spec": "spec-esc",
                        "severity": "critical", "admin_run_id": "admin-spec-esc-1",
                        "created": iso_ago(29)})
    cfg = tmp_path / "dashboard.yaml"
    reg = Registry(config_path=cfg)
    reg.save({"port": 8787,
              "projects": [{"name": "proj-act", "path": str(proot)}],
              # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
              "scan_dirs": [str(tmp_path / "scan-empty")]})
    srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
    yield proot, store, srv
    srv.stop()


class TestDashboardAlertsAPI:
    def test_api_alerts_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts?project=proj-alerts")
        assert status == 200
        assert data["project"] == "proj-alerts"
        assert len(data["alerts"]) == 3
        assert data["summary"]["unhandled_count"] == 2
        assert data["summary"]["max_severity"] == "critical"

    def test_api_alerts_aggregated(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts")
        assert status == 200
        assert data["total_unhandled"] == 2
        assert len(data["alerts"]) == 2
        assert all("project" in a for a in data["alerts"])
        assert any(a["project"] == "proj-alerts" for a in data["alerts"])

    def test_api_alerts_mark_handled(self, alerts_fx):
        proot, store, srv = alerts_fx
        esc = store.unhandled()[0]
        status, data = srv.post(f"/api/alerts/{esc['id']}/handled?project=proj-alerts")
        assert status == 200
        assert data["ok"] is True
        _, d2 = srv.get("/api/alerts?project=proj-alerts")
        assert d2["summary"]["unhandled_count"] == 1
        assert d2["summary"]["latest"]["handled"] is False  # 剩的那条仍未处理

    def test_api_alerts_mark_handled_unknown(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, _ = srv.post("/api/alerts/nonexistent-id/handled?project=proj-alerts")
        assert status == 404

    def test_api_alerts_mark_handled_unknown_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, _ = srv.post("/api/alerts/abc/handled?project=nope")
        assert status == 400

    def test_api_alerts_unknown_project(self, alerts_fx):
        proot, store, srv = alerts_fx
        status, data = srv.get("/api/alerts?project=nope")
        assert status == 200
        assert "error" in data

    def test_api_alerts_clear_all(self, tmp_path):
        """跨项目一次性清理：POST /api/alerts/clear 标记所有未处理告警。"""
        proot1 = tmp_path / "proj-clear-1"
        proot2 = tmp_path / "proj-clear-2"
        for p in (proot1, proot2):
            (p / ".fenix").mkdir(parents=True, exist_ok=True)
            (p / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        AdminStore(proot1, FakeLogger()).append(
            {"kind": ESCALATION, "signal_type": "stuck", "spec": "spec-a",
             "severity": "critical"})
        AdminStore(proot2, FakeLogger()).append(
            {"kind": ESCALATION, "signal_type": "flapping", "spec": "spec-b"})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-clear-1", "path": str(proot1)},
                               {"name": "proj-clear-2", "path": str(proot2)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            _, before = srv.get("/api/alerts")
            assert before["total_unhandled"] == 2
            status, data = srv.post("/api/alerts/clear")
            assert status == 200
            assert data["cleared"] == 2
            _, after = srv.get("/api/alerts")
            assert after["total_unhandled"] == 0
            _, per_proj = srv.get("/api/alerts?project=proj-clear-1")
            assert per_proj["summary"]["unhandled_count"] == 0
        finally:
            srv.stop()


# ── 4.2 /api/admin-activities（运维记录 API） ───────────

class TestDashboardAdminActivitiesAPI:
    def test_admin_activities_only_dispositions(self, activities_fx):
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        assert len(data["activities"]) == 3  # 只有 disposition，不含 escalation
        assert all("actions_taken" in a and "result" in a for a in data["activities"])

    def test_admin_activities_unhandled_pinned(self, activities_fx):
        """未处理升级关联的处置置顶并标记 handled=False + escalation_id。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        acts = data["activities"]
        assert acts[0]["spec"] == "spec-esc"           # 关联未处理升级 → 置顶
        assert acts[0]["handled"] is False
        assert acts[0]["escalation_id"] is not None
        assert acts[0]["escalate"] is True
        # 其余按时间倒序且 handled=True
        rest = acts[1:]
        assert all(a["handled"] is True for a in rest)
        assert [a["spec"] for a in rest] == ["spec-new", "spec-old"]

    def test_admin_activities_sorted_desc(self, tmp_path):
        """无升级干扰时按时间倒序。"""
        proot = tmp_path / "proj-sort"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        store = AdminStore(proot, FakeLogger())
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "oldest",
                      "created": iso_ago(60)})
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "middle",
                      "created": iso_ago(30)})
        store.append({"kind": DISPOSITION, "signal_type": "stuck", "spec": "newest",
                      "created": iso_ago(10)})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-sort", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-sort")
            assert status == 200
            assert [a["spec"] for a in data["activities"]] == ["newest", "middle", "oldest"]
        finally:
            srv.stop()

    def test_admin_activities_missing_summary_degrade(self, activities_fx):
        """旧记录无 summary 时正常返回，结构化字段齐全（界面降级依据）。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=proj-act")
        assert status == 200
        old = next(a for a in data["activities"] if a["spec"] == "spec-old")
        assert not old.get("summary")
        # action_taken 归一化为 actions_taken
        assert old["actions_taken"] == "清理缓存"
        assert old["result"] == "resolved"

    def test_admin_activities_pending_dedup(self, tmp_path):
        """同 admin_run_id 的 pending + 最终记录归并：只显示最终，不出现"永久处置中"。"""
        proot = tmp_path / "proj-dedup"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        store = AdminStore(proot, FakeLogger())
        # run A：pending + 最终 → 只显示最终
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "run-a",
                      "created": iso_ago(30)})
        store.append({"kind": DISPOSITION, "status": None, "result": "resolved",
                      "signal_type": "stuck", "spec": "spec-a", "admin_run_id": "run-a",
                      "actions_taken": "已处置", "created": iso_ago(10)})
        # run B：只有 pending（admin 仍在处置/被中断）→ 显示处置中
        store.append({"kind": DISPOSITION, "status": "pending", "result": "pending",
                      "signal_type": "flapping", "spec": "spec-b", "admin_run_id": "run-b",
                      "created": iso_ago(5)})
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-dedup", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-dedup")
            assert status == 200
            acts = data["activities"]
            specs = [a["spec"] for a in acts]
            assert "spec-a" in specs and specs.count("spec-a") == 1  # 归并后只有一条
            a_run = next(a for a in acts if a["spec"] == "spec-a")
            assert a_run["result"] == "resolved"                      # 以最终为准
            assert a_run.get("status") != "pending"
            b_run = next(a for a in acts if a["spec"] == "spec-b")
            assert b_run["result"] == "pending"                       # 无最终 → 显示处置中
        finally:
            srv.stop()

    def test_admin_activities_empty_list(self, tmp_path):
        """无任何记录 → 空列表且不报错。"""
        proot = tmp_path / "proj-empty"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "STATE.md").write_text("# State\n\n## Specs\n\n", encoding="utf-8")
        cfg = tmp_path / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787,
                  "projects": [{"name": "proj-empty", "path": str(proot)}],
                  # 指向不存在目录的 scan_dirs：避免空列表触发默认扫描真实主目录 ~ 混入
                  "scan_dirs": [str(tmp_path / "scan-empty")]})
        srv = _AlertTestServer(reg, Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static")
        try:
            status, data = srv.get("/api/admin-activities?project=proj-empty")
            assert status == 200
            assert data["activities"] == []
        finally:
            srv.stop()

    def test_admin_activities_aggregated_by_project(self, activities_fx):
        """缺省 project → 跨项目聚合，按项目分组。"""
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities")
        assert status == 200
        groups = {g["name"]: g for g in data["projects"]}
        assert "proj-act" in groups
        assert len(groups["proj-act"]["activities"]) == 3
        assert all(a["project"] == "proj-act" for a in groups["proj-act"]["activities"])

    def test_admin_activities_unknown_project(self, activities_fx):
        proot, store, srv = activities_fx
        status, data = srv.get("/api/admin-activities?project=nope")
        assert status == 200
        assert "error" in data


# ── 手动唤起 Admin：daemon 主循环拾取（add-spec-manual-admin-invoke 2.2；
#    fix-admin-run-blocks-mainloop：拾取后投递后台 worker 池） ──────────────

import fenixd as _fenixd_mod


class _FakeDaemon(_fenixd_mod.FenixDaemon):
    """FenixDaemon 子类替身：仅装配主循环拾取路径所需属性。

    复用真实 __init__（只置空属性，不加载 config / event_bus / pm_engine），
    再注入 agent_runner、admin_monitor、admin_store、logger 与 worker 池字段。
    _check_admin_invoke_requests 只读模块全局 PROJECT_ROOT（测试中 monkeypatch）、
    上述实例属性；admin_monitor 默认 None 走 agent_runner 直调回退分支。
    """

    def __init__(self, project_root: Path, logger, runner, store,
                 admin_monitor=None, executor=None):
        super().__init__()
        self.running = True
        self.agent_runner = runner
        self.admin_monitor = admin_monitor
        self.admin_store = store
        self.logger = logger
        self._admin_executor = executor
        self._project_root = project_root


class TestAdminInvokePickup:
    @staticmethod
    def _write_request(proot: Path, spec="myspec"):
        req_path = proot / ".fenix" / "admin_invoke_request.json"
        req_path.write_text(
            json.dumps({"spec": spec, "source": "manual",
                        "created": utcnow_iso()}), encoding="utf-8")
        return req_path

    @staticmethod
    def _pickup(monkeypatch, proot: Path, daemon):
        """monkeypatch 模块全局 PROJECT_ROOT 后执行一次主循环拾取。"""
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        daemon._check_admin_invoke_requests()

    def test_pickup_invokes_administrator_and_deletes_file(self, tmp_path, monkeypatch):
        """请求文件存在 → 唤起 manual-intervention 信号并删除文件（同步回退路径）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = FakeRunner()
        store = AdminStore(proot, FakeLogger())
        # executor=None → admin.workers:0 的同步回退行为
        daemon = _FakeDaemon(proot, FakeLogger(), runner, store)
        req_path = self._write_request(proot)
        self._pickup(monkeypatch, proot, daemon)

        # 文件被消费删除
        assert not req_path.exists()
        # 唤起信号正确
        assert len(runner.calls) == 1
        sig = runner.calls[0]
        assert sig["signal_type"] == "manual-intervention"
        assert sig["spec"] == "myspec"
        assert sig["severity"] == "major"
        assert "检查 SPEC myspec 出现什么问题" in sig["description"]
        # 无失败 disposition 落盘
        assert store.read_all() == []

    def test_pickup_routes_through_admin_monitor(self, tmp_path, monkeypatch):
        """装配了 admin_monitor → 走 invoke_manual（复用 _invoke_administrator 落最终
        disposition），不再直调 run_administrator（fix-manual-admin-disposition-finalize）。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)

        class _FakeMonitor:
            def __init__(self):
                self.signals = []

            def invoke_manual(self, signal):
                self.signals.append(signal)

        monitor = _FakeMonitor()
        runner = FakeRunner()
        store = AdminStore(proot, FakeLogger())
        daemon = _FakeDaemon(proot, FakeLogger(), runner, store,
                             admin_monitor=monitor)
        req_path = self._write_request(proot)
        self._pickup(monkeypatch, proot, daemon)

        assert not req_path.exists()
        # 走 AdminMonitor 入口，信号原样透传
        assert len(monitor.signals) == 1
        assert monitor.signals[0]["spec"] == "myspec"
        assert monitor.signals[0]["signal_type"] == "manual-intervention"
        # 不再直调 agent_runner
        assert runner.calls == []
        assert store.read_all() == []

    def test_pickup_without_file_is_noop(self, tmp_path, monkeypatch):
        """无请求文件 → 不唤起、不报错。"""
        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = FakeRunner()
        store = AdminStore(proot, FakeLogger())
        daemon = _FakeDaemon(proot, FakeLogger(), runner, store)
        self._pickup(monkeypatch, proot, daemon)
        assert runner.calls == []

    def test_pickup_exception_records_failed_disposition(self, tmp_path, monkeypatch):
        """唤起异常 → 不丢痕：写 failed disposition 且文件已删（同步回退路径）。"""

        class _BoomRunner:
            def run_administrator(self, signal):
                raise RuntimeError("claude 未授权")

        proot = tmp_path / "proj"
        proot.mkdir(parents=True, exist_ok=True)
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _BoomRunner()
        store = AdminStore(proot, FakeLogger())
        daemon = _FakeDaemon(proot, FakeLogger(), runner, store)
        req_path = self._write_request(proot)
        self._pickup(monkeypatch, proot, daemon)

        assert not req_path.exists()
        records = store.read_all()
        assert len(records) == 1
        assert records[0]["kind"] == DISPOSITION
        assert records[0]["status"] == "failed"
        assert records[0]["spec"] == "myspec"
        assert "claude 未授权" in records[0]["description"]


class _EventRunner:
    """记录唤起信号并在处置开始/结束时设置事件（worker 池异步行为验证）。

    gate：置为 Event 时处置挂起等待放行——用于证明拾取在处置运行期间已返回
    （主循环不被阻塞）。
    """

    def __init__(self, fail_specs=()):
        self.calls = []
        self.signals = []
        self.fail_specs = set(fail_specs)
        self.started = threading.Event()
        self.done = threading.Event()
        self.barrier = None  # 可选：多请求并行在场同步
        self.gate = None     # 可选：处置挂起（模拟数分钟运行）

    def run_administrator(self, signal):
        self.calls.append(signal)
        self.signals.append(signal)
        self.started.set()
        if self.barrier is not None:
            self.barrier.wait(timeout=5)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if signal.get("spec") in self.fail_specs:
            raise RuntimeError(f"处置失败：{signal.get('spec')}")
        self.done.set()
        return AdminDisposition(run_id=f"admin-{signal.get('spec')}-1",
                                spec=signal.get("spec"), success=True,
                                result="resolved")


class TestAdminRunWorkerPool:
    """fix-admin-run-blocks-mainloop：拾取后投递 worker 池，主循环不再被处置阻塞。"""

    def _make_daemon(self, proot, runner, workers=2, admin_monitor=None):
        store = AdminStore(proot, FakeLogger())
        executor = (ThreadPoolExecutor(max_workers=workers,
                                       thread_name_prefix="fenixd-admin-run-test")
                    if workers else None)
        daemon = _FakeDaemon(proot, FakeLogger(), runner, store,
                             admin_monitor=admin_monitor, executor=executor)
        return daemon, store

    def test_pickup_submits_to_pool_without_blocking(self, tmp_path, monkeypatch):
        """拾取即投递：处置仍在后台运行时拾取已返回（tasks 3.1 / spec 不停摆场景）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        runner.gate = threading.Event()  # 处置保持「运行中」
        daemon, store = self._make_daemon(proot, runner)
        req_path = TestAdminInvokePickup._write_request(proot)

        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)

        # 拾取周期内：请求文件已消费、已计入提交
        assert not req_path.exists()
        assert daemon._admin_pool_stats["submitted"] == 1
        wait_for_event(runner.started)
        assert runner.calls[0]["spec"] == "myspec"
        # 处置仍在后台运行 → 拾取未被其阻塞
        assert not runner.done.is_set()

        runner.gate.set()
        wait_for_event(runner.done)
        assert daemon._admin_pool_stats["completed"] == 1
        daemon._admin_executor.shutdown(wait=True)

    def test_pickup_timeliness_within_one_cycle(self, tmp_path, monkeypatch):
        """拾取及时性：写入请求文件后一次拾取即完成投递（≤1 个扫描周期）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        daemon, _ = self._make_daemon(proot, runner)
        TestAdminInvokePickup._write_request(proot)

        t0 = time.monotonic()
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)
        elapsed = time.monotonic() - t0

        # 单次拾取（≈1 个扫描周期）内完成投递，远小于处置运行时长
        assert elapsed < 1.0
        assert daemon._admin_pool_stats["submitted"] == 1
        daemon._admin_executor.shutdown(wait=True)

    def test_parallel_requests_run_concurrently(self, tmp_path, monkeypatch):
        """连续两次 invoke：两个 run 并行执行、互不覆盖（tasks 5.3）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        runner.barrier = threading.Barrier(2)  # 两个处置必须同时在场
        daemon, store = self._make_daemon(proot, runner, workers=2)

        TestAdminInvokePickup._write_request(proot, "spec-a")
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)
        # 第二次呼叫（第一个处置仍在后台执行）
        wait_for_event(runner.started)
        TestAdminInvokePickup._write_request(proot, "spec-b")
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)

        deadline = time.time() + 5
        while len(runner.signals) < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert {s["spec"] for s in runner.signals} == {"spec-a", "spec-b"}
        assert daemon._admin_pool_stats["submitted"] == 2

        deadline = time.time() + 5
        while daemon._admin_pool_stats["completed"] < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert daemon._admin_pool_stats["completed"] == 2
        daemon._admin_executor.shutdown(wait=True)

    def test_worker_survives_failure_and_processes_next(self, tmp_path, monkeypatch):
        """处置异常 → failed disposition 不丢痕，worker 存活并处理后续请求
        （tasks 4.2 / spec「后台处置失败不丢痕」）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner(fail_specs={"spec-a"})
        daemon, store = self._make_daemon(proot, runner, workers=1)

        TestAdminInvokePickup._write_request(proot, "spec-a")
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)
        deadline = time.time() + 5
        while daemon._admin_pool_stats["failed"] < 1 and time.time() < deadline:
            time.sleep(0.02)

        records = store.read_all()
        assert len(records) == 1
        assert records[0]["kind"] == DISPOSITION
        assert records[0]["status"] == "failed"
        assert records[0]["spec"] == "spec-a"
        assert "处置失败" in records[0]["description"]

        # 同一 worker 继续领取后续任务
        TestAdminInvokePickup._write_request(proot, "spec-b")
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)
        deadline = time.time() + 5
        while daemon._admin_pool_stats["completed"] < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert daemon._admin_pool_stats["completed"] == 1
        assert [s["spec"] for s in runner.signals] == ["spec-a", "spec-b"]
        daemon._admin_executor.shutdown(wait=True)

    def test_submit_rejection_records_failed_disposition(self, tmp_path, monkeypatch):
        """executor 已关闭（提交被拒）→ 落 failed disposition 不丢痕（tasks 2.2）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        daemon, store = self._make_daemon(proot, runner)

        class _ClosedExecutor:
            def submit(self, *a, **k):
                raise RuntimeError("cannot schedule new futures after shutdown")

        daemon._admin_executor = _ClosedExecutor()
        ok = daemon._submit_admin_run({"spec": "spec-a", "signal_type": "manual-intervention"})

        assert ok is False
        records = store.read_all()
        assert len(records) == 1
        assert records[0]["status"] == "failed"
        assert "拒绝" in records[0]["description"]
        assert runner.calls == []

    def test_shutdown_cancels_queued_without_waiting(self, tmp_path, monkeypatch):
        """daemon shutdown → executor 优雅关闭（不等待在途处置，tasks 2.3）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        daemon, _ = self._make_daemon(proot, runner)
        executor = daemon._admin_executor

        TestAdminInvokePickup._write_request(proot, "spec-a")
        TestAdminInvokePickup._pickup(monkeypatch, proot, daemon)
        wait_for_event(runner.started)

        # 其余组件未装配（None）→ shutdown 只关停 worker 池即退出
        daemon.agent_runner = None
        with pytest.raises(SystemExit):
            daemon.shutdown()

        assert daemon.running is False
        # executor 已进入关闭状态：后续提交被拒
        with pytest.raises(RuntimeError):
            executor.submit(lambda: None)

    def test_sweep_stale_disposition_files(self, tmp_path, monkeypatch):
        """拾取新请求时清理超过 24h 的残留实例文件，新鲜文件与在途文件保留（tasks 1.3）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        daemon, _ = self._make_daemon(proot, runner)
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)

        fenix_dir = proot / ".fenix"
        stale = fenix_dir / "admin_disposition-admin-old-1.json"
        fresh = fenix_dir / "admin_disposition-admin-new-1.json"
        legacy = fenix_dir / "admin_disposition.json"   # 旧全局路径：存在即清理
        stale.write_text("{}", encoding="utf-8")
        fresh.write_text("{}", encoding="utf-8")
        legacy.write_text("{}", encoding="utf-8")
        old_ts = time.time() - 25 * 3600
        os.utime(stale, (old_ts, old_ts))
        os.utime(legacy, (old_ts, old_ts))

        daemon._sweep_stale_admin_dispositions()

        assert not stale.exists()
        assert not legacy.exists()
        assert fresh.exists()  # 未超时 → 保留

    def test_sweep_noop_when_no_files(self, tmp_path, monkeypatch):
        """无残留文件 → 清扫零操作不报错。"""
        proot = tmp_path / "proj"
        (proot / ".fenix").mkdir(parents=True, exist_ok=True)
        runner = _EventRunner()
        daemon, _ = self._make_daemon(proot, runner)
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        daemon._sweep_stale_admin_dispositions()  # 不抛异常即通过


# ── improve-hot-reload-robustness：代码陈旧检测（tasks 2.2 / D4） ──

class _RecordingLogger:
    """记录告警条目的最小 logger（陈旧检测 WARNING 断言用）。"""

    def __init__(self):
        self.warnings = []
        self.errors = []
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        self.infos.append(a)

    def warning(self, *a, **k):
        self.warnings.append(a)

    def error(self, *a, **k):
        self.errors.append(a)


def _mk_code_proj(tmp_path) -> tuple:
    """构造含 fenixd.py + core/**/*.py 的临时项目，返回 (proot, files, baseline)。"""
    proot = tmp_path / "proj"
    (proot / "core").mkdir(parents=True)
    (proot / "fenixd.py").write_text("# fenixd\n", encoding="utf-8")
    (proot / "core" / "a.py").write_text("# a\n", encoding="utf-8")
    (proot / "core" / "b.py").write_text("# b\n", encoding="utf-8")
    files = _fenixd_mod.code_tracked_files(proot)
    baseline = _fenixd_mod.max_code_mtime_ns(files)
    return proot, files, baseline


class TestCodeStalenessDetection:
    def test_no_change_false(self, tmp_path):
        """所有受跟踪文件 mtime 均未超 baseline → False（无陈旧告警）。"""
        proot, files, baseline = _mk_code_proj(tmp_path)
        assert baseline > 0
        assert len(files) == 3  # fenixd.py + core/a.py + core/b.py
        assert _fenixd_mod.code_files_changed_since(baseline, files) is False

    def test_core_update_true(self, tmp_path):
        """core/ 下代码文件更新 → True。"""
        proot, files, baseline = _mk_code_proj(tmp_path)
        os.utime(proot / "core" / "a.py", ns=(baseline + 5 * 10 ** 9, baseline + 5 * 10 ** 9))
        assert _fenixd_mod.code_files_changed_since(baseline, files) is True

    def test_fenixd_update_true(self, tmp_path):
        """fenixd.py 更新也算。"""
        proot, files, baseline = _mk_code_proj(tmp_path)
        os.utime(proot / "fenixd.py", ns=(baseline + 5 * 10 ** 9, baseline + 5 * 10 ** 9))
        assert _fenixd_mod.code_files_changed_since(baseline, files) is True

    def test_missing_file_ignored(self, tmp_path):
        """文件缺失忽略：baseline 后新增/删除文件不误报。"""
        proot, files, baseline = _mk_code_proj(tmp_path)
        missing = list(files) + [proot / "core" / "never-existed.py"]
        assert _fenixd_mod.code_files_changed_since(baseline, missing) is False
        # 删除一个受跟踪文件后再检测
        (proot / "core" / "b.py").unlink()
        assert _fenixd_mod.code_files_changed_since(baseline, files) is False

    def test_warn_stale_once_emits_and_dedups(self, tmp_path):
        """_update_stale_code_state：更新后提示一次 WARNING，持续为真期间不重复。

        add-stale-code-selfheal 1.1/1.2：一次性旗标升级为持续状态——状态由假转真
        落一次 WARNING（告警写入在此测试中跳过：admin_store=None），状态保持为真
        期间不重复刷日志。
        """
        proot, files, baseline = _mk_code_proj(tmp_path)
        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon._code_files = files
        daemon._code_baseline_ns = baseline
        daemon._code_stale = False
        daemon.admin_store = None
        daemon.logger = _RecordingLogger()
        # 无变更 → 状态为假、不提示
        daemon._update_stale_code_state()
        assert daemon._code_stale is False
        assert daemon.logger.warnings == []
        # core 文件更新 → 状态转真、提示一次
        os.utime(proot / "core" / "a.py", ns=(baseline + 5 * 10 ** 9, baseline + 5 * 10 ** 9))
        daemon._update_stale_code_state()
        assert daemon._code_stale is True
        assert len(daemon.logger.warnings) == 1
        assert "建议重启" in daemon.logger.warnings[0][1]
        # 持续为真期间再次调用 → 不重复刷 WARNING
        daemon._update_stale_code_state()
        daemon._update_stale_code_state()
        assert len(daemon.logger.warnings) == 1


# ── improve-hot-reload-robustness：任务 5 验证（事故场景模拟 + 升级时序） ──

class TestAccidentScenarioSimulation:
    """任务 5.2：旧白名单进程语义 + 含新键配置 → 热重载成功、单次降级告警、
    无 30s 告警刷屏、陈旧检测 WARNING 出现。"""

    def test_old_whitelist_hot_reload_unknown_key(self, tmp_path, monkeypatch):
        from core.config import ConfigLoader as _CL
        import logging as _logging
        proot = tmp_path / "proj"
        (proot / ".fenix" / "logs").mkdir(parents=True)
        (proot / "core").mkdir(parents=True)
        (proot / "fenixd.py").write_text("# fenixd\n", encoding="utf-8")
        (proot / "core" / "config.py").write_text("# cfg\n", encoding="utf-8")
        # 配置含未知键 turbo-draft（旧白名单进程）+ 合法 implementer 分配
        (proot / ".fenix" / "config.yaml").write_text(
            "project:\n  name: proj\n"
            "agents:\n  models:\n"
            "    implementer: {provider: volc}\n"
            "    turbo-draft: {provider: volc}\n"
            "llm:\n  providers:\n"
            "    - {name: volc, baseurl: https://v, apikey: k, model: claude-sonnet-5}\n",
            encoding="utf-8",
        )
        user_cfg_dir = tmp_path / "user-fenix"
        user_cfg_dir.mkdir()
        monkeypatch.setattr(_fenixd_mod, "PROJECT_ROOT", proot)
        monkeypatch.setattr("core.config.USER_CONFIG_DIR", user_cfg_dir)

        daemon = _fenixd_mod.FenixDaemon.__new__(_fenixd_mod.FenixDaemon)
        daemon.config = {}
        daemon.logger = _RecordingLogger()
        daemon.admin_monitor = None
        daemon._admin_executor = None
        daemon._config_snapshot = ()  # 空快照 → 首次调用触发重载
        # 代码陈旧检测 baseline：先缓存当前文件 mtime，随后 touch 模拟代码更新
        files = _fenixd_mod.code_tracked_files(proot)
        baseline = _fenixd_mod.max_code_mtime_ns(files)
        daemon._code_files = files
        daemon._code_baseline_ns = baseline
        daemon._code_stale = False
        daemon.admin_store = None
        _CL.reset_stuck_threshold_state()  # 清未知键去重集合，确保首告警可见

        # 配置校验降级告警走 Python logging（fenixd.config logger），挂 handler 捕获
        cfg_logger = _logging.getLogger("fenixd.config")
        cfg_logger.setLevel(_logging.ERROR)
        cfg_records = []
        _handler = _logging.Handler()
        _handler.emit = lambda record: cfg_records.append(record.getMessage())
        cfg_logger.addHandler(_handler)
        try:
            # 第 1 次热重载：未知键不整段拒绝，热重载成功
            daemon._maybe_reload_config()
            assert "turbo-draft" in daemon.config["agents"]["models"]  # 键保留
            assign = _CL.get_agent_model_assignment(daemon.config, "implementer")
            assert len(assign) == 1  # implementer 分配完整生效
            deg = [m for m in cfg_records if "未知 agent 类型键" in m]
            assert len(deg) == 1  # 单次降级告警
            assert daemon.logger.warnings == []  # 代码未更新 → 无陈旧告警

            # 模拟 30s 重试风暴：配置 mtime 变化 + 代码文件更新（对应事故场景
            # dashboard 写盘 → daemon 旧代码热重载）
            os.utime(proot / "core" / "config.py",
                     ns=(baseline + 5 * 10 ** 9, baseline + 5 * 10 ** 9))
            daemon._config_snapshot = ()  # 强制再次触发重载路径
            for _ in range(3):
                daemon._maybe_reload_config()

            # 同一未知键不重复刷屏（去重生效）
            deg2 = [m for m in cfg_records if "未知 agent 类型键" in m]
            assert len(deg2) == 1
            # 陈旧检测 WARNING：状态由假转真边沿出现一次，持续为真期间不重复
            # （add-stale-code-selfheal：一次性旗标 → 持续状态边沿语义）
            stale = [w for w in daemon.logger.warnings if "建议重启" in w[1]]
            assert len(stale) == 1
            daemon._maybe_reload_config()
            assert len(stale) == 1  # 不重复
        finally:
            cfg_logger.removeHandler(_handler)
            _CL.reset_stuck_threshold_state()


class TestDaemonErrorEscalationTiming:
    """任务 5.3：同指纹 ERROR 每 30s 两条 → 下一轮巡检即产生 critical signal
    （模拟巡检周期，不再依赖日志安静度）。"""

    def test_next_inspection_produces_critical_signal(self, tmp_path):
        proot, mon = make_monitor(tmp_path, {
            "spec-a": {"status": "implementing", "updated": utcnow_iso()},
        }, config={"admin": {"escalation_cooldown_minutes": 15}})
        log_dir = proot / ".fenix" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        # 两条同指纹 ERROR 相隔 30s（活跃期被 INFO 打断）→ 升级口径与新错误复现率挂钩
        (log_dir / "fenixd.log").write_text(
            json.dumps({"timestamp": iso_ago(0.5), "level": "ERROR",
                        "component": "fenixd", "message": "boom"}) + "\n"
            + json.dumps({"timestamp": iso_ago(0.4), "level": "INFO",
                          "component": "fenixd", "message": "mid"}) + "\n"
            + json.dumps({"timestamp": iso_ago(0.1), "level": "ERROR",
                          "component": "fenixd", "message": "boom"}) + "\n",
            encoding="utf-8",
        )
        # 下一轮巡检即命中（无需等日志安静）
        signals = mon.run_once()
        sig = next(s for s in signals if s["signal_type"] == "daemon_errors")
        # daemon_errors 是 daemon 全局信号（_make_signal 第二参恒 None），不归属具体 spec
        assert sig["spec"] is None
        assert sig["severity"] == "critical"
        assert "复现 2 次" in sig["description"]
        assert "连续" not in sig["description"]
