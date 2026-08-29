## Context

behavior.md §7:/api/alerts 带 project= 为单项目、缺省为跨项目未处理聚合;/api/admin-activities 支持 ?spec= 服务端过滤,响应结构见 §1。componentId 契约:alert-banner、act-timeline(计划头部)。

## Goals / Non-Goals

- Goals: 横幅在有告警时可见并可处理;运维记录时间线与页签渲染
- Non-Goals: 告警的推送来源(后端已有);页签之外的过滤维度

## Decisions

- **横幅整块可点**开 Dialog 列表(替代老版展开列表,形态可变);空告警时横幅不可见(visibleOn rows.length>0)
- **运维记录页签**:全部(无 project 参数)/ 各项目;页签动态性以静态「全部 + 常见项目」或 URL 参数控制,以实现简单为准
- 无告警环境下横幅用例 test.fixme 标注(计划 Task 11 注明)

## Risks / Trade-offs

- 告警数据依赖环境实况;无告警时验证受限于 DOM 结构断言
