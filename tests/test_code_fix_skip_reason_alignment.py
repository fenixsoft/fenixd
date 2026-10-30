"""tests/test_code_fix_skip_reason_alignment.py — evo-align-codefix-skip-reason-enum

覆盖：
- 1.1/2.2 读侧 skip_reason 前缀归一：strip 后以 IGNORE_ELIGIBLE_SKIP_REASONS
  任一枚举值开头即命中豁免硬出口（整串相等快路径不回归）；命中条目的
  ignored 理由 = skip_reason 完整原文 + 可选 reason 字段组装；缺失/非字符
  串按未命中处理不抛异常；(no_marker) 后缀命中（过渡形态互认）。
- 1.2 脱靶可观测：非空字符串、既不命中白名单（裸值/前缀）也不属既有
  skipped 词汇表（unfixable/needs_human）的 skipped 行记 warning（含
  item_id 与原文）且不进豁免硬出口；词汇表成员与缺省/非字符串静默。
- 1.3 链级零进度护栏：连续 2 轮终局 rollup 零核销 → admin 信号落告警面
  + 暂停自动重派（checkpoint 拦截、phase=blocked/reason=zero_progress_paused
  文案分流）；仅 1 轮零进度不触发；出现 resolved/ignored>0 的轮次计数归零；
  解除路径——人工处置（override_enabled 手动入口）即时解除、新一轮评审
  产出台账变更（open 集合 ≠ 暂停快照）选批扫描复核解除。

MUST NOT 真跑 agent——分区判定为纯函数单测；护栏经 fake runner + 真 git
仓 worktree 替身驱动 checkpoint（沿 tests/test_codefix_digest_metrics.py
同款装配）。
"""

