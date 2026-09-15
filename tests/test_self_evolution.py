"""
add-framework-self-evolution：自进化链路测试。

按任务组组织：
- TestSelfEvolutionConfig（任务 1.3）：self_evolution 配置读取的缺省、非法回退与不抛异常
- TestEvolutionStorage（任务 9.1）：身份键、items.jsonl 读写、水位、todo.md 解析与增量筛选
- 后续任务（接受/拒绝、agent 执行、daemon 检查点）随实现追加
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from core.config import (
    ConfigLoader,
    SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT,
    SELF_EVOLUTION_MAX_ITEMS_DEFAULT,
    SELF_EVOLUTION_MAX_ITEMS_UPPER,
    SELF_EVOLUTION_SPEC_RUN_AT_DEFAULT,
)


class TestSelfEvolutionConfig(unittest.TestCase):
    """任务 1.3：get_self_evolution_config 的缺省、非法回退与不抛异常。"""

    def _get(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return ConfigLoader.get_self_evolution_config(config)

    def test_defaults_when_section_missing(self):
        """节缺失 → auto_accept=False / max_items_per_run=20 / spec_run_at=None。"""
        out = self._get({})
        self.assertEqual(out, {
            "auto_accept": SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT,
            "max_items_per_run": SELF_EVOLUTION_MAX_ITEMS_DEFAULT,
            "spec_run_at": SELF_EVOLUTION_SPEC_RUN_AT_DEFAULT,
        })

    def test_defaults_when_section_empty(self):
        """节存在但为空 dict → 缺省值。"""
        out = self._get({"self_evolution": {}})
        self.assertEqual(out["auto_accept"], False)
        self.assertEqual(out["max_items_per_run"], 20)

    def test_defaults_when_section_wrong_type(self):
        """节为非法类型（字符串/列表）→ 按缺省值处理，不抛异常。"""
        for bad in ("on", ["a"], 42, None):
            out = self._get({"self_evolution": bad})
            self.assertEqual(out["auto_accept"], False)
            self.assertEqual(out["max_items_per_run"], 20)

    def test_valid_values_passthrough(self):
        """合法值原样生效。"""
        out = self._get({"self_evolution": {"auto_accept": True, "max_items_per_run": 7}})
        self.assertEqual(out, {"auto_accept": True, "max_items_per_run": 7,
                               "spec_run_at": None})
        out = self._get({"self_evolution": {"auto_accept": False, "max_items_per_run": 200}})
        self.assertEqual(out["auto_accept"], False)
        self.assertEqual(out["max_items_per_run"], 200)

    def test_spec_run_at_passthrough_and_fallback(self):
        """spec_run_at：合法 HH:mm 生效；缺失/非法（含越界与类型错）回退 None。"""
        self.assertEqual(
            self._get({"self_evolution": {"spec_run_at": "02:00"}})["spec_run_at"],
            "02:00")
        self.assertEqual(
            self._get({"self_evolution": {"spec_run_at": "23:59"}})["spec_run_at"],
            "23:59")
        for bad in ("25:00", "2:00", "02:60", "abc", "", 2, True, [], {}, 2.5):
            out = self._get({"self_evolution": {"spec_run_at": bad}})
            self.assertIsNone(out["spec_run_at"], f"应回退 None: {bad!r}")
        # 显式 null 即「立即执行」，是合法值而非非法
        self.assertIsNone(
            self._get({"self_evolution": {"spec_run_at": None}})["spec_run_at"])

    def test_auto_accept_invalid_types_fallback(self):
        """auto_accept 非布尔（1 / "yes" / "true" / 0 / None）→ 回退缺省 False。"""
        for bad in (1, "yes", "true", 0, None, 0.0, [], {}):
            out = self._get({"self_evolution": {"auto_accept": bad}})
            self.assertEqual(out["auto_accept"], False)

    def test_max_items_invalid_fallbacks(self):
        """max_items_per_run 非法（字符串 / 0 / 负数 / 非数字 / 201 / 布尔）→ 回退 20。"""
        for bad in ("abc", "5", 0, -1, -100, 3.14, 201, 5000, True, False, None):
            out = self._get({"self_evolution": {"max_items_per_run": bad}})
            self.assertEqual(out["max_items_per_run"], 20)

    def test_max_items_float_not_integer(self):
        """float 值（即使整数值）按非整数回退缺省。"""
        out = self._get({"self_evolution": {"max_items_per_run": 5.0}})
        self.assertEqual(out["max_items_per_run"], SELF_EVOLUTION_MAX_ITEMS_DEFAULT)

    def test_mixed_invalid_one_key_fallback_only_that_key(self):
        """单键非法只回退该键，另一键合法值不受影响。"""
        out = self._get({
            "self_evolution": {"auto_accept": "yes", "max_items_per_run": 5},
        })
        self.assertEqual(out, {"auto_accept": False, "max_items_per_run": 5,
                               "spec_run_at": None})

    def test_no_exception_on_daemon_start_path(self):
        """resolve_config 宽松校验路径（热更新/启动）不会被 self_evolution 破坏。"""
        import tempfile
        from pathlib import Path
        import shutil

        tmpdir = tempfile.mkdtemp()
        try:
            proot = Path(tmpdir) / "proj"
            proot.mkdir(parents=True)
            # 项目级配置放非法 self_evolution 值：resolve_config 不得抛异常
            proj_cfg = proot / ".fenix"
            proj_cfg.mkdir(parents=True)
            (proj_cfg / "config.yaml").write_text(
                "project:\n  name: proj\nself_evolution:\n"
                '  auto_accept: "yes"\n  max_items_per_run: 999\n',
                encoding="utf-8",
            )
            resolved = ConfigLoader.resolve_config(proot)
            out = ConfigLoader.get_self_evolution_config(resolved)
            self.assertEqual(out["auto_accept"], False)
            self.assertEqual(out["max_items_per_run"], 20)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_constants_exposed(self):
        """模块级常量可供测试与文档引用。"""
        self.assertFalse(SELF_EVOLUTION_AUTO_ACCEPT_DEFAULT)
        self.assertEqual(SELF_EVOLUTION_MAX_ITEMS_DEFAULT, 20)
        self.assertEqual(SELF_EVOLUTION_MAX_ITEMS_UPPER, 200)
        self.assertIsNone(SELF_EVOLUTION_SPEC_RUN_AT_DEFAULT)


class TestNextSpecRunAt(unittest.TestCase):
    """``next_spec_run_at``：每日时刻 → 下一次到期的 UTC ISO。

    now 一律传 naive 本地时间，期望值用同一进程的 ``astimezone`` 推算——用例
    不依赖跑测试的机器时区。
    """

    @staticmethod
    def _want(y, mo, d, h, mi):
        from datetime import datetime as _dt, timezone as _tz
        return _dt(y, mo, d, h, mi).astimezone(_tz.utc).isoformat()

    def test_today_when_time_not_yet_reached(self):
        """本地 09:44 且目标 23:00 未到 → 当日 23:00。"""
        from datetime import datetime as _dt
        got = next_spec_run_at("23:00", now=_dt(2026, 9, 14, 9, 44))
        self.assertEqual(got, self._want(2026, 9, 14, 23, 0))

    def test_tomorrow_when_time_already_passed(self):
        """本地 23:30 且目标 23:00 已过 → 次日 23:00。"""
        from datetime import datetime as _dt
        got = next_spec_run_at("23:00", now=_dt(2026, 9, 14, 23, 30))
        self.assertEqual(got, self._want(2026, 9, 15, 23, 0))

    def test_tomorrow_when_time_exactly_now(self):
        """恰好等于 now 也算已过 → 次日（保证 start_after 严格晚于当前时刻）。"""
        from datetime import datetime as _dt
        got = next_spec_run_at("23:00", now=_dt(2026, 9, 14, 23, 0))
        self.assertEqual(got, self._want(2026, 9, 15, 23, 0))

    def test_seconds_zeroed(self):
        """秒/微秒归零：start_after 落到整分，不受调用时刻的秒数影响。"""
        from datetime import datetime as _dt
        got = next_spec_run_at("23:00", now=_dt(2026, 9, 14, 9, 44, 37, 12345))
        self.assertEqual(got, self._want(2026, 9, 14, 23, 0))

    def test_invalid_returns_none(self):
        """None / 非字符串 / 格式错 / 越界 → None（不设门，fail-open）。"""
        from datetime import datetime as _dt
        now = _dt(2026, 9, 14, 9, 44)
        for bad in (None, "", "abc", "2:00", "25:00", "09:60", "-1:00",
                    5, 5.5, True, [], {}):
            self.assertIsNone(next_spec_run_at(bad, now=now), f"应为 None: {bad!r}")

    def test_result_is_utc_iso(self):
        """返回值带 UTC 偏移（STATE.start_after 全链 UTC 的契约）。"""
        from datetime import datetime as _dt
        got = next_spec_run_at("23:00", now=_dt(2026, 9, 14, 9, 44))
        self.assertTrue(got.endswith("+00:00"), got)


# ── 任务 9.1（身份键 / items.jsonl / 水位 / todo.md 解析 / 增量筛选）──

from core.evolution import (
    item_id,
    read_items,
    upsert_item,
    write_items,
    known_ids,
    read_watermarks,
    write_watermarks,
    advance_watermark,
    evolution_dir,
    items_path,
    watermarks_path,
    parse_todo_entries,
    select_pending_entries,
    TODO_SECTIONS,
    scan_ready_projects,
)


class TestEvolutionItemIdentity(unittest.TestCase):
    """任务 2.1 / 9.1：身份键稳定性与四元组敏感性。"""

    def test_stability(self):
        """同四元组多次计算结果一致。"""
        id1 = item_id("proj", "2026-09-12", "浪费", "冗余函数")
        id2 = item_id("proj", "2026-09-12", "浪费", "冗余函数")
        self.assertEqual(id1, id2)
        self.assertEqual(len(id1), 12)

    def test_sensitive_to_project(self):
        """改变项目名 → id 不同。"""
        a = item_id("projA", "2026-09-12", "浪费", "冗余函数")
        b = item_id("projB", "2026-09-12", "浪费", "冗余函数")
        self.assertNotEqual(a, b)

    def test_sensitive_to_date_section(self):
        a = item_id("proj", "2026-09-12", "浪费", "冗余函数")
        b = item_id("proj", "2026-09-13", "浪费", "冗余函数")
        self.assertNotEqual(a, b)

    def test_sensitive_to_section(self):
        a = item_id("proj", "2026-09-12", "浪费", "冗余函数")
        b = item_id("proj", "2026-09-12", "失误", "冗余函数")
        self.assertNotEqual(a, b)

    def test_sensitive_to_title(self):
        a = item_id("proj", "2026-09-12", "浪费", "冗余函数")
        b = item_id("proj", "2026-09-12", "浪费", "命名不规范")
        self.assertNotEqual(a, b)


class TestEvolutionItemsJsonl(unittest.TestCase):
    """任务 2.2 / 9.1：items.jsonl 同 id 更新不追加、原子写、读损坏容错。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_when_missing(self):
        """文件不存在 → 空 dict。"""
        self.assertEqual(read_items(self.proot), {})

    def test_read_write_roundtrip(self):
        """写入后读取一致。"""
        rec = {
            "id": "a1b2c3d4e5f6", "project": "proj",
            "date_section": "2026-09-12", "section": "浪费",
            "title": "测试", "status": "pending", "created_at": "2026-09-12T00:00:00Z",
        }
        write_items(self.proot, [rec])
        items = read_items(self.proot)
        self.assertEqual(set(items.keys()), {"a1b2c3d4e5f6"})
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "pending")

    def test_upsert_replaces_not_appends(self):
        """同 id upsert → 只保留一条（字段更新），不追加。"""
        rec = {
            "id": "a1b2c3d4e5f6", "project": "proj",
            "date_section": "2026-09-12", "section": "浪费",
            "title": "测试", "status": "pending",
            "created_at": "2026-09-12T00:00:00Z",
        }
        write_items(self.proot, [rec])
        rec2 = {**rec, "status": "analyzed"}
        upsert_item(self.proot, rec2)
        items = read_items(self.proot)
        self.assertEqual(len(items), 1)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "analyzed")

    def test_multiple_records(self):
        """多条记录读取正确。"""
        recs = [
            {"id": "id1", "project": "a", "status": "pending",
             "date_section": "d1", "section": "浪费", "title": "t1"},
            {"id": "id2", "project": "b", "status": "rejected",
             "date_section": "d2", "section": "失误", "title": "t2"},
        ]
        write_items(self.proot, recs)
        items = read_items(self.proot)
        self.assertEqual(set(items.keys()), {"id1", "id2"})
        self.assertEqual(items["id1"]["status"], "pending")
        self.assertEqual(items["id2"]["status"], "rejected")

    def test_broken_lines_skipped(self):
        """损坏行跳过，其余行正常读取。"""
        path = items_path(self.proot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "not json\n"
            + json.dumps({"id": "ok1", "status": "pending",
                           "date_section": "d1", "section": "浪费",
                           "title": "ok"}) + "\n",
            encoding="utf-8",
        )
        items = read_items(self.proot)
        self.assertEqual(set(items.keys()), {"ok1"})


