<!-- knowledge: capability=spec-doc-view rev=3 sources=spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear,spec/archive/2026-09-02-add-spec-doc-buttons,spec/archive/2026-09-08-improve-v3-spec-doc-markdown -->

# SPEC 文档查看

SPEC 文档端点与文档弹窗：proposal/design/tasks 原文读取、三页签懒加载与组件内缓存、Markdown 安全渲染与三态区分。

## 现行规则

- 文档端点：`GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>` 按项目与 SPEC 名称读取 `spec/changes/<spec>/` 目录下的对应文档原文，返回 `{found: boolean, content: string}`；文件缺失返回 `found=false`、content 为空字符串；`doc` 参数仅接受 `proposal`/`design`/`tasks` 三个值，其余值返回 400；`spec` 名称须匹配 kebab-case（`^[a-z0-9][a-z0-9-]*$`），不匹配或该 SPEC 不存在于项目中返回 404，且不读取任何 `spec/changes/` 目录之外的文件；该端点不影响既有 `/api/specs` 及其它端点。
- 文档弹窗：SPEC 列表行内文档入口在当前页弹出模态窗展示该 SPEC 文档，标题包含 SPEC 名称；「文档」弹窗提供需求背景（proposal）/ 详细设计（design）/ 任务清单（tasks）三个页签。
- 懒加载与缓存：页签首次激活时经文档端点懒加载对应文档，不随弹窗打开全量拉取；加载结果按 spec+doc 键缓存在组件内——已看过页签回切不重复请求，弹窗关闭后重新打开已缓存内容立即展示、不重新请求（缓存键带序号防旧请求串扰：旧 `found=false` 结果不得把仍在展示的文档打成「无此文档」）。
- Markdown 安全渲染：文档 content 以 Markdown 渲染为富文本，支持 GFM 常用语法（标题、列表、表格、代码块、任务勾选、链接、行内样式）；链接仅放行 http/https/mailto 协议，其它协议（如 `javascript:`）不渲染为可点击链接。
- 三态并存且不得渲染为空白：文档不存在（`found:false`）→「无此文档」空态（仅影响对应页签）；请求失败 → 错误态并允许重试（切换页签或重开弹窗再次触发加载）；加载中 → 加载态。
- 缺失空态与入口：文档入口在缺失时保持可见可点；点击文档入口仅弹窗展示文档，不触发行级跳转进入详情页，点击行其余区域保持原有跳转行为。
- 关闭交互：弹窗支持通过关闭按钮、点击遮罩与 Esc 键关闭，Esc 关闭不误伤其他弹窗；弹窗打开期间不阻塞列表页状态，关闭后列表页保持原状。

## 溯源

- 史前复原 — 背景/设计文档按钮与 /api/spec-doc 端点基线（文档三页签弹窗展示、Escape 关闭不误伤其他弹窗）
- 2026-09-02 add-dashboard-spec-doc-tabs-and-info-clear（spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear） — 文档端点 `doc` 白名单由 {proposal, design} 扩展为 {proposal, design, tasks}（tasks.md 读取路径构造、缺失空态语义与既有行为一致）
- 2026-09-02 add-spec-doc-buttons（spec/archive/2026-09-02-add-spec-doc-buttons） — 固化文档按钮/弹窗契约：入口始终可见不要求文档存在、Markdown 渲染管线复用、加载占位与错误提示、缺失空态、关闭交互不阻塞列表页
- 2026-09-08 improve-v3-spec-doc-markdown（spec/archive/2026-09-08-improve-v3-spec-doc-markdown） — 落地三页签懒加载与组件内缓存、GFM Markdown 安全渲染（链接协议白名单）及空态/错误态/加载态三态区分（原 v3-spec-doc-view 能力页 2026-11-07 并入本页）
