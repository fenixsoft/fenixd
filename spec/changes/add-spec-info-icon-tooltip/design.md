# Design: SPEC 列表信息改状态旁悬浮图标

## Context

SPEC 列表页 `core/dashboard/static/src/pages/projects/list.tsx` 现状：

- **桌面表格**（~L1583-1601）：`expandable.expandedRowRender` 在 `record.error` 非空时渲染行下信息子行——橙色「信息」Tag + 完整文本（可换行）+「清除」按钮（`onClearError` → `POST /api/spec-error-clear`）；`rowExpandable: (record) => !!record.error` 门控。
- **移动端卡片**（~L941-963）：`record.error` 非空时渲染 amber 软底信息行——橙「信息」前缀 + 单行省略文本 +「清除」按钮（stopPropagation）。
- **受控展开**（~L1920-2009）：`expandedKeys` 首次全展开（b229013a3316 闩锁）+ 增量合并已见节点记忆（81b677017e09）+ 项目切换复位（9dd9b3c6679b），同时服务树形子级与 error 信息行。
- **状态标签锚点**：桌面状态列 render（~L1106-1111）为 `<Space size={4} wrap><Pill/>{blockedPhaseMeta}<StatusWaitGroup/></Space>`；移动端语义胶囊行（~L831-862）为 `<Pill dot>` + `<StatusWaitGroup pill/>` + `<ModePill/>` + ⋮ 菜单。

界面约束来源：DESIGN.md（界面设计宪法）；dashboard-spec-table 能力页（信息子行/信息清除/名称 hover 提示条款）。本需求不偏离宪法条款，无偏离声明。

## Goals

1. 有信息的 SPEC 恢复台账单行形态，信息收敛为状态标签旁一个信息图标。
2. 悬浮（桌面）/点按（移动端）即可看到完整信息文本，可及性不降级。
3. 「信息清除」既有契约保留：清除入口仍可达、点击不触发行导航、清除后信息消失。
4. fix-* 树形展开、整行点击导航、名称 Why 悬浮、验证异常悬浮零回归。

## Decisions

- **D1 用 Popover 而非 Tooltip**：弹层内含「清除」按钮（交互内容）；antd Tooltip overlay 不承载交互（pointer-events: none 语义），Popover 内容可交互且 hover 触发下鼠标移入弹层保持可见。触发方式 `trigger={['hover', 'click']}`——桌面悬浮满足「鼠标放上去 hint」，click 兜底移动端触屏点按（无 hover 能力）。
- **D2 图标形态**：`InfoCircleOutlined`（antd 图标，形态即「i」），色取 `token.colorWarning`（对齐原「信息」Tag 的橙色语义——告警/提示中性偏警觉），14px；紧随状态 Pill / StatusWaitGroup 之后渲染于同一 `Space`/胶囊行，`record.error` 为空/null 不渲染（缺失=无该元素，非占位灰显）。
- **D3 清除迁移到弹层内**：Popover 内容 = 完整 `record.error` 文本（whiteSpace: pre-wrap、可换行、maxWidth 限宽防超宽）+「清除」small Button。按钮 onClick `stopPropagation`（图标触发器在行命中面内，防误触发行导航）后调既有 `onClearError`；清除成功后 `error` 置空 → 图标随下次渲染消失（既有刷新链路承担）。`onClearError` handler 本体零改动。
- **D4 expandable 收缩**：移除 `expandedRowRender` 与 `rowExpandable` 两键，`expandable` 保留 `columnWidth: 28`、受控 `expandedRowKeys`/`onExpandedRowsChange`——antd v5 树形表格仅凭受控 keys 即驱动 fix-* 子级展开，零回归面。受控展开三段闩锁逻辑（首次全展开/增量合并/项目复位）**代码不动**：error 行退出 keys 消费后逻辑自然子集化，树形子级语义原样保留；仅更新指向已移除信息行的过时注释（~L1927-1931、~L1981、~L1998 等「error 信息行」措辞）。
- **D5 触控目标**：移动端图标外层点按目标对齐卡片行内控件纪律（≥32px，同 ⋮ 按钮），图标视觉 14px 居中。
- **D6 弹层不阻断行点击**：Popover 经 portal 渲染于表格行外（不在 onRow 命中面），弹层内点击天然不导航；图标触发器 click 需自身 stopPropagation（D3）。
- **D7 spec 增量 header 保留旧名**：delta spec 的 requirement header 沿用基准名「SPEC 信息子行替换『错误』列」（保证 MODIFIED 合并锚点唯一），新行为以正文与 Scenario 表达（子行退役、图标 + Popover 形态）；语义真相以正文为准。

## Risks

- **行内点击面误触**：图标在行命中面内，click 触发 + stopPropagation 双保险已覆盖；评审时对「点图标不进详情」出场景实证。
- **移动端 hover 无效环境**：click 触发兜底；Popover 点开后点击弹层外区域关闭（antd 默认），不残留遮罩。
- **树形展开回归**：rc-table 受控展开对树形子级的支持是既有事实（当前 keys 同时驱动两类展开），收缩配置不新增变量；场景钉死 fix-* 展开/收起。

## Migration

纯前端展示层改动，无数据迁移、无 API 变更、无配置变更。生产 rebuild 后 dist 锚点刷新（`core/dashboard/static/dist/index.html`）。
