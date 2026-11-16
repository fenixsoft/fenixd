# add-spec-name-copy-menu — 详细设计

## Context

- 现行 v3 SPEC 列表桌面表格（`core/dashboard/static/src/pages/projects/list.tsx` DevTab）名称列为 dense 形态：英文名主行（13.5px 半粗深色单行省略）+ 中文标题副标题行（`add-spec-chinese-title`）。名称列单元格已有 Why 悬浮提示（div 悬浮层，`list.tsx:332` 段起）与整行点击进详情（`specRowClick.ts` 事件守卫）等交互。
- 历史先例：v1 dashboard 曾有行右键自绘上下文菜单（2026-09-03 `add-spec-context-menu`，自绘 div + 手写边缘翻转/关闭逻辑），随 v1 界面在 `ea88dd5a7`（移除 v1/v2 dashboard）整体退役，现行前端源码中无任何 `contextmenu` 处理。知识页 `add-spec-context-menu.md` 是陈旧残留，本 SPEC 不依赖也不复活其自绘实现。
- 剪贴板写入单源：`copyToClipboard`（`src/components/claude-msg/Markdown.tsx:26-57`，已导出）——`navigator.clipboard?.writeText` 首选，异常 fall through 到隐藏 textarea + `execCommand('copy')`（含节点清理，code-review item 8df2dd69b7bc）。dashboard 经 frp 公网纯 HTTP 访问（home.icyfenix.cn:18787）时 `navigator.clipboard` 整体缺失（非 secure context），降级路径是硬要求；既有消费先例 `ClaudeOutputPane.tsx:427`、`MessageItem.tsx:63`。
- 设计约束以仓库根 `DESIGN.md` 为准（界面设计宪法；当前摘录注入原型生成）——本 SPEC 无新增色值/圆角/留白，菜单形态复用页面既有 antd Dropdown 菜单语言（与操作列 ⋮ 菜单、overview 台账同款），天然处于宪法一般域默认法约束内，无偏离条款。

## Goals

- SPEC 标题（名称列单元格）右键弹出单项菜单「复制 SPEC 名称」，点击后英文名入剪贴板，就近取用零跳转。
- 公网 HTTP 访问下复制照常可用（复用单源降级助手）。
- 既有名称列交互与整行点击导航零回归。

## Non-Goals

- 移动端卡片流（<768px）不改动——触屏无右键语义，卡内 ⋮ 菜单已有既有入口形态，本 SPEC 不扩。
- 不复制中文标题、不做「复制路径」「复制项目名」等多菜单项扩展。
- 不为其他列（状态、优先级等）接线右键菜单。
- 不新增后端端点，纯前端交互。

## Decisions

1. **菜单实现选 antd Dropdown `trigger={['contextMenu']}` 包裹名称列单元格，不复活 v1 自绘菜单**。
   理由：页面全部菜单已是 antd Dropdown 形态（操作列 ⋮、文档菜单），`contextMenu` trigger 原生提供定位、视口边缘翻转、外点/Esc/滚动关闭，行为契约与 v1 交互契约等价但零自绘代码；自绘方案（v1 先例）需手写 mouse 坐标、翻转、全局监听清理，维护面大且无收益。备选 v1 自绘复活被否。
2. **右键目标 = 名称列单元格整体（英文名 + 中文副标题区域），不是整行**。
   理由：用户原话「在 SPEC 标题上右键」；名称列是语义命中面，其他列右键保持原生默认（见 spec Scenario）。归档视图与 fix-\* 子行共用同一名称列 render，接线单点天然覆盖。
3. **复制内容 = `record.name` 英文 id**（用户确认），不含中文标题/项目名。
   理由：英文名是全链寻址键（/fenix-process、grep、issue 引用），剪贴板取用后可直接拼接命令。
4. **剪贴板写入复用 `copyToClipboard` 导入，不在本 SPEC 内重写或搬迁该助手**。
   理由：单源纪律——该助手已带非安全上下文降级与节点清理，两个既有消费先例同一形态；搬迁属独立重构不在本 SPEC 范围。成功 `message.success('已复制 SPEC 名称')`、失败 `message.error(...)` 与页面既有提示习语一致。
5. **导航防护靠 portal 隔离，不加行级 hack**。
   理由：antd Dropdown 弹层经 portal 渲染于行命中面之外（与信息图标 Popover 同范式，`add-spec-info-icon-tooltip` 先例），菜单内点击天然不触发行导航；右键（contextmenu 事件）本身不在行 `onClick` 路径上，无需额外 stopPropagation 以外的防御。

## Risks / Trade-offs

- [antd Dropdown contextMenu trigger 与单元格内 Why 悬浮层叠加] → Why 悬浮仅在 hover 触发，右键弹出菜单不影响悬浮层生命周期；实现时确认右键菜单 z-index/portal 层级正常即可，无状态共享面。
- [非 secure context 下 execCommand 需 transient activation] → 菜单项点击在用户手势同步回调链内调用 `copyToClipboard`，满足手势窗口约束（知识页 dsh-web-clipboard-fallback 手势条款）。
- [自动刷新重绘后 Dropdown 接线丢失] → 接线在名称列 render 函数内（每行渲染时挂载），SSE/2s 刷新重绘自然重挂，无跨渲染持有的有状态句柄。
- [fast-track 单 Agent 验证面] → 降级路径无法在 127.0.0.1 直接复现，验证以 node:test 源码扫描钉死 `copyToClipboard` 复用与 contextMenu 接线 + 浏览器冒烟（右键弹菜单/复制成功/零回归）双通道覆盖，HTTP 端到端判据在 spec Scenario 留档备查。

## Migration Plan

纯前端增量改动，无数据迁移、无 API 变更；实现分支合并即生效（dashboard dist 随 SPEC 收工 rebuild），无回滚面（revert 提交即可）。
