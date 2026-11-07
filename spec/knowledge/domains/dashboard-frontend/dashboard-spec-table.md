<!-- knowledge: capability=dashboard-spec-table rev=12 sources=spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear,spec/archive/2026-09-02-add-dashboard-spec-table,spec/archive/2026-09-02-add-spec-doc-buttons,spec/archive/2026-09-02-add-spec-list-hover-hint,spec/archive/2026-09-02-add-spec-type-filter,spec/archive/2026-09-23-add-spec-manual-activation,spec/archive/2026-10-06-add-archive-state-migration,spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md,spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md,spec/changes/add-spec-chinese-title,spec/changes/add-spec-subtitle-and-row-click,spec/changes/add-spec-list-mobile-style -->

# SPEC 列表表格

项目视图的 SPEC 列表主体：桌面（≥768px）为 v2 台账表格形态（功能保留），移动端（<768px）为磁贴卡片流形态；承载列表化展示、整行/整卡点击进详情、前端过滤、行内文档入口、错误信息子行与状态列标记。移动端卡片与筛选编排的界面布局与组件形态以批准原型为 UI 真相源（冲突须升级用户裁决），数值与交互语义以本页规则为准。

## 现行规则

- 归档清单条目合并：`/api/specs` 在活跃 STATE.md 条目之外合并归档清单 `.fenix/STATE.archive.md` 的条目（并集，同名单活跃侧优先，不产生重复行），使条目已迁出的已归档 SPEC 继续出现在列表中且 archived=true；清单条目透迁出前的既有字段（status、created、updated、优先级等）与 `archived_at`/`archived_by` 溯源字段。「已归档」视图对这些行复用既有渲染（状态、任务进度、文档按钮等，文档与进度经归档目录回退读取）；默认「未归档」视图不出现清单条目；概览统计口径不受本合并影响（统计只算活跃）。
- 列表数据与默认排序：`/api/specs` 每个 SPEC 摘要项含 `created` 与 `updated` 字段（取 STATE.md 条目的 ISO 时间，缺失为 null）；列表以 created 倒序（新在前）为默认排序，缺失创建时间的排最后；默认排序仅在用户未选择任何表头排序时生效。
- 表格化展示：以带表头的表格呈现，表头逐列说明含义（状态/模式/名称/优先级/创建时间/任务进度/验证/耗时等）；无创建时间或验证进度的行显示占位符「—」。
- 整行点击进详情：行任意位置（任务进度、耗时、状态等非交互单元格）点击即进入该 SPEC 详情页，整行 `cursor: pointer`（与 overview 项目表格同一整行点击范式）；行内既有交互不被行点击吞并——展开钮（fix-* 树展开/收起、error 信息子行展开）点击仅做展开切换，操作列（⋯ 菜单、状态操作）点击仅触发对应操作，交互单元格经事件守卫（stopPropagation 或事件目标判定命中展开钮/操作列容器即短路）阻止行级导航；名称链接不额外拦截（链接自身导航与行导航同目标，连跳同路由无害）；展开行内容区点击不触发导航（expandedRowRender 渲染于行外，天然不在行级命中面）；无 error 抑制语义（overview 行点击的 error 守卫在 SPEC 列表无对应物），行恒可点；名称 Why 悬浮提示等其余行内交互不变。
- 桌面表格 v2 重绘（重绘非替换）：DevTab 桌面表格重绘为 v2 台账形态——Table 包 `.ov-bento` > `.ov-bento-table`（白磁贴发丝边 + 透明表头 + 发丝线行分隔 + 首列缩进，复用 overview 侧镜像 CSS，双页共享同改），优先级列表头 nowrap（6% 定宽防三字头折行）；antd Table 全部功能保留——表头排序、分页（20 条 + 换页大小）、树形展开、信息子行、悬浮 Why 提示与验证结论悬浮、优先级编辑、行选中底色；只重绘边框与行内容呈现，不得退化为自绘表格丢功能。
- 行内容 v2 形态：状态=语义胶囊（原色点+文字）；模式=胶囊（快速 warning / 标准 muted——详情页仍走 ModeTag 单源）；名称=dense 形态（13.5px 半粗深色单行省略，悬浮 Why 与键盘跳转不变）；创建时间=等宽三阶灰（精度保持完整时间戳）；任务进度=阶段名 + 「计数 · 百分比」同行置于进度条上方（镜像 v2 PhaseProgressCell 版式；run 线索与验证/门禁 current 行保留）；验证=胶囊（异常红/进行中蓝/完毕灰/未执行灰，悬浮结论不变）；耗时=右对齐等宽。进度条配色不走 v2 ramp：progressPhase.ts 阶段 ramp 是 DESIGN.md 登记的数据编码色豁免（底轨「空条可辨」语义），保留原函数。
- 名称列中文副标题：名称列在 SPEC 英文名主行下方渲染中文标题副标题行（数据源条目 `title` 字段）——次级视觉（字号小于主行、次级文字色、单行省略），随主行同级缩进（fix-* 树形子行缩进保持）；title 为 null/空不渲染副标题行（保持单行形态，缺失=无该行而非「—」占位）；副标题不承载点击与悬停交互，行点击进详情、名称 Why 悬浮提示等既有交互不变；排序键仍为英文名（字典序），fix-* 类型过滤与树形挂载不受影响。
- 前端过滤（桌面表格分支）：名称关键字输入框（大小写不敏感、包含匹配，英文名或中文标题任一命中即保留该行）与状态下拉框（「全部状态」或指定状态）；过滤作用于已排序的列表、保留排序顺序，纯前端实现不发起新的服务端请求；过滤后为空展示「无匹配的 SPEC」空态（区别于「该项目暂无 SPEC」）。
- 类型过滤（桌面表格分支）：Radio 并排按钮组「全部 / 仅需求 / 仅问题」，默认「全部」；「仅需求」隐藏名称以 `fix-` 开头的全部 SPEC（含无父级分组行及其子树），「仅问题」仅显示 `fix-` 开头的 SPEC；类型过滤与名称、状态过滤 AND 叠加，不改变排序，仅问题视图下 fix 树层级缩进保持。
- 过滤 Radio 组黑底白字：类型过滤与归档切换两组 Radio 并排按钮组挂独立单源覆写类 `.ov-radio-dark`（激活项黑底白字，DESIGN.md 一般域条款；overview 运行态筛选同挂同源类）。
- 刷新保持：2 秒自动刷新/SSE 重绘仅更新表格数据，不重置名称关键字、状态选择与类型选择，过滤条件仍生效且控件回填当前值。
- 行内文档入口：每行操作列为三点图标触发的下拉菜单（与 overview 台账同款），「文档」为菜单首项且恒可见（不要求文档文件存在），点击打开三页签文档弹窗（需求背景/详细设计/任务清单，对应 proposal.md/design.md/tasks.md）且不触发行级跳转，点击行其余区域保持跳转详情；菜单其余项仍由 onMenu 单点承载。
- 文档弹窗：正文以 Markdown 渲染（复用 marked 渲染管线，支持 GFM，执行既有链接白名单与转义约束），标题含 SPEC 名称；页签内容按需加载——默认激活「需求背景」，切换到未加载页签发起请求并显示加载占位，已加载页签直接用缓存不再请求；加载失败在页签内显示错误提示；文档缺失显示页签级空态文案（如「该 spec 未提供详细设计文档」）而非空白或报错，链接与页签在缺失时保持可见可点；弹窗经关闭按钮或点击遮罩关闭，打开期间不阻塞列表页状态，关闭后列表页保持原状。
- 错误信息子行：表格无「错误」列（表头、单元格与以 error 为键的排序一并移除）；STATE.md 条目 `error` 字段非空时，在该 SPEC 行正下方渲染跨全部列宽的信息子行，完整文本展示、自动换行、不截断；「信息」标签与消息内容渲染在同一行（消息内部换行按原样保留，长行独立换行不破坏表格宽度）；error 为空或 null 不渲染子行、不占行高。
- 信息清除：信息子行行尾提供「清除」按钮（点击不触发行级跳转），调用 `POST /api/spec-error-clear?project=<name>&spec=<name>` 将该 SPEC 的 error 字段置空（原子写回，不改动其余字段），列表刷新后子行消失；清除为当前快照操作，后续再次写入 error 时子行重新出现；清除失败在行内给出失败提示，不产生误导性成功感。
- 名称 hover 提示：悬停 SPEC 名称单元格显示悬浮提示框，内容为 proposal.md `## Why` 段的 Markdown 渲染结果；按需经 `GET /api/spec-doc?doc=proposal` 获取并按 (project, spec 名) 内存缓存，重复悬停不发请求；proposal 缺失、无 `## Why` 段或提取后无内容时不显示；移开单元格或点击行跳转时隐藏，视口边缘自动翻转定位，不影响行点击/排序/过滤。
- 状态列标记：`start_after` 为哨兵值 `manual` 的 SPEC 额外渲染「待激活」tag（配色与语义对齐「人工介入等待」，hover 提示需人工激活后才会被拾取；桌面表格与移动端卡片均渲染）；status 为 `ready` 且 `depends_on` 规范化后非空的 SPEC 渲染「前置依赖」tag（hover 显示依赖 SPEC 名单；仅 ready 展示，其它状态不展示）；两类标记均不改变既有排序/过滤与行点击跳转。
- depends_on 摘要字段：`/api/specs` 摘要含规范化后的 `depends_on`——缺失/null/空串/字面量字符串 `"null"` 统一折叠为 null（与调度器 `_dependencies_satisfied` 的 `deps == "null"` 守卫同口径，保证展示与调度读出一致依赖语义）；该字段纳入列表摘要索引条目指纹字段集，依赖变化即触发摘要缓存失效重算，「前置依赖」标记不滞后。

