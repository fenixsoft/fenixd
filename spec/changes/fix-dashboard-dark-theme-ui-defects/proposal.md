## Why

add-dashboard-dark-theme 交付后用户深档验收发现四处 UI 缺陷（三张截图，独立访问 8787 实测全部复现）：①项目页导航页签选中态与墨条在深底上近隐；②SPEC 详情运行时间轴卡片整卡白底（浅档残留）内嵌已切深的黑底引文框，同卡双层反转不可读；③页签计数徽标压住页签文字；④列表次级文本与复选框/进度条取色偏离 D2 映射。全部为深档视觉缺陷，不影响功能与浅档。

## What Changes

- ProLayout 三分区主题 scope 按档切主色族（缺陷①④的根因）：`defaultSettings.ts` 的 `colorPrimary:'#0f1115'`/`navTheme:'light'` 恒定不随档，ProLayout 内部 ConfigProvider 以浅档种子重算主色/链接派生族——实测深档下主内容/侧栏 scope `--ant-color-primary=#101115`（应 #f9fafb）、`--ant-color-link=#6b94dc`（应 #7aaaff），而 colorText/背景已正确切深。修复后选中页签、墨条、复选框、进度条等主色族消费面在深档回归 D2 值。
- SpecTimeline 时间轴卡片背景 token 化（缺陷②根因）：无类名 wrapper div 硬编码白底，卡内子元素已切深（引文框 #232324、近白文字）→ 深档白卡黑字反转。卡底/边框按 theme.ts 单源走双档。
- SPEC 详情子页签计数徽标 offset 校正（缺陷③）：徽标不再压住「场景结果」「测试截图」文字。
- 次级文本双档校准（缺陷④收尾）：`OV_TEXT_TERTIARY` 浅值内联消费点（list.tsx/detail.tsx 多处）深档换档，深档次级色对齐 dsh 深档 label-tertiary #adb2b8 校准 `OV_TEXT_TERTIARY_DARK`。

## Capabilities

### New Capabilities

（无——全部为 dashboard-dark-theme 既有能力的缺陷修复。）

### Modified Capabilities

- `dashboard-dark-theme`：修复深档呈现 requirement 的实现缺口（ProLayout 主色族 scope 切档、时间轴卡底 token 化、徽标 offset、次级文本双档），浅档行为逐字节不变。

## Impact

- `core/dashboard/static/config/defaultSettings.ts`：navTheme/colorPrimary 按档取值（或 runtime layout 配置覆写，以实现为准）。
- `core/dashboard/static/src/app.tsx`：runtime layout 配置按档传 ProLayout 主色族。
- `core/dashboard/static/src/theme.ts`：补 Tabs/Progress/Radio/Checkbox 组件级显式 token（双档）；`OV_TEXT_TERTIARY_DARK` 校准。
- `core/dashboard/static/src/global.less`：深档覆写层随迁（如需）。
- `core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx`：卡底 token 化。
- `core/dashboard/static/src/pages/projects/list.tsx`、`core/dashboard/static/src/pages/projects/detail.tsx`：次级文本内联消费点双档化。
- tests/：计算变量断言测试 + 既有 theme 测试回归。
- 用户验收基线：三张截图对应的三处视觉缺陷在深档全部消失，浅档零变化。
