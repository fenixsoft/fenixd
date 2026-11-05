# 验证报告：redesign-dashboard-v2-ui-mobile

> ⚠️ 本报告由框架于 2026-11-05T12:36:37Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-11-05T12:36:36.322256+00:00+run-result@mtime1793882196372280318

## 结论：✅ 通过（verified）

**状态：verified — 31/31 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 31/31 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 31 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 13.16M |
| 本链增量 Token（输出） | 0.17M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| fixture-registry-unignore | 夹具软删除解除 seed（幂等）：用户级 dashboard registry(~/.config/fenixd/dashboard.yaml) 的 ignored 列表若含 /root/scheduling-showcase（历史轮次删除类场景写入且跨轮持久；prepare 层 bin/fixture_scheduling_showcase.py 的 _ensure_registered 只登记不解除 ignored），discover() 一律过滤该路径 → /api/projects 不返回夹具项目，本轮 11 个夹具依赖场景级联失败（report 证据：概览无卡片/pd 卡片流空/作用域无选项/sd 默认渲染无 P5 无就绪）。本场景幂等移除该 ignored 条目（registry 项目发现 TTL 10s 内生效），恢复夹具可见性。 | pass | 0/2 | - |
| bp-token-single-source | 移动断点两轨同界的源码级单源校验：theme.tsx V2_MOBILE_MAX_WIDTH=767.98 与现产 useIsMobile 的 (max-width: 767.98px) 同界、v2.less @media 镜像同值；v2 域零散落 matchMedia、六页统一消费 useV2IsMobile、除 theme.tsx 外 tsx 零 767.98 魔法数（出处 core/dashboard/static/src/pages/v2/theme.tsx:157-166、src/hooks/useIsMobile.ts、pages/v2/v2.less:154-167） | pass | 0/10 | - |
| bp-boundary-just-below-768-mobile | 767px 视口（<768 边界内侧）设置页呈移动形态：.v2-chip-row 胶囊菜单与选中 chip （.v2-chip.on）可见、st-menu 锚点在位、桌面专属「新增 Provider」按钮不渲染、页面无溢出（出处 core/dashboard/static/src/pages/v2/settings.tsx:415-448,229；theme.tsx:157-166 useV2IsMobile 分支） | pass | 0/5 | - |
| v2m-overview-kpi-2x2 | 390px 概览页 KPI 四磁贴（SPEC 总数/任务进度/Token 消耗/活跃 Agent）移动 2×2 网格标签齐备，桌面专属任务进度圆环（.ant-progress）与「按类型分布」徽标不渲染，页面无越界（出处 overview.tsx:311-317 KPI 移动网格、:320,:371,:394,:423 磁贴 label、:379,:437-451 mobile 隐藏分支） | pass | 0/7 | - |
| v2m-overview-card-search-empty | 390px 概览页搜索无匹配空态：键入不存在项目名后项目卡片消失、空态文案「无匹配项目」可见（出处 overview.tsx:737 无匹配项目空态） | pass | 0/2 | - |
| v2m-overview-alert-banner-mobile | 390px 概览页告警胶囊卡（mock /api/alerts 注入 1 critical + 1 major 带 choices，端点为页面消费的既有壳层端点、非本 SPEC 交付端点）：「严重 1」胶囊 + N 条待处理 + 收起开关 + 去处置/标记已处理双按钮 + 次级告警行裁决 Select 与 pre-wrap 长明细 + 无越界（出处 overview.tsx:189-238 AlertCard 移动分支、AlertList.tsx:59-127 V2AlertRow 移动分支） | pass | 0/8 | - |
| v2m-overview-alert-collapse | 390px 概览页告警胶囊收起（渐进披露单方向终态）：点击「收起」后去处置按钮与次级告警行（裁决 Select）消失、「N 条待处理」仍在、开关文案变「展开」（出处 overview.tsx:211,:214-236 collapsed 分支） | pass | 0/4 | - |
| v2m-sd-tabs-short-labels | 390px SPEC 详情页签短标签：时间轴/场景/Bug/截图 N/Hook 短标签可见，桌面长标签（场景结果/测试截图/Bug 列表）不渲染；点「场景」页签落地空态「暂无验证报告」（夹具无验证报告；出处 specDetail.tsx:868-872 移动短标签、:875-879 桌面长标签、:418 空态 pill） | pass | 0/9 | - |
| v2m-sd-long-name-no-overflow | 390px 长名称 SPEC 详情：真实 SPEC redesign-dashboard-v2-ui-mobile 长名标题与 sd-tasks 任务卡可见，页面无横向溢出（D1 行壳位换行收纳契约；出处 specDetail.tsx:783-846 移动标题 17px 换行收纳、:190 sd-tasks） | pass | 0/3 | - |
| v2m-st-capsule-menu | 390px 设置页胶囊菜单分面切换：点「自进化」chip 落地占位面板（{label}分面 + 打开现产配置页按钮可用），「系统」chip 不被遮挡可触（出处 settings.tsx:342-347 PlaceholderPanel、:419-425 v2-chip-row/v2-chip.on） | pass | 0/4 | - |
| v2m-st-provider-cards-switches | 390px 设置页模型与网关分面移动堆叠卡：Provider 卡片与「健康检测」入口可见，知识真相源总开关（用户级）开关按钮可见且可用（aria-label 全角括号词表；出处 settings.tsx:136 st-provider 卡、:175 开关 label、:332 aria-label 模板） | pass | 0/5 | - |
| v2m-help-toc-drawer-pick-doc | 390px 帮助中心目录抽屉化：标题行「目录」按钮开抽屉 → 点「快速上手」toc 项后抽屉收起（pickDoc 选中即收）+ 正文落地快速上手 + 副标题 N 篇文档（出处 help.tsx:196-221 目录按钮与 Drawer、:139-145 pickDoc、:65 v2-toc-item） | pass | 0/4 | - |
| v2m-help-no-search-single-column | 390px 帮助中心正文单列且无搜索入口：hp-doc 磁贴可见、桌面双栏容器 hp-layout 不渲染、无搜索输入框、「目录」按钮在位、README 默认文档落地「Fenix 帮助中心」（现产两形态均无搜索入口与原型一致；出处 help.tsx:190-205 移动分支、:231 hp-layout、DEFAULT_DOC=README.md） | pass | 0/6 | - |
| v2m-ops-stat-chips-chain-cards | 390px 运维活动页统计条与处置链移动堆叠卡（mock /api/chain 注入 1 条在飞，端点为页面消费的既有壳层端点、非本 SPEC 交付端点）：待处理告警/在飞链/升级中/配额耗尽四项统计在位；点「处置链观测」页签后在飞链 1 + ch-ops-demo 卡可见 + 暂无升级件/暂无签名配额记录空态 + 无 .ant-table（移动堆叠卡替代桌面表格；出处 ops.tsx:31-36 StatRow、:93-163 ChainPane 移动分支、:388 页签） | pass | 0/9 | - |
| v2m-ops-alert-stacked-adjudication | 390px 运维页人工告警移动堆叠裁决（mock /api/alerts 注入 1 条带 choices + 1 条不带，端点为既有壳层端点非本 SPEC 交付端点）：带选项告警呈 严重 胶囊 + 选择处置动作 Select + 附注入口，选「重试处置」后「执行」按钮可用；无选项告警仅「标记已处理」出口（出处 AlertList.tsx:59-127 V2AlertRow 移动分支、useAlertAdjudication.tsx:124-160 执行按钮 disabled={!selChoiceId}） | pass | 0/6 | - |
| v2d-overview-table-radio-badges | 桌面概览零回归（≥768 默认视口）：项目表格 .v2-bento-table + 全部/运行中 Radio 组 + 「按类型分布」徽标 + 跨项目概览标题在位，页面无溢出（出处 overview.tsx:860-872 桌面 Radio 与表格、:437-451 徽标、:939 V2TitleBand） | pass | 0/6 | - |
| v2d-sd-transfer-entry-desktop-tabs | 桌面 SPEC 详情零回归（≥768 默认视口）：「状态转移」按钮与「更多操作」入口在位，长页签 运行时间轴/场景结果/测试截图 可见（出处 specDetail.tsx:793 状态转移、:810 更多操作、:875-879 桌面长页签） | pass | 0/5 | - |
| v2d-settings-provider-menu | 桌面设置页零回归（≥768 默认视口）：「新增 Provider」按钮与左侧 st-menu 菜单在位，移动专属 .v2-chip-row 胶囊菜单不渲染（出处 settings.tsx:229 新增 Provider、:451 桌面 st-menu、:419 移动 chip-row） | pass | 0/4 | - |
| v2d-help-two-pane-toc | 桌面帮助中心双栏零回归（≥768 默认视口）：hp-layout 双栏容器 + hp-toc 目录磁贴在位、「目录」按钮不渲染（桌面无目录按钮）、README 默认文档落地「Fenix 帮助中心」 + N 篇文档副标题（出处 help.tsx:231 hp-layout、:52 hp-toc、:196-205 目录按钮仅 mobile 分支） | pass | 0/5 | - |
| v2d-ops-chain-table | 桌面运维处置链零回归（≥768 默认视口，mock /api/chain 同 S23）：处置链观测页签下 .ant-table 表格 + ch-ops-demo 行可见 + 升级中统计在位（出处 ops.tsx:282-303 桌面 Table、:31-36 StatRow） | pass | 0/4 | - |
| v2m-overview-card-search-filter | 390px 概览页移动卡片流搜索过滤：搜索项目输入框键入 scheduling-showcase 后夹具项目卡片可见（出处 overview.tsx:669 Input.Search placeholder 搜索项目、:680-686 v2-bento 卡片流） | pass | 0/2 | - |
| v2m-overview-card-enter-project-detail | 390px 概览页卡片点击进入项目详情：点击 scheduling-showcase 卡片落地项目详情，副标题「共 8 个 SPEC」与夹具 SPEC 卡片可见（出处 overview.tsx:680-686 卡片 onClick navigate、projectDetail.tsx:470 subtitle 共 N 个 SPEC、:309 pd-row 卡片） | pass | 0/3 | - |
| v2m-pd-filter-dual-selects | 390px 项目详情页移动工具条：状态/模式双下拉（placeholder 状态、模式）可见，桌面专属搜索 SPEC 输入框与 Radio 组不渲染，夹具 SPEC 卡片可见（出处 projectDetail.tsx:279-365 移动分支、:286,:296 双 Select、:374,:384,:386-390 桌面专属控件） | pass | 0/6 | - |
| v2m-pd-mode-filter-empty | 390px 项目详情页模式过滤空态：模式下拉选「快速」后夹具 8 个 SPEC（均无 mode 字段）全部滤空，空态文案「无匹配 SPEC」+ pd-row 卡片清零（出处 projectDetail.tsx:296 模式 Select、:360 无匹配 SPEC；夹具 bin/fixture_scheduling_showcase.py BASELINE_STATE 无 mode）；断言选择器修复：原 [data-proto-id='pd-toolbar'] .ant-select:nth-child(2) 依赖兄弟序，选中「快速」后工具条插入选中值 SPAN 致第 2 子非 Select 而零匹配，改为 .ant-select:has-text('快速')（复现验证匹配且无遮挡） | pass | 0/3 | - |
| v2m-pd-status-filter-ready | 390px 项目详情页状态过滤：状态下拉选「就绪」后仅剩 2 张就绪夹具卡（c-sched-set/c-sched-clear），done 态 c-sched-done 卡片消失（出处 projectDetail.tsx:286 状态 Select mode=multiple、:309 pd-row；夹具 BASELINE_STATE 两 ready 一 done） | pass | 0/4 | - |
| v2m-pd-card-entry-spec-detail | 390px 项目详情卡片名称点击进 SPEC 详情：点击 c-sched-set 卡片名称 span 落地 SPEC 详情页，sd-info 信息卡可见（出处 projectDetail.tsx:309-317 名称 span onClick navigate、specDetail.tsx:129 sd-info） | pass | 0/3 | - |
| v2m-pd-card-dropdown-delete-confirm | 390px 项目详情卡片「更多操作」→ 删除：Dropdown 菜单点「删除」弹出确认框，文案含「将从项目中删除该 SPEC 目录，不可撤销」且弹窗按钮在位；不点确认避免污染夹具，故不挂拦截断言（弹窗遮罩覆盖底层，断言只看终态；出处 projectDetail.tsx:318-341 Dropdown、:155-157 modal.confirm 文案） | pass | 0/3 | - |
| v2m-sd-title-no-transfer | 390px SPEC 详情页头部收敛：标题 c-sched-set 与「就绪」状态胶囊可见，桌面专属「状态转移」按钮与「更多操作」入口移除（D4 移动端移除状态转移/删除等入口；出处 specDetail.tsx:783-846 移动形态、:793 状态转移、:810 更多操作） | pass | 0/4 | - |
| v2m-sd-info-single-column-dashes | 390px SPEC 详情信息卡单列键值行：优先级/创建时间/更新时间/依赖/输入 Token/输出 Token/耗时/成本 八行标签齐备，夹具 c-sched-set 呈 P5 与「无依赖」，sd-info 容器内数值 .v2-num 结构在位（出处 specDetail.tsx:115-130 items 词表、:129 sd-info、:138-151 移动单列键值行） | pass | 0/8 | - |
| v2m-st-scope-switch-refetch | 390px 设置页作用域切换触发数据重拉：作用域 Select 切「项目级：scheduling-showcase」→ 步骤窗口内 /api/config?project= 重拉（expect_network）+ 开关 aria-label 翻转为（项目级）（出处 settings.tsx:403-409 scope Select、:389-390 选项词表、:332 aria-label 模板） | pass | 0/2 | - |
| v2d-pd-table-search-radio | 桌面项目详情零回归（≥768 默认视口）：pd-table 表格 + 搜索 SPEC 输入框 + 全部/进行中 Radio 在位，移动专属 pd-row 卡片不渲染，夹具 c-sched-set 行可见（出处 projectDetail.tsx:367-420 桌面分支、:404 pd-table、:374 搜索 SPEC） | pass | 0/6 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

