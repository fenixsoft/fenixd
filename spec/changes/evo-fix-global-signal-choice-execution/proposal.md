# fix-global-signal-choice-execution

## 背景

2026-10-02T20:29:59Z，admin run admin-global-1790972103 处置全局指纹告警 ce27a93f9dca（daemon_errors 升级信号、spec=null）时选择 spec 作用域动作 retry_review。框架将空 spec 占位为 'global'（core/agent_runner/maintenance_runs.py:245），执行器查证失败报『spec not found: global』；同一秒终态回写已把信号记为 handled=true / result=resolved（.fenix/logs/fenixd.log:40819-40820，先回写后报错），告警记录 action_taken 与 result 恒为 null。属通道设计缺口：『全局信号 × spec 作用域 choice』组合无路由防护，任一全局告警选到此类动作都会复现。

## 目标

1. 全局信号（spec 为空或占位 'global'）不再执行 spec 作用域 choice，且跳过/拒绝行为留痕可见。
2. choice 执行失败不得回写 resolved/handled，信号保留待重审并记录失败原因。
3. choice 执行结果（动作名与成败终态）落到告警记录 action_taken/result 字段。

## 非目标

- 不改变 spec 作用域信号（spec 非空）的既有处置流程与动作语义。
- 不修改人工端点 core/dashboard/routes/alert_routes.py 的既有防护行为（仅保证回归不回退）。
- 不新增告警类型或处置通道；不强制修改 admin 提示词中 choices 的呈现方式。

## 验收

- 全局信号 × retry_review：执行被跳过/拒绝，有 INFO 或错误留痕，信号终态非 resolved。
- 构造 choice 执行失败：告警 result 记 failed（或等价终态）、处置记录 error 含失败原因、action_taken 记录动作名。
- 既有用例 tests/test_adjudication_choices.py、tests/test_admin_disposition_failure_context.py 全部通过。