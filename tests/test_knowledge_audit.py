"""周期 audit 车道 + 每日检查点单测（任务 3.1 / 3.3）。

fake spawn 替身 + 注入的 core.knowledge 替身，覆盖：
- audit 三支路：机械自修直提交 / 语义转写（含判无矛盾零改动）/ 零病灶；
- 转写失败 → 回滚 + todo.md 登记；
- 规模趋势超 +10% 标「需精简」；
- 每日检查点：门控、自然日防重、异常不落日戳。
（graph 生成车道已随 graphify 功能取消下线，对应用例一并移除——2026-09-29。）
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
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


PAGE_ALPHA = """<!-- knowledge: capability=alpha rev=1 sources=arc-good,arc-ghost -->
# alpha

## 规则

- 超时:300 秒。
- 禁用明文日志输出。

## 溯源

- spec/archive/arc-good
- spec/archive/arc-ghost
"""

PAGE_BETA = """<!-- knowledge: capability=beta rev=1 sources=arc-good -->
# beta

## 规则

- 超时:600 秒。
- 禁用明文日志输出。

## 溯源

- spec/archive/arc-good
"""


def page_gamma_overcap() -> str:
    body = "<!-- knowledge: capability=gamma rev=1 sources=arc-good -->\n# gamma\n\n## 规则\n\n"
    body += "\n".join(f"- 填充规则第 {i} 条。" for i in range(160))
    return body + "\n"


PAGE_GAMMA_DUP = """<!-- knowledge: capability=gamma rev=1 sources=arc-good -->
# gamma

## 规则

- 超时:300 秒。

## 溯源

