## Context

自动修复车道（`core/code_fix.py` `CodeFixOrchestrator`）当前只有两路后台激活：审查收尾（`maintenance_runs.run_code_review` 末尾经 `runner._code_fix_orchestrator`）与异常中断续做（`event_bus`），唯一入口是 `checkpoint()`——内置完整守卫链（enabled → 单飞 → 无 open 条目/失败保留 → 回归契约 fail-closed）并返回 `{triggered, reason}`。设置页开关（`admin.code_review_fix.enabled`）打开后仍要等下一次后台事件才跑，用户无法「现在就修一批」。

项目里已有成熟的「dashboard 写文件信号 → daemon 主循环消费」先例：`.fenix/code_review_request.json`（POST /api/code-review/run → `_check_code_review_requests`，1s 粒度）与 regression 触发同款。dashboard（:8787 H11）与 daemon 分进程，直接跨进程调 checkpoint 不可行。

## Goals / Non-Goals

**Goals:**
- 质量页签一键手动投递一批自动修复，不必等后台调度
- 判定结果（成功/被拒原因）以结果文件回显到界面
- 手动触发绕过总开关（临时授权），其余安全守卫原样保留
- 复用 checkpoint 单一入口，不另造第二套守卫/投递逻辑

**Non-Goals:**
- 不改批 worker、进度链（activation_id/total 沿用 D8 契约）、失败保留/release 机制
- 不改设置页开关的既有语义（开关仍约束两路后台自动激活）
- 不做定时/批量排队触发（一次信号 = 至多一批；在跑时拒绝而非排队）

## Decisions

1. **文件信号族新成员，不做跨进程直调**：新增 `.fenix/code_fix_request.json`（dashboard 端 `O_CREAT|O_EXCL` 原子独占创建，防并发覆盖丢触发——code-review item d3c1d2ef4a88 同款）与 `.fenix/code_fix_request_result.json`。daemon 主循环新增 `_check_code_fix_requests`（先读后删、读删失败跳过本轮，对齐 `_check_code_review_requests`）。理由：全库既有模式，dashboard 与 daemon 分进程的既定边界不破。

2. **checkpoint 加 `override_enabled` 参数（缺省 False）而非消费端改配置或绕过 checkpoint**：守卫链保持单点，临时授权语义显式成参；既有两路调用点不传参、行为零变化。失败保留/回归契约/单飞守卫即使在 override 下也照常生效——临时授权只授权「不等调度」，不授权「跳过安全链」。

3. **结果文件 + `request_created` 回链，而非前端靠进度卡猜**（用户已选「结果反馈文件」）：消费端无论 triggered 与否都落 `{request_created, triggered, reason, message, finished_at}`；路由端点在写入新信号前预删旧结果文件；前端仅认 `request_created` 与本次 `requested_at` 一致的结果。拒绝类 reason → message 映射（already_running/no_open_items/regression_*/orchestrator_missing/dispatch_error 等）放消费端一处，前端只渲染 message。

4. **orchestrator 取用经 `getattr(agent_runner, "_code_fix_orchestrator", None)` 判空**（对齐 maintenance_runs.py 既有形态）：未装配不静默——落 `orchestrator_missing` 结果文件，用户可见明确原因。

5. **前端落点与反馈链路**：按钮加在 QualityTab 动作按钮组（全仓库审查/当期提交审查之后），复用 `actionPending` 同款 pending 门控；受理后 1s 间隔轮询 fix-run-result（上限 20s），到点弹 message；成功后无需额外动作——CodeFixProgressCard 既有 2s 轮询自动接管进度展示。

## Risks / Trade-offs

- [override 参数被未来调用点误用成「随手绕开关」] → 参数名显式表意 + 仅 daemon 信号消费函数调用；既有调用点不传参零变化，code review/测试固化两路后台激活在 enabled=false 下仍不投递。
- [结果文件残留被误当本次反馈] → 路由端点写新信号前预删旧结果 + `request_created` 回链双重防御；回链不一致按「暂无结果」处理。
- [消费端 checkpoint 抛异常留死信号/无反馈] → 信号文件先读后删（异常也不复消费）；结果写入包 try/except，异常态落 `dispatch_exception` 结果而非静默。
- [无 open 条目时手动触发高频空转] → 拒绝即时反馈 no_open_items 文案，无重试/排队语义，用户按台账实际情况操作。

## Migration Plan

纯增量：新端点、新信号/结果文件、checkpoint 新增缺省关闭参数、主循环新消费函数。无数据迁移；回滚即还原四处改动（信号/结果文件留盘无副作用——旧码不读）。daemon 需重启加载新消费函数（supervisor 消费 restart_request 既有通道，人工步骤不进任务门禁）。

## Open Questions

<!-- 无：反馈深度、开关语义、执行模式、执行时机均已在立项澄清中确认。 -->
