"""
schema-alignment-showcase/check.py — evo-planner-scenario-schema-alignment 验证辅助脚本。

供 cli 场景 run 调用：subcommand 分发 + 结构化 JSON 输出。
每个 subcommand 将检查结果输出为单行 JSON（{"status": "pass"|"fail", "detail": ...}），
cli 场景用 output_match / json_output 断言解析。

运行前提：cwd 为验证树根（engine 自动注入），sys.path 已含项目根。
"""
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROOT = Path.cwd()


def _log():
    class L:
        def __init__(self):
            self.warnings = []
            self.errors = []
            self.infos = []
        def warning(self, *a, **k): self.warnings.append((a, k))
        def error(self, *a, **k): self.errors.append((a, k))
        def info(self, *a, **k): self.infos.append((a, k))
    return L()


# ── 各检查项 ──────────────────────────────────────────────────

def check_output_match_missing_expected() -> dict:
    """D1: output_match 缺 expected → 校验拒绝。"""
    sys.path.insert(0, str(PROOT))
    from core.verify_engine.scenarios import validate_scenario_dicts
    errs = validate_scenario_dicts([{
        "id": "x", "kind": "cli",
        "steps": [{"action": "run", "command": "echo hi"}],
        "assertions": [{"type": "output_match"}],
    }])
    hit = any("output_match" in e and "expected" in e for e in errs)
    return {"status": "pass" if hit else "fail",
            "detail": json.dumps(errs, ensure_ascii=False)}


def check_json_output_missing_step_path() -> dict:
    """D1: json_output 缺 step + path → 两条报错。"""
    sys.path.insert(0, str(PROOT))
    from core.verify_engine.scenarios import validate_scenario_dicts
    errs = validate_scenario_dicts([{
        "id": "x", "kind": "cli",
        "steps": [{"action": "run", "command": "echo hi"}],
        "assertions": [{"type": "json_output"}],
    }])
    joined = "；".join(errs)
    hit = "step" in joined and "path" in joined
    return {"status": "pass" if hit else "fail",
            "detail": json.dumps(errs, ensure_ascii=False)}


def check_status_code_include_zero() -> dict:
    """D1 + 4.3: status_code expected=0 合法、缺 expected 非法（include_zero）。"""
    sys.path.insert(0, str(PROOT))
    from core.verify_engine.scenarios import validate_scenario_dicts
    zero_ok = validate_scenario_dicts([{
        "id": "x", "kind": "api",
        "steps": [{"action": "http_request", "method": "GET", "url": "http://localhost/"}],
        "assertions": [{"type": "status_code", "expected": 0}],
    }])
    missing_bad = validate_scenario_dicts([{
        "id": "x", "kind": "api",
        "steps": [{"action": "http_request", "method": "GET", "url": "http://localhost/"}],
        "assertions": [{"type": "status_code"}],
    }])
    hit = (zero_ok == []) and any("status_code" in e for e in missing_bad)
    return {"status": "pass" if hit else "fail",
            "detail": json.dumps({"zero_ok": zero_ok, "missing_bad": missing_bad},
                                 ensure_ascii=False)}


def check_api_step_missing_method_url() -> dict:
    """D1: http_request 缺 method + url → 报错；run 缺 command → 报错。"""
    sys.path.insert(0, str(PROOT))
    from core.verify_engine.scenarios import validate_scenario_dicts
    api_errs = validate_scenario_dicts([{
        "id": "x", "kind": "api",
        "steps": [{"action": "http_request"}],
        "assertions": [{"type": "status_code", "expected": 200}],
    }])
    cli_errs = validate_scenario_dicts([{
        "id": "y", "kind": "cli",
        "steps": [{"action": "run"}],
        "assertions": [{"type": "exit_code", "expected": 0}],
    }])
    a = "；".join(api_errs); c = "；".join(cli_errs)
    hit = ("method" in a and "url" in a) and ("command" in c)
    return {"status": "pass" if hit else "fail",
            "detail": json.dumps({"api": api_errs, "cli": cli_errs},
                                 ensure_ascii=False)}


def check_valid_complete_scenarios() -> dict:
    """D1 正向: 合法完整 cli + api 场景通过校验。"""
    sys.path.insert(0, str(PROOT))
    from core.verify_engine.scenarios import validate_scenario_dicts
    errs = validate_scenario_dicts([
        {"id": "c1", "kind": "cli",
         "steps": [{"action": "run", "command": "echo hello"}],
         "assertions": [{"type": "output_match", "expected": "hello"},
                        {"type": "json_output", "step": "r1", "path": "data.items"}]},
        {"id": "a1", "kind": "api",
         "steps": [{"action": "http_request", "method": "GET", "url": "http://localhost/"}],
         "assertions": [{"type": "status_code", "expected": 200},
                        {"type": "json_path", "path": "data"}]},
    ])
    return {"status": "pass" if errs == [] else "fail",
            "detail": json.dumps(errs, ensure_ascii=False)}


