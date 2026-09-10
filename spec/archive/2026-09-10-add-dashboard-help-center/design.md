# Design: add-dashboard-help-center

## Context

Dashboard（Ant Design Pro + umi，hash 路由，dist 入库）现有四页：概览/项目/设置/运维（`app.tsx` 菜单数组 + `config/routes.ts` 路由双处定义）。后端为 `core/dashboard/server.py`（标准库 ThreadingHTTPServer），数据读侧集中在 `core/dashboard/data.py`，前端已有 react-markdown@10 + remark-gfm 渲染链（`SpecDocModal.tsx` 导出的 `markdownComponents`、`components/claude-msg/Markdown.tsx` 富文本版）。框架仓库单副本、项目经 `.fenix` 软链引用；`docs/` 目录为空，正为此文档集预留。

## Goals

- 11 篇以代码为准的中文帮助文档落 `docs/help/`，图表全部 mermaid。
- Dashboard「运维」下新增「帮助」菜单与帮助中心页（目录 + 正文 + mermaid 渲染 + 移动端）。
- 后端动态读取文档：改文档免前端重建。

## Non-Goals

- 不做文档鉴权/在线编辑（Dashboard 本身无鉴权、仅绑 127.0.0.1，帮助文档为纯静态内容）。
- 不动 README.md（其过时点在文档中以代码事实澄清，README 重写另行立项）。
- 不做全文搜索（文档量 11 篇，目录导航够用；留待后续）。

## Decisions

### D1 文档服务走后端端点动态读盘，而非打包进前端

**选择**：`server.py` 新增两个 GET 端点（文档清单、单篇正文），从框架仓库 `docs/help/` 实时读盘；前端按需拉取。

**理由**：dist 为入库构建产物，文档走前端打包则每次改文档都要重建 dist、提交产物——与「文档随代码轻量演进」矛盾。后端动态读盘后，编辑 .md 刷新即生效。Dashboard server 本身运行在框架仓库（单副本软链），`Path(__file__)` 向上解析即框架根，`docs/help/` 定位可靠。

**备选**：umi raw-import 打包进 bundle（改文档必须重建 dist）；前端 fetch 仓库原始文件（引入外部依赖，不成立）。均弃。

### D2 文档定位与安全

框架根解析：复用 dashboard 后端既有路径推导（`core/dashboard/` 上两级 = 框架根），拼 `docs/help/`。安全约束沿用 server 既有防穿越风格：文档名限定 `[A-Za-z0-9._-]+\.md` 且解析后 real path 必须落在 `docs/help/` 之内；清单端点列出目录内全部合法 .md。`docs/help/` 缺失/为空时清单返回空列表（前端空态），读取失败返回 404（前端正文区错误提示）。

### D3 mermaid 渲染：动态 import 按需加载

**选择**：帮助页维护本地 Markdown 渲染（react-markdown + remark-gfm + 复用 `markdownComponents`），对 `code` 组件拦截 `language-mermaid` 块，用 `React.lazy`/动态 `import('mermaid')` 渲染为 SVG；渲染异常回退显示原始代码文本。

**理由**：mermaid 体积大（MB 级），静态引入会显著放大 dist 与首屏；帮助页是低频入口，按需加载代价最小。`claude-msg/Markdown.tsx` 富文本版不含 mermaid 且带 KaTeX 等重依赖，不合适；轻量版 + mermaid 拦截是最小增量。

**备选**：服务端预渲染 SVG（需引入 mermaid CLI，构建链复杂化）——弃。

### D4 帮助页布局复用既有模式

桌面：左目录（Menu 或简单列表）+ 右正文（Article 排版）；当前文档编码进 URL query（`#/help?doc=<name>`），刷新/直链可还原。移动端：<768px 用 `useIsMobile` 切换为「正文 + 顶部文档切换」堆叠布局（或 Drawer 目录），沿用 v3 各页 `screen-xs` 作用域写法，保证 PC 零回归。文档切换为本地状态 + fetch，不做路由级子页面。

### D5 文档命名与导航契约

文件名即路由参数：`README.md` 为默认文档，正文 `NN-slug.md` 按编号排序；标题从各文档首个一级标题解析（清单端点返回 `[{name, title}]`）。前端目录顺序 = 服务端返回顺序（服务端按文件名字典序，`README` 置顶，`NN-` 编号天然有序）。

## Risks / Trade-offs

- [mermaid 图写错导致渲染失败] → 前端渲染异常回退原始文本（D3）；验证场景覆盖「渲染失败不白屏」。
- [文档内容与代码漂移] → 文档中关键行为均经代码核对；漂移点在配置篇/FAQ 集中列出；后续可考虑每日自省类机制校对（不在本期范围）。
- [mermaid 依赖拉高 dist 体积] → 动态 import 按需 chunk（D3）；构建后核对产物清单。
- [dashboard serve 静态回退规则误伤 /help 直链] → hash 路由下未知路径回退 dist/index.html 已有机制，`/help` 走前端路由不受影响；API 前缀 `/api/` 与文档端点沿用既有分发器风格，无冲突。

## Migration Plan

纯增量：新文件（docs/help/ 11 篇、pages/help/ 组件）+ 三处小改（routes.ts、app.tsx 菜单与面包屑、server.py 分发器注册端点）+ package.json 依赖。上线 = `npm run build` 重建 dist 入库 + 重启 dashboard 进程（改了 server.py）。回滚 = 还原对应提交，无数据迁移。

## Open Questions

无（提纲与模式已由用户确认；文档内容细节由实现按提纲与代码事实执行）。
