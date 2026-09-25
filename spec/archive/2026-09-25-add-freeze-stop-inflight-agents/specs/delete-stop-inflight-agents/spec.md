# delete-stop-inflight-agents — Spec

## ADDED Requirements

### Requirement: 删除 SPEC 先停止在跑 agent 再软删除

删除 SPEC 时的运行中保护 MUST 由「拒绝」升级为「先停止再等待终态再删除」：当该 spec 存在在跑 run 时，MUST 先请求终止其名下全部在跑 run（归属判定用全等 `run_spec_part(run_id) == spec`，覆盖全部 agent 前缀），再在**有界窗口**内等待其落终态（每 run 宽限与既有 `AGENT_TERMINATE_GRACE_SECONDS` 同源，另有总上限），终态齐备后执行既有软删除流程（STATE 移除 + 目录移入 archive）。

等待超时仍有 run 未落终态时 MUST 返回明确失败（含未终止 run 列表），MUST NOT 在 run 仍可能写盘时移动其 spec 目录。

无在跑 run 时 MUST 保持既有行为（直接软删除），不引入额外等待。

#### Scenario: 有在跑 agent 时先停后删

- **WHEN** 对某有在跑 implementer 的 SPEC 发起删除
- **THEN** 先终止该 run 并等待终态，随后 STATE 条目移除、`spec/changes/<name>/` 移入 archive，返回成功结果与已停止的 agent 计数

#### Scenario: 等待超时不删除

- **WHEN** 终止请求已发出但某 run 在总上限内仍未落终态
- **THEN** 返回失败并附未终止 run 列表，spec 条目与目录均不变更（不产生半删状态）

#### Scenario: 前缀相似的兄弟 spec 不被误伤

- **WHEN** `fix-x` 与 `fix-x-y` 同时有在跑 run，删除 `fix-x`
- **THEN** 只停止并删除 `fix-x`，`fix-x-y` 的 run 与 STATE 条目不受影响

### Requirement: 删除 API 异步受理

`POST /api/spec-delete` 在该 SPEC 有在跑 agent 时 MUST 改为异步受理：MUST 写删除请求文件信号（含 `spec` / `source` / `created`，原子写 tmp+rename），立即返回受理结果（含待停止 agent 计数），MUST NOT 在请求线程内阻塞等待终止完成。

前置校验 MUST 包含 daemon 托管态：非 `managed` → 409 明确拒绝（信号无人消费，比静默滞留更可诊断）；已有未消费信号 → 409 冲突。无在跑 agent 时 MUST 保持既有同步软删除语义。

daemon 主循环 MUST 消费该信号：停止该 spec 全部在跑 run → 有界等待终态 → 调软删除；信号文件先读后删（删除失败下轮再试），损坏 JSON 删除防卡死（与既有信号消费同构）。

#### Scenario: 有在跑 agent 时返回受理

- **WHEN** 对某有 2 个在跑 agent 的 SPEC 调用删除 API
- **THEN** 返回受理结果（含 `stopping: 2`）且信号文件已落盘，HTTP 请求不阻塞至终止完成

#### Scenario: 无在跑 agent 时同步删除

- **WHEN** 对某无在跑 agent 的 SPEC 调用删除 API
- **THEN** 同步完成软删除并返回既有成功结果（无异步往返）

#### Scenario: daemon 未托管时拒绝

- **WHEN** daemon 进程存在但无 supervisor 托管，对某有在跑 agent 的 SPEC 调用删除 API
- **THEN** 返回 409 与明确原因（信号不会被消费），不写信号文件

#### Scenario: 重复受理被拒

- **WHEN** 已存在未消费的删除信号时再次调用删除 API
- **THEN** 返回 409 冲突，不覆盖既有信号

### Requirement: 前端删除的停止反馈

SPEC 列表的删除确认弹窗与受理后提示 MUST 展示待停止的 agent 计数与进行中状态；收到异步受理结果后 MUST 提示「正在停止 N 个进行中的 agent」并轮询刷新，直至该 SPEC 从列表消失。无在跑 agent 时 MUST NOT 展示该类提示。

#### Scenario: 删除受理后的前端反馈

- **WHEN** 用户确认删除且有 2 个在跑 agent
- **THEN** 提示「正在停止 2 个进行中的 agent」，列表轮询刷新，spec 行在停止+删除完成后消失

#### Scenario: 无在跑 agent 时不展示停止提示

- **WHEN** 用户删除一个无在跑 agent 的 SPEC
- **THEN** 不展示「停止 N 个 agent」类提示，交互与现状一致
