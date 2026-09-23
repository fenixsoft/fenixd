"""fix-fasttrack-implemented-deadstate：fast-track implemented 死态恢复出口测试。

覆盖矩阵（tasks.md 1.4）：
- 死态重入走完收尾：重入 → testing → join defer（产物缺失幂等补启车道）→
  车道完成回调既有唤醒路径 → verified（含 _on_spec_verified 交接）；
- 恢复三条件任一不成立维持既有短路（负例：①status/implementer_run
  ②转录 mtime 宽限窗 ③ocr_lane_busy 在飞）；
- 正常收尾流不触发重入（孤儿 planner 防线不变）；
- 重入路径不读 fast-track 共享结果文件；
- 重入动作 INFO 日志在场（spec 名/判据/动作）；
- ocr_lane_busy 公开判定：带参 per-spec / 无参任一在飞 / 异常按 busy。

引擎侧用真实 PMEngine + 真实 StateMachine（_write_spec_mode 落 .spec.yaml），
dispatcher 收尾段用 FakePM/FakeSM 驱动（与 test_impl_ocr_parallel_lane 同款）。
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pm_engine import PMEngine
from core.pm_engine.dispatch import Dispatcher
from core.state_machine import ENV_BLOCK_ROUNDS_FIELD, StateMachine

# join 门禁指纹三件套（_ocr_current_fingerprint 产物：branch/_ocr_base_commit/
# _git_rev_parse(branch) 钉死，不经真 git）
FP = {"branch": "fenix/demo", "merge_base": "aa", "head_commit": "bb"}


class FakeLogger:
    def __init__(self):
        self.debugs, self.infos, self.warns = [], [], []

    def debug(self, *a, **kw):
        self.debugs.append(" ".join(str(x) for x in a))

    def info(self, *a, **kw):
        self.infos.append(" ".join(str(x) for x in a))

    def warning(self, *a, **kw):
        self.warns.append(" ".join(str(x) for x in a))

    def error(self, *a, **kw):
        pass


class FakeSM:
    """最小 StateMachine：read_one/update_spec/transition（记录 trigger_run_id）。"""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.transitions = []

    def read_one(self, spec_name):
        entry = self.entries.get(spec_name)
        return dict(entry) if entry else None

    def update_spec(self, spec_name, patch):
        self.entries.setdefault(spec_name, {}).update(patch)

    def transition(self, spec_name, to, *, trigger_run_id=None,
                   agent_type=None, channel="auto") -> bool:
        # 签名对齐生产 StateMachine.transition（双保真：不比 prod 更宽容）
        self.transitions.append((spec_name, to, trigger_run_id))
        self.entries.setdefault(spec_name, {})["status"] = to
        return True


class FakePM:
    def __init__(self, project_root: Path, config: dict | None = None):
        self.project_root = project_root
        self.config = config or {}
        self.logger = FakeLogger()
        self.state_machine = FakeSM()
        self.verified_calls = []
        # 恢复重入路径 tripwire：任何对共享结果文件的读取都会被记录
        self._read_implementer_result = MagicMock(return_value=None)

    def _env_whitewash_gate(self, spec_name):
        return True

    def _on_spec_verified(self, spec_name):
        self.verified_calls.append(spec_name)


def _make_dispatcher(repo: Path, config: dict | None = None):
    pm = FakePM(repo, config)
    return Dispatcher(pm), pm


def _seed_implemented(dispatcher: Dispatcher, pm: FakePM, spec: str = "demo",
                      status: str = "implemented",
                      implementer_run: str = "impl-demo-42"):
    pm.state_machine.entries[spec] = {
        "status": status,
        "implementer_run": implementer_run,
        "branch": "fenix/demo",
        "_ocr_base_commit": "aa",
    }
    # head 分量钉住（不经真 git）
    dispatcher._git_rev_parse = (
        lambda ref: "bb" if ref == "fenix/demo" else None
    )


def _write_artifact(root: Path, spec: str = "demo", findings=None):
    path = root / ".fenix" / "verify-progress" / spec / "code-review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "status": "completed",
            "fingerprint": FP,
            "findings": findings or [],
            "run_id": "impl-ocr-demo-1",
        }),
        encoding="utf-8",
    )
    return path


class TestOcrLaneBusy:
    """ocr_lane_busy 公开判定（tasks 2.1：带参/无参/异常按 busy）。"""

    def test_no_arg_any_inflight_is_busy(self, tmp_path):
        dispatcher, _pm = _make_dispatcher(tmp_path)
        assert dispatcher.ocr_lane_busy() is False
        dispatcher._ocr_lane_inflight["a"] = True
        assert dispatcher.ocr_lane_busy() is True

    def test_with_spec_scoped_lookup(self, tmp_path):
        dispatcher, _pm = _make_dispatcher(tmp_path)
        dispatcher._ocr_lane_inflight["a"] = True
        assert dispatcher.ocr_lane_busy("a") is True
        assert dispatcher.ocr_lane_busy("b") is False
        assert dispatcher.ocr_lane_busy("demo") is False

    def test_exception_treated_busy(self, tmp_path):
        # 宁紧勿松：内部异常（锁不可用等）按 busy 处理
        dispatcher, _pm = _make_dispatcher(tmp_path)
        dispatcher._ocr_lane_lock = None  # with None → 异常
        assert dispatcher.ocr_lane_busy() is True
        assert dispatcher.ocr_lane_busy("a") is True


class TestResumeFastTrackAfterRestart:
    """恢复重入收尾段（tasks 1.2：implemented → testing → 收尾段复用）。"""

    def _deferred_reentry(self, tmp_path, config):
        """重入至 join defer 停等（产物缺失 → 幂等补启车道）。"""
        dispatcher, pm = _make_dispatcher(tmp_path, config)
        _seed_implemented(dispatcher, pm)
        started = []
        dispatcher._start_impl_ocr_lane = (
            lambda spec, fp: started.append((spec, fp)) or "started"
        )
        dispatcher._resume_fast_track_after_restart("demo")
        return dispatcher, pm, started

    def test_dead_state_reentry_defers_and_awaits_lane(self, tmp_path):
        dispatcher, pm, started = self._deferred_reentry(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        # implemented → testing（channel=auto 语义，trigger_run_id=implementer_run）
        assert pm.state_machine.transitions == [
            ("demo", "testing", "impl-demo-42")
        ]
        entry = pm.state_machine.read_one("demo")
        assert entry["status"] == "testing"
        # join defer：pending 停等标记落盘 + 幂等补启车道（恢复形态的兜底可达）
        assert entry["_ocr_join_wait"] == 1
        assert entry["_ocr_join_agent"] == "fast-track"
        assert started == [("demo", FP)]
        assert pm.verified_calls == []  # defer 停等，不推 verified

    def test_lane_finish_callback_completes_to_verified(self, tmp_path):
        dispatcher, pm, _started = self._deferred_reentry(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        # 车道收尾：产物落盘（指纹新鲜、零 actionable）→ 回调唤醒 join 重评
        _write_artifact(Path(pm.project_root))
        dispatcher._on_impl_ocr_lane_finished("demo", "impl-ocr-demo-1")
        entry = pm.state_machine.read_one("demo")
        assert entry["status"] == "verified"
        assert pm.verified_calls == ["demo"]
        assert entry.get("tester_run")

    def test_reentry_does_not_read_shared_result_file(self, tmp_path):
        # 结果文件已在首次收尾时消费清理，重入 MUST NOT 再读（tripwire 断言）
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": False}}
        )
        _seed_implemented(dispatcher, pm)
        dispatcher._resume_fast_track_after_restart("demo")
        pm._read_implementer_result.assert_not_called()

    def test_reentry_writes_verified_zero_reset_fields(self, tmp_path):
        # 清零点字段集由抽取段统一写入（禁止复制粘贴漂移的回归锚点，tasks 1.1）
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": False}}
        )
        _seed_implemented(dispatcher, pm)
        dispatcher._resume_fast_track_after_restart("demo")
        entry = pm.state_machine.read_one("demo")
        assert entry["status"] == "verified"
        assert pm.verified_calls == ["demo"]
        assert entry["error"] is None
        assert entry["_inconclusive_attempts"] == 0
        assert entry["_verify_parallel_override"] is None
        assert entry["_verify_fail_rounds"] == 0
        assert entry["_verify_redo_count"] == 0
        assert entry[ENV_BLOCK_ROUNDS_FIELD] == 0

    def test_reentry_reuses_finalize_segment(self, tmp_path):
        # 1.1 抽取约束：advance 与恢复路径共用同一段（advance 内部转调）
        dispatcher, _pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": False}}
        )
        calls = []
        dispatcher._fast_track_finalize_after_testing = (
            lambda spec, result: calls.append((spec, getattr(result, "run_id", None)))
        )
        _seed_implemented(dispatcher, _pm)
        dispatcher._resume_fast_track_after_restart("demo")
        assert calls == [("demo", "impl-demo-42")]


class _RecoveryEngineBase(unittest.TestCase):
    """引擎侧基座：真实 PMEngine + 真实 StateMachine + .spec.yaml 落盘。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.project_root = Path(self.tmpdir)
        (self.project_root / ".fenix").mkdir(parents=True, exist_ok=True)
        self.logger = MagicMock()
        self.sm = StateMachine(
            self.project_root / ".fenix" / "STATE.md", self.logger
        )
        self.agent_runner = MagicMock()
        self.engine = PMEngine(
            self.sm, self.agent_runner, {}, self.project_root, self.logger
        )
        self.engine._enqueue = MagicMock()
        self.resume = MagicMock()
        self.engine._dispatcher._resume_fast_track_after_restart = self.resume

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_spec_mode(self, name, mode="fast-track"):
        d = self.project_root / "spec" / "changes" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / ".spec.yaml").write_text(
            f"schema: spec-driven\ncreated: 2026-09-23\nmode: {mode}\n",
            encoding="utf-8",
        )

    def _seed_entry(self, name, status="implemented",
                    implementer_run="impl-ft-spec-1", mtime_age=None):
        """真实 StateMachine 注册条目 + 可选落一份 age 秒前的 run 转录文件。"""
        entry = {"status": status}
        if implementer_run is not None:
            entry["implementer_run"] = implementer_run
        self.sm.add_spec(name, entry)
        if implementer_run:
            runs = self.project_root / ".fenix" / "runs"
            runs.mkdir(parents=True, exist_ok=True)
            f = runs / f"{implementer_run}.jsonl"
            f.write_text('{"event": "start"}\n', encoding="utf-8")
            if mtime_age is not None:
                old = time.time() - mtime_age
                os.utime(f, (old, old))


