# Design: add-project-home-tab

## Context

项目详情页（`core/dashboard/static/src/pages/projects/list.tsx`，路由 `/projects/:name`）现有五分面 Tabs（dev/quality/regression/architecture/knowledge，`list.tsx:2230` 附近 items 数组），选中态经 `useSearchParams` + replace 语义持久化（`list.tsx:1858` 附近，缺省 dev 不写参）。各分面组件落 `pages/projects/components/<X>Tab.tsx`，active 门控按需拉取。后端为表驱动路由（`core/dashboard/routes/base.py` 三元组路由表）+ 资源 mixin（`routes/*.py` 薄 handler）+ 数据模块（`data/*.py`）三层，项目经 `server.project_by_name(name)` 解析（dict 含 `path` 即项目根）。

前端已有可复用资产：react-markdown + `markdownComponents`/`SafeLink` 安全渲染族（`components/markdown-shared`，SpecDocModal 同源）；`isMobile` 窄屏 hook（<768px）。用户经 fenix-prototype 原型确认环（vendor 层真组件原型，两轮批注迭代）明示认可定稿，原型入库 `spec/changes/add-project-home-tab/prototype/`（UI 真相源，具约束力）。

## Goals / Non-Goals

- **Goals**：项目首页分面（文件树 + README + 文件内容/下载）对齐原型；默认选中「功能开发」零改变；按需加载门控对齐既有四分面；后端 API 安全（越界防护）。
- **Non-Goals**：分支/标签切换（本期 Select 单值只读）；文件编辑/写入；git 历史页（log 列表）；搜索文件名；SSE 实时刷新文件树（每次进入目录拉取即新鲜）；符号链接目录展开（ls-files 集合天然不含链外路径，直接跳过）。

## Decisions

### D1 页签编排：首位插入、默认 dev 不变

`list.tsx` items 数组首项插入 `{key:'home', label:'项目首页', children: <ProjectHomeTab project={name} active={activeTab==='home'} />}`；`ListTab` 类型与 `parseListFilters` 的 tab 合法值域扩为六值。默认解析逻辑（无 `tab` 参数 → `dev`）**零改动**——「项目首页居首但不默认」由 items 顺序与缺省解析天然保证，不加任何特判。

### D2 后端 API 契约：三端点、数据模块单源

新文件 `core/dashboard/data/project_files.py`（数据逻辑）+ `core/dashboard/routes/project_files_routes.py`（薄 handler mixin）；`routes/base.py` GET 路由表接线三条（kind=exact，携带 ETag 签名函数返回 None 即不参与 304 协商——文件树含实时 git 属性，签名不廉价）；`server.py` 挂 mixin。

- `GET /api/project-files/list?project=<name>&path=<relpath>` → `{branch, latest: {author, hash, time}|null, entries: [{name, dir, last_commit: {hash, message, time}|null}], readme: "README.md"|null, non_git: false}`。readme 字段按 README.md → readme.md 缺省链判定（仅根目录查询时返回）；`non_git` 置 true（此时 entries 为空、branch/latest 为 null）标记非 git 项目（判定见 D3），前端据此渲染 Empty 空态。
- `GET /api/project-files/content?project=<name>&path=<relpath>` → `{content, lines, bytes, truncated, binary}`；文本读至 256 KiB 上限截断；二进制（前 8 KiB 含 NUL）置 `binary=true` 不带 content。
- `GET /api/project-files/download?project=<name>&path=<relpath>` → 原始字节流 + `Content-Disposition: attachment; filename*=UTF-8''<basename>`（RFC 5987 编码防注入）；handler 自写响应（不走 `_json`）。
- 端点命名对齐既有 `project-files` 前缀族；400/404 口径对齐 `project_routes._project_query_or_error`（缺参 400、未知项目 404）。

### D3 文件集合边界与 git 属性策略

