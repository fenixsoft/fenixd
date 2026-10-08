"""add-impl-ocr-parallel-lane：ocr 异步车道与 testing 出口 join 测试（任务 7.1）。

覆盖矩阵（tasks.md 7.1）：
- 车道启动时点：merge-back 成功收口（queue 主路径 + fast-track 同点）启动车道；
- 指纹 stale fail-closed：completed 产物指纹 ≠ 当前指纹 → 停等重跑不放行；
- 超时降级 unavailable：车道硬超时/非零退出折算 unavailable + 非空 reason；
- join 三分支：双绿放行 / gate 档打回 bug-found / 修复轮上限转台账放行；
- advisory 档：findings 只入台账，永不打回；
- 增量游标：cursor 命中走增量，cursor 损坏回退全量；
- tester 停等不重派：defer 落 pending 标量，车道完成回调唤醒重评；
- 产物缺失/车道未运行：幂等触发车道 + 停等，启动失败 fail-open 放行；
- fast-track 出口 join：defer 停留 testing 不推 verified。

车道直测（run_impl_ocr）用 tmp 真实 git 仓库 + 伪造 bin/ocr_review.py 端到端
跑通 detached 检出 → ocr 子进程 → 产物落盘 → 游标推进 → worktree 清理全链路；
join 测试用 FakePM/FakeSM 驱动 Dispatcher mixin 方法。
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.pm_engine.dispatch import Dispatcher

# 伪造 ocr 脚本：按 FAKE_OCR_MODE 环境变量切换行为（ok/fail/hang），
# 把收到的 --from/--to 写进报告 _reviewed 供增量游标断言。
_FAKE_OCR_SCRIPT = textwrap.dedent(
    """
    import json, os, sys, time
    args = sys.argv[1:]
    out = args[args.index("--output") + 1]
    frm = args[args.index("--from") + 1]
    to = args[args.index("--to") + 1]
    # 记录完整 argv（--exclude 接线断言用）
    try:
        with open(out + ".argv.json", "w", encoding="utf-8") as af:
            json.dump(args, af)
    except OSError:
        pass
    # 仓库发现钉住契约：ocr 子进程 MUST 以 GIT_DIR/GIT_WORK_TREE 显式指向
    # detached worktree（漂移到主检出会审错区间），否则直接失败暴露。
    if os.environ.get("GIT_WORK_TREE") != os.getcwd():
        sys.stderr.write("GIT_WORK_TREE not pinned to worktree cwd")
        sys.exit(9)
    if os.environ.get("FAKE_OCR_MODE") == "fail":
        sys.stderr.write("fake provider unreachable")
        sys.exit(3)
    if os.environ.get("FAKE_OCR_MODE") == "hang":
        time.sleep(60)
    # fix-ocr-lane-orphaned-state-misfire 任务 1.3：可调时长的慢审查模式
    # （配合心跳间隔 monkeypatch 至亚秒级，模拟「阻塞超过 2 个心跳间隔」）
    if os.environ.get("FAKE_OCR_MODE") == "sleep":
        time.sleep(float(os.environ.get("FAKE_OCR_SLEEP", "0.3")))
    if os.environ.get("FAKE_OCR_MODE") == "sleep-fail":
        time.sleep(float(os.environ.get("FAKE_OCR_SLEEP", "0.3")))
        sys.stderr.write("fake provider unreachable after slow review")
        sys.exit(3)
    report = {
        "comments": [{
            "path": "src/a.py",
            "content": "FAKE-1 bug",
            "category": "bug",
            "severity": "major",
            "start_line": 1,
            "end_line": 2,
            "existing_code": "x = 1",
            "suggestion_code": "x = 2",
            "thinking": "t",
        }],
        "summary": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
        "llm": {"provider": "fake", "model": "fake-1"},
        "status": "complete",
        "_reviewed": {"from": frm, "to": to},
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f)
    """
)


class FakeLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass


class FakeSM:
    """最小 StateMachine：read_one/update_spec/transition（无转移合法性校验）。"""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.transitions = []

    def read_one(self, spec_name):
        entry = self.entries.get(spec_name)
        return dict(entry) if entry else None

    def update_spec(self, spec_name, patch) -> bool:
        # 返回值对齐生产 StateMachine.update_spec（成功 True）：打回记账写点
        # （item ffcee35add49）消费该 bool 判写入是否生效，替身缺返回值会被
        # 误判为写入失败走 defer 分支
        self.entries.setdefault(spec_name, {}).update(patch)
        return True

    def transition(self, spec_name, to, *, trigger_run_id=None,
                   agent_type=None, channel="auto") -> bool:
        # 签名对齐生产 StateMachine.transition（双保真：不比 prod 更宽容）
        self.transitions.append((spec_name, to))
        self.entries.setdefault(spec_name, {})["status"] = to
        return True


class FakeRunner:
    def __init__(self, project_root: Path, config: dict | None = None):
        self.project_root = project_root
        self.config = config or {}
        self.logger = FakeLogger()

    def _get_agent_model_assignment(self, agent_type):
        # 返回空 → provider 注入跳过（车道用环境缺省 ocr bin）
        return []


class FakePM:
    def __init__(self, project_root: Path, config: dict | None = None):
        self.project_root = project_root
        self.config = config or {}
        self.logger = FakeLogger()
        self.state_machine = FakeSM()
        self.agent_runner = FakeRunner(project_root, self.config)
        self.bug_found_calls = []

    def _on_spec_bug_found(self, spec_name, failure_class="product", run_id=""):
        self.bug_found_calls.append((spec_name, failure_class, run_id))

    def _apply_verified(self, spec_name, judge_result, report):
        # 镜像 PMEngine.__getattr__ 门面转发（design D3 规则 3）：惰性解析到
        # 当前 _verification 组件，测试替换 pm._verification 后仍被命中。
        # 签名与 VerificationPipeline._apply_verified 保真（fake-double-fidelity
        # 守卫核对 fake/prod arity：property 形态 arity=0 ≠ prod=(3,False,False)
        # 会被判「必填不足」违规，转发方法形态行为不变）。
        return self._verification._apply_verified(spec_name, judge_result, report)


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"git {args} failed: {r.stderr}"
    return r.stdout.strip()


def _init_repo_with_fake_ocr(tmp_path: Path) -> Path:
    """建 tmp git 仓库：main + feature 分支，feature 分支 head 提交含伪造
    bin/ocr_review.py（detached 检出后子进程 cwd 内可直接跑）。"""
    repo = tmp_path / "proj"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "fenix/demo")
    bin_dir = repo / "bin"
    bin_dir.mkdir()
    (bin_dir / "ocr_review.py").write_text(_FAKE_OCR_SCRIPT, encoding="utf-8")
    (repo / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "impl")
    return repo


def _run_lane(repo: Path, spec: str = "demo", **config_overrides) -> dict:
    """在 tmp 仓库上直跑 run_impl_ocr（base=main，head=feature 分支 head）。"""
    from core.agent_runner.maintenance_runs import run_impl_ocr

    config = {"verify": {"impl_code_review": True}}
    config["verify"].update(config_overrides)
    runner = FakeRunner(repo, config)
    base = _git(repo, "merge-base", "main", "fenix/demo")
    head = _git(repo, "rev-parse", "fenix/demo")
    return run_impl_ocr(runner, spec, "fenix/demo", base, head)


def _artifact_path(repo: Path, spec: str = "demo") -> Path:
    return repo / ".fenix" / "verify-progress" / spec / "code-review.json"


def _write_completed_artifact(
    repo: Path,
    fingerprint: dict,
    findings: list | None = None,
    spec: str = "demo",
    status: str = "completed",
    reason: str = "",
) -> None:
    """直写主树车道产物（join 读侧以文件为准）。"""
    path = _artifact_path(repo, spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "spec": spec,
                "run_id": "impl-ocr-demo-1",
                "kind": "impl-ocr-lane",
                "fingerprint": fingerprint,
                "findings": findings or [],
                "reason": reason,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _make_dispatcher(repo: Path, config: dict | None = None):
    pm = FakePM(repo, config)
    dispatcher = Dispatcher(pm)
    return dispatcher, pm


class TestRunImplOcrLane:
    """run_impl_ocr 车道直测（任务 3.1-3.4：端到端 tmp 真仓库）。"""

    def test_success_completed_artifact_cursor_and_cleanup(self, tmp_path):
        repo = _init_repo_with_fake_ocr(tmp_path)
        artifact = _run_lane(repo)
        head = _git(repo, "rev-parse", "fenix/demo")

        assert artifact["status"] == "completed"
        assert artifact["reason"] == ""
        # 指纹 = 触发时捕获的 (branch, merge_base, head_commit)
        assert artifact["fingerprint"]["branch"] == "fenix/demo"
        assert artifact["fingerprint"]["head_commit"] == head
        assert artifact["fingerprint"]["merge_base"] == _git(
            repo, "merge-base", "main", "fenix/demo"
        )
        # findings 规范化：ocr comments → 统一词形
        assert len(artifact["findings"]) == 1
        f = artifact["findings"][0]
        assert f["path"] == "src/a.py"
        assert f["category"] == "bug"
        assert f["start_line"] == 1

        # 产物落盘（join 读侧以文件为准）
        on_disk = json.loads(_artifact_path(repo).read_text(encoding="utf-8"))
        assert on_disk["status"] == "completed"
        # 原始报告副本存在
        raw = repo / ".fenix" / "verify-progress" / "demo" / "code-review-raw.json"
        assert raw.is_file()
        # 游标推进到 head
        cursor_path = repo / ".fenix" / "verify-progress" / "demo" / "ocr-cursor.json"
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        assert cursor["last_reviewed_commit"] == head
        # run 时间线 jsonl（start + result 终态，agent_type=impl-ocr）
        run_files = list((repo / ".fenix" / "runs").glob("impl-ocr-*.jsonl"))
        assert len(run_files) == 1
        lines = [
            json.loads(line)
            for line in run_files[0].read_text(encoding="utf-8").splitlines()
        ]
        assert [ln["type"] for ln in lines] == ["start", "result"]
        assert lines[-1]["agent_type"] == "impl-ocr"
        assert lines[-1]["status"] == "completed"
        # token 记账：impl-ocr 类目（input 不叠加 cache_read）
        tokens_data = json.loads(
            (repo / ".fenix" / "cost" / "code_review_tokens.json")
            .read_text(encoding="utf-8")
        )
        entry = [
            e for e in tokens_data.get("runs", [])
            if e.get("agent_type") == "impl-ocr"
        ][-1]
        assert entry["input_tokens"] == 100
        assert entry["output_tokens"] == 10
        # detached worktree 已清理
        serving = repo / ".fenix" / "verify-serving"
        assert not [p for p in serving.glob("ocr-*")], list(serving.iterdir())

    def test_exclude_file_wired_to_ocr_cmd(self, tmp_path):
        """`.fenix/ocr-exclude.txt` 含有效行 → 拼接为 ocr --exclude（09-23 误报治理）。

        生成/快照类文件（playwright 页面捕获 yml 等）不入审：注释行与空行
        跳过，其余逐行拼成逗号分隔串。
        """
        repo = _init_repo_with_fake_ocr(tmp_path)
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "ocr-exclude.txt").write_text(
            "# 生成/快照类文件不入审\n"
            "core/dashboard/static/*.yml\n"
            "\n"
            "**/.playwright-cli/**\n",
            encoding="utf-8",
        )
        _run_lane(repo)
        raw_argv = _artifact_path(repo).with_name("code-review-raw.json.argv.json")
        argv = json.loads(raw_argv.read_text(encoding="utf-8"))
        assert "--exclude" in argv
        assert argv[argv.index("--exclude") + 1] == (
            "core/dashboard/static/*.yml,**/.playwright-cli/**"
        )

    def test_ignore_marker_background_always_injected(self, tmp_path):
        """忽略标记约定常驻经 ocr --background 注入（09-23，不依赖排除文件）。"""
        repo = _init_repo_with_fake_ocr(tmp_path)
        _run_lane(repo)
        raw_argv = _artifact_path(repo).with_name("code-review-raw.json.argv.json")
        argv = json.loads(raw_argv.read_text(encoding="utf-8"))
        assert "--background" in argv
        assert "[fenix-ignore:" in argv[argv.index("--background") + 1]

    def test_exclude_file_comment_only_zero_injection(self, tmp_path):
        """排除文件缺失/只有注释 → 命令零注入（无 --exclude，逐字节同现状）。"""
        repo = _init_repo_with_fake_ocr(tmp_path)
        (repo / ".fenix").mkdir(exist_ok=True)
        (repo / ".fenix" / "ocr-exclude.txt").write_text(
            "# 只有注释\n", encoding="utf-8"
        )
        _run_lane(repo)
        raw_argv = _artifact_path(repo).with_name("code-review-raw.json.argv.json")
        argv = json.loads(raw_argv.read_text(encoding="utf-8"))
        assert "--exclude" not in argv

    def test_incremental_cursor_then_corrupt_fallback_full(self, tmp_path):
        repo = _init_repo_with_fake_ocr(tmp_path)
        base = _git(repo, "merge-base", "main", "fenix/demo")
        head1 = _git(repo, "rev-parse", "fenix/demo")

        first = _run_lane(repo)
        assert first["review_range"]["incremental"] is False
        assert first["review_range"]["from"] == base

        # 分支前进一个提交 → 游标命中，第二跑走增量（from = head1）
        (repo / "src" / "b.py").write_text("y = 1\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "impl2")
        head2 = _git(repo, "rev-parse", "fenix/demo")
        second = _run_lane(repo)
        assert second["review_range"]["incremental"] is True
        assert second["review_range"]["from"] == head1
        assert second["review_range"]["to"] == head2

        # 游标损坏（非分支祖先的不存在提交）→ 回退全量
        cursor_path = repo / ".fenix" / "verify-progress" / "demo" / "ocr-cursor.json"
        cursor_path.write_text(
            json.dumps({"last_reviewed_commit": "0" * 40}), encoding="utf-8"
        )
        third = _run_lane(repo)
        assert third["review_range"]["incremental"] is False
        assert third["review_range"]["from"] == base

    def test_nonzero_exit_unavailable(self, tmp_path, monkeypatch):
        repo = _init_repo_with_fake_ocr(tmp_path)
        monkeypatch.setenv("FAKE_OCR_MODE", "fail")
        artifact = _run_lane(repo)
        assert artifact["status"] == "unavailable"
        assert "非零退出" in artifact["reason"]
        assert "rc=3" in artifact["reason"]
        # 失败不推进游标
        cursor_path = repo / ".fenix" / "verify-progress" / "demo" / "ocr-cursor.json"
        assert not cursor_path.exists()

    def test_lane_hard_timeout_unavailable(self, tmp_path, monkeypatch):
        repo = _init_repo_with_fake_ocr(tmp_path)
        monkeypatch.setenv("FAKE_OCR_MODE", "hang")
        artifact = _run_lane(repo, impl_code_review_lane_timeout_sec=1)
        assert artifact["status"] == "unavailable"
        assert "硬超时" in artifact["reason"]

    def test_checkout_failure_unavailable(self, tmp_path):
        # 非 git 仓库：detached 检出失败 → unavailable 非空 reason（任务 3.3）
        plain = tmp_path / "plain"
        plain.mkdir()
        from core.agent_runner.maintenance_runs import run_impl_ocr

        runner = FakeRunner(plain, {"verify": {"impl_code_review": True}})
        artifact = run_impl_ocr(
            runner, "demo", "fenix/demo", "0" * 40, "1" * 40
        )
        assert artifact["status"] == "unavailable"
        assert "检出失败" in artifact["reason"]

    def test_carry_forward_skips_adjudicated_and_dedupes(self, tmp_path):
        repo = _init_repo_with_fake_ocr(tmp_path)
        # 预置上一轮产物：一条未裁决（无 disposition）、一条已裁决 fixed
        prev = [
            {
                "path": "src/a.py",
                "category": "bug",
                "content": "FAKE-1 bug",
                "start_line": 1,
                "severity": "major",
            },
            {
                "path": "src/old.py",
                "category": "style",
                "content": "OLD-1 style",
                "start_line": 3,
                "severity": "info",
                "disposition": "fixed",
                "reason": "已修复",
            },
        ]
        path = _artifact_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"status": "completed", "findings": prev}),
            encoding="utf-8",
        )
        artifact = _run_lane(repo)
        # 新报告同一 finding（FAKE-1）不重复携带；已裁决 fixed 的 OLD-1 不携带
        assert len(artifact["findings"]) == 1
        assert artifact["findings"][0]["content"] == "FAKE-1 bug"


class TestOcrJoinGate:
    """join 机械裁决单点 _ocr_join_gate（任务 4.2-4.6 决策树）。"""

    FP = {"branch": "fenix/demo", "merge_base": "aa", "head_commit": "bb"}

    def _dispatcher_with_fingerprint(self, tmp_path, config=None):
        dispatcher, pm = _make_dispatcher(tmp_path, config)
        pm.state_machine.update_spec(
            "demo",
            {
                "status": "testing",
                "branch": "fenix/demo",
                "_ocr_base_commit": "aa",
                "tester_run": "test-demo-1",
            },
        )
        # head 分量钉住（不经真 git）
        dispatcher._git_rev_parse = lambda ref: "bb" if ref == "fenix/demo" else None
        return dispatcher, pm

    def test_disabled_passes_without_side_effects(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": False}}
        )
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"
        entry = pm.state_machine.read_one("demo")
        # 总开关关闭出口与其余 pass 出口同口径清 pending（写 cleared 标量，
        # code-review item 653b78f24c6c），故断言无「未清」停等标记而非键不存在
        assert not entry.get("_ocr_join_wait")

    def test_missing_artifact_triggers_lane_and_defers(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        started = []
        dispatcher._start_impl_ocr_lane = (
            lambda spec, fp: started.append((spec, fp)) or "started"
        )
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "defer"
        # 幂等触发以当前指纹启动 + pending 停等标量落盘
        assert started == [("demo", self.FP)]
        entry = pm.state_machine.read_one("demo")
        assert entry["_ocr_join_wait"] == 1
        assert entry["_ocr_join_agent"] == "planner-judge"

    def test_start_failure_fail_open(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        # 车道未启动（开关关/分支不可得返回 None）且不在飞 → MUST NOT 无限停等
        dispatcher._start_impl_ocr_lane = lambda spec, fp: None
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"
        entry = pm.state_machine.read_one("demo")
        assert not entry.get("_ocr_join_wait")

    def test_stale_fingerprint_fail_closed_reruns(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        started = []
        dispatcher._start_impl_ocr_lane = (
            lambda spec, fp: started.append((spec, fp)) or "started"
        )
        # 产物 completed 但指纹是旧的（head_commit 不等）→ 不采信不放行
        _write_completed_artifact(
            tmp_path,
            {"branch": "fenix/demo", "merge_base": "aa", "head_commit": "OLD"},
            findings=[],
        )
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "defer"
        assert started == [("demo", self.FP)]
        assert pm.state_machine.read_one("demo")["_ocr_join_wait"] == 1

    def test_double_green_passes(self, tmp_path):
        dispatcher, _ = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        _write_completed_artifact(tmp_path, dict(self.FP), findings=[])
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"

    def test_all_rejected_findings_pass(self, tmp_path):
        dispatcher, _ = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        _write_completed_artifact(
            tmp_path,
            dict(self.FP),
            findings=[
                {"path": "src/a.py", "category": "bug", "content": "x",
                 "disposition": "rejected", "reason": "误报"},
            ],
        )
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"

    def test_gate_mode_rejects_to_bug_found(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_mode": "gate"}},
        )
        findings = [
            {"path": "src/a.py", "category": "bug", "content": "FAKE-1",
             "start_line": 1, "severity": "major"},
        ]
        _write_completed_artifact(tmp_path, dict(self.FP), findings=findings)
        decision = dispatcher._ocr_join_gate("demo", "planner-judge")
        assert decision == "reject"
        # testing → bug-found 打回
        assert ("demo", "bug-found") in pm.state_machine.transitions
        entry = pm.state_machine.read_one("demo")
        # 轮次计数递增持久化 + pending 清账 + error 注明 ocr findings
        assert entry["_ocr_fix_rounds"] == 1
        assert not entry.get("_ocr_join_wait")
        assert "ocr" in (entry.get("error") or "")
        # 修复轮 directive 已写（prompt_builder 读）
        directive = (
            tmp_path / ".fenix" / "verify-progress" / "demo"
            / "ocr_findings_directive.json"
        )
        data = json.loads(directive.read_text(encoding="utf-8"))
        assert data["round"] == 1
        assert data["max_rounds"] == 1
        assert data["findings"][0]["content"] == "FAKE-1"
        # 走验证失败既有打回通道（原地重派）
        assert pm.bug_found_calls == [("demo", "product", "impl-ocr-demo-1")]

    def test_round_limit_transfers_to_ledger_and_passes(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_mode": "gate"}},
        )
        pm.state_machine.update_spec("demo", {"_ocr_fix_rounds": 1})
        findings = [
            {"path": "src/a.py", "category": "bug", "content": "FAKE-1",
             "start_line": 1, "severity": "major"},
        ]
        _write_completed_artifact(tmp_path, dict(self.FP), findings=findings)
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"
        # findings 已转台账（status=open、spec 归属本 spec）
        items_path = tmp_path / ".fenix" / "code-review" / "items.jsonl"
        items = [
            json.loads(line)
            for line in items_path.read_text(encoding="utf-8").splitlines()
        ]
        match = [i for i in items if i.get("file") == "src/a.py"]
        assert match, items
        assert match[0]["status"] == "open"
        assert match[0]["spec_name"] == "demo"

    def test_advisory_mode_never_rejects(self, tmp_path):
        dispatcher, pm = self._dispatcher_with_fingerprint(
            tmp_path,
            {"verify": {"impl_code_review": True, "impl_code_review_mode": "advisory"}},
        )
        findings = [
            {"path": "src/a.py", "category": "bug", "content": "FAKE-1",
             "start_line": 1, "severity": "major"},
        ]
        _write_completed_artifact(tmp_path, dict(self.FP), findings=findings)
        # rounds=0（首轮）advisory 也不打回
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"
        assert pm.state_machine.transitions == []
        assert pm.bug_found_calls == []
        items_path = tmp_path / ".fenix" / "code-review" / "items.jsonl"
        assert items_path.is_file()

    def test_unavailable_passes_in_both_modes(self, tmp_path):
        for mode in ("gate", "advisory"):
            repo = tmp_path / mode
            repo.mkdir()
            dispatcher, _ = self._dispatcher_with_fingerprint(
                repo,
                {"verify": {"impl_code_review": True, "impl_code_review_mode": mode}},
            )
            _write_completed_artifact(
                repo, dict(self.FP), status="unavailable",
                reason="provider unreachable",
            )
            assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"

    def test_no_branch_passes(self, tmp_path):
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        pm.state_machine.update_spec("demo", {"status": "testing"})
        dispatcher._git_rev_parse = lambda ref: None
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"

    # ── ocr 审查 finding#5：directive 消费即失效（放行/启动双防线清理）──

    @staticmethod
    def _write_stale_directive(proot: Path) -> Path:
        d = proot / ".fenix" / "verify-progress" / "demo"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "ocr_findings_directive.json"
        p.write_text('{"findings": [{"path": "src/a.py"}]}', encoding="utf-8")
        return p

    def test_gate_pass_clears_stale_directive(self, tmp_path):
        """join 放行出口（双绿）清除残留 directive——后续无关实现轮零误注入。"""
        dispatcher, _ = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        _write_completed_artifact(tmp_path, dict(self.FP), findings=[])
        directive = self._write_stale_directive(tmp_path)
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"
        assert not directive.exists()

    def test_gate_pass_directive_absent_is_silent(self, tmp_path):
        """放行出口对无 directive 场景幂等（缺失静默、不报错）。"""
        dispatcher, _ = self._dispatcher_with_fingerprint(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        _write_completed_artifact(tmp_path, dict(self.FP), findings=[])
        assert dispatcher._ocr_join_gate("demo", "planner-judge") == "pass"

    def test_lane_start_clears_stale_directive(self, tmp_path):
        """新车道启动即旧修复义务作废（第二道防线：pass 出口未覆盖的
        冻结/人工接管打回轮后再实现形态）。"""
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        directive = self._write_stale_directive(tmp_path)
        started = dispatcher._start_impl_ocr_lane("demo", dict(self.FP))
        assert started == "started"
        assert not directive.exists()
        # 车道线程异步：等在飞标记释放（伪造 runner 立即返回）
        import time as _time

        for _ in range(100):
            if not dispatcher._ocr_lane_inflight.get("demo"):
                break
            _time.sleep(0.05)


class TestJoinWakeAndResume:
    """停等-唤醒闭环（任务 4.1/4.2：车道完成回调唤醒 join 重评）。"""

    def _pending_dispatcher(self, tmp_path, origin="planner-judge"):
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        pm.state_machine.update_spec(
            "demo",
            {
                "status": "testing",
                "branch": "fenix/demo",
                "tester_run": "test-demo-1",
                "_ocr_join_wait": 1,
                "_ocr_join_agent": origin,
            },
        )
        return dispatcher, pm

    def test_lane_finished_resumes_verified(self, tmp_path):
        dispatcher, pm = self._pending_dispatcher(tmp_path)
        resumed = []
        dispatcher._ocr_join_gate = lambda spec, origin: "pass"
        dispatcher._resume_verified_after_ocr = (
            lambda spec, origin: resumed.append((spec, origin))
        )
        dispatcher._on_impl_ocr_lane_finished("demo", "impl-ocr-demo-1")
        assert resumed == [("demo", "planner-judge")]

    def test_lane_finished_gate_defer_keeps_waiting(self, tmp_path):
        dispatcher, pm = self._pending_dispatcher(tmp_path)
        resumed = []
        dispatcher._ocr_join_gate = lambda spec, origin: "defer"
        dispatcher._resume_verified_after_ocr = (
            lambda spec, origin: resumed.append((spec, origin))
        )
        dispatcher._on_impl_ocr_lane_finished("demo", "impl-ocr-demo-1")
        # defer（stale 重触发等）：不 resume，继续停等新车道
        assert resumed == []

    def test_lane_finished_without_pending_is_noop(self, tmp_path):
        dispatcher, pm = _make_dispatcher(
            tmp_path, {"verify": {"impl_code_review": True}}
        )
        pm.state_machine.update_spec(
            "demo", {"status": "testing", "branch": "fenix/demo"}
        )
        gate_calls = []
        dispatcher._ocr_join_gate = (
            lambda spec, origin: gate_calls.append((spec, origin)) or "pass"
        )
        dispatcher._on_impl_ocr_lane_finished("demo", "impl-ocr-demo-1")
        # tester 未完成（无 pending 停等义务）→ 幂等空转
        assert gate_calls == []

    def test_lane_finished_after_status_migrated_is_noop(self, tmp_path):
        dispatcher, pm = self._pending_dispatcher(tmp_path)
        pm.state_machine.update_spec("demo", {"status": "implemented"})
        gate_calls = []
        dispatcher._ocr_join_gate = (
            lambda spec, origin: gate_calls.append((spec, origin)) or "pass"
        )
        dispatcher._on_impl_ocr_lane_finished("demo", "impl-ocr-demo-1")
        assert gate_calls == []

    def test_resume_planner_judge_origin_reenters_apply_verified(self, tmp_path,
                                                                  monkeypatch):
        dispatcher, pm = self._pending_dispatcher(tmp_path, origin="planner-judge")
        applied = []
        pm._verification = SimpleNamespace(
            _apply_verified=lambda spec, result, report: applied.append(
                (spec, result.run_id, report)
            )
        )
        monkeypatch.setattr(
            "core.verify_report._load_report_json",
            lambda project_root, spec: {"passed": 1},
        )
        dispatcher._resume_verified_after_ocr("demo", "planner-judge")
        assert applied == [("demo", "test-demo-1", {"passed": 1})]

    def test_resume_fast_track_origin_reenters_fast_track(self, tmp_path):
        dispatcher, pm = self._pending_dispatcher(tmp_path, origin="fast-track")
        advanced = []
        dispatcher._fast_track_advance_to_verified = (
            lambda spec, result: advanced.append((spec, result.run_id))
        )
        dispatcher._resume_verified_after_ocr("demo", "fast-track")
        assert advanced == [("demo", "test-demo-1")]


class TestLaneStartTiming:
    """车道启动时点（任务 4.1：merge-back 成功 + tester 派发同点）。"""

    def test_finalize_merge_success_starts_lane(self):
        from unittest.mock import MagicMock

        pm = MagicMock()
        pm.config = {"verify": {"impl_code_review": True}}
        dispatcher = Dispatcher(pm)
        fp = {"branch": "fenix/demo", "merge_base": "aa", "head_commit": "bb"}
        dispatcher._ocr_current_fingerprint = lambda spec: fp
        started = []
        dispatcher._start_impl_ocr_lane = (
            lambda spec, f: started.append((spec, f)) or "started"
        )
        dispatcher._finalize_merge_success("demo", "impl-demo-1", "fenix/demo", {}, [])
        assert started == [("demo", fp)]

    def test_finalize_merge_success_lane_error_nonblocking(self):
        from unittest.mock import MagicMock

        pm = MagicMock()
        pm.config = {"verify": {"impl_code_review": True}}
        dispatcher = Dispatcher(pm)
        dispatcher._ocr_current_fingerprint = lambda spec: {"branch": "b"}
        dispatcher._start_impl_ocr_lane = lambda spec, f: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        # 车道启动异常不阻塞 merge 收尾主流程
        dispatcher._finalize_merge_success("demo", "impl-demo-1", "fenix/demo", {}, [])

    def test_fast_track_merge_success_starts_lane(self):
        from unittest.mock import MagicMock

        pm = MagicMock()
        pm.config = {"verify": {"impl_code_review": True}}
        dispatcher = Dispatcher(pm)
        pm.agent_runner.worktree_manager.merge_back_from_branch.return_value = (
            True,
            None,
        )
        result = SimpleNamespace(run_id="ft-demo-1", branch="fenix/demo")
        started = []
        fp = {"branch": "fenix/demo", "merge_base": "aa", "head_commit": "bb"}
        dispatcher._ocr_current_fingerprint = lambda spec: fp
        dispatcher._start_impl_ocr_lane = (
            lambda spec, f: started.append((spec, f)) or "started"
        )
        ok = dispatcher._reconcile_and_merge("demo", result)
        assert ok is True
        # 同点启动：merge-back 成功返回 True 前车道已按当前指纹启动
        assert started == [("demo", fp)]

    def test_fast_track_exit_join_defer_stays_testing(self):
        from unittest.mock import MagicMock

        pm = MagicMock()
        sm = FakeSM({"demo": {"status": "implemented", "branch": "fenix/demo"}})
        pm.state_machine = sm
        dispatcher = Dispatcher(pm)
        dispatcher._ocr_join_gate = lambda spec, origin: "defer"
        dispatcher._fast_track_advance_to_verified(
            "demo", SimpleNamespace(run_id="ft-demo-1")
        )
        # testing 转移发生但 verified 不推进（停等车道）
        assert ("demo", "testing") in sm.transitions
        assert ("demo", "verified") not in sm.transitions

    def test_fast_track_exit_join_pass_advances_verified(self):
        from unittest.mock import MagicMock

        pm = MagicMock()
        sm = FakeSM({"demo": {"status": "implemented", "branch": "fenix/demo"}})
        pm.state_machine = sm
        verified_calls = []
        pm._on_spec_verified = lambda spec: verified_calls.append(spec)
        dispatcher = Dispatcher(pm)
        dispatcher._ocr_join_gate = lambda spec, origin: "pass"
        dispatcher._fast_track_advance_to_verified(
            "demo", SimpleNamespace(run_id="ft-demo-1")
        )
        assert ("demo", "verified") in sm.transitions
        assert verified_calls == ["demo"]


class TestPipelineContextGateWiring:
    """context 承载 join 门禁（D10 惯例）：桩 pm 缺 Dispatcher 恒放行。"""

    def test_context_without_dispatcher_defaults_pass(self, tmp_path):
        from core.pm_engine.verification.context import PipelineContext

        pm = SimpleNamespace(
            logger=FakeLogger(),
            project_root=tmp_path,
            state_machine=FakeSM(),
            _get_config=lambda key, default=None: default,
            _send_human_escalation_alert=lambda **kw: None,
            _enqueue=lambda spec, agent: None,
            _is_fix_spec=lambda spec: False,
            _on_spec_verified=lambda spec: None,
            _on_spec_bug_found=lambda spec, **kw: None,
            _read_implementer_result=lambda spec: None,
            _exempt_infra_run_budget=lambda spec, reason, refund_key="": False,
        )
        ctx = PipelineContext.from_pm(pm)
        assert ctx.ocr_join_gate("demo", "planner-judge") == "pass"

    def test_context_with_dispatcher_delegates(self, tmp_path):
        from core.pm_engine.verification.context import PipelineContext

        calls = []

        class _Dispatcher:
            def _ocr_join_gate(self, spec, origin):
                calls.append((spec, origin))
                return "defer"

        pm = SimpleNamespace(
            logger=FakeLogger(),
            project_root=tmp_path,
            state_machine=FakeSM(),
            _get_config=lambda key, default=None: default,
            _send_human_escalation_alert=lambda **kw: None,
            _enqueue=lambda spec, agent: None,
            _is_fix_spec=lambda spec: False,
            _on_spec_verified=lambda spec: None,
            _on_spec_bug_found=lambda spec, **kw: None,
            _read_implementer_result=lambda spec: None,
            _exempt_infra_run_budget=lambda spec, reason, refund_key="": False,
            _dispatcher=_Dispatcher(),
        )
        ctx = PipelineContext.from_pm(pm)
        assert ctx.ocr_join_gate("demo", "planner-judge") == "defer"
        assert calls == [("demo", "planner-judge")]


# ── fix-ocr-lane-orphaned-state-misfire：车道运行中心跳与探针/分类器相容 ────


class TestOcrLaneHeartbeat:
    """车道运行中心跳行为（任务 1.3）。

    全部用例经 monkeypatch 把间隔常量缩至亚秒级（0.05s）后运行，MUST NOT
    真实等待 ≥45s——间隔常量为模块级可 patch 形态
    （``IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS``，``_start_impl_ocr_heartbeat``
    在调用时读取全局而非缺省参数绑定），套件时长不被心跳间隔放大。
    """

    HEARTBEAT_INTERVAL = 0.05

    @pytest.fixture(autouse=True)
    def _fast_heartbeat(self, monkeypatch):
        from core.agent_runner import maintenance_runs

        monkeypatch.setattr(
            maintenance_runs,
            "IMPL_OCR_HEARTBEAT_INTERVAL_SECONDS",
            self.HEARTBEAT_INTERVAL,
        )

    def _only_run_file(self, repo: Path) -> Path:
        run_files = list((repo / ".fenix" / "runs").glob("impl-ocr-*.jsonl"))
        assert len(run_files) == 1, run_files
        return run_files[0]

    def _read_lines(self, path: Path) -> list:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_long_review_appends_progress_and_refreshes_mtime(
        self, tmp_path, monkeypatch
    ):
        """a) 长审查（子进程阻塞 > 2 个心跳间隔）期间转录持续追加 progress
        且 mtime 持续刷新——orphaned_state 条件①（mtime 宽限窗）因此为假。"""
        repo = _init_repo_with_fake_ocr(tmp_path)
        monkeypatch.setenv("FAKE_OCR_MODE", "sleep")
        monkeypatch.setenv("FAKE_OCR_SLEEP", "0.35")  # > 2 × 0.05s 间隔
        artifact = _run_lane(repo)
        assert artifact["status"] == "completed"

        lines = self._read_lines(self._only_run_file(repo))
        types = [ln["type"] for ln in lines]
        progress = [ln for ln in lines if ln["type"] == "progress"]
        # 运行期持续追加：start 首行、progress ≥ 2 条（运行 0.35s / 间隔 0.05s）
        assert types[0] == "start"
        assert len(progress) >= 2, types
        for ln in progress:
            assert ln["agent_type"] == "impl-ocr"
            assert ln["spec"] == "demo"
            assert set(ln["review_range"]) == {"from", "to"}
            assert ln["review_range"]["to"] == artifact["fingerprint"]["head_commit"]
            assert ln["elapsed_seconds"] >= self.HEARTBEAT_INTERVAL
        # 已用时单调递增＝事件按序追加（每次追加即一次 mtime 刷新的转录证据）
        elapsed = [ln["elapsed_seconds"] for ln in progress]
        assert elapsed == sorted(elapsed)
        assert elapsed[-1] > elapsed[0]

    def test_heartbeat_stops_and_terminal_is_last_line(self, tmp_path, monkeypatch):
        """b) 子进程收尾后停跳：不再追加 progress，终态事件是文件末行。"""
        repo = _init_repo_with_fake_ocr(tmp_path)
        monkeypatch.setenv("FAKE_OCR_MODE", "sleep")
        monkeypatch.setenv("FAKE_OCR_SLEEP", "0.2")
        artifact = _run_lane(repo)
        assert artifact["status"] == "completed"

        run_file = self._only_run_file(repo)
        types = [ln["type"] for ln in self._read_lines(run_file)]
        assert types[0] == "start"
        assert "progress" in types
        assert types[-1] == "result"
        assert self._read_lines(run_file)[-1]["status"] == "completed"
        # 停跳：等 > 2 个心跳间隔后行集不变（无迟到心跳、无终态后追加）
        frozen = self._read_lines(run_file)
        time.sleep(2 * self.HEARTBEAT_INTERVAL + 0.05)
        assert self._read_lines(run_file) == frozen

    def test_error_and_timeout_paths_stop_heartbeat_terminal_last(
        self, tmp_path, monkeypatch
    ):
        """c) 异常收尾路径（非零退出/车道硬超时）同样停跳且终态末行。"""
        # 慢审查后非零退出：心跳只在子进程运行期，失败收尾停跳
        repo = _init_repo_with_fake_ocr(tmp_path)
        monkeypatch.setenv("FAKE_OCR_MODE", "sleep-fail")
        monkeypatch.setenv("FAKE_OCR_SLEEP", "0.2")
        artifact = _run_lane(repo)
        assert artifact["status"] == "unavailable"
        assert "非零退出" in artifact["reason"]
        run_file = self._only_run_file(repo)
        lines = self._read_lines(run_file)
        types = [ln["type"] for ln in lines]
        assert "progress" in types
        assert types[-1] == "result"
        assert lines[-1]["status"] == "unavailable"

        # 车道硬超时：hang 子进程被 TimeoutExpired 打断，停跳后终态末行
        timeout_root = tmp_path / "timeout"
        timeout_root.mkdir()
        repo2 = _init_repo_with_fake_ocr(timeout_root)
        monkeypatch.setenv("FAKE_OCR_MODE", "hang")
        artifact2 = _run_lane(repo2, impl_code_review_lane_timeout_sec=1)
        assert artifact2["status"] == "unavailable"
        assert "硬超时" in artifact2["reason"]
        run_file2 = self._only_run_file(repo2)
        lines2 = self._read_lines(run_file2)
        types2 = [ln["type"] for ln in lines2]
        assert types2[0] == "start"
        # 运行期（1s ≫ 0.05s 间隔）确有心跳，被打断后停跳
        assert "progress" in types2
        assert types2[-1] == "result"
        assert lines2[-1]["status"] == "unavailable"
        time.sleep(2 * self.HEARTBEAT_INTERVAL + 0.05)
        assert self._read_lines(run_file2) == lines2


class TestOcrLaneProbeCompat:
    """无驱动探针相容回归（任务 2.1）。

    直接调 ``core.admin_monitor.spec_is_undriven``（实现零改动、不打桩）：
    心跳方案的效果链恰是「车道 run 转录 mtime 新鲜 → 条件①
    ``_has_recent_spec_run`` 为真 → AND 链为假 → 返回 False」。
    """

    def _write_heartbeat_run(self, repo: Path, spec: str) -> Path:
        runs_dir = repo / ".fenix" / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"impl-ocr-{spec}-1790086106.jsonl"
        entries = (
            {
                "type": "start",
                "spec": spec,
                "agent_type": "impl-ocr",
                "timestamp": "2026-09-22T12:00:00+00:00",
            },
            {
                "type": "progress",
                "spec": spec,
                "agent_type": "impl-ocr",
                "timestamp": "2026-09-22T12:01:00+00:00",
                "review_range": {"from": "a" * 40, "to": "b" * 40},
                "elapsed_seconds": 60.0,
            },
        )
        run_file.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8",
        )
        return run_file

    def test_fresh_heartbeat_mtime_means_driven(self, tmp_path):
        """a) 车道在跑（心跳写入后 mtime 新鲜）→ False，不误报孤儿。"""
        from core.admin_monitor import spec_is_undriven

        spec = "probe-lane-live-1790086106"
        self._write_heartbeat_run(tmp_path, spec)
        entry = {"name": spec, "status": "testing"}
        assert spec_is_undriven(tmp_path, spec, entry) is False

    def test_stale_mtime_after_restart_still_reports_orphan(self, tmp_path):
        """b) daemon 重启停跳后 mtime 停滞超宽限窗且无其他驱动 → True，
        自愈链（orphaned_state → admin 处置 → 重验入队）不被遮蔽。"""
        from core.admin_monitor import ORPHANED_RUN_GRACE_SECONDS, spec_is_undriven

        spec = "probe-lane-dead-1790086106"
        run_file = self._write_heartbeat_run(tmp_path, spec)
        # 心跳线程随 daemon 进程消失：mtime 回拨到宽限窗外
        stale = time.time() - (ORPHANED_RUN_GRACE_SECONDS + 300)
        os.utime(run_file, (stale, stale))
        entry = {"name": spec, "status": "testing"}
        assert spec_is_undriven(tmp_path, spec, entry) is True


class TestOcrLaneTerminalClassifierCompat:
    """终态分类回归钉住（任务 2.2）。

    ``progress`` 不在 ``_RUN_TERMINAL_STATUS_MAP`` / ``_run_terminal_status``
    的终态判定中，两侧实现零改动（缺省 ``running`` 兜底即契约）——防未来
    终态映射表扩张时把心跳误判终态。
    """

    _PROGRESS = {
        "type": "progress",
        "spec": "demo",
        "agent_type": "impl-ocr",
        "timestamp": "2026-09-22T12:01:00+00:00",
        "review_range": {"from": "a" * 40, "to": "b" * 40},
        "elapsed_seconds": 60.0,
    }

    def test_classify_run_progress_last_line_is_running(self):
        from core.dashboard.data.runs import classify_run

        lines = [
            {"type": "start", "spec": "demo", "agent_type": "impl-ocr",
             "timestamp": "2026-09-22T12:00:00+00:00"},
            dict(self._PROGRESS),
        ]
        assert classify_run(lines) == "running"

    def test_admin_monitor_run_terminal_status_progress_is_running(self, tmp_path):
        from core.admin_monitor import AdminMonitor

        run_file = tmp_path / "impl-ocr-demo-1790086106.jsonl"
        run_file.write_text(
            json.dumps({"type": "start", "spec": "demo",
                        "agent_type": "impl-ocr"}) + "\n"
            + json.dumps(self._PROGRESS) + "\n",
            encoding="utf-8",
        )
        assert AdminMonitor._run_terminal_status(run_file) == "running"
