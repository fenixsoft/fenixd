"""tests/test_dsh_acceptance.py — dsh-primary-acceptance-switch 2.2。

bin/dsh_acceptance.py（一键验收脚本）的行为测试：
- 三模式：fixture（夹具结构/唯一前缀/清理回执）、smoke（未知车道拒绝、
  车道步骤编排；e2e 三车道全链与 SPEC-3 冒烟同源装置，缺 dsh/node 即
  skip——环境依赖测试不假失败）、accept（自检失败列缺失项+修复指引；
  dry-run 零真实调用；计划形状）。
- 证据判定纯函数：evaluate_agent_lane / evaluate_judge_lane /
  evaluate_evidence / compare_baseline——绿夹具零失败，逐类坏证据逐项
  fail-loud（构造证据直测，不依赖装置）。
- 夹具清理无残留：build → cleanup → residue_check 闭环（Path.home 隔离）。
- fail-loud：任一判定失败 → 整体 ok=False；产物硬门走同源 selfcheck。

判定逻辑不重跑装置；e2e 只跑一次真实三车道冒烟（秒级）作为 2.1 的
测试化证明。
"""

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_mod():
    name = "dsh_acceptance_under_test"
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "bin" / "dsh_acceptance.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _load_mod()


HAS_DSH_NODE = bool(shutil.which("dsh") and shutil.which("node"))
HAS_CLAUDE = bool(shutil.which("claude"))

e2e_gate = pytest.mark.skipif(
    not HAS_DSH_NODE,
    reason="e2e 冒烟依赖真实 dsh 与 node 二进制（未装则跳过，同 SPEC-3 7.1）")


# ── 全绿证据构造（判定函数的判定输入）─────────────────────────────────

def _green_agent_evidence(mod, lane: str) -> dict:
    ev = {
        "lane": lane, "run_id": f"impl-x-a1", "spec": "x-impl",
        "elapsed_seconds": 2.0,
        "inflight_observed": True,
        "inflight_cmdline_sample": ["dsh --headless"],
        "output": "实现冒烟完成" if lane == "implementer" else "验证冒烟完成",
        "turns": 2, "session_id": "sess-1",
        "usage_source": "available",
        "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": None},
        "problems": [],
        "run_jsonl_first": {"type": "system", "harness": "dsh"},
        "run_jsonl_last_type": "result",
        "tool_use_names": ["TaskCreate", "Write"],
        "projection": {
            "harness": "dsh",
            "events_received": {"final": 1, "session": 1},
            "events_projected": {"final": 1, "session": 1},
            "bad_events": {"json_parse_failed": 0, "unknown_type": 0,
                           "over_limit_truncated": 0},
        },
        "raw_dump_exists": True, "raw_dump_first_type": "session",
        "result_gate": {"exit_code": 0, "passed": True, "detail": ""},
        "verification_report_written": True if lane == "verifier" else None,
        "mock_requests": 3, "mock_model_seen": mod.MOCK_MODEL,
        "mock_tools_contain_taskcreate": True,
    }
    return ev


def _green_judge_evidence(mod) -> dict:
    return {
        "lane": "judge", "run_id": "judge-one-shot",
        "elapsed_seconds": 1.5, "inflight_observed": True,
        "inflight_cmdline_sample": ["d"],
        "returncode": 0, "timed_out": False,
        "final_text": '{"verdict": "advancing", "evidence": "前进一步"}',
        "stream_error": None,
        "verdict": {"verdict": "advancing", "evidence": "前进一步"},
        "stderr_head": "", "mock_requests": 2,
        "mock_model_seen": mod.MOCK_MODEL,
    }


# ── 夹具：结构 / 唯一前缀 / 清理闭环 ──────────────────────────────────

def test_unique_prefix_is_unique(mod):
    assert mod.unique_prefix() != mod.unique_prefix()
    assert mod.unique_prefix().startswith(mod.FIXTURE_STEM + "-")


def test_fixture_build_structure(mod, tmp_path):
    prefix = mod.unique_prefix()
    fx = mod.build_fixture(tmp_path, prefix)
    assert fx["prefix"] == prefix
    assert fx["impl_spec"] == f"{prefix}-impl"
    assert fx["verify_spec"] == f"{prefix}-verify"
    for key in ("project_root", "worktree", "runs_dir"):
        assert Path(fx[key]).is_dir(), key
    for spec in (fx["impl_spec"], fx["verify_spec"]):
        spec_dir = Path(fx["worktree"]) / "spec" / "changes" / spec
        assert (spec_dir / "proposal.md").is_file()
        # 全勾 tasks.md 种子：result gate completed_tasks↔tasks.md 对账输入
        assert "[x] 1.1" in (spec_dir / "tasks.md").read_text(encoding="utf-8")


