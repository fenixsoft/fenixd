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

## 6. 2026-11-10 五点增强批次（用户 request m00001 追加：bento 卡片 / md 渲染 / 代码高亮行号 / 图片直显 / 纯文本兜底）

- [x] 6.1 Bento 磁贴帧：ProjectHomeTab.tsx 三卡（文件列表 / 文件内容 / README）统一 TILE_FRAME 局部常量（发丝边 #eef2f7 + 12px 圆角 + 软阴影 '0 1px 3px rgba(15,23,42,0.05), 0 1px 2px rgba(15,23,42,0.03)' + 纯白底；沿用 SpecTimeline OV_TILE 先例，不新设共享常量），替换原 8px/DASH_BORDER_SECONDARY 卡帧
- [x] 6.2 纯函数：projectHomeShared.ts 增 fileKind（markdown/image/code/text 四分类，大小写不敏感、点文件剥前导点参与映射）与 prismLanguageFor（NAME_TO_LANGUAGE + EXT_TO_LANGUAGE，.vue→markup，无映射 null）；前端 IMAGE_EXTENSIONS 与后端 IMAGE_INLINE_TYPES 镜像（node 测试钉两侧一致）
- [x] 6.3 代码高亮：新组件 ProjectCodeBlock.tsx——react-syntax-highlighter PrismLight 轻量构建（非全量 Prism，不进首屏 chunk）+ 显式注册 38 语言集（bash/batch/c/cmake/cpp/csharp/css/dart/diff/docker/go/graphql/ini/java/javascript/json/jsx/kotlin/less/lua/makefile/markup/nginx/perl/php/powershell/protobuf/python/r/ruby/rust/sass/scss/sql/swift/toml/tsx/typescript/yaml）+ showLineNumbers + oneLight（与 claude-msg 视觉基线同源）；选型上网调研结论：vuepress v1 内置 highlight.js / v2 shiki 均需新依赖，弃
- [x] 6.4 后端 raw 内联通道：project_files.py 增 IMAGE_INLINE_TYPES（9 键 content-type 映射）+ image_content_type；project_files_routes.py 增 `GET /api/project-files/raw`（inline 语义无 attachment、扩展白名单精确 Content-Type、nosniff、svg 追加 CSP: sandbox、流式同 download；目录/存在性先于扩展白名单判定避免目录误报 not an inline image）；base.py 路由行 + 适配函数（server.py 同 mixin 无需改）
- [x] 6.5 内容盒四路渲染：ProjectHomeTab.tsx 头部类型徽标（Markdown/图片/代码/文本）+ 正文分支（md→MarkdownBody 安全管线与 README 同源单组件；image→FileImagePreview raw `<img>` 直显 + 失败降级提示，不经 content 通道无截断；code→ProjectCodeBlock；其余→原等宽 pre 兜底）；非图片二进制降级文案保留；导航动作复位 fileLoading（图片短路 content effect 后在飞文本请求取消回调不触发，不复位会永久 Spin——实现中发现的竞态）
- [x] 6.6 服务函数：dashboard.ts 增 fetchProjectFileRawUrl（withApiBase 前缀化单点，同 download 旁路先例）
- [x] 6.7 测试与 spec 同步：projectHomeTab.test.mjs 增 8 用例（fileKind/prismLanguageFor 直测、语言映射⊆注册集⊆实际模块文件、IMAGE 镜像钉、Bento 帧值、md 管线、图片 raw 直显、代码块 PrismLight+行号、纯文本兜底、raw 服务函数）；test_dashboard_project_files_api.py 增 3 用例（raw png 头与字节回读、非图片/目录/缺失/越界错误形态、svg CSP sandbox）；spec.md 改「二进制文件降级」为非图片二进制 + 增「内容盒四路渲染」「Bento 磁贴帧一致性」Requirement；docs/help/08-dashboard.md 更新项目首页分面章节
- [x] 6.8 构建出 dist + 浏览器冒烟（tsc 已过、构建已过、entry chunk 零 prism、441 node 测试 + 15 pytest 全绿；浏览器实测五视图：bento 帧计算样式命中（边 rgb(238,242,247)/12px/软阴影）、README 与 request.md 经管线渲染（标题/表格/代码块）、projectHomeShared.ts 代码高亮 token + 行号 1-3、logo-64.png raw 直显 naturalWidth 64、.gitignore 纯文本 pre 零 token、LICENSE 不存在路径降级「路径不存在」；console 仅一条预期内 list(path=文件) 404 资源日志——seed 直达解析先探 list 再回退父目录，原 SPEC 既有行为；截图 .history/home-tab-{root-bento,code-highlight,image-preview,markdown-file,plain-text}.png；注意 dashboard daemon 须重启才加载新 raw 路由）

