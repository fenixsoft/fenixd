"""test_code_fix.py — 自动修复车道（add-code-review-auto-fix）核心逻辑测试

覆盖：
- 1.3: get_code_review_fix_config 缺省/非法值回退矩阵；code-fix 在
  KNOWN_AGENT_TYPES 中。
- 4.2: mark_resolved 命中/不误伤/空列表/并发写。
- 5.9: 编排核心（守卫矩阵、select_batch、进度读写、activation_id、接线）。
- 6.5: run_code_fix 产物硬门、out 解析、run_id 撞名退避、模型链、门面注册。
- 7.4: 激活接线。
- 8.4: 进度 API。
- 10.4: 配置读写。

MUST NOT 真跑 agent——全部用 fake runner / 临时目录。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# /tmp 可能被外部清扫进程周期性清空（2026-09-19 实测）。统一用仓库内
# .history/tmp（gitignored），MUST NOT 改写全局 tempfile.tempdir。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


def _make_project_root() -> Path:
    """建一个带 .fenix/code-review 目录的临时项目根。"""
    td = Path(_mkdtemp("cfix-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_items(project_root, records):
    """按 item_id 排序写 items.jsonl（对齐 core.code_review 的落盘形态）。"""
    path = Path(project_root) / ".fenix" / "code-review" / "items.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
    )
    path.write_text(content, encoding="utf-8")


def _item(item_id, status="open", first_seen_at=None, **extra):
    rec = {"item_id": item_id, "status": status, "file": f"core/{item_id}.py",
           "line": 1, "severity": "major", "category": "correctness",
           "title": f"title {item_id}", "description": f"desc {item_id}",
           "suggestion": f"sug {item_id}", "fingerprint": f"fp-{item_id}"}
    if first_seen_at is not None:
        rec["first_seen_at"] = first_seen_at
    rec.update(extra)
    return rec


# ── 1.3 配置回退矩阵 ───────────────────────────────────────────────


class TestCodeReviewFixConfig(unittest.TestCase):
    def test_defaults_when_section_missing(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_fix_config({})
        self.assertEqual(cfg, {"enabled": False, "batch_size": 20})
        cfg2 = ConfigLoader.get_code_review_fix_config({"admin": {}})
        self.assertEqual(cfg2, {"enabled": False, "batch_size": 20})
        # 段非 dict 视为缺省
        cfg3 = ConfigLoader.get_code_review_fix_config({"admin": {"code_review_fix": "x"}})
        self.assertEqual(cfg3, {"enabled": False, "batch_size": 20})

    def test_invalid_batch_size_falls_back(self):
        from core.config import ConfigLoader

        for bad in (0, -3, True, "20", 20.5, None):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"enabled": True, "batch_size": bad}}}
            )
            self.assertEqual(cfg["batch_size"], 20, f"batch_size={bad!r} 应回退 20")
            self.assertTrue(cfg["enabled"])

    def test_invalid_enabled_falls_back(self):
        from core.config import ConfigLoader

        for bad in ("true", 1, 0, [], {}):
            cfg = ConfigLoader.get_code_review_fix_config(
                {"admin": {"code_review_fix": {"enabled": bad}}}
            )
            self.assertFalse(cfg["enabled"], f"enabled={bad!r} 应回退 False")

    def test_valid_values_kept(self):
        from core.config import ConfigLoader

        cfg = ConfigLoader.get_code_review_fix_config(
            {"admin": {"code_review_fix": {"enabled": True, "batch_size": 30}}}
        )
        self.assertEqual(cfg, {"enabled": True, "batch_size": 30})

    def test_code_fix_in_known_agent_types(self):
        from core.config import ConfigLoader

        self.assertIn("code-fix", ConfigLoader.KNOWN_AGENT_TYPES)
        # 与 code-review 同处登记（紧邻既有 code-review）
        self.assertIn("code-review", ConfigLoader.KNOWN_AGENT_TYPES)


# ── 2.6/2.7 code-fix agent 注册与提示词 ────────────────────────────


class _FakeLogger:
    def __getattr__(self, name):
        return lambda *a, **k: None


def _make_runner(project_root):
    """构造最小 AgentRunner（__new__ 绕过 __init__，对齐 test_agent_runner.make_runner）。"""
    from core.agent_runner import runner as runner_mod

    r = runner_mod.AgentRunner.__new__(runner_mod.AgentRunner)
    r.config = {}
    r.worktree_manager = None
    r.state_machine = None
    r.project_root = Path(project_root)
    r.logger = _FakeLogger()
    r._running_agents = {}
    return r


class TestCodeFixAgentRegistration(unittest.TestCase):
    def test_infer_run_agent_type(self):
        from core.agent_runner.run_files import infer_run_agent_type

        self.assertEqual(infer_run_agent_type("code-fix-123"), ("code-fix", "123"))
        # code-review- 不错配 code-fix（前缀无子串冲突）
        self.assertEqual(infer_run_agent_type("code-review-100"), ("code-review", "100"))
        self.assertEqual(infer_run_agent_type("code-fix-100"), ("code-fix", "100"))

    def test_agent_prompt_files_contains_mapping(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_FILES

        self.assertIn("code-fix", AGENT_PROMPT_FILES)
        self.assertEqual(AGENT_PROMPT_FILES["code-fix"], "code-fix.md")
        # 框架根 agents/code-fix.md 存在
        from pathlib import Path
        agents_dir = Path(__file__).resolve().parent.parent / "agents"
        self.assertTrue((agents_dir / "code-fix.md").is_file())

    def test_build_prompt_fills_items_outpath(self):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES
        from core.agent_runner.run_files import infer_run_agent_type

        proot = _make_project_root()
        runner = _make_runner(proot)
        detail = {
            "items": [
                {
                    "item_id": "item-1",
                    "file": "core/a.py",
                    "line": 3,
                    "severity": "major",
                    "category": "correctness",
                    "title": "t",
                    "description": "d",
                    "suggestion": "s",
                }
            ],
            "out_path": str(proot / ".fenix" / "code-review" / "fix-out-abc.jsonl"),
            "worktree": str(proot),
        }
        prompt = runner._build_prompt("runner", "code-fix", detail)
        self.assertIn("item-1", prompt)
        self.assertIn("core/a.py", prompt)
        self.assertIn(str(proot / ".fenix" / "code-review" / "fix-out-abc.jsonl"), prompt)

    def test_build_prompt_items_field_whitelist(self):
        """items 注入按白名单序列化：台账原始行的框架字段不得外泄（09-23 提速）。"""
        proot = _make_project_root()
        runner = _make_runner(proot)
        detail = {
            "items": [
                {
                    "item_id": "item-1",
                    "file": "core/a.py",
                    "line": 3,
                    "severity": "major",
                    "category": "correctness",
                    "title": "t",
                    "description": "d",
                    "suggestion": "s",
                    # 台账原始行附带的框架字段——MUST NOT 注入 prompt
                    "project": "fenixd",
                    "review_id": "impl-ocr-noise-1",
                    "review_kind": "impl-ocr",
                    "reviewed_at": "2026-09-23T00:00:00+00:00",
                    "spec": "",
                    "status": "open",
                    "spec_name": "add-noise-spec",
                    "fingerprint": "fp-noise-1",
                }
            ],
            "out_path": str(proot / ".fenix" / "code-review" / "fix-out-abc.jsonl"),
            "worktree": str(proot),
        }
        prompt = runner._build_prompt("runner", "code-fix", detail)
        # 白名单字段在场
        for keep in ('"item_id"', '"file"', '"severity"', '"category"',
                     '"title"', '"description"', '"suggestion"'):
            self.assertIn(keep, prompt)
        # 框架噪音字段（键与值）均不在场
        for noise_key in ('"project"', '"review_id"', '"review_kind"',
                          '"reviewed_at"', '"spec_name"', '"fingerprint"'):
            self.assertNotIn(noise_key + ":", prompt)
        for noise_val in ("impl-ocr-noise-1", "add-noise-spec", "fp-noise-1"):
            self.assertNotIn(noise_val, prompt)

    def test_build_prompt_no_detail_no_crash(self):
        """_build_prompt("code-fix") 无 detail 时不得抛异常（test_agent_prompt_files 参数化）。"""
        proot = _make_project_root()
        runner = _make_runner(proot)
        prompt = runner._build_prompt("runner", "code-fix")
        # 占位符被缺省回退填充，无残留大括号占位符
        for token in ("{items}", "{out_path}", "{worktree}"):
            self.assertNotIn(token, prompt)
        self.assertIn(str(proot / ".fenix" / "code-review"), prompt)

    def test_template_first_line_fillable(self):
        """模板首行 MUST 可被 _fill_placeholders 处理（test_agent_prompt_files 断言）。"""
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES

        proot = _make_project_root()
        runner = _make_runner(proot)
        template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["code-fix"]).read_text(
            encoding="utf-8")
        first = template.splitlines()[0]
        filled = runner._prompt_builder._fill_placeholders(first, "code-fix", "demo", None)
        self.assertTrue(filled.startswith(first.replace("{spec_name}", "demo")))


class TestCodeFixParallelPrompt(unittest.TestCase):
    """并行处置段提示词回归（add-codefix-batch-parallel task 3.1）。

    只做内容断言（agents/code-fix.md 每次派发现读、合回即生效）——
    MUST NOT 真跑 agent（本文件头铁律）。
    """

    @classmethod
    def setUpClass(cls):
        from core.agent_runner.prompt_builder import AGENT_PROMPT_DIR, AGENT_PROMPT_FILES

        cls.template = (AGENT_PROMPT_DIR / AGENT_PROMPT_FILES["code-fix"]).read_text(
            encoding="utf-8")

    def test_parallel_section_key_constraints_present(self):
        t = self.template
        # 触发条件：组数 ≥2 且总条目 >2 才并行（D7 单组/小批退化为串行）
        self.assertIn("组数 ≥2", t)
        self.assertIn("总条目 >2", t)
        # 并发上限 3（固定常量写进提示词，不设配置键——design D3）
        self.assertIn("≤3", t)
        # 波次语义：完成一组（落盘后）即补派下一组
        self.assertIn("补派", t)
        # 单写者（D4）：{out_path} 唯一写者是 orchestrator，逐组立即落盘、禁攒批
        self.assertIn("唯一写者", t)
        self.assertIn("MUST NOT 攒到全部组完成才写", t)
        # 组 prompt 修复契约下发：fenix-ignore 标记规则逐字下发、out 行格式
        self.assertIn("逐字下发", t)
        # 子代理边界：禁自行写 out_path / 自行验证 / 自行提交（D6）
        self.assertIn("MUST NOT 自行写 `{out_path}`", t)
        self.assertIn("MUST NOT 自行验证", t)
        self.assertIn("MUST NOT 自行提交", t)
        # 失败兜底三级（D5）：亲自重做 → skipped 语义 → 非法行重试一次不写非法行
        self.assertIn("亲自串行重做", t)
        self.assertIn("重试一次", t)
        self.assertIn("MUST NOT 把非法行写入", t)
        # 单组兜底不阻塞其他组的落盘与补派
        self.assertIn("MUST NOT 阻塞其他组", t)
        # 验证/提交契约（add-codefix-commit-first-contract：边修复边提交、
        # 收尾一次验证、验证不阻塞 commit；旧「单次提交/MUST NOT 多次提交」
        # 口径已废）
        self.assertIn("MUST NOT 逐组验证", t)
        self.assertIn("逐条修复即 commit", t)
        self.assertIn("验证不阻塞 commit", t)
        self.assertIn("收尾工作区干净", t)
        self.assertNotIn("MUST NOT 多次提交", t)

    def test_serial_path_wording_preserved(self):
        """串行路径（退化批）行为描述保留：逐组 append 落盘规则不被并行段覆盖。"""
        t = self.template
        self.assertIn("串行路径", t)
        self.assertIn("append", t)
        self.assertIn("MUST NOT 每条单独一次写入", t)

    def test_placeholders_intact(self):
        """新增段不得破坏占位符完整性：{items}/{out_path}/{worktree} 均在场。"""
        for token in ("{items}", "{out_path}", "{worktree}"):
            self.assertIn(token, self.template)

    def test_built_prompt_keeps_parallel_section_and_fills_placeholders(self):
        """多组批 detail 构建：并行段在场、三个占位符全部被填充无残留。"""
        proot = _make_project_root()
        runner = _make_runner(proot)
        # 6 条 × 3 文件 = 3 组（满足并行触发条件的批形态）
        detail = {
            "items": [
                {"item_id": f"item-{i}", "file": f"core/m{i % 3}.py", "line": 1,
                 "severity": "major", "category": "correctness",
                 "title": f"t{i}", "description": f"d{i}", "suggestion": f"s{i}"}
                for i in range(1, 7)
            ],
            "out_path": str(proot / ".fenix" / "code-review" / "fix-out-par.jsonl"),
            "worktree": str(proot),
        }
        prompt = runner._build_prompt("runner", "code-fix", detail)
        self.assertIn("并行处置", prompt)
        self.assertIn("≤3", prompt)
        for token in ("{items}", "{out_path}", "{worktree}"):
            self.assertNotIn(token, prompt)
        self.assertIn("item-6", prompt)


if __name__ == "__main__":
    unittest.main()


# ── 3.3 回归锁根参数 ────────────────────────────────────────────────


class TestRegressionLockRoot(unittest.TestCase):
    def _spec(self):
        from core.verify_contract import RegressionSpec

        return RegressionSpec(cmd="true", output=".fenix/regression/junit.xml")

    def test_suite_lock_default_root(self):
        from core.regression import _LOCK_FILE_REL, _SuiteLock

        proot = _make_project_root()
        lock = _SuiteLock(proot)
        self.assertEqual(
            lock._lock_path, Path(proot) / _LOCK_FILE_REL
        )

    def test_run_regression_lock_root_anchors_lock_file(self):
        """lock_root=<main> 时锁文件在 main/.fenix/full-suite.lock，cwd 仍为 project_root。"""
        import core.regression as reg

        wt = _make_project_root()   # 执行根（worktree 模拟）
        main = _make_project_root()  # 锁根（主树模拟）
        result = reg.run_regression(wt, self._spec(), lock_root=main)
        # cmd=true 不产出 JUnit XML → parse_error/failed 均可，但锁一定在 main
        self.assertIn(result.get("status"), ("parse_error", "failed", "passed", "timeout"))
        self.assertTrue((main / ".fenix" / "full-suite.lock").exists(),
                        "锁文件 MUST 落在 lock_root")
        self.assertFalse((wt / ".fenix" / "full-suite.lock").exists(),
                         "锁文件 MUST NOT 落在执行根（worktree）")

    def test_run_regression_default_lock_root_unchanged(self):
        """缺省 lock_root=None 时锁路径与改动前一致（project_root 下）。"""
        import core.regression as reg

        proot = _make_project_root()
        reg.run_regression(proot, self._spec())
        self.assertTrue((proot / ".fenix" / "full-suite.lock").exists())

    def test_facade_passes_project_root_and_lock_root(self):
        """门面两参数透传到 run_and_write_regression（monkeypatch 捕获）。"""
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        wt = _make_project_root()
        runner = _make_runner(proot)
        captured = {}

        def fake_raw(exec_root, spec, logger=None, lock_root=None):
            captured["exec_root"] = exec_root
            captured["lock_root"] = lock_root
            return {"status": "passed", "total": 1, "duration_seconds": 0}

        with mock.patch("core.regression.run_and_write_regression", fake_raw):
            mr.run_regression(runner, self._spec(), project_root=wt, lock_root=proot)
        self.assertEqual(captured["exec_root"], wt)
        self.assertEqual(captured["lock_root"], proot)

    def test_facade_defaults_fall_back(self):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        runner = _make_runner(proot)
        captured = {}

        def fake_raw(exec_root, spec, logger=None, lock_root=None):
            captured["exec_root"] = exec_root
            captured["lock_root"] = lock_root
            return {"status": "passed"}

        with mock.patch("core.regression.run_and_write_regression", fake_raw):
            mr.run_regression(runner, self._spec())
        self.assertEqual(captured["exec_root"], proot)  # 回落 runner.project_root
        self.assertIsNone(captured["lock_root"])  # 回落 None（→ run_regression 内回落 project_root）


# ── 4.2 mark_resolved 台账核销 ───────────────────────────────────────


class TestMarkResolved(unittest.TestCase):
    def test_marks_multiple_and_skips_missing(self):
        from core.code_review import mark_resolved, read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "b": _item("b"),
            "c": _item("c"),
        })
        hit = mark_resolved(proot, ["a", "c", "missing-id"])
        self.assertEqual(hit, 2)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["c"]["status"], "resolved")
        self.assertEqual(items["b"]["status"], "open")  # 未命中不误伤

    def test_empty_list_safe(self):
        from core.code_review import mark_resolved

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self.assertEqual(mark_resolved(proot, []), 0)
        self.assertEqual(mark_resolved(proot, ["a", "a"]), 1)  # 幂等：重复 id 只命中一次

    def test_concurrent_writes_do_not_lose_records(self):
        """并发 mark_resolved 不丢条目（复用台账并发测试形态：flock + 原子替换）。"""
        from core.code_review import mark_resolved, read_items

        proot = _make_project_root()
        records = {f"i{n}": _item(f"i{n}") for n in range(20)}
        _write_items(proot, records)
        groups = [[f"i{n}" for n in range(k, 20, 4)] for k in range(4)]
        threads = [
            threading.Thread(target=mark_resolved, args=(proot, g)) for g in groups
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        items = read_items(proot)
        self.assertEqual(len(items), 20, "并发写不得丢条目")
        self.assertTrue(all(r["status"] == "resolved" for r in items.values()))


class TestMarkIgnored(unittest.TestCase):
    """LLM 拒绝出口（2026-09-23）：code-fix 车道把误报/不值得修条目置 ignored。"""

    def test_marks_open_only_and_records_reason(self):
        from core.code_review import mark_ignored, read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a"),
            "b": _item("b", status="in_spec"),   # 已立项：MUST NOT 被车道降级
            "c": _item("c", status="resolved"),  # 已核销：MUST NOT 被覆盖
            "d": _item("d"),
        })
        hit = mark_ignored(
            proot, ["a", "b", "c", "missing-id"],
            reasons={"a": "false_positive", "b": "not_worth_fixing"},
        )
        self.assertEqual(hit, 1)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored")
        self.assertEqual(items["a"]["ignored_by"], "code-fix-agent")
        self.assertEqual(items["a"]["ignored_reason"], "false_positive")
        self.assertIn("ignored_at", items["a"])
        self.assertEqual(items["b"]["status"], "in_spec")   # 未误伤
        self.assertEqual(items["c"]["status"], "resolved")  # 未误伤
        self.assertEqual(items["d"]["status"], "open")      # 未命中不误伤

    def test_reason_missing_records_empty(self):
        from core.code_review import mark_ignored, read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        self.assertEqual(mark_ignored(proot, ["a", "a"]), 1)  # 重复 id 只命中一次
        self.assertEqual(read_items(proot)["a"]["ignored_reason"], "")


class TestSplitFixRows(unittest.TestCase):
    """批收尾产物行分区（LLM 拒绝出口）：fixed 与可忽略 skipped 的划分口径。"""

    def test_partitions_fixed_and_ignorable_skipped(self):
        from core.code_fix import _split_fix_rows

        rows = [
            {"item_id": "a", "status": "fixed", "file": "x.py"},
            {"item_id": "b", "status": "skipped", "skip_reason": "false_positive", "file": "x.py"},
            {"item_id": "c", "status": "skipped", "skip_reason": "not_worth_fixing", "file": "x.py"},
            {"item_id": "d", "status": "skipped", "skip_reason": "unfixable", "file": "x.py"},
            {"item_id": "e", "status": "skipped", "file": "x.py"},  # 无标注：缺省保守不降级
            {"item_id": "f", "status": "skipped", "skip_reason": "needs_human", "file": "x.py"},
        ]
        fixed_ids, skip_reasons = _split_fix_rows(rows)
        self.assertEqual(fixed_ids, ["a"])
        self.assertEqual(skip_reasons, {"b": "false_positive", "c": "not_worth_fixing"})

    def test_retry_fixed_wins_over_earlier_skip(self):
        # 并集口径：首轮 skipped 判误报、重试轮 fixed → 以 fixed 为准，不降级
        from core.code_fix import _split_fix_rows

        rows = [
            {"item_id": "a", "status": "skipped", "skip_reason": "false_positive", "file": "x.py"},
            {"item_id": "a", "status": "fixed", "file": "x.py"},
            {"item_id": "b", "status": "skipped", "skip_reason": "unfixable", "file": "x.py"},
            {"item_id": "b", "status": "skipped", "skip_reason": "false_positive", "file": "x.py"},
        ]
        fixed_ids, skip_reasons = _split_fix_rows(rows)
        self.assertEqual(fixed_ids, ["a"])
        self.assertEqual(skip_reasons, {"b": "false_positive"})  # 后行覆盖：重试轮判定更新


# ── 5.1/5.2/5.9 编排核心：进度、选批、守卫矩阵 ────────────────────────


class TestProgressIO(unittest.TestCase):
    def test_progress_default_contains_chain_skipped(self):
        """chain_skipped 进 FIX_PROGRESS_DEFAULT（selfheal 1.4）：读侧缺文件/缺字段补齐 []。"""
        from core.code_fix import FIX_PROGRESS_DEFAULT, read_progress, write_progress

        proot = _make_project_root()
        self.assertIn("chain_skipped", FIX_PROGRESS_DEFAULT)
        self.assertEqual(read_progress(proot)["chain_skipped"], [])
        # 合并写：未传字段保留现值
        write_progress(proot, chain_skipped=["a"])
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a"])

    def test_read_progress_missing_returns_default(self):
        from core.code_fix import FIX_PROGRESS_DEFAULT, read_progress

        proot = _make_project_root()
        self.assertEqual(read_progress(proot), FIX_PROGRESS_DEFAULT)

    def test_read_progress_corrupt_returns_default(self):
        from core.code_fix import read_progress

        proot = _make_project_root()
        (proot / ".fenix" / "code-review" / "fix-progress.json").write_text(
            "{not json", encoding="utf-8")
        self.assertEqual(read_progress(proot)["phase"], "idle")

    def test_write_progress_atomic_merge(self):
        from core.code_fix import read_progress, write_progress

        proot = _make_project_root()
        write_progress(proot, running=True, phase="fixing", total=10, done=3,
                       activation_id="act-1")
        write_progress(proot, done=5)  # 未传字段保留
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 5)
        self.assertEqual(prog["total"], 10)
        self.assertEqual(prog["phase"], "fixing")
        self.assertEqual(prog["activation_id"], "act-1")


class TestSelectBatch(unittest.TestCase):
    def test_orders_by_first_seen_at_and_caps_batch_size(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "old": _item("old", first_seen_at="2026-01-01T00:00:00Z"),
            "mid": _item("mid", first_seen_at="2026-02-01T00:00:00Z"),
            "new": _item("new", first_seen_at="2026-03-01T00:00:00Z"),
            "resolved": _item("resolved", status="resolved"),
            "ignored": _item("ignored", status="ignored"),
        })
        batch = select_batch(proot, 2)
        self.assertEqual([r["item_id"] for r in batch], ["old", "mid"])

    def test_missing_first_seen_falls_back_to_item_id(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {"b": _item("b"), "a": _item("a")})
        batch = select_batch(proot, 10)
        self.assertEqual([r["item_id"] for r in batch], ["a", "b"])

    def test_excludes_failed_batch_items(self):
        from core.code_fix import record_failed_batch, select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        record_failed_batch(proot, ["a"], "/tmp/wt-kept")
        batch = select_batch(proot, 10)
        self.assertEqual([r["item_id"] for r in batch], ["b"])

    def test_release_failed_batch_restores_selection(self):
        from core.code_fix import record_failed_batch, release_failed_batch, select_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        record_failed_batch(proot, ["a"], "/tmp/wt-kept")
        self.assertEqual(select_batch(proot, 10), [])
        released = release_failed_batch(proot, ["a"])
        self.assertEqual(released, 1)
        self.assertEqual([r["item_id"] for r in select_batch(proot, 10)], ["a"])

    def test_exclude_ids_extends_exclusion(self):
        """exclude_ids（chain_skipped）与失败档案并集构成排除口径（selfheal 1.4）。"""
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
        })
        batch = select_batch(proot, 10, exclude_ids=["a", "b"])
        self.assertEqual([r["item_id"] for r in batch], ["c"])
        # 缺省 None 向后兼容：不引入额外排除
        self.assertEqual(len(select_batch(proot, 10)), 3)

    def test_corrupt_failed_file_treated_as_empty(self):
        from core.code_fix import select_batch

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        (proot / ".fenix" / "code-review" / "fix-failed.json").write_text(
            "garbage", encoding="utf-8")
        self.assertEqual(len(select_batch(proot, 10)), 1)


def _make_git_repo() -> Path:
    """构造带一个初始提交的临时 git 仓（模拟 worktree）。"""
    repo = Path(_mkdtemp("cfix-wt-"))
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("init", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
        cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo, check=True, capture_output=True)
    return repo


class _FakeWM:
    """fake worktree_manager：create/merge_back/cleanup 记录调用。

    ``enforce_lock=True`` 时模拟真实 worktree_manager 的进程内 spec 锁语义：
    存在未 cleanup 的 active worktree 时 ``create()`` 返回 None（「Worktree
    already active」锁拒绝）；``cleanup()`` 释放锁并删除 worktree 目录
    （现场即弃的锁/目录级断言用，add-code-fix-batch-failure-selfheal 3.2）。
    """

    def __init__(self, create_result="git", enforce_lock=False):
        self.create_calls = []
        self.merge_calls = []
        self.cleanup_calls = []
        self._create_result = create_result  # "git" | None
        self._enforce_lock = enforce_lock
        self._active = set()  # str(wt_path)：模拟 code-review-fix:code-fix spec 锁

    def create(self, spec_name, agent_type="implementer"):
        self.create_calls.append((spec_name, agent_type))
        if self._enforce_lock and self._active:
            return None  # 模拟锁拒绝
        if self._create_result is None:
            return None
        repo = _make_git_repo()
        if self._enforce_lock:
            self._active.add(str(repo))
        return repo

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        import types as _t
        return _t.SimpleNamespace(success=True, error="")

    def release_spec_lock(self, spec_name, agent_type="implementer"):
        """模拟真实 release_spec_lock（defer 放锁）：仅摘锁，不动目录/活动集。"""
        self._active.clear()
        return True

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))
        self._active.discard(str(wt_path))
        # 模拟真实 cleanup：worktree 目录被删除
        shutil.rmtree(str(wt_path), ignore_errors=True)


class _FakeRunner:
    """fake AgentRunner：记录 run_code_fix / run_regression 调用。"""

    def __init__(self, project_root, fix_statuses=None, regression_statuses=None,
                 create_result="git"):
        self.project_root = Path(project_root)
        self.logger = _FakeLogger()
        self._running_agents = {}
        self.worktree_manager = _FakeWM(create_result)
        self.config = {}
        self.fix_calls = []          # (worktree, n_items, failure_summary)
        self.regression_calls = []   # (project_root, lock_root)
        self.fix_statuses = fix_statuses  # 每 run 的行状态列表列表，如 [["fixed"],["fixed"]]
        self.regression_statuses = regression_statuses or ["passed"]
        self._run_no = 0

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-fake-{self._run_no}"
        self.fix_calls.append((str(worktree_root), len(items), failure_summary))
        statuses = None
        if self.fix_statuses is not None:
            statuses = self.fix_statuses[(self._run_no - 1) % len(self.fix_statuses)] \
                if self._run_no - 1 < len(self.fix_statuses) else self.fix_statuses[-1]
        rows = []
        for idx, it in enumerate(items):
            status = (statuses[idx % len(statuses)] if statuses else "fixed")
            rows.append({"item_id": it["item_id"], "status": status,
                         "file": it.get("file", "")})
        out = Path(worktree_root) / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        # 模拟 agent 提交（零有效修复守卫的 git 侧判据）
        if any(r["status"] == "fixed" for r in rows):
            (Path(worktree_root) / f"touched-{rid}.txt").write_text("fix", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"],
                cwd=worktree_root, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
                 "-m", f"fix-{rid}"],
                cwd=worktree_root, check=True, capture_output=True)
        import types as _t
        fixed = sum(1 for r in rows if r["status"] == "fixed")
        skipped = sum(1 for r in rows if r["status"] == "skipped")
        return _t.SimpleNamespace(run_id=rid, success=True, fixed=fixed,
                                  skipped=skipped, error="", output="done")

    def run_regression(self, spec, reason="manual", project_root=None, lock_root=None):
        self.regression_calls.append((str(project_root), str(lock_root)))
        status = self.regression_statuses[min(
            len(self.regression_calls) - 1, len(self.regression_statuses) - 1)]
        import types as _t
        return _t.SimpleNamespace(status=status, snapshot={"failures": [
            {"classname": "tests.test_x", "name": "test_a", "message": "boom"}]},
            error="")


def _write_verify_yaml(proot: Path, with_regression=True):
    body = (
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
    )
    if with_regression:
        body += (
            "regression:\n"
            "  cmd: \"true\"\n"
            "  output: \".fenix/regression/junit.xml\"\n"
        )
    (proot / ".fenix" / "verify.yaml").write_text(body, encoding="utf-8")


_CFG_ON = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}


class _RealCfgRunner(_FakeRunner):
    """对齐真实 AgentRunner 的配置读取：``config`` 为**根**形态，``_get_config``
    按嵌套键路径返回**子段**（真实 runner 即 `ConfigLoader.get(self.config, key)`）。
    """

    def _get_config(self, key, default=None):
        from core.config import ConfigLoader

        return ConfigLoader.get(self.config, key, default)


class TestOrchestratorDaemonConfigPath(unittest.TestCase):
    """daemon 装配形态（config=None）MUST 读到根 config 下的段（生产回归锁）。

    回归锁：`_get_config` 回落原先直接把 `runner._get_config("admin.code_review_fix")`
    的**子段**交给 `ConfigLoader.get_code_review_fix_config`，而该读取器的契约是
    **根 config**（内部 `config.get("admin")`）→ 子段里无 `admin` 键 → 判定段缺失
    → 恒返回缺省 `enabled=False`。fenixd.py 是唯一走 `config=None` 的调用点，故
    设置页开关打开后整条自动修复车道静默失效（两路激活都经 checkpoint）。
    既有测试均显式传根形态 config，覆盖不到这条 daemon 路径。
    """

    def test_daemon_enabled_reads_root_config(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 50}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        cfg = orch._get_config()
        self.assertTrue(cfg["enabled"],
                        "config=None（daemon）MUST 读根 config 下的段，"
                        "不得因子段/根形态错配恒判 disabled")
        self.assertEqual(cfg["batch_size"], 50)

    def test_daemon_disabled_reads_root_config(self):
        """反向锁：根 config 段关闭时 MUST 仍判 disabled（不得恒真/硬编码）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": False}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        self.assertFalse(orch._get_config()["enabled"])

    def test_daemon_checkpoint_no_longer_disabled(self):
        """端到端：daemon 形态 + 根 config 开启 → checkpoint MUST NOT 返回 disabled。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        runner = _RealCfgRunner(proot)
        runner.config = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 20}}}
        orch = CodeFixOrchestrator(runner, proot, config=None, logger=None)
        self.assertNotEqual(orch.checkpoint().get("reason"), "disabled")


class TestOrchestratorGuards(unittest.TestCase):
    def test_disabled_zero_action(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        self.assertEqual(runner.fix_calls, [])
        self.assertFalse((proot / ".fenix" / "code-review" / "fix-progress.json").exists(),
                         "开关关闭 MUST NOT 写进度")

    def test_already_running_in_flight_agent(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner._running_agents = {"code-fix-123": object()}
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "already_running"})

    def test_no_open_items(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "no_open_items"})
        self.assertEqual(runner.fix_calls, [])

    def test_regression_contract_missing_blocks_and_signals(self):
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.admin_store import AdminStore

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        # 不写 verify.yaml → 契约整体缺失
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "regression_contract_missing"})
        self.assertEqual(runner.fix_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "regression_contract_missing")
        store = AdminStore(proot, logger=None)
        types = [r.get("signal_type") for r in store.read_all()]
        self.assertIn("verify_contract_missing", types)

    def test_regression_section_missing_blocks_and_signals(self):
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.admin_store import AdminStore

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot, with_regression=False)  # 契约有效仅缺段
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "regression_section_missing"})
        self.assertEqual(runner.fix_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "regression_section_missing")
        store = AdminStore(proot, logger=None)
        types = [r.get("signal_type") for r in store.read_all()]
        self.assertIn("verify_regression_missing", types)
        self.assertNotIn("verify_contract_missing", types,
                         "MUST NOT 写 verify_contract_missing（会重写有效契约）")

    def test_normal_dispatch_full_chain(self):
        """正常链：分批 → 回归 → 合回 → 核销 → cleanup → 自驱动下一批 → 收尾。

        batch_size=2、3 条 open → 2 批；total 全程 3（不倒退）；done=3。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items
        from core.config import ConfigLoader

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 2}}}
        self.assertTrue(ConfigLoader.get_code_review_fix_config(cfg)["enabled"])
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        res = orch.checkpoint()  # 无 executor → 同步跑完整条链
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 2, "3 条 batch_size=2 → 2 批")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 2)
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 2)
        self.assertTrue(all(s for _, s in runner.worktree_manager.cleanup_calls),
                        "成功批 cleanup(success=True)")
        items = read_items(proot)
        self.assertTrue(all(r["status"] == "resolved" for r in items.values()),
                        f"全部核销: {[(k, v['status']) for k, v in items.items()]}")
        prog = read_progress(proot)
        self.assertEqual(prog["total"], 3)
        self.assertEqual(prog["done"], 3)
        self.assertEqual(prog["batch_no"], 2)
        self.assertFalse(prog["running"])
        # 回归调用：执行根=worktree、锁根=主树
        for exec_root, lock_root in runner.regression_calls:
            self.assertNotEqual(exec_root, str(proot), "执行根 MUST 为 worktree")
            self.assertEqual(lock_root, str(proot), "锁根 MUST 为主树")

    def test_activation_id_total_preserved_across_chain(self):
        """同链再投递不重置 total（D8：total 为激活链起点的 open 快照）。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {
            k: _item(k, first_seen_at=f"2026-0{i}-01T00:00:00Z")
            for i, k in enumerate(["a", "b", "c"], start=1)
        })
        _write_verify_yaml(proot)
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        orch.checkpoint()
        prog = read_progress(proot)
        self.assertEqual(prog["total"], 3, "链内 total 不随 open 缩小而重置")
        self.assertEqual(prog["done"], 3)
        self.assertEqual(prog["activation_id"], "see-above") if False else None
        self.assertTrue(prog["activation_id"], "链身份已持久化")

    def test_chain_total_grows_on_midchain_new_items(self):
        """链中途新审查新增 open 条目 → 分母随「done+open」活口径增长。

        用户事故（2026-09-25）：D8 链身份把 total 定格在链起点快照，链在飞
        期间新审查轮追加的问题会被本链继续处置，但分母不涨——done 追平定格
        total 后前端钳 100% 恒满，新增条目的进度不可见。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress, write_progress

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", status="resolved", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", status="resolved", first_seen_at="2026-02-01T00:00:00Z"),
            # c/d/e：链启动后新审查轮追加的 open 条目
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
            "d": _item("d", first_seen_at="2026-04-01T00:00:00Z"),
            "e": _item("e", first_seen_at="2026-05-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        # 链在飞快照：链起点 open 共 2 条且已核销（旧口径 total 定格为 2）
        write_progress(proot, running=True, phase="fixing", total=2, done=2,
                       batch_no=1, activation_id="act-mid")
        cfg = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=cfg, logger=None)
        orch.checkpoint()  # 同步跑完：c/d/e 三批全核销
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 5)
        # 旧口径：total 沿用定格的 2 → done(5) > total(2)，前端恒钳 100%
        self.assertEqual(
            prog["total"], 5, "链中途新增条目 MUST 推高分母（done+open 活口径）")

    def test_worktree_create_failed_no_dispatch(self):
        """create() 返回 None → 不派 run、不合回、进度 failed、条目保持 open。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, create_result=None)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(runner.fix_calls, [])
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "worktree_create_failed")
        self.assertEqual(read_items(proot)["a"]["status"], "open")

    def test_zero_effective_fix_rejects_merge(self):
        """产物行全 skipped → 不合回、不核销、条目入 chain_skipped（链继续收敛）。"""
        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)  # 有效 regression 段（零有效修复守卫在回归通过后判定）
        runner = _FakeRunner(proot, fix_statuses=[["skipped", "skipped"]])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [], "零有效修复 MUST NOT 合回")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "open")
        prog = read_progress(proot)
        # consumed（链内跳过）：不终止链，自驱动收敛到「选批为空」终态
        self.assertEqual(prog["chain_skipped"], ["a", "b"])
        self.assertEqual(load_failed_batches(proot), [],
                         "零有效修复 ≠ 确定性失败，MUST NOT 入失败档案")
        self.assertEqual(prog["phase"], "blocked")
        self.assertIn("下轮自动重试", prog["current"])

    def test_regression_failed_twice_discards_and_continues(self):
        """两次回归均失败 → 现场即弃（cleanup 释放现场）、branch/tip_sha 入档案、链继续。"""
        from core.admin_store import AdminStore

        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress, select_batch)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "failed"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        # 现场即弃（selfheal 1.2，替代原「MUST NOT cleanup 保留现场」语义）
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 1,
                         "失败批 MUST cleanup（现场即弃 + 释放 spec 锁）")
        self.assertFalse(runner.worktree_manager.cleanup_calls[0][1])
        self.assertEqual(len(runner.fix_calls), 2, "首次失败后重试一次")
        self.assertTrue(runner.fix_calls[1][2], "重试 prompt 注入失败用例摘要")
        items = read_items(proot)
        self.assertTrue(all(r["status"] == "open" for r in items.values()))
        # 失败档案：fail_count 预算 + branch/tip_sha/reason/failed_at 追溯字段
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a", "b"})
        self.assertEqual(failed[0]["reason"], "regression_failed_twice")
        self.assertTrue(failed[0]["branch"], "branch 追溯线索 MUST 在场")
        self.assertTrue(failed[0]["tip_sha"], "tip_sha 追溯线索 MUST 在场")
        self.assertTrue(failed[0]["failed_at"])
        self.assertEqual(failed[0]["fail_count"], 1)
        self.assertEqual(select_batch(proot, 10), [], "失败档案条目被跳过")
        # 告警去人工化措辞（selfheal 2.4）
        store = AdminStore(proot, logger=None)
        alerts = [r for r in store.read_all()
                  if r.get("signal_type") == "code_fix_regression_failed"]
        self.assertEqual(len(alerts), 1)
        self.assertIn("已跳过，下轮自动重试", alerts[0]["recommended_action"])
        self.assertNotIn("待人工", alerts[0]["description"])
        # 预算内（fail_count=1）入档不产生 todo 人工项（selfheal 2.1）
        todo_path = proot / ".fenix" / "todo.md"
        self.assertFalse(todo_path.exists(),
                         "预算内失败 MUST NOT 登记 todo 人工项（下轮自动重试）")
        # consumed 链收敛：选批为空终态文案按 D5 改写（不误报为故障）
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertIn("下轮自动重试", prog["current"])

    def test_regression_failed_twice_consumed_chain_continues(self):
        """回归两败批 consumed 后链自驱动推进下一批（selfheal 3.1）。"""
        from core.code_fix import CodeFixOrchestrator, load_failed_batches
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        # 批 a 两次回归失败（2 次 run + 2 次回归）→ consumed；批 b 正常成功
        runner = _FakeRunner(proot, regression_statuses=["failed", "failed", "passed"])
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}},
            logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 3,
                         "失败批 consumed 后 MUST 自驱动推进批 b（2+1 次 run）")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1, "仅批 b 合回")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open", "入档案条目保持 open")
        self.assertEqual(items["b"]["status"], "resolved", "后续批照常核销")
        self.assertEqual({tuple(sorted(r["item_ids"])) for r in load_failed_batches(proot)},
                         {("a",)})

    def test_regression_retry_then_pass_merges(self):
        """首次回归失败、重试后通过 → 正常合回核销。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "passed"])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        self.assertEqual(read_items(proot)["a"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 1)

    def test_retry_fixed_items_are_resolved_by_union(self):
        """重试轮各自 fixed 的条目按两轮产物**并集**核销（只读首次 run 会漏）。

        回归锁：ocr 审查发现——重试轮写独立的 ``fix-out-<retry_run_id>.jsonl``，
        仅读首次 run 的产物会把「重试才修复」的条目合回主树却仍留 open，
        下轮被反复重派。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        # 首次：a fixed / b skipped；重试：a skipped / b fixed
        runner = _FakeRunner(
            proot,
            fix_statuses=[["fixed", "skipped"], ["skipped", "fixed"]],
            regression_statuses=["failed", "passed"],
        )
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "首次回归失败后重试一次")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved")
        self.assertEqual(items["b"]["status"], "resolved",
                         "重试轮才修复的条目也必须核销（并集口径）")
        self.assertEqual(read_progress(proot)["done"], 2)

    def test_retry_run_failed_cleans_up_without_failed_set(self):
        """重试 run 失败（第二次回归未跑）→ 入 chain_skipped（不入档案），cleanup 释放锁，链继续。

        回归锁：ocr 审查发现——原实现把「重试 run 失败」记进
        ``fix-failed.json``（该文件语义是「两次回归均失败」）且不 cleanup，
        令 spec 锁永久占用（后续 create() 恒 None，车道首批后即死），
        同时把很可能是一次性失败的条目永久排除出选批。
        """
        from types import SimpleNamespace

        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, regression_statuses=["failed", "passed"])
        real_fix = runner.run_code_fix
        calls = {"n": 0}

        def flaky_fix(worktree_root, items, run_id=None, failure_summary=""):
            calls["n"] += 1
            if calls["n"] == 2:  # 批 a 的重试 run 直接失败（产物硬门）
                return SimpleNamespace(run_id="code-fix-retry", success=False,
                                       fixed=0, skipped=0, error="重试产物缺失",
                                       output="")
            return real_fix(worktree_root, items, run_id=run_id,
                            failure_summary=failure_summary)

        runner.run_code_fix = flaky_fix
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}},
            logger=None)
        orch.checkpoint()
        # 批 a：fix1 ok → reg failed → 重试 run 失败 → consumed（chain_skipped）
        # 批 b：链自驱动，正常合回核销
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1, "仅批 b 合回")
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 2,
                         "失败批与成功批均释放现场（spec 锁不残留）")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "resolved", "consumed 后链 MUST 继续推进")
        self.assertEqual(load_failed_batches(proot), [],
                         "run 失败 ≠ 两次回归均失败，MUST NOT 入失败档案")
        prog = read_progress(proot)
        self.assertEqual(prog["chain_skipped"], ["a"], "瞬态失败条目入链内跳过集")

    def test_agent_run_failed_cleans_up_and_retries_later(self):
        """run 失败（产物硬门）→ 不合回不核销，cleanup 释放锁，条目入 chain_skipped，链继续。"""
        from types import SimpleNamespace

        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)

        def failing_fix(worktree_root, items, run_id=None, failure_summary=""):
            return SimpleNamespace(run_id="code-fix-x", success=False, fixed=0,
                                   skipped=0, error="产物缺失", output="")

        runner.run_code_fix = failing_fix
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}},
            logger=None)
        orch.checkpoint()
        self.assertEqual(runner.worktree_manager.merge_calls, [])
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 2,
                         "agent 失败也要释放锁（两批各 cleanup 一次）")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "open")
        self.assertEqual(load_failed_batches(proot), [],
                         "瞬态 run 失败 MUST NOT 烧跨轮重试预算")
        prog = read_progress(proot)
        self.assertEqual(prog["chain_skipped"], ["a", "b"])
        self.assertIn("下轮自动重试", prog["current"])


class TestOverrideEnabled(unittest.TestCase):
    """checkpoint(override_enabled=True) 临时授权语义（add-code-fix-manual-trigger 1.2）。

    手动触发绕过总开关，但其余守卫（单飞 / 无 open 条目 / 失败保留 / 回归
    契约 fail-closed）原样生效；不传参的两路后台激活形态在 enabled=false
    下仍不投递（现状逐字节一致）。
    """

    def test_override_dispatches_when_disabled(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertTrue(res["triggered"], "开关关闭 + 手动临时授权 MUST 仍投递这一批")
        self.assertEqual(len(runner.fix_calls), 1)

    def test_override_still_respects_already_running(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner._running_agents = {"code-fix-123": object()}
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": False, "reason": "already_running"})
        self.assertEqual(runner.fix_calls, [])

    def test_override_still_respects_regression_contract_missing(self):
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        # 不写 verify.yaml → 回归契约整体缺失；fail-closed 不因手动触发放宽
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": False, "reason": "regression_contract_missing"})
        self.assertEqual(runner.fix_calls, [])

    def test_default_no_override_disabled_still_blocks(self):
        """两路后台激活形态（不传参）在 enabled=false 下仍不投递（现状不变）。"""
        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(runner, proot,
                                   config={"admin": {"code_review_fix": {"enabled": False}}},
                                   logger=None)
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        self.assertEqual(runner.fix_calls, [])
        self.assertFalse((proot / ".fenix" / "code-review" / "fix-progress.json").exists(),
                         "开关关闭（未授权）MUST NOT 写进度")


class TestManualAuthorizationChain(unittest.TestCase):
    """手动授权语义 = 授权**整条链**跑完，而非一批（2026-09-22 事故修复）。

    事故：enabled=false 下手动触发投出批 1，批 1 合回成功后 `_resubmit` 的
    checkpoint（不带 override）命中 disabled 守卫**静默早退**（不写进度）
    → fix-progress.json 永久冻结在 running=true/phase=merging，前端永远
    显示「合回主树中」。设计本意：手动授权覆盖整条链直至 open 条目清零。

    契约：
    - 授权旗标 ``manual_authorized`` 持久化在 fix-progress.json，随链身份
      传播（batch 间的 phase 改写不得丢失）；仅当链 live（running=true）
      时生效——收尾链的旗标不外溢到新链；
    - 终态（idle / blocked / failed）清除旗标；
    - live 链撞 disabled 守卫（开关被中途关闭）MUST 落终态进度，不得静默
      冻结在 running=true。
    """

    def test_manual_chain_runs_to_completion_while_disabled(self):
        """核心回归锁：enabled=false + 手动授权 → 链自驱动跑完全部 open 条目。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": False, "batch_size": 2}}},
            logger=None)
        res = orch.checkpoint(override_enabled=True)  # 同步模式：链内自驱动推进
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 2,
                         "3 条 batch_size=2 → 手动授权 MUST 自驱动跑满 2 批（非一批即停）")
        items = read_items(proot)
        self.assertTrue(all(r["status"] == "resolved" for r in items.values()),
                        f"全部核销: {[(k, v['status']) for k, v in items.items()]}")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 3)
        self.assertFalse(prog["running"], "链收尾（无 open 条目）MUST 落终态")
        self.assertFalse(prog.get("manual_authorized", True),
                         "链收尾 MUST 清除授权旗标")

    def test_manual_chain_continues_past_failed_batch(self):
        """链内批两次回归失败 → 现场即弃 + 链继续（selfheal 改写原「失败批终止链」语义），授权旗标随链延续、收敛终态清除。"""
        from core.code_fix import CodeFixOrchestrator, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
            "c": _item("c", first_seen_at="2026-03-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        # 批 a 两次回归失败（2 run）→ consumed；批 b、c 链自驱动成功（各 1 run）
        runner = _FakeRunner(proot, regression_statuses=["failed", "failed", "passed", "passed"])
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": False, "batch_size": 1}}},
            logger=None)
        res = orch.checkpoint(override_enabled=True)
        self.assertEqual(res, {"triggered": True, "reason": "dispatched"})
        self.assertEqual(len(runner.fix_calls), 4,
                         "失败批 consumed MUST NOT 终止手动授权链（2+1+1 次 run）")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open", "失败批条目入档案保持 open")
        self.assertEqual(items["b"]["status"], "resolved")
        self.assertEqual(items["c"]["status"], "resolved")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 2)
        self.assertFalse(prog["running"], "链收敛（剩余条目全被排除）后落终态")
        self.assertFalse(prog.get("manual_authorized", True),
                         "链收敛终态 MUST 清除授权旗标")

    def test_manual_authorization_not_carried_to_new_chain(self):
        """收尾链的授权旗标不外溢：新增 open 条目后无授权 checkpoint → disabled。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": False, "batch_size": 2}}},
            logger=None)
        orch.checkpoint(override_enabled=True)  # 链跑完（a、b 全 resolved）
        self.assertEqual(len(runner.fix_calls), 1)
        # 链收尾后新进一条 open 条目；不传 override 的后台激活 MUST NOT 被旧旗标放行
        _write_items(proot, {
            "a": _item("a", status="resolved", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", status="resolved", first_seen_at="2026-02-01T00:00:00Z"),
            "d": _item("d", first_seen_at="2026-04-01T00:00:00Z"),
        })
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        self.assertEqual(len(runner.fix_calls), 1,
                         "收尾链的授权 MUST NOT 外溢到新链")
        self.assertFalse(read_progress(proot).get("manual_authorized", True))

    def test_disabled_mid_chain_lands_terminal_progress(self):
        """事故缺陷面二：live 链撞 disabled 守卫 MUST 有进度落笔（不静默冻结）。

        code-review item 1421fde483a3 细化契约：批在飞时 disabled 不得直接写
        blocked 终态——批 worker 不感知开关，照常回归、合回并再写 merging 进
        度，抢先写终态会与「已终止」语义矛盾且随即被覆盖。故在飞窗口仅合并写
        reason=disabled 的提示性 current（保留 running=true 与批上下文），终态
        改写留给批收尾（_run_batch finally 清退 _in_flight）后的下一次 checkpoint。
        """
        from core.code_fix import CodeFixOrchestrator, read_progress

        class _CapturingExecutor:
            def __init__(self):
                self.jobs = []

            def submit(self, fn, *args, **kwargs):
                self.jobs.append((fn, args, kwargs))

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        executor = _CapturingExecutor()
        cfg = {"admin": {"code_review_fix": {"enabled": True}}}
        orch = CodeFixOrchestrator(runner, proot, config=cfg,
                                   logger=None, executor=executor)
        self.assertTrue(orch.checkpoint()["triggered"])
        self.assertTrue(read_progress(proot)["running"], "链已在盘上 live")
        # 模拟开关被中途关闭（config 字典原地翻转）
        cfg["admin"]["code_review_fix"]["enabled"] = False
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        # 批在飞窗口：仅提示性落笔，running 与批上下文保留（不静默冻结）
        prog = read_progress(proot)
        self.assertTrue(prog["running"],
                        "批在飞时 disabled MUST NOT 抹成终态（批 worker 仍在飞）")
        self.assertEqual(prog["reason"], "disabled")
        self.assertIn("收尾后终止", prog["current"])
        self.assertEqual(len(executor.jobs), 1, "disabled 后 MUST NOT 再投递")
        # 模拟批 worker 收尾（_run_batch finally 清退在飞标记）
        orch._in_flight = False
        res = orch.checkpoint()
        self.assertEqual(res, {"triggered": False, "reason": "disabled"})
        prog = read_progress(proot)
        self.assertFalse(prog["running"],
                         "批收尾后撞 disabled MUST 落终态，不得冻结在 running=true")
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "disabled")
        self.assertEqual(len(executor.jobs), 1, "disabled 后 MUST NOT 再投递")


class TestConcurrentCheckpoint(unittest.TestCase):
    def test_two_concurrent_checkpoints_dispatch_once(self):
        """两路并发到同一 checkpoint → 至多一次投递（单飞锁）。"""
        import types as _t

        from core.code_fix import CodeFixOrchestrator

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        started = threading.Event()
        release = threading.Event()

        class _SlowRunner(_FakeRunner):
            def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
                started.set()
                release.wait(timeout=10)
                return super().run_code_fix(worktree_root, items, run_id=run_id,
                                            failure_summary=failure_summary)

        runner = _SlowRunner(proot)
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        results = {}

        def _call(tag):
            results[tag] = orch.checkpoint()

        t1 = threading.Thread(target=_call, args=("t1",))
        t1.start()
        self.assertTrue(started.wait(timeout=5), "批 worker 未启动")
        t2 = threading.Thread(target=_call, args=("t2",))
        t2.start()
        t2.join(timeout=10)
        release.set()
        t1.join(timeout=10)
        dispatched = [r["reason"] for r in results.values() if r.get("triggered")]
        blocked = [r["reason"] for r in results.values() if not r.get("triggered")]
        self.assertEqual(len(runner.fix_calls), 1, "至多一次投递")
        self.assertEqual(dispatched, ["dispatched"])
        self.assertIn("already_running", blocked)


# ── 6.5 run_code_fix 执行函数 ────────────────────────────────────────


def _make_exec_runner(proot, run_claude):
    runner = _make_runner(proot)
    runner._get_agent_model_assignment = lambda t: None
    runner._get_admin_model = lambda: "admin-model"
    runner._run_claude = run_claude
    return runner


def _write_out(opath, rows):
    opath.parent.mkdir(parents=True, exist_ok=True)
    with opath.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestRunCodeFix(unittest.TestCase):
    def test_artifact_gate_missing_out(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()  # out 落 worktree 侧
        calls = {}

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            calls["cwd"] = cwd
            calls["spec_name"] = kw.get("spec_name")
            calls["agent_type"] = kw.get("agent_type")
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        items = [_item("a")]
        result = run_code_fix(runner, wt, items)
        self.assertFalse(result.success)
        self.assertIn("产物", result.error)
        self.assertEqual(calls["cwd"], wt, "agent cwd MUST 为 worktree")
        self.assertEqual(calls["spec_name"], "code-review-fix")
        self.assertEqual(calls["agent_type"], "code-fix")

    def test_artifact_gate_zero_valid_rows(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, ["garbage-not-json", ""])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        result = run_code_fix(runner, wt, [_item("a")])
        self.assertFalse(result.success)
        self.assertIn("零有效行", result.error)

    def test_out_parsing_counts(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [
                {"item_id": "a", "status": "fixed", "file": "x.py"},
                {"item_id": "b", "status": "fixed", "file": "y.py"},
                {"item_id": "c", "status": "skipped", "file": "z.py"},
            ])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        result = run_code_fix(runner, wt, [_item("a"), _item("b"), _item("c")])
        self.assertTrue(result.success)
        self.assertEqual(result.fixed, 2)
        self.assertEqual(result.skipped, 1)

    def test_unique_run_id_backoff(self):
        from unittest import mock

        from core.agent_runner.maintenance_runs import _unique_code_fix_run_id

        proot = _make_project_root()
        runner = _make_runner(proot)
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            first = _unique_code_fix_run_id(runner)
        self.assertEqual(first, "code-fix-1000")
        # 撞名：预建同名产物文件 → 退避 -1
        (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        (proot / ".fenix" / "code-review" / "fix-out-code-fix-1000.jsonl").write_text(
            "{}", encoding="utf-8")
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            second = _unique_code_fix_run_id(runner)
        self.assertEqual(second, "code-fix-1000-1")
        # 在飞 run 同名 → 再退避
        runner._running_agents = {"code-fix-1000-1": object()}
        with mock.patch("core.agent_runner.maintenance_runs.time.time", return_value=1000):
            third = _unique_code_fix_run_id(runner)
        self.assertEqual(third, "code-fix-1000-2")

    def test_model_chain_falls_back_to_code_review(self):
        """模型链：code-fix 缺配置时落 code-review 级（env 与 code-review 一致）。"""
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        captured = {}

        provider = {
            "name": "prov-a", "baseurl": "http://gw", "apikey": "k",
            "env": {"X_EXTRA": "1"},
        }

        def assignment(agent_type):
            return [(provider, "model-for-review")] if agent_type == "code-review" else None

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            captured["env"] = env
            captured["model"] = model
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = assignment
        runner._get_admin_model = lambda: "admin-model"
        runner._ensure_agent_config_dir = lambda name, model: "/tmp/cfgdir"
        runner._run_claude = fake_claude
        result = run_code_fix(runner, wt, [_item("a")])
        self.assertTrue(result.success)
        self.assertEqual(captured["env"]["ANTHROPIC_BASE_URL"], "http://gw")
        self.assertEqual(captured["env"]["ANTHROPIC_MODEL"], "model-for-review")
        self.assertEqual(captured["env"]["X_EXTRA"], "1")
        self.assertEqual(captured["model"], "model-for-review")

    def test_model_chain_prefers_code_fix(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        captured = {}

        def assignment(agent_type):
            table = {
                "code-fix": [({"name": "p-fix", "baseurl": "http://fix",
                                "apikey": "k", "env": {}}, "model-fix")],
                "code-review": [({"name": "p-rev", "baseurl": "http://rev",
                                   "apikey": "k", "env": {}}, "model-rev")],
            }
            return table.get(agent_type)

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            captured["model"] = model
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = assignment
        runner._get_admin_model = lambda: "admin-model"
        runner._ensure_agent_config_dir = lambda name, model: "/tmp/cfgdir"
        runner._run_claude = fake_claude
        run_code_fix(runner, wt, [_item("a")])
        self.assertEqual(captured["model"], "model-fix", "显式 code-fix 配置优先")

    def test_forwarder_registered_and_not_in_execute_agent(self):
        import inspect

        from core.agent_runner.runner import AgentRunner

        self.assertIn("run_code_fix", AgentRunner._FORWARDER_REGISTRY)
        src = inspect.getsource(AgentRunner._execute_agent)
        self.assertNotIn("run_code_fix", src,
                         "code-fix MUST NOT 走 _execute_agent（不占 spec 维度预算）")

    def test_failure_summary_injected_into_prompt(self):
        from core.agent_runner.maintenance_runs import run_code_fix

        proot = _make_project_root()
        wt = _make_project_root()
        prompts = []

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            prompts.append(prompt)
            out = Path(cwd) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
            _write_out(out, [{"item_id": "a", "status": "fixed", "file": "x.py"}])
            return ("done", 1, "sid", {})

        runner = _make_exec_runner(proot, fake_claude)
        run_code_fix(runner, wt, [_item("a")], failure_summary="status=failed\n- t::x: boom")
        self.assertIn("上一轮回归失败用例", prompts[0])
        self.assertIn("boom", prompts[0])


# ── 7.4 激活接线 ─────────────────────────────────────────────────────


class _CheckpointRecorder:
    def __init__(self):
        self.calls = 0

    def checkpoint(self):
        self.calls += 1
        return {"triggered": False, "reason": "recorded"}


class TestActivationWiring(unittest.TestCase):
    def _run_review(self, proot, inserted, recorder):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "m"
        runner._code_fix_orchestrator = recorder

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"file": "core/a.py", "findings": [
                    {"file": "core/a.py", "title": "t", "severity": "major",
                     "category": "correctness", "line": 1, "description": "d",
                     "suggestion": "s"},
                ]}) + "\n")
            return ("done", 1, "sid", {})

        runner._run_claude = fake_claude
        with mock.patch.object(mr, "_accumulate_code_review_tokens",
                               lambda *a, **k: None), \
             mock.patch.object(mr, "upsert_findings",
                               lambda *a, **k: {"inserted": inserted, "updated": 0}):
            result = mr.run_code_review(runner, ["core/a.py"], "scheduled")
        return result

    def test_review_finish_triggers_checkpoint_when_inserted(self):
        proot = _make_project_root()
        recorder = _CheckpointRecorder()
        result = self._run_review(proot, inserted=3, recorder=recorder)
        self.assertTrue(result.success)
        self.assertEqual(recorder.calls, 1, "inserted>0 且成功落账 → 触发一次 checkpoint")

    def test_review_zero_insert_no_trigger(self):
        proot = _make_project_root()
        recorder = _CheckpointRecorder()
        result = self._run_review(proot, inserted=0, recorder=recorder)
        self.assertTrue(result.success)
        self.assertEqual(recorder.calls, 0, "零产出 MUST NOT 激活")

    def test_review_checkpoint_exception_does_not_fail_review(self):
        from unittest import mock

        from core.agent_runner import maintenance_runs as mr

        proot = _make_project_root()
        runner = _make_runner(proot)
        runner._get_agent_model_assignment = lambda t: None
        runner._get_admin_model = lambda: "m"

        class _Boom:
            def checkpoint(self):
                raise RuntimeError("boom")

        runner._code_fix_orchestrator = _Boom()

        def fake_claude(prompt, cwd, run_id, model, env, **kw):
            out = Path(cwd) / ".fenix" / "code-review" / f"out-{run_id}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps({"file": "core/a.py", "findings": [
                    {"file": "core/a.py", "title": "t", "severity": "major",
                     "category": "correctness", "line": 1, "description": "d",
                     "suggestion": "s"},
                ]}) + "\n")
            return ("done", 1, "sid", {})

        runner._run_claude = fake_claude
        with mock.patch.object(mr, "_accumulate_code_review_tokens",
                               lambda *a, **k: None), \
             mock.patch.object(mr, "upsert_findings",
                               lambda *a, **k: {"inserted": 5, "updated": 0}):
            result = mr.run_code_review(runner, ["core/a.py"], "scheduled")
        self.assertTrue(result.success, "checkpoint 异常 MUST NOT 使审查 run 失败")

    def test_full_scan_without_orchestrator_no_crash(self):
        import types as _t

        from core.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus.logger = _FakeLogger()
        bus.state_machine = _t.SimpleNamespace(read_all=lambda: {})
        bus._dispatch_changes = lambda specs: None
        bus.pm_engine = _t.SimpleNamespace(check_blockers=lambda: None)
        # 未装配 code_fix_orchestrator → 不抛异常
        bus._run_full_scan_body()

    def test_full_scan_calls_checkpoint(self):
        import types as _t

        from core.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus.logger = _FakeLogger()
        bus.state_machine = _t.SimpleNamespace(read_all=lambda: {})
        bus._dispatch_changes = lambda specs: None
        bus.pm_engine = _t.SimpleNamespace(check_blockers=lambda: None)
        recorder = _CheckpointRecorder()
        bus.code_fix_orchestrator = recorder
        bus._run_full_scan_body()
        self.assertEqual(recorder.calls, 1)


# ── 8.4 进度 API ─────────────────────────────────────────────────────


class TestFixProgressAPI(unittest.TestCase):
    def _server(self, tmpdir):
        from conftest import _TestServer, make_project
        from core.dashboard.registry import Registry

        tmp = Path(tmpdir)
        proot = make_project(tmp, "proj-a")
        cfg = tmp / "dashboard.yaml"
        reg = Registry(config_path=cfg)
        reg.save({"port": 8787, "projects": [{"name": "proj-a", "path": str(proot)}],
                  "scan_dirs": [str(tmp / "scan-empty")]})
        static = Path(__file__).resolve().parents[1] / "core" / "dashboard" / "static"
        return _TestServer(reg, static), proot

    def test_default_state_when_no_progress_file(self):
        td = _mkdtemp("cfix-api-")
        server, _ = self._server(td)
        try:
            status, body = server.get("/api/code-review/fix-progress?project=proj-a")
            self.assertEqual(status, 200)
            self.assertEqual(body["running"], False)
            self.assertEqual(body["phase"], "idle")
            self.assertEqual(body["total"], 0)
            self.assertEqual(body["done"], 0)
        finally:
            server.httpd.shutdown()

    def test_returns_written_progress(self):
        from core.code_fix import write_progress

        td = _mkdtemp("cfix-api-")
        server, proot = self._server(td)
        try:
            write_progress(proot, running=True, phase="fixing", total=60, done=40,
                           batch_no=2, activation_id="act-1")
            status, body = server.get("/api/code-review/fix-progress?project=proj-a")
            self.assertEqual(status, 200)
            self.assertEqual(body["running"], True)
            self.assertEqual(body["phase"], "fixing")
            self.assertEqual(body["total"], 60)
            self.assertEqual(body["done"], 40)
            self.assertEqual(body["batch_no"], 2)
        finally:
            server.httpd.shutdown()

    def test_unknown_project_404(self):
        td = _mkdtemp("cfix-api-")
        server, _ = self._server(td)
        try:
            status, _body = server.get("/api/code-review/fix-progress?project=nope")
            self.assertEqual(status, 404)
        finally:
            server.httpd.shutdown()


# ── 11.1 端到端装配预演（全新进程）────────────────────────────────────


class TestEndToEndSmoke(unittest.TestCase):
    def test_fresh_process_import_and_orchestrator(self):
        """全新 Python 进程 import + 构造 + 守卫断言（无需真实 daemon/agent）。"""
        code = r"""
