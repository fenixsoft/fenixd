"""周期 audit 车道 + graph 生成 + 每日检查点单测（任务 3.1 / 3.3 / 4.1）。

fake spawn 替身 + 注入的 core.knowledge 替身，覆盖：
- audit 三支路：机械自修直提交 / 语义转写（含判无矛盾零改动）/ 零病灶；
- 转写失败 → 回滚 + todo.md 登记；
- 规模趋势超 +10% 标「需精简」；
- graph 三支路：成功 / CLI 缺失 / 禁用（另含执行失败、产物缺失）；
- 每日检查点：门控、自然日防重、异常不落日戳。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
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


def test_audit_semantic_rewrite_commits(proj, install_core):
    """矛盾（超时 300 vs 600）与跨页重复（禁用明文日志输出）→ 定向转写提交。"""
    install_core(FakeCore(proj))

    spawn_calls = {"n": 0}

    def spawn(prompt, run_id):
        if "定向转写" in prompt:
            spawn_calls["n"] += 1
            # 按病灶类型定向修复（每个 run 只处理本条候选，两个候选同页面，
            # prompt 均含对方规则文本，须以 FINDING_KIND 区分）
            beta = read_page(proj, "spec/knowledge/domains/dom-a/beta.md")
            if "contradiction" in prompt:
                beta = beta.replace("- 超时:600 秒。", "- 超时:300 秒。")
            elif "duplicate" in prompt:
                beta = beta.replace("- 禁用明文日志输出。\n", "")
            (proj / "spec/knowledge/domains/dom-a/beta.md").write_text(
                beta, encoding="utf-8"
            )
        return "ok"

    result = ka.run_audit(proj, spawn=spawn)
    assert result["counts"]["rewritten"] == 2
    assert spawn_calls["n"] == 2
    subjects = _git(proj, "log", "--format=%s")
    assert "audit rewrite contradiction" in subjects
    assert "audit rewrite duplicate" in subjects
    beta = read_page(proj, "spec/knowledge/domains/dom-a/beta.md")
    assert "超时:600" not in beta
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "转写明细" in report


def test_audit_no_conflict_verdict_counts_passed(proj, install_core):
    """转写 run 判「无矛盾」零改动收场：计入「过」，不产生转写提交。"""
    core = install_core(FakeCore(proj))
    result = ka.run_audit(proj, spawn=lambda p, r: "AUDIT_VERDICT: no-conflict")
    assert result["counts"]["rewritten"] == 0
    assert result["counts"]["passed"] >= 2  # 矛盾 + 重复 两候选均判无矛盾
    assert all("rewrite" not in m for _, m in core.commit_calls)
    report = (proj / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "判无矛盾" in report


def test_audit_rewrite_failure_rolls_back_and_registers_todo(proj, install_core):
    """转写 run 校验两轮仍失败：回滚半成品 + todo.md 登记 + 待人工计数。"""
    state = {"broken": False}

    def violations():
        return ["spec/knowledge/domains/dom-a/beta.md：marker 不可解析"] if state["broken"] else []

    install_core(FakeCore(proj, violations_fn=violations))

    def spawn(prompt, run_id):
        if "定向转写" in prompt:
            state["broken"] = True  # 修正轮也持续违规
        return "ok"

    result = ka.run_audit(proj, spawn=spawn)
    assert result["counts"]["rewritten"] == 0
    assert result["counts"]["pending_manual"] >= 1
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "转写失败" in todo
    # 半成品已回滚：真相源目录无未提交残留（.fenix 运行时文件除外）
    status = _git(proj, "status", "--porcelain", "--", "spec/knowledge")
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


# ── graph 生成（任务 4.1） ───────────────────────────────────────────────


def make_graph_artifacts(root: Path):
    gdir = root / "spec/knowledge/graph"
    gdir.mkdir(parents=True, exist_ok=True)
    (gdir / "graph.html").write_text("<html>g</html>\n")
    (gdir / "GRAPH_REPORT.md").write_text("# report\n")
    (gdir / "graph.json").write_text("{}\n")


def test_graph_success_commits_artifacts(proj, install_core):
    core = install_core(FakeCore(proj))
    logger = ListLogger()

    def run_cmd(cmd, timeout):
        assert cmd[0] == "/usr/bin/graphify"
        assert cmd[1] == "spec/knowledge"
        make_graph_artifacts(proj)

        class P:
            returncode = 0
            stderr = ""

        return P()

    result = ka.run_graph(
        proj, logger=logger, which=lambda name: "/usr/bin/graphify", run_cmd=run_cmd
    )
    assert result == {"triggered": True, "ok": True, "committed": True}
    # graph 产物 pathspec 限定提交入库（graph 车道不依赖 core.knowledge，
    # 直接走车道内 pathspec 提交）
    subjects = _git(proj, "log", "--format=%s")
    assert "[fenix] knowledge: graph update" in subjects
    assert (proj / "spec/knowledge/graph/graph.html").is_file()


def test_graph_cli_missing_failopen_single_line(proj, install_core):
    install_core(FakeCore(proj))
    logger = ListLogger()
    which_calls = []

    def which(name):
        which_calls.append(name)
        return None

    result = ka.run_graph(proj, logger=logger, which=which)
    assert result == {"triggered": False, "reason": "cli-missing"}
    assert which_calls == ["graphify"]
    info_lines = [m for lvl, m in logger.lines if lvl == "info"]
    assert len(info_lines) == 1  # 单行日志，无告警噪音
    assert "uv tool install graphifyy" in info_lines[0]


def test_graph_disabled_skips_silently(proj, install_core):
    install_core(FakeCore(proj))
    logger = ListLogger()

    def which(name):  # pragma: no cover - 禁用时不应被调用
        raise AssertionError("disabled lane must not probe CLI")

    result = ka.run_graph(
        proj,
        config={"knowledge": {"graph_enabled": False}},
        logger=logger,
        which=which,
    )
    assert result == {"triggered": False, "reason": "disabled"}
    assert logger.lines == []


def test_graph_cli_failure_and_missing_artifacts(proj, install_core):
    install_core(FakeCore(proj))
    logger = ListLogger()

    class P1:
        returncode = 1
        stderr = "boom"

    r1 = ka.run_graph(
        proj, logger=logger, which=lambda n: "g", run_cmd=lambda cmd, t: P1()
    )
    assert r1["reason"] == "cli-failed"
    r2 = ka.run_graph(
        proj, logger=logger, which=lambda n: "g", run_cmd=lambda cmd, t: None
    )
    # run_cmd 返回 None（returncode 缺省按非零）→ cli-failed
    assert r2["reason"] == "cli-failed"

    def run_ok_no_artifacts(cmd, timeout):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    r3 = ka.run_graph(
        proj, logger=logger, which=lambda n: "g", run_cmd=run_ok_no_artifacts
    )
    assert r3["reason"] == "artifacts-missing"


# ── 每日检查点（任务 3.3 调度门控） ──────────────────────────────────────


def make_lane(recorder, key, ret=None):
    def lane(project_root, logger=None):
        recorder.append(key)
        return ret if ret is not None else {"triggered": True, "ok": True}

    return lane


def test_daily_check_both_disabled_silent(proj):
    calls: list = []
    result = ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": False, "graph_enabled": False}},
        logger=ListLogger(),
        audit_lane=make_lane(calls, "audit"),
        graph_lane=make_lane(calls, "graph"),
    )
    assert result == {"triggered": False, "reason": "disabled"}
    assert calls == []


def test_daily_check_runs_each_lane_once_per_day(proj):
    calls: list = []
    cfg = {}
    logger = ListLogger()
    r1 = ka.knowledge_daily_check(
        proj,
        config=cfg,
        logger=logger,
        audit_lane=make_lane(calls, "audit"),
        graph_lane=make_lane(calls, "graph"),
    )
    assert r1["triggered"] is True
    assert sorted(calls) == ["audit", "graph"]
    # 同自然日第二周期：防重，不再调用
    ka.knowledge_daily_check(
        proj,
        config=cfg,
        logger=logger,
        audit_lane=make_lane(calls, "audit"),
        graph_lane=make_lane(calls, "graph"),
    )
    assert sorted(calls) == ["audit", "graph"]


def test_daily_check_independent_gates(proj):
    calls: list = []
    ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": False, "graph_enabled": True}},
        logger=ListLogger(),
        audit_lane=make_lane(calls, "audit"),
        graph_lane=make_lane(calls, "graph"),
    )
    assert calls == ["graph"]


def test_daily_check_crash_does_not_mark_day(proj):
    calls: list = []

    def bad_lane(project_root, logger=None):
        calls.append("audit")
        raise RuntimeError("boom")

    logger = ListLogger()
    r1 = ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": True, "graph_enabled": False}},
        logger=logger,
        audit_lane=bad_lane,
    )
    assert r1["results"]["audit"]["ok"] is False
    assert any(lvl == "error" for lvl, _ in logger.lines)
    # 未落日戳：下一周期重试
    ka.knowledge_daily_check(
        proj,
        config={"knowledge": {"audit_enabled": True, "graph_enabled": False}},
        logger=logger,
        audit_lane=bad_lane,
    )
    assert calls == ["audit", "audit"]
