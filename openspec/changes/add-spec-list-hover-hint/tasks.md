# Tasks: add-spec-list-hover-hint

## 1. 名称 hover Why 提示

- [ ] 1.1 在 `app.js` 新增 hint 状态与缓存：`const whyCache = new Map()`（键 `project│spec`，值 `{status: 'loading'|'done'|'empty', html}`）；`fetchWhy(project, spec)` 按缓存键返回（done→html，empty→null，loading→复用进行中的 Promise），未命中发起 `/api/spec-doc?project=&spec=&doc=proposal`，`found=false` 或提取为空缓存为 `empty`
- [ ] 1.2 新增 `extractWhy(markdown)`：按行扫描，匹配 `/^##\s+why\s*$/i` 标题行，收集其后到下一个 `/^##\s/m` 标题行（不含）或文末的内容，`trim()` 后返回；无标题或段落为空返回 `null`
- [ ] 1.3 `specRow()` 名称单元格上通过事件委托绑定 `mouseenter`（`spec-name-cell` 上 `data-project`/`data-spec` 属性提供目标）：200ms 延迟后 `showWhyHint(target)`，期间再次 `mouseenter`（重渲染后新节点）重置计时器；`mouseleave` 清除计时器并隐藏
- [ ] 1.4 新增 `showWhyHint(target)`：`.getBoundingClientRect()` 定位，`fetchWhy` 返回期间显示「加载中…」，`done` 用 `mdRender(html片段)`（Why 段已是 markdown 子串，直接 `mdRender`）填充 hint 容器，`empty` 直接隐藏
- [ ] 1.5 新增 div 提示框：`app.js` 动态创建 `#spec-name-hint` 容器（`position: fixed`，`max-width: 420px`，`max-height: 60vh`，`overflow-y: auto`，`z-index` 高于表格）；定位优先名称下方、视口右侧越界左移、底部越界上移（翻转）；可见性用 hidden class
- [ ] 1.6 关闭路径：`document` 捕获阶段监听 `click` 与 `scroll`（覆盖表格 wrap 滚动与窗口滚动）时隐藏；`mouseleave` 名称单元格时若鼠标未进入 hint 容器内也隐藏（或简化：一律隐藏）

## 2. 「错误」列改信息子行

- [ ] 2.1 `renderProject()` 的 `headers` 数组删除 `{ key: 'error', label: '错误' }` 项
- [ ] 2.2 `sortValue()` 删除 `case 'error'` 分支（排序键随列移除）
- [ ] 2.3 `specRow()` 删除 `err` 变量与错误单元格 `<td>${err}</td>`；返回值为两个 `<tr>`：主行 + 条件信息子行；子行仅在 `s.error` 非空时输出 `<tr class="spec-info-row"><td colspan="${表头列数}">…</td></tr>`，`colspan` 从表头长度常量派生；消息内容 `esc(String(s.error))`，子行样式 `white-space: pre-wrap`，前缀「信息」小徽标
- [ ] 2.4 `s.error` 为 `null`/空字符串时仅返回主行，无子行、无额外行高

## 3. 样式

- [ ] 3.1 `style.css` 新增 `#spec-name-hint`（fixed 定位、阴影、背景层、圆角、内边距、滚动、markdown 正文排版复用既有 `.docmodal-body` 类或同款间距）与加载占位样式
- [ ] 3.2 `style.css` 新增 `.spec-info-row`（浅色底、左对齐、行内间距、`white-space: pre-wrap`，消息长时不破坏表格宽度）与「信息」小徽标样式
- [ ] 3.3 校验：hint 与子行样式在浅色/深色主题下与既有表格/弹窗视觉一致（沿用 `var(--…)` 变量）

## 4. 验证

- [ ] 4.1 启动 Dashboard（`bin/fenix_dashboard.py --serve` 或 skill 通道），打开含 proposal.md 的项目视图：悬停任一 SPEC 名称，提示框出现并渲染 Why 段（粗体/列表生效）；移开消失；重复悬停无网络请求（DevTools Network 面板确认缓存命中）
- [ ] 4.2 构造无 `## Why` 段的 spec 悬停：无提示框；`proposal.md` 缺失的 spec 悬停：无提示框
- [ ] 4.3 悬停时点击该行任意区域：行正常跳转 SPEC 详情，提示框同时消失
- [ ] 4.4 在 `STATE.md` 给某 spec 写入非空 `error` 字段：该行下方出现跨全列信息子行，长消息完整换行显示不截断；清空为 `null` 后刷新，子行消失
- [ ] 4.5 2 秒自动刷新后在含消息的 spec 行下仍显示信息子行；表头与任意行均无「错误」列；各剩余列排序（状态/名称/优先级/时间/进度/验证/耗时）仍正常
- [ ] 4.6 回归：`python3 -m pytest tests/test_dashboard.py` 通过；项目概览、详情页、运行弹窗、文档弹窗（「背景」「设计」按钮）不受影响