import json, sys, tempfile
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))

import core.code_fix
import core.config
import core.dashboard.data.code_review
# routes 直接 import 会撞 static_routes↔server 的既有循环导入（server.py:164
# ← static_routes.py:16），经 server 入口加载后（完成双向注册）再直接 import。
import core.dashboard.server
import core.dashboard.routes.code_review_routes
assert core.dashboard.routes.code_review_routes.H11CodeReviewRoutesMixin is not None

from core.code_fix import CodeFixOrchestrator, read_progress

td = Path(tempfile.mkdtemp(prefix="cfix-smoke-", dir=str(root / ".history" / "tmp")))
(td / ".fenix" / "code-review").mkdir(parents=True)

class FakeRunner:
    project_root = td
    def _get_config(self, key, default=None):
        return {}

# enabled=false → disabled
orch = CodeFixOrchestrator(FakeRunner(), td, config={"admin": {}}, logger=None)
assert orch.checkpoint() == {"triggered": False, "reason": "disabled"}, "disabled"

# enabled=true + 无 verify.yaml → regression_contract_missing + blocked 进度
(td / ".fenix" / "code-review" / "items.jsonl").write_text(
    json.dumps({"item_id": "a", "status": "open", "file": "x.py", "line": 1,
                "severity": "major", "category": "correctness", "title": "t",
                "description": "d", "suggestion": "s"}) + "\n", encoding="utf-8")
