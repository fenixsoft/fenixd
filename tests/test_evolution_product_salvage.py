# -*- coding: utf-8 -*-
"""evo-add-evolution-product-salvage：run_evolution 产物抢救与失败归因分级。

覆盖（tasks 2.1 / 2.2）：
- 五类抢救场景：产物已写但 CLI 非零退出、产物缺失但有分片、产物与分片
  皆空、产物不可解析但有分片、分片条目数不足按失败落地（水位不推进）；
- _salvage_evolution_out 合并配方单元行为（sorted(glob)、损坏分片跳过、
  产物可解析不覆盖）；
- read_contract「产物文件未写出」与「产物 JSON 不可解析」文案分级；
- 单条非法宽口径部分接受 / 全非法整体拒绝 / 失败现场留档
  （evo-add-evolution-contract-partial-accept 2.1）。

run_evolution 级测试以 __new__ 绕过 __init__ 的最小 AgentRunner 替身驱动
（同 tests/test_self_evolution.py::_FakeEvolutionRunner 形态），_run_agent
不实测真实 claude 进程。
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.agent_runner import maintenance_runs
from core.agent_runner.maintenance_runs import (
    _delete_evolution_parts_dir,
    _salvage_evolution_out,
    run_evolution,
)
from core.agent_runner.runner import AgentRunner
from core.evolution import (
    ContractError,
    read_contract,
    watermarks_path,
)

FIXED_RUN_ID = "evo-salvage-fixed"

VALID_ITEM = {
    "project": "proj",
    "date_section": "2026-09-27",
    "section": "浪费",
    "title": "抢救测试条目",
    "impact": "i",
    "evidence": "e",
    "analysis": "a",
    "suggestion": "s",
    "verdict": {
        "problem_exists": "yes",
        "suggestion_sound": "yes",
        "worth_spec": False,
        "rationale": "证据: t.py:1",
    },
    "analysis_md": "## 分析\n结论：不存在问题。",
    "spec": None,
}


def _item(title: str) -> dict:
    return {**VALID_ITEM, "title": title}


class _ListLogger:
    """记录 info/warning 的最小日志替身（断言 INFO 抢救说明用）。"""

    def __init__(self):
        self.infos = []
        self.warnings = []

    def info(self, tag, msg):
        self.infos.append((tag, msg))

    def warning(self, tag, msg):
        self.warnings.append((tag, msg))


class _SalvageRunner(AgentRunner):
    """绕过 __init__ 装配的 AgentRunner 替身。

    raises 非空时 _run_agent 抛异常（模拟 CLI 非零退出）；write_out 为真
    时先写出契约产物再抛——覆盖「写完产物 CLI 才败」现场。
    """

    def __init__(self, proot: Path, *, raises: str = None,
                 write_out: bool = False, out_items: list = None):
        self.project_root = Path(proot)
        self.config = {}
        self.state_machine = None
        self.logger = _ListLogger()
        self.worktree_manager = None
        self.tokens = []
        self._raises = raises
        self._write_out = write_out
        self._out_items = out_items

    def _run_agent(self, prompt, cwd, run_id, model_override=None,
                    env_overrides=None, resume_session_id=None,
                    max_turns=None, spec_name=None, agent_type=None):
        if self._write_out:
            self._write_contract(cwd, run_id)
        if self._raises:
            raise RuntimeError(self._raises)
        return "", 3, "session-1", {"input_tokens": 1, "output_tokens": 1}

    def _write_contract(self, cwd, run_id):
        out = {
            "run_id": run_id,
            "degraded": None,
            "items": list(self._out_items if self._out_items is not None
                          else [VALID_ITEM]),
        }
        out_path = (Path(cwd) / ".fenix" / "evolution"
                    / f"out-{run_id}.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, ensure_ascii=False),
                            encoding="utf-8")

    def _build_prompt(self, spec_name, agent_type, detail=None, wt_path=None):
        return "fake prompt"

    def _get_agent_model_assignment(self, agent_type):
        return None

    def _get_admin_model(self):
        return "DEFAULT_MODEL"

    def _get_config(self, key, default=None):
        from core.config import ConfigLoader
        return ConfigLoader.get(self.config, key, default)

    def _ensure_agent_config_dir(self, provider_name, provider_model=""):
        d = self.project_root / ".fenix" / "cc" / provider_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _extract_usage_info(self, result_event):
        return {"input_tokens": 0, "output_tokens": 0}

    def _accumulate_evolution_tokens(self, run_id, usage_info):
        self.tokens.append(run_id)


def _fixed_run_id_patch():
    return mock.patch.object(
        maintenance_runs,
        "_unique_evolution_run_id",
        return_value=FIXED_RUN_ID,
    )


class _SalvageCase(unittest.TestCase):
    """公共 tmp 树与路径装配。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)
        self.evo_dir = self.proot / ".fenix" / "evolution"
        self.out_path = self.evo_dir / f"out-{FIXED_RUN_ID}.json"
        self.parts_dir = Path(f"{self.out_path}.parts")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_part(self, name: str, item: dict):
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        (self.parts_dir / name).write_text(
            json.dumps(item, ensure_ascii=False), encoding="utf-8"
        )

    def _run(self, runner, pending_entries=None):
        with _fixed_run_id_patch():
            return run_evolution(runner, ["proj"], pending_entries or [])

    def _watermark_snapshot(self):
        wm = watermarks_path(self.proot)
        return wm.read_text(encoding="utf-8") if wm.exists() else None

    @staticmethod
    def _ingested_titles(proot: Path) -> list:
        """items.jsonl 里已落地条目的 title 序列（run 后产物已被既有清理
        删除，落地记录才是抢救读取发生的证据）。"""
        items_file = Path(proot) / ".fenix" / "evolution" / "items.jsonl"
        if not items_file.exists():
            return []
        titles = []
        for line in items_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                titles.append(json.loads(line).get("title"))
        return titles


