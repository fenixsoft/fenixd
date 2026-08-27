# ui-theme Spec（delta）

## ADDED Requirements

### Requirement: 配置页「界面风格」页签

系统 SHALL 在配置页面（用户级与项目级共用同一渲染入口）的页签栏新增「界面风格」页签，内含「黑色风格」「白色风格」两个单选选项。该页签与两个选项在用户级和项目级配置页 SHALL 均可见，行为一致（主题是 Dashboard 全局属性，不随配置作用域变化）。未设置任何偏好时默认选中「黑色风格」。该页签的选项 SHALL 不参与「保存配置」按钮的持久化（即 SHALL NOT 写入 config.yaml 或任何 fenix 配置文件），选择 SHALL 即时生效并持久化到浏览器本地（见「主题偏好持久化与启动恢复」要求）。页签外观与交互 SHALL 复用既有配置页页签模式（`config-tabs` 内的 `tab-btn`/`tab-pane`），风格页签切换不影响其它页签的输入状态。

#### Scenario: 配置页显示界面风格页签与两选项
- **WHEN** 打开任一项目（或用户级）的配置页
- **THEN** 页签栏出现「界面风格」页签，点击后显示「黑色风格」「白色风格」两个单选选项，且默认选中「黑色风格」（未设置偏好时）

#### Scenario: 用户级与项目级配置页均可见
- **WHEN** 分别在用户级配置页与某项目配置页打开「界面风格」页签
- **THEN** 两处均显示相同的两个选项且行为一致（与当前配置作用域无关）

#### Scenario: 主题选择不写入配置文件
- **WHEN** 将主题切换为「白色风格」后点击「保存配置」
- **THEN** 用户级与项目级 config.yaml 中均不出现主题相关键（如 `ui.theme`），保存内容与切换前相比无主题字段差异；刷新后主题仍为白色（说明由浏览器本地持久化保持）

#### Scenario: 切页签不丢失行为
- **WHEN** 在「界面风格」页签选择「白色风格」，随后切换到「并行度设置」页签再切回
- **THEN** 「界面风格」页签仍选中「白色风格」，其它页签输入值未受影响

### Requirement: 主题即时切换与全局应用

系统 SHALL 在用户选择「白色风格」时立即将整个 Dashboard（概览、SPEC 列表、SPEC 详情、配置页、运维记录、各模态弹窗、告警 banner、文档弹窗等全部视图与组件）切换为浅色配色，无需刷新页面或重启 daemon；选择「黑色风格」时 SHALL 立即恢复深色配色。切换 SHALL 通过设置 `<html>` 根元素 `data-theme` 属性（值为 `light` / `dark`）驱动 CSS 变量切换实现；浅色主题下根元素 `color-scheme` SHALL 为 `light`（原生控件、滚动条等随之适配），深色主题保持 `dark`。切换 SHALL NOT 触发页面重载、NOT 重新拉取任何 API、NOT 改变页面内容与实际布局（仅配色变化）。未显式设置时根元素默认深色，与现状一致。

#### Scenario: 切换到白色风格全站变浅
- **WHEN** 在配置页「界面风格」页签选择「白色风格」
- **THEN** 不刷新页面即生效：`<html>` 根的 `data-theme` 为 `light`，`body` 计算背景色为浅色系（如接近 `#ffffff`），普通文本为深色系；当前所在视图（如仍在配置页）内容不重置

#### Scenario: 切回黑色风格恢复
- **WHEN** 处于白色风格时选择「黑色风格」
- **THEN** 立即恢复深色配色（`data-theme` 为 `dark`，`body` 计算背景色回到深色系），与默认深色一致

#### Scenario: 切换不刷新不重新请求
- **WHEN** 在任意视图下切换主题（监听网络请求与页面加载事件）
- **THEN** 无整页重载（`document` 未重新加载、URL 不变），除既有轮询/SSE 流量外无新的 API 请求因切换而产生

#### Scenario: 非配置页亦即时生效
- **WHEN** 在配置页切换到「白色风格」后导航到概览页（不刷新）
- **THEN** 概览页以浅色配色渲染（卡片、文本、状态徽标均可读）

### Requirement: 主题偏好持久化与启动恢复（防闪烁）

