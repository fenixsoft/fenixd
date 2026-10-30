"""tests/test_dsh_projection.py — dsh 事件投影层契约测试
（add-dsh-adapter-integration 2.3 fixtures 回放 + 2.4 失败语义 + 2.2 可观测性
三件套）。

契约源：dsh-bundle/tests/fixtures/headless-events.jsonl（SPEC-2 真机探针
录制的 11 行事件流）。场景「fixtures 回放接通成对契约」：投影后写入临时
run jsonl，run_task_track 解析出 1 基 taskId 进度、liveness 终态判定正确、
result gate 读侧不受影响。
"""

import json
from pathlib import Path

from core.agent_runner.harness.dsh_adapter import (
    DSH_BAD_EVENT_KINDS,
    DSH_EVENT_TYPES,
    DshEventProjector,
)
from core.run_task_track import parse_run_task_done, read_init_tools

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "dsh-bundle" / "tests" / "fixtures" / "headless-events.jsonl"
)


def _replay(tmp_path: Path, lines, run_id="replay"):
    """逐行经投影器写入临时 run jsonl，返回（投影器, 投影事件列表）。"""
    projector = DshEventProjector(run_id, str(tmp_path))
    projected = []
    run_file = tmp_path / f"{run_id}.jsonl"
    with run_file.open("w", encoding="utf-8") as f:
        for line in lines:
            for ev in projector.ingest(line, json.loads(line)):
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
                projected.append(ev)
    return projector, projected, run_file


def _fixture_lines():
    return [l.strip() for l in FIXTURE.read_text(encoding="utf-8").splitlines()
            if l.strip()]


# dsh 事件语法扩展段：Task 工具族调用（与 fixtures 同一事件语法——probe
# 「工具注册面补充」确认 TaskCreate/TaskGet/TaskList/TaskUpdate 已注册，
# tool_call/tool_result 语法即 fixtures 的 read 调用形态）。
_TASK_LINES = [
    json.dumps({"type": "status", "phase": "turn_start", "turn": 2}),
    json.dumps({"type": "status", "phase": "step_start", "turn": 2, "step": 1}),
    # 1 基 taskId 契约：TaskCreate（subject 内嵌 tasks.md id）→ TaskUpdate
    # status=completed（taskId=1 → flat_done {0}）
    json.dumps({"type": "tool_call", "callId": "tc-1", "tool": "TaskCreate",
                "input": {"subject": "Task 1.1: build_spawn_spec",
                          "description": "dsh 投影回放"}}),
    json.dumps({"type": "tool_result", "callId": "tc-1", "status": "completed",
                "result": "Task #1 created"}),
    json.dumps({"type": "tool_call", "callId": "tc-2", "tool": "TaskUpdate",
                "input": {"taskId": 1, "status": "completed"}}),
    json.dumps({"type": "tool_result", "callId": "tc-2", "status": "completed",
                "result": "updated"}),
    json.dumps({"type": "status", "phase": "step_end", "turn": 2, "step": 1,
                "usage": {"inputTokens": 100, "outputTokens": 20,
                          "totalTokens": 120}}),
    json.dumps({"type": "status", "phase": "turn_end", "turn": 2,
                "reason": {"kind": "completed"}}),
    json.dumps({"type": "final", "text": "任务 1.1 完成",
                "reason": {"kind": "completed"}}),
]


