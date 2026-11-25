# 验证报告：add-framework-i18n-zh-en

> ⚠️ 本报告由框架于 2026-11-25T11:09:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-25T11:03:32.227227+00:00+run-result@mtime1795604961875360721

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 13/17 场景通过，4 失败，0 错误（3 个真实产品 Bug）**

17 场景 13 过 4 败，失败全部归因 3 个产品 Bug：major 一项（CATALOG 缺 overview.title/ops.* 键族致原始键名直出、双语页题/页签全坏）、minor 两项（list.tsx:1776 showTotal 硬编码「共 N 条」；activities 页签 label 硬编码「更新」由守卫检出）。框架静态情报的 7 处双汉字选择器（概览/项目/配置/浅色/深色）经执行证据核实均为误报：匹配目标为 .ant-pro-sider 容器 text_match、.ant-menu-item、.ant-radio-wrapper，均非 antd Button 不受 autoInsertSpace 影响，且相关断言全部实际执行 pass、实际文本连续无空格插入，无需修场景文件。web-locale-activities-title-chain-label 的菜单锚点 Operations 为场景文件缺陷（en-US.ts 钉死 menu.ops='Ops'，同批 patrol 场景断言 Ops 已过），已按断言级 test-defect 记录；因该场景另有 2 条 product-bug 断言主导，本轮按 bug-found 路由，锚点修正留待下一裁决轮原地修复。

| 指标 | 数量 |
| --- | --- |
| 通过 | 13 |
| 失败 | 4 |
| 错误 | 0 |
| 产品 Bug | 3 |
| 本链增量 Token（输入） | 9.28M |
| 本链增量 Token（输出） | 0.11M |


## 真实产品 Bug

### BUG-01（severity=major）· text_match