- spec/archive/arc-good
"""


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "spec" / "archive" / "arc-good").mkdir(parents=True)
    (root / "spec" / "archive" / "arc-good" / "proposal.md").write_text("x\n")
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    kadr = root / "spec" / "knowledge" / "adr"
    kdom.mkdir(parents=True)
    kadr.mkdir(parents=True)
    (root / "spec" / "knowledge" / "index.md").write_text("# 真相源\n\n- [alpha](domains/dom-a/alpha.md)\n")
    (kdom / "alpha.md").write_text(PAGE_ALPHA, encoding="utf-8")
    (kdom / "beta.md").write_text(PAGE_BETA, encoding="utf-8")
    (kadr / "ADR-001-legacy.md").write_text(
        "# ADR-001 legacy\n\nstatus: accepted\n\n正文一句。\n", encoding="utf-8"
    )
    (kadr / "ADR-002-new.md").write_text(
        "# ADR-002 new\n\nstatus: superseded\nSuperseded by: ADR-003\n\n正文一句。\n",
        encoding="utf-8",
    )
    (kadr / "index.md").write_text(
        "- [ADR-001 legacy](ADR-001-legacy.md) — accepted\n"
        "- [ADR-002 new](ADR-002-new.md) — accepted\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


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


@pytest.fixture
def proj_settled(proj):
    """无机械病灶的干净夹具：保留语义疑点（超时 300/600 矛盾 + 跨页重复），
    机械自修段零动作 → 不触发同批纠偏跳过（superseded-in-batch），语义疑点
    可正常进入复核循环。"""
    alpha = (
        read_page(proj, "spec/knowledge/domains/dom-a/alpha.md")
        .replace("- spec/archive/arc-ghost\n", "")
        .replace("sources=arc-good,arc-ghost", "sources=arc-good")
    )
    (proj / "spec/knowledge/domains/dom-a/alpha.md").write_text(alpha, encoding="utf-8")
    (proj / "spec/knowledge/adr/ADR-002-new.md").write_text(
        "# ADR-002 new\n\nstatus: superseded\n\n正文一句。\n", encoding="utf-8"
    )
    (proj / "spec/knowledge/adr/index.md").write_text(
        "- [ADR-001 legacy](ADR-001-legacy.md) — accepted\n"
        "- [ADR-002 new](ADR-002-new.md) — superseded\n",
        encoding="utf-8",
    )
    _git(proj, "add", ".")
    _git(proj, "commit", "-qm", "settle")
    return proj


# ── 机械自修支路（fixture 默认 alpha/beta 规则不同主题：语义零候选） ─────


def test_audit_mechanical_fix_commits(proj, install_core):
    # 去掉语义重叠：beta 的两条规则换成不同主题
    beta = read_page(proj, "spec/knowledge/domains/dom-a/beta.md")
    beta = beta.replace("- 超时:600 秒。", "- 重试至多 5 次。").replace(
        "- 禁用明文日志输出。", "- 导出文件走临时目录。"
    )
    (proj / "spec/knowledge/domains/dom-a/beta.md").write_text(beta, encoding="utf-8")
    # beta 加一处格式违规（行尾空白）
    (proj / "spec/knowledge/domains/dom-a/beta.md").write_text(
        beta + "trailing   \n", encoding="utf-8"
    )
    core = install_core(FakeCore(proj))
    logger = ListLogger()
    result = ka.run_audit(proj, logger=logger, spawn=lambda p, r: "ok")

    assert result["triggered"] is True
    assert result["counts"]["fixed"] >= 3  # 悬空溯源 / 格式 / ADR index 对齐
    # 悬空溯源行被删、越界 sources 剔除
    alpha = read_page(proj, "spec/knowledge/domains/dom-a/alpha.md")
    assert "arc-ghost" not in alpha
    assert "sources=arc-good" in alpha
    assert "spec/archive/arc-good" in alpha  # 有效溯源行保留
    # 格式违规清理
    assert "trailing   \n" not in read_page(proj, "spec/knowledge/domains/dom-a/beta.md")
    # ADR index 状态机械对齐（条目头 superseded）
    index = read_page(proj, "spec/knowledge/adr/index.md")
    assert "ADR-002-new.md) — superseded" in index
    # 机械修复直提交
    msgs = [m for _, m in core.commit_calls]
    assert msgs and msgs[0].startswith("[fenix] knowledge: audit fix ")
    # 体检报告与规模基线落盘
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "audit 体检报告" in report
    state = json.loads((proj / ".fenix" / "knowledge_audit_state.json").read_text())
    assert state["last_scale"]["pages"] >= 2


def test_audit_mechanical_keeps_fullpath_sources(tmp_path):
    """回归（fix f0868c0cf0f9）：marker sources 契约为全路径（core.knowledge
    校验器强制 ``spec/archive/`` 前缀），悬空溯源判定与 sources 剔除必须按
    基名归一比对。旧实现拿全路径对归档基名集合比对恒判悬空 → sources 被
    清空 → 真实校验报 marker 字段非法 → 整轮机械修复被回滚（真实运行证据：
    knowledge_audit_report.md 2026-09-28「修 0 / marker 字段非法，已回滚」）。
    本例不装 FakeCore，走真实校验器与 pathspec 提交。"""
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
    (kdom / "alpha.md").write_text(
        "<!-- knowledge: capability=alpha rev=1 sources=spec/archive/arc-good -->\n"
        "# alpha\n\n## 规则\n\n- 超时:300 秒。\n\n## 溯源\n\n"
        "- spec/archive/arc-good\n- spec/archive/arc-ghost\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")

    result = ka.run_audit(root, spawn=lambda p, r: "ok")

    assert result["counts"]["fixed"] >= 1
    alpha = (kdom / "alpha.md").read_text(encoding="utf-8")
    assert "sources=spec/archive/arc-good" in alpha  # 全路径 sources 未被清空
    assert "arc-ghost" not in alpha  # 悬空溯源行已删
    # 机械修复过真实校验并已提交，真相源目录无未提交残留
    status = _git(root, "status", "--porcelain", "--", "spec/knowledge")
    assert status.strip() == ""
    assert "audit fix" in _git(root, "log", "--format=%s")


def test_audit_zero_defect_passes_without_commit(proj, tmp_path, install_core):
    root = tmp_path / "clean"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    kdom.mkdir(parents=True)
    (root / "spec" / "archive" / "arc-good").mkdir(parents=True)
    (kdom / "alpha.md").write_text(
        "<!-- knowledge: capability=alpha rev=1 sources=arc-good -->\n"
        "# alpha\n\n## 规则\n\n- 超时:300 秒。\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    core = install_core(FakeCore(root))
    result = ka.run_audit(root, spawn=lambda p, r: "ok")
    assert result["counts"]["fixed"] == 0
    assert result["counts"]["pending_manual"] == 0
    assert result["counts"]["passed"] >= 1
    assert core.commit_calls == []  # 零病灶不产生修复提交
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "通过" in report


# ── 语义转写支路 ─────────────────────────────────────────────────────────


def test_audit_semantic_rewrite_commits(proj_settled, install_core):
    """矛盾（超时 300 vs 600）与跨页重复 → 定向转写提交。

    跨页重复候选放独立页面 gamma（重复规则与 alpha 同文）：同批内先提交的
    转写会纠偏涉及页（2.3 superseded-in-batch 快照滞后去重），后续涉同页
    疑点被跳过——两条候选要都拿到真实转写就不能共用页面。"""
    install_core(FakeCore(proj_settled))
    (proj_settled / "spec/knowledge/domains/dom-a/gamma.md").write_text(
        PAGE_GAMMA_DUP, encoding="utf-8"
    )
    _git(proj_settled, "add", ".")
    _git(proj_settled, "commit", "-qm", "gamma")

    spawn_calls = {"n": 0}

    def spawn(prompt, run_id):
        if "定向转写" in prompt:
            spawn_calls["n"] += 1
            # 按病灶类型定向修复（每个 run 只处理本条候选，须以 FINDING_KIND
            # 区分）
            if "contradiction" in prompt:
                beta = read_page(proj_settled, "spec/knowledge/domains/dom-a/beta.md")
                beta = beta.replace("- 超时:600 秒。", "- 超时:300 秒。")
                (proj_settled / "spec/knowledge/domains/dom-a/beta.md").write_text(
                    beta, encoding="utf-8"
                )
            elif "duplicate" in prompt:
                gamma = read_page(proj_settled, "spec/knowledge/domains/dom-a/gamma.md")
                gamma = gamma.replace("- 超时:300 秒。\n", "")
                (proj_settled / "spec/knowledge/domains/dom-a/gamma.md").write_text(
                    gamma, encoding="utf-8"
                )
        return "ok"

    result = ka.run_audit(proj_settled, spawn=spawn)
    assert result["counts"]["rewritten"] == 2
    assert result["counts"]["superseded"] >= 1  # beta 被首笔转写纠偏后的同页疑点
    assert spawn_calls["n"] == 2
    subjects = _git(proj_settled, "log", "--format=%s")
    assert "audit rewrite contradiction" in subjects
    assert "audit rewrite duplicate" in subjects
    beta = read_page(proj_settled, "spec/knowledge/domains/dom-a/beta.md")
    assert "超时:600" not in beta
    report = (proj_settled / ".fenix" / "knowledge_audit_report.md").read_text(
        encoding="utf-8"
    )
    assert "转写明细" in report


def test_audit_no_conflict_verdict_counts_passed(proj_settled, install_core):
    """转写 run 判「无矛盾」零改动收场：计入「过」，不产生转写提交。

    用 settled 夹具：proj 的机械自修段会纠偏 alpha（2.3 同批快照滞后去重），
    两候选会被标 superseded-in-batch 跳过而进不了复核。"""
    core = install_core(FakeCore(proj_settled))
    result = ka.run_audit(proj_settled, spawn=lambda p, r: "AUDIT_VERDICT: no-conflict")
    assert result["counts"]["rewritten"] == 0
    assert result["counts"]["passed"] >= 2  # 矛盾 + 重复 两候选均判无矛盾
    assert all("rewrite" not in m for _, m in core.commit_calls)
    report = (proj_settled / ".fenix" / "knowledge_audit_report.md").read_text(
        encoding="utf-8"
    )
    assert "判无矛盾" in report


def test_audit_rewrite_failure_rolls_back_and_registers_todo(proj_settled, install_core):
    """转写 run 校验两轮仍失败：回滚半成品 + todo.md 登记 + 待人工计数。

    用 settled 夹具：proj 的机械自修段会纠偏 alpha，两候选在派发前就被
    superseded-in-batch 跳过（2.3），到不了转写失败支路。"""
    state = {"broken": False}

    def violations():
        return ["spec/knowledge/domains/dom-a/beta.md：marker 不可解析"] if state["broken"] else []

    install_core(FakeCore(proj_settled, violations_fn=violations))

    def spawn(prompt, run_id):
        if "定向转写" in prompt:
            state["broken"] = True  # 修正轮也持续违规
        return "ok"

    result = ka.run_audit(proj_settled, spawn=spawn)
    assert result["counts"]["rewritten"] == 0
    assert result["counts"]["pending_manual"] >= 1
    todo = (proj_settled / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "转写失败" in todo
    # 半成品已回滚：真相源目录无未提交残留（.fenix 运行时文件除外）
    status = _git(proj_settled, "status", "--porcelain", "--", "spec/knowledge")
    assert status.strip() == ""


# ── 报告项与规模趋势 ─────────────────────────────────────────────────────


def test_audit_overcap_and_broken_chain_reported(proj, install_core):
    install_core(FakeCore(proj))
    (proj / "spec/knowledge/domains/dom-a/gamma.md").write_text(
        page_gamma_overcap(), encoding="utf-8"
    )
    result = ka.run_audit(proj, spawn=lambda p, r: "ok")
    manual = "\n".join(
        str(x) for x in _manual_items(proj)
    )
    assert "超 150 行硬顶" in manual
    assert "supersede 链断裂" in manual
    assert result["counts"]["pending_manual"] >= 2
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "待人工明细" in report


def _manual_items(root: Path) -> list:
    text = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    section = text.split("## 待人工明细")[-1]
    return [ln.strip("- ").strip() for ln in section.splitlines() if ln.startswith("- ")]


def test_audit_slim_flag_when_growth_exceeds_threshold(proj, install_core):
    install_core(FakeCore(proj))
    # 放大当前规模（163 行超限页），相对基线 100 行增长 > +10%
    (proj / "spec/knowledge/domains/dom-a/gamma.md").write_text(
        page_gamma_overcap(), encoding="utf-8"
    )
    state_path = proj / ".fenix" / "knowledge_audit_state.json"
    state_path.parent.mkdir(exist_ok=True)
    state_path.write_text(json.dumps({"last_scale": {"lines": 100, "pages": 3}}))
    result = ka.run_audit(proj, spawn=lambda p, r: "ok")
    assert result["slim_flag"] is True
    assert result["growth"] > 0.10
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "需精简" in report


# ── 每日检查点（任务 3.3 调度门控） ──────────────────────────────────────


def make_lane(recorder, key, ret=None):
    def lane(project_root, logger=None, config=None):
        recorder.append(key)
        return ret if ret is not None else {"triggered": True, "ok": True}

    return lane


def test_daily_check_disabled_silent(proj):
    calls: list = []
    result = ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": False}},
        logger=ListLogger(),
        audit_lane=make_lane(calls, "audit"),
    )
    assert result == {"triggered": False, "reason": "disabled"}
    assert calls == []


def test_daily_check_runs_lane_once_per_day(proj):
    calls: list = []
    cfg = {}
    logger = ListLogger()
    r1 = ka.knowledge_daily_check(
        proj,
        config=cfg,
        logger=logger,
        audit_lane=make_lane(calls, "audit"),
    )
    assert r1["triggered"] is True
    assert calls == ["audit"]
    # 同自然日第二周期：防重，不再调用
    ka.knowledge_daily_check(
        proj,
        config=cfg,
        logger=logger,
        audit_lane=make_lane(calls, "audit"),
    )
    assert calls == ["audit"]


def test_daily_check_crash_does_not_mark_day(proj):
    calls: list = []

    def bad_lane(project_root, logger=None, config=None):
        calls.append("audit")
        raise RuntimeError("boom")

    logger = ListLogger()
    r1 = ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": True}},
        logger=logger,
        audit_lane=bad_lane,
    )
    assert r1["results"]["audit"]["ok"] is False
    assert any(lvl == "error" for lvl, _ in logger.lines)
    # 未落日戳：下一周期重试
    ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": True}},
        logger=logger,
        audit_lane=bad_lane,
    )
    assert calls == ["audit", "audit"]


# ── 疑点台账（add-knowledge-audit-finding-ledger 任务 5.1/5.2/5.3） ──────


def _finding(kind: str, page_a: str, rule_a: str, page_b: str, rule_b: str) -> dict:
    return {
        "kind": kind,
        "a": {"page": page_a, "rule": rule_a},
        "b": {"page": page_b, "rule": rule_b},
    }


def test_findings_ledger_roundtrip_and_atomicity(tmp_path):
    """台账读写 roundtrip + 原子写（无 .tmp 残留）+ 缺失/损坏 fail-open 空台账。"""
    ledger = {
        "fp1": {
            "kind": "contradiction",
            "pages": ["a.md", "b.md"],
            "rules": ["超时:300 秒。", "超时:600 秒。"],
            "page_hashes": {"a.md": "h1", "b.md": "h2"},
            "verdicts": [{"date": "2026-09-29", "verdict": "no-conflict", "commit": None}],
            "status": "exempt",
            "first_seen": "2026-09-29",
            "updated_at": "2026-09-29",
        }
    }
    ka._save_findings_ledger(tmp_path, ledger)
    fpath = tmp_path / ".fenix" / "knowledge_audit_findings.json"
    assert fpath.is_file()
    assert ka._load_findings_ledger(tmp_path) == ledger
    assert not fpath.with_name(fpath.name + ".tmp").exists()  # 原子替换无残留
    # 损坏 / 缺失 → fail-open 空台账（不抛异常）
    fpath.write_text("{broken", encoding="utf-8")
    assert ka._load_findings_ledger(tmp_path) == {}
    assert ka._load_findings_ledger(tmp_path / "no-such-root") == {}


def test_finding_fingerprint_stable_across_text_noise():
    """指纹只由 kind + 两页 rel + 归一化规则行 + digits 决定：标点/空白噪声、
    甲乙互换不影响；kind、数字、页面任一变化即换指纹。"""
    alpha = "spec/knowledge/domains/dom-a/alpha.md"
    beta = "spec/knowledge/domains/dom-a/beta.md"
    base = _finding("contradiction", alpha, "超时：300 秒。", beta, "超时:600 秒。")
    # 归一化等价（标点/空白差异）→ 同指纹
    noisy = _finding("contradiction", alpha, "超时:300秒", beta, "超时：600秒")
    assert ka._finding_fingerprint(base) == ka._finding_fingerprint(noisy)
    # 甲乙互换（扫描顺序差异）→ 同指纹
    swapped = _finding("contradiction", beta, "超时：600 秒", alpha, "超时:300 秒。")
    assert ka._finding_fingerprint(base) == ka._finding_fingerprint(swapped)
    # kind / digits / 页面任一不同 → 不同指纹
    assert ka._finding_fingerprint(base) != ka._finding_fingerprint(
        _finding("duplicate", alpha, "超时：300 秒。", beta, "超时:600 秒。")
    )
    assert ka._finding_fingerprint(base) != ka._finding_fingerprint(
        _finding("contradiction", alpha, "超时：301 秒。", beta, "超时:600 秒。")
    )
    assert ka._finding_fingerprint(base) != ka._finding_fingerprint(
        _finding("contradiction", "spec/knowledge/domains/dom-a/gamma.md", "超时：300 秒。", beta, "超时:600 秒。")
    )


def test_audit_no_conflict_exempt_skips_redispatch(proj_settled, install_core):
    """内容未变豁免：首轮 no-conflict 入账（记两页全文哈希），同指纹重出且
    两页内容未变时不再派发复核 run，计入 exempt 并记录豁免发生时间。"""
    install_core(FakeCore(proj_settled))
    r1 = ka.run_audit(proj_settled, spawn=lambda p, r: "AUDIT_VERDICT: no-conflict")
    assert r1["counts"]["passed"] >= 2  # 两个语义疑点均判无矛盾
    ledger = ka._load_findings_ledger(proj_settled)
    assert len(ledger) == 2
    assert all(e["status"] == "exempt" for e in ledger.values())
    assert all(e["page_hashes"] for e in ledger.values())  # 豁免键已记录

    spawn_calls = {"n": 0}

    def spawn(prompt, run_id):
        spawn_calls["n"] += 1
        return "AUDIT_VERDICT: no-conflict"

    r2 = ka.run_audit(proj_settled, spawn=spawn, logger=ListLogger())
    assert spawn_calls["n"] == 0  # 内容未变：不派发复核 run
    assert r2["counts"]["exempt"] == 2
    assert r2["counts"]["rewritten"] == 0
    report = (proj_settled / ".fenix" / "knowledge_audit_report.md").read_text(
        encoding="utf-8"
    )
    assert "豁免 2" in report
    ledger = ka._load_findings_ledger(proj_settled)
    assert all(e.get("exempted_at") for e in ledger.values())  # 豁免发生时间入账


def test_audit_content_change_unfreezes_exempt(proj_settled, install_core):
    """内容变更解冻：任一页哈希偏离台账记录 → 回 suspected 照常派发；复核后
    重新豁免并更新哈希，升级轮次随解冻清零（解冻重派不计入升级轮次）。"""
    install_core(FakeCore(proj_settled))
    ka.run_audit(proj_settled, spawn=lambda p, r: "AUDIT_VERDICT: no-conflict")

    # beta 内容变更（规则行原样保留 → 指纹不变，只动内容哈希）
    beta_path = proj_settled / "spec/knowledge/domains/dom-a/beta.md"
    beta_path.write_text(
        read_page(proj_settled, "spec/knowledge/domains/dom-a/beta.md")
        + "<!-- rev2 口径微调 -->\n",
        encoding="utf-8",
    )

    calls = {"n": 0}

    def spawn(prompt, run_id):
        calls["n"] += 1
        return "AUDIT_VERDICT: no-conflict"

    r2 = ka.run_audit(proj_settled, spawn=spawn)
    assert calls["n"] == 2  # 两个疑点（均涉 beta）都解冻重派
    assert r2["counts"]["exempt"] == 0
    ledger = ka._load_findings_ledger(proj_settled)
    assert all(e["status"] == "exempt" for e in ledger.values())  # 复核后重新豁免
    assert all(e["review_rounds"] == 0 for e in ledger.values())  # 升级轮次已清零
    assert all(len(e["verdicts"]) == 2 for e in ledger.values())  # 两轮判定历史


def test_audit_second_suspected_round_escalates(proj_settled, install_core):
    """连续两轮复核均无确定性判定（转写失败回滚）→ escalated + todo.md 登记
    + 停止自动派发；消费指引（删除台账条目）随登记落 todo。"""
    state = {"broken": False}

    def violations():
        return (
            ["spec/knowledge/domains/dom-a/beta.md：marker 不可解析"]
            if state["broken"]
            else []
        )

    install_core(FakeCore(proj_settled, violations_fn=violations))
    calls = {"n": 0}

    def spawn(prompt, run_id):
        if "定向转写" in prompt:
            calls["n"] += 1
            state["broken"] = True  # 修正轮持续违规 → 转写失败回滚
        return "ok"

    r1 = ka.run_audit(proj_settled, spawn=spawn)
    assert r1["counts"]["rewritten"] == 0
    assert r1["counts"]["pending_manual"] >= 2  # 两疑点首轮转写失败
    ledger = ka._load_findings_ledger(proj_settled)
    assert all(
        e["status"] == "suspected" and e["review_rounds"] == 1 for e in ledger.values()
    )

    r2 = ka.run_audit(proj_settled, spawn=spawn)  # 第二轮仍疑似 → 升级
    ledger = ka._load_findings_ledger(proj_settled)
    assert all(e["status"] == "escalated" for e in ledger.values())
    todo = (proj_settled / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "升级待人工" in todo
    assert "knowledge_audit_findings.json" in todo  # 人工消费指引在场

    calls_before = calls["n"]
    r3 = ka.run_audit(proj_settled, spawn=spawn)  # 挂起等人工
    assert calls["n"] == calls_before  # escalated 零派发
    assert r3["counts"]["pending_manual"] >= 2


def test_adr_broken_chain_matches_slug_filenames(proj):
    """ADR 断链按 ADR-\\d{3} 前缀匹配 slug 文件名（ADR-015/019/034 实况）：
    盘上存在 ADR-015-<slug>.md 即不断链；真缺失仍进待人工。"""
    kadr = proj / "spec/knowledge/adr"
    (kadr / "ADR-005-old.md").write_text(
        "# ADR-005 old\n\nstatus: superseded\nSuperseded by: ADR-015\n\n正文一句。\n",
        encoding="utf-8",
    )
    (kadr / "ADR-015-add-knowledge-atlas.md").write_text(
        "# ADR-015 add-knowledge-atlas\n\nstatus: accepted\n\n正文一句。\n",
        encoding="utf-8",
    )
    (kadr / "ADR-006-zombie.md").write_text(
        "# ADR-006 zombie\n\nstatus: superseded\nSuperseded by: ADR-099\n\n正文一句。\n",
        encoding="utf-8",
    )
    result = ka._scan_adrs(proj)
    joined = "\n".join(result["broken_chain"])
    assert "ADR-015" not in joined  # slug 形态文件在场，不再误报
    assert "ADR-005" not in joined  # ADR-005-old → ADR-015 因 slug 文件在场不断链
    assert "ADR-099" in joined  # 真缺失仍报告（ADR-006-zombie → ADR-099）


def test_checkpoint_merge_keeps_last_scale_and_report_trend(proj, install_core, monkeypatch):
    """检查点回写前重读合并：run_audit 写入的 last_scale 不被检查点的陈旧
    state 副本覆盖丢失；次日体检报告出现基于 last_scale 的「上次 X 行」后缀。"""
    install_core(FakeCore(proj))

    def audit_lane(project_root, logger=None, config=None):
        # 经检查点走真 run_audit（spawn 注入替身，见 e2e 同款缝）
        return ka.run_audit(
            project_root,
            logger=logger,
            spawn=lambda p, r: "AUDIT_VERDICT: no-conflict",
            config=config,
        )

    logger = ListLogger()
    ka.knowledge_daily_check(
        proj,
        logger=logger,
        audit_lane=audit_lane,
    )
    state = json.loads((proj / ".fenix" / "knowledge_audit_state.json").read_text())
    assert state["last_audit_date"] == ka._today()
    assert state["last_scale"]["pages"] >= 2  # 未被检查点回写覆盖丢失
    lines1 = state["last_scale"]["lines"]

    # 自然日推进 → 第二次体检基于 last_scale 出趋势后缀
    monkey_today = "2026-10-02"
    assert monkey_today != ka._today()
    monkeypatch.setattr(ka, "_today", lambda: monkey_today)
    ka.knowledge_daily_check(
        proj,
        logger=logger,
        audit_lane=audit_lane,
    )
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert f"上次 {lines1} 行" in report
    state = json.loads((proj / ".fenix" / "knowledge_audit_state.json").read_text())
    assert state["last_audit_date"] == monkey_today
    assert state["last_scale"]["pages"] >= 2  # 次日合并回写后仍在


def test_knowledge_lane_config_ledger_keys():
    """get_knowledge_lane_config 新增两键：缺省 no_conflict_exempt=True /
    escalate_after_rounds=2；非法值回退缺省（bool 不当轮次数）。"""
    cfg = ConfigLoader.get_knowledge_lane_config({})
    assert cfg["no_conflict_exempt"] is True
    assert cfg["escalate_after_rounds"] == 2
    cfg = ConfigLoader.get_knowledge_lane_config(
        {"knowledge": {"no_conflict_exempt": False, "escalate_after_rounds": 3}}
    )
    assert cfg["no_conflict_exempt"] is False
    assert cfg["escalate_after_rounds"] == 3
    for bad in ("2", True, 0, -1, 1.5):
        cfg = ConfigLoader.get_knowledge_lane_config(
            {"knowledge": {"escalate_after_rounds": bad}}
        )
        assert cfg["escalate_after_rounds"] == 2, bad
    cfg = ConfigLoader.get_knowledge_lane_config({"knowledge": {"no_conflict_exempt": "yes"}})
    assert cfg["no_conflict_exempt"] is True
