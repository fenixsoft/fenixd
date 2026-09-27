"""三车道端到端测试（任务 5.2）。

真实车道实现 + fake spawn / 假 graphify 子进程替身，从配置装载到自然日检查点
全链路贯通：
- 回填：域清单缺失 → 自举 → 按域分批 → 校验提交 → 收敛汇报 → 重入幂等；
- audit：植入机械+语义病灶 → daemon 检查点触发 → 机械修 + 定向转写 → 报告
  与日戳断言，同自然日防重；
- graph：假 graphify 产物落盘 → pathspec 提交 → 日戳断言。
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from core import knowledge_audit as ka
from core import knowledge_backfill as kb
from core.config import ConfigLoader


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "e2e@example.com")
    _git(root, "config", "user.name", "e2e")
    (root / "README.md").write_text("e2e\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")


def make_config(root: Path, **overrides) -> dict:
    """写真实 config.yaml 经 ConfigLoader.load 严格装载（配置文件 → 检查点全链路）。"""
    fenix = root / ".fenix"
    fenix.mkdir(exist_ok=True)
    knowledge = {"audit_enabled": True, "graph_enabled": True}
    knowledge.update(overrides)
    lines = [
        "project:",
        "  type: cli",
        "schedule: {}",
        "agents: {}",
        "worktree: {}",
        "gates: {}",
        "commands: {}",
        "logging: {}",
        "knowledge:",
    ]
    for key, val in knowledge.items():
        lines.append(f"  {key}: {'true' if val else 'false'}")
    cfg_path = fenix / "config.yaml"
    cfg_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ConfigLoader.load(cfg_path)


@pytest.fixture
def e2e_root(tmp_path):
    root = tmp_path / "proj"
    _init_repo(root)
    return root


def install_core(monkeypatch, root: Path, violations_fn=None):
    mod = types.ModuleType("core.knowledge")
    mod.validate_knowledge = lambda pr: list(violations_fn() or []) if violations_fn else []
    mod.commit_knowledge = lambda pr, paths, msg: ka.commit_pathspec(pr, paths, msg)
    import core as core_pkg

    monkeypatch.setitem(sys.modules, "core.knowledge", mod)
    monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)


# ── 回填车道端到端（自举 → 分批 → 收敛汇报） ─────────────────────────────


ARCHIVES = ["arc-a1", "arc-a2", "arc-a3", "arc-b1", "arc-b2", "arc-c1"]
DOMAIN_MAP = {
    "arc-a1": "dom-a", "arc-a2": "dom-a", "arc-a3": "dom-a",
    "arc-b1": "dom-b", "arc-b2": "dom-b",
    "arc-c1": "dom-c",
}


def seed_archives(root: Path) -> None:
    for name in ARCHIVES:
        d = root / "spec" / "archive" / name / "specs" / "cap-x"
        d.mkdir(parents=True)
        (d.parent.parent / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
        (d / "spec.md").write_text("delta\n", encoding="utf-8")


def page_text(archive: str) -> str:
    return (
        f"<!-- knowledge: capability=cap-{archive} rev=1 sources={archive} -->\n"
        f"# cap-{archive}\n\n## 规则\n\n- {archive} 的现行规则一句。\n"
    )


def write_batch_pages(root: Path, prompt: str) -> None:
    for ln in prompt.splitlines():
        if ln.startswith("- arc-"):
            name = ln[2:].strip()
            p = root / "spec" / "knowledge" / "domains" / "dom-x" / f"cap-{name}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(page_text(name), encoding="utf-8")


def test_e2e_backfill_bootstrap_batches_convergence(e2e_root, monkeypatch):
    root = e2e_root
    seed_archives(root)
    install_core(monkeypatch, root)

    def spawn(prompt, run_id):
        if run_id.startswith("kb-bootstrap"):
            (root / ".fenix" / "knowledge_backfill_domains.json").write_text(
                json.dumps(DOMAIN_MAP, ensure_ascii=False), encoding="utf-8"
            )
            (root / "spec" / "knowledge").mkdir(parents=True, exist_ok=True)
            (root / "spec" / "knowledge" / "index.md").write_text(
                "# 真相源导航\n", encoding="utf-8"
            )
            return "ok"
        write_batch_pages(root, prompt)
        return "ok"

    summary = kb.run_backfill(root, spawn=spawn)

    # 自举 → 3 域 3 批 → 全部成功
    assert summary["converged"] is True
    assert summary["batches_total"] == 3
    assert summary["batches_ok"] == 3
    assert summary["counts"]["distilled"] == 6
    # 提交序列：bootstrap 先于 batch 1/3，批次消息连续
    subjects = [
        ln
        for ln in _git(root, "log", "--format=%s", "--reverse").splitlines()
        if ln.startswith("[fenix] knowledge:")
    ]
    assert subjects == [
        "[fenix] knowledge: backfill bootstrap",
        "[fenix] knowledge: backfill batch 1/3",
        "[fenix] knowledge: backfill batch 2/3",
        "[fenix] knowledge: backfill batch 3/3",
    ]
    # 台账全 distilled + 收敛汇报含批数/成败/规模统计
    ledger = (root / ".fenix" / "knowledge_backfill.jsonl").read_text(encoding="utf-8")
    assert ledger.count('"distilled"') == 6
    report = (root / ".fenix" / "knowledge_backfill_report.md").read_text(encoding="utf-8")
    assert "批次总数：3（成功 3 / 失败 0）" in report
    assert "真相源规模" in report
    # 产物真身：6 个能力页落 domains/
    pages = list((root / "spec" / "knowledge" / "domains").rglob("cap-*.md"))
    assert len(pages) == 6
    # 重入幂等：收敛后零派发
    calls_after: list = []

    def noop_spawn(prompt, run_id):
        calls_after.append(run_id)
        return "ok"

    again = kb.run_backfill(root, spawn=noop_spawn)
    assert again["triggered"] is False
    assert again["reason"] == "converged"
    assert calls_after == []


# ── audit 车道端到端（植入病灶 → 机械修 + 语义转写 → 报告/日戳） ──────────

ALPHA = """<!-- knowledge: capability=alpha rev=1 sources=arc-a1,arc-zombie -->
# alpha

