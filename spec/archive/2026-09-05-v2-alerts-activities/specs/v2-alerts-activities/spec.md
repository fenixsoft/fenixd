## ADDED Requirements

### Requirement: 壳级告警横幅

header 的 alert-banner service 拉 /api/alerts(跨项目聚合);有未处理告警时横幅可见并显示条数;点击打开 Dialog 列表,每行「标记已处理」POST /api/alerts/<id>/handled 后 reload,「全部清空」POST /api/alerts/clear;监听 sse:alerts reload。

#### Scenario: 告警处理闭环
- **WHEN** 环境存在未处理告警并点击横幅打开列表
- **THEN** 列表可见;标记单条已处理后该行消失

#### Scenario: 无告警不显示
- **WHEN** /api/alerts 返回空
- **THEN** 横幅不可见

### Requirement: 运维记录页

#/activities 渲染 admin 活动时间线(Timeline)与跨项目页签;act-timeline 监听 sse:admin_activities reload;单项目路由 #/activities/:project 传 ?project= 过滤(behavior.md §7)。

#### Scenario: 时间线渲染
- **WHEN** 访问 #/activities
- **THEN** 时间线组件可见且渲染活动条目(空环境渲染空态不报错)
