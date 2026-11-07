"""锚点存活检查 + ADR retired 词汇单测（add-knowledge-anchor-lint-and-prune 1.3）。

六组场景：
1. 锚点段悬空报：段内悬空路径报「锚点悬空」，盘上存在路径零报告；
2. 段外路径不扫：规则段/溯源段提及的路径不参与锚点存在性检查；
3. 排除目录跳过：spec/archive/、spec/knowledge/_inbox/、node_modules/ 前缀跳过；
4. 行号违例：``路径:<纯数字>`` 尾形态报「行号必腐」格式违规，与悬空并列两类发现；
5. retired 校验：合规条目（status: retired + Retired: 注记行）零违规放行、
   缺注记行报违规、头部注记不触发正文改写（不可变比对同 superseded 口径）；
6. 二值行为不回归：accepted（无 Retired 行）与合法 superseded（含 Superseded by）
   判定与词汇扩展前一致；adr/index 状态一致性检查覆盖 retired 值。

夹具形态同 test_knowledge_audit.py：tmp_path 临时知识树，无 git 依赖
（不可变性用例单独 git init + commit）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from core import knowledge_audit as ka
from core.knowledge import check_anchor_references, validate_knowledge

GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

GOOD_ADR = """# ADR-001：{title}

date: 2026-11-08
{header}

## Context

{body}

## Decision

{body}

## Consequences

{body}
"""


@pytest.fixture
def ktree(tmp_path):
    """临时知识树：归档目录 + 单域目录（无 index.md——校验器按在场才检）。"""
    root = tmp_path / "proj"
    (root / "spec" / "archive" / "2026-01-01-demo").mkdir(parents=True)
    (root / "spec" / "knowledge" / "domains" / "dom-a").mkdir(parents=True)
    return root


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        env=GIT_ENV, capture_output=True, text=True, timeout=60,
    )


# ── 场景 1：锚点段悬空报 ─────────────────────────────────────────────────

PAGE_ANCHOR = """# 示例能力

<!-- knowledge: capability=demo-cap rev=1
     sources=spec/archive/2026-01-01-demo -->

示例能力一句话。

## 规则

- 示例规则。

## 代码锚点

- 主实现：`core/demo.py`
- 单源符号：`core/demo.py:run_demo`
- 守卫测试：`tests/test_demo.py`

## 溯源

- 2026-01-01 demo（spec/archive/2026-01-01-demo/） — 新建本页
"""


def test_anchor_dangling_reported(ktree):
    _write(ktree, "spec/knowledge/domains/dom-a/demo.md", PAGE_ANCHOR)
    # 全部路径在盘 → 零报告（范例即自证形态）
    _write(ktree, "core/demo.py", "def run_demo(): ...\n")
    _write(ktree, "tests/test_demo.py", "def test_demo(): ...\n")
    assert check_anchor_references(ktree) == []
    # 抽掉主实现文件 → 悬空逐条报，含页相对路径与悬空路径
    (ktree / "core" / "demo.py").unlink()
    findings = check_anchor_references(ktree)
    assert len(findings) == 1
    assert "spec/knowledge/domains/dom-a/demo.md" in findings[0]
    assert "锚点悬空: core/demo.py" in findings[0]


def test_anchor_dangling_with_symbol_suffix(ktree):
    """`路径:符号` 形态取路径部分校验，符号名不进存在性判定。"""
    _write(ktree, "spec/knowledge/domains/dom-a/demo.md", PAGE_ANCHOR)
    _write(ktree, "core/demo.py", "def run_demo(): ...\n")
    _write(ktree, "tests/test_demo.py", "x\n")
    assert check_anchor_references(ktree) == []
    # 符号不存在的文件路径仍在盘 → 仍零报告（符号语义不归本检查管辖）
    # 文件整体消失才报悬空，且报的是路径而非 路径:符号 全串
    (ktree / "core" / "demo.py").unlink()
    findings = check_anchor_references(ktree)
    assert findings == [
        "spec/knowledge/domains/dom-a/demo.md: 锚点悬空: core/demo.py"
    ]


# ── 场景 2：段外路径不扫 ─────────────────────────────────────────────────

PAGE_OUTSIDE = PAGE_ANCHOR.replace(
    "- 示例规则。",
    "- 规则正文提及 core/rules-ghost.py 与 spec/archive/ghost-dir 的路径不算锚点。",
).replace(
    "- 2026-01-01 demo（spec/archive/2026-01-01-demo/） — 新建本页",
    "- 2026-01-01 demo（spec/archive/2026-01-01-demo/） — 新建本页\n"
    "- 2026-01-02 other（spec/changes/gone-spec/） — 溯源段悬空归既有溯源检查管辖",
)


def test_paths_outside_section_not_scanned(ktree):
    _write(ktree, "spec/knowledge/domains/dom-a/demo.md", PAGE_OUTSIDE)
    _write(ktree, "core/demo.py", "x\n")
    _write(ktree, "tests/test_demo.py", "x\n")
    findings = check_anchor_references(ktree)
    assert findings == []  # 规则段/溯源段路径均不入锚点检查


# ── 场景 3：排除目录跳过 ─────────────────────────────────────────────────

PAGE_SKIPS = """# 示例能力

