#!/usr/bin/env python3
"""provider-fallback-dispatch-gate 场景执行探针（fast-track 场景集驱动）。

每个场景独立执行并输出单行 JSON 结论（{"scenario","pass","summary",
"checks":[...]}），退出码 0=场景内全部检查通过。供 verify 链（cli 形态
场景 run 步骤 + json_output 断言）与本 run 的 PHASE 3 复用；密闭性纪律
同 tests/test_provider_fallback_dispatch_gate.py——os.environ 三键显式
控制、AdminStore 落盘不出 tmp、dsh 版本漂移以 stub 真子进程模拟（不
patch check_health 本体，闸消费链路全真实）。

用法：python3 tests/verify_fb_gate_probe.py <scenario_id>
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner import AgentRunner  # noqa: E402
from core.agent_runner.harness import (  # noqa: E402
    DshAdapter,
    DshAdapterConfig,
    set_current_adapter,
)
from core.agent_runner.lane_preflight import (  # noqa: E402
    LANE_INFRA_FINGERPRINTS,
    PROVIDER_FALLBACK_ALERT_SIGNAL,
    classify_lane_failure,
    probe_default_chain_credentials,
    probe_lane_health,
    provider_fallback_dedup_key,
)
from core.admin_store import AdminStore  # noqa: E402
from tests.helpers import make_runner  # noqa: E402

# env 三键显式控制面（不依赖宿主环境值）
ENV_OK = {"ANTHROPIC_BASE_URL": "https://gw.example/v1",
          "ANTHROPIC_AUTH_TOKEN": "tok-1", "ANTHROPIC_API_KEY": ""}
ENV_MISSING = {"ANTHROPIC_BASE_URL": "https://gw.example/v1",
               "ANTHROPIC_AUTH_TOKEN": "", "ANTHROPIC_API_KEY": ""}
ENV_EMPTY = {"ANTHROPIC_BASE_URL": "", "ANTHROPIC_AUTH_TOKEN": "",
             "ANTHROPIC_API_KEY": ""}

_EXPLICIT_CHAIN_CONFIG = {
    "llm": {"providers": [{
        "name": "p1", "baseurl": "https://gw.example/v1",
        "apikey": "sk-test", "model": "m1",
    }]},
    "agents": {"models": {"repair": {"provider": "p1"}}},
}

_DISPATCH_PROBE_LANES_BASELINE = frozenset({
    "evolution", "code-review", "code-fix", "administrator", "self-review",
    "arbiter",
})


def _check(checks, name, ok, detail=""):
    checks.append({"name": name, "pass": bool(ok), "detail": str(detail)[:300]})


def _alerts(proot):
    store = AdminStore(proot, None)
    return [r for r in store.read_all()
            if r.get("signal_type") == PROVIDER_FALLBACK_ALERT_SIGNAL]


def _patch_env(form):
    return patch.dict("os.environ", form, clear=False)


def _make_runner(proot, config=None):
    return make_runner(proot, config if config is not None else {})


# ── s1: probe-fallback-credential-verdicts ─────────────────────────────

def s1_probe_fallback_credential_verdicts():
    checks = []
    with _patch_env(ENV_OK):
        v, d = probe_default_chain_credentials({})
        _check(checks, "env-complete-verdict-ok", v == "ok", d)
    with _patch_env(ENV_MISSING):
        v, d = probe_default_chain_credentials({})
        _check(checks, "route-without-key-verdict-missing", v == "missing", d)
    with _patch_env(ENV_EMPTY):
        v, d = probe_default_chain_credentials({})
        _check(checks, "no-route-trace-indeterminable",
               v == "indeterminable", d)
    v, d = probe_default_chain_credentials({"agent": {"harness": "dsh"}})
    _check(checks, "dsh-profile-default-indeterminable",
           v == "indeterminable" and "dsh" in d, d)
    # probe② 输出带 fallback 标记的明确结果（不再静默跳过）
    with _patch_env(ENV_MISSING):
        health = probe_lane_health({"agent": {"harness": "claude"}})
        _check(checks, "probe2-outputs-fallback-verdict",
               health.fallback_verdicts.get("repair") == "missing",
               health.fallback_verdicts)
        _check(checks, "probe2-reason-carries-fallback-flag",
               any("fallback=true" in r and "repair" in r
                   for r in health.reasons),
               health.reasons)
    # 显式链角色探针行为不变：不进 fallback_verdicts 表
    with _patch_env(ENV_MISSING):
        health2 = probe_lane_health(_EXPLICIT_CHAIN_CONFIG)
        _check(checks, "explicit-chain-role-not-in-verdicts",
               "repair" not in health2.fallback_verdicts,
               health2.fallback_verdicts)
    # 合法回落语义保留：回落到可用链 verdict ok、无 fallback reason
    with _patch_env(ENV_OK):
        health3 = probe_lane_health({"agent": {"harness": "claude"}})
        _check(checks, "legal-fallback-verdict-ok-no-reason",
               health3.fallback_verdicts.get("repair") == "ok"
               and not [r for r in health3.reasons if "fallback=true" in r],
               health3.fallback_verdicts)
    return _result("probe-fallback-credential-verdicts", checks,
                   "probe② 回落角色默认链凭据三值判定与 fallback 标记输出")


# ── s2: fallback-first-dispatch-frozen ─────────────────────────────────

def s2_fallback_first_dispatch_frozen():
    checks = []
    tmp = tempfile.mkdtemp(prefix="fb-s2-")
    try:
        proot = Path(tmp)
        runner = _make_runner(proot)
        with _patch_env(ENV_MISSING):
            reject1 = runner._provider_fallback_dispatch_gate("repair")
        _check(checks, "first-dispatch-rejected", reject1 is not None
               and "[provider-fallback-frozen]" in reject1, reject1)
        _check(checks, "rejection-names-role", "repair" in (reject1 or ""), "")
        alerts = _alerts(proot)
        _check(checks, "single-alert-recorded", len(alerts) == 1
               and alerts[0].get("dedup_key") == provider_fallback_dedup_key("repair"),
               [a.get("dedup_key") for a in alerts])
        _check(checks, "alert-names-role-and-chain",
               "repair" in str(alerts[0].get("description"))
               and "fallback_chain" in str(alerts[0].get("evidence")),
               alerts[0].get("description"))
        # 后续命中更新计数而非新建
        with _patch_env(ENV_MISSING):
            runner._provider_fallback_dispatch_gate("repair")
        alerts = _alerts(proot)
        _check(checks, "hit-bumps-count-not-new-record",
               len(alerts) == 1 and alerts[0].get("hit_count") == 2,
               [(a.get("hit_count")) for a in alerts])
        # _run_agent 开头消费闸：拦截零产物（不产生秒挂 run）
        with _patch_env(ENV_MISSING):
            try:
                runner._run_agent("p", proot, "fb-run-1", spec_name="s",
                                  agent_type="repair")
                raised = None
            except RuntimeError as e:
                raised = str(e)
        _check(checks, "run-agent-raises-gate-error",
               raised is not None and "[provider-fallback-frozen]" in raised,
               raised)
        _check(checks, "no-run-artifact-created",
               not (proot / ".fenix" / "runs" / "fb-run-1.jsonl").exists(), "")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return _result("fallback-first-dispatch-frozen", checks,
                   "回落角色首派发被拦截且告警单条（命中计数不新建）")


# ── s3: explicit-chain-and-legal-fallback-pass ─────────────────────────

def s3_explicit_chain_and_legal_fallback():
    checks = []
    tmp = tempfile.mkdtemp(prefix="fb-s3-")
    try:
        proot = Path(tmp)
        runner = _make_runner(proot, dict(_EXPLICIT_CHAIN_CONFIG))
        with _patch_env(ENV_MISSING):
            r = runner._provider_fallback_dispatch_gate("repair")
        _check(checks, "explicit-chain-bypasses-freeze", r is None, r)
        _check(checks, "explicit-chain-no-alert", _alerts(proot) == [], "")
        # 合法回落（回落到可用链）仍放行——D3 语义保留
        runner2 = _make_runner(proot)
        with _patch_env(ENV_OK):
            r2 = runner2._provider_fallback_dispatch_gate("repair")
        _check(checks, "legal-fallback-to-usable-chain-passes", r2 is None, r2)
        _check(checks, "legal-fallback-no-alert", _alerts(proot) == [], "")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return _result("explicit-chain-and-legal-fallback-pass", checks,
                   "显式链角色不误伤；回落到可用链仍放行（D3 语义保留）")


# ── s4: thaw-hot-reload-and-allow-key ──────────────────────────────────

def s4_thaw_hot_reload_and_allow_key():
    checks = []
    tmp = tempfile.mkdtemp(prefix="fb-s4-")
    try:
        proot = Path(tmp)
        runner = _make_runner(proot)
        with _patch_env(ENV_MISSING):
            frozen = runner._provider_fallback_dispatch_gate("repair")
        _check(checks, "frozen-before-fix", frozen is not None, frozen)
        _check(checks, "alert-inflight", len(_alerts(proot)) == 1, "")
        # 配置热重载（凭据可用）经 TTL 重探感知 → 解冻 + 告警自动关闭
        cache = runner.__dict__.get("_provider_fallback_gate_cache")
        if cache is not None:
            cache.invalidate()
        with _patch_env(ENV_OK):
            r = runner._provider_fallback_dispatch_gate("repair")
        _check(checks, "thawed-after-hot-reload", r is None, r)
        alerts = _alerts(proot)
        _check(checks, "alert-auto-resolved-on-thaw",
               len(alerts) == 1 and alerts[0].get("handled") is True,
               alerts and alerts[0].get("handled"))
        # 放行配置项兜底：坏 env 下显式放行键打开即旁路
        runner3 = _make_runner(proot, {"agents": {
            "allow_harness_default_fallback": True}})
        with _patch_env(ENV_MISSING):
            r3 = runner3._provider_fallback_dispatch_gate("repair")
        _check(checks, "allow-key-bypasses-freeze", r3 is None, r3)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return _result("thaw-hot-reload-and-allow-key", checks,
                   "热重载凭据可用后解冻且告警自动关闭；放行键旁路生效")


# ── s5: direct-lane-version-gate ───────────────────────────────────────

_STUB_DSH_TEMPLATE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import sys
    args = sys.argv[1:]
    with open(%(counter)r, "a", encoding="utf-8") as f:
        f.write(" ".join(args) + "\\n")
    if "--version" in args:
        sys.stdout.write("dsh 0.2.1\\n")
        sys.exit(0)
    if "--dump-config" in args:
        sys.stdout.write("plugins: []\\n")
        sys.exit(0)
    sys.exit(0)
    ''')


def s5_direct_lane_version_gate():
    checks = []
    tmp = tempfile.mkdtemp(prefix="fb-s5-")
    try:
        stub = Path(tmp) / "dsh"
        counter = Path(tmp) / "counter.txt"
        stub.write_text(_STUB_DSH_TEMPLATE % {"counter": str(counter)},
                        encoding="utf-8")
        stub.chmod(0o755)
        proot = Path(tmp) / "proj"
        proot.mkdir()
        runner = _make_runner(proot)
        adapter = DshAdapter(DshAdapterConfig(dsh_bin=str(stub)))
        prev = set_current_adapter(adapter)
        try:
            # 版本探测走真实子进程（不 patch Popen——check_health 内部经
            # subprocess.run 同管道；「拦截在 spawn 前」由 stub counter 仅含
            # 探测行、无 agent spawn 调用 + runs 零产物共同证明）
            try:
                runner._run_agent("p", proot, "sr-run-1", spec_name="sx",
                                  agent_type="spec-review")
                raised = None
            except RuntimeError as e:
                raised = str(e)
            _check(checks, "version-drift-blocked-before-spawn",
                   raised is not None
                   and "[harness-health-gate]" in raised
                   and "低于最低兼容版本" in raised,
                   raised)
            _check(checks, "no-agent-spawn-hit-stub",
                   not (proot / ".fenix" / "runs" / "sr-run-1.jsonl").exists(),
                   "")
            # adapter 级缓存：二次直调复用失败结论，不再起探测子进程
            try:
                runner._run_agent("p", proot, "sr-run-2", spec_name="sx",
                                  agent_type="spec-review")
                raised2 = None
            except RuntimeError as e:
                raised2 = str(e)
            probes = counter.read_text(encoding="utf-8").splitlines()
            _check(checks, "second-call-also-blocked",
                   raised2 is not None and "[harness-health-gate]" in raised2,
                   raised2)
            _check(checks, "cache-reuses-conclusion-no-extra-probe",
                   len(probes) == 1 and probes[0].strip() == "--version",
                   probes)
        finally:
            set_current_adapter(prev)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return _result("direct-lane-version-gate-blocks", checks,
                   "直调车道版本漂移在 spawn 前被拦截（与 dispatch 族一致）；"
                   "adapter 级缓存复用不起重复探测子进程")


# ── s6: regression-protections-dispatch-lanes ──────────────────────────

def s6_regression_protections_dispatch_lanes():
    checks = []
    _check(checks, "dispatch-probe-lanes-whitelist-unchanged",
           AgentRunner._DISPATCH_PROBE_LANES == _DISPATCH_PROBE_LANES_BASELINE,
           sorted(AgentRunner._DISPATCH_PROBE_LANES))
    tmp = tempfile.mkdtemp(prefix="fb-s6-")
    try:
        proot = Path(tmp)
        runner = _make_runner(proot)
        for lane in ("spec", "impl", "verifier", "dispute-judge",
                     "spec-review"):
            if runner._dispatch_probe_lane(lane, "user-spec") is not None:
                _check(checks, f"dispatch-family-excluded-{lane}", False, lane)
                break
        else:
            _check(checks, "dispatch-family-excluded-from-connectivity-probe",
                   True, "")
        _check(checks, "maintenance-lane-still-probed",
               runner._dispatch_probe_lane("arbiter", "user-spec") == "arbiter"
               and runner._dispatch_probe_lane(None, "code-review")
               == "code-review", "")
        # 维护车道连通预检挂点行为不变：白名单车道仍触发预检
        runner2 = _make_runner(proot)
        calls = []
        runner2._dispatch_connectivity_preflight = (
            lambda *a, **k: calls.append(a))
        prev = set_current_adapter(MagicMock(name="claude"))
        try:
            with patch("subprocess.Popen",
                       side_effect=AssertionError("reached-popen")):
                for agent_type, expect_probe in (("evolution", True),
                                                 ("impl", False)):
                    calls.clear()
                    try:
                        runner2._run_agent("p", proot,
                                           f"{agent_type}-chk-1",
                                           spec_name="user-spec",
                                           agent_type=agent_type)
                    except AssertionError:
                        pass
                    _check(checks,
                           f"connectivity-preflight-{'fires' if expect_probe else 'skips'}-{agent_type}",
                           bool(calls) == expect_probe, len(calls))
        finally:
            set_current_adapter(prev)
        # 失败分级指纹与 0-rounds 判据不变
        _check(checks, "infra-fingerprints-unchanged",
               "MISSING_CREDENTIAL" in LANE_INFRA_FINGERPRINTS
               and "No such file or directory" in LANE_INFRA_FINGERPRINTS
               and "skipping profile bundle" in LANE_INFRA_FINGERPRINTS,
               LANE_INFRA_FINGERPRINTS)
        _check(checks, "zero-rounds-still-infra",
               classify_lane_failure({"rounds": 0}) == "infra"
               and classify_lane_failure(
                   {"rounds": 5, "error": "business fail"}) == "judgment",
               "")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return _result("regression-protections-dispatch-lanes", checks,
                   "dispatch 族 DNS 连通预检排除不扩、维护车道预检行为不变、"
                   "合法回落语义与 infra 指纹保持")


def _result(sid, checks, summary):
    return {
        "scenario": sid,
        "pass": all(c["pass"] for c in checks),
        "summary": summary,
        "checks": checks,
    }


SCENARIOS = {
    "probe-fallback-credential-verdicts": s1_probe_fallback_credential_verdicts,
    "fallback-first-dispatch-frozen": s2_fallback_first_dispatch_frozen,
    "explicit-chain-and-legal-fallback-pass": s3_explicit_chain_and_legal_fallback,
    "thaw-hot-reload-and-allow-key": s4_thaw_hot_reload_and_allow_key,
    "direct-lane-version-gate-blocks": s5_direct_lane_version_gate,
    "regression-protections-dispatch-lanes": s6_regression_protections_dispatch_lanes,
}


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = SCENARIOS.get(sid)
    if fn is None:
        print(json.dumps({"scenario": sid, "pass": False,
                          "summary": f"未知场景 id: {sid}", "checks": []},
                         ensure_ascii=False))
        return 1
    result = fn()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
