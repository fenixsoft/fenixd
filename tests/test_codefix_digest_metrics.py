"""tests/test_codefix_digest_metrics.py — evo-add-codefix-digest-cost-metrics

覆盖：
- 3.1 run 工具构成指标（1.1/1.2）：含 tool_use 与纯文本行的转录样本 →
  run_metrics 行的 tool_uses 直方图（按名计数）/ tool_uses_total /
  text_turns 正确，且先于 result 终态行落盘（文件末行仍是终态）；
  metrics 落盘失败不阻断 run 终态（_run_agent 正常返回、result 行照常落盘）。
- 3.2 链级 rollup（2.1/2.2）：多 run 链末批合回成功（trigger=chain_last_batch）
  与链中途终局（run 失败跳批 → 选批为空 blocked 终局 trigger=chain_exhausted）
  两形态——run 数/轮数/tool_use/条数汇总与台账核销一致、覆盖链中全部 run
  不漏样本（链级持久清单记账）、归档缺失按零贡献、一行结构化日志在场。

MUST NOT 真跑 agent / 真跑回归——runner 侧用假 Popen 流，编排侧用 fake
runner + 真 git 仓 worktree 替身。
"""

import io
import itertools
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.agent_runner import AgentRunner
from core.agent_runner import runner as runner_module
import core.agent_runner.maintenance_runs as maintenance_runs_module
from core.code_fix import (
    FIX_PROGRESS_DEFAULT,
    CodeFixOrchestrator,
    _read_run_metrics,
    read_items,
    read_progress,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_HISTORY_TMP = Path(__file__).resolve().parent.parent / ".history" / "tmp"
_HISTORY_TMP.mkdir(parents=True, exist_ok=True)


def _mkdtemp(prefix: str) -> str:
    return tempfile.mkdtemp(prefix=prefix, dir=str(_HISTORY_TMP))


# ═════════════════════════════════════════════════════════════════════════════
# 3.1 run 工具构成指标（runner 侧）
# ═════════════════════════════════════════════════════════════════════════════


class _FakeLogger:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeProc:
    """假 Popen：stdout 预载脚本化转录（StringIO 逐行 readline），秒退。"""

    # 不可达 pid 取正值越界（2**22 > Linux 默认 pid_max=4194304），对齐
    # add-killpg-self-guard 对本替身的口径：本替身流入组长直传型清场点
    # （maintenance_runs/_kill_ocr_process_group、liveness 的 killpg 直传跳），
    # test_knowledge_backfill.py 先例的 -1 在该语境不成立（os.killpg(-1) 经
    # kill(-pgid) 折算 ≡ kill(1) 误投递、pid=-1 直传同样命中负值折算），故
    # 不可达性以「正但不可能存在」达成。守卫 pgid<=0 拒绝分支是第二道防线，
    # 守卫未落地前 pid=0 曾使 killpg(0) 折算为 kill(0)＝调用者自身进程组
    # 广播，全量回归被团灭（2026-10-07 事故形态）。
    UNREACHABLE_PID = 2**22

    def __init__(self, out_lines):
        self.stdout = io.StringIO("".join(line + "\n" for line in out_lines))
        self.stderr = io.StringIO("")
        self.pid = _FakeProc.UNREACHABLE_PID

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def _make_runner(proot: Path) -> AgentRunner:
    """最小 AgentRunner（__new__ 绕过 __init__），缝对齐 test_run_stop_loss。"""
    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = proot
    runner.logger = _FakeLogger()
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    runner._worktree_path_valid = lambda p: False
    return runner


def _assistant_event(text=None, tool_name=None, tool_id="tu1"):
    """构造 assistant 流事件：带 tool_use block 或纯文本行（1.1 统计对象）。"""
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool_name is not None:
        content.append(
            {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {}}
        )
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": content,
            "usage": {"input_tokens": 10, "output_tokens": 1},
        },
    }


