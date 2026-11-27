# honest-exit-convergence（修改：申报告警面与顶层 status 解耦）

## MODIFIED Requirements

### Requirement: 不可达申报的人工感知通道

实现 run 在结果文件申报 `unattainable` 任务时，框架必须保证人工裁决者获得主动告警与门禁上下文注记，不依赖人工主动查进度；该感知通道的触发条件是「申报存在且全部条目合法」，与结果文件顶层 `status` 取值无关。

#### Scenario: success 态申报写告警

- **WHEN** 实现 run 以顶层 `status: "success"` 收工且结果文件 `unattainable` 非空（fast-track 契约下 verified/bug-found 属于 verification.verdict，success 是唯一合法顶层值，此为合法申报形态）
- **THEN** 车道收口路径写入 `impl_unattainable_tasks` ESCALATION 告警（severity=warning，含 SPEC 名与申报清单），与 partial 路径同一信号、同一消费出口；SPEC 不因告警而自动放行未勾任务（verified→done 门禁维持 fail-closed 拦截）

#### Scenario: partial 态申报既有语义不变

- **WHEN** 实现 run 以 `status: "partial"` 收工且缺口全部 ⊆ 合法 `unattainable` 申报
- **THEN** 既有诚实退出收敛判据、放行豁免、`impl_unattainable_tasks` 告警全部保持现状（回归零变化）

#### Scenario: 无申报路径零误报

- **WHEN** 实现 run 以 `status: "success"` 收工且 `unattainable` 缺失或为空
- **THEN** 不写 `impl_unattainable_tasks` 告警（车道正常收口零打扰），门禁 task-gap 判定不消费申报

#### Scenario: 门禁拦截注记申报上下文

- **WHEN** verified→done 门禁因未勾任务拦截且其中部分任务在结果文件已申报 unattainable
- **THEN** task-gap error 文案附申报注记（「其中 N 项已申报不可达」），fail-closed 拦截行为不变；无申报时不附加注记

#### Scenario: 非法申报 fail-closed 不变

- **WHEN** `unattainable` 存在非法条目（非映射 / task 非合法 id / 缺 reason）
- **THEN** 该申报整体不生效：不写告警、不产生门禁注记、不参与任何放行豁免，沿既有 D2b fail-closed 通道处置
