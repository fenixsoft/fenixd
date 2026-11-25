# Tasks: 仪表盘深色主题验收缺陷修复

## Deliverables

```yaml
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/theme.ts
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
- [ ] 2.2 既有 theme 相关测试回归（tests/darkSeedBgToken.test.mjs、pageChrome.test.mjs、tokens.test.mjs、themePreference.test.mjs、themeChannel.test.mjs、embedMount.test.mjs 全绿）

## 3. F2 时间轴卡片 token 化

- [ ] 3.1 SpecTimeline.tsx 时间轴步骤内容 wrapper div 硬编码白底改 theme.ts 双档卡底 token（深档 #232324 系、边框白 alpha 系），整卡（底/边框/阴影族）与卡内 spec-origin-request-quote(:203) 同层协调，无浅底残留；浅档不变

## 4. F3 页签计数徽标 offset 校正

- [ ] 4.1 detail.tsx「场景结果」「测试截图」子页签计数徽标 offset/边距调至不遮挡页签文字，深浅档均验证

## 5. F4 次级文本双档校准

- [ ] 5.1 `OV_TEXT_TERTIARY_DARK` 校准 #adb2b8（theme.ts:327，对齐 dsh 深档 label-tertiary）；list.tsx:359/367/1354/1358、detail.tsx:1954 等内联 `OV_TEXT_TERTIARY` 消费点改双档取值（配色单源红线），浅档值 #64748b 不变

## 6. 双档活体回归与交付核验

- [ ] 6.1 playwright-cli 深档全量走查：项目页页签选中态可见、任务清单复选框/进度条主色族正确、运行时间轴无白卡、徽标不压字（对照 request.md 三截图逐项销号；截图存 .history/）
- [ ] 6.2 浅档回归走查（fenix.theme=light）：全部改动面与修复前一致；`python3 .fenix/bin/fenix_spec.py status --change fix-dashboard-dark-theme-ui-defects` 收敛 done
