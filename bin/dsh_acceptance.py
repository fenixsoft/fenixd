#!/usr/bin/env python3
"""bin/dsh_acceptance.py — dsh 通道一键验收脚本（dsh-primary-acceptance-switch）。

三模式（spec「一键验收脚本」）：

- ``fixture``：生成玩具项目夹具（临时目录 + 最小 SPEC 种子 + 唯一前缀），
  打印 manifest 后默认即弃（``--keep`` 保留供人工排查）。
- ``smoke``：假端点全链冒烟——DSH_HOME 隔离（同 SPEC-3 冒烟 7.1 装置）+
  dsh-bundle/tests/fixtures/mock-model-server.mjs 假模型端点，无凭据可重复，
  覆盖 ≥3 车道（implementer / verifier / 监督 judge，judge 经 harness.
  run_one_shot）。证据只收既有机制产物：run jsonl、SPEC-3 投影可观测性
  计数（含坏事件分类）、``.fenix-run-result.json`` 硬门（result gate
  selfcheck 同源）、run_metrics 耗时指标。
- ``accept``：真实全链验收——执行前自检凭据/健康检查并输出 dry-run 计划；
  缺项时列出缺失项与修复指引且**不发起任何真实模型调用**。真实执行必须
  显式 ``--go``（人工触发，信号式交付：agent 只预演，用户发起，见
  .fenix/todo.md 队列）。

证据判定 **fail-loud**：任一车道任一检查不过 → 汇总失败明细、退出码 1，
MUST NOT 产出「假绿」报告。夹具与 runs 产物在 finally 清理（唯一前缀识
别），并对真实项目注册表与 ~/.dsh 做零残留核对。

设计决策锚点（spec/changes/dsh-primary-acceptance-switch/design.md）：
决策 1（既有机制产物为唯一真相源，脚本只收集比对）、决策 2（真实验收信
号式交付）、决策 4（验收发现的缺陷回归本 SPEC 修复）、决策 5（玩具夹具
即测即弃）。

用法::

    python3 bin/dsh_acceptance.py fixture [--keep]
    python3 bin/dsh_acceptance.py smoke [--lanes impl,verify,judge]
                                        [--evidence-dir DIR] [--timeout S]
                                        [--baseline-json FILE] [--keep]
    python3 bin/dsh_acceptance.py accept [--go] [--project-root DIR]
                                         [--model M] [--evidence-dir DIR]
                                         [--no-claude-baseline]

退出码：0=全绿；1=验收失败（fail-loud，证据文件内含失败明细）；2=用法/
装置错误。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    # 以仓库根为 import 锚点（脚本从任意 CWD 可执行）
    sys.path.insert(0, str(REPO_ROOT))

BUNDLE = REPO_ROOT / "dsh-bundle"
MOCK_SERVER = BUNDLE / "tests" / "fixtures" / "mock-model-server.mjs"

#: 证据默认落点（仓库内 .fenix 运行时目录，已 gitignore；stray-first-sight）
DEFAULT_EVIDENCE_DIR = REPO_ROOT / ".fenix" / "verify-evidence" / \
    "dsh-primary-acceptance-switch"

#: 夹具唯一前缀词干（清理与零残留核对的识别锚点）
FIXTURE_STEM = "dshacc"

#: smoke 假端点模型名（patch 渲染值；假模型端点请求日志对账用）
MOCK_MODEL = "mock-model"

#: smoke 车道词表（任务 2.1：≥3 车道；judge = 监督 judge，经 run_one_shot）
SMOKE_LANES: Tuple[str, ...] = ("implementer", "verifier", "judge")

#: 监督 judge 的裁决词表（与 core.agent_runner.liveness 判定提示词同口径）
JUDGE_VERDICTS = ("advancing", "stagnant")

#: 单车道期望超时（秒）——smoke 缺省；超时按 fail-loud 计失败，不静默豁免
DEFAULT_LANE_TIMEOUT = 300.0


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def unique_prefix() -> str:
    """夹具唯一前缀（秒级时间戳 + 6 位随机），清理与残留核对凭它识别。"""
    return f"{FIXTURE_STEM}-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


def redact(value: str, keep: int = 4) -> str:
    """凭据脱敏（只露尾 4 位；空值原样）。"""
    if not value:
        return ""
    return f"***{value[-keep:]}" if len(value) > keep else "***"


# ══════════════════════════════════════════════════════════════════════
# 玩具项目夹具（决策 5：即测即弃，不污染真实项目注册表）
# ══════════════════════════════════════════════════════════════════════

def build_fixture(parent: Path, prefix: str) -> Dict[str, Any]:
    """生成玩具项目夹具：临时项目根（含 .fenix/runs）+ 玩具 worktree（最小
    SPEC 种子：impl/verify 两个 spec 各一份全勾 tasks.md，供 result gate
    tasks.md 对账）。

    返回 manifest dict（含全部路径与前缀）。不写任何注册表——runner 在进
    程内以 project_root=玩具根构造，隔离由构造保证。
    """
    project_root = parent / f"proj-{prefix}"
    worktree = parent / f"wt-{prefix}"
    (project_root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    worktree.mkdir(parents=True, exist_ok=True)
    impl_spec = f"{prefix}-impl"
    verify_spec = f"{prefix}-verify"
    for spec in (impl_spec, verify_spec):
        spec_dir = worktree / "spec" / "changes" / spec
        spec_dir.mkdir(parents=True)
        (spec_dir / "proposal.md").write_text(
            f"# {spec}\n\ndsh 验收冒烟夹具 SPEC（玩具，勿当真实变更）。\n",
            encoding="utf-8")
        # 全勾 tasks.md：result gate 的 completed_tasks↔tasks.md 对账对象
        #（同 SPEC-3 e2e 冒烟装置；勾选纪律约束的是真实 run，夹具种子是
        # 硬门机制的判定输入）。
        (spec_dir / "tasks.md").write_text(
            f"# Tasks\n\n- [x] 1.1 dsh 验收冒烟（{spec}）\n", encoding="utf-8")
    return {
        "prefix": prefix,
        "parent": str(parent),
        "project_root": str(project_root),
        "worktree": str(worktree),
        "runs_dir": str(project_root / ".fenix" / "runs"),
        "impl_spec": impl_spec,
        "verify_spec": verify_spec,
    }


def cleanup_fixture(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """清理夹具（项目根 + worktree + 空掉的父目录），返回清理回执。"""
    removed = []
    for key in ("project_root", "worktree"):
        path = Path(manifest[key])
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            removed.append(manifest[key])
    parent = Path(manifest["parent"])
    parent_removed = False
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent_removed = True
    except OSError:
        pass
    return {
        "removed": removed,
        "parent_removed": parent_removed,
        "residue_free": all(not Path(p).exists() for p in removed),
    }


# ══════════════════════════════════════════════════════════════════════
# 装置：假模型端点 + DSH_HOME 隔离（装置与 SPEC-3 e2e 冒烟 7.1 同源）
# ══════════════════════════════════════════════════════════════════════

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class MockModelServer:
    """dsh-bundle 假模型端点封装（SPEC-2 交付的 mock-model-server.mjs）。

    每车道独立实例（独立端口/步骤脚本/请求日志），杜绝跨车道步骤游标竞态。
    """

    def __init__(self, steps: List[Dict[str, Any]], workdir: Path):
        if not MOCK_SERVER.is_file():
            raise RuntimeError(
                f"假模型端点脚本缺失：{MOCK_SERVER}——SPEC-2 dsh-bundle 交付物"
                f"不在场，无法装置假端点冒烟")
        self.steps = steps
        self.workdir = workdir
        self.proc: Optional[subprocess.Popen] = None
        self.port = 0
        self.steps_file = workdir / "mock-steps.json"
        self.log_file = workdir / "mock-requests.jsonl"

    def __enter__(self) -> "MockModelServer":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def start(self) -> None:
        if shutil.which("node") is None:
            raise RuntimeError(
                "node 不在 PATH：假模型端点（mock-model-server.mjs）依赖 "
                "node 运行——请安装 node.js 后重试")
        self.port = _free_port()
        # 步骤脚本启动前落盘（服务器启动时一次性加载，启动后改写不生效）
        self.steps_file.write_text(
            json.dumps(self.steps, ensure_ascii=False), encoding="utf-8")
        self.proc = subprocess.Popen(
            ["node", str(MOCK_SERVER), "--port", str(self.port),
             "--script", str(self.steps_file), "--log", str(self.log_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection(
                        ("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                if self.proc.poll() is not None:
                    raise RuntimeError("mock-model-server 提前退出")
                time.sleep(0.1)
        self.stop()
        raise RuntimeError("mock-model-server 端口就绪超时")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc = None

    def requests(self) -> List[Dict[str, Any]]:
        if not self.log_file.is_file():
            return []
        out = []
        for line in self.log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"


def ensure_bundle_dist() -> None:
    """Bundle 构建产物保障：dist 缺失时就地 ``npm run build``（幂等环境预
    置；gitignored 构建产物在全新 checkout/worktree 缺席是常态）。构建失败
    仍 fail-loud，不带病挂载（缺 dist 时插件 failed to import）。"""
    if (BUNDLE / "dist" / "index.js").is_file():
        return
    if shutil.which("npm") is None:
        raise RuntimeError(
            f"dsh-bundle 缺构建产物（{BUNDLE / 'dist' / 'index.js'} 不存在）"
            f"且 npm 不在 PATH：请在 dsh-bundle/ 下 npm ci && npm run build")
    try:
        subprocess.run(["npm", "run", "build"], cwd=str(BUNDLE),
                       capture_output=True, text=True, timeout=300,
                       check=True)
    except (subprocess.SubprocessError, OSError) as e:
        raise RuntimeError(
            f"dsh-bundle 构建失败（{e}）：请在 dsh-bundle/ 下手工执行 "
            f"npm ci && npm run build 后重试") from e


def prepare_dsh_home(profile: str = "fenix",
                     workdir: Optional[Path] = None) -> Dict[str, Any]:
    """DSH_HOME 隔离装置（与 tests/test_dsh_e2e_smoke.py dsh_home 夹具同源）：
    temp home + ``dsh plugin --profile <p> add link:<repo>/dsh-bundle``，
    plugin add 不可用时手工装配 profile 清单。就绪性由 adapter.check_health
    终判（调用方执行）。

    bundles 清单必须显式含 ``@deepseek-ai/dsh-headless``：全新 home 的
    ``plugin add`` 只登记 ``@deepseek-ai/dsh-base``，缺 headless bundle 时
    headless 命令静默永等（实测 hang 根因，2026-10-13）。
    """
    if shutil.which("dsh") is None:
        raise RuntimeError(
            "dsh 不在 PATH：请安装（npm install -g @deepseek-ai/dsh，见 "
            "dsh-bundle/README.md 部署段），或将 agent.harness 改回 claude")
    ensure_bundle_dist()
    home = Path(tempfile.mkdtemp(prefix="dshacc-home-", dir=str(workdir) if
                                 workdir else None))
    env = dict(os.environ, DSH_HOME=str(home))
    try:
        added = subprocess.run(
            ["dsh", "plugin", "--profile", profile, "add", f"link:{BUNDLE}"],
            env=env, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        shutil.rmtree(home, ignore_errors=True)
        raise RuntimeError(f"dsh plugin add 失败（{e}）——DSH_HOME 隔离装置"
                           f"不可用") from e
    pkg = home / "profiles" / profile / "package.json"
    data: Dict[str, Any] = {}
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    bundles = (data.setdefault("dsh", {}).setdefault("profile", {})
               .setdefault("bundles", []))
    for required in ("@deepseek-ai/dsh-headless", "fenix-dsh-bundle"):
        if required not in bundles:
            bundles.append(required)
    pkg.parent.mkdir(parents=True, exist_ok=True)
    pkg.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    device: Dict[str, Any] = {"home": str(home), "profile": profile}
    if added.returncode != 0:
        # plugin add 失败不静默滑入手工装配分支：原始失败原因留痕（供证据
        # 与报告引用；就绪性仍由调用方 check_health 终判）
        device["plugin_add_fallback"] = {
            "returncode": added.returncode,
            "stderr_head": (added.stderr or added.stdout or "").strip()[:300]}
    return device


def dispose_dsh_home(device: Dict[str, Any]) -> None:
    shutil.rmtree(device["home"], ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════
# 证据采集：结构化日志捕获 + 最小 runner 装配
# ══════════════════════════════════════════════════════════════════════

class EvidenceLogger:
    """结构化日志捕获（run_metrics 落盘读侧同形状：info(component, message,
    context)）。warning/error 同样入册——fail-loud 的诊断素材。"""

    def __init__(self) -> None:
        self.infos: List[Dict[str, Any]] = []
        self.problems: List[str] = []

    def debug(self, *a, **k) -> None:
        pass

    def info(self, component, message, context=None) -> None:
        self.infos.append({"component": component, "message": str(message),
                           "context": context or {}})

    def warning(self, component, message, context=None) -> None:
        self.problems.append(f"[warn] {component}: {message}")

    def error(self, component, message, context=None) -> None:
        self.problems.append(f"[error] {component}: {message}")

    def run_metrics_entries(self) -> List[Dict[str, Any]]:
        return [i["context"] for i in self.infos
                if i["context"].get("metric_type") == "run_metrics"]

    def projections(self) -> List[Dict[str, Any]]:
        return [c["projection"] for c in self.run_metrics_entries()
                if "projection" in c]


def build_runner(project_root: Path, logger: EvidenceLogger,
                 lane_timeout: float):
    """最小 AgentRunner 装配（与 tests/helpers.make_runner 同一形状：绕过
    真实 __init__ 的 worktree/state_machine 依赖；进程内驱动 _run_agent 全
    链——构造方式是测试装置既定形态，非桩：spawn/读环/投影/收口全真）。
    """
    from core.agent_runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner.config = {"agents": {"run_timeout_seconds": int(lane_timeout)}}
    runner.worktree_manager = None
    runner.state_machine = None
    runner.project_root = Path(project_root)
    runner.logger = logger
    runner._running_agents = {}
    runner._daily_run_count = 0
    runner._provider_circuit._daily_reset_date = None
    runner._provider_circuit._daily_provider_attempts = {}
    runner._provider_circuit._daily_provider_warned = {}
    runner._provider_circuit.provider_circuits = {}
    return runner


def _proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(
            "utf-8", "replace")
    except OSError:
        return ""


def reap_lane_processes(runner) -> None:
    """车道挂起兜底：SIGTERM→SIGKILL 两段式收割在飞进程组（与 harness.
    one_shot 清场语义同构；spawn 以 start_new_session 启动，pgid==pid）。"""
    for proc in list(getattr(runner, "_running_agents", {}).values()):
        if proc.poll() is not None:
            continue
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                break
            try:
                proc.wait(timeout=5)
                break
            except subprocess.TimeoutExpired:
                continue


def _read_jsonl_entries(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """jsonl 逐行容错解析（与 _last_jsonl_type 同口径）：坏行/非 dict 行跳过
    并计数，不抛异常——证据解析失败不放大成装置失败。返回 (entries, 坏行数)。"""
    entries: List[Dict[str, Any]] = []
    bad_lines = 0
    if not path.is_file():
        return entries, bad_lines
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            bad_lines += 1
            continue
        if isinstance(payload, dict):
            entries.append(payload)
    return entries, bad_lines


# ══════════════════════════════════════════════════════════════════════
# 车道驱动（≥3 车道假端点全链；各车道终态/在飞判定/产物硬门）
# ══════════════════════════════════════════════════════════════════════

def result_file_payload(spec: str, summary: str) -> Dict[str, Any]:
    """夹具车道结果文件载荷（与 tasks.md 全勾种子对账；result gate 同源
    selfcheck 判定对象）。"""
    return {"status": "success", "spec": spec, "summary": summary,
            "completed_tasks": ["1.1"]}


def lane_prompt(lane: str, fixture: Dict[str, Any],
                real: bool = False) -> str:
    """车道提示词（smoke 夹具与真实模式分形：smoke 由假端点编排工具调用，
    真实模式给真实任务语义）。"""
    spec = fixture["impl_spec"] if lane == "implementer" else \
        fixture["verify_spec"]
    result_path = Path(fixture["worktree"]) / ".fenix-run-result.json"
    if real:
        if lane == "implementer":
            return (f"实现 {spec}：完成 tasks.md 1.1（在 {fixture['worktree']} "
                    f"下创建 hello.txt 内容 dsh-ok），完成后把结果 JSON 写入 "
                    f"{result_path}（status=success, spec={spec}, "
                    f"completed_tasks=[\"1.1\"]）")
        report_path = (Path(fixture["worktree"]) / "spec" / "changes" / spec /
                       "verification-report.md")
        return (f"验证 {spec}：核对 hello.txt 存在且内容为 dsh-ok，把验证"
                f"报告写入 {report_path}，并把结果 JSON 写入 {result_path}"
                f"（status=success, spec={spec}, completed_tasks=[\"1.1\"]）")
    if lane == "implementer":
        return f"实现 {spec} 并把结果写入 {result_path}"
    report_path = (Path(fixture["worktree"]) / "spec" / "changes" / spec /
                   "verification-report.md")
    return (f"验证 {spec}：把验证报告写入 {report_path}，"
            f"并把结果写入 {result_path}")


def lane_steps(lane: str, fixture: Dict[str, Any],
               real: bool = False) -> List[Dict[str, Any]]:
    """车道假端点步骤编排（smoke 专用；real 模式无假端点不编排）。"""
    spec = fixture["impl_spec"] if lane == "implementer" else \
        fixture["verify_spec"]
    result_path = Path(fixture["worktree"]) / ".fenix-run-result.json"
    if real:
        return []
    if lane == "judge":
        return judge_lane_steps()
    if lane == "implementer":
        return impl_lane_steps(result_path, spec)
    report_path = (Path(fixture["worktree"]) / "spec" / "changes" / spec /
                   "verification-report.md")
    return verify_lane_steps(result_path, report_path, spec)


def impl_lane_steps(result_path: Path, spec: str) -> List[Dict[str, Any]]:
    """implementer 车道假端点步骤编排：TaskCreate（双步防会话标题竞态，
    任一消费者抢到首步主链都确定拿到 TC）→ write 结果文件 → 终文本收口。"""
    payload = result_file_payload(spec, "dsmoke 实现 lane 完成")
    return [
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: dsh 验收冒烟",
                           "description": "implementer lane"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: dsh 验收冒烟（备步）",
                           "description": "implementer lane"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "write",
             "arguments": {"file_path": str(result_path),
                           "content": json.dumps(payload, ensure_ascii=False,
                                                 indent=2)}}]},
        {"kind": "text", "text": "实现冒烟完成"},
    ]


def verify_lane_steps(result_path: Path, report_path: Path,
                      spec: str) -> List[Dict[str, Any]]:
    """verifier 车道：TaskCreate（双步）→ write 验证报告 → write 结果文件
    → 终文本收口。"""
    payload = result_file_payload(spec, "dsmoke 验证 lane 完成")
    report = (f"# 验证报告 — {spec}\n\n| 场景 | 判定 | 失败数 |\n"
              f"|---|---|---|\n| dsh-acceptance-smoke | pass | 0/1 |\n")
    return [
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: dsh 验收冒烟",
                           "description": "verifier lane"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: dsh 验收冒烟（备步）",
                           "description": "verifier lane"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "write",
             "arguments": {"file_path": str(report_path), "content": report}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "write",
             "arguments": {"file_path": str(result_path),
                           "content": json.dumps(payload, ensure_ascii=False,
                                                 indent=2)}}]},
        {"kind": "text", "text": "验证冒烟完成"},
    ]


def judge_prompt() -> str:
    """监督 judge 提示词（与 core.agent_runner.liveness 判定提示词同形）。"""
    return (
        "你是监督 judge。根据以下 run 快照判定活性：\n"
        "快照：run impl-dshacc 正在推进，最近 3 分钟有 tool_use 事件。\n"
        '输出一行 JSON：{"verdict": "advancing|stagnant", '
        '"evidence": "简短判定依据（<=200字）"}\n'
    )


def judge_lane_steps() -> List[Dict[str, Any]]:
    """judge 车道假端点步骤：裁决文本双步（防标题请求竞态）+ loop 兜底。"""
    verdict = json.dumps({"verdict": "advancing",
                          "evidence": "dsmoke: 最近事件为 tool_use，活性推进"},
                         ensure_ascii=False)
    return [{"kind": "text", "text": verdict},
            {"kind": "text", "text": verdict}]


def run_agent_lane(*, lane: str, device: Dict[str, Any], fixture: Dict[str, Any],
                   mock: MockModelServer, timeout: float) -> Dict[str, Any]:
    """implementer/verifier 车道：经 AgentRunner._run_agent 的全链驱动
    （dispatch 面 adapter 装配 + 健康门 → 真实 dsh spawn → 在飞判定 → 终态
    收口 → 产物硬门）。证据只取既有机制产物。"""
    from core.agent_runner.harness import (
        resolve_adapter, set_current_adapter, get_current_adapter,
    )

    spec = fixture["impl_spec"] if lane == "implementer" else \
        fixture["verify_spec"]
    run_id = f"{'impl' if lane == 'implementer' else 'verify'}-{spec}-a1"
    result_path = Path(fixture["worktree"]) / ".fenix-run-result.json"
    report_path = (Path(fixture["worktree"]) / "spec" / "changes" / spec /
                   "verification-report.md")
    runs_dir = Path(fixture["runs_dir"])

    adapter = resolve_adapter("dsh", {"agent": {
        "harness": "dsh", "dsh_home": device["home"],
        "dsh_profile": device["profile"]}})
    adapter.check_health()  # 版本白名单 + Bundle 挂载探测（不满足 fail-fast）

    prompt = lane_prompt(lane, fixture)
    logger = EvidenceLogger()
    runner = build_runner(Path(fixture["project_root"]), logger, timeout)

    box: Dict[str, Any] = {}

    def _drive() -> None:
        try:
            box["ret"] = runner._run_agent(
                prompt, Path(fixture["worktree"]), run_id,
                model_override=MOCK_MODEL,
                env_overrides={
                    "ANTHROPIC_BASE_URL": mock.base_url,
                    "ANTHROPIC_API_KEY": "sk-mock",
                    "ANTHROPIC_MODEL": MOCK_MODEL,
                },
                spec_name=spec, agent_type=lane)
        except Exception as e:  # noqa: BLE001 — 失败形态原样带回判定面
            box["err"] = e

    prev = set_current_adapter(adapter)
    started = time.perf_counter()
    try:
        th = threading.Thread(target=_drive, daemon=True)
        th.start()
        # 在飞判定：Popen 登记在场且子进程 cmdline 是真实 dsh headless
        #（完成 ⇒ 在飞窗口存在过，终态先于观测窗到达同样算观测过）
        inflight_seen = False
        sampled: List[str] = []
        deadline = time.time() + 30
        while time.time() < deadline and "ret" not in box and "err" not in box:
            for proc in list(runner._running_agents.values()):
                if proc.poll() is not None:
                    continue
                cmdline = _proc_cmdline(proc.pid)
                if cmdline and (not sampled or sampled[-1] != cmdline):
                    sampled.append(cmdline)
                if "dsh" in cmdline and "--profile" in cmdline:
                    inflight_seen = True
            # 观测到在飞后仍保留固定采样间隔：满速热自旋空耗 CPU，且与被
            # 观测的 dsh 子进程争抢，反过来拉长被测车道耗时（elapsed_seconds
            # 是基线对比输入）
            time.sleep(0.2 if inflight_seen else 0.1)
        th.join(timeout=timeout + 60)
    finally:
        set_current_adapter(prev)
    if th.is_alive() and "ret" not in box and "err" not in box:
        # 驱动线程超时未归：收割在飞进程组（fail-loud，不静默挂起）
        reap_lane_processes(runner)
        box["err"] = RuntimeError(
            f"车道驱动线程 {timeout + 60}s 未归（run_timeout_seconds="
            f"{int(timeout)} 强制未生效？）——已收割在飞进程组")
    elapsed = time.perf_counter() - started

    ev: Dict[str, Any] = {
        "lane": lane, "run_id": run_id, "spec": spec,
        "elapsed_seconds": round(elapsed, 3),
        "inflight_observed": inflight_seen,
        "inflight_cmdline_sample": sampled[:1],
    }
    if "err" in box:
        ev["error"] = repr(box["err"])
        ev["problems"] = logger.problems[:5]
        return ev

    output, turns, session_id, usage = box.get("ret") or ("", 0, None, {})
    ev.update({
        "output": output, "turns": turns, "session_id": session_id,
        "usage_source": usage.get("usage_source"),
        "usage": {k: usage.get(k) for k in
                  ("input_tokens", "output_tokens", "cost_usd")},
        "problems": logger.problems[:5],
    })

    # ── 证据 1：run jsonl（既有机制产物；逐行容错，坏行跳过+计数）──
    run_file = runs_dir / f"{run_id}.jsonl"
    ev["run_jsonl_path"] = str(run_file)
    entries, ev["run_jsonl_bad_lines"] = _read_jsonl_entries(run_file)
    ev["run_jsonl_first"] = {"type": entries[0].get("type"),
                             "harness": entries[0].get("harness")} \
        if entries else None
    ev["run_jsonl_last_type"] = entries[-1].get("type") if entries else None
    ev["tool_use_names"] = sorted({
        blk.get("name") for e in entries if e.get("type") == "assistant"
        for blk in ((e.get("message") or {}).get("content") or [])
        if isinstance(blk, dict) and blk.get("type") == "tool_use"})

    # ── 证据 2：投影可观测性（run_metrics 结构化日志：逐级计数+坏事件）──
    projs = logger.projections()
    ev["projection"] = projs[-1] if projs else None

    # ── 证据 3：原始 dsh 事件 dump 旁路 ─────────────────────────────
    dump = runs_dir / f"{run_id}.dsh-events.jsonl"
    ev["raw_dump_path"] = str(dump)
    ev["raw_dump_exists"] = dump.is_file()
    if dump.is_file():
        dump_entries, _ = _read_jsonl_entries(dump)
        ev["raw_dump_first_type"] = dump_entries[0].get("type") \
            if dump_entries else None
    else:
        ev["raw_dump_first_type"] = None

    # ── 证据 4：产物硬门（result gate selfcheck 同源）────────────────
    ev["result_file_path"] = str(result_path)
    ev["result_gate"] = result_gate_selfcheck(result_path)
    ev["verification_report_written"] = (
        report_path.is_file() if lane == "verifier" else None)

    # ── 证据 5：run_metrics 耗时（既有机制产物，非脚本自测秒表单源）──
    metrics = [c for c in logger.run_metrics_entries()
               if c.get("run_id") == run_id or c.get("spec") == spec]
    ev["run_metrics"] = metrics[-1] if metrics else None

    # ── 假端点交互对账：请求到达 + model 名即 patch 渲染值 ───────────
    reqs = mock.requests()
    ev["mock_requests"] = len(reqs)
    ev["mock_model_seen"] = reqs[0].get("model") if reqs else None
    ev["mock_tools_contain_taskcreate"] = any(
        "TaskCreate" in (req.get("tools") or []) for req in reqs)
    return ev


def run_judge_lane(*, device: Dict[str, Any], fixture: Dict[str, Any],
                   mock: MockModelServer, timeout: float) -> Dict[str, Any]:
    """监督 judge 车道：经 harness.run_one_shot（claude 通道 judge 通道的
    dsh 同构——adapter 只换不分支）。dsh stdout 为 NDJSON 事件流，终文本取
    final 事件 text（claude 的整体 JSON payload 形态同样兼容解析）。
    """
    from core.agent_runner.harness import resolve_adapter
    from core.agent_runner.harness.one_shot import run_one_shot
    from core.agent_runner.harness.protocol import (
        ENV_MODE_CLEAN, SpawnRequest,
    )

    adapter = resolve_adapter("dsh", {"agent": {
        "harness": "dsh", "dsh_home": device["home"],
        "dsh_profile": device["profile"]}})

    inflight: Dict[str, Any] = {"observed": False, "cmdline": ""}

    def _on_spawn(proc) -> None:
        cmdline = _proc_cmdline(proc.pid)
        inflight["cmdline"] = cmdline
        if "dsh" in cmdline and "--profile" in cmdline:
            inflight["observed"] = True

    request = SpawnRequest(
        judge_prompt(),
        cwd=str(fixture["worktree"]),
        output_format="json",
        model=MOCK_MODEL,
        env_mode=ENV_MODE_CLEAN,
        env_overrides={
            "ANTHROPIC_BASE_URL": mock.base_url,
            "ANTHROPIC_API_KEY": "sk-mock",
        },
    )
    started = time.perf_counter()
    err: Optional[BaseException] = None
    result = None
    try:
        result = run_one_shot(adapter, request, timeout=timeout,
                              on_spawn=_on_spawn)
    except Exception as e:  # noqa: BLE001
        err = e
    elapsed = time.perf_counter() - started

    ev: Dict[str, Any] = {
        "lane": "judge", "run_id": "judge-one-shot",
        "elapsed_seconds": round(elapsed, 3),
        "inflight_observed": inflight["observed"],
        "inflight_cmdline_sample": inflight["cmdline"][:1],
    }
    if err is not None:
        ev["error"] = repr(err)
        return ev
    stdout = result.stdout or ""
    ev["returncode"] = result.returncode
    ev["timed_out"] = result.timed_out
    ev["final_text"], ev["stream_error"] = _parse_dsh_one_shot_stream(stdout)
    ev["verdict"] = _parse_verdict(ev["final_text"])
    ev["stderr_head"] = (result.stderr or "")[:300]
    reqs = mock.requests()
    ev["mock_requests"] = len(reqs)
    ev["mock_model_seen"] = reqs[0].get("model") if reqs else None
    return ev


def _parse_dsh_one_shot_stream(stdout: str) -> Tuple[str, Optional[str]]:
    """judge 通道 stdout 解析：NDJSON 事件流取 final.text；error 事件回传
    供 fail-loud；整体 JSON（claude 形态 {"result": ...}) 同样兼容。"""
    text = stdout.strip()
    if not text:
        return "", "stdout 为空（无任何事件）"
    if text.lstrip().startswith("{") and '"type"' not in text.splitlines()[0]:
        try:
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("result"):
                return str(payload["result"]), None
        except json.JSONDecodeError:
            pass
    final_text = ""
    stream_error: Optional[str] = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "final":
            final_text = entry.get("text") or ""
        elif entry.get("type") == "error":
            stream_error = str(entry.get("message") or entry)
    if not final_text and stream_error is None:
        stream_error = "事件流中无 final/error 终态"
    return final_text, stream_error


def _balanced_json_object(text: str) -> Optional[str]:
    """括号配对扫描：提取 text 中首个括号平衡的 JSON 对象片段（字符串字面量
    内的引号/转义不参与配对）。栅栏包裹、嵌套对象、前后混杂文本均容忍——
    非贪婪正则遇嵌套对象会在首个 ``}`` 截出括号不平衡的片段，配对扫描不受
    影响。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _parse_verdict(text: str) -> Optional[Dict[str, Any]]:
    """裁决 JSON 提取（容忍代码栅栏包裹与嵌套对象；词表对齐 liveness 判定）。"""
    if not text:
        return None
    candidates = [text.strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    balanced = _balanced_json_object(text)
    if balanced and balanced not in candidates:
        candidates.insert(0, balanced)
    for cand in candidates:
        try:
            payload = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("verdict"):
            return {"verdict": str(payload["verdict"]),
                    "evidence": str(payload.get("evidence") or "")}
    return None


def result_gate_selfcheck(result_path: Path) -> Dict[str, Any]:
    """产物硬门：result gate selfcheck（与 daemon 收工硬门同源校验函数）。"""
    if not result_path.is_file():
        return {"exit_code": None, "passed": False,
                "detail": f"结果文件缺失：{result_path}"}
    try:
        chk = subprocess.run(
            [sys.executable, "-m", "core.agent_runner.result_gate",
             "--selfcheck", str(result_path)],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        # 硬门子进程挂起按该车道硬门未过计入 failures，不放大成装置失败
        # 中止整轮验收
        return {"exit_code": None, "passed": False,
                "detail": "result gate selfcheck 超时（120s）"}
    return {
        "exit_code": chk.returncode,
        "passed": chk.returncode == 0,
        "detail": (chk.stderr or chk.stdout or "").strip()[:500],
    }


# ══════════════════════════════════════════════════════════════════════
# 证据判定（纯函数，fail-loud）
# ══════════════════════════════════════════════════════════════════════

def evaluate_agent_lane(ev: Dict[str, Any], real: bool = False) -> List[str]:
    """implementer/verifier 车道判定：返回失败明细（空 = 全过）。

    real=True（accept --go 真实车道）：真实模型终文本与工具面不受假端点
    步骤编排约束，去掉 smoke 专属判据（固定终文本 / TaskCreate 工具面 /
    假端点请求对账），只保留终文本非空下限；既有机制产物判据两模式同口径
    （真实车道由 _real_agent_lane 补采同形状证据）。
    """
    failures: List[str] = []
    if ev.get("error"):
        failures.append(f"车道异常：{ev['error']}")
        return failures
    if real:
        if not str(ev.get("output") or "").strip():
            failures.append("终态 output 为空（真实车道模型无终文本）")
    else:
        expect_text = ("实现冒烟完成" if ev["lane"] == "implementer"
                       else "验证冒烟完成")
        if ev.get("output") != expect_text:
            failures.append(
                f"终态 output={ev.get('output')!r}（期望 {expect_text!r}）")
    if not ev.get("session_id"):
        failures.append("session_id 缺失（session 事件未投影）")
    if not (ev.get("turns") or 0) >= 1:
        failures.append(f"num_turns={ev.get('turns')}（期望 ≥1）")
    if ev.get("usage_source") != "available":
        failures.append(f"usage_source={ev.get('usage_source')}（期望 available）")
    usage = ev.get("usage") or {}
    if not usage.get("input_tokens") or not usage.get("output_tokens"):
        failures.append(f"usage 数值异常：{usage}")
    if not ev.get("inflight_observed"):
        failures.append("未观测到在飞 dsh headless 进程（在飞判定失效）")
    rj = ev.get("run_jsonl_first")
    if not rj or rj.get("type") != "system" or rj.get("harness") != "dsh":
        failures.append(f"run jsonl 首行异常：{rj}")
    if ev.get("run_jsonl_last_type") != "result":
        failures.append(f"run jsonl 末行非 result 终态：{ev.get('run_jsonl_last_type')}")
    if not real and "TaskCreate" not in (ev.get("tool_use_names") or []):
        failures.append(
            f"Bundle Task 工具族未投影（tool_use={ev.get('tool_use_names')}）")
    proj = ev.get("projection")
    if not proj:
        failures.append("run_metrics 缺 projection 计数（可观测性三件套缺失）")
    else:
        if proj.get("harness") != "dsh":
            failures.append(f"projection.harness={proj.get('harness')}")
        received = proj.get("events_received") or {}
        if not received.get("final", 0) >= 1:
            failures.append(f"projection.events_received.final<1：{received}")
        bad = proj.get("bad_events") or {}
        if any(v for v in bad.values()):
            failures.append(f"坏事件计数非零：{bad}")
    if not ev.get("raw_dump_exists"):
        failures.append("原始 dsh 事件 dump 旁路文件缺失")
    elif ev.get("raw_dump_first_type") != "session":
        failures.append(f"dump 首行非 session：{ev.get('raw_dump_first_type')}")
    gate = ev.get("result_gate") or {}
    if not gate.get("passed"):
        failures.append(f"产物硬门 selfcheck 未过：{gate.get('detail')}")
    if ev["lane"] == "verifier" and not ev.get("verification_report_written"):
        failures.append("verifier 车道验证报告未落盘")
    if real:
        return failures
    if not ev.get("mock_requests"):
        failures.append("假模型端点零请求（交互未发生）")
    elif ev.get("mock_model_seen") != MOCK_MODEL:
        failures.append(
            f"假端点收到的 model={ev.get('mock_model_seen')}（期望 "
            f"{MOCK_MODEL}，patch 渲染未达传输层）")
    if ev.get("mock_requests") and not ev.get("mock_tools_contain_taskcreate") \
            and ev["lane"] != "judge":
        failures.append("请求工具面未含 TaskCreate（Bundle 工具注册缺失）")
    return failures


def evaluate_judge_lane(ev: Dict[str, Any], real: bool = False) -> List[str]:
    """监督 judge 车道判定：run_one_shot 终态 + 在飞 + 裁决可解析。

    real=True 时去掉 smoke 专属的假端点请求对账（真实车道无假端点）。
    """
    failures: List[str] = []
    if ev.get("error"):
        failures.append(f"judge 车道异常：{ev['error']}")
        return failures
    if ev.get("timed_out"):
        failures.append("judge 车道超时收割（timed_out=True）")
    if ev.get("returncode") != 0:
        failures.append(f"judge 退出码={ev.get('returncode')}（期望 0）；"
                        f"stderr={ev.get('stderr_head')!r}")
    if not ev.get("inflight_observed"):
        failures.append("未观测到在飞 judge dsh 进程")
    if ev.get("stream_error"):
        failures.append(f"事件流异常：{ev['stream_error']}")
    verdict = ev.get("verdict")
    if not verdict:
        failures.append(f"裁决不可解析：final_text={ev.get('final_text')!r}")
    elif verdict.get("verdict") not in JUDGE_VERDICTS:
        failures.append(f"裁决词表外：{verdict.get('verdict')!r}")
    elif not verdict.get("evidence"):
        failures.append("裁决 evidence 为空")
    if not real and not ev.get("mock_requests"):
        failures.append("假模型端点零请求（judge 交互未发生）")
    return failures


def evaluate_evidence(lanes: List[Dict[str, Any]],
                      real: bool = False) -> Dict[str, Any]:
    """全量判定：任一车道任一检查不过 → 整体失败（fail-loud）。real=True
    切换真实车道判定口径（见 evaluate_agent_lane / evaluate_judge_lane）。"""
    failures: Dict[str, List[str]] = {}
    for ev in lanes:
        lane = ev.get("lane", "?")
        if lane == "judge":
            lane_failures = evaluate_judge_lane(ev, real=real)
        else:
            lane_failures = evaluate_agent_lane(ev, real=real)
        if lane_failures:
            failures[lane] = lane_failures
    return {"ok": not failures, "failures": failures}


def compare_baseline(lanes: List[Dict[str, Any]],
                     baseline_path: Optional[Path]) -> Dict[str, Any]:
    """与同夹具 claude 通道基线比对（耗时；基线文件由 claude 通道同夹具
    run 的 run_metrics 产出，``--baseline-json`` 提供）。缺基线 → 显式
    unavailable（不伪造对比结论）。"""
    if baseline_path is None or not Path(baseline_path).is_file():
        return {"status": "unavailable",
                "reason": "未提供 claude 通道基线（--baseline-json）；"
                          "smoke 模式默认无基线，真实验收由 accept --go "
                          "现场采集同夹具 claude 车道"}
    try:
        baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "unavailable", "reason": f"基线文件不可读：{e}"}
    base_lanes = baseline.get("lanes") if isinstance(baseline, dict) else None
    if not isinstance(base_lanes, dict) and isinstance(baseline, dict):
        # 兼容 accept --go 产出的 rows 数组形态（{status, source, rows:
        # [{lane, claude_seconds, ...}]}；整份 accept 证据 JSON 同样可回灌，
        # 其 baseline 子对象即此形态）：就地投影成 lanes/duration_seconds，
        # 两模式基线互为 --baseline-json 输入
        rows_doc = baseline if isinstance(baseline.get("rows"), list) \
            else baseline.get("baseline")
        rows = rows_doc.get("rows") if isinstance(rows_doc, dict) else None
        if isinstance(rows, list):
            base_lanes = {
                r.get("lane"): {"duration_seconds": r.get("claude_seconds")}
                for r in rows if isinstance(r, dict) and r.get("lane")}
    if not isinstance(base_lanes, dict):
        return {"status": "unavailable", "reason": "基线文件缺 lanes 对象"}
    rows = []
    for ev in lanes:
        lane = ev.get("lane")
        base = base_lanes.get(lane)
        if not isinstance(base, dict) or not base.get("duration_seconds"):
            rows.append({"lane": lane, "dsh_seconds": ev.get("elapsed_seconds"),
                         "claude_seconds": None, "ratio": None})
            continue
        dsh_s = ev.get("elapsed_seconds") or 0
        claude_s = float(base["duration_seconds"])
        rows.append({
            "lane": lane, "dsh_seconds": dsh_s, "claude_seconds": claude_s,
            "ratio": round(dsh_s / claude_s, 3) if claude_s else None,
        })
    return {"status": "available", "source": str(baseline_path), "rows": rows}


# ══════════════════════════════════════════════════════════════════════
# 验收报告（五段证据 + 决策申请段；模板与 runbook 3.2 节同构）
# ══════════════════════════════════════════════════════════════════════

def render_report_md(evidence: Dict[str, Any]) -> str:
    """验收报告 Markdown（五段证据 + 决策申请段）——结构与
    docs/help/dsh-harness-runbook.md 报告模板节逐段同构。"""
    mode = evidence.get("meta", {}).get("mode", "?")
    lines: List[str] = []
    lines.append(f"# dsh 通道验收报告（{mode}）")
    lines.append("")
    lines.append(f"- 生成时间：{evidence.get('meta', {}).get('finished_at')}")
    fixture_cleanup = evidence.get("fixture_cleanup") or {}
    if fixture_cleanup.get("skipped"):
        fixture_note = (f"（--keep 保留："
                        f"`{evidence.get('meta', {}).get('fixture_kept', '?')}`，"
                        "需手工清理）")
    else:
        fixture_note = "（即测即弃，已清理）"
    lines.append(f"- 夹具前缀：`{evidence.get('meta', {}).get('prefix')}`"
                 f"{fixture_note}")
    lines.append(f"- 判定：**{'PASS' if evidence.get('evaluation', {}).get('ok') else 'FAIL'}**"
                 "（fail-loud：任一检查不过即 FAIL）")
    lines.append("")
    lines.append("## 一、各车道终态")
    lines.append("")
    lines.append("| 车道 | 终态 | 在飞判定 | turns | session | 耗时(s) |")
    lines.append("|---|---|---|---|---|---|")
    for ev in evidence.get("lanes", []):
        if ev.get("lane") == "judge":
            terminal = "returncode=%s" % ev.get("returncode")
            if ev.get("timed_out"):
                terminal += " (timed_out)"
            inflight = "✓" if ev.get("inflight_observed") else "✗"
            lines.append(f"| judge | {terminal} | {inflight} | - | - | "
                         f"{ev.get('elapsed_seconds')} |")
        else:
            inflight = "✓" if ev.get("inflight_observed") else "✗"
            lines.append(
                f"| {ev.get('lane')} | {ev.get('run_jsonl_last_type')} | "
                f"{inflight} | {ev.get('turns')} | "
                f"{'有' if ev.get('session_id') else '无'} | "
                f"{ev.get('elapsed_seconds')} |")
    lines.append("")
    lines.append("## 二、投影计数与坏事件统计")
    lines.append("")
    lines.append("| 车道 | final 收到 | 投影各类型 | 坏事件（解析失败/未知类型/超限截断） |")
    lines.append("|---|---|---|---|")
    for ev in evidence.get("lanes", []):
        proj = ev.get("projection")
        if ev.get("lane") == "judge" or not proj:
            lines.append(f"| {ev.get('lane')} | -（one-shot 通道不落投影）| - | - |")
            continue
        bad = proj.get("bad_events") or {}
        lines.append(
            f"| {ev.get('lane')} | {(proj.get('events_received') or {}).get('final')} | "
            f"{json.dumps(proj.get('events_projected') or {}, ensure_ascii=False)} | "
            f"{bad.get('json_parse_failed')}/{bad.get('unknown_type')}/"
            f"{bad.get('over_limit_truncated')} |")
    lines.append("")
    lines.append("## 三、usage 降级情况")
    lines.append("")
    lines.append("| 车道 | usage_source | input | output | cost_usd |")
    lines.append("|---|---|---|---|---|")
    for ev in evidence.get("lanes", []):
        if ev.get("lane") == "judge":
            lines.append(f"| judge | -（judge 通道不落 run usage）| - | - | - |")
            continue
        usage = ev.get("usage") or {}
        lines.append(
            f"| {ev.get('lane')} | {ev.get('usage_source')} | "
            f"{usage.get('input_tokens')} | {usage.get('output_tokens')} | "
            f"{usage.get('cost_usd')} |")
    lines.append("")
    lines.append("## 四、耗时对比 claude 基线")
    lines.append("")
    baseline = evidence.get("baseline") or {}
    if baseline.get("status") == "available":
        lines.append("| 车道 | dsh(s) | claude(s) | 倍率 |")
        lines.append("|---|---|---|---|")
        for row in baseline.get("rows", []):
            lines.append(f"| {row.get('lane')} | {row.get('dsh_seconds')} | "
                         f"{row.get('claude_seconds')} | {row.get('ratio')} |")
    else:
        lines.append(f"基线状态：**unavailable**——{baseline.get('reason', '')}")
    lines.append("")
    lines.append("## 五、产物硬门结果")
    lines.append("")
    lines.append("| 车道 | 结果文件 | result gate selfcheck |")
    lines.append("|---|---|---|")
    for ev in evidence.get("lanes", []):
        if ev.get("lane") == "judge":
            lines.append("| judge | -（judge 通道无结果文件产物）| - |")
            continue
        gate = ev.get("result_gate") or {}
        lines.append(f"| {ev.get('lane')} | `{ev.get('result_file_path')}` | "
                     f"{'PASS' if gate.get('passed') else 'FAIL'} |")
    lines.append("")
    lines.append("## 六、默认值翻转决策申请（用户裁决项）")
    lines.append("")
    lines.append("> 本段为**决策申请**，不是决策。`agent.harness` 缺省值是否"
                 "由 `claude` 翻转为 `dsh` 由用户依据本报告裁决；翻转属后续"
                 "一次性微变更（config 缺省值 + ADR-271 补记），不在验收链路"
                 "自动化范围内。")
    lines.append("")
    ok = evidence.get("evaluation", {}).get("ok")
    lines.append("- 建议：%s" % (
        "证据齐备，可进入真实验收（accept --go）或由用户裁决翻转" if ok
        else "存在失败项（见证据文件 failures），不建议翻转"))
    if baseline.get("status") == "available":
        lines.append("- 影响面：耗时对比见第四节；假端点证据与真实模型行为"
                     "差异需以真实证据（accept --go 产出）复核")
    else:
        lines.append("- 影响面：缺 claude 基线对比与真实模型行为证据，翻转"
                     "决策只认真实证据")
    lines.append("")
    return "\n".join(lines)


def write_evidence(evidence: Dict[str, Any], evidence_dir: Path,
                   stem: str) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    path = evidence_dir / f"{stem}.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════
# 模式：smoke（假端点全链冒烟，无凭据可重复）
# ══════════════════════════════════════════════════════════════════════

def run_smoke(args: argparse.Namespace) -> int:
    started = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"
    prefix = unique_prefix()
    lanes = [l.strip() for l in (args.lanes or ",".join(SMOKE_LANES)).split(",")
             if l.strip()]
    unknown = [l for l in lanes if l not in SMOKE_LANES]
    if unknown or not lanes:
        print(f"未知车道：{unknown}（合法值 {list(SMOKE_LANES)}）",
              file=sys.stderr)
        return 2

    holder = Path(tempfile.mkdtemp(prefix=f"{FIXTURE_STEM}-"))
    fixture = build_fixture(holder, prefix)
    device: Optional[Dict[str, Any]] = None
    evidence: Dict[str, Any] = {
        "meta": {"spec": "dsh-primary-acceptance-switch", "mode": "smoke",
                 "prefix": prefix, "lanes": lanes, "started_at": started,
                 "repo_root": str(REPO_ROOT), "dsh_profile": args.profile},
        "lanes": [],
    }
    workdir = holder / "mock"
    workdir.mkdir()
    try:
        device = prepare_dsh_home(profile=args.profile, workdir=workdir)
        evidence["meta"]["dsh_home"] = device["home"]
        if device.get("plugin_add_fallback"):
            evidence["meta"]["plugin_add_fallback"] = \
                device["plugin_add_fallback"]
        for lane in lanes:
            lane_workdir = workdir / lane
            lane_workdir.mkdir()
            # 步骤脚本启动前落盘（服务器启动时一次性加载）
            steps = lane_steps(lane, fixture)
            with MockModelServer(steps, lane_workdir) as mock:
                if lane == "judge":
                    ev = run_judge_lane(device=device, fixture=fixture,
                                        mock=mock, timeout=args.timeout)
                else:
                    ev = run_agent_lane(lane=lane, device=device,
                                        fixture=fixture, mock=mock,
                                        timeout=args.timeout)
            evidence["lanes"].append(ev)
            # 逐车道渐进输出（Dashboard 可见性）
            print(f"[lane] {lane}: "
                  f"{'error: ' + ev['error'] if ev.get('error') else 'done'}"
                  f"（{ev.get('elapsed_seconds')}s）", file=sys.stderr,
                  flush=True)
    except Exception as e:  # noqa: BLE001 — 装置失败同样 fail-loud 入证据
        evidence["device_error"] = repr(e)
    finally:
        if device is not None:
            dispose_dsh_home(device)
        if args.keep:
            # 调试保留：跳过清理与残留核对（runbook 手工清理兜底命令收尾）
            evidence["fixture_cleanup"] = {
                "removed": [], "parent_removed": False, "residue_free": None,
                "skipped": True, "reason": f"--keep 保留夹具 {holder}",
                "manual_cleanup": (
                    f"rm -rf {holder}；再核对 rm -rf ~/.dsh 中 *{prefix}* 残留")}
            evidence["residue_check"] = {"residue_free": None,
                                         "skipped": True}
            evidence["meta"]["fixture_kept"] = str(holder)
        else:
            evidence["fixture_cleanup"] = cleanup_fixture(fixture)
            shutil.rmtree(holder, ignore_errors=True)
            evidence["residue_check"] = residue_check(prefix, fixture, holder)

    evidence["baseline"] = compare_baseline(
        evidence["lanes"],
        Path(args.baseline_json) if args.baseline_json else None)
    evidence["evaluation"] = evaluate_evidence(evidence["lanes"])
    if evidence.get("device_error"):
        evidence["evaluation"]["ok"] = False
        evidence["evaluation"]["failures"]["device"] = [evidence["device_error"]]
    cleanup = evidence["fixture_cleanup"]
    if cleanup.get("residue_free") is False:
        evidence["evaluation"]["ok"] = False
        evidence["evaluation"]["failures"]["fixture_cleanup"] = [
            "夹具清理后仍有残留"]
    if evidence["residue_check"].get("residue_free") is False:
        evidence["evaluation"]["ok"] = False
        evidence["evaluation"]["failures"]["residue_check"] = \
            evidence["residue_check"].get("problems") or ["残留核对未过"]
    evidence["meta"]["finished_at"] = utc_iso()

    evidence_dir = Path(args.evidence_dir or DEFAULT_EVIDENCE_DIR)
    path = write_evidence(evidence, evidence_dir,
                          f"dsh-acceptance-smoke-{prefix}")

    if args.json:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    else:
        _print_summary(evidence, path)
    return 0 if evidence["evaluation"]["ok"] else 1


def residue_check(prefix: str, fixture: Dict[str, Any],
                  holder: Optional[Path] = None) -> Dict[str, Any]:
    """零残留核对（spec Scenario「假端点模式可重复」）：真实项目注册表与
    ~/.dsh 零残留。"""
    problems: List[str] = []
    home = Path.home() / ".dsh"
    if home.is_dir():
        try:
            names = [p.name for p in home.rglob(f"*{prefix}*")]
            if names:
                problems.append(f"~/.dsh 出现夹具残留：{names[:5]}")
        except OSError as e:
            problems.append(f"~/.dsh 扫描失败：{e}")
    # 夹具目录树必须已消失（cleanup_fixture 后核对）
    for key in ("project_root", "worktree"):
        if Path(fixture[key]).exists():
            problems.append(f"夹具未清理：{fixture[key]}")
    if holder is not None and holder.exists():
        problems.append(f"夹具父目录未清理：{holder}")
    return {"residue_free": not problems, "problems": problems}


def _print_summary(evidence: Dict[str, Any], path: Path) -> None:
    meta = evidence.get("meta", {})
    ev_all = evidence.get("evaluation", {})
    print(f"== dsh 验收（{meta.get('mode')}）前缀 {meta.get('prefix')} ==")
    for ev in evidence.get("lanes", []):
        lane = ev.get("lane")
        if ev.get("error"):
            print(f"  [{lane}] ERROR: {ev['error']}")
        else:
            print(f"  [{lane}] ok（{ev.get('elapsed_seconds')}s）")
    for name, failures in (ev_all.get("failures") or {}).items():
        for f in failures:
            print(f"  [FAIL:{name}] {f}")
    print(f"判定：{'PASS' if ev_all.get('ok') else 'FAIL'}；证据：{path}")


# ══════════════════════════════════════════════════════════════════════
# 模式：accept（真实全链验收——自检/dry-run/--go 人工触发）
# ══════════════════════════════════════════════════════════════════════

def accept_selfcheck(project_root: Path, profile: str,
                     with_claude_baseline: bool) -> List[Dict[str, Any]]:
    """真实验收前置自检（缺项列缺失项+修复指引；全程零真实模型调用）。

    检查项：dsh 在 PATH + 健康门（版本白名单/Bundle 挂载/headless 运行时）、
    provider 链凭据（llm.providers baseurl+apikey 非空，值脱敏）、claude CLI
    （基线车道）、临时夹具可写。
    """
    checks: List[Dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, fix: str = "") -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "fix": fix})

    if shutil.which("dsh") is None:
        add("dsh 可用", False, "dsh 不在 PATH",
            "npm install -g @deepseek-ai/dsh（见 dsh-bundle/README.md 部署段）")
    else:
        add("dsh 可用", True, f"PATH 命中：{shutil.which('dsh')}")

    # provider 链凭据（accept 的模型三要素来源；值永不打印）
    providers: List[Dict[str, Any]] = []
    try:
        from core.config import ConfigLoader
        cfg = ConfigLoader.resolve_config(project_root)
        raw = ((cfg.get("llm") or {}).get("providers")) or []
        if isinstance(raw, list):
            providers = [p for p in raw
                         if isinstance(p, dict) and p.get("baseurl")
                         and p.get("apikey")]
    except Exception as e:  # noqa: BLE001 — 配置解析失败即缺凭据
        add("provider 链凭据", False, f"配置解析失败：{e}",
            "检查 .fenix/config.yaml 的 llm.providers 段")
    else:
        if providers:
            p0 = providers[0]
            names = [str(p.get("name")) for p in providers]
            add("provider 链凭据", True,
                f"{len(providers)} 个可用 provider：{names}；缺省选中首个 "
                f"baseurl={p0.get('baseurl')}，"
                f"apikey={redact(str(p0.get('apikey')))}"
                f"（首个可能已失效——用 --provider <name> 显式指定）")
        else:
            add("provider 链凭据", False, "llm.providers 无 baseurl+apikey 齐备项",
                "在 .fenix/config.yaml 的 llm.providers 配置 baseurl+apikey")

    # dsh 健康门（真实部署：默认 DSH_HOME + profile）
    if shutil.which("dsh") is not None:
        try:
            from core.agent_runner.harness import resolve_adapter
            # 线协议随 config 装配（agent.dsh_api）：Anthropic 兼容形态
            # baseurl 须配 anthropic-messages，否则健康门过的 Bundle 照样
            # 在真实调用上 TRANSPORT 断流（2026-10-14 两轮验收实证）。
            from core.config import ConfigLoader as _ConfigLoader
            _cfg = _ConfigLoader.resolve_config(project_root)
            adapter = resolve_adapter("dsh", {"agent": {
                "harness": "dsh", "dsh_profile": profile,
                "dsh_api": str(_ConfigLoader.get(_cfg, "agent.dsh_api", "") or "").strip()}})
            adapter.check_health()
            add("dsh 健康门", True,
                f"版本白名单 + Bundle 挂载探测通过（profile={profile}）")
        except Exception as e:  # noqa: BLE001 — 健康门异常含修复指引
            add("dsh 健康门", False, str(e),
                "按 dsh-bundle/README.md 部署段修复，或将 agent.harness 改回 "
                "claude")

    if with_claude_baseline:
        if shutil.which("claude") is None:
            add("claude CLI（基线车道）", False, "claude 不在 PATH",
                "安装 claude CLI，或以 --no-claude-baseline 跳过基线对比"
                "（报告第四节将标记 unavailable）")
        else:
            add("claude CLI（基线车道）", True,
                f"PATH 命中：{shutil.which('claude')}")

    try:
        probe = Path(tempfile.mkdtemp(prefix=f"{FIXTURE_STEM}-probe-"))
        shutil.rmtree(probe, ignore_errors=True)
        add("临时夹具可写", True, "临时目录可创建可删除")
    except OSError as e:
        add("临时夹具可写", False, f"临时目录创建失败：{e}", "检查 TMPDIR 权限")
    return checks


