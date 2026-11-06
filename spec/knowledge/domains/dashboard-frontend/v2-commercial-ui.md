# v2 商业化界面域（Bento 工作台）

<!-- knowledge: capability=v2-commercial-ui rev=3
     sources=spec/changes/redesign-dashboard-v2-ui,spec/changes/redesign-dashboard-v2-ui-mobile,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md -->

dashboard 的商业化观感界面域：Bento 磁贴设计语言（浅灰页底 + 白磁贴大圆角软阴影、黑主色按钮、蓝链接、语义胶囊徽标）承载概览/项目/SPEC 详情/配置/帮助/运维六页的桌面与移动双形态，与既有页面并存互不干扰。

## 规则

- **例外域并存**：v2 六页全部挂 `/v2/*` 路由前缀（hash 形态 `#/v2/overview` 等），与既有页面并存；本域条款只约束 v2 六页，域外页面不适用。是否切换为默认界面由用户另行裁决、另行立项。
- **路由与菜单零污染**：既有路由表条目（path/component/name/icon）逐字零改动；v2 路由条目不写 name/icon，`app.tsx` 的 menuDataRender 白名单（现产侧栏菜单单源，手写数组、不消费路由表）不新增任何 v2 条目，现产侧栏菜单逐字不变。未匹配的 `/v2/*` 路径落既有 `*` 兜底重定向，不影响既有路由匹配。routes 快照守卫测试（`tests/v2RoutesGuard.test.mjs`）钉死上述全部断言。
- **原型为 UI 真相源（双形态分立）**：六页布局、组件选型、信息架构按视口形态分立定源——桌面形态（≥768px）以 redesign-dashboard-v2-ui 定稿原型为准（`spec/changes/redesign-dashboard-v2-ui/prototype/` 六张单文件 HTML：variant-b-bento.html=概览、project-detail.html、spec-detail.html、settings.html、help.html、ops.html，附 screenshots/ 渲染凭证）；移动形态（<768px）以 redesign-dashboard-v2-ui-mobile 定稿原型为准（`spec/changes/redesign-dashboard-v2-ui-mobile/prototype/` 六张 m-*.html：m-overview.html、m-project-detail.html、m-spec-detail.html、m-settings.html、m-help.html、m-ops.html，附 screenshots/ 渲染凭证）。与「数值以 Scenario 为准」同纪律等级；实现与原型冲突不得擅自偏离，须升级用户裁决。
- **真实数据消费**：复用 `services/dashboard.ts` 既有 API 客户端与类型，消费与既有页面相同的 `/api/` 端点，不内联原型假数据、不新增后端端点；接口缺口按既有端点语义最小适配。缺口字段渲染「—」不伪装 0；无数据源的分面渲染占位说明、如实声明。数据刷新走 30s 心跳轮询，不接现产 SSE 合帧（开发期简化口径）。
- **主题单源分立**：v2 页面颜色、圆角、控件形态只准取自 `src/pages/v2/theme.tsx` 单源（Bento token 常量 + antd 主题表 + V2ConfigProvider 局部包裹，只作用于 v2 六页子树；locale 由根 ConfigProvider 下传）。v2 域不引用现产 theme.ts，v2 域外任何页面不得引用 v2 主题——两域配色各自单源、互不引用。
- **跨域消费=镜像不引用**：域外页面消费 v2 视觉的唯一方式是复制组件 + 镜像色值（overview 侧 `OV_*` 常量与 global.less `.ov-*` 规则族、指挥中心 `shared.ts` `CARD_FRAME_*` 镜像 `theme.tsx` 等），镜像值注释标注源并以「两处同改」纪律维护；MUST NOT import `@/pages/v2/*`（例外域条款钉死域外禁引用，pageChrome 守卫拦截跨域 import）。
- **筛选形态分叉**：v2 域自身运行态筛选保持 `.v2-chip` 胶囊形态；overview 侧运行态筛选为 Radio 按钮组黑底白字（`.ov-radio-dark`）——分叉系用户指令（只撤 overview 侧胶囊），v2 域不随动对齐。
- **Bento token 基线**：页底浅灰 #f8fafc；白磁贴 radius 12（`V2_TILE_RADIUS`，v2.less 镜像同值）+ 软阴影 + 细边框——该值即 DESIGN.md 通用条款「Bento 磁贴圆角固定 12px」，全站 Bento 磁贴统一 12px，v2 theme.tsx / v2.less / overview 镜像 `.ov-bento` / overview 统计卡豁免规则四处同值，pageChrome 守卫钉值（v2 常量钉值守卫走源码正则，node:test 无法 import .tsx，不 import theme.tsx）；徽标胶囊 radius 999 与 v2 控件圆角 12/8、一般域 antd 控件圆角 6/4/8 条款均不受磁贴条款影响；主按钮与 ACTIVE 分段按钮黑 #0f1115（hover #43454a / active #2c2c2e）白字；链接与输入焦点蓝 #4176e6；语义色 success #22c55e / error #dc2626 / warning #d97706；阶段进度 ramp 出题青 #0891b2 / 实现蓝 #2563eb / 门禁橙 #ea580c / 验证绿 #16a34a；活跃 Agent 堆叠条用 V2_LANE_COLORS 数据编码色板；文字四阶 slate；数字排版 tabular-nums（.v2-num）。
- **移动断点单源**：移动形态判定收进 v2 主题单源——`src/pages/v2/theme.tsx` 定义断点 token `V2_MOBILE_MAX_WIDTH = 767.98`（与现产 `hooks/useIsMobile.ts` 的 `(max-width: 767.98px)` 同界，`pages/v2/v2.less` 的 `@media` 镜像同值）并导出 `useV2IsMobile` 形态判定 hook，六页统一消费；v2 域 tsx 零散落 matchMedia 调用、除 theme.tsx 外零 767.98 魔法数。
- **双形态分支**：桌面/移动两形态在页组件内按断点分支渲染，分支收敛在布局容器级，卡片/行级组件抽为子件两形态复用；数据层共享，零新路由、零新 API。≥768px 桌面形态对照 redesign-dashboard-v2-ui 原型零回归，两形态零交叉污染。
- **移动端头部入口收敛**：移动端六页头部不渲染 新建 SPEC、状态转移、搜索 三入口（桌面保留），对应动作由列表页/桌面端承载。
- **移动端越界与触控**：移动形态无横向滚动越界（body scrollWidth ≤ 视口宽）；操作按钮/入口触控目标可用（≥28px 控件 + 命中区 ≥32px，复用 global.less 移动端作用域 `.touch-expand` 工具类，对齐仓库触控目标约定）。
- **移动端信息密度**：移动形态长文本（≥200 字注释/告警明细）换行完整呈现（pre-wrap），不截断伪装；数值口径缺口按「—」占位约定渲染。
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