class TestOnSpecImplementedRecovery(_RecoveryEngineBase):
    """_on_spec_implemented 恢复三条件判定（tasks 1.3 / spec 死态恢复场景）。"""

    def test_dead_state_reenters(self):
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="implemented",
                         implementer_run="impl-ft-spec-1", mtime_age=600)
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_called_once_with("ft-spec")
        self.engine._enqueue.assert_not_called()  # 孤儿 planner 防线不变
        # 重入动作可观测：INFO 日志含 spec 名/判据/动作
        infos = " ".join(str(c) for c in self.engine.logger.info.call_args_list)
        assert "恢复重入" in infos and "ft-spec" in infos

    def test_dead_state_reentry_full_chain_to_verified(self):
        # 端到端（ocr 关闭 → join 即时放行）：implemented → testing → verified
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="implemented",
                         implementer_run="impl-ft-spec-1", mtime_age=600)
        # 恢复 setUp 的 MagicMock 桩，还原真实绑定方法（del 实例属性即回落类绑定）
        del self.engine._dispatcher._resume_fast_track_after_restart
        self.engine._on_spec_verified = MagicMock()
        self.engine._on_spec_implemented("ft-spec")
        entry = self.sm.read_one("ft-spec")
        assert entry["status"] == "verified"
        self.engine._on_spec_verified.assert_called_once_with("ft-spec")

    def test_stranded_testing_reenters_finalize_only(self):
        # 条件① testing 搁浅形态（code-review item 3766612aca27）：收尾段在
        # testing 转移之后抛异常搁浅（无车道、无 pending 停等标记、run 已死）
        # 时重发事件重入收尾——already_testing=True（VALID_TRANSITIONS 不允许
        # testing→implemented 回滚重走，只能直接重跑收尾段）。
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="testing",
                         implementer_run="impl-ft-spec-1", mtime_age=600)
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_called_once_with("ft-spec", already_testing=True)
        self.engine._enqueue.assert_not_called()  # 孤儿 planner 防线不变

    def test_negative_testing_with_pending_waker(self):
        # 条件① testing 形态负例：pending 停等标记在场（_ocr_join_wait）=
        # 车道完成回调唤醒路径在场，不经恢复入口重入（防双驱动）。
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="testing",
                         implementer_run="impl-ft-spec-1", mtime_age=600)
        self.sm.update_spec(
            "ft-spec", {"_ocr_join_wait": 1, "_ocr_join_agent": "fast-track"}
        )
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_not_called()
        self.engine._enqueue.assert_not_called()

    def test_negative_implementer_run_missing(self):
        # 条件①不成立：implementer_run 为空（legacy/手工 spec）不重入
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="implemented",
                         implementer_run=None, mtime_age=600)
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_not_called()
        self.engine._enqueue.assert_not_called()

    def test_negative_run_transcript_fresh(self):
        # 条件②不成立：run 转录 mtime 新鲜（run 活着）不重入
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="implemented",
                         implementer_run="impl-ft-spec-1", mtime_age=None)
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_not_called()
        self.engine._enqueue.assert_not_called()

    def test_negative_ocr_lane_inflight(self):
        # 条件③不成立：本 spec 车道在飞（收尾可能由回调推进中）不重入
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="implemented",
                         implementer_run="impl-ft-spec-1", mtime_age=600)
        self.engine._dispatcher._ocr_lane_inflight["ft-spec"] = True
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_not_called()
        self.engine._enqueue.assert_not_called()

    def test_normal_finish_flow_no_reentry(self):
        # 正常收尾连跳后（testing + 转录新鲜）恢复循环重发事件：维持既有短路
        self._write_spec_mode("ft-spec")
        self._seed_entry("ft-spec", status="testing",
                         implementer_run="impl-ft-spec-1", mtime_age=None)
        self.engine._on_spec_implemented("ft-spec")
        self.resume.assert_not_called()
        self.engine._enqueue.assert_not_called()
        debugs = " ".join(str(c) for c in self.engine.logger.debug.call_args_list)
        assert "单 run 全包" in debugs

    def test_full_mode_still_enqueued(self):
        # full 模式 spec 不受恢复出口影响：照常入队 verifier
        self._write_spec_mode("full-spec", mode="full")
        self.engine._on_spec_implemented("full-spec")
        self.engine._enqueue.assert_called_once_with("full-spec", "verifier")


if __name__ == "__main__":
    unittest.main()
