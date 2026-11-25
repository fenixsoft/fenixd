## Context

add-dashboard-dark-theme 已交付（pushed），深档验收暴露四处视觉缺陷。本设计基于 2026-11-25 在独立访问（127.0.0.1:8787，localStorage `fenix.theme=dark`）的活体实测与计算样式取证。

复现配方（验收与回归共用）：dashboard 8787 → 设 `fenix.theme=dark` → 刷新；查看 ①`#/projects/fenixd` 页头导航页签 ②`add-dashboard-dark-theme` 详情任务清单 ③详情「验证→运行时间轴」。

宿主深色对齐基线不变：dsh web 深调色板（theme.ts DSH_*_DARK 族，D2 映射表）；DESIGN.md 条款全部有效（配色单源红线=界面颜色只准取自 theme.ts/antd 语义 token；静态渲染红线=禁动画；圆角红线=MUST NOT 挂 borderRadius 覆写）。

## Findings（实测取证）

### F1 主色族未切档（缺陷①④根因，影响面最大）

- `config/defaultSettings.ts` 恒定 `navTheme:'light'` + `colorPrimary:'#0f1115'`，不随档。
- ProLayout（@ant-design/pro-components）内部按布局分区自建 ConfigProvider scope（实测 `css-var-_r_1_` 主内容、`_r_4_` 侧栏、`_r_h_` 顶栏，共 161+ 元素挂 scope class），这些 scope 用浅档种子重算主色族。
- 实测深档变量：主内容/侧栏 scope `--ant-color-primary=#101115`（=浅档 #0f1115 经 antd 处理；应 #f9fafb）、`--ant-color-link=#6b94dc`（=浅档 #4176e6 的深算法派生；应 #7aaaff）；同 scope `--ant-color-text=#f9fafb`/`--ant-color-bg-container=#232324`/`--ant-color-bg-layout=#151517` 已正确（显式 token 直达的键都对，缺的是被 ProLayout scope 重算的派生族）。
- 可见故障：antd Tabs `itemSelectedColor`/`inkBarColor` 缺省取 colorPrimary → 选中页签文字与墨条深底近隐（项目页导航、SPEC 详情子页签两处实证）；复选框/进度条等主色族消费面取 muddy 派生蓝非 #7aaaff。
- 既有先例：theme.ts Menu 块「itemActiveBg 必须显式给值」注释与 `.ov-radio-dark`（global.less:390 概览页分段控件深档补丁）——同类陷阱已两次按「显式给值/局部补丁」处置，本次收口到根因。

### F2 时间轴卡片白底（缺陷②根因）

- SpecTimeline 时间轴步骤内容的无类名 wrapper div 硬编码 `background:#fff`；卡内子元素已切深（文字 rgb(249,250,251)、`.spec-origin-request-quote` 引文框 #232324）→ 深档出现「白卡 + 黑底引文框」双层反转。
- 该卡即用户截图2主缺陷。修复必须整卡 token 化（底、边框、阴影族走 theme.ts 双档），不得只补 wrapper 一处。

### F3 页签计数徽标压字（缺陷③）

- SPEC 详情子页签「场景结果」「测试截图」的计数徽标 offset 过大，盖住页签文字（实测与用户截图2一致）。

### F4 次级文本对比度（缺陷④收尾）

- `OV_TEXT_TERTIARY`（浅档 #64748b）在 list.tsx/detail.tsx 多处内联消费（list.tsx:359/367/1354/1358、detail.tsx:1954），深档未换档。
- `OV_TEXT_TERTIARY_DARK` 现值 #8b8f94（theme.ts:327）比 dsh 深档 label-tertiary（#adb2b8）暗一档，表格次级文本（创建时间等）深底对比度不足；按 D2 语义对位校准为 #adb2b8 系。

## Goals / Non-Goals

**Goals:** 深档下①选中页签文字+墨条可见（计算变量断言 `--ant-color-primary=#f9fafb`、`--ant-color-link=#7aaaff`）；②时间轴卡片整卡深档化无反转；③徽标不压字；④次级文本对比度达标。浅档逐字节不变。

**Non-Goals:** 不动浅档任何视觉；不动主题状态机/防闪烁/嵌入跟随（add-dashboard-dark-theme 既有面）；不重排页签布局；不引入新颜色源（单源红线）。

## Decisions

### D1 主色族按档切：runtime 层覆写 + 组件级显式 token 双保险

- 根因层：app.tsx runtime layout 配置按 `getCurrentScheme()` 覆写 ProLayout 侧主色（dark 档 `colorPrimary=DSH_PRIMARY_DARK`、`navTheme='realDark'`；浅档维持现值逐字节不变）。若 ProLayout 版本对 navTheme/内部 scope 的消费路径实测不符（以计算变量断言为准），则在 ProLayout 消费的 token 通道（`token:` 布局 token）补 `colorPrimary/colorLink` 双档值——两通道最终验收口径一致：深档三个 scope 计算变量达标。
- 保险层：theme.ts 双档按「必须显式给值」纪律补组件级 token——`Tabs`（itemSelectedColor/itemColor/itemHoverColor/inkBarColor）、`Progress`（defaultColor）、`Radio`/`Checkbox`（主色族键，按 antd v6 组件 token 名以实现时实测为准）、`Segmented`（如消费 colorPrimary 则显式）。显式键不依赖派生链，scope 重算也直达。
- 理由：根因层治本，保险层把「Tabs 选中态近隐」这一用户最大感知缺陷与派生链解耦；两层都以计算变量断言验收，任一达标即视觉达标，两层同做成本极低。

### D2 时间轴卡片 token 化

SpecTimeline 卡片底/边框改 theme.ts 双档 token（深档卡底 #232324、边框白 alpha 系、同 spec-detail 卡族）；wrapper div 硬编码白底移除。引文框 `.spec-origin-request-quote` 已切深不动。

### D3 徽标 offset 校正

页签计数徽标 offset/边距调至不压文字（纯 CSS/props 调整，不动页签结构）。

### D4 次级文本双档校准

`OV_TEXT_TERTIARY_DARK` 校准为 #adb2b8（对齐 dsh 深档 label-tertiary）；list.tsx/detail.tsx 内联 `OV_TEXT_TERTIARY` 消费点改经双档 helper/theme token 取值（配色单源红线）。浅档值 #64748b 不变。

## Risks / Trade-offs

- [ProLayout 内部 scope 消费路径随版本差异] → 验收以计算变量断言为准（不信任文档）；D1 两通道兜底。
- [浅档回归] → 浅档所有改动面显式「逐字节不变」为任务红线；既有 theme 测试（darkSeedBgToken/pageChrome 等）全量回归。
- [navTheme='realDark' 引入 ProLayout 侧栏/顶栏额外配色变化] → 深档 chrome 已由 dshLayoutTokenFor+global.less 双通道染色，若 realDark 引入冲突值则以 token 通道为准、不用 navTheme 通道（实现时实测取舍，验收口径不变）。

## Migration Plan

纯前端 token/CSS 修复 + 测试；dist 构建随既有链路；回滚=还原本 SPEC 文件。无配置/数据迁移。

## Open Questions

无。
