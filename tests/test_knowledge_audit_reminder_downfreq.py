"""升级聚合提醒降频单测（evo-add-knowledge-audit-reminder-downfreq 任务 2.1/2.3）。

覆盖：
- 同集 7 天窗口内跳过：upsert 不发生（行内容停留旧值、零写盘、零提交、
  log.info 跳过留痕）；
- 集变化立即拍：新增 escalated 旁路降频，行含下次提醒尾注、状态键刷新；
- 清零旁路：escalated 清空照常纯清理摘行，两状态键重置；
- 到期恢复拍：last_escalated_reminder_date 回拨 ≥7 天后恢复一拍并刷新；
- fail-open：状态键缺失 / 损坏 / 未来日期 / 集合形状不符 → 应拍不抛异常；
- 写失败不静默：upsert 抛 OSError 或 strict 解码失败（返回 False）→ 状态键
  不刷新，下一轮仍重拍；
- 在场性兜底：聚合行被外部删除而判定本应跳过 → 强制拍重建；
- 纯函数直测：判定序与 fail-open 各分支（不经 run_audit 装置）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import knowledge_audit as ka


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


class ListLogger:
    def __init__(self):
        self.lines: list[tuple[str, str]] = []

    def info(self, comp, msg):
        self.lines.append(("info", msg))

    def warning(self, comp, msg):
        self.lines.append(("warning", msg))

    def error(self, comp, msg):
        self.lines.append(("error", msg))

    def all_text(self) -> str:
        return "\n".join(msg for _, msg in self.lines)


def _pair_page(name: str, subject: str, value: int) -> str:
    return (
        f"<!-- knowledge: capability={name} rev=1 sources=arc-good -->\n"
        f"# {name}\n\n## 规则\n\n- {subject}:{value} 秒。\n\n## 溯源\n\n- spec/archive/arc-good\n"
    )


def _make_proj(root: Path, pairs: int = 1) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "spec" / "archive" / "arc-good").mkdir(parents=True)
    (root / "spec" / "archive" / "arc-good" / "proposal.md").write_text("x\n")
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    kdom.mkdir(parents=True)
    for k in range(pairs):
        idx = f"{k:02d}"
        (kdom / f"p{idx}a.md").write_text(
            _pair_page(f"p{idx}a", f"主题{idx}", 300), encoding="utf-8"
        )
        (kdom / f"p{idx}b.md").write_text(
            _pair_page(f"p{idx}b", f"主题{idx}", 600), encoding="utf-8"
        )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


class FakeCore:
    def __init__(self, root: Path):
        self.root = root
        self.commit_calls: list = []

    def validate_knowledge(self, project_root):
        return []

    def commit_knowledge(self, project_root, paths, message) -> bool:
        self.commit_calls.append((list(paths), message))
        return ka.commit_pathspec(project_root, paths, message)


@pytest.fixture
def install_core(monkeypatch):
    def _install(core_obj):
        mod = types.ModuleType("core.knowledge")
        mod.validate_knowledge = core_obj.validate_knowledge
        mod.commit_knowledge = core_obj.commit_knowledge
        import core as core_pkg

        monkeypatch.setitem(sys.modules, "core.knowledge", mod)
        monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
        return core_obj

    return _install


def _findings_by_fp(root: Path) -> dict[str, dict]:
    pages = ka._collect_pages(root)
    return {ka._finding_fingerprint(f): f for f in ka._scan_semantic(pages)}


def _seed_escalated(root: Path, fps, first_seen: str, review_rounds: int = 2) -> None:
    findings = _findings_by_fp(root)
    ledger = ka._load_findings_ledger(root)
    for fp in fps:
        f = findings[fp]
        ledger[fp] = {
            "kind": f["kind"],
            "pages": [f["a"]["page"], f["b"]["page"]],
            "rules": [f["a"]["rule"], f["b"]["rule"]],
            "page_hashes": {},
            "verdicts": [],
            "status": "escalated",
            "first_seen": first_seen,
            "updated_at": ka._today(),
            "review_rounds": review_rounds,
        }
    ka._save_findings_ledger(root, ledger)


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _todo_lines(root: Path) -> list[str]:
    todo = root / ".fenix" / "todo.md"
    if not todo.exists():
        return []
    return todo.read_text(encoding="utf-8").splitlines()


def _agg_lines(root: Path) -> list[str]:
    return [ln for ln in _todo_lines(root) if "audit 疑点升级待人工" in ln]


def _read_state(root: Path) -> dict:
    spath = root / ".fenix" / "knowledge_audit_state.json"
    if not spath.exists():
        return {}
    return json.loads(spath.read_text(encoding="utf-8"))


def _write_state(root: Path, state: dict) -> None:
    spath = root / ".fenix" / "knowledge_audit_state.json"
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _todo_mtime_ns(root: Path) -> int:
    return os.stat(root / ".fenix" / "todo.md").st_mtime_ns


# ── 纯函数直测（判定序与 fail-open 各分支） ──────────────────────────────


def test_pure_due_judgment_order():
    """判定序：空集清理旁路 / 集变化立即拍 / 同集窗口内跳过 / 到期恢复拍。"""
    today = ka._today()
    near = _days_ago(6)
    expired = _days_ago(8)
    assert ka._escalated_reminder_due({}, {}, today) is True  # 空集 → 清理旁路
    state = {"last_escalated_reminder_date": near, "last_escalated_set": ["a", "b"]}
    assert ka._escalated_reminder_due({"a": {}, "b": {}}, state, today) is False  # 同集窗口内
    assert ka._escalated_reminder_due({"a": {}, "c": {}}, state, today) is True  # 集变化
    assert ka._escalated_reminder_due({"a": {}}, state, today) is True  # 集变化（减少）
    state8 = {"last_escalated_reminder_date": expired, "last_escalated_set": ["a"]}
    assert ka._escalated_reminder_due({"a": {}}, state8, today) is True  # 到期恢复拍
    state7 = {"last_escalated_reminder_date": _days_ago(7), "last_escalated_set": ["a"]}
    assert ka._escalated_reminder_due({"a": {}}, state7, today) is True  # 恰 7 天 = 到期


def test_pure_due_failopen_shapes():
    """fail-open：键缺失 / 非列表 / 未排序 / 非法日期 / 未来日期 → 应拍不抛。"""
    today = ka._today()
    assert ka._escalated_reminder_due({"a": {}}, {}, today) is True
    assert ka._escalated_reminder_due({"a": {}}, {"last_escalated_set": "bad"}, today) is True
    assert ka._escalated_reminder_due({"a": {}}, {"last_escalated_set": 7}, today) is True
    assert ka._escalated_reminder_due({"a": {}}, {"last_escalated_set": ["a", None]}, today) is True
    # 未排序（写入侧恒 sorted，未排序 = 手编 / 外来损坏态）→ 应拍
    assert (
        ka._escalated_reminder_due(
            {"a": {}, "b": {}},
            {"last_escalated_set": ["b", "a"], "last_escalated_reminder_date": _days_ago(1)},
            today,
        )
        is True
    )
    for bad_date in ("not-a-date", "", None, "2099-12-31", 20261127):
        state = {"last_escalated_set": ["a"], "last_escalated_reminder_date": bad_date}
        assert ka._escalated_reminder_due({"a": {}}, state, today) is True, bad_date


def test_pure_next_remind_date():
    """尾注日 = 本地自然日 +7；解析失败返回空串（不追加尾注）。"""
    assert ka._next_remind_date("2026-11-27") == "2026-12-04"
    assert ka._next_remind_date("junk") == ""


def test_line_tail_only_when_requested():
    """行文案尾注：None 不追加（既有文案逐字节稳定），非 None 追加尾注。"""
    escalated = {"fp1": {}}
    base = ka._escalated_todo_line(escalated)
    assert "下次重复提醒" not in base
    with_tail = ka._escalated_todo_line(escalated, next_remind_date="2026-12-04")
    assert with_tail.startswith(base)
    assert with_tail.endswith("（下次重复提醒不早于 2026-12-04）")
    assert ka._escalated_todo_line({}) == ""  # 空台账清理语义不变


# ── run_audit 收尾装置级四态 ─────────────────────────────────────────────


def test_same_set_within_window_skips_upsert(tmp_path, install_core):
    """同集 7 天窗口内跳过：upsert 不发生——行内容停留旧值（龄期文案不刷新）、
    todo.md 零写盘（mtime 不变）、零提交，log.info 跳过留痕。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    core = install_core(FakeCore(root))
    log = ListLogger()
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))

    ka.run_audit(root, spawn=lambda p, rid: "ok", logger=log)
    lines = _agg_lines(root)
    assert len(lines) == 1
    assert "最长龄期 3 天" in lines[0]
    first_line = lines[0]  # 首跑带下次提醒尾注（due=True 路径）
    assert "下次重复提醒不早于" in first_line
    state = _read_state(root)
    assert state["last_escalated_reminder_date"] == ka._today()
    assert state["last_escalated_set"] == [fp]
    mtime_before = _todo_mtime_ns(root)

    # 第二跑前龄期推进 6 天（台账变、escalated 指纹集不变；6 < 7 不触发
    # disputed 注记段，提交面只剩 todo 车道）：若降频未生效，upsert 会整行
    # 替换为「最长龄期 6 天」；降频生效则行停留旧值「3 天」。
    ledger = ka._load_findings_ledger(root)
    ledger[fp]["first_seen"] = _days_ago(6)
    ka._save_findings_ledger(root, ledger)

    log2 = ListLogger()
    ka.run_audit(root, spawn=lambda p, rid: "ok", logger=log2)
    lines = _agg_lines(root)
    assert len(lines) == 1
    assert lines[0] == first_line  # 集合指纹不含龄期：行停留首跑旧值（零写盘）
    assert _todo_mtime_ns(root) == mtime_before  # 零写盘（mtime 不变 = 无 upsert）
    assert "降频跳过" in log2.all_text()  # log.info 留痕（含下次提醒日）
    state2 = _read_state(root)
    assert state2["last_escalated_reminder_date"] == ka._today()  # 状态键不动
    assert state2["last_escalated_set"] == [fp]

    # 到期恢复拍（回拨 ≥7 天）→ 行整行替换为新龄期 + 下次提醒尾注（衔接 2.1 第四态）
    state2["last_escalated_reminder_date"] = _days_ago(8)
    _write_state(root, state2)
    log3 = ListLogger()
    ka.run_audit(root, spawn=lambda p, rid: "ok", logger=log3)
    lines = _agg_lines(root)
    assert len(lines) == 1
    assert "最长龄期 6 天" in lines[0]
    assert f"（下次重复提醒不早于 {ka._next_remind_date(ka._today())}）" in lines[0]
    state3 = _read_state(root)
    assert state3["last_escalated_reminder_date"] == ka._today()  # 两状态键刷新
    assert state3["last_escalated_set"] == [fp]