orch2 = CodeFixOrchestrator(FakeRunner(), td,
                            config={"admin": {"code_review_fix": {"enabled": True}}},
                            logger=None)
res = orch2.checkpoint()
assert res == {"triggered": False, "reason": "regression_contract_missing"}, res
prog = read_progress(td)
assert prog["phase"] == "blocked", prog
assert prog["reason"] == "regression_contract_missing", prog
print("SMOKE_OK")
"""
        repo_root = Path(__file__).resolve().parent.parent
        (repo_root / ".history" / "tmp").mkdir(parents=True, exist_ok=True)
        out = subprocess.run(
            [sys.executable, "-c", code, str(repo_root)],
            capture_output=True, text=True, timeout=120)
        self.assertIn("SMOKE_OK", out.stdout, f"stderr: {out.stderr[-2000:]}")


# ── 10.4 配置读写（admin.code_review_fix 受管键）──────────────────────


class TestCodeReviewFixConfigAdmin(unittest.TestCase):
    """admin.code_review_fix 受管键：登记 / sources / 回显 / 写读 / 非法拒绝（task 10.1/10.4）。"""

    def test_source_keys_registered(self):
        from core.dashboard.data import _SOURCE_KEYS

        self.assertIn("admin.code_review_fix", _SOURCE_KEYS)

    def test_sync_page_keys_contains_section(self):
        from core.dashboard.data.config_admin import _SYNC_PAGE_KEYS

        self.assertIn("code_review_fix", _SYNC_PAGE_KEYS["quality"].get("admin", []))

    def test_default_echo(self):
        from unittest.mock import patch

        from core.dashboard.data import read_config, read_effective_config

        proot = _make_project_root()
        # 用户级配置隔离（patch USER_CONFIG_DIR，仓库既定模式，对齐
        # test_fenix_tui_reports 双 patch）：本测试断言「任何作用域都未配置」
        # 的缺省回显，而总开关（admin.code_review_fix）落地后用户级
        # ~/.fenix/config.yaml 常开——不隔离则缺省断言随宿主环境漂移
        # （用户级配置敏感测试类，daily_self_review/billing 空表同源）。
        with patch("core.config.USER_CONFIG_DIR", proot / ".user-none"), \
             patch("core.dashboard.data.USER_CONFIG_PATH",
                   proot / ".user-none" / "config.yaml"):
            rc = read_config(proot)
            self.assertEqual(rc["code_review_fix"], {"enabled": False, "batch_size": 20})
            self.assertEqual(rc["sources"]["admin.code_review_fix"], "user")
            eff = read_effective_config(proot)
            self.assertEqual(eff["code_review_fix"], {"enabled": False, "batch_size": 20})

    def test_write_read_roundtrip(self):
        from core.dashboard.data import read_config, write_config

        proot = _make_project_root()
        r = write_config(proot, {"code_review_fix": {"enabled": True, "batch_size": 30}})
        self.assertIsNone(r.get("error"), r)
        rc = read_config(proot)
        self.assertEqual(rc["code_review_fix"], {"enabled": True, "batch_size": 30})
        self.assertEqual(rc["sources"]["admin.code_review_fix"], "project")

    def test_invalid_batch_size_rejected_no_half_write(self):
        from core.dashboard.data import read_config, write_config

        proot = _make_project_root()
        # 先写一个合法值
        r = write_config(proot, {"code_review_fix": {"enabled": True, "batch_size": 30}})
        self.assertIsNone(r.get("error"))
        # 非法 batch_size → 拒绝且不半写
        for bad in (0, -3, True, "20"):
            r = write_config(proot, {"code_review_fix": {"batch_size": bad}})
            self.assertIsNotNone(r.get("error"), f"batch_size={bad!r} MUST 拒绝")
            self.assertIn("positive integer", r["error"])
        # enabled 非 bool → 拒绝
        r = write_config(proot, {"code_review_fix": {"enabled": "yes"}})
        self.assertIsNotNone(r.get("error"))
        self.assertIn("boolean", r["error"])
        # 落盘值保持原值（不半写）
        rc = read_config(proot)
        self.assertEqual(rc["code_review_fix"], {"enabled": True, "batch_size": 30})


# ── add-code-fix-batch-failure-selfheal：三态收尾 / 锁释放 / 重试预算 / 链内跳过 ──


class _CapturingExecutor:
    """捕获 executor 作业（不执行）：手动逐个跑，断言自驱动/终止行为。"""

    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args, **kwargs):
        self.jobs.append((fn, args, kwargs))

    def run_one(self):
        """FIFO 跑一个作业，返回其是否为批 worker（args 非空）。"""
        fn, args, _ = self.jobs.pop(0)
        fn(*args)
        return bool(args)


class TestBatchOutcomeSelfDrive(unittest.TestCase):
    """三态收尾与自驱动（selfheal 3.1）：success/consumed 均推进下一批，halt 终止。"""

    def _orch(self, proot, runner, batch_size=1):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": batch_size}}},
            logger=None)

    def test_merge_back_conflict_consumed_resubmits_next_batch(self):
        """合回冲突批 consumed → 自驱动批 b 合回核销；冲突批条目入档案。"""
        from core.code_fix import CodeFixOrchestrator, load_failed_batches
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        wm = runner.worktree_manager
        real_merge = wm.merge_back

        def conflict_once(wt_path):
            if not wm.merge_calls:  # 批 a 合回冲突
                import types as _t
                wm.merge_calls.append(str(wt_path))
                return _t.SimpleNamespace(success=False, error="conflict")
            return real_merge(wt_path)

        wm.merge_back = conflict_once
        orch = self._orch(proot, runner)
        orch.checkpoint()
        self.assertEqual(len(wm.merge_calls), 2, "冲突批 consumed 后 MUST 自驱动批 b 合回")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "resolved")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a"})
        self.assertEqual(failed[0]["reason"], "merge_back_conflict")
        self.assertTrue(failed[0]["branch"] and failed[0]["tip_sha"])

    def test_no_effective_fix_consumed_resubmits_next_batch(self):
        """零有效修复批 consumed → 自驱动批 b；条目入 chain_skipped 不入档案。"""
        from core.code_fix import CodeFixOrchestrator, load_failed_batches, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, fix_statuses=[["skipped"], ["fixed"]])
        orch = self._orch(proot, runner)
        orch.checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "零产物批 consumed 后 MUST 自驱动批 b")
        self.assertEqual(len(runner.worktree_manager.merge_calls), 1)
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "resolved")
        self.assertEqual(load_failed_batches(proot), [])
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a"])

    def test_worktree_create_failed_halt_no_resubmit(self):
        """halt（worktree_create_failed）：链终止不自驱动（executor 无再投递作业）。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, create_result=None)
        executor = _CapturingExecutor()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None,
                                   executor=executor)
        self.assertTrue(orch.checkpoint()["triggered"])
        self.assertTrue(executor.run_one(), "批 worker 已被投递并执行")
        self.assertEqual(executor.jobs, [], "halt 批 MUST NOT 自驱动再投递")
        self.assertEqual(runner.fix_calls, [])
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertEqual(prog["reason"], "worktree_create_failed")

    def test_batch_worker_exception_halt_no_resubmit(self):
        """批 worker 异常（run 抛异常）→ 兜底 cleanup 释放锁 + 链终止不自驱动。"""
        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)

        def boom(*a, **k):
            raise RuntimeError("agent exploded")

        runner.run_code_fix = boom
        executor = _CapturingExecutor()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None,
                                   executor=executor)
        self.assertTrue(orch.checkpoint()["triggered"])
        executor.run_one()
        self.assertEqual(executor.jobs, [], "批 worker 异常 MUST NOT 自驱动再投递")
        self.assertTrue(runner.worktree_manager.cleanup_calls,
                        "异常兜底 MUST cleanup 释放 spec 锁")
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "failed")
        self.assertIn("batch_worker_error", prog["reason"])

    def test_consumed_failure_progress_wording(self):
        """consumed 失败收尾：非终态 phase + 「失败已跳过 — 继续后续批次」文案（D6）。"""
        from types import SimpleNamespace

        from core.code_fix import CodeFixOrchestrator, read_progress

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)

        def failing_fix(worktree_root, items, run_id=None, failure_summary=""):
            return SimpleNamespace(run_id="code-fix-x", success=False, fixed=0,
                                   skipped=0, error="产物缺失", output="")

        runner.run_code_fix = failing_fix
        executor = _CapturingExecutor()
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}},
            logger=None, executor=executor)
        orch.checkpoint()
        executor.run_one()  # 批 a worker：run 失败 → consumed
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "fixing", "consumed 收尾 MUST 用非终态 phase")
        self.assertFalse(prog["running"] is False, "consumed 收尾不复位 running（链继续）")
        self.assertIn("失败已跳过", prog["current"])
        self.assertIn("继续后续批次", prog["current"])
        self.assertIn("agent_run_failed", prog["reason"])
        self.assertEqual(prog["chain_skipped"], ["a"])
        # 随后 checkpoint 自驱动被投递（链继续）
        self.assertEqual(len(executor.jobs), 1)


