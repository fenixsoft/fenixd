"""maintenance_ledger 台账读写测试（maintenance-work-ledger 3.1）。

钉住 R1（追加/读取/空文件自动创建/坏行容错）与 R3（run_id 关联字段读写）。
"""

import json
from pathlib import Path

from core.agent_runner.run_files import _ATOMIC_APPEND_LINE_BYTES, infer_run_agent_type
from core.maintenance_ledger import (
    LEDGER_FILENAME,
    append_maintenance_entry,
    list_entries_for_run,
    list_maintenance_entries,
    make_maintenance_run_id,
)


def _ledger_file(tmp_path) -> Path:
    return tmp_path / ".fenix" / LEDGER_FILENAME


class TestAppendAndList:
    """R1：追加/读取往返与空文件自动创建。"""

    def test_append_creates_file_and_roundtrips(self, tmp_path):
        """文件不存在则创建（含 .fenix 目录），条目字段齐全、读侧逐字还原。"""
        entry = append_maintenance_entry(
            tmp_path,
            scope="hotfix-dashboard",
            actor="icyfenix",
            evidence=".fenix/verify-evidence/hotfix-dashboard",
            note="spec done 后的延伸中性化补丁",
        )
        assert _ledger_file(tmp_path).exists()
        lines = _ledger_file(tmp_path).read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        stored = json.loads(lines[0])
        assert stored == entry
        assert stored["scope"] == "hotfix-dashboard"
        assert stored["actor"] == "icyfenix"
        assert stored["evidence"] == ".fenix/verify-evidence/hotfix-dashboard"
        assert stored["note"] == "spec done 后的延伸中性化补丁"
        assert stored["run_id"] is None
        assert stored["ts"]  # ts 由写侧生成（ISO UTC，to_storage 口径）

    def test_append_preserves_order_and_existing_content(self, tmp_path):
        """追加不覆盖既有条目，读取保持落账顺序（旧→新）。"""
        append_maintenance_entry(tmp_path, "a", "actor-a", "ev-a", "first")
        append_maintenance_entry(tmp_path, "b", "actor-b", "ev-b", "second")
        entries = list_maintenance_entries(tmp_path)
        assert [e["scope"] for e in entries] == ["a", "b"]
        assert [e["note"] for e in entries] == ["first", "second"]

    def test_list_missing_file_returns_empty(self, tmp_path):
        """台账未落任何条目（文件不存在）读取返回空列表，不抛异常。"""
        assert list_maintenance_entries(tmp_path) == []
        assert list_entries_for_run(tmp_path, "maintenance-x-1") == []

    def test_bad_lines_skipped(self, tmp_path):
        """坏行（非法 JSON / 非 dict 顶层 / 空行）容错跳过，不中断全量读取。"""
        _ledger_file(tmp_path).parent.mkdir(parents=True)
        _ledger_file(tmp_path).write_text(
            json.dumps({"ts": "t1", "scope": "ok1"}) + "\n"
            + "{not-valid-json\n"
            + "\n"
            + json.dumps(["not", "a", "dict"]) + "\n"
            + '"bare string"\n'
            + json.dumps({"ts": "t2", "scope": "ok2"}) + "\n",
            encoding="utf-8",
        )
        entries = list_maintenance_entries(tmp_path)
        assert [e["scope"] for e in entries] == ["ok1", "ok2"]

    def test_oversized_line_still_roundtrips(self, tmp_path):
        """行超 _ATOMIC_APPEND_LINE_BYTES 走二进制 os.write 路径仍整行落盘可读
        （沿用 run_files 原子追加约定，先例 item 29df176ff441）。"""
        note = "x" * (_ATOMIC_APPEND_LINE_BYTES + 1)
        append_maintenance_entry(tmp_path, "big", "actor", "ev", note)
        entries = list_maintenance_entries(tmp_path)
        assert len(entries) == 1
        assert entries[0]["note"] == note


class TestRunIdAssociation:
    """R3：run_id 关联字段读写。"""

    def test_entry_carries_run_id_and_read_side_filters(self, tmp_path):
        run_id = make_maintenance_run_id("hotfix-x")
        append_maintenance_entry(
            tmp_path, "hotfix-x", "icyfenix", "ev-x", "落账", run_id=run_id)
        append_maintenance_entry(tmp_path, "other", "actor", "ev", "无关联")
        hits = list_entries_for_run(tmp_path, run_id)
        assert len(hits) == 1
        assert hits[0]["scope"] == "hotfix-x"
        assert hits[0]["run_id"] == run_id
        assert list_entries_for_run(tmp_path, "maintenance-other-1") == []

    def test_make_run_id_shape_matches_prefix_table(self):
        """生成的 run id 走 maintenance- 前缀：真源表归属 maintenance、
        剩余段为 <scope>-<epoch>（admin_monitor._spec_from_run_id 可还原
        scope，形态与既有 <prefix><spec>-<ts> 一致）。"""
        rid = make_maintenance_run_id("hotfix-y")
        assert rid.startswith("maintenance-hotfix-y-")
        assert infer_run_agent_type(rid) == ("maintenance", rid[len("maintenance-"):])
        epoch = int(rid.rsplit("-", 1)[1])
        assert abs(epoch - __import__("time").time()) < 60