## 规则

- 全局请求超时:300 秒。
- 禁止明文记录日志。

## 溯源

- spec/archive/arc-a1
- spec/archive/arc-zombie
"""

BETA = """<!-- knowledge: capability=beta rev=1 sources=arc-b1 -->
# beta

## 规则

- 全局请求超时:600 秒。
- 禁止明文记录日志。

## 溯源

- spec/archive/arc-b1
"""


def seed_knowledge_with_defects(root: Path) -> None:
    kdom = root / "spec" / "knowledge" / "domains" / "dom-a"
    kdom.mkdir(parents=True)
    (root / "spec" / "knowledge" / "index.md").write_text("# 真相源\n", encoding="utf-8")
    (kdom / "alpha.md").write_text(ALPHA, encoding="utf-8")
    (kdom / "beta.md").write_text(BETA, encoding="utf-8")
    adr = root / "spec" / "knowledge" / "adr"
    adr.mkdir()
    (adr / "index.md").write_text("", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "seed knowledge")


def test_e2e_audit_through_daily_checkpoint(e2e_root, monkeypatch):
    root = e2e_root
    seed_knowledge_with_defects(root)
    install_core(monkeypatch, root)

    def spawn(prompt, run_id):
        assert "定向转写" in prompt
        # 按初筛病灶类型定向重写受影响页（beta 统一口径 / 去重复）
        beta = root / "spec/knowledge/domains/dom-a/beta.md"
        text = beta.read_text(encoding="utf-8")
        if "contradiction" in prompt:
            text = text.replace("- 全局请求超时:600 秒。", "- 全局请求超时:300 秒。")
        elif "duplicate" in prompt:
            text = text.replace("- 禁止明文记录日志。\n", "")
        beta.write_text(text, encoding="utf-8")
        return "ok"

    config = make_config(root, graph_enabled=False)

    def audit_lane(project_root, logger=None):
        # 经检查点走真 run_audit，LLM 边界（spawn）注入替身；不注入会落到
        # 生产 default_spawn 真跑 claude 子进程
        return ka.run_audit(project_root, logger=logger, spawn=spawn)

    result = ka.knowledge_daily_check(root, config=config, audit_lane=audit_lane)

    assert result["triggered"] is True
    audit = result["results"]["audit"]
    assert audit["ok"] is True
    assert audit["counts"]["fixed"] >= 1  # 悬空溯源 arc-zombie 被机械清除
    assert audit["counts"]["rewritten"] == 2  # 矛盾 + 跨页重复各一次定向转写
    # 提交链（时间正序）：机械修 → 转写 contradiction → 转写 duplicate
    subjects = [
        ln
        for ln in _git(root, "log", "--format=%s", "--reverse").splitlines()
        if ln.startswith("[fenix] knowledge:")
    ]
    assert subjects[0].startswith("[fenix] knowledge: audit fix ")
    assert any("audit rewrite contradiction" in s for s in subjects)
    assert any("audit rewrite duplicate" in s for s in subjects)
    # 半成品零残留：工作区真相源干净
    assert _git(root, "status", "--porcelain", "--", "spec/knowledge").strip() == ""
    beta_final = (root / "spec/knowledge/domains/dom-a/beta.md").read_text(encoding="utf-8")
    assert "600" not in beta_final
    assert "禁止明文记录日志" not in beta_final
    alpha_final = (root / "spec/knowledge/domains/dom-a/alpha.md").read_text(encoding="utf-8")
    assert "arc-zombie" not in alpha_final
    # 体检报告计数 + 日戳落盘
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "转写 2" in report
    state = json.loads((root / ".fenix" / "knowledge_audit_state.json").read_text())
    assert state["last_audit_date"] == ka._today()
    # 同自然日第二周期：防重不再执行
    calls: list = []

    def counting_lane(project_root, logger=None):
        calls.append(1)
        return ka.run_audit(project_root, logger=logger)

    ka.knowledge_daily_check(root, config=config, audit_lane=counting_lane)
    assert calls == []


# ── graph 车道端到端（假 graphify 子进程 → 产物提交 → 日戳） ─────────────


def test_e2e_graph_through_daily_checkpoint(e2e_root, monkeypatch):
    root = e2e_root
    seed_knowledge_with_defects(root)
    install_core(monkeypatch, root)
    config = make_config(root, audit_enabled=False)

    # 在 run_graph 声明的注入缝（which/run_cmd）替身假 CLI：探测到 graphify，
    # 执行落产物。不走全局 subprocess 替身——那会连 commit_pathspec 的 git
    # 子进程一并劫持。
    seen_cmds: list = []

    def fake_run_cmd(cmd, timeout):
        seen_cmds.append((list(cmd), timeout))
        gdir = root / "spec" / "knowledge" / "graph"
        gdir.mkdir(parents=True, exist_ok=True)
        (gdir / "graph.html").write_text("<html>atlas</html>\n", encoding="utf-8")
        (gdir / "GRAPH_REPORT.md").write_text("# graph report\n", encoding="utf-8")
        (gdir / "graph.json").write_text('{"nodes": []}\n', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "ok")

    def graph_lane(project_root, logger=None):
        return ka.run_graph(
            project_root,
            logger=logger,
            which=lambda name: "/usr/bin/graphify",
            run_cmd=fake_run_cmd,
        )

    result = ka.knowledge_daily_check(root, config=config, graph_lane=graph_lane)

    assert result["triggered"] is True
    assert result["results"]["graph"] == {"triggered": True, "ok": True, "committed": True}
    # 命令形态：graphify spec/knowledge --out spec/knowledge/graph，带超时上限
    cmd, timeout = seen_cmds[0]
    assert cmd[0] == "/usr/bin/graphify" and cmd[1] == "spec/knowledge"
    assert "--out" in cmd and timeout == ka.GRAPH_TIMEOUT_SECONDS
    # 产物落盘 + pathspec 提交
    for artifact in ("graph.html", "GRAPH_REPORT.md", "graph.json"):
        assert (root / "spec/knowledge/graph" / artifact).is_file()
    assert "[fenix] knowledge: graph update" in _git(root, "log", "--format=%s")
    state = json.loads((root / ".fenix" / "knowledge_audit_state.json").read_text())
    assert state["last_graph_date"] == ka._today()
    # 同自然日第二周期：不再执行（fail-open 跳过也不重试）
    seen_cmds.clear()
    ka.knowledge_daily_check(root, config=config, graph_lane=graph_lane)
    assert seen_cmds == []