class TestFixtureReplay:
    def test_fixture_projection_shapes(self, tmp_path):
        """投影表逐类型对账：session→init、text→assistant text、tool_call→
        tool_use、tool_result→user tool_result、final→result、status 静默。"""
        lines = _fixture_lines()
        projector, projected, _ = _replay(tmp_path, lines)
        types = [e["type"] for e in projected]
        # 11 行 fixtures：session/status×6/text/tool_call/tool_result/final
        # → 投影出 init/text+tool_call 两 assistant/tool_result 载体/result
        assert types[0] == "system"
        assert types[-1] == "result"
        assert types.count("assistant") == 2  # text + tool_call
        user_events = [e for e in projected if e["type"] == "user"]
        assert len(user_events) == 1
        blk = user_events[0]["message"]["content"][0]
        assert blk["type"] == "tool_result"
        assert blk["tool_use_id"] == "call_mock_1_0"
        # status 相位不投影（turn_end completed 无 error）
        assert "status" not in types
        # 投影契约：1 行 → 0/1 事件（读环取 projected[-1] 的前提）
        assert all(isinstance(e, dict) for e in projected)

    def test_init_carries_session_id_and_tools(self, tmp_path):
        _, projected, _ = _replay(tmp_path, _fixture_lines())
        init = projected[0]
        assert init["subtype"] == "init"
        assert init["session_id"].startswith("session-")
        for tool in ("TaskCreate", "TaskUpdate", "bash", "read", "write"):
            assert tool in init["tools"]

    def test_truncated_flag_passthrough(self, tmp_path):
        """场景：截断标记透传（probe：8KiB 值/32KiB 行，truncated: true）。"""
        lines = [
            json.dumps({"type": "tool_call", "callId": "c1", "tool": "write",
                        "input": {"content": "x" * 20000},
                        "truncated": True}),
        ]
        _, projected, _ = _replay(tmp_path, lines)
        blk = projected[0]["message"]["content"][0]
        assert projected[0]["truncated"] is True
        assert blk["type"] == "tool_use"

    def test_unknown_type_ignored_and_counted(self, tmp_path):
        """未知类型忽略+计数，MUST NOT 中断流（spec 投影需求）。"""
        lines = _fixture_lines()
        lines.insert(3, json.dumps({"type": "hologram", "x": 1}))
        projector, projected, _ = _replay(tmp_path, lines)
        assert projector.bad_events["unknown_type"] == 1
        # 流未中断：final 仍投影为 result 终态
        assert projected[-1]["type"] == "result"


class TestFixtureReplayReadSide:
    """场景「fixtures 回放接通成对契约」：读侧三件套原样消费投影产物。"""

    def test_run_task_track_parses_1based_taskid(self, tmp_path):
        lines = _fixture_lines() + _TASK_LINES
        _, _, run_file = _replay(tmp_path, lines)
        done = parse_run_task_done(run_file)
        assert done["created_count"] == 1
        assert done["done_ids"] == {"1.1"}
        assert done["flat_done"] == {0}

    def test_read_init_tools_capability_gate(self, tmp_path):
        """fix-impl-tasks-completion-gate D4 能力探测：投影 init 的 tools 表
        携带 Task 工具族（dsh 通道不误判工具不可用）。"""
        lines = _fixture_lines() + _TASK_LINES
        _, _, run_file = _replay(tmp_path, lines)
        tools = read_init_tools(run_file)
        assert tools is not None
        assert "TaskCreate" in tools and "TaskUpdate" in tools

    def test_liveness_terminal_judgement(self, tmp_path):
        """场景：liveness 终态判定正确——投影后末行 = result 终态。"""
        from core.agent_runner.liveness import (
            RUN_TERMINAL_EVENT_TYPES,
            _line_is_terminal,
        )

        lines = _fixture_lines() + _TASK_LINES
        _, _, run_file = _replay(tmp_path, lines)
        last = run_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert _line_is_terminal(last) is True
        entry = json.loads(last)
        assert entry["type"] in RUN_TERMINAL_EVENT_TYPES
        assert entry["type"] == "result"

    def test_result_gate_read_side_shape(self, tmp_path):
        """result gate 读侧不受影响：投影 result 事件与 claude canon 形状
        同键（收口段 last_result 消费的字段全数在场）。"""
        from core.agent_runner.session import SessionTracker

        lines = _fixture_lines() + _TASK_LINES
        _, _, run_file = _replay(tmp_path, lines)
        last = json.loads(
            run_file.read_text(encoding="utf-8").strip().splitlines()[-1])
        for key in ("type", "subtype", "is_error", "result", "num_turns",
                    "session_id", "usage"):
            assert key in last, key
        assert last["num_turns"] == 2  # turn_end 计数（design D4）
        assert last["usage"]["input_tokens"] == 356  # 128+128 + 100（step_end 求和）
        assert last["usage"]["output_tokens"] == 84  # 32+32 + 20
        assert last["usage"]["cost_usd"] is None  # 不伪造成本
        assert last["usage_source"] == "available"
        # 读侧 _extract_session_id 原样取回投影 init 的 session_id
        sid = SessionTracker._extract_session_id(run_file)
        assert sid is not None and sid.startswith("session-")


