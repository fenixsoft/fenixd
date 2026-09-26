# Spec: 项目页分面导航（选中态 URL 持久化改写）

本文件改写活跃能力 `project-page-tabs`（由 `add-project-detail-tabs` 引入）中「页签选中态不持久化」的条款：页签选中态由仅存组件内存改为持久化到 URL 查询参数 `tab`。分面组成（现为开发/质量/回归/会话四分面，含 `add-test-regression-tab` 扩展）、切换交互、按需加载门控等其余条款不变。

## MODIFIED Requirements

### Requirement: 项目页分面导航容器

SPEC 列表页（项目页，路由 `/projects/:name`）SHALL 在**项目名称下方**渲染一个 `Tabs` 分面导航容器，作为页面的主内容组织方式。

- Tabs 的选中态 SHALL 持久化到 URL 查询参数 `tab`（合法值 `dev`/`quality`/`regression`/`session`，缺省 `dev` 且缺省不写参）；选中态为缺省值时 URL MUST 无 `tab` 参数（原「MUST NOT 持久化到 URL」条款废除）。
- 页签切换的写入 MUST 采用 replace 语义，MUST NOT 为切换操作新增浏览器历史条目（原「切换分面不改变路由」条款保持：MUST NOT 整页刷新、路由路径不变）。
- 刷新页面后 MUST 恢复刷新前的选中分面（原「刷新回到默认分面」条款废除）；URL 无 `tab` 参数时 MUST 回到默认「开发」分面。
- Tabs 的分面组成为「开发」「质量」「回归」「会话」四个分面（顺序固定，含 `add-test-regression-tab` 扩展的「回归」分面），默认选中「开发」，Tabs 容器在桌面与移动端两种视口下均渲染——上述条款维持既有规范不变。

#### Scenario: 页签选中态持久化

- **WHEN** 用户点击「回归」页签
- **THEN** URL 查询串 MUST 出现 `tab=regression`，页面原地切换内容（不整页刷新、不新增历史条目）

#### Scenario: 刷新保持当前分面

- **WHEN** 用户当前位于「会话」分面并刷新页面
- **THEN** 刷新后 MUST 仍停在「会话」分面（URL `tab=session` 恢复），且 MUST NOT 隐式启动会话进程

#### Scenario: 缺省页签不写参

- **WHEN** 用户从「回归」页签切回「开发」页签
- **THEN** URL 中的 `tab` 参数 MUST 被移除（缺省值不写参）
