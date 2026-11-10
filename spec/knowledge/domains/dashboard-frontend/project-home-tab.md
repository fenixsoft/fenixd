# 项目首页页签（文件与 README 浏览）

<!-- knowledge: capability=project-home-tab rev=2
     sources=spec/changes/add-project-home-tab,spec/knowledge/_inbox/done/dashboard-smoke-prismlight-routes-1110.md -->

项目详情页（`/projects/:name`）「项目首页」分面：仿 GitHub 项目页形态的**只读文件浏览**——文件树、README GFM 渲染、文件内容查看与下载（文本 / Markdown / 代码高亮 / 图片分通道渲染），由后端 project-files 四端点支撑。边界：无文件编辑/写入、无分支/标签切换、无 git 历史列表、无文件名搜索、无 SSE 实时刷新（每次进入目录拉取即新鲜）、符号链接目录不展开。

## 规则

- **页签占位与门控**：分面位于项目页 Tabs 首位（key `home`），默认选中分面仍为「功能开发」；数据仅在分面被选中时拉取 project-files API，未选中零请求；切离后在飞结果静默丢弃（不报错弹窗）；同 path 结果进程内缓存（组件卸载即弃），回到分面不重复请求。
- **界面形态真相源**：布局与组件选型以本能力 SPEC 原型定稿为准（工具栏 → 根目录最近提交条 → 面包屑 → 文件表格 → README 渲染盒 / 文件内容盒）；颜色经 theme token 引用、字号落 11/12/13/14 阶、时间数值 tabular-nums、零动效。
- **文件表格**：三列「名称 / 最近提交信息 / 最近提交时间」；目录条目先行（同类型按名称不区分大小写升序），提交信息单行溢出省略，无提交历史的条目显示「—」；窄屏视口（<768px）仅渲染名称列。目录条目数上限 200：超出部分截断，list 响应附 `truncated_count` 字段，前端显示截断提示（如「仅展示前 200 项」）。
- **目录与文件行均可点击**：目录行进入子目录，文件行打开内容视图。
- **目录导航原地更新**：进入子目录或回退仅原地更新列表与面包屑，不整页刷新、路由路径保持 `/projects/:name` 不变；面包屑层级与当前目录一一对应（根节点=项目名，如 `fenixd / core / dashboard`），文件视图打开时末段为该文件名，点击文件名前任意层级回退到对应目录。
- **URL path 持久化**：浏览位置持久化到查询参数 `path`（仅 `tab=home` 时承载）——进入子目录或打开文件写入 `path=<相对路径>`（URL 编码，replace 语义不新增浏览器历史条目），回根目录移除 `path`（`tab=home` 保留）；`tab≠home` 时 `path` 不出现。带参直达：`?tab=home&path=core/dashboard` 直接渲染该目录视图，`path` 指向文件时直接打开内容视图。带参直达是**挂载时一次性 seed**：`?path=` 仅在路由组件挂载时惰性读取一次（仅 `tab=home` 时消费），此后浏览位置由页内导航驱动写回——同页 hash 变更（组件复用不重挂载）不会重新解析 seed，带参直达冒烟必须整页加载；`path` 指向文件的直达实现为先 `GET list?path=<文件>` 得 404（list 仅服务目录）再回退父目录 + 文件选中，console 中该条 404 资源日志是预期行为非故障。
- **文件内容查看**：文本文件返回 `{content, lines, bytes, truncated}`，文本大小上限 256 KiB，超出截断并置 `truncated=true`，前端提示「文件过大，仅展示前 256 KB，下载查看全文」；图片文件不经文本通道，走 raw 内联直显（见「内容渲染分通道」条）；其余二进制文件（前 8 KiB 含 NUL 字节判定）不返回文本（`binary=true`），内容区显示「二进制文件，暂不支持预览」+ 下载按钮（NUL 启发式对 UTF-16 文本会误判二进制，降级为可下载不预览，属设计内损失）。内容盒头部含文件图标 / 文件名 / 行数与字节数（tabular-nums）/「下载」按钮，内容区按扩展名分通道渲染（见下条）。
- **内容渲染分通道**：内容区按扩展名分流渲染——Markdown（`md`/`markdown`）走既有 react-markdown 安全渲染管线（与 README 同源管线，SafeLink 协议白名单）；图片（白名单扩展名）经 raw 端点内联 `<img>` 直显；代码类经 PrismLight 语法高亮渲染；其余类型一律纯文本兜底，未知形态不崩。
- **代码高亮 = PrismLight 轻量构建**：首屏 chunk（`list.tsx` 链）MUST 用 `PrismLight` + `registerLanguage` 显式注册语言集（`ProjectCodeBlock.tsx` 的 REGISTERED 数组），MUST NOT `import { Prism }` 全量构建进首屏——全量 Prism 会把 refractor 全部语法拖进首屏 chunk；claude-msg 链路的全量 Prism 在独立异步 chunk（dist 3173.async.js）可照旧，前例不可照搬到首屏链。语言语法模块自包含依赖链（如 cpp 自带 import c），注册顺序无约束；`.vue` 无专属 Prism 语法，映射 `markup`（单文件组件主体是模板）。未知语言安全：refractor 分支 try/catch 回退纯文本，`language='text'` 短路兜底。
- **文件下载**：内容盒「下载」经 `GET /api/project-files/download` 触发浏览器下载（`Content-Disposition: attachment`，文件名取 basename 并 RFC 5987 编码防注入），对任意文件（含二进制）可用；Content-Length 取 stat 实值，64 KiB 分块流式发送，不限文件大小。
- **README 渲染**：项目根存在 `README.md`（回退 `readme.md`）时，根目录视图在文件列表下方以 GFM 安全渲染 README 全文——复用既有 react-markdown + `markdownComponents` 安全渲染族（与 spec-doc-view 同源管线，SafeLink 协议白名单过滤），MUST NOT 引入新的 markdown 渲染路径；README 内容走 project-files 文本通道（受同一 256 KiB 截断与越界防护约束，超限截断展示并提示）；两者均不存在时不渲染空 README 盒；打开任意文件时 README 盒隐藏，返回目录后恢复。
- **git 属性展示**：文件表格每行（含目录行）显示该路径最近一次提交的信息摘要与时间（相对时间，六档秒/分/时/天/月/年）；根目录视图顶部显示整仓最近一次提交（作者 / 短 hash / 相对时间），打开文件时不渲染。目录条目的提交属性取该目录路径下最近一次提交（`git log -1 -- <dir>` 语义）；git 属性逐条目单飞 `git log -1` 获取，不做批量化预取（200 上限封顶下毫秒级）。
- **列表边界 = git 可见集合**：文件集合单源为 `git ls-files --cached --others --exclude-standard`（在项目根执行），任意层级列表都不出现 gitignored 路径（node_modules / dist / .fenix 等）；`.git` 目录全链路（列表 / README 盒 / 内容 / 下载）永不触及。集合按 `.git/index` mtime 做进程内缓存（30s TTL + mtime 变化即失效），目录查询在集合上前缀分组构建。未跟踪且未 gitignore 的临时文件出现在列表属「工作树实况」语义（与 GitHub 一致），非缺陷。
- **project-files API 四端点**：`GET /api/project-files/list?project&path`（目录列表：`branch` / `latest` / `entries` / `readme` / `non_git`）、`GET /api/project-files/content`（文本内容）、`GET /api/project-files/download`（原始字节流，attachment）、`GET /api/project-files/raw`（图片内联字节流：扩展名白名单 png/jpg/jpeg/gif/webp/bmp/ico/avif/svg 按扩展名精确下发 Content-Type 供 `<img>` 直显，非图片扩展与目录 400、不存在 404，svg 追加 CSP sandbox——SVG 可内嵌 script，内联场景一律禁脚本；保存文件走 download 通道）。`readme` 字段按 README.md → readme.md 判定链仅在根目录查询时返回；`non_git=true` 时 entries 为空、branch/latest 为 null。分支名取 `git rev-parse --abbrev-ref HEAD`，detached HEAD 显示短 hash。四端点均不参与 304 协商（ETag 签名函数返回 None）——文件树含实时 git 属性，宁缺 304 不假 304。
- **路径安全（后端硬约束）**：`project` 参数必须解析为 registry 内存在的项目（未知项目 404、缺参 400，对齐 `_project_query_or_error` 口径）；`path` 经 URL 解码后 `resolve()` 必须 containment 于项目根内（拒 `..`、绝对路径、符号链接逃逸），越界返回 400 且响应体不含内部路径细节；`path` 指向不存在的路径返回 404；list 通道仅服务集合内路径（集合外路径 404），content/download 对 gitignored 路径按磁盘实况校验 containment 后照常服务（工作树实况语义）；`path` 解析为已存在的目录时 content/download 返回 400（目录不经内容/下载通道，list 通道正常服务目录）。
- **分支只读**：工具栏分支 Select 仅渲染当前分支单选项并附只读提示，不提供分支/标签切换（原型中分支/标签为假数据演示，非能力）。
- **非 git 项目空态**：非 git 仓库或无提交历史的注册项目展示 Empty 空态 +「该项目不是 git 仓库或暂无提交历史」，不报错弹窗、不渲染破损列表。

