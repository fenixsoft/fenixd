# dashboard-overview Spec

## ADDED Requirements

### Requirement: 概览页不承载告警信息面

概览页（/overview）SHALL 仅渲染统计卡、项目台账与既有错误态/降级视图，MUST NOT 渲染告警横幅、告警列表、裁决控件或「清理所有事件」入口；概览页 SHALL NOT 为告警展示维护专属数据管线（告警 SSE 订阅、告警合帧、告警降级轮询）。既有 `GET /api/overview` 心跳刷新与故障隔离降级行为 MUST 保持不变。

#### Scenario: 概览页无告警面
- **WHEN** 存在未处理告警（含待裁决与知情类），用户打开概览页
- **THEN** 页面仅显示统计卡与项目台账，无任何告警横幅、告警条目或清理入口

#### Scenario: 心跳与降级不受影响
- **WHEN** 概览页停留期间 `/api/overview` 请求失败后恢复
- **THEN** 统计卡与项目台账按既有降级→恢复行为工作，与告警退役前一致