def _transcript_lines():
    """含 tool_use 与纯文本行的转录样本：5 个 assistant 轮 + result 终态。

    Read×2、Bash×1、纯文本×2 → 期望 tool_uses={"Bash":1,"Read":2}、
    tool_uses_total=3、text_turns=2、turns=5。
    """
    events = [
        _assistant_event(tool_name="Read", tool_id="t1"),
        _assistant_event(tool_name="Bash", tool_id="t2"),
        _assistant_event(text="locating..."),
        _assistant_event(tool_name="Read", tool_id="t3"),
        _assistant_event(text="done"),
        {
            "type": "result",
            "subtype": "success",
            "result": "ok",
            "num_turns": 5,
            "session_id": "sess-1",
            "usage": {"input_tokens": 50, "output_tokens": 5},
        },
    ]
    return [json.dumps(e, ensure_ascii=False) for e in events]


def _drive_run_agent(runner, proot, run_id, lines):
    """以假 Popen 驱动真实 _run_agent（读线程/指标落盘/终态次序全真）。"""
    orig_popen = runner_module.subprocess.Popen
    runner_module.subprocess.Popen = lambda cmd, **kw: _FakeProc(lines)
    try:
        return runner._run_agent(
            "prompt", proot, run_id,
            model_override="m", max_turns=50,
            spec_name="spec-x", agent_type="implementer",
        )
    finally:
        runner_module.subprocess.Popen = orig_popen


def _read_run_file(proot: Path, run_id: str) -> list[dict]:
    path = proot / ".fenix" / "runs" / f"{run_id}.jsonl"
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


class TestToolCompositionMetrics:
    def test_histogram_and_text_turns(self, tmp_path):
        """tool_use 按名直方图 + 纯文本行计数正确，先于终态行落盘（1.1）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        runner = _make_runner(proot)
        rid = "code-fix-metrics-x1"

        output, turns, session_id, _usage, _stall = _drive_run_agent(
            runner, proot, rid, _transcript_lines()
        )

        assert output == "ok"
        assert turns == 5
        lines = _read_run_file(proot, rid)
        metrics = [r for r in lines if r.get("type") == "run_metrics"]
        assert len(metrics) == 1, "run 收尾恰落一条 run_metrics 行"
        m = metrics[0]
        # 直方图按工具名计数；总数为直方图求和（单一真源）
        assert m["tool_uses"] == {"Bash": 1, "Read": 2}
        assert m["tool_uses_total"] == 3
        # 无 tool_use 的 assistant 轮单列 text_turns（2 个纯文本行）
        assert m["text_turns"] == 2
        assert m["turns"] == 5
        assert m["run_id"] == rid
        # run_metrics 行在 result 终态行之前追加：文件末行仍是终态
        assert lines[-1]["type"] == "result"

    def test_metrics_persist_failure_does_not_block_terminal(self, tmp_path, monkeypatch):
        """metrics 落盘失败（如盘满）不阻断 run 终态（1.1 既有语义）。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        runner = _make_runner(proot)
        rid = "code-fix-metrics-x2"

        orig_append = runner_module.append_run_line

        def _boom(run_file, entry):
            if isinstance(entry, dict) and entry.get("type") == "run_metrics":
                raise OSError("disk full")
            return orig_append(run_file, entry)

        monkeypatch.setattr(runner_module, "append_run_line", _boom)

        output, turns, _sess, _usage, _stall = _drive_run_agent(
            runner, proot, rid, _transcript_lines()
        )

        # _run_agent 正常返回（未被 OSError 打断）
        assert output == "ok"
        assert turns == 5
        lines = _read_run_file(proot, rid)
        assert not [r for r in lines if r.get("type") == "run_metrics"]
        # result 终态行照常落盘且为文件末行
        assert lines[-1]["type"] == "result"

    def test_text_only_transcript_counts(self, tmp_path):
        """全纯文本转录（无任何 tool_use）：text_turns 逐轮计数、直方图为空。"""
        proot = tmp_path / "proj"
        (proot / ".fenix" / "runs").mkdir(parents=True)
        runner = _make_runner(proot)
        rid = "code-fix-metrics-x3"
        lines = [
            json.dumps(_assistant_event(text="a")),
            json.dumps(_assistant_event(text="b")),
            json.dumps({"type": "result", "subtype": "success",
                        "result": "ok", "num_turns": 2, "session_id": "s"}),
        ]
        _drive_run_agent(runner, proot, rid, lines)
        m = next(r for r in _read_run_file(proot, rid)
                 if r.get("type") == "run_metrics")
        assert m["tool_uses"] == {}
        assert m["tool_uses_total"] == 0
        assert m["text_turns"] == 2