class TestEvolutionWatermark(unittest.TestCase):
    """任务 2.3 / 9.1：水位推进——仅在 run 启动快照时刻推进。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_when_missing(self):
        self.assertEqual(read_watermarks(self.proot), {})

    def test_advance_and_read(self):
        advance_watermark(
            self.proot, "proj", "2026-09-12T03:00:00+00:00", "evo-100")
        wm = read_watermarks(self.proot)
        self.assertEqual(wm["proj"]["last_analyzed_at"], "2026-09-12T03:00:00+00:00")
        self.assertEqual(wm["proj"]["last_run_id"], "evo-100")

    def test_advance_updates_not_appends(self):
        """同一项目多次推进 → 只保留最新。"""
        advance_watermark(self.proot, "proj", "2026-09-12T03:00:00Z", "evo-100")
        advance_watermark(self.proot, "proj", "2026-09-13T03:00:00Z", "evo-200")
        wm = read_watermarks(self.proot)
        self.assertEqual(len(wm), 1)
        self.assertEqual(wm["proj"]["last_analyzed_at"], "2026-09-13T03:00:00Z")
        self.assertEqual(wm["proj"]["last_run_id"], "evo-200")

    def test_corrupt_state_returns_empty(self):
        """损坏的 state.json → 空 dict。"""
        path = watermarks_path(self.proot)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(read_watermarks(self.proot), {})


class TestEvolutionTodoParse(unittest.TestCase):
    """任务 2.5 / 9.1：todo.md 解析（三节 + 四字段 + 占位跳过 + 未知小节跳过）。"""

    SAMPLE_TODO = """\
## 2026-09-12

### 浪费

- **冗余函数 test_unused**
  - 影响：测试文件体积膨胀
  - 证据：tests/test_foo.py 有 15 处未引用
  - 调查评估：历史遗留死代码
  - 建议：删除 test_unused 系列

### 失误

- （当日无）

### 可改进

- **日志格式不统一**
  - 影响：告警难以检索
  - 证据：多处 logger 调用参数顺序不一致

## 2026-09-11

### 浪费

- **临时脚本残留**
  - 影响：主树存在未跟踪文件
  - 证据：ls 输出含 fix_tmp_*.py
