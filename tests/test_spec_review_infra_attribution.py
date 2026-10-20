"""test_spec_review_infra_attribution.py — evo-fix-spec-review-infra-attribution-bridge 单元测试。

验收标准（tasks.md 5.1-5.3）：
  5.1 归因桥接：api_error_status=429 / conn_error=True 的失败结果结构化字段随
      AgentRunResult 传递、_classify_run_failure 判 infra、_review_attempts 不
      递增、infra_breaker 记失败；无结构化字段但文本命中 "rate limit" 时回退
      分类仍生效。
  5.2 评审车道在飞上限：超限条目保留队列且不并发超限、后续轮次正常补位派发。
  5.3 content 重试短退避（间隔≥配置、判重无重复定时器）；评审冻结新前缀含
      「原状态 reviewing」可被 parse_orig_status 解析、不命中
      _INTENTIONAL_PAUSE_MARKERS 且不以 "frozen:" 开头、FREEZE_ERROR_PREFIX
      常量值未被改动；infra 分类失败不进入冻结路径。
"""

import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.result_gate import AgentRunResult
from core.admin_monitor import _INTENTIONAL_PAUSE_MARKERS
from core.pm_engine.infra_breaker import InfraCircuitBreaker
from core.pm_engine.spec_review import MAX_REVIEW_ATTEMPTS, SpecReviewManager
from core.state_machine import (
    FREEZE_ERROR_PREFIX,
    REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX,
    REVIEW_REJECTED_FREEZE_ERROR_PREFIX,
    parse_orig_status,
)


# ── fixtures ────────────────────────────────────────────────────────


class FakeStateMachine:
    """最小 state_machine mock，支持 read_one / update_spec / bump_counters /
    freeze_for_human（签名与 production core/state_machine.py 逐参对齐，
    冻结调用录制供前缀断言）。
    """

    def __init__(self):
        self._specs = {}
        self.freeze_calls = []

    def read_one(self, spec_name):
        return self._specs.get(spec_name)

    def update_spec(self, spec_name, updates):
        if spec_name not in self._specs:
            self._specs[spec_name] = {}
        self._specs[spec_name].update(updates)

    def bump_counters(self, spec_name: str, deltas):
        if spec_name not in self._specs:
            return {field: 0 for field in deltas}
        entry = self._specs[spec_name]
        result = {}
        for field, delta in deltas.items():
            try:
                current = int(entry.get(field, 0) or 0)
            except (TypeError, ValueError):
                current = 0
            result[field] = max(0, current + delta)
            entry[field] = result[field]
        return result

    def freeze_for_human(
        self,
        spec_name: str,
        *,
        error: str,
        signal_type: str,
        severity: str,
        description: str,
        evidence: str,
        recommended_action: str,
        alert_callback=None,
        extra_updates=None,
    ) -> bool:
        self.freeze_calls.append({"spec": spec_name, "error": error})
        self.update_spec(spec_name, {"frozen": True, "error": error})
        if extra_updates:
            self.update_spec(spec_name, extra_updates)
        return True


def _make_manager(tmp_path, artifact_valid=False, pm_engine=None):
    """构造 SpecReviewManager（最小 mock，同 test_review_circuit_breaker 范式）。"""
    (tmp_path / ".fenix").mkdir(exist_ok=True)
    manager = SpecReviewManager(
        tmp_path,
        FakeStateMachine(),
        MagicMock(),
        pm_engine if pm_engine is not None else MagicMock(),
        {"admin": {}},
        logger=MagicMock(),
    )
    manager.pm_engine.infra_breaker = InfraCircuitBreaker(
        tmp_path,
        {"admin": {"run_infra_breaker": {"threshold": 3, "cooldown_minutes": 30}}},
    )
    manager._artifact_landed_valid = lambda s: artifact_valid
    return manager


# ── 5.1 归因桥接 ────────────────────────────────────────────────────