# ═════════════════════════════════════════════════════════════════════════════
# 3.2 链级 rollup（编排侧）
# ═════════════════════════════════════════════════════════════════════════════


class _RecLogger:
    """捕获日志的 fake logger（编排器 _log 形如 logger.info(tag, msg)）。"""

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


def _make_git_repo() -> Path:
    """最小 git 仓（零有效修复守卫的提交数判据需要真提交）。"""
    repo = Path(_mkdtemp("rollup-repo-"))
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True, capture_output=True)
    return repo


class _FakeWM:
    """fake worktree_manager：create 返回真 git 仓，merge_back 恒成功。"""

    def __init__(self):
        self.create_calls = []
        self.merge_calls = []
        self.cleanup_calls = []
        self._create_result = "git"

    def create(self, spec_name, agent_type="implementer"):
        self.create_calls.append((spec_name, agent_type))
        if self._create_result is None:
            return None
        return _make_git_repo()

    def merge_back(self, wt_path):
        self.merge_calls.append(str(wt_path))
        return SimpleNamespace(success=True, error="")

    def release_spec_lock(self, spec_name, agent_type="implementer"):
        return True

    def cleanup(self, wt_path, success=True):
        self.cleanup_calls.append((str(wt_path), success))
        import shutil
        shutil.rmtree(str(wt_path), ignore_errors=True)


class _RollupRunner:
    """fake AgentRunner：run_code_fix 写产物+提交+主树 run 归档；回归恒 passed。

    每个 run 的归档 run_metrics 行随 run 序号递增（turns=10n / tools=7n /
    text=n），供链级汇总断言「逐 run 求和、不漏样本」。
    """

    def __init__(self, project_root, fix_success=True, archive_runs=False,
                 metrics_plan=None, write_run_file=True):
        self.project_root = Path(project_root)
        self._running_agents = {}
        self.config = {}
        self.worktree_manager = _FakeWM()
        self.fix_success = fix_success
        # fix-codefix-rollup-archive-read 夹具开关：archive_runs=True 时 run
        # 归档直接落 .fenix/runs/archive/（模拟 retention 移档后仅存归档副
        # 本）；metrics_plan 逐 run 覆盖 metrics 行体（本窗口真实形状）；
        # write_run_file=False 时不落任何 run 文件（双缺失边界）。
        self.archive_runs = archive_runs
        self._metrics_plan = list(metrics_plan or [])
        self.write_run_file = write_run_file
        self._run_no = 0
        self.run_ids = []

    def _get_config(self, key, default=None):
        return self.config.get(key, default)

    def run_code_fix(self, worktree_root, items, run_id=None, failure_summary=""):
        self._run_no += 1
        rid = run_id or f"code-fix-fake-{self._run_no}"
        self.run_ids.append(rid)
        wt = Path(worktree_root)
        out = wt / ".fenix" / "code-review" / f"fix-out-{rid}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for it in items:
                fh.write(json.dumps(
                    {"item_id": it["item_id"], "status": "fixed",
                     "file": it.get("file", "")}, ensure_ascii=False) + "\n")
        if self.fix_success:
            # 提交（零有效修复守卫的 git 侧判据）
            (wt / f"touched-{rid}.txt").write_text("fix", encoding="utf-8")
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "add", "-A"],
                cwd=wt, check=True, capture_output=True)
            subprocess.run(
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", f"fix-{rid}"],
                cwd=wt, check=True, capture_output=True)
            # 主树 run 归档（含 run_metrics 行；run 失败=未到收尾→不落）
            if self.write_run_file:
                n = self._run_no
                runs_dir = self.project_root / ".fenix" / "runs"
                if self.archive_runs:
                    archive = runs_dir / "archive" / f"{rid}.jsonl"
                else:
                    archive = runs_dir / f"{rid}.jsonl"
                archive.parent.mkdir(parents=True, exist_ok=True)
                body = {
                    "type": "run_metrics",
                    "run_id": rid,
                    "turns": 10 * n,
                    "tool_uses_total": 7 * n,
                    "text_turns": n,
                    "tool_uses": {"Read": 3 * n, "Bash": 2 * n},
                }
                if n <= len(self._metrics_plan):
                    body.update(self._metrics_plan[n - 1])
                archive.write_text(
                    json.dumps(body) + "\n",
                    encoding="utf-8")
        return SimpleNamespace(
            run_id=rid, success=self.fix_success,
            fixed=len(items) if self.fix_success else 0,
            skipped=0, error="" if self.fix_success else "agent boom",
            output="done")

    def run_regression(self, spec, reason="manual", project_root=None,
                       lock_root=None, subset_nodeids=None):
        return SimpleNamespace(status="passed", snapshot={"failures": []},
                               error="")


