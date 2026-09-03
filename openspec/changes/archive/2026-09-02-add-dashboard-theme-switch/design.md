# Design: add-dashboard-theme-switch

## Context

Dashboard 为纯前端静态单页应用（`core/dashboard/static/`，由 daemon 同进程托管）。深色主题通过 `style.css` 的 `:root` CSS 变量定义，但约 57 处颜色以字面量散落在具体规则中（顶栏 `rgba(13,13,13,0.92)`、若干 `#fff` 按钮文字、阴影等），vendor 时间线 bundle（react-vertical-timeline）默认浅色已被 `#tl-root` 变量驱动覆盖规则接管。配置页 `renderConfig()`（app.js:1616）现有 4 个页签，全部通过「保存配置」写入 config.yaml。

需求：配置页新增「界面风格」页签，提供黑色/白色两套风格并支持即时切换。**用户已明确决策**：主题是 Dashboard 自身的展示属性而非 fenix 配置信息，偏好存于浏览器 `localStorage`，不写入 config.yaml、无需重启 daemon，属纯前端改动。

## Goals / Non-Goals

**Goals**
- 浅色（白色）+ 深色（黑色）两套完整可用的配色，默认深色与现状一致。
- 配置页新增「界面风格」页签，切换即时全站生效，偏好按浏览器持久化，刷新不闪烁。
- 后端（server.py、config schema、daemon）零改动。

**Non-Goals**
- 不引入「跟随系统」（`prefers-color-scheme`）三态选项（需求为两态，留作后续扩展）。
- 不做主题的跨浏览器同步（无服务端存储）。
- 不重写现有样式体系、不引入 CSS 框架/预处理器。

## Decisions

### D1: 主题用 `data-theme` 根属性 + CSS 变量覆盖，而非独立样式表

`<html>` 根元素以 `data-theme="dark|light"` 标识当前主题；`style.css` 中新增 `:root[data-theme='light']` 块，覆盖与深色完全同名的变量（`--page`、`--surface`、`--ink`…）为浅色取值；深色为 `:root` 默认。切换 = 改一个属性，全站样式随之变化，既有所有 `var(--*)` 引用（含 `#tl-root` vendor 覆盖）自动适配，无需任何逐条覆盖。

- **备选**：独立 `light.css` 全量重声明 —— 与变量派生重复、两套主题漂移风险大；否决。
- **备选**：`body.class` 作用域 —— 遮罩、弹窗等挂 `body` 之外节点时易漏；根属性覆盖全局，选取根属性。

### D2: 浅色调色板：沿用深色色相，正文/背景反转，强调色按浅底对比度加深

浅色板与深色板共用变量名，取值原则：

| 变量 | 深色（现） | 浅色 | 说明 |
|---|---|---|---|
| `--page` | `#0d0d0d` | `#f4f4f1` | 页面底（近白暖灰） |
| `--surface` | `#1a1a19` | `#ffffff` | 卡片面 |
| `--surface-2` | `#242422` | `#ebebe6` | 内嵌块/代码底 |
| `--ink` | `#ffffff` | `#1f1f1e` | 主文本 |
| `--ink-2` | `#c3c2b7` | `#4a4944` | 次文本 |
| `--muted` | `#898781` | `#7a7871` | 弱文本 |
| `--hairline` | `rgba(255,255,255,.10)` | `rgba(0,0,0,.10)` | 分隔线 |
| `--hairline-strong` | `rgba(255,255,255,.18)` | `rgba(0,0,0,.18)` | 强分隔线 |
| `--good/--serious/--critical` | 原色 | 保持 | 状态色，验证后可改深 |
| `--warning` | `#fab219` | `#b06d00` 类加深变体 | 浅底上加深保证对比 |
| `--blue/--aqua/--violet` | 原色 | 按浅底对比度适当加深 | 分类色可读性 |

状态/分类色原则：白底上保持 AA 对比的深色变体，深色板不动。同时新增少量主题相关变量用于现状中无法映射的硬编码（见 D3）。

### D3: 硬编码颜色收敛为变量（审计式，非全量重构）

