"""self_review aware UTC 迁移 characterization（add-timelib-callsite-migration 1.1）。

以「固定 run 数据集 + 固定调度配置 + 固定 now」固化迁移前现行为（命中集合
快照），作为批① naive→aware UTC 等价迁移的基准：迁移前后用同一数据集、同
一瞬时（naive 本地 12:00 ↔ aware UTC 对应值）分别运行新旧实现，命中集合与
调度判定必须逐项相同（spec Scenario「窗口判定等价」「调度时刻语义保持本地
墙钟」）。

时间接缝双写：迁移前实现走 ``core.self_review.datetime.now``/``.fromtimestamp``
（mock datetime 类），迁移后实现走模块级 ``now_utc``/``from_epoch``/``now_local``
（create=True 注入）。两个接缝同轮打桩、注入同一瞬时的 naive/aware 对偶值，
测试体与断言在迁移前后零改动。
"""

import core.self_review as csr
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from core.self_review import (
    SelfReviewScheduler,
    _in_window,
    _iter_window_runs,
    collect_log_errors,
    collect_runs_stats,
)

# 固定「当下」：naive 本地 2026-09-13 12:00 ↔ 同一瞬时的 aware 对偶值。
# naive.astimezone()（本地语义）依赖机器时区 Asia/Shanghai（spec Scenario 口径）。
FIXED_NAIVE_LOCAL = datetime(2026, 9, 13, 12, 0, 0)
FIXED_AWARE_UTC = FIXED_NAIVE_LOCAL.astimezone(timezone.utc)
FIXED_AWARE_LOCAL = FIXED_NAIVE_LOCAL.astimezone()

WINDOW_START_NAIVE = datetime(2026, 9, 13, 0, 0, 0)


def _patch_clock():
    """同时打桩迁移前（datetime.now/fromtimestamp）与迁移后（now_utc/
    from_epoch/now_local）时间源，注入同一瞬时。"""
    mock_dt = mock.MagicMock(wraps=datetime)
    mock_dt.now.return_value = FIXED_NAIVE_LOCAL
    mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
    return [
        mock.patch.object(csr, "datetime", mock_dt),
        mock.patch.object(
            csr, "now_utc", create=True, return_value=FIXED_AWARE_UTC
        ),
        mock.patch.object(
            csr, "now_local", create=True, return_value=FIXED_AWARE_LOCAL
        ),
        mock.patch.object(
            csr,
            "from_epoch",
            create=True,
            side_effect=lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc),
        ),
    ]


def _make_run(runs_dir: Path, prefix: str, local_dt: datetime) -> str:
    """run_id 内嵌 epoch 起始时间戳（_run_start_ts 抽取约定）。"""
    rid = f"{prefix}-{int(local_dt.timestamp())}"
    (runs_dir / f"{rid}.jsonl").write_text(
        json.dumps({"type": "result", "data": {}}), encoding="utf-8"
    )
    return rid


