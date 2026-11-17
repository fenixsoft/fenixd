# Spec: 项目首页页签（文件与 README 浏览）

项目详情页（SPEC 列表页，路由 `/projects/:name`）新增「项目首页」页签，仿 GitHub 项目页形态：文件树浏览 + README 渲染 + 文件内容查看与下载。本能力由 `add-project-home-tab` 引入。

**界面原型（UI 真相源）：`spec/changes/add-project-home-tab/prototype/index.html`**（vendor 层真组件原型，具约束力；渲染凭证见同目录 `screenshots/`）。凡涉界面布局、组件选型、文案、区块组织的 Scenario 均以 prototype/ 为准（冲突须升级用户裁决）；数值与行为契约以本 spec Scenario 为准。

## ADDED Requirements

### Requirement: 项目首页分面承载

项目页 SHALL 在「项目首页」分面渲染文件浏览视图（`ProjectHomeTab`），组件形态以 prototype/ 为准：根目录最近提交条（分支 Select 移入条右端——独立工具栏标头于 2026-11-10 第二批增强取消以减面积）→ 面包屑（进入目录后才显示，2026-11-10 第三批增强）→ 文件表格 → README 渲染盒（根目录）或文件内容盒（打开文件时）。

- 分面数据拉取 MUST 遵循按需加载门控：仅在本分面被选中时请求 project-files API，未选中零请求；切离分面时在飞请求结果到达后静默丢弃（不报错弹窗）。
- 文件表格列 MUST 为：名称 / 大小 / 最近提交信息 / 最近提交时间；目录条目先行（同类型按名称不区分大小写升序）；窄屏视口（<768px）MUST 隐藏后三列，仅留名称列。
- 大小列（2026-11-10 第二批增强）：文件条目显示实际字节（后端条目 `bytes` 字段 stat 实值，`formatBytes` 自动 B/KB/MB/GB 档位）；目录条目 MUST NOT 做递归汇总，显示「目录」；读取失败显示「—」；列内容 MUST 靠左对齐（2026-11-11 用户修正——数值列右对齐惯例让位于名称列视觉连续性）。
- 隐藏文件显示（2026-11-11 第四批增强）：list 通道 MUST 一并返回忽略项（`git ls-files --others --ignored --exclude-standard --directory` 通道，纯 TTL 30s 缓存；全忽略目录折叠为 `dir/` 尾斜杠形态、`.git` 永不出现；子目录导航时以不带 `--directory` 的 scoped 重扫补齐直接子项），条目携带 `hidden: true`；前端 MUST 以灰色显（`DSH_TEXT_TERTIARY`）渲染名称文案与图标（`ProjectFileIcon` 增 `muted` prop），大小/提交信息/时间列同步灰化或显「—」；隐藏条目与可见条目同名时可见方优先不标灰（混合目录语义）；纯忽略目录磁盘存在即可导航（404 门以 `is_dir()` 兜底，文件路径必须 404）。
- 目录条目数 MUST 有 200 项上限：超出部分截断，list 响应附 `truncated_count` 字段，前端 MUST 显示截断提示（如「仅展示前 200 项」）。
- 目录与文件的行均 SHALL 可点击（原型第 2 轮批注定稿）：目录行进入子目录，文件行打开内容视图。
- 分支 Select SHALL 仅渲染当前分支单选项（detached HEAD 显示短 hash）于最近提交条右侧，MUST NOT 提供切换（本期边界，原型中分支/标签为假数据演示）；最近提交条不渲染的视图（子目录/文件视图）分支名不展示。
- 表格行图标（2026-11-10 第三批增强）：目录与文件图标统一蓝色系（antd blue-6 `#1677ff`，常量 `ICON_BLUE` 单源在图标组件）；文件图标三级映射——常用扩展名/知名文件名 → simple-icons 品牌图标（具名导入按需打包：ts/js/py/vue/rs/go/html/css/json/yaml/sh/docker/package.json/.gitignore 等 ~30 项，按品牌色渲染），其余可识别扩展名 → @ant-design/icons 文件型图标（md/pdf/zip/图片/音视频/sql 等，蓝色），未知类型 → FileOutlined 兜底（蓝色）；禁止全量导入 simple-icons 进首屏 chunk。

#### Scenario: 首次进入项目首页

- **WHEN** 用户点击「项目首页」页签
- **THEN** 渲染根目录文件列表（目录先行）+ 根目录 README 渲染盒 + 最近提交条，且布局与组件选型以 spec/changes/add-project-home-tab/prototype/ 为 UI 真相源

#### Scenario: 按需加载门控

- **WHEN** 用户停在「功能开发」分面刷新项目页
- **THEN** MUST NOT 发出任何 project-files API 请求；点击「项目首页」后才发出首次列表请求

