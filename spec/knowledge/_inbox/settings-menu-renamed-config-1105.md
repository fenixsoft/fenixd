# fenix 设置菜单更名「配置」（2026-11-05 用户指令交付）

## 结论

dashboard 的「设置」菜单全表面更名为「配置」，避让 dsh web 既有官方「设置」（Settings）菜单的视觉重名。标签同步面共四处，改一处漏三处即出现菜单/页题不一致：

| 表面 | 位置 |
| --- | --- |
| standalone 侧栏菜单 | fenixd `core/dashboard/static/src/app.tsx` menuDataRender（`name: '配置'`） |
| 路由名（document.title 链路） | fenixd `core/dashboard/static/config/routes.ts` `/settings` 条目 |
| 统一标题栏页题 | fenixd `core/dashboard/static/src/pages/settings/index.tsx` PageTitleBar `title` |
| dsh web 侧栏桥条目 | dsh-plugins `fenix-dsh-dashboard-bridge/src/client/index.ts` FIXED_ENTRIES `fenix-settings` label + srcContract 断言 |

提交：fenixd 5e6acb1c4（手术式提交——`settings/index.tsx` 当时混有另一在飞会话的 settingsSection 重构，仅摘 PageTitleBar 单 hunk `git apply --cached`）；dsh-plugins 64882e5。

## 不变面（无迁移）

- 路由 `/settings`、桥深链 `#/settings`、条目 id `fenix-settings` 均不改名——只改 label/name，老深链与书签零影响。
- `.umi/appData.json` 缓存里的旧「设置」快照为构建临时产物，随 build 再生，非源码残留。

## 已知残余

- `docs/help/` 全域仍以「设置页」指称该页（09-config.md 大面积「设置页面板」映射表、08-dashboard.md 锚点 `#设置页settings`）——文档措辞未随更名，后续触及帮助文档的改动可顺带统一；锚点含中文段，改名须同步内外链。

## 相关

- 验证：fenixd 静态测试 359/359 + 桥 vitest 79/79；playwright 命名会话实拍三面（dsh 侧栏条目、standalone 侧栏+顶栏页题+document.title、dsh iframe 面板行壳位页题）。
- 同日上下文：统一标题栏（unified-page-title-bar）后页题由 PageTitleBar 单点声明，是本次更名的第三表面来源。