- **集合单源**：`git ls-files --cached --others --exclude-standard`（在项目根执行，`cwd=项目根`）输出即文件集合全集；请求期按 `.git/index` mtime 做进程内缓存（TTL 30s + mtime 变化即失效），目录查询在该集合上做前缀分组构建，天然排除 gitignored（node_modules/dist/.fenix）与 `.git`。非 git 项目（命令失败/空仓）返回 `{entries: [], non_git: true}`，前端渲染空态。
- **提交属性**：列表每条目单飞 `git log -1 --format=%h%x1f%s%x1f%aI -- <entry>`（目录条目用目录路径，git 自动取目录下最近提交）；目录条目数上限 **200**（超出截断，响应附 `truncated_count`，前端提示「仅展示前 200 项」）。fenixd 实测最大目录（core/dashboard/static 根）在阈值内；每条目一次子进程在该量级为毫秒级，可接受——批量化（`git log --name-only` 一次遍历）留作后续优化，不进本期。
- **分支名**：`git rev-parse --abbrev-ref HEAD`；detached 返回 `git rev-parse --short HEAD`。
- **整仓最近提交**：`git log -1 --format=%an%x1f%h%x1f%aI`（仅根目录查询附带）。

### D4 内容通道安全

- **containment 双保险**：`path` 经 `urllib.parse.unquote` 后与项目根拼接 `Path(root, relpath).resolve()`，MUST `is_relative_to(root.resolve())`（拒绝 `..`、绝对路径、symlink 逃逸），越界 400 且响应体不含内部路径细节（对齐 `_api_project_describe` 泛化文案纪律）。list 通道另受 ls-files 集合约束（集合内路径必然 containment，双保险防未来改动回潮）。
- `.git` 全链路排除：list 靠集合边界；content/download 显式拒绝解析后落在 `<root>/.git` 内的路径（防御深层）。
- **下载**：Content-Length 取 stat 实值，流式读取分块发送（64 KiB chunk），不限文件大小。

### D5 前端组件与渲染管线复用

`ProjectHomeTab.tsx`：props `{project, active}`；`active` 门控首次 fetch（进入分面才请求，切离不再重复请求同一路径，回到分面按缓存直渲染——缓存粒度 `path` 键值，组件卸载即弃）。文件表格 antd Table（`pagination={false}`，row onClick）；面包屑 antd Breadcrumb 或原型同构自绘（以 prototype/ 为准）；内容盒 `<pre>` 等宽渲染；下载经隐藏 `<a download>` 触发（原型同款）。README 渲染复用 `Markdown remarkPlugins=[remarkGfm] components={markdownComponents}`（与 SpecDocModal 同族，SafeLink 白名单生效）——MUST NOT 新写 markdown 管线。窄屏两列隐藏用 `isMobile` hook 列定义分流（原型 narrow<768px 行为）。相对时间展示复用/对齐既有时间格式化惯例（无现成工具则组件内实现，秒/分/时/天/月/年六档）。

### D6 URL path 持久化

`path` 参数仅随 `tab=home` 写入/移除（replace 语义，并入既有 `setSearchParams` 防抖写回块）；根目录不写 `path`。直达解析：`parseListFilters` 扩展读取 `path`（仅 `tab=home` 时生效），`ProjectHomeTab` 以 initialPath 初始化浏览位置。

### D7 DESIGN.md 宪法对照（无偏离）

设计约束以仓库根 `DESIGN.md` 为准（红线：静态渲染零动画、配色单源、字号阶、tabular-nums、antd 陷阱）。原型按画像 token 生成，已合宪：颜色全部来自 theme.ts 既有 token（hover 文件名用 colorLink、灰字走 colorTextTertiary 三阶灰），字号全部落 11/12/13/14 阶，提交时间数值 tabular-nums，零新增动效（Tabs 维持未关 animated 的 antd 默认，与现产一致），**无偏离条款，无偏离声明段**。分面数据零值/空态口径：无提交历史的条目显示「—」（null 口径红线），非 git 项目走 Empty 空态。

## Risks / Trade-offs

- **[性能] 大目录逐条目 git log**：200 上限封顶 + 进程内缓存兜底；若实测 >2s 体验劣化，后续 SPEC 批量化（风险登记，不阻塞本期）。
- **[正确性] 二进制误判**：NUL 字节启发式对 UTF-16 文本会误判为二进制——降级为「可下载不预览」，损失可接受（GitHub 同策略）。
- **[安全] 下载文件名注入**：RFC 5987 filename* 编码 + basename 取名，双保险；响应头值禁含 CR/LF（encode 后天然排除）。
- **[一致性] ls-files 与磁盘实况漂移**：未跟踪且未 gitignore 的临时文件会出现在列表（`--others --exclude-standard` 语义即「工作树实况」），与 GitHub 一致，非缺陷。
- **[回归] list.tsx 页签插入**：items 数组插入属低风险结构变更，桌面/移动端 Tabs 行为不变；任务清单含「功能开发分面零回归」验证项兜底。