class TestAttributionBridge(unittest.TestCase):
    """结构化归因字段随 AgentRunResult 传递并驱动 infra 分类（tasks 5.1）。"""

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / ".tmp_infrattr"
        self.tmp.mkdir(exist_ok=True)
        (self.tmp / ".fenix").mkdir(exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agent_run_result_carries_structured_fields(self):
        """AgentRunResult 结构化字段随结果对象传递，缺省 None 兼容既有构造。"""
        r = AgentRunResult(
            "run-1", "demo", "spec-review", success=False,
            duration_seconds=1.0, error="Exit code: 1",
            api_error_status=429, conn_error=True,
        )
        self.assertEqual(r.api_error_status, 429)
        self.assertTrue(r.conn_error)
        # 既有构造点不传即缺省（design 风险段：兼容性低风险）
        r2 = AgentRunResult(
            "run-2", "demo", "spec-review", success=False, duration_seconds=1.0,
        )
        self.assertIsNone(r2.api_error_status)
        self.assertIsNone(r2.conn_error)

    def test_429_structured_attribution_classifies_infra(self):
        """api_error_status=429 → infra（文本只剩 Exit code: 1 仍判 infra）。"""
        m = _make_manager(self.tmp)
        # "Exit code: 1" 单独是 content（评审器内容失败）；结构化 429 优先翻 infra
        self.assertEqual(
            m._classify_run_failure(
                "Exit code: 1", "demo", api_error_status=429
            ),
            "infra",
        )

    def test_429_string_form_classifies_infra(self):
        """裸数字字符串 "429" 形态（runner 落盘的另一形态）同样判 infra。"""
        m = _make_manager(self.tmp)
        self.assertEqual(
            m._classify_run_failure(
                "Exit code: 1", "demo", api_error_status="429"
            ),
            "infra",
        )

    def test_conn_error_classifies_infra(self):
        """conn_error=True → infra。"""
        m = _make_manager(self.tmp)
        self.assertEqual(
            m._classify_run_failure(
                "Exit code: 1", "demo", conn_error=True
            ),
            "infra",
        )

    def test_text_fallback_rate_limit_still_works(self):
        """无结构化字段但文本命中 "rate limit" → 文本回退分类仍生效。"""
        m = _make_manager(self.tmp)
        self.assertEqual(
            m._classify_run_failure("Rate limit exceeded", "demo"),
            "infra",
        )

    def test_underscore_adjacent_fingerprints_stay_content(self):
        """紧邻下划线的指纹不判 infra（code-review item ecec53733c66）：
        foo_429_bar（数字）/ quota_used（词根）与连字符形态同按分隔符语义
        处理——边界字符类未收下划线时二者均被误判 infra、跳过重试预算。"""
        m = _make_manager(self.tmp)
        self.assertEqual(
            m._classify_run_failure("fix_429_backoff: Exit code: 1", "demo"),
            "content",
        )
        self.assertEqual(
            m._classify_run_failure("quota_used exhausted in spec", "demo"),
            "content",
        )

    def test_unstructured_content_failure_stays_content(self):
        """conn_error 非 True（含替身真值子对象）不误判 infra（严格等值判定）。"""
        m = _make_manager(self.tmp)
        self.assertEqual(
            m._classify_run_failure("Exit code: 1", "demo", conn_error=False),
            "content",
        )
        self.assertEqual(
            m._classify_run_failure("Exit code: 1", "demo", api_error_status=200),
            "content",
        )

    def test_handle_failure_429_does_not_bump_attempts_and_records_breaker(self):
        """429 失败走 _handle_review_failure：判 infra、attempts 不递增、
        breaker 记失败；不冻结。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing", "reviewer_run": "r1"})
        m._handle_review_failure(
            "demo", "Exit code: 1", api_error_status=429,
        )
        entry = sm.read_one("demo")
        self.assertEqual(entry.get("_review_attempts", 0), 0)
        self.assertIsNone(entry.get("reviewer_run"))
        self.assertNotIn("frozen", entry)
        # error 保留 spec-review-incomplete 前缀（re_review startswith 契约）
        self.assertTrue(
            str(entry.get("error", "")).startswith("spec-review-incomplete:")
        )
        # breaker 记失败（未达阈值不触发）
        self.assertEqual(m.pm_engine.infra_breaker.get_state("spec-review")["count"], 1)

    def test_handle_failure_429_trips_breaker_at_threshold(self):
        """连续 3 次 429 infra 失败 → 熔断武装（冷却自动恢复载体）。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing"})
        for _ in range(3):
            m._handle_review_failure(
                "demo", "Exit code: 1", api_error_status=429,
            )
        self.assertTrue(m.pm_engine.infra_breaker.is_open("spec-review"))
        # 三次 infra 均不递增尝试预算（对照 MAX_REVIEW_ATTEMPTS=3 的 content 语义）
        self.assertEqual(sm.read_one("demo").get("_review_attempts", 0), 0)
        self.assertNotIn("frozen", sm.read_one("demo"))

    def test_handle_failure_conn_error_infra(self):
        """conn_error=True 失败结果同样判 infra（不递增 attempts）。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing"})
        m._handle_review_failure("demo", "Exit code: 1", conn_error=True)
        self.assertEqual(sm.read_one("demo").get("_review_attempts", 0), 0)

    def test_handle_failure_text_fallback_infra(self):
        """无结构化字段、文本命中 rate limit → 回退分类走 infra 分支。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing"})
        m._handle_review_failure("demo", "Rate limit exceeded")
        self.assertEqual(sm.read_one("demo").get("_review_attempts", 0), 0)
        self.assertEqual(m.pm_engine.infra_breaker.get_state("spec-review")["count"], 1)


# ── 5.2 评审车道在飞上限 ────────────────────────────────────────────


def _mk_multi_spec_project(tmpdir: Path, names):
    """最小 project root + 多个 reviewing spec（同 test_spec_review_async_dispatch）。"""
    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    from core.state_machine import StateMachine

    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", MagicMock())
    for name in names:
        spec_dir = tmpdir / "spec" / "changes" / name
        spec_dir.mkdir(parents=True, exist_ok=True)
        (spec_dir / ".spec.yaml").write_text(
            "schema: spec-driven\ncreated: 2026-09-19\nmode: full\n", encoding="utf-8"
        )
        (spec_dir / "tasks.md").write_text(
            "# Tasks\n\n## 1. 实现\n\n- [ ] 1.1 do it\n", encoding="utf-8"
        )
        sm.add_spec(name, {"status": "reviewing", "priority": 5})
    return sm


class TestReviewInflightCap(unittest.TestCase):
    """评审车道在飞上限（tasks 5.2，evo-fix-spec-review-infra-attribution-bridge 2.1）。"""

    def setUp(self):
        import shutil
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp())
        self._shutil = shutil

    def tearDown(self):
        self._shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_engine(self, config=None):
        from core.pm_engine import PMEngine

        logger = MagicMock()
        engine = PMEngine(
            _mk_multi_spec_project(self.tmpdir, ["d1", "d2", "d3", "d4"]),
            MagicMock(),
            config or {},
            self.tmpdir,
            logger,
        )
        engine._check_impl_budget_exhausted = MagicMock(return_value=False)
        engine._check_spec_content_missing = MagicMock(return_value=False)
        engine._dependencies_satisfied = MagicMock(return_value=True)
        # 在飞判定替身：候选 spec 无真实在飞评审（上限计量由
        # _active_reviews/_reviews_dispatching 集合计数承载）
        engine.agent_runner.reviewer_in_flight = MagicMock(return_value=(False, ""))
        # worker 替身：不真起评审 run；出队登记（_active_reviews）保留，
        # 供上限计量与补位断言
        engine._run_agent_worker = MagicMock()
        return engine

    def _seed_queue(self, engine):
        engine._dispatcher._run_queue = [
            (5, name, "spec-review", time.time()) for name in ("d1", "d2", "d3", "d4")
        ]

    def test_over_cap_entries_kept_in_queue(self):
        """在飞达上限（2）时 4 条评审候选全部保留队列、零派发。"""
        engine = self._make_engine(config={"review": {"max_inflight": 2}})
        self._seed_queue(engine)
        # 模拟已有 2 个在飞评审（过渡集，真实在飞 run 都在这段窗口内）
        engine._dispatcher._reviews_dispatching = {"ghost1", "ghost2"}

        with engine._dispatcher._queue_lock:
            pass  # _process_queue 自取锁；此处仅确认锁可用
        engine._dispatcher._process_queue()

        self.assertEqual(
            len(engine._dispatcher._run_queue), 4,
            f"达上限时候选条目须保留队列: {engine._dispatcher._run_queue}",
        )
        self.assertEqual(len(engine._dispatcher._active_reviews), 0)

    def test_under_cap_dispatches_up_to_limit_then_backfills(self):
        """在飞 < 上限时补位派发至多 cap 条，不并发超限、余量保留队列。"""
        engine = self._make_engine(config={"review": {"max_inflight": 2}})
        self._seed_queue(engine)
        engine._dispatcher._reviews_dispatching = {"ghost1", "ghost2"}
        # 释放一个在飞（评审 run 收工）→ 空出 1 个名额
        engine._dispatcher._reviews_dispatching.discard("ghost1")

        engine._dispatcher._process_queue()

        cap = engine._dispatcher._review_inflight_cap()
        self.assertEqual(cap, 2)
        inflight = engine._dispatcher._review_inflight_count()
        self.assertLessEqual(inflight, cap, "派发后不得并发超限")
        # 补位恰好 1 条（2 - 1 在飞 = 1 名额），余量 3 条保留队列
        self.assertEqual(len(engine._dispatcher._active_reviews), 1)
        self.assertEqual(len(engine._dispatcher._run_queue), 3)

        # 再释放 2 个在飞 → 下一轮补位 2 条（cap 内），余 1 条保留
        engine._dispatcher._reviews_dispatching.clear()
        engine._dispatcher._active_reviews.clear()
        engine._dispatcher._process_queue()

        self.assertEqual(len(engine._dispatcher._active_reviews), 2)
        self.assertEqual(len(engine._dispatcher._run_queue), 1)
        self.assertLessEqual(engine._dispatcher._review_inflight_count(), cap)

    def test_cap_configurable_and_fault_tolerant(self):
        """上限可配（review.max_inflight）；非法/非正值回退缺省 3。"""
        engine = self._make_engine(config={"review": {"max_inflight": 5}})
        self.assertEqual(engine._dispatcher._review_inflight_cap(), 5)
        engine2 = self._make_engine(config={"review": {"max_inflight": "oops"}})
        self.assertEqual(engine2._dispatcher._review_inflight_cap(), 3)
        engine3 = self._make_engine(config={"review": {"max_inflight": 0}})
        self.assertEqual(engine3._dispatcher._review_inflight_cap(), 3)
        engine4 = self._make_engine(config={})
        self.assertEqual(engine4._dispatcher._review_inflight_cap(), 3)