#### Scenario: 窄屏隐藏提交列

- **WHEN** 视口宽度 <768px 打开项目首页
- **THEN** 文件表格仅渲染名称列（大小/最近提交信息/时间三列不渲染）

### Requirement: 目录导航与面包屑

文件树 SHALL 支持任意深度子目录导航：点击目录行进入该目录，面包屑（根节点显示为项目名）逐级回退，点击根节点回根目录。

- 导航切换 MUST 原地更新列表与面包屑，MUST NOT 整页刷新或改变路由路径 `/projects/:name`。
- 面包屑层级 MUST 与当前目录一一对应（如 `fenixd / core / dashboard`）；文件视图打开时面包屑末段为该文件名（如 `fenixd / core / scheduler.py`），点击文件名前任意层级回退到对应目录。
- 面包屑条（2026-11-10 第三批增强）MUST 仅在进入目录后渲染（当前目录非根时显示整条，含边框与内边距）；根目录（无论是否打开文件）整条隐藏，减面积且根视图提交条即天然首行。

#### Scenario: 进入子目录并返回

- **WHEN** 用户在根目录点击目录 `core`，再点击面包屑中的 `fenixd`（根）
- **THEN** 列表先切换为 `core/` 内容（面包屑 `fenixd / core`），再回根目录（面包屑仅 `fenixd`），全程无整页刷新

### Requirement: 文件内容查看与下载

点击文件行 SHALL 在列表下方展开内容盒（替代 README 盒的位置；仅根目录且未打开文件时渲染 README 盒），内容盒形态以 prototype/ 为准：头部（文件图标 + 文件名 + 类型徽标 + 行数/字节（tabular-nums）+ 「下载」按钮）+ 正文区。正文按文件类型四路渲染（2026-11-10 增强，详见「内容盒四路渲染」Requirement）。

- 后端 `GET /api/project-files/content` 对文本文件返回 `{content, lines, bytes, truncated}`；文本大小上限 256 KiB，超出部分截断并置 `truncated=true`，前端 MUST 显示「文件过大，仅展示前 256 KB，下载查看全文」提示。
- 非图片二进制文件（前 8 KiB 含 NUL 字节判定）MUST NOT 返回文本内容（`binary=true`），前端内容区显示「二进制文件，暂不支持预览」+ 下载按钮。
- `GET /api/project-files/download` SHALL 以 `Content-Disposition: attachment` 下发文件，文件名取 basename；下载 MUST 对任意文件（含二进制）可用。
- `GET /api/project-files/raw` SHALL 仅对图片扩展白名单（``IMAGE_INLINE_TYPES``：png/jpg/jpeg/gif/webp/bmp/ico/avif/svg）以内联语义（无 attachment 头）下发字节，Content-Type 按扩展名精确下发并附 `X-Content-Type-Options: nosniff`；svg SHALL 追加 `Content-Security-Policy: sandbox`（SVG 可内嵌脚本，直开场景一律禁脚本）；非图片扩展 400、目录 400、缺失 404、越界 400。
- 图片文件 MUST NOT 经 content 文本通道取数（前端以 `<img>` 指向 raw 通道直显完整字节，不经 256 KiB 截断语义）。
- 打开文件时根目录 README 盒 MUST 隐藏；返回目录（面包屑）后 README 盒恢复。

#### Scenario: 查看并下载文本文件

- **WHEN** 用户点击根目录文件 `README.md`
- **THEN** 内容盒展开并经 markdown 安全管线渲染全文（标题/列表/表格等 GFM 元素生效）与「N 行 · x KB」，URL 变为含 `tab=home&path=README.md` 的查询串，点击「下载」触发浏览器下载且保存文件名为 `README.md`

#### Scenario: 非图片二进制文件降级

- **WHEN** 用户点击一个非图片的二进制文件（如 `.zip`）
- **THEN** 内容盒显示「二进制文件，暂不支持预览」，下载按钮可用且点击后正常下载

#### Scenario: 图片直显

- **WHEN** 用户点击 `.png`/`.jpg`/`.svg` 等图片文件
- **THEN** 内容盒以 `<img>` 经 `/api/project-files/raw` 直显图片（不经文本通道、无截断），头部徽标显示「图片」，下载按钮可用；加载失败时显示「图片加载失败，可下载后查看」降级提示

#### Scenario: 大文件截断

- **WHEN** 用户点击一个 1 MB 的文本文件
- **THEN** 内容盒仅渲染前 256 KB 文本并显示截断提示，下载按钮可获取完整文件

### Requirement: 内容盒四路渲染（2026-11-10 增强）

