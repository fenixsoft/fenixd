// zh-CN.ts — Dashboard 中文文案目录（add-framework-i18n-zh-en 1.2 / design D3）。
//
// Umi Max locale 插件约定路径（config.ts locale.default 指向本文件）：
// 全站界面静态文案的唯一中文来源，键命名 `<域>.<页/组件>.<语义键>`。
// 域前缀划分：menu.*（侧栏菜单与页题链路）、common.*（通用动作/状态/空态）、
// projects.* / settings.* / overview.* / ops.*（运维页）/ commandCenter.* /
// help.* / components.*（全局组件）/ utils.*（utils 展示映射）。
//
// **en-US 目录以本文件为缺省底座**（design D3）：en-US.ts 经
// `{ ...zhCN, ...enOverrides }` 展开导出——en 缺键运行时自动回落中文，
// 杜绝「键名裸露」。新增键 MUST 先落本文件（zh 为回退源），再补 enOverrides。
//
// **双语术语对照表**（design Risks：技术术语译法统一，验证批按表复核）：
// - SPEC：不译（present tense id，本产品双语数据基因）
// - 晋升 = promote / 回炉 = reflow / 激活 = activate / 归档 = archive
// - 处置链 = disposition chain / 仲裁 = arbiter / 自愈 = self-heal
// - 运维 = ops（本页面名，区别于「设置/Settings」= dsh 官方）
// - 配置 = Config（本品页面名，避让 dsh 官方「设置/Settings」词汇面，
//   settings-page 能力页词汇对表纪律）
// - 实现者 = implementer / 规划者 = planner / 审查者 = reviewer /
//   验证者 = verifier / 裁决者 = judge / 管理员 = administrator
const zhCN = {
  // ── 侧栏菜单与页题链路（3.1：menuDataRender / routes / document.title 三处同源）──
  'menu.overview': '概览',
  'menu.projects': '项目',
  'menu.settings': '配置',
  'menu.ops': '运维',
  'menu.commandCenter': '指挥中心',
  'menu.help': '帮助',

  // ── 通用动作 ──
  'common.ok': '确定',
  'common.cancel': '取消',
  'common.close': '关闭',
  'common.save': '保存',
  'common.delete': '删除',
  'common.edit': '编辑',
  'common.refresh': '刷新',
  'common.retry': '重试',
  'common.copy': '复制',
  'common.search': '搜索',
  'common.reset': '重置',
  'common.more': '更多',
  'common.loading': '加载中…',
  'common.confirmTitle': '操作确认',

  // ── 通用状态 ──
  'common.status.unknown': '未知',
  'common.status.running': '运行中',
  'common.status.success': '成功',
  'common.status.failed': '失败',
  'common.status.pending': '等待中',
  'common.error': '错误',

  // ── 通用空态 ──
  'common.empty.default': '暂无数据',
  'common.empty.noResults': '无匹配结果',

  // 通用动作（表格列头）：**有意未进 enOverrides**——「en 缺键回退中文」契约的
  // 活样例（tests/localePreference.test.mjs 抽查本键返回中文文案，验证 spread
  // 底座回退）。en 翻译就绪后补入 enOverrides 并同步调整该测试抽查对象。
  'common.actions': '操作',

  // ── 配置页「界面语言」面板（add-framework-i18n-zh-en 2.1/2.2）──
  'settings.locale.tab': '界面语言',
  'settings.locale.title': '界面语言',
  'settings.locale.desc':
    '界面语言立即全站生效并保存在浏览器本地（不写入配置文件）。跟随系统档随浏览器语言自动判定。',
  'settings.locale.option.system': '跟随系统',
  'settings.locale.option.systemHint': '随浏览器语言自动判定（缺省）',
  'settings.locale.option.zh': '中文',
  'settings.locale.option.zhHint': '固定简体中文（zh-CN）',
  'settings.locale.option.en': 'English',
  'settings.locale.option.enHint': '固定英文（en-US），未覆盖文案回退中文',

  // ── 抽取批次合并区（.history/i18n-batch 片段合并，add-framework-i18n-zh-en 3.x）──

  // 批次：components（22 键）
  'components.pageTitleBar.themeToDark': "切换到深色风格",
  'components.pageTitleBar.themeToLight': "切换到浅色风格",
  'components.pageTitleBar.back': "返回",
  'components.pagePlaceholder.underConstruction': "建设中 — 该页面将在后续阶段实现",
  'components.scheduleFields.defaultHint': "将为该条目创建 SPEC 并进入流水线。执行时间：",
  'components.scheduleFields.optionImmediate': "创建后立即执行",
  'components.scheduleFields.optionScheduled': "在指定时间执行",
  'components.scheduleFields.optionManual': "手工激活",
  'components.scheduleFields.manualPendingSuffix': "，已设为待激活（手工激活后进入调度）",
  'components.scheduleFields.scheduledAtSuffix': "，将于 {time} 执行",
  'components.alertAdjudication.exec': "执行",
  'components.alertAdjudication.confirmTitle': "确认执行该裁决？",
  'components.alertAdjudication.confirmFallbackDesc': "该操作可能不可自动恢复，请确认",
  'components.alertAdjudication.okConfirm': "确认执行",
  'components.alertAdjudication.caveatNotMarked': "告警未入已处理（可重试「标记已处理」）",
  'components.alertAdjudication.caveatNotLogged': "处置留痕写入失败（审计轨迹缺失）",
  'components.alertAdjudication.caveatLogUnknown': "留痕状态未知（后端响应缺失 marked/disposition_logged 回执）",
  'components.alertAdjudication.executedBare': "裁决已执行",
  'components.alertAdjudication.executedLogged': "裁决已执行，处置留痕已写入",
  'components.alertAdjudication.caveatWrap': "（{caveats}）",
  'components.alertAdjudication.stepSuffix': "：{steps}",
  'components.alertAdjudication.execFailed': "裁决执行失败，告警保持未处理，可调整后重试",

  // 批次：projects（77 键）
  'projects.index.placeholderTitle': "项目",
  'projects.modeTag.fast': "快速模式",
  'projects.modeTag.full': "完整模式",
  'projects.runCancel.title': "终止运行",
  'projects.runCancel.okText': "确认终止",
  'projects.runCancel.cancelText': "取消",
  'projects.runCancel.successAccepted': "取消请求已受理，运行将在下一次轮询被终止",
  'projects.runCancel.pendingInfo': "已有进行中的取消请求，请等待受理",
  'projects.runCancel.failed': "取消失败：{msg}",
  'projects.runCancel.willTerminate': "即将终止运行",
  'projects.runCancel.reasonLabel': "终止原因（可选）：",
  'projects.runCancel.reasonPlaceholder': "如：空转烧 token、跑错方向…",
  'projects.runRecord.title': "运行记录 · {runId}",
  'projects.progressTile.done': "已完成 ",
  'projects.architecture.loadFailed': "加载失败: {msg}",
  'projects.architecture.acceptedGenerating': "已受理，架构图生成中",
  'projects.architecture.generatingBusy': "架构图生成正在进行中，请稍候",
  'projects.architecture.triggerFailed': "触发失败: {msg}",
  'projects.architecture.readFailedTitle': "进度读取失败，已停止自动刷新",
  'projects.architecture.readFailedDesc': "{err}（可点击「重试读取」，或切出本分面再切回触发重新读取）",
  'projects.architecture.retryRead': "重试读取",
  'projects.architecture.refresh': "刷新架构图",
  'projects.architecture.noneTitle': "尚未生成架构图",
  'projects.architecture.noneDesc': "系统将启动一次 headless harness 生成进程（挂 vendored floorplan skill，按 agent.harness 配置解析：claude 或 dsh）扫描并阅读本项目代码，产出一张可交互的高层运行时架构图（3–9 个顶层子系统 / 调用与数据流 / 外部依赖，中文标注）。生成不自动进行，可随时手动触发；生成需要几分钟到十几分钟。",
  'projects.architecture.generatingTitle': "架构图生成中…",
  'projects.architecture.generatingDesc': "正在阅读项目代码并绘制架构图，通常需要几分钟到十几分钟；可离开本页，稍后回来查看。",
  'projects.architecture.failedTitle': "架构图生成失败",
  'projects.architecture.failedFallback': "原因未知，可重试或查看服务端日志",
  'projects.architecture.iframeTitle': "项目架构图",
  'projects.codeFix.phase.idle': "空闲",
  'projects.codeFix.phase.selecting': "选批中",
  'projects.codeFix.phase.fixing': "修复中",
  'projects.codeFix.phase.regressing': "全量回归中",
  'projects.codeFix.phase.retrying': "回归失败重试中",
  'projects.codeFix.phase.merging': "合回主树中",
  'projects.codeFix.phase.blocked': "已阻塞",
  'projects.codeFix.phase.failed': "失败",
  'projects.codeFix.itemStatus.fixed': "已修复",
  'projects.codeFix.itemStatus.skipped': "已跳过",
  'projects.codeFix.batchDoneOf': "本批已处置 {done}/{total} 条",
  'projects.codeFix.batchDone': "本批已处置 {done} 条",
  'projects.codeFix.justFinished': "刚完成：{status}：{file}{title}",
  'projects.codeFix.startupWaited': "{stage}（已等待 {minutes} 分钟）",
  'projects.codeFix.reasonPrefix': "原因：{reason}",
  'projects.codeFix.readFailedPolling': "进度读取失败，已停止轮询",
  'projects.codeFix.titleWaiting': "自动修复代码问题（第 {batch} 批 · 等待下一轮）",
  'projects.codeFix.titlePhase': "自动修复代码问题（第 {batch} 批 · {phase}）",
  'projects.codeFix.howToHandle': "如何处理：{guidance}",
  'projects.home.kind.markdown': "Markdown",
  'projects.home.kind.image': "图片",
  'projects.home.kind.code': "代码",
  'projects.home.kind.text': "文本",
  'projects.home.dirLoadNotFound': "路径不存在，可能已被移动或删除",
  'projects.home.dirLoadFailed': "加载失败",
  'projects.home.pathMissing': "路径不存在",
  'projects.home.fileLoadFailed': "文件内容加载失败",
  'projects.home.col.name': "名称",
  'projects.home.authorFallback': "未知",
  'projects.home.linesAndSize': "{lines} 行 · {size}",
  'projects.home.download': "下载",
  'projects.adminInvoke.templateCheckProgress': "检查 {spec} 的进度",
  'projects.adminInvoke.templateInvestigate': "调查 {spec} 出现了什么问题并给出解决方案",
  'projects.adminInvoke.stalledWarning': "处置长时间无输出且未到终态，可能已中断，可重新发起",
  'projects.adminInvoke.promptRequired': "请输入给 Admin 的提示词",
  'projects.adminInvoke.conflictInfo': "已有进行中的 Admin 处置，正在定位其输出",
  'projects.adminInvoke.invokeFailed': "发起失败：{msg}",
  'projects.adminInvoke.title': "{spec} · 呼叫 Admin 介入",
  'projects.adminInvoke.eventCount': "共 {n} 条事件",
  'projects.adminInvoke.waitingText': "Administrator 已唤起",
  'projects.adminInvoke.stalledAlert': "处置超过 {minutes} 分钟无输出且未到终态，可能已中断：请重新发起或关闭弹窗稍后查看",
  'projects.adminInvoke.locateTimeout': "定位处置输出超时（超过 {seconds} 秒）：daemon 可能未受理本次请求，请重新发起或稍后重试",
  'projects.adminInvoke.queuedWaiting': "Administrator 正在处理先前的处置，本次请求已排队等候（串行处理，完成后自动开始）…",
  'projects.adminInvoke.waitingStart': "等待 Administrator 开始处置…",
  'projects.adminInvoke.promptHint': "在下方输入给 Admin 的提示词（可从输入框下拉选择常用问题），发起后此处将实时展示 Administrator 的处置输出。",
  'projects.adminInvoke.promptPlaceholder': "输入提示词，回车发起",
  'projects.adminInvoke.inProgress': "处置进行中",
  'projects.adminInvoke.invoke': "发起处置",

  // 批次：settings 页壳收口（3.3：保存/校验提示与作用域标签）
  'settings.index.projectsLoadFailed': "项目列表加载失败，项目级作用域暂不可用：{msg}",
  'settings.index.discardConfirm': "当前页签的修改尚未保存，切换将丢弃，确定继续？",
  'settings.index.saveFailed': "保存失败：{msg}",
  'settings.index.saveSuccess': "保存成功",
  'settings.index.savedButRefreshFailed': "已保存，但刷新配置失败，请切换作用域或刷新页面查看最新值",
  'settings.index.quickAssignApplied': "配置已保存，重启 daemon 后生效（快速分配成功写入 {count} 个目标）",
  'settings.index.fixValidationFirst': "请先修正表单校验错误",
  'settings.index.nothingToSave': "没有需要保存的变更",
  'settings.index.selfEvo.collectError': "收集自进化配置失败，保存已中止，请稍后重试",
  'settings.index.selfEvo.notReady': "自进化面板未就绪，无法收集本节配置，请稍后重试",
  'settings.index.arbiter.collectError': "收集仲裁配置失败，保存已中止，请稍后重试",
  'settings.index.arbiter.notReady': "仲裁面板未就绪，无法收集配置，请稍后重试",
  'settings.index.configMissing': "{scope, select, project {项目尚无配置文件，表单为默认值} other {用户级配置文件不存在，表单为默认值}}",
  'settings.index.configPath': "（解析路径：{path}）",
  // ── 配置页页签面板名（3.3：PAGE_LABELS 值改承载本目录键，单源契约不变）──
  'settings.tab.llm': "模型",
  'settings.tab.agents': "模型分配",
  'settings.tab.prompts': "提示词",
  'settings.tab.parallel': "并行",
  'settings.tab.token': "预算",
  'settings.tab.verify': "验证",
  'settings.tab.quality': "质量",
  'settings.tab.approval': "审批",
  'settings.tab.misc': "归档",
  'settings.tab.system': "系统",
  'settings.tab.selfEvolution': "自进化",
  'settings.tab.arbiter': "仲裁",
  'settings.tab.theme': "界面风格",
  'settings.tab.locale': "界面语言",
  'settings.tab.selfReview': "自省",
  'settings.tab.projectProfile': "项目",
  'settings.tab.hook': "Hook",
  // ── 模型分配面板角色标签（3.3 补落：AgentModelPanel labelKey 引用的目录键，
  //    zh 与抽取前字面量逐字一致；缺键即裸键名渲染，D3 契约红线）──
  'settings.agents.role.implementer': "Implementer（执行）",
  'settings.agents.role.plannerPlan': "Planner Plan（生成场景）",
  'settings.agents.role.plannerJudge': "Planner Judge（判定结果）",
  'settings.agents.role.verifier': "Verifier（验证）",
  'settings.agents.role.administrator': "Administrator（运维）",
  'settings.agents.role.selfReview': "Self-Review（自省）/ Evolution（自改进）",
  'settings.agents.role.fastTrack': "Fast-Track（快速通道）",
  'settings.agents.role.specReview': "Spec Review（方案评审）",
  'settings.agents.role.disputeJudge': "Dispute Judge（交付物终审）",
  'settings.agents.role.codeReview': "Code-Review（代码审查）",
  'settings.agents.role.codeFix': "Code-Fix（自动修复）",
  'settings.agents.role.knowledgeDistiller': "Knowledge-Distiller（知识蒸馏）",
  'settings.agents.role.arbiter': "Arbiter（全局决策）",
  'settings.agents.roleFallback': "角色 {index}",
  'settings.index.scopeLabel': "作用域：",
  'settings.index.scopeUser': "用户级",
  'settings.index.scopeProject': "项目级：{name}",

  // 批次：command-center 页壳收口（3.4；页题 title 复用 menu.commandCenter）
  'commandCenter.index.allProjects': "全部项目",
  'commandCenter.index.tabOrg': "组织总览",
  'commandCenter.index.tabPipeline': "交付流水线",
  'commandCenter.index.tabLedger': "执行台账",

  // 批次：help 页壳收口（3.4；页题 title 复用 menu.help）
  'help.index.docsListLoadFailed': "文档清单加载失败",
  'help.index.docLoadFailed': "文档加载失败",
  'help.index.empty': "暂无帮助文档",
  'help.index.contentEmpty': "文档内容为空",
  'help.index.docToc': "文档目录",

  // 批次：activities 页壳收口（3.4；横幅合并透出文案）
  'activities.index.alertsLoadFailed': "{actMsg}；告警加载失败：{err}",
} as const;

export default zhCN;
