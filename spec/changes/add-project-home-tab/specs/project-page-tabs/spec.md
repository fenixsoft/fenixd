# Spec: 项目页分面导航（六分面扩展：项目首页居首）

本文件改写活跃能力 `project-page-tabs`（由 `add-project-detail-tabs` 引入，经 `add-test-regression-tab` / `add-project-architecture-tab` / `add-knowledge-atlas` / `add-spec-list-filter-stickiness` 多轮扩展）中「分面组成」与「URL tab 合法值域」条款：新增「项目首页」（`home`）分面并置于**首位**，默认选中「功能开发」不变。

## MODIFIED Requirements

### Requirement: 项目页分面导航容器

SPEC 列表页（项目页，路由 `/projects/:name`）SHALL 在项目名称下方渲染 `Tabs` 分面导航容器，作为页面的主内容组织方式。

- Tabs 的分面组成为「项目首页」「功能开发」「代码审查」「测试回归」「架构蓝图」「项目知识」**六个分面**（顺序固定，「项目首页」居**首位**；原五分面顺序相对不变），默认选中仍为「**功能开发**」——新分面仅占据菜单位，MUST NOT 改变默认选中分面。Tabs 容器在桌面与移动端两种视口下均渲染（维持既有规范）。
- 页签选中态持久化到 URL 查询参数 `tab`（合法值 `home`/`dev`/`quality`/`regression`/`architecture`/`knowledge`，缺省 `dev` 且缺省不写参——选中态为缺省值时 URL 无 `tab` 参数；写入 replace 语义，不新增历史条目）。
- 页签切换原地切换内容：不整页刷新、路由路径保持 `/projects/:name` 不变；各分面按需加载门控语义维持（未选中分面零请求）。
- 「功能开发」分面承载既有 SPEC 列表全部能力，行为与引入「项目首页」前保持一致（零回归）；其余四个既有分面零改动。

#### Scenario: 默认进入功能开发

- **WHEN** 用户打开 `/projects/fenixd`（URL 无 `tab` 参数）
- **THEN** 页签菜单位为「项目首页」，但选中分面 MUST 为「功能开发」（URL 保持无 `tab` 参数），「项目首页」分面内容不拉取

#### Scenario: 项目首页居首

- **WHEN** 用户打开项目页查看页签菜单
- **THEN** 六个页签顺序为 项目首页 / 功能开发 / 代码审查 / 测试回归 / 架构蓝图 / 项目知识，「项目首页」位于第一位

#### Scenario: tab=home 直达与恢复

- **WHEN** 用户在「项目首页」分面刷新页面
- **THEN** 刷新后仍停在「项目首页」（URL `tab=home` 恢复），文件浏览位置按 `path` 参数恢复（path 语义由 `project-home-tab` 能力承载）
