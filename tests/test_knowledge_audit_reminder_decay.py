"""escalated 聚合提醒降频节拍（evo-knowledge-audit-reminder-frequency-decay）。

覆盖 tasks.md 2.1 六形态（测试名前缀对应形态编号）：
1. 未超龄（max_age_days ≤ stale_days）：每日一拍；
2. 超龄零消费降频：间隔内 upsert 不调用且聚合行保持原样，拍出文案附降频注记；
3. 降频期间新增 escalated 指纹：当日应拍（集合变化旁路）；
4. 消费后恢复每日拍、stale_days 后重新降频（consume_arbitration 记账 +
   集合减少视同消费活动的旁路）；
5. escalated 全部消费：当日纯清理摘除残留行并复位三键；
6. 状态键缺失/损坏、upsert 失败（OSError / 幂等 False）：本拍应拍不抑制提醒，
   且失败不刷新最近提醒日期（下轮重试）。

夹具取单能力页知识目录（规则主题互异 → 语义初筛零候选，转写 spawn 断言不被
触达），escalated 台账条目直接写入 findings 台账（指纹不命中任何扫描候选，
语义循环零派发），``ka._today`` 打桩到固定日期控制龄期与间隔。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from core import knowledge_audit as ka

FIXED_TODAY = "2026-11-27"
PAGE_REL = "spec/knowledge/domains/dom-a/alpha.md"
FP_A = "aaaa1111aaaa2222aaaa3333aaaa4444"
FP_B = "bbbb1111bbbb2222bbbb3333bbbb4444"
FP_C = "cccc1111cccc2222cccc3333cccc4444"
OLD_FIRST_SEEN = "2026-10-01T09:00:00"  # 龄期 57 天 > 缺省 stale_days 7
RECENT_FIRST_SEEN = "2026-11-24T09:00:00"  # 龄期 3 天 ≤ 7（未超龄形态）
# 与 _escalated_todo_line 既有文案逐字节一致的历史聚合行（龄期文案为旧值）
OLD_AGG_LINE = (
    "- audit 疑点升级待人工（聚合）：1 条待人工仲裁（最长龄期 40 天），请人工按指纹在 "
    ".fenix/knowledge_audit_arbitration.json 登记仲裁决定（fingerprint/decision/"
    "decided_at/note），框架检查点自动消费后恢复自动复核"
)
DECAY_NOTE = "（已降频为每周一拍、欠账仍在）"


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

    def messages(self, level=None):
        return [m for lv, m in self.lines if level is None or lv == level]


PAGE_ALPHA = """<!-- knowledge: capability=alpha rev=1 sources=arc-good -->
# alpha

## 规则

- 超时:300 秒。
- 禁用明文日志输出。

## 溯源