class TestFailureLockRelease(unittest.TestCase):
    """现场即弃的锁释放（selfheal 3.2）：失败收尾清理 worktree 目录并释放 spec 锁。"""

    def _runner(self, proot, **kw):
        runner = _FakeRunner(proot, **kw)
        runner.worktree_manager = _FakeWM(enforce_lock=True)
        return runner

    def _orch(self, proot, runner, batch_size=1):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": batch_size}}},
            logger=None)

    def test_regression_failed_twice_releases_lock_for_next_batch(self):
        """回归两败批现场即弃：目录清理 + 锁释放，同链下一批 create 不被拒。"""
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = self._runner(proot, regression_statuses=["failed", "failed"])
        orch = self._orch(proot, runner)
        orch.checkpoint()
        wm = runner.worktree_manager
        self.assertEqual(
            len(wm.create_calls), 2,
            "批 b 的 create MUST NOT 被批 a 残留的 code-review-fix 锁拒绝")
        self.assertEqual(wm._active, set(), "两批失败收尾后锁集合必为空")
        for path, success in wm.cleanup_calls:
            self.assertFalse(success)
            self.assertFalse(Path(path).exists(), "失败批 worktree 目录 MUST 被清理")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 2)
        for rec in failed:
            self.assertTrue(rec["branch"] and rec["tip_sha"] and rec["failed_at"])
        self.assertEqual(read_items(proot)["a"]["status"], "open")

    def test_merge_back_conflict_releases_lock_for_next_batch(self):
        """合回冲突批现场即弃：目录清理 + 锁释放，同链下一批正常建树合回。"""
        from core.code_fix import load_failed_batches
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = self._runner(proot)
        wm = runner.worktree_manager
        real_merge = wm.merge_back

        def conflict_once(wt_path):
            if not wm.merge_calls:
                import types as _t
                wm.merge_calls.append(str(wt_path))
                return _t.SimpleNamespace(success=False, error="conflict")
            return real_merge(wt_path)

        wm.merge_back = conflict_once
        orch = self._orch(proot, runner)
        orch.checkpoint()
        self.assertEqual(len(wm.create_calls), 2, "批 b 建树 MUST NOT 被残留锁拒绝")
        self.assertEqual(wm._active, set())
        conflict_dirs = [p for p, s in wm.cleanup_calls if not s]
        self.assertEqual(len(conflict_dirs), 1)
        self.assertFalse(Path(conflict_dirs[0]).exists(), "冲突批 worktree MUST 被清理")
        self.assertEqual(read_items(proot)["b"]["status"], "resolved")
        self.assertEqual(load_failed_batches(proot)[0]["reason"], "merge_back_conflict")


