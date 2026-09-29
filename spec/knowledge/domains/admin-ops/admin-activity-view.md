<!-- knowledge: capability=admin-activity-view rev=1 sources=spec/archive/2026-09-02-add-admin-activity-view -->

# 管理员运维记录视图

面向人类的 Administrator 活动界面：运维记录时间线展示「admin 做了什么、为什么、结果如何」，未处理升级置顶高亮。

## 现行规则

- API `GET /api/admin-activities?project=<name>`：返回该项目的 Administrator 活动记录列表（按时间倒序）；每条含时间（created）、spec、信号类型、严重度、叙述总结（summary）、处置动作（actions_taken）、结果（result）、是否升级（escalate）、人工建议（recommended_action）、未处理标记（handled）；跨项目聚合请求按项目分组返回。
- 未处理 escalation 记录置于 API 返回列表顶部；项目无任何 admin 活动记录时返回空列表且不报错。
- 同一处置的 pending/final 记录按 `admin_run_id` 归并展示，处置过程实时可见，不出现「永久处置中」假象。
- Dashboard 独立「运维记录」页面以时间线展示全部活动：时间、spec、信号类型、叙述总结、处置动作、结果徽章、人工建议。
- 未处理升级告警在页面置顶高亮，明确展示「需人工决策」的建议与 mark-handled 操作。
- 旧记录无 `summary` 字段时页面降级显示结构化字段（actions_taken/result），不报错。

## 溯源

- 2026-09-02 史前复原（git:44e1443ba-..2026-09-02） — 迁移期已存在的基线：运维记录时间线按 admin_run_id 归并展示（API/页面/测试），处置过程实时可见
- [2026-09-02 add-admin-activity-view](spec/archive/2026-09-02-add-admin-activity-view/) — 固化运维记录 API 字段契约（倒序/未处理置顶/跨项目分组）与独立页面交互（时间线、高亮、mark-handled、降级兼容）