def test_set_change_shoots_immediately(tmp_path, install_core):
    """集变化立即拍（减少方向）：escalated 条目减少旁路降频当日拍，行 count
    更新且含下次提醒尾注，状态键刷新为新集。

    装置注记：以「减少」为集变化方向——被 run 复核消费过的候选（exempt +
    page_hashes 入账）经 _save_findings_ledger 合并写后以盘上条目为准，事后
    种回 escalated 会被盘上 exempt 条目覆盖，故「新增」方向在装置级不可稳定
    构造（纯函数层 test_pure_due_judgment_order 已覆盖新增分支）。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=2)
    install_core(FakeCore(root))
    fps = list(_findings_by_fp(root))
    _seed_escalated(root, fps, first_seen=_days_ago(3))

    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert "2 条待人工仲裁" in _agg_lines(root)[0]

    # 第二跑前人工删除一条 escalated（同日，窗口内本应跳过）→ 集变化立即拍
    ledger = ka._load_findings_ledger(root)
    del ledger[fps[1]]
    ka._save_findings_ledger(root, ledger, deleted_fingerprints={fps[1]})
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    lines = _agg_lines(root)
    assert len(lines) == 1
    assert "1 条待人工仲裁" in lines[0]
    assert f"（下次重复提醒不早于 {ka._next_remind_date(ka._today())}）" in lines[0]
    state = _read_state(root)
    assert state["last_escalated_set"] == [fps[0]]
    assert state["last_escalated_reminder_date"] == ka._today()


def test_clear_bypasses_window_and_resets_keys(tmp_path, install_core):
    """清零旁路：escalated 清空照常纯清理摘除聚合行（不受降频抑制），两状态
    键重置（恢复后首拍不被陈旧集误跳过）。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert len(_agg_lines(root)) == 1
    assert "last_escalated_set" in _read_state(root)

    # 台账 escalated 清零（人工删条目）：同日（窗口内）仍照常清理
    ledger = ka._load_findings_ledger(root)
    del ledger[fp]
    ka._save_findings_ledger(root, ledger, deleted_fingerprints={fp})
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert _agg_lines(root) == []  # 纯清理执行（降频不得抑制摘除）
    state = _read_state(root)
    assert "last_escalated_reminder_date" not in state  # 两键重置
    assert "last_escalated_set" not in state
    # 双保险的纯函数面：两键缺失 → 后续任何集的首拍必应拍（装置级「恢复后
    # 首拍」需种回 escalated 条目，被合并写以盘上 exempt 条目覆盖，不可稳定
    # 构造，见 test_set_change_shoots_immediately 装置注记）。
    assert ka._escalated_reminder_due({"x": {}}, state, ka._today()) is True


