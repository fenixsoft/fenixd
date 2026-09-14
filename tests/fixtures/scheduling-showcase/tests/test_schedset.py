"""c-sched-set 单元测试：覆盖 set 幂等 / get / clear / complete / freeze / ready_entries。"""

import datetime
import time

import pytest

from scheduling_showcase import ScheduleEntry, SchedulingSet


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def test_set_create_defaults() -> None:
    s = SchedulingSet()
    e = s.set("alpha")
    assert e.status == "ready"
    assert e.priority == 5
    assert len(s) == 1
    assert "alpha" in s


def test_set_idempotent_update() -> None:
    s = SchedulingSet()
    e1 = s.set("alpha")
    created = e1.created
    time.sleep(0.01)
    e2 = s.set("alpha", priority=1)
    assert e1 is e2
    assert e1.created == created
    assert e1.updated > created
    assert len(s) == 1
    assert e2.priority == 1


def test_set_invalid_status() -> None:
    s = SchedulingSet()
    with pytest.raises(ValueError, match="非法 status"):
        s.set("alpha", status="bogus")


def test_set_empty_name() -> None:
    s = SchedulingSet()
    with pytest.raises(ValueError, match="name 必须是非空字符串"):
        s.set("")


def test_get_existing_and_missing() -> None:
    s = SchedulingSet()
    s.set("alpha")
    assert s.get("alpha") is not None
    assert s.get("missing") is None


def test_entries_insertion_order() -> None:
    s = SchedulingSet()
    s.set("a")
    s.set("b")
    s.set("a", priority=9)
    assert [e.name for e in s.entries()] == ["a", "b"]


def test_ready_filter() -> None:
    s = SchedulingSet()
    now = _now()
    s.set("r1")
    s.set("late", start_after=now + datetime.timedelta(hours=1))
    s.freeze("fz") if False else s.set("fz")
    s.freeze("fz")
    assert [e.name for e in s.ready_entries(now)] == ["r1"]


def test_ready_frozen_expiry() -> None:
    s = SchedulingSet()
    now = _now()
    s.set("fz")
    s.freeze("fz", until=now - datetime.timedelta(seconds=10))
    assert [e.name for e in s.ready_entries(now)] == ["fz"]


def test_ready_sort_priority_name() -> None:
    s = SchedulingSet()
    s.set("c", priority=9)
    s.set("a", priority=1)
    s.set("b", priority=5)
    assert [e.name for e in s.ready_entries()] == ["a", "b", "c"]


def test_ready_sort_start_after() -> None:
    s = SchedulingSet()
    now = _now()
    s.set("later", start_after=now + datetime.timedelta(hours=1), priority=1)
    s.set("now1", priority=5)
    s.set("now2", priority=1)
    # 注意：later 未到期，不在就绪列表；此处验证无 start_after 优先排前。
    assert [e.name for e in s.ready_entries(now)] == ["now2", "now1"]


def test_ready_sort_start_after_expired_orders_last() -> None:
    s = SchedulingSet()
    now = _now()
    s.set("later", start_after=now - datetime.timedelta(seconds=1), priority=1)
    s.set("now1", priority=5)
    s.set("now2", priority=1)
    assert [e.name for e in s.ready_entries(now)] == ["now2", "now1", "later"]


def test_clear_remove() -> None:
    s = SchedulingSet()
    s.set("alpha")
    assert s.clear("alpha") is True
    assert s.clear("alpha") is False
    assert len(s) == 0


def test_clear_all() -> None:
    s = SchedulingSet()
    s.set("a")
    s.set("b")
    assert s.clear_all() == 2
    assert len(s) == 0


def test_complete_done() -> None:
    s = SchedulingSet()
    s.set("a")
    e = s.complete("a")
    assert e.status == "done"
    assert [x.name for x in s.ready_entries()] == []


def test_complete_blocked_reject() -> None:
    s = SchedulingSet()
    s.set("a", status="blocked", error="user")
    with pytest.raises(ValueError, match="不可直接标记完成"):
        s.complete("a")


def test_complete_blocked_no_error_ok() -> None:
    s = SchedulingSet()
    s.set("a", status="blocked")
    e = s.complete("a")
    assert e.status == "done"


def test_freeze_unfreeze() -> None:
    s = SchedulingSet()
    s.set("a")
    e = s.freeze("a", reason="测试")
    assert e.frozen is True
    assert e.error == "用户指令冻结：测试"
    s.unfreeze("a")
    assert e.frozen is False
    assert e.frozen_until is None


def test_freeze_until_expiry_ready() -> None:
    s = SchedulingSet()
    now = _now()
    s.set("a")
    s.freeze("a", until=now - datetime.timedelta(seconds=5))
    assert [e.name for e in s.ready_entries(now)] == ["a"]
    assert s.get("a").frozen is True


def test_to_from_dict() -> None:
    e = ScheduleEntry(name="a", status="blocked", priority=3)
    d = e.to_dict()
    e2 = ScheduleEntry.from_dict(d)
    assert (e2.name, e2.status, e2.priority) == ("a", "blocked", 3)
    assert isinstance(d["created"], str)


def test_to_from_dict_datetime_roundtrip() -> None:
    now = _now()
    e = ScheduleEntry(name="a", start_after=now)
    e2 = ScheduleEntry.from_dict(e.to_dict())
    assert e2.start_after == now
    assert e2.start_after is not None
