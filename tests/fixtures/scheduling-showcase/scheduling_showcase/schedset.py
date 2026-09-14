"""调度集合核心模块：条目定义与集合操作。

调度集合（SchedulingSet）是一个按名称管理调度条目的有序集合，提供
创建/更新（set）、查询（get/entries）、就绪筛选（ready_entries）、
完成（complete）、删除（clear/clear_all）与冻结（freeze/unfreeze）
等操作。状态机与 ready_entries 的筛选/排序语义严格对应 spec 中
c-sched-set 的状态定义。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Union

# 合法状态集合，与 spec 状态定义一致。
VALID_STATUSES = ("ready", "done", "blocked", "frozen")

# ready_entries 排序键中"无 start_after"的替身：视作最早（最老优先）。
_NO_START_AFTER = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

def _as_utc(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """将 naive datetime 归一化为 UTC（naive 视为 UTC），保留 aware 原值。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=datetime.timezone.utc)
    return dt


@dataclass
class ScheduleEntry:
    """单条调度条目。

    字段语义：
    - name：条目名称，必须为非空字符串；
    - status：状态，取值限定在 VALID_STATUSES；
    - priority：优先级，数值越小越优先（就绪排序维度之一）；
    - created/updated：创建/最近更新时间（UTC aware，ISO 序列化）；
    - start_after：最早可就绪时间（None 表示不限制）；
    - frozen/frozen_until：冻结标记与冻结到期时间（到期后视为未冻结）；
    - error：最近一次错误描述（blocked 的解除依据之一）。
    """

    name: str
    status: str = "ready"
    priority: int = 5
    created: Optional[datetime.datetime] = None
    updated: Optional[datetime.datetime] = None
    start_after: Optional[datetime.datetime] = None
    frozen: bool = False
    frozen_until: Optional[datetime.datetime] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name 必须是非空字符串")
        if self.status not in VALID_STATUSES:
            raise ValueError(f"非法 status: {self.status!r}（可选: {', '.join(VALID_STATUSES)}）")
        now = datetime.datetime.now(datetime.timezone.utc)
        self.created = _as_utc(self.created) if self.created is not None else now
        if self.updated is not None:
            self.updated = _as_utc(self.updated)
        else:
            self.updated = self.created
        self.start_after = _as_utc(self.start_after)
        self.frozen_until = _as_utc(self.frozen_until)

    def to_dict(self) -> Dict[str, Union[str, int, bool, None]]:
        """序列化为普通 dict，datetime 字段转 ISO 字符串（None 保持 None）。"""
        return {
            "name": self.name,
            "status": self.status,
            "priority": self.priority,
            "created": self.created.isoformat() if self.created else None,
            "updated": self.updated.isoformat() if self.updated else None,
            "start_after": self.start_after.isoformat() if self.start_after else None,
            "frozen": self.frozen,
            "frozen_until": self.frozen_until.isoformat() if self.frozen_until else None,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "ScheduleEntry":
        """从 dict（可含 ISO 字符串时间）还原条目。"""
        def _parse(key: str) -> Optional[datetime.datetime]:
            value = data.get(key)
            if value is None or value == "":
                return None
            return datetime.datetime.fromisoformat(str(value))

        return cls(
            name=str(data["name"]),
            status=str(data.get("status", "ready")),
            priority=int(data.get("priority", 5)),
            created=_parse("created"),
            updated=_parse("updated"),
            start_after=_parse("start_after"),
            frozen=bool(data.get("frozen", False)),
            frozen_until=_parse("frozen_until"),
            error=data.get("error"),
        )


class SchedulingSet:
    """按名称管理调度条目的有序集合。

    内部以有序 dict 保存（Python 3.7+ 保证插入序），同名 set() 更新
    不改变既有位置。线程安全性不在此模块范围内（单线程展示用途）。
    """

    def __init__(self) -> None:
        self._entries: Dict[str, ScheduleEntry] = {}

    # ---- 创建 / 更新 ----

    def set(
        self,
        name: str,
        *,
        status: str = "ready",
        priority: int = 5,
        start_after: Optional[datetime.datetime] = None,
        frozen: bool = False,
        frozen_until: Optional[datetime.datetime] = None,
        error: Optional[str] = None,
    ) -> ScheduleEntry:
        """创建新条目或幂等更新同名条目。

        新条目：按参数生成，created/updated 取当前时间。
        同名更新：返回既有对象，created 保持，updated 刷新为当前时间，
        其余显式传入字段覆盖旧值。非法 status 或空 name 抛 ValueError。
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        existing = self._entries.get(name)
        if existing is None:
            entry = ScheduleEntry(
                name=name,
                status=status,
                priority=priority,
                created=now,
                updated=now,
                start_after=_as_utc(start_after),
                frozen=frozen,
                frozen_until=_as_utc(frozen_until),
                error=error,
            )
            self._entries[name] = entry
            return entry

        # 幂等更新：不新建对象，保持位置与 created。
        existing.status = status
        existing.priority = priority
        existing.updated = now
        if start_after is not None:
            existing.start_after = _as_utc(start_after)
        existing.frozen = frozen
        if frozen_until is not None:
            existing.frozen_until = _as_utc(frozen_until)
        if error is not None:
            existing.error = error
        return existing

    # ---- 查询 ----

    def get(self, name: str) -> Optional[ScheduleEntry]:
        """按名称取条目，不存在返回 None。"""
        return self._entries.get(name)

    def entries(self) -> List[ScheduleEntry]:
        """按插入序返回全部条目（同名更新不改变位置）。"""
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return name in self._entries

    # ---- 就绪筛选 ----

    def is_frozen_effective(self, entry: ScheduleEntry, now: Optional[datetime.datetime] = None) -> bool:
        """判断条目当前是否"生效冻结"。

        frozen=True 且 frozen_until 未到期（或未指定）视为生效冻结；
        frozen_until 已到期视为未冻结（标记仍在，重新进入就绪判定）。
        """
        return is_frozen_effective(entry, now)

    def ready_entries(self, now: Optional[datetime.datetime] = None) -> List[ScheduleEntry]:
        """返回当前就绪条目列表（不修改集合）。

        筛选：status=ready 且未生效冻结且 start_after 为空或已到期。
        排序：按 (start_after 或最老替身, priority, name) 升序——无
        start_after 的条目视作最老、优先排前。
        """
        ref = _as_utc(now) if now is not None else datetime.datetime.now(datetime.timezone.utc)
        ready = []
        for entry in self._entries.values():
            if entry.status != "ready":
                continue
            if self.is_frozen_effective(entry, ref):
                continue
            if entry.start_after is not None and entry.start_after > ref:
                continue
            ready.append(entry)
        ready.sort(key=lambda e: (e.start_after or _NO_START_AFTER, e.priority, e.name))
        return ready

    # ---- 完成 ----

    def complete(self, name: str) -> ScheduleEntry:
        """标记条目完成（status=done 并刷新 updated）。

        约束：blocked 且 error 非空的条目不可直接标记完成，须先解除
        阻塞（unfreeze 或清除 error），否则抛 ValueError。
        """
        entry = self._entries.get(name)
        if entry is None:
            raise ValueError(f"条目不存在: {name!r}")
        if entry.status == "blocked" and entry.error:
            raise ValueError(
                f"条目 {name!r} 处于 blocked 且 error 非空，不可直接标记完成（error: {entry.error}）"
            )
        entry.status = "done"
        entry.updated = datetime.datetime.now(datetime.timezone.utc)
        return entry

    # ---- 删除 ----

    def clear(self, name: str) -> bool:
        """删除指定条目，存在返回 True，不存在返回 False 且无副作用。"""
        if name in self._entries:
            del self._entries[name]
            return True
        return False

    def clear_all(self) -> int:
        """清空全部条目，返回删除数。"""
        count = len(self._entries)
        self._entries.clear()
        return count

    # ---- 冻结 ----

    def freeze(
        self,
        name: str,
        reason: Optional[str] = None,
        until: Optional[datetime.datetime] = None,
    ) -> ScheduleEntry:
        """冻结条目：置 frozen=True、error=原因文案。

        error 文案固定前缀"用户指令冻结："，追加原因（缺省时直接使用
        前缀）。until 指定冻结到期时间（到期后自动视为未冻结）。
        条目不存在时自动以默认字段创建后再冻结（交互式构造的便利语义，
        与验证场景 cli-ready-filter/cli-ready-frozen-expiry 的用法一致）。
        """
        entry = self._entries.get(name)
        if entry is None:
            entry = ScheduleEntry(name=name)
            self._entries[name] = entry
        entry.frozen = True
        entry.frozen_until = _as_utc(until)
        prefix = "用户指令冻结："
        entry.error = prefix + reason if reason else prefix
        entry.updated = datetime.datetime.now(datetime.timezone.utc)
        return entry

    def unfreeze(self, name: str) -> ScheduleEntry:
        """解除冻结：置 frozen=False、frozen_until=None 并清空 error。"""
        entry = self._entries.get(name)
        if entry is None:
            raise ValueError(f"条目不存在: {name!r}")
        entry.frozen = False
        entry.frozen_until = None
        entry.error = None
        entry.updated = datetime.datetime.now(datetime.timezone.utc)
        return entry


def is_frozen_effective(entry: ScheduleEntry, now: Optional[datetime.datetime] = None) -> bool:
    """模块级便捷函数，语义同 SchedulingSet.is_frozen_effective。"""
    if not entry.frozen:
        return False
    if entry.frozen_until is None:
        return True
    ref = _as_utc(now) if now is not None else datetime.datetime.now(datetime.timezone.utc)
    return entry.frozen_until > ref


def run_demo() -> int:
    """CLI 演示：构造就绪 / 未到期 / 冻结三类条目并打印就绪列表。"""
    now = datetime.datetime.now(datetime.timezone.utc)
    showcase = SchedulingSet()
    showcase.set("r-sched-set")
    showcase.set("w-start-after", start_after=now + datetime.timedelta(hours=1))
    showcase.set("f-frozen")
    showcase.freeze("f-frozen", reason="演示冻结")

    print("=== 全部条目 ===")
    for entry in showcase.entries():
        print(
            f"- {entry.name} status={entry.status} priority={entry.priority} "
            f"frozen={entry.frozen} start_after={entry.start_after} error={entry.error}"
        )
    print("=== 就绪列表 ready_entries(now) ===")
    for entry in showcase.ready_entries(now):
        print(f"- {entry.name}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """模块 CLI 入口：仅支持 `demo` 子命令，无参数时打印用法并返回 2。"""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["demo"]:
        return run_demo()
    print("用法: python -m scheduling_showcase.schedset demo", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
