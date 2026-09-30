#!/usr/bin/env python3
"""drive_engine.py — CLI 场景驱动脚本：在真实环境中测试 admin.bug_repair_mode 分流。

用法：python3 drive_engine.py <test_case> <spec_name>

test_case:
  first-round       — 首次失败 inplace（spec_name 首次 bug-found）
  second-round      — 二次失败递增（spec_name 已 fail_rounds=1）
  derive-loop       — derive 模式派生子 fix + 子完成后闭环重验
  third-round       — 三轮冻结升级（spec_name 已 fail_rounds=2）
  restart-persist   — 计数器跨重启持久（打回后重建 SM 再打回）
  hot-switch        — 热切换：derive 打回一次 → config 置空 → inplace 打回

输出：JSON 到 stdout，包含各断言所需字段。
"""

import json
import sys
import shutil
import tempfile
import traceback
from pathlib import Path
from unittest.mock import MagicMock

# 定位 repo 根（脚本可能位于 scripts/ 或 .history/bug-repair-verify/ 等位置：
# 向上查找含 core/ 目录的祖先）
def _find_repo_root(start: Path) -> str:
    cur = start
    while cur != cur.parent:
        if (cur / "core").is_dir():
            return str(cur)
        cur = cur.parent
    return str(start)

REPO_ROOT = _find_repo_root(Path(__file__).resolve().parent)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.state_machine import StateMachine
from core.pm_engine import PMEngine


def _setup_project(tmpdir: Path) -> Path:
    """构造最小 fenix 项目：.fenix/ + spec/changes/<name>/tasks.md。"""
    proot = tmpdir / "project"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    # 空 STATE.md（StateMachine 初始化需要）
    (proot / ".fenix" / "STATE.md").write_text("# Fenix Project State\n", encoding="utf-8")
    return proot


def _write_tasks(proot: Path, name: str):
    spec_dir = proot / "spec" / "changes" / name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text(
        "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 x\n", encoding="utf-8"
    )


def _make_buggy_spec(sm: StateMachine, name: str):
    sm.add_spec(name, {"priority": 5})
    for s in ("ready", "implementing", "implemented", "testing", "bug-found"):
        sm.transition(name, s)


def _first_round(sm: StateMachine, proot: Path, spec_name: str, config: dict):
    engine = PMEngine(sm, MagicMock(), config, proot, MagicMock())
    engine._enqueue = MagicMock()
    _make_buggy_spec(sm, spec_name)
    _write_tasks(proot, spec_name)

    engine._family._do_spec_bug_found(spec_name)

    entry = sm.read_one(spec_name) or {}
    txt = (proot / "spec" / "changes" / spec_name / "tasks.md").read_text(encoding="utf-8")
    return {
        "rounds": int(entry.get("_verify_fail_rounds", 0)),
        "status": entry.get("status"),
        "fix_spawned": sm.read_one(f"fix-{spec_name}") is not None,
        "has_verify_section": "## 验证修复" in txt,
    }