# ── 5.3 content 短退避 + 冻结前缀区分 ───────────────────────────────


class _BackoffHost:
    """真实 BBackoffMixin 宿主（持 _queue_lock），排程走 production 判重路径。"""

    def __init__(self):
        from core.pm_engine.dispatch.backoff import BBackoffMixin

        self._queue_lock = threading.Lock()
        self._mixin = BBackoffMixin()
        # mixin 排程自取宿主 _queue_lock（QQQueue 同款共享锁形态）；
        # 日志走宿主 self._pm.logger（scheduled_log 留痕）
        self._mixin._queue_lock = self._queue_lock
        self._mixin._pm = SimpleNamespace(logger=MagicMock())

    def _schedule_recovery_timer(self, spec_name, timers, resolve_delay,
                                 min_delay, callback, scheduled_log=None,
                                 lock_held=False):
        self._mixin._schedule_recovery_timer(
            spec_name, timers, resolve_delay, min_delay, callback,
            scheduled_log, lock_held)


class _PmStub:
    """pm_engine 门面替身：真实判重集合 + 真实排程入口，入队/重扫录制。"""

    def __init__(self, delay=5.0):
        self._review_content_backoff_timers = set()
        self._queue_lock = threading.Lock()
        self._backoff_host = _BackoffHost()
        self._delay = delay
        self.enqueued = []
        self.rescanned = 0

    def _get_config(self, key, default=None):
        if key == "review.content_retry_delay_seconds":
            return self._delay
        return default

    def _schedule_recovery_timer(self, spec_name, timers, resolve_delay,
                                 min_delay, callback, scheduled_log=None,
                                 lock_held=False):
        self._backoff_host._schedule_recovery_timer(
            spec_name, timers, resolve_delay, min_delay, callback,
            scheduled_log, lock_held)

    def _enqueue(self, spec_name, agent_type):
        self.enqueued.append((spec_name, agent_type))

    def _process_queue(self):
        self.rescanned += 1