def _make_project_root(items_spec) -> Path:
    """临时项目根：items.jsonl + 有效 verify.yaml 契约 + runs 目录。"""
    proot = Path(_mkdtemp("rollup-proot-"))
    (proot / ".fenix" / "code-review").mkdir(parents=True, exist_ok=True)
    (proot / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    records = {}
    for iid in items_spec:
        # 每条目独立顶层目录（异目录组）：batch_size=1 时逐条成批
        records[iid] = {
            "item_id": iid, "status": "open", "file": f"{iid}/{iid}.py",
            "line": 1, "severity": "major", "category": "correctness",
            "title": f"title {iid}", "description": f"desc {iid}",
            "suggestion": f"sug {iid}", "fingerprint": f"fp-{iid}",
        }
    lines = "".join(
        json.dumps(records[k], ensure_ascii=False) + "\n" for k in sorted(records)
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
        rid = f"code-fix-rollup-{next(counter)}"
        assert rid not in set(exclude or ())
        return rid

    monkeypatch.setattr(
        maintenance_runs_module, "_unique_code_fix_run_id", _fake_unique)
    return counter


class TestChainRollupLastBatch:
    def test_multi_run_chain_last_batch_rollup(self, seq_run_ids):
        """多 run 链末批合回成功：run 数/轮数/tool_use/条数与台账核销一致。

        两批（batch_size=1）→ 链级清单 2 个 run；末批合回时出账
        trigger=chain_last_batch，汇总=逐 run 归档求和；出账后链级累积归零，
        后续收敛（idle）不再重复出账。
        """
        proot = _make_project_root(["a", "b"])
        runner = _RollupRunner(proot, fix_success=True)
        rec = _RecLogger()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1, logger=rec)

        res = orch.checkpoint()
        assert res["triggered"] is True
        assert len(runner.run_ids) == 2, "两批各一个 run，链共 2 run"

        prog = read_progress(proot)
        # 链收敛后终态 idle；出账后链级清单归零（机械不漏样本的另一面：
        # 出账即清账，新链从空累积起步）
        assert prog["phase"] == "idle"
        assert prog["chain_run_ids"] == []
        assert prog["chain_resolved"] == 0
        assert prog["chain_ignored"] == 0

        rollup = prog["chain_rollup"]
        assert rollup is not None
        assert rollup["trigger"] == "chain_last_batch"
        assert rollup["runs"] == 2
        assert rollup["run_ids"] == runner.run_ids
        # 逐 run 归档求和：run1(turns=10,tools=7,text=1) + run2(20,14,2)
        assert rollup["turns"] == 30
        assert rollup["tool_uses_total"] == 21
        assert rollup["text_turns"] == 3
        # 条目计数与台账核销一致：两批各核销 1 条
        assert rollup["resolved"] == 2
        assert rollup["ignored"] == 0
        assert rollup["avg_turns_per_item"] == 15.0
        assert rollup.get("finished_at")

        # 台账侧真值：两条目均 resolved
        ledger = read_items(proot)
        assert ledger["a"]["status"] == "resolved"
        assert ledger["b"]["status"] == "resolved"

        # 一行结构化 rollup 日志在场（含关键汇总字段）
        rollup_logs = [
            msg for lv, _tag, msg in rec.records
            if lv == "info" and "chain rollup" in msg
        ]
        assert any(
            "trigger=chain_last_batch" in m and "runs=2" in m
            and "turns=30" in m and "resolved=2" in m
            for m in rollup_logs
        ), rollup_logs

    def test_intermediate_batch_does_not_emit(self, seq_run_ids):
        """非末批合回不出账（chain_rollup 缺席、清单继续累积）。"""
        proot = _make_project_root(["a", "b"])

        # 用记录型 executor 截断自驱动：只跑第一批
        class _HoldExecutor:
            def __init__(self):
                self.jobs = []

            def submit(self, fn, *a, **k):
                self.jobs.append((fn, a, k))

        runner = _RollupRunner(proot, fix_success=True)
        hold = _HoldExecutor()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1,
                                   logger=_RecLogger(), executor=hold)
        res = orch.checkpoint()
        assert res["triggered"] is True
        assert len(hold.jobs) == 1
        hold.jobs[0][0](*hold.jobs[0][1], **hold.jobs[0][2])  # 跑第一批

        prog = read_progress(proot)
        assert prog["chain_rollup"] is None, "非末批不出账"
        assert len(prog["chain_run_ids"]) == 1
        assert prog["chain_resolved"] == 1