内容盒正文 SHALL 按文件类型四路渲染：`*.md`/`*.markdown` → markdown 安全管线；图片扩展 → raw 通道 `<img>` 直显；代码文件（映射命中的扩展名/构建文件名）→ 语法高亮 + 行号；其余（非代码、非图片、非 markdown）→ 纯文本等宽 pre 展示。

- markdown 渲染 MUST 复用 react-markdown + `markdownComponents` 安全渲染族（与 README 同源单组件 `MarkdownBody`），MUST NOT 引入新的 markdown 渲染路径，MUST NOT 放行 raw HTML。
- 代码高亮 MUST 使用 `react-syntax-highlighter` 的 PrismLight 轻量构建 + 显式注册常用语言集（bash/batch/c/cmake/cpp/csharp/css/dart/diff/docker/go/graphql/ini/java/javascript/json/jsx/kotlin/less/lua/makefile/markup/nginx/perl/php/powershell/protobuf/python/r/ruby/rust/sass/scss/sql/swift/toml/tsx/typescript/yaml），SHALL 显示行号、使用 oneLight 主题（与 claude-msg 视觉基线同源）；MUST NOT 引入全量 Prism 或新依赖进首屏 chunk（语言映射 ⊆ 注册集 ⊆ 实际模块文件，由 node 测试钉住）。
- 文件类型分类与语言映射 MUST 为 `projectHomeShared.ts` 零依赖纯函数（`fileKind`/`prismLanguageFor`，node --test 直测）；前端 `IMAGE_EXTENSIONS` 与后端 `IMAGE_INLINE_TYPES` MUST 保持镜像一致（测试钉）。
- 特定命名映射：`.vue` 映射 markup（无独立 Prism 语法）；`Makefile`/`Dockerfile`/`CMakeLists.txt` 按文件名映射；点文件（`.env`）剥前导点参与映射；无映射扩展名归纯文本。

#### Scenario: markdown 文件渲染

- **WHEN** 用户点击 `docs/guide.md`
- **THEN** 内容盒经与 README 相同的安全管线渲染 GFM 全文（SafeLink 白名单生效），头部徽标显示「Markdown」

#### Scenario: 代码文件高亮与行号

- **WHEN** 用户点击 `src/app.py`（或其他映射命中的代码文件）
- **THEN** 内容盒以语法高亮 + 行号渲染源码（oneLight 主题），头部徽标显示「代码」；未注册语言的安全回退为纯文本渲染（不崩溃）

#### Scenario: 纯文本兜底

- **WHEN** 用户点击 `LICENSE` 或其他非代码、非图片、非 markdown 文件
- **THEN** 内容盒以等宽字体纯文本展示（原形态），头部徽标显示「文本」

### Requirement: Bento 磁贴帧一致性（2026-11-10 增强）

文件列表卡、文件内容卡、README 卡 SHALL 统一采用 dashboard-frontend 域 Bento 磁贴帧条款形态（与其他页签卡片风格一致）：发丝边 `#eef2f7` + `12px` 圆角 + 软阴影 `0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)` + 纯白底（沿用 SpecTimeline `OV_TILE` 局部常量先例，不新设共享常量）。

#### Scenario: 三卡帧形态一致

- **WHEN** 用户进入项目首页任意视图（根目录 / 子目录 / 打开文件）
- **THEN** 可见卡片均呈现同一帧形态（同边框色/圆角/阴影/白底），内容盒与 README 盒切换时帧形态不变

### Requirement: README 渲染

项目根存在 `README.md`（缺省回退 `readme.md`）时，根目录视图 SHALL 在文件列表下方以 GFM 渲染 README 全文；两者均不存在时不渲染 README 盒（列表仍展示）。

- 渲染管线 MUST 复用既有 react-markdown + `markdownComponents` 安全渲染族（与 SpecDocModal 同源），链接经 SafeLink 协议白名单过滤，MUST NOT 引入新的 markdown 渲染路径。
- README 内容 MUST 来自 project-files API 文本通道（受同一 256 KiB 截断与越界防护约束；超限 README 截断展示并提示）。

#### Scenario: 根目录 README 展示

- **WHEN** 项目根存在 README.md 且用户位于项目首页根目录
- **THEN** 列表下方渲染 README 全文（标题/列表/表格等 GFM 元素生效），打开任意文件时该盒隐藏、返回后恢复

#### Scenario: 无 README 项目

- **WHEN** 项目根不存在 README.md 与 readme.md
- **THEN** 项目首页仅渲染文件列表，MUST NOT 渲染空 README 盒

### Requirement: git 属性展示

文件表格与最近提交条 SHALL 展示 git 最近提交属性：表格每行（含目录行）显示该路径最近一次提交的信息摘要与时间；根目录视图顶部显示整仓最近一次提交（作者 / 短 hash / 相对时间）。