def test_fixture_cleanup_roundtrip(mod, tmp_path):
    fx = mod.build_fixture(tmp_path, mod.unique_prefix())
    receipt = mod.cleanup_fixture(fx)
    assert receipt["residue_free"] is True
    assert sorted(Path(p).name for p in receipt["removed"]) == \
        sorted([Path(fx["project_root"]).name, Path(fx["worktree"]).name])
    assert not Path(fx["project_root"]).exists()
    assert not Path(fx["worktree"]).exists()
    # 父目录已空则一并移除（tmp_path 只含夹具时成立）
    assert receipt["parent_removed"] is True
    assert not tmp_path.exists()


def test_fixture_cli_roundtrip(mod, tmp_path, capsys):
    rc = mod.main(["fixture", "--json"])
    assert rc == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["cleanup"]["residue_free"] is True
    assert not Path(manifest["project_root"]).exists()


def test_fixture_cli_keep_preserves(mod, tmp_path, capsys):
    rc = mod.main(["fixture", "--parent", str(tmp_path), "--keep", "--json"])
    assert rc == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest.get("kept") is True
    assert Path(manifest["project_root"]).is_dir()
    mod.cleanup_fixture(manifest)  # 现场自清理，不留测试残留


# ── smoke 模式行为 ─────────────────────────────────────────────────────

def test_smoke_unknown_lane_rejected(mod, capsys):
    rc = mod.main(["smoke", "--lanes", "bogus"])
    assert rc == 2
    assert "未知车道" in capsys.readouterr().err


def test_lane_steps_shape(mod, tmp_path):
    fx = mod.build_fixture(tmp_path, mod.unique_prefix())
    assert mod.lane_steps("judge", fx) == mod.judge_lane_steps()
    for lane in ("implementer", "verifier"):
        steps = mod.lane_steps(lane, fx)
        assert steps, lane
        kinds = [s.get("kind") for s in steps]
        assert "tool_calls" in kinds and "text" in kinds, kinds
        # 终文本收口（evaluate 判定的 output 期望值来源）
        assert steps[-1]["kind"] == "text"
    # 车道编排均含 write 结果文件步骤（产物硬门的判定对象）
    assert any(
        tc["name"] == "write"
        for s in mod.lane_steps("implementer", fx) if s["kind"] == "tool_calls"
        for tc in s["toolCalls"])
    # real 模式不编排假端点步骤
    for lane in ("implementer", "verifier", "judge"):
        assert mod.lane_steps(lane, fx, real=True) == []
    mod.cleanup_fixture(fx)


def test_result_file_payload_passes_gate(mod, tmp_path):
    # 结果文件落夹具 worktree 根（selfcheck 按 <结果文件目录>/spec/changes/
    # <spec>/tasks.md 对账勾选集合，故须配全勾种子夹具）
    fx = mod.build_fixture(tmp_path, mod.unique_prefix())
    payload = mod.result_file_payload(fx["impl_spec"], "smoke")
    path = Path(fx["worktree"]) / ".fenix-run-result.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    gate = mod.result_gate_selfcheck(path)
    assert gate["passed"] is True, gate["detail"]
    assert gate["exit_code"] == 0
    mod.cleanup_fixture(fx)


def test_result_gate_missing_file_fail_loud(mod, tmp_path):
    gate = mod.result_gate_selfcheck(tmp_path / "absent.json")
    assert gate["passed"] is False
    assert "缺失" in gate["detail"]


# ── 证据判定纯函数 ─────────────────────────────────────────────────────

def test_evaluate_agent_lane_green(mod):
    for lane in ("implementer", "verifier"):
        assert mod.evaluate_agent_lane(_green_agent_evidence(mod, lane)) == []


@pytest.mark.parametrize("mutate,fragment", [
    (lambda e: e.update(output="答非所问"), "output"),
    (lambda e: e.update(session_id=None), "session_id"),
    (lambda e: e.update(turns=0), "num_turns"),
    (lambda e: e.update(usage_source="unavailable"), "usage_source"),
    (lambda e: e.update(usage={"input_tokens": 0, "output_tokens": 0}),
     "usage 数值异常"),
    (lambda e: e.update(inflight_observed=False), "在飞"),
    (lambda e: e.update(run_jsonl_first={"type": "assistant"}),
     "run jsonl 首行"),
    (lambda e: e.update(run_jsonl_last_type="assistant"), "末行"),
    (lambda e: e.update(tool_use_names=["Write"]), "Task 工具族"),
    (lambda e: e["projection"]["bad_events"].update({"unknown_type": 2}),
     "坏事件"),
    (lambda e: e.update(raw_dump_exists=False), "dump"),
    (lambda e: e.update(raw_dump_first_type="status"), "dump 首行"),
    (lambda e: e.update(result_gate={"passed": False, "detail": "x"}),
     "硬门"),
    (lambda e: e.update(mock_requests=0), "零请求"),
    (lambda e: e.update(mock_model_seen="claude-3"), "model="),
    (lambda e: e.update(mock_tools_contain_taskcreate=False), "工具面"),
])
def test_evaluate_agent_lane_fail_loud_matrix(mod, mutate, fragment):
    ev = _green_agent_evidence(mod, "implementer")
    mutate(ev)
    failures = mod.evaluate_agent_lane(ev)
    assert failures and any(fragment in f for f in failures), failures


