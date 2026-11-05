# Dashboard 帮助中心

<!-- knowledge: capability=help-center rev=3
     sources=spec/archive/2026-09-10-add-dashboard-help-center,spec/changes/unified-page-title-bar,spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md -->

Dashboard 内置的框架使用帮助入口：侧边栏直达的帮助中心页面，在线阅读 `docs/help/` 帮助文档集，文档更新无需重建前端。

## 规则

- 入口与导航：侧边栏设「帮助」菜单项（QuestionCircle 图标，路径 `/help`），菜单位于「运维」之下，完整顺序为概览、项目、设置、运维、帮助；页面标识由统一标题栏承载（顶栏渲染标题「帮助」）。
- 文档读取 API（只读、后端标准库实现零新依赖）：
  - `GET /api/help/docs` 列出框架仓库 `docs/help/` 全部合法 `.md` 文档，返回 `[{name, title}]`（title 取文档一级标题）；`README.md` 置顶，其余按文件名字典序（`NN-` 编号天然有序）；非 `.md` 文件不入清单。
  - `GET /api/help/doc?name=<file>` 返回单篇文档的 Markdown 原文。
  - 文档每请求实时读盘（`HELP_DOCS_DIR` 指向框架根 `docs/help/`），编辑文档后刷新页面即生效，无需执行前端构建。
- 路径防护：文档名必须匹配白名单 `[A-Za-z0-9._-]+\.md`，不匹配返回 400；`resolve()` 后不落在 `docs/help/` 内（目录穿越）返回 400；目录缺失或文件不存在返回 404；错误响应不泄露服务器文件系统信息。
- 页面布局：左侧文档目录 + 右侧 Markdown 正文；目录按编号排序、当前选中项高亮；URL 同步记录当前文档（`#/help?doc=<名>`），刷新后仍停留在该文档；未指定文档时默认渲染 `README.md` 目录索引。页面纵向滚动为文档级（滚动条跨标题区域），目录列 sticky 钉住不随页面滚走——滚动形态与钉位常数细则由 dashboard-frontend 域 `document-scroll-unify` 单源承载。
- 渲染：正文渲染标题、列表、表格、代码块与链接；`mermaid` 代码块渲染为图形，采用动态 import 按需加载（不放大首屏体积，实例首次初始化后复用），渲染失败回退显示原始代码文本且不白屏；普通代码块保持等宽字体展示。
- 页内导航：正文中指向其它帮助文档的相对链接在帮助页内切换渲染目标，不整页跳出。
- 容错与空态：`docs/help/` 目录缺失或为空时显示「暂无帮助文档」空态，无未捕获异常；单篇文档读取失败时正文区显示错误提示，目录保持可用。
- 移动端：视口宽度 <768px 时目录与正文不并排显示（上下堆叠或抽屉式切换），复用 useIsMobile + screen-xs 作用域适配模式；切换文档无横向滚动，正文文字不溢出。

## 溯源

- 2026-09-10 2026-09-10-add-dashboard-help-center（spec/archive/2026-09-10-add-dashboard-help-center） — 建立「帮助」菜单与 `/help` 路由、文档清单与单篇正文两个读取端点（动态读盘 + 白名单防穿越）、目录+正文布局与 mermaid 动态渲染、空态容错与移动端适配
- 2026-11-04 unified-page-title-bar（spec/changes/unified-page-title-bar/） — 顶栏面包屑全局退役，`/help` 位置指示改由标题栏页面标题承担（规则段移除面包屑条款，帮助页迁入统一标题栏控件）
- 2026-11-05 settings-help-document-scroll-unify（spec/knowledge/_inbox/done/settings-help-document-scroll-unify.md） — 布局规则随迁：页面文档级滚动、文档目录 sticky 钉住（滚动形态细则归 document-scroll-unify 单源）