class TestRunEvolutionSalvage(_SalvageCase):
    """任务 2.1：五类抢救场景。"""

    def test_out_written_but_claude_failed_ingests_success(self):
        """产物已写但 CLI 非零退出：按成功落地，落 INFO，不被静默删除。"""
        runner = _SalvageRunner(
            self.proot, raises="exit code 1", write_out=True,
            out_items=[_item("甲")],
        )
        result = self._run(runner, pending_entries=[{"id": "x1"}])
        self.assertTrue(result.success)
        self.assertEqual(result.items_ingested, 1)
        self.assertEqual(result.error, "")
        # 落地发生 = 产物先被读取（非静默删除）
        self.assertTrue((self.evo_dir / "items.jsonl").exists())
        # INFO 说明 CLI 退出异常
        self.assertTrue(
            any("CLI 退出异常" in msg for _, msg in runner.logger.infos),
            runner.logger.infos,
        )

    def test_missing_out_with_parts_merged_and_recovered(self):
        """产物缺失但有分片：合并恢复、按成功落地、分片目录清理。"""
        self._write_part("01.json", _item("分片甲"))
        self._write_part("02.json", _item("分片乙"))
        runner = _SalvageRunner(self.proot, raises="exit code 1")
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertEqual(result.items_ingested, 2)
        # 合并按 sorted(glob) 配方恢复；items.jsonl 按 id 排序存储，
        # 断言恢复条目集合（title 顺序不作依赖）。run 后产物已被既有
        # 清理删除，落地记录即读取发生的证据
        self.assertEqual(sorted(self._ingested_titles(self.proot)),
                         ["分片乙", "分片甲"])
        self.assertFalse(self.parts_dir.exists())

    def test_missing_out_and_empty_parts_reports_not_written(self):
        """产物缺失且分片为空：报「产物文件未写出」，清理残片目录。"""
        self.parts_dir.mkdir(parents=True)
        (self.parts_dir / "README.txt").write_text("残片垃圾", encoding="utf-8")
        runner = _SalvageRunner(self.proot, raises="exit code 1")
        result = self._run(runner)
        self.assertFalse(result.success)
        self.assertIn("产物文件未写出", result.error)
        # 清理范围含 .parts 残片目录（非 json 残片一并清除）
        self.assertFalse(self.parts_dir.exists())

    def test_unparsable_out_with_parts_overwritten(self):
        """产物存在但 JSON 不可解析且有分片：合并覆盖恢复后按成功落地。"""
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text('{"items": [{"trunc', encoding="utf-8")
        self._write_part("only.json", _item("唯一分片"))
        runner = _SalvageRunner(self.proot, raises="exit code 1")
        result = self._run(runner)
        self.assertTrue(result.success)
        self.assertEqual(result.items_ingested, 1)
        self.assertEqual(self._ingested_titles(self.proot), ["唯一分片"])

    def test_partial_items_fail_without_watermark_advance(self):
        """分片条目数不足：按失败落地（缺失数入 error）且水位不推进。"""
        self._write_part("01.json", _item("仅存的一条"))
        pending = [{"id": f"e{i}"} for i in range(3)]
        before = self._watermark_snapshot()
        runner = _SalvageRunner(self.proot, raises="exit code 1")
        result = self._run(runner, pending_entries=pending)
        self.assertFalse(result.success)
        self.assertIn("缺失 2 条", result.error)
        # 已恢复条目仍落地（幂等去重由下轮补齐）
        self.assertEqual(result.items_ingested, 1)
        # 水位不推进：watermarks 文件在 run 前后不变
        self.assertEqual(self._watermark_snapshot(), before)

    def test_partial_recovery_with_matching_count_succeeds(self):
        """恢复条目数与待分析条目数一致：按成功落地（对照场景五）。"""
        self._write_part("01.json", _item("甲"))
        self._write_part("02.json", _item("乙"))
        pending = [{"id": "e1"}, {"id": "e2"}]
        runner = _SalvageRunner(self.proot, raises="exit code 1")
        result = self._run(runner, pending_entries=pending)
        self.assertTrue(result.success)
        self.assertEqual(result.items_ingested, 2)


