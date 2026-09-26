"""add-codefix-affinity-batching 单测：选批亲和性聚类（1.1/1.2）、批内波次
上限自适应（2.1/2.4）、批收尾回归两段式（3.1-3.5）。

覆盖 spec 全部 Scenario：
- 同文件条目必同批 / 同目录组超目标规模仍同批 / 异目录组达目标规模即封批 /
  硬上限封批且余组进下批 / 单文件超大组独立成批不拆 / 排除口径与稳定性；
- 波次上限三档边界 + {wave_cap} prompt 注入 + 模板缺占位符回退；
- 链末批判定（含裸 count_open_items 陷阱反证）/ 触碰面映射规则 /
  {test_targets} 占位符 str/list 两态替换 / 三分支回退。
"""

import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.code_fix import (
    CODE_FIX_TEST_TARGETS_ENV,
    CODE_FIX_TEST_TARGETS_PLACEHOLDER,
    CODE_FIX_WAVE_CAP_MAX,
    _apply_test_targets,
    _cmd_has_test_targets,
    _file_parent_dir,
    _fixed_files_from_rows,
    _is_test_path,
    _map_fix_files_to_tests,
    _module_names_for_file,
    is_chain_last_batch,
    record_deferred_batch,
    record_failed_batch,
    select_batch,
    wave_cap_for_groups,
)
from core.verify_contract import RegressionSpec


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix)