def dry_run_plan(lanes: List[str], args: argparse.Namespace,
                 project_root: Path) -> List[Dict[str, Any]]:
    """dry-run 计划（预演输出；不发起任何调用）。"""
    plan: List[Dict[str, Any]] = []
    baseline = not args.no_claude_baseline
    order = (["claude-implementer（基线）"] if baseline else []) + list(lanes)
    for lane in order:
        harness = "claude" if lane.startswith("claude") else "dsh"
        plan.append({
            "lane": lane,
            "harness": harness,
            "driver": ("harness.run_one_shot（监督 judge 通道）" if "judge" in lane
                       else "AgentRunner._run_agent"),
            "expected_timeout_seconds": args.timeout,
            "real_model_call": True,
        })
    plan.append({
        "lane": "报告产出",
        "harness": "-",
        "driver": "render_report_md → 五段证据 + 决策申请段",
        "expected_timeout_seconds": 0,
        "real_model_call": False,
        "output": str(Path(args.evidence_dir or DEFAULT_EVIDENCE_DIR) /
                      "dsh-acceptance-real"),
    })
    return plan


def run_accept(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root or REPO_ROOT).resolve()
    profile = args.profile
    checks = accept_selfcheck(project_root, profile,
                              with_claude_baseline=not args.no_claude_baseline)
    missing = [c for c in checks if not c["ok"]]
    plan = dry_run_plan(list(SMOKE_LANES), args, project_root)

    if not args.go:
        # 预演：自检 + dry-run 计划；缺项列出修复指引；**零真实模型调用**
        print("== dsh 真实验收预演（dry-run，未发起任何真实模型调用）==")
        for c in checks:
            mark = "✓" if c["ok"] else "✗"
            print(f"  [{mark}] {c['name']}：{c['detail']}")
            if not c["ok"] and c.get("fix"):
                print(f"        修复指引：{c['fix']}")
        print("-- 执行计划 --")
        for step in plan:
            print(f"  - {step['lane']}（{step['harness']}，"
                  f"{step['driver']}，timeout={step['expected_timeout_seconds']}s）")
        if missing:
            print(f"自检未过：{len(missing)} 项缺失——修复后重跑；本次未执行"
                  f"任何真实调用", file=sys.stderr)
            return 1
        print("自检全绿。真实执行需显式 --go（人工触发；见 .fenix/todo.md "
              "真实验收执行请求）")
        return 0

    # ── --go：真实执行（人工触发路径）────────────────────────────────
    if missing:
        print("自检未过，拒绝 --go 真实执行；缺失项：",
              "；".join(c["name"] for c in missing), file=sys.stderr)
        return 1
    return execute_real_acceptance(args, project_root, profile, checks)


