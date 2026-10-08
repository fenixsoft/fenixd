"""失败批自动重派预算按回归终局形态分档（evo-add-codefix-anomaly-redispatch-budget 2.1）。

覆盖：
- anomaly（reg_form=anomaly，零失败面）预算降为 1：首记入档即触顶——既有
  触顶机制登记待人工（todo + code_fix_retry_budget_exhausted，文案按生效
  预算动态呈现）+ 复用 write_regression_failed_alert 通道的停派告警一次，
  且新链启动不再释放（在档排除直至人工解除）
- mapped（有真实失败面）保持 FAIL_RETRY_MAX=3：预算内入档零人工项、
  链末自动释放、走满才触顶
- 旧记录缺 reg_form 键 / 非法值按 mapped 兼容（不报错、不分档）
- 复燃合档：reg_form 与 fail_count 以最近一次失败为准（mapped 复燃转
  anomaly 即按分档预算触顶，不悬为无告警墓碑）
- 降档/停派告警一次性：budget_alerted 记录标记判重，复燃再败不重复触发

evo-codefix-zero-face-regression-hardening 扩展（TestTimeoutZeroFaceAnomaly
Hardening）：timeout 无明细进 anomaly 判据与分档、两个计数点首记即收口
（timeout 阈值 1）、parse_error/failed 阈值 2 不回归——批 worker 级用例
复用定向重试套件的编排替身（tests.test_codefix_targeted_retry），零分叉
harness。
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_codefix_targeted_retry import (_CFG_ON, _FakeRunner, _item,
                                               _make_project_root,
                                               _write_items, _write_verify_yaml)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix)


def _make_project_root() -> Path:
    td = Path(_mkdtemp("cfix-anomaly-"))
    (td / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    return td


def _write_failed_records(proot: Path, records) -> None:
    """直接写失败档案（构造历史形态/外部直改态记录用）。"""
    path = proot / ".fenix" / "code-review" / "fix-failed.json"
    path.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


class TestAnomalyRedispatchBudget(unittest.TestCase):
    """失败批自动重派预算分档（evo-add-codefix-anomaly-redispatch-budget）。"""

    def _signals(self, proot, signal_type):
        from core.admin_store import AdminStore

        return [r for r in AdminStore(proot, logger=None).read_all()
                if r.get("signal_type") == signal_type]

    def test_effective_budget_single_source(self):
        """分档取值单源：anomaly→1，mapped/缺键/非法值→FAIL_RETRY_MAX。"""
        from core.code_fix import (ANOMALY_FAIL_RETRY_MAX, FAIL_RETRY_MAX,
                                   _effective_retry_budget)

        self.assertEqual(ANOMALY_FAIL_RETRY_MAX, 1)
        self.assertEqual(
            _effective_retry_budget({"reg_form": "anomaly"}),
            ANOMALY_FAIL_RETRY_MAX)
        self.assertEqual(_effective_retry_budget({}), FAIL_RETRY_MAX,
                         "缺键（历史记录）按 mapped")
        self.assertEqual(
            _effective_retry_budget({"reg_form": "mapped"}), FAIL_RETRY_MAX)
        self.assertEqual(
            _effective_retry_budget({"reg_form": "bogus"}), FAIL_RETRY_MAX,
            "非法值按 mapped 容错（不因坏键分档）")

    def test_anomaly_exhausts_budget_at_first_archive(self):
        """anomaly 首记即触顶：登记待人工 + 停派告警一次 + 不再自动释放。"""
        from core.code_fix import (_failed_item_ids, load_failed_batches,
                                   record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        record_failed_batch(
            proot, ["a", "b"], "/tmp/wt-1",
            reason="regression_parse_error_breaker", branch="br-a", tip_sha="s1",
            reg_form="anomaly",
            reg_detail={"anomaly_streak": 2, "retry_rounds": 1,
                        "breaker_triggered": True},
        )
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["fail_count"], 1)
        self.assertEqual(recs[0]["reg_form"], "anomaly")
        self.assertEqual(recs[0]["reg_detail"]["anomaly_streak"], 2,
                         "重试收敛事实快照随档留存")
        self.assertTrue(recs[0]["budget_alerted"], "触顶标记随入档落盘")
        # 既有触顶机制（1.2）：触顶告警 + todo 登记，文案按生效预算=1 动态呈现
        exhausted = self._signals(proot, "code_fix_retry_budget_exhausted")
        self.assertEqual(len(exhausted), 1)
        self.assertIn("（1 轮）", exhausted[0]["description"],
                      "触顶文案 MUST 按分档预算呈现，不误导为 FAIL_RETRY_MAX 轮")
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("自动重试 1 轮均失败", todo)
        self.assertIn("br-a", todo)
        self.assertIn("s1", todo)
        self.assertNotIn("/tmp/wt-1", todo, "现场即弃后不引用 worktree 路径")
        # 复用 write_regression_failed_alert 通道的停派告警（1.3）：登记
        # branch、reg_form 与被跳过条目，不新增告警类型
        budget_alerts = self._signals(proot, "code_fix_regression_failed")
        self.assertEqual(len(budget_alerts), 1, "停派告警恰一条")
        self.assertIn("reg_form=anomaly", budget_alerts[0]["description"])
        self.assertIn("停止自动重派", budget_alerts[0]["description"])
        self.assertIn("reg_form=anomaly", budget_alerts[0]["evidence"])
        self.assertIn("br-a", budget_alerts[0]["evidence"])
        self.assertIn("a, b", budget_alerts[0]["evidence"],
                      "被跳过条目登记在 evidence")
        self.assertIn("regression_parse_error_breaker",
                      budget_alerts[0]["evidence"], "失败原因随 evidence 留痕")
        # 分档释放门（1.2）：预算已耗尽 → 新链启动不释放，保持在档排除
        self.assertEqual(release_retryable_failed_batches(proot), 0,
                         "anomaly 预算已耗尽 MUST NOT 被预算内释放")
        self.assertEqual(_failed_item_ids(proot), {"a", "b"},
                         "耗尽记录保持选批排除（永久跳过直至人工解除）")

    def test_mapped_keeps_full_budget(self):
        """mapped 保持 FAIL_RETRY_MAX=3：预算内零人工项、释放、走满才触顶。"""
        from core.code_fix import (FAIL_RETRY_MAX, load_failed_batches,
                                   record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        for i in range(FAIL_RETRY_MAX - 1):
            record_failed_batch(
                proot, ["m"], f"/tmp/wt-{i}", reason="regression_failed_twice",
                branch="br-m", tip_sha=f"s{i}", reg_form="mapped")
            self.assertEqual(
                self._signals(proot, "code_fix_retry_budget_exhausted"), [],
                "预算内入档 MUST NOT 触顶告警")
            self.assertEqual(self._signals(proot, "code_fix_regression_failed"),
                             [], "预算内入档 MUST NOT 发停派告警")
            self.assertFalse(
                (proot / ".fenix" / "todo.md").exists(),
                "预算内入档 MUST NOT 登记 todo 人工项")
        self.assertEqual(release_retryable_failed_batches(proot), 1,
                         "mapped 预算内记录照常自动释放")
        # 复燃递增至 FAIL_RETRY_MAX 的那次才触顶（文案按 mapped 预算呈现）
        record_failed_batch(
            proot, ["m"], "/tmp/wt-final", reason="regression_failed_twice",
            branch="br-m", tip_sha="s-final", reg_form="mapped")
        exhausted = self._signals(proot, "code_fix_retry_budget_exhausted")
        self.assertEqual(len(exhausted), 1)
        self.assertIn(f"（{FAIL_RETRY_MAX} 轮）", exhausted[0]["description"])
        self.assertEqual(self._signals(proot, "code_fix_regression_failed"), [],
                         "mapped 触顶走既有触顶告警，不发停派告警")
        recs = load_failed_batches(proot)
        self.assertEqual(recs[0]["fail_count"], FAIL_RETRY_MAX)
        self.assertEqual(release_retryable_failed_batches(proot), 0,
                         "达上限记录不再释放")

    def test_legacy_record_without_reg_form_treated_as_mapped(self):
        """旧记录缺 reg_form 键（/非法值）按 mapped：沿用既有预算，不报错。"""
        from core.code_fix import (FAIL_RETRY_MAX, _record_reg_form,
                                   load_failed_batches, record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        _write_failed_records(proot, [
            {"item_ids": ["old"], "fail_count": FAIL_RETRY_MAX - 1,
             "reason": "regression_failed_twice"},
            {"item_ids": ["bad"], "fail_count": 1, "reg_form": "bogus"},
        ])
        recs = load_failed_batches(proot)
        self.assertEqual(_record_reg_form(recs[0]), "mapped")
        self.assertEqual(_record_reg_form(recs[1]), "mapped")
        released = release_retryable_failed_batches(proot)
        self.assertEqual(released, 2, "缺键/非法值记录均按 mapped 预算内释放")
        # 缺键记录复燃递增至 FAIL_RETRY_MAX 才触顶（分档不因缺键提前触发）
        for _ in range(FAIL_RETRY_MAX - 1):
            record_failed_batch(proot, ["old"], "/tmp/wt-x", reason="r")
        self.assertEqual(len(self._signals(
            proot, "code_fix_retry_budget_exhausted")), 1)
        self.assertEqual(self._signals(proot, "code_fix_regression_failed"), [],
                         "缺键记录按 mapped，不发生停派告警")

    def test_reignite_merge_takes_latest_form(self):
        """复燃合档取最近失败形态：mapped 复燃转 anomaly 即按分档预算触顶。"""
        from core.code_fix import (load_failed_batches, record_failed_batch,
                                   release_retryable_failed_batches)

        proot = _make_project_root()
        record_failed_batch(
            proot, ["r"], "/tmp/wt-1", reason="regression_failed_twice",
            branch="br-1", tip_sha="s1", reg_form="mapped")
        self.assertEqual(release_retryable_failed_batches(proot), 1,
                         "mapped 首记预算内释放")
        # 复燃入档：同条目集合档（不追加记录），reg_form 以最近一次失败为准
        record_failed_batch(
            proot, ["r"], "/tmp/wt-2", reason="regression_parse_error_breaker",
            branch="br-2", tip_sha="s2", reg_form="anomaly",
            reg_detail={"anomaly_streak": 2, "retry_rounds": 2,
                        "breaker_triggered": True},
        )
        recs = load_failed_batches(proot)
        self.assertEqual(len(recs), 1, "复燃沿用合档语义（不追加记录）")
        self.assertEqual(recs[0]["fail_count"], 2)
        self.assertEqual(recs[0]["reg_form"], "anomaly",
                         "reg_form 以最近一次失败为准")
        self.assertFalse(recs[0].get("released"), "复燃清标回到在档排除态")
        # fail_count 已越过分档预算（1）→ 超调兜底触顶，不悬为无告警墓碑
        exhausted = self._signals(proot, "code_fix_retry_budget_exhausted")
        self.assertEqual(len(exhausted), 1, "分档切换即触顶（超调兜底）")
        self.assertIn("（1 轮）", exhausted[0]["description"])
        self.assertEqual(len(self._signals(proot, "code_fix_regression_failed")),
                         1, "停派告警随触顶发一次")
        self.assertEqual(release_retryable_failed_batches(proot), 0,
                         "anomaly 形态预算已耗尽，不再自动释放")

    def test_budget_alert_fires_once_per_record(self):
        """降档/停派与触顶告警一次性：budget_alerted 标记判重，复燃不重发。"""
        from core.code_fix import load_failed_batches, record_failed_batch

        proot = _make_project_root()
        record_failed_batch(
            proot, ["x"], "/tmp/wt-1", reason="regression_parse_error_breaker",
            branch="br-x", tip_sha="s1", reg_form="anomaly")
        self.assertEqual(
            len(self._signals(proot, "code_fix_retry_budget_exhausted")), 1)
        self.assertEqual(
            len(self._signals(proot, "code_fix_regression_failed")), 1)
        # 外部落标释放（模拟人工/外部把记录置回可复燃态）后再次入档：
        # fail_count 越顶但标记已置位 → 不再重复触发任何触顶/停派告警
        recs = load_failed_batches(proot)
        recs[0]["released"] = True
        _write_failed_records(proot, recs)
        record_failed_batch(
            proot, ["x"], "/tmp/wt-2", reason="regression_parse_error_breaker",
            branch="br-x", tip_sha="s2", reg_form="anomaly")
        self.assertEqual(
            len(self._signals(proot, "code_fix_retry_budget_exhausted")), 1,
            "触顶告警一次性（记录标记判重）")
        self.assertEqual(
            len(self._signals(proot, "code_fix_regression_failed")), 1,
            "停派告警一次性（记录标记判重）")
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertEqual(todo.count("## [code-fix]"), 1,
                         "todo 登记一次性（不随复燃重复追加）")


class TestTimeoutZeroFaceAnomalyHardening(unittest.TestCase):
    """timeout 零失败面判据扩展与首记即收口（evo-codefix-zero-face-regression-hardening）。

    2026-10-08 白天实证：``_is_regression_anomaly`` 只认 parse_error/failed
    无明细，timeout 恒 False——前两批 6 轮全部 timeout（每轮恰好烧满 1800s
    墙钟），异常计数从未起表，a26dbe88 的 anomaly 分档（预算 1、一次性降档
    告警）对该形态完全失效。锁定：timeout 无明细进 anomaly 分档、两个计数
    点首记即收口、parse_error/failed 阈值 2 不回归。

    批 worker 级用例复用定向重试套件的编排替身（同一批收尾循环、同一
    fake runner 契约），MUST NOT 为本 spec 另起一套分叉 harness。
    """

    def _orch(self, runner, proot, **cfg_extra):
        from core.code_fix import CodeFixOrchestrator

        cfg = {"admin": {"code_review_fix": dict(
            _CFG_ON["admin"]["code_review_fix"], **cfg_extra)}}
        return CodeFixOrchestrator(runner, proot, config=cfg, logger=None)

    def _signals(self, proot, signal_type):
        from core.admin_store import AdminStore

        return [r for r in AdminStore(proot, logger=None).read_all()
                if r.get("signal_type") == signal_type]

    def test_timeout_zero_face_judged_anomaly(self):
        """1.1：timeout 且无可用明细 → anomaly；timeout 有真实失败面 → 非。"""
        from types import SimpleNamespace

        from core.code_fix import _is_regression_anomaly

        self.assertTrue(_is_regression_anomaly(
            SimpleNamespace(status="timeout"), []),
            "timeout 无明细（junit 缺失/未产出一个用例）判 anomaly")
        self.assertFalse(_is_regression_anomaly(
            SimpleNamespace(status="timeout"),
            [{"nodeid": "tests/test_x.py::test_a"}]),
            "timeout 但映射出明细 = 有真实失败面，MUST NOT 进异常分档")
        # 既有形态不回归（add-codefix-parse-error-breaker D1 原语义）
        self.assertTrue(_is_regression_anomaly(
            SimpleNamespace(status="parse_error"), []))
        self.assertTrue(_is_regression_anomaly(
            SimpleNamespace(status="failed"), []))
        self.assertFalse(_is_regression_anomaly(
            SimpleNamespace(status="failed"),
            [{"nodeid": "tests/test_x.py::test_a"}]))
        self.assertFalse(_is_regression_anomaly(
            SimpleNamespace(status="passed"), []))

    def test_breaker_threshold_per_form(self):
        """1.2：阈值按形态取值——timeout=1（首记即收口），其余维持 2。"""
        from core.code_fix import (ANOMALY_BREAKER_TIMEOUT_THRESHOLD,
                                   REGRESSION_ANOMALY_BREAKER_THRESHOLD,
                                   _anomaly_breaker_threshold)

        self.assertEqual(ANOMALY_BREAKER_TIMEOUT_THRESHOLD, 1)
        self.assertEqual(REGRESSION_ANOMALY_BREAKER_THRESHOLD, 2)
        self.assertEqual(_anomaly_breaker_threshold("timeout"), 1)
        self.assertEqual(_anomaly_breaker_threshold("parse_error"), 2)
        self.assertEqual(_anomaly_breaker_threshold("failed"), 2)
        self.assertEqual(_anomaly_breaker_threshold("passed"), 2,
                         "未知/其它形态保守回落既有阈值")

    def test_timeout_first_hit_stops_batch_without_targeted_run(self):
        """1.2：首轮全量回归即 timeout 零失败面 → 首记即收口，不派任何定向 run。

        （2026-10-08 批 1 实际形态：改前首轮 timeout 后仍派 1 个定向 run
        并再烧一轮 1800s 全量回归才可能熔断。）
        """
        from core.code_fix import (load_failed_batches, read_progress,
                                   release_retryable_failed_batches)
        from core.code_review import read_items

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a", first_seen_at="2026-01-01T00:00:00Z")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["timeout", "timeout"],
            failure_sets=[[]],
        )
        self._orch(runner, proot).checkpoint()
        # 首轮 timeout 零失败面即收口：不派定向 run、不再烧第二轮全量回归
        self.assertEqual(len(runner.fix_calls), 1, "仅首轮 run，未派任何定向轮")
        self.assertEqual(len(runner.regression_calls), 1, "不再执行第二轮回归")
        self.assertEqual(runner.worktree_manager.merge_calls, [],
                         "现场即弃 MUST NOT 合回")
        self.assertEqual(len(runner.worktree_manager.cleanup_calls), 1)
        self.assertFalse(runner.worktree_manager.cleanup_calls[0][1],
                         "现场即弃 cleanup（success=False）")
        self.assertEqual(read_items(proot)["a"]["status"], "open", "条目保持 open")
        failed = load_failed_batches(proot)
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["reason"], "regression_parse_error_breaker")
        self.assertEqual(failed[0]["reg_form"], "anomaly",
                         "timeout 无明细入档 anomaly 分档（1.1 判据自动生效）")
        self.assertEqual(failed[0]["reg_detail"],
                         {"anomaly_streak": 1, "retry_rounds": 0,
                          "breaker_triggered": True},
                         "首记即收口：streak=1、实际执行 0 轮定向重试")
        self.assertTrue(failed[0].get("detail_ref"))
        self.assertTrue((proot / failed[0]["detail_ref"]).is_file())
        # anomaly 分档（预算 1）+ 一次性降档告警随新判据自动生效（重派侧零改动）
        self.assertEqual(release_retryable_failed_batches(proot), 0,
                         "anomaly 预算首记即耗尽，不再自动释放")
        budget = [r for r in self._signals(proot, "code_fix_regression_failed")
                  if r["description"].startswith("code-fix 批回归终局为零失败面")]
        self.assertEqual(len(budget), 1, "一次性降档/停派告警恰一条")
        self.assertIn("停止自动重派", budget[0]["description"])
        self.assertIn("reg_form=anomaly", budget[0]["evidence"])
        exhausted = self._signals(proot, "code_fix_retry_budget_exhausted")
        self.assertEqual(len(exhausted), 1, "触顶告警恰一条（预算 1 即达上限）")
        self.assertIn("（1 轮）", exhausted[0]["description"])
        todo = (proot / ".fenix" / "todo.md").read_text(encoding="utf-8")
        self.assertIn("自动重试 1 轮均失败", todo)
        prog = read_progress(proot)
        self.assertEqual(prog["phase"], "blocked")
        self.assertIn("需人工排查", prog["current"])

    def test_timeout_in_targeted_round_breaks_immediately(self):
        """1.2：定向轮回归才 timeout 零失败面 → 同样首记即收口（第二计数点）。"""
        from core.code_fix import load_failed_batches

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a", first_seen_at="2026-01-01T00:00:00Z")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["parse_error", "timeout"],
            failure_sets=[[]],
        )
        self._orch(runner, proot).checkpoint()
        # 首轮 parse_error（计数 1 < 阈值 2）→ 定向轮 1 照常派发；其回归
        # timeout 零失败面（阈值 1）→ 当轮终止，不再第二轮
        self.assertEqual(len(runner.fix_calls), 2, "首轮 + 定向轮 1，随后收口")
        self.assertEqual(len(runner.regression_calls), 2)
        failed = load_failed_batches(proot)
        self.assertEqual(failed[0]["reason"], "regression_parse_error_breaker")
        self.assertEqual(failed[0]["reg_form"], "anomaly")
        self.assertEqual(failed[0]["reg_detail"],
                         {"anomaly_streak": 2, "retry_rounds": 1,
                          "breaker_triggered": True})

    def test_parse_error_threshold_stays_two(self):
        """1.2 不回归项：parse_error 形态维持阈值 2——首记不收口。"""
        from core.code_fix import load_failed_batches

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a", first_seen_at="2026-01-01T00:00:00Z")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["parse_error", "parse_error"],
            failure_sets=[[]],
        )
        self._orch(runner, proot).checkpoint()
        self.assertEqual(len(runner.fix_calls), 2,
                         "首轮计数 1 不达阈值 2 → 定向轮 1 照常派发")
        self.assertEqual(len(runner.regression_calls), 2)
        failed = load_failed_batches(proot)
        self.assertEqual(failed[0]["reason"], "regression_parse_error_breaker")
        self.assertEqual(failed[0]["reg_detail"]["anomaly_streak"], 2,
                         "第二轮才达阈值熔断（批 3 实际行为逐位不变）")

    def test_failed_zero_detail_threshold_stays_two(self):
        """1.2 不回归项：failed 无明细形态阈值 2（2026-10-08 批 3 形态）。"""
        from core.code_fix import load_failed_batches

        proot = _make_project_root()
        _write_items(proot, {"a": _item("a", first_seen_at="2026-01-01T00:00:00Z")})
        _write_verify_yaml(proot)
        runner = _FakeRunner(
            proot,
            regression_statuses=["failed", "failed"],
            failure_sets=[[]],
        )
        self._orch(runner, proot).checkpoint()
        self.assertEqual(len(runner.fix_calls), 2, "failed 无明细首记不收口")
        failed = load_failed_batches(proot)
        self.assertEqual(failed[0]["reg_detail"]["anomaly_streak"], 2)


if __name__ == "__main__":
    unittest.main()