## 7. 2026-11-10 第二批增强（用户 request m00566 追加：去工具栏 / 大小列 / 文件夹蓝标）

- [x] 7.1 工具栏标头取消：ProjectHomeTab.tsx 删 project-home-toolbar 整条（含只读提示文案），分支 Select 移入根目录最近提交条右端（dirData?.branch 门控、仍单值只读无 onChange）；Space/Typography 失效 import 清理
- [x] 7.2 大小列：project_files.py list_directory 文件条目 stat 出 bytes（目录/读取失败 null，不做递归汇总）；dashboard.ts ProjectFileEntry 声明 `bytes: number | null`；表格四列（名称/大小/最近提交信息/时间），大小列窄屏隐藏、右对齐 tabular-nums、目录「目录」/文件 formatBytes/空「—」三态；formatBytes 补 GB 档（projectHomeShared.ts）
- [x] 7.3 文件夹图标蓝色：表格目录行 FolderOutlined 改 FOLDER_BLUE '#1677ff'（antd blue-6，与全站蓝 ramp 同源；文件图标维持次级灰）
- [x] 7.4 测试与 spec 同步：projectHomeTab.test.mjs 增/改用例（四列钉、hidden isMobile 计数 3、大小列三态与 FOLDER_BLUE 钉、工具栏 testid 与提示文案否定钉、Select 位于最近提交条、formatBytes GB 档直测、ProjectFileEntry bytes 接口钉）；test_dashboard_project_files_api.py 增 test_list_entry_bytes_files_only；spec.md 分面承载 Requirement 改四列/Select 位置/大小列/文件夹蓝条款 + 窄屏 Scenario 改三列隐藏；docs/help/08-dashboard.md 同步
- [x] 7.5 构建 + 全量回归 + 浏览器冒烟（443 node + 16 pytest 全绿、tsc 改动文件零错、构建过；实测：toolbar testid 已消失、Select 位于最近提交条内且显示 main、表头四列「名称/大小/最近提交信息/最近提交时间」、文件夹图标计算色 rgb(22,119,255)、README.md 行「22.0 KB」/.gitignore 行「3.1 KB」与磁盘一致、目录行「目录」、console 零错误；截图 .history/home-tab-batch2-toolbar-size-blue.png；运维注：改 list_directory 后端须重启 daemon——旧进程释放 8787 有延迟，kill 后需确认端口已释放再拉起）

## 8. 2026-11-10 第三批增强（用户 request m00735 追加：文件蓝色 + 扩展名图标库 / 面包屑按目录显示）

