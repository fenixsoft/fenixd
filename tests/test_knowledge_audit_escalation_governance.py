"""escalated 治理单测（add-knowledge-audit-escalation-consumption 任务 3.1/3.2/3.3）。

覆盖：
- 1.1 占槽豁免：10 条 escalated 在册时切片前剔除，新候选当日仍被转写派发；
- 1.2/1.3 聚合：体检报告单条汇总（条数 + 最长龄期）、todo 聚合行同前缀替换
  不追加、历史逐条行清理；
- 2.1 超龄注记：写入/摘除自提交、150 行硬顶跳过留痕、配置键覆盖与回退、
  注记不劫持 knowledge: marker 解析；
- 2.2 仲裁清单消费闭环：合法 decision 删条目恢复自动复核、脏输入跳过留痕、
  当日体检已跑（防重短路态）写入清单仍当日消费、未命中零写零提交。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import date, timedelta
from pathlib import Path

import pytest

from core import knowledge_audit as ka
from core.config import ConfigLoader


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


def _pair_page(name: str, subject: str, value: int) -> str:
    return (
        f"<!-- knowledge: capability={name} rev=1 sources=arc-good -->\n"
        f"# {name}\n\n## 规则\n\n- {subject}:{value} 秒。\n\n## 溯源\n\n- spec/archive/arc-good\n"
    )


def _make_proj(root: Path, pairs: int = 1) -> Path:
    """建 git 化知识库夹具：``pairs`` 对同主题不同数值页（每对恰一条矛盾候选，
    对间主题词互异不产生跨对候选），arc-good 归档在盘。"""
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


@pytest.fixture
def proj(tmp_path):
    """单矛盾对夹具：p00a（300 秒）× p00b（600 秒）。"""
    return _make_proj(tmp_path / "main", pairs=1)


class FakeCore:
    def __init__(self, root: Path, violations_fn=None):
        self.root = root
        self.violations_fn = violations_fn or (lambda: [])
        self.validate_calls = 0
        self.commit_calls: list = []

    def _commit(self, project_root, paths, message) -> bool:
        self.commit_calls.append((list(paths), message))
        return ka.commit_pathspec(project_root, paths, message)

    def validate_knowledge(self, project_root):
        self.validate_calls += 1
        return list(self.violations_fn())


@pytest.fixture
def install_core(monkeypatch):
    def _install(core_obj):
        mod = types.ModuleType("core.knowledge")
        mod.validate_knowledge = core_obj.validate_knowledge
        mod.commit_knowledge = core_obj._commit
        import core as core_pkg

        monkeypatch.setitem(sys.modules, "core.knowledge", mod)
        monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
        return core_obj

    return _install


def read_page(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _findings_by_fp(root: Path) -> dict[str, dict]:
    pages = ka._collect_pages(root)
    return {ka._finding_fingerprint(f): f for f in ka._scan_semantic(pages)}


def _seed_escalated(root: Path, fps, first_seen: str, review_rounds: int = 2) -> None:
    """按真实候选指纹种 escalated 台账条目（schema 对齐 _new_finding_entry）。"""
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


PAIR_PAGES = (
    "spec/knowledge/domains/dom-a/p00a.md",
    "spec/knowledge/domains/dom-a/p00b.md",
)


def _todo_lines(root: Path) -> list[str]:
    todo = root / ".fenix" / "todo.md"
    if not todo.exists():
        return []
    return todo.read_text(encoding="utf-8").splitlines()


# ── 3.1 占槽豁免 + 报告聚合形态 ──────────────────────────────────────────


def test_escalated_do_not_consume_semantic_budget(tmp_path, install_core):
    """10 条 escalated 在册（候选总量 11 > MAX_SEMANTIC_RUNS=10）时新候选仍被
    转写派发：escalated 切片前剔除不占槽，转写预算留给在册新候选。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=11)  # 11 对矛盾候选，p00 对为「新候选」
    core = install_core(FakeCore(root))
    fps = _findings_by_fp(root)
    assert len(fps) == 11
    fresh_fp = next(fp for fp in fps if "p00a" in str(fps[fp]["a"]["page"]))
    escalated_fps = [fp for fp in fps if fp != fresh_fp]
    _seed_escalated(root, escalated_fps, first_seen=ka._today())  # 龄期 0：不触发注记

    dispatched: list[str] = []

    def spawn(prompt, run_id):
        dispatched.append(prompt)
        return "ok"  # 零改动收场 → 判无矛盾

    r = ka.run_audit(root, spawn=spawn)
    # 解冻：11 条候选中唯一非 escalated 的新候选被转写（旧实现会被 10 条
    # escalated 占满 10 个槽位，新候选零派发）
    assert len(dispatched) == 1
    assert "主题00" in dispatched[0]  # 派发的正是新候选（而非 escalated 疑点）
    assert r["counts"]["rewritten"] == 0  # 判无矛盾零改动
    ledger = ka._load_findings_ledger(root)
    assert ledger[fresh_fp]["status"] == "exempt"  # 新候选当日入账并判定
    assert len(ledger[fresh_fp]["verdicts"]) == 1
    for fp in escalated_fps:
        assert ledger[fp]["status"] == "escalated"  # 在册挂起态零触碰
        assert ledger[fp]["verdicts"] == []
        assert ledger[fp]["review_rounds"] == 2
    assert core.commit_calls == []  # 零改动 + 龄期未超阈值：零提交