class TestRetryBudget(unittest.TestCase):
    """失败档案自动重试预算（selfheal 3.3 / D3/D4）。"""

    def _signals(self, proot, signal_type):
        from core.admin_store import AdminStore

        store = AdminStore(proot, logger=None)
        return [r for r in store.read_all() if r.get("signal_type") == signal_type]

    def test_first_record_fail_count_one_with_trace_fields(self):
        from core.code_fix import load_failed_batches, record_failed_batch

        proot = _make_project_root()
        record_failed_batch(
            proot, ["a", "b"], "/tmp/wt-x",
            reason="regression_failed_twice",
            branch="fenix/code-review-fix-x", tip_sha="abc1234")
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["fail_count"], 1)
        self.assertEqual(recs[0]["reason"], "regression_failed_twice")
        self.assertEqual(recs[0]["branch"], "fenix/code-review-fix-x")
        self.assertEqual(recs[0]["tip_sha"], "abc1234")
        self.assertTrue(recs[0]["failed_at"])
        # 预算内入档：无告警、无 todo 人工项
        self.assertEqual(self._signals(proot, "code_fix_retry_budget_exhausted"), [])
        todo_path = proot / ".fenix" / "todo.md"
        self.assertFalse(todo_path.exists())

    def test_same_item_set_increments_without_duplicate(self):
        from core.code_fix import load_failed_batches, record_failed_batch

        proot = _make_project_root()
        record_failed_batch(proot, ["a", "b"], "/tmp/wt-1",
                            reason="regression_failed_twice", branch="br-1", tip_sha="s1")
        record_failed_batch(proot, ["b", "a"], "/tmp/wt-2",
                            reason="merge_back_conflict", branch="br-2", tip_sha="s2")
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1, "同条目集（集合相等，与顺序无关）MUST 复用记录")
        self.assertEqual(recs[0]["fail_count"], 2)
        self.assertEqual(recs[0]["reason"], "merge_back_conflict", "其余字段刷新")
        self.assertEqual(recs[0]["branch"], "br-2")
        self.assertEqual(recs[0]["tip_sha"], "s2")

    def test_new_chain_releases_below_max_keeps_at_max(self):
        from core.code_fix import (FAIL_RETRY_MAX, load_failed_batches,
                                   record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        # 三条档案：fail_count 1 / 2 / 3（selfheal 混合预算场景）
        record_failed_batch(proot, ["c1"], "/tmp/wt-a", reason="r")
        record_failed_batch(proot, ["c2"], "/tmp/wt-b", reason="r")
        record_failed_batch(proot, ["c2"], "/tmp/wt-b", reason="r")
        for _ in range(FAIL_RETRY_MAX):
            record_failed_batch(proot, ["c3"], "/tmp/wt-c", reason="r")
        released = release_retryable_failed_batches(proot)
        self.assertEqual(released, 2, "仅 fail_count<3 的两条被释放")
        # 墓碑语义（code-review item 931df4af59cc）：释放打标不删除，fail_count
        # 预算由墓碑保留；仅达上限记录保持「在档排除」态
        remaining = load_failed_batches(proot)
        self.assertEqual(len(remaining), 3)
        tombstones = [r for r in remaining if r.get("released")]
        self.assertEqual(
            {tuple(sorted(r["item_ids"])) for r in tombstones}, {("c1",), ("c2",)}
        )
        self.assertTrue(all(r.get("released_at") for r in tombstones))
        active = [r for r in remaining if not r.get("released")]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["fail_count"], FAIL_RETRY_MAX)
        self.assertEqual(set(active[0]["item_ids"]), {"c3"})

    def test_release_tombstone_keeps_budget_across_chains(self):
        """跨链预算累计（code-review item 931df4af59cc 集成缺口）：
        链末释放（打标墓碑）→ 条目重回可选池 → 同条目集再次失败复燃墓碑并
        递增 fail_count——不再每链重新以 1 建档，达上限告警可达。"""
        from core.code_fix import (FAIL_RETRY_MAX, _failed_item_ids,
                                   load_failed_batches, record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        record_failed_batch(proot, ["a"], "/tmp/wt-1", reason="r")
        self.assertEqual(_failed_item_ids(proot), {"a"}, "在档记录参与选批排除")
        # 链末新链启动：预算内释放 → 条目重回可选池（不被排除），记录保留
        self.assertEqual(release_retryable_failed_batches(proot), 1)
        self.assertEqual(_failed_item_ids(proot), set(), "墓碑不参与选批排除")
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1, "释放打标不删除")
        self.assertTrue(recs[0].get("released"))
        self.assertEqual(recs[0]["fail_count"], 1, "预算由墓碑保留")
        # 新链同条目集再次失败：复燃墓碑并续增（不再重新建档）
        record_failed_batch(proot, ["a"], "/tmp/wt-2", reason="r")
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["fail_count"], 2)
        self.assertFalse(recs[0].get("released"), "复燃清标回到在档排除态")
        self.assertEqual(_failed_item_ids(proot), {"a"})
        # 递增至 FAIL_RETRY_MAX 的那次发一次性告警（真实编排路径可达）
        for _ in range(FAIL_RETRY_MAX - 2):
            record_failed_batch(proot, ["a"], "/tmp/wt-3", reason="r")
        self.assertEqual(len(self._signals(proot, "code_fix_retry_budget_exhausted")), 1)
        # 幂等：已释放墓碑不重刷、达上限记录不重复释放
        self.assertEqual(release_retryable_failed_batches(proot), 0)

    def test_max_alert_exactly_once_then_never_again(self):
        from core.code_fix import (FAIL_RETRY_MAX, record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        for i in range(FAIL_RETRY_MAX):
            record_failed_batch(proot, ["x"], f"/tmp/wt-{i}",
                                reason="regression_failed_twice",
                                branch="br", tip_sha=f"sha-{i}")
        alerts = self._signals(proot, "code_fix_retry_budget_exhausted")
        self.assertEqual(len(alerts), 1, "递增至 FAIL_RETRY_MAX 的那次恰好一条告警")
        self.assertIn("x", alerts[0]["evidence"])
        # 再次入档（>MAX）与新链启动释放均不再发告警
        record_failed_batch(proot, ["x"], "/tmp/wt-4", reason="r", branch="br", tip_sha="s")
        release_retryable_failed_batches(proot)
        self.assertEqual(len(self._signals(proot, "code_fix_retry_budget_exhausted")), 1,
                         "达上限后 MUST NOT 重复告警")

    def test_todo_entry_only_at_max_with_trace_fields(self):
        from core.code_fix import FAIL_RETRY_MAX, record_failed_batch

        proot = _make_project_root()
        todo_path = proot / ".fenix" / "todo.md"
        for i in range(FAIL_RETRY_MAX - 1):
            record_failed_batch(proot, ["y"], f"/tmp/wt-{i}",
                                reason="regression_failed_twice",
                                branch="br-y", tip_sha=f"sha-{i}")
            self.assertFalse(todo_path.exists(),
                             "预算内入档 MUST NOT 产生 todo 人工项")
        record_failed_batch(proot, ["y"], "/tmp/wt-final",
                            reason="regression_failed_twice", branch="br-y", tip_sha="sha-final")
        todo = todo_path.read_text(encoding="utf-8")
        self.assertIn("br-y", todo)
        self.assertIn("sha-final", todo)
        self.assertIn("y", todo)
        self.assertNotIn("/tmp/wt-final", todo, "现场即弃后 MUST NOT 引用 worktree 路径")
        self.assertNotIn("保留 worktree", todo)
        self.assertNotIn("车道不再自动重派", todo)


class TestChainSkippedLifecycle(unittest.TestCase):
    """链内跳过集生命周期（selfheal 3.4 / D3）。"""

    def test_chain_skipped_not_in_archive_and_reselected_by_new_chain(self):
        """agent run 失败条目：本链不再选批、不入档案；新链启动重置后重新可选。"""
        from types import SimpleNamespace

        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)

        def failing_fix(worktree_root, items, run_id=None, failure_summary=""):
            return SimpleNamespace(run_id="code-fix-x", success=False, fixed=0,
                                   skipped=0, error="产物缺失", output="")

        runner.run_code_fix = failing_fix
        executor = _CapturingExecutor()
        orch = CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}},
            logger=None, executor=executor)
        # 批 a：失败 → consumed（chain_skipped=[a]）→ 自驱动 checkpoint
        orch.checkpoint()
        executor.run_one()
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a"])
        self.assertEqual(len(executor.jobs), 1, "consumed 后自驱动 checkpoint 已投递")
        executor.run_one()  # checkpoint：选批排除 a → 批 b
        # 批 b：失败 → chain_skipped=[a, b] → 自驱动 checkpoint → 选批为空收敛
        executor.run_one()
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a", "b"])
        executor.run_one()
        self.assertEqual(executor.jobs, [], "可选池耗尽后链收敛，无新投递")
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertIn("下轮自动重试", prog["current"])
        self.assertEqual(load_failed_batches(proot), [],
                         "瞬态失败 MUST NOT 写 fix-failed.json")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "open")
        # 新链启动（下一轮激活）：chain_skipped 重置为空，条目重新可选
        runner.run_code_fix = _FakeRunner(proot).run_code_fix.__get__(runner)
        res = orch.checkpoint()
        self.assertTrue(res["triggered"], "新链 MUST 重新组批被跳过条目")
        prog = read_progress(proot)
        self.assertEqual(prog["chain_skipped"], [], "新链启动 MUST 重置链内跳过集")
        self.assertEqual(prog["batch_no"], 1, "新链批号重置")
        self.assertEqual(len(executor.jobs), 1, "新链已投递批 worker")
        executor.run_one()
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved", "上链被跳过条目被重新消费")

    def test_no_effective_fix_entries_skip_rest_of_chain(self):
        """零有效修复条目：本链 select_batch 不再选中，随收敛终态下轮自动重试。"""
        from core.code_fix import (CodeFixOrchestrator, load_failed_batches,
                                   read_progress, select_batch)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a"), "b": _item("b")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot, fix_statuses=[["skipped", "skipped"]])
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_ON, logger=None)
        orch.checkpoint()  # 单批全 skipped → no_effective_fix → consumed → 收敛
        self.assertEqual(read_progress(proot)["chain_skipped"], ["a", "b"])
        self.assertEqual(load_failed_batches(proot), [])
        # 本链口径：排除 chain_skipped 后无可选条目
        self.assertEqual(select_batch(proot, 10, exclude_ids=["a", "b"]), [])
        self.assertEqual(read_items(proot)["a"]["status"], "open")


