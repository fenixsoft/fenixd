# 能力规格：dashboard-i18n（Dashboard 前端国际化）

## ADDED Requirements

### Requirement: 双语文案目录与缺省语言跟随系统
前端 SHALL 采用 Umi Max 内建 locale 机制承载双语：`zh-CN` 为缺省与回退语言，`en-US` 为第二语言，两份文案目录为界面静态文案的唯一来源；未显式选择语言时 SHALL 跟随浏览器/系统 locale（baseNavigator），无法识别或值域外的 locale 一律回退 `zh-CN`。

#### Scenario: 中文浏览器首次访问显示中文
- **WHEN** 浏览器语言为 zh 系且 localStorage 无语言偏好键时首次访问 Dashboard
- **THEN** 全站界面静态文案为中文，与现状渲染一致

#### Scenario: 英文浏览器首次访问显示英文
- **WHEN** 浏览器语言为 en 系且无显式语言偏好时首次访问 Dashboard
- **THEN** 全站界面静态文案为英文

#### Scenario: 值域外 locale 回退中文
- **WHEN** 浏览器 locale 为 ja/fr 等不支持语言且无显式语言偏好
- **THEN** 界面静态文案回退为 `zh-CN` 中文呈现

### Requirement: 手动切换与持久化
配置页 SHALL 新增「界面语言」子项，提供三档选择：跟随系统 / 中文（zh-CN）/ English（en-US）；选择即时生效并持久化到浏览器 localStorage，刷新与重开浏览器后保持；「跟随系统」档行为与「Requirement: 双语文案目录与缺省语言跟随系统」一致。命名 SHALL 遵守既有词汇对表纪律（本品用「配置」页承载，不新增与 dsh 官方「设置」的冲突面）。

#### Scenario: 手动切换 English 即时生效并持久化
- **WHEN** 用户在配置页「界面语言」子项选择 English
- **THEN** 全站界面静态文案即时切换为英文，语言偏好写入 localStorage；刷新页面后仍为英文

#### Scenario: 切回跟随系统恢复系统判定
- **WHEN** 用户从 English 切回「跟随系统」
- **THEN** localStorage 显式偏好清除，界面语言按浏览器 locale 重新判定

### Requirement: 菜单与页面标题联动
侧栏菜单项名称（menuDataRender 单源）、路由级浏览器标题（document.title 链路）SHALL 随当前语言切换呈现对应语言文案，切换语言后无需刷新页面。

#### Scenario: 切换语言后菜单与标题联动
- **WHEN** 当前语言由中文切换为 English
- **THEN** 侧栏菜单项（概览/项目/配置/运维等）呈现英文文案，浏览器标签页标题随语言更新

### Requirement: antd 组件族文案联动
antd 组件内建文案（分页、日期选择、空态、确认按钮等）SHALL 随当前语言联动（ConfigProvider locale 双语接入），MUST NOT 出现语言切换后组件内建文案仍停留单一语言。

#### Scenario: 英文档下 antd 分页为英文
- **WHEN** 当前语言为 en-US 且 SPEC 列表分页器可见
- **THEN** 分页器内建项文案（如每页条数）为英文

### Requirement: 全站静态文案双语覆盖与中文残留红线
六个常规页（概览/项目列表/SPEC 详情/配置/运维/指挥中心）与全局组件（PageTitleBar、StatusTag、弹窗、表格列名与空态、活动卡片等）的前端自有静态文案 SHALL 全量进入双语文案目录；语言为 en-US 时前端自有静态文案 MUST NOT 出现中文残留。动态数据文本（后端返回的 SPEC 中文标题、用户数据、验证报告内容等）不属于本能力覆盖面，按 `backend-message-i18n` 能力规则处理。

#### Scenario: 英文档下前端静态文案无中文残留
- **WHEN** 当前语言为 en-US 并遍历六个常规页的主要视图（含空态与操作弹窗）
- **THEN** 前端自有静态文案均为英文（动态数据中的中文不在判定面）

#### Scenario: 未覆盖键回退中文不裸露键名
- **WHEN** en-US 目录缺失某文案键而 zh-CN 目录存在
- **THEN** 该处界面呈现该键的中文文案，MUST NOT 显示键名或空白

### Requirement: 既有测试回归与 i18n 守卫
既有前端守卫测试（`node --test tests/*.test.mjs`）SHALL 全量通过；SHALL 新增 i18n 守卫测试钉住语言偏好状态机（三档解析/localStorage 读写/非法值回退）与「zh-CN 目录为 en-US 缺键回退源」契约。

#### Scenario: 语言偏好状态机守卫
- **WHEN** 运行 i18n 守卫测试
- **THEN** 三档偏好解析、localStorage 持久化、非法值回退跟随系统、en 缺键回退中文四类断言全部通过
