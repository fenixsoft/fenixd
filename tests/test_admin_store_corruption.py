"""fix-robustness-edge-cases 2.3：AdminStore 告警存储抗损坏。

覆盖 spec「告警存储读损坏不得静默清空历史」五场景：
  - 损坏文件留底：读损坏 → 改名 `.corrupt-<ts>` 保留取证、返回空集合、可观测记录
  - 拒绝清库式写回：损坏留底后的写回被拒，历史文件不被覆盖
  - 损坏后恢复写入：留底已完成 → 新增告警正常写入新文件，不被下限保护误拦
  - 正常追加不受影响：合法文件追加，既有记录保留
  - 合法空集合不被误拦：文件不存在或合法空数组 → 写入正常完成
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.admin_store import AdminStore  # noqa: E402


class _FakeLogger:
    """捕获 AdminStore 观测记录（warning/error）的假 logger。"""

    def __init__(self):
        self.warnings: list = []
        self.errors: list = []

    def warning(self, *args):
        self.warnings.append(args)

    def error(self, *args):
        self.errors.append(args)

    def info(self, *args):
        pass

    def debug(self, *args):
        pass


@pytest.fixture
def store(tmp_path, request=None):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True, exist_ok=True)
    logger = _FakeLogger()
    return AdminStore(proot, logger), logger


def _corrupt(store) -> Path:
    """写一个非法 JSON 的告警文件。"""
    p = store.alerts_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not-valid-json!!!", encoding="utf-8")
    return p


def _corrupt_quarantined_files(store) -> list:
    return [p for p in store.alerts_path.parent.glob("*.corrupt-*")]


# ── 1. 损坏文件留底 ────────────────────────────────────────────────


class TestCorruptQuarantine:
    def test_read_corrupt_quarantines_and_returns_empty(self, store):
        admin_store, logger = store
        p = _corrupt(admin_store)
        assert admin_store.read_all() == []
        # 原文件被改名留底
        quarantined = _corrupt_quarantined_files(admin_store)
        assert len(quarantined) == 1
        assert ".corrupt-" in quarantined[0].name
        assert not p.exists(), "损坏原文件不得残留原位"
        # 可观测记录
        assert any("留底" in str(a) for a in logger.warnings)

    def test_quarantine_preserves_content_for_forensics(self, store):
        admin_store, _logger = store
        p = _corrupt(admin_store)
        admin_store.read_all()
        q = _corrupt_quarantined_files(admin_store)[0]
        assert q.read_text(encoding="utf-8") == "{not-valid-json!!!", "留底文件保留损坏原文（取证）"


# ── 2. 拒绝清库式写回 ──────────────────────────────────────────────


class TestRefuseWriteBack:
    def test_write_after_corrupt_refused(self, store):
        admin_store, logger = store
        _corrupt(admin_store)
        rec = admin_store.append({"kind": "signal", "spec": "s", "signal_type": "x"})
        assert rec.get("id")  # append 返回规范化记录（不承诺本次落盘）
        # 写回被拒绝：留底文件存在，且没有新 admin_alerts.json 覆盖历史
        assert _corrupt_quarantined_files(admin_store), "损坏证据已留底"
        assert not admin_store.alerts_path.exists(), "拒绝写回：不得新建文件覆盖损坏历史"
        assert any("拒绝写回" in str(a) for a in logger.errors), "拒绝写回须有告警记录"

    def test_corrupt_non_list_also_refused(self, store):
        """非数组合法 JSON（如 {..}）同样无法解读 → 留底 + 写回拒绝。"""
        admin_store, logger = store
        admin_store.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        admin_store.alerts_path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
        admin_store.append({"kind": "signal", "spec": "s", "signal_type": "x"})
        assert _corrupt_quarantined_files(admin_store), "非数组内容同样留底"
        assert not admin_store.alerts_path.exists(), "写回被拒"


# ── 3. 损坏后恢复写入（留底后新告警不被下限保护误拦）───────────────


class TestRecoveryWriteAfterQuarantine:
    def test_append_after_quarantine_writes(self, store):
        admin_store, _logger = store
        _corrupt(admin_store)
        admin_store.read_all()  # 触发留底
        assert _corrupt_quarantined_files(admin_store), "前置：留底已完成"
        # 随后新增一条告警 → 正常写入新文件，MUST NOT 被下限保护拒绝
        rec = admin_store.append({"kind": "signal", "spec": "s1", "signal_type": "t1"})
        assert admin_store.alerts_path.exists(), "恢复写入落盘"
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        assert any(e.get("id") == rec.get("id") for e in data), "新告警出现在新文件"
        # 留底证据仍在（未被覆盖）
        assert _corrupt_quarantined_files(admin_store), "留底取证不被覆盖"

    def test_recovery_append_then_more_appends(self, store):
        admin_store, _logger = store
        _corrupt(admin_store)
        admin_store.read_all()
        admin_store.append({"kind": "signal", "spec": "s1", "signal_type": "t1"})
        rec2 = admin_store.append({"kind": "signal", "spec": "s2", "signal_type": "t2"})
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        assert len(data) == 2, "恢复后连续追加正常工作"
        assert any(e.get("id") == rec2.get("id") for e in data)


# ── 4. 正常追加不受影响 ────────────────────────────────────────────


class TestNormalAppend:
    def test_append_preserves_existing(self, store):
        admin_store, _logger = store
        first = admin_store.append({"kind": "signal", "spec": "s", "signal_type": "a"})
        second = admin_store.append({"kind": "signal", "spec": "s", "signal_type": "b"})
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        ids = {e.get("id") for e in data}
        assert {first.get("id"), second.get("id")} <= ids, "既有记录保留 + 新记录追加"
        assert len(data) == 2

    def test_cap_records_at_max(self, store):
        """写回裁剪上限（MAX_RECORDS）不受损坏保护影响。"""
        from core.admin_store import MAX_RECORDS

        admin_store, _logger = store
        for i in range(MAX_RECORDS + 10):
            admin_store.append({"kind": "signal", "spec": "s", "signal_type": f"t{i}"})
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        assert len(data) == MAX_RECORDS


# ── 5. 合法空集合不被误拦 ──────────────────────────────────────────


class TestLegitEmptyNotBlocked:
    def test_missing_file_append_ok(self, store):
        admin_store, _logger = store
        # 文件本不存在
        rec = admin_store.append({"kind": "signal", "spec": "s", "signal_type": "t"})
        assert admin_store.alerts_path.exists()
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        assert any(e.get("id") == rec.get("id") for e in data)
        # 无留底文件（从未误判损坏）
        assert _corrupt_quarantined_files(admin_store) == []

    def test_legit_empty_array_append_ok(self, store):
        admin_store, _logger = store
        admin_store.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        admin_store.alerts_path.write_text("[]", encoding="utf-8")
        rec = admin_store.append({"kind": "signal", "spec": "s", "signal_type": "t"})
        data = json.loads(admin_store.alerts_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["id"] == rec["id"]
        assert _corrupt_quarantined_files(admin_store) == [], "合法空数组不得触发留底"