def test_missing_row_forces_shoot(tmp_path, install_core):
    """在场性兜底：聚合行被外部删除而判定本应跳过（同集窗口内）→ 强制拍重建，
    不等 7 天窗口结束。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert len(_agg_lines(root)) == 1

    # 人工删除聚合行（todo.md 重写去行，状态键保持同集同日）
    todo = root / ".fenix" / "todo.md"
    kept = [ln for ln in todo.read_text(encoding="utf-8").splitlines()
            if not ln.startswith(f"- {ka.TODO_ESCALATED_AGG_PREFIX}")]
    todo.write_text("\n".join(kept).rstrip("\n") + "\n", encoding="utf-8")
    assert _agg_lines(root) == []

    ka.run_audit(root, spawn=lambda p, rid: "ok")
    lines = _agg_lines(root)
    assert len(lines) == 1  # 强制拍重建
    assert f"（下次重复提醒不早于 {ka._next_remind_date(ka._today())}）" in lines[0]
    state = _read_state(root)
    assert state["last_escalated_reminder_date"] == ka._today()
    assert state["last_escalated_set"] == [fp]


# ── fail-open 与写失败（任务 2.3） ───────────────────────────────────────


@pytest.mark.parametrize(
    "state_mut",
    [
        {},  # 两键全缺失
        {"last_escalated_set": "not-a-list"},  # 集合非列表
        {"last_escalated_set": {"a": 1}},  # dict 形状不符
        {  # 未排序（写入侧恒 sorted）
            "last_escalated_set": ["b", "a"],
            "last_escalated_reminder_date": None,
        },
    ],
)
def test_failopen_corrupt_state_shoots(tmp_path, install_core, state_mut):
    """状态键缺失 / 损坏 / 形状不符 → 判定应拍（行落盘 + 状态键刷新），不抛
    异常不阻断体检收尾。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    _write_state(root, {"last_audit_date": _days_ago(9), **state_mut})

    ka.run_audit(root, spawn=lambda p, rid: "ok")  # 不抛
    lines = _agg_lines(root)
    assert len(lines) == 1  # 应拍
    state = _read_state(root)
    assert state["last_escalated_set"] == [fp]  # 状态键以应拍形态刷新
    assert state["last_escalated_reminder_date"] == ka._today()


