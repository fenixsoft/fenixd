# Design: add-command-center-spec-view

## Context

指挥中心组织总览屏（`OrgGrid.tsx` + `aggregate_org`）现为纯实时视图：车道卡活动区只显示在飞归属，「需求数量」（`summary.spec_count`）是纯数字。本 SPEC 叠加一个「按 spec 看全组织」的显示模式。

完整设计真相源（交互形态、红线、验收 Scenario、builder 审查结论）：
`docs/superpowers/specs/2026-10-30-command-center-spec-view-design.md` ——本文为其机器消费摘要，冲突时以真相源为准。

## Goals / Non-Goals

**Goals**：需求数量格点击出下拉（搜索+滚动）→ 选中后全板车道卡活动区切该 spec 轮次视图（全史编号、最新在前、在飞可点开）→ 点轮次开 RunRecordModal；深链进 URL；显式/隐式退出。

**Non-Goals**：轮次行不带状态徽标；车道卡其余四段在 spec 视图下不变；不做按 spec 成本/时长新指标；不改花名册/分区/汇报线/其余三屏；planner 不造轮次（无真实 run 产物，诚实显「未运行」）。

## Decisions

1. **org 只加 `summary.specs`、轮次走独立新端点**（备选：org 加 `?spec=` 参数原响应内联轮次）——后者每次选中变更都重拉全量 org 载荷且改动既有端点签名；独立 `spec-runs` 让 org 轮询成本与响应形状零变化，仅选中态多一路轻量请求。既有键零变动是红线。
2. **轮次两步收集（全史定序 → 窗内出列）**（用户 10-30 裁决全史编号）——「第N轮」若按窗内局部编号，fix 链 today 窗 1 轮显示「第1轮」具误导性；全史定序需不限窗扫描（不套 org 的 14 日 mtime 粗筛），单项目单 spec + get_runs memo 元数据，成本可接受；archived_names 剔除同口径保留（选中的是活跃 SPEC 时天然无影响）。
3. **specView 深链进 URL，状态提升 index.tsx**（用户 10-30 裁决；备选：OrgGrid 内部 state）——组织总览定位管理演示屏，`spec` + `spec_project` 双参数入链后刷新/分享直达特定视图，与既有 project/window 深链口径一致；antd Tabs 非激活页签不销毁，切屏保持选中天然成立。名单校验不过（隐式退出规则）时清参数。
4. **后端下发 `seq` 与 `inflight`，前端零推导**——编号口径与在飞判定单点在后端（IN_FLIGHT_STATUSES 读侧枚举既有），前端纯渲染；轮次行状态判定纯函数进 `shared.ts` 配 node --test 用例。
5. **下拉用 antd Popover + Input + 滚动列表**（备选：antd Select/Dropdown menu）——需内嵌搜索框与自定义条目形态（`project/spec` 消歧、created 序），Popover 自由度最高；其开箱动画不违反静态渲染红线（红线约束的是卡片 DOM，与全站 antd Modal 既有口径一致）。
6. **纯只读端点、表驱动路由追加**——沿用 `command_center_routes.py` 既有 `_API_GET_ROUTES.extend` 形态，不动 base.py/server.py；错误契约复用 `_command_center_scope`（未知项目 200+error 字典）。

## Risks / Trade-offs

- [spec-runs 全史扫描在 run 产物极多的项目上变慢] → 单项目单 spec 过滤 + get_runs 既有 memo 缓存；端点仅选中态触发（非轮询热路径），60s 轮询频率与 org 一致可接受。
- [org 响应新增键导致旧前端/新后端混跑异常] → 纯增量键，旧前端不读不炸；前端对 `summary.specs` 缺键做兜底（视为空名单，下拉显空态）。
- [跨项目同名 spec 在深链中歧义] → `spec_project` 恒随选中入链，单项目筛选下与 project 同值属有意冗余，消歧零歧义。
- [轮次列表点击在飞 run 打开 RunRecordModal 的行为] → 与 10-29 活动行点击在飞归属完全同语义，无新路径。

## Migration Plan

纯增量（新键 + 新只读端点 + 前端新分支），无数据迁移、无破坏性变更；回滚 = 还原前后端改动即可，org 既有消费者全程不受影响。

## Open Questions

（无——两项用户裁决（深链进 URL、全史编号）已定，builder 审查两问题均已闭环。）