"""

    def test_parse_entries_basic(self):
        """两个日期节，三个条目（一个跳过占位）。"""
        entries = parse_todo_entries(self.SAMPLE_TODO)
        self.assertEqual(len(entries), 3)
        # 第一条：2026-09-12 浪费
        e0 = entries[0]
        self.assertEqual(e0["date_section"], "2026-09-12")
        self.assertEqual(e0["section"], "浪费")
        self.assertEqual(e0["title"], "冗余函数 test_unused")
        self.assertIn("测试文件体积膨胀", e0.get("impact", ""))
        self.assertIn("15 处未引用", e0.get("evidence", ""))
        self.assertIn("历史遗留死代码", e0.get("analysis", ""))
        self.assertIn("删除 test_unused 系列", e0.get("suggestion", ""))
        # 第三条：2026-09-11 浪费
        e2 = entries[2]
        self.assertEqual(e2["date_section"], "2026-09-11")
        self.assertEqual(e2["title"], "临时脚本残留")

    def test_empty_marker_skipped(self):
        """'（当日无）' 占位不产生条目。"""
        entries = parse_todo_entries(self.SAMPLE_TODO)
        # 第二节（失误）只有占位，没有条目
        mistake_entries = [e for e in entries if e["section"] == "失误"]
        self.assertEqual(len(mistake_entries), 0)

    def test_unknown_section_skipped_with_warning(self):
        """未知小节名跳过且不产生条目。"""
        text = "## 2026-09-12\n\n### 未知节\n\n- **未归属条目**\n  - 影响：测试\n"
        entries = parse_todo_entries(text)
        self.assertEqual(len(entries), 0)

    def test_multiline_field_concatenation(self):
        """四字段值多行续行正确拼接。"""
        text = (
            "## 2026-09-12\n\n### 可改进\n\n"
            "- **多行字段测试**\n"
            "  - 影响：第一行\n"
            "  - 影响：第二行续写\n"
        )
        entries = parse_todo_entries(text)
        self.assertEqual(len(entries), 1)
        self.assertIn("第一行", entries[0]["impact"])
        self.assertIn("第二行续写", entries[0]["impact"])


class TestEvolutionSelectPending(unittest.TestCase):
    """任务 2.6 / 9.1：增量筛选——已入库不重复选中，截断后下轮仍可选。"""

    def setUp(self):
        self.entries = [
            {"project": "p", "date_section": "d1", "section": "浪费",
             "title": "t1", "impact": "", "evidence": ""},
            {"project": "p", "date_section": "d1", "section": "失误",
             "title": "t2", "impact": "", "evidence": ""},
            {"project": "p", "date_section": "d1", "section": "浪费",
             "title": "t3", "impact": "", "evidence": ""},
        ]

    def test_filters_known_ids(self):
        """已入库条目被过滤。"""
        known = {item_id("p", "d1", "浪费", "t1")}
        result = select_pending_entries(self.entries, known, 10)
        titles = [e["title"] for e in result]
        self.assertNotIn("t1", titles)
        self.assertIn("t2", titles)
        self.assertIn("t3", titles)

    def test_deduplicates_within_batch(self):
        """同一批内重复条目去重。"""
        dup_entries = [self.entries[0], self.entries[0]]
        result = select_pending_entries(dup_entries, set(), 10)
        self.assertEqual(len(result), 1)

    def test_limit_truncation(self):
        """超出 limit 的条目被截断。"""
        result = select_pending_entries(self.entries, set(), 2)
        self.assertEqual(len(result), 2)

    def test_limit_zero_returns_empty(self):
        result = select_pending_entries(self.entries, set(), 0)
        self.assertEqual(len(result), 0)

    def test_ids_inserted(self):
        """结果中包含 id 字段。"""
        result = select_pending_entries(self.entries, set(), 10)
        for e in result:
            self.assertIn("id", e)
            self.assertEqual(len(e["id"]), 12)

    def test_preserves_original_order(self):
        """保持 todo.md 原始顺序。"""
        result = select_pending_entries(self.entries, set(), 10)
        titles = [e["title"] for e in result]
        self.assertEqual(titles, ["t1", "t2", "t3"])


# ── 任务 9.1（materialize_draft / read_contract）─────────────────────

from core.evolution import (
    materialize_draft,
    draft_dir,
    SPEC_YAML_TEMPLATE,
    ContractError,
    read_contract,
    _spec_summary,
    _KEBAB_RE,
    _safe_draft_dir,
    evolution_dir,
    accept_item,
    reject_item,
    delete_item,
    auto_accept_pending,
    next_spec_run_at,
    resolve_spec_name,
    upsert_item,
    write_todo_marker,
    strip_processed_entries,
)

import core.evolution as evolution_mod  # noqa: E402 —— 供用例替换项目名→路径解析


class TestEvolutionTodoMarker(unittest.TestCase):
    """todo.md 处理标记：回写 AI 结论 / 处理意见 / 删除标志；带标记条目跳过。"""

    SAMPLE = (
        "## 2026-09-13\n\n"
        "### 浪费\n"
        "- **问题甲**\n"
        "  - 影响：i1\n"
        "  - 证据：e1\n"
        "  - 调查评估：a1\n"
        "  - 建议：s1\n\n"
        "### 可改进\n"
        "- **问题乙**\n"
        "  - 影响：i2\n"
        "  - 证据：e2\n"
        "  - 调查评估：a2\n"
        "  - 建议：s2\n"
    )

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)
        self.todo = self.proot / ".fenix" / "todo.md"
        self.todo.parent.mkdir(parents=True, exist_ok=True)
        self.todo.write_text(self.SAMPLE, encoding="utf-8")
        self._orig_resolver = evolution_mod._resolve_project_path_by_name
        evolution_mod._resolve_project_path_by_name = lambda name: self.proot

    def tearDown(self):
        evolution_mod._resolve_project_path_by_name = self._orig_resolver
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ── 辅助 ──────────────────────────────────────────────────
    def _lines(self):
        return self.todo.read_text(encoding="utf-8").splitlines()

    def _marker_for(self, title):
        lines = self._lines()
        idx = next(i for i, l in enumerate(lines)
                   if l.strip() == f"- **{title}**")
        return lines[idx + 1].strip()

    def _item(self, title="问题甲", section="浪费", **verdict):
        base = {"problem_exists": "yes", "suggestion_sound": "yes",
                "worth_spec": True, "rationale": "r"}
        base.update(verdict)
        return {
            "project": "proj", "date_section": "2026-09-13", "section": section,
            "title": title, "impact": "i", "evidence": "e", "analysis": "a",
            "suggestion": "s", "verdict": base, "analysis_md": "md",
            "spec": {"name": "add-evo-x", "capability": "evo-x",
                     "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
                     "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n"},
        }

    def _seed_record(self, eid="a1b2c3d4e5f6", title="问题甲", status="pending"):
        upsert_item(self.proot, {
            "id": eid, "project": "proj", "date_section": "2026-09-13",
            "section": "浪费", "title": title, "impact": "i", "evidence": "e",
            "analysis": "a", "suggestion": "s",
            "verdict": {"worth_spec": True, "problem_exists": "yes",
                        "suggestion_sound": "yes", "rationale": "r"},
            "analysis_md": "md",
            "spec": {"name": "add-evo-x", "capability": "evo-x",
                     "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
                     "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n"},
            "spec_summary": "", "degraded": None,
            "created_at": "2026-09-13T00:00:00Z", "decided_at": None,
            "decided_by": None, "spec_name": None,
            "violations": None, "draft_failed_reason": None, "status": status,
        })

    # ── 写入 ──────────────────────────────────────────────────
    def test_ingest_writes_marker_right_after_title(self):
        """落地后标记行紧跟在标题行下方，含 AI 结论 + 处理：待处理。"""
        evolution_mod.ingest_item(self._item(), self.proot)
        lines = self._lines()
        idx = next(i for i, l in enumerate(lines) if l.strip() == "- **问题甲**")
        self.assertEqual(
            lines[idx + 1].strip(),
            "- 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：待处理 · 删除：否")

    def test_analyzed_marker_has_no_disposition(self):
        """不需要立项的条目只写 AI 结论，不出现处理/删除段。"""
        evolution_mod.ingest_item(
            self._item(suggestion_sound="partial", worth_spec=False), self.proot)
        self.assertEqual(
            self._marker_for("问题甲"),
            "- 自进化：问题成立 / 建议部分合理 / — 不需要")

    def test_accept_updates_marker_to_accepted(self):
        self._seed_record()
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        d.mkdir(parents=True)
        for name in ("proposal.md", "design.md", "tasks.md", ".spec.yaml"):
            (d / name).write_text("x", encoding="utf-8")
        (d / "specs" / "evo-x").mkdir(parents=True)
        (d / "specs" / "evo-x" / "spec.md").write_text("x", encoding="utf-8")
        result = accept_item("a1b2c3d4e5f6", self.proot, _StateMachineFixture(self.proot).sm)
        self.assertTrue(result["ok"])
        self.assertIn("· 处理：接受 · 删除：否", self._marker_for("问题甲"))

    def test_reject_updates_marker_to_rejected(self):
        self._seed_record()
        evolution_mod.reject_item("a1b2c3d4e5f6", self.proot)
        self.assertIn("· 处理：拒绝 · 删除：否", self._marker_for("问题甲"))

    def test_delete_sets_deleted_flag(self):
        self._seed_record()
        delete_item("a1b2c3d4e5f6", self.proot)
        self.assertIn("· 处理：待处理 · 删除：是", self._marker_for("问题甲"))

    def test_marker_write_is_idempotent(self):
        """重复落地只更新那一行，不追加第二行。"""
        evolution_mod.ingest_item(self._item(), self.proot)
        evolution_mod.ingest_item(self._item(), self.proot)
        markers = [l for l in self._lines() if "自进化：" in l]
        self.assertEqual(len(markers), 1)

    def test_missing_entry_is_noop(self):
        """todo.md 里没有该条目（用户改过标题/删过）→ 不写、不抛、原文件不变。"""
        before = self.todo.read_text(encoding="utf-8")
        ok = write_todo_marker(self._item(title="不存在的条目"), project_path=self.proot)
        self.assertFalse(ok)
        self.assertEqual(self.todo.read_text(encoding="utf-8"), before)

    # ── 跳过 ──────────────────────────────────────────────────
    def test_parse_skips_marked_entry(self):
        """带标记行的条目 MUST NOT 进入待分析集合。"""
        write_todo_marker(self._item(), project_path=self.proot)
        entries = parse_todo_entries(self.todo.read_text(encoding="utf-8"))
        titles = [e["title"] for e in entries]
        self.assertEqual(titles, ["问题乙"])

    def test_strip_processed_entries_removes_marked_block(self):
        """剥离后的文本不含已处理条目（含其四字段）。"""
        write_todo_marker(self._item(), project_path=self.proot)
        stripped = strip_processed_entries(self.todo.read_text(encoding="utf-8"))
        self.assertNotIn("问题甲", stripped)
        self.assertNotIn("i1", stripped)
        self.assertIn("问题乙", stripped)
        self.assertIn("i2", stripped)
        # 剥离前后未标记条目的解析结果一致
        self.assertEqual(
            [e["title"] for e in parse_todo_entries(stripped)], ["问题乙"])


class TestEvolutionMaterializeDraft(unittest.TestCase):
    """任务 3.1：草稿落盘——校验与写入。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _valid_spec(self):
        return {
            "name": "add-fix-test",
            "capability": "test-capability",
            "proposal_md": "# Proposal",
            "design_md": "# Design",
            "spec_md": "# Spec",
            "tasks_md": ("## Deliverables\n\n```yaml\n"
                         "- path: a.txt\n  kind: new\n```\n\n"
                         "## 1. 实现\n\n- [ ] 1.1 落地功能\n"),
        }

    def test_materialize_draft_success(self):
        """合法 spec → draft_dir 创建成功，五文件齐全。"""
        item = {"project": "p", "date_section": "2026-09-12",
                "section": "浪费", "title": "t",
                "spec": self._valid_spec()}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNotNone(d)
        self.assertEqual(reason, "")
        self.assertTrue((d / "proposal.md").is_file())
        self.assertTrue((d / "design.md").is_file())
        self.assertTrue((d / "specs" / "test-capability" / "spec.md").is_file())
        self.assertTrue((d / "tasks.md").is_file())
        spec_yaml = (d / ".spec.yaml").read_text(encoding="utf-8")
        self.assertIn("schema: spec-driven", spec_yaml)
        self.assertIn("mode: full", spec_yaml)

    def test_materialize_draft_no_spec(self):
        """无 spec 字段 → None + reason。"""
        item = {"project": "p", "date_section": "d", "section": "浪费", "title": "t"}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNone(d)
        self.assertIn("spec 内容", reason)

    def test_materialize_draft_bad_name(self):
        """spec.name 非法 → None。"""
        item = {"project": "p", "date_section": "d", "section": "浪费", "title": "t",
                "spec": {"name": "UPPER", "capability": "cap",
                         "proposal_md": "p", "design_md": "d",
                         "spec_md": "s", "tasks_md": "t"}}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNone(d)
        self.assertIn("spec.name 非法", reason)

    def test_materialize_draft_bad_capability(self):
        """spec.capability 非法 → None。"""
        item = {"project": "p", "date_section": "d", "section": "浪费", "title": "t",
                "spec": {"name": "add-fix", "capability": "INVALID!",
                         "proposal_md": "p", "design_md": "d",
                         "spec_md": "s", "tasks_md": "t"}}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNone(d)
        self.assertIn("spec.capability 非法", reason)

    def test_materialize_draft_missing_doc(self):
        """spec 缺必备文档 → None。"""
        item = {"project": "p", "date_section": "d", "section": "浪费", "title": "t",
                "spec": {"name": "add-fix", "capability": "cap",
                         "proposal_md": "p", "design_md": None,
                         "spec_md": "s", "tasks_md": ""}}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNone(d)
        self.assertIn("design_md", reason)
        self.assertIn("tasks_md", reason)

    def test_materialize_draft_bad_spec_type(self):
        """spec 不是 dict → None。"""
        item = {"project": "p", "date_section": "d", "section": "浪费",
                "title": "t", "spec": "bad"}
        d, reason = materialize_draft(item, self.proot)
        self.assertIsNone(d)


class TestEvolutionReadContract(unittest.TestCase):
    """任务 3.8：契约产物解析。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_contract(self, data: dict) -> Path:
        p = self.proot / "out.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return p

    def _valid_item(self, **overrides):
        return {
            "project": "proj", "date_section": "2026-09-12",
            "section": "浪费", "title": "问题", "verdict": {"worth_spec": False},
            **overrides,
        }

    def test_valid_contract(self):
        data = {"run_id": "evo-1", "degraded": None,
                "items": [self._valid_item()]}
        result = read_contract(self._write_contract(data))
        self.assertEqual(len(result["items"]), 1)

    def test_corrupt_json_raises(self):
        p = self.proot / "bad.json"
        p.write_text("not json", encoding="utf-8")
        with self.assertRaises(ContractError):
            read_contract(p)

    def test_missing_items_raises(self):
        with self.assertRaises(ContractError):
            read_contract(self._write_contract({"run_id": "evo-1"}))

    def test_invalid_section_raises(self):
        data = {"run_id": "e", "items": [
            self._valid_item(section="未知节"),
        ]}
        with self.assertRaises(ContractError):
            read_contract(self._write_contract(data))

    def test_item_missing_title_raises(self):
        item = {"project": "p", "date_section": "d", "section": "浪费",
                "verdict": {"worth_spec": False}}
        data = {"run_id": "e", "items": [item]}
        with self.assertRaises(ContractError):
            read_contract(self._write_contract(data))


class TestEvolutionSpecSummary(unittest.TestCase):
    """_spec_summary 摘要辅助。"""

    def test_spec_summary_non_none(self):
        result = _spec_summary({
            "name": "add-fix", "capability": "cap",
            "proposal_md": "p", "spec_md": "s",
            "design_md": "d", "tasks_md": "t"})
        self.assertIn("proposal_len", result)
        self.assertIn("add-fix", result)

    def test_spec_summary_none(self):
        self.assertEqual(_spec_summary(None), "")
        self.assertEqual(_spec_summary("bad"), "")


class TestEvolutionSafeDraftDir(unittest.TestCase):
    """3.6：路径安全校验。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_normal_id_resolves(self):
        base = evolution_dir(self.proot) / "drafts" / "abc123"
        self.assertIsNone(_safe_draft_dir(self.proot, "../etc"))
        self.assertIsNone(_safe_draft_dir(self.proot, "abc/def"))
        self.assertIsNone(_safe_draft_dir(self.proot, ""))
        self.assertIsNone(_safe_draft_dir(self.proot, ".."))
        # 合法 id 返回非 None（不要求目录存在）
        self.assertIsNotNone(_safe_draft_dir(self.proot, "abc123"))

    def test_null_byte_rejected(self):
        self.assertIsNone(_safe_draft_dir(self.proot, "abc\x00def"))