def test_evaluate_agent_lane_verifier_report_required(mod):
    ev = _green_agent_evidence(mod, "verifier")
    ev["verification_report_written"] = False
    failures = mod.evaluate_agent_lane(ev)
    assert any("验证报告" in f for f in failures), failures


def test_evaluate_agent_lane_projection_missing(mod):
    ev = _green_agent_evidence(mod, "implementer")
    ev["projection"] = None
    failures = mod.evaluate_agent_lane(ev)
    assert any("projection" in f for f in failures), failures


def test_evaluate_judge_lane_green(mod):
    assert mod.evaluate_judge_lane(_green_judge_evidence(mod)) == []


def test_evaluate_judge_lane_fail_loud(mod):
    base = _green_judge_evidence(mod)
    for mutate, fragment in (
            (lambda e: e.update(returncode=1), "退出码"),
            (lambda e: e.update(timed_out=True), "超时"),
            (lambda e: e.update(inflight_observed=False), "在飞"),
            (lambda e: e.update(stream_error="事件流断"), "事件流"),
            (lambda e: e.update(verdict=None), "裁决不可解析"),
            (lambda e: e["verdict"].update(verdict="vibes"),
             "词表外"),
            (lambda e: e["verdict"].update(evidence=""), "evidence 为空"),
            (lambda e: e.update(mock_requests=0), "零请求"),
    ):
        ev = json.loads(json.dumps(base))
        mutate(ev)
        failures = mod.evaluate_judge_lane(ev)
        assert failures and any(fragment in f for f in failures), \
            (fragment, failures)


def test_evaluate_evidence_fail_loud_any_lane(mod):
    lanes = [_green_agent_evidence(mod, "implementer"),
             _green_agent_evidence(mod, "verifier"),
             _green_judge_evidence(mod)]
    assert mod.evaluate_evidence(lanes) == {"ok": True, "failures": {}}
    lanes[1]["output"] = "跑偏"
    ev = mod.evaluate_evidence(lanes)
    assert ev["ok"] is False
    assert "verifier" in ev["failures"]


# ── 基线比对 ───────────────────────────────────────────────────────────

def test_compare_baseline_unavailable(mod, tmp_path):
    lanes = [_green_agent_evidence(mod, "implementer")]
    no_arg = mod.compare_baseline(lanes, None)
    assert no_arg["status"] == "unavailable"
    missing = mod.compare_baseline(
        lanes, tmp_path / "nope.json")
    assert missing["status"] == "unavailable"
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert mod.compare_baseline(lanes, bad)["status"] == "unavailable"
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    assert mod.compare_baseline(lanes, empty)["status"] == "unavailable"


def test_compare_baseline_ratio(mod, tmp_path):
    baseline = tmp_path / "base.json"
    baseline.write_text(json.dumps({"lanes": {
        "implementer": {"duration_seconds": 4.0}}}), encoding="utf-8")
    lanes = [_green_agent_evidence(mod, "implementer"),
             _green_judge_evidence(mod)]
    out = mod.compare_baseline(lanes, baseline)
    assert out["status"] == "available"
    rows = {r["lane"]: r for r in out["rows"]}
    assert rows["implementer"]["ratio"] == 0.5
    assert rows["implementer"]["claude_seconds"] == 4.0
    assert rows["judge"]["ratio"] is None  # 基线无该车道 → 不伪造对比


# ── 夹具残留核对（Path.home 隔离到 tmp）───────────────────────────────