import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.agent_runner.maintenance_runs as maintenance_runs_module
from core.code_fix import (
    IGNORE_ELIGIBLE_SKIP_REASONS,
    CodeFixOrchestrator,
    _split_fix_rows,
    mark_ignored,
    read_items,
    read_progress,
    skip_reason_hit_whitelist,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# /tmp 可能被外部清扫进程周期性清空。统一用仓库内 .history/tmp（gitignored）。
_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


class _RecLogger:
    """捕获日志的 fake logger（编排器/分区 lenient 形如 logger.warning(tag, msg)）。"""

    def __init__(self):
        self.records = []

    def _rec(self, level):
        def _f(tag, msg):
            self.records.append((level, tag, msg))
        return _f

    def debug(self, tag, msg):
        self._rec("debug")(tag, msg)

    def info(self, tag, msg):
        self._rec("info")(tag, msg)

    def warning(self, tag, msg):
        self._rec("warning")(tag, msg)

    def error(self, tag, msg):
        self._rec("error")(tag, msg)


# ═════════════════════════════════════════════════════════════════════════════
# 3.1 skip_reason 对齐（读侧分区纯函数）
# ═════════════════════════════════════════════════════════════════════════════


class TestSkipReasonWhitelist:
    """白名单命中判定（1.1）：裸枚举快路径 + 前缀归一 + 非法形态安全。"""

    def test_bare_enums_hit(self):
        """裸枚举整串相等快路径：行为与历史完全一致（向后兼容）。"""
        for v in IGNORE_ELIGIBLE_SKIP_REASONS:
            assert skip_reason_hit_whitelist(v) is True

    def test_suffixed_reasons_hit(self):
        """带后缀解释的过渡形态：strip 后以枚举值开头即命中（spec 场景形态）。"""
        assert skip_reason_hit_whitelist(
            "false_positive (位置已有 fenix-ignore:5ae61ac429c4 标记，理由仍适用)"
        )
        assert skip_reason_hit_whitelist(
            "not_worth_fixing (纯风格问题，修复风险大于收益)"
        )

    def test_no_marker_suffix_hit(self):
        """模板历史 (no_marker) 尾注：前缀归一命中，不因模板收紧脱靶。"""
        assert skip_reason_hit_whitelist(
            "false_positive (no_marker)"
        )

    def test_surrounding_whitespace_hit(self):
        """首尾空白：strip 后命中。"""
        assert skip_reason_hit_whitelist("  false_positive  ")

    def test_missing_and_non_string_miss_without_raise(self):
        """缺失/None/非字符串按未命中处理，MUST NOT 抛异常。"""
        for bad in (None, 42, 1.5, True, ["false_positive"], {"a": 1}, b"fp"):
            assert skip_reason_hit_whitelist(bad) is False

    def test_unrelated_and_vocab_miss(self):
        """无关值与既有出口词汇不命中（不进豁免硬出口）。"""
        for miss in ("unfixable", "needs_human", "", "   ", "误报", "cannot_fix"):
            assert skip_reason_hit_whitelist(miss) is False


class TestSplitFixRowsAlignment:
    """分区口径（1.1/1.2/2.2）：命中组装、裸枚举不回归、脱靶 warning。"""

    def test_suffixed_hit_composes_full_text_into_reasons(self):
        """带后缀 skip_reason 命中且完整原文入 reasons（含后缀解释）。"""
        raw = "false_positive (位置已有 fenix-ignore:xxx 标记，理由仍适用)"
        rows = [{"item_id": "a", "status": "skipped", "skip_reason": raw}]
        fixed_ids, skip_reasons = _split_fix_rows(rows)
        assert fixed_ids == []
        assert skip_reasons == {"a": raw}

    def test_reason_field_merged_into_ignored_text(self):
        """reason 字段（2.2）并入 ignored 理由原文。"""
        rows = [{
            "item_id": "a", "status": "skipped",
            "skip_reason": "not_worth_fixing",
            "reason": "纯风格问题，修复风险大于收益",
        }]
        _, skip_reasons = _split_fix_rows(rows)
        assert skip_reasons["a"] == (
            "not_worth_fixing；reason: 纯风格问题，修复风险大于收益"
        )

    def test_suffixed_with_reason_field_both_present(self):
        """带后缀 + reason 字段同时在场：原文与 reason 并存。"""
        rows = [{
            "item_id": "a", "status": "skipped",
            "skip_reason": "false_positive (no_marker)",
            "reason": "非代码文件无法安放注释",
        }]
        _, skip_reasons = _split_fix_rows(rows)
        assert skip_reasons["a"] == (
            "false_positive (no_marker)；reason: 非代码文件无法安放注释"
        )

    def test_reason_only_row_stays_open(self):
        """仅写 reason 未写（可忽略）skip_reason：不命中白名单、保持 open、
        按「缺省」静默（无 skip_reason 不告警）。"""
        cap = _RecLogger()
        rows = [{"item_id": "a", "status": "skipped",
                 "reason": "误报（未标注枚举）"}]
        _, skip_reasons = _split_fix_rows(rows, logger=cap)
        assert skip_reasons == {}
        assert cap.records == []

    def test_bare_enum_regression(self):
        """裸枚举行为不回归：值与历史逐字一致（既有用例口径）。"""
        rows = [
            {"item_id": "b", "status": "skipped", "skip_reason": "false_positive"},
            {"item_id": "c", "status": "skipped",
             "skip_reason": "not_worth_fixing"},
            {"item_id": "d", "status": "skipped", "skip_reason": "unfixable"},
            {"item_id": "e", "status": "skipped"},
            {"item_id": "f", "status": "skipped", "skip_reason": "needs_human"},
        ]
        _, skip_reasons = _split_fix_rows(rows)
        assert skip_reasons == {
            "b": "false_positive", "c": "not_worth_fixing",
        }

    def test_retry_fixed_wins_over_earlier_skip(self):
        """并集口径不回归：首轮 skipped 判误报、重试轮 fixed → 以 fixed 为准。"""
        rows = [
            {"item_id": "a", "status": "skipped",
             "skip_reason": "false_positive (x)"},
            {"item_id": "a", "status": "fixed"},
        ]
        fixed_ids, skip_reasons = _split_fix_rows(rows)
        assert fixed_ids == ["a"]
        assert skip_reasons == {}

    def test_offtarget_value_warns_and_stays_open(self):
        """脱靶值：warning 留痕（含 item_id 与原文）且不进豁免硬出口。"""
        cap = _RecLogger()
        rows = [{"item_id": "a", "status": "skipped",
                 "skip_reason": "cannot_reproduce_anything"}]
        _, skip_reasons = _split_fix_rows(rows, logger=cap)
        assert skip_reasons == {}
        warns = [r for r in cap.records if r[0] == "warning"]
        assert len(warns) == 1, cap.records
        assert "item_id=a" in warns[0][2]
        assert "cannot_reproduce_anything" in warns[0][2]

    def test_vocab_and_missing_and_non_string_silent(self):
        """unfixable/needs_human/缺省/非字符串 skip_reason 静默且不抛异常。"""
        cap = _RecLogger()
        rows = [
            {"item_id": "a", "status": "skipped", "skip_reason": "unfixable"},
            {"item_id": "b", "status": "skipped", "skip_reason": "needs_human"},
            {"item_id": "c", "status": "skipped"},
            {"item_id": "d", "status": "skipped", "skip_reason": None},
            {"item_id": "e", "status": "skipped", "skip_reason": 42},
            {"item_id": "f", "status": "skipped", "skip_reason": ["x"]},
        ]
        _, skip_reasons = _split_fix_rows(rows, logger=cap)
        assert skip_reasons == {}
        assert cap.records == [], "词汇表成员/缺省/非字符串 MUST 静默"

    def test_fixed_rows_never_warn(self):
        """最终态 fixed 的条目不因历史 skipped 行告警（以 fixed 为准）。"""
        cap = _RecLogger()
        rows = [
            {"item_id": "a", "status": "skipped",
             "skip_reason": "cannot_reproduce_anything"},
            {"item_id": "a", "status": "fixed"},
        ]
        fixed_ids, skip_reasons = _split_fix_rows(rows, logger=cap)
        assert fixed_ids == ["a"]
        assert skip_reasons == {}
        assert cap.records == []


class TestIgnoredRoundTrip:
    """组装理由经 mark_ignored 落台账（1.1/2.2 端到端）。"""

    def test_mark_ignored_records_composed_reason(self):
        proot = Path(_mkdtemp("skipalign-"))
        (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
        rec = {"item_id": "a", "status": "open", "file": "x/a.py", "line": 1,
               "severity": "major", "category": "correctness", "title": "t",
               "description": "d", "suggestion": "s", "fingerprint": "fp-a"}
        (proot / ".fenix" / "code-review" / "items.jsonl").write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        rows = [{
            "item_id": "a", "status": "skipped",
            "skip_reason": "false_positive (位置已有 fenix-ignore:xxx 标记)",
            "reason": "标记理由仍适用",
        }]
        _, skip_reasons = _split_fix_rows(rows)
        assert mark_ignored(proot, list(skip_reasons), reasons=skip_reasons) == 1
        items = read_items(proot)
        assert items["a"]["status"] == "ignored"
        assert items["a"]["ignored_reason"] == (
            "false_positive (位置已有 fenix-ignore:xxx 标记)；reason: 标记理由仍适用"
        )


# ═════════════════════════════════════════════════════════════════════════════
# 3.2 链级零进度护栏（编排侧 checkpoint 驱动）
# ═════════════════════════════════════════════════════════════════════════════


def _make_git_repo() -> Path:
    """最小 git 仓（零有效修复守卫的提交数判据需要真提交）。"""
    repo = Path(_mkdtemp("skipalign-repo-"))
    subprocess.run(["git", "init", "-q", str(repo)], check=True,
                   capture_output=True)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True,
                   capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True)
    return repo


class _FakeWM:
    """fake worktree_manager：create 返回真 git 仓，merge_back 恒成功。"""

    def create(self, spec_name, agent_type="implementer"):
        return _make_git_repo()

    def merge_back(self, wt_path):
        return SimpleNamespace(success=True, error="")

    def release_spec_lock(self, spec_name, agent_type="implementer"):
        return True

    def cleanup(self, wt_path, success=True):
        import shutil
        shutil.rmtree(str(wt_path), ignore_errors=True)


class _ZeroRunner:
    """fake AgentRunner：fix_success 可切换——False=run 失败（零核销轮），
    True=全批 fixed（有进度轮，成功 run 落归档+提交供合回核销）。"""

    def __init__(self, project_root, fix_success=False):
        self.project_root = Path(project_root)
        self._running_agents = {}
        self.config = {}
        self.worktree_manager = _FakeWM()
        self.fix_success = fix_success
        self._run_no = 0
        self.run_ids = []

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None,
                     failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-skipalign-{self._run_no}"
        self.run_ids.append(rid)
        wt = Path(worktree_root)
        out = wt / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        if self.fix_success:
            with out.open("w", encoding="utf-8") as fh:
                for it in items:
                    fh.write(json.dumps(
                        {"item_id": it["item_id"], "status": "fixed",
                         "file": it.get("file", "")}, ensure_ascii=False)
                        + "\n")
            (wt / f"touched-{rid}.txt").write_text("fix", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add",
                 "-A"], cwd=wt, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit",
                 "-q", "-m", f"fix-{rid}"], cwd=wt, check=True,
                capture_output=True)
            archive = self.project_root / ".fenix" / "runs" / f"{rid}.jsonl"
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_text(json.dumps({
                "type": "run_metrics", "run_id": rid, "turns": 3,
                "tool_uses_total": 2, "text_turns": 1,
                "tool_uses": {"Read": 2},
            }) + "\n", encoding="utf-8")
        else:
            out.write_text("", encoding="utf-8")
        return SimpleNamespace(
            run_id=rid, success=self.fix_success,
            fixed=len(items) if self.fix_success else 0,
            skipped=0, error="" if self.fix_success else "agent boom",
            output="done")

    def run_regression(self, spec, reason="manual", project_root=None,
                       lock_root=None, subset_nodeids=None):
        return SimpleNamespace(status="passed", snapshot={"failures": []},
                               error="")


