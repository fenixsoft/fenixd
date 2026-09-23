"""产物归属校验测试（add-task-artifact-ownership-gate）。

覆盖：
- 5.1 判据矩阵（路径限定 + 产出动词 + 无代码文件 → 违规；写代码让框架产出放行；
  裸产物字面量放行；未登记侧车放行；无关任务放行）
- 5.2 执行车道比对（full 违规；fast-track 对 test_scenarios.json 合法、
  report.json 仍违规；mode 缺失保守 full；读取异常保守 full）
- 5.3 归属表断言（六条核心产物 + 目录级；验证链不含 implementer）
- 5.4 零误拦回归（扫描 HEAD 已提交态 spec/changes/ + spec/archive/ 下全部
  tasks.md——读 HEAD 不读工作区，规避 daemon 实时写 spec 的瞬态竞态）
- 5.5 fail-open（lint 自身故障返回空违规清单）
"""

from __future__ import annotations

import glob
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.artifact_ownership import (
    IMPL_RESULT_FILE_OWNERS,
    VERIFICATION_ARTIFACT_OWNERS,
    VERIFY_PROGRESS_DIR_OWNERS,
    ownership_violations_for_task_line,
)
from core.deliverables import (
    _resolve_lane_for_spec_dir,
    lint_tasks_parseable,
    lint_tasks_text,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 5.1 判据矩阵
# ═══════════════════════════════════════════════════════════════════════════════

class TestOwnershipViolationMatrix:
    """5.1 判据矩阵——三重合取才判违规，放行形态全部覆盖。"""

    def test_violation_persist_his_lane_artifact(self):
        """场景：要求实现者持久化他车道产物 → 判违规。"""
        line = (
            "- [ ] 6.2 写 .fenix-run-result.json，"
            "并持久化场景集与结果到 .fenix/verify-progress/<spec>/"
        )
        v = ownership_violations_for_task_line(line, "full")
        assert len(v) == 1
        assert ".fenix/verify-progress/" in v[0]
        assert "实现" in v[0]  # 纠正处方

    def test_violation_path_qualified_report_fast_track(self):
        """场景：fast-track 路径限定产出 report.json → 判违规。"""
        line = "持久化 .fenix/verify-progress/<spec>/report.json"
        v = ownership_violations_for_task_line(line, "fast-track")
        assert len(v) == 1
        assert "report.json" in v[0]

    def test_no_violation_bare_report_json(self):
        """场景：裸 report.json 字面量（未路径限定到 verify-progress）→ 放行。"""
        line = "spec 戳计算：specs/report.json 内容 sha256 前 16 位"
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_bare_scenarios_json(self):
        """场景：裸 scenarios.json 字面量（非 verify-progress 路径）→ 放行。"""
        line = "spec 戳计算：spec/changes/<spec>/spec.md 与 specs/scenarios.json 内容 sha256"
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_impl_result_bare(self):
        """场景：实现者写自己的 .fenix-run-result.json 收工票据（无 verify-progress）→ 放行。"""
        line = "写 .fenix-run-result.json（含 completed_tasks）"
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_unregistered_sidecar(self):
        """场景：写入未登记侧车文件 → 放行。"""
        line = (
            '门入口把 {"round": …} '
            "写入 .fenix/verify-progress/<spec>/scenario_reroute_stoploss.json"
        )
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_write_code_for_framework(self):
        """场景：写代码让框架产出该文件（含代码文件引用）→ 放行。"""
        line = (
            "新增 core/agent_runner/prompt_builder.py，"
            "持久化 test_scenarios.json 到 .fenix/verify-progress/<spec>/"
        )
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_code_path_in_line(self):
        """场景：任务行含代码路径特征 → 放行。"""
        line = (
            "新增 parses 函数把 test_scenarios.json 生成逻辑"
            "抽到 core/artifact_ownership.py"
        )
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_unrelated_task(self):
        """场景：与验证产物无关的任务 → 放行。"""
        line = "与验证产物无关的任务"
        v = ownership_violations_for_task_line(line, "full")
        assert v == []

    def test_no_violation_no_production_verb(self):
        """场景：有路径限定但无产出动词 → 放行。"""
        line = "读取 .fenix/verify-progress/<spec>/report.json 内容做校验"
        v = ownership_violations_for_task_line(line, "full")
        assert v == []


# ═══════════════════════════════════════════════════════════════════════════════
# 5.2 执行车道比对
# ═══════════════════════════════════════════════════════════════════════════════

class TestLaneComparison:
    """5.2 执行车道比对——lane ∉ 归属集合才判违规。"""

    def test_full_lane_artifact_violation(self):
        """full 车道要求产出验证产物 → 判违规。"""
        line = (
            "生成并落盘 test_scenarios.json 到 .fenix/verify-progress/<spec>/"
        )
        v = ownership_violations_for_task_line(line, "full")
        assert len(v) == 1

    def test_fast_track_test_scenarios_legal(self):
        """fast-track 车道自行出题 test_scenarios.json → 合法。"""
        line = (
            "生成并落盘 test_scenarios.json 到 .fenix/verify-progress/<spec>/"
        )
        v = ownership_violations_for_task_line(line, "fast-track")
        assert v == []

    def test_fast_track_scenarios_legal(self):
        """fast-track 车道产出 scenarios.json → 合法。"""
        line = (
            "持久化 .fenix/verify-progress/<spec>/scenarios.json"
        )
        v = ownership_violations_for_task_line(line, "fast-track")
        assert v == []

    def test_fast_track_report_violation(self):
        """fast-track 车道产出 report.json → 仍判违规（report.json 归属仅 verify_engine）。"""
        line = "持久化 .fenix/verify-progress/<spec>/report.json"
        v = ownership_violations_for_task_line(line, "fast-track")
        assert len(v) == 1

    def test_pm_engine_scenarios_legal(self):
        """pm_engine 车道产出 scenarios.json → 合法。"""
        line = "持久化 .fenix/verify-progress/<spec>/scenarios.json"
        v = ownership_violations_for_task_line(line, "pm_engine")
        assert v == []

    def test_planner_judge_result_legal(self):
        """planner-judge 车道写 .fenix-run-result.json → 合法。"""
        line = "写 .fenix/verify-progress/<spec>/.fenix-run-result.json"
        v = ownership_violations_for_task_line(line, "planner-judge")
        assert v == []

    def test_full_planner_judge_result_violation(self):
        """full 车道写 planner-judge 结果文件 → 判违规。"""
        line = "写 .fenix/verify-progress/<spec>/.fenix-run-result.json"
        v = ownership_violations_for_task_line(line, "full")
        assert len(v) == 1

    def test_dir_ref_full_violation(self):
        """full 车道持久化到 verify-progress 目录 → 判违规。"""
        line = "持久化 .fenix/verify-progress/<spec>/"
        v = ownership_violations_for_task_line(line, "full")
        assert len(v) == 1

    def test_dir_ref_fast_track_legal(self):
        """fast-track 车道持久化到 verify-progress 目录 → 合法。"""
        line = "持久化 .fenix/verify-progress/<spec>/"
        v = ownership_violations_for_task_line(line, "fast-track")
        assert v == []


class TestResolveLane:
    """5.2 _resolve_lane_for_spec_dir：mode 缺失保守 full；异常保守 full。"""

    def test_mode_missing_returns_full(self):
        """无 .spec.yaml → lane = full。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec_dir = root / "spec" / "changes" / "demo"
            spec_dir.mkdir(parents=True)
            assert _resolve_lane_for_spec_dir(spec_dir) == "full"

    def test_mode_full_returns_full(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec_dir = root / "spec" / "changes" / "demo"
            spec_dir.mkdir(parents=True)
            (spec_dir / ".spec.yaml").write_text("mode: full\n", encoding="utf-8")
            assert _resolve_lane_for_spec_dir(spec_dir) == "full"

    def test_mode_fast_track_returns_fast_track(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec_dir = root / "spec" / "changes" / "demo"
            spec_dir.mkdir(parents=True)
            (spec_dir / ".spec.yaml").write_text("mode: fast-track\n", encoding="utf-8")
            assert _resolve_lane_for_spec_dir(spec_dir) == "fast-track"

    def test_mode_invalid_returns_full(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec_dir = root / "spec" / "changes" / "demo"
            spec_dir.mkdir(parents=True)
            (spec_dir / ".spec.yaml").write_text("mode: unknown\n", encoding="utf-8")
            assert _resolve_lane_for_spec_dir(spec_dir) == "full"

    def test_read_exception_returns_full(self):
        """spec_dir 不在预期位置（异常保守 full）。"""
        with tempfile.TemporaryDirectory() as td:
            # spec_dir 不含 /spec/changes/<spec> 结构
            bad_dir = Path(td) / "bad"
            bad_dir.mkdir()
            assert _resolve_lane_for_spec_dir(bad_dir) == "full"


# ═══════════════════════════════════════════════════════════════════════════════
# 5.3 归属表断言
# ═══════════════════════════════════════════════════════════════════════════════

class TestOwnershipTable:
    """5.3 归属表断言——六条核心产物 + 目录级 + 验证链不含 implementer。"""

    def test_core_artifacts_count(self):
        """归属表至少含六条核心产物（含目录级条目引用场景）。"""
        # 四条文件级核心产物
        assert "test_scenarios.json" in VERIFICATION_ARTIFACT_OWNERS
        assert "scenarios.json" in VERIFICATION_ARTIFACT_OWNERS
        assert "report.json" in VERIFICATION_ARTIFACT_OWNERS
        assert ".fenix-run-result.json" in VERIFICATION_ARTIFACT_OWNERS
        # 目录级归属独立常量
        assert len(VERIFY_PROGRESS_DIR_OWNERS) >= 5

    def test_verification_artifacts_no_implementer(self):
        """验证链产物归属集合 MUST NOT 含 implementer。"""
        for key, owners in VERIFICATION_ARTIFACT_OWNERS.items():
            assert "implementer" not in owners, (
                f"{key} 的归属集合不得含 implementer"
            )
        # 目录级亦不含 implementer
        assert "implementer" not in VERIFY_PROGRESS_DIR_OWNERS

    def test_impl_result_owners_contain_implementer(self):
        """worktree 根 .fenix-run-result.json 的归属含 implementer（合法收工票据）。"""
        assert "implementer" in IMPL_RESULT_FILE_OWNERS

    def test_test_scenarios_owners(self):
        """test_scenarios.json 归属 planner-plan + fast-track。"""
        owners = VERIFICATION_ARTIFACT_OWNERS["test_scenarios.json"]
        assert owners == {"planner-plan", "fast-track"}

    def test_scenarios_owners(self):
        """scenarios.json 归属 pm_engine + fast-track。"""
        owners = VERIFICATION_ARTIFACT_OWNERS["scenarios.json"]
        assert owners == {"pm_engine", "fast-track"}

    def test_report_owners(self):
        """report.json 归属 verify_engine。"""
        owners = VERIFICATION_ARTIFACT_OWNERS["report.json"]
        assert owners == {"verify_engine"}

    def test_planner_judge_owners(self):
        """.fenix-run-result.json 归属 planner-judge。"""
        owners = VERIFICATION_ARTIFACT_OWNERS[".fenix-run-result.json"]
        assert owners == {"planner-judge"}


# ═══════════════════════════════════════════════════════════════════════════════
# 5.4 零误拦回归
# ═══════════════════════════════════════════════════════════════════════════════

def _collect_tasks_files() -> list[tuple[str, str]]:
    """收集 HEAD 已提交态（spec/changes + spec/archive）全部 tasks.md → (路径, 文本)。

    读 HEAD 而非工作区：本仓库由 fenix daemon 实时写 spec 文件（planner
    起草、任务勾选、归档迁移、merge-back 的 stash 窗口），工作区存在合法的
    未提交中间态——半成品 tasks.md 的可解析性判定必然失败，存量零误拦回归
    被瞬态污染（2026-09-23 全量回归假失败）。spec 目录由 hook 即建即提交，
    HEAD 态即存量全集；回归语料口径 = 版本库已提交内容（确定性、零竞态）。
    """
    ls = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD",
         "spec/changes", "spec/archive"],
        capture_output=True, timeout=30,
    )
    ls.check_returncode()
    paths = sorted(
        ln.decode("utf-8") for ln in ls.stdout.splitlines()
        if ln.decode("utf-8").endswith("tasks.md")
    )
    if not paths:
        return []
    # 单进程批量取 blob（避免逐文件 git show 的 260 次进程 spawn）
    batch_in = "".join(f"HEAD:{p}\n" for p in paths).encode("utf-8")
    batch = subprocess.run(
        ["git", "cat-file", "--batch"],
        input=batch_in, capture_output=True, timeout=60,
    )
    batch.check_returncode()
    result: list[tuple[str, str]] = []
    pos = 0
    data = batch.stdout
    for p in paths:
        # 每条记录形如 b"<sha> blob <size>\n<content>\n"
        header_end = data.index(b"\n", pos)
        size = int(data[pos:header_end].rsplit(b" ", 1)[1])
        content_start = header_end + 1
        result.append(
            (p, data[content_start:content_start + size].decode("utf-8"))
        )
        pos = content_start + size + 1  # 跳过记录尾分隔空行
    return result


class TestZeroFalsePositive:
    """5.4 零误拦回归——除事故真阳性外，既有合法 spec 不得产生产物归属违规。

    回归基线：实测 260 份 tasks.md（spec/changes 61 + spec/archive 199）、
    3424 条任务行。唯一预期违规为 ``fix-verify-serving-disk-reclaim`` 的
    任务 6.2（历史事故任务行）。测试内动态扫描（MUST NOT 硬编码文件数），
    允许的违规集仅为该事故 spec 的 tasks.md（实现期可重写其为零违规，
    两种终局都放行），其余任何文件出现违规即失败。

    允许清单按 spec 名匹配（非完整路径）：该事故 spec 2026-09-23 归档入库后
    文件已迁至 ``spec/archive/2026-09-23-fix-verify-serving-disk-reclaim/``，
    按名匹配使允许清单跟随在册/归档两种位置，归档迁移不再构成「非事故文件」。
    """

    _KNOWN_ACCIDENT_SPEC = "fix-verify-serving-disk-reclaim"

    def test_no_violations_in_existing_specs(self):
        """对全库（changes + archive）既有 tasks.md 运行 lint_tasks_text，
        除事故真阳性文件外不得产生产物归属违规。
        """
        tasks_files = _collect_tasks_files()
        assert len(tasks_files) > 0, "未发现任何 tasks.md 文件（回归基线不可为空）"

        violations_by_file: list[tuple[str, list[str]]] = []
        for tf, text in tasks_files:
            violations = lint_tasks_text(text, lane="full")
            if violations:
                violations_by_file.append((tf, violations))

        unexpected = [
            (tf, vs)
            for tf, vs in violations_by_file
            if self._KNOWN_ACCIDENT_SPEC not in str(tf)
        ]
        if unexpected:
            details = "\n".join(
                f"  {f}: {v[0][:200]}" for f, v in unexpected
            )
            pytest.fail(
                f"存量 tasks.md 零误拦回归失败（{len(unexpected)} 个非事故文件"
                f"产生违规）：\n{details}"
            )


class TestAccidentAnchor:
    """6.3 事故真阳性回归钉——fix-verify-serving-disk-reclaim 任务 6.2 判违规。

    只读断言（MUST NOT 改写该 SPEC 文件），端到端锚点：若该历史事故行在
    新判据下不再违规，说明新规则失效（事故形态漏出），测试即失败。
    """

    _ACCIDENT_SPEC = "fix-verify-serving-disk-reclaim"

    @classmethod
    def _locate_accident_file(cls):
        """事故 SPEC 定位：changes/ 在册优先，归档后回退 archive/<date>-<name>/。

        2026-09-23 归档入库后该文件已迁至
        spec/archive/2026-09-23-fix-verify-serving-disk-reclaim/tasks.md；
        锚点跟随归档继续生效，而非从此 skip 失效。
        """
        candidates = [Path(f"spec/changes/{cls._ACCIDENT_SPEC}/tasks.md")]
        candidates.extend(
            Path(p)
            for p in sorted(
                glob.glob(f"spec/archive/*-{cls._ACCIDENT_SPEC}/tasks.md")
            )
        )
        for c in candidates:
            if c.exists():
                return c
        return None

    def test_accident_line_6_2_flagged(self):
        """任务 6.2（持久化场景集到 verify-progress）在新判据下判违规。"""
        accident_file = self._locate_accident_file()
        if accident_file is None:
            pytest.skip("事故 SPEC 不在 changes/ 且无归档副本，锚点文件不存在")
        text = accident_file.read_text(encoding="utf-8")
        line6_2 = next(
            (
                ln
                for ln in text.splitlines()
                if "6.2 写" in ln and "verify-progress" in ln
            ),
            None,
        )
        assert line6_2 is not None, (
            "事故 SPEC 中未找到任务 6.2 行（锚点断言前提不成立）"
        )
        v = ownership_violations_for_task_line(line6_2, "full")
        assert len(v) == 1, (
            f"事故真阳性 6.2 行未被新判据拦下（漏拦事故形态）：{line6_2[:120]}"
        )
        assert "verify-progress" in v[0]


# ═══════════════════════════════════════════════════════════════════════════════
# 5.5 fail-open
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailOpen:
    """5.5 fail-open——lint 自身故障返回空违规清单、不抛异常。"""

    def test_ownership_violations_exception_returns_empty(self):
        """ownership_violations_for_task_line 内部异常 → 空清单，不抛。"""
        # 制造异常：传入 None 触发 TypeError
        try:
            v = ownership_violations_for_task_line(None, "full")  # type: ignore
            assert v == []
        except Exception:
            pytest.fail("ownership_violations_for_task_line 不应抛出异常")

    def test_lint_tasks_text_ownership_scan_exception_fail_open(self):
        """lint_tasks_text 的产物归属扫描模块导入异常 → fail-open 返回空清单。"""
        # 模拟 ownership_violations_for_task_line 抛异常
        # （lint_tasks_text 内为 `from core.artifact_ownership import ...`，
        # 故 patch 目标是 core.artifact_ownership 模块符号）
        with patch(
            "core.artifact_ownership.ownership_violations_for_task_line",
            side_effect=RuntimeError("mocked failure"),
        ):
            text = "## 1. Setup\n\n- [ ] 1.1 持久化 .fenix/verify-progress/<spec>/report.json\n"
            # 不应抛异常，fail-open 返回空违规
            v = lint_tasks_text(text, lane="full")
            assert v == []