def test_report_aggregates_escalated_details(tmp_path, install_core):
    """报告把 escalated 明细折叠为单条汇总：条数 + 自 first_seen 起算的最长
    龄期，不再逐条展开；候选超限截断留痕按剔除后口径计数。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=3)
    install_core(FakeCore(root))
    fps = list(_findings_by_fp(root))
    _seed_escalated(root, fps[:2], first_seen=_days_ago(9))
    _seed_escalated(root, fps[2:], first_seen=_days_ago(3))

    r = ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert r["counts"]["pending_manual"] == 1  # 折叠为单条聚合（不逐条 +1）
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert report.count("## 升级待人工（escalated）汇总") == 1
    assert "共 3 条待人工仲裁" in report
    assert "最长龄期 9 天" in report  # 自 first_seen 起算的最长龄期
    assert "knowledge_audit_arbitration.json" in report  # 聚合行指向仲裁清单
    # 旧逐条展开形态不再出现
    assert "：升级待人工（escalated），已停止自动复核" not in report


# ── 3.2 聚合 todo 行 upsert / 注记写入与摘除 / marker 不劫持 ─────────────


def test_todo_aggregated_row_upsert_replaces_not_appends(tmp_path, install_core):
    """todo 升级登记收敛为单条聚合行：龄期变化整行替换不追加；历史逐条行
    首跑一并替换清理；escalated 清零后聚合行被摘除。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(3))
    # 预置历史逐条行（旧实现形态）
    todo_path = root / ".fenix" / "todo.md"
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    todo_path.write_text(
        f"## {ka._today()}\n### 知识真相源\n"
        "- audit 疑点升级待人工：contradiction（a × b）连续 2 轮复核无确定性判定，请人工仲裁\n",
        encoding="utf-8",
    )

    ka.run_audit(root, spawn=lambda p, rid: "ok")
    lines = [ln for ln in _todo_lines(root) if "audit 疑点升级待人工" in ln]
    assert len(lines) == 1  # 历史逐条行被清理，只余聚合行
    assert lines[0].startswith("- audit 疑点升级待人工（聚合）：1 条待人工仲裁（最长龄期 3 天）")
    assert "knowledge_audit_arbitration.json" in lines[0]  # 指向唯一人工入口

    # 龄期推进 → 同前缀整行替换，不追加新行
    ledger = ka._load_findings_ledger(root)
    ledger[fp]["first_seen"] = _days_ago(9)
    ka._save_findings_ledger(root, ledger)
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    lines = [ln for ln in _todo_lines(root) if "audit 疑点升级待人工" in ln]
    assert len(lines) == 1
    assert "最长龄期 9 天" in lines[0]

    # 台账 escalated 清零（人工删条目）→ 聚合行摘除，不残留陈旧登记
    ledger = ka._load_findings_ledger(root)
    del ledger[fp]
    # 合并写语义下删除须走显式删除通道（deleted_fingerprints），否则按指纹
    # 合并会把盘上条目复活（与仲裁消费段同款口径）
    ka._save_findings_ledger(root, ledger, deleted_fingerprints={fp})
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert [ln for ln in _todo_lines(root) if "audit 疑点升级待人工" in ln] == []


