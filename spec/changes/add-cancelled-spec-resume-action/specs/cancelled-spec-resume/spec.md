# 被取消保持 SPEC 的界面恢复能力

## ADDED Requirements

### Requirement: 取消保持态在列表摘要与详情中可见

Dashboard 的 SPEC 摘要（列表页 `/api/specs` 条目）与详情（`/api/specs/<spec>`）MUST 下发
`cancelled_hold` 布尔字段，取值为 STATE 条目 `_cancelled_hold` 的规范布尔值
（字符串 `"true"/"false"` 须按 StateParser 同口径转为布尔）。

#### Scenario: 取消保持 SPEC 暴露保持标记
- **WHEN** 某 SPEC 的 STATE 条目含 `_cancelled_hold: true`
- **THEN** 该 SPEC 的列表摘要与详情响应中 `cancelled_hold` 为 `true`

#### Scenario: 非保持 SPEC 不误标
- **WHEN** 某 SPEC 的 STATE 条目 `_cancelled_hold` 为 `false` 或缺失
- **THEN** 该 SPEC 的响应中 `cancelled_hold` 为 `false`

### Requirement: 恢复运行动作复位为保留分支续做

Dashboard MUST 提供 POST 端点（`/api/spec-resume?project=<name>&spec=<name>`），
对取消保持态 SPEC 执行复位。命中时单次原子写 MUST 满足：

- `status: ready`（携带 status 即由 `update_spec` 自动清 `_cancelled_hold`）；
- `branch` 写为解析出的保留分支、`implementer_run` 保留原锚点；
- `_recovery_resume: true`——dispatch 据此在保留分支 worktree 内续做而非从零新建；
- `_retry_count` / `_redispatch_same_cause_streak` / `_redispatch_cause_fp` 归零，
  避免恢复后陈旧同因计数立即触发熔断；
- `error` 写恢复留痕文案（含原状态与「resume preserved branch」语义）。

保留分支解析 MUST 复用 `_resolve_preserved_branch` 共享判定（STATE.branch →
在册 worktree → 分支命名空间枚举三层回落 + `rev-list main..branch` 非空闸门 +
`resolve_resume_site` 载体三态），MUST NOT 新建平行副本。判定通过后 MUST 写
scheduling_kick 信号即时唤醒派发；写失败 MUST 如实回传 warning（STATE 已变更，
不回滚）。

#### Scenario: 有保留分支时恢复续做
- **WHEN** 取消保持 SPEC 的实现分支相对 main 有未合并提交且载体可用
- **THEN** 动作返回 `ok: true`；STATE 落 ready + 原分支 + `_recovery_resume: true`，
  `_cancelled_hold` 为 false；scheduling_kick 信号文件存在于
  `.fenix/scheduling_kick/<spec>.json`

#### Scenario: 无可保留分支时降级普通重派
- **WHEN** 取消保持 SPEC 三层锚点均不可得，或分支相对 main 零提交，或载体不可用
- **THEN** 动作返回 `ok: true` 并携带 `degraded: true` 与降级原因；STATE 落 ready
  （锚点清空、不置 `_recovery_resume`），daemon 走普通全新派发；降级 MUST 有
  WARNING 留痕

#### Scenario: 恢复后即时派发
- **WHEN** 恢复动作成功且 scheduling_kick 信号写入成功
- **THEN** daemon 主循环（1s 粒度）消费信号并按 ready 态唤起 `_on_spec_ready`，
  无需等待周期扫描

### Requirement: 恢复动作的拒绝语义

恢复动作 MUST 对以下情形拒绝且不产生 STATE 变更（对齐 freeze-config 家族的
幂等拒绝语义）：

- spec 不存在于项目 STATE.md → not found；
- 终态（done/pushed）→ 终态不可恢复；
- `_cancelled_hold` 非 true（含冻结态）→ 非取消保持态，幂等拒绝并附原因；
- 冻结态（`frozen` 结构化标记或文本前缀命中）→ 冻结 SPEC 须先解冻，禁止绕过。

#### Scenario: 非取消保持态幂等拒绝
- **WHEN** 对 `_cancelled_hold` 为 false 的非终态 SPEC 调用恢复动作
- **THEN** 返回 `ok: false` 与原因「该 SPEC 并非取消保持态」，STATE.md 零变更

#### Scenario: 冻结态拒绝恢复
- **WHEN** 对 `frozen: true` 的 SPEC（即使 `_cancelled_hold` 为 true）调用恢复动作
- **THEN** 返回 `ok: false` 与原因「冻结 SPEC 须先解冻」，STATE.md 零变更

#### Scenario: 终态拒绝恢复
- **WHEN** 对 status 为 done 或 pushed 的 SPEC 调用恢复动作
- **THEN** 返回拒绝（HTTP 403 语义），STATE.md 零变更

### Requirement: 弹窗恢复运行区块

「修改状态」弹窗 MUST 对 `cancelled_hold` 为 true 的非终态 SPEC 渲染「恢复运行」
区块，文案说明：恢复将复位为 ready 并按保留分支续做（若无可保留分支则全新重派），
将消耗一次实现尝试预算。点击 MUST 弹确认框；确认后调用恢复端点并按返回结果
（成功 / 降级 / 拒绝）给出对应反馈。非取消保持态 SPEC MUST NOT 渲染该区块。

#### Scenario: 取消保持态渲染恢复区块
- **WHEN** 打开取消保持态 SPEC 的「修改状态」弹窗
- **THEN** 渲染「恢复运行」区块（含预算消耗提示与降级说明），非终态之外不渲染

#### Scenario: 确认后恢复成功
- **WHEN** 用户在确认框中确认恢复
- **THEN** 前端调用恢复端点，成功后提示「已复位 ready，daemon 将在保留分支上续做」
  并刷新列表；降级时提示「无可保留分支，将全新重派」