def execute_real_acceptance(args: argparse.Namespace, project_root: Path,
                            profile: str, checks: List[Dict[str, Any]]) -> int:
    """真实验收执行（--go）：同夹具 dsh 三车道 + claude 基线车道（可选），
    产出五段证据报告。"""
    from core.config import ConfigLoader
    cfg = ConfigLoader.resolve_config(project_root)
    # provider 选择：--provider 按 name 精确选；缺省取首个合格项——盲取
    # providers[0] 曾选中已失效网关（404，2026-10-14 run1 实证），自检段
    # 会列出全部候选名提示显式指定。
    providers = [p for p in (cfg.get("llm") or {}).get("providers") or []
                 if isinstance(p, dict) and p.get("baseurl") and p.get("apikey")]
    wanted = str(getattr(args, "provider", "") or "").strip()
    if wanted:
        provider = next((p for p in providers
                         if str(p.get("name", "")) == wanted), None)
        if provider is None:
            print(f"--provider {wanted!r} 不在 provider 链：可用 "
                  f"{[str(p.get('name')) for p in providers]}", file=sys.stderr)
            return 1
    else:
        provider = providers[0] if providers else None
    if provider is None:
        print("provider 链无 baseurl+apikey 齐备项", file=sys.stderr)
        return 1
    model = args.model or str(provider.get("model") or "")
    if not model:
        print("未指定 --model 且 provider 缺 model 字段——dsh 通道要求显式模型",
              file=sys.stderr)
        return 1
    env_overrides = {
        "ANTHROPIC_BASE_URL": str(provider["baseurl"]),
        "ANTHROPIC_API_KEY": str(provider["apikey"]),
    }

    started = utc_iso()
    prefix = unique_prefix()
    holder = Path(tempfile.mkdtemp(prefix=f"{FIXTURE_STEM}-"))
    fixture = build_fixture(holder, prefix)
    evidence: Dict[str, Any] = {
        "meta": {"spec": "dsh-primary-acceptance-switch", "mode": "accept",
                 "prefix": prefix, "started_at": started,
                 "repo_root": str(REPO_ROOT), "dsh_profile": profile,
                 "model": model,
                 "baseurl_host": _host_of(str(provider["baseurl"]))},
        "lanes": [],
    }
    try:
        from core.agent_runner.harness import (
            ClaudeAdapter, resolve_adapter, set_current_adapter,
        )
        # 真实部署不隔离 home：adapter 按 ambient DSH_HOME/默认 home 装配；
        # 线协议随 config 装配（agent.dsh_api，见 self-check 同款注释）
        adapter = resolve_adapter("dsh", {"agent": {
            "harness": "dsh", "dsh_profile": profile,
            "dsh_home": os.environ.get("DSH_HOME", ""),
            "dsh_api": str(ConfigLoader.get(cfg, "agent.dsh_api", "") or "").strip()}})
        adapter.check_health()

        lanes = list(SMOKE_LANES)
        for lane in lanes:
            started_lane = time.perf_counter()
            try:
                if lane == "judge":
                    ev = _real_judge_lane(adapter, fixture, model,
                                          env_overrides, args.timeout)
                else:
                    set_current_adapter(adapter)
                    ev = _real_agent_lane(lane, adapter, fixture,
                                          model, env_overrides, args.timeout)
            finally:
                set_current_adapter(ClaudeAdapter())
            ev["elapsed_seconds"] = round(time.perf_counter() - started_lane, 3)
            evidence["lanes"].append(ev)
            print(f"[lane] {lane}: "
                  f"{'error: ' + ev['error'] if ev.get('error') else 'done'}",
                  file=sys.stderr, flush=True)

        # claude 基线（同夹具同 provider 链）
        if not args.no_claude_baseline:
            started_lane = time.perf_counter()
            baseline_ev = _real_claude_baseline_lane(fixture, model,
                                                     env_overrides,
                                                     args.timeout)
            baseline_ev["elapsed_seconds"] = round(
                time.perf_counter() - started_lane, 3)
            evidence["lanes"].append(baseline_ev)
            evidence["baseline"] = {
                "status": "available", "source": "同夹具 claude 车道现场采集",
                "rows": [{"lane": "implementer",
                          "claude_seconds": baseline_ev.get("elapsed_seconds"),
                          "dsh_seconds": next(
                              (e.get("elapsed_seconds") for e in
                               evidence["lanes"] if e.get("lane") == "implementer"),
                              None)}],
            }
            evidence["baseline"]["rows"][0]["ratio"] = round(
                (evidence["baseline"]["rows"][0]["dsh_seconds"] or 0) /
                baseline_ev["elapsed_seconds"], 3) \
                if baseline_ev.get("elapsed_seconds") else None
        else:
            evidence["baseline"] = {
                "status": "unavailable",
                "reason": "--no-claude-baseline 指定：跳过基线车道"}
    except Exception as e:  # noqa: BLE001 — fail-loud 入证据
        evidence["device_error"] = repr(e)
    finally:
        evidence["fixture_cleanup"] = cleanup_fixture(fixture)
        shutil.rmtree(holder, ignore_errors=True)
        evidence["residue_check"] = residue_check(prefix, fixture, holder)

    evidence["evaluation"] = evaluate_evidence(
        [e for e in evidence["lanes"]
         if not e.get("lane").startswith("claude")], real=True)
    if evidence.get("device_error"):
        evidence["evaluation"]["ok"] = False
        evidence["evaluation"]["failures"]["device"] = [evidence["device_error"]]
    evidence["meta"]["finished_at"] = utc_iso()

    evidence_dir = Path(args.evidence_dir or DEFAULT_EVIDENCE_DIR)
    json_path = write_evidence(evidence, evidence_dir,
                               f"dsh-acceptance-real-{prefix}")
    report_path = evidence_dir / f"dsh-acceptance-real-{prefix}.md"
    report_path.write_text(render_report_md(evidence), encoding="utf-8")
    if args.json:
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
    else:
        _print_summary(evidence, json_path)
        print(f"验收报告：{report_path}")
    return 0 if evidence["evaluation"]["ok"] else 1


