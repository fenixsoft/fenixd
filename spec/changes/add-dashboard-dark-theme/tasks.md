## Deliverables

```yaml
- path: core/dashboard/static/src/theme.ts
  kind: modify
- path: core/dashboard/static/src/utils/themePreference.ts
  kind: new
- path: core/dashboard/static/src/utils/themeChannel.ts
  kind: new
- path: core/dashboard/static/src/utils/embedMount.ts
  kind: modify
- path: core/dashboard/static/config/config.ts
  kind: modify
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/src/global.less
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/pageLabels.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/ThemePanel.tsx
  kind: new
- path: core/dashboard/static/tests/themePreference.test.mjs
  kind: new
- path: core/dashboard/static/tests/themeChannel.test.mjs
  kind: new
- path: core/dashboard/static/tests/embedMount.test.mjs
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/ui-theme.md
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/settings-page.md
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 主题状态基建

- [ ] 1.1 theme.ts 双档化：DSH_* 语义常量改为浅/深两档结构（浅档值与现状逐字节一致），深档按 design.md D2 映射表填值；导出按当前档取值的 dshAlignedTheme/dshLayoutToken 等价形态（深色档 antd 接 theme.darkAlgorithm + D2 显式 token 覆写，含黑主色种子陷阱白底黑字主按钮档；不挂 borderRadius 覆写），既有消费方以浅色缺省档编译零改动
- [ ] 1.2 新增 src/utils/themePreference.ts：三档偏好读写（localStorage 键 fenix.theme，值域 system|light|dark，缺省/非法回退 system）、effective scheme 解析（matchMedia prefers-color-scheme 监听与清理）、文档根 data-fenix-theme 应用、embed 态不读写 localStorage 分支；配套 tests/themePreference.test.mjs（type-stripping 直载，注血 storage/matchMedia 覆盖三档缺省解析）
- [ ] 1.3 config/config.ts headScripts 注入首帧防闪烁内联脚本（读 localStorage 偏好 + embed=1 theme 参数 + prefers-color-scheme → 首帧前写 data-fenix-theme），逻辑与 themePreference.ts 同构并注释互指；脚本三档解析逻辑以直载测试覆盖（themePreference.test.mjs 内提取 config.ts 内联脚本源码执行，注血 storage/matchMedia 断言三输入组合与非法值回退——对齐 dashboard-dark-theme「既有测试回归」Requirement 的防闪烁覆盖项）
- [ ] 1.4 app.tsx ConfigProvider 按当前 effective scheme 传入对应 ThemeConfig 与 layout token（浅色档行为与现状一致），data-fenix-theme 档位驱动 global.less 变量切换

## 2. 嵌入跟随通道

- [ ] 2.1 embedMount.ts 扩展第三参数 theme（值域白名单 dark|light，缺省/非法回退未注入），惰性缓存与 _setEmbedSearchParamsForTest 模式复用；tests/embedMount.test.mjs 补场景（合法注入、非法回退、三参数组合且 hash 导航稳定）
- [ ] 2.2 新增 src/utils/themeChannel.ts：window message 监听（event.source===window.parent + kind 白名单 fenix-dashboard:theme + theme 值域校验，不合法静默忽略），embed 态接入 themePreference 应用宿主档且不读写 localStorage；配套 tests/themeChannel.test.mjs（合法切换、非法值忽略、非 parent 来源忽略）

## 3. 配置页界面风格子项

- [ ] 3.1 新增 pages/settings/components/ThemePanel.tsx：三档 Radio（跟随系统/浅色/深色）选中即时生效并持久化，嵌入态渲染锁定态（控件置灰 + 「跟随 dsh web」说明文案）；颜色取值走 theme.ts 单源
- [ ] 3.2 pages/settings/index.tsx BASE_MENU_ITEMS 新增「界面风格」页签并接入 ThemePanel 面板路由，pageLabels.ts 登记标签（命名「界面风格」，不触「设置」避让词汇面）

## 4. 全站深色适配

- [ ] 4.1 global.less 硬编码界面色值清单化（grep 产出全量清单）并收敛为主题 CSS 变量：:root 与 [data-fenix-theme="dark"] 双档定义、值源 theme.ts 档位（含 V2_TILE_SHADOW 阴影系、配置页灰底准例深档、OV_HAIRLINE、焦点环）；毛玻璃深档 rgb 通道与深档 DSH_BG_SOFT 一致且 alpha<1
- [ ] 4.2 组件深档适配核对：StatusTag TONE_HEX 六 tone 深档、PageTitleBar、DshIconButton、markdown-shared 代码块深档（#1b1b1c 系）等 theme 常量直消费面
- [ ] 4.3 六页深浅双档渲染自查（overview/projects/settings/help/activities/command-center）：深档无白块残留、无黑字黑底、对比可读；浅档与落地前逐页一致（自查记录与截图证据留 .history/），npm test 全量与 npm run build 通过

## 5. 文档与知识回填

- [ ] 5.1 回填 spec/knowledge/domains/dashboard-frontend/ui-theme.md：v1 规则标注退役，重写现产规则（三档缺省跟随系统、键 fenix.theme、嵌入跟随契约、theme.ts 单源与 D2 映射表指针）
- [ ] 5.2 同步 spec/knowledge/domains/dashboard-frontend/settings-page.md「界面风格子项」行（亮/暗切换 → 三档语义 + 嵌入锁定）与 docs/help/09-config.md 面板映射表补「界面风格」行
