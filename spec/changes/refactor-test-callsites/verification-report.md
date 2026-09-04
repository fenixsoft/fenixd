# 验证报告 — refactor-test-callsites

## 验证结果

**结论：✅ 通过**

全部 26 个验证场景通过，0 失败 / 0 警告 / 0 错误。

## 场景覆盖

| 序号 | 场景 ID | 描述 | 状态 |
|------|---------|------|------|
| 1 | dashboard-project-overview | Dashboard 项目概览页面正确展示项目列表与状态统计 | ✅ pass |
| 2 | overview-api-response-structure | GET /api/overview 返回正确的项目状态聚合结构 | ✅ pass |
| 3 | projects-api-response-structure | GET /api/projects 返回项目列表与聚合摘要 | ✅ pass |
| 4 | spec-doc-api-proposal | GET /api/spec-doc 正确返回 Proposal 文档原文 | ✅ pass |
| 5 | spec-doc-api-design | GET /api/spec-doc 正确返回 Design 文档原文 | ✅ pass |
| 6 | spec-detail-api-response | GET /api/specs/<spec> 返回单个 SPEC 完整详情 | ✅ pass |
| 7 | production-path-fenixd-import | fenixd.py 与 core/dashboard 的 import 调用语句无修改 | ✅ pass |
| 8 | sse-connection-establish | SSE 长连接正确建立，实时推送功能可用 | ✅ pass |
| 9 | test-callsite-inventory-display | test-callsite-inventory.md 文件正确记录迁移计划与调用点统计 | ✅ pass |
| 10 | v1-view-roundtrip-regression | v1 多视图往返切换回归：概览→配置→运维记录→概览 | ✅ pass |
| 11 | regression-spec-detail | SPEC 详情页加载回归：进入 SPEC 详情，验证标签页主体渲染 | ✅ pass |
| 12 | regression-overview-load | 概览页加载回归：验证重构后首屏统计瓦片与项目列表渲染正常 | ✅ pass |
| 13 | v1-overview-load-regression | v1 概览页加载回归（生产面未受扰实证） | ✅ pass |
| 14 | regression-v2-overview | v2 AMIS 概览页渲染回归：验证 AMIS 引擎正确渲染统计瓦片与项目面板 | ✅ pass |
| 15 | v2-overview-load | v2 概览页加载回归（AMIS 界面）：统计瓦片与项目面板零行为变化 | ✅ pass |
| 16 | v1-project-enter-spec-list | v1 进入项目 SPEC 列表（正向路径） | ✅ pass |
| 17 | v1-spec-detail-open | v1 打开 SPEC 详情（多步骤交互：概览→项目→SPEC 行） | ✅ pass |
| 18 | regression-spec-filter | 项目 SPEC 过滤器交互回归 | ✅ pass |
| 19 | spec-detail-page-refactor-test-callsites | SPEC 详情页正确展示 refactor-test-callsites 的提案与设计文档 | ✅ pass |
| 20 | alert-lifecycle-display | 告警生命周期记录正确展示 | ✅ pass |
| 21 | spec-proposal-document-display | Proposal 文档内容正确渲染，包含 Why/What Changes/Impact 章节 | ✅ pass |
| 22 | spec-design-document-display | Design 文档正确展示组件命名与迁移计划 | ✅ pass |
| 23 | spec-status-pills-display | SPEC 状态标签正确显示优先级与运行状态 | ✅ pass |
| 24 | spec-dependency-chain-display | SPEC 依赖链正确展示 refactor-core-packages 前置依赖 | ✅ pass |
| 25 | empty-state-no-runs | 无运行记录时 SPEC 详情页正确显示空状态 | ✅ pass |
| 26 | breadcrumb-navigation | 面包屑导航正确显示项目路径 | ✅ pass |

## 优先复核场景

| 场景 ID | 上轮状态 | 本轮状态 | 结论 |
|---------|----------|----------|------|
| projects-api-response-structure | warning | pass | 已收敛，无需升级裁决 |

## 裁决说明

由于全部 26 个场景均为 pass 状态，无需对任何场景补充 `classification`、`evidence` 或 `assertion_triage` 字段。

## 持久化场景集核对

持久化集共 26 个场景，本轮全部覆盖，无新增、无遗漏、无删除。

## 验证环境

- Dashboard 地址：http://127.0.0.1:8787/
- 验证时间：2026-08-31T22:11:47.632019+00:00
- SPEC 名称：refactor-test-callsites

## 本轮场景集变更

场景集与持久化集一致，无变更。

