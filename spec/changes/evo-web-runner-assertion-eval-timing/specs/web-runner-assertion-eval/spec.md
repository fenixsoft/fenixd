# Capability: web-runner-assertion-eval

## ADDED Requirements

### Requirement: 断言求值时机按类型分层

验证引擎 web_runner SHALL 按断言类型对求值时机分层：交互可用性类断言（`WEB_ASSERTION_LAYERS` 第 2 层封闭枚举：no_click_interception、no_overlap、in_viewport、z_index_order）MUST 在视图切换感知的求值窗口内求值——逐步骤完成点探测目标元素可见性，于目标元素仍可见的最后一个步骤完成点即时求值（含 trial click）；目标元素全程不可见时 MUST 回退既有后置时机求值。流程级断言（no_console_error 等）MUST 保持后置统一求值语义不变。求值时机分层由引擎按断言声明自动判定，MUST NOT 要求场景文件逐场景改动，MUST NOT 新增断言 schema 字段。

#### Scenario: 导航切视图不再误报

- **WHEN** 场景步骤中途切换视图（如导航进会话视图后目标元素所在页被隐藏），交互断言若按既有后置时刻求值将误报 not visible
- **THEN** 交互断言在目标元素仍可见的最后步骤完成点求值并通过，真实点击与功能断言结果不受影响

#### Scenario: 流程级断言语义不变

- **WHEN** 含 no_console_error / no_network_error 断言的场景完成全部步骤
- **THEN** 流程级断言仍在全部步骤后统一求值，结果与现状一致

#### Scenario: 全程不可见回退后置

- **WHEN** 交互断言目标元素自始至终不可见（元素缺失或真实缺陷）
- **THEN** 回退既有后置时机求值判失败并附视图快照，真实缺陷不被提前求值掩盖

#### Scenario: 早期失败不中断步骤

- **WHEN** 交互断言在其求值窗口内判定失败
- **THEN** 后续步骤继续执行，assertion_results 保持断言声明序，断言失败取证截图触发条件不变

### Requirement: 交互断言失败附视图快照

交互可用性类断言报 not visible 等失败时，失败载荷 MUST 附求值时刻的页面视图状态快照（当前可见视图、目标元素所在视图、可见性判定依据），使 judge 能区分「元素被遮挡」「元素随视图切走」与「场景真实缺陷」。

- 快照 MUST 为轻量 DOM 摘要形态，MUST NOT 以截图为默认载体。

#### Scenario: 元素确被遮挡

- **WHEN** 目标元素在当前可见视图内被其他元素遮挡，trial click 报 intercepts pointer events
- **THEN** 失败载荷含 intercept_detail 与视图快照（同视图判定依据），judge 可归因遮挡

#### Scenario: 元素随视图切走

- **WHEN** 目标元素所在视图非当前可见视图，trial click 报 not visible
- **THEN** 失败载荷视图快照明示「目标元素所在视图非当前可见视图」，归因明确