def test_residue_check_clean_and_dirty(mod, tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    fx = mod.build_fixture(tmp_path / "holder", mod.unique_prefix())
    mod.cleanup_fixture(fx)
    clean = mod.residue_check(fx["prefix"], fx, tmp_path / "holder")
    assert clean["residue_free"] is True, clean["problems"]

    # 夹具未清理 → 报残留
    fx2 = mod.build_fixture(tmp_path / "holder2", mod.unique_prefix())
    dirty = mod.residue_check(fx2["prefix"], fx2, None)
    assert dirty["residue_free"] is False
    assert any("夹具未清理" in p for p in dirty["problems"])

    # ~/.dsh 残留 → 报残留（唯一前缀识别）
    home_dsh = tmp_path / ".dsh"
    (home_dsh / "sessions").mkdir(parents=True)
    (home_dsh / "sessions" / f"run-{fx2['prefix']}.jsonl").write_text(
        "{}", encoding="utf-8")
    mod.cleanup_fixture(fx2)
    dirty2 = mod.residue_check(fx2["prefix"], fx2, None)
    assert dirty2["residue_free"] is False
    assert any(".dsh" in p for p in dirty2["problems"])


# ── accept 模式：自检 / dry-run ────────────────────────────────────────

def test_accept_selfcheck_lists_missing_dsh(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    checks = mod.accept_selfcheck(tmp_path, "fenix", with_claude_baseline=True)
    by_name = {c["name"]: c for c in checks}
    assert by_name["dsh 可用"]["ok"] is False
    assert by_name["dsh 可用"]["fix"], "缺修复指引"
    assert by_name["claude CLI（基线车道）"]["ok"] is False
    # 健康门在 dsh 缺失时不再探测（不重复报同一根因）
    assert "dsh 健康门" not in by_name


def test_accept_selfcheck_missing_providers(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/dsh")
    empty_root = tmp_path / "proj"
    (empty_root / ".fenix").mkdir(parents=True)
    (empty_root / ".fenix" / "config.yaml").write_text(
        "llm:\n  providers: []\n", encoding="utf-8")
    from core.config import ConfigLoader
    monkeypatch.setattr(
        ConfigLoader, "resolve_config",
        classmethod(lambda cls, root: {"llm": {"providers": []}}))
    checks = mod.accept_selfcheck(empty_root, "fenix",
                                  with_claude_baseline=False)
    item = next(c for c in checks if c["name"] == "provider 链凭据")
    assert item["ok"] is False
    assert item["fix"], "缺修复指引"


def test_dry_run_plan_shape(mod):
    args = argparse.Namespace(no_claude_baseline=False, timeout=900.0,
                              evidence_dir=str(tmp_evidence()))
    plan = mod.dry_run_plan(list(mod.SMOKE_LANES), args)
    assert plan[0]["lane"].startswith("claude-implementer")
    assert plan[0]["harness"] == "claude"
    by_lane = {p["lane"]: p for p in plan}
    judge = next(p for name, p in by_lane.items()
                 if name.startswith("judge"))
    assert "run_one_shot" in judge["driver"]
    assert all(p["real_model_call"] is True
               for name, p in by_lane.items() if name != "报告产出")
    report = by_lane["报告产出"]
    assert report["real_model_call"] is False


def test_dry_run_plan_no_baseline_lane(mod):
    args = argparse.Namespace(no_claude_baseline=True, timeout=1.0,
                              evidence_dir=str(tmp_evidence()))
    plan = mod.dry_run_plan(["implementer"], args)
    assert not any(p["lane"].startswith("claude") for p in plan)


def tmp_evidence() -> Path:
    import tempfile
    return Path(tempfile.mkdtemp(prefix="dshacc-plan-"))


@pytest.mark.skipif(not (HAS_DSH_NODE and HAS_CLAUDE),
                    reason="accept 自检全绿路径依赖 dsh/node/claude 在场")
def test_accept_cli_dry_run_all_green(mod, capsys):
    # 预演：零真实调用；全绿时退出 0 且明示 --go 人工触发语义
    rc = mod.main(["accept"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    assert "dry-run" in out.out and "--go" in out.out
    assert "自检全绿" in out.out


def test_accept_cli_dry_run_missing_never_go(mod, capsys, monkeypatch):
    # 凭据/环境缺失场景：自检失败列出缺失项与修复指引，退出 1，
    # 绝不进入执行分支（spec Scenario「真实模式执行前自检」）
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    rc = mod.main(["accept", "--no-claude-baseline"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "✗" in captured.out and "修复指引" in captured.out
    assert "未执行" in captured.err and "真实调用" in captured.err


# ── e2e：三车道假端点全链（真实 dsh + node；同 SPEC-3 冒烟装置）────────

@e2e_gate
def test_smoke_end_to_end_three_lanes(mod, tmp_path):
    args = argparse.Namespace(
        lanes=",".join(mod.SMOKE_LANES), profile="fenix", timeout=150.0,
        evidence_dir=str(tmp_path), baseline_json=None, keep=False,
        json=False)
    rc = mod.run_smoke(args)
    assert rc == 0, "smoke 三车道全链未过（fail-loud 判定见证据文件）"
    evidence_files = list(tmp_path.glob("dsh-acceptance-smoke-*.json"))
    assert len(evidence_files) == 1
    ev = json.loads(evidence_files[0].read_text(encoding="utf-8"))
    assert [l["lane"] for l in ev["lanes"]] == \
        ["implementer", "verifier", "judge"]
    assert ev["evaluation"]["ok"] is True
    assert ev["fixture_cleanup"]["residue_free"] is True
    assert ev["residue_check"]["residue_free"] is True