移动形态（<768px，390px 基准，UI 真相源为移动版定稿原型）：

- 概览：KPI 四磁贴转 2×2 网格（桌面任务进度圆环与「按类型分布」徽标不渲染）+ 告警胶囊卡（单条摘要 + 去处置/标记已处理双按钮 + 收起/展开渐进披露，次级告警行内嵌裁决 Select 与 pre-wrap 长明细）+ 项目台账转堆叠项目卡（搜索过滤、点击进项目详情）。
- 项目详情：状态/模式筛选双下拉（桌面搜索 SPEC 输入框与 Radio 组不渲染）+ SPEC 表格转卡片流（名称 + 状态/模式/验证胶囊 + 阶段进度 + 耗时）+ 无新建按钮。
- SPEC 详情：标题行换行收纳 + 无状态转移/更多操作入口 + 项目信息单列键值行（八项齐备）+ 页签短标签（时间轴/场景/Bug/截图 N/Hook）。
- 配置：左菜单转横向滑动胶囊菜单（ACTIVE 黑底）+ Provider 堆叠卡（含健康检测入口）+ 开关行；作用域切换仍触发 `/api/config?project=` 重拉。
- 帮助：目录抽屉化（标题行「目录」按钮开 Drawer，选中目录项即收）+ 无搜索入口 + 正文单列。
- 运维：统计条转 chips（四项口径不变）+ 表格转堆叠卡（处置链卡替代桌面表格；人工告警堆叠卡：裁决 Select 全宽 + 执行/标记已处理双按钮行）。

## 溯源

- 2026-11-05 redesign-dashboard-v2-ui（spec/changes/redesign-dashboard-v2-ui/） — 新建本页：/v2/* 六页 Bento 化落地；登记路由/菜单隔离、主题单源分立互不引用、原型 UI 真相源、真实 API 消费与缺口「—」口径、30s 心跳轮询、DESIGN.md 例外域条款；项目详情后三页签、配置页未实体化分面、运维自愈记录分面为占位说明态
- 2026-11-05 redesign-dashboard-v2-ui-mobile（spec/changes/redesign-dashboard-v2-ui-mobile/） — 修改本页：六页叠加 <768px 移动形态——原型 UI 真相源改写为桌面/移动双形态分立（移动以本 SPEC prototype/m-*.html 为准）、新增移动断点单源（V2_MOBILE_MAX_WIDTH 与现产 useIsMobile 同界 + useV2IsMobile 六页统一消费）、双形态页内布局容器级分支（数据层共享、零新路由零新 API）、移动端头部 新建 SPEC/状态转移/搜索 三入口收敛、越界与触控目标门、移动端信息密度门
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 修改本页：Bento 白磁贴圆角改 12px（DESIGN.md 通用条款全站统一，四处同值守卫钉值）、新增跨域镜像不引用消费纪律与 overview/v2 筛选形态分叉条款（v2 侧 .v2-chip 胶囊不随动）、登记 node:test 禁 import .tsx 的守卫习语