class TestPartialAcceptContract(_SalvageCase):
    """evo-add-evolution-contract-partial-accept 任务 2.1：单条非法宽口径。

    run_evolution 以 lenient read_contract 读取：单条契约错误只牺牲该条，
    合法条目照常落库但按失败落地（水位不推进）；失败现场产物文件按
    design D4 改名 ``.failed`` 留档；全部条目非法仍整体拒绝。
    """

    def test_single_invalid_section_partial_accept(self):
        """单条非法小节：跳该条、其余登记落库、按失败落地水位不推进。"""
        invalid = {**_item("越界条目"), "section": "流程"}
        runner = _SalvageRunner(
            self.proot, write_out=True,
            out_items=[_item("甲"), invalid, _item("乙")],
        )
        before = self._watermark_snapshot()
        result = self._run(
            runner,
            pending_entries=[{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
        )
        # 合法条目照常落库，非法条目不登记
        self.assertEqual(result.items_ingested, 2)
        self.assertEqual(sorted(self._ingested_titles(self.proot)), ["乙", "甲"])
        # 按失败落地：run_ok=False、错误附逐条原因（下检查点幂等补齐）
        self.assertFalse(result.success)
        self.assertIn("部分接受", result.error)
        self.assertIn("items[1]", result.error)
        self.assertIn("三值枚举", result.error)
        # 失败现场留档（design D4）：原产物改名 .failed 同目录保留且内容完整
        failed_path = Path(f"{self.out_path}.failed")
        self.assertTrue(failed_path.exists())
        self.assertFalse(self.out_path.exists())
        self.assertIn(str(failed_path), result.error)
        failed = json.loads(failed_path.read_text(encoding="utf-8"))
        self.assertEqual(len(failed["items"]), 3)
        # 水位不推进：watermarks 文件在 run 前后不变
        self.assertEqual(self._watermark_snapshot(), before)

    def test_all_items_invalid_still_rejected(self):
        """全部条目非法：仍整体拒绝（D3 fail-closed），现场不留档。"""
        runner = _SalvageRunner(
            self.proot, write_out=True,
            out_items=[
                {**_item("甲"), "section": "流程"},
                {**_item("乙"), "verdict": None},
            ],
        )
        result = self._run(runner)
        self.assertFalse(result.success)
        self.assertEqual(result.items_ingested, 0)
        self.assertIn("全部 2 条条目契约非法", result.error)
        # 全非法拒绝路径行为与现状一致（design D4：不扩大留档面，含清理）
        self.assertFalse(self.out_path.exists())
        self.assertFalse(Path(f"{self.out_path}.failed").exists())
        self.assertFalse((self.evo_dir / "items.jsonl").exists())


class TestSalvageHelper(_SalvageCase):
    """_salvage_evolution_out 合并配方单元行为。"""

    def test_noop_when_out_parsable(self):
        """产物完整可解析：不覆盖（契约字段级问题交 read_contract 分级）。"""
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.out_path.write_text('{"items": []}', encoding="utf-8")
        self._write_part("01.json", _item("不应并入"))
        got = _salvage_evolution_out(self.out_path)
        self.assertIsNone(got)
        self.assertEqual(
            json.loads(self.out_path.read_text(encoding="utf-8")),
            {"items": []},
        )

    def test_noop_when_parts_missing_or_empty(self):
        """无分片目录 / 目录为空：返回 None，不触碰产物。"""
        self.assertIsNone(_salvage_evolution_out(self.out_path))
        self.parts_dir.mkdir(parents=True)
        (self.parts_dir / "note.txt").write_text("x", encoding="utf-8")
        self.assertIsNone(_salvage_evolution_out(self.out_path))
        self.assertFalse(self.out_path.exists())

    def test_corrupt_parts_skipped(self):
        """损坏分片跳过，不阻塞其余分片恢复。"""
        self._write_part("00.json", _item("好分片"))
        self.parts_dir.mkdir(parents=True, exist_ok=True)
        (self.parts_dir / "01.json").write_text("{broken", encoding="utf-8")
        (self.parts_dir / "02.json").write_text('["非对象"]', encoding="utf-8")
        got = _salvage_evolution_out(self.out_path)
        self.assertEqual(got, 1)
        merged = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual([it["title"] for it in merged["items"]], ["好分片"])

    def test_delete_parts_dir_idempotent(self):
        """残片目录清理幂等安全（目录缺失不抛）。"""
        _delete_evolution_parts_dir(self.out_path)  # 不存在 → 静默
        self._write_part("01.json", _item("x"))
        _delete_evolution_parts_dir(self.out_path)
        self.assertFalse(self.parts_dir.exists())
        _delete_evolution_parts_dir(self.out_path)  # 已删 → 静默


class TestReadContractMessageSplit(unittest.TestCase):
    """任务 2.2：read_contract 失败文案分级断言。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proot = Path(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_reports_not_written(self):
        with self.assertRaises(ContractError) as ctx:
            read_contract(self.proot / "out-none.json")
        self.assertIn("产物文件未写出", str(ctx.exception))

    def test_invalid_json_reports_unparsable(self):
        p = self.proot / "out-bad.json"
        p.write_text('{"items": [{truncated', encoding="utf-8")
        with self.assertRaises(ContractError) as ctx:
            read_contract(p)
        self.assertIn("产物 JSON 不可解析", str(ctx.exception))

    def test_messages_distinguishable(self):
        """两种文案互不包含，告警与日志可直接判别失败面。"""
        p = self.proot / "out-bad.json"
        p.write_text("not json", encoding="utf-8")
        try:
            read_contract(p)
        except ContractError as e_invalid:
            invalid_msg = str(e_invalid)
        try:
            read_contract(self.proot / "out-missing.json")
        except ContractError as e_missing:
            missing_msg = str(e_missing)
        self.assertIn("产物 JSON 不可解析", invalid_msg)
        self.assertNotIn("产物文件未写出", invalid_msg)
        self.assertIn("产物文件未写出", missing_msg)
        self.assertNotIn("产物 JSON 不可解析", missing_msg)

    def test_other_validation_messages_unaffected(self):
        """既有契约校验文案不随分级改动漂移（回归保护）。"""
        p = self.proot / "out-noitems.json"
        p.write_text("{}", encoding="utf-8")
        with self.assertRaises(ContractError) as ctx:
            read_contract(p)
        self.assertIn("items", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