class _FakeTimer:
    """threading.Timer 替身：录制 (delay, args)，start() 不起真线程。"""

    instances = []

    def __init__(self, delay, callback, args=None):
        self.delay = delay
        self.callback = callback
        self.args = args or ()
        self.daemon = False
        _FakeTimer.instances.append(self)

    def start(self):
        pass


class TestContentRetryBackoff(unittest.TestCase):
    """content（评审质量）失败重派短退避（tasks 5.3，3.1）。"""

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / ".tmp_infrattr2"
        self.tmp.mkdir(exist_ok=True)
        (self.tmp / ".fenix").mkdir(exist_ok=True)
        _FakeTimer.instances = []

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _manager(self, pm):
        return _make_manager(self.tmp, pm_engine=pm)

    def test_backoff_schedules_delayed_retry_with_dedup(self):
        """content 重派间隔不小于配置短退避；重复触发无重复定时器。"""
        pm = _PmStub(delay=5.0)
        m = self._manager(pm)
        m.state_machine.update_spec(
            "demo", {"status": "reviewing", "reviewer_run": "r1"}
        )

        with patch("threading.Timer", _FakeTimer):
            # 第一次 content 失败 → 排程退避定时器（不入队）
            m._handle_review_failure("demo", "Exit code: 1")
            self.assertEqual(len(_FakeTimer.instances), 1)
            timer = _FakeTimer.instances[0]
            self.assertGreaterEqual(
                timer.delay, 5.0, "重派延迟不得小于配置的短退避秒数"
            )
            self.assertEqual(timer.args, ("demo",))
            self.assertEqual(
                pm._review_content_backoff_timers, {"demo"}
            )
            self.assertEqual(pm.enqueued, [], "退避期内不得立即入队")

            # 第二次触发（判重）→ 不产生重复定时器
            m._handle_review_failure("demo", "Exit code: 1")
            self.assertEqual(
                len(_FakeTimer.instances), 1, "判重集合须阻止重复定时器"
            )

        # 到期回调：摘判重标记 → 重入队 → 重扫队列
        m._fire_content_backoff("demo")
        self.assertEqual(pm._review_content_backoff_timers, set())
        self.assertEqual(pm.enqueued, [("demo", "spec-review")])
        self.assertEqual(pm.rescanned, 1)

    def test_zero_delay_falls_back_to_immediate_enqueue(self):
        """delay=0（退避关闭）→ 立即入队降级，不排程定时器。"""
        pm = _PmStub(delay=0)
        m = self._manager(pm)
        m.state_machine.update_spec("demo", {"status": "reviewing"})

        with patch("threading.Timer", _FakeTimer):
            m._handle_review_failure("demo", "Exit code: 1")
        self.assertEqual(_FakeTimer.instances, [])
        self.assertEqual(pm.enqueued, [("demo", "spec-review")])

    def test_infra_branch_has_no_backoff_timer(self):
        """infra 分支节奏由熔断负责：不排程 content 短退避定时器。"""
        pm = _PmStub(delay=5.0)
        m = self._manager(pm)
        m.state_machine.update_spec("demo", {"status": "reviewing"})

        with patch("threading.Timer", _FakeTimer):
            m._handle_review_failure("demo", "Exit code: 1", api_error_status=429)
        self.assertEqual(_FakeTimer.instances, [], "infra 分支不得排程短退避")
        self.assertEqual(pm.enqueued, [])


