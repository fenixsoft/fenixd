# 帮助/设置页滚动形态统一为文档级（定高内滚退役）

## 背景

2026-11-05 用户指令「统一 dashboard 内容区域滚动条的范围」：概览/项目/
运维记录的滚动条跨标题区域（文档级），而帮助/设置页滚动条局限在标题下方
内容区（定高卡体 + 正文容器自滚），要求统一为前者。

## 结论

- 帮助/设置页页面纵向滚动统一走**文档级**——滚动条跨标题区域，同
  overview/projects/activities 口径。桌面/移动/embed 三模式同构（此前仅
  移动端走文档滚动，现全模式一致）。
- **`HELP_FRAME_OFFSET` / `SETTINGS_FRAME_OFFSET` 偏移常数族（standalone
  56 / embed 60）退役**，卡体不再 `calc(100vh - 偏移)` 定高；正文/右栏
  `overflowY: auto` 内滚移除。
- **目录列/设置页左菜单本体 sticky 钉住不随页面滚走**（同日用户指令
  「菜单/目录不能滚走」）：列外壳撑满列高（右缘分隔线全长），本体
  `position: sticky` 钉在固定标题带下缘——新常数 `HELP_TOC_STICKY_TOP` /
  `SETTINGS_MENU_STICKY_TOP`（standalone 56 / embed 60，**纯定位用途**，
  与旧定高偏移数值巧合、职责不同）；maxHeight `calc(100vh - 偏移 - 16px)`
  钉住预算，长目录/长菜单超出视口时本体自滚兜底（唯一的页内 overflowY，
  正文/右栏无内滚）；顶带 16px 呼吸随本体走钉位。设置页菜单旧
  `height: '100%'` 随定高形态退役。
- global.less 两条定高支撑规则同批退役：`.settings-page > .ant-card-body`
  的 `height:100% + 纵向 flex` 卡体传导链；`.settings-page` 的
  `margin-right: -15px` 贴缘外扩（-15 与 dshLayoutToken
  paddingInlinePageContainerContent=15 的强耦合解除，内容区恢复与他页一致
  的 15px 右留白，文档滚动条天然贴视口右缘）。
- 帮助页包裹卡的 `marginInlineEnd: -dshLayoutToken…` 内联负边距同批移除。
- **定高贴底页仍存续两类**，children-container `padding-block-end: 0` 全局
  规则保留不回填：项目详情页框（`pageChrome.ts` PAGE_CHROME_OFFSET 族）与
  指挥中心（SCREEN_CHROME_OFFSET 双档）——本指令未触及，仍为定高自滚形态。
- 守卫测试反转：`tests/helpPageScroll.test.mjs` 与 `pageChrome.test.mjs`
  的设置页定高测试改为锁定新形态（无 `const *_FRAME_OFFSET`、无
  `height: calc(100vh)` 高度链、正文/右栏无 `overflowY`、贴缘负边距不回潮、
  目录/菜单 sticky 钉住接线与双档偏移值锁定）。

## 建议折叠去向

- dashboard-frontend/unified-page-title-bar：「定高偏移口径」规则段中
  settings/help `FRAME_OFFSET`（standalone 56 / embed 48→60）条目已退役，
  该规则现存有效对象仅项目详情页框与指挥中心 SCREEN_CHROME_OFFSET。
- dashboard-frontend/page-container-chrome：children padB=0 规则的定高贴底
  页指向更新（帮助/设置 → 项目详情/指挥中心）。
- dashboard-frontend 域导航：v3-settings-page / v3-help 帮助中心条目滚动
  形态一句（定高内滚 → 文档级统一）。

## 溯源

- 2026-11-05 用户指令；涉及 core/dashboard/static/src/pages/help/index.tsx、
  pages/settings/index.tsx、src/global.less、tests/helpPageScroll.test.mjs、
  tests/pageChrome.test.mjs（工作区交付，与处置链并入运维页批次
  be6dc352b 及其后续在途批次共享 settings/index.tsx）。
- 实拍验证（playwright，1440×900，端口 8787 直连）：设置页
  scrollHeight 2331 > 900 文档滚、右栏 overflowY visible、滚至页底
  docEndGap=0 卡体贴视口底；帮助页 scrollHeight 1126 文档滚；滚至页底时
  两页菜单/目录 sticky 钉在视口 y=56（紧贴固定顶栏下缘）、分隔线全长；
  两页均无横向溢出。
