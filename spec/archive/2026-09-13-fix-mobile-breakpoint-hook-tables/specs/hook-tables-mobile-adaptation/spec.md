## ADDED Requirements

### Requirement: HookManager 三表容器内横滚兜底
HookManager 的三张 antd Table（生效合并表、Hook CRUD 表、最近执行审计表）SHALL 各自配置 `scroll={{ x: 'max-content' }}`，使表格溢出内容限制在表格自身容器（`.ant-table-content`）内横向滚动。任何视口宽度下页面整体（`document.scrollingElement`）SHALL NOT 出现由这三张表格引起的横向滚动。

#### Scenario: 390px 视口下整页不横滚
- **WHEN** 390×844 视口打开 spec 详情页 Hook 页签（生效合并表列宽合计 1055px）
- **THEN** `document.scrollingElement.scrollWidth` 等于 390，页面无横向滚动；表格容器自身可横向滑动查看全部列

#### Scenario: 设置页项目作用域 Hook 面板同受兜底
- **WHEN** 390px 视口在设置页切换到项目级作用域并打开 Hook 面板
- **THEN** 页面 `scrollWidth` 等于 390，「最近执行」等表格在容器内横滚，不再出现列头一字一行竖排的挤压形态

#### Scenario: PC 端表格渲染不变
- **WHEN** 视口宽度 ≥768px 且内容区宽度足够容纳表格
- **THEN** 三张表格的列数、列宽、无横向滚动条的表现与改动前一致

### Requirement: HookManager 移动端卡片化渲染
HookManager SHALL 自持 `useIsMobile()`（同步 matchMedia，与既有 hook 一致），在 <768px 视口下将三张 Table 分支渲染为卡片 List（复用 `pages/projects/list.tsx` SpecCardList 的结构范式：`List.Item` 内包裹 `width: '100%', minWidth: 0` 的 div）。卡片字段 SHALL 与桌面表格列一一对应，复用组件内既有常量（`EVENT_LABELS`、`HOOK_ACTION_LABELS`、`paramSummary`）与既有交互 handler（启停 / 编辑 / 删除）。PC 端（≥768px）SHALL 保持既有 Table 渲染路径不变。两个消费方（spec 详情 Hook 页签、设置页 HooksPanel）的组件接口 SHALL 零改动。

#### Scenario: 生效合并卡字段完整
- **WHEN** 390px 视口打开含生效 Hooks 的 spec 详情 Hook 页签
- **THEN** 每条生效 Hook 以卡片呈现：来源标注 Tag、事件 Tag 列表（可换行）、动作名称、启用/停用状态 Tag、参数全文（不截断、可换行）

#### Scenario: CRUD Hook 卡交互保留
- **WHEN** 390px 视口下 Hook 列表存在可编辑 Hook（未到终态）
- **THEN** 卡片上启停 Switch 可切换且立即保存生效；编辑按钮打开既有 Modal 且表单回填正确；删除按钮经 Popconfirm 确认后删除

#### Scenario: 终态只读形态
- **WHEN** 390px 视口打开已推送（终态）spec 的 Hook 页签
- **THEN** 卡片不呈现编辑/删除入口，Switch 置灰不可操作，页面保留「SPEC 已推送（终态），订阅不再变化，仅供查看」提示

#### Scenario: 审计卡信息完整
- **WHEN** 390px 视口查看「最近执行」审计卡片
- **THEN** 每卡呈现执行时间、结果 Tag、SPEC 名、动作、耗时与摘要全文（pre-wrap 换行，不截断）

#### Scenario: PC 端交互路径不变
- **WHEN** 视口宽度 ≥768px 打开 Hook 页签
- **THEN** 三张表格按既有 Table 渲染，启停/编辑/删除经表格内控件操作，行为与改动前一致
