# Tasks: add-dashboard-theme-switch

## 1. 样式基础：浅色调色板与变量收敛

- [ ] 1.1 在 `style.css` 新增 `:root[data-theme='light']` 块，按 design D2 色值表定义浅色调色板（`--page`/`--surface`/`--surface-2`/`--ink`/`--ink-2`/`--muted`/`--hairline`/`--hairline-strong` 及新增主题变量、状态/分类色），`:root` 默认深色不变
- [ ] 1.2 浅色块设置 `color-scheme: light`（深色保持 `color-scheme: dark`）
- [ ] 1.3 审计 `style.css` 全部硬编码颜色字面量（~57 处）：将换肤后不可读的面收敛为变量（顶栏半透明背景 → 引入 `--topbar-bg`-类变量并在两板定义；遮罩色、阴影/光晕色、按钮文字等逐一判定），可在两主题通用使用的字面量（如蓝底按钮上的白字）保持不动并记录判定
- [ ] 1.4 状态/分类色浅底对比度处理：`--warning` 等浅底上偏浅的颜色加深（如 `#b06d00` 类变体），深色板取值不动；以白底 AA 对比（≥4.5:1 正文面）为基准

## 2. 首帧防闪烁

- [ ] 2.1 `index.html` 的 `<head>` 内、两个外部样式表之前，内联主题应用脚本（design D4）：读取 `localStorage.fenix.theme`，仅接受 `light`/`dark`，非法/缺失回退 `dark`，设置 `document.documentElement.dataset.theme`
- [ ] 2.2 内联脚本以 try/catch 包裹，localStorage 异常时静默回退深色，不阻塞页面加载

## 3. 配置页页签与切换交互

- [ ] 3.1 `app.js` 的 `renderConfig()` 在现有 4 个页签后新增第 5 个「界面风格」页签（`tab-btn` + `tab-pane`，复用 `config-tabs` 结构与既有页签切换逻辑），用户级与项目级配置页共用入口自动生效
- [ ] 3.2 页签内渲染「黑色风格」「白色风格」两个单选选项（复用审批模式 radio 视觉样式），初值读 `localStorage.fenix.theme`（非法回退 dark），不读配置快照 `data`
- [ ] 3.3 在 `app.js` 实现单一主题函数：`setTheme(theme)` 写 `documentElement.dataset.theme` 并写 `localStorage.fenix.theme`；`initTheme()` 读取/校验偏好供渲染与其它视图同步使用
- [ ] 3.4 绑定单选 change 事件：切换即时全站生效，不触发重载/不重新请求 API
- [ ] 3.5 「界面风格」页签选项不进入 `collectConfigData()`/「保存配置」写入路径，`lastConfigData` 快照与保存内容均不含主题字段；配置页轮询重绘后该页签从 localStorage 恢复选中态

## 4. 全局适配核查

- [ ] 4.1 审计 vendor（fenix.bundle.css 时间线等）残留硬编码颜色：`#tl-root` 覆盖规则确保全部变量驱动（content 白底、`#303e49` 标题、箭头白边等），浅色/深色两板下均正确
- [ ] 4.2 浏览器实测两主题下全视图遍历：概览、SPEC 列表、SPEC 详情、配置页、运维记录 timeline、运行记录弹窗、文档弹窗、告警 banner —— 无白字灰底/白底白字等不可读组合，状态徽标对比可辨识
- [ ] 4.3 深色主题回归核查：未设置偏好时（默认深色）全站视觉与改动前一致，无新增硬编码污染深色

## 5. 验证

- [ ] 5.1 playwright/浏览器验证 spec `ui-theme` 全部场景：页签可见与默认选中、两级配置页一致、主题不写入 config.yaml、切换即时全站生效（`data-theme`/计算样式断言）、切回恢复、无重载无新增请求、非配置页即时生效、刷新保持白色、无偏好默认深色、非法值回退深色、首帧前应用（head 内联脚本结构断言）、白色主题关键面色/顶栏/弹窗/timeline/徽标可读、深色不回归
- [ ] 5.2 回归既有测试：`tests/test_dashboard.py` 及其它 dashboard 相关测试全绿