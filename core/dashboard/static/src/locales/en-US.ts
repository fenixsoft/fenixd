// en-US.ts — Dashboard 英文文案目录（add-framework-i18n-zh-en 1.2 / design D3）。
//
// **spread 底座回退契约**（design D3）：导出 `{ ...zhCN, ...enOverrides }`——
// 未翻译键自动回落中文，运行时永不出现键名裸露（dashboard-i18n
// 「未覆盖键回退中文不裸露键名」Scenario）。enOverrides 键集 MUST ⊆
// zh-CN 键集，tests/localePreference.test.mjs 静态断言（防拼写漂移）。
// 术语对照表见 zh-CN.ts 文件头注释（目录内单点承载）。
import zhCN from './zh-CN.ts';

/**
 * en 覆写集：仅登记已完成翻译的键。新增键先落 zh-CN.ts（回退源），
 * 翻译完成后在本对象补同键英文覆写。
 */
export const enOverrides: Record<string, string> = {
  // ── 侧栏菜单与页题链路 ──
  'menu.overview': 'Overview',
  'menu.projects': 'Projects',
  'menu.settings': 'Config',
  'menu.ops': 'Ops',
  'menu.commandCenter': 'Command Center',
  'menu.help': 'Help',

  // ── 通用动作 ──
  'common.ok': 'OK',
  'common.cancel': 'Cancel',
  'common.close': 'Close',
  'common.save': 'Save',
  'common.delete': 'Delete',
  'common.edit': 'Edit',
  'common.refresh': 'Refresh',
  'common.retry': 'Retry',
  'common.copy': 'Copy',
  'common.search': 'Search',
  'common.reset': 'Reset',
  'common.more': 'More',
  'common.loading': 'Loading…',
  'common.confirmTitle': 'Confirm',

  // ── 通用状态 ──
  'common.status.unknown': 'Unknown',
  'common.status.running': 'Running',
  'common.status.success': 'Success',
  'common.status.failed': 'Failed',
  'common.status.pending': 'Pending',
  'common.error': 'Error',

  // ── 通用空态 ──
  'common.empty.default': 'No data yet',
  'common.empty.noResults': 'No matching results',

  // 注意：common.actions 有意不覆写——「en 缺键回退中文」契约活样例
  // （zh-CN.ts 内注释与 tests/localePreference.test.mjs 抽查断言）。

  // ── 配置页「界面语言」面板 ──
  'settings.locale.tab': 'Language',
  'settings.locale.title': 'Language',
  'settings.locale.desc':
    'Applies immediately and is stored in your browser (not written to config files). The system option follows your browser language.',
  'settings.locale.option.system': 'System',
  'settings.locale.option.systemHint': 'Follow the browser language (default)',
  'settings.locale.option.zh': '中文',
  'settings.locale.option.zhHint': 'Fixed Simplified Chinese (zh-CN)',
  'settings.locale.option.en': 'English',
  'settings.locale.option.enHint': 'Fixed English (en-US); uncovered text falls back to Chinese',

  // ── 抽取批次合并区（与 zh-CN.ts 合并区同批，en 覆写）──

  // 批次：components
  'components.pageTitleBar.themeToDark': "Switch to dark theme",
  'components.pageTitleBar.themeToLight': "Switch to light theme",
  'components.pageTitleBar.back': "Back",
  'components.pagePlaceholder.underConstruction': "Under construction — this page will be implemented in a later phase",
  'components.scheduleFields.defaultHint': "A SPEC will be created for this item and enter the pipeline. Execution time:",
  'components.scheduleFields.optionImmediate': "Run immediately after creation",
  'components.scheduleFields.optionScheduled': "Run at a scheduled time",
  'components.scheduleFields.optionManual': "Manual activation",
  'components.scheduleFields.manualPendingSuffix': ", set to pending activation (enters scheduling after manual activation)",
  'components.scheduleFields.scheduledAtSuffix': ", will run at {time}",
  'components.alertAdjudication.exec': "Execute",
  'components.alertAdjudication.confirmTitle': "Execute this adjudication?",
  'components.alertAdjudication.confirmFallbackDesc': "This action may not be recoverable automatically; please confirm",
  'components.alertAdjudication.okConfirm': "Confirm execution",
  'components.alertAdjudication.caveatNotMarked': "Alert not marked as handled (retry \"Mark handled\")",
  'components.alertAdjudication.caveatNotLogged': "Disposition log write failed (audit trail missing)",
  'components.alertAdjudication.caveatLogUnknown': "Log status unknown (backend response missing marked/disposition_logged receipt)",
  'components.alertAdjudication.executedBare': "Adjudication executed",
  'components.alertAdjudication.executedLogged': "Adjudication executed; disposition logged",
  'components.alertAdjudication.caveatWrap': "({caveats})",
  'components.alertAdjudication.stepSuffix': ": {steps}",
  'components.alertAdjudication.execFailed': "Adjudication failed; alert remains unhandled — adjust and retry",

  // 批次：projects
  'projects.index.placeholderTitle': "Projects",
  'projects.modeTag.fast': "Fast Mode",
  'projects.modeTag.full': "Full Mode",
  'projects.runCancel.title': "Terminate Run",
  'projects.runCancel.okText': "Confirm Termination",
  'projects.runCancel.cancelText': "Cancel",
  'projects.runCancel.successAccepted': "Cancellation request accepted; the run will be terminated on the next poll",
  'projects.runCancel.pendingInfo': "A cancellation request is already pending; please wait for it to be accepted",
  'projects.runCancel.failed': "Cancel failed: {msg}",
  'projects.runCancel.willTerminate': "About to terminate run",
  'projects.runCancel.reasonLabel': "Termination reason (optional):",
  'projects.runCancel.reasonPlaceholder': "e.g. burning tokens on a stalled loop, off in the wrong direction…",
  'projects.runRecord.title': "Run Record · {runId}",
  'projects.progressTile.done': "Completed ",
  'projects.architecture.loadFailed': "Load failed: {msg}",
  'projects.architecture.acceptedGenerating': "Accepted; the architecture diagram is being generated",
  'projects.architecture.generatingBusy': "Architecture diagram generation is already in progress; please wait",
  'projects.architecture.triggerFailed': "Trigger failed: {msg}",
  'projects.architecture.readFailedTitle': "Progress read failed; auto refresh has stopped",
  'projects.architecture.readFailedDesc': "{err} (click \"Retry Read\", or switch away from this tab and back to trigger a re-read)",
  'projects.architecture.retryRead': "Retry Read",
  'projects.architecture.refresh': "Refresh Architecture Diagram",
  'projects.architecture.noneTitle': "No architecture diagram yet",
  'projects.architecture.noneDesc': "This launches a headless harness generation process (with the vendored floorplan skill, resolved from the agent.harness config: claude or dsh) to scan and read this project's code and produce an interactive high-level runtime architecture diagram (3–9 top-level subsystems / call & data flows / external dependencies, labeled in Chinese). Generation never runs automatically and can be triggered manually at any time; it takes from a few to a dozen minutes.",
  'projects.architecture.generatingTitle': "Generating architecture diagram…",
  'projects.architecture.generatingDesc': "Reading the project code and drawing the architecture diagram; this usually takes from a few to a dozen minutes. You can leave this page and come back later to check.",
  'projects.architecture.failedTitle': "Architecture diagram generation failed",
  'projects.architecture.failedFallback': "Unknown cause; retry or check the server logs",
  'projects.architecture.iframeTitle': "Project architecture diagram",
  'projects.codeFix.phase.idle': "Idle",
  'projects.codeFix.phase.selecting': "Selecting batch",
  'projects.codeFix.phase.fixing': "Fixing",
  'projects.codeFix.phase.regressing': "Running full regression",
  'projects.codeFix.phase.retrying': "Retrying after regression failure",
  'projects.codeFix.phase.merging': "Merging back to main tree",
  'projects.codeFix.phase.blocked': "Blocked",
  'projects.codeFix.phase.failed': "Failed",
  'projects.codeFix.itemStatus.fixed': "Fixed",
  'projects.codeFix.itemStatus.skipped': "Skipped",
  'projects.codeFix.batchDoneOf': "Handled {done}/{total} in this batch",
  'projects.codeFix.batchDone': "Handled {done} in this batch",
  'projects.codeFix.justFinished': "Just finished: {status}: {file}{title}",
  'projects.codeFix.startupWaited': "{stage} (waited {minutes} min)",
  'projects.codeFix.reasonPrefix': "Reason: {reason}",
  'projects.codeFix.readFailedPolling': "Progress read failed; polling has stopped",
  'projects.codeFix.titleWaiting': "Auto-fix code issues (batch {batch} · waiting for the next round)",
  'projects.codeFix.titlePhase': "Auto-fix code issues (batch {batch} · {phase})",
  'projects.codeFix.howToHandle': "How to handle: {guidance}",
  'projects.home.kind.markdown': "Markdown",
  'projects.home.kind.image': "Image",
  'projects.home.kind.code': "Code",
  'projects.home.kind.text': "Text",
  'projects.home.dirLoadNotFound': "Path not found; it may have been moved or deleted",
  'projects.home.dirLoadFailed': "Load failed",
  'projects.home.pathMissing': "Path not found",
  'projects.home.fileLoadFailed': "Failed to load file content",
  'projects.home.col.name': "Name",
  'projects.home.authorFallback': "Unknown",
  'projects.home.linesAndSize': "{lines} lines · {size}",
  'projects.home.download': "Download",
  'projects.adminInvoke.templateCheckProgress': "Check the progress of {spec}",
  'projects.adminInvoke.templateInvestigate': "Investigate what went wrong with {spec} and propose a solution",
  'projects.adminInvoke.stalledWarning': "The disposition has produced no output for a long time and has not reached a terminal state; it may have been interrupted and can be re-invoked",
  'projects.adminInvoke.promptRequired': "Please enter the prompt for the Admin",
  'projects.adminInvoke.conflictInfo': "An Admin disposition is already in progress; locating its output",
  'projects.adminInvoke.invokeFailed': "Invoke failed: {msg}",
  'projects.adminInvoke.title': "{spec} · Invoke Admin",
  'projects.adminInvoke.eventCount': "{n} events",
  'projects.adminInvoke.waitingText': "Administrator invoked",
  'projects.adminInvoke.stalledAlert': "The disposition has had no output for over {minutes} minutes and has not reached a terminal state, so it may have been interrupted: re-invoke it, or close the dialog and check back later",
  'projects.adminInvoke.locateTimeout': "Timed out locating the disposition output (over {seconds} seconds): the daemon may not have accepted this request; re-invoke it or retry later",
  'projects.adminInvoke.queuedWaiting': "The Administrator is processing the previous disposition; this request is queued (serial processing, it will start automatically once that finishes)…",
  'projects.adminInvoke.waitingStart': "Waiting for the Administrator to start the disposition…",
  'projects.adminInvoke.promptHint': "Enter the prompt for the Admin below (frequently used questions are available in the dropdown); once invoked, the Administrator's disposition output will be streamed here live.",
  'projects.adminInvoke.promptPlaceholder': "Enter a prompt; press Enter to invoke",
  'projects.adminInvoke.inProgress': "Disposition in progress",
  'projects.adminInvoke.invoke': "Invoke Disposition",

  // ── settings 页壳收口（3.3）──
  'settings.index.projectsLoadFailed': "Failed to load the project list; project scope is unavailable: {msg}",
  'settings.index.discardConfirm': "Unsaved changes on the current tab will be discarded when you switch. Continue?",
  'settings.index.saveFailed': "Save failed: {msg}",
  'settings.index.saveSuccess': "Saved",
  'settings.index.savedButRefreshFailed': "Saved, but refreshing the configuration failed; switch the scope or refresh the page to see the latest values",
  'settings.index.quickAssignApplied': "Configuration saved; takes effect after the daemon restarts (quick assignment wrote {count} targets)",
  'settings.index.fixValidationFirst': "Fix the form validation errors first",
  'settings.index.nothingToSave': "No changes to save",
  'settings.index.selfEvo.collectError': "Failed to collect the self-evolution configuration; save aborted. Please try again later",
  'settings.index.selfEvo.notReady': "The self-evolution panel is not ready; cannot collect this section's configuration. Please try again later",
  'settings.index.arbiter.collectError': "Failed to collect the arbiter configuration; save aborted. Please try again later",
  'settings.index.arbiter.notReady': "The arbiter panel is not ready; cannot collect the configuration. Please try again later",
  'settings.index.configMissing': "{scope, select, project {No configuration file for this project yet; the form shows defaults} other {The user-level configuration file does not exist; the form shows defaults}}",
  'settings.index.configPath': " (resolved path: {path})",
  'settings.index.scopeLabel': "Scope:",
  'settings.index.scopeUser': "User level",
  'settings.index.scopeProject': "Project: {name}",

  // ── command-center 页壳收口（3.4）──
  'commandCenter.index.allProjects': "All projects",
  'commandCenter.index.tabOrg': "Org Overview",
  'commandCenter.index.tabPipeline': "Delivery Pipeline",
  'commandCenter.index.tabLedger': "Execution Ledger",

  // ── help 页壳收口（3.4）──
  'help.index.docsListLoadFailed': "Failed to load the document list",
  'help.index.docLoadFailed': "Failed to load the document",
  'help.index.empty': "No help documents yet",
  'help.index.contentEmpty': "Document content is empty",
  'help.index.docToc': "Document TOC",

  // ── activities 页壳收口（3.4）──
  'activities.index.alertsLoadFailed': "{actMsg}; failed to load alerts: {err}",
};

const enUS: Record<string, string> = { ...zhCN, ...enOverrides };

export default enUS;
