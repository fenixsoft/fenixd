"""叙事侧车异步补叙（upgrade-narrative-to-investigation 3.2/3.3/3.4）测试。

覆盖 tasks 5.2：
- 告警先落盘后补叙（发射耗时不含 LLM 时延断言）
- 侧车原子写与读侧合并字段形态（前端零 schema 变更）
- handled 后照常补叙（读侧合并 narrative、无 pending 标记）
- 侧车缺失 pending 标记（未 handled 裁决类告警）
- 清理级联删除（保留上限裁剪触发，删除失败不阻断主流程）

假通道注入，MUST NOT 真调网关；后台补叙线程经 wait_pending_narrative
确定性等待。
"""

import json
import time

import pytest

import core.adjudication_narrative as adj
from core.adjudication_narrative import (
    load_narrative_sidecars,
    reset_breaker,
    reset_channel,
    schedule_narrative,
    set_channel,
    wait_pending_narrative,
    write_narrative_sidecar,
)
from core.admin_store import AdminStore
from core.dashboard.data import admin_alerts

GOOD_TEXT = (
    "## 发生了什么\n现象。\n\n"
    "## 调查结论\n根因（材料内有据）。\n\n"
    "## 为什么需要你决策\n预算到顶。\n\n"
    "## 决策选项\n**ignore（忽略）**：仅供参考，最终由你决定。"
)

CHOICES = [{"id": "ignore", "label": "忽略", "desc": "知情确认", "action": "ignore"}]


class RecordingLogger:
    def __init__(self):
        self.records = []

    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        self.records.append(("warning", a[1] if len(a) > 1 else ""))

    def error(self, *a, **k):
        self.records.append(("error", a[1] if len(a) > 1 else ""))


def make_entry(spec="spec-a", **over):
    entry = {
        "kind": "escalation",
        "signal_type": "token_budget",
        "spec": spec,
        "severity": "major",
        "description": "预算告警",
        "evidence": "ratio=100%",
        "recommended_action": "人工裁决",
        "choices": list(CHOICES),
    }
    entry.update(over)
    return entry


@pytest.fixture(autouse=True)
def _cleanup():
    reset_channel()
    reset_breaker()
    yield
    reset_channel()
    reset_breaker()
    wait_pending_narrative(timeout=10)


# ── 告警先落盘后补叙 ────────────────────────────────────


class TestAlertFirstNarrativeLater:
    def test_emit_latency_excludes_llm(self, tmp_path):
        """告警发射（append + 调度）不含 LLM 时延：慢通道下发射立即返回且
        记录已可读，侧车在后台线程完成后才出现。"""
        llm_seconds = 1.5

        def slow_channel(prompt, model, timeout):
            time.sleep(llm_seconds)
            return GOOD_TEXT

        set_channel(slow_channel)
        store = AdminStore(tmp_path, RecordingLogger())
        ctx = {"config": {}, "logger": RecordingLogger(), "project_root": tmp_path}
        entry = make_entry()
        t0 = time.monotonic()
        rec = store.append(entry)
        schedule_narrative(rec["id"], entry, ctx)
        emit_seconds = time.monotonic() - t0
        # 发射远快于 LLM 时延（零阻塞落盘）
        assert emit_seconds < llm_seconds
        # 记录此刻已可读（机械文案先行）
        assert store.read_all()[0]["id"] == rec["id"]
        # 侧车尚未出现（LLM 仍在跑）
        assert load_narrative_sidecars(tmp_path) == {}
        # 后台完成后侧车出现
        assert wait_pending_narrative(timeout=15)
        assert rec["id"] in load_narrative_sidecars(tmp_path)

    def test_handled_then_narrative_still_lands(self, tmp_path):
        """人工已处置（handled）后补叙照常落盘，处置流程不受影响。"""
        set_channel(lambda p, m, t: GOOD_TEXT)
        store = AdminStore(tmp_path, RecordingLogger())
        ctx = {"config": {}, "logger": RecordingLogger(), "project_root": tmp_path}
        entry = make_entry()
        rec = store.append(entry)
        assert store.mark_handled(rec["id"]) is True
        schedule_narrative(rec["id"], entry, ctx)
        assert wait_pending_narrative(timeout=10)
        assert load_narrative_sidecars(tmp_path)[rec["id"]]["text"] == GOOD_TEXT