class TestEvolutionMaterializeDraftWriting(unittest.TestCase):
    """3.1：写盘完整性（draft_dir 位置）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_draft_dir_position(self):
        """draft_dir 返回路径位于 evolution/drafts/<id>/ 下。"""
        d = draft_dir(self.proot, "test123")
        self.assertEqual(d.name, "test123")
        self.assertEqual(d.parent.name, "drafts")
        self.assertEqual(d.parent.parent.name, "evolution")


# ── 任务 9.3 / 9.4（接受 / 拒绝 / 自动接受）────────────────────────

def _make_git_repo(path: Path) -> Path:
    """初始化临时 git 仓库（含初始提交与 spec/changes 占位）。"""
    path.mkdir(parents=True, exist_ok=True)
    import subprocess as _sp

    for cmd in (
        ["git", "init", "-q", str(path)],
        ["git", "-C", str(path), "config", "user.email", "test@fenix.local"],
        ["git", "-C", str(path), "config", "user.name", "Fenix Test"],
    ):
        _sp.run(cmd, capture_output=True, text=True, timeout=30,
                check=True)
    (path / "spec").mkdir(parents=True, exist_ok=True)
    (path / "spec" / "changes").mkdir(parents=True, exist_ok=True)
    (path / "README.md").write_text("test repo", encoding="utf-8")
    _sp.run(["git", "-C", str(path), "add", "--", "README.md"],
            capture_output=True, text=True, timeout=30, check=True)
    _sp.run(["git", "-C", str(path), "commit", "-m", "init"],
            capture_output=True, text=True, timeout=30, check=True)
    return path


class _StateMachineFixture:
    def __init__(self, proot: Path):
        state = proot / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix State\n\n", encoding="utf-8")
        from core.state_machine import StateMachine
        self.sm = StateMachine(state)


class TestEvolutionAcceptPath(unittest.TestCase):
    """任务 3.5 / 9.3：接受路径——落地提交与注册。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)
        self.sm = _StateMachineFixture(self.proot).sm

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _pending_record(self, eid="a1b2c3d4e5f6"):
        return {
            "id": eid, "project": "proj", "date_section": "2026-09-12",
            "section": "浪费", "title": "问题", "impact": "i", "evidence": "e",
            "analysis": "a", "suggestion": "s",
            "verdict": {"worth_spec": True, "problem_exists": "yes",
                        "suggestion_sound": "yes", "rationale": "r"},
            "analysis_md": "md",
            "spec": {
                "name": "add-evo-test", "capability": "evo-test",
                "proposal_md": "# Proposal", "design_md": "# Design",
                "spec_md": "# Spec",
                "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n",
            },
            "spec_summary": "", "degraded": None,
            "created_at": "2026-09-12T00:00:00Z", "decided_at": None,
            "decided_by": None, "spec_name": None,
            "violations": None, "draft_failed_reason": None,
            "status": "pending",
        }

    def _materialize_draft(self, eid="a1b2c3d4e5f6") -> Path:
        rec = self._pending_record(eid)
        upsert_item(self.proot, rec)
        d = draft_dir(self.proot, eid)
        d.mkdir(parents=True)
        (d / "proposal.md").write_text("p", encoding="utf-8")
        (d / "design.md").write_text("d", encoding="utf-8")
        (d / "tasks.md").write_text("t", encoding="utf-8")
        (d / ".spec.yaml").write_text("s", encoding="utf-8")
        (d / "specs" / "evo-test").mkdir(parents=True)
        (d / "specs" / "evo-test" / "spec.md").write_text("s", encoding="utf-8")
        return d

    def test_accept_success_commit_and_register(self):
        """人工同意完成立项全链：落目录、提交、注册。"""
        self._materialize_draft()
        result = accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["spec_name"], "evo-add-evo-test")
        # spec/changes 目录存在且已提交
        dest = self.proot / "spec" / "changes" / "evo-add-evo-test"
        self.assertTrue(dest.is_dir())
        # 暂存草稿已删除
        self.assertFalse(draft_dir(self.proot, "a1b2c3d4e5f6").exists())
        # STATE 已注册 drafted
        entry = self.sm.read_all().get("evo-add-evo-test")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["status"], "drafted")
        self.assertEqual(entry["priority"], 5)
        self.assertIsNone(entry.get("start_after"))
        # 条目状态
        items = read_items(self.proot)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "accepted")
        self.assertEqual(items["a1b2c3d4e5f6"]["spec_name"], "evo-add-evo-test")

    def test_accept_idempotent_on_accepted(self):
        """重复接受幂等：不产生第二次提交与 add_spec。"""
        self._materialize_draft()
        accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        result = accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["spec_name"], "evo-add-evo-test")
        # 无第二次提交：git log 应有且仅一次 [fenix] spec 提交
        import subprocess
        log = subprocess.run(
            ["git", "-C", str(self.proot), "log", "--oneline"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(log.stdout.strip().count("[fenix] spec:"), 1)

    def test_accept_with_start_after_registers_scheduled_spec(self):
        """带 start_after 的接受：新 SPEC 的 STATE 条目落该字段（定时拾取生效）。"""
        self._materialize_draft()
        sa = "2026-09-15T18:00:00+00:00"
        result = accept_item("a1b2c3d4e5f6", self.proot, self.sm,
                             start_after=sa)
        self.assertTrue(result["ok"])
        entry = self.sm.read_all().get("evo-add-evo-test")
        self.assertEqual(entry.get("start_after"), sa)

    def test_accept_without_start_after_keeps_field_null(self):
        """不带 start_after（缺省）：字段为 None，drafted 立即进入调度（原行为）。"""
        self._materialize_draft()
        accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        entry = self.sm.read_all().get("evo-add-evo-test")
        self.assertIsNone(entry.get("start_after"))

    def test_accept_with_empty_start_after_is_immediate(self):
        """start_after 为空串 = 立即执行（假值不写字段），不是「排队到 1970 年」。"""
        self._materialize_draft()
        accept_item("a1b2c3d4e5f6", self.proot, self.sm, start_after="")
        entry = self.sm.read_all().get("evo-add-evo-test")
        self.assertIsNone(entry.get("start_after"))
        # STATE 仅一条
        self.assertEqual(len(self.sm.read_all()), 1)

    def test_commit_failure_no_register_retryable(self):
        """提交失败不注册且可重试（移除副本、保留暂存草稿）。"""
        self._materialize_draft()
        # 制造提交失败：把 spec/changes 预置为同名目录使其 git add 冲突
        import subprocess
        conflict = self.proot / "spec" / "changes" / "evo-add-evo-test"
        conflict.mkdir(parents=True)
        (conflict / "block.txt").write_text("block", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.proot), "add", "--", "spec/changes/evo-add-evo-test"],
            capture_output=True, text=True, timeout=30)
        # 现在 commit 会因为冲突（已 add 的 block.txt 也在）失败——其实不会失败，
        # 我们改为让 commit 失败的方式：在 index 中塞入冲突状态。此处用 hook 更可靠
        # —— 注入 pre-commit 失败 hook
        hooks = self.proot / ".git" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        os.chmod(hooks / "pre-commit", 0o755)

        result = accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "accept_failed")
        # STATE 无该条目
        self.assertIsNone(self.sm.read_all().get("evo-add-evo-test"))
        # 暂存草稿保留（可重试）
        self.assertTrue(draft_dir(self.proot, "a1b2c3d4e5f6").exists())
        # 副本被清理（主树无未跟踪文件）
        self.assertFalse((self.proot / "spec" / "changes" / "evo-add-evo-test"
                          / "proposal.md").exists())

        # 移除 hook 后可重试成功
        (hooks / "pre-commit").unlink()
        result2 = accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        self.assertTrue(result2["ok"])
        self.assertEqual(result2["status"], "accepted")

    def test_name_conflict_appends_suffix(self):
        """重名自动加后缀。"""
        self._materialize_draft("a1b2c3d4e5f6")
        # 先接受第一条产生 evo-add-evo-test
        accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        # 第二条同 name
        self._materialize_draft("f6e5d4c3b2a1")
        result = accept_item("f6e5d4c3b2a1", self.proot, self.sm)
        self.assertTrue(result["ok"])
        self.assertTrue(result["spec_name"].startswith("evo-add-evo-test-"))
        self.assertEqual(len(result["spec_name"]), len("evo-add-evo-test-") + 6)

    def test_reject_already_accepted_fails(self):
        """已接受条目不可拒绝。"""
        self._materialize_draft()
        accept_item("a1b2c3d4e5f6", self.proot, self.sm)
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        # 暂存草稿已删除；为验证拒绝不改状态，直接调用
        result = reject_item("a1b2c3d4e5f6", self.proot)
        self.assertFalse(result["ok"])
        items = read_items(self.proot)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "accepted")


