# 验证报告：add-dashboard-incremental-data

> ⚠️ 本报告由框架于 2026-09-03T10:26:46Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 10/10 场景通过，0 失败，0 错误（全部场景通过）**

验证通过：add-dashboard-incremental-data 全部 10 个场景（summary-index-list-renders / summary-index-empty-state / search-debounce-pending / search-debounce-applied / status-filter-apply / sse-refresh-type-filter / sse-refresh-archived-toggle / connection-limit-sse-blocked-fallback / log-offset-detail-timeline-renders / overview-heartbeat-renders）均 pass，无失败断言，无 warning/error，无环境阻塞。摘要索引（SummaryIndex）驱动列表渲染、空态、搜索防抖、状态/类型/归档本地过滤、SSE 阻断降级心跳、日志偏移时间轴、概览心跳降频等能力全部按预期工作。裁决：无产品缺陷，验证通过。

| 指标 | 数量 |
| --- | --- |
| 通过 | 10 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 7.76M |
| 本链增量 Token（输出） | 0.12M |


## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| summary-index-list-renders | pass | 0/10 | - |
| summary-index-empty-state | pass | 0/5 | - |
| search-debounce-pending | pass | 0/5 | - |
| search-debounce-applied | pass | 0/8 | - |
| status-filter-apply | pass | 0/7 | - |
| sse-refresh-type-filter | pass | 0/7 | - |
| sse-refresh-archived-toggle | pass | 0/6 | - |
| connection-limit-sse-blocked-fallback | pass | 0/4 | - |
| log-offset-detail-timeline-renders | pass | 0/7 | - |
| overview-heartbeat-renders | pass | 0/5 | - |

## 本轮场景集变更

当前稳定场景集共 10 个（第 1 轮）。

- 首轮写入 10 个场景

