# 任务：框架国际化与中英文缺省支持

## Deliverables

```yaml
- path: core/dashboard/static/config/config.ts
  kind: modify
- path: core/dashboard/static/src/locales/zh-CN.ts
  kind: new
- path: core/dashboard/static/src/locales/en-US.ts
  kind: new
- path: core/dashboard/static/src/utils/localePreference.ts
  kind: new
- path: core/dashboard/static/src/app.tsx
  kind: modify
- path: core/dashboard/static/config/routes.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/pageLabels.ts
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/LocalePanel.tsx
  kind: new
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/tests/localePreference.test.mjs
  kind: new
- path: core/dashboard/static/tests/noHardcodedZh.test.mjs
  kind: new
- path: core/i18n.py
  kind: new
- path: core/i18n_surfaces.md
  kind: new
- path: core/config.py
  kind: modify
- path: core/dashboard/routes/base.py
  kind: modify
- path: tests/test_i18n.py
  kind: new
- path: bin/fenix_cli.py
  kind: modify
- path: docs/help/09-config.md
  kind: modify
- path: spec/knowledge/domains/dashboard-frontend/locale-i18n.md
  kind: new
- path: spec/knowledge/domains/dashboard-frontend/_domain.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 前端 i18n 基建

- [x] 1.1 config/config.ts 开启 Umi locale 插件（default zh-CN、baseNavigator true、antd true；实现时验证 antd 6 联动，不兼容按 design D1 退化路径手动挂 antd locale 并留注释）+ headScripts 注入首帧语言防闪烁内联脚本（读 fenix.locale 显式偏好 → 写/清 umi_locale，system 档清键走浏览器判定；与 localePreference.ts 状态机同构、注释互指）
- [x] 1.2 新增 src/locales/zh-CN.ts（键目录骨架：侧栏菜单、页题、通用动作/状态/空态首批键集，键命名 `<域>.<页/组件>.<语义键>`）与 src/locales/en-US.ts（export 展开 `{ ...zhCN, ...enOverrides }` 形态，en 缺键运行时回退中文）
- [x] 1.3 新增 src/utils/localePreference.ts 三档状态机（localStorage 键 `fenix.locale`，值域 system|zh-CN|en-US，缺省/非法回退 system；浏览器 locale 映射 zh 系→zh-CN、en 系→en-US、其余→zh-CN；生效值经 umi `setLocale(target, false)` 应用、切换即时生效不刷新）+ app.tsx bootstrap 接线（挂载时按偏好应用生效语言）
- [x] 1.4 新增 tests/localePreference.test.mjs（node --test 直载：三档解析、localStorage 持久化、非法值回退、防闪烁内联脚本从 config.ts 源码提取执行断言三输入组合；另断言 en 缺键回退中文（en-US 展开 zhCN 底座后抽查缺失键返回中文文案）与 enOverrides 键集 ⊆ zh 键集（防拼写漂移，对齐 design D3）——形态对齐 themePreference.test.mjs，合计覆盖 spec「语言偏好状态机守卫」THEN 四类断言）

## 2. 配置页「界面语言」子项

- [x] 2.1 新增 pages/settings/components/LocalePanel.tsx：三档 Radio（跟随系统/中文/English），选中即时生效并持久化，形态与色值对齐 ThemePanel（theme.ts 单源，零新硬编码色）
- [x] 2.2 pages/settings/index.tsx BASE_MENU_ITEMS 新增「界面语言」页签接入 LocalePanel 面板路由，pageLabels.ts 登记标签（命名不触 dsh「设置」避让面，不新增路由/菜单项）
- [x] 2.3 docs/help/09-config.md 补「界面语言」子项说明行（中文文档正文不变语言，仅补新面板条目）

## 3. 全站文案抽取（逐页双语化）

- [x] 3.1 菜单与页题链路：app.tsx menuDataRender 菜单项名、config/routes.ts 条目 name、document.title 链路三处同批接 formatMessage（同批改齐纪律：改一漏三即菜单/页题不一致）
- [x] 3.2 projects 域抽取：pages/projects 下列表/详情/SPEC 表格列名与空态/状态标签/操作弹窗/筛选器/移动端卡片流等前端自有静态文案全部迁入目录并接线（动态数据文本不动）
- [x] 3.3 settings 域抽取：pages/settings 下既有配置面板文案（含 BASE_MENU_ITEMS 面板名、继承提示、保存提示与错误反馈）迁入目录并接线
- [x] 3.4 overview / activities / command-center / help 页壳抽取：四页前端自有静态文案（副标题、页签、KPI 标签、空态）迁入目录并接线
- [x] 3.5 全局组件与 utils 常量抽取：components（PageTitleBar/StatusTag/弹窗/claude-msg 壳层等）与 utils（AGENT_LABEL 等展示映射、format 提示词）静态文案迁入目录并接线；双语术语对照表以目录内注释承载（SPEC 不译、晋升=promote、处置链=disposition chain）
- [x] 3.6 新增 tests/noHardcodedZh.test.mjs 抽查守卫（代表文件 JSX 字符串字面量断言无中文字符，注释与 locales 目录豁免；抽查清单写入测试内并覆盖每页至少一文件）+ playwright en 档逐页巡检截图留档 .history/（对照 Scenario「英文档下前端静态文案无中文残留」）

## 4. 后端消息目录

- [x] 4.1 新增 core/i18n.py：CATALOG（键 → {zh, en}）、t(key, locale, **kw)（en 缺键回退 zh、未知键原样返回键名）、resolve_locale(accept_language)（逗号 q 值前缀白名单 zh/en，非法回退 zh）；新增 tests/test_i18n.py 覆盖三行为（pytest）
- [x] 4.2 core/config.py 新增 general.locale 配置键（白名单 zh/en 校验、缺省 zh、沿用用户级/项目级作用域与继承标注既有机制）
- [x] 4.3 core/dashboard/routes/base.py _error 助手支持按请求 Accept-Language 解析 locale、消息经目录展开展示型错误文本（响应结构/HTTP 状态零变化，200+error 形态既有守卫保持）
- [x] 4.4 后端组装的展示文本改造：告警与自动运维记录的展示型描述、状态展示标签中由后端下发部分等经 t() 输出（判据=文本由后端组装且前端直接渲染不再加工；内部日志不动）。注意：时间轴处置链事件标签、AGENT_LABEL、blockedPhaseMeta 等实为前端 kind→标签映射（前端自有静态文案，见 SpecTimeline.tsx 标签映射与 utils/runVisual.ts），属任务 3.5 前端目录面，MUST NOT 重复进后端目录；改造面盘点清单落盘 core/i18n_surfaces.md（键清单 + 改造点位），钉住具体文案字面量的既有 pytest 断言同批修正并留注释
- [x] 4.5 后端既有 pytest 全量回归通过，确认 en/zh 双请求响应结构一致（对照 Scenario「请求头决定消息语言」「内部日志不受请求语言影响」）

## 5. CLI 人读输出双语

- [x] 5.1 bin/fenix_cli.py 接入 core/i18n.py：新增 --lang 参数，解析链 --lang > FENIX_LANG > general.locale > zh（白名单外回退 zh），人读 print 文案经 t() 输出；退出码、行为语义、机器可读输出零变化；补 CLI 输出双语测试入 tests/test_i18n.py（对照 Scenario「解析链逐级生效」「命令输出双语且行为不变」）

## 6. 前端请求层 locale 附带

- [x] 6.1 src/services/dashboard.ts 统一 fetch 封装 reqHeaders 附带 Accept-Language（生效语言映射 zh-CN→zh / en-US→en），散点内联 fetch 调用同批补挂；语言切换后新请求携带新值（对照 Scenario「语言切换后请求头跟随」）

## 7. 知识回填与收尾验证

- [x] 7.1 新增 spec/knowledge/domains/dashboard-frontend/locale-i18n.md（语言偏好三档状态机/首帧防闪烁/umi locale 机制/en 目录 spread 回退契约/嵌入态不随宿主边界，结构镜像 ui-theme 页）并登记 spec/knowledge/domains/dashboard-frontend/_domain.md 能力表
- [x] 7.2 收尾验证：前端既有 node --test 全量回归 + `max build` 构建通过（dist/index.html 锚点再生）；zh 档渲染与现状一致性抽检（对照 Requirement「双语文案目录与缺省语言跟随系统」zh 场景）
