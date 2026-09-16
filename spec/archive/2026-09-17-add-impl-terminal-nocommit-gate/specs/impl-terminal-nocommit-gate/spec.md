# impl-terminal-nocommit-gate

## ADDED Requirements

### Requirement: implementer 终态零提交门

框架 SHALL 在 implementer run 成功收口路径（`cleanup` 之前、`wt_dirty` 取证之后）执行终态零提交门判定：当分支相对 main 零新提交（`git rev-list --count main..branch` 为 0）且 worktree dirty 取证非空时，MUST 抛出携带 `[terminal-no-commit]` 前缀与机械归因文案的 `AgentArtifactGateError`，进入既有原地退避重试通道；分支有新提交、或 worktree 干净（零提交且零未提交产物）时 MUST NOT 拦截。

#### Scenario: 分支零提交且 worktree dirty → 拦截进退避通道

- **WHEN** implementer run 以 exit 0 + 合法结果文件判定成功，但实现分支相对 main 零新提交，且 cleanup 前 `git status --porcelain` 取证非空
- **THEN** 框架在 cleanup 之前抛出 `AgentArtifactGateError`，error 文本以 `[terminal-no-commit]` 开头并包含归因结论；worktree 未被清理，run 进入既有原地退避重试通道（复用 fix-provider-transient-backoff，不新增重试机制）

#### Scenario: 分支有新提交 → 正常放行

- **WHEN** implementer run 成功且分支相对 main 有 ≥1 个新提交
- **THEN** 终态零提交门不触发，cleanup 与后续收口流程逐字节不变

#### Scenario: 零提交但 worktree 干净 → 不拦（归零变更哨管辖）

- **WHEN** implementer run 成功、分支零新提交，但 `git status --porcelain` 为空（真空转）
- **THEN** 终态零提交门不触发；该场景维持既有 `_implementer_zero_change` 零变更哨语义处置

#### Scenario: 非 implementer 车道不拦

- **WHEN** fast-track / repair / verifier run 到达各自成功收口路径
- **THEN** 终态零提交门不生效（fast-track/repair 成功不清理、verifier 产物由结果文件硬门管），现行行为不变

### Requirement: 退避通道处置语义

终态零提交门 MUST 完全复用 `AgentArtifactGateError` 既有通道：退避 sleep 前对当前 attempt 的 worktree 执行锚点 B WIP 提交（`_wip_checkpoint_before_backoff`）；退避后同 worktree + `--resume` 续做；原地退避预算耗尽后 error 自动携带 `[provider-transient]` 前缀，终态失败走 keep_for_reuse 保全现场。

#### Scenario: 门触发后 WIP 提交保全产物

- **WHEN** 终态零提交门触发且原地退避预算未耗尽
- **THEN** 框架在 sleep 前对 worktree 执行 `fenix(wip): checkpoint transient-backoff <spec>` WIP 提交（锚点 B 原样复用），未提交产物上分支成为可恢复提交

#### Scenario: 续做而非整轮重做

- **WHEN** 退避结束、下一 attempt 启动
- **THEN** 复用同一 worktree 并以 `--resume` 续跑原会话（实现者从「正要 commit」处继续），不重建 worktree、不重新派发整轮

#### Scenario: 原地预算耗尽 → 现场保全交下轮认领

- **WHEN** 终态零提交门连续触发耗尽原地退避预算
- **THEN** error 携带 `[provider-transient]` 前缀退出 attempt 循环，worktree 经 keep_for_reuse 登记为复用遗产，下一轮重派经 `_take_reusable_worktree` 认领继承现场，产物不丢失

### Requirement: 机械归因透传

终态零提交门触发时框架 SHALL 对 run 转录末轮 assistant 消息做机械归因：末轮 text 块包含 `<function_calls>` 或 markdown 代码块形式的工具调用文本 → 归因为「格式回退截断」；否则归因为「未提交即收工」。归因结论 MUST 写入 error 文案；归因仅用于审计与日志语义区分，MUST NOT 改变处置路径（两种原因均走同一退避+resume 通道）。

#### Scenario: 末轮假工具调用 → 归因格式回退

- **WHEN** 门触发且 run 转录最后一条 assistant 消息的 text 块含 `<function_calls>` 内嵌 XML 或 markdown fenced code 形式的工具调用（Edit/Write/Bash 等）
- **THEN** error 文案归因为「格式回退截断」（模型把工具调用写成正文，SDK 未解析致 end_turn）

#### Scenario: 末轮无假工具调用 → 归因忘提交

- **WHEN** 门触发且末轮 text 不含上述假工具调用特征
- **THEN** error 文案归因为「未提交即收工」

#### Scenario: 归因不影响处置

- **WHEN** 两种归因任意一种成立
- **THEN** 处置路径相同（WIP 提交 + 退避 + resume）；归因仅出现在 error 文案与日志中供人工审计

### Requirement: cleanup rmtree fallback 前的 dirty 快照留档

`worktree_manager.cleanup` 在 `git worktree remove` 失败转 `shutil.rmtree` 硬删之前，若 worktree 存在未提交产物，SHALL 尽力而为执行 `git stash create` 生成快照引用并记录到日志（含 stash 引用 SHA 与分支名）；失败仅 WARNING 留痕、不阻断清理流程。该留档对全 agent_type 生效，作为终态零提交门之外的纵深防御。

#### Scenario: rmtree 前有未提交产物 → 留档后再删

- **WHEN** cleanup 的 `git worktree remove` 因含 modified/untracked 文件失败、即将 `shutil.rmtree`，且 `git status --porcelain` 非空
- **THEN** 先执行 `git stash create`（尊重 gitignore），将快照引用 SHA 与所属分支记入日志，再删除目录；快照引用可通过 `git stash store` / `git fsck --unreachable` 追溯取证

#### Scenario: 留档失败不阻断

- **WHEN** `git stash create` 超时或失败
- **THEN** 仅记 WARNING，清理流程照常继续，现行行为不变