# ── fix-codefix-wipgate-defer：wip_gate_blocked 分类 / defer 台账 / 预算 ──


class _CapturingLogger:
    """记录 (level, tag, msg) 的假 logger（_FakeLogger 的可断言版）。"""

    def __init__(self):
        self.records = []

    def __getattr__(self, name):
        def _log(tag, msg):
            self.records.append((name, tag, msg))
        return _log


def _wip_blocked_info(overlap):
    """wip_gate_blocked=True 的 MergeConflictInfo 替身（mergeback.py 升级出口形态）。"""
    import types as _t
    return _t.SimpleNamespace(
        success=False,
        error="Merge-back blocked by WIP overlap precheck (policy=escalate)",
        wip_overlap=list(overlap),
        wip_gate_blocked=True,
    )


class TestWipGateDeferred(unittest.TestCase):
    """wip_gate_blocked 分类、defer 台账/重试/预算/再认领（fix-codefix-wipgate-defer）。"""

    def _orch(self, proot, runner, batch_size=1, logger=None, executor=None):
        from core.code_fix import CodeFixOrchestrator

        return CodeFixOrchestrator(
            runner, proot,
            config={"admin": {"code_review_fix": {"enabled": True,
                                                  "batch_size": batch_size}}},
            logger=logger, executor=executor)

    def _signals(self, proot, signal_type):
        from core.admin_store import AdminStore

        store = AdminStore(proot, logger=None)
        return [r for r in store.read_all()
                if r.get("signal_type") == signal_type]

    def _arm_blocked_merge(self, wm, overlap, blocked_calls):
        """伪 merge_back：前 blocked_calls 次返回 wip_gate_blocked=True，此后放行。"""
        real_merge = wm.merge_back
        state = {"n": 0}

        def flaky(wt_path):
            state["n"] += 1
            wm.merge_calls.append(str(wt_path))
            if state["n"] <= blocked_calls:
                return _wip_blocked_info(overlap)
            return real_merge(wt_path)

        wm.merge_back = flaky

    # -- 5.1 分类 + 1.2 台账八字段 + 1.3 首次 info 告警 --------------------

    def test_blocked_merge_defers_preserves_scene_and_budget(self):
        """wip_gate_blocked=True → defer：不入档案、不 cleanup、现场保留、放锁。"""
        from core.code_fix import (load_deferred_batches, load_failed_batches,
                                   read_progress)

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner.worktree_manager = _FakeWM("git", enforce_lock=True)
        wm = runner.worktree_manager
        self._arm_blocked_merge(wm, ["src/a.py"], blocked_calls=99)  # 恒阻断
        executor = _CapturingExecutor()
        orch = self._orch(proot, runner, executor=executor)
        self.assertTrue(orch.checkpoint()["triggered"])
        executor.run_one()  # 批 a worker：defer 收尾（checkpoint 作业留队列不跑）

        # True 分支：不写 fix-failed、不烧 fail_count、不 cleanup
        self.assertEqual(load_failed_batches(proot), [],
                         "wip_gate_blocked MUST NOT 写失败档案")
        self.assertEqual(wm.cleanup_calls, [], "defer MUST NOT 清理现场")
        # 台账八字段齐全（1.2）
        entries = load_deferred_batches(proot)
        self.assertEqual(len(entries), 1)
        e = entries[0]
        for k in ("worktree", "branch", "tip_sha", "item_ids", "fixed_ids",
                  "defer_count", "first_deferred_at", "last_overlap"):
            self.assertIn(k, e, f"台账条目缺字段 {k}")
        self.assertEqual(e["item_ids"], ["a"])
        self.assertEqual(e["fixed_ids"], ["a"], "fixed_ids 为批产物行 fixed 核销集合")
        self.assertEqual(e["defer_count"], 1, "首记 defer_count=1（批收尾那次被阻断的实际尝试）")
        self.assertEqual(e["last_overlap"], ["src/a.py"])
        self.assertRegex(e["first_deferred_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        # 现场保留：worktree 目录在、分支 tip 等于记录的 tip_sha
        self.assertTrue(Path(e["worktree"]).exists(), "worktree 目录保留")
        self.assertTrue(e["branch"] and e["tip_sha"])
        # spec 锁已释放（1.1：随后同键 create 可成功的前提）
        self.assertEqual(wm._active, set(), "defer MUST 释放 code-review-fix:code-fix spec 锁")
        # 进度文案可区分（D7 / spec：reason=wip_gate_blocked + 主树未提交改动）
        prog = read_progress(proot)
        self.assertEqual(prog["reason"], "wip_gate_blocked")
        self.assertIn("主树未提交改动", prog["current"])
        self.assertIn("src/a.py", prog["current"])
        # 首次 defer 即发 info 告警（1.3）：含交集清单与处置话术
        alerts = self._signals(proot, "code_fix_wip_gate_deferred")
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["severity"], "info")
        self.assertIn("src/a.py", alerts[0]["evidence"])
        self.assertIn("git add/commit", alerts[0]["recommended_action"])
        self.assertIn("git stash push", alerts[0]["recommended_action"])

    # -- 5.2 端到端 + 5.6 选批排除 -----------------------------------------

    def test_defer_e2e_retry_success_after_main_tree_clean(self):
        """首合回被阻断→台账完整、锁释放、下一批正常建树；主树净后自动合回核销。"""
        from core.code_fix import load_deferred_batches, read_progress
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        runner.worktree_manager = _FakeWM("git", enforce_lock=True)
        wm = runner.worktree_manager
        # 调用 1=批 a 合回（阻断）、2=链边界重试 a（仍阻断）、3=批 b 合回（净）、
        # 4=链边界重试 a（主树已净 → 成功）
        self._arm_blocked_merge(wm, ["src/a.py"], blocked_calls=2)
        executor = _CapturingExecutor()
        orch = self._orch(proot, runner, executor=executor)
        orch.checkpoint()          # 投批 a
        executor.run_one()         # 批 a worker → defer
        e0 = load_deferred_batches(proot)[0]
        first_ts = e0["first_deferred_at"]
        wt_a = Path(e0["worktree"])
        executor.run_one()         # checkpoint：重试 a（阻断，defer_count+1）→ 选批 b（排除生效）→ 投批 b
        e1 = load_deferred_batches(proot)[0]
        self.assertEqual(e1["defer_count"], 2, "链边界重试仍被阻断 → defer_count+1（2.3）")
        self.assertEqual(e1["first_deferred_at"], first_ts, "first_deferred_at 不因重试改变")
        self.assertEqual(len(executor.jobs), 1, "批 b 已投递")
        self.assertEqual(executor.jobs[0][1][0]["item_ids"], ["b"],
                         "defer 条目不重选（排除并集生效），下一批是 b 而非重跑 a")
        executor.run_one()         # 批 b worker：合回核销 b
        self.assertEqual(len(runner.fix_calls), 2, "批 b 已执行（锁释放后建树成功）")
        self.assertEqual(read_items(proot)["b"]["status"], "resolved")
        executor.run_one()         # checkpoint：重试 a（主树净 → 成功）→ 收敛 idle
        self.assertEqual(executor.jobs, [])
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "resolved", "延迟批合回成功后核销")
        self.assertEqual(load_deferred_batches(proot), [], "台账清空")
        self.assertFalse(wt_a.exists(), "重试成功后 worktree 目录被清理")
        self.assertTrue(any(w == str(wt_a) and s is True
                            for w, s in wm.cleanup_calls),
                        "重试收尾走 cleanup(success=True)")
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 2, "进度 done 累加（批 b 1 + 延迟批核销 1）")
        self.assertIn("延迟批合回成功", prog["current"])
        self.assertIn("核销 1 条", prog["current"])

    def test_retry_success_skips_manually_ignored_items(self):
        """defer 窗口内被人工置 ignored 的条目：重试成功不核销覆写、不计 done。"""
        from core.code_fix import load_deferred_batches, read_progress
        from core.code_review import mark_ignored, read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        self._arm_blocked_merge(runner.worktree_manager, ["src/a.py"], blocked_calls=1)
        executor = _CapturingExecutor()
        orch = self._orch(proot, runner, executor=executor)
        orch.checkpoint()
        executor.run_one()  # 批 a worker → defer（merge 调用 1）
        mark_ignored(proot, ["a"], reasons={"a": "false_positive"})  # 人工置终态
        executor.run_one()  # checkpoint：重试成功（调用 2）→ 过滤后无可核销
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "ignored",
                         "mark_resolved 无终态保护 → 核销方 MUST 过滤，不得覆写 ignored")
        self.assertEqual(load_deferred_batches(proot), [])
        prog = read_progress(proot)
        self.assertEqual(prog["done"], 0, "人工终态条目不计 done")
        self.assertIn("核销 0 条", prog["current"])

    # -- 5.3 预算双门 + 3.2 一次性告警 --------------------------------------

    def test_budget_time_gate_downgrades_without_attempt(self):
        """first_deferred_at 超 90 分钟 → 降级入档案，且不再尝试 merge_back。"""
        from core.code_fix import (_save_deferred_batches, load_deferred_batches,
                                   load_failed_batches, _worktree_head)

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        wm = runner.worktree_manager
        self._arm_blocked_merge(wm, ["src/a.py"], blocked_calls=99)
        executor = _CapturingExecutor()
        orch = self._orch(proot, runner, executor=executor)
        orch.checkpoint()
        executor.run_one()  # defer
        e = load_deferred_batches(proot)[0]
        e["first_deferred_at"] = "2020-01-01T00:00:00Z"  # 注入过期时间
        _save_deferred_batches(proot, [e])
        n_merge = len(wm.merge_calls)
        executor.run_one()  # checkpoint：时间门降级
        self.assertEqual(len(wm.merge_calls), n_merge,
                         "预算已耗尽 MUST NOT 再尝试 merge_back（先到为准）")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "wip_gate_blocked_expired")
        self.assertEqual(failed[0]["fail_count"], 1, "正常烧 fail_count 预算")
        self.assertEqual(set(failed[0]["item_ids"]), {"a"})
        self.assertTrue(failed[0]["branch"] and failed[0]["tip_sha"])
        self.assertEqual(load_deferred_batches(proot), [], "台账移除")
        self.assertTrue(any(w == e["worktree"] and s is False
                            for w, s in wm.cleanup_calls),
                        "走失败收尾（success=False 遗产分支）")
        alerts = self._signals(proot, "code_fix_wip_gate_defer_expired")
        self.assertEqual(len(alerts), 1)
        self.assertIn("src/a.py", alerts[0]["evidence"], "告警含交集文件清单")
        self.assertIn("git stash push", alerts[0]["recommended_action"])
        # 同条目集（item_ids 指纹）二次降级不再发告警（3.2）。预置 fail_count=2
        # 使二次降级后达 FAIL_RETRY_MAX，档案不被新链自动释放（预算内记录会被
        # 新链 release_retryable_failed_batches 释放——既有语义），可断言终态。
        import json as _json

        from core.code_fix import _atomic_write, _failed_path

        recs = load_failed_batches(proot)
        recs[0]["fail_count"] = 2
        _atomic_write(_failed_path(proot), _json.dumps(recs, ensure_ascii=False, indent=2))
        wt2 = _make_git_repo()
        e2 = dict(e, worktree=str(wt2), tip_sha=_worktree_head(wt2),
                  first_deferred_at="2020-01-01T00:00:00Z")
        _save_deferred_batches(proot, [e2])
        orch.checkpoint()  # 重试点（降级路径不自驱动，直调 checkpoint 触发下一拍）
        failed = load_failed_batches(proot)
        self.assertEqual([f["fail_count"] for f in failed], [3],
                         "二次降级复用同条目集记录递增（达上限不被新链释放）")
        self.assertEqual(load_deferred_batches(proot), [])
        self.assertEqual(len(self._signals(proot, "code_fix_wip_gate_defer_expired")),
                         1, "同指纹二次降级 MUST NOT 重复告警")

    def test_budget_count_gate_downgrades_after_blocked_retry(self):
        """defer_count 打满 → 次数门降级（降级前确有实际 merge_back 尝试）。"""
        from core.code_fix import (_save_deferred_batches, load_deferred_batches,
                                   load_failed_batches)

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        wm = runner.worktree_manager
        self._arm_blocked_merge(wm, ["src/a.py"], blocked_calls=99)
        executor = _CapturingExecutor()
        orch = self._orch(proot, runner, executor=executor)
        orch.checkpoint()
        executor.run_one()  # defer（defer_count=1）
        e = load_deferred_batches(proot)[0]
        e["defer_count"] = 5  # 打满前夜：本次重试仍阻断即达 6
        _save_deferred_batches(proot, [e])
        n_merge = len(wm.merge_calls)
        executor.run_one()  # checkpoint：重试（阻断）→ defer_count=6 → 降级
        self.assertEqual(len(wm.merge_calls), n_merge + 1,
                         "次数门在本次实际尝试仍被阻断后判定")
        failed = load_failed_batches(proot)
        self.assertEqual(failed[0]["reason"], "wip_gate_blocked_expired")
        self.assertEqual(load_deferred_batches(proot), [])

    # -- 5.4 再认领 ---------------------------------------------------------

    def test_reclaim_keeps_alive_drops_lost(self):
        """新链再认领：存活条目字段原样保留（不重置），丢失条目移出。"""
        from core.code_fix import (_save_deferred_batches, load_deferred_batches,
                                   reclaim_deferred_batches, _worktree_head)

        proot = _make_project_root()
        wt = _make_git_repo()
        alive = {"worktree": str(wt), "branch": "fenix/x-1",
                 "tip_sha": _worktree_head(wt), "item_ids": ["a"],
                 "fixed_ids": ["a"], "defer_count": 3,
                 "first_deferred_at": "2026-09-23T01:00:00Z",
                 "last_overlap": ["f.py"]}
        lost = dict(alive, worktree=str(Path(_mkdtemp("cfix-gone")) / "missing"),
                    item_ids=["b"], fixed_ids=["b"])
        _save_deferred_batches(proot, [alive, lost])
        dropped = reclaim_deferred_batches(proot)
        self.assertEqual(dropped, 1)
        self.assertEqual(load_deferred_batches(proot), [alive],
                         "存活条目字段不变保留；丢失条目移出")

    def test_new_chain_logs_warning_for_lost_entries(self):
        """新链启动扫台账：丢失条目清出台账并记 warning（条目保持 open 可重选）。"""
        from core.code_fix import (_save_deferred_batches, load_deferred_batches,
                                   read_progress)

        proot = _make_project_root()
        _write_items(proot, {"c": _item("c")})
        _write_verify_yaml(proot)
        lost = {"worktree": str(Path(_mkdtemp("cfix-gone2")) / "nope"),
                "branch": "fenix/y-2", "tip_sha": "deadbeef",
                "item_ids": ["z"], "fixed_ids": ["z"], "defer_count": 1,
                "first_deferred_at": "2026-09-23T01:00:00Z",
                "last_overlap": []}
        _save_deferred_batches(proot, [lost])
        runner = _FakeRunner(proot)
        logger = _CapturingLogger()
        orch = self._orch(proot, runner, logger=logger)
        orch.checkpoint()  # 新链：重试点丢弃条目 + 新链再认领扫描
        warnings = [m for lvl, _tag, m in logger.records
                    if lvl == "warning" and "丢失" in m]
        self.assertTrue(warnings, "丢失条目 MUST 记 warning")
        self.assertEqual(load_deferred_batches(proot), [])
        self.assertEqual(read_progress(proot)["chain_skipped"], [],
                         "条目未核销天然在 open 池，不进链内跳过集")

    # -- 5.5 回归锁定：真冲突路径逐字不变 -----------------------------------

    def test_true_conflict_path_unchanged(self):
        """wip_gate_blocked=False 的合回失败维持既有「现场即弃」语义。"""
        import types as _t

        from core.code_fix import (load_deferred_batches, load_failed_batches,
                                   read_progress)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {
            "a": _item("a", first_seen_at="2026-01-01T00:00:00Z"),
            "b": _item("b", first_seen_at="2026-02-01T00:00:00Z"),
        })
        _write_verify_yaml(proot)
        runner = _FakeRunner(proot)
        wm = runner.worktree_manager
        real_merge = wm.merge_back

        def conflict_once(wt_path):
            if not wm.merge_calls:  # 批 a 真冲突（无 wip_gate_blocked 属性）
                wm.merge_calls.append(str(wt_path))
                return _t.SimpleNamespace(success=False, error="conflict")
            return real_merge(wt_path)

        wm.merge_back = conflict_once
        orch = self._orch(proot, runner)
        orch.checkpoint()  # 同步模式：批 a 冲突 → consumed → 自驱动批 b
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "merge_back_conflict")
        self.assertEqual(failed[0]["fail_count"], 1)
        self.assertEqual(set(failed[0]["item_ids"]), {"a"})
        self.assertTrue(failed[0]["branch"] and failed[0]["tip_sha"])
        self.assertEqual(load_deferred_batches(proot), [],
                         "真冲突 MUST NOT 进 defer 台账")
        items = read_items(proot)
        self.assertEqual(items["a"]["status"], "open")
        self.assertEqual(items["b"]["status"], "resolved", "链继续后续批")
        # worktree 路径不再入档（code-review item a0e268c1f1c1：现场即弃后
        # 落盘路径写入几秒即失效且无读者，记录恒为 null，追溯以 branch/tip_sha
        # 为准）；现场证据改从 cleanup 调用核对
        self.assertIsNone(failed[0]["worktree"])
        self.assertTrue(
            any(s is False and not Path(w).exists() for w, s in wm.cleanup_calls),
            "现场即弃：worktree 目录被清理",
        )
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertEqual(prog["reason"], "failed_batch_retained",
                         "链收敛出口语义不变（「合回冲突」文案为批收尾瞬态）")

    # -- D3 放锁原语（真实 WorktreeManager）---------------------------------

    def test_release_spec_lock_allows_same_key_create(self):
        """release_spec_lock 只摘锁：目录/活动集保留，同键 create 可再成功。"""
        from core.worktree_manager import WorktreeManager

        repo = _make_git_repo()
        base = Path(_mkdtemp("cfix-wm-"))
        wm = WorktreeManager(base, repo, _FakeLogger())
        wt = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        self.assertIsNotNone(wt)
        self.assertTrue(wm.has_active_lock("code-review-fix", "code-fix"))
        self.assertTrue(wm.release_spec_lock("code-review-fix", "code-fix"))
        self.assertFalse(wm.has_active_lock("code-review-fix", "code-fix"))
        self.assertFalse(wm.release_spec_lock("code-review-fix", "code-fix"),
                         "重复放锁幂等（无锁返回 False）")
        self.assertIn(str(wt), wm._active_worktrees, "defer 现场：活动集保留")
        self.assertTrue(Path(wt).exists(), "defer 现场：目录保留")
        import time as _time

        _time.sleep(1.1)  # 分支名含秒级时间戳（create 端硬编码），隔秒防同名撞分支
        wt2 = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        self.assertIsNotNone(wt2, "放锁后同键 create 可成功（下一批建树不再被拒）")
