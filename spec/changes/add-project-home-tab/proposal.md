# Proposal: add-project-home-tab

## Why

Dashboard 项目详情页（SPEC 列表页，`/projects/:name`）现有五页签（功能开发 / 代码审查 / 测试回归 / 架构蓝图 / 项目知识）全部面向「开发过程」，没有一处能让用户直接看懂**项目本身**：文件结构长什么样、README 说了什么、每个文件最近被谁改过。用户要看这些必须离开 dashboard 去文件系统或仓库托管平台。参照 GitHub 项目页（github.com/fenixsoft/dmla）的成熟形态，在页签**首位**增加一个「项目首页」页签承载文件浏览 + README 渲染，以低成本补上这个空白。经原型确认环（fenix-prototype，vendor 层真组件原型两轮批注迭代）用户已明示认可定稿。

**硬性要求**：新页签虽然占据 tab 菜单**第一位**，进入页面时**默认选中的仍是「功能开发」页签**（退居第二位）——既有主工作流零改变。

## What Changes

- **新增「项目首页」页签**（key `home`），位于项目页 Tabs **首位**；默认选中仍为「功能开发」（`dev`），缺省 URL 不写 `tab` 参数的既有语义不变。
- **文件树浏览**：根目录与任意子目录的文件/目录列表（antd Table：名称 / 最近提交信息 / 最近提交时间，目录先行排序，窄屏 <768px 隐藏后两列）；列表边界为 git 可见文件（`git ls-files --cached --others --exclude-standard`），gitignored 路径（node_modules / dist / .fenix / .git 等）不出现。
- **目录导航**：目录行点击进入子目录，面包屑（根=fenixd 项目名）逐级返回；URL `path` 参数持久化（replace 语义），带参链接直达任意目录/文件视图。
- **文件内容查看**：文本文件点击后，在列表下方内容盒展示源码文本（头部含文件名 / 行数 / 字节数 / 下载按钮）；二进制文件不渲染文本、仅提供下载；超大文本（>256 KiB）截断展示并提示下载全文。
- **文件下载**：内容盒「下载」按钮经 `GET /api/project-files/download` 触发浏览器下载（Content-Disposition attachment，文件名取 basename）。
- **README 渲染**：项目根存在 README.md（或 readme.md）时在根目录文件列表下方以 GFM 安全渲染展示（复用 spec-doc-view 同族 react-markdown + markdown-shared 管线）；无 README 不渲染该盒。
- **根目录最近提交条**：展示整仓最近一次提交（作者 / 短 hash / 相对时间）。
- **后端新增 project-files API**：目录列表 / 文件内容 / 文件下载三端点（路径越界防护、二进制判定、大小截断、git 属性批量单飞）。
- **分支只读**：工具栏分支 Select 仅显示当前分支单选项（本期不支持分支/标签切换——原型中为假数据演示，立项时与用户确认过子目录导航与提交列需求，未含分支切换）。
- **按需加载门控**：项目首页分面仅在自身被选中时拉取 project-files API（对齐 QualityTab/RegressionTab/ArchitectureTab/KnowledgeTab 既有语义），未选中零请求。
- **帮助文档**：`docs/help/08-dashboard.md` 补「项目首页」页签章节。

## Capabilities

### New Capabilities

- `project-home-tab`: 项目首页页签的完整能力——文件树浏览（git 可见边界、目录导航、面包屑、提交信息列）、文件内容查看（文本渲染 / 二进制降级 / 大文件截断）、文件下载、README GFM 渲染、根目录最近提交条、URL `path` 持久化、按需加载门控、路径越界防护、后端 project-files API 契约。

### Modified Capabilities

- `project-page-tabs`: 分面组成由五分面扩为六分面（「项目首页」居首位）、URL `tab` 合法值域增加 `home`；默认选中「功能开发」、replace 写回语义、缺省不写参、原地切换、按需加载门控等其余条款不变。

## Impact

- **后端**：`core/dashboard/routes/project_files_routes.py`（新增，3 端点）、`core/dashboard/data/project_files.py`（新增，列表/内容/下载/git 属性数据模块）、`core/dashboard/routes/base.py`（GET 路由表接线）、`core/dashboard/server.py`（mixin 接线）。
- **前端**：`core/dashboard/static/src/pages/projects/components/ProjectHomeTab.tsx`（新增）、`core/dashboard/static/src/pages/projects/list.tsx`（页签首位插入 + tab 值域扩展）、`core/dashboard/static/src/services/dashboard.ts`（API 函数）。
- **文档**：`docs/help/08-dashboard.md` 补章节。
- **界面真相源**：`spec/changes/add-project-home-tab/prototype/`（vendor 层真组件原型，具约束力；screenshots/ 含渲染凭证）。
- **不新增配置项**；不改状态机、不动调度链路；各注册项目一视同仁（非 git 目录的项目该页签展示空态 + 说明）。
