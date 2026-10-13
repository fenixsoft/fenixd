"""claude adapter 平移字节级等价快照测试（add-harness-adapter-layer task 2.4）。

spec agent-harness-adapter「快照测试逐字节对账」：**迁移动手前**以现状
``_run_claude`` 捕获代表性 SpawnRequest 集合（spec 车道/维护车道/resume/
provider 链各至少一例）的 argv/env/stdin 金样本 fixture 入库
（tests/fixtures/harness_claude_snapshot.json）；此后任何时刻，同一
SpawnRequest 集合驱动 ``claude_adapter.build_spawn_spec`` 与金样本逐字节
对照——argv 列表、env 字典（含清除键）、stdin 载荷全部相等。

捕获机制：假 Popen（记录 cmd/kwargs，不真起子进程）+ 记录型 stdin（捕获
stdin 线程写入的 prompt 载荷）+ patch.dict 固定最小 os.environ（env 字典
确定性）+ tmp 隔离项目。路径随机性经 token 归一化（{PROJECT_ROOT}/
{WORKTREE}/{PROGRESS_DIR}）消除——归一化是双射替换，字节级等价断言强度
不变。

金样本再生成（仅当命令构造确需变更时重录并 review diff）::

    python3 tests/test_harness_claude_snapshot.py --capture

注意：快照只护 argv/env/stdin 与 Popen 形参子集；run jsonl 事件行序由
test_run_claude_poll_loop_crash_writes_error_terminal 锁定（行序契约警示，
见 tasks.md 3.1），两者互补不重叠。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.agent_runner.harness import ENV_MODE_AGENT_RUN, ClaudeAdapter, SpawnRequest
from core.agent_runner.harness.claude_adapter import build_env
from tests.helpers import create_temp_project, make_runner

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "harness_claude_snapshot.json"

# 现状 runner 侧 spawn 入口（task 3.1 改名 _run_agent 后同步更新此常量；
# 金样本 fixture 不随之重录——它锚定的是平移前行为）
RUNNER_SPAWN_ENTRY = "_run_claude"

# 固定最小 env（patch.dict clear=True）：AUTH_TOKEN 故意播种——provider 链
# 用例断言「ANTHROPIC_API_KEY 覆盖生效时清除继承的 ANTHROPIC_AUTH_TOKEN」。
FIXED_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/fixture-home",
    "LANG": "C.UTF-8",
    "TERM": "dumb",
    "ANTHROPIC_AUTH_TOKEN": "sk-ant-legacy-inherited-token",
}

# Popen 形参中属 SpawnSpec 字段子集的键（bufsize=1 是执行器侧行缓冲策略，
# SpawnSpec 不承载，fixture 留档但不参与 adapter 对照）
SPEC_POPEN_KEYS = ("text", "encoding", "errors", "start_new_session", "cwd")

SNAP_VERSION = 1


class _StdinRecorder:
    """记录型 stdin：捕获 stdin-feed 线程写入的 prompt 载荷与关闭时序。"""

    def __init__(self):
        self.chunks = []
        self.closed_event = threading.Event()

    def write(self, text):
        self.chunks.append(text)

    def close(self):
        self.closed_event.set()

    def flush(self):
        pass


class _ImmediateProc:
    """立即 EOF 的假进程，供 spawn 轮询环迅速退出（同 test_runner_add_dir_injection）。"""

    def __init__(self):
        self.returncode = 0
        self.stdin = _StdinRecorder()
        self.stdout = MagicMock()
        self.stderr = MagicMock()
        self.stdout.readline = MagicMock(return_value="")
        self.stderr.readline = MagicMock(return_value="")

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass

    def kill(self):
        pass


# ── 代表性 SpawnRequest 集合（spec：车道/resume/provider 链各至少一例）────

CASES = [
    # spec 车道：implementer（无主树 verify-progress 注入；agent-settings.json
    # 在场 → --settings 注入；worktree cwd ≠ project_root → FENIX_RUN_WORKTREE 非空）
    dict(name="implementer_lane", prompt="implement the thing",
         spec_name="demo-spec", agent_type="implementer", agent_settings=True),
    # verifier 车道：主树 verify-progress --add-dir 注入；无 agent-settings
    dict(name="verifier_lane", prompt="verify the thing",
         spec_name="demo-spec", agent_type="verifier"),
    # 维护车道：agent_type=None（缺省注入语义，maintenance/admin 会话现状）
    dict(name="maintenance_default", prompt="maintenance pass", agent_type=None),
    # resume + 显式 model：--model/--resume 追加段
    dict(name="resume_with_model", prompt="continue work",
         spec_name="demo-spec", agent_type="implementer",
         model="deepseek-v4-flash", resume="sess-abc123def456"),
    # provider 链：env_overrides 携带 ANTHROPIC_* + CLAUDE_CONFIG_DIR（dispatch
    # 侧路由产物），断言 AUTH_TOKEN 清除与覆盖合并
    dict(name="provider_chain", prompt="run via provider",
         spec_name="demo-spec", agent_type="fast-track",
         env_overrides={
             "ANTHROPIC_BASE_URL": "https://api.example.com",
             "ANTHROPIC_API_KEY": "sk-provider-key",
             "ANTHROPIC_MODEL": "glm-5.3-flash",
             "CLAUDE_CONFIG_DIR": "/fixture-project/.fenix/agent-config/prov-a",
         }),
]


def _normalize(value, token_map):
    """递归把真实 tmp 路径替换为 token（长 key 先替换，防前缀吞噬）。"""
    if isinstance(value, str):
        for real, token in token_map:
            if real and real in value:
                value = value.replace(real, token)
        return value
    if isinstance(value, list):
        return [_normalize(v, token_map) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v, token_map) for k, v in value.items()}
    return value


def _token_map(project_root: Path, cwd: Path, progress_dir: Path):
    # 长路径在前（progress_dir/cwd 均为 project_root 子路径）
    return [
        (str(progress_dir), "{PROGRESS_DIR}"),
        (str(cwd), "{WORKTREE}"),
        (str(project_root), "{PROJECT_ROOT}"),
    ]


def _capture_from_runner(case: dict, base: Path) -> dict:
    """以现状 runner spawn 入口捕获一次 argv/env/stdin（token 归一化后返回）。"""
    from core.agent_runner import runner as runner_mod

    project_root = create_temp_project(str(base / f"proj-{case['name']}"))
    if case.get("agent_settings"):
        (project_root / ".fenix" / "agent-settings.json").write_text(
            json.dumps({"hooks": {}}), encoding="utf-8")
    cwd = base / f"wt-{case['name']}"
    cwd.mkdir(parents=True, exist_ok=True)
    progress_dir = project_root / ".fenix" / "verify-progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    (project_root / ".fenix" / "runs").mkdir(parents=True, exist_ok=True)
    runner = make_runner(project_root)

    captured = {}
    procs = []

    def fake_popen(cmd, **kwargs):
        proc = _ImmediateProc()
        procs.append(proc)
        captured["argv"] = list(cmd)
        captured["popen"] = {k: kwargs[k] for k in SPEC_POPEN_KEYS}
        captured["bufsize"] = kwargs.get("bufsize")
        return proc

    with patch.dict(os.environ, FIXED_ENV, clear=True):
        with patch(
            "core.agent_runner.runner.subprocess.Popen", side_effect=fake_popen
        ):
            getattr(runner, RUNNER_SPAWN_ENTRY)(
                prompt=case["prompt"],
                cwd=cwd,
                run_id=f"snap-{case['name']}",
                model_override=case.get("model"),
                env_overrides=case.get("env_overrides"),
                resume_session_id=case.get("resume"),
                spec_name=case.get("spec_name"),
                agent_type=case.get("agent_type"),
            )
    # stdin-feed 是独立守护线程：事件等待其写毕（载荷远小于管道缓冲，必然
    # 立即完成；超时视为捕获装置损坏，硬失败）
    if not procs[0].stdin.closed_event.wait(timeout=5):
        raise AssertionError("stdin-feed 线程 5s 内未写毕，捕获装置失效")
    captured["stdin"] = "".join(procs[0].stdin.chunks)
    return _normalize(
        captured, _token_map(project_root, cwd, progress_dir))


def _spawn_request_for(case: dict, project_root: Path, cwd: Path) -> SpawnRequest:
    """与 _capture_from_runner 同参语义的 SpawnRequest（同一集合的 adapter 侧）。"""
    from core.agent_runner.runner import _NO_MAIN_TREE_VERIFY_PROGRESS_LANES

    return SpawnRequest(
        prompt=case["prompt"],
        cwd=str(cwd),
        prompt_transport="stdin",
        output_format="stream-json",
        model=case.get("model"),
        resume_session_id=case.get("resume"),
        permission_mode="bypassPermissions",
        env_overrides=dict(case.get("env_overrides") or {}),
        env_mode=ENV_MODE_AGENT_RUN,
        project_root=str(project_root),
        add_dir_cwd=True,
        add_main_tree_verify_progress=(
            case.get("agent_type") not in _NO_MAIN_TREE_VERIFY_PROGRESS_LANES
        ),
    )


def _capture_from_adapter(case: dict, base: Path) -> dict:
    """同一 SpawnRequest 驱动 claude_adapter.build_spawn_spec 并物化为捕获形状。"""
    project_root = create_temp_project(str(base / f"proj-{case['name']}"))
    if case.get("agent_settings"):
        (project_root / ".fenix" / "agent-settings.json").write_text(
            json.dumps({"hooks": {}}), encoding="utf-8")
    cwd = base / f"wt-{case['name']}"
    cwd.mkdir(parents=True, exist_ok=True)
    progress_dir = project_root / ".fenix" / "verify-progress"

    with patch.dict(os.environ, FIXED_ENV, clear=True):
        spec = ClaudeAdapter().build_spawn_spec(
            _spawn_request_for(case, project_root, cwd))
    captured = {
        "argv": list(spec.argv),
        "stdin": spec.stdin_payload,
        "popen": {
            "text": spec.text,
            "encoding": spec.encoding,
            "errors": spec.errors,
            "start_new_session": spec.start_new_session,
            "cwd": spec.cwd,
        },
    }
    return _normalize(
        captured, _token_map(project_root, cwd, progress_dir))


def _load_fixture() -> dict:
    if not FIXTURE_PATH.is_file():
        raise AssertionError(
            f"金样本 fixture 缺失：{FIXTURE_PATH}——"
            "运行 python3 tests/test_harness_claude_snapshot.py --capture 重录"
        )
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _dump_fixture(payload: dict) -> None:
    FIXTURE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _capture_all() -> dict:
    """现状 runner 入口全量捕获（金样本生成入口）。"""
    cases = {}
    for case in CASES:
        with tempfile.TemporaryDirectory(prefix="harness-snap-") as td:
            cases[case["name"]] = _capture_from_runner(case, Path(td))
    return {
        "version": SNAP_VERSION,
        "runner_entry": RUNNER_SPAWN_ENTRY,
        "fixed_env": FIXED_ENV,
        "cases": cases,
    }


if __name__ == "__main__":
    if "--capture" in sys.argv:
        _dump_fixture(_capture_all())
        print(f"金样本已重录：{FIXTURE_PATH}")
    else:
        print(__doc__)


# ── 测试 ──────────────────────────────────────────────────────────────

_fixture_payload = None


def _fixture():
    global _fixture_payload
    if _fixture_payload is None:
        _fixture_payload = _load_fixture()
    return _fixture_payload


class TestClaudeSnapshotEquivalence:
    """同一 SpawnRequest 集合：adapter 产出与平移前金样本逐字节相等。"""

    @pytest.mark.parametrize(
        "case_name", [c["name"] for c in CASES], ids=[c["name"] for c in CASES]
    )
    def test_adapter_matches_golden(self, tmp_path, case_name):
        case = next(c for c in CASES if c["name"] == case_name)
        golden = _fixture()["cases"][case_name]
        actual = _capture_from_adapter(case, tmp_path)
        assert actual["argv"] == golden["argv"], "argv 与金样本不等"
        assert actual["stdin"] == golden["stdin"], "stdin 载荷与金样本不等"
        assert actual["popen"] == golden["popen"], "Popen 形参子集与金样本不等"

    def test_runner_entry_matches_golden(self, tmp_path):
        # 金样本诚实性自证：fixture 录制装置与现状 runner 入口一致。task 3.1
        # 改名后本测试仍绿（入口内部已委托 adapter，与上一测试形成双保险）。
        for case in CASES:
            golden = _fixture()["cases"][case["name"]]
            actual = _capture_from_runner(case, tmp_path)
            assert actual["argv"] == golden["argv"], f"{case['name']}: argv 漂移"
            assert actual["stdin"] == golden["stdin"], f"{case['name']}: stdin 漂移"
            assert actual["popen"] == golden["popen"], f"{case['name']}: Popen 形参漂移"

    def test_fixture_covers_required_dimensions(self):
        # spec 要求的覆盖维度：spec 车道/维护车道/resume/provider 链各至少一例
        names = set(_fixture()["cases"])
        assert {"implementer_lane", "maintenance_default",
                "resume_with_model", "provider_chain"} <= names
        assert _fixture()["runner_entry"] == "_run_claude"
        assert _fixture()["version"] == SNAP_VERSION

    def test_provider_chain_pops_inherited_auth_token(self):
        # env 字典「含清除键」断言：API_KEY 覆盖生效时继承的 AUTH_TOKEN 必被清除
        case = next(c for c in CASES if c["name"] == "provider_chain")
        actual_env_keys = _capture_adapter_env_keys(case)
        assert "ANTHROPIC_AUTH_TOKEN" not in actual_env_keys
        assert "ANTHROPIC_API_KEY" in actual_env_keys

    def test_agent_run_env_injections(self):
        # 主车道三注入键在场 + 无覆盖时继承 token 保留（金样本 implementer 用例）
        case = CASES[0]
        with tempfile.TemporaryDirectory(prefix="harness-snap-") as td:
            project_root = create_temp_project(str(Path(td) / "proj"))
            cwd = Path(td) / "wt"
            cwd.mkdir()
            with patch.dict(os.environ, FIXED_ENV, clear=True):
                env = build_env(_spawn_request_for(case, project_root, cwd))
        assert env["FENIX_RUN_PROJECT_ROOT"] == str(project_root)
        assert env["FENIX_RUN_WORKTREE"] == str(cwd)
        assert env["CLAUDE_CODE_ENABLE_TODO_TOOLS"] == "1"
        assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-ant-legacy-inherited-token"


def _capture_adapter_env_keys(case: dict):
    """adapter 侧 env 键集（不落 fixture 的现场断言用）。"""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="harness-snap-") as td:
        project_root = create_temp_project(str(Path(td) / "proj"))
        cwd = Path(td) / "wt"
        cwd.mkdir()
        with patch.dict(os.environ, FIXED_ENV, clear=True):
            env = build_env(_spawn_request_for(case, project_root, cwd))
    return set(env)
