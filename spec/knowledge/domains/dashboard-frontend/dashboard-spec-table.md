<!-- knowledge: capability=dashboard-spec-table rev=7 sources=spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear,spec/archive/2026-09-02-add-dashboard-spec-table,spec/archive/2026-09-02-add-spec-doc-buttons,spec/archive/2026-09-02-add-spec-list-hover-hint,spec/archive/2026-09-02-add-spec-type-filter,spec/archive/2026-09-23-add-spec-manual-activation,spec/archive/2026-10-06-add-archive-state-migration -->

# SPEC 列表表格

项目视图的 SPEC 列表主体：表格化展示、前端过滤、行内文档入口、错误信息子行与状态列标记。

## 现行规则

- 归档清单条目合并：`/api/specs` 在活跃 STATE.md 条目之外合并归档清单 `.fenix/STATE.archive.md` 的条目（并集，同名单活跃侧优先，不产生重复行），使条目已迁出的已归档 SPEC 继续出现在列表中且 archived=true；清单条目透迁出前的既有字段（status、created、updated、优先级等）与 `archived_at`/`archived_by` 溯源字段。「已归档」视图对这些行复用既有渲染（状态、任务进度、文档按钮等，文档与进度经归档目录回退读取）；默认「未归档」视图不出现清单条目；概览统计口径不受本合并影响（统计只算活跃）。
- 列表数据与默认排序：`/api/specs` 每个 SPEC 摘要项含 `created` 与 `updated` 字段（取 STATE.md 条目的 ISO 时间，缺失为 null）；列表以 created 倒序（新在前）为默认排序，缺失创建时间的排最后；默认排序仅在用户未选择任何表头排序时生效。
- 表格化展示：以带表头的表格呈现，表头逐列说明含义（状态/名称/优先级/创建时间/任务进度/验证等）；每行保留点击进详情、状态 pill、进度条等既有视觉；无创建时间或验证进度的行显示占位符「—」。
- 前端过滤：名称关键字输入框（大小写不敏感、包含匹配）与状态下拉框（「全部状态」或指定状态）；过滤作用于已排序的列表、保留排序顺序，纯前端实现不发起新的服务端请求；过滤后为空展示「无匹配的 SPEC」空态（区别于「该项目暂无 SPEC」）。
- 类型过滤：过滤栏类型下拉框「全部 / 仅需求 / 仅问题」，默认「全部」；「仅需求」隐藏名称以 `fix-` 开头的全部 SPEC（含无父级分组行及其子树），「仅问题」仅显示 `fix-` 开头的 SPEC；类型过滤与名称、状态过滤 AND 叠加，不改变排序，仅问题视图下 fix 树层级缩进保持。
- 刷新保持：2 秒自动刷新/SSE 重绘仅更新表格数据，不重置名称关键字、状态选择与类型选择，过滤条件仍生效且控件回填当前值。
- 行内文档入口：每行文档操作列为单个「文档」超链接（始终可见，不要求文档文件存在），点击打开三页签文档弹窗（需求背景/详细设计/任务清单，对应 proposal.md/design.md/tasks.md）且不触发行级跳转；点击行其余区域保持跳转详情。
- 文档弹窗：正文以 Markdown 渲染（复用 marked 渲染管线，支持 GFM，执行既有链接白名单与转义约束），标题含 SPEC 名称；页签内容按需加载——默认激活「需求背景」，切换到未加载页签发起请求并显示加载占位，已加载页签直接用缓存不再请求；加载失败在页签内显示错误提示；文档缺失显示页签级空态文案（如「该 spec 未提供详细设计文档」）而非空白或报错，链接与页签在缺失时保持可见可点；弹窗经关闭按钮或点击遮罩关闭，打开期间不阻塞列表页状态，关闭后列表页保持原状。
- 错误信息子行：表格无「错误」列（表头、单元格与以 error 为键的排序一并移除）；STATE.md 条目 `error` 字段非空时，在该 SPEC 行正下方渲染跨全部列宽的信息子行，完整文本展示、自动换行、不截断；「信息」标签与消息内容渲染在同一行（消息内部换行按原样保留，长行独立换行不破坏表格宽度）；error 为空或 null 不渲染子行、不占行高。
- 信息清除：信息子行行尾提供「清除」按钮（点击不触发行级跳转），调用 `POST /api/spec-error-clear?project=<name>&spec=<name>` 将该 SPEC 的 error 字段置空（原子写回，不改动其余字段），列表刷新后子行消失；清除为当前快照操作，后续再次写入 error 时子行重新出现；清除失败在行内给出失败提示，不产生误导性成功感。
- 名称 hover 提示：悬停 SPEC 名称单元格显示 div 模拟悬浮提示框（非 title 属性），内容为 proposal.md `## Why` 段的 Markdown 渲染结果；按需经 `GET /api/spec-doc?doc=proposal` 获取并按 (project, spec 名) 内存缓存，重复悬停不发请求；proposal 缺失、无 `## Why` 段或提取后无内容时不显示；移开单元格或点击行跳转时隐藏，视口边缘自动翻转定位，不影响行点击/排序/过滤。
- 状态列标记：`start_after` 为哨兵值 `manual` 的 SPEC 额外渲染「待激活」tag（配色与语义对齐「人工介入等待」，hover 提示需人工激活后才会被拾取；桌面表格与移动端卡片均渲染）；status 为 `ready` 且 `depends_on` 规范化后非空的 SPEC 渲染「前置依赖」tag（hover 显示依赖 SPEC 名单；仅 ready 展示，其它状态不展示）；两类标记均不改变既有排序/过滤与行点击跳转。
- depends_on 摘要字段：`/api/specs` 摘要含规范化后的 `depends_on`——缺失/null/空串/字面量字符串 `"null"` 统一折叠为 null（与调度器 `_dependencies_satisfied` 的 `deps == "null"` 守卫同口径，保证展示与调度读出一致依赖语义）；该字段纳入列表摘要索引条目指纹字段集，依赖变化即触发摘要缓存失效重算，「前置依赖」标记不滞后。

