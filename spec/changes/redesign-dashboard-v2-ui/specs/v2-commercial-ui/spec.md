# v2-commercial-ui Specification

## ADDED Requirements

### Requirement: /v2/ 前缀路由隔离

v2 页面族全部挂载在 `/v2/*` 路由前缀下（hash 路由形态 `#/v2/overview` 等），开发期间与既有页面并存；既有路由表条目、既有页面组件与渲染行为 MUST NOT 发生任何改动。

#### Scenario: v2 概览页经前缀访问

- **WHEN** 浏览器访问 `#/v2/overview`
- **THEN** 渲染 v2 概览页（Bento 语言），既有 `#/overview` 页面仍渲染原版组件

#### Scenario: 既有路由零改动

- **WHEN** 对照路由表快照（`config/routes.ts` 既有条目）
- **THEN** 既有条目（`/overview`、`/projects/:name`、`/projects/:name/:spec`、`/settings`、`/activities`、`/help` 等）的 path、component、name、icon 全部不变

#### Scenario: v2 未匹配路径回退

- **WHEN** 访问未实现的 `/v2/*` 路径
- **THEN** 渲染占位页或回退既有兜底，MUST NOT 影响既有页面路由匹配

### Requirement: 六页面按定稿原型实现

界面原型（UI 真相源）：`spec/changes/redesign-dashboard-v2-ui/prototype/`（6 张单文件 HTML：variant-b-bento.html=概览、project-detail.html、spec-detail.html、settings.html、help.html、ops.html；渲染凭证 screenshots/*.png）。

相关页面布局、组件选型、信息架构 **界面以 prototype/ 为准**（与「数值以 Scenario 为准」同纪律等级；实现与原型冲突 MUST NOT 擅自偏离，MUST 升级用户裁决）。

- 概览（/v2/overview）：4 卡等宽 KPI（SPEC 总数/任务进度圆环/Token 消耗/活跃 Agent 堆叠条）、告警横幅（多行明细 + 内嵌裁决选择题）、项目台账表格（fixed 布局、首列 14px 缩进、长注释换行）
- 项目详情（/v2/projects/:name）：标题带（返回+运行中徽标）+ 页签（功能开发/代码审查/测试回归/会话接入）+ 真实列集（状态/模式/名称/优先级/创建时间/任务进度/验证/耗时/操作·仅三点）
- SPEC 详情（/v2/projects/:name/:spec）：标题带（模式/状态徽标+状态转移下拉）+ 项目信息 8 项 + 任务清单（大百分比+勾选任务）+ 页签（运行时间轴/场景结果/Bug 列表/测试截图/Hook），时间轴节点含 run 元数据（模型/成本/耗时/结果文件/涉及文件）
- 配置（/v2/settings）：左侧菜单 + 作用域切换（用户级/项目级）+ 面板（Provider 表格、开关行）
- 帮助（/v2/help）：分组目录（sticky）+ Markdown 正文双栏
- 运维（/v2/activities）：头部统计条 + 页签（人工告警含裁决选择题/处置链观测/自愈记录）

#### Scenario: 概览页布局以原型为准

- **WHEN** 实现 /v2/overview
- **THEN** 页面布局与组件选型以 prototype/variant-b-bento.html 为 UI 真相源（冲突须升级用户裁决）

#### Scenario: SPEC 详情以真实页面信息架构为准

- **WHEN** 实现 /v2/projects/:name/:spec
- **THEN** 信息架构（项目信息 8 项、任务清单、五页签、时间轴 run 元数据）对齐现产 SPEC 详情页数据结构，视觉以 prototype/spec-detail.html 为准

#### Scenario: v2 页面消费真实 API

- **WHEN** v2 任一页面加载数据
- **THEN** 消费与既有页面相同的 `/api/` 端点（真实数据），MUST NOT 内联原型假数据；接口缺口按既有端点语义最小适配，不新增后端端点

### Requirement: v2 设计语言单源

v2 页面颜色、圆角、控件形态取自新增的 v2 主题单源常量（独立文件，不修改现产 theme.ts）：页面底 #f8fafc、白磁贴 radius 16 + 软阴影、主按钮/ACTIVE 分段按钮黑 #0f1115（hover #43454a / active #2c2c2e）、链接与输入焦点蓝 #4176e6、语义色 success #22c55e / error #dc2626 / warning #d97706、阶段进度 ramp（出题青 #0891b2 / 实现蓝 #2563eb / 验证绿 #16a34a）、徽标胶囊 radius 999。

#### Scenario: 主按钮与分段按钮 ACTIVE 黑底

- **WHEN** 渲染 v2 页面任一 primary 按钮或选中分段按钮
- **THEN** 黑底白字 #0f1115；链接色保持蓝 #4176e6

#### Scenario: 表格布局防撑坏

- **WHEN** v2 表格单元格出现长文本（≥200 字注释、≥300 字告警明细）
- **THEN** `table-layout: fixed` + 内容换行（pre-wrap）呈现，MUST NOT 出现表格横向撑破容器

### Requirement: DESIGN.md 同步重生成

本次页面样式修改 MUST 同步输出新的 DESIGN.md：按修正案程序新增「例外域：v2 商业化界面域」小节（用途声明 + 域专属 token + 与一般域偏离清单），既有条款不回溯改动；SPEC 设计文档含偏离声明段。

#### Scenario: v2 例外域小节落地

- **WHEN** 本 SPEC 实现合入
- **THEN** DESIGN.md 例外域章节含「v2 商业化界面域」小节，登记 Bento 语言 token 表与偏离清单（大圆角 16/胶囊 999/黑主色/浅灰页底），出处标注本 SPEC 与 prototype/ 路径

#### Scenario: 既有域不受影响

- **WHEN** 对照 DESIGN.md 既有条款
- **THEN** 一般域与大屏域条款文本不变，仅新增 v2 小节

### Requirement: 构建与交付

#### Scenario: 构建通过

- **WHEN** 执行 `npm run build`
- **THEN** 构建成功，dist 产物含 v2 路由 chunk

#### Scenario: 交付物对账

- **WHEN** 收工守卫按 tasks.md Deliverables 声明对账
- **THEN** 声明的 new/modify 文件在实现分支全部存在