def _make_project_root(item_ids) -> Path:
    """临时项目根：items.jsonl（每条目独立顶层目录）+ 有效 verify.yaml。"""
    proot = Path(_mkdtemp("skipalign-proot-"))
    (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    records = {}
    for iid in item_ids:
        records[iid] = {
            "item_id": iid, "status": "open", "file": f"{iid}/{iid}.py",
            "line": 1, "severity": "major", "category": "correctness",
            "title": f"title {iid}", "description": f"desc {iid}",
            "suggestion": f"sug {iid}", "fingerprint": f"fp-{iid}",
        }
    lines = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n"
        for k in sorted(records)
    )
    (proot / ".fenix" / "code-review" / "items.jsonl").write_text(
        lines, encoding="utf-8")
    (proot / ".fenix" / "verify.yaml").write_text(
        "prepare:\n  - run: 'true'\n"
        "serve:\n  kind: static\n  root: site\n"
        "ready:\n  url: /\n  expect: 200\n"
        "regression:\n  cmd: \"true\"\n"
        "  output: \".fenix/regression/junit.xml\"\n",
        encoding="utf-8")
    return proot


_CFG_BS1 = {"admin": {"code_review_fix": {"enabled": True, "batch_size": 1}}}


@pytest.fixture()
def seq_run_ids(monkeypatch):
    """确定性递增 run_id：规避同秒撞名（真实退避口径依赖时钟，测试不可控）。"""
    counter = itertools.count()

    def _fake_unique(runner, exclude=()):
        rid = f"code-fix-skipalign-{next(counter)}"
        assert rid not in set(exclude or ())
        return rid

    monkeypatch.setattr(
        maintenance_runs_module, "_unique_code_fix_run_id", _fake_unique)
    return counter