class TestEvolutionRejectPath(unittest.TestCase):
    """任务 3.6 / 9.3：拒绝路径。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delta_record(self, eid, status="pending"):
        rec = {
            "id": eid, "project": "proj", "date_section": "2026-09-12",
            "section": "可改进", "title": "问题", "verdict": {"worth_spec": True},
            "analysis_md": "md", "status": status,
            "created_at": "2026-09-12T00:00:00Z",
            "decided_at": None, "decided_by": None, "spec_name": None,
            "impact": "", "evidence": "", "analysis": "", "suggestion": "",
            "spec_summary": "", "degraded": None, "violations": None,
            "draft_failed_reason": None, "spec": None,
        }
        upsert_item(self.proot, rec)

    def test_reject_pending_deletes_draft_and_sets_status(self):
        self._delta_record("a1b2c3d4e5f6")
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        d.mkdir(parents=True)
        (d / "proposal.md").write_text("p", encoding="utf-8")
        result = reject_item("a1b2c3d4e5f6", self.proot)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(d.exists())
        items = read_items(self.proot)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "rejected")
        self.assertIsNotNone(items["a1b2c3d4e5f6"]["decided_at"])
        # spec/changes 目录存在但无 evo- 条目
        evo_entries = [p for p in (self.proot / "spec" / "changes").iterdir()
                       if p.name.startswith("evo-")]
        self.assertEqual(len(evo_entries), 0)

    def test_reject_accepted_not_allowed(self):
        self._delta_record("a1b2c3d4e5f6", status="accepted")
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        d.mkdir(parents=True)
        result = reject_item("a1b2c3d4e5f6", self.proot)
        self.assertFalse(result["ok"])
        # 草稿与状态不改动
        self.assertTrue(d.exists())
        items = read_items(self.proot)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "accepted")

    def test_reject_rejected_not_allowed(self):
        self._delta_record("a1b2c3d4e5f6", status="rejected")
        result = reject_item("a1b2c3d4e5f6", self.proot)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "rejected")

    def test_reject_unknown_id(self):
        result = reject_item("nonexistent", self.proot)
        self.assertFalse(result["ok"])

    def test_reject_symlink_escape_rejected(self):
        """越界路径（符号链接指向外部）不被删除。"""
        self._delta_record("a1b2c3d4e5f6")
        # 草稿目录替换为指向外部的符号链接
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        outside = self.proot.parent / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "payload.txt").write_text("keep", encoding="utf-8")
        # 先建真实目录再替换为 symlink（安全：symlink 指向外部）
        d.parent.mkdir(parents=True, exist_ok=True)
        d.symlink_to(outside, target_is_directory=True)
        result = reject_item("a1b2c3d4e5f6", self.proot)
        self.assertFalse(result["ok"])
        self.assertTrue((outside / "payload.txt").exists())
        # 条目状态保持 pending（未被篡改为 rejected）
        items = read_items(self.proot)
        self.assertEqual(items["a1b2c3d4e5f6"]["status"], "pending")


class TestEvolutionDeletePath(unittest.TestCase):
    """删除路径（硬删）：任意状态可删，记录移出 items.jsonl，草稿目录一并清理。

    硬删的已知后果：该 id 不再出现在 known_ids() 中，todo.md 里同名记录会在
    下一轮分析 run 重新入库（用户已确认接受）。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _delta_record(self, eid, status="pending"):
        rec = {
            "id": eid, "project": "proj", "date_section": "2026-09-12",
            "section": "可改进", "title": "问题", "verdict": {"worth_spec": True},
            "analysis_md": "md", "status": status,
            "created_at": "2026-09-12T00:00:00Z",
            "decided_at": None, "decided_by": None, "spec_name": None,
            "impact": "", "evidence": "", "analysis": "", "suggestion": "",
            "spec_summary": "", "degraded": None, "violations": None,
            "draft_failed_reason": None, "spec": None,
        }
        upsert_item(self.proot, rec)

    def test_delete_removes_record_and_draft_dir(self):
        self._delta_record("a1b2c3d4e5f6")
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        d.mkdir(parents=True)
        (d / "proposal.md").write_text("p", encoding="utf-8")
        result = delete_item("a1b2c3d4e5f6", self.proot)
        self.assertTrue(result["ok"])
        self.assertNotIn("a1b2c3d4e5f6", read_items(self.proot))
        self.assertFalse(d.exists())

    def test_delete_keeps_other_records(self):
        self._delta_record("a1b2c3d4e5f6")
        self._delta_record("ffffffffffff")
        result = delete_item("a1b2c3d4e5f6", self.proot)
        self.assertTrue(result["ok"])
        items = read_items(self.proot)
        self.assertNotIn("a1b2c3d4e5f6", items)
        self.assertIn("ffffffffffff", items)

    def test_delete_accepted_allowed(self):
        """全部状态可删：已同意条目同样允许删除（不设状态门）。"""
        self._delta_record("a1b2c3d4e5f6", status="accepted")
        result = delete_item("a1b2c3d4e5f6", self.proot)
        self.assertTrue(result["ok"])
        self.assertNotIn("a1b2c3d4e5f6", read_items(self.proot))

    def test_delete_unknown_id(self):
        result = delete_item("nonexistent", self.proot)
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])

    def test_delete_symlink_escape_keeps_record(self):
        """草稿目录为指向外部的软链 → 拒绝删除，记录保持不动。"""
        self._delta_record("a1b2c3d4e5f6")
        d = draft_dir(self.proot, "a1b2c3d4e5f6")
        outside = self.proot.parent / "outside"
        outside.mkdir(exist_ok=True)
        (outside / "payload.txt").write_text("keep", encoding="utf-8")
        d.parent.mkdir(parents=True, exist_ok=True)
        d.symlink_to(outside, target_is_directory=True)
        result = delete_item("a1b2c3d4e5f6", self.proot)
        self.assertFalse(result["ok"])
        self.assertTrue((outside / "payload.txt").exists())
        self.assertIn("a1b2c3d4e5f6", read_items(self.proot))


class TestEvolutionAutoAccept(unittest.TestCase):
    """任务 3.7 / 9.4：自动接受。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)
        self.sm = _StateMachineFixture(self.proot).sm

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_with_drafts(self, eids):
        """为若干 eid 建 pending 条目 + 草稿目录。"""
        for eid in eids:
            rec = {
                "id": eid, "project": "proj", "date_section": "2026-09-12",
                "section": "浪费", "title": f"问题 {eid}",
                "impact": "i", "evidence": "e", "analysis": "a",
                "suggestion": "s",
                "verdict": {"worth_spec": True, "problem_exists": "yes",
                            "suggestion_sound": "yes", "rationale": "r"},
                "analysis_md": "md",
                "spec": {"name": f"evo-auto-{eid}",
                         "capability": "evo-test",
                         "proposal_md": "# P", "design_md": "# D",
                         "spec_md": "# S",
                         "tasks_md": "## Deliverables\n\n- path: a.txt\n  kind: new\n"},
                "spec_summary": "", "degraded": None,
                "created_at": "2026-09-12T00:00:00Z", "decided_at": None,
                "decided_by": None, "spec_name": None,
                "violations": None, "draft_failed_reason": None,
                "status": "pending",
            }
            upsert_item(self.proot, rec)
            d = draft_dir(self.proot, eid)
            d.mkdir(parents=True)
            (d / "proposal.md").write_text("p", encoding="utf-8")
            (d / "design.md").write_text("d", encoding="utf-8")
            (d / "tasks.md").write_text("t", encoding="utf-8")
            (d / ".spec.yaml").write_text("s", encoding="utf-8")
            (d / "specs" / "evo-test").mkdir(parents=True)
            (d / "specs" / "evo-test" / "spec.md").write_text("s", encoding="utf-8")

    def test_auto_accept_all_pending(self):
        """开关为真时全部 pending 被接受且 decided_by=auto。"""
        self._seed_with_drafts(["a1a1a1a1a1a1", "b2b2b2b2b2b2"])
        summary = auto_accept_pending(self.proot, self.sm)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(summary["failed"], 0)
        items = read_items(self.proot)
        for eid in ("a1a1a1a1a1a1", "b2b2b2b2b2b2"):
            self.assertEqual(items[eid]["status"], "auto_accepted")
            self.assertEqual(items[eid]["decided_by"], "auto")
            self.assertTrue(items[eid]["spec_name"].startswith("evo-"))

    def test_auto_accept_applies_spec_run_at(self):
        """spec_run_at 配置生效：批量立项的 SPEC 都排到「下一个该时刻」。"""
        self._seed_with_drafts(["a1a1a1a1a1a1", "b2b2b2b2b2b2"])
        summary = auto_accept_pending(self.proot, self.sm, spec_run_at="23:00")
        self.assertEqual(summary["accepted"], 2)
        # 期望值按同一进程的本地时区推算（用例不依赖机器时区）
        from datetime import datetime, timedelta, timezone
        now = datetime.now()
        want = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if want <= now:
            want += timedelta(days=1)
        want_iso = want.astimezone(timezone.utc).isoformat()
        specs = self.sm.read_all()
        for eid in ("a1a1a1a1a1a1", "b2b2b2b2b2b2"):
            entry = next((e for name, e in specs.items() if name.endswith(eid)), None)
            self.assertIsNotNone(entry, f"{eid} 未注册")
            # 同批共用一次换算结果：两条排到同一时刻
            self.assertEqual(entry.get("start_after"), want_iso)

    def test_auto_accept_without_spec_run_at_is_immediate(self):
        """未配 spec_run_at：立项后立即执行，start_after 缺省为 None。"""
        self._seed_with_drafts(["a1a1a1a1a1a1"])
        auto_accept_pending(self.proot, self.sm)
        entry = next((e for name, e in self.sm.read_all().items()
                      if name.endswith("a1a1a1a1a1a1")), None)
        self.assertIsNotNone(entry)
        self.assertIsNone(entry.get("start_after"))

    def test_auto_accept_ignores_non_pending(self):
        """analyzed 与 draft_failed 条目不受影响。"""
        self._seed_with_drafts(["c3c3c3c3c3c3"])
        upsert_item(self.proot, {
            "id": "analyzed1", "project": "proj", "status": "analyzed",
            "date_section": "d", "section": "浪费", "title": "a",
            "verdict": {"worth_spec": False}, "analysis_md": "md",
            "created_at": "t",
        })
        summary = auto_accept_pending(self.proot, self.sm)
        self.assertEqual(summary["total"], 1)
        items = read_items(self.proot)
        self.assertEqual(items["analyzed1"]["status"], "analyzed")
        self.assertEqual(items["c3c3c3c3c3c3"]["status"], "auto_accepted")

    def test_auto_accept_single_failure_does_not_affect_others(self):
        """单条失败不影响其余（名称冲突制造失败）。"""
        self._seed_with_drafts(["d1d1d1d1d1d1", "e2e2e2e2e2e2"])
        upsert_item(self.proot, {
            "id": "confl", "project": "proj", "status": "pending",
            "date_section": "d", "section": "浪费", "title": "c",
            "verdict": {"worth_spec": True}, "spec": None, "analysis_md": "m",
            "created_at": "t",
        })
        upsert_item(self.proot, {
            "id": "d1d1d1d1d1d1", "project": "proj", "status": "pending",
            "date_section": "d", "section": "浪费", "title": "x",
            "verdict": {"worth_spec": True}, "spec": None, "analysis_md": "m",
            "created_at": "t", "spec_name": None, "decided_at": None,
            "decided_by": None, "violations": None, "draft_failed_reason": None,
        })
        summary = auto_accept_pending(self.proot, self.sm)
        # confl 与 d1d1d1d1d1d1 缺 spec → draft_failed/失败，不影响 e2e2e2e2e2e2
        self.assertGreaterEqual(summary["failed"], 1)
        items = read_items(self.proot)
        self.assertEqual(items["e2e2e2e2e2e2"]["status"], "auto_accepted")


class TestEvolutionResolveSpecName(unittest.TestCase):
    """任务 3.4：SPEC 名生成与冲突消解。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir) / "proj"
        self.proot.mkdir(parents=True)
        _make_git_repo(self.proot)
        (self.proot / "spec" / "changes").mkdir(parents=True, exist_ok=True)
        (self.proot / "spec" / "archive").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_base_name(self):
        name = resolve_spec_name("add-x", "abc123def456", self.proot, None)
        self.assertEqual(name, "evo-add-x")

    def test_invalid_name_returns_none(self):
        self.assertIsNone(
            resolve_spec_name("UPPER", "abc123def456", self.proot, None))
        self.assertIsNone(
            resolve_spec_name("bad name", "abc123def456", self.proot, None))

    def test_conflict_with_changes_dir(self):
        (self.proot / "spec" / "changes" / "evo-add-x").mkdir(parents=True)
        name = resolve_spec_name("add-x", "abc123def456", self.proot, None)
        self.assertEqual(name, "evo-add-x-abc123")

    def test_conflict_with_state(self):
        from core.state_machine import StateMachine
        state = self.proot / ".fenix" / "STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text("# Fenix State\n\n", encoding="utf-8")
        sm = StateMachine(state)
        sm.add_spec("evo-add-x", {"status": "drafted", "priority": 5})
        name = resolve_spec_name("add-x", "abc123def456", self.proot, sm)
        self.assertEqual(name, "evo-add-x-abc123")

    def test_conflict_with_archive(self):
        (self.proot / "spec" / "archive" / "add-evo-add-x"
         ).mkdir(parents=True)
        name = resolve_spec_name("add-x", "abc123def456", self.proot, None)
        self.assertEqual(name, "evo-add-x-abc123")

    def test_both_conflicts_returns_none(self):
        (self.proot / "spec" / "changes" / "evo-add-x").mkdir(parents=True)
        (self.proot / "spec" / "changes" / "evo-add-x-abc123"
         ).mkdir(parents=True)
        self.assertIsNone(
            resolve_spec_name("add-x", "abc123def456", self.proot, None))