def test_disputed_annotation_write_and_remove(tmp_path, install_core):
    """escalated 超龄 → 涉事两页顶部写 disputed 注记并走 [fenix] knowledge
    提交路径自提交；条目不再超龄在册时同款路径摘除。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    core = install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(8))  # 8 > 7 缺省阈值

    ka.run_audit(root, spawn=lambda p, rid: "ok")
    fps8 = str(fp)[:8]
    for rel in PAIR_PAGES:
        lines = read_page(root, rel).splitlines()
        # 页顶：H1 与 knowledge marker 之后的独立注释行
        assert lines[2].startswith("<!-- disputed: since=")
        assert lines[2].endswith(f" fps={fps8} -->")
        assert "knowledge:" not in lines[2]  # 不劫持 marker 前缀
        assert "spec/archive" not in lines[2]  # 不引用 archive 路径
    # 自提交：注记不留工作区（不成为下一轮 carryover 告警源）
    assert any("disputed" in msg for _, msg in core.commit_calls)
    assert _git(root, "status", "--porcelain", "--", "spec/knowledge").strip() == ""

    # 条目转出 escalated（人工改判）→ 下一轮体检摘除注记并自提交
    ledger = ka._load_findings_ledger(root)
    ledger[fp]["status"] = "exempt"
    ka._save_findings_ledger(root, ledger)
    core.commit_calls.clear()
    ka.run_audit(root, spawn=lambda p, rid: "ok")
    for rel in PAIR_PAGES:
        assert "<!-- disputed:" not in read_page(root, rel)
    assert any("disputed" in msg for _, msg in core.commit_calls)
    assert _git(root, "status", "--porcelain", "--", "spec/knowledge").strip() == ""


def test_disputed_annotation_respects_line_cap(tmp_path, install_core):
    """页已达 150 行硬顶时注记写入跳过并留痕，不越顶。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    # 恰 150 行（未超顶不报 overcap）：写注记需 +1 行 → 越顶，须跳过
    body = "<!-- knowledge: capability=gamma rev=1 sources=arc-good -->\n# gamma\n\n## 规则\n\n"
    body += "\n".join(f"- 填充规则第 {i:03d} 条。" for i in range(141))
    body += "\n\n## 溯源\n\n- spec/archive/arc-good\n"
    assert len(body.splitlines()) == ka.LINE_CAP
    (kdom / "gamma.md").write_text(body, encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "gamma")
    ledger = ka._load_findings_ledger(root)
    ledger["f" + "0" * 63] = {
        "kind": "contradiction",
        "pages": ["spec/knowledge/domains/dom-a/gamma.md"],
        "rules": ["- 填充规则第 000 条。", "- 填充规则第 001 条。"],
        "page_hashes": {},
        "verdicts": [],
        "status": "escalated",
        "first_seen": _days_ago(10),
        "updated_at": ka._today(),
        "review_rounds": 2,
    }
    ka._save_findings_ledger(root, ledger)

    ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert "<!-- disputed:" not in read_page(root, "spec/knowledge/domains/dom-a/gamma.md")
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "disputed 注记写入跳过" in report
    assert "gamma.md" in report