def _zero_progress_alerts(proot):
    from core.admin_store import AdminStore

    recs = AdminStore(proot, logger=None).read_all()
    return [r for r in recs
            if r.get("signal_type") == "code_fix_zero_progress_paused"]


def _append_open_item(proot, iid):
    """台账追加一条 open 条目（模拟新一轮评审产出台账变更）。"""
    path = proot / ".fenix" / "code-review" / "items.jsonl"
    rec = {"item_id": iid, "status": "open", "file": f"{iid}/{iid}.py",
           "line": 1, "severity": "major", "category": "correctness",
           "title": f"title {iid}", "description": f"desc {iid}",
           "suggestion": f"sug {iid}", "fingerprint": f"fp-{iid}"}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


class TestZeroProgressGuard:
    """链级零进度护栏（1.3 / spec R4）。"""

    def _orch(self, proot, runner, logger=None):
        return CodeFixOrchestrator(
            runner, proot, config=_CFG_BS1, logger=logger or _RecLogger())

    def test_two_zero_rounds_pause_and_alert(self, seq_run_ids):
        """连续 2 轮零进度：admin 信号落告警面 + 暂停重派 + 进度呈现暂停原因。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        # 第 1 轮：链终局 rollup 零核销 → 计数 1，不触发
        assert orch.checkpoint()["triggered"] is True
        prog = read_progress(proot)
        assert prog["zero_progress_rounds"] == 1
        assert prog["zero_progress_paused"] is False
        assert _zero_progress_alerts(proot) == []

        # 第 2 轮：再零核销 → 计数达 2 → 熔断（信号 + 暂停标记 + open 快照）
        assert orch.checkpoint()["triggered"] is True
        prog = read_progress(proot)
        assert prog["zero_progress_rounds"] == 2
        assert prog["zero_progress_paused"] is True
        assert prog["zero_progress_paused_open_ids"] == ["a"]
        alerts = _zero_progress_alerts(proot)
        assert len(alerts) == 1, "每暂停 episode 恰一条 admin 信号"
        assert "连续 2 轮" in alerts[0]["description"]
        assert alerts[0]["source"] == "code-fix-lane"

        # 第 3 个 checkpoint：护栏拦截自动重派，进度呈现暂停原因
        res = orch.checkpoint()
        assert res["triggered"] is False
        assert res["reason"] == "zero_progress_paused"
        prog = read_progress(proot)
        assert prog["phase"] == "blocked"
        assert prog["reason"] == "zero_progress_paused"
        assert "零进度" in prog["current"]

    def test_single_zero_round_no_pause(self, seq_run_ids):
        """仅 1 轮零进度：不触发暂停、不发信号。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        assert orch.checkpoint()["triggered"] is True
        prog = read_progress(proot)
        assert prog["zero_progress_rounds"] == 1
        assert prog["zero_progress_paused"] is False
        assert _zero_progress_alerts(proot) == []
        # 下一 checkpoint 不被护栏拦截（护栏未生效——新链正常重派）
        res = orch.checkpoint()
        assert res["triggered"] is True

    def test_progress_round_resets_counter(self, seq_run_ids):
        """零进度 1 轮后出现 resolved>0 的轮次：计数归零、不触发暂停。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        assert orch.checkpoint()["triggered"] is True
        assert read_progress(proot)["zero_progress_rounds"] == 1

        # 有进度轮：run 成功 → 条目核销 → rollup resolved=1 → 计数归零
        runner.fix_success = True
        assert orch.checkpoint()["triggered"] is True
        prog = read_progress(proot)
        assert prog["zero_progress_rounds"] == 0
        assert read_items(proot)["a"]["status"] == "resolved"

        # 新零进度轮从 0 起算（不与历史累计）
        _append_open_item(proot, "b")
        runner.fix_success = False
        assert orch.checkpoint()["triggered"] is True
        prog = read_progress(proot)
        assert prog["zero_progress_rounds"] == 1
        assert prog["zero_progress_paused"] is False

    def test_release_via_ledger_change(self, seq_run_ids):
        """暂停后新一轮评审产出台账变更：选批扫描复核解除、恢复自动重派。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        orch.checkpoint()
        orch.checkpoint()
        assert read_progress(proot)["zero_progress_paused"] is True
        assert orch.checkpoint()["reason"] == "zero_progress_paused"

        # 新一轮评审追加 open 条目 → open 集合 ≠ 暂停快照 → 解除并放行
        _append_open_item(proot, "c")
        res = orch.checkpoint()
        assert res["triggered"] is True, "解除后同一 checkpoint 恢复派批"
        prog = read_progress(proot)
        assert prog["zero_progress_paused"] is False
        assert prog["zero_progress_paused_open_ids"] == []
        # 解除即重新武装（计数先归零再起算）：放行的本轮仍零核销 → 新窗口 1 轮
        assert prog["zero_progress_rounds"] == 1

    def test_release_via_manual_override(self, seq_run_ids):
        """暂停后人工处置（override_enabled 手动入口）：即时解除并派批。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        orch.checkpoint()
        orch.checkpoint()
        assert read_progress(proot)["zero_progress_paused"] is True

        res = orch.checkpoint(override_enabled=True)
        assert res["triggered"] is True, "手动重派入口即时解除护栏"
        prog = read_progress(proot)
        assert prog["zero_progress_paused"] is False
        # 解除即重新武装（计数先归零）：放行的本轮仍零核销 → 新窗口 1 轮
        assert prog["zero_progress_rounds"] == 1

    def test_no_ledger_change_stays_paused(self, seq_run_ids):
        """暂停后台账未变更：持续拦截（不因重复 checkpoint 自行解除）。"""
        proot = _make_project_root(["a"])
        runner = _ZeroRunner(proot, fix_success=False)
        orch = self._orch(proot, runner)

        orch.checkpoint()
        orch.checkpoint()
        for _ in range(3):
            assert orch.checkpoint()["reason"] == "zero_progress_paused"
        assert read_progress(proot)["zero_progress_paused"] is True
        assert len(_zero_progress_alerts(proot)) == 1, "不重复发信号"
        assert len(runner.run_ids) == 2, "暂停期间不再派新 run"
