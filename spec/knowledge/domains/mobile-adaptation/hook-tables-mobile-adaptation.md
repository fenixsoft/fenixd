<!-- knowledge: capability=hook-tables-mobile-adaptation rev=1 sources=spec/archive/2026-09-13-fix-mobile-breakpoint-hook-tables -->

# Hook 表格移动端适配

HookManager 三张表格（生效合并表、Hook CRUD 表、最近执行审计表）的移动端呈现契约：宽表格容器内横滚兜底 + 窄屏卡片化渲染，任何视口下整页不横向滚动。

## 规则

- 容器内横滚兜底：三张 antd Table 各自配置 `scroll={{ x: 'max-content' }}`，溢出内容限制在表格自身容器（`.ant-table-content`）内横向滑动；任何视口宽度下页面整体（`document.scrollingElement`）不出现由这三张表格引起的横向滚动。
- 移动端卡片化：HookManager 自持 `useIsMobile()`（同步 matchMedia），<768px 视口下三张 Table 分支渲染为卡片 List（复用 `pages/projects/list.tsx` SpecCardList 的结构范式：`List.Item` 内包裹 `width: '100%', minWidth: 0` 的 div）；≥768px 保持 Table 渲染路径不变。
- 卡片字段与桌面表格列一一对应，复用组件内常量（`EVENT_LABELS`、`HOOK_ACTION_LABELS`、`paramSummary`）与交互 handler（启停 / 编辑 / 删除）。
- 组件接口稳定：两个消费方（spec 详情 Hook 页签、设置页 HooksPanel）仅经组件 props 传递，接口零改动。
- 终态只读形态：已推送（终态）spec 的 Hook 卡片不呈现编辑/删除入口，启停 Switch 置灰不可操作，页面保留「SPEC 已推送（终态），订阅不再变化，仅供查看」提示。

## 关键行为

- 生效合并卡：来源标注 Tag、事件 Tag 列表（可换行）、动作名称、启用/停用状态 Tag、参数全文（不截断、可换行）。
- CRUD Hook 卡：启停 Switch 切换后立即保存生效；编辑按钮打开编辑 Modal 且表单回填正确；删除按钮经 Popconfirm 确认后删除。
- 审计卡：呈现执行时间、结果 Tag、SPEC 名、动作、耗时与摘要全文（pre-wrap 换行，不截断）。

## 溯源

- 2026-09-13 fix-mobile-breakpoint-hook-tables — 建立三表容器内横滚兜底（`scroll.x: max-content`）与 <768px 卡片化渲染分支（PC 端 Table 路径不变）