class TestReviewFreezePrefix(unittest.TestCase):
    """评审冻结前缀区分（tasks 5.3，4.1）：三红线 + 人工冻结契约不变。"""

    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / ".tmp_infrattr3"
        self.tmp.mkdir(exist_ok=True)
        (self.tmp / ".fenix").mkdir(exist_ok=True)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_freeze_error_prefix_unchanged(self):
        """FREEZE_ERROR_PREFIX 常量值未被改动（freeze_spec 人工冻结契约）。"""
        self.assertEqual(FREEZE_ERROR_PREFIX, "用户指令冻结：")

    def test_new_prefixes_distinguishable_from_manual_freeze(self):
        """评审专用前缀与「用户指令冻结」可区分且各站点语义分明。"""
        self.assertNotEqual(REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX, FREEZE_ERROR_PREFIX)
        self.assertNotEqual(REVIEW_REJECTED_FREEZE_ERROR_PREFIX, FREEZE_ERROR_PREFIX)
        self.assertEqual(REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX, "评审失败冻结：")
        self.assertEqual(REVIEW_REJECTED_FREEZE_ERROR_PREFIX, "评审否决冻结：")

    def _assert_red_lines(self, error_msg: str):
        """三红线断言：可解冻还原 / 不挪用有意等待豁免 / 标记子串保留。"""
        # 红线①：「原状态 reviewing」子串可被 parse_orig_status 解析（解冻还原）
        self.assertIn("原状态 reviewing", error_msg)
        self.assertEqual(parse_orig_status(error_msg), "reviewing")
        # 红线②：不得命中 _INTENTIONAL_PAUSE_MARKERS 三短语、不以 "frozen:" 开头
        for marker in _INTENTIONAL_PAUSE_MARKERS:
            self.assertNotIn(marker, error_msg)
        self.assertFalse(error_msg.startswith("frozen:"))
        # 红线③补充：标记子串保留（re_review / 否决重做 startswith 契约）
        self.assertIn("spec-review-incomplete:", error_msg)

    def test_attempts_limit_freeze_message_satisfies_red_lines(self):
        """尝试上限冻结文案（生产格式）满足三条红线。"""
        msg = (
            f"{REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX}原状态 reviewing · "
            f"spec-review-incomplete: Exit code: 1"
        )
        self._assert_red_lines(msg)

    def test_rejected_freeze_message_satisfies_red_lines(self):
        """否决冻结文案（生产格式）满足三条红线。"""
        msg = (
            f"{REVIEW_REJECTED_FREEZE_ERROR_PREFIX}原状态 reviewing · "
            f"spec-review-rejected: 方案连续被否决"
        )
        # 红线①②同款；标记子串此处按否决形态核对
        self.assertIn("原状态 reviewing", msg)
        self.assertEqual(parse_orig_status(msg), "reviewing")
        for marker in _INTENTIONAL_PAUSE_MARKERS:
            self.assertNotIn(marker, msg)
        self.assertFalse(msg.startswith("frozen:"))
        self.assertIn("spec-review-rejected:", msg)

    def test_content_failure_exhaustion_freezes_with_review_prefix(self):
        """content 失败烧尽尝试预算 → 冻结走评审专用前缀 + 成对入口。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing", "reviewer_run": "r1"})
        # attempts 从 0 起：MAX+1 次 content 失败后达上限转冻结
        for _ in range(MAX_REVIEW_ATTEMPTS + 1):
            m._handle_review_failure("demo", "Exit code: 1")

        self.assertEqual(len(sm.freeze_calls), 1, "达上限恰冻结一次")
        call = sm.freeze_calls[0]
        error_msg = call["error"]
        self.assertTrue(
            error_msg.startswith(REVIEW_ATTEMPTS_FREEZE_ERROR_PREFIX),
            f"冻结文案须用评审专用前缀: {error_msg}",
        )
        self.assertNotIn(FREEZE_ERROR_PREFIX, error_msg, "自动冻结不得自称用户指令")
        self._assert_red_lines(error_msg)
        # freeze_for_human 成对契约：frozen 置位
        self.assertTrue(sm.read_one("demo").get("frozen"))

    def test_infra_failure_never_enters_freeze_path(self):
        """infra 分类失败（429）不进冻结路径：不递增 attempts、不落 frozen。"""
        m = _make_manager(self.tmp)
        sm = m.state_machine
        sm.update_spec("demo", {"status": "reviewing"})
        for _ in range(MAX_REVIEW_ATTEMPTS + 3):
            m._handle_review_failure(
                "demo", "Exit code: 1", api_error_status=429,
            )
        entry = sm.read_one("demo")
        self.assertEqual(sm.freeze_calls, [], "infra 失败不得冻结")
        self.assertNotIn("frozen", entry)
        self.assertEqual(entry.get("_review_attempts", 0), 0)


# ── evo-add-review-failure-attribution 3.1：失败行归因留痕 ───────────


def _mk_dispatch_project(tmpdir: Path, spec_name="spec"):
    """真实 StateMachine + SPEC 目录（同 test_spec_review_agent._mk_project 形态）。"""
    from core.state_machine import StateMachine

    (tmpdir / ".fenix").mkdir(parents=True, exist_ok=True)
    sm = StateMachine(tmpdir / ".fenix" / "STATE.md", MagicMock())
    spec_dir = tmpdir / "spec" / "changes" / spec_name
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 do it\n", encoding="utf-8")
    sm.add_spec(spec_name, {"status": "reviewing", "priority": 5})
    sm.update_spec(spec_name, {"reviewer_run": None})
    return sm


class _ScriptedReviewRunner:
    """受控评审 runner：按脚本返回失败结果或抛异常（桥接上游形态）。"""

    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc

    def _check_agent_result_artifact(self, spec_name, agent_type,
                                     run_started_at=None, wt_path=None):
        return "结果文件缺失"

    def run_spec_review(self, spec_name, run_id=None):
        if self.exc is not None:
            raise self.exc
        return self.result


class TestRunnerBridgeAttribution(unittest.TestCase):
    """run_spec_review 失败归因桥接（evo-add-review-failure-attribution 1.1/1.2）：
    stderr_tail / exit_code 与既有 api_error_status 并列随 AgentRunResult 透出，
    共享底座错误文本不改。"""

    def setUp(self):
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _runner(self):
        from core.agent_runner.runner import AgentRunner

        r = AgentRunner.__new__(AgentRunner)
        r.project_root = self.tmpdir
        r.logger = MagicMock()
        return r

    def _wire(self, r, boom):
        r._build_prompt = lambda *a, **k: "prompt"
        r._get_agent_model_assignment = lambda agent_type: None
        r._get_config = lambda key, default=None: default
        r._run_agent = boom

    def test_bridge_threads_stderr_tail_and_exit_code(self):
        """限流失败异常：stderr_tail 摘要（原始 stderr_lines 尾行）与 exit_code
        并列透出；error 保持 str(e) 原文（proposal Out of Scope 不改底座文本）。"""
        r = self._runner()

        def _boom(*a, **k):
            exc = RuntimeError("claude CLI failed: Exit code: 1")
            exc.stderr_lines = ["[claude-code:noise]", "Exit code: 1", ""]
            exc.exit_code = 1
            exc.api_error_status = 429
            raise exc

        self._wire(r, _boom)
        res = r.run_spec_review("demo")
        self.assertFalse(res.success)
        self.assertEqual(res.api_error_status, 429)
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(res.stderr_tail, "[claude-code:noise] | Exit code: 1")
        self.assertEqual(res.error, "claude CLI failed: Exit code: 1")

    def test_bridge_defaults_none_without_exception_attrs(self):
        """非 API 错误异常（取消/冻结终止等）不携带属性：字段缺省 None 兼容。"""
        r = self._runner()

        def _boom(*a, **k):
            raise RuntimeError("cancelled by admin")

        self._wire(r, _boom)
        res = r.run_spec_review("demo")
        self.assertFalse(res.success)
        self.assertIsNone(res.api_error_status)
        # _stderr_tail_summary 契约：无 stderr_lines → 空串（追溯摘要形态，
        # 与 code-fix 车道同源）；归因括注按 falsy 省略 stderr 段
        self.assertEqual(res.stderr_tail, "")
        self.assertIsNone(res.exit_code)


class TestFailureLineAttribution(unittest.TestCase):
    """评审失败 ERROR 行归因括注（evo-add-review-failure-attribution 1.3）：
    形态对齐 code-fix 车道、键名 api_error_status；result 为 None 的异常子路径
    括注整体省略。"""

    def setUp(self):
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp())
        self.logger = MagicMock()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _error_messages(self):
        msgs = []
        for call in self.logger.error.call_args_list:
            args = call[0]
            if len(args) >= 2:
                msgs.append(str(args[1]))
            elif args:
                msgs.append(str(args[0]))
        return msgs

    def _mgr(self, runner):
        sm = _mk_dispatch_project(self.tmpdir)
        engine = MagicMock()
        engine.is_review_in_flight = MagicMock(return_value=False)
        mgr = SpecReviewManager(self.tmpdir, sm, runner, engine, {}, self.logger)
        return mgr, sm

    def test_429_failure_line_carries_bracket(self):
        """限流失败就地归因：ERROR 行含 api_error_status=429、exit_code 与
        stderr_tail 摘要；:490 reason 侧（infra error 字段）同样携带括注。"""
        result = SimpleNamespace(
            success=False, error="claude CLI failed: Exit code: 1",
            api_error_status=429, exit_code=1,
            stderr_tail="Exit code: 1 | [claude-code:unrecognized_model]",
            frozen_terminated=False,
        )
        mgr, sm = self._mgr(_ScriptedReviewRunner(result=result))
        self.assertFalse(mgr.dispatch_review("spec"))
        joined = "\n".join(self._error_messages())
        self.assertIn(
            "评审 run 执行失败: spec: claude CLI failed: Exit code: 1 "
            "[api_error_status=429 exit_code=1 stderr_tail: "
            "Exit code: 1 | [claude-code:unrecognized_model]]",
            joined,
        )
        err_field = str(sm.read_one("spec").get("error") or "")
        self.assertIn("spec-review-incomplete: infra failure: ", err_field)
        self.assertIn("[api_error_status=429 exit_code=1 stderr_tail: ", err_field)

    def test_exception_path_omits_bracket(self):
        """result 为 None 的异常子路径（run_spec_review 抛异常）：无结构化字段
        可读，括注整体省略不添噪。"""
        mgr, sm = self._mgr(
            _ScriptedReviewRunner(exc=RuntimeError("派发进程崩了"))
        )
        self.assertFalse(mgr.dispatch_review("spec"))
        line = [m for m in self._error_messages() if "评审 run 执行失败" in m][0]
        self.assertIn("评审 run 执行失败: spec: 派发进程崩了", line)
        self.assertNotIn("[api_error_status=", line)
        self.assertNotIn("stderr_tail:", line)

    def test_plain_failure_without_fields_no_bracket(self):
        """三元全空的普通失败结果：不添噪。"""
        result = SimpleNamespace(
            success=False, error="Exit code: 1", frozen_terminated=False,
        )
        mgr, sm = self._mgr(_ScriptedReviewRunner(result=result))
        self.assertFalse(mgr.dispatch_review("spec"))
        line = [m for m in self._error_messages() if "评审 run 执行失败" in m][0]
        self.assertIn("评审 run 执行失败: spec: Exit code: 1", line)
        self.assertNotIn("[api_error_status=", line)


if __name__ == "__main__":
    unittest.main()