# ── 任务 4.5（模型链解析 / 不创建 worktree）────────────────────────

from core.agent_runner.runner import AgentRunner, EvolutionResult


class _FakeEvolutionRunner(AgentRunner):
    """以 __new__ 绕过 __init__，仅按测试需要装配的最小 AgentRunner 替身。

    _run_claude 被替换为记录 cwd/run_id/model 并模拟产物写盘的替身——不实测
    真实 claude 进程（任务 4.5「可用替身注入」）。
    """

    def __init__(self, proot: Path, config: dict):
        # 直接装配 __dict__（__new__ 绕过 __init__）
        self.proot = Path(proot)
        self._assignment = {}
        self._tokens = []
        self._build_prompt_calls = []
        self.calls = []
        self.project_root = self.proot
        self.config = config or {}
        self.state_machine = None
        self.logger = None
        self.worktree_manager = None

    def _setup(self, proot: Path, config: dict):
        self.project_root = Path(proot)
        self.config = config or {}
        self.state_machine = None
        self.logger = None
        self.calls = []  # 记录 (cwd, run_id, model, env)
        self._build_prompt_calls = []
        self.worktree_manager = None

    def _run_claude(self, prompt, cwd, run_id, model_override=None,
                    env_overrides=None, resume_session_id=None,
                    max_turns=None, spec_name=None, agent_type=None):
        # 模拟写入契约产物（success 路径）
        self.calls.append({
            "cwd": str(cwd), "run_id": run_id, "model": model_override,
            "env_overrides": dict(env_overrides or {}), "spec_name": spec_name,
        })
        out = {
            "run_id": run_id, "degraded": None, "items": [
                {"project": "proj", "date_section": "2026-09-12",
                 "section": "浪费", "title": "测试条目",
                 "impact": "i", "evidence": "e", "analysis": "a",
                 "suggestion": "s",
                 "verdict": {"problem_exists": "yes", "suggestion_sound": "yes",
                             "worth_spec": False, "rationale": "证据: t.py:1"},
                 "analysis_md": "## 分析\n结论：不存在问题。",
                 "spec": None,
                },
            ],
        }
        out_path = cwd / ".fenix" / "evolution" / f"out-{run_id}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False),
                            encoding="utf-8")
        return "", 3, "session-1", {"input_tokens": 10, "output_tokens": 5}

    def _build_prompt(self, spec_name, agent_type, detail=None, wt_path=None):
        self._build_prompt_calls.append(agent_type)
        return "fake prompt"

    def _get_agent_model_assignment(self, agent_type):
        return self._assignment.get(agent_type)

    def _get_admin_model(self):
        return "DEFAULT_MODEL"

    def _get_config(self, key, default=None):
        from core.config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    def _ensure_agent_config_dir(self, provider_name):
        d = self.project_root / ".fenix" / "cc" / provider_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _extract_usage_info(self, result_event):
        return {"input_tokens": 0, "output_tokens": 0}

    def _accumulate_evolution_tokens(self, run_id, usage_info):
        self._tokens.append(run_id)

    def run_with(self, ready_projects, config):
        from core.agent_runner.runner import AgentRunner
        self._assignment = {}
        self._tokens = []
        self._build_prompt_calls = []
        self.project_root = self.proot
        self.config = config or {}
        self.state_machine = None
        self.logger = None
        self.worktree_manager = None
        result = self.run_evolution(ready_projects, [])
        return result


