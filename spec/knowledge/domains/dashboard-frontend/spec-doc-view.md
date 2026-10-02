<!-- knowledge: capability=spec-doc-view rev=2 sources=spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear,spec/archive/2026-09-02-add-spec-doc-buttons -->

# SPEC 文档查看

SPEC 文档端点与文档弹窗：proposal/design/tasks 原文读取、Markdown 渲染与空态语义。

## 现行规则

- 文档端点：`GET /api/spec-doc?project=<name>&spec=<name>&doc=<proposal|design|tasks>` 按项目与 SPEC 名称读取 `spec/changes/<spec>/` 目录下的对应文档原文，返回 `{found: boolean, content: string}`；文件缺失返回 `found=false`、content 为空字符串；`doc` 参数仅接受 `proposal`/`design`/`tasks` 三个值，其余值返回 400；`spec` 名称须匹配 kebab-case（`^[a-z0-9][a-z0-9-]*$`），不匹配或该 SPEC 不存在于项目中返回 404，且不读取任何 `spec/changes/` 目录之外的文件；该端点不影响既有 `/api/specs` 及其它端点。
- 文档弹窗：SPEC 列表行内文档入口在当前页弹出模态窗展示该 SPEC 文档，标题包含 SPEC 名称；正文以 Markdown 渲染（复用既有 `marked` 渲染管线，支持 GFM 语法，执行既有链接白名单与转义约束）。
- 加载与失败：加载期间显示加载占位；请求失败（非 200/404、网络中断）显示错误提示，不显示空文档。
- 缺失空态：对应文档文件不存在时，弹窗内展示明确空态文案（如「该 spec 未提供设计文档」），而非空白或报错；文档入口在缺失时保持可见可点。
- 关闭交互：弹窗支持通过关闭按钮、点击遮罩与 Esc 键关闭，Esc 关闭不误伤其他弹窗；弹窗打开期间不阻塞列表页状态，关闭后列表页保持原状。
- 入口与跳转隔离：点击文档入口仅弹窗展示文档，不触发行级跳转进入详情页；点击行其余区域保持原有跳转行为。

## 溯源

- 史前复原 — 背景/设计文档按钮与 /api/spec-doc 端点基线（文档三页签弹窗展示、Escape 关闭不误伤其他弹窗）
- 2026-09-02 add-dashboard-spec-doc-tabs-and-info-clear（spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear） — 文档端点 `doc` 白名单由 {proposal, design} 扩展为 {proposal, design, tasks}（tasks.md 读取路径构造、缺失空态语义与既有行为一致）
- 2026-09-02 add-spec-doc-buttons（spec/archive/2026-09-02-add-spec-doc-buttons） — 固化文档按钮/弹窗契约：入口始终可见不要求文档存在、Markdown 渲染管线复用、加载占位与错误提示、缺失空态、关闭交互不阻塞列表页
