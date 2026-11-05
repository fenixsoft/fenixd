# v2 商业化界面域（Bento 工作台）

<!-- knowledge: capability=v2-commercial-ui rev=1
     sources=spec/changes/redesign-dashboard-v2-ui -->

dashboard 的商业化观感界面域：Bento 磁贴设计语言（浅灰页底 + 白磁贴大圆角软阴影、黑主色按钮、蓝链接、语义胶囊徽标）承载概览/项目/SPEC 详情/配置/帮助/运维六页，与既有页面并存互不干扰。

## 规则

- **例外域并存**：v2 六页全部挂 `/v2/*` 路由前缀（hash 形态 `#/v2/overview` 等），与既有页面并存；本域条款只约束 v2 六页，域外页面不适用。是否切换为默认界面由用户另行裁决、另行立项。
- **路由与菜单零污染**：既有路由表条目（path/component/name/icon）逐字零改动；v2 路由条目不写 name/icon，`app.tsx` 的 menuDataRender 白名单（现产侧栏菜单单源，手写数组、不消费路由表）不新增任何 v2 条目，现产侧栏菜单逐字不变。未匹配的 `/v2/*` 路径落既有 `*` 兜底重定向，不影响既有路由匹配。routes 快照守卫测试（`tests/v2RoutesGuard.test.mjs`）钉死上述全部断言。
- **原型为 UI 真相源**：六页布局、组件选型、信息架构以定稿原型（`spec/changes/redesign-dashboard-v2-ui/prototype/` 六张单文件 HTML：variant-b-bento.html=概览、project-detail.html、spec-detail.html、settings.html、help.html、ops.html，附 screenshots/ 渲染凭证）为准，与「数值以 Scenario 为准」同纪律等级；实现与原型冲突不得擅自偏离，须升级用户裁决。
- **真实数据消费**：复用 `services/dashboard.ts` 既有 API 客户端与类型，消费与既有页面相同的 `/api/` 端点，不内联原型假数据、不新增后端端点；接口缺口按既有端点语义最小适配。缺口字段渲染「—」不伪装 0；无数据源的分面渲染占位说明、如实声明。数据刷新走 30s 心跳轮询，不接现产 SSE 合帧（开发期简化口径）。
- **主题单源分立**：v2 页面颜色、圆角、控件形态只准取自 `src/pages/v2/theme.tsx` 单源（Bento token 常量 + antd 主题表 + V2ConfigProvider 局部包裹，只作用于 v2 六页子树；locale 由根 ConfigProvider 下传）。v2 域不引用现产 theme.ts，v2 域外任何页面不得引用 v2 主题——两域配色各自单源、互不引用。
- **Bento token 基线**：页底浅灰 #f8fafc；白磁贴 radius 16 + 软阴影 + 细边框；徽标胶囊 radius 999；控件圆角 12/8；主按钮与 ACTIVE 分段按钮黑 #0f1115（hover #43454a / active #2c2c2e）白字；链接与输入焦点蓝 #4176e6；语义色 success #22c55e / error #dc2626 / warning #d97706；阶段进度 ramp 出题青 #0891b2 / 实现蓝 #2563eb / 门禁橙 #ea580c / 验证绿 #16a34a；活跃 Agent 堆叠条用 V2_LANE_COLORS 数据编码色板；文字四阶 slate；数字排版 tabular-nums（.v2-num）。
- **表格防撑坏**：表格 fixed 布局 + 首列 14px 缩进 + 长文本 pre-wrap 换行（.v2-bento-table）；长文本（≥200 字注释、≥300 字告警明细）不得横向撑破容器。
- **页面壳与标题带例外**：v2 页跳过 PageContainer 与全站统一标题栏形态基准，V2Page 壳自带全出血页底与 24px 内容边距（.v2-inner 1400px 居中）；六页自绘标题带（大标题 + 返回箭头 + 运行中/模式/状态徽标 + 右侧富组合）。PageContainer 页头适用全站退役约定（`title={false}`），避免 ProLayout 从路由上下文兜底渲染双标题。上述偏离已在 DESIGN.md 例外域偏离清单显式登记，按已声明偏离对待、不判违规。
- **静态渲染红线适用**：v2 域适用全站静态渲染红线——零装饰动效；antd 组件默认微交互不在此列。
- **宪法例外域条款**：DESIGN.md 设「例外域：v2 商业化界面域」小节（用途声明 + 域专属 token 表 + 与一般域偏离清单），既有条款不回溯改动；v2 域界面争议以该小节与定稿原型为准。

## 关键行为

- 概览（/v2/overview）：4 卡等宽 KPI 磁贴（SPEC 总数 / 任务进度圆环 / Token 消耗 / 活跃 Agent 堆叠条）+ 告警横幅（多行明细 + 内嵌裁决选择题）+ 项目台账表格（名称搜索、运行中分段过滤、行点击进项目详情、行三点下拉 停止/安装托管/删除、删除带 antd 确认框）。
- 项目详情（/v2/projects/:name）：标题带（返回 + 运行中徽标）+ 四页签（功能开发实体渲染；代码审查/测试回归/会话接入项目级数据缺口，先占位说明）+ SPEC 表真实列集（状态/模式/名称/优先级/创建时间/任务进度/验证/耗时/操作·仅三点），行点击进 SPEC 详情。
- SPEC 详情（/v2/projects/:name/:spec）：标题带（模式/状态徽标 + 状态转移入口）+ 项目信息 8 项（优先级/创建时间/更新时间/依赖/输入 Token/输出 Token/耗时/成本）+ 任务清单大百分比卡（已完成 N/M + 勾选任务）+ 五页签（运行时间轴含立项原话与 run 元数据/场景结果/Bug 列表/测试截图/Hook），信息架构对齐现产 SPEC 详情数据结构。
- 配置（/v2/settings）：左侧分面菜单 + 作用域切换（用户级/项目级，切换重拉 `/api/config?project=`，开关行 aria 作用域标注同步）+ 实体面板（模型与网关 Provider 表、真实 config 开关行，零写操作）；未实体化分面渲染占位说明。
- 帮助（/v2/help）：分组目录（sticky）+ Markdown 正文双栏，目录项选中态与 aria-current 同步切换。
- 运维（/v2/activities）：头部统计条四项真实口径（待处理告警/在飞链/升级中/配额耗尽）+ 三页签（人工告警含裁决选择题、处置链观测三段计数实体渲染；自愈记录暂无数据端点，占位说明）。

## 溯源

- 2026-11-05 redesign-dashboard-v2-ui（spec/changes/redesign-dashboard-v2-ui/） — 新建本页：/v2/* 六页 Bento 化落地；登记路由/菜单隔离、主题单源分立互不引用、原型 UI 真相源、真实 API 消费与缺口「—」口径、30s 心跳轮询、DESIGN.md 例外域条款；项目详情后三页签、配置页未实体化分面、运维自愈记录分面为占位说明态