# ── 读侧合并与 pending 标记 ─────────────────────────────


class TestReadSideMerge:
    def test_sidecar_merged_field_shape(self, tmp_path):
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())
        write_narrative_sidecar(tmp_path, rec["id"], GOOD_TEXT, "m-nar")
        alerts = admin_alerts.get_alerts(tmp_path)
        item = next(a for a in alerts if a["id"] == rec["id"])
        # 字段形态与既有 {"text","model","at"} 一致——前端零 schema 变更
        assert set(item["narrative"]) == {"text", "model", "at"}
        assert item["narrative"]["text"] == GOOD_TEXT
        assert item["narrative"]["model"] == "m-nar"
        assert "narrative_pending" not in item

    def test_missing_sidecar_pending_marker(self, tmp_path):
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())  # 未 handled、choices 非空、无侧车
        alerts = admin_alerts.get_alerts(tmp_path)
        item = next(a for a in alerts if a["id"] == rec["id"])
        assert item.get("narrative_pending") is True
        # unhandled 读路径同样合并
        un = admin_alerts.get_unhandled_alerts(tmp_path)
        assert un[0].get("narrative_pending") is True

    def test_handled_without_sidecar_no_pending(self, tmp_path):
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())
        store.mark_handled(rec["id"])
        item = admin_alerts.get_alerts(tmp_path)[0]
        assert "narrative_pending" not in item
        assert "narrative" not in item

    def test_no_choices_no_pending(self, tmp_path):
        """桶 0（无 choices）告警不附 pending（本就不生成叙事，防假态）。"""
        store = AdminStore(tmp_path, RecordingLogger())
        store.append(make_entry(choices=None))
        item = admin_alerts.get_alerts(tmp_path)[0]
        assert "narrative_pending" not in item

    def test_legacy_inline_narrative_no_pending(self, tmp_path):
        """存量告警（旧同步实现把 narrative 写进本体）不标 pending。"""
        store = AdminStore(tmp_path, RecordingLogger())
        store.append(make_entry(narrative={"text": GOOD_TEXT, "model": "m", "at": "t"}))
        item = admin_alerts.get_alerts(tmp_path)[0]
        assert item["narrative"]["text"] == GOOD_TEXT
        assert "narrative_pending" not in item

    def test_terminal_sidecar_merged_not_pending(self, tmp_path):
        """终态侧车（失败说明）与补叙侧车同构合并，不出 pending。"""
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())
        write_narrative_sidecar(tmp_path, rec["id"], adj.GENERATION_FAILED_TEXT, None)
        item = admin_alerts.get_alerts(tmp_path)[0]
        assert item["narrative"]["text"] == adj.GENERATION_FAILED_TEXT
        assert item["narrative"]["model"] is None
        assert "narrative_pending" not in item

    def test_resolved_alerts_merge_narrative(self, tmp_path):
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())
        store.mark_handled(rec["id"])
        write_narrative_sidecar(tmp_path, rec["id"], GOOD_TEXT, None)
        resolved = admin_alerts.get_resolved_alerts(tmp_path)
        assert resolved[0]["narrative"]["text"] == GOOD_TEXT

    def test_corrupt_sidecar_fail_open(self, tmp_path):
        d = tmp_path / ".fenix" / adj.SIDECAR_DIRNAME
        d.mkdir(parents=True)
        (d / "broken.json").write_text("{trunc", encoding="utf-8")
        store = AdminStore(tmp_path, RecordingLogger())
        rec = store.append(make_entry())
        alerts = admin_alerts.get_alerts(tmp_path)
        item = next(a for a in alerts if a["id"] == rec["id"])
        # 损坏侧车跳过，告警渲染不受影响（回落 pending 占位）
        assert item.get("narrative_pending") is True