def test_first_round(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        result = _first_round(sm, proot, spec_name, {})
        print(json.dumps(result, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_second_round(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        sm.update_spec(spec_name, {"_verify_fail_rounds": 1, "status": "bug-found"})

        engine = PMEngine(sm, MagicMock(), {}, proot, MagicMock())
        engine._enqueue = MagicMock()
        engine._family._do_spec_bug_found(spec_name)

        entry = sm.read_one(spec_name) or {}
        print(json.dumps({
            "rounds": int(entry.get("_verify_fail_rounds", 0)),
            "status": entry.get("status"),
            "depth": engine._family._fix_prefix_depth(spec_name),
            "fix_spawned": sm.read_one(f"fix-{spec_name}") is not None,
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_derive_loop(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        config = {"admin": {"bug_repair_mode": "derive"}}
        engine = PMEngine(sm, MagicMock(), config, proot, MagicMock())
        engine._enqueue = MagicMock()

        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        engine._family._do_spec_bug_found(spec_name)

        fix_name = f"fix-{spec_name}"
        fix_entry = sm.read_one(fix_name) or {}
        if not fix_entry:
            print(json.dumps({"fix_spawned": False, "reverified": False,
                              "error": "fix spec not created"}, ensure_ascii=False))
            sys.exit(1)

        # 模拟子 fix 完成 → 闭环
        sm.update_spec(fix_name, {"status": "done"})
        engine._on_spec_done(fix_name)
        parent = sm.read_one(spec_name) or {}
        print(json.dumps({
            "fix_spawned": True,
            "fix_status": fix_entry.get("status"),
            "reverified": parent.get("status") == "implemented",
            "parent_status": parent.get("status"),
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_third_round(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        engine = PMEngine(sm, MagicMock(), {}, proot, MagicMock())
        engine._enqueue = MagicMock()

        _make_buggy_spec(sm, spec_name)
        sm.update_spec(spec_name, {"_verify_fail_rounds": 2, "status": "bug-found"})

        engine._family._do_spec_bug_found(spec_name)

        entry = sm.read_one(spec_name) or {}
        # 升级闸门告警落盘于 .fenix/admin_alerts.json（AdminStore 真实读取）
        from core.admin_store import AdminStore
        store = AdminStore(proot, MagicMock())
        alerts = [a for a in store.read_all()
                  if a.get("signal_type") == "verify_fail_escalation"
                  and a.get("spec") == spec_name]

        print(json.dumps({
            "rounds": int(entry.get("_verify_fail_rounds", 0)),
            "status": entry.get("status"),
            "alerted": len(alerts) > 0,
            "alert_count": len(alerts),
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_restart_persist(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        engine = PMEngine(sm, MagicMock(), {}, proot, MagicMock())
        engine._enqueue = MagicMock()

        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        engine._family._do_spec_bug_found(spec_name)

        # 模拟重启：重建 SM + engine
        sm2 = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        entry_before = sm2.read_one(spec_name) or {}
        if int(entry_before.get("_verify_fail_rounds", 0)) != 1:
            print(json.dumps({
                "error": "counter must persist",
                "case": "restart-persist",
                "rounds": int(entry_before.get("_verify_fail_rounds", 0)),
            }, ensure_ascii=False))
            sys.exit(1)

        engine2 = PMEngine(sm2, MagicMock(), {}, proot, MagicMock())
        engine2._enqueue = MagicMock()
        engine2._family._do_spec_bug_found(spec_name)

        entry_after = sm2.read_one(spec_name) or {}
        print(json.dumps({
            "rounds": int(entry_after.get("_verify_fail_rounds", 0)),
            "status": entry_after.get("status"),
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


def test_hot_switch(spec_name: str):
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        # Phase 1: derive 模式
        engine = PMEngine(sm, MagicMock(), {"admin": {"bug_repair_mode": "derive"}}, proot, MagicMock())
        engine._enqueue = MagicMock()
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)

        engine._family._do_spec_bug_found(spec_name)
        fix_spawned_first = sm.read_one(f"fix-{spec_name}") is not None
        if not fix_spawned_first:
            print(json.dumps({
                "error": "fix spec not created in Phase 1",
                "case": "hot-switch",
                "fix_spawned_first": False,
            }, ensure_ascii=False))
            sys.exit(1)

        # Phase 2: 切换到 inplace（清空 config）
        engine.config = {}
        sm.update_spec(spec_name, {"status": "bug-found"})
        sm.remove_spec(f"fix-{spec_name}")
        engine._enqueue.reset_mock()

        engine._family._do_spec_bug_found(spec_name)
        entry = sm.read_one(spec_name) or {}

        print(json.dumps({
            "fix_spawned_first": fix_spawned_first,
            "fix_spawned_after_switch": sm.read_one(f"fix-{spec_name}") is not None,
            "status_after_switch": entry.get("status"),
            "rounds_after_switch": int(entry.get("_verify_fail_rounds", 0)),
        }, ensure_ascii=False))
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


COMMANDS = {
    "first-round": test_first_round,
    "second-round": test_second_round,
    "derive-loop": test_derive_loop,
    "third-round": test_third_round,
    "restart-persist": test_restart_persist,
    "hot-switch": test_hot_switch,
}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(json.dumps({"error": "usage: drive_engine.py <case> <spec>"}, ensure_ascii=False))
        sys.exit(1)
    case, spec = sys.argv[1], sys.argv[2]
    if case not in COMMANDS:
        print(json.dumps({"error": f"unknown case: {case}", "cases": list(COMMANDS)}, ensure_ascii=False))
        sys.exit(1)
    try:
        COMMANDS[case](spec)
    except Exception as e:
        # 用例内意外异常兜底：失败路径与既有守卫分支同构（stdout JSON + exit 1）
        print(json.dumps({
            "error": f"{type(e).__name__}: {e}",
            "case": case,
            "traceback": traceback.format_exc(),
        }, ensure_ascii=False))
        sys.exit(1)
