"""verification-modules 契约测试（refactor-verification-module tasks 7.1 / spec）。

验证拆分重构后的模块组织契约（spec「verification-pipeline-modules」）：

1. 子模块职责边界：9 个职责子模块各自承载 D2 分组方法；
2. `grep "self._pm._"` == 0（私有回引清零）；
3. 大函数仍在 pipeline.py，主函数收敛为编排骨架（内部段落提取为私有方法）；
4. 门面 re-export 完整性：全部既有公开符号可导入；
5. D9 patch 缝隙名仍可从 `core.pm_engine.verification` 访问。
"""

import re
from pathlib import Path

import core.pm_engine.verification as vmod
from core.pm_engine.verification import VerificationPipeline

ROOT = Path(__file__).resolve().parent.parent


# ── 1. 子模块职责边界（D2 分组表）──────────────────────────

MODULE_GROUPS = {
    "pipeline": ("VerificationPipeline",),
    "report_gate": ("_read_verify_report", "_check_verification_gate", "VerdictReadResult"),
    "branch_guard": ("_deliverable_gate_missing", "resolve_env_blocked_reset_path"),
    "infra_classify": ("_verifier_error_is_infra", "reclassify_infra_rounds"),
    "scenario_gate": ("_apply_scenario_freeze", "_apply_interaction_contract"),
    "serving": ("_ensure_serving_worktree", "_ensure_app_reachable"),
    "judge_gate": ("_judge_dispatch_gate", "_all_green_fast_path"),
    "escalation": ("_env_whitewash_gate", "_escalate_env_blocked"),
    "verdict_evidence": ("_verify_verdict_evidence", "_record_verdict_adoption"),
    "legacy": ("_run_legacy_verification",),
}


class TestModuleBoundaries:
    def test_each_module_has_assigned_symbols(self):
        import importlib

        for mod_name, symbols in MODULE_GROUPS.items():
            mod = importlib.import_module(
                f"core.pm_engine.verification.{mod_name}")
            for sym in symbols:
                assert hasattr(mod, sym), f"{mod_name}.{sym} 缺失"

    def test_pipeline_has_verification_pipeline_class(self):
        import importlib

        mod = importlib.import_module("core.pm_engine.verification.pipeline")
        cls = getattr(mod, "VerificationPipeline", None)
        assert cls is not None, "pipeline.py 缺少 VerificationPipeline 类"
        assert hasattr(cls, "_run_three_stage_verification"), \
            "VerificationPipeline 缺少 _run_three_stage_verification"


# ── 2. 私有回引为 0 ─────────────────────────────────────

class TestNoPrivateBackrefs:
    def test_no_self_pm_private_in_pipeline(self):
        text = (ROOT / "core/pm_engine/verification/pipeline.py").read_text(encoding="utf-8")
        hits = re.findall(r"self\._pm\._", text)
        assert not hits, f"pipeline.py 残留 self._pm._ 回引: {len(hits)} 处"

    def test_no_self_pm_private_in_submodules(self):
        for mod in MODULE_GROUPS:
            if mod == "pipeline":
                continue
            path = ROOT / f"core/pm_engine/verification/{mod}.py"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            hits = re.findall(r"self\._pm\._", text)
            assert not hits, f"{mod}.py 残留 self._pm._ 回引: {len(hits)} 处"


# ── 3. 大函数仅搬移 ───────────────────────────────────

class TestThreeStageWholeMove:
    def test_run_three_stage_in_pipeline(self):
        from core.pm_engine.verification.pipeline import VerificationPipeline as VP

        assert hasattr(VP, "_run_three_stage_verification")

    def test_run_three_stage_is_method_not_reassign(self):
        """大函数以方法体存在（非运行时赋值），且不在其它子模块承载体。"""
        src = (ROOT / "core/pm_engine/verification/pipeline.py").read_text(encoding="utf-8")
        # def 定义（非赋值）
        assert re.search(r"def _run_three_stage_verification\(", src) is not None
        for mod in MODULE_GROUPS:
            if mod == "pipeline":
                continue
            path = ROOT / f"core/pm_engine/verification/{mod}.py"
            if not path.exists():
                continue
            body = path.read_text(encoding="utf-8")
            assert re.search(r"def _run_three_stage_verification\(", body) is None, \
                f"{mod}.py 重复承载 _run_three_stage_verification"


# ── 4. 门面 re-export 完整性 ──────────────────────────

class TestFacadeReexports:
    SYMBOLS = [
        "VerificationPipeline", "VerdictReadResult", "reclassify_infra_rounds",
        "resolve_env_blocked_reset_path", "_branch_merged_into_tree",
        "_SCENARIO_REPAIR_MAX_ROUNDS", "_MAX_JUDGE_RERUNS",
        "RECLASSIFY_SIGNAL_TYPE", "POST_READY_SETTLE_SECONDS",
        "LEGACY_START_PROBE_ATTEMPTS", "LEGACY_START_PROBE_INTERVAL_SECONDS",
        "ENV_BLOCK_SIGNAL_TYPES", "ENV_BLOCK_MERGE_CHECK_TIMEOUT_SECONDS",
        "PipelineContext",
    ]

    def test_all_public_symbols_importable(self):
        missing = [s for s in self.SYMBOLS if not hasattr(vmod, s)]
        assert not missing, f"门面缺失符号: {missing}"


# ── 5. D9 patch 缝隙名 ─────────────────────────────────

class TestD9PatchGap:
    NAMES = ["subprocess", "time", "probe_ready", "ensure_main_tree_deps",
             "run_prepare_steps", "load_verify_contract", "rewrite_scenarios_origin"]

    def test_d9_names_accessible(self):
        for name in self.NAMES:
            assert hasattr(vmod, name), f"门面缺失 D9 patch 名 {name}"