def _host_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1) if m else (url or "")[:40]


def _real_agent_lane(lane: str, adapter, fixture: Dict[str, Any],
                     model: str, env_overrides: Dict[str, str],
                     timeout: float) -> Dict[str, Any]:
    """真实 dsh 车道（--go）：与 smoke 同一驱动与证据面，端点换 provider 链。"""
    spec = fixture["impl_spec"] if lane == "implementer" else \
        fixture["verify_spec"]
    run_id = f"{'impl' if lane == 'implementer' else 'verify'}-{spec}-a1"
    result_path = Path(fixture["worktree"]) / ".fenix-run-result.json"
    prompt = lane_prompt(lane, fixture, real=True)
    logger = EvidenceLogger()
    runner = build_runner(Path(fixture["project_root"]), logger, timeout)

    box: Dict[str, Any] = {}

    def _drive() -> None:
        try:
            box["ret"] = runner._run_agent(
                prompt, Path(fixture["worktree"]), run_id,
                model_override=model, env_overrides=dict(env_overrides),
                spec_name=spec, agent_type=lane)
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    from core.agent_runner.harness import set_current_adapter
    prev = set_current_adapter(adapter)
    inflight_seen = False
    sampled: List[str] = []
    started = time.perf_counter()
    try:
        th = threading.Thread(target=_drive, daemon=True)
        th.start()
        deadline = time.time() + 60
        while time.time() < deadline and "ret" not in box and "err" not in box:
            for proc in list(runner._running_agents.values()):
                if proc.poll() is not None:
                    continue
                cmdline = _proc_cmdline(proc.pid)
                if cmdline and (not sampled or sampled[-1] != cmdline):
                    sampled.append(cmdline)
                if "dsh" in cmdline and "--profile" in cmdline:
                    inflight_seen = True
            # 同 run_agent_lane：在飞观测后保留固定采样间隔，不做热自旋
            time.sleep(0.4 if inflight_seen else 0.2)
        th.join(timeout=timeout + 120)
    finally:
        set_current_adapter(prev)
    if th.is_alive() and "ret" not in box and "err" not in box:
        reap_lane_processes(runner)
        box["err"] = RuntimeError(
            f"车道驱动线程 {timeout + 120}s 未归——已收割在飞进程组")
    elapsed = time.perf_counter() - started

    ev: Dict[str, Any] = {"lane": lane, "run_id": run_id, "spec": spec,
                          "elapsed_seconds": round(elapsed, 3),
                          "inflight_observed": inflight_seen,
                          "inflight_cmdline_sample": sampled[:1]}
    if "err" in box:
        ev["error"] = repr(box["err"])
        return ev
    output, turns, session_id, usage = box.get("ret") or ("", 0, None, {})
    ev.update({"output": output[:500], "turns": turns,
               "session_id": session_id,
               "usage_source": usage.get("usage_source"),
               "usage": {k: usage.get(k) for k in
                         ("input_tokens", "output_tokens", "cost_usd")},
               "problems": logger.problems[:5]})
    run_file = Path(fixture["runs_dir"]) / f"{run_id}.jsonl"
    ev["run_jsonl_path"] = str(run_file)
    ev["run_jsonl_exists"] = run_file.is_file()
    ev["run_jsonl_last_type"] = _last_jsonl_type(run_file)
    # 真实车道判定面补采（与 smoke 同判据同形状）：run jsonl 首行/tool 面、
    # 原始事件 dump 旁路（投影器按 run 目录无条件落盘）、verifier 报告落盘
    run_entries, ev["run_jsonl_bad_lines"] = _read_jsonl_entries(run_file)
    first = run_entries[0] if run_entries else None
    ev["run_jsonl_first"] = {"type": first.get("type"),
                             "harness": first.get("harness")} \
        if first else None
    ev["tool_use_names"] = sorted({
        blk.get("name") for e in run_entries
        if e.get("type") == "assistant"
        for blk in ((e.get("message") or {}).get("content") or [])
        if isinstance(blk, dict) and blk.get("type") == "tool_use"})
    dump = Path(fixture["runs_dir"]) / f"{run_id}.dsh-events.jsonl"
    ev["raw_dump_path"] = str(dump)
    ev["raw_dump_exists"] = dump.is_file()
    dump_entries, _ = _read_jsonl_entries(dump)
    ev["raw_dump_first_type"] = dump_entries[0].get("type") \
        if dump_entries else None
    report_path = (Path(fixture["worktree"]) / "spec" / "changes" / spec /
                   "verification-report.md")
    ev["verification_report_written"] = (
        report_path.is_file() if lane == "verifier" else None)
    projs = logger.projections()
    ev["projection"] = projs[-1] if projs else None
    ev["result_file_path"] = str(result_path)
    ev["result_gate"] = result_gate_selfcheck(result_path)
    metrics = [c for c in logger.run_metrics_entries()
               if c.get("run_id") == run_id or c.get("spec") == spec]
    ev["run_metrics"] = metrics[-1] if metrics else None
    return ev


