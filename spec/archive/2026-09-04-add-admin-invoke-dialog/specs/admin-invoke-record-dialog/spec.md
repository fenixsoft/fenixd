# admin-invoke-record-dialog — 呼叫 Admin 处置过程弹窗

## ADDED Requirements

### Requirement: 呼叫成功后弹出处置过程弹窗

用户在 SPEC 行右键菜单点击「呼叫 Admin 介入」后，系统 SHALL 在呼叫请求返回成功（HTTP 2xx）或返回 409（已有处置进行中）时打开处置过程弹窗。呼叫请求因其他错误失败（网络异常、5xx 等）时 SHALL NOT 打开弹窗，仅显示错误提示。

#### Scenario: 呼叫成功自动弹窗
- **WHEN** 用户对 SPEC `fix-foo` 点击右键菜单「呼叫 Admin 介入」，POST `/api/spec-admin-invoke` 返回成功
- **THEN** 页面打开处置过程弹窗，此时 Administrator 尚未启动则先显示等待态，无需用户再次操作

#### Scenario: 已在处置中仍弹窗
- **WHEN** 用户点击「呼叫 Admin 介入」但服务端返回 409（该 SPEC 已有呼叫进行中）
- **THEN** 页面同样打开处置过程弹窗，并定位到正在进行的处置

#### Scenario: 呼叫失败不弹窗
- **WHEN** POST `/api/spec-admin-invoke` 因网络或服务端错误失败
- **THEN** 仅显示错误 toast，不打开弹窗

### Requirement: 弹窗实时展示 Administrator 处置过程输出

弹窗主体 SHALL 展示该 SPEC 对应 Administrator run 的**处置过程输出**（Agent 消息事件时间轴），而非仅显示结果的处置记录卡片。系统 SHALL 复用运行时间轴查看各 Agent 消息的现有链路：通过该 SPEC 的 `admin_run_id` 定位 run（可经 `GET /api/admin-activities?spec=<name>` 解析 pending/final disposition 记录），随后复用 run watch 机制（watch/unwatch + `run_events` SSE 增量推送）实时渲染 Agent 输出。Administrator 尚未启动时弹窗 SHALL 显示等待态，并在 run 启动后自动切换为实时输出视图；弹窗顶部 SHALL 显示当前处置状态（处置中/已完成/已中断）。

#### Scenario: Admin 未启动时显示等待态
- **WHEN** 呼叫成功弹窗打开，但 Administrator 尚未被 daemon 巡检唤起（无 pending disposition 记录）
- **THEN** 弹窗显示「等待 Administrator 开始处置」等待态提示，不显示错误

#### Scenario: Admin 启动后自动切换为实时输出
- **WHEN** 等待态期间 daemon 唤起 Administrator 并产生 pending disposition（含 `admin_run_id`），`.fenix/admin_alerts.json` 变更触发处置记录更新广播
- **THEN** 弹窗无需用户刷新即解析到 `admin_run_id`，自动切换为该 run 的事件时间轴视图并注册 run watch

#### Scenario: 处置过程中消息增量实时出现
- **WHEN** 弹窗显示 run 事件时间轴期间，Administrator Agent 持续处置并写入新事件到 run jsonl
- **THEN** 新 Agent 消息通过 `run_events` SSE 增量推送实时出现在时间轴中，无需手动刷新

#### Scenario: 处置完成后保留完整过程与最终状态
- **WHEN** Administrator 完成处置（disposition 落定最终结果），用户查看弹窗
- **THEN** 弹窗保留该 run 的完整过程输出，顶部状态行显示最终处置状态（已完成/已中断等）

### Requirement: 关闭弹窗不影响后台处置

用户可随时关闭弹窗；关闭 SHALL 不影响 Administrator 后台处置流程。弹窗关闭后系统 SHALL 停止响应处置输出更新（取消 run watch），后台处置与记录落盘继续正常进行。

#### Scenario: 关闭弹窗后后台处置继续
- **WHEN** 用户关闭弹窗，此后 Administrator 在后台继续处置
- **THEN** 后台处置流程不受影响，处置结果正常落盘

#### Scenario: 关闭后停止订阅
- **WHEN** 弹窗关闭后该 run 仍产生新事件
- **THEN** 前端已取消该 run 的 watch 订阅，不因弹窗关闭而报错或产生无效更新
