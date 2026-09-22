## ADDED Requirements

### Requirement: 手动修复触发信号端点
质量页签提供「立即自动修复」动作，系统 SHALL 提供 `POST /api/code-review/fix-run` 端点（project 取 query `?project=<name>`，对齐既有 `POST /api/code-review/run` 的 `_project_from_query` 形态），向目标项目原子写入 `.fenix/code_fix_request.json` 触发信号（`O_CREAT|O_EXCL` 独占创建，payload 含 `source: "dashboard"` 与 `created` UTC 时间戳），由 daemon 主循环消费。项目不存在 SHALL 返回 404。

#### Scenario: 受理成功
- **WHEN** 对存在且 daemon 托管正常的项目 POST fix-run
- **THEN** 返回 200 `{ok: true, requested_at}`，且项目 `.fenix/code_fix_request.json` 信号文件被创建

#### Scenario: 并发或残留未消费信号
- **WHEN** 信号文件已存在（并发第二次 POST，或上一信号尚未被消费）
- **THEN** 返回 409 明确文案，MUST NOT 覆盖已有信号

#### Scenario: daemon 不可消费时的前置拦截
- **WHEN** 目标项目 daemon 未运行（stopped）或未受 supervisor 托管（unmanaged）
- **THEN** 分别返回 400 / 409 明确文案，不写信号（对齐 POST /api/code-review/run 的消费方守卫）

### Requirement: 手动触发即临时授权
daemon 消费手动修复信号时，SHALL 以临时授权形态调用 `CodeFixOrchestrator.checkpoint()`：绕过「自动修复代码问题」总开关（`enabled`）守卫，即使开关关闭也投递这一批。checkpoint 的其余守卫 MUST 全部保留：单飞（already_running）、无 open 条目（no_open_items）、失败保留集合、回归契约 fail-closed（regression_contract_missing / regression_section_missing）。

#### Scenario: 总开关关闭时手动触发仍投递
- **WHEN** `admin.code_review_fix.enabled` 为 false 且 daemon 消费到手动修复信号
- **THEN** checkpoint 绕过 enabled 守卫完成投递，进度文件进入 running=true

#### Scenario: 已有修复在跑时拒绝
- **WHEN** 手动信号被消费时存在在途 code-fix 批（编排器单飞或 code-fix- 前缀 run）
- **THEN** 不投递新批，判定为 already_running 并反馈前端

#### Scenario: 无待修条目时拒绝
- **WHEN** 手动信号被消费时台账 open 条目为 0（或全部在失败保留集合中）
- **THEN** 不投递，判定为 no_open_items 并反馈前端

#### Scenario: 回归契约缺失时拒绝
- **WHEN** 手动信号被消费时 verify.yaml 回归契约缺失或缺 regression 段
- **THEN** 不投递（fail-closed 不因手动触发放宽），按契约缺失反馈前端

#### Scenario: 既有后台激活路径行为不变
- **WHEN** 审查收尾或异常中断续做这两路既有激活调用 checkpoint
- **THEN** 未传旁路参数时行为与现状完全一致（enabled=false 时不投递）

### Requirement: 触发判定结果反馈
daemon 消费手动修复信号后，SHALL 把判定结果原子写入 `.fenix/code_fix_request_result.json`：`{request_created, triggered, reason, message, finished_at}`，其中 `request_created` 回链信号文件的 `created` 时间戳，`message` 为面向用户的人类可读中文文案。系统 SHALL 提供只读端点 `GET /api/code-review/fix-run-result?project=<name>` 返回该文件内容（缺失返回缺省态，MUST NOT 500）。判定为被拒时（含 orchestrator 未装配、checkpoint 内部异常）MUST 同样落结果文件并给出明确 reason，MUST NOT 静默丢弃信号。

#### Scenario: 触发成功的结果
- **WHEN** checkpoint 投递成功
- **THEN** 结果文件 `triggered=true`，前端可读到成功文案

#### Scenario: 被拒原因可见
- **WHEN** checkpoint 因 already_running / no_open_items / 回归契约缺失等拒绝
- **THEN** 结果文件 `triggered=false` 且 `reason`、`message` 如实反映拒绝原因

#### Scenario: 编排器未装配不静默
- **WHEN** daemon 上未装配 code-fix 编排器时信号被消费
- **THEN** 结果文件 `triggered=false` 且 reason 指明编排器缺失，不静默丢信号

#### Scenario: 结果按时间戳回链本次触发
- **WHEN** 前端读取 fix-run-result
- **THEN** 仅当结果文件 `request_created` 与本次触发返回的 `requested_at` 一致时才视为本次结果；陈旧残留结果 MUST NOT 被当作本次反馈

### Requirement: 前端按钮与原因回显
质量页签（QualityTab）动作按钮组 SHALL 新增「立即自动修复」按钮：点击后调用 fix-run，受理后轮询 fix-run-result（带超时上限），按结果以 message 成功/警告回显；触发成功后由既有 CodeFixProgressCard 轮询接管进度展示。按钮 SHALL 有 pending 门控防连点；触发流程进行中按钮 MUST 呈 loading 态。

#### Scenario: 点击后受理并回显结果
- **WHEN** 用户点击「立即自动修复」且信号受理成功
- **THEN** 按钮进入 loading，轮询到本次结果后按 triggered 弹出成功或拒绝原因文案

#### Scenario: 轮询超时兜底
- **WHEN** 受理后在超时上限内未读到 `request_created` 匹配的结果文件
- **THEN** 给出「请稍后在进度卡片或 daemon 日志确认」类提示，按钮退出 loading

#### Scenario: 触发成功后进度卡接管
- **WHEN** 结果 `triggered=true`
- **THEN** 既有自动修复进度卡片在 2s 轮询内呈现「第 N 批修复中」，无需额外操作
