"""add-alerts-archive-and-overview-cache 1.3：AdminStore 裁剪归档。

覆盖 spec/admin-alerts-archive 三场景：
  - 超限裁剪触发归档：151 条写回触发 1 条归档（内容逐字段一致、活跃仍 150 条）
  - 归档失败不阻塞主写回：归档文件不可写时活跃写回成功且无异常抛出
  - 归档自身滚动淘汰：2001 条归档触发滚动裁剪（最旧出、最新留）
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.admin_store import (  # noqa: E402
    ARCHIVE_NAME,
    MAX_ARCHIVE_RECORDS,
    MAX_RECORDS,
    AdminStore,
)


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
def store(tmp_path):
    proot = tmp_path / "proj"
    proot.mkdir(parents=True)
    logger = _FakeLogger()
    return AdminStore(proot, logger), logger


def _rec(i: int) -> dict:
    """构造带可辨序号的告警记录（created 随 i 单调递增，id 唯一）。"""
    return {
        "id": f"rec-{i:04d}",
        "kind": "disposition",
        "created": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}+00:00",
        "spec": f"spec-{i}",
        "summary": f"处置记录 {i}",
    }


def _seed_active(store: AdminStore, n: int) -> list:
    """直接写活跃文件为 n 条记录（不经 append，精确控制裁剪触发点）。"""
    records = [_rec(i) for i in range(n)]
    store.alerts_path.parent.mkdir(parents=True, exist_ok=True)
    store.alerts_path.write_text(
        json.dumps(records, ensure_ascii=False), encoding="utf-8"
    )
    return records


def _archive_lines(store: AdminStore) -> list:
    text = store.archive_path.read_text(encoding="utf-8")
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def test_trim_151st_appends_archive(store):
    """150 条池再写入 1 条：最旧 1 条进归档末行（逐字段一致），活跃仍 150 条。"""
    st, _logger = store
    seed = _seed_active(st, MAX_RECORDS)

    st.append({"id": "new-rec", "kind": "disposition", "spec": "spec-new"})

    archived = _archive_lines(st)
    assert len(archived) == 1, "恰好 1 条被裁记录进归档"
    assert archived[0] == seed[0], "归档内容与被裁记录逐字段一致"
    active = json.loads(st.alerts_path.read_text(encoding="utf-8"))
    assert len(active) == MAX_RECORDS, "活跃文件仍为 150 条"
    assert active[0]["id"] == seed[1]["id"], "新最旧记录是被裁记录的后一条"
    assert active[-1]["id"] == "new-rec", "新记录在活跃文件末尾"


def test_archive_unwritable_active_write_succeeds(store):
    """归档文件不可写（目录占位，root 下权限位失效的可靠替代）→ 活跃写回
    成功、无异常抛出、日志记录归档失败。"""
    st, logger = store
    _seed_active(st, MAX_RECORDS)
    st.archive_path.parent.mkdir(parents=True, exist_ok=True)
    st.archive_path.mkdir()  # IsADirectoryError（OSError 子类），对 root 同样生效

    rec = st.append({"id": "new-rec", "kind": "disposition", "spec": "spec-new"})

    assert rec is not None, "活跃写回成功（记录落地）"
    active = json.loads(st.alerts_path.read_text(encoding="utf-8"))
    assert len(active) == MAX_RECORDS
    assert active[-1]["id"] == "new-rec"
    assert any("归档" in str(w) for w in logger.warnings), "归档失败记入日志"
    assert not logger.errors, "软失败不升级为 error/异常"


def test_archive_rolling_trim_evicts_oldest(store):
    """归档已达 2000 条再归档 1 条：裁至 2000 条，最旧 1 条淘汰、新条目在末尾。"""
    st, _logger = store
    st.archive_path.parent.mkdir(parents=True, exist_ok=True)
    old_lines = [
        json.dumps({**_rec(i), "id": f"arch-{i:04d}"}, ensure_ascii=False)
        for i in range(MAX_ARCHIVE_RECORDS)
    ]
    st.archive_path.write_text("\n".join(old_lines) + "\n", encoding="utf-8")
    _seed_active(st, MAX_RECORDS)

    st.append({"id": "new-rec", "kind": "disposition", "spec": "spec-new"})

    archived = _archive_lines(st)
    assert len(archived) == MAX_ARCHIVE_RECORDS, "归档裁回上限内"
    assert archived[0]["id"] == "arch-0001", "最旧 1 条被淘汰"
    # 本次新归档条目 = 活跃被裁出的最旧记录（rec-0000），落在归档末尾；
    # new-rec 本身留活跃侧（见上一用例），不进归档
    assert archived[-1]["id"] == "rec-0000", "新归档条目在末尾"
    assert json.loads(st.alerts_path.read_text(encoding="utf-8"))[-1]["id"] == "new-rec"
    assert st.archive_path.name == ARCHIVE_NAME


def test_read_archive_tolerates_corrupt_lines(store):
    """read_archive 容错：损坏行跳过、空行跳过、合法行全量按存储原序返回。"""
    st, _logger = store
    st.archive_path.parent.mkdir(parents=True, exist_ok=True)
    st.archive_path.write_text(
        json.dumps(_rec(0), ensure_ascii=False)
        + "\n{not-valid-json!!!\n\n"
        + json.dumps(_rec(1), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    out = st.read_archive()
    assert [r["id"] for r in out] == ["rec-0000", "rec-0001"]
    assert st.read_archive() is not out, "返回独立列表，与内部状态无共享引用"
