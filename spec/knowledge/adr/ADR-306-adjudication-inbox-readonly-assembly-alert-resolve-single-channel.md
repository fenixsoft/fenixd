# ADR-306：裁决收件箱只装配不执行，alert-resolve 单执行通道

date: 2026-10-31
status: accepted

## Context

指挥中心大屏需要向管理层展示待人工裁决事项并支持现场一键裁决。裁决域已有既定事实源与执行通道：choices 以告警记录内快照为准（历史告警不回写注册表演进态，add-human-adjudication-choices D2 语义）、执行走既有 `POST /api/alert-resolve`（动作执行与告警 handled 标记一次完成，destructive 选项带二次确认语义）。大屏若自建执行端点、或在前端复制裁决动词映射，裁决执行与动词语义就会出现第二实现；回读注册表演进态还会打破历史告警的快照一致性。

## Decision

- **收件箱是纯只读装配端点**：`GET /api/command-center/inbox` 只收集未终态且携带 choices 快照的告警并装配决策卡；`choices` 一律读告警记录内快照，MUST NOT 回读裁决注册表的演进态；响应卡片定形（additionalProperties false），不携带任何执行动作端点引用。
- **执行唯一通道复用 alert-resolve**：MUST NOT 新增裁决执行端点；前端不复制裁决动词映射，destructive 二次确认等确认语义由既有端点契约与选项数据承载。后续任何展示裁决收件箱的新界面同受此契约。

## Consequences

- 裁决动词语义与动作执行逻辑只存在于 alert-resolve 单点，语义演进自动惠及全部收件箱消费面；新增裁决动词零前端映射成本。
- 收件箱卡与执行结果之间允许短暂不一致：裁决完成后靠重拉收件箱与 KPI 收敛（成功即移卡、失败保留现场可重试），不做执行侧主动推送。
- 大屏演示路径依赖既有端点可用性；alert-resolve 的确定性失败（如动作前置态不满足返回 400 结构化错误且不标记 handled）会直达决策卡内联展示，卡片保留可重试。