class TestFailureSemantics:
    """场景「失败语义可终判」：两形态投影后末行均为 RUN_TERMINAL_EVENT_TYPES
    可判定的终态，不产生悬挂在飞（2.4）。"""

    def test_exit1_turn_end_error_yields_terminal_error_line(self, tmp_path):
        from core.agent_runner.liveness import _line_is_terminal

        lines = [
            json.dumps({"type": "session", "sessionId": "session-f1",
                        "cwd": "/w"}),
            json.dumps({"type": "text", "text": "working…"}),
            # exit 1 + turn_end(aborted/error) 无 final（dsh 中止形态）
            json.dumps({"type": "status", "phase": "turn_end", "turn": 1,
                        "reason": {"kind": "error",
                                   "error": {"message": "aborted",
                                             "code": "ABORTED"}}}),
        ]
        _, projected, run_file = _replay(tmp_path, lines)
        last = run_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert _line_is_terminal(last) is True
        assert json.loads(last)["type"] == "error"
        err_text = json.loads(last)["error"]
        assert "aborted" in err_text
        assert "dsh: ABORTED" in err_text  # 码保留供分类/取证
        assert projected[-1]["exit_code"] == 1

    def test_error_without_final_yields_terminal_error_line(self, tmp_path):
        from core.agent_runner.liveness import _line_is_terminal

        lines = [
            json.dumps({"type": "session", "sessionId": "session-f2",
                        "cwd": "/w"}),
            json.dumps({"type": "text", "text": "thinking…"}),
            # error 事件且无 final（probe：error 无 final 形态）
            json.dumps({"type": "error",
                        "message": "dsh: MISSING_CREDENTIAL: no credential"}),
        ]
        _, projected, run_file = _replay(tmp_path, lines)
        last = run_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert _line_is_terminal(last) is True
        entry = json.loads(last)
        assert entry["type"] == "error"
        assert "MISSING_CREDENTIAL" in entry["error"]

    def test_error_event_structured_code_kept(self, tmp_path):
        """BUG-02 回归：error 事件结构化形态 ``error:{code,message}`` 投影
        保留错误码（``dsh: <code>: <message>`` 口径，与 turn_end 错误分支
        一致）供 circuit 归因——曾只渲染 message 丢码。"""
        from core.agent_runner.liveness import _line_is_terminal

        lines = [
            json.dumps({"type": "session", "sessionId": "session-f3",
                        "cwd": "/w"}),
            json.dumps({"type": "error",
                        "error": {"code": "TRANSPORT",
                                  "message": "conn refused"}}),
        ]
        _, projected, run_file = _replay(tmp_path, lines)
        last = run_file.read_text(encoding="utf-8").strip().splitlines()[-1]
        assert _line_is_terminal(last) is True
        entry = json.loads(last)
        assert entry["type"] == "error"
        assert "dsh: TRANSPORT: conn refused" == entry["error"]
        # 顶层 code 字段形态同样保留
        lines_top = [
            json.dumps({"type": "error", "code": "TIMEOUT",
                        "message": "timed out"}),
        ]
        _, _, run_file2 = _replay(tmp_path, lines_top)
        err2 = json.loads(
            run_file2.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert err2["error"] == "dsh: TIMEOUT: timed out"


class TestObservabilityTriple:
    """可观测性三件套（2.2）：dump 旁路 + 逐级计数 + 坏事件分类，经
    metrics() 落 run_metrics 结构化日志（runner 集成）。"""

    def test_metrics_counts_line_up_with_projection(self, tmp_path):
        lines = _fixture_lines()
        projector, projected, _ = _replay(tmp_path, lines)
        m = projector.metrics()
        assert m["harness"] == "dsh"
        # 收到 = 投影 + 忽略（逐类型对账）
        for t in DSH_EVENT_TYPES:
            assert m["events_received"][t] == (
                m["events_projected"][t] + m["events_ignored"][t]), t
        assert sum(m["events_received"].values()) == len(lines)
        assert sum(m["events_projected"].values()) == len(projected)
        # fixtures：session/status/text/tool_call/tool_result/final 全类型
        for t in ("session", "status", "text", "tool_call", "tool_result",
                  "final"):
            assert m["events_received"][t] >= 1, t
        # 干净流零坏事件
        assert all(v == 0 for v in m["bad_events"].values())

    def test_bad_event_classification(self, tmp_path):
        projector = DshEventProjector("bad", str(tmp_path))
        projector.ingest("not-a-json-line", None)                # 解析失败
        projector.ingest(json.dumps({"type": "mystery"}),         # 未知类型
                         {"type": "mystery"})
        projector.ingest(json.dumps({"type": "text", "text": "x",
                                     "truncated": True}),         # 超限截断
                         {"type": "text", "text": "x", "truncated": True})
        m = projector.metrics()
        assert m["bad_events"]["json_parse_failed"] == 1
        assert m["bad_events"]["unknown_type"] == 1
        assert m["bad_events"]["over_limit_truncated"] == 1
        assert set(DSH_BAD_EVENT_KINDS) == set(m["bad_events"])

    def test_raw_event_dump_sidecar(self, tmp_path):
        """采集输入原样落盘 run 目录旁路文件（含解析失败行，取证现场完整）。"""
        lines = _fixture_lines()
        projector, _, run_file = _replay(tmp_path, lines)
        dump = Path(projector.metrics()["raw_event_dump"])
        assert dump.exists()
        assert dump.parent == run_file.parent
        dump_lines = [l for l in dump.read_text(encoding="utf-8").splitlines()
                      if l.strip()]
        assert dump_lines == lines  # 原样（逐行等值）

    def test_dump_io_failure_does_not_block_projection(self, tmp_path):
        """dump 打开失败（目录锚点被文件占位）不阻断投影——观测是旁路职责。
        （root 下 chmod 权限位不构成打开失败，故用文件占位制造 OSError。）"""
        blocker = tmp_path / "ro"
        blocker.write_text("not a dir", encoding="utf-8")
        projector = DshEventProjector("x", str(blocker))
        evs = projector.ingest(
            json.dumps({"type": "final", "text": "done"}),
            {"type": "final", "text": "done"})
        assert evs[0]["type"] == "result"
        assert projector.metrics()["raw_event_dump"] is None

    def test_close_idempotent(self, tmp_path):
        projector = DshEventProjector("c", str(tmp_path))
        projector.close()
        projector.close()  # 幂等

    def test_projected_events_carry_timestamp(self, tmp_path):
        """evo-add-dsh-events-latency-timestamps 2.1：投影产出的每条事件
        （含 assistant/user）携带到达时刻 timestamp 字段（数值、正数、随
        到达序单调不减），且 dump 旁路原始行维持原样不加字段——
        latency_samples_from_events 对 dsh 事件流可出样本的前置。"""
        lines = _fixture_lines()
        projector, projected, run_file = _replay(tmp_path, lines)
        # 全部投影事件（assistant/user/system init/result）均带 timestamp
        assert projected, "fixtures 回放应产出投影事件"
        ts_list = [e["timestamp"] for e in projected]
        assert all(isinstance(ts, float) and ts > 0 for ts in ts_list)
        assert ts_list == sorted(ts_list)  # 到达序单调不减
        # assistant/user 形态逐键对账（任务字面锚点）
        stampeds = [e for e in projected if e["type"] in ("assistant", "user")]
        assert len(stampeds) >= 2  # text+tool_call 两 assistant + user 载体
        for ev in stampeds:
            assert isinstance(ev["timestamp"], float) and ev["timestamp"] > 0
        # dump 旁路维持原样（原始行不加 timestamp，避免体积膨胀）
        dump_path = Path(projector.metrics()["raw_event_dump"])
        dump_lines = [
            json.loads(l)
            for l in dump_path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert dump_lines == [json.loads(l) for l in lines]
        assert all("timestamp" not in raw for raw in dump_lines)