class TestChainRollupMidChainTerminal:
    def test_run_failure_skip_chain_exhausted_rollup(self, seq_run_ids):
        """链中途终局（run 失败跳批 → 选批为空 blocked 终局）同样出账。

        两批全部 run 失败 → 条目入 chain_skipped → 选批为空 → blocked 终局
        （failed_batch_retained）：rollup trigger=chain_exhausted，run 清单
        覆盖失败 run（启动写点即记账），归档缺失按零贡献，条目计数=0（无
        核销），条目保持 open。
        """
        proot = _make_project_root(["a", "b"])
        runner = _RollupRunner(proot, fix_success=False)
        rec = _RecLogger()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1, logger=rec)

        res = orch.checkpoint()
        assert res["triggered"] is True
        assert len(runner.run_ids) == 2, "两批各一个失败 run"

        prog = read_progress(proot)
        assert prog["phase"] == "blocked"
        assert prog["reason"] == "failed_batch_retained"

        rollup = prog["chain_rollup"]
        assert rollup is not None
        assert rollup["trigger"] == "chain_exhausted"
        assert rollup["runs"] == 2
        assert rollup["run_ids"] == runner.run_ids, "失败 run 也在链清单"
        # run 未到收尾 → 归档缺失 → 零贡献（不炸链终局）
        assert rollup["turns"] == 0
        assert rollup["tool_uses_total"] == 0
        assert rollup["text_turns"] == 0
        # 无核销：条目计数 0，条均轮数无分母为 None
        assert rollup["resolved"] == 0
        assert rollup["ignored"] == 0
        assert rollup["avg_turns_per_item"] is None
        # 出账后清账
        assert prog["chain_run_ids"] == []
        # 条目未核销（保持 open）、入链内跳过集
        ledger = read_items(proot)
        assert ledger["a"]["status"] == "open"
        assert ledger["b"]["status"] == "open"
        assert prog["chain_skipped"] == ["a", "b"]

    def test_halt_terminal_emits_rollup(self, seq_run_ids):
        """halt 终局（worktree 创建失败）出账：既往批次累积值不丢。"""
        proot = _make_project_root(["a", "b"])

        class _HoldExecutor:
            def __init__(self):
                self.jobs = []

            def submit(self, fn, *a, **k):
                self.jobs.append((fn, a, k))

        def _run_one(hold):
            fn, a, k = hold.jobs.pop(0)
            fn(*a, **k)

        runner = _RollupRunner(proot, fix_success=True)
        hold = _HoldExecutor()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1,
                                   logger=_RecLogger(), executor=hold)
        orch.checkpoint()
        _run_one(hold)  # 第一批成功合回（非末批）
        prog = read_progress(proot)
        assert prog["chain_rollup"] is None  # 非末批不出账
        assert prog["chain_run_ids"] == runner.run_ids

        # 下一批建树失败 → halt → 链终局出账（既往 run 的累积值在场）
        runner.worktree_manager._create_result = None
        _run_one(hold)  # 自驱动 checkpoint → 派第二批
        _run_one(hold)  # 第二批建树失败 → halt 出账

        prog = read_progress(proot)
        assert prog["phase"] == "failed"
        rollup = prog["chain_rollup"]
        assert rollup is not None
        assert rollup["trigger"] == "halt"
        assert rollup["runs"] == 1
        assert rollup["turns"] == 10
        assert rollup["resolved"] == 1