def _build_prompt(agent_type: str) -> str:
    """在最小工作目录下构建指定 agent 的 prompt（复用测试夹具方式）。"""
    from tests.test_agent_runner import make_runner
    tmp = Path("/tmp/sa-prompt-%s" % agent_type)
    shutil.rmtree(tmp, ignore_errors=True)
    proot = tmp / "proj"
    proot.mkdir(parents=True)
    (proot / "spec" / "changes" / "test").mkdir(parents=True)
    (proot / "spec" / "changes" / "test" / "tasks.md").write_text(
        "# Tasks\n- [ ] 1.1 do it\n")
    (proot / ".fenix" / "verify-progress" / "test").mkdir(parents=True)
    runner = make_runner(proot)
    return runner._prompt_builder._build_prompt("test", agent_type)


def check_prompt_injection(agent_type: str, expect_present: bool) -> dict:
    """D2: 指定分支 prompt 是否含 schema 注入段。"""
    sys.path.insert(0, str(PROOT))
    prompt = _build_prompt(agent_type)
    hit = "场景断言/操作必填字段" in prompt
    ok = hit == expect_present
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"agent": agent_type, "has_schema_section": hit},
                                 ensure_ascii=False)}


def check_prompt_contains_samples(agent_type: str, needles: list) -> dict:
    """D2: 注入段含必填字段的合法 JSON 样例（output_match.expected / json_output.step+path）。"""
    sys.path.insert(0, str(PROOT))
    prompt = _build_prompt(agent_type)
    missing = [n for n in needles if n not in prompt]
    ok = not missing
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"agent": agent_type, "missing": missing},
                                 ensure_ascii=False)}


def check_prevalidation_single_invalid() -> dict:
    """D3: 单条非法剔除留痕、合法条目照常写回并可经 load_scenarios 加载。"""
    sys.path.insert(0, str(PROOT))
    from core.pm_engine.verification import VerificationPipeline
    from core.state_machine import StateMachine
    from core.verify_engine.scenarios import load_scenarios

    tmp = Path("/tmp/sa-prevalidation-single")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / ".fenix").mkdir(parents=True)
    sm = StateMachine(tmp / ".fenix" / "STATE.md", _log())
    pm = MagicMock()
    pm.project_root = tmp
    pm.logger = _log()
    pm.state_machine = sm
    vp = tmp / ".fenix" / "verify-progress" / "test"
    vp.mkdir(parents=True)
    (vp / "test_scenarios.json").write_text(json.dumps([
        {"id": "w1", "kind": "web",
         "steps": [{"action": "navigate", "value": "http://127.0.0.1:8000/"},
                   {"action": "click", "target": "#x"}],
         "assertions": [{"type": "element_visible", "selector": "#x"}]},
        {"id": "bad", "description": "缺 steps"},
    ], ensure_ascii=False, indent=2))
    sm.add_spec("test", {"priority": 5})
    sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
    pm._current_verify_round.return_value = 1
    vpipe = VerificationPipeline(pm)
    result = vpipe._apply_scenario_freeze("test")
    if result.get("aborted"):
        return {"status": "fail", "detail": json.dumps(result, ensure_ascii=False)}
    ids = {e.id for e in result["diff"].scenario_set.scenarios}
    written = json.loads((vp / "test_scenarios.json").read_text())
    wids = {s.get("id") for s in written}
    loaded = load_scenarios(vp / "test_scenarios.json")
    ok = (ids == {"w1"} and wids == {"w1"}
          and [s.id for s in loaded] == ["w1"]
          and "bad" not in wids)
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"diff_ids": sorted(ids), "written_ids": sorted(wids),
                                  "loaded": [s.id for s in loaded]},
                                 ensure_ascii=False)}


def check_prevalidation_all_invalid_abort() -> dict:
    """D3: 全部条目非法 → 结构化 aborted 信号，不写空文件。"""
    sys.path.insert(0, str(PROOT))
    from core.pm_engine.verification import VerificationPipeline
    from core.state_machine import StateMachine

    tmp = Path("/tmp/sa-prevalidation-all")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / ".fenix").mkdir(parents=True)
    sm = StateMachine(tmp / ".fenix" / "STATE.md", _log())
    pm = MagicMock()
    pm.project_root = tmp
    pm.logger = _log()
    pm.state_machine = sm
    vp = tmp / ".fenix" / "verify-progress" / "test"
    vp.mkdir(parents=True)
    (vp / "test_scenarios.json").write_text(json.dumps([
        {"id": "a", "description": "缺 kind/steps"},
        {"id": "b", "description": "也缺"},
    ], ensure_ascii=False, indent=2))
    sm.add_spec("test", {"priority": 5})
    sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
    pm._current_verify_round.return_value = 1
    vpipe = VerificationPipeline(pm)
    result = vpipe._apply_scenario_freeze("test")
    # 断言：aborted 信号 + rejected 列表 + 不写空文件
    aborted = result.get("aborted") == "no_valid_scenarios"
    rejected_ok = isinstance(result.get("rejected"), list) and len(result["rejected"]) == 2
    orig = json.loads((vp / "test_scenarios.json").read_text())
    not_emptied = len(orig) == 2  # 原始非法条目仍保留（未被写空/覆盖）
    ok = aborted and rejected_ok and not_emptied
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"result": result, "file_len": len(orig)},
                                 ensure_ascii=False, default=str)}


