# 提案：fast-track 结果文件 verification 段写后硬门

## 背景与问题
fast-track 实现 run 交付的结果文件若缺 verification 段（验证结论段），要到 merge 前的 dispatch 交接点才被 `_hard_check_fast_track`（core/pm_engine/dispatch/fast_track.py:753）硬校验拒收——此时 run 已 success 终态、git 成果已入分支，只能整轮作废重派。近期三连发生（.fenix/logs/fenixd.log:12085 2026-09-22、:27649/:27886 2026-09-26），单次沉没 8-12 美元级整轮 run 成果。

根因：run 末产物硬门 `_check_impl_result_artifact`（core/agent_runner/result_gate.py:1060-1173）只查文件存在/可解析/status 白名单/tasks.md 完成度，不查 verification 段；运行时注入的契约段（core/agent_runner/prompt_builder.py:2297-2328）也只要求「可解析的非空 JSON」。缺段结果文件可一路 success 收尾，无任何 run 内反馈机会。

## 目标
1. fast-track 的 success 结果文件在 run 末即校验 verification 段结构，不合规当场报错，由既有产物门重试机制（runner `_handle_artifact_gate_retry`）驱动实现者同 session 原地补写；
2. 运行时注入契约段与 run 末硬门同频，明确 fast-track 的 success 结果必须含合法 verification 段。

## 非目标
- 不改 verification 段 schema（单源复用 core/fast_track_result.py 既有解析）；
- 不做「同 worktree 补交接轻量车道」：写后硬门落地后缺段在 run 内即被补写，整轮重派场景预期消失，新增派发形态改动面大，若后续仍有漏网再议。

## 代价与风险
- 改动集中在 result_gate.py 校验分支与 prompt_builder.py 契约段，量小；
- 校验必须以 `mode=="fast-track"` 且 `status=="success"` 限定：`_check_impl_result_artifact` 被 full 车道共用，误拦会伤及 full 车道；partial/error（诚实退出）结果本就不含 verification 段，必须放行。