# ── 清理级联删除 ────────────────────────────────────────


class TestCleanupCascade:
    def test_trim_cascades_sidecar_deletion(self, tmp_path, monkeypatch):
        """保留上限裁剪触发时被裁告警的侧车级联删除。"""
        from core import admin_store as store_mod

        monkeypatch.setattr(store_mod, "MAX_RECORDS", 2)
        set_channel(lambda p, m, t: GOOD_TEXT)
        store = AdminStore(tmp_path, RecordingLogger())
        ctx = {"config": {}, "logger": RecordingLogger(), "project_root": tmp_path}
        ids = []
        for i in range(2):
            entry = make_entry(spec=f"spec-{i}")
            rec = store.append(entry)
            ids.append(rec["id"])
            schedule_narrative(rec["id"], entry, ctx)
        assert wait_pending_narrative(timeout=15)
        # 两条侧车都在（未触裁剪）
        assert set(load_narrative_sidecars(tmp_path)) == set(ids)
        # 第 3 条触发裁剪（保留最近 2 条）：最老一条的侧车被级联删除
        store.append(make_entry(spec="spec-2"))
        remaining = set(load_narrative_sidecars(tmp_path))
        assert ids[0] not in remaining
        assert remaining == set(ids[1:])

    def test_cleanup_failure_does_not_block_trim(self, tmp_path, monkeypatch):
        """级联删除失败仅 WARNING，不阻断清理主流程（记录照常裁剪写回）。"""
        from core import admin_store as store_mod

        monkeypatch.setattr(store_mod, "MAX_RECORDS", 2)

        def boom(root, ids):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(adj, "delete_narrative_sidecars", boom)
        logger = RecordingLogger()
        store = AdminStore(tmp_path, logger)
        store.append(make_entry(spec="s0"))
        store.append(make_entry(spec="s1"))
        store.append(make_entry(spec="s2"))  # 触发裁剪，级联删除将抛错
        # 主流程不受影响：活跃文件保留最近 2 条
        assert len(store.read_all()) == 2
        assert logger.records, "删除失败应 WARNING 留痕"

    def test_archived_records_not_required_to_have_sidecars(self, tmp_path, monkeypatch):
        """归档视图不含 narrative 属预期（design D2：侧车只服务活跃告警集）。"""
        from core import admin_store as store_mod

        monkeypatch.setattr(store_mod, "MAX_RECORDS", 2)
        store = AdminStore(tmp_path, RecordingLogger())
        store.append(make_entry(spec="s0"))
        store.append(make_entry(spec="s1"))
        store.append(make_entry(spec="s2"))
        archived = store.read_archive()
        assert len(archived) == 1  # 最老一条归档
        assert "narrative" not in archived[0]


# ── 原子写形态 ──────────────────────────────────────────


class TestAtomicWrite:
    def test_no_temp_files_left_behind(self, tmp_path):
        for i in range(5):
            assert write_narrative_sidecar(tmp_path, f"id-{i}", "正文", None)
        d = tmp_path / ".fenix" / adj.SIDECAR_DIRNAME
        leftovers = [p for p in d.iterdir() if p.suffix != ".json" or p.name.startswith(".")]
        assert leftovers == []
        assert len(list(d.glob("*.json"))) == 5

    def test_sidecar_json_valid_shape_on_disk(self, tmp_path):
        write_narrative_sidecar(tmp_path, "shape1", "文本", "model-x")
        p = tmp_path / ".fenix" / adj.SIDECAR_DIRNAME / "shape1.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data == {
            "alert_id": "shape1",
            "text": "文本",
            "model": "model-x",
            "at": data["at"],
        }
