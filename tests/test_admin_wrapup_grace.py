"""evo-add-admin-run-wrapup-contract — admin/维护车道一次性收尾宽限 单测。

覆盖（tasks 3.1，四类用例 × 轮数/墙钟两侧）：
- 末次扩容点触发收尾宽限：非实现车道（administrator）且 run 内自建任务
  全部 completed 的 run，在轮数扩容封顶分支（``_turn_limit_action``）与
  墙钟 max_extensions 用满分支（``_supervision_deadline_action``）各发放
  一次性宽限（evidence 注记 ``wrapup_grace``）；
- 宽限耗尽落终态：已发放标记在案时两侧都走既有击杀路径——kill 文案逐字
  保留豁免匹配子串 "extension budget exhausted"（budget._is_exemptable_reason
  按子串匹配，观测信息只进 evidence）；
- 自建任务未清零 / 清单为空（run 无 TaskCreate 记录）：不触发，维持既有
  击杀；判据数据源是 run 产物 TaskCreate/TaskUpdate 解析而非 spec
  tasks.md 的 remaining_tasks（数据源错位禁用——design 明示）；
- impl 车道不受影响：implementer 车道同条件下不发放（车道集合不相交）。

邻位装置：tests/test_impl_run_budget_sizing.py（make_runner 装置）与
tests/test_liveness_hang_discrimination.py（LivenessSupervisor 直调装置）。
"""

import json
import time
from pathlib import Path

import pytest

from core.agent_runner.liveness import LivenessSupervisor
from core.agent_runner.runner import (
    TURN_EXTENSION_MAX,
    TURN_EXTENSION_STEP_FRACTION,
)
from tests.helpers import make_runner


# ── 共用小装置（自足，不跨测试文件 import） ───────────────────────────


def _task_create_evt(subject: str) -> dict:
    """run 产物中的 TaskCreate tool_use 事件（_scan_run_events 消费形态）。"""
    return {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "TaskCreate", "id": "tc",
             "input": {"subject": subject}},
        ]},
    }


def _task_update_evt(task_id: int, status: str) -> dict:
    """run 产物中的 TaskUpdate tool_use 事件（taskId 1 基创建序）。"""
    return {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "TaskUpdate", "id": "tu",
             "input": {"taskId": task_id, "status": status}},
        ]},
    }