def _make_project_root() -> Path:
    root = Path(_mkdtemp("affinity-proot-"))
    (root / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return root


def _write_items(project_root, records: dict) -> None:
    lines = "".join(
        json.dumps(rec, ensure_ascii=False) + "\n" for rec in records.values()
    )
    (project_root / ".fenix" / "code-review" / "items.jsonl").write_text(
        lines, encoding="utf-8"
    )


def _item(item_id, status="open", first_seen_at=None, **extra):
    rec = {
        "item_id": item_id,
        "status": status,
        "file": f"core/{item_id}.py",
        "line": 1,
        "severity": "major",
        "category": "correctness",
        "title": f"title {item_id}",
        "description": f"desc {item_id}",
        "suggestion": f"sug {item_id}",
        "fingerprint": f"fp-{item_id}",
    }
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    rec.update(extra)
    return rec


def _seq(prefix: str, file: str, start: int, count: int) -> dict:
    """生成同文件 count 条连续 first_seen_at 的条目集（t01..tNN 稳定序）。"""
    out = {}
    for i in range(start, start + count):
        iid = f"{prefix}{i:02d}"
        out[iid] = _item(
            iid,
            file=file,
            first_seen_at=f"2026-01-01T{(i // 60) % 24:02d}:{i % 60:02d}:00Z",
        )
    return out


def _ids(batch) -> list:
    return [r["item_id"] for r in batch]


# ── 1.1/1.2 选批亲和性聚类 ────────────────────────────────────────────


class TestAffinitySelectBatch(unittest.TestCase):
    def test_same_file_items_always_same_batch(self):
        """Scenario 同文件条目必同批：core/foo.py 3 条（t1/t5/t9）跨时间不被
        拆散；batch_size=4（T=4, H=8）时同目录 bar 组浮动吸收，异目录 baz 组
        因批 ≥ T 不再吸收——foo 组 3 条恒同批。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("f", "core/foo.py", 1, 1))   # t01
        records.update(_seq("b", "core/bar.py", 2, 2))   # t02-t03
        records.update(_seq("z", "util/baz.py", 4, 1))   # t04
        records.update(_seq("f", "core/foo.py", 5, 1))   # t05
        records.update(_seq("b", "core/bar.py", 6, 1))   # t06（bar 组第 3 条）
        records.update(_seq("f", "core/foo.py", 9, 1))   # t09
        _write_items(proot, records)
        batch = select_batch(proot, 4)
        got = _ids(batch)
        foo_ids = [k for k in got if k.startswith("f")]
        self.assertEqual(len(foo_ids), 3, f"同文件 3 条必同批: {got}")
        # 文件组不可拆且按最早 first_seen_at 参与装箱：foo（t01）开批，
        # 同目录 bar 浮动吸收（3+3=6 ≤ H=8），异目录 baz 因 6 ≥ T=4 不吸收
        self.assertEqual(got, ["f01", "f05", "f09", "b02", "b03", "b06"])

    def test_same_file_entries_across_time_same_batch_large_t(self):
        """spec Scenario 原样：batch_size=20 时三文件全并入一批，foo 3 条
        （t1/t5/t9）在同一批。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("f", "core/foo.py", 1, 1))
        records.update(_seq("b", "core/bar.py", 2, 2))
        records.update(_seq("z", "util/baz.py", 4, 1))
        records.update(_seq("f", "core/foo.py", 5, 1))
        records.update(_seq("f", "core/foo.py", 9, 1))
        _write_items(proot, records)
        batch = select_batch(proot, 20)
        foo_ids = [r["item_id"] for r in batch if r["file"] == "core/foo.py"]
        self.assertEqual(len(foo_ids), 3)

    def test_same_dir_group_floats_above_target(self):
        """Scenario 同目录文件超目标规模仍同批：批 8 条 + 同目录 15 条 =
        23 > T=20 但 ≤ H=40 → 吸收；异目录组不再吸收。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("a", "core/foo.py", 1, 8))    # 8 条
        records.update(_seq("b", "core/bar.py", 9, 15))   # 15 条（同目录 core/）
        records.update(_seq("c", "util/c.py", 24, 3))     # 异目录
        _write_items(proot, records)
        batch = select_batch(proot, 20)
        got = _ids(batch)
        self.assertEqual(len(got), 23, f"同目录组浮动吸收至 23（超 T=20）: {len(got)}")
        bar_ids = [k for k in got if k.startswith("b")]
        self.assertEqual(len(bar_ids), 15, "bar 组整组吸收（组不可拆）")
        self.assertFalse(any(k.startswith("c") for k in got), "异目录组 23 ≥ T 不吸收")

    def test_cross_dir_group_closes_batch_at_target(self):
        """Scenario 异目录组达到目标规模即封批：批 18（< T=20）吸收异目录
        5 条 → 23 ≥ T 立即封批；装不下的同目录组（43 > H=40）与封批后
        剩余组均不入选。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("a", "core/foo.py", 1, 10))    # 10
        records.update(_seq("b", "core/bar.py", 11, 8))    # 8（同目录 → 18）
        records.update(_seq("c", "util/c.py", 19, 5))      # 异目录 5 → 23 封批
        records.update(_seq("d", "core/big.py", 24, 25))   # 同目录但 18+25>40 不可吸收
        records.update(_seq("e", "util/e.py", 49, 2))      # 封批后不可入
        _write_items(proot, records)
        batch = select_batch(proot, 20)
        got = _ids(batch)
        self.assertEqual(len(got), 23)
        self.assertEqual(set(got), {f"a{i:02d}" for i in range(1, 11)}
                         | {f"b{i:02d}" for i in range(11, 19)}
                         | {f"c{i:02d}" for i in range(19, 24)})

    def test_hard_cap_closes_batch_and_rest_goes_next(self):
        """Scenario 硬上限封批：批 38 + 同目录 6（44 > H=40）→ 不吸收，
        38 封批；余组进下一装箱批（链推进 = 核销后重调 select_batch）。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("a", "core/x.py", 1, 20))
        records.update(_seq("b", "core/y.py", 21, 18))    # 同目录 → 38
        records.update(_seq("c", "core/z.py", 39, 6))     # 38+6 > 40 → 下批
        _write_items(proot, records)
        first = select_batch(proot, 20)
        self.assertEqual(len(first), 38, "38 条封批（未超硬上限）")
        self.assertEqual(
            set(_ids(first)),
            {f"a{i:02d}" for i in range(1, 21)} | {f"b{i:02d}" for i in range(21, 39)},
        )
        # 链推进语义：首批核销（置 resolved）后重调 → 余组进下批
        for iid in _ids(first):
            records[iid]["status"] = "resolved"
        _write_items(proot, records)
        second = select_batch(proot, 20)
        self.assertEqual(sorted(_ids(second)), sorted(f"c{i:02d}" for i in range(39, 45)))

    def test_oversized_single_file_group_standalone_not_split(self):
        """Scenario 单文件超大组独立成批不拆分：45 条 > H=40 整批保留。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("big", "core/huge.py", 1, 45))
        records.update(_seq("s", "util/s.py", 46, 2))
        _write_items(proot, records)
        batch = select_batch(proot, 20)
        got = _ids(batch)
        self.assertEqual(len(got), 45, "单文件组 45 条整组成批（MUST NOT 拆分）")
        self.assertTrue(all(r["file"] == "core/huge.py" for r in batch))
        self.assertFalse(any(k.startswith("s") for k in got), "超限组独立成批不吸收他组")

    def test_exclusion_scope_and_determinism(self):
        """Scenario 排除口径与稳定性不变：失败档案 ∪ chain_skipped 不入选；
        同一台账状态连续两次调用完全一致。"""
        proot = _make_project_root()
        records = {}
        records.update(_seq("a", "core/a.py", 1, 2))
        records.update(_seq("b", "core/b.py", 3, 2))
        records.update(_seq("c", "util/c.py", 5, 2))
        _write_items(proot, records)
        record_failed_batch(proot, ["a01", "a02"], "/tmp/wt-kept")
        exclude = {"b01"}
        first = select_batch(proot, 20, exclude_ids=exclude)
        second = select_batch(proot, 20, exclude_ids=exclude)
        self.assertEqual(_ids(first), _ids(second), "两次调用完全一致（确定性）")
        self.assertNotIn("a01", _ids(first), "失败档案条目不入选")
        self.assertNotIn("b01", _ids(first), "chain_skipped 条目不入选")
        self.assertTrue(any(k.startswith("c") for k in _ids(first)))