def _real_judge_lane(adapter, fixture: Dict[str, Any], model: str,
                     env_overrides: Dict[str, str],
                     timeout: float) -> Dict[str, Any]:
    """真实监督 judge 车道（--go）：run_one_shot，裁决按 advancing 预期
    （快照描述推进中的 run）。"""
    from core.agent_runner.harness.one_shot import run_one_shot
    from core.agent_runner.harness.protocol import ENV_MODE_CLEAN, SpawnRequest

    inflight: Dict[str, Any] = {"observed": False, "cmdline": ""}

    def _on_spawn(proc) -> None:
        cmdline = _proc_cmdline(proc.pid)
        inflight["cmdline"] = cmdline
        if "dsh" in cmdline and "--profile" in cmdline:
            inflight["observed"] = True

    request = SpawnRequest(
        judge_prompt(), cwd=str(fixture["worktree"]),
        output_format="json", model=model, env_mode=ENV_MODE_CLEAN,
        env_overrides=dict(env_overrides))
    err = None
    result = None
    try:
        result = run_one_shot(adapter, request, timeout=timeout,
                              on_spawn=_on_spawn)
    except Exception as e:  # noqa: BLE001
        err = e
    ev: Dict[str, Any] = {"lane": "judge", "run_id": "judge-one-shot",
                          "inflight_observed": inflight["observed"],
                          "inflight_cmdline_sample": inflight["cmdline"][:1]}
    if err is not None:
        ev["error"] = repr(err)
        return ev
    ev["returncode"] = result.returncode
    ev["timed_out"] = result.timed_out
    ev["final_text"], ev["stream_error"] = _parse_dsh_one_shot_stream(
        result.stdout or "")
    ev["verdict"] = _parse_verdict(ev["final_text"])
    ev["stderr_head"] = (result.stderr or "")[:300]
    return ev


