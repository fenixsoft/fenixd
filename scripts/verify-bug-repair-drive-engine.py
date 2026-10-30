#!/usr/bin/env python3
"""verify-bug-repair-drive-engine.py（由 drive_engine.py 迁移改名）— CLI 场景驱动脚本：在真实环境中测试 admin.bug_repair_mode 分流。

用法：python3 scripts/verify-bug-repair-drive-engine.py <test_case> <spec_name>

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
import os
import re
import sys
import shutil
import tempfile
import traceback
from contextlib import contextmanager
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

try:
    from core.state_machine import StateMachine
    from core.pm_engine import PMEngine
except Exception as _import_err:
    # repo 定位失败（无 core/ 祖先）或 core 依赖缺失时保持既有失败输出契约：
    # stdout JSON + exit 1（与 main 兜底分支同构），不让驱动方从 stdout 拿到空输入
    print(json.dumps({
        "error": f"{type(_import_err).__name__}: {_import_err}",
        "traceback": traceback.format_exc(),
    }, ensure_ascii=False))
    sys.exit(1)

# ── 内部接口依赖清单（code-review item 14b01a5269cb）────────────────────────
# 本脚本为验证驱动脚本，依赖下述 core 私有接口驱动被测行为；core/pm_engine
# 重构（改名/改签名/组合组件调整）时 MUST 同步维护本清单与下方 facade 帮助函数：
#   1. PMEngine._family（property，core/pm_engine/engine.py，惰性构造
#      FamilyGovernor）→ FamilyGovernor._do_spec_bug_found（实例方法，
#      core/pm_engine/family.py）
#   2. FamilyGovernor._fix_prefix_depth（staticmethod，core/pm_engine/family.py；
#      PMEngine 上另有类级别别名）
#   3. PMEngine._enqueue（core/pm_engine/dispatch/queue.py；用例打桩为 MagicMock）
# 全部私有调用已收敛到 _trigger_bug_found / _fix_depth / _stub_enqueue 三个
# facade 帮助函数，用例只依赖 facade，不直接触碰 engine 私有属性。


def _trigger_bug_found(engine: PMEngine, spec_name: str) -> None:
    """facade：驱动 engine 的 bug-found 处置（收敛 engine._family 私有调用）。"""
    engine._family._do_spec_bug_found(spec_name)


def _fix_depth(engine: PMEngine, name: str) -> int:
    """facade：读取 fix- 前缀族谱深度（收敛 _family._fix_prefix_depth 私有调用）。"""
    return engine._family._fix_prefix_depth(name)


def _stub_enqueue(engine: PMEngine) -> MagicMock:
    """facade：把 engine._enqueue 打桩为 MagicMock 并返回桩（收敛私有属性直读/直写）。"""
    stub = MagicMock()
    engine._enqueue = stub
    return stub


def _setup_project(tmpdir: Path) -> Path:
    """构造最小 fenix 项目：.fenix/ + spec/changes/<name>/tasks.md。"""
    proot = tmpdir / "project"
    (proot / ".fenix").mkdir(parents=True, exist_ok=True)
    # 空 STATE.md（StateMachine 初始化需要）
    (proot / ".fenix" / "STATE.md").write_text("# Fenix Project State\n", encoding="utf-8")
    return proot


@contextmanager
def _case_env(config: dict):
    """收口各用例共同的装配/清理脚手架：建临时目录 → 最小项目 → SM/engine 装配 → 清理。

    产出 (proot, sm, engine)；engine._enqueue 经 _stub_enqueue 打桩。
    异常（含 sys.exit）时仍保证临时目录被清理。
    """
    tmpdir = Path(tempfile.mkdtemp())
    try:
        proot = _setup_project(tmpdir)
        sm = StateMachine(proot / ".fenix" / "STATE.md", MagicMock())
        engine = PMEngine(sm, MagicMock(), config, proot, MagicMock())
        _stub_enqueue(engine)
        yield proot, sm, engine
    finally:
        shutil.rmtree(str(tmpdir), ignore_errors=True)


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


def _first_round(engine: PMEngine, sm: StateMachine, proot: Path, spec_name: str):
    _make_buggy_spec(sm, spec_name)
    _write_tasks(proot, spec_name)

    _trigger_bug_found(engine, spec_name)

    entry = sm.read_one(spec_name) or {}
    txt = (proot / "spec" / "changes" / spec_name / "tasks.md").read_text(encoding="utf-8")
    return {
        "rounds": int(entry.get("_verify_fail_rounds", 0)),
        "status": entry.get("status"),
        "fix_spawned": sm.read_one(f"fix-{spec_name}") is not None,
        "has_verify_section": "## 验证修复" in txt,
    }


def test_first_round(spec_name: str):
    with _case_env({}) as (proot, sm, engine):
        result = _first_round(engine, sm, proot, spec_name)
        print(json.dumps(result, ensure_ascii=False))


def test_second_round(spec_name: str):
    with _case_env({}) as (proot, sm, engine):
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        sm.update_spec(spec_name, {"_verify_fail_rounds": 1, "status": "bug-found"})

        _trigger_bug_found(engine, spec_name)

        entry = sm.read_one(spec_name) or {}
        print(json.dumps({
            "rounds": int(entry.get("_verify_fail_rounds", 0)),
            "status": entry.get("status"),
            "depth": _fix_depth(engine, spec_name),
            "fix_spawned": sm.read_one(f"fix-{spec_name}") is not None,
        }, ensure_ascii=False))


def test_derive_loop(spec_name: str):
    with _case_env({"admin": {"bug_repair_mode": "derive"}}) as (proot, sm, engine):
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        _trigger_bug_found(engine, spec_name)

        fix_name = f"fix-{spec_name}"
        # read_one 快照语义（StateMachine.read_one → StateParser.parse 每次从
        # STATE.md 重新解析、返回新 dict，非活引用）：此处读出的 status 是
        # spawn 时刻状态，下方 update/闭环不会改写本值（item ba354c4abf9f）
        fix_entry = sm.read_one(fix_name) or {}
        if not fix_entry:
            # 失败输出契约统一带 case 归因（code-review item 1752ce00a480，
            # 与 restart-persist/hot-switch/main 兜底同款）
            print(json.dumps({"case": "derive-loop",
                              "fix_spawned": False, "reverified": False,
                              "error": "fix spec not created"}, ensure_ascii=False))
            sys.exit(1)

        # 模拟子 fix 完成 → 闭环
        sm.update_spec(fix_name, {"status": "done"})
        engine._on_spec_done(fix_name)
        parent = sm.read_one(spec_name) or {}
        print(json.dumps({
            "fix_spawned": True,
            "fix_status_at_spawn": fix_entry.get("status"),
            "reverified": parent.get("status") == "implemented",
            "parent_status": parent.get("status"),
        }, ensure_ascii=False))


def test_third_round(spec_name: str):
    with _case_env({}) as (proot, sm, engine):
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        sm.update_spec(spec_name, {"_verify_fail_rounds": 2, "status": "bug-found"})

        _trigger_bug_found(engine, spec_name)

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


def test_restart_persist(spec_name: str):
    with _case_env({}) as (proot, sm, engine):
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)
        _trigger_bug_found(engine, spec_name)

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
        _stub_enqueue(engine2)
        _trigger_bug_found(engine2, spec_name)

        entry_after = sm2.read_one(spec_name) or {}
        print(json.dumps({
            "rounds": int(entry_after.get("_verify_fail_rounds", 0)),
            "status": entry_after.get("status"),
        }, ensure_ascii=False))


def test_hot_switch(spec_name: str):
    # Phase 1: derive 模式（config 由 _case_env 装配进 engine）
    with _case_env({"admin": {"bug_repair_mode": "derive"}}) as (proot, sm, engine):
        _make_buggy_spec(sm, spec_name)
        _write_tasks(proot, spec_name)

        _trigger_bug_found(engine, spec_name)
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
        # 重新打桩取代原 reset_mock()：新 MagicMock 同样清空 Phase 1 的调用
        # 记录，且不再直读 engine._enqueue 私有属性（item 14b01a5269cb）
        _stub_enqueue(engine)

        _trigger_bug_found(engine, spec_name)
        entry = sm.read_one(spec_name) or {}

        print(json.dumps({
            "fix_spawned_first": fix_spawned_first,
            "fix_spawned_after_switch": sm.read_one(f"fix-{spec_name}") is not None,
            "status_after_switch": entry.get("status"),
            "rounds_after_switch": int(entry.get("_verify_fail_rounds", 0)),
        }, ensure_ascii=False))


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
        # 动态取当前脚本名：文件已由 drive_engine.py 改名，硬编码旧名会在
        # 下次改名时再次漂移
        print(json.dumps({"error": f"usage: {os.path.basename(sys.argv[0])} <case> <spec>"}, ensure_ascii=False))
        sys.exit(1)
    case, spec = sys.argv[1], sys.argv[2]
    if case not in COMMANDS:
        print(json.dumps({"error": f"unknown case: {case}", "cases": list(COMMANDS)}, ensure_ascii=False))
        sys.exit(1)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", spec):
        # spec_name 会被直接拼进 spec/changes/<name>：白名单拦截斜杠、.. 等越界路径
        print(json.dumps({"error": f"invalid spec name: {spec}"}, ensure_ascii=False))
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