class TestWindowEquivalenceCharacterization:
    """_in_window / collect_runs_stats / collect_log_errors 命中集合快照。"""

    def test_in_window_boundaries(self):
        """闭区间边界语义：恰在 window_end 上的点命中。"""
        wins = [
            (datetime(2026, 9, 13, 10, 0, 0), True),
            (datetime(2026, 9, 13, 14, 0, 0), False),
            (datetime(2026, 9, 13, 12, 0, 0), True),  # 恰在端点
            (datetime(2026, 9, 12, 23, 59, 59), False),
            (None, False),
        ]
        for dt, expected in wins:
            dt_aware = dt.astimezone() if dt is not None else None
            got = _in_window(dt_aware, WINDOW_START_NAIVE.astimezone(),
                             FIXED_NAIVE_LOCAL.astimezone())
            assert got is expected, f"{dt}: {got} != {expected}"

    def test_collect_runs_stats_hit_set_snapshot(self, tmp_path: Path):
        """固定 run 数据集：命中集合恰为窗口内两个 run（快照化窗口上界）。"""
        runs_dir = tmp_path / ".fenix" / "runs"
        runs_dir.mkdir(parents=True)
        # 窗口 [09-13 00:00, 12:00（固定 now）]：前两个命中、后两个不命中
        rid_in_a = _make_run(runs_dir, "run-a", datetime(2026, 9, 13, 0, 0, 0))
        rid_in_b = _make_run(runs_dir, "run-b", datetime(2026, 9, 13, 11, 30, 0))
        _make_run(runs_dir, "run-x", datetime(2026, 9, 12, 23, 59, 0))
        _make_run(runs_dir, "run-y", datetime(2026, 9, 13, 12, 0, 1))

        for ctxs in (_patch_clock(),):
            with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
                hit_ids = {rid for rid, _p, _ts in _iter_window_runs(
                    tmp_path, WINDOW_START_NAIVE.astimezone(),
                    FIXED_NAIVE_LOCAL.astimezone())}
                stats = collect_runs_stats(tmp_path, WINDOW_START_NAIVE.astimezone())
        assert hit_ids == {rid_in_a, rid_in_b}
        assert stats["total"] == 2
        assert stats["succeeded"] == 2

    def test_collect_log_errors_hit_set_snapshot(self, tmp_path: Path):
        """固定日志数据集（naive ISO 串替身）：窗口内错误条目命中快照。"""
        logs_dir = tmp_path / ".fenix" / "logs"
        logs_dir.mkdir(parents=True)

        def entry(local_dt, msg):
            return json.dumps(
                {
                    "timestamp": local_dt.isoformat(),
                    "level": "ERROR",
                    "component": "test",
                    "message": msg,
                },
                ensure_ascii=False,
            )

        (logs_dir / "fenixd.log").write_text(
            "\n".join(
                [
                    entry(datetime(2026, 9, 13, 10, 0, 0), "error in window"),
                    entry(datetime(2026, 9, 13, 14, 0, 0), "error after now"),
                    entry(datetime(2026, 9, 12, 23, 0, 0), "error before window"),
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        for ctxs in (_patch_clock(),):
            with ctxs[0], ctxs[1], ctxs[2], ctxs[3]:
                result = collect_log_errors(tmp_path, WINDOW_START_NAIVE.astimezone())
        assert result["error_count"] == 1
        assert len(result["samples"]) == 1
        assert "error in window" in result["samples"][0]


def _make_scheduler(tmp_path: Path) -> SelfReviewScheduler:
    return SelfReviewScheduler(
        config={"admin": {"self_review": {"enabled": True, "run_at": "23:00"}}},
        project_root=tmp_path,
        logger=mock.MagicMock(),
        state_machine=mock.MagicMock(),
        agent_runner=mock.MagicMock(),
        store=mock.MagicMock(),
    )


def _patched_config(enabled=True, run_at="23:00"):
    return mock.patch(
        "core.config.ConfigLoader.get_self_review_config",
        return_value={"enabled": enabled, "run_at": run_at, "read_todo": False},
    )


class TestSchedulerTriggerCharacterization:
    """调度触发快照：HH:MM 人类时刻语义 + 增量窗口锚点（同瞬时对偶验证）。"""

    def _run_check(self, tmp_path, now_naive_local, last_run_at_str, state=None):
        sched = _make_scheduler(tmp_path)
        fixed_naive = now_naive_local
        fixed_utc = now_naive_local.astimezone(timezone.utc)
        fixed_local = now_naive_local.astimezone()
        captured = {}

        def fake_execute(today, sr, window_start):
            captured["today"] = today
            captured["window_start"] = window_start
            return {"triggered": True, "ok": True}

        mock_dt = mock.MagicMock(wraps=datetime)
        mock_dt.now.return_value = fixed_naive
        mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)

        # last_run_at 替身走生产解析器（aware 化后 _iso_to_aware_dt 直返
        # aware；naive 替身串按本地解读，与迁移前同一瞬时）。
        def fake_load_last_run_at():
            if last_run_at_str is None:
                return None
            return csr._iso_to_aware_dt(last_run_at_str)

        with (
            mock.patch.object(csr, "datetime", mock_dt),
            mock.patch.object(
                csr, "now_utc", create=True, return_value=fixed_utc
            ),
            mock.patch.object(
                csr, "now_local", create=True, return_value=fixed_local
            ),
            mock.patch.object(
                csr,
                "from_epoch",
                create=True,
                side_effect=lambda ts: datetime.fromtimestamp(ts, tz=timezone.utc),
            ),
            mock.patch.object(sched, "_execute_review", side_effect=fake_execute),
            mock.patch.object(
                sched,
                "_load_state",
                return_value=state or {"last_run_date": "2026-09-12"},
            ),
            mock.patch.object(sched, "_load_last_run_at", side_effect=fake_load_last_run_at),
            mock.patch.object(sched, "_save_state"),
            _patched_config(),
        ):
            result = sched.check_and_run()
        return result, captured

    def test_triggers_after_local_run_at(self, tmp_path):
        """本地 23:30（=15:30Z）≥ run_at 23:00（=15:00Z）→ 触发。"""
        result, captured = self._run_check(
            tmp_path,
            datetime(2026, 9, 13, 23, 30, 0),
            "2026-09-13T08:00:00",  # 旧格式 naive 本地替身
        )
        assert result["triggered"] is True
        assert result.get("ok") is True
        assert captured["today"] == "2026-09-13"
        # 增量窗口锚点 = last_run_at 同一瞬时（naive 本地 08:00 = 00:00Z）
        assert captured["window_start"].timestamp() == datetime(
            2026, 9, 13, 8, 0, 0
        ).timestamp()
        # now 不再传入 _execute_review（现签名 today, sr, window_start）：
        # 触发判定用的固定瞬时由 now_utc/now_local 替身钉住（见
        # test_before_run_at_not_triggered 的边界对偶）。

    def test_before_run_at_not_triggered(self, tmp_path):
        """本地 22:59（=14:59Z）< run_at 23:00（=15:00Z）→ 不触发。

        spec Scenario「调度时刻语义保持本地墙钟」的边界对偶：23:00 本地
        恰为当日 15:00Z，触发判定用的 aware UTC 时刻按本地墙钟折算。
        """
        result, captured = self._run_check(
            tmp_path, datetime(2026, 9, 13, 22, 59, 0), "2026-09-13T08:00:00"
        )
        assert result == {"triggered": False, "reason": "before_run_at"}
        assert captured == {}

    def test_first_run_falls_back_24h_window(self, tmp_path):
        """无 last_run_at（首跑/旧格式）→ 窗口回退 now-24h。"""
        result, captured = self._run_check(
            tmp_path, datetime(2026, 9, 13, 23, 30, 0), None
        )
        assert result["triggered"] is True
        assert captured["window_start"].timestamp() == (
            datetime(2026, 9, 13, 23, 30, 0) - timedelta(hours=24)
        ).timestamp()

    def test_already_ran_today_not_triggered(self, tmp_path):
        result, captured = self._run_check(
            tmp_path,
            datetime(2026, 9, 13, 23, 30, 0),
            "2026-09-13T08:00:00",
            state={"last_run_date": "2026-09-13"},
        )
        assert result == {"triggered": False, "reason": "already_ran_today"}
        assert captured == {}