对现有 ~57 处颜色字面量逐一审计分类：
1. **必须变量化**：主题相关面 —— 顶栏半透明背景（浅色下需还原为浅色半透明/frosted）、阴影/光晕色、部分按钮文字色、遮罩色、`color-scheme` 等 → 新增（如 `--topbar-bg`、`--shadow`、`--overlay` 等）并在两套主题板定义。
2. **两主题通用可保留**：如「蓝底按钮上的 `#fff` 文字」（两种主题下 active 按钮底色均为深蓝，白字在浅色页面上依然对比充分）→ 保持字面量，不引入变量。

实施中在 `style.css` 内逐处 grep 比对，输出收敛清单；目标不是消灭字面量，而是消灭「换肤后不可读」的字面量。

### D4: 防闪烁 —— `<head>` 内联脚本先行应用

`index.html` 的 `<head>` 内、两个 `<link rel="stylesheet">` 之前，内联一段无依赖小脚本：

```html
<script>
  try {
    var t = localStorage.getItem('fenix.theme');
    if (t !== 'light' && t !== 'dark') t = 'dark';
    document.documentElement.dataset.theme = t;
  } catch (e) { document.documentElement.dataset.theme = 'dark'; }
</script>
```

- **备选**：`app.js` 加载后应用 —— 首帧会以深色绘制再跳变（FOUC）；否决。
- try/catch 兜底：localStorage 被禁用/异常时回退深色，页面照常可用。

### D5: 配置页页签与「保存配置」解耦

「界面风格」作为第 5 个页签追加在「审批模式」之后，复用既有 `config-tabs` 的 `tab-btn`/`tab-pane` 结构；单选组复用「审批模式」的 radio 视觉样式（`.approve-mode-row` 风格）。与其它页签的关键差异：

- 选项初值读 `localStorage.fenix.theme`（非法回退 `dark`），**不读取** `data` 传入的配置快照
- 切换即调用主题应用函数 + 写 localStorage，**不进入** `collectConfigData()`/保存路径，`lastConfigData` 不受影响
- 配置页重绘（轮询刷新）时该页签状态从 localStorage 恢复，不丢失

### D6: 主题应用为单一全局函数

主题切换在 `app.js` 收敛为一个函数（如 `setTheme(theme)` → 写 `documentElement.dataset.theme` + localStorage；`initTheme()` → 供配置页初始化选项与其它视图的同步态），避免多处在 DOM 上散落修改。所有视图共用根属性，无需各页面单独处理。

## Risks / Trade-offs

- [️浅色主题对比度不足（状态/分类色在浅底上发白）] → D2 中状态色按浅底加深；spec 含「状态徽标可读」浏览器断言场景兜底。
- [vendor bundle 残留硬编码浅色（timeline h2 `#303e49`、content 白底、箭头白边）在浅色下错位] → 既有 `#tl-root` 覆盖规则已变量化；task 含逐 vendor 颜色审计 + 浏览器实测。
- [内联脚本导致 CSP/语法问题或 localStorage 异常] → 脚本为纯 vanilla 单行逻辑 + try/catch，异常静默回退深色（现状），不阻塞页面任何功能。
- [深色主题回归] → 默认 `data-theme` 缺省即深色视觉零变化；spec 含深色回归场景，浏览器验证含默认深色遍历。
- [切换瞬间的过渡闪烁（如背景先变白再改文字色）] → 顺带为 `body` 背景等关键面加 `transition`（可接受）或不做过渡直接整体切换；实现时以「无瞬时可读性劣化」为验收，不做强制过渡动画。

## Migration Plan

纯前端静态文件改动（index.html / style.css / app.js），安全可回滚（`git revert` 即恢复，`localStorage` 键因浏览器隔离无残留服务端状态）。无数据迁移。上线无需重启 daemon（静态资源随请求即得），但建议浏览器验证完整走一遍两主题的六类场景。

## Open Questions

- 浅色主题下顶栏采用「浅色半透明 + 模糊」沿用现状 `backdrop-filter`，还是实底浅色？（倾向保留 frosted 半透明，与外层变量一致，实现时按视觉决策，不在 spec 上锁死）
- 状态色浅底加深的具体色值（如 `--warning` 目标色）由实现时按 AA 对比实测确定，spec 只约束「可辨识」，不锁具体 hex。