class TestChainRollupArchivedRuns:
    """run 文件仅存于 .fenix/runs/archive/ 时链末批 rollup 仍计得真实值。

    retention（每 300 秒 runs_retention_check）把终态 run 移入 archive/——
    code-fix 链横跨数小时，链终局时除末批外的 run 顶层必然早已移档；单路径
    读取曾致链级 rollup 的 turns 恒零（本窗口实测 runs=2/turns=0 与
    runs=1/turns=0 两次全零出账）。夹具取本窗口真实形状：388+49=437 轮 /
    272 轮，修复后同形状输入应计得非零真实值。
    """

    def test_two_run_chain_archived_only(self, seq_run_ids):
        """runs=2 形状：两批各一 run，均仅存归档副本，末批出账逐 run 求和。"""
        proot = _make_project_root(["a", "b"])
        runner = _RollupRunner(
            proot, fix_success=True, archive_runs=True,
            metrics_plan=[
                {"turns": 388, "tool_uses_total": 1200, "text_turns": 190},
                {"turns": 49, "tool_uses_total": 150, "text_turns": 20},
            ])
        rec = _RecLogger()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1, logger=rec)

        res = orch.checkpoint()
        assert res["triggered"] is True
        assert len(runner.run_ids) == 2

        # 顶层 runs/ 无任何 run 文件残留（全链仅存归档副本）
        assert list((proot / ".fenix" / "runs").glob("*.jsonl")) == []

        prog = read_progress(proot)
        rollup = prog["chain_rollup"]
        assert rollup is not None
        assert rollup["trigger"] == "chain_last_batch"
        assert rollup["runs"] == 2
        assert rollup["run_ids"] == runner.run_ids
        assert rollup["turns"] == 437  # 388+49
        assert rollup["tool_uses_total"] == 1350
        assert rollup["text_turns"] == 210
        assert rollup["resolved"] == 2

        # 结构化日志与落盘快照一致（同为真实值非零）
        rollup_logs = [
            msg for lv, _tag, msg in rec.records
            if lv == "info" and "chain rollup" in msg
        ]
        assert any(
            "runs=2" in m and "turns=437" in m
            and "tool_uses=1350" in m and "text_turns=210" in m
            for m in rollup_logs
        ), rollup_logs

    def test_single_run_chain_archived_only(self, seq_run_ids):
        """runs=1 形状：单 run 链末批即终局，归档副本计得 272 轮。"""
        proot = _make_project_root(["a"])
        runner = _RollupRunner(
            proot, fix_success=True, archive_runs=True,
            metrics_plan=[
                {"turns": 272, "tool_uses_total": 650, "text_turns": 141},
            ])
        orch = CodeFixOrchestrator(
            runner, proot, config=_CFG_BS1, logger=_RecLogger())

        res = orch.checkpoint()
        assert res["triggered"] is True
        assert len(runner.run_ids) == 1

        rollup = read_progress(proot)["chain_rollup"]
        assert rollup is not None
        assert rollup["runs"] == 1
        assert rollup["turns"] == 272
        assert rollup["tool_uses_total"] == 650
        assert rollup["text_turns"] == 141
        assert rollup["resolved"] == 1
        assert rollup["avg_turns_per_item"] == 272.0


class TestChainRollupRunFileMissing:
    def test_both_missing_zero_contribution_chain_completes(self, seq_run_ids):
        """顶层与归档两处皆缺：按零贡献，链终局正常完成不抛错。"""
        proot = _make_project_root(["a", "b"])
        runner = _RollupRunner(proot, fix_success=True, write_run_file=False)
        rec = _RecLogger()
        orch = CodeFixOrchestrator(runner, proot, config=_CFG_BS1, logger=rec)

        res = orch.checkpoint()  # 不抛错即链终局未炸
        assert res["triggered"] is True
        assert len(runner.run_ids) == 2

        prog = read_progress(proot)
        assert prog["phase"] == "idle"
        rollup = prog["chain_rollup"]
        assert rollup is not None
        assert rollup["runs"] == 2
        assert rollup["turns"] == 0
        assert rollup["tool_uses_total"] == 0
        assert rollup["text_turns"] == 0
        assert rollup["resolved"] == 2
        # 零贡献照样出账（run 清单非空判据）且出账即清账
        assert prog["chain_run_ids"] == []