## 代码锚点

- 主实现：`core/dashboard/data/project_files.py`（文件集合与缓存、git 属性、内容通道、路径安全）、`core/dashboard/routes/project_files_routes.py`（三端点薄 handler mixin）、`core/dashboard/routes/base.py`（GET 路由表接线）、`core/dashboard/server.py`（mixin 挂载）
- 前端：`core/dashboard/static/src/pages/projects/components/ProjectHomeTab.tsx`（分面组件）、`core/dashboard/static/src/pages/projects/components/ProjectCodeBlock.tsx`（PrismLight 代码高亮块与语言注册）、`core/dashboard/static/src/pages/projects/components/projectHomeShared.ts`（扩展名→渲染通道分流与语言映射）、`core/dashboard/static/src/pages/projects/list.tsx`（页签首位接线、tab/path 参数解析与写回）、`core/dashboard/static/src/services/dashboard.ts`（API 函数）
- 守卫测试：`tests/test_dashboard_project_files_api.py`、`core/dashboard/static/tests/projectHomeTab.test.mjs`

## 溯源

- 2026-11-10 add-project-home-tab（spec/changes/add-project-home-tab/） — 新建本能力：项目首页分面（文件树浏览 / README GFM 渲染 / 文件内容查看与下载 / URL path 持久化 / 按需加载门控 / 路径越界防护 / project-files 三端点契约），原型确认环两轮批注定稿后入库（UI 真相源随 SPEC 目录归档迁移）
- 2026-11-10 dashboard-smoke-prismlight-routes-1110（spec/knowledge/_inbox/done/dashboard-smoke-prismlight-routes-1110.md） — 折叠五点增强批次（bento 帧统一 / md 管线渲染 / PrismLight 代码高亮行号 / 图片 raw 直显 / 纯文本兜底）冒烟结论：内容渲染分通道与 PrismLight 首屏轻量构建纪律（禁全量 Prism 进首屏、未知语言纯文本回退、vue→markup）、raw 图片内联端点契约（三端点扩四端点）、`?path=` 挂载一次性 seed 与文件 seed 404 回退预期
