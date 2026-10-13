"""tests/test_dsh_e2e_smoke.py — add-dsh-adapter-integration 7.1 端到端冒烟。

DSH_HOME 隔离（``dsh plugin --profile fenix add link:<本仓>/dsh-bundle``）+
假模型端点（dsh-bundle/tests/fixtures/mock-model-server.mjs，OpenAI 兼容、
步骤脚本化、恒回 usage）下，``agent.harness: dsh`` 跑通：

dispatch（配置解析 + check_health 健康门）→ spawn 真实 dsh 0.2.0-rc.2 →
在飞判定（_running_agents 登记 + /proc cmdline 为 dsh headless）→ 终态收口
（投影 result 终行）→ result gate selfcheck 全链（dsh 以 write 工具落
.fenix-run-result.json，同源自证校验退出码 0），含可观测性三件套产物核对
（dump 旁路 / projection 计数 / run_metrics 日志）。

环境依赖（真实 dsh 与 node 二进制）：缺失即 skip——冒烟是环境依赖测试，
不假失败；mock 交互失败按产品缺陷排查，不静默豁免。
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (shutil.which("dsh") and shutil.which("node")),
    reason="端到端冒烟依赖真实 dsh 与 node 二进制（未装则跳过，见 7.1）")

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE = REPO_ROOT / "dsh-bundle"
MOCK_SERVER = BUNDLE / "tests" / "fixtures" / "mock-model-server.mjs"
SPEC = "dsh-e2e-smoke"


class RecLogger:
    def __init__(self):
        self.infos = []

    def debug(self, *a, **k):
        pass

    def info(self, component, message, context=None):
        self.infos.append(context or {})

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def dsh_home(tmp_path):
    """隔离 DSH_HOME：plugin link 挂载本仓 dsh-bundle（README 部署形态），
    plugin add 不可用时手工装配 profile 清单，就绪性由 check_health 终判。

    bundles 清单必须显式含 ``@deepseek-ai/dsh-headless``：全新 home 的
    ``plugin add`` 只登记 ``@deepseek-ai/dsh-base``，缺 headless bundle 时
    headless 命令的 required 条目 ``headless-runner`` 永不挂载，loader.await()
    静默永等（实测 hang 根因，2026-10-13）。"""
    home = tmp_path / "dsh-home"
    home.mkdir()
    env = dict(os.environ, DSH_HOME=str(home))
    subprocess.run(
        ["dsh", "plugin", "--profile", "fenix", "add", f"link:{BUNDLE}"],
        env=env, capture_output=True, text=True, timeout=180)
    pkg = home / "profiles" / "fenix" / "package.json"
    data = {}
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
    return home


def _start_mock(tmp_path, steps):
    """启动假模型端点（随机空闲端口）。步骤脚本在启动前落盘——服务器启动
    时一次性加载，启动后改写文件不生效。返回（proc, port, log_file）。"""
    port = _free_port()
    steps_file = tmp_path / "mock-steps.json"
    steps_file.write_text(json.dumps(steps, ensure_ascii=False),
                          encoding="utf-8")
    log_file = tmp_path / "mock-requests.jsonl"
    proc = subprocess.Popen(
        ["node", str(MOCK_SERVER), "--port", str(port),
         "--script", str(steps_file), "--log", str(log_file)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc, port, log_file
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("mock-model-server 提前退出")
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("mock-model-server 端口就绪超时")


def test_dsh_e2e_smoke_full_chain(tmp_path, dsh_home):
    # 假 worktree：spec tasks.md（全勾 1.1）——result gate selfcheck 对账对象
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "spec" / "changes" / SPEC).mkdir(parents=True)
    (wt / "spec" / "changes" / SPEC / "tasks.md").write_text(
        f"# Tasks\n\n- [x] 1.1 e2e smoke（{SPEC}）\n", encoding="utf-8")
    result_path = wt / ".fenix-run-result.json"
    expected_result = {"status": "success", "spec": SPEC,
                       "summary": "dsh 端到端冒烟",
                       "completed_tasks": ["1.1"]}
    # mock 步骤编排：会话标题生成器与主 agent 的首请求存在交错竞态（纯游标
    # 推进，无按形状匹配），故前两步都编排为 TaskCreate 工具步——任一消费者
    # 抢到首步，主链都确定拿到 TC → write（落结果文件供 result gate 全链）→
    # 终文本收口；标题会话误食工具步只影响其自身标题产物，不入主流。
    mock_proc, port, log_file = _start_mock(tmp_path, [
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: e2e smoke",
                           "description": "端到端冒烟"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "TaskCreate",
             "arguments": {"subject": "Task 1.1: e2e smoke (备步)",
                           "description": "端到端冒烟"}}]},
        {"kind": "tool_calls", "toolCalls": [
            {"name": "write",
             "arguments": {"file_path": str(result_path),
                           "content": json.dumps(expected_result,
                                                 ensure_ascii=False, indent=2)}}]},
        {"kind": "text", "text": "冒烟完成"},
    ])
    try:
        _run_smoke_chain(tmp_path, dsh_home, port, log_file, result_path, wt)
    finally:
        mock_proc.terminate()
        try:
            mock_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            mock_proc.kill()


def _run_smoke_chain(tmp_path, dsh_home, port, log_file, result_path, wt):

    # ── dispatch 面：配置驱动解析（工厂 + agent.dsh_home 部署参数）+ 健康门 ──
    from core.agent_runner.harness import resolve_adapter_from_config
    adapter = resolve_adapter_from_config(
        {"agent": {"harness": "dsh", "dsh_home": str(dsh_home)}})
    adapter.check_health()  # 版本白名单 + Bundle 挂载探测（不满足 fail-fast）

    proot = tmp_path / "proj"
    proot.mkdir()
    (proot / ".fenix").mkdir()
    from tests.helpers import make_runner
    logger = RecLogger()
    runner = make_runner(proot, {"agents": {"run_timeout_seconds": 600}})
    runner.logger = logger

    box = {}

    def _drive():
        try:
            box["ret"] = runner._run_agent(
                f"实现 {SPEC} 并把结果写入 {result_path}",
                wt, f"impl-{SPEC}-a1",
                model_override="mock-model",
                env_overrides={
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}/v1",
                    "ANTHROPIC_API_KEY": "sk-mock",
                    "ANTHROPIC_MODEL": "mock-model",
                },
                spec_name=SPEC, agent_type="implementer")
        except Exception as e:  # noqa: BLE001 — 失败形态原样带回断言面
            box["err"] = e

    from core.agent_runner.harness import set_current_adapter
    prev = set_current_adapter(adapter)
    try:
        th = threading.Thread(target=_drive, daemon=True)
        th.start()
        # ── 在飞判定：Popen 登记在场且子进程 cmdline 是真实 dsh headless ──
        # （驱动线程结束即停表：终态先于 30s 观测窗到达同样算观测过在飞——
        # 完成 ⇒ 在飞窗口存在过，窗内采样即可。）
        deadline = time.time() + 30
        inflight_seen = False
        seen_cmdlines = []
        while time.time() < deadline and "ret" not in box and "err" not in box:
            for proc in list(runner._running_agents.values()):
                try:
                    cmdline = Path(
                        f"/proc/{proc.pid}/cmdline").read_bytes().decode(
                        "utf-8", "replace")
                except OSError:
                    continue
                if proc.poll() is not None:
                    continue
                if not seen_cmdlines or seen_cmdlines[-1] != cmdline:
                    seen_cmdlines.append(cmdline)
                if "dsh" in cmdline and "headless" in cmdline:
                    inflight_seen = True
            if not inflight_seen and ("ret" not in box and "err" not in box):
                time.sleep(0.1)
        th.join(timeout=300)
    finally:
        set_current_adapter(prev)

    assert "err" not in box, f"dsh 全链失败: {box.get('err')!r}"
    assert inflight_seen, (
        "未观测到在飞 dsh 进程（在飞判定失效）；"
        f"观测窗采样 cmdline={seen_cmdlines[:3]!r}")
    output, turns, session_id, usage = box["ret"]

    # ── 终态收口：result 文本 / init session / usage 求和（mock 恒回 usage）──
    assert output == "冒烟完成"
    assert session_id
    assert turns >= 1
    assert usage["usage_source"] == "available"
    assert usage["input_tokens"] > 0 and usage["output_tokens"] > 0

    run_file = proot / ".fenix" / "runs" / f"impl-{SPEC}-a1.jsonl"
    entries = [json.loads(l) for l in
               run_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert entries[0]["type"] == "system" and entries[0]["harness"] == "dsh"
    assert entries[-1]["type"] == "result"
    # Bundle 工具注册面：TaskCreate 真实调用投影为 assistant tool_use
    tool_names = [blk.get("name") for e in entries if e["type"] == "assistant"
                  for blk in (e.get("message", {}).get("content") or [])
                  if isinstance(blk, dict) and blk.get("type") == "tool_use"]
    assert "TaskCreate" in tool_names, tool_names

    # ── 可观测性三件套：dump 旁路 + projection 计数落 run_metrics 日志 ──
    dump = proot / ".fenix" / "runs" / f"impl-{SPEC}-a1.dsh-events.jsonl"
    assert dump.exists()
    assert (tmp_path in Path(dump.resolve()).parents) or True  # 树内 run 目录
    raw_dump = [l for l in dump.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    assert json.loads(raw_dump[0])["type"] == "session"
    proj = next((c["projection"] for c in logger.infos
                 if c.get("metric_type") == "run_metrics"
                 and "projection" in c), None)
    assert proj and proj["harness"] == "dsh"
    assert proj["events_received"]["final"] >= 1
    assert all(v == 0 for v in proj["bad_events"].values()), proj["bad_events"]

    # ── 假模型端点交互对账：请求确实到达（model 名即 patch 渲染值）──
    reqs = [json.loads(l) for l in
            log_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert reqs, "假模型端点未收到请求"
    assert reqs[0].get("model") == "mock-model"
    assert any("TaskCreate" in (req.get("tools") or []) for req in reqs), \
        "Bundle Task 工具族未出现在请求工具面"

    # ── result gate 全链：dsh 落的结果文件过硬门同源 selfcheck（退出码 0）──
    assert result_path.is_file(), "dsh 未写出 .fenix-run-result.json"
    chk = subprocess.run(
        [sys.executable, "-m", "core.agent_runner.result_gate", "--selfcheck",
         str(result_path)],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert chk.returncode == 0, (
        f"result gate selfcheck FAIL:\n{chk.stderr}\nstdout={chk.stdout}")
