# 设计

## 改动点
1. core/agent_runner/result_gate.py `_check_impl_result_artifact`（:1060-1173）：在 status 白名单检查（约 ：1091-1096）之后追加分支——status 为 success 且 data.get("mode")=="fast-track" 时调用 core.fast_track_result.parse_fast_track_verification(data)，返回 None 则返回错误串「fast-track 结果文件 verification 段缺失或结构不完整」。该函数被 full 车道共用，必须以 mode 字段区分；partial/error 状态不进入该分支（诚实退出语义，core/pm_engine/dispatch/fast_track.py:370-377）。
2. core/agent_runner/prompt_builder.py `_result_gate_section` fast-track 分支（:2297-2328）：补契约句「fast-track 的 success 结果文件必须含合法 verification 段（scenarios 非空、每条含非空 scenario_id/description、status 枚举、verdict 属 verified/bug-found）」，与 run 末校验同频，消除两层契约宽严不一。

## 复用与边界
- 校验单源复用 core/fast_track_result.py:59 `parse_fast_track_verification`，与 dispatch 交接点（fast_track.py:819）同一解析器，不引入第二套 schema；
- 失败处置零新机制：`_check_impl_result_artifact` 失败即抛 AgentArtifactGateError（runner.py:2419-2421），由 `_handle_artifact_gate_retry`（runner.py:3256）按结构类失败走原地退避重试——同 session/worktree resume，实现者下一轮收到错误当场补写 verification 段；
- dispatch 交接点 `_hard_check_fast_track`（fast_track.py:753）保留不动，作为第二道防线（防转录捞回等路径绕过 run 末硬门）。

## 备选与否决
- dispatch 拒收分支加「同 worktree 补交接轻量车道」（fast_track.py:824-832 改 `_enqueue_front` 为有界收尾 run）：写后硬门已把缺段消灭在 run 内，整轮重派场景预期消失，且需新增派发形态、改动面大，本期不做；
- 校验放 worktree/merge 层：时机更晚、仍无补写机会，不采用。

## 测试
新增 tests/test_fasttrack_verification_write_gate.py：缺段拦截、补写放行、partial/error 放行、full 车道不触发四类场景；既有 tests/test_agent_runner_gate.py 全量回归。