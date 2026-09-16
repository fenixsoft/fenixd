# add-impl-terminal-nocommit-gate

## Why

2026-09-10 双 SPEC 首轮零提交全丢（impl-add-verdict-credibility-gate-1789001677，36.5min/$18.12；impl-add-impl-wip-checkpoint-1789002687，31.8min/$12.11）：implementer 末轮输出格式回退（把 git commit 命令写成 text 正文而非 tool_use），SDK 以 `end_turn`「自然完成」收轮，框架判定成功后 `cleanup(success=True)` 将带未提交产物的 worktree rmtree 硬删，交付物守卫在毁灭之后才查分支 HEAD——必然缺件、整轮重做。这是零提交死法第三变体（①排水杀在飞 run、②shutdown 误判瞬断均已治理），「run 正常终态 + 分支零提交 + worktree dirty」既无 WIP 锚点（add-impl-wip-checkpoint 锚点 A/B 只钉排水收口与瞬断退避两处）、零变更哨又因「有 Edit/Write 调用」豁免放行、终局守卫时点在产物毁灭后，属系统性残留缺口，每案实测白耗一轮 32-36min + 一次 dispute-judge。

## What Changes

- implementer 成功路径 cleanup **之前**新增「终态零提交门」：分支相对 main 零新提交 **且** worktree 取证 dirty 非空时，抛 `AgentArtifactGateError("[terminal-no-commit] ...")`——复用既有 fix-provider-transient-backoff 原地退避通道，不新增重试机制。
- 复用通道内置全套处置即得修复语义：退避 sleep 前已调用锚点 B `_wip_checkpoint_before_backoff`（框架替模型执行它没发出去的 git commit）；退避后同 worktree `--resume` 续做（从「正要 commit」处继续而非从零重做）；原地预算耗尽后 error 自动携带 `[provider-transient]` 前缀 → keep_for_reuse 保全现场交下轮认领。
- 原因透传：门触发时对 run 转录末轮做机械归因——text 含 `<function_calls>` 或 markdown 代码块假工具调用 → 归因「格式回退截断」；否则归因「忘记提交」。归因写入 error 文案与 run 转录终态记录，仅供人工审计与日志语义区分，不改变处置路径（resume 对两种原因均正确）。
- 零提交 + worktree 干净的真空转场景**不拦**（维持既有零变更哨 `_implementer_zero_change` 管辖，语义不重叠）。
- 纵深防御：`worktree_manager.cleanup` 的 `shutil.rmtree` fallback 前增加 dirty 快照留档（`git stash create`，尽力而为、失败仅 WARNING），消灭「守卫裁决需要证据而现场已毁」的取证盲区（09-09 verify-add-verdict-contract-singularity 已暴露同款 untracked 告警）。

## Capabilities

### New Capabilities

- `impl-terminal-nocommit-gate`: implementer 正常终态但分支零提交且 worktree 有未提交产物时，在 cleanup 前拦截为可恢复错误——WIP 锚点提交 + 原地退避 + 同 worktree resume 续做，替代整轮重做；含格式回退/忘提交的机械归因透传与 cleanup rmtree 前的 dirty 快照留档纵深防御。

### Modified Capabilities

（无——零变更哨、交付物守卫、WIP 锚点 A/B 的既有语义均不变；本能力是三防线之间的残留缝隙补位）

## Impact

- `core/agent_runner/runner.py`：成功收口路径（cleanup 前）插入终态门判定与 AgentArtifactGateError 抛出；错误分支沿用既有 AgentArtifactGateError except 通道（原地退避+锚点B+resume 全套已在位，仅接线）。
- `core/worktree_manager.py`：cleanup 的 rmtree fallback 前 stash create 留档。
- `core/wip_checkpoint.py`：不改（锚点 B 原样复用）。
- 测试：`tests/test_agent_runner.py`（终态门判定矩阵）、`tests/test_impl_wip_checkpoint.py` 或新文件（cleanup 留档）。
- 风险面：仅 implementer 车道；fast-track / repair 成功不清理语义不变；verifier 成功路径暂不拦（其产物由结果文件硬门管，dirty 不影响分支合并），留档纵深防御对全 agent_type 生效。
