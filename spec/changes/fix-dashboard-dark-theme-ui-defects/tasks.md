# Tasks: 仪表盘深色主题验收缺陷修复

## Deliverables

```yaml
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/theme.ts
  kind: modify
- path: core/dashboard/static/src/global.less
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/SpecTimeline.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/tests/darkSeedBgToken.test.mjs
  kind: reference
- path: core/dashboard/static/tests/pageChrome.test.mjs
  kind: reference
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. F1 根因层：ProLayout 主色族按档切

- [ ] 1.1 app.tsx runtime 布局配置按 `getCurrentScheme()` 深档覆写 ProLayout 侧主色（`colorPrimary=DSH_PRIMARY_DARK`(#f9fafb, theme.ts:300)、`navTheme='realDark'`；浅档路径维持现值逐字节不变）；若实测 ProLayout 内部 scope（css-var-_r_0_/_r_1_/_r_4_/_r_h_）消费路径不符则以布局 token 通道补 `colorPrimary/colorLink` 双档值，验收口径不变
- [ ] 1.2 深档计算变量验证：主内容/侧栏 scope `--ant-color-primary`=#f9fafb、`--ant-color-link`=#7aaaff（playwright-cli 活体验证 8787，复现配方见 design.md）；若 realDark 通道与 dshLayoutTokenFor 深档 chrome 染色冲突，取舍并记录于实现说明

## 2. F1 保险层：theme.ts 组件级显式 token

- [ ] 2.1 theme.ts 双档 components 补 `Tabs`（itemSelectedColor/itemColor/itemHoverColor/inkBarColor）、`Progress`（defaultColor）、`Radio`、`Checkbox`、`Segmented`（如消费主色派生则显式给值；遵守「必须显式给值」纪律与 darkSeedBgToken 陷阱注记，不挂 borderRadius）——浅档值=现视觉逐字节不变（Tabs 选中态现取 DSH_TEXT，theme.ts:444 先例）
- [ ] 2.2 既有相关测试回归（tests/darkSeedBgToken.test.mjs、pageChrome.test.mjs、tokens.test.mjs、themePreference.test.mjs、themeChannel.test.mjs、embedMount.test.mjs 全绿）

## 3. F2 时间轴卡片 token 化

- [ ] 3.1 SpecTimeline.tsx 时间轴节点磁贴 cardBox(:618-629) 非急态硬编码白底（:627 `'#ffffff'`）改 theme.ts 双档卡底 token（深档 #232324 系、边框白 alpha 系），整卡（底/边框/阴影族）与卡内 spec-origin-request-quote(:203) 同层协调，无浅底残留；浅档磁贴形态（12px 圆角/发丝边/软阴影/纯白底）不变；同步改写 :609-617「白底有意取舍勿改回」旧注释（深档已按本 SPEC 校正、浅档维持 2026-11-06 Bento 形态指令），urgent 分支语义 token 不动
- [ ] 3.2 既有 SpecTimeline 测试回归（tests/specTimelineChainNodes.test.mjs、specTimelineOriginRequest.test.mjs 全绿）

## 4. F3 页签计数徽标 offset 校正

- [ ] 4.1 detail.tsx 全部子页签计数徽标（:1502 场景结果 / :1521 缺陷 / :1539 测试截图，现 offset `marginTop:-5`）offset/边距调至不遮挡页签文字，深浅档均验证

## 5. F4 次级文本双档校准

- [ ] 5.1 深值双源同步校准 #adb2b8（对齐 dsh 深档 label-tertiary）：theme.ts:327 `OV_TEXT_TERTIARY_DARK` 与 global.less:105 `--fenix-ov-text-tertiary` 深档定义；消费点（list.tsx/detail.tsx/ProjectTable.tsx）已走 CSS var 双档取值，校准自动生效，MUST NOT 逐点改内联色值（配色单源红线），抽查深档计算值为 #adb2b8；浅档值 #64748b 不变

## 6. 双档活体回归与交付核验

- [ ] 6.1 playwright-cli 深档全量走查：项目页页签选中态可见、任务清单复选框/进度条主色族正确、运行时间轴无白卡、徽标不压字、次级文本（列表创建时间/任务清单分组标题）对比度 #adb2b8 系（对照 request.md 三截图逐项销号；截图存 .history/）
- [ ] 6.2 浅档回归走查（fenix.theme=light）：全部改动面与修复前一致；`python3 .fenix/bin/fenix_spec.py status --change fix-dashboard-dark-theme-ui-defects` 收敛 done
