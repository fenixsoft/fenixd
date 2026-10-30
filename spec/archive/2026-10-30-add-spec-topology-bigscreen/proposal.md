# Proposal: add-spec-topology-bigscreen

## Why

管理层推动 AI-Native 组织建设，需要向管理层展示「各 AI Agent 像人类 SDLC 角色一样分工协作」完成一个 SPEC 的全过程。当前 dashboard 的 SPEC「运行时间轴」（`SpecTimeline.tsx`）是线性审计流水账，无法呈现 Agent 间协作拓扑，也不具备 IOC 大屏的汇报形态。

## What Changes

- 后端新增只读拓扑派生端点 `GET /api/specs/<spec>/topology`（与 `/api/specs/<spec>` detail 同族单键寻址）：以既有 timeline/runs 数据源为唯一输入，派生 nodes/edges/kpis（含角色归列、attempt 链归并、KPI 口径、多轮验证、交付闸门自适应、归档降级骨架）
- 前端新增「脱壳」全屏深色大屏页面（路由 `/projects/:name/:spec/topology`，无 dashboard 框架），含两个切换式视图：
  - **管线视图**：左→右 7 阶段列（需求/规划/开发/审查修复/测试验证/运维/交付）的分层 DAG，用户/fenix-new 与 PMEngine 为特殊节点
  - **协作时序视图**：角色泳道 × 真实时间轴，run 色块宽度=耗时，跨泳道箭头=交接
- SPEC 列表「更多」菜单新增「协作拓扑」导航项（桌面表格与移动卡片同源 `specMenuItems`）
- `SpecTimeline.tsx` 状态着色/角色映射**等价纯迁移**至共享常量模块（渲染输出严格等价）
- 节点下钻复用现有运行记录弹窗（`RunRecordModal`/`ClaudeOutputPane`）；SSE 失效重拉；跨视图联动高亮

## Capabilities

### New Capabilities

- `topology-derivation` — 后端拓扑派生与只读端点：角色归列、KPI 口径、重试边、多轮验证、闸门自适应、归档降级
- `topology-bigscreen-ui` — 脱壳大屏前端：入口、双视图、切换联动、下钻、实时刷新、零改动红线

### Modified Capabilities

（无——既有 spec-timeline 能力行为零变更，仅等价迁移内部实现）

## Impact

- **影响代码**：`core/dashboard/routes/`、`core/dashboard/server.py`、`core/dashboard/data/`、`core/dashboard/static/src/pages/projects/`、`core/dashboard/static/src/services/dashboard.ts`、`core/dashboard/static/config/routes.ts`
- **零改动红线**：detail 页面行为、归档链路（`archive_spec_runs`）、现有页面视觉/交互均不变；`SpecTimeline.tsx` 仅允许等价迁移
- **无新增配置项**、无数据迁移、无破坏性变更