class TestSelectBatchHelpers(unittest.TestCase):
    def test_file_parent_dir_top_level_files_are_distinct(self):
        self.assertEqual(_file_parent_dir("core/foo.py"), "core")
        self.assertEqual(_file_parent_dir("a/b/c/foo.py"), "a/b/c")
        self.assertIsNone(_file_parent_dir("foo.py"), "顶层文件无父目录")
        self.assertIsNone(_file_parent_dir(""), "空路径无父目录")
        # 顶层文件互不同目录（design D1）：None 哨兵不参与同目录匹配——
        # 三个顶层文件在 T=2 下表现为异目录序列（第 3 条不入批）
        proot = _make_project_root()
        _write_items(proot, {
            "f": _item("f", file="foo.py", first_seen_at="2026-01-01T00:00:01Z"),
            "b": _item("b", file="bar.py", first_seen_at="2026-01-01T00:00:02Z"),
            "z": _item("z", file="baz.py", first_seen_at="2026-01-01T00:00:03Z"),
        })
        batch = select_batch(proot, 2)
        self.assertEqual(_ids(batch), ["f", "b"], "顶层文件互不为同目录（异目录封批）")

    def test_invalid_batch_size_falls_back_to_default_target(self):
        proot = _make_project_root()
        records = {}
        records.update(_seq("a", "core/a.py", 1, 25))
        _write_items(proot, records)
        # 非法 batch_size 回退缺省目标 20（H=40）：25 条同文件组独立成批
        batch = select_batch(proot, 0)
        self.assertEqual(len(batch), 25)


# ── 2.1/2.4 批内波次上限自适应 ────────────────────────────────────────