- [x] 8.1 依赖引入：core/dashboard/static `pnpm add simple-icons`（3470 图标；具名 ESM 导出 tree-shake——构建实测 entry umi chunk 零 registerLanguage/零品牌 hex，图标路径数据与 prism 语言共居共享异步块 3765.*.async.js 128K，仅项目页加载）
- [x] 8.2 ProjectFileIcon.tsx 新组件：三级映射（EXT_TO_SI/NAME_TO_SI → simple-icons 品牌图标按品牌色渲染；EXT_TO_ANTD → antd 文件型图标蓝色；FileOutlined 兜底蓝色）；ICON_BLUE '#1677ff' 单源导出（原 ProjectHomeTab 局部 FOLDER_BLUE 删除，FolderOutlined 改消费 ICON_BLUE）；fileIconKind 纯函数导出；extOf 从 projectHomeShared 导出复用；表格文件行/文件内容盒头部/README 盒头部三处 FileOutlined 次级灰全部替换
- [x] 8.3 面包屑按目录显示：project-home-breadcrumb 整条以 `{dir !== '' && (...)}` 门控——根目录（无论是否打开文件）整条隐藏（含边框内边距），进入目录后才渲染
- [x] 8.4 测试与文档同步：projectHomeTab.test.mjs 增 3 用例（simple-icons 镜像钉——源码引用的 siXxx 必须在安装包真实存在 createRequire 直查、EXT_TO_SI/NAME_TO_SI/EXT_TO_ANTD 两级映射钉、面包屑 dir 门控钉）+ FOLDER_BLUE→ICON_BLUE 钉迁移；node 446/446 全绿；spec.md 行图标条款重写 + 面包屑门控条款 + 视图头部链路描述；docs/help/08-dashboard.md 同步；构建过 + tsc 改动文件零错
- [x] 8.5 浏览器冒烟：根目录面包屑消失、进 core 出现「fenixd / core」、Git 图标 #F03C2E / Python #3776AB / GNU Bash #4EAA25 品牌色渲染、file-markdown/file-text 蓝色 antd 图标、根目录文件视图（.gitignore）面包屑仍隐藏且头部 Git 图标、console 零错误；截图 .history/home-tab-batch3-icons-breadcrumb.png

## 9. 2026-11-11 第四批增强（用户 request m01285 追加：大小列左对齐 / 隐藏文件灰显）

- [x] 9.1 大小列左对齐：ProjectHomeTab.tsx 大小列 render `textAlign: 'left'`（用户修正——右对齐改左对齐）；测试钉 sizeSeg 断言
- [x] 9.2 后端忽略项通道：project_files.py 新增 `ignored_entries`（git ls-files -z --others --ignored --exclude-standard --directory，全忽略目录折叠 `dir/` 尾斜杠、.git 永不出现、失败 None 静默）+ `ignored_children`（前缀过滤直接子项纯函数）+ `ignored_entries_scoped`（子目录导航补扫——不带 --directory 否则 git 恒折叠；纯 TTL 30s 缓存，.gitignore 变化不挪 index mtime 判据无效）；`build_entries` 归并同名可见优先、条目增 `hidden` 字段
- [x] 9.3 路由与前端接线：list 通道 404 门改 `is_known_path or is_dir()`（纯忽略目录可导航，文件路径独立 404）；dashboard.ts `ProjectFileEntry.hidden?: boolean`；ProjectHomeTab 名称文案/图标/大小/提交列 hidden 灰化（DSH_TEXT_TERTIARY）；ProjectFileIcon 增 `muted` prop（ICON_MUTED 单源自 theme）
- [x] 9.4 测试：node 447/447（+4：左对齐钉/muted 钉/hidden 灰显与接口钉/旧钉迁移）；pytest 18/18（+2：test_list_hidden_entries_ignored_channel 三级链、test_build_entries_hidden_dedup；fixture 增 *.log/ignored/sub/deep.txt/stray.log/node_modules/pkg；build_entries 返回 tuple 解包）
- [x] 9.5 冒烟与文档：构建过（batch-4 dist）、dashboard daemon 重启载新后端；实测根目录 .debug/.history/.local/.playwright-cli/.pytest_cache 灰显 rgb(129,133,140)、混合目录 .claude/.fenix/.github 保持主色+蓝、大小列 start 对齐；截图 .history/home-tab-batch4-hidden-size.png；spec.md 大小列左对齐条款 + 隐藏文件显示条款 + gitignored Scenario 改写（灰显可导航 + 混合目录可见优先）
