# spec-approve-push-modal 规格

## ADDED Requirements

### Requirement: 修改状态弹窗对 done SPEC 渲染审批推送区块

SPEC 状态为 `done` 时，修改状态弹窗 MUST 在归档区块之前渲染「审批推送」区块，包含：

- 说明文案：审批后将由 daemon 执行推送（main 先行 + feature 分支尽力），成功后 SPEC 推进到 pushed 终态；推送失败走既有退避重试，超限升级 push_failed 人工告警。
- 「审批推送」确认按钮：点击后 MUST 弹出二次确认（Modal.confirm），确认文案含 SPEC 名称与推送目标（远端 origin）；确认后调用审批推送 API。

状态为 `pushed`（已推送终态）或任何非 done 状态时，弹窗 MUST NOT 渲染该区块。

#### Scenario: done SPEC 显示审批推送区块

- **WHEN** 对状态为 done 的 SPEC 打开修改状态弹窗
- **THEN** 弹窗在归档区块之前渲染审批推送区块（说明文案 + 审批推送按钮）

#### Scenario: pushed SPEC 不显示审批推送区块

- **WHEN** 对状态为 pushed 的 SPEC 打开修改状态弹窗
- **THEN** 弹窗不渲染审批推送区块（已推送无待审批语义），归档区块照常

#### Scenario: 审批确认后发起推送请求

- **WHEN** 用户点击「审批推送」并在二次确认中确认
- **THEN** 前端调用审批推送 API；成功后提示「已提交推送，daemon 执行中」并刷新列表；失败展示错误信息（含冲突与 daemon 未运行提示）

### Requirement: 审批推送 API 与文件信号

新增 `POST /api/spec-approve-push?project=<name>&spec=<name>`，行为 MUST 为：

- project 不存在或 spec 不在项目 STATE.md → 404；
- spec 状态非 `done` → 403 拒绝（pushed 幂等无操作、其他状态非法，error 文案区分）；
- daemon 未运行（复用既有存活探测 `core.fenix_session.is_running`）→ 409「daemon 未运行，请先启动 daemon」（信号无人消费，前置拦截）；
- 已存在未消费的 `.fenix/approve_push_request.json` → 409「已有进行中的审批推送请求」（不覆盖，对齐 cancel_run/scheduling_kick 冲突语义）；
- 校验通过 → 原子写入（tmp+rename，与 `request_admin_invoke` 同构）payload `{"spec": <name>, "source": "dashboard", "created": <ISO8601 UTC>}`，返回 200 `{ok: true, created}`。

#### Scenario: API 对非 done SPEC 返回 403

- **WHEN** 对状态为 ready（或 implementing/pushed 等任何非 done 状态）的 SPEC 调用审批推送 API
- **THEN** 返回 403，body 含区分文案（非 done 状态 / 已 pushed 幂等提示）

#### Scenario: daemon 未运行时 API 返回 409

- **WHEN** daemon 进程未运行时对 done SPEC 调用审批推送 API
- **THEN** 返回 409「daemon 未运行，请先启动 daemon」，不写信号文件

#### Scenario: 已有未消费信号时返回 409 冲突

- **WHEN** `.fenix/approve_push_request.json` 已存在时再次调用审批推送 API
- **THEN** 返回 409「已有进行中的审批推送请求」，既有信号文件不被覆盖

#### Scenario: 校验通过后原子写入信号

- **WHEN** 对 done SPEC 且 daemon 运行中、无残留信号时调用审批推送 API
- **THEN** `.fenix/approve_push_request.json` 被原子写入，内容含 spec/source=dashboard/created，返回 200 `{ok: true}`

### Requirement: daemon 主循环消费审批推送信号

daemon 主循环（1s 粒度）MUST 扫描 `.fenix/approve_push_request.json`，与既有 `_check_cancel_requests` / `_check_scheduling_kick_requests` 同构：

- 损坏 JSON（解析失败）→ 删除信号文件防卡死，本轮跳过；
- 先读后删：删除失败（被并发消费）→ 本轮跳过下轮再试；
- payload 缺 spec → 记 WARNING 并忽略；
- pm_engine 未初始化 → 记 WARNING 并丢弃；
- 消费时调用 `pm_engine.approve_push(spec)`——单飞锁、main 先行+分支尽力、SHA 去重、退避、归档收口、project log 全部沿用既有实现，MUST NOT 新增任何推送语义；
- `approve_push` 返回 False（已 pushed 幂等返回 True 之外的失败：非 done、退避期内、推送失败）→ 记 WARNING，不重试（退避重放与 recovery 兜底已覆盖）。

#### Scenario: daemon 消费信号完成推送

- **WHEN** daemon 运行中，dashboard 写入审批推送信号且 spec 状态为 done
- **THEN** daemon 在主循环下一轮（≤2s）消费信号（读取→删除→approve_push），推送成功后 spec 状态推进为 pushed，project log 记录推送事件

#### Scenario: 损坏信号文件被删除不卡死

- **WHEN** `.fenix/approve_push_request.json` 内容为损坏 JSON
- **THEN** daemon 主循环删除该文件并继续正常运行，后续新信号可正常消费

#### Scenario: 消费时 spec 非 done 由 approve_push 幂等拒绝

- **WHEN** 信号消费时 spec 已不处于 done（如已被其他路径推送或人工迁移）
- **THEN** approve_push 按既有语义幂等跳过或拒绝（已 pushed 返回 True 不重复推送；非 done 返回 False 记 WARNING），不产生 pushed→pushed ERROR

#### Scenario: daemon 未运行时信号滞留且不阻塞

- **WHEN** 信号文件存在但 daemon 已停止
- **THEN** 信号文件滞留（前置 409 已拦截此场景，此处兜底）；daemon 下次启动后主循环照常拾取消费，不阻塞其他调度