def test_failopen_future_date_shoots(tmp_path, install_core):
    """状态日期晚于 today（时钟回拨 / 手编）→ 应拍。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    _write_state(
        root,
        {
            "last_escalated_set": [fp],
            "last_escalated_reminder_date": "2099-12-31",
        },
    )
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert len(_agg_lines(root)) == 1
    assert _read_state(root)["last_escalated_reminder_date"] == ka._today()


def _seed_reminded_state(root: Path, fp) -> None:
    _write_state(
        root,
        {
            "last_escalated_set": [fp],
            "last_escalated_reminder_date": ka._today(),
        },
    )


def _assert_keys_unrefreshed(root: Path, stale: dict) -> None:
    """断言两状态键未刷新（其余键如 last_scale 由 run_audit 收尾照常落盘，
    不在本断言范围）。"""
    state = _read_state(root)
    assert state.get("last_escalated_reminder_date") == stale["last_escalated_reminder_date"]
    assert state.get("last_escalated_set") == stale["last_escalated_set"]


def test_upsert_oserror_keeps_state(tmp_path, install_core, monkeypatch):
    """upsert 抛 OSError → fail-open WARNING 不掀翻收尾，状态键不刷新（下一
    轮仍重拍）。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    _seed_reminded_state(root, fp)
    stale = _read_state(root)

    def boom(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(ka, "upsert_todo_line", boom)
    log = ListLogger()
    ka.run_audit(root, spawn=lambda p, rid: "ok", logger=log)  # OSError 被吸收
    assert "upsert 失败" in log.all_text()
    _assert_keys_unrefreshed(root, stale)  # 写失败不得换来 7 天静默


def test_upsert_false_keeps_state(tmp_path, install_core, monkeypatch):
    """upsert 返回 False（strict 解码失败等零写盘路径）→ 状态键不刷新。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    _seed_reminded_state(root, fp)
    stale = _read_state(root)

    monkeypatch.setattr(ka, "upsert_todo_line", lambda *a, **kw: False)
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    _assert_keys_unrefreshed(root, stale)


def test_state_write_oserror_keeps_state(tmp_path, install_core, monkeypatch):
    """upsert 写盘成功但状态键回写抛 OSError → 降级 WARNING，键不刷新（下一
    轮仍重拍）。patch 按调用序只让第一次 _write_state（escalated 段回写）抛
    OSError——后续 last_scale 收尾回写照常执行，不掀翻收尾。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    _seed_reminded_state(root, fp)
    stale = _read_state(root)

    real_write = ka._write_state
    calls = {"n": 0}

    def flaky(project_root, state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("state write failed")
        return real_write(project_root, state)

    monkeypatch.setattr(ka, "_write_state", flaky)
    log = ListLogger()
    ka.run_audit(root, spawn=lambda p, rid: "ok", logger=log)
    assert "状态键回写失败" in log.all_text()
    _assert_keys_unrefreshed(root, stale)