系统 SHALL 将主题偏好持久化在浏览器 `localStorage`（键 `fenix.theme`，取值仅 `dark` / `light`）。用户每次切换 SHALL 立即更新该键。页面加载时 SHALL 在第一帧绘制之前应用主题：在 `index.html` 的 `<head>` 内联一段脚本（先于外部样式表渲染），读取 `fenix.theme` 并设置根元素 `data-theme`；刷新或重开页面（同一浏览器）后 SHALL 恢复上次选择且 SHALL NOT 出现「先按深色绘制再闪成浅色」的闪烁。取值缺失或非法（非 `dark`/`light`）时 SHALL 回退为 `dark`。该持久化 SHALL NOT 使用服务端存储。

#### Scenario: 刷新后保持白色主题
- **WHEN** 选择「白色风格」后刷新页面
- **THEN** 页面直接以浅色配色渲染，`localStorage.fenix.theme === 'light'`，`data-theme === 'light'`，无深色瞬时闪烁

#### Scenario: 无偏好时默认深色
- **WHEN** 清除 `localStorage`（或首次访问）后打开 Dashboard
- **THEN** 以深色配色渲染（`data-theme` 为 `dark`），与现有行为一致

#### Scenario: 非法值回退深色
- **WHEN** `localStorage.fenix.theme` 被手工设为非法值（如 `'blue'`）后刷新
- **THEN** 页面以深色渲染且不报错，`data-theme` 为 `dark`

#### Scenario: 首帧前应用（结构性断言）
- **WHEN** 查看 `index.html` 源码
- **THEN** `<head>` 内于外部样式表之前存在内联脚本：读取 `fenix.theme` 并设置 `document.documentElement.dataset.theme`，非法/缺失回退 `dark`，且该脚本不依赖 `app.js` 等后加载脚本

### Requirement: 白色主题覆盖完整且无不可读组合

系统 SHALL 提供覆盖全部既有 UI 面的浅色调色板，与深色主题共用同一套 CSS 变量（`--page`、`--surface`、`--surface-2`、`--ink`、`--ink-2`、`--muted`、`--hairline`、`--hairline-strong`、状态色、分类色等）：浅色主题下页面底色、卡片面、内嵌块、主/次/弱文本、分隔线、顶栏、导航、页签、按钮、表单、表格、SPEC 状态徽标、timeline（含 vendor 时间线组件）、模态遮罩与弹窗、banner、代码块等 SHALL 全部映射为浅色变量取值，SHALL NOT 出现白字灰底、白底白字等不可读组合，状态色与分类色 SHALL 在浅色背景上保持可辨识的对比度。`style.css` 中散落的硬编码颜色值（如顶栏半透明深色背景、特定文字色）SHALL 收敛为 CSS 变量（或在浅色作用域内提供变量派生覆盖），使两套主题无需逐条硬编码覆盖。vendor 样式（如 react-vertical-timeline 的白色内容面与 `#303e49` 标题色）SHALL 由既有变量驱动覆盖规则接管，保证浅色变量下仍正确。深色主题的当前视觉 SHALL 保持不变（默认深色为回归基准）。

#### Scenario: 白色主题关键面色断言
- **WHEN** 处于白色风格，在概览页与配置页分别读取 `body`、卡片容器、主文本的计算样式
- **THEN** `body` 背景为浅色（亮度高），卡片背景为白色或比页面底略深/略浅的可区分浅色，主文本为深色（对比度满足正常阅读），三者均为浅色系的变量派生值

#### Scenario: 顶栏与弹窗适配
- **WHEN** 处于白色风格，查看顶栏与打开任一模态弹窗（如运行记录弹窗）
- **THEN** 顶栏背景为浅色半透明/浅色实底（不再使用深色半透明如 `rgba(13,13,13,…)`），弹窗内容面为浅色，遮罩仍以深色半透明呈现且可辨识

#### Scenario: timeline 与状态徽标可读
- **WHEN** 处于白色风格，打开运维记录（timeline）与 SPEC 列表
- **THEN** timeline 内容块为浅色（跟随 `--surface`），其标题/日期/状态文字为深色系；SPEC 状态徽标（通过/警告/异常/bug）在浅色背景上文字与底色对比可辨识（非深色主题下专属的不可读配色）

#### Scenario: 深色主题不回归
- **WHEN** 未设置偏好（默认深色）遍历概览、SPEC 列表/详情、配置、运维记录
- **THEN** 各面颜色与本次改动前一致（变量映射未变、无新硬编码污染深色视觉）