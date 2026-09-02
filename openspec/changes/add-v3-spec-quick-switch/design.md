## Context

v3 Dashboard 的 SPEC 详情页（`core/dashboard/static/v3/src/pages/projects/detail.tsx`）通过路由 `/projects/:name/:spec` 渲染，`useParams` 取 `name`（项目）与 `spec`。页面主数据加载的 `useEffect` 依赖 `[name, spec]`，SSE 订阅同样按 `(name, spec)` 过滤，因此路由参数变化即可触发完整的数据重载与订阅重建，无需额外的刷新逻辑。

服务层已有 `getSpecs(project)`（`GET /api/specs?project=`，v3 列表页在用），返回 `SpecSummary[]`，含 `name`、`status`、`priority` 等字段。状态标签渲染已有统一入口 `statusMeta()`（`services/dashboard.ts`），与 SPEC 列表页同源。

## Goals / Non-Goals

**Goals:**
- 详情页头部 SPEC 名称旁提供下拉箭头，展开后以表格形式列出其他 SPEC（名称 + 状态标签），选中即切换。
- 复用现有接口与组件体系，后端零改动。

**Non-Goals:**
- 不做下拉内搜索/过滤（项目下 SPEC 数量通常不多，用户已确认）。
- 不改动 `/api/specs` 接口与后端聚合逻辑。
- 不在列表页引入同类入口（列表页本身已是全量列表）。

## Decisions

1. **入口位置：PageContainer header 的 title 区内，SPEC 名称与状态 Tag 之后追加 Dropdown 触发箭头。**
   - 备选：面包屑区（`extra`）加独立按钮，或面包屑第三级做成可点击下拉。
   - 选择 title 区内嵌箭头：用户明确要求"在 spec 名称中加下拉箭头"；面包屑第三级当前是纯文本标题，改造成本更高且视觉动线偏右。
   - 触发器用 `Button type="text" size="small"` 内嵌 `DownOutlined`，与页面既有 `DownOutlined`（告警展开箭头）风格一致。

2. **下拉实现：Ant Design `Dropdown` + 自定义 `menu` 渲染表格样式面板。**
   - 备选 `Select`（组件内置但样式难定制为"表格"）、`Popover` + Table。
   - 选择 `Dropdown`（`popupRender`/自定义 overlay）：可自由渲染行结构（名称 + OutlinedTag/statusMeta 状态标签），满足"下拉表格形式"；`Select` 的 option 定制能力不足以呈现表格感。antd v6 下使用 `menu` 属性 + 自定义 label 或 `popupRender`，具体以组件库实际 API 为准（实现时验证）。
   - 面板宽度固定上限（约 320px），SPEC 名称过长时截断（ellipsis + title 提示）。

3. **数据获取：详情页挂载/项目变化时拉一次 `getSpecs(name)`，结果缓存于组件 state。**
   - 详情页自身已有 SSE 热更新主数据；下拉列表是低频辅助信息，不为其建立独立 SSE 通道。SPEC 增删在下拉展开那一刻以已缓存数据呈现即可接受（下一次进入详情页会刷新）。
   - 状态字段语义：`SpecSummary.status` 与 `statusMeta` 同源（列表页已验证），直接复用。

4. **切换方式：`history.push(`/projects/${name}/${targetSpec}`)`。**
   - 路由参数变化触发既有 `useEffect` 重载与 SSE 重订阅，无需新增刷新代码。Umi 的 `history.push` 与当前页 `onBack` 用法一致。

5. **降级：`getSpecs` 失败时不展示箭头（catch 中保持列表为空数组）。**
   - 不弹错误提示打扰详情页主体；与页面既有"后台刷新失败静默保留旧视图"的容错哲学一致。

## Risks / Trade-offs

- [antd v6 Dropdown 自定义面板 API 与预期不符（popupRender/menu 变体差异）] → 实现时先在浏览器中验证最小用例，必要时改用 `Popover` + 自绘面板，不影响 spec 行为要求。
- [项目下 SPEC 很多时下拉面板过高] → 面板内容区限高（如 max-height 60vh）滚动；本项目无搜索需求（用户已确认）。
- [下拉数据与实时状态不同步（SPEC 状态在停留期间变化）] → 接受该 trade-off：下拉是导航辅助，选中后详情页数据始终实时；不为其增加 SSE 订阅复杂度。
- [移动端窄屏 title 区拥挤] → 下拉面板宽度自适应视口（`max-width: calc(100vw - 32px)`），箭头按钮点击区域 ≥ 24px。

## Migration Plan

纯前端增量改动，随 v3 前端正常构建发布；无数据迁移。回滚即还原该文件改动。

## Open Questions

（无——入口形态、行内容、排除策略已在需求澄清阶段与用户对齐。）