<!-- knowledge: capability=demo-cap rev=1
     sources=spec/archive/2026-01-01-demo -->

示例能力一句话。

## 规则

- 示例规则。

## 代码锚点

- 历史出处：`spec/archive/1999-01-01-gone/proposal.md`
- 候选区：`spec/knowledge/_inbox/gone-entry.md`
- 第三方：`node_modules/pkg/index.js`

## 溯源

- 2026-01-01 demo（spec/archive/2026-01-01-demo/） — 新建本页
"""


def test_excluded_prefixes_skipped(ktree):
    """三类豁免前缀路径即便盘上不存在也不报悬空（design D1）。"""
    _write(ktree, "spec/knowledge/domains/dom-a/demo.md", PAGE_SKIPS)
    assert check_anchor_references(ktree) == []


def test_missing_domains_dir_returns_empty(tmp_path):
    assert check_anchor_references(tmp_path) == []


def test_domain_nav_page_excluded(ktree):
    """域导航页 `_domain.md` 不在扫描面（锚点契约只约束能力页）。"""
    _write(
        ktree,
        "spec/knowledge/domains/dom-a/_domain.md",
        "# 域\n\n## 代码锚点\n\n- 主实现：`core/ghost-nav.md`\n",
    )
    assert check_anchor_references(ktree) == []


# ── 场景 4：行号违例报格式违规 ───────────────────────────────────────────

PAGE_LINENO = PAGE_ANCHOR.replace(
    "- 守卫测试：`tests/test_demo.py`",
    "- 守卫测试：`tests/test_demo.py:179`",
)


def test_line_number_form_reports_format_violation(ktree):
    _write(ktree, "spec/knowledge/domains/dom-a/demo.md", PAGE_LINENO)
    _write(ktree, "core/demo.py", "x\n")
    _write(ktree, "tests/test_demo.py", "x\n")
    findings = check_anchor_references(ktree)
    assert len(findings) == 1
    assert "行号必腐" in findings[0]
    assert "tests/test_demo.py:179" in findings[0]


def test_line_number_and_dangling_both_reported(ktree):
    """两类发现并列：行号违例不吞悬空，悬空不吞行号违例。"""
    _write(
        ktree,
        "spec/knowledge/domains/dom-a/demo.md",
        PAGE_ANCHOR.replace(
            "- 主实现：`core/demo.py`",
            "- 主实现：`core/missing.py:12`",
        ),
    )
    _write(ktree, "tests/test_demo.py", "x\n")
    findings = check_anchor_references(ktree)
    assert any("行号必腐" in f and "core/missing.py:12" in f for f in findings)


# ── 场景 5：retired 校验 ─────────────────────────────────────────────────

def _adr(root: Path, header: str, body: str = "原始正文", name: str = "ADR-001-x.md"):
    return _write(
        root,
        f"spec/knowledge/adr/{name}",
        GOOD_ADR.format(title="x", header=header, body=body),
    )


def _adr_index(root: Path, status: str = "retired"):
    _write(
        root,
        "spec/knowledge/adr/index.md",
        f"- [ADR-001](ADR-001-x.md) — {status}\n",
    )


def test_retired_compliant_passes(ktree):
    _adr(ktree, "status: retired\nRetired: 2026-11-08 主体已从产品退役，无取代裁定")
    _adr_index(ktree)
    assert validate_knowledge(ktree) == []


def test_retired_missing_note_violation(ktree):
    _adr(ktree, "status: retired")
    _adr_index(ktree)
    v = validate_knowledge(ktree)
    assert any("retired 条目缺 Retired: 注记行" in x for x in v)


def test_retired_note_must_be_date_anchored(ktree):
    """Retired: 行无日期锚（YYYY-MM-DD）不视为合法注记。"""
    _adr(ktree, "status: retired\nRetired: 主体已退役")
    _adr_index(ktree)
    v = validate_knowledge(ktree)
    assert any("retired 条目缺 Retired: 注记行" in x for x in v)


def test_retired_header_note_not_body_rewrite(ktree):
    """头部补注记行不触发三段正文改写违规（不可变比对口径同 superseded）。"""
    path = _adr(ktree, "status: retired")
    _adr_index(ktree)
    assert _git(ktree, "init", "-q").returncode == 0
    assert _git(ktree, "config", "user.name", "t").returncode == 0
    assert _git(ktree, "config", "user.email", "t@t").returncode == 0
    assert _git(ktree, "add", "--", ".").returncode == 0
    assert _git(ktree, "commit", "-q", "-m", "init").returncode == 0
    # 只动头部：追加 Retired: 注记行（合法 retired 两处标记之二）
    path.write_text(
        GOOD_ADR.format(
            title="x",
            header="status: retired\nRetired: 2026-11-08 主体退役",
            body="原始正文",
        ),
        encoding="utf-8",
    )
    assert validate_knowledge(ktree) == []
    # 改三段正文 → 与 superseded 同口径报不可变违规
    path.write_text(
        GOOD_ADR.format(
            title="x",
            header="status: retired\nRetired: 2026-11-08 主体退役",
            body="被改写的正文",
        ),
        encoding="utf-8",
    )
    v = validate_knowledge(ktree)
    assert any("三段正文被改写" in x for x in v)


# ── 场景 6：二值行为不回归 ───────────────────────────────────────────────

def test_accepted_without_note_unchanged(ktree):
    """accepted 条目（无 Retired 行）行为与词汇扩展前一致：零违规。"""
    _adr(ktree, "status: accepted")
    _adr_index(ktree, "accepted")
    assert validate_knowledge(ktree) == []


def test_superseded_unchanged(ktree):
    """合法 superseded（含指向存在条目的 Superseded by）照旧放行。"""
    _adr(ktree, "status: superseded\nSuperseded by: ADR-002(新)", name="ADR-001-x.md")
    _adr(ktree, "status: accepted", name="ADR-002-y.md")
    _write(
        ktree,
        "spec/knowledge/adr/index.md",
        "- [ADR-001](ADR-001-x.md) — superseded\n- [ADR-002](ADR-002-y.md) — accepted\n",
    )
    assert validate_knowledge(ktree) == []
    # superseded 缺 Superseded by 行照旧报违规
    _adr(ktree, "status: superseded", name="ADR-003-z.md")
    v = validate_knowledge(ktree)
    assert any("superseded 条目缺 Superseded by 行" in x for x in v)


def test_adr_index_status_consistency_covers_retired(ktree):
    """audit 侧 adr/index 状态一致性检查覆盖 retired 值（知识体检病灶⑤口径）。"""
    _adr(ktree, "status: retired\nRetired: 2026-11-08 主体退役")
    _adr_index(ktree, "accepted")  # index 状态未同步
    scan = ka._scan_adrs(ktree)
    assert any(
        m["name"] == "ADR-001" and m["expected"] == "retired" and m["wrong"] == "accepted"
        for m in scan["status_mismatch"]
    )
    # 同步后零误报
    _adr_index(ktree, "retired")
    scan = ka._scan_adrs(ktree)
    assert scan["status_mismatch"] == []


# ── run_audit 病灶⑥接线 ─────────────────────────────────────────────────


class _NullLogger:
    def info(self, *_a, **_k):
        pass

    def warning(self, *_a, **_k):
        pass

    def error(self, *_a, **_k):
        pass


def test_run_audit_consumes_anchor_findings(tmp_path, monkeypatch):
    """病灶⑥接线（add-knowledge-anchor-lint-and-prune 1.5）：悬空锚点进体检
    报告「待人工/定向转写」档并计入待人工，锚点行不被机械自删。"""
    import types

    import core as core_pkg

    root = tmp_path / "proj"
    (root / "spec" / "archive" / "2026-01-01-demo").mkdir(parents=True)  # sources 在盘，机械段零动作
    page = _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    # 不在盘上创建 core/demo.py / tests/test_demo.py → 两条悬空
    monkeypatch.setitem(
        sys.modules,
        "core.knowledge",
        _fake_core_module(root),
    )
    monkeypatch.setattr(core_pkg, "knowledge", sys.modules["core.knowledge"], raising=False)
    result = ka.run_audit(root, logger=_NullLogger(), spawn=lambda p, r: "ok")
    assert result["triggered"] is True
    assert result["counts"]["pending_manual"] >= 2
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(encoding="utf-8")
    assert "病灶⑥" in report
    assert "锚点悬空: core/demo.py" in report
    # 不机械自删：悬空锚点行仍在页面上
    assert "core/demo.py" in page.read_text(encoding="utf-8")


def _fake_core_module(root: Path):
    """最小 core.knowledge 替身：真实 check_anchor_references + 中性校验/提交。"""
    from core import knowledge as ck

    mod = types.ModuleType("core.knowledge")
    mod.validate_knowledge = lambda project_root: []
    mod.commit_knowledge = lambda project_root, paths, message: True
    mod.check_anchor_references = ck.check_anchor_references
    return mod


def test_run_audit_anchor_check_fail_open(tmp_path, monkeypatch):
    """core 替身缺 check_anchor_references 时（旧版本共存窗）体检零阻断。"""
    import core as core_pkg

    root = tmp_path / "proj"
    (root / "spec" / "archive" / "2026-01-01-demo").mkdir(parents=True)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    mod = types.ModuleType("core.knowledge")
    mod.validate_knowledge = lambda project_root: []
    mod.commit_knowledge = lambda project_root, paths, message: True
    monkeypatch.setitem(sys.modules, "core.knowledge", mod)
    monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
    result = ka.run_audit(root, logger=_NullLogger(), spawn=lambda p, r: "ok")
    assert result["triggered"] is True
    assert result["ok"] is True
