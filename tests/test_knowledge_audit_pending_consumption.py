"""待人工发现登记与消费接线单测（evo-knowledge-audit-pending-consumption 3.2）。

五组场景（全部经 run_audit 真实接线驱动，夹具形态同 test_knowledge_anchor_
check.py 的 run_audit 级用例：tmp_path 临时项目 + core.knowledge 替身中性化
校验/提交、保留真实 check_anchor_references）：

1. 逐页登记：病灶⑥锚点发现 + 行数硬顶（临时夹具页驱动，当前知识树零破顶
   实例）两类发现逐页一行写入 ``.fenix/todo.md``，页内多发现并集单行；
2. 清零摘行：页内发现清零（下轮体检不再报）后该页整行摘除，无陈旧欠账；
3. 整组替换：发现集变化按 upsert 整行替换收敛，不追加新行；
4. escalated 聚合行安全：登记/摘行全程不触碰 escalated 聚合行（新前缀与
   TODO_ESCALATED_* 无前缀关系，cleanup 不误清）；
5. 档位标签真实：报告病灶⑥节标题收敛为「待人工」，全文无「定向转写」
   无通路措辞。
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

from core import knowledge_audit as ka

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


class _NullLogger:
    def info(self, *_a, **_k):
        pass

    def warning(self, *_a, **_k):
        pass

    def error(self, *_a, **_k):
        pass


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _overcap_page_text(lines: int) -> str:
    """临时夹具页：无锚点段的纯正文页，精确 lines 行（行数硬顶驱动，当前
    知识树零破顶实例——本 SPEC 登记通路以夹具页验证）。"""
    body = [f"夹具正文第 {i} 行。" for i in range(1, lines)]
    return "# 夹具超限页\n\n" + "\n".join(body) + "\n"


def _fake_core_module() -> types.ModuleType:
    """最小 core.knowledge 替身：真实 check_anchor_references + 中性校验/提交
    （对齐 test_knowledge_anchor_check.py 同名夹具口径）。"""
    from core import knowledge as ck

    mod = types.ModuleType("core.knowledge")
    mod.validate_knowledge = lambda project_root: []
    mod.commit_knowledge = lambda project_root, paths, message: True
    mod.check_anchor_references = ck.check_anchor_references
    return mod


def _audit(tmp_path, monkeypatch):
    import core as core_pkg

    mod = _fake_core_module()
    monkeypatch.setitem(sys.modules, "core.knowledge", mod)
    monkeypatch.setattr(core_pkg, "knowledge", mod, raising=False)
    return ka.run_audit(tmp_path, logger=_NullLogger(), spawn=lambda p, r: "ok")


def _proj(tmp_path) -> Path:
    root = tmp_path / "proj"
    # sources 在盘：机械段零动作，不引入额外发现
    (root / "spec" / "archive" / "2026-01-01-demo").mkdir(parents=True)
    (root / "spec" / "knowledge" / "domains" / "dom-a").mkdir(parents=True)
    return root


def _todo(root: Path) -> str:
    path = root / ".fenix" / "todo.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _pending_lines(root: Path) -> list[str]:
    return [
        ln
        for ln in _todo(root).splitlines()
        if ln.startswith(f"- {ka.TODO_PENDING_PAGE_PREFIX}：")
    ]


# ── 场景 1：待人工发现逐页登记 ───────────────────────────────────────────


def test_pending_findings_registered_per_page(tmp_path, monkeypatch):
    """锚点悬空（单页两条并集单行）与行数硬顶（夹具页）逐页一行登记进
    .fenix/todo.md。"""
    root = _proj(tmp_path)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)  # 2 条悬空
    overcap_lines = ka.LINE_CAP + 9
    _write(
        root, "spec/knowledge/domains/dom-a/fat.md", _overcap_page_text(overcap_lines)
    )
    result = _audit(root, monkeypatch)
    assert result["triggered"] is True
    lines = _pending_lines(root)
    assert len(lines) == 2  # 逐页一行：两页各一条，无逐发现一行
    page_line = next(ln for ln in lines if "dom-a/x.md" in ln)
    assert (
        f"- {ka.TODO_PENDING_PAGE_PREFIX}：spec/knowledge/domains/dom-a/x.md："
        "锚点悬空: core/demo.py；锚点悬空: tests/test_demo.py" == page_line
    )
    fat_line = next(ln for ln in lines if "dom-a/fat.md" in ln)
    # 行数取扫描实侧值（_collect_pages 对页文本有空白规整，不钉死夹具构造值）
    m = re.search(rf"超 {ka.LINE_CAP} 行硬顶（(\d+) 行）$", fat_line)
    assert m and int(m.group(1)) > ka.LINE_CAP


# ── 场景 2：页内发现清零整行摘除 ─────────────────────────────────────────


def test_page_findings_cleared_removes_line(tmp_path, monkeypatch):
    """页内发现清零（悬空锚点补建文件后下轮不再报）→ 该页登记行整行摘除。"""
    root = _proj(tmp_path)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    _audit(root, monkeypatch)
    assert len(_pending_lines(root)) == 1
    # 补齐悬空文件 → 第二轮发现清零
    _write(root, "core/demo.py", "def run_demo(): ...\n")
    _write(root, "tests/test_demo.py", "def test_demo(): ...\n")
    _audit(root, monkeypatch)
    assert _pending_lines(root) == []
    assert f"{ka.TODO_PENDING_PAGE_PREFIX}：" not in _todo(root)


# ── 场景 3：发现集变化整组替换 ───────────────────────────────────────────


def test_findings_change_replaces_line(tmp_path, monkeypatch):
    """发现集变化按 upsert 整行替换收敛：仍保留单行、行内只列剩余发现。"""
    root = _proj(tmp_path)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    _audit(root, monkeypatch)
    before = _pending_lines(root)
    assert len(before) == 1 and "core/demo.py" in before[0]
    # 只修 tests/test_demo.py：发现集从 2 条收敛为 1 条
    _write(root, "tests/test_demo.py", "def test_demo(): ...\n")
    _audit(root, monkeypatch)
    lines = _pending_lines(root)
    assert len(lines) == 1  # 单行收敛，不追加第二条
    assert lines != before  # 行内容已替换
    assert "锚点悬空: tests/test_demo.py" not in lines[0]
    assert "锚点悬空: core/demo.py" in lines[0]


# ── 场景 4：escalated 聚合行不被新前缀误清 ────────────────────────────────


_ESCALATED_ENTRY = {
    "status": "escalated",
    "first_seen": "2026-11-27 08:00:00",
    "updated_at": "2026-11-27",
    "review_rounds": 2,
    "a": {"page": "spec/knowledge/domains/dom-a/x.md"},
    "b": {"page": "spec/knowledge/domains/dom-a/y.md"},
}


def _seed_escalated_ledger(root: Path) -> None:
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    (root / ".fenix" / "knowledge_audit_findings.json").write_text(
        json.dumps({"fp1234abcd": dict(_ESCALATED_ENTRY)}, ensure_ascii=False),
        encoding="utf-8",
    )


def _agg_lines(root: Path) -> list[str]:
    return [
        ln
        for ln in _todo(root).splitlines()
        if ln.startswith(f"- {ka.TODO_ESCALATED_AGG_PREFIX}：")
    ]


def test_escalated_agg_line_survives_registration(tmp_path, monkeypatch):
    """escalated 聚合行（台账有在册升级条目，run_audit 自登记）与本车道逐页
    登记行共存；摘行路径（发现清零轮）不触碰聚合行（前缀互不构成前缀关系，
    _registered_pending_pages 只识别本前缀行）。"""
    root = _proj(tmp_path)
    _seed_escalated_ledger(root)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    _audit(root, monkeypatch)
    assert _pending_lines(root)  # 本车道逐页行已在册
    agg_now = _agg_lines(root)
    assert len(agg_now) == 1 and "待人工仲裁" in agg_now[0]
    # 摘行路径（发现清零轮）同样不触碰 escalated 聚合行
    _write(root, "core/demo.py", "def run_demo(): ...\n")
    _write(root, "tests/test_demo.py", "def test_demo(): ...\n")
    _audit(root, monkeypatch)
    assert _pending_lines(root) == []
    assert _agg_lines(root) == agg_now
    # 对账面：escalated 聚合行不被识别为本车道登记页（摘行集合来源安全）
    assert ka._registered_pending_pages(root) == set()


def test_pending_sync_cleanup_scoped_to_own_prefix(tmp_path):
    """_sync_pending_page_todo_lines 清理只触本前缀行：escalated 聚合行/历史
    逐条行与外来手工行原样保留；零变化二连调幂等零改写。"""
    root = _proj(tmp_path)
    (root / ".fenix").mkdir(parents=True, exist_ok=True)
    seed = (
        f"- {ka.TODO_ESCALATED_AGG_PREFIX}：1 条待人工仲裁（最长龄期 0 天）\n"
        f"- {ka.TODO_ESCALATED_LEGACY_PREFIX}fp1234abcd 页 A × 页 B\n"
        "- 其他车道手工待办：保持原样\n"
        f"- {ka.TODO_PENDING_PAGE_PREFIX}：spec/knowledge/domains/dom-a/old.md："
        "锚点悬空: core/gone.py\n"
    )
    (root / ".fenix" / "todo.md").write_text(seed, encoding="utf-8")
    log = _NullLogger()
    ka._sync_pending_page_todo_lines(root, {}, log)  # 本轮零发现 → 摘 old.md 行
    text = _todo(root)
    assert "dom-a/old.md" not in text
    assert ka.TODO_ESCALATED_AGG_PREFIX in text
    assert ka.TODO_ESCALATED_LEGACY_PREFIX in text
    assert "其他车道手工待办" in text
    # 零变化二连调：幂等零改写（无提交噪声）
    before = (root / ".fenix" / "todo.md").read_text(encoding="utf-8")
    ka._sync_pending_page_todo_lines(root, {}, log)
    assert (root / ".fenix" / "todo.md").read_text(encoding="utf-8") == before


# ── 场景 5：报告档位标签真实 ─────────────────────────────────────────────


def test_report_pending_label_converged(tmp_path, monkeypatch):
    """报告病灶⑥节标题收敛为「待人工」，报告全文不再出现无实现通路的
    「定向转写」措辞。"""
    root = _proj(tmp_path)
    _write(root, "spec/knowledge/domains/dom-a/x.md", PAGE_ANCHOR)
    _audit(root, monkeypatch)
    report = (root / ".fenix" / "knowledge_audit_report.md").read_text(
        encoding="utf-8"
    )
    assert "## 病灶⑥：锚点悬空/行号违例（待人工）" in report
    assert "定向转写" not in report
    assert "锚点悬空: core/demo.py" in report  # 明细仍逐条列明