## 溯源

- 史前复原 — SPEC 表 summary 携带 created/updated、created 倒序缺失排最后与表头排序/耗时列可用基线
- 2026-09-02 add-dashboard-spec-doc-tabs-and-info-clear（spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear） — 建立「文档」单链接入口（整合背景/设计两按钮）与信息子行「标签同行 + 清除按钮」契约
- 2026-09-02 add-dashboard-spec-table（spec/archive/2026-09-02-add-dashboard-spec-table） — 建立 created/updated 摘要字段、created 倒序默认排序、表格化展示与名称/状态前端过滤及其刷新保持
- 2026-09-02 add-spec-doc-buttons（spec/archive/2026-09-02-add-spec-doc-buttons） — 固化三页签文档弹窗（按需加载与缓存、页签级缺失空态）与信息子行 error 清除链路
- 2026-09-02 add-spec-list-hover-hint（spec/archive/2026-09-02-add-spec-list-hover-hint） — 新增名称 hover Why 提示（div 悬浮 + 按需缓存），并以信息子行替换「错误」列
- 2026-09-02 add-spec-type-filter（spec/archive/2026-09-02-add-spec-type-filter） — 新增类型过滤（全部/仅需求/仅问题，fix- 树层级保持）
- 2026-09-23 add-spec-manual-activation（spec/archive/2026-09-23-add-spec-manual-activation） — 新增「待激活」「前置依赖」状态列标记与 depends_on 规范化摘要字段（纳入指纹字段集）
- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 新增列表合并归档清单条目（并集、同名单活跃侧优先、透传 archived_at/archived_by 溯源字段）；已归档视图对已迁出条目仍可见可进详情，未归档视图不含清单条目
