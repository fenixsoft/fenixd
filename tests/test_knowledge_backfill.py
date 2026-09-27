"""存量回填车道单测（任务 2.2 / 2.3）。

fake spawn 替身 + 注入的 core.knowledge 替身（真实 import 路径经 sys.modules +
父包属性注入，接线语义与生产一致），覆盖：
- 全量成功（分批 + 校验提交 + 收敛汇报）；
- 聚类自举（清单缺失 → 自举 run 先行，bootstrap 提交先于批次提交）；
- 批失败续跑（单批校验两轮仍失败 → failed + todo.md，不阻塞后续批）；
- 中断重入（重入只处理 pending/failed，已蒸馏条目不重做；收敛后零派发）；
- core.knowledge 接线（validate_knowledge / commit_knowledge 复用与回退）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from core import knowledge_backfill as kb


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


ARCHIVES = ["arc-a1", "arc-a2", "arc-b1", "arc-b2", "arc-c1", "arc-d1"]
DOMAIN_MAP = {
    "arc-a1": "dom-a",
    "arc-a2": "dom-a",
    "arc-b1": "dom-b",
    "arc-b2": "dom-b",
    "arc-c1": "dom-c",
    "arc-d1": "dom-d",
}


@pytest.fixture
def proj(tmp_path):
    """临时主树：git 仓库（含基线提交）+ 6 个存量归档 + 预置域归位清单。"""
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    for name in ARCHIVES:
        d = root / "spec" / "archive" / name
        (d / "specs" / "cap-x").mkdir(parents=True)
        (d / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
        (d / "specs" / "cap-x" / "spec.md").write_text("delta\n", encoding="utf-8")
    (root / ".fenix").mkdir()
    (root / ".fenix" / "knowledge_backfill_domains.json").write_text(
        json.dumps(DOMAIN_MAP, ensure_ascii=False), encoding="utf-8"
    )
    return root


class FakeCore:
    """core.knowledge 替身：validate 可编程违规；commit 走真 git（批次提交真实
    落库，失败批回滚语义与生产一致），同时记录调用供接线断言。"""

    def __init__(self, root: Path, violations_fn=None, with_commit=True):
        self.root = root
        self.violations_fn = violations_fn or (lambda: [])
        self.validate_calls = 0
        self.commit_calls: list = []
        if with_commit:
            self.commit_knowledge = self._commit

    def _commit(self, project_root, paths, message) -> bool:
        self.commit_calls.append((list(paths), message))
        return kb.commit_pathspec(project_root, paths, message)

    def validate_knowledge(self, project_root):
        self.validate_calls += 1
        return list(self.violations_fn())


@pytest.fixture
def install_core(monkeypatch):
    """把替身经生产同款延迟导入路径装回（sys.modules + 父包属性）。"""

    def _install(core_obj, with_commit=True):
        mod = types.ModuleType("core.knowledge")
        mod.validate_knowledge = core_obj.validate_knowledge
        if with_commit:
            mod.commit_knowledge = core_obj._commit
        import core as core_pkg

        monkeypatch.setitem(sys.modules, "core.knowledge", mod)
        monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
        return core_obj

    return _install


class Recorder:
    """fake spawn：记录 (prompt, run_id)，委托 on_call 产出模拟 agent 写盘。"""

    def __init__(self, root: Path, on_call=None):
        self.root = root
        self.calls: list = []
        self.on_call = on_call

    def __call__(self, prompt: str, run_id: str) -> str:
        self.calls.append((prompt, run_id))
        if self.on_call:
            self.on_call(self, prompt, run_id)
        return "ok"


def write_page(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def page_text(archive: str) -> str:
    return (
        f"<!-- knowledge: capability=cap-{archive} rev=1 sources={archive} -->\n"
        f"# cap-{archive}\n\n## 规则\n\n- {archive} 的现行规则一句。\n"
    )


def batch_names(prompt: str) -> list[str]:
    return [
        ln[2:].strip() for ln in prompt.splitlines() if ln.startswith("- arc-")
    ]


def write_batch_pages(rec: Recorder, prompt: str) -> None:
    for name in batch_names(prompt):
        write_page(
            rec.root, f"spec/knowledge/domains/dom-x/cap-{name}.md", page_text(name)
        )


# ── 全量成功 ─────────────────────────────────────────────────────────────


def test_full_success_batches_commit_and_convergence(proj, install_core):
    core = install_core(FakeCore(proj))
    spawn = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    summary = kb.run_backfill(proj, spawn=spawn)

    assert summary["triggered"] is True
    assert summary["converged"] is True
    # 6 归档按 4 域聚批（每域一批，均 ≤20）：dom-a / dom-b / dom-c / dom-d
    assert summary["batches_total"] == 4
    assert summary["batches_ok"] == 4
    assert summary["counts"]["distilled"] == 6
    # 接线（任务 2.3）：校验器与提交工具来自 core.knowledge 替身
    assert core.validate_calls >= 1
    msgs = [m for _, m in core.commit_calls]
    assert msgs[0] == "[fenix] knowledge: backfill batch 1/4"
    assert msgs[-1] == "[fenix] knowledge: backfill batch 4/4"
    assert all("/spec/knowledge" not in m for m in msgs)  # 消息不含路径杂音
    log = _git(proj, "log", "--format=%s")
    assert "[fenix] knowledge: backfill batch" in log
    # 台账与收敛汇报文件落盘
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    assert ledger.count("distilled") == 6
    assert (proj / ".fenix" / "knowledge_backfill_report.md").is_file()
    # 收敛后重入零派发（幂等）
    spawn2 = Recorder(proj)
    again = kb.run_backfill(proj, spawn=spawn2)
    assert again["triggered"] is False
    assert again["reason"] == "converged"
    assert spawn2.calls == []


# ── 聚类自举 ─────────────────────────────────────────────────────────────


def test_bootstrap_run_commits_skeleton_before_batches(proj, install_core):
    install_core(FakeCore(proj))
    (proj / ".fenix" / "knowledge_backfill_domains.json").unlink()

    def on_call(rec, prompt, run_id):
        if run_id.startswith("kb-bootstrap"):
            (rec.root / ".fenix" / "knowledge_backfill_domains.json").write_text(
                json.dumps(DOMAIN_MAP, ensure_ascii=False), encoding="utf-8"
            )
            write_page(rec.root, "spec/knowledge/index.md", "# 真相源导航\n")
            return
        write_batch_pages(rec, prompt)

    spawn = Recorder(proj, on_call=on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    assert summary["batches_total"] == 4
    subjects = [
        ln
        for ln in _git(proj, "log", "--format=%s", "--reverse").splitlines()
        if ln.startswith("[fenix] knowledge:")
    ]
    assert subjects[0] == "[fenix] knowledge: backfill bootstrap"
    assert subjects[1].startswith("[fenix] knowledge: backfill batch 1/4")


def test_bootstrap_missing_domain_map_registers_todo(proj, install_core):
    install_core(FakeCore(proj))
    (proj / ".fenix" / "knowledge_backfill_domains.json").unlink()
    spawn = Recorder(proj)  # 自举 run 零产出
    result = kb.run_backfill(proj, spawn=spawn)
    assert result["ok"] is False
    assert result["reason"] == "bootstrap-no-domain-map"
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "### 知识真相源" in todo
    assert "域归位清单" in todo


# ── 批失败不阻塞后续批 + todo.md 登记 ────────────────────────────────────

POISON = "spec/knowledge/domains/dom-x/cap-arc-b1.md"


def test_batch_failure_marks_failed_and_continues(proj, install_core):
    def violations():
        return [f"{POISON}：超 150 行"] if (proj / POISON).exists() else []

    core = install_core(FakeCore(proj, violations_fn=violations))
    spawn = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    summary = kb.run_backfill(proj, spawn=spawn)

    assert summary["batches_failed"] == 1
    assert summary["batches_ok"] == 3  # dom-b 之后的批次照常派发提交
    assert summary["counts"]["failed"] == 2
    assert summary["counts"]["distilled"] == 4
    failed_names = {n for item in summary["failed"] for n in item["archives"]}
    assert failed_names == {"arc-b1", "arc-b2"}
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "回填批次" in todo
    # 失败批不产生提交（半成品已回滚）
    msgs = [m for _, m in core.commit_calls]
    assert len(msgs) == 3


def test_reentry_redoes_only_failed(proj, install_core):
    poison_on = {"on": True}

    def violations():
        if poison_on["on"] and (proj / POISON).exists():
            return [f"{POISON}：违规"]
        return []

    install_core(FakeCore(proj, violations_fn=violations))
    spawn1 = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    kb.run_backfill(proj, spawn=spawn1)

    # 环境修复后重跑：只处理 pending/failed 条目
    poison_on["on"] = False
    spawn2 = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    summary = kb.run_backfill(proj, spawn=spawn2)

    assert summary["converged"] is True
    assert summary["counts"]["distilled"] == 6
    all_prompts = "\n".join(p for p, _ in spawn2.calls)
    assert "arc-b1" in all_prompts and "arc-b2" in all_prompts
    for done in ("arc-a1", "arc-a2", "arc-c1", "arc-d1"):
        assert f"- {done}\n" not in all_prompts
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    statuses = [
        json.loads(ln)["status"] for ln in ledger.splitlines() if ln.strip()
    ]
    assert statuses.count("distilled") == 6
    assert "failed" not in statuses


# ── 中断重入（中断批按失败处置，重跑不重做已完成批） ────────────────────


def test_interrupted_run_resumes_without_redo(proj, install_core):
    install_core(FakeCore(proj))
    seen = {"dom-b": False}

    def crash_on_dom_b(rec, prompt, run_id):
        names = batch_names(prompt)
        if "arc-b1" in names and not seen["dom-b"]:
            seen["dom-b"] = True
            raise RuntimeError("daemon 重启，run 中断")
        write_batch_pages(rec, prompt)

    spawn1 = Recorder(proj, on_call=crash_on_dom_b)
    summary = kb.run_backfill(proj, spawn=spawn1)
    assert summary["batches_failed"] == 1
    assert summary["batches_ok"] == 3

    spawn2 = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    summary2 = kb.run_backfill(proj, spawn=spawn2)
    assert summary2["converged"] is True
    for prompt, _ in spawn2.calls:
        for done in ("arc-a1", "arc-a2", "arc-c1", "arc-d1"):
            assert f"- {done}\n" not in prompt


# ── 前置缺失与提交工具回退 ───────────────────────────────────────────────


def test_skips_without_knowledge_core(proj, monkeypatch):
    monkeypatch.setattr(kb, "load_knowledge_core", lambda: None)
    spawn = Recorder(proj)
    result = kb.run_backfill(proj, spawn=spawn)
    assert result == {"triggered": False, "reason": "knowledge-core-unavailable"}
    assert spawn.calls == []


def test_commit_fallback_without_core_helper(proj, install_core):
    """core.knowledge 未提供提交工具时回退车道内 pathspec 提交（任务 2.3）。"""
    install_core(FakeCore(proj), with_commit=False)
    spawn = Recorder(proj, on_call=lambda rec, p, r: write_batch_pages(rec, p))
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    log = _git(proj, "log", "--format=%s")
    assert "[fenix] knowledge: backfill batch 1/4" in log
    assert "[fenix] knowledge: backfill batch 4/4" in log


# ── 批次划分 ─────────────────────────────────────────────────────────────


def test_build_batches_cap_and_grouping():
    domain_map = {f"a{i}": "d1" for i in range(25)}
    domain_map.update({f"b{i}": "d2" for i in range(3)})
    domain_map["orphan"] = ""
    batches = kb.build_batches(domain_map, sorted(domain_map))
    assert all(len(b) <= kb.BATCH_SIZE_MAX for b in batches)
    assert sum(len(b) for b in batches) == 29
    assert [len(b) for b in batches] == [1, 20, 5, 3]  # 兜底域 + d1 两片 + d2