def _write_run_file(path: Path, entries: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


def _all_completed_run_file(tmp_path: Path, run_id: str, total: int = 2) -> Path:
    entries = [_task_create_evt(f"Task 1.{i}: 任务 {i}") for i in range(1, total + 1)]
    entries += [_task_update_evt(i, "completed") for i in range(1, total + 1)]
    return _write_run_file(tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl", entries)


def _partial_run_file(tmp_path: Path, run_id: str, total: int = 2,
                      completed: int = 1) -> Path:
    entries = [_task_create_evt(f"Task 1.{i}: 任务 {i}") for i in range(1, total + 1)]
    entries += [_task_update_evt(i, "completed") for i in range(1, completed + 1)]
    return _write_run_file(tmp_path / ".fenix" / "runs" / f"{run_id}.jsonl", entries)


def _turn_runner(proot: Path, config_extra: dict | None = None):
    cfg = {"agents": {"run_timeout_seconds": 3600, "max_turns": 800}}
    if config_extra:
        cfg["agents"].update(config_extra)
    return make_runner(proot, cfg)


def _sup_config(**sup_extra) -> dict:
    sup = {"enabled": True, "max_extensions": 2, "extension_seconds": 1800,
           "absolute_max_seconds": 7200, "judge_window": 600}
    sup.update(sup_extra)
    return {"agents": {"run_timeout_seconds": 3600, "timeout_supervision": sup}}


# ── 1. 轮数侧：_turn_limit_action 扩容封顶分支 ────────────────────────


class TestTurnSideWrapupGrace:
    """轮数末次扩容点（turn_extensions_used >= TURN_EXTENSION_MAX）。"""

    RUN_ID = "admin-demo-1-a1"

    def _act(self, runner, run_file, agent_type="administrator"):
        return runner._turn_limit_action(
            run_file, None, self.RUN_ID, TURN_EXTENSION_MAX, None,
            agent_type=agent_type, max_turns=800)

    def test_grace_granted_at_extension_cap(self, tmp_path):
        """admin 车道 + 自建任务全部 completed → 发放一次性宽限。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(_turn_runner(tmp_path), run_file)
        assert action["action"] == "extend"
        assert "wrapup_grace" in action["evidence"]
        # 宽限窗口 = 既有封顶 cap + 默认 20 轮
        assert action["new_turn_cap"] == (
            800 + int(800 * TURN_EXTENSION_STEP_FRACTION) * TURN_EXTENSION_MAX
            + 20)
        # extension_index 保持原值（宽限不是常规扩容，观测口径不变）
        assert action["extension_index"] == TURN_EXTENSION_MAX

    def test_grace_exhausted_falls_through_to_kill(self, tmp_path):
        """宽限耗尽（已发放标记在案）→ 既有击杀路径，文案逐字保留豁免子串。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        runner = _turn_runner(tmp_path)
        first = self._act(runner, run_file)
        assert first["action"] == "extend"
        second = self._act(runner, run_file)
        assert second["action"] == "kill"
        assert "extension budget exhausted" in second["evidence"]
        assert "wrapup_grace" not in second["evidence"]

    def test_no_grace_when_tasks_not_all_completed(self, tmp_path):
        """自建任务未清零（2 建 1 完成）→ 不触发，维持既有击杀。"""
        run_file = _partial_run_file(tmp_path, self.RUN_ID)
        action = self._act(_turn_runner(tmp_path), run_file)
        assert action["action"] == "kill"
        assert "wrapup_grace" not in action["evidence"]

    def test_no_grace_when_no_tasks_created(self, tmp_path):
        """run 无 TaskCreate 记录（清单为空）→ 不触发，维持既有击杀。"""
        run_file = _write_run_file(
            tmp_path / ".fenix" / "runs" / f"{self.RUN_ID}.jsonl", [])
        action = self._act(_turn_runner(tmp_path), run_file)
        assert action["action"] == "kill"
        assert "wrapup_grace" not in action["evidence"]

    def test_impl_lane_unaffected(self, tmp_path):
        """implementer 车道同条件不发放（车道集合不相交）。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(_turn_runner(tmp_path), run_file,
                           agent_type="implementer")
        assert action["action"] == "kill"
        assert "wrapup_grace" not in action["evidence"]

    def test_tasks_md_remaining_tasks_is_not_the_criterion(self, tmp_path):
        """判据数据源=run 产物自建任务，禁用 spec tasks.md remaining_tasks：
        spec 全部任务未勾选不影响 admin run 的宽限发放。"""
        spec_dir = tmp_path / "spec" / "changes" / "demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "tasks.md").write_text(
            "# demo\n\n- [ ] 1.1 a\n- [ ] 1.2 b\n", encoding="utf-8")
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = _turn_runner(tmp_path)._turn_limit_action(
            run_file, "demo", self.RUN_ID, TURN_EXTENSION_MAX, None,
            agent_type="administrator", max_turns=800)
        assert action["action"] == "extend"
        assert "wrapup_grace" in action["evidence"]
        assert action["remaining_tasks"] == 2  # 只观测，不作判据

    def test_config_disabled_no_grace(self, tmp_path):
        """agents.wrapup_grace.enabled=false → 同条件不发放。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        runner = _turn_runner(tmp_path, {"wrapup_grace": {"enabled": False}})
        action = self._act(runner, run_file)
        assert action["action"] == "kill"
        assert "wrapup_grace" not in action["evidence"]


# ── 2. 墙钟侧：_supervision_deadline_action 扩容封顶分支 ──────────────


class TestWallclockWrapupGrace:
    """墙钟末次扩容点（extensions_used >= max_extensions）。"""

    RUN_ID = "admin-demo-1-a1"

    def _sup(self, tmp_path, wrapup_cfg: dict | None = None):
        cfg = _sup_config()
        if wrapup_cfg is not None:
            cfg["agents"]["wrapup_grace"] = wrapup_cfg
        return LivenessSupervisor(make_runner(tmp_path, cfg))

    def _act(self, sup, run_file, extensions_used=2, agent_type="administrator",
             started_at=None, turn_count=100, judge=None):
        return sup._supervision_deadline_action(
            run_file, "demo", self.RUN_ID,
            started_at=time.time() - 7000 if started_at is None else started_at,
            extensions_used=extensions_used, agent_type=agent_type,
            turn_count=turn_count, judge=judge)

    def test_grace_at_extension_cap_with_fold(self, tmp_path):
        """发放量按秒折算：宽限轮数 × 近期平均每轮墙钟（elapsed/turn_count）。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(self._sup(tmp_path), run_file)
        assert action["action"] == "extend"
        assert action["reason"] == "wrapup grace granted (final wrap-up window)"
        assert "wrapup_grace" in action["evidence"]
        # elapsed=7000s / 100 轮 = 70s 每轮 → 20 × 70 = 1400s（区间内不 clamp）
        assert action["extension_seconds"] == pytest.approx(1400.0)

    def test_grace_exhausted_kill_keeps_exempt_substring(self, tmp_path):
        """宽限耗尽（已发放标记在案）→ 既有击杀，reason 保留豁免子串。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        sup = self._sup(tmp_path)
        first = self._act(sup, run_file)
        assert first["action"] == "extend"
        second = self._act(sup, run_file)
        assert second["action"] == "kill"
        assert second["reason"] == "extension budget exhausted (2/2)"

    def test_absolute_max_lifted_by_granted_seconds(self, tmp_path):
        """发放的宽限秒数一次性抬升 absolute_max：总墙钟越过硬上限但落在
        宽限窗内时不死于 branch 2（而是继续走后续活性判定路径，judge 用
        stub 替身——不起真子进程）。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        sup = self._sup(tmp_path)
        self._act(sup, run_file)  # 先发放（1400s，见上例折算）
        # elapsed=7500s > absolute_max(7200) 但 < 7200+1400：未发放时会死于
        # absolute_max 分支；抬升生效则进入活性矩阵（stub judge 判 advancing
        # → extend）。
        late = self._act(sup, run_file, extensions_used=0,
                         started_at=time.time() - 7500,
                         judge=lambda *a, **k: {"verdict": "advancing",
                                                "evidence": "stub"})
        assert late["action"] == "extend"
        assert "absolute_max" not in str(late.get("reason"))
        # 未发放的对照：同一 elapsed 直接死在 absolute_max 分支
        fresh = self._sup(tmp_path)
        bare = self._act(fresh, run_file, extensions_used=0,
                         started_at=time.time() - 7500)
        assert bare["action"] == "kill"
        assert "absolute_max_seconds cap reached" in bare["reason"]

    def test_turn_count_unavailable_falls_back_to_extension_seconds(self,
                                                                    tmp_path):
        """turn_count 缺省：以 extension_seconds 作每轮代理折算并 clamp 上限。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(self._sup(tmp_path), run_file, turn_count=None)
        assert action["action"] == "extend"
        # 20 × 1800 = 36000 → clamp 到 WRAPUP_GRACE_MAX_SECONDS
        assert action["extension_seconds"] == pytest.approx(3600.0)

    def test_no_grace_when_tasks_not_all_completed(self, tmp_path):
        run_file = _partial_run_file(tmp_path, self.RUN_ID)
        action = self._act(self._sup(tmp_path), run_file)
        assert action["action"] == "kill"
        assert action["reason"] == "extension budget exhausted (2/2)"

    def test_impl_lane_unaffected(self, tmp_path):
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(self._sup(tmp_path), run_file,
                           agent_type="implementer")
        assert action["action"] == "kill"
        assert action["reason"] == "extension budget exhausted (2/2)"

    def test_config_disabled_no_grace(self, tmp_path):
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        action = self._act(self._sup(tmp_path, {"enabled": False}), run_file)
        assert action["action"] == "kill"
        assert action["reason"] == "extension budget exhausted (2/2)"


# ── 3. 两侧共用「是否已发放」状态 ─────────────────────────────────────


class TestSharedGrantedState:
    """design 1.2：轮数侧与墙钟侧共用同一配置开关键与已发放状态。"""

    RUN_ID = "admin-demo-1-a1"

    def test_turn_side_grant_blocks_wallclock_side(self, tmp_path):
        """轮数侧已发放 → 墙钟侧同 run 不再发放（走既有击杀）。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        runner = _turn_runner(
            tmp_path, {"timeout_supervision": _sup_config()["agents"]["timeout_supervision"]})
        sup = LivenessSupervisor(runner)
        first = runner._turn_limit_action(
            run_file, None, self.RUN_ID, TURN_EXTENSION_MAX, None,
            agent_type="administrator", max_turns=800)
        assert first["action"] == "extend"
        second = sup._supervision_deadline_action(
            run_file, "demo", self.RUN_ID,
            started_at=time.time() - 7000, extensions_used=2,
            agent_type="administrator", turn_count=100)
        assert second["action"] == "kill"
        assert second["reason"] == "extension budget exhausted (2/2)"

    def test_state_entry_reachable_and_marked(self, tmp_path):
        """发放标记落 _turn_branch_state[run_id]（共享状态槽单点）。"""
        run_file = _all_completed_run_file(tmp_path, self.RUN_ID)
        runner = _turn_runner(tmp_path)
        runner._turn_limit_action(
            run_file, None, self.RUN_ID, TURN_EXTENSION_MAX, None,
            agent_type="administrator", max_turns=800)
        entry = runner._wrapup_grace_state_entry(self.RUN_ID)
        assert entry.get("wrapup_grace_granted") is True