def check_prevalidation_persisted_unchanged() -> dict:
    """D3: 空集时持久化集 scenarios.json 保持不变。"""
    sys.path.insert(0, str(PROOT))
    from core.pm_engine.verification import VerificationPipeline
    from core.state_machine import StateMachine
    from core.verify_scenarios import ScenarioEntry, ScenarioSet, save_scenario_set, load_scenario_set

    tmp = Path("/tmp/sa-prevalidation-persist")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / ".fenix").mkdir(parents=True)
    sm = StateMachine(tmp / ".fenix" / "STATE.md", _log())
    pm = MagicMock()
    pm.project_root = tmp
    pm.logger = _log()
    pm.state_machine = sm
    # 预置持久化集
    save_scenario_set(tmp, ScenarioSet("test", 1,
        [ScenarioEntry("existing", "既有场景", added_in_round=1, kind="web")]))
    vp = tmp / ".fenix" / "verify-progress" / "test"
    vp.mkdir(parents=True, exist_ok=True)
    if (vp / "test_scenarios.json").exists():
        (vp / "test_scenarios.json").unlink()
    (vp / "test_scenarios.json").write_text(json.dumps([
        {"id": "bad", "description": "非法"},
    ], ensure_ascii=False, indent=2))
    sm.add_spec("test", {"priority": 5})
    sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
    pm._current_verify_round.return_value = 1
    vpipe = VerificationPipeline(pm)
    result = vpipe._apply_scenario_freeze("test")
    aborted = result.get("aborted") == "no_valid_scenarios"
    ps = load_scenario_set(tmp, "test")
    persisted_ok = ps is not None and [e.id for e in ps.scenarios] == ["existing"]
    ok = aborted and persisted_ok
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"aborted": result.get("aborted"),
                                  "persisted_ids": [e.id for e in ps.scenarios] if ps else None},
                                 ensure_ascii=False)}


def check_rejected_covers_stored() -> dict:
    """D3.10: 剔除条目 id 与 covers 留痕供交互契约消费。"""
    sys.path.insert(0, str(PROOT))
    from core.pm_engine.verification import VerificationPipeline
    from core.state_machine import StateMachine

    tmp = Path("/tmp/sa-covers")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / ".fenix").mkdir(parents=True)
    sm = StateMachine(tmp / ".fenix" / "STATE.md", _log())
    pm = MagicMock()
    pm.project_root = tmp
    pm.logger = _log()
    pm.state_machine = sm
    vp = tmp / ".fenix" / "verify-progress" / "test"
    vp.mkdir(parents=True)
    (vp / "test_scenarios.json").write_text(json.dumps([
        {"id": "w1", "kind": "web",
         "steps": [{"action": "navigate", "value": "http://127.0.0.1:8000/"},
                   {"action": "click", "target": "#x"}],
         "assertions": [{"type": "element_visible", "selector": "#x"}]},
        {"id": "bad", "description": "非法", "kind": "web", "covers": ["card-link"]},
    ], ensure_ascii=False, indent=2))
    sm.add_spec("test", {"priority": 5})
    sm.update_spec("test", {"status": "testing", "_verify_fail_rounds": 0})
    pm._current_verify_round.return_value = 1
    vpipe = VerificationPipeline(pm)
    vpipe._apply_scenario_freeze("test")
    ok = ("bad" in vpipe._last_freeze_rejected
          and "card-link" in vpipe._last_freeze_rejected_covers)
    return {"status": "pass" if ok else "fail",
            "detail": json.dumps({"rejected": vpipe._last_freeze_rejected,
                                  "covers": sorted(vpipe._last_freeze_rejected_covers)},
                                 ensure_ascii=False)}


# ── 分发 ──────────────────────────────────────────────────────

HANDLERS = {
    "output-match-missing-expected": lambda: check_output_match_missing_expected(),
    "json-output-missing-step-path": lambda: check_json_output_missing_step_path(),
    "status-code-include-zero": lambda: check_status_code_include_zero(),
    "api-step-missing-method-url": lambda: check_api_step_missing_method_url(),
    "valid-complete-scenarios": lambda: check_valid_complete_scenarios(),
    "prompt-injection": lambda: check_prompt_injection(sys.argv[2],
        sys.argv[3] == "present"),
    "prompt-samples": lambda: check_prompt_contains_samples(sys.argv[2],
        sys.argv[3:]),
    "prevalidation-single-invalid": lambda: check_prevalidation_single_invalid(),
    "prevalidation-all-invalid-abort": lambda: check_prevalidation_all_invalid_abort(),
    "prevalidation-persisted-unchanged": lambda: check_prevalidation_persisted_unchanged(),
    "rejected-covers-stored": lambda: check_rejected_covers_stored(),
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in HANDLERS:
        print(json.dumps({"status": "fail", "detail": "unknown subcommand"},
                         ensure_ascii=False))
        return 1
    try:
        result = HANDLERS[sys.argv[1]]()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"status": "fail", "detail": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())