- 关联场景：web-locale-menu-title-linkage、web-locale-activities-title-chain-label
- 描述：i18n 键未登记进词表致原始键名直出：overview 页页题显示「overview.title」、运维页页题/页签/筛选/链路徽标显示 ops.title、ops.subtitle、ops.tabs.chain/auto/alert、ops.chain.chip.* 等十余处键名，zh/en 双语均坏（zh 基线亦被回归）
- 根因：页面代码 intl.formatMessage({id:'overview.title'/'ops.*'}) 引用的键在 src/locales/zh-CN.ts 与 en-US.ts 均未登记（grep 两词表零命中），umi intl 对未知 id 回退返回 id 本身
- 证据（场景 web-locale-menu-title-linkage 结构化证据，引用）：
  - failed_assertions: [{"type": "text_match", "selector": "[data-testid='page-title-bar-title']", "expected": "Cross-Project Overview", "actual": "overview.title（原始键名直出）"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-framework-i18n-zh-en/screenshots/web-locale-menu-title-linkage_assert_fail_1.png"]
  - first_failed_step: 断言3：overview 页题直出原始键名 overview.title，未呈任何语言译文

### BUG-02（severity=minor）· element_not_exist

- 关联场景：web-locale-antd-pagination-en
- 描述：en 档 SPEC 列表分页器 showTotal 仍渲染中文「共 N 条」（内建文案 / page 已英化，唯 showTotal 漏改）
- 根因：src/pages/projects/list.tsx:1776 pagination showTotal: (t) => `共 ${t} 条` 硬编码中文，未走 intl
- 证据（场景 web-locale-antd-pagination-en 结构化证据，引用）：
  - failed_assertions: [{"type": "element_not_exist", "selector": ".ant-pagination :text(\"共\")", "expected": "元素不存在", "actual": "actual_count=1；同场景断言2实际文本「共 50 条12320 / page」示中文 showTotal 残留"}]
  - screenshots: ["/root/fenixd/.fenix/verify-progress/add-framework-i18n-zh-en/screenshots/web-locale-antd-pagination-en_assert_fail_0.png"]
  - first_failed_step: 断言6（负向）：en 档分页器仍渲染中文 showTotal「共 50 条」，projects/list.tsx:1776 硬编码未走 i18n

### BUG-03（severity=minor）· exit_code

- 关联场景：cli-locale-guard-node-green
- 描述：activities 页存在硬编码中文页签 label「更新」，noHardcodedZh 守卫检出后 node --test 退出码 1（守卫自身逻辑正常）
- 根因：src/pages/activities/index.tsx 页签 label: '更新' 硬编码（run 快照 line 1124，现 worktree line 1143），应迁入 locales 词表并经 intl 接线；守卫白名单 LITERAL_EXEMPTS 仅豁免匹配后端数据的 成功/失败/处理，「更新」不在豁免面，检出为真阳性
- 证据（场景 cli-locale-guard-node-green 结构化证据，引用）：
  - failed_assertions: [{"type": "exit_code", "expected": 0, "actual": 1}, {"type": "output_match", "stream": "combined", "expected": "fail 0", "actual": "noHardcodedZh 检出 1 处硬编码中文：line 1124 literal '更新'（ERR_ASSERTION deepStrictEqual actual=[{line:1124,literal:'更新'}]）"}]
  - screenshots: []
  - first_failed_step: 步骤1 guard_run：noHardcodedZh 守卫检出源码残留硬编码「更新」（line 1124），node --test 退出码 1


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| web-locale-zh-explicit-baseline | 中文显式档基线回归：预置 fenix.locale=zh-CN 后，侧栏菜单/页题保持中文现状，配置页同时呈现既有「界面风格」页签与新增「界面语言」页签（spec 钉死命名），界面风格面板三档（跟随系统/浅色/深色）文案零变化（zh 用户零感知）。navigate 出自 core/dashboard/static/config/routes.ts:11-62（hash 路由） | pass | 0/8 | - |
| web-locale-en-switch-instant | 手动切换 English 即时生效：配置页「界面语言」页签点选 English 后，不做任何刷新动作，侧栏菜单即刻呈英文（React setLocale 驱动重渲染）。验收锚点：侧栏菜单英文 Overview/Projects；en 档「界面语言」页签文本为 Language；Radio 三档命名 spec 钉死（跟随系统/中文/English）。页签点击出 settings/index.tsx BASE_MENU_ITEMS（pageLabels.ts 单源）、LocalePanel 形态对齐 ThemePanel.tsx:57-62（antd Radio.Group） | pass | 0/6 | - |
| web-locale-en-switch-persist-reload | 手动切换后持久化：UI 点选 English（写入 localStorage fenix.locale=en-US）后刷新页面，语言仍为英文（持久化读回链路：fenix.locale → 防闪烁脚本/umi locale）。验收锚点：Overview/Projects/Language。navigate 出自 routes.ts:50 | pass | 0/5 | - |
| web-locale-en-six-pages-patrol | en 档六页巡检：预置 fenix.locale=en-US 依次遍历六常规页（每页 navigate 验证加载无错），断言收拢在最终停留页执行——侧栏六项菜单全英文（菜单为六页常驻面，一次覆盖全站导航文案）+ 配置页页题英文 + LocalePanel English 档在场。验收锚点：Overview/Projects/Config/Ops/Command Center/Help（en 译名出 en-US.ts menu.*；2026-11-25 judge 修正锚点：原 Settings/Operations 无源码出处）。menuDataRender 出 app.tsx:242-263，settings 页题出 settings/index.tsx:477（title=配置） | pass | 0/11 | - |
| web-locale-follow-system-resolve | 跟随系统档：显式偏好为 system 时状态机清 umi locale 键、按 navigator.language 重新判定（与主题 fenix.theme 三档状态机同构）。引擎 browser.py chromium context 显式 locale="zh-CN"（2026-11-25 judge 核实，非缺省 en-US），system 档按 design zh 系→zh-CN 判定应呈中文；前置 seed umi_locale=en-US 残留 en 偏好，system 档清键重判定覆盖残留后仍呈中文即判定链生效的强证据（若 system 档未生效残留 en 键则呈英文即失败）。navigate 出自 routes.ts:11 | pass | 0/4 | - |
| web-locale-antd-pagination-en | antd 组件族文案随语言联动（en 档）：SPEC 列表分页器内建文案为英文「/ page」（antd en-US 库内建译法为小写，2026-11-25 judge 修正锚点大小写；另以负向断言钉住 list.tsx:1776 showTotal 硬编码中文残留待产品修复），无中文内建文案残留。列表分页出 core/dashboard/static/src/pages/projects/list.tsx:1776（pagination showSizeChanger，fenixd 项目 SPEC 数 >20 保证分页器在场）。zh 档基线由 web-locale-zh-explicit-baseline 承担 | failed（已修正） | 1/6 | product-bug |
| web-locale-menu-title-linkage | 菜单与浏览器标题随语言联动：en 档下侧栏菜单呈英文且 document.title（head title 元素文本，路由 name 经 umi title 链路，routes.ts name → document.title）含英文页名 Overview。menuDataRender 出 app.tsx:242-263 | failed（已修正） | 1/4 | product-bug |
| web-locale-activities-title-chain-label | en 档运维页页题与处置链页签联动：页题呈英文 Operations（title=运维 出处 activities/index.tsx:1031），处置链页签呈英文（design 术语表钉死：处置链=disposition chain，验收锚点 Disposition Chain）。页签出 activities 三页签结构（处置链/自动运维记录/告警记录，默认处置链） | failed（已修正） | 3/4 | product-bug |
| api-error-accept-language-bilingual | Accept-Language 头决定展示型错误语言：同一不存在项目端点分别以 en 头/无头/fr 头请求，error 字段依次为英文（验收锚点：含 not found or not monitored 短语）/中文（逐字「项目不存在或未监控」）/中文（白名单外回退），三者 HTTP 状态一致 400。出 core/dashboard/routes/project_routes.py:327（_error 中文硬编码改造点）与 base.py _error 助手 | pass | 0/6 | - |
| api-error-shape-consistency | en/zh 双语言响应结构零变化：同一错误端点 zh 头与 en 头请求的响应均为 400、body 均为含 error 键的 JSON 对象、Content-Type 均为 application/json（只改文案来源不改响应结构）。出 design.md D5 与 tasks 4.3 | pass | 0/6 | - |
| cli-lang-flag-en-vs-default | CLI --lang 参数双语对照：同一失败命令（--project 指向非 Fenix 目录）以 --lang en 与缺省各执行一次，stderr 错误提示分别为英文（验收锚点：含 not a Fenix project directory 短语）与中文（逐字「不是 Fenix 项目目录」），退出码一致为 1。出 bin/fenix_cli.py:34（_resolve_project_root 中文提示改造点）；--lang 参数与既有 --project 同构（子命令前后均可） | pass | 0/4 | - |
| cli-lang-env-and-whitelist-fallback | FENIX_LANG 环境变量与白名单回退：FENIX_LANG=en 时错误提示英文（验收锚点 not a Fenix project directory）；FENIX_LANG=fr（白名单外）回退中文「不是 Fenix 项目目录」。解析链出 design.md D6 | pass | 0/4 | - |
| cli-lang-config-general-locale | 用户级配置 general.locale=en 生效：以 FENIX_HOME 指向临时目录写入含 general.locale: en 的用户级配置（config.py:30 USER_CONFIG_DIR=$FENIX_HOME/.fenix，import 期绑定），CLI 无 --lang 无 FENIX_LANG 时错误提示为英文（解析链第三级） | pass | 0/2 | - |
| cli-lang-priority-chain | CLI 解析链优先级：--lang en + FENIX_LANG=zh + config locale=zh 时输出英文（--lang 最高）；仅 FENIX_LANG=en + config locale=zh 时输出英文（env 高于 config）。配置经 FENIX_HOME 临时目录承载 | pass | 0/4 | - |
| cli-i18n-pytest-green | core/i18n.py 行为守卫 pytest 全绿：tests/test_i18n.py 覆盖 t() 双语查询/en 缺键回退 zh/未知键返回键名/resolve_locale 白名单解析与 CLI 解析链（tasks 4.1、5.1）。断言 exit 0 与 PASSED 输出（仅 -v 不并列 -q） | pass | 0/2 | - |
| cli-locale-guard-node-green | 前端 i18n 守卫测试全绿：node --test 运行 localePreference.test.mjs（三档解析/localStorage 持久化/非法值回退/防闪烁脚本三输入组合/en 缺键回退中文/overrides 键集⊆zh 键集）与 noHardcodedZh.test.mjs（抽查守卫）。形态对齐 add-dashboard-dark-theme 守卫场景先例 | failed（已修正） | 2/2 | product-bug |
| cli-i18n-source-contract-audit | i18n 基建源码契约静态审计：钉住 design 钳定形态——core/i18n.py 提供 CATALOG/t/resolve_locale；localePreference.ts 用 localStorage 键 fenix.locale；en-US.ts 以 {...zhCN, ...enOverrides} spread 底座承载回退；config.ts 开启 baseNavigator；core/config.py 登记 general.locale；dashboard.ts 请求层附带 Accept-Language；dist/index.html 防闪烁脚本读 fenix.locale（构建锚点再生）。file_content 均为 contains 子串断言 | pass | 0/8 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| web-locale-activities-title-chain-label | text_match .ant-pro-sider 菜单运维英文 Operations | test-defect | 测试用例自身缺陷（非产品缺陷） | en 译名词表钉死 menu.ops=Ops（en-US.ts），同批 web-locale-en-six-pages-patrol 断言 Ops 已通过；本场景 expected 误写 Operations 无源码出处，属场景文件锚点错误 |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