- 列表边界 MUST 为「git 可见文件集合 + 忽略项通道」（2026-11-11 第四批增强改定）：tracked/未忽略未跟踪条目常态显示；gitignored 路径以 `hidden: true` 条目一并显示（灰色显），`.git` 目录永不列出；同名冲突可见方优先。
- 时间展示：相对时间（如「2 小时前」），数值部分 tabular-nums；提交信息单行溢出省略。
- 目录条目的提交属性 MUST 取该目录路径下最近一次提交（`git log -1 -- <dir>` 语义）。

#### Scenario: gitignored 灰显可导航（2026-11-11 改定）

- **WHEN** 项目工作树存在 gitignored 的 `node_modules/` 与 `.fenix/` 目录
- **THEN** 列表中 MUST 出现这两个目录条目且呈灰色显（名称文案与图标 `DSH_TEXT_TERTIARY`），点击可进入（子目录内容同样以 hidden 条目呈现）；磁盘不存在的纯路径（如从未构建的 `dist`）仍 404

#### Scenario: 混合目录可见优先

- **WHEN** 目录 `.claude/` 内同时含 tracked 文件（目录本身不在忽略清单）
- **THEN** `.claude` 条目按可见目录渲染（蓝色图标 + 主色文案），MUST NOT 误标灰

#### Scenario: 根目录最近提交条

- **WHEN** 用户位于项目首页根目录
- **THEN** 渲染最近提交条（作者名 + 短 hash + 相对时间 + 右端分支 Select），形态以 prototype/ 为准；打开文件时不渲染

### Requirement: URL path 持久化

项目首页分面的浏览位置 SHALL 持久化到 URL 查询参数 `path`（仅当 `tab=home` 时承载）：进入子目录或打开文件写入 `path=<相对路径>`（URL 编码），回根目录移除 `path`；写入采用 replace 语义（MUST NOT 新增浏览器历史条目）。

- 带参直达：`/projects/<name>?tab=home&path=core/dashboard` SHALL 直接渲染该目录视图；`path` 指向文件时直接打开内容视图。
- `tab` 缺省（功能开发）不写参的既有语义 MUST NOT 改变；`path` 在 `tab≠home` 时 MUST NOT 出现。

#### Scenario: 带参直达文件视图

- **WHEN** 用户打开 `/projects/fenixd?tab=home&path=core%2Fscheduler.py`
- **THEN** 页面停在「项目首页」分面、面包屑 `fenixd / core / scheduler.py`、内容盒渲染该文件文本

#### Scenario: 回根清参

- **WHEN** 用户从 `?tab=home&path=core` 点击面包屑回根目录
- **THEN** URL 中 `path` 参数 MUST 被移除（`tab=home` 保留），README 盒恢复渲染

### Requirement: 路径越界防护与项目校验

project-files 三端点（list / content / download）SHALL 实施路径安全防护，作为后端硬约束：

- `project` 参数 MUST 解析为 registry 内存在（exists）的项目，未知/缺失项目返回 404/400（对齐 `_project_query_or_error` 既有口径）。
- `path` 参数 MUST 解析（含 URL 解码）后 containment 校验：解析出的绝对路径 MUST 仍位于该项目根内（resolve + is_relative_to），越界（`..`、绝对路径、符号链接逃逸）返回 400，MUST NOT 泄露项目根外任何文件内容。
- `path` 指向不存在的文件/目录返回 404；对 git 可见集合之外的路径（gitignored），list 不展示、content/download 仍按磁盘实况校验 containment 后服务（与 GitHub「工作树实况」语义一致）。
- `path` 解析后指向已存在的目录时，content / download 端点 MUST 返回 400（目录不经内容/下载通道服务；list 通道正常服务目录）。
- 端点 MUST NOT 读取或列出 `.git` 目录内容（README 盒、列表、内容、下载全链路排除）。

#### Scenario: 越界路径拒绝

- **WHEN** 请求 `GET /api/project-files/content?project=fenixd&path=../../../etc/passwd`
- **THEN** 服务端返回 400 错误，响应体不含任何项目根外文件内容

#### Scenario: 未知项目 404

- **WHEN** 请求 `GET /api/project-files/list?project=<不存在项目名>`
- **THEN** 服务端返回 404「project not found」

### Requirement: 非 git 项目空态

非 git 仓库的注册项目（git 命令不可用或无提交历史）打开项目首页 SHALL 展示空态视图：Empty 组件 + 中文说明（「该项目不是 git 仓库或暂无提交历史」），MUST NOT 报错弹窗、MUST NOT 渲染破损列表。

#### Scenario: 非 git 项目空态

- **WHEN** 用户对非 git 项目打开「项目首页」分面
- **THEN** 渲染 Empty 空态 + 说明文案，console 无新增错误