def _real_claude_baseline_lane(fixture: Dict[str, Any], model: str,
                               env_overrides: Dict[str, str],
                               timeout: float) -> Dict[str, Any]:
    """claude 基线车道（--go）：同夹具同 provider 链走 claude 通道。"""
    spec = fixture["impl_spec"]
    run_id = f"impl-{spec}-claude-base"
    result_path = Path(fixture["worktree"]) / f".fenix-run-result-claude.json"
    prompt = (f"实现 {spec}：完成 tasks.md 1.1（在 {fixture['worktree']} 下"
              f"创建 hello-claude.txt 内容 claude-ok），完成后把结果 JSON 写"
              f"入 {result_path}（status=success, spec={spec}, "
              f"completed_tasks=[\"1.1\"]）")
    logger = EvidenceLogger()
    runner = build_runner(Path(fixture["project_root"]), logger, timeout)
    box: Dict[str, Any] = {}

    def _drive() -> None:
        try:
            box["ret"] = runner._run_agent(
                prompt, Path(fixture["worktree"]), run_id,
                model_override=model, env_overrides=dict(env_overrides),
                spec_name=spec, agent_type="implementer")
        except Exception as e:  # noqa: BLE001
            box["err"] = e

    from core.agent_runner.harness import ClaudeAdapter, set_current_adapter
    prev = set_current_adapter(ClaudeAdapter())
    started = time.perf_counter()
    try:
        th = threading.Thread(target=_drive, daemon=True)
        th.start()
        th.join(timeout=timeout + 120)
    finally:
        set_current_adapter(prev)
    if th.is_alive() and "ret" not in box and "err" not in box:
        # 驱动线程超时未归：收割在飞进程组（fail-loud 口径对齐 dsh 车道，
        # 不遗留 daemon 驱动线程与 claude 子进程孤儿）
        reap_lane_processes(runner)
        box["err"] = RuntimeError(
            f"claude 基线车道驱动线程 {timeout + 120}s 未归——已收割在飞进程组")
    ev: Dict[str, Any] = {"lane": "claude-implementer（基线）",
                          "run_id": run_id, "spec": spec,
                          "elapsed_seconds": round(time.perf_counter() - started, 3)}
    if "err" in box:
        ev["error"] = repr(box["err"])
        return ev
    output, turns, session_id, usage = box.get("ret") or ("", 0, None, {})
    ev.update({"turns": turns, "session_id": session_id,
               "usage_source": usage.get("usage_source"),
               "result_gate": result_gate_selfcheck(result_path)})
    return ev


