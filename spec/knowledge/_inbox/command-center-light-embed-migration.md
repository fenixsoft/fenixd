# 指挥中心黑改白 + 去脱壳嵌入，退出大屏例外域

## 背景

2026-11-04 用户直接指令调整指挥中心 UI：①黑色风格改白色；②不再以弹窗式全屏（脱壳）打开，改为与其他页面一样在 ProLayout 内容区打开；③为适应内容区宽度，Agent 卡片缩为原宽度 90%。原 `add-command-center`（2026-10-31）确立的「脱壳全屏深色大屏 + IOC 暗色控制台风格」形态整体退役。用户在澄清问答中确认：「智慧中心」即指挥中心页（/command-center）本身。

## 结论（当前事实，折叠主体）

**`command-center-console-ui` 能力页改写素材**：

- **页面形态**：路由 `/command-center` 已去 `layout:false`，改为 ProLayout 内容区常规页（侧栏/顶栏/PageContainer 页头与全菜单一致；routes.ts 注册 `name: '指挥中心'`，PageContainer 显式传 `header.title`——与 overview/settings 同款传参习语）。菜单项仍由 app.tsx `menuDataRender` 注册，routes name 仅供 PageContainer 标题链路。
- **配色单源**：页级暗色 ConfigProvider（darkAlgorithm + `colorBgBase '#000'`）与 html/body 纯黑注入、深色滚动条样式整体删除；页面继承 app.tsx rootContainer 的 `dshAlignedTheme`（白底/黑主色 #0f1115/蓝链接 #4176e6）。`pages/command-center/shared.ts` 色板常量（BG/PANEL_BORDER/TEXT_MAIN/TEXT_SUB/CARD_BG/ACCENT/GREEN/LINK_STROKE 及 badge 函数族）全部改挂 theme.ts dsh 常量派生（`from '../../theme.ts'`，type-stripping 直载兼容、`allowImportingTsExtensions` 先例 mermaidInit.ts）。原「严肃企业风格硬约束」条中「暗色控制台风格」「复用 antd 暗色 token」两句失效；「无插画/无动画角色/无装饰性动效」红线与静态渲染红线继续有效。
- **Agent 卡缩宽**：LaneCard 固定宽 310→279px（用户指令 90%），单源常量 `shared.LANE_CARD_WIDTH=279` + 守卫测试。汇报线 SVG 按 DOM 实测坐标绘制，随卡宽自动重算，无需另行适配。
- **定高滚动模型保持**：组织总览/交付流水线仍走「容器定高+屏内滚动」（org 双向滚动、pipeline 赛道内滚），定高扣减值从 `100vh-78px`（纯页签区）换为 `100vh-SCREEN_CHROME_OFFSET`（壳层 chrome 口径），`SCREEN_CHROME_OFFSET=182`（1920×1080 playwright 实拍校准：容器 top=182、底缘恰贴视口底缘零溢出；ProLayout 顶栏+PageContainer 页头+页面 padding-top 8+页签条）。页头结构任一变化须复核并重新实拍。
- **页面白底化后的平铺纪律**：各屏加载/错误占位框（ScreenStates）按 11-04 平铺方向去描边/底色；LaneCard/团队卡/流水线列/KPI 条为**数据卡**保留描边（0.10 档，同 overview 统计卡豁免习语）。global.less 去边框规则作用域注释已同步（指挥中心入 `.ant-pro-page-container` 作用域但页内无 `.ant-card`，不受影响）。
- **DESIGN.md 例外域条款已同步**：大屏域成员收缩为 spec-topology 一项；原「深蓝黑四色单源」域专属 token 表随指挥中心迁移退役（历史值见 spec/archive/2026-10-31-add-command-center）。
- **交互与数据面零变化**：三 Tab 结构、URL 深链（project/window/spec/spec_project 参数）、60s 静默轮询、时间窗/项目筛选、钻取跳转、运行记录弹窗全部保留。

## 证据

- 实现：`config/routes.ts`（去 layout:false）、`src/pages/command-center/index.tsx`（PageContainer 嵌入壳）、`shared.ts`（theme.ts 单源配色 + LANE_CARD_WIDTH/SCREEN_CHROME_OFFSET）、`OrgGrid.tsx`/`PipelineBoard.tsx`（定高口径）、`ScreenStates.tsx`（平铺占位）。
- 守卫：`tests/commandCenter.test.mjs` 新增 5 守卫（卡宽 279 单源/视口扣减 182 单源/配色挂 theme.ts/routes 禁 layout:false 回潮/index 禁 darkAlgorithm 与 html,body 注入）+ 徽标配色断言跟随换版。
- 验证：node --test 340/340 过；`npm run build` 后 8787 直连 playwright 实拍三屏白底形态（.history/cc-white-{org,pipeline,ledger}.png），容器几何 eval 实测 bottom=1080=innerHeight；控制台零错误。
- 改版无 SPEC（用户直接指令小改，brainstorm 确认后当轮交付）。
