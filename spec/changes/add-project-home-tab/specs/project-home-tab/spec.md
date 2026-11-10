# Spec: 项目首页页签（文件与 README 浏览）

项目详情页（SPEC 列表页，路由 `/projects/:name`）新增「项目首页」页签，仿 GitHub 项目页形态：文件树浏览 + README 渲染 + 文件内容查看与下载。本能力由 `add-project-home-tab` 引入。

**界面原型（UI 真相源）：`spec/changes/add-project-home-tab/prototype/index.html`**（vendor 层真组件原型，具约束力；渲染凭证见同目录 `screenshots/`）。凡涉界面布局、组件选型、文案、区块组织的 Scenario 均以 prototype/ 为准（冲突须升级用户裁决）；数值与行为契约以本 spec Scenario 为准。

## ADDED Requirements

### Requirement: 项目首页分面承载

项目页 SHALL 在「项目首页」分面渲染文件浏览视图（`ProjectHomeTab`），组件形态以 prototype/ 为准：工具栏（分支 Select + 只读提示）→ 根目录最近提交条 → 面包屑 → 文件表格 → README 渲染盒（根目录）或文件内容盒（打开文件时）。

- 分面数据拉取 MUST 遵循按需加载门控：仅在本分面被选中时请求 project-files API，未选中零请求；切离分面时在飞请求结果到达后静默丢弃（不报错弹窗）。
- 文件表格列 MUST 为：名称 / 最近提交信息 / 最近提交时间；目录条目先行（同类型按名称不区分大小写升序）；窄屏视口（<768px）MUST 隐藏后两列，仅留名称列。
- 目录条目数 MUST 有 200 项上限：超出部分截断，list 响应附 `truncated_count` 字段，前端 MUST 显示截断提示（如「仅展示前 200 项」）。
- 目录与文件的行均 SHALL 可点击（原型第 2 轮批注定稿）：目录行进入子目录，文件行打开内容视图。
- 分支 Select SHALL 仅渲染当前分支单选项（detached HEAD 显示短 hash），MUST NOT 提供切换（本期边界，原型中分支/标签为假数据演示）。

#### Scenario: 首次进入项目首页

- **WHEN** 用户点击「项目首页」页签
- **THEN** 渲染根目录文件列表（目录先行）+ 根目录 README 渲染盒 + 最近提交条，且布局与组件选型以 spec/changes/add-project-home-tab/prototype/ 为 UI 真相源

#### Scenario: 按需加载门控

- **WHEN** 用户停在「功能开发」分面刷新项目页
- **THEN** MUST NOT 发出任何 project-files API 请求；点击「项目首页」后才发出首次列表请求

#### Scenario: 窄屏隐藏提交列

- **WHEN** 视口宽度 <768px 打开项目首页
- **THEN** 文件表格仅渲染名称列（最近提交信息/时间两列不渲染）

### Requirement: 目录导航与面包屑

文件树 SHALL 支持任意深度子目录导航：点击目录行进入该目录，面包屑（根节点显示为项目名）逐级回退，点击根节点回根目录。

- 导航切换 MUST 原地更新列表与面包屑，MUST NOT 整页刷新或改变路由路径 `/projects/:name`。
- 面包屑层级 MUST 与当前目录一一对应（如 `fenixd / core / dashboard`）；文件视图打开时面包屑末段为该文件名（如 `fenixd / core / scheduler.py`），点击文件名前任意层级回退到对应目录。

#### Scenario: 进入子目录并返回

- **WHEN** 用户在根目录点击目录 `core`，再点击面包屑中的 `fenixd`（根）
- **THEN** 列表先切换为 `core/` 内容（面包屑 `fenixd / core`），再回根目录（面包屑仅 `fenixd`），全程无整页刷新

### Requirement: 文件内容查看与下载

点击文件行 SHALL 在列表下方展开内容盒（替代 README 盒的位置；仅根目录且未打开文件时渲染 README 盒），内容盒形态以 prototype/ 为准：头部（文件图标 + 文件名 + 行数/字节（tabular-nums）+ 「下载」按钮）+ 等宽字体源码区。

- 后端 `GET /api/project-files/content` 对文本文件返回 `{content, lines, bytes, truncated}`；文本大小上限 256 KiB，超出部分截断并置 `truncated=true`，前端 MUST 显示「文件过大，仅展示前 256 KB，下载查看全文」提示。
- 二进制文件（前 8 KiB 含 NUL 字节判定）MUST NOT 返回文本内容（`binary=true`），前端内容区显示「二进制文件，暂不支持预览」+ 下载按钮。
- `GET /api/project-files/download` SHALL 以 `Content-Disposition: attachment` 下发文件，文件名取 basename；下载 MUST 对任意文件（含二进制）可用。
- 打开文件时根目录 README 盒 MUST 隐藏；返回目录（面包屑）后 README 盒恢复。

#### Scenario: 查看并下载文本文件

- **WHEN** 用户点击根目录文件 `README.md`
- **THEN** 内容盒展开显示其源码文本与「N 行 · x KB」，URL 变为含 `tab=home&path=README.md` 的查询串，点击「下载」触发浏览器下载且保存文件名为 `README.md`

#### Scenario: 二进制文件降级

- **WHEN** 用户点击一张 `.png` 图片文件
- **THEN** 内容盒显示「二进制文件，暂不支持预览」，下载按钮可用且点击后正常下载

#### Scenario: 大文件截断

- **WHEN** 用户点击一个 1 MB 的文本文件
- **THEN** 内容盒仅渲染前 256 KB 文本并显示截断提示，下载按钮可获取完整文件

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

- 列表边界 MUST 为 git 可见文件集合（`git ls-files --cached --others --exclude-standard`）：gitignored 路径（node_modules / dist / .fenix / .git 等）MUST NOT 出现在任何层级的列表中；`.git` 目录永不列出。
- 时间展示：相对时间（如「2 小时前」），数值部分 tabular-nums；提交信息单行溢出省略。
- 目录条目的提交属性 MUST 取该目录路径下最近一次提交（`git log -1 -- <dir>` 语义）。

#### Scenario: gitignored 不入列表

- **WHEN** 项目工作树存在 gitignored 的 `node_modules/` 与 `.fenix/` 目录
- **THEN** 项目首页任何层级的列表中 MUST NOT 出现这两个目录条目

#### Scenario: 根目录最近提交条

- **WHEN** 用户位于项目首页根目录
- **THEN** 工具栏下方渲染最近提交条（作者名 + 短 hash + 相对时间），形态以 prototype/ 为准；打开文件时不渲染

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
