<!-- knowledge: capability=impl-terminal-nocommit-gate rev=1 sources=spec/archive/2026-09-17-add-impl-terminal-nocommit-gate -->

# 实现者终态零提交门

implementer run 成功收口前的最后机械检查：分支零新提交且工作区有未提交产物时拦截，防「做了工作却没 commit」的整轮空转。

## 现行规则

- 判定时点与条件：在 implementer run 成功收口路径（`cleanup` 之前、`wt_dirty` 取证之后）判定——分支相对 main 零新提交（`git rev-list --count main..branch` 为 0）且 worktree dirty 取证非空时，抛出携带 `[terminal-no-commit]` 前缀与机械归因文案的 `AgentArtifactGateError`，进入既有原地退避重试通道。
- 放行条件：分支有 ≥1 个新提交、或 worktree 干净（零提交且零未提交产物）时不拦截。零提交且 worktree 干净的真空转场景归零变更哨管辖，本门不触发。
- 车道边界：仅对 implementer 生效；fast-track/repair 成功不清理 worktree、verifier 产物由结果文件硬门管辖，均不适用本门。
- 退避通道处置语义：完全复用 `AgentArtifactGateError` 既有通道——退避 sleep 前对当前 attempt 的 worktree 执行锚点 B WIP 提交（`_wip_checkpoint_before_backoff`，见 `impl-wip-checkpoint`）；退避后同 worktree + `--resume` 续做（从「正要 commit」处继续，不重建、不整轮重做）；原地退避预算耗尽后 error 自动携带 `[provider-transient]` 前缀终态失败，worktree 经 keep_for_reuse 保全现场供下轮认领。
- 机械归因：对 run 转录末轮 assistant 消息做纯文本机械判定——text 块含 `<function_calls>` 或 markdown 代码块形式工具调用文本 → 归因「格式回退截断」；否则归因「未提交即收工」。归因结论写入 error 文案；归因仅用于审计与日志语义区分，不改变处置路径（两种原因走同一退避 + resume 通道）。
- cleanup 快照留档（纵深防御）：`worktree_manager.cleanup` 在 `git worktree remove` 失败转 `shutil.rmtree` 硬删之前，若 worktree 存在未提交产物，尽力而为执行 `git stash create` 生成快照引用并记录（含 stash SHA 与分支名）；失败仅 WARNING 留痕、不阻断清理。该留档对全部 agent_type 生效。

## 溯源

- 2026-09-17 2026-09-17-add-impl-terminal-nocommit-gate（spec/archive/2026-09-17-add-impl-terminal-nocommit-gate） — 确立终态零提交判定、退避 + resume 处置复用、机械归因透传与 cleanup rmtree 前快照留档