def test_disputed_annotation_does_not_hijack_marker(tmp_path, install_core):
    """注记在场时 knowledge marker 解析不受劫持：_MARKER_RE/parse_marker 取
    首个 knowledge: 匹配，disputed 行无 knowledge: 前缀天然不冲突。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(8))
    ka.run_audit(root, spawn=lambda p, rid: "ok")

    text = read_page(root, PAIR_PAGES[0])
    assert "<!-- disputed:" in text
    marker = ka._parse_marker(text)  # 取首个 knowledge: 匹配
    assert marker is not None
    assert marker["capability"] == "p00a"
    assert marker["rev"] == "1"
    assert marker["sources"] == "arc-good"
    first_match = ka._MARKER_RE.search(text).group(0)
    assert "capability=" in first_match  # 首匹配仍是 knowledge marker 本体
    assert "disputed" not in first_match


def test_stale_days_config_override(tmp_path, install_core):
    """knowledge.escalated_stale_days 覆盖阈值：3 天阈值时 4 龄期即注记；
    非法值回退缺省 7（同 escalate_after_rounds 口径），4 龄期不注记。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(4))
    rel = PAIR_PAGES[0]

    ka.run_audit(
        root,
        spawn=lambda p, rid: "ok",
        config={"knowledge": {"escalated_stale_days": 3}},
    )
    assert "<!-- disputed:" in read_page(root, rel)

    (root / rel).write_text(
        read_page(root, rel).split("<!-- disputed:")[0].rstrip() + "\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "reset")
    ka.run_audit(
        root,
        spawn=lambda p, rid: "ok",
        config={"knowledge": {"escalated_stale_days": "3"}},  # 非法：字符串
    )
    assert "<!-- disputed:" not in read_page(root, rel)  # 回退缺省 7：4 龄期不注记


def test_lane_config_escalated_stale_days_defaults():
    """get_knowledge_lane_config 白名单新增 escalated_stale_days：缺省 7、
    正整数可覆盖、非法值（非 int/bool/非正）回退 7。"""
    assert ConfigLoader.get_knowledge_lane_config({})["escalated_stale_days"] == 7
    cfg = ConfigLoader.get_knowledge_lane_config({"knowledge": {"escalated_stale_days": 3}})
    assert cfg["escalated_stale_days"] == 3
    for bad in ("3", True, False, 0, -1, 1.5, None):
        cfg = ConfigLoader.get_knowledge_lane_config(
            {"knowledge": {"escalated_stale_days": bad}}
        )
        assert cfg["escalated_stale_days"] == 7, bad


# ── 3.3 仲裁清单消费闭环 ─────────────────────────────────────────────────


def _write_arbitration(root: Path, entries: list[dict]) -> None:
    path = root / ".fenix" / "knowledge_audit_arbitration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_arbitration(root: Path) -> list:
    path = root / ".fenix" / "knowledge_audit_arbitration.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _mark_day_done(root: Path) -> None:
    """置自然日防重戳：当日体检已跑（车道防重短路态）。"""
    state = ka._read_state(root)
    state["last_audit_date"] = ka._today()
    ka._write_state(root, state)


def test_arbitration_consumed_on_done_day_and_review_resumes(tmp_path, install_core):
    """消费闭环：当日体检已跑（防重短路态）写入清单仍当日消费——台账删条目、
    注记同轮摘除自提交；条目缺席后台账重建，该页对恢复自动复核。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    core = install_core(FakeCore(root))
    fp = next(iter(_findings_by_fp(root)))
    _seed_escalated(root, [fp], first_seen=_days_ago(8))
    ka.run_audit(root, spawn=lambda p, rid: "ok")  # 先跑一轮：注记在盘、todo 聚合行在场
    assert "<!-- disputed:" in read_page(root, PAIR_PAGES[0])
    _mark_day_done(root)
    core.commit_calls.clear()
    _write_arbitration(
        root,
        [{"fingerprint": fp, "decision": "no-conflict", "decided_at": ka._today(), "note": "人工判定无矛盾"}],
    )

    lane_calls: list[str] = []

    def lane(project_root, logger=None, config=None):
        lane_calls.append("audit")
        return {"triggered": True, "ok": True}

    logger = ListLogger()
    r = ka.knowledge_daily_check(root, logger=logger, audit_lane=lane)
    assert lane_calls == []  # 防重短路：体检车道未跑
    assert r["results"]["arbitration"]["consumed"] == 1  # 消费段不受防重影响
    assert fp not in ka._load_findings_ledger(root)  # 台账条目删除（缺席即重建）
    assert _read_arbitration(root) == []  # 已消费条目被剔除，不周期重复消费
    for rel in PAIR_PAGES:
        assert "<!-- disputed:" not in read_page(root, rel)  # 注记同轮摘除
    assert any("disputed" in msg for _, msg in core.commit_calls)  # 摘除自提交
    assert _git(root, "status", "--porcelain", "--", "spec/knowledge").strip() == ""
    assert any("仲裁清单消费" in msg for _, msg in logger.lines)

    # 条目缺席 → 下一轮体检以新 suspected 条目重开复核，自动派发恢复
    dispatched: list[str] = []

    def spawn(prompt, run_id):
        dispatched.append(prompt)
        return "ok"

    ka.run_audit(root, spawn=spawn)
    assert len(dispatched) == 1
    ledger = ka._load_findings_ledger(root)
    assert fp in ledger  # _new_finding_entry 重建（零新机制）
    assert ledger[fp]["status"] == "exempt"  # 零改动判无矛盾重新入账
    assert ledger[fp]["review_rounds"] == 0
    # todo 聚合行随 backlog 清零被摘除
    assert [ln for ln in _todo_lines(root) if "audit 疑点升级待人工" in ln] == []


def test_arbitration_dirty_inputs_skipped_with_trace(tmp_path, install_core):
    """脏输入防御：未知指纹 / 非 escalated 状态 / 非法 decision 逐条跳过留痕，
    合法条目正常消费，审计循环不受影响。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=2)
    install_core(FakeCore(root))
    fps = list(_findings_by_fp(root))
    _seed_escalated(root, fps[:1], first_seen=ka._today())
    # 预置一条非 escalated 态条目（suspected）
    suspected_fp = fps[1]
    _seed_escalated(root, [suspected_fp], first_seen=ka._today())
    ledger = ka._load_findings_ledger(root)
    ledger[suspected_fp]["status"] = "suspected"
    ka._save_findings_ledger(root, ledger)

    unknown_fp = "dead" + "0" * 60
    _write_arbitration(
        root,
        [
            {"fingerprint": unknown_fp, "decision": "no-conflict", "decided_at": ka._today()},
            {"fingerprint": suspected_fp, "decision": "fixed", "decided_at": ka._today()},
            {"fingerprint": fps[0], "decision": "approve", "decided_at": ka._today()},  # 非法 decision
            {"fingerprint": fps[0], "decision": "false-positive", "decided_at": ka._today()},
        ],
    )
    logger = ListLogger()
    r = ka.consume_arbitration(root, logger=logger)
    assert r["consumed"] == 1 and r["skipped"] == 3
    ledger = ka._load_findings_ledger(root)
    assert fps[0] not in ledger  # 合法条目已消费删除
    assert suspected_fp in ledger and ledger[suspected_fp]["status"] == "suspected"
    kept_fps = {e["fingerprint"] for e in _read_arbitration(root)}
    assert kept_fps == {unknown_fp, suspected_fp, fps[0]}  # 跳过条目留清单不吞
    assert sum(1 for _, msg in logger.lines if "跳过留痕" in msg) == 3

    # 审计循环不受影响：消费后体检正常跑完
    res = ka.run_audit(root, spawn=lambda p, rid: "ok")
    assert res["ok"] is True


def test_arbitration_no_hit_zero_write(tmp_path, install_core):
    """未命中零写零提交：无清单文件不创建、有清单无命中不回写不提交。"""
    root = tmp_path / "main"
    _make_proj(root, pairs=1)
    core = install_core(FakeCore(root))
    logger = ListLogger()

    r = ka.knowledge_daily_check(root, logger=logger, audit_lane=lambda *a, **k: {"triggered": True, "ok": True})
    assert "arbitration" not in r.get("results", {})
    assert not (root / ".fenix" / "knowledge_audit_arbitration.json").exists()
    assert core.commit_calls == []

    # 空清单文件（人工已清空）同样零动作
    _write_arbitration(root, [])
    ledger_before = ka._load_findings_ledger(root)
    ka.consume_arbitration(root, logger=logger)
    assert ka._load_findings_ledger(root) == ledger_before
    assert core.commit_calls == []