class TestWaveCap(unittest.TestCase):
    def test_tier_boundaries(self):
        """分档三档边界：4/5/8/9 组。"""
        self.assertEqual(wave_cap_for_groups(1), 4)
        self.assertEqual(wave_cap_for_groups(4), 4, "G ≤ 4 → 4")
        self.assertEqual(wave_cap_for_groups(5), 6, "5 ≤ G ≤ 8 → 6")
        self.assertEqual(wave_cap_for_groups(8), 6)
        self.assertEqual(wave_cap_for_groups(9), 8, "G ≥ 9 → 8")
        self.assertEqual(wave_cap_for_groups(12), 8)
        self.assertEqual(wave_cap_for_groups(0), 4, "空批回退下限")
        self.assertEqual(CODE_FIX_WAVE_CAP_MAX, 8, "8 为硬上限常量")

    def test_wave_cap_injected_into_prompt(self):
        """prompt 注入含 {wave_cap}：12 个文件组 → 注入 8。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        proot = _make_project_root()
        pb = PromptBuilder(SimpleNamespace(project_root=str(proot)))
        items = [
            _item(f"i{i}", file=f"pkg{i}/mod.py") for i in range(12)
        ]
        prompt = pb._build_code_fix_prompt("affinity-run-1", {"items": items})
        self.assertNotIn("{wave_cap}", prompt, "占位符应被替换")
        self.assertIn("并发上限 8", prompt)
        self.assertIn("**8**", prompt, "注入值在派发节以加粗呈现")

    def test_prompt_template_fallback_without_placeholder(self):
        """模板无 {wave_cap} 占位符回退缺省 4（旧模板文案兼容）。"""
        from core.agent_runner.prompt_builder import PromptBuilder

        proot = _make_project_root()
        pb = PromptBuilder(SimpleNamespace(project_root=str(proot)))
        old_template = "### 派发（波次语义，并发上限 4）\n\n- 同一波在飞子代理 ≤4（固定上限）\n"
        pb._load_agent_template = lambda name: old_template  # 旧模板替身
        items = [_item(f"i{i}", file=f"pkg{i}/mod.py") for i in range(12)]
        prompt = pb._build_code_fix_prompt("affinity-run-2", {"items": items})
        self.assertNotIn("{wave_cap}", prompt)
        self.assertIn("并发上限 4", prompt, "旧文案原样保留（行为=缺省 4）")

    def test_single_file_group_batch_still_floor(self):
        """Scenario 单文件大组批（G=1）仍为下限 4。"""
        self.assertEqual(wave_cap_for_groups(1), 4)


# ── 3.1 链末批判定 ────────────────────────────────────────────────────


class TestChainLastBatch(unittest.TestCase):
    def test_remaining_open_zero_is_last(self):
        proot = _make_project_root()
        records = {"a": _item("a"), "b": _item("b")}
        _write_items(proot, records)
        self.assertTrue(is_chain_last_batch(proot, ["a", "b"]), "排除本批后无剩余 → 末批")

    def test_remaining_open_nonzero_is_not_last(self):
        proot = _make_project_root()
        records = {"a": _item("a"), "b": _item("b"), "c": _item("c")}
        _write_items(proot, records)
        self.assertFalse(is_chain_last_batch(proot, ["a", "b"]), "c 仍可选 → 非末批")

    def test_excluded_open_items_do_not_defeat_last_batch(self):
        """反证（design D3）：被链口径排除的 open 条目（失败档案/延迟台账）
        令裸 count_open_items > 0，但同口径判定为末批。"""
        proot = _make_project_root()
        records = {"a": _item("a"), "b": _item("b")}
        _write_items(proot, records)
        record_failed_batch(proot, ["b"], "/tmp/wt-kept")
        self.assertTrue(
            is_chain_last_batch(proot, ["a"]),
            "失败档案条目不计入末批判定（裸 count_open_items 会误判非末批）",
        )
        # 延迟台账同口径：defer 条目在合回成功前始终 open
        proot2 = _make_project_root()
        records2 = {"x": _item("x"), "y": _item("y")}
        _write_items(proot2, records2)
        record_deferred_batch(
            proot2, ["y"], ["y"], worktree="/tmp/wt-defer", branch="b", tip_sha="t"
        )
        self.assertTrue(is_chain_last_batch(proot2, ["x"]))

    def test_chain_skipped_excluded(self):
        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        self.assertFalse(
            is_chain_last_batch(proot, ["a"], chain_skipped=[]) , "b 未排除 → 非末批"
        )
        self.assertTrue(
            is_chain_last_batch(proot, ["a"], chain_skipped=["b"]),
            "chain_skipped 与本批一并排除后无剩余 → 末批",
        )


# ── 3.2 触碰面映射 ────────────────────────────────────────────────────


class TestTouchFaceMapping(unittest.TestCase):
    def setUp(self):
        self.root = Path(_mkdtemp("affinity-map-"))
        (self.root / "core").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "core" / "foo.py").write_text("X = 1\n", encoding="utf-8")
        (self.root / "tests" / "test_bar.py").write_text(
            "import core.foo\n\n\ndef test_x():\n    assert core.foo.X == 1\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_test_file_directly_selected(self):
        self.assertEqual(
            _map_fix_files_to_tests(["tests/test_bar.py"], self.root),
            ["tests/test_bar.py"],
        )

    def test_name_match_and_import_reverse_lookup_union(self):
        """Scenario 触碰面映射规则：core/foo.py（命名匹配缺省 tests/ 无
        test_foo.py → 仅 import 反查）∪ tests/test_bar.py（直选）。"""
        (self.root / "core" / "tests").mkdir()
        (self.root / "core" / "tests" / "test_foo.py").write_text(
            "def test_foo():\n    pass\n", encoding="utf-8"
        )
        got = _map_fix_files_to_tests(["core/foo.py", "tests/test_bar.py"], self.root)
        self.assertIn("tests/test_bar.py", got, "测试文件直接入选")
        self.assertIn("tests/test_bar.py", got, "import 反查（同一文件并集去重）")
        self.assertIn("core/tests/test_foo.py", got, "同目录 tests/ 命名匹配")
        self.assertEqual(got, sorted(set(got)), "排序去重")

    def test_product_file_import_lookup(self):
        got = _map_fix_files_to_tests(["core/foo.py"], self.root)
        self.assertEqual(got, ["tests/test_bar.py"], "tests/ 树内 import 反查命中")

    def test_empty_mapping_when_no_match(self):
        (self.root / "core" / "lonely.py").write_text("Y = 2\n", encoding="utf-8")
        got = _map_fix_files_to_tests(["core/lonely.py"], self.root)
        self.assertEqual(got, [], "无命名匹配且无 import 反查 → 空集（fail-open）")

    def test_test_prefix_and_suffix_paths_direct(self):
        self.assertTrue(_is_test_path("test_helper.py"))
        self.assertTrue(_is_test_path("pkg/foo_test.py"))
        self.assertTrue(_is_test_path("tests/conftest.py"))
        self.assertFalse(_is_test_path("core/foo.py"))

    def test_module_names(self):
        self.assertEqual(_module_names_for_file("core/foo.py"), ["foo", "core.foo"])
        self.assertEqual(_module_names_for_file("foo.py"), ["foo"])
        self.assertEqual(_module_names_for_file(""), [])

    def test_fixed_files_extraction(self):
        rows = [
            {"item_id": "a", "status": "fixed", "file": "core/a.py"},
            {"item_id": "b", "status": "skipped", "file": "core/b.py"},
            {"item_id": "c", "status": "fixed", "file": "core/a.py"},
            {"item_id": "d", "status": "fixed"},
        ]
        self.assertEqual(_fixed_files_from_rows(rows), ["core/a.py"])


# ── 3.3 {test_targets} 占位符替换 ─────────────────────────────────────


class TestTestTargetsPlaceholder(unittest.TestCase):
    def _spec(self, cmd):
        return RegressionSpec(cmd=cmd, output=".fenix/junit.xml", timeout_seconds=600)

    def test_str_form_shell_quoted(self):
        spec = self._spec("pytest {test_targets} -q --junit-xml out.xml")
        eff = _apply_test_targets(spec, ["tests/test a.py", "tests/test_b.py"])
        self.assertIsInstance(eff, RegressionSpec)
        self.assertEqual(
            eff.cmd,
            "pytest 'tests/test a.py' tests/test_b.py -q --junit-xml out.xml",
            "str 形态替换为空格连接 + shlex 引用包裹",
        )
        self.assertEqual(eff.output, spec.output, "其余字段继承（副本语义）")
        self.assertEqual(eff.timeout_seconds, spec.timeout_seconds)

    def test_list_form_element_expansion(self):
        spec = self._spec(["pytest", "{test_targets}", "-q", "--junit-xml", "out.xml"])
        eff = _apply_test_targets(spec, ["tests/test_a.py", "tests/test_b.py"])
        self.assertEqual(
            eff.cmd,
            ["pytest", "tests/test_a.py", "tests/test_b.py", "-q", "--junit-xml", "out.xml"],
            "list 形态元素级展开（argv 不经 shell，路径原样不引用）",
        )

    def test_list_form_embedded_element_raw_replacement(self):
        spec = self._spec(["pytest", "dir={test_targets}", "-q"])
        eff = _apply_test_targets(spec, ["tests/a.py", "tests/b.py"])
        self.assertEqual(eff.cmd, ["pytest", "dir=tests/a.py tests/b.py", "-q"])

    def test_no_placeholder_returns_same_spec(self):
        spec = self._spec("pytest tests/ -q")
        self.assertIs(_apply_test_targets(spec, ["tests/test_a.py"]), spec)
        self.assertIs(_apply_test_targets(spec, []), spec, "映射空集原样返回")

    def test_cmd_has_test_targets_two_states(self):
        self.assertTrue(_cmd_has_test_targets(self._spec("pytest {test_targets}")))
        self.assertTrue(_cmd_has_test_targets(self._spec(["pytest", "{test_targets}"])))
        self.assertFalse(_cmd_has_test_targets(self._spec("pytest tests/")))
        self.assertFalse(_cmd_has_test_targets(None))

    def test_env_export_dual_channel(self):
        """同值导出 FENIX_TEST_TARGETS（{port} 占位符先例双轨）。"""
        sentinel = os.environ.get(CODE_FIX_TEST_TARGETS_ENV)
        try:
            with _env_helper(["tests/a.py", "tests/b.py"]) as env_value:
                self.assertEqual(
                    env_value, "tests/a.py tests/b.py",
                    "窗口内环境变量与占位符替换同值",
                )
                self.assertEqual(
                    os.environ[CODE_FIX_TEST_TARGETS_ENV], "tests/a.py tests/b.py"
                )
            self.assertIsNone(os.environ.get(CODE_FIX_TEST_TARGETS_ENV), "窗口外还原")
        finally:
            if sentinel is not None:
                os.environ[CODE_FIX_TEST_TARGETS_ENV] = sentinel

    def test_env_export_restores_previous_value(self):
        os.environ[CODE_FIX_TEST_TARGETS_ENV] = "prev"
        try:
            with _env_helper(["tests/a.py"]):
                self.assertEqual(os.environ[CODE_FIX_TEST_TARGETS_ENV], "tests/a.py")
            self.assertEqual(
                os.environ[CODE_FIX_TEST_TARGETS_ENV], "prev", "还原先前值"
            )
        finally:
            os.environ.pop(CODE_FIX_TEST_TARGETS_ENV, None)


class _env_helper:
    """_with_test_targets_env 的上下文取值辅助（取窗口内环境值供断言）。"""

    def __init__(self, targets):
        from core.code_fix import _with_test_targets_env

        self._ctx = _with_test_targets_env(targets)

    def __enter__(self):
        self._ctx.__enter__()
        return os.environ.get(CODE_FIX_TEST_TARGETS_ENV)

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


# ── 3.4 批收尾回归分流（三分支回退 + 定向构造）───────────────────────


def _orchestrator(config_segment: dict):
    from core.code_fix import CodeFixOrchestrator

    logs: list = []
    orch = CodeFixOrchestrator(
        agent_runner=None,
        project_root=_make_project_root(),
        config={"admin": {"code_review_fix": config_segment}},
        logger=None,
    )
    # 日志捕获（_log 经 logger 接口，替身收集留痕断言）
    orch._logger = SimpleNamespace(
        **{
            level: (lambda lv: lambda *a, **k: logs.append((lv, a[1] if len(a) > 1 else "")))(
                level
            )
            for level in ("info", "warning", "error")
        }
    )
    orch._logs = logs
    return orch


class TestBatchRegressionBranching(unittest.TestCase):
    def setUp(self):
        self.wt = Path(_mkdtemp("affinity-wt-"))
        (self.wt / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        (self.wt / "core").mkdir()
        (self.wt / "core" / "foo.py").write_text("X = 1\n", encoding="utf-8")
        (self.wt / "tests").mkdir()
        (self.wt / "tests" / "test_foo.py").write_text(
            "import core.foo\n\n\ndef test_x():\n    assert core.foo.X == 1\n",
            encoding="utf-8",
        )
        (self.wt / ".fenix" / "code-review" / "fix-out-run-1.jsonl").write_text(
            json.dumps({"item_id": "a", "status": "fixed", "file": "core/foo.py"})
            + "\n",
            encoding="utf-8",
        )
        self.spec = self._spec("pytest {test_targets} -q --junit-xml out.xml")

    def tearDown(self):
        shutil.rmtree(self.wt, ignore_errors=True)

    @staticmethod
    def _spec(cmd):
        return RegressionSpec(cmd=cmd, output=".fenix/junit.xml", timeout_seconds=600)

    def test_last_batch_always_full_regression(self):
        """Scenario 链末批恒全量：无论开关/占位符，末批 spec 原样。"""
        orch = _orchestrator({"enabled": True, "targeted_regression": True})
        eff, targeted, targets = orch._resolve_batch_regression_spec(
            self.spec, self.wt, "run-1", batch_no=1, is_last_batch=True
        )
        self.assertIs(eff, self.spec)
        self.assertFalse(targeted)
        self.assertEqual(targets, [])

    def test_non_last_batch_targeted(self):
        """Scenario 非末批定向回归生效：占位符被映射结果替换。"""
        orch = _orchestrator({"enabled": True, "targeted_regression": True})
        eff, targeted, targets = orch._resolve_batch_regression_spec(
            self.spec, self.wt, "run-1", batch_no=1, is_last_batch=False
        )
        self.assertTrue(targeted)
        self.assertEqual(targets, ["tests/test_foo.py"])
        self.assertEqual(
            eff.cmd, "pytest tests/test_foo.py -q --junit-xml out.xml",
            "定向 spec 为替换后的副本（不跑全量测试集）",
        )
        self.assertIsNot(eff, self.spec, "既有契约对象不被原地改写")

    def test_fallback_no_placeholder(self):
        """Scenario cmd 无占位符回退全量（向后兼容零迁移）。"""
        orch = _orchestrator({"enabled": True, "targeted_regression": True})
        spec = self._spec("pytest tests/ -q")
        eff, targeted, targets = orch._resolve_batch_regression_spec(
            spec, self.wt, "run-1", batch_no=1, is_last_batch=False
        )
        self.assertIs(eff, spec)
        self.assertFalse(targeted)
        self.assertTrue(any("占位符" in msg for _, msg in orch._logs), "回退记日志留痕")

    def test_fallback_empty_mapping(self):
        """Scenario 映射空集回退全量（fail-open 防漏检）。"""
        orch = _orchestrator({"enabled": True, "targeted_regression": True})
        # 产物行 fixed 指向无测试对应的文件 → 映射空集
        (self.wt / ".fenix" / "code-review" / "fix-out-run-1.jsonl").write_text(
            json.dumps({"item_id": "a", "status": "fixed", "file": "core/orphan.py"})
            + "\n",
            encoding="utf-8",
        )
        eff, targeted, targets = orch._resolve_batch_regression_spec(
            self.spec, self.wt, "run-1", batch_no=1, is_last_batch=False
        )
        self.assertIs(eff, self.spec)
        self.assertFalse(targeted)
        self.assertEqual(targets, [])
        self.assertTrue(any("映射空集" in msg for _, msg in orch._logs))

    def test_fallback_config_off(self):
        """Scenario 配置关闭回退全量：targeted_regression=false 等价现状。"""
        orch = _orchestrator({"enabled": True, "targeted_regression": False})
        eff, targeted, targets = orch._resolve_batch_regression_spec(
            self.spec, self.wt, "run-1", batch_no=1, is_last_batch=False
        )
        self.assertIs(eff, self.spec)
        self.assertFalse(targeted)
        self.assertEqual(targets, [])

    def test_targeted_failure_goes_into_existing_retry_path(self):
        """定向失败进既有失败路径：分流仅替换首轮 spec，重试轮沿用原
        reg_spec + subset_nodeids（零新增处置分支的结构性保证——分流点在
        定向重试块之前，失败汇入同一 reg 对象）。"""
        import inspect

        from core.code_fix import CodeFixOrchestrator

        src = inspect.getsource(CodeFixOrchestrator._run_batch_created)
        self.assertIn("with _with_test_targets_env(targets):", src)
        self.assertIn("reg = runner.run_regression(\n                eff_spec", src)
        # 重试轮回归调用仍传原 reg_spec（定向重试机制以 subset_nodeids 缩面）
        self.assertIn("runner.run_regression(\n                    reg_spec", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
