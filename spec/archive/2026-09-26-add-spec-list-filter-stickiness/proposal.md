# Why

项目页 SPEC 开发列表（路由 `/projects/:name`，`pages/projects/list.tsx`）的 4 个过滤条件——搜索关键词、状态多选、类型（全部/进行中/已完成）、归档切换——以及页签选中态（开发/质量/回归/会话）全部是组件内存 `useState`。用户按状态筛出关注集后点进某个 SPEC 看详情，返回列表时组件已卸载重建，**过滤条件与页签全部归零**，必须重新设置一遍——这是日常高频路径上的重复操作，打断心流。

过滤条件持久化到 **URL 查询参数** 是列表页的标准做法：浏览器返回/刷新天然带回参数，链接分享/收藏也能原样重现视图。项目页前端栈（`@umijs/max` v4）原生提供 `useSearchParams`，改动面可收敛在单文件内。

本变更同时推翻 `add-project-detail-tabs` 当时声明的非目标「Tab 选中态不持久化到 URL」（proposal.md 第 15 行）——页签与过滤条件同属「回到列表不想重来」的易失状态，一并持久化。

# What Changes

- `list.tsx` 的 5 项易失状态与 URL 查询参数**双向同步**：
  - **读侧**：组件挂载时从 URL 读参初始化（`useState` 惰性初始化，一次性）；
  - **写侧**：状态变更时写回 URL，采用 **replace 语义**（不新增历史条目，敲搜索字符不产生历史污染）。
- 参数白名单与缺省约定（缺省值一律**不写参数**，保持 URL 干净）：

  | 参数 | 承载 | 合法值 | 缺省（不写参） |
  |------|------|--------|----------------|
  | `tab` | 页签 | `dev` \| `quality` \| `regression` \| `session` | `dev` |
  | `q` | 搜索关键词 | URL 编码自由文本 | 空 |
  | `status` | 状态多选 | 合法状态枚举逗号分隔（11 个） | 空（全部状态） |
  | `type` | 类型过滤 | `active` \| `completed` | 空（全部） |
  | `archived` | 归档切换 | `1` | 未归档 |

- **fail-safe 白名单解析**：URL 可被手工改坏——非法 `tab`/`type` 回退默认，`status` 中非法枚举丢弃（全非法视为无参），不崩溃、不产生 console error；解析即消毒，写回 effect 会把脏参数清洗为干净形态。
- 搜索词按**防抖节拍**写入 URL：输入框即时值仍走本地 state（300ms 防抖过滤逻辑不变），防抖到期后的 `debouncedQ` 才落 URL；恢复时 URL 的 `q` 同时灌入输入框与 `debouncedQ`（不闪全量列表）。
- 页签恢复时既有**按需加载门控**自然生效：`QualityTab` / `RegressionTab` / `SessionPanel` 的 `active` prop 语义不变——URL 带 `tab=session` 打开只触发该分面的会话状态拉取，仍不隐式启动会话进程。
- 无参数打开 URL = 现状默认行为，**零回归**（现有用户书签不受影响）。

# Capabilities

## New Capabilities

- `spec-list-filter-stickiness`: SPEC 开发列表过滤条件与页签选中态的 URL 粘滞——参数白名单与缺省约定、读侧恢复（返回/刷新/带参直达）、写侧 replace 同步、非法参数 fail-safe、页签恢复与按需加载门控的相容。

## Modified Capabilities

- `project-page-tabs`: 页签选中态由「仅保存在组件内存中，MUST NOT 持久化到 URL」改为「持久化到 URL 查询参数 `tab`」；原「刷新回到默认分面」场景相应改写为「刷新保持当前分面」。分面组成、切换交互、按需加载门控等其余条款不变。

# Impact

- **前端（本项目交付物）**：
  - `core/dashboard/static/src/pages/projects/list.tsx`：引入 `useSearchParams`（`@umijs/max` 已导出），新增参数解析与写回同步逻辑；过滤条 UI 与过滤口径零改动。
- **前端（非交付物）**：`core/dashboard/static/dist/`（构建产物，gitignored）由框架合并后重建，声明 `reference` 锚点；交付需保证 `npm run build` 通过。
- **后端 / API / 数据结构**：无变更。路由、`/api/specs`、SSE 契约均不动。
- **非目标**：
  - 表格分页页码不持久化（返回后回到第 1 页是可接受现状）；
  - 树形展开状态（`expandedKeys`）不持久化；
  - 不引入 localStorage（URL 已覆盖返回/刷新/分享三类场景）;
  - 不改过滤逻辑口径、防抖时长、页签按需加载语义等任何既有行为。
