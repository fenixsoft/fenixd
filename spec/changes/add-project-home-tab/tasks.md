## Deliverables

```yaml
- path: core/dashboard/data/project_files.py
  kind: new
- path: core/dashboard/routes/project_files_routes.py
  kind: new
- path: core/dashboard/routes/base.py
  kind: modify
- path: core/dashboard/server.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/components/ProjectHomeTab.tsx
  kind: new
- path: core/dashboard/static/src/pages/projects/list.tsx
  kind: modify
- path: core/dashboard/static/src/services/dashboard.ts
  kind: modify
- path: core/dashboard/static/tests/projectHomeTab.test.mjs
  kind: new
- path: tests/test_dashboard_project_files_api.py
  kind: new
- path: docs/help/08-dashboard.md
  kind: modify
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 后端数据模块（core/dashboard/data/project_files.py）

- [x] 1.1 core/dashboard/data/project_files.py 建模块：文件集合单源——`git ls-files --cached --others --exclude-standard`（cwd=项目根）全集 + `.git/index` mtime 进程内缓存（30s TTL + mtime 变化失效）；集合上前缀分组构建任意子目录条目列表（目录条目 = 集合内存在该前缀下文件的去重目录名），目录先行、名称不分大小写升序排序；非 git 项目（命令失败/空输出且非空仓歧义时以 `git rev-parse --is-inside-work-tree` 复核）返回 non_git 标记
- [x] 1.2 路径安全：`resolve_relative(root, relpath)` 助手——URL 解码 → `Path(root, relpath).resolve()` → `is_relative_to(root.resolve())` containment 校验，越界/绝对路径/`..` 抛 `PathEscape`；`.git` 内路径显式拒绝；list 通道仅服务集合内路径（404 语义）
- [x] 1.3 git 属性：每条目单飞 `git log -1 --format=%h%x1f%s%x1f%aI -- <entry>`（目录条目传目录路径），解析为 {hash, message, time}；目录条目数上限 200（超出附 truncated_count）；整仓最近提交 `%an%x1f%h%x1f%aI`（仅根目录查询）；分支名 `git rev-parse --abbrev-ref HEAD`（detached 回退短 hash）
- [x] 1.4 内容通道：文本读至 256 KiB 截断（truncated 标记 + 行数/字节数）；二进制判定（前 8 KiB 含 NUL → binary=true 不带 content）；README 判定链 README.md → readme.md（仅根目录查询返回 readme 字段）

## 2. 后端路由接线

- [x] 2.1 `core/dashboard/routes/project_files_routes.py` 薄 handler mixin：`GET /api/project-files/list|content|download` 三端点——list/content 走 `_json`，download 自写响应（流式 64 KiB 分块 + Content-Length 实值 + `Content-Disposition: attachment; filename*=UTF-8''<basename>` RFC 5987 编码）；项目解析/400/404 口径对齐 `_project_query_or_error`；错误响应体不含内部路径细节（对齐 `_api_project_describe` 泛化文案纪律）；ETag 签名函数返回 None（不参与 304 协商）
- [x] 2.2 `core/dashboard/routes/base.py` GET 路由表接线三条（kind=exact，置于既有精确路由区段）；`core/dashboard/server.py` mixin 挂载；README 盒全链路（list/content/download）不触 `.git`

## 3. 前端页签接线与 API 函数

- [x] 3.1 `services/dashboard.ts` 新增 `fetchProjectFileList / fetchProjectFileContent / fetchProjectFileDownloadUrl` 三函数（对齐既有 API 函数形态与错误处理惯例）
- [x] 3.2 `list.tsx`：`ListTab` 类型与 `parseListFilters` tab 值域扩为六值（home/dev/quality/regression/architecture/knowledge）；items 数组**首位**插入 `{key:'home', label:'项目首页', children:<ProjectHomeTab project active={activeTab==='home'} />}`；缺省解析（无 tab 参数 → dev）零改动；`path` 参数随 tab=home 写入/移除（replace 语义并入既有写回块，根目录不写参，tab≠home 不出现）
- [x] 3.3 功能开发分面零回归自证：items 插入为纯结构变更，桌面表格列/整行点击/树形/菜单/过滤条现状 diff 自证（源码扫描 + 构建后浏览器断言）

## 4. ProjectHomeTab 组件（UI 真相源对照）

- [x] 4.1 ProjectHomeTab.tsx 布局对照：实现前必读 `spec/changes/add-project-home-tab/prototype/index.html` 定稿原型，逐区块对照实现（工具栏/最近提交条/面包屑/文件表格/README 盒/文件内容盒/空态），布局与组件选型以 prototype/ 为 UI 真相源；颜色经 theme token 引用（禁散落硬编码色值）、字号落 11/12/13/14 阶、时间数值 tabular-nums、零动效
- [x] 4.2 active 门控：仅选中本分面发首次列表请求；同 path 结果进程内缓存（组件卸载即弃），回分面不重复请求；切离后在飞结果静默丢弃
- [x] 4.3 文件表格：名称/最近提交信息/最近提交时间三列（目录先行、单行省略、无提交显示「—」），行点击（目录进入/文件打开），窄屏 <768px（isMobile）仅名称列；超 200 项显示截断提示条
- [x] 4.4 导航与面包屑：目录行进入、面包屑逐级回退（根=项目名）、文件视图面包屑末段为文件名；initialPath 从 URL 恢复直达目录/文件视图
- [x] 4.5 文件内容盒：头部（图标+文件名+行数/字节 tabular-nums+下载按钮）+ pre 等宽源码区；truncated 显示「文件过大，仅展示前 256 KB，下载查看全文」；binary 显示「二进制文件，暂不支持预览」+下载可用；打开文件隐藏 README 盒、回目录恢复
- [x] 4.6 README 盒：根目录按 readme 字段渲染（react-markdown + remarkGfm + markdownComponents 复用，MUST NOT 新写管线）；无 README 不渲染空盒；256 KiB 截断同款提示
- [x] 4.7 工具栏（分支 Select 单值只读 + 当前分支名，detached 显示短 hash）与根目录最近提交条（作者/短 hash/相对时间，打开文件时不渲染）；非 git 项目 Empty 空态 +「该项目不是 git 仓库或暂无提交历史」，无报错弹窗

## 5. 测试与构建验证

- [x] 5.1 `tests/test_dashboard_project_files_api.py`（pytest，对齐 test_dashboard_architecture_api.py 习语，tmp_path+monkeypatch 造 git 仓夹具）：containment 越界 400（含 `..`/绝对路径/`.git` 深防）、未知项目 404、缺参 400、目录列表目录先行排序与 gitignored 排除、条目提交属性解析、README 判定链、256 KiB 截断、二进制 binary 标记、download attachment 头与字节回读、非 git 项目 non_git 标记、目录路径 content/download 400、超 200 项截断 truncated_count
- [x] 5.2 `core/dashboard/static/tests/projectHomeTab.test.mjs`（零依赖 node:test，同 qualityGates.test.mjs 习语）：纯逻辑直测（相对时间六档格式化、条目排序、面包屑层级构建）+ 源码扫描钉接线（list.tsx items 首位 home + 缺省 dev 不变 + active 门控表达式 + path 写回 replace + 窄屏列分流 + markdown 管线复用点 + ProjectHomeTab 渲染锚）
- [x] 5.3 `npm run build`（core/dashboard/static）成功出 dist；worktree 实例浏览器冒烟：默认进页签功能开发选中且 URL 无 tab 参、项目首页居首；home 分面目录导航/面包屑回退/文件打开/下载触发/README 渲染/URL path 直达复现；console 无新增错误；截图存 `.history/`（禁读仅存档），与 prototype/ 逐区块对照记录
- [x] 5.4 全量回归：pytest 既有套件 + `node --test tests/*.test.mjs`（core/dashboard/static）全绿（bin/run_full_suite.py --timeout 3600 --baseline e93f00fd0（fork 点）--json：失败 2 项 test_current_tests_have_zero_violations / test_no_bare_getlogger_in_core 经入口归类为存量（baseline 同败、主树 2026-11-09 回归产物同败），verdict=None 零引入；node --test 410/410 绿；期间修复 bin/fenixd_supervisor.py 导入期误消费宿主 pytest argv 致套件 exit 3 秒败的缺陷）