class TestRunMetricsReader:
    def test_last_run_metrics_line_wins(self, tmp_path):
        """同 run 多条 run_metrics 行取末条；损坏行/缺失文件安全。"""
        runs = tmp_path / ".fenix" / "runs"
        runs.mkdir(parents=True)
        f = runs / "code-fix-x.jsonl"
        f.write_text(
            "\n".join([
                json.dumps({"type": "assistant", "message": {}}),
                json.dumps({"type": "run_metrics", "turns": 3,
                            "tool_uses_total": 2}),
                json.dumps({"type": "result"}),
                json.dumps({"type": "run_metrics", "turns": 9,
                            "tool_uses_total": 4, "text_turns": 1}),
                "not-json",
            ]) + "\n",
            encoding="utf-8")
        m = _read_run_metrics(tmp_path, "code-fix-x")
        assert m["turns"] == 9
        assert m["tool_uses_total"] == 4
        assert m["text_turns"] == 1
        # 顶层与归档两处皆缺 → 空 dict（零贡献）
        assert _read_run_metrics(tmp_path, "code-fix-missing") == {}

    def test_archive_fallback_when_top_level_missing(self, tmp_path):
        """顶层缺失回退归档副本（retention 移档后仍可读，本窗口根因场景）。"""
        runs = tmp_path / ".fenix" / "runs"
        (runs / "archive").mkdir(parents=True)
        (runs / "archive" / "code-fix-x.jsonl").write_text(
            json.dumps({"type": "run_metrics", "turns": 388,
                        "tool_uses_total": 1200, "text_turns": 190}) + "\n",
            encoding="utf-8")
        m = _read_run_metrics(tmp_path, "code-fix-x")
        assert m["turns"] == 388
        assert m["tool_uses_total"] == 1200
        assert m["text_turns"] == 190

    def test_top_level_wins_over_archive_copy(self, tmp_path):
        """顶层与归档副本并存：取顶层（retention 去重语义，先读先赢）。"""
        runs = tmp_path / ".fenix" / "runs"
        (runs / "archive").mkdir(parents=True)
        (runs / "code-fix-x.jsonl").write_text(
            json.dumps({"type": "run_metrics", "turns": 30,
                        "tool_uses_total": 12, "text_turns": 3}) + "\n",
            encoding="utf-8")
        (runs / "archive" / "code-fix-x.jsonl").write_text(
            json.dumps({"type": "run_metrics", "turns": 9,
                        "tool_uses_total": 4, "text_turns": 1}) + "\n",
            encoding="utf-8")
        m = _read_run_metrics(tmp_path, "code-fix-x")
        assert m["turns"] == 30
        assert m["tool_uses_total"] == 12
        assert m["text_turns"] == 3

    def test_both_paths_missing_zero_dict(self, tmp_path):
        """顶层与归档两处皆缺 → 空 dict（归零语义收窄后的零贡献）。"""
        (tmp_path / ".fenix" / "runs" / "archive").mkdir(parents=True)
        assert _read_run_metrics(tmp_path, "code-fix-none") == {}


class TestProgressChainFields:
    def test_progress_default_carries_chain_fields(self):
        """新链级字段 MUST 进缺省集（白名单合并语义，先例 manual_authorized）。"""
        for key in ("chain_run_ids", "chain_resolved", "chain_ignored",
                    "chain_rollup"):
            assert key in FIX_PROGRESS_DEFAULT

    def test_read_progress_copies_list_default(self, tmp_path):
        """chain_run_ids 缺省读出为新列表（防共享可变缺省，同 chain_skipped）。"""
        (tmp_path / ".fenix" / "code-review").mkdir(parents=True)
        p1 = read_progress(tmp_path)
        p1["chain_run_ids"].append("code-fix-x")
        p2 = read_progress(tmp_path)
        assert p2["chain_run_ids"] == []