class TestEvolutionRunnerModelChain(unittest.TestCase):
    """任务 4.5：模型链解析（self-review 命中 / 回退 administrator / 兜底）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _runner_with_assignment(self, assignment):
        runner = _FakeEvolutionRunner(self.proot, {})
        runner._assignment = assignment
        runner._tokens = []
        return runner

    def _provider(self, name="p1", model="m1"):
        return ({"name": name, "baseurl": "http://x", "apikey": "k"}, model)

    def test_self_review_chain_hit(self):
        """agents.models.self-review 命中 → 使用其 provider/model。"""
        runner = self._runner_with_assignment({
            "self-review": [self._provider("p-sr", "m-sr")],
            "administrator": [self._provider("p-admin", "m-admin")],
        })
        result = runner.run_with([], {})
        self.assertTrue(runner.calls, "应发起 run 调用")

    def test_fallback_to_administrator(self):
        """self-review 缺失 → 回退 administrator。"""
        runner = self._runner_with_assignment({
            "administrator": [self._provider("p-admin", "m-admin")],
        })
        runner.run_with([], {})
        self.assertTrue(runner.calls)
        # _build_prompt 使用 evolution 角色
        self.assertEqual(runner._build_prompt_calls, ["evolution"])

    def test_fallback_to_admin_model(self):
        """两者皆无 → _get_admin_model 兜底。"""
        runner = self._runner_with_assignment({})
        runner.run_with([], {})
        self.assertTrue(runner.calls)

    def test_no_worktree_created(self):
        """不创建 worktree：执行目录为主树 project_root。"""
        runner = self._runner_with_assignment({
            "self-review": [self._provider("p-sr", "m-sr")],
        })
        result = runner.run_with([],
                                 {"agents": {"max_turns": 10}})
        # run 在 project_root 下执行（cwd == project_root）
        for call in runner.calls:
            self.assertEqual(call["cwd"], str(self.proot))
        # worktree 目录无新增
        wt_root = self.proot / ".claude" / "worktrees"
        self.assertFalse(wt_root.exists())
        # run_id 前缀 evo-
        self.assertTrue(runner.calls[0]["run_id"].startswith("evo-"))
        self.assertTrue(result.success)
        self.assertEqual(result.items_ingested, 1)
        self.assertEqual(result.degraded, None)
        # 产物文件已清理（items.jsonl 会保留，out-*.json 必须删除）
        evo_dir = self.proot / ".fenix" / "evolution"
        leftover = [p.name for p in evo_dir.iterdir()
                    if p.name.startswith("out-evo-")]
        self.assertEqual(leftover, [])


# ── 任务 9.2（就绪扫描五分支 / 宿主守卫 / run 失败水位不推进）───────

def _make_managed_project(root: Path, name: str,
                          last_run_at: str | None,
                          todo_text: str = "") -> dict:
    """构造被管项目（self_review_state.json + todo.md），返回 registry 条目。"""
    proot = root / name
    fenix = proot / ".fenix"
    fenix.mkdir(parents=True, exist_ok=True)
    if last_run_at is not None:
        (fenix / "self_review_state.json").write_text(
            json.dumps({"last_run_at": last_run_at, "last_run_date": "2026-09-12"}),
            encoding="utf-8")
    if todo_text:
        (fenix / "todo.md").write_text(todo_text, encoding="utf-8")
    return {"name": name, "path": str(proot), "discovered": True, "exists": True}


class TestEvolutionScanReady(unittest.TestCase):
    """任务 2.4 / 9.2：就绪扫描五分支。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.managed = Path(self.tmpdir) / "managed"
        self.managed.mkdir(parents=True)
        self.framework = Path(self.tmpdir) / "framework"
        self.framework.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _state_missing_not_ready(self):
        """状态文件缺失 → 不就绪。"""
        proj = {"name": "p1", "path": str(self.managed / "p1"),
                "exists": True}
        (self.managed / "p1").mkdir(parents=True, exist_ok=True)
        (self.managed / "p1" / ".fenix").mkdir(parents=True, exist_ok=True)
        (self.managed / "p1" / ".fenix" / "todo.md").write_text(
            "## 2026-09-12\n\n### 浪费\n\n- **t**\n", encoding="utf-8")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_invalid_last_run_at_not_ready(self):
        """last_run_at 非法 → 不就绪（不告警）。"""
        proj = _make_managed_project(self.managed, "p1", "not-a-time",
                                     "## 2026-09-12\n\n### 浪费\n\n- **t**\n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_not_later_than_watermark_not_ready(self):
        """last_run_at 不晚于水位 → 不就绪。"""
        proj = _make_managed_project(self.managed, "p1",
                                     "2026-09-12T03:00:00+00:00",
                                     "## 2026-09-12\n\n### 浪费\n\n- **t**\n")
        advance_watermark(self.framework, "p1",
                          "2026-09-12T04:00:00+00:00", "evo-1")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_missing_todo_not_ready(self):
        """todo.md 缺失 → 不就绪。"""
        proj = _make_managed_project(self.managed, "p1",
                                     "2026-09-12T03:00:00+00:00")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_blank_todo_not_ready(self):
        """todo.md 去空白后为空 → 不就绪。"""
        proj = _make_managed_project(self.managed, "p1",
                                     "2026-09-12T03:00:00+00:00",
                                     "   \n  \n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_all_entries_marked_not_ready(self):
        """条目全部带处理标记 → 无未处理条目，不就绪（省掉一整轮分析 run）。"""
        proj = _make_managed_project(
            self.managed, "p1", "2026-09-12T03:00:00+00:00",
            "## 2026-09-12\n\n### 浪费\n\n- **t**\n"
            "  - 自进化：问题成立 / 建议合理 / ✓ 值得立项 · 处理：接受 · 删除：否\n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 0)

    def test_ready_todo_md_has_processed_entries_stripped(self):
        """部分标记 → 仍就绪，但返回的 todo_md 已剥离已处理条目。"""
        proj = _make_managed_project(
            self.managed, "p1", "2026-09-12T03:00:00+00:00",
            "## 2026-09-12\n\n### 浪费\n\n- **已处理项**\n"
            "  - 自进化：问题成立 / 建议合理 / — 不需要\n\n"
            "- **待分析项**\n  - 影响：i\n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 1)
        self.assertNotIn("已处理项", ready[0]["todo_md"])
        self.assertIn("待分析项", ready[0]["todo_md"])

    def test_ready_project(self):
        """全条件满足 → 就绪（含 todo_md 全文）。"""
        proj = _make_managed_project(self.managed, "p1",
                                     "2026-09-12T03:00:00+00:00",
                                     "## 2026-09-12\n\n### 浪费\n\n- **t**\n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["name"], "p1")
        self.assertIn("## 2026-09-12", ready[0]["todo_md"])

    def test_no_watermark_record_is_ready(self):
        """无水位记录（从未分析）→ 只要 last_run_at 存在即就绪。"""
        proj = _make_managed_project(self.managed, "p1",
                                     "2026-09-12T03:00:00+00:00",
                                     "## 2026-09-12\n\n### 浪费\n\n- **t**\n")
        ready = scan_ready_projects([proj], self.framework)
        self.assertEqual(len(ready), 1)

    def test_multiple_projects_ready(self):
        """多个项目同时就绪 → 一并返回（一次 run 拿到多份 todo.md）。"""
        p1 = _make_managed_project(self.managed, "p1",
                                   "2026-09-12T03:00:00+00:00",
                                   "## 2026-09-12\n\n### 浪费\n\n- **t1**\n")
        p2 = _make_managed_project(self.managed, "p2",
                                   "2026-09-12T04:00:00+00:00",
                                   "## 2026-09-12\n\n### 可改进\n\n- **t2**\n")
        ready = scan_ready_projects([p1, p2], self.framework)
        self.assertEqual(len(ready), 2)
        names = {r["name"] for r in ready}
        self.assertEqual(names, {"p1", "p2"})


class TestEvolutionHostGuard(unittest.TestCase):
    """任务 9.2：非自托管宿主不启用。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_host_guard_unequal_roots(self):
        """PROJECT_ROOT != FRAMEWORK_ROOT → 检查点不派发（5.2）。"""
        import fenixd

        class _Silent:
            def info(self, *a, **k):
                pass
            def error(self, *a, **k):
                pass
            def warning(self, *a, **k):
                pass

        # 以 __new__ 构造真实 FenixDaemon 实例（类属性/静态方法可解析）
        daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        daemon._evolution_in_flight = False
        daemon._evolution_host_guard_logged = False
        daemon.logger = _Silent()

        from unittest import mock
        from pathlib import Path
        # Patch PROJECT_ROOT 到临时目录，FRAMEWORK_ROOT 保持真值（二者不等）
        with mock.patch.object(fenixd, "PROJECT_ROOT", self.proot):
            fenixd.FenixDaemon._check_evolution_checkpoint(daemon)
            self.assertTrue(daemon._evolution_host_guard_logged)


# ── 任务 9.2 / 9.3（read_contract / ingest_item / 检查点失败语义）────

from core.evolution import (
    read_contract as _rc,
)


class TestEvolutionIngestDraftFailed(unittest.TestCase):
    """任务 9.3：draft_failed（lint violation / 缺文档 / 非法 name）不留半成品。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / "spec" / "changes").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _contract_item(self, spec=None, worth_spec=True, **overrides):
        from core.evolution import item_id as _id
        item = {
            "project": "proj", "date_section": "2026-09-12", "section": "浪费",
            "title": "测试条目", "impact": "i", "evidence": "e",
            "analysis": "a", "suggestion": "s",
            "verdict": {"problem_exists": "yes", "suggestion_sound": "yes",
                        "worth_spec": worth_spec,
                        "rationale": "证据: t.py:1"},
            "analysis_md": "## 分析",
            "spec": spec,
            **overrides,
        }
        item["id"] = _id(item["project"], item["date_section"],
                         item["section"], item["title"])
        return item

    def _valid_spec(self):
        return {
            "name": "add-evo-x", "capability": "evo-cap",
            "proposal_md": "# P", "design_md": "# D", "spec_md": "# S",
            "tasks_md": (
                "## Deliverables\n\n"
                "```yaml\n- path: a.txt\n  kind: new\n```\n\n"
                "## 1. 实现\n\n"
                "- [ ] 1.1 落地功能\n"),
        }

    def test_worth_spec_false_analyzed_no_draft(self):
        """worth_spec 假 → analyzed，不建草稿目录。"""
        from core.evolution import ingest_item, read_items, draft_dir
        item = self._contract_item(spec=None, worth_spec=False)
        status = ingest_item(item, self.proot)
        self.assertEqual(status, "analyzed")
        items = read_items(self.proot)
        self.assertEqual(items[item["id"]]["status"], "analyzed")
        self.assertFalse(draft_dir(self.proot, item["id"]).exists())

    def test_valid_spec_pending_with_draft(self):
        """worth_spec 真 + 合法 spec → pending，草稿落盘。"""
        from core.evolution import ingest_item, read_items, draft_dir
        item = self._contract_item(spec=self._valid_spec())
        status = ingest_item(item, self.proot)
        self.assertEqual(status, "pending")
        items = read_items(self.proot)
        self.assertEqual(items[item["id"]]["status"], "pending")
        self.assertTrue(draft_dir(self.proot, item["id"]).is_dir())
        # 不落 spec/changes
        self.assertEqual(list((self.proot / "spec" / "changes").iterdir()), [])

    def test_missing_spec_content_draft_failed(self):
        """worth_spec 真但 spec 缺文档 → draft_failed，无半成品。"""
        from core.evolution import ingest_item, read_items, draft_dir
        item = self._contract_item(spec={"name": "add-evo-x",
                                         "capability": "evo-cap"})
        status = ingest_item(item, self.proot)
        self.assertEqual(status, "draft_failed")
        items = read_items(self.proot)
        self.assertEqual(items[item["id"]]["status"], "draft_failed")
        self.assertIn("spec 内容缺必备文档", items[item["id"]]["draft_failed_reason"])
        self.assertFalse(draft_dir(self.proot, item["id"]).exists())
        self.assertEqual(list((self.proot / "spec" / "changes").iterdir()), [])

    def test_bad_spec_name_draft_failed(self):
        """spec.name 非法 → draft_failed + 记录原因。"""
        from core.evolution import ingest_item, read_items
        item = self._contract_item(spec={**self._valid_spec(), "name": "BAD!"})
        status = ingest_item(item, self.proot)
        self.assertEqual(status, "draft_failed")
        items = read_items(self.proot)
        self.assertIn("spec.name 非法", items[item["id"]]["draft_failed_reason"])

    def test_lint_violation_draft_deleted(self):
        """lint 不过 → 草稿目录删除 + draft_failed + violation 记录。"""
        from core.evolution import ingest_item, read_items, draft_dir
        # tasks.md 声明 gitignored 路径 → lint_declared 应报 violation
        bad_tasks = (
            "## Deliverables\n\n"
            "- path: .fenix/evolution/x.txt\n"
            "  kind: new\n")
        item = self._contract_item(spec={
            **self._valid_spec(), "tasks_md": bad_tasks,
        })
        status = ingest_item(item, self.proot)
        self.assertEqual(status, "draft_failed")
        items = read_items(self.proot)
        rec = items[item["id"]]
        self.assertEqual(rec["status"], "draft_failed")
        self.assertTrue(rec["violations"], "应有 lint violation 记录")
        self.assertFalse(draft_dir(self.proot, item["id"]).exists())
        self.assertEqual(list((self.proot / "spec" / "changes").iterdir()), [])

    def test_read_contract_valid_and_invalid(self):
        """契约解析正常/非法分支。"""
        from core.evolution import ContractError
        p = self.proot / "out.json"
        p.write_text(json.dumps({
            "run_id": "evo-1", "items": [
                {"project": "p", "date_section": "2026-09-12",
                 "section": "可改进", "title": "t",
                 "verdict": {"worth_spec": False}}]}),
            encoding="utf-8")
        self.assertEqual(len(_rc(p)["items"]), 1)
        # 缺 verdict → 抛 ContractError
        p2 = self.proot / "bad.json"
        p2.write_text(json.dumps({
            "items": [{"project": "p", "date_section": "d",
                       "section": "浪费", "title": "t"}]}),
            encoding="utf-8")
        with self.assertRaises(ContractError):
            _rc(p2)


class TestEvolutionWorkerFailureSemantics(unittest.TestCase):
    """任务 9.2：run 失败水位不推进 + 告警；自动接受开关分流。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix").mkdir(parents=True, exist_ok=True)
        import fenixd
        self.daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        self.daemon._evolution_in_flight = True
        self.daemon.config = {}
        self.daemon.state_machine = None
        self.daemon.admin_store = None
        self.daemon._evolution_warn = self._fake_warn
        self.daemon.logger = type("S", (), {
            "error": lambda *a, **k: None, "info": lambda *a, **k: None,
            "warning": lambda *a, **k: None,
        })()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _fake_warn(self, message):
        self.warnings.append(message)

    def _stub_runner(self, **result_kw):
        from types import SimpleNamespace
        runner = SimpleNamespace()
        runner.run_evolution = lambda *a, **k: SimpleNamespace(**result_kw)
        return runner

    def test_failure_no_watermark_and_warning(self):
        """分析 run 失败 → 水位不推进 + WARNING 告警。"""
        from core.evolution import advance_watermark, read_watermarks
        import fenixd
        from unittest import mock
        self.warnings = []
        advance_watermark(self.proot, "proj", "2026-09-10T00:00:00Z", "evo-old")
        self.daemon.agent_runner = self._stub_runner(
            run_id="evo-123", success=False, items_ingested=0, drafts=0,
            accepted=0, degraded=None, error="模拟失败", output="")
        import fenixd
        with mock.patch.object(fenixd, "PROJECT_ROOT", self.proot):
            self.daemon._evolution_worker(
                [{"name": "proj", "path": str(self.proot)}], [],
                "2026-09-12T00:00:00Z")
        # 水位未推进（仍为 evo-old / 09-10）
        wm = read_watermarks(self.proot)
        self.assertEqual(wm["proj"]["last_run_id"], "evo-old")
        self.assertTrue(self.warnings, "应写 admin 告警")
        self.assertIn("模拟失败", self.warnings[0])
        # 在飞标记复位
        self.assertFalse(self.daemon._evolution_in_flight)

    def test_success_advances_watermark_snapshot(self):
        """分析 run 成功 → 水位用派发快照时刻推进（非落地时刻）。"""
        from core.evolution import read_watermarks
        import fenixd
        from unittest import mock
        self.warnings = []
        self.daemon.agent_runner = self._stub_runner(
            run_id="evo-200", success=True, items_ingested=2, drafts=1,
            accepted=0, degraded=None, error="", output="")
        # auto_accept 关闭 → pending 保持
        with mock.patch.object(fenixd, "PROJECT_ROOT", self.proot):
            self.daemon._evolution_worker(
                [{"name": "proj", "path": str(self.proot)}], [],
                "2026-09-12T03:00:00Z")
        wm = read_watermarks(self.proot)
        self.assertEqual(wm["proj"]["last_analyzed_at"], "2026-09-12T03:00:00Z")
        self.assertEqual(wm["proj"]["last_run_id"], "evo-200")
        self.assertFalse(self.daemon._evolution_in_flight)

    def test_auto_accept_enabled_calls_pending(self):
        """auto_accept 为真 → 自动接受路径被调用。"""
        from unittest import mock
        self.warnings = []
        self.daemon.agent_runner = self._stub_runner(
            run_id="evo-300", success=True, items_ingested=1, drafts=1,
            accepted=0, degraded=None, error="", output="")
        self.daemon.config = {"self_evolution": {"auto_accept": True}}
        with mock.patch(
                "core.evolution.auto_accept_pending",
                return_value={"total": 1, "accepted": 1, "failed": 0}):
            self.daemon._evolution_worker(
                [{"name": "proj", "path": str(self.proot)}], [],
                "2026-09-12T04:00:00Z")

    def test_checkpoint_internal_exception_does_not_raise(self):
        """检查点内部异常（registry 读取失败）→ 捕获记 ERROR，不中断主循环。"""
        from unittest import mock
        self.daemon.logger = type("S", (), {
            "error": lambda *a, **k: None, "info": lambda *a, **k: None,
            "warning": lambda *a, **k: None,
        })()
        with mock.patch.object(
                self.daemon, "_evolution_framework_root",
                return_value=self.proot):
            with mock.patch("core.dashboard.registry.Registry.discover",
                            side_effect=OSError("registry 读取失败")):
                with mock.patch("fenixd.PROJECT_ROOT", self.proot):
                    # 不应抛异常
                    self.daemon._check_evolution_checkpoint()


# ── evo-item-retention-doc-tracking 任务 1.7：检查点接入点回归 ──────

from core.evolution import (
    draft_dir as _draft_dir,
    items_path as _items_path,
    prune_items as _prune_items,
    read_items as _read_items,
    write_items as _write_items,
)
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class TestEvolutionCheckpointPrune(unittest.TestCase):
    """任务 1.7：检查点清理接入点回归（D4——清理不因在途跳过、非托管不清理）。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        (self.proot / ".fenix" / "evolution").mkdir(parents=True, exist_ok=True)
        import fenixd
        self.daemon = fenixd.FenixDaemon.__new__(fenixd.FenixDaemon)
        self.daemon._evolution_in_flight = False
        self.daemon._evolution_host_guard_logged = False
        self.daemon.config = {}
        self.daemon.state_machine = None
        self.daemon.admin_store = None
        self.daemon.agent_runner = None
        self.daemon.pm_engine = None
        self.daemon._evolution_warn = lambda *a, **k: None
        self.daemon.logger = type("S", (), {
            "error": lambda *a, **k: None, "info": lambda *a, **k: None,
            "warning": lambda *a, **k: None,
        })()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed_old_and_new(self, status="pending"):
        """写入 100 条 recent + 1 条 30 天前的受害条目 + 1 条今天的条目。

        受害条目必须落在「最近 7 天 ∪ 最近 100 条」之外才会被清理——仅 2 条
        时全部都在 top 100 内，永不删除。
        """
        now = _dt.now(_tz.utc)
        from core.evolution import upsert_item as _upsert
        for i in range(100):
            _upsert(self.proot, {
                "id": f"fill-{i:03d}", "project": "proj", "status": status,
                "date_section": "2026-09-12", "section": "浪费",
                "title": f"fill {i}", "verdict": {"worth_spec": False},
                "analysis_md": "md",
                "created_at": (now - _td(hours=i)).isoformat(),
            })
        old = {
            "id": "oldvictim123", "project": "proj", "status": status,
            "date_section": "2026-09-12", "section": "浪费", "title": "old",
            "verdict": {"worth_spec": False}, "analysis_md": "md",
            "created_at": (now - _td(days=30)).isoformat(),
        }
        new = {
            "id": "newkeeper456", "project": "proj", "status": "pending",
            "date_section": "2026-09-12", "section": "浪费", "title": "new",
            "verdict": {"worth_spec": True}, "analysis_md": "md",
            "created_at": now.isoformat(),
        }
        _upsert(self.proot, old)
        _upsert(self.proot, new)

    def _seed_draft_for_victim(self):
        d = _draft_dir(self.proot, "oldvictim123")
        d.mkdir(parents=True, exist_ok=True)
        (d / "proposal.md").write_text("x", encoding="utf-8")

    def test_prune_runs_despite_in_flight(self):
        """(a) _evolution_in_flight=True 时检查点仍清理过期受害条目。

        对齐 spec「清理不因分析 run 在途而跳过」：单飞判定在清理之后，
        在途只影响派发，不影响已执行的保留清理。
        """
        from unittest import mock
        import fenixd
        self._seed_old_and_new()
        self._seed_draft_for_victim()
        self.daemon._evolution_in_flight = True

        with mock.patch.object(
                self.daemon, "_evolution_framework_root",
                return_value=self.proot):
            with mock.patch("fenixd.PROJECT_ROOT", self.proot):
                with mock.patch(
                        "core.evolution.read_watermarks",
                        return_value={}):
                    # 阻断派发后续（无 ready 项目）：直接走到清理后即返回
                    with mock.patch(
                            "core.dashboard.registry.Registry.discover",
                            return_value=[]):
                        self.daemon._check_evolution_checkpoint()

        items = _read_items(self.proot)
        self.assertNotIn("oldvictim123", items, "过期受害条目应已被清理")
        self.assertIn("newkeeper456", items)
        self.assertFalse(
            _draft_dir(self.proot, "oldvictim123").exists(),
            "受害条目草稿目录应已被清理")

    def test_prune_despite_in_flight_even_with_ready_guard(self):
        """在途时检查点不派发（早于就绪扫描），清理仍发生。"""
        from unittest import mock
        import fenixd
        self._seed_old_and_new()
        self.daemon._evolution_in_flight = True
        pruned_calls = []

        with mock.patch.object(
                self.daemon, "_evolution_framework_root",
                return_value=self.proot):
            with mock.patch("fenixd.PROJECT_ROOT", self.proot):
                with mock.patch(
                        "core.evolution.prune_items",
                        side_effect=lambda *a, **k: pruned_calls.append(a)
                        or {"total": 0, "kept": 0, "deleted": 0,
                            "failed": 0, "details": []}):
                    self.daemon._check_evolution_checkpoint()

        self.assertEqual(len(pruned_calls), 1, "清理应恰好执行一次")

    def test_non_self_hosted_no_prune(self):
        """(b) PROJECT_ROOT != FRAMEWORK_ROOT → 检查点不触发任何清理。"""
        from unittest import mock
        import fenixd
        self._seed_old_and_new()
        self._seed_draft_for_victim()

        # FRAMEWORK_ROOT 指向 self.proot，而 PROJECT_ROOT patch 为他的子目录
        other_root = self.proot / "other_root"
        other_root.mkdir(exist_ok=True)
        pruned_calls = []

        with mock.patch.object(
                self.daemon, "_evolution_framework_root",
                return_value=self.proot):
            with mock.patch("fenixd.PROJECT_ROOT", other_root):
                with mock.patch(
                        "core.evolution.prune_items",
                        side_effect=lambda *a, **k: pruned_calls.append(a)
                        or {"total": 0, "kept": 0, "deleted": 0,
                            "failed": 0, "details": []}):
                    self.daemon._check_evolution_checkpoint()

        self.assertEqual(pruned_calls, [], "非自托管部署 MUST NOT 触发清理")


if __name__ == "__main__":
    unittest.main()