def _last_jsonl_type(run_file: Path) -> Optional[str]:
    if not run_file.is_file():
        return None
    last = None
    for line in run_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line).get("type")
        except json.JSONDecodeError:
            continue
    return last


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dsh_acceptance",
        description="dsh 通道一键验收：fixture / smoke / accept 三模式")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_fx = sub.add_parser("fixture", help="生成玩具项目夹具并打印 manifest")
    p_fx.add_argument("--parent", default=None,
                      help="夹具父目录（缺省系统临时目录）")
    p_fx.add_argument("--keep", action="store_true", help="保留夹具不清理")
    p_fx.add_argument("--json", action="store_true", help="机器可读输出")

    p_sm = sub.add_parser("smoke", help="假端点全链冒烟（无凭据可重复）")
    p_sm.add_argument("--lanes", default=",".join(SMOKE_LANES),
                      help=f"车道清单（逗号分隔，合法值 {list(SMOKE_LANES)}）")
    p_sm.add_argument("--profile", default="fenix", help="dsh profile 名")
    p_sm.add_argument("--timeout", type=float, default=DEFAULT_LANE_TIMEOUT,
                      help="单车道超时秒数")
    p_sm.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    p_sm.add_argument("--baseline-json", default=None,
                      help="claude 通道基线文件（耗时对比）")
    p_sm.add_argument("--keep", action="store_true",
                      help="调试：保留夹具目录（正常情况 finally 清理）")
    p_sm.add_argument("--json", action="store_true", help="机器可读输出")

    p_ac = sub.add_parser("accept", help="真实全链验收（自检/dry-run；--go 人工触发）")
    p_ac.add_argument("--go", action="store_true",
                      help="真实执行（人工触发；缺省只自检+输出 dry-run 计划）")
    p_ac.add_argument("--project-root", default=None,
                      help="项目根（provider 链配置来源；缺省仓库根）")
    p_ac.add_argument("--profile", default="fenix", help="dsh profile 名")
    p_ac.add_argument("--model", default=None,
                      help="真实验收模型名（缺省取 provider 配置）")
    p_ac.add_argument("--provider", default=None,
                      help="provider 链按 name 选择（缺省取首个合格项；"
                           "自检会列出全部候选名）")
    p_ac.add_argument("--timeout", type=float, default=900.0,
                      help="单车道超时秒数（真实模式放宽）")
    p_ac.add_argument("--evidence-dir", default=str(DEFAULT_EVIDENCE_DIR))
    p_ac.add_argument("--no-claude-baseline", action="store_true",
                      help="跳过 claude 基线车道（报告第四节标记 unavailable）")
    p_ac.add_argument("--json", action="store_true", help="机器可读输出")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "fixture":
        parent = Path(args.parent) if args.parent else Path(
            tempfile.mkdtemp(prefix=f"{FIXTURE_STEM}-"))
        prefix = unique_prefix()
        manifest = build_fixture(parent, prefix)
        if not args.keep:
            receipt = cleanup_fixture(manifest)
            manifest["cleanup"] = receipt
        else:
            manifest["kept"] = True
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    if args.mode == "smoke":
        return run_smoke(args)
    if args.mode == "accept":
        return run_accept(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
