"""test_serving_registry_sweep_anchor_recheck.py — sweep 收尾 _purge 锚点复核守卫。

code-review item dacecc311ec1：sweep 的 entries() 快照与收尾 _mutate 之间隔着
收割等待窗口（kill_process_group 最长 3 秒），期间同 (pid, spec) 的新实例
register 会就地刷新身份快照（start_ticks/registered_at）。_purge 锚点复核对
「快照锚点 ≠ 登记条目锚点」的条目 MUST 保留（否则收割窗口内 pid 复用、同
spec 重验 spawn 的新实例登记被误删，该实例自此脱离登记制收割面），只记
kept_fresh 留痕名单。

本守卫锁定该分支的双向行为：锚点已刷新的条目仍在登记表中；锚点未变的
stale 条目照常摘除（防修复滑向「永不摘除」）。离线可跑：pid_alive 与
entries() 快照打桩，不触真实进程、不发任何信号。
"""

import json
from unittest.mock import MagicMock, patch

import core.serving_registry as serving_registry

PID_REFRESHED = 910001
PID_STALE = 910002
SPEC_A = "fix-anchor"
SPEC_B = "fix-stale"
OLD_TICKS = 1000000
NEW_TICKS = 2000000
OLD_TS = 1700000000
NEW_TS = 1700000600


def _record(pid, spec, ticks, ts):
    return {
        "pid": pid,
        "port": 0,
        "spec": spec,
        "worktree": f"/tmp/wt-{spec}",
        "registered_at": ts,
        "start_ticks": ticks,
    }


def _write_servers(project_root, records):
    path = serving_registry.servers_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def _read_servers(project_root):
    path = serving_registry.servers_path(project_root)
    return json.loads(path.read_text(encoding="utf-8"))


def _run_sweep(project_root, snapshot, on_disk, logger):
    """以 snapshot 作 entries() 快照、on_disk 作 _mutate 时点盘上状态跑 sweep。

    复刻真实竞态时序：entries() 快照（旧锚点）先于收割等待窗口，register
    就地刷新发生在快照之后、_purge 持锁读盘之前。pid_alive 打桩为 False
    使两条目都直接落入待摘名单（不走收割投递路径，零信号零等待）。
    """
    _write_servers(project_root, on_disk)
    with patch.object(serving_registry, "pid_alive", lambda pid: False), patch.object(
        serving_registry.ServingRegistry, "entries", lambda self: list(snapshot)
    ):
        return serving_registry.sweep(project_root, logger=logger)


class TestSweepPurgeAnchorRecheck:
    def test_refreshed_entry_survives_and_stale_entry_purged(self, tmp_path):
        """快照后 register 刷新了 A 的锚点：A 保留、B（锚点未变）照常摘除。"""
        snapshot = [
            _record(PID_REFRESHED, SPEC_A, OLD_TICKS, OLD_TS),
            _record(PID_STALE, SPEC_B, OLD_TICKS, OLD_TS),
        ]
        on_disk = [
            _record(PID_REFRESHED, SPEC_A, NEW_TICKS, NEW_TS),
            _record(PID_STALE, SPEC_B, OLD_TICKS, OLD_TS),
        ]
        logger = MagicMock()
        harvested = _run_sweep(tmp_path, snapshot, on_disk, logger)
        survivors = {r["pid"]: r for r in _read_servers(tmp_path)}
        # 锚点已刷新（register 就地刷新身份快照）的新登记 MUST 保留
        assert PID_REFRESHED in survivors
        assert survivors[PID_REFRESHED]["start_ticks"] == NEW_TICKS
        assert survivors[PID_REFRESHED]["registered_at"] == NEW_TS
        # 锚点未变的 stale 条目照常摘除（防修复滑向永不摘除）
        assert PID_STALE not in survivors
        # 保留分支没有对任何进程组发出信号（kept_fresh 不是收割）
        assert harvested == 0
        # 留痕契约：kept_fresh 名单对应 WARNING 落日志
        warnings = [
            c.args[1]
            for c in logger.warning.call_args_list
            if c.args[0] == "serving_registry"
        ]
        assert any("keeping refreshed entry" in w for w in warnings)

    def test_single_field_refresh_kept(self, tmp_path):
        """仅 registered_at 刷新（start_ticks 同值）同属「锚点已刷新」→ 保留。

        _purge 的 all() 双字段复核任一字段不等即视为新登记，不得按部分
        匹配放行摘除。
        """
        snapshot = [_record(PID_REFRESHED, SPEC_A, OLD_TICKS, OLD_TS)]
        on_disk = [_record(PID_REFRESHED, SPEC_A, OLD_TICKS, NEW_TS)]
        logger = MagicMock()
        harvested = _run_sweep(tmp_path, snapshot, on_disk, logger)
        survivors = {r["pid"]: r for r in _read_servers(tmp_path)}
        assert PID_REFRESHED in survivors
        assert survivors[PID_REFRESHED]["registered_at"] == NEW_TS
        assert harvested == 0