- 移动断点与桌面互斥：SPEC 列表以 768px 为分支断点——<768px 渲染移动卡片流，≥768px 渲染桌面表格（列结构/排序/整行点击/树形展开/信息子行保持现状），两分支互斥不同时渲染。
- 移动卡片承载体：整页一张白磁贴（12px 圆角、发丝边框，Bento 磁贴通用条款）承载全部卡片，卡间发丝线分隔（不逐卡开卡框，信息密度优先），磁贴置于内容区左右留白 15px 内。
- 移动卡片信息层级：英文名主行（14px/600 单行省略）→ 中文标题次行（12px 三阶灰单行省略，title 缺失不渲染该行）→ 语义胶囊行 → 阶段进度区 → 元信息行 → 验证行 → 信息行；整卡为点击目标。
- 移动卡片语义胶囊行：状态胶囊取 STATUS_META tone 色对（999 软底、带色点，与桌面列 Pill 单源同构，移动端不另造色）；等待标记组（定时/待激活/前置依赖）为独立灰软底胶囊；模式胶囊「快速」橙软底（warning）、「标准」灰软底（muted）。
- 移动卡片阶段进度区：阶段名与「计数 · 百分比」同行置于进度条上方，阶段推导与桌面「任务进度」列共用 phaseProgressOf 单源；进度条色随阶段 ramp（progressPhase 单源，DESIGN.md 登记的数据编码色豁免），移动端禁另写色值表。
- 移动卡片终态紧凑化：终态（已推送/完成）卡省略阶段进度区（终态不重复画 100% 条）；草稿或无任务计数显「—」（0 与口径不可得分离，不显示假 0）。
- 移动卡片元信息行：优先级、创建时间、耗时以竖线分隔（12px tabular-nums）；run 活跃时追加「● 运行中」（success 色静态绿点）。
- 移动卡片验证行与信息行：验证行 通过 ✓ 绿、异常 ⚠ 红（VerifyCell 语义随迁）；条目有 error 的卡渲染信息行（amber 软底圆角条、orange「信息」前缀、摘要单行省略）。
- 移动卡片树形与导航：fix-* 子卡缩进 26px 并以 `└` 前缀灰符标识父子 relations（buildTree 树形单源不变）；整卡点击进详情（specDetailPath 单源）；卡内 ⋮ 更多菜单（触控目标 32px）承载 查看文档/调整优先级/冻结 操作项。
- 移动卡片实现落点：卡片样式走 JSX 内联（不新增 less）；SSE 增量 patch 下卡片按 rowKey 身份复用（不自引入索引复用）。
- 移动筛选编排：搜索框保留既有命中语义（specKeywordHit 单源：英文名 OR 中文标题）；状态筛选为横向滚动 chips（全部与各状态 + 计数徽标，激活态黑底白字镜像 overview Radio 惯例，再点取消）；「筛选」按钮打开底部 Drawer（antd Segmented 三组：类型 全部/进行中/已完成、归档 未归档/已归档、排序 名称/优先级/进度/创建时间——排序键集合与桌面表头一致），「查看结果」关闭 Drawer 并按所选过滤排序生效。
- 移动分页：磁贴底部「加载更多」按钮 +「共 N 条 · 已显示 M 条」caption 替代 antd 分页器；数据层 pageSize 20 分页语义不变，已显示满额时按钮禁用。
- 移动内容区背景色：SPEC 列表页移动端内容区背景为白底 `#ffffff`（theme.ts 单源常量 `SPEC_LIST_MOBILE_BG` 消费；色值条款在 DESIGN.md 修正案登记，改值走附则修正案程序；白磁贴卡与白底之间靠磁贴发丝边分界，不依赖灰底衬托；仅移动端内容区消费，桌面不改）。
- 移动顶栏豁免：SPEC 列表页顶栏（页面标题栏）在移动端不做适配处理、保持现状（用户批注豁免）。