- spec/archive/arc-good
"""


class FakeCore:
    def __init__(self, root: Path):
        self.root = root
        self.commit_calls: list = []

    def _commit(self, project_root, paths, message) -> bool:
        self.commit_calls.append((list(paths), message))
        return ka.commit_pathspec(project_root, paths, message)

    def validate_knowledge(self, project_root):
        return []


@pytest.fixture
def proj(tmp_path):
    """单能力页知识目录（无 ADR 目录、规则主题互异）：机械/语义零病灶，
    run_audit 收尾只有 escalated 节拍门控分支会触碰 todo 聚合行。"""
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "spec" / "archive" / "arc-good").mkdir(parents=True)
    (root / "spec" / "archive" / "arc-good" / "proposal.md").write_text("x\n")
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    kdom.mkdir(parents=True)
    (root / "spec" / "knowledge" / "index.md").write_text(
        "# 真相源\n\n- [alpha](domains/dom-a/alpha.md)\n"
    )
    (kdom / "alpha.md").write_text(PAGE_ALPHA, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


@pytest.fixture
def install_core(monkeypatch):
    core_obj = None

    def _install(core_obj_):
        nonlocal core_obj
        core_obj = core_obj_
        mod = types.ModuleType("core.knowledge")
        mod.validate_knowledge = core_obj.validate_knowledge
        mod.commit_knowledge = core_obj._commit
        import core as core_pkg

        monkeypatch.setitem(sys.modules, "core.knowledge", mod)
        monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
        return core_obj

    return _install


@pytest.fixture
def no_spawn():
    """语义循环 spawn 断言：零候选夹具下任何派发都是意外。"""

    def _spawn(prompt, run_id):
        raise AssertionError(f"意外的语义转写派发：run_id={run_id}")

    return _spawn


def _entry(first_seen: str = OLD_FIRST_SEEN, fp: str = FP_A) -> dict:
    return {
        "status": "escalated",
        "first_seen": first_seen,
        "pages": [PAGE_REL],
        "rule": "超时:300 秒。",
    }


def _seed_ledger(root: Path, entries: dict) -> None:
    path = root / ka.FINDINGS_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _seed_state(root: Path, **kv) -> None:
    path = root / ka.STATE_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
    existing.update(kv)
    path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")


def _read_state(root: Path) -> dict:
    path = root / ka.STATE_RELPATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _seed_todo(root: Path, *lines: str) -> None:
    path = root / ".fenix" / "todo.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_todo(root: Path) -> str:
    path = root / ".fenix" / "todo.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _run_audit(root: Path, install_core, no_spawn, log):
    install_core(FakeCore(root))
    return ka.run_audit(root, logger=log, spawn=no_spawn, config={})


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(ka, "_today", lambda: FIXED_TODAY)
    return FIXED_TODAY


# ── 形态 1：未超龄（max_age_days ≤ stale_days）→ 每日一拍 ────────────────


def test_due_when_not_stale(today):
    """未超龄：空历史状态每日一拍，非降频态。"""
    due, decayed = ka._escalated_reminder_due(
        {FP_A: _entry(RECENT_FIRST_SEEN)}, {}, FIXED_TODAY
    )
    assert (due, decayed) == (True, False)


def test_due_daily_beat_after_consumption(today):
    """形态 4 前半：消费记账在 stale_days 内 → 非降频态每日一拍
    （即使距上次提醒不足阈值也不跳拍）。"""
    state = {
        ka.STATE_KEY_ESCALATED_CONSUMED: "2026-11-24",  # 3 天前（≤ 7）
        ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
        ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
    }
    due, decayed = ka._escalated_reminder_due(
        {FP_A: _entry()}, state, FIXED_TODAY
    )
    assert (due, decayed) == (True, False)


# ── 形态 2：超龄零消费降频（间隔内跳拍 + 注记拍出） ──────────────────────


def test_skip_within_interval_pure(today):
    """形态 2 纯函数面：超龄 + 零消费历史 + 距上次提醒 1 天 → 跳拍、降频态。"""
    state = {
        ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
        ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
    }
    due, decayed = ka._escalated_reminder_due({FP_A: _entry()}, state, FIXED_TODAY)
    assert (due, decayed) == (False, True)


def test_skip_run_audit_does_not_upsert_and_keeps_line(
    proj, install_core, no_spawn, today, monkeypatch
):
    """形态 2 集成面：跳拍完全不调用 upsert（不写盘不提交），todo 聚合行
    保持旧行原文不被清空，状态三键不刷新，log.info 留痕下次提醒日。"""
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    _seed_todo(proj, OLD_AGG_LINE)
    before = _read_todo(proj)

    calls: list = []

    def _spy(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(ka, "upsert_todo_line", _spy)
    log = ListLogger()
    res = _run_audit(proj, install_core, no_spawn, log)
    assert res["ok"] is True
    assert calls == []  # 完全不调用 upsert
    assert _read_todo(proj) == before  # 聚合行保持原样（不清空不替换）
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_REMINDED] == "2026-11-26"  # 不刷新日期
    assert state[ka.STATE_KEY_ESCALATED_FP_SET] == [FP_A]
    assert any("降频跳过本拍" in m and "2026-12-03" in m for m in log.messages("info"))


def test_decayed_shot_attaches_note_and_refreshes_state(
    proj, install_core, no_spawn, today, monkeypatch
):
    """形态 2 拍出面：距上次提醒 ≥ stale_days → 应拍，文案附降频注记，
    写盘成功后持锁刷新 reminded_date 与指纹集。"""
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-20",  # 7 天前 → 到期
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    _seed_todo(proj, OLD_AGG_LINE)

    captured: list = []

    def _spy(project_root, prefix, line, **kwargs):
        captured.append((prefix, line, kwargs))
        return True

    monkeypatch.setattr(ka, "upsert_todo_line", _spy)
    log = ListLogger()
    res = _run_audit(proj, install_core, no_spawn, log)
    assert res["ok"] is True
    assert len(captured) == 1
    prefix, line, kwargs = captured[0]
    assert prefix == ka.TODO_ESCALATED_AGG_PREFIX
    assert DECAY_NOTE in line  # 降频态拍出附注记
    assert "1 条待人工仲裁" in line
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_REMINDED] == FIXED_TODAY
    assert state[ka.STATE_KEY_ESCALATED_FP_SET] == [FP_A]


def test_daily_shot_has_no_note(proj, install_core, no_spawn, today, monkeypatch):
    """非降频态拍出（消费后每日节拍）文案不附注记。"""
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(proj, **{ka.STATE_KEY_ESCALATED_CONSUMED: "2026-11-24"})
    captured: list = []

    def _spy(project_root, prefix, line, **kwargs):
        captured.append(line)
        return True

    monkeypatch.setattr(ka, "upsert_todo_line", _spy)
    _run_audit(proj, install_core, no_spawn, ListLogger())
    assert len(captured) == 1
    assert DECAY_NOTE not in captured[0]


# ── 形态 3：降频期间新增 escalated 指纹 → 当日应拍 ──────────────────────


def test_new_fingerprint_bypasses_decay(proj, install_core, no_spawn, today, monkeypatch):
    """形态 3：指纹集新增（[A] → [A,B]）旁路降频当日拍出，行内含新计数。"""
    _seed_ledger(proj, {FP_A: _entry(), FP_B: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    captured: list = []

    def _spy(project_root, prefix, line, **kwargs):
        captured.append(line)
        return True

    monkeypatch.setattr(ka, "upsert_todo_line", _spy)
    _run_audit(proj, install_core, no_spawn, ListLogger())
    assert len(captured) == 1
    assert "2 条待人工仲裁" in captured[0]
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_REMINDED] == FIXED_TODAY
    assert sorted(state[ka.STATE_KEY_ESCALATED_FP_SET]) == sorted([FP_A, FP_B])


# ── 形态 4：消费后恢复每日拍、stale_days 后重新降频 ──────────────────────


def test_consume_arbitration_books_beat_state(proj, today):
    """consume_arbitration consumed 非空：记账消费日、清除上次提醒日、指纹集
    同步为消费后余集；消费判定本身不变（台账条目删除）。"""
    _seed_ledger(proj, {FP_A: _entry()})
    arb = proj / ka.ARBITRATION_RELPATH
    arb.parent.mkdir(parents=True, exist_ok=True)
    arb.write_text(
        json.dumps(
            [
                {
                    "fingerprint": FP_A,
                    "decision": "fixed",
                    "decided_at": "2026-11-27T08:00:00",
                    "note": "人工纠偏",
                }
            ]
        ),
        encoding="utf-8",
    )
    res = ka.consume_arbitration(proj, config={})
    assert res["triggered"] is True
    assert res["consumed"] == 1
    ledger = ka._load_findings_ledger(proj)
    assert FP_A not in ledger  # 消费判定不变：条目删除
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_CONSUMED] == FIXED_TODAY
    assert ka.STATE_KEY_ESCALATED_REMINDED not in state  # 清除 → 下轮按无历史应拍
    assert state[ka.STATE_KEY_ESCALATED_FP_SET] == []


def test_consume_with_zero_consumed_is_zero_write(proj, today):
    """consumed 为空（指纹未知跳过留痕）零写：三键不被记账。"""
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-20",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    arb = proj / ka.ARBITRATION_RELPATH
    arb.parent.mkdir(parents=True, exist_ok=True)
    arb.write_text(
        json.dumps([{"fingerprint": "deadbeef", "decision": "fixed"}]),
        encoding="utf-8",
    )
    res = ka.consume_arbitration(proj, config={})
    assert res["triggered"] is False
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_REMINDED] == "2026-11-20"
    assert ka.STATE_KEY_ESCALATED_CONSUMED not in state


def test_redecay_after_stale_days_without_consumption(today):
    """形态 4 后半：消费超 stale_days 前每日拍；超过后且距上次提醒不足
    阈值 → 重新降频跳拍。"""
    # 消费后第 8 天：重新进入降频态；距上次提醒 1 天 → 跳拍（消费记账会同步
    # 指纹集，故此处集合与上次集一致、无集合变化旁路）
    state = {
        ka.STATE_KEY_ESCALATED_CONSUMED: "2026-11-19",  # 8 天前（> 7）
        ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
        ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
    }
    due, decayed = ka._escalated_reminder_due({FP_A: _entry()}, state, FIXED_TODAY)
    assert (due, decayed) == (False, True)


def test_shrink_restores_daily_beat(today):
    """规则 6：集合减少（当前集是上次集真子集）视同消费活动 → 当日非降频态
    应拍（人工删条目等未记账消费路径）。"""
    state = {
        ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
        ka.STATE_KEY_ESCALATED_FP_SET: [FP_A, FP_B],
    }
    due, decayed = ka._escalated_reminder_due({FP_A: _entry()}, state, FIXED_TODAY)
    assert (due, decayed) == (True, False)
    # 相等集合不算减少：同状态无消费记账 → 维持降频跳拍
    due2, decayed2 = ka._escalated_reminder_due(
        {FP_A: _entry(), FP_B: _entry()}, state, FIXED_TODAY
    )
    assert (due2, decayed2) == (False, True)


def test_shrink_shot_books_consumed_date(proj, install_core, no_spawn, today, monkeypatch):
    """规则 6 集成面：集合减少拍出后把消费日记账（恢复每日节拍持久化）。"""
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-26",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A, FP_B],
        },
    )
    captured: list = []

    def _spy(project_root, prefix, line, **kwargs):
        captured.append(line)
        return True

    monkeypatch.setattr(ka, "upsert_todo_line", _spy)
    _run_audit(proj, install_core, no_spawn, ListLogger())
    assert len(captured) == 1
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_CONSUMED] == FIXED_TODAY
    assert state[ka.STATE_KEY_ESCALATED_FP_SET] == [FP_A]


# ── 形态 5：全部消费 → 纯清理摘除残留行并复位三键 ────────────────────────


def test_empty_escalated_cleans_line_and_resets_keys(
    proj, install_core, no_spawn, today
):
    """形态 5：escalated 清零旁路降频照常 upsert 纯清理摘除残留行，三键复位
    （键本不在场时零写）。"""
    _seed_ledger(proj, {})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-20",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
            ka.STATE_KEY_ESCALATED_CONSUMED: "2026-11-19",
        },
    )
    _seed_todo(proj, OLD_AGG_LINE)
    log = ListLogger()
    res = _run_audit(proj, install_core, no_spawn, log)
    assert res["ok"] is True
    assert OLD_AGG_LINE not in _read_todo(proj)  # 纯清理摘除残留行
    state = _read_state(proj)
    for key in (
        ka.STATE_KEY_ESCALATED_REMINDED,
        ka.STATE_KEY_ESCALATED_FP_SET,
        ka.STATE_KEY_ESCALATED_CONSUMED,
    ):
        assert key not in state


# ── 形态 6：状态键缺失/损坏、upsert 失败不抑制提醒且不刷新日期 ────────────


def test_missing_or_corrupt_keys_due(today):
    """形态 6 纯函数面：键缺失/类型损坏一律按无历史走向本轮应拍。"""
    # 全缺
    assert ka._escalated_reminder_due({FP_A: _entry()}, {}, FIXED_TODAY) == (True, True)
    # 类型损坏
    corrupt = {
        ka.STATE_KEY_ESCALATED_FP_SET: "corrupt",
        ka.STATE_KEY_ESCALATED_REMINDED: 123,
        ka.STATE_KEY_ESCALATED_CONSUMED: {"not": "a date"},
    }
    assert ka._escalated_reminder_due({FP_A: _entry()}, corrupt, FIXED_TODAY) == (
        True,
        True,
    )
    # state 非字典
    assert ka._escalated_reminder_due({FP_A: _entry()}, None, FIXED_TODAY) == (True, True)


def test_upsert_oserror_failopen_does_not_refresh_date(
    proj, install_core, no_spawn, today, monkeypatch
):
    """形态 6 集成面：upsert 抛 OSError 走既有 fail-open WARNING，且不刷新
    最近提醒日期——下一轮体检按到期重试，不被降频抑制。"""

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ka, "upsert_todo_line", _boom)
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-20",  # 到期应拍
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    log = ListLogger()
    res = _run_audit(proj, install_core, no_spawn, log)
    assert res["ok"] is True
    assert any("fail-open" in m for m in log.messages("warning"))
    state = _read_state(proj)
    assert state[ka.STATE_KEY_ESCALATED_REMINDED] == "2026-11-20"  # 不刷新
    # 下一轮（间隔内）：仍应拍（写失败不被降频抑制）
    due, decayed = ka._escalated_reminder_due(
        {FP_A: _entry()}, _read_state(proj), FIXED_TODAY, stale_days=7
    )
    assert (due, decayed) == (True, True)


def test_upsert_idempotent_false_does_not_refresh_date(
    proj, install_core, no_spawn, today, monkeypatch
):
    """upsert 幂等零写（返回 False）同样不刷新日期（design 落库纪律）。"""

    def _false(*args, **kwargs):
        return False

    monkeypatch.setattr(ka, "upsert_todo_line", _false)
    _seed_ledger(proj, {FP_A: _entry()})
    _seed_state(
        proj,
        **{
            ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-20",
            ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
        },
    )
    _run_audit(proj, install_core, no_spawn, ListLogger())
    assert _read_state(proj)[ka.STATE_KEY_ESCALATED_REMINDED] == "2026-11-20"


def test_stale_days_config_override(today):
    """stale_days 取 config 单源（knowledge.escalated_stale_days 白名单解析），
    缺省 7 不在本文件重复设常量：传入覆盖值时判定按覆盖值走。"""
    state = {
        ka.STATE_KEY_ESCALATED_REMINDED: "2026-11-24",  # 3 天前
        ka.STATE_KEY_ESCALATED_FP_SET: [FP_A],
    }
    # 龄期 3 天 ≤ 14 未超龄（first_seen=2026-11-24 → 龄期 3）→ 每日一拍
    due, decayed = ka._escalated_reminder_due(
        {FP_A: _entry(RECENT_FIRST_SEEN)}, state, FIXED_TODAY, stale_days=14
    )
    assert (due, decayed) == (True, False)
    # 超龄（first_seen 10-01，龄期 57 > 14）但消费 11-24（3 天前 ≤ 14）→ 非降频
    due2, decayed2 = ka._escalated_reminder_due(
        {FP_A: _entry()}, {ka.STATE_KEY_ESCALATED_CONSUMED: "2026-11-24"}, FIXED_TODAY,
        stale_days=14,
    )
    assert (due2, decayed2) == (True, False)
