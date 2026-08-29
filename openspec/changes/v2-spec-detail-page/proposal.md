## Why

SPEC 详情页是排查工作面:验证结论卡、验证进度、任务清单 + 4 页签(时间轴/场景结果/Bug/失败截图)。v2 用 service + tabs 实现,时间轴用 AMIS Timeline 替代老版 React 垂直时间轴(形态可变,用户已确认),截图用 Image 网格+内建放大(计划 Task 7)。

## What Changes

- 新增 `core/dashboard/static/v2/pages/spec-detail.json`:service(spec-detail)拉 /api/specs/:project/:spec(adaptSpecDetail)+ 验证卡与清单 + 4 页签;时间轴节点点击先弹占位 Dialog(Task 8 接入 RunStream);spec-detail 监听 sse:detail(带 spec 名比对,behavior.md §0)与 sse:state
- 新增 tests/v2/spec-detail.spec.js

## Capabilities

### New Capabilities
- `v2-spec-detail-page`: SPEC 详情页(验证卡/清单/4 页签/SSE 增量刷新)

### Modified Capabilities

## Impact

- 新增 pages/spec-detail.json 与测试;依赖 v2-data-adapters、v2-shell-hash-router
- 时间轴节点点击的动作接口(带 runId 的 dialog)是 Task 8 的接入契约