## 溯源

- 史前复原 — SPEC 表 summary 携带 created/updated、created 倒序缺失排最后与表头排序/耗时列可用基线
- 2026-09-02 add-dashboard-spec-doc-tabs-and-info-clear（spec/archive/2026-09-02-add-dashboard-spec-doc-tabs-and-info-clear） — 建立「文档」单链接入口（整合背景/设计两按钮）与信息子行「标签同行 + 清除按钮」契约
- 2026-09-02 add-dashboard-spec-table（spec/archive/2026-09-02-add-dashboard-spec-table） — 建立 created/updated 摘要字段、created 倒序默认排序、表格化展示与名称/状态前端过滤及其刷新保持
- 2026-09-02 add-spec-doc-buttons（spec/archive/2026-09-02-add-spec-doc-buttons） — 固化三页签文档弹窗（按需加载与缓存、页签级缺失空态）与信息子行 error 清除链路
- 2026-09-02 add-spec-list-hover-hint（spec/archive/2026-09-02-add-spec-list-hover-hint） — 新增名称 hover Why 提示（div 悬浮 + 按需缓存），并以信息子行替换「错误」列
- 2026-09-02 add-spec-type-filter（spec/archive/2026-09-02-add-spec-type-filter） — 新增类型过滤（全部/仅需求/仅问题，fix- 树层级保持）
- 2026-09-23 add-spec-manual-activation（spec/archive/2026-09-23-add-spec-manual-activation） — 新增「待激活」「前置依赖」状态列标记与 depends_on 规范化摘要字段（纳入指纹字段集）
- 2026-10-06 add-archive-state-migration（spec/archive/2026-10-06-add-archive-state-migration） — 新增列表合并归档清单条目（并集、同名单活跃侧优先、透传 archived_at/archived_by 溯源字段）；已归档视图对已迁出条目仍可见可进详情，未归档视图不含清单条目
- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — DevTab 桌面表格 v2 重绘非替换（antd 功能保留、.ov-bento/.ov-bento-table 边框）、行内容 v2 形态（状态/模式/名称 dense/创建时间/任务进度/验证/耗时，进度 ramp 豁免保留）、操作列改三点菜单且「文档」并入首项（入口位迁移，恒可见契约保留）、类型过滤改 Radio 组并与归档切换同挂 .ov-radio-dark 黑底白字
- 2026-11-06 add-spec-chinese-title（spec/changes/add-spec-chinese-title/） — 新增名称列中文副标题条款（英文名主行下方次级中文行、缺失零渲染）与名称关键字过滤中文标题 OR 命中；排序键仍为英文名、树形/类型过滤语义不变
- 2026-11-06 add-spec-subtitle-and-row-click（spec/changes/add-spec-subtitle-and-row-click/） — 新增整行点击进详情条款（任意非交互单元格可点、展开钮/操作列事件守卫、名称链接连跳不拦截、展开行豁免、无 error 抑制语义）
- 2026-11-06 add-spec-list-mobile-style（spec/changes/add-spec-list-mobile-style/） — 移动端节整体改版：新增移动卡片形态与移动筛选编排规则组（白磁贴卡流与七行层级、语义胶囊行镜像 v2 色对、阶段进度区共用单源、终态紧凑化与草稿「—」、元信息/验证/信息行、fix-* 子卡缩进 └、整卡点击与 ⋮ 菜单、状态 chips、筛选底部 Drawer、加载更多分页、#E3E3E3 内容区背景单源常量）；废除移动卡片链接蓝 16px 名称形态与平铺按钮文档入口（收编卡内 ⋮ 菜单）；桌面表格规则零改动
- 2026-11-07 mobile-ui-fixes-1107（spec/knowledge/_inbox/done/mobile-ui-fixes-1107.md） — 移动内容区背景色改白：SPEC_LIST_MOBILE_BG 单源值 #E3E3E3→#ffffff，灰底衬托退役（白磁贴卡靠发丝边分界），DESIGN.md 修正案登记随值同步、改值走附则修正案程序纪律不变
