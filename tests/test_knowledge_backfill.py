"""存量回填车道单测（fix-knowledge-backfill-reconstruction，方案 B 聚合语义）。

fake spawn 替身 + 注入的 core.knowledge 替身（真实 import 路径经 sys.modules +
父包属性注入，接线语义与生产一致），覆盖：
- 链索引确定性（同输入同链序，日期前缀升序）；
- 全量成功（能力聚合批次 + ADR 抽取批次 + 校验提交 + 分维度收敛汇报）；
- 多归档能力一次成文（×3 链产 rev=3、sources 全链、无逐归档重放）；
- 批次顺序无关（颠倒输入同划分）；
- 台账 v2 断点续跑（legacy 作废重建、failed 不阻塞、维度独立）；
- bootstrap 能力清单输入；ADR 无 design.md 留痕跳过；
- core.knowledge 接线（validate_knowledge / commit_knowledge 复用与回退）。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import pytest

from core import evolution  # 写后就地提交的复用助手（add-todo-append-commit-on-write）
from core import knowledge as knowledge_impl  # 真模块引用（排队门 e2e 用；不受替身注入影响）
from core import knowledge_backfill as kb


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# 有日期前缀的归档名（链索引日期升序的直接证据）；cap-x 被 3 个归档触碰
ARCHIVE_SPECS = {
    "2026-09-01-arc-a1": ["cap-x"],
    "2026-09-02-arc-a2": ["cap-x"],
    "2026-09-03-arc-b1": ["cap-x", "cap-y"],
    "2026-09-04-arc-c1": ["cap-y"],
}
WITH_DESIGN = ["2026-09-01-arc-a1", "2026-09-03-arc-b1"]
DOMAIN_MAP = {"cap-x": "dom-x", "cap-y": "dom-y"}


@pytest.fixture
def proj(tmp_path):
    """临时主树：git 仓库（含基线提交）+ 4 个存量归档 + 预置域归位清单。

    a2/c1 无 design.md（ADR 维度留痕跳过支路）；域清单按能力名归位
    （方案 B：聚类对象从归档名改为能力名）。
    """
    root = tmp_path / "main"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    for name, caps in ARCHIVE_SPECS.items():
        d = root / "spec" / "archive" / name
        for cap in caps:
            (d / "specs" / cap).mkdir(parents=True)
            (d / "specs" / cap / "spec.md").write_text("delta\n", encoding="utf-8")
        (d / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
        if name in WITH_DESIGN:
            (d / "design.md").write_text("# 设计\n\n## Decisions\n\n- 架构级选型\n", encoding="utf-8")
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


# ── fake spawn 的产物模拟（按提示词语义逐字驱动） ────────────────────────


def batch_caps(prompt: str) -> list[str]:
    """解析模式二批次清单（能力名 + 链长 + 链序）。"""
    seg = prompt.split("本批能力清单（共", 1)[1]
    return re.findall(r"^- ([a-z0-9][a-z0-9-]*)（链", seg, re.M)


def cap_chain(prompt: str, cap: str) -> list[str]:
    m = re.search(rf"^- {cap}（链 (\d+) 份 delta：([^）]*)）", prompt, re.M)
    assert m, f"批次清单缺少 {cap} 链标注"
    return m.group(2).split(" → ") if int(m.group(1)) else []


def adr_archives(prompt: str) -> list[str]:
    seg = prompt.split("本批归档清单（共", 1)[1]
    return re.findall(r"^- (\S+)$", seg, re.M)


def agg_page(cap: str, chain: list[str], baseline: str | None = None) -> str:
    """聚合语义页面：rev=链长、sources 全链、溯源按时间序、只有最终态规则。"""
    src = ",".join(f"spec/archive/{a}" for a in chain)
    lines = [
        f"<!-- knowledge: capability={cap} rev={len(chain)} sources={src} -->",
        f"# {cap}",
        "",
        "## 规则",
        "",
        f"- {cap} 最终态规则一句。",
        "",
        "## 溯源",
    ]
    if baseline:
        lines.append(f"- 2026-09-02 史前复原 — 迁移期已存在的基础规则")
    for a in chain:
        lines.append(f"- {a[:10]} {a} — 贡献一句")
    return "\n".join(lines) + "\n"


def write_batch_pages(rec: Recorder, prompt: str) -> None:
    domain_map = json.loads(
        (rec.root / ".fenix" / "knowledge_backfill_domains.json").read_text(encoding="utf-8")
    )
    for cap in batch_caps(prompt):
        chain = cap_chain(prompt, cap)
        write_page(
            rec.root,
            f"spec/knowledge/domains/{domain_map.get(cap, '_unassigned')}/{cap}.md",
            agg_page(cap, chain),
        )


def write_adr(rec: Recorder, prompt: str) -> None:
    for i, name in enumerate(adr_archives(prompt), 1):
        write_page(
            rec.root,
            f"spec/knowledge/adr/ADR-{i:03d}-decision-{name}.md",
            f"# ADR-{i:03d}：x\n\ndate: 2026-09-27\nstatus: accepted\n\n"
            "## Context\n\nc\n\n## Decision\n\nd\n\n## Consequences\n\ne\n",
        )


def bootstrap_writer(rec: Recorder, prompt: str) -> None:
    (rec.root / ".fenix" / "knowledge_backfill_domains.json").write_text(
        json.dumps(DOMAIN_MAP, ensure_ascii=False), encoding="utf-8"
    )
    write_page(rec.root, "spec/knowledge/index.md", "# 真相源导航\n")


# 史前清单：cap-x 已被归档覆盖（baseline 走链头）、cap-pre 未覆盖（产史前页）
INVENTORY = [
    {"capability": "cap-x", "domain": "dom-x", "baseline": "史前基线：迁移期轮询为 600 秒。"},
    {"capability": "cap-pre", "domain": "dom-x", "baseline": "史前独有能力基线。"},
]


def prehistoric_writer(rec: Recorder, prompt: str) -> None:
    (rec.root / ".fenix" / "knowledge_backfill_prehistoric.json").write_text(
        json.dumps(INVENTORY, ensure_ascii=False), encoding="utf-8"
    )
    write_page(
        rec.root,
        "spec/knowledge/domains/dom-x/cap-pre.md",
        "<!-- knowledge: capability=cap-pre rev=1 origin=prehistoric "
        "sources=git:abc123456-..2026-09-02 -->\n"
        "# cap-pre\n\n## 规则\n\n- 现行规则一句。\n\n## 溯源\n\n"
        "- 2026-09-02 史前复原 — 迁移期已存在的基础规则\n",
    )


def default_on_call(rec: Recorder, prompt: str, run_id: str) -> None:
    if run_id.startswith("kb-bootstrap"):
        bootstrap_writer(rec, prompt)
    elif run_id.startswith("kb-prehistoric"):
        prehistoric_writer(rec, prompt)
    elif run_id.startswith("kb-adr"):
        write_adr(rec, prompt)
    else:
        write_batch_pages(rec, prompt)


def knowledge_subjects(root: Path) -> list[str]:
    return [
        ln
        for ln in _git(root, "log", "--format=%s", "--reverse").splitlines()
        if ln.startswith("[fenix] knowledge:")
    ]


# ── 链索引确定性（任务 1.4） ─────────────────────────────────────────────


def test_chain_index_deterministic_and_date_order(proj):
    idx = kb.build_chain_index(proj)
    assert idx["cap-x"] == [
        "2026-09-01-arc-a1", "2026-09-02-arc-a2", "2026-09-03-arc-b1",
    ]
    assert idx["cap-y"] == ["2026-09-03-arc-b1", "2026-09-04-arc-c1"]
    # 同输入同链序（纯函数零 LLM）
    assert kb.build_chain_index(proj) == idx


# ── 全量成功：能力批次 + ADR 批次 + 分维度收敛（任务 1.4 / 1.5） ──────────


def test_full_success_capability_and_adr_batches(proj, install_core):
    core = install_core(FakeCore(proj))
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)

    assert summary["triggered"] is True
    assert summary["converged"] is True
    # 2 能力各归其域 → 2 个能力批；4 归档中 2 个有 design.md → 1 个 ADR 批
    assert summary["batches_total"] == 2
    assert summary["batches_ok"] == 2
    assert summary["adr_batches_total"] == 1
    assert summary["adr_batches_ok"] == 1
    assert summary["adr_skipped_no_design"] == [
        "2026-09-02-arc-a2", "2026-09-04-arc-c1",
    ]
    # 分维度计数（台账 v2）
    assert summary["counts"]["capability"] == {
        "pending": 0, "distilled": 2, "failed": 0,
    }
    assert summary["counts"]["adr"] == {
        "pending": 0, "distilled": 4, "failed": 0,
    }
    assert core.validate_calls >= 1
    # 提交序列：史前复原 → 能力批 → ADR 批
    msgs = [m for _, m in core.commit_calls]
    assert msgs == [
        "[fenix] knowledge: backfill prehistoric",
        "[fenix] knowledge: backfill batch 1/2",
        "[fenix] knowledge: backfill batch 2/2",
        "[fenix] knowledge: backfill adr batch 1/1",
    ]
    # 台账 v2 键形态与分维度落盘
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    assert "capability:cap-x" in ledger and "adr:2026-09-01-arc-a1" in ledger
    assert ledger.count('"status": "distilled"') == 6
    assert (proj / ".fenix" / "knowledge_backfill_report.md").is_file()
    # 收敛后重入零派发（幂等）
    spawn2 = Recorder(proj)
    again = kb.run_backfill(proj, spawn=spawn2)
    assert again["triggered"] is False
    assert again["reason"] == "converged"
    assert spawn2.calls == []


# ── 多归档能力一次成文（×3 链，任务 1.4） ────────────────────────────────


def test_multi_archive_capability_single_shot(proj, install_core):
    install_core(FakeCore(proj))
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True

    batch_prompts = [p for p, r in spawn.calls if r.startswith("kb-batch")]
    x_prompt = next(p for p in batch_prompts if "cap-x" in p)
    # 提示词携带完整 3 归档链（日期升序），且无逐归档重放指引
    assert (
        "cap-x（链 3 份 delta：2026-09-01-arc-a1 → 2026-09-02-arc-a2 → "
        "2026-09-03-arc-b1）" in x_prompt
    )
    assert "逐归档" not in x_prompt or "禁止逐归档重放" in x_prompt
    # 产物：rev=3、sources 全链、溯源按时间序、无中间态规则
    page = (
        proj / "spec/knowledge/domains/dom-x/cap-x.md"
    ).read_text(encoding="utf-8")
    assert "rev=3" in page
    for a in ("2026-09-01-arc-a1", "2026-09-02-arc-a2", "2026-09-03-arc-b1"):
        assert f"spec/archive/{a}" in page
    assert "最终态规则" in page
    # 只有一个规则条目（一次成文，非 ×3 重放叠加）
    assert page.count("- cap-x 最终态规则一句。") == 1
    # 溯源段链序完整
    trail = page.split("## 溯源")[1]
    assert trail.index("2026-09-01-arc-a1") < trail.index("2026-09-02-arc-a2") < trail.index(
        "2026-09-03-arc-b1"
    )


# ── 批次顺序无关（任务 1.4） ─────────────────────────────────────────────


def test_batch_order_independence():
    domain_map = {f"cap-{i:02d}": "d1" for i in range(25)}
    domain_map.update({f"capb-{i:02d}": "d2" for i in range(3)})
    names = sorted(domain_map)
    forward = kb.build_batches(domain_map, names)
    backward = kb.build_batches(domain_map, list(reversed(names)))
    assert forward == backward  # 划分与输入顺序无关（确定性排序）
    assert all(len(b) <= kb.BATCH_SIZE_MAX for b in forward)
    assert sum(len(b) for b in forward) == 28


# ── bootstrap：能力清单输入（任务 1.4） ──────────────────────────────────


def test_bootstrap_input_is_capability_set(proj, install_core):
    install_core(FakeCore(proj))
    (proj / ".fenix" / "knowledge_backfill_domains.json").unlink()
    seen: dict = {}

    def on_call(rec, prompt, run_id):
        if run_id.startswith("kb-bootstrap"):
            seen["prompt"] = prompt
            bootstrap_writer(rec, prompt)
            return
        default_on_call(rec, prompt, run_id)

    spawn = Recorder(proj, on_call=on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    bp = seen["prompt"]
    assert "能力清单（共 2 个）" in bp
    assert "- cap-x" in bp and "- cap-y" in bp
    assert "- 2026-09-01-arc-a1" not in bp  # 聚类对象不再是归档名
    # bootstrap 提交先于 prehistoric 与批次提交
    subjects = knowledge_subjects(proj)
    assert subjects[0] == "[fenix] knowledge: backfill bootstrap"
    assert subjects[1] == "[fenix] knowledge: backfill prehistoric"
    assert subjects[2].startswith("[fenix] knowledge: backfill batch 1/2")


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


# ── 台账 v2：legacy 作废重建（任务 1.3 / 1.4） ───────────────────────────


def test_ledger_v2_discards_legacy_entries(proj, install_core):
    install_core(FakeCore(proj))
    (proj / ".fenix" / "knowledge_backfill.jsonl").write_text(
        json.dumps({"name": "arc-a1", "status": "distilled"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    # 旧归档粒度条目作废：无裸归档名键，全部带维度前缀
    for ln in ledger.splitlines():
        if ln.strip():
            key = json.loads(ln)["name"]
            assert key.startswith(("capability:", "adr:")), key
    assert '"name": "arc-a1"' not in ledger


# ── 批失败不阻塞后续批/ADR 维度 + 断点续跑（任务 1.4） ────────────────────

POISON = "spec/knowledge/domains/dom-x/cap-x.md"


def test_capability_failure_not_blocking_and_resume(proj, install_core):
    poison_on = {"on": True}

    def violations():
        if poison_on["on"] and (proj / POISON).exists():
            return [f"{POISON}：违规"]
        return []

    install_core(FakeCore(proj, violations_fn=violations))
    spawn1 = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn1)

    # cap-x 批失败：不阻塞 cap-y 批，也不阻塞 ADR 维度
    assert summary["batches_failed"] == 1
    assert summary["batches_ok"] == 1
    assert summary["adr_batches_ok"] == 1
    assert summary["counts"]["capability"] == {
        "pending": 0, "distilled": 1, "failed": 1,
    }
    assert summary["converged"] is False
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "回填批次" in todo
    failed_caps = {c for item in summary["failed"] for c in item["capabilities"]}
    assert failed_caps == {"cap-x"}

    # 环境修复后重跑：只重做 failed 能力维度条目，ADR 维度不再派发
    poison_on["on"] = False
    spawn2 = Recorder(proj, on_call=default_on_call)
    summary2 = kb.run_backfill(proj, spawn=spawn2)
    assert summary2["converged"] is True
    run_ids = [r for _, r in spawn2.calls]
    assert any(r.startswith("kb-batch") for r in run_ids)
    assert not any(r.startswith("kb-adr") for r in run_ids)  # ADR 已终态不重做
    batch_prompt = next(p for p, r in spawn2.calls if r.startswith("kb-batch"))
    assert "cap-x" in batch_prompt
    assert "cap-y" not in batch_prompt  # 已蒸馏能力不重做
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    statuses = [
        json.loads(ln)["status"] for ln in ledger.splitlines() if ln.strip()
    ]
    assert "failed" not in statuses
    assert statuses.count("distilled") == 6


# ── ADR 维度消化与无 design.md 跳过（任务 1.5 两支路） ────────────────────


def test_adr_batch_consumed_and_no_design_skipped(proj, install_core):
    install_core(FakeCore(proj))
    adr_calls: list[str] = []

    def on_call(rec, prompt, run_id):
        if run_id.startswith("kb-adr"):
            adr_calls.extend(adr_archives(prompt))
        default_on_call(rec, prompt, run_id)

    spawn = Recorder(proj, on_call=on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    # ADR 批只收含 design.md 的归档
    assert adr_calls == ["2026-09-01-arc-a1", "2026-09-03-arc-b1"]
    # 无 design.md：零 run 直接标 distilled 留痕（跳过清单 + 台账终态）
    assert summary["adr_skipped_no_design"] == [
        "2026-09-02-arc-a2", "2026-09-04-arc-c1",
    ]
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    entries = {
        json.loads(ln)["name"]: json.loads(ln)["status"]
        for ln in ledger.splitlines()
        if ln.strip()
    }
    assert entries["adr:2026-09-02-arc-a2"] == "distilled"
    assert entries["adr:2026-09-04-arc-c1"] == "distilled"
    report = (proj / ".fenix" / "knowledge_backfill_report.md").read_text(encoding="utf-8")
    assert "无 design.md" in report


def test_no_design_only_ledger_persisted(proj, install_core):
    """纯 no_design 场景（零 ADR 批 run）：留痕跳过必须落盘。

    回归锁：save 原先只在批次循环内，adr_batches 为空时 mark 只改内存，
    台账文件停在 pending → has_pending 恒真 → 排队门永久阻塞增量派发。
    """
    (proj / "spec" / "archive" / "2026-09-01-arc-a1" / "design.md").unlink()
    (proj / "spec" / "archive" / "2026-09-03-arc-b1" / "design.md").unlink()
    install_core(FakeCore(proj))
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    assert summary["adr_batches_total"] == 0
    ledger = (proj / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    statuses = {
        json.loads(ln)["name"]: json.loads(ln)["status"]
        for ln in ledger.splitlines()
        if ln.strip()
    }
    assert all(
        v == "distilled" for k, v in statuses.items() if k.startswith("adr:")
    ), statuses
    # 排队门随之释放：重入收敛零派发
    assert kb.ledger_has_pending(proj) is False


def test_adr_failure_marks_failed_and_registers_todo(proj, install_core):
    poison_adr = "spec/knowledge/adr/ADR-001-decision-2026-09-01-arc-a1.md"

    def violations():
        if (proj / poison_adr).exists():
            return [f"{poison_adr}：违规"]
        return []

    install_core(FakeCore(proj, violations_fn=violations))
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["adr_batches_failed"] == 1
    assert summary["counts"]["adr"]["failed"] == 2  # 失败批整批标 failed
    assert summary["counts"]["adr"]["distilled"] == 2  # 跳过支路不受影响
    assert summary["converged"] is False
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "回填 ADR 批次" in todo


# ── 聚合回填全流程 e2e（任务 4.1）：回填期排队登记 → 二轮消化收敛 ─────────


def seed_archive_d1(root: Path) -> None:
    """回填期新归档：触达排队中的 cap-y（二轮扩链重聚合的证据）。"""
    d = root / "spec" / "archive" / "2026-09-05-arc-d1"
    (d / "specs" / "cap-y").mkdir(parents=True)
    (d / "specs" / "cap-y" / "spec.md").write_text("delta\n", encoding="utf-8")
    (d / "proposal.md").write_text("# 2026-09-05-arc-d1\n", encoding="utf-8")


def read_ledger(root: Path) -> dict:
    text = (root / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    return {
        json.loads(ln)["name"]: json.loads(ln)["status"]
        for ln in text.splitlines()
        if ln.strip()
    }


def test_full_loop_dispatch_queue_then_drain(proj, install_core):
    """全流程：首轮史前段失败早退（台账全 pending 落盘）→ 回填期新归档经
    dispatch_distill 排队门登记入台账（不派发增量 run）→ 二轮断点续跑消化
    收敛，排队能力以扩链后的全链（含新归档）重新聚合。"""
    install_core(FakeCore(proj))
    # 首轮：史前 run 不产清单 → 早退，台账保持 reconcile 出的全 pending
    stall = Recorder(proj, on_call=lambda rec, p, r: None)
    first = kb.run_backfill(proj, spawn=stall)
    assert first["ok"] is False
    assert first["reason"] == "prehistoric-no-inventory"
    assert read_ledger(proj)["capability:cap-y"] == "pending"

    # 回填期新归档派发被排队门拦截：登记 adr 键、不真派发（dispatcher 未触）
    seed_archive_d1(proj)
    calls: list = []

    class Fake:
        def dispatch(self, proot, names):
            calls.append(list(names))

    r = knowledge_impl.dispatch_distill(
        proj, "2026-09-05-arc-d1", {"knowledge": {"enabled": True}}, dispatcher=Fake()
    )
    assert r == {"dispatched": False, "reason": "backfill-queued"}
    assert calls == []
    assert read_ledger(proj)["adr:2026-09-05-arc-d1"] == "pending"

    # 二轮：史前正常 → 断点续跑消化全部 pending；cap-y 以扩链 3 链重新聚合
    spawn = Recorder(proj, on_call=default_on_call)
    second = kb.run_backfill(proj, spawn=spawn)
    assert second["converged"] is True
    batch_prompts = [p for p, run in spawn.calls if run.startswith("kb-batch")]
    y_prompt = next(p for p in batch_prompts if "cap-y" in p)
    assert cap_chain(y_prompt, "cap-y") == [
        "2026-09-03-arc-b1", "2026-09-04-arc-c1", "2026-09-05-arc-d1",
    ]
    final = read_ledger(proj)
    assert final["capability:cap-y"] == "distilled"
    assert final["adr:2026-09-05-arc-d1"] == "distilled"
    assert kb.ledger_has_pending(proj) is False


# ── 史前求差与基线链头（任务 2.3） ───────────────────────────────────────


def test_prehistoric_diff_and_baseline_chain_head(proj, install_core):
    install_core(FakeCore(proj))
    seen: dict = {}

    def on_call(rec, prompt, run_id):
        if run_id.startswith("kb-prehistoric"):
            seen["prompt"] = prompt
        default_on_call(rec, prompt, run_id)

    spawn = Recorder(proj, on_call=on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    # 史前 run 输入携带求差基准（归档链能力全集）
    assert "- cap-x" in seen["prompt"] and "- cap-y" in seen["prompt"]
    # 提交序：prehistoric 在能力批之前
    subjects = knowledge_subjects(proj)
    assert subjects[0] == "[fenix] knowledge: backfill prehistoric"
    assert subjects[1].startswith("[fenix] knowledge: backfill batch 1/2")
    # 未覆盖能力产史前页（入域、origin=prehistoric）
    pre_page = (
        proj / "spec/knowledge/domains/dom-x/cap-pre.md"
    ).read_text(encoding="utf-8")
    assert "origin=prehistoric" in pre_page
    # 已覆盖能力：baseline 注入批次提示词作链头输入
    batch_prompt = next(p for p, r in spawn.calls if r.startswith("kb-batch") and "cap-x" in p)
    assert "史前基线（链头输入）：史前基线：迁移期轮询为 600 秒。" in batch_prompt
    # 未覆盖能力不进聚合批次（不写页，diff 排除）
    all_batch_prompts = "\n".join(p for p, r in spawn.calls if r.startswith("kb-batch"))
    assert "cap-pre" not in all_batch_prompts
    y_prompt = next(p for p, r in spawn.calls if r.startswith("kb-batch") and "cap-y" in p)
    # cap-y 无史前基线：批次清单块不注入链头（模板正文的语义说明除外）
    assert "史前基线（链头输入）" not in y_prompt
    # 重入：清单已持久化，prehistoric 不重跑，收敛零派发
    spawn2 = Recorder(proj)
    again = kb.run_backfill(proj, spawn=spawn2)
    assert again["reason"] == "converged"
    assert spawn2.calls == []


def test_prehistoric_missing_page_blocks_with_todo(proj, install_core):
    install_core(FakeCore(proj))

    def incomplete_prehistoric(rec, prompt, run_id):
        # 只写清单不写未覆盖能力页 → 求差核验拦截
        (rec.root / ".fenix" / "knowledge_backfill_prehistoric.json").write_text(
            json.dumps(INVENTORY, ensure_ascii=False), encoding="utf-8"
        )

    spawn = Recorder(proj, on_call=incomplete_prehistoric)
    result = kb.run_backfill(proj, spawn=spawn)
    assert result["ok"] is False
    assert result["reason"] == "prehistoric-missing-pages"
    todo = (proj / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert "cap-pre" in todo


# ── 自举重跑清理 fixture 遗留（任务 2.3） ────────────────────────────────


def test_bootstrap_cleans_fixture_leftovers(proj, install_core):
    install_core(FakeCore(proj))
    # 未跟踪 fixture 残留（e2e 污染形态：zn 演示域 / fixture ADR / graph 产物）
    write_page(
        proj, "spec/knowledge/domains/zn-demo-domain/zn-demo-capability.md", "# zn\n"
    )
    write_page(proj, "spec/knowledge/adr/ADR-001-zn-one.md", "# ADR-001：zn\n")
    write_page(proj, "spec/knowledge/graph/graph.html", "<html>zn</html>\n")
    # 已入库遗留域（真实聚类不再归位 → 重建时移除）
    write_page(proj, "spec/knowledge/domains/dom-stale/old.md", "# old\n")
    _git(proj, "add", "--", "spec/knowledge/domains/dom-stale")
    _git(proj, "commit", "-qm", "seed stale domain")
    (proj / ".fenix" / "knowledge_backfill_domains.json").unlink()

    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    # 未跟踪残留被清场
    assert not (proj / "spec/knowledge/domains/zn-demo-domain").exists()
    assert not (proj / "spec/knowledge/adr/ADR-001-zn-one.md").exists()
    assert not (proj / "spec/knowledge/graph").exists()
    # 已跟踪遗留域被真实聚类重建移除
    assert not (proj / "spec/knowledge/domains/dom-stale").exists()
    # 真实产物不受影响
    assert (proj / "spec/knowledge/domains/dom-x/cap-x.md").is_file()


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
    spawn = Recorder(proj, on_call=default_on_call)
    summary = kb.run_backfill(proj, spawn=spawn)
    assert summary["converged"] is True
    log = _git(proj, "log", "--format=%s")
    assert "[fenix] knowledge: backfill batch 1/2" in log
    assert "[fenix] knowledge: backfill adr batch 1/1" in log


# ── 批次划分（能力粒度，域内切片 ≤20） ───────────────────────────────────


def test_build_batches_cap_and_grouping():
    domain_map = {f"cap-{i:02d}": "d1" for i in range(25)}
    domain_map.update({f"capb-{i:02d}": "d2" for i in range(3)})
    domain_map["orphan"] = ""
    batches = kb.build_batches(domain_map, sorted(domain_map))
    assert all(len(b) <= kb.BATCH_SIZE_MAX for b in batches)
    assert sum(len(b) for b in batches) == 29
    assert [len(b) for b in batches] == [1, 20, 5, 3]  # 兜底域 + d1 两片 + d2


# ── 失败归因降噪（reduce-cli-stderr-noise-attribution D3） ───────────────

NOISE_LINE = ("[claude-code:unrecognized_model] Model 'glm-5.3-flash' "
              "is not a valid model name")


def _fake_proc(returncode: int, stdout: str, stderr: str):
    return subprocess.CompletedProcess(
        args=["claude", "-p"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_popen_proc(returncode: int, stdout: str, stderr: str):
    """default_spawn 的 Popen+communicate 替身（spawn 进程组化后的新缝）。"""

    class _Proc:
        # pid=-1：os.getpgid(-1) 确定性抛 ProcessLookupError——替身进程组查询
        # 永远失败、清场走 proc.kill() 兜底（下方 no-op），绝不解析到真实进程
        # 组。此前 pid=0 会让 getpgid(0) 解析到 pytest 自身进程组，killpg 清场
        # 直接团灭整个测试运行（全量回归在 51% 处 -9 暴毙、junit 缺失 →
        # parse_error 的根因，2026-10-07）。
        pid = -1

        def __init__(self, rc, out, err):
            self.returncode = rc
            self._io = (out, err)

        # 签名对齐真实 Popen.communicate(prompt, timeout=...)：此前缺 prompt
        # 形参，真实调用以 TypeError 落入 spawn 的异常清场分支，走不到本替身
        # 想模拟的「退出码 1 + stderr 噪声」归因路径。
        def communicate(self, prompt, timeout=None):
            return self._io

        def kill(self):
            pass

    return _Proc(returncode, stdout, stderr)


def test_failure_attribution_tail_filters_noise_lines():
    """stderr 混合噪声 + 真实死因：归因取过滤后尾部，不含噪声行。"""
    stderr = (
        f"{NOISE_LINE}\n"
        "Traceback: upstream error\n"
        "API Error: Request rejected (429)\n"
    )
    tail = kb._failure_attribution_tail("", stderr)
    assert "API Error: Request rejected (429)" in tail
    assert "unrecognized_model" not in tail
    assert "Traceback: upstream error" in tail


def test_failure_attribution_tail_falls_back_to_stdout_tail():
    """stderr 全噪声：回退 stdout 尾部（stdout 不过滤）。"""
    stdout = "loading...\nAPI Error: Request rejected (429)\n"
    tail = kb._failure_attribution_tail(stdout, f"{NOISE_LINE}\n")
    assert "API Error: Request rejected (429)" in tail
    assert "unrecognized_model" not in tail
    assert tail.endswith("API Error: Request rejected (429)")
    # 两者皆空：返回空串，归因仅保留退出码前缀（调用方拼装）
    assert kb._failure_attribution_tail("", f"{NOISE_LINE}\n") == ""
    assert kb._failure_attribution_tail("", "") == ""


def test_spawn_failure_attribution_uses_filtered_tail(proj, monkeypatch):
    """spawn 失败归因端到端：噪声行不进归因文本，真实 429 死因可见。"""
    monkeypatch.setattr(
        kb.subprocess, "Popen",
        lambda *a, **k: _fake_popen_proc(1, "", f"{NOISE_LINE}\n"),
    )
    spawn = kb.default_spawn(proj)
    with pytest.raises(RuntimeError) as ei:
        spawn("prompt", "kb-attrib-noise")
    msg = str(ei.value)
    assert "退出码 1" in msg
    assert "unrecognized_model" not in msg


def test_spawn_failure_attribution_falls_back_to_stdout(proj, monkeypatch):
    """stderr 全噪声且 stdout 含 429 死因：归因回退 stdout 尾部。

    `.out` 留档不受影响——stdout/stderr 原始双留证，降噪只作用于归因消息。
    """
    stdout = "boot ok\nAPI Error: Request rejected (429)\n"
    monkeypatch.setattr(
        kb.subprocess, "Popen",
        lambda *a, **k: _fake_popen_proc(1, stdout, f"{NOISE_LINE}\n"),
    )
    spawn = kb.default_spawn(proj)
    with pytest.raises(RuntimeError) as ei:
        spawn("prompt", "kb-attrib-stdout")
    msg = str(ei.value)
    assert "API Error: Request rejected (429)" in msg
    assert "unrecognized_model" not in msg
    out_file = proj / ".fenix" / "runs" / "kb-attrib-stdout.out"
    assert out_file.is_file()
    body = out_file.read_text(encoding="utf-8")
    assert NOISE_LINE in body  # 留证现场完整（原始 stderr 不滤）
    assert "API Error: Request rejected (429)" in body


# ── todo.md 写后就地提交（add-todo-append-commit-on-write） ────────────────


@pytest.fixture
def tracked_todo_proj(tmp_path):
    """git 仓库夹具：``.fenix/todo.md`` 已被跟踪（含基线提交），用于提交形态断言。"""
    root = tmp_path / "todo_repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / ".fenix").mkdir()
    (root / ".fenix" / "todo.md").write_text("## 待办\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


def _todo_commit_count(root: Path) -> int:
    """触及 .fenix/todo.md 的提交总数。"""
    return len(_git(root, "log", "--format=%H", "--", ".fenix/todo.md").split())


def _head_commit_files(root: Path) -> list[str]:
    """HEAD 提交包含的文件清单（name-only，按空白切分）。"""
    return _git(root, "show", "--name-only", "--format=", "HEAD").split()


def test_append_commit_todo_only_and_not_sweep_staged(tracked_todo_proj):
    """2.1 实际追加后恰一个仅含 todo.md 的提交；索引预置他物不被卷入。"""
    root = tracked_todo_proj
    (root / "other.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "other.txt")  # 预置他物入索引（并发暂存场景）

    assert kb.append_todo_line(root, "蒸馏重试登记") is True

    assert _todo_commit_count(root) == 2  # 基线 + 本次，恰一个新提交
    assert _head_commit_files(root) == [".fenix/todo.md"]
    assert _git(root, "log", "-1", "--format=%s").strip().startswith("[fenix] todo: ")
    # 工作区对该文件干净
    assert _git(root, "status", "--porcelain", "--", ".fenix/todo.md").strip() == ""
    # 预置暂存未被 pathspec 提交卷入：仍停在索引待提交
    # （夹具无 .gitignore，flock 伴生锁文件 .fenix/.todo.md.lock 以 untracked 露出，滤除）
    porcelain = [
        ln
        for ln in _git(root, "status", "--porcelain").splitlines()
        if ".todo.md.lock" not in ln
    ]
    assert porcelain == ["A  other.txt"]


def test_append_idempotent_hit_no_second_commit(tracked_todo_proj):
    """2.2a 重复追加已存在行：幂等命中不写盘，不产生第二次提交。"""
    root = tracked_todo_proj
    assert kb.append_todo_line(root, "重复待办") is True
    assert _todo_commit_count(root) == 2
    assert kb.append_todo_line(root, "重复待办") is False
    assert _todo_commit_count(root) == 2


def test_append_untracked_and_non_git_degrade(tmp_path):
    """2.2b untracked / 非 git 夹具：写入成功、无提交、无异常穿透。"""
    # git 仓库但 todo.md 未被跟踪：跳过提交（不报错），写入照常
    repo = tmp_path / "untracked"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    assert kb.append_todo_line(repo, "untracked 待办") is True
    assert "untracked 待办" in (repo / ".fenix" / "todo.md").read_text(encoding="utf-8")
    assert len(_git(repo, "log", "--format=%H").split()) == 1  # 无新提交

    # 非 git 目录：同样只写入、不提交、不抛错
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    assert kb.append_todo_line(nogit, "无仓库待办") is True
    assert "无仓库待办" in (nogit / ".fenix" / "todo.md").read_text(encoding="utf-8")


def test_upsert_commits_on_each_actual_write_path(tracked_todo_proj):
    """2.3 upsert 三种实际写盘路径各恰一个仅含 todo.md 的提交；零写盘不提交。"""
    root = tracked_todo_proj
    assert kb.append_todo_line(root, "审计聚合 旧") is True  # 铺底（+1 提交）

    # 替换：同前缀整行替换
    assert kb.upsert_todo_line(root, "审计聚合", "审计聚合 新（龄期 2 天）") is True
    assert _head_commit_files(root) == [".fenix/todo.md"]
    # 新增：无匹配行归位追加
    assert kb.upsert_todo_line(root, "回填批次失败", "回填批次失败：cap-x") is True
    assert _head_commit_files(root) == [".fenix/todo.md"]
    # 清理：残留行删除（line 为空）
    assert (
        kb.upsert_todo_line(root, "回填批次失败", "", cleanup_prefixes=("回填批次失败",))
        is True
    )
    assert _head_commit_files(root) == [".fenix/todo.md"]
    assert "回填批次失败" not in (root / ".fenix" / "todo.md").read_text(encoding="utf-8")
    # 基线 1 + 铺底 1 + 三次实际写盘各 1 = 恰 5 个提交（每个实际写盘恰一个）
    assert _todo_commit_count(root) == 5

    # 零写盘路径一：同前缀单行且内容未变（幂等命中）
    assert kb.upsert_todo_line(root, "审计聚合", "审计聚合 新（龄期 2 天）") is False
    # 零写盘路径二：纯清理但无残留行
    assert kb.upsert_todo_line(root, "不存在的行", "") is False
    assert _todo_commit_count(root) == 5  # 零写盘不产生提交


def test_commit_runs_after_flock_release(tracked_todo_proj, monkeypatch):
    """2.4 git 子命令在 _todo_write_lock 的 flock 释放之后才执行（提交不进锁内）。"""
    events: list[str] = []
    real_lock = kb._todo_write_lock

    @contextmanager
    def tracked_lock(project_root):
        events.append("flock-acquire")
        with real_lock(project_root):
            yield
        events.append("flock-release")

    monkeypatch.setattr(kb, "_todo_write_lock", tracked_lock)

    real_run = evolution.subprocess.run

    def spy_run(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:1] == ["git"]:
            events.append("git:" + " ".join(str(c) for c in cmd[1:3]))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(evolution.subprocess, "run", spy_run)

    assert kb.append_todo_line(tracked_todo_proj, "锁序待办") is True

    assert events[0] == "flock-acquire"
    git_idx = [i for i, e in enumerate(events) if e.startswith("git:")]
    assert git_idx, events  # 提交链路确实执行了 git 子命令（ls-files/add/commit/push）
    release_idx = events.index("flock-release")
    assert min(git_idx) > release_idx  # 全部 git 调用都在 flock 释放之后
