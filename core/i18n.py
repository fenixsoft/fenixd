"""i18n.py — 消息目录单源（add-framework-i18n-zh-en 4.1 / design D5/D6）。

Dashboard API 展示型字符串与 CLI 人读提示**共用**的 zh/en 双语消息目录
（cli-message-i18n「消息目录跨车道共用」Requirement：MUST NOT 各自维护
第二份字典）。

边界（backend-message-i18n「展示型字符串经目录输出」Requirement）：
- 目录只收「前端直接渲染、后端组装下发」的展示型文本（error 字段、展示
  标签/描述）与 CLI 人读提示；
- 前端 kind→标签映射类静态文案（时间轴处置链事件标签、AGENT_LABEL、
  blockedPhaseMeta 等）属 dashboard-i18n 前端目录面，MUST NOT 进本目录；
- 内部运行日志、调试日志、落盘产物文件内容 MUST NOT 经目录改造（操作员
  面，保持中文现状）。

用法：
    from core.i18n import t, resolve_locale
    t("error.project_not_found", "en", project="proj-a")
    locale = resolve_locale(request.headers.get("Accept-Language"))

键命名 `<域>.<语义>`：``error.*``（Dashboard API 展示错误）、``cli.*``
（fenix_cli.py 人读提示）、``label.*``（后端下发展示标签）。
"""

from __future__ import annotations

# 值域白名单（cli-message-i18n / backend-message-i18n：zh/en 两档，白名单外
# 一律回退 zh）。
VALID_LOCALES = ("zh", "en")

# ── 消息目录（键 → {zh, en}）─────────────────────────────────────────
# zh 文本与现状存量文案保持一致（zh 用户零感知迁移）；en 为对照翻译。
# en 缺键运行时回退 zh（t() 内实现）；新增键 MUST 同时给 zh 与 en（与前端
# 目录 spread 底座不同——本目录键集小、逐键双语即可，无 spread 机制）。
# 插值用 str.format 占位（{name} 形态），调用方经 **kw 传入。
CATALOG: dict[str, dict[str, str]] = {
    # ── Dashboard API 展示错误（core/dashboard/routes 展开面）──
    "error.project_not_found": {
        "zh": "项目不存在：{project}",
        "en": "Project not found: {project}",
    },
    "error.project_missing": {
        "zh": "缺少 project 参数",
        "en": "Missing 'project' parameter",
    },
    "error.project_missing_context": {
        "zh": "缺少 project 参数（{context}为项目级文件）",
        "en": "Missing 'project' parameter ({context} is a project-scoped file)",
    },
    "error.project_not_monitored": {
        "zh": "项目不存在或未监控",
        "en": "Project not found or not monitored",
    },
    "error.spec_not_found": {
        "zh": "SPEC 不存在：{spec}",
        "en": "SPEC not found: {spec}",
    },
    "error.invalid_request": {
        "zh": "请求参数无效：{reason}",
        "en": "Invalid request: {reason}",
    },
    "error.invalid_run_id": {
        "zh": "无效的 run id",
        "en": "Invalid run id",
    },
    "error.config_load_failed": {
        "zh": "配置加载失败：{reason}",
        "en": "Failed to load config: {reason}",
    },
    # ── Dashboard API 展示错误（4.4：告警/审查/自进化/运行取消路由展开面）──
    # zh 文本与改造前字面量逐字一致（zh 用户零感知）；占位符经调用方 **kw 传入。
    "error.alert_already_handled": {
        "zh": "alert already handled（不重复执行动作）",
        "en": "Alert already handled (action not repeated)",
    },
    "error.alert_not_adjudicable": {
        "zh": "该告警不可人工裁决（signal_type={signal_type}，无合法 choice 集）："
        "知情/自愈类信号请用「标记已处理」完成处置",
        "en": "This alert is not manually adjudicable (signal_type={signal_type}, "
        "no legal choice set): for informational/self-heal signals use "
        "'Mark handled' to complete the disposition",
    },
    "error.invalid_choice_id": {
        "zh": "非法 choice_id '{choice_id}'，该信号合法选项：{legal}",
        "en": "Invalid choice_id '{choice_id}'; legal choices for this signal: {legal}",
    },
    "error.adjudication_exec_failed": {
        "zh": "动作执行异常（告警保持未处理，可重试裁决）",
        "en": "Action execution error (alert remains unhandled; the adjudication can be retried)",
    },
    "error.adjudication_not_ok": {
        "zh": "{detail}（告警保持未处理，可调整后重试）",
        "en": "{detail} (alert remains unhandled; adjust and retry)",
    },
    "error.handled_mark_failed": {
        "zh": "动作已执行成功，但 handled 标记写入失败"
        "（告警仍显示未处理；请勿直接重试裁决，以免动作重复执行）",
        "en": "The action executed successfully, but writing the handled flag failed "
        "(the alert still shows unhandled; do not retry the adjudication directly, "
        "or the action may run twice)",
    },
    "error.code_review_scope_invalid": {
        "zh": "非法 scope（应为 full 或 window）: {value}",
        "en": "Invalid scope (expected full or window): {value}",
    },
    "error.code_review_running": {
        "zh": "已有审查在进行中",
        "en": "A review is already in progress",
    },
    "error.code_review_backlog": {
        "zh": "台账仍有 {count} 条 open（超过确认阈值 {threshold}），"
        "上一轮全仓审查可能未消化完。再次触发并携带 confirm=true "
        "以确认开始新一轮全仓审查",
        "en": "The ledger still has {count} open items (above the confirm threshold "
        "{threshold}); the previous full-repo review may not have been fully "
        "consumed. Trigger again with confirm=true to confirm starting a new "
        "full-repo review",
    },
    "error.code_review_ack_pending": {
        "zh": "审查已受理，正在启动（文件收集/排队中），请稍候",
        "en": "Review accepted and starting (file collection/queuing); please wait",
    },
    "error.code_review_request_pending": {
        "zh": "已有未消费的审查触发请求（请稍后重试）",
        "en": "An unconsumed review trigger request already exists (retry later)",
    },
    "error.code_review_trigger_failed": {
        "zh": "审查触发信号写入失败",
        "en": "Failed to write the review trigger signal",
    },
    "error.code_fix_trigger_failed": {
        "zh": "修复触发信号写入失败",
        "en": "Failed to write the fix trigger signal",
    },
    "error.code_fix_request_pending": {
        "zh": "已有未消费的修复触发请求（请稍后重试）",
        "en": "An unconsumed fix trigger request already exists (retry later)",
    },
    "error.item_ids_not_array": {
        "zh": "item_ids 必须为字符串数组",
        "en": "item_ids must be an array of strings",
    },
    "error.item_ids_empty": {
        "zh": "item_ids 不能为空",
        "en": "item_ids must not be empty",
    },
    "error.fix_spec_failed": {
        "zh": "生成修复 SPEC 失败（详见服务端日志）",
        "en": "Failed to generate the fix SPEC (see server logs)",
    },
    "error.item_status_invalid": {
        "zh": "status 仅支持 open/ignored（人工可置状态）: {value}",
        "en": "status only supports open/ignored (manually settable): {value}",
    },
    "error.item_status_failed": {
        "zh": "状态流转失败（详见服务端日志）",
        "en": "Status transition failed (see server logs)",
    },
    "error.cancel_write_failed": {
        "zh": "写入取消请求失败",
        "en": "Failed to write the cancel request",
    },
    "error.cancel_request_pending": {
        "zh": "已有进行中的取消请求，请等待受理",
        "en": "A cancel request is already in progress; wait for it to be accepted",
    },
    "error.cancel_daemon_unmanaged": {
        "zh": "本项目 daemon 未受 supervisor 托管，取消信号不会被消费",
        "en": "This project's daemon is not managed by the supervisor; "
        "the cancel signal will not be consumed",
    },
    "error.daemon_not_running": {
        "zh": "daemon 未运行，请先启动 daemon",
        "en": "The daemon is not running; start it first",
    },
    "error.evo_item_id_missing": {
        "zh": "缺少 item_id 参数",
        "en": "Missing 'item_id' parameter",
    },
    "error.evo_item_not_found": {
        "zh": "条目不存在: {item_id}",
        "en": "Item not found: {item_id}",
    },
    "error.evo_doc_missing": {
        "zh": "缺少 doc 参数（proposal|design|tasks|spec）",
        "en": "Missing 'doc' parameter (proposal|design|tasks|spec)",
    },
    "error.evo_doc_invalid": {
        "zh": "非法 doc 参数（应为 proposal|design|tasks|spec）: {doc}",
        "en": "Invalid doc parameter (expected proposal|design|tasks|spec): {doc}",
    },
    "error.evo_accept_thread_failed": {
        "zh": "后台接受任务线程启动失败，请重试",
        "en": "Failed to start the background accept task thread; please retry",
    },
    "error.evo_start_after_invalid": {
        "zh": "start_after 非法（应为 UTC ISO8601 / manual）: {value}",
        "en": "Invalid start_after (expected UTC ISO8601 / manual): {value}",
    },
    "error.evo_no_active_accept": {
        "zh": "该条目没有进行中或已完成的接受任务: {item_id}",
        "en": "No in-progress or completed accept task for this item: {item_id}",
    },
    "error.evo_accept_failed": {
        "zh": "接受失败（详见服务端日志）",
        "en": "Accept failed (see server logs)",
    },
    "error.evo_reject_failed": {
        "zh": "拒绝失败（详见服务端日志）",
        "en": "Reject failed (see server logs)",
    },
    "error.evo_delete_failed": {
        "zh": "删除失败（详见服务端日志）",
        "en": "Delete failed (see server logs)",
    },
    # ── 后端下发展示标签（label.*：command_center 数据层分区名，前端直渲染）──
    # zh 与 core/dashboard/data/command_center.py ZONE_*/OTHER_ZONE 常量逐字
    # 一致（zh 用户零感知）；路由层按请求 Accept-Language 经 t() 映射改写
    # org/spec-runs 响应中的 zone 字段（zh 档原样透传，载荷结构零变化）。
    "label.zone.demand": {
        "zh": "需求线",
        "en": "Demand",
    },
    "label.zone.design": {
        "zh": "设计线",
        "en": "Design",
    },
    "label.zone.delivery": {
        "zh": "交付线",
        "en": "Delivery",
    },
    "label.zone.quality": {
        "zh": "质量线",
        "en": "Quality",
    },
    "label.zone.ops": {
        "zh": "运营线",
        "en": "Ops",
    },
    "label.zone.other": {
        "zh": "其他",
        "en": "Other",
    },
    # ── 手动触发回链结果文案（fenixd.py CODE_REVIEW_RESULT_MESSAGES /
    # CODE_FIX_RESULT_MESSAGES 的路由层翻译源）：daemon 写结果文件无请求上下文，
    # zh 原文落盘；GET result 路由按 Accept-Language 以 reason 查键改写 message。
    # zh 值与 fenixd.py 文案表逐字一致（tests/test_i18n.py 有同步守卫防漂移）。
    "label.reviewResult.started": {
        "zh": "审查已受理，正在启动（文件收集/排队中），请稍候",
        "en": "Review accepted and starting (collecting files / queued); please wait",
    },
    "label.reviewResult.already_running": {
        "zh": "已有审查在跑，请等当前审查完成后再试",
        "en": "A review is already running; wait for it to finish before retrying",
    },
    "label.reviewResult.daemon_not_running": {
        "zh": "daemon 未运行，审查信号无人消费已丢弃，请先启动 daemon",
        "en": "daemon is not running, so the review signal was dropped unconsumed; start the daemon first",
    },
    "label.reviewResult.daemon_unmanaged": {
        "zh": "daemon 未受 supervisor 托管，审查信号无人消费已丢弃",
        "en": "daemon is not supervised, so the review signal was dropped unconsumed",
    },
    "label.reviewResult.invalid_payload": {
        "zh": "审查触发信号内容非法，本次触发已丢弃",
        "en": "The review trigger signal was malformed and has been discarded",
    },
    "label.reviewResult.manifest_empty": {
        "zh": "没有可审查的文件（manifest 为空），本次审查未执行",
        "en": "No files to review (empty manifest); this review did not run",
    },
    "label.reviewResult.manifest_error": {
        "zh": "审查文件清单收集失败，本次审查未执行（详见 daemon 日志）",
        "en": "Failed to collect the review file list; this review did not run (see daemon logs)",
    },
    "label.reviewResult.submit_error": {
        "zh": "审查任务投递失败，本次审查未执行（详见 daemon 日志）",
        "en": "Failed to enqueue the review task; this review did not run (see daemon logs)",
    },
    "label.reviewResult.stale_created": {
        "zh": "审查触发信号已过期未执行（积压超过 1 小时，可能为停机残留），如仍需审查请重新发起",
        "en": "The review trigger expired unexecuted (backlog over 1 hour, likely left from downtime); trigger again if still needed",
    },
    "label.codeFixResult.dispatched": {
        "zh": "已投递一批自动修复，可在进度卡片查看进展",
        "en": "A fix batch has been dispatched; track progress on the progress card",
    },
    "label.codeFixResult.already_running": {
        "zh": "已有自动修复批次在跑，请等当前批完成后再试",
        "en": "A fix batch is already running; wait for it to finish before retrying",
    },
    "label.codeFixResult.no_open_items": {
        "zh": "当前没有待修复的 open 问题",
        "en": "There are no open issues to fix right now",
    },
    "label.codeFixResult.regression_contract_missing": {
        "zh": "回归契约缺失（verify.yaml 尚未起草），按 fail-closed 拒绝投递",
        "en": "Regression contract missing (verify.yaml not drafted yet); dispatch rejected fail-closed",
    },
    "label.codeFixResult.regression_section_missing": {
        "zh": "verify.yaml 缺 regression 段，按 fail-closed 拒绝投递",
        "en": "verify.yaml has no regression section; dispatch rejected fail-closed",
    },
    "label.codeFixResult.orchestrator_missing": {
        "zh": "自动修复编排器未装配，无法投递（daemon 初始化异常或版本过旧）",
        "en": "The auto-fix orchestrator is not assembled; cannot dispatch (daemon init error or outdated version)",
    },
    "label.codeFixResult.dispatch_prepare_error": {
        "zh": "自动修复投递前置异常，本批未投递（详见 daemon 日志）",
        "en": "Auto-fix dispatch hit a pre-dispatch error; nothing was dispatched (see daemon logs)",
    },
    "label.codeFixResult.dispatch_error": {
        "zh": "自动修复投递失败，本批未投递（详见 daemon 日志）",
        "en": "Auto-fix dispatch failed; nothing was dispatched (see daemon logs)",
    },
    "label.codeFixResult.dispatch_exception": {
        "zh": "自动修复消费异常，本批未投递（详见 daemon 日志）",
        "en": "Auto-fix consumption raised an exception; nothing was dispatched (see daemon logs)",
    },
    "label.codeFixResult.disabled": {
        "zh": "自动修复开关处于关闭状态",
        "en": "The auto-fix switch is turned off",
    },
    "label.codeFixResult.night_quiet_window": {
        "zh": "当前处于每日夜间静默窗（默认 03:00-03:15,04:15-04:45 多窗），窗内暂缓投递自动修复，窗末自动恢复",
        "en": "The nightly quiet window is active (default 03:00-03:15, 04:15-04:45); auto-fix dispatch is deferred and resumes automatically when the window ends",
    },
    "label.codeFixResult.stale_created": {
        "zh": "触发信号已过期未执行（积压超过 1 小时，可能为停机残留），如仍需修复请重新发起",
        "en": "The trigger expired unexecuted (backlog over 1 hour, likely left from downtime); trigger again if still needed",
    },
    "label.codeFixResult.invalid_payload": {
        "zh": "触发信号内容非法，本次触发已丢弃",
        "en": "The trigger signal was malformed and has been discarded",
    },
    "label.codeFixResult.daemon_not_running": {
        "zh": "daemon 未在托管运行，信号无人消费（可能为停机窗口残留），如仍需修复请重新发起",
        "en": "daemon is not running supervised, so the signal went unconsumed (possibly left from downtime); trigger again if still needed",
    },
    "label.codeFixResult.daemon_unmanaged": {
        "zh": "daemon 未受 supervisor 托管，文件信号无人消费，如仍需修复请重新发起",
        "en": "daemon is not supervised, so the file signal went unconsumed; trigger again if still needed",
    },
    # regression 车道覆写两条（REGRESSION_FIX_RESULT_MESSAGES 展开表外的自有文案）
    "label.regressionFixResult.dispatched": {
        "zh": "已把回归问题转入修复台账并投递一批自动修复，可在质量页签进度卡片查看进展",
        "en": "Regression issues were moved to the fix ledger and a fix batch has been dispatched; track progress on the Quality tab's progress card",
    },
    "label.regressionFixResult.snapshot_missing": {
        "zh": "最近一次回归快照缺失或不可解析，无法定位回归问题（请先执行一次全量回归，或稍后重试）",
        "en": "The latest regression snapshot is missing or unparseable, so the regression issues cannot be located (run a full regression first, or retry later)",
    },
    # regression autodraft 回包文案（regression_routes.py _api_regression_autodraft_post）
    "label.regressionAutodraft.skipped": {
        "zh": "regression 段已配置，无需生成。如需调整请在「项目简介」面板编辑 verify.yaml。",
        "en": "The regression section is already configured; nothing to generate. Edit verify.yaml in the Project profile panel if needed.",
    },
    "label.regressionAutodraft.successNew": {
        "zh": "已生成 regression 段并写入 .fenix/verify.yaml",
        "en": "Generated the regression section and wrote it to .fenix/verify.yaml",
    },
    "label.regressionAutodraft.successFull": {
        "zh": "已起草验证契约（含 regression 段）并写入 .fenix/verify.yaml",
        "en": "Drafted the verify contract (with regression section) and wrote it to .fenix/verify.yaml",
    },
    "label.regressionAutodraft.noTestSystem": {
        "zh": "项目无可用测试体系，未臆造回归命令（周期回归保持未配置）。",
        "en": "No usable test system in this project; no regression command was invented (scheduled regression stays unconfigured).",
    },
    # ── CLI 人读提示（bin/fenix_cli.py）──
    "cli.error.not_project": {
        "zh": "错误：{path} 不是 Fenix 项目目录（缺少 .fenix/STATE.md）",
        "en": "Error: {path} is not a Fenix project directory (missing .fenix/STATE.md)",
    },
    "cli.promote.contract_missing_next_status": {
        "zh": "✗ 晋升失败：promote_drafted 返回缺少 next_status 分流结论（契约破坏），"
        "MUST NOT 回退 ready 绕过评审门禁，请人工核查",
        "en": "✗ Promotion failed: promote_drafted returned no next_status verdict "
        "(contract violation); MUST NOT fall back to ready to bypass the review "
        "gate — manual inspection required",
    },
    "cli.promote.invalid_next_status": {
        "zh": "✗ 晋升失败：promote_drafted 返回非法 next_status={value!r}"
        "（契约破坏，合法值 ready/reviewing），MUST NOT 执行未知转移，"
        "请人工核查",
        "en": "✗ Promotion failed: promote_drafted returned invalid "
        "next_status={value!r} (contract violation; valid values are "
        "ready/reviewing). MUST NOT apply an unknown transition — manual "
        "inspection required",
    },
    "cli.promote.transition_rejected": {
        "zh": "✗ 状态转移被拒（可能已被并发转移），请核查 STATE.md 当前状态",
        "en": "✗ Transition rejected (possibly applied concurrently); inspect the "
        "current status in STATE.md",
    },
    "cli.promote.success_reviewing": {
        "zh": "✓ SPEC「{spec}」已晋升 reviewing（待方案评审），等待评审 run",
        "en": "✓ SPEC '{spec}' promoted to reviewing (pending design review); "
        "waiting for the review run",
    },
    "cli.promote.success_ready": {
        "zh": "✓ SPEC「{spec}」已晋升 ready，等待调度",
        "en": "✓ SPEC '{spec}' promoted to ready; waiting for dispatch",
    },
    "cli.promote.rejected": {
        "zh": "✗ 晋升被拒绝：{reason}",
        "en": "✗ Promotion rejected: {reason}",
    },
    "cli.promote.lint_failed": {
        "zh": "✗ 晋升 lint 未通过：",
        "en": "✗ Promotion lint did not pass:",
    },
    "cli.promote.failed": {
        "zh": "✗ 晋升失败",
        "en": "✗ Promotion failed",
    },
    "cli.review.not_found": {
        "zh": "✗ SPEC「{spec}」不存在于 STATE.md",
        "en": "✗ SPEC '{spec}' does not exist in STATE.md",
    },
    "cli.review.success": {
        "zh": "✓ SPEC「{spec}」已重新进入评审（reviewing），等待评审 run",
        "en": "✓ SPEC '{spec}' re-entered review (reviewing); waiting for the "
        "review run",
    },
    "cli.review.rejected": {
        "zh": "✗ 重新评审被拒绝：{reason}",
        "en": "✗ Re-review rejected: {reason}",
    },
    "cli.activate.success_kick_failed": {
        "zh": "✓ SPEC「{spec}」已激活（start_after manual → null），"
        "但即时唤醒信号写入失败，将由下次扫描（缺省 ≤30 分钟）派发",
        "en": "✓ SPEC '{spec}' activated (start_after manual → null), but the "
        "instant wake-up signal write failed; dispatch waits for the next scan "
        "(default ≤30 min)",
    },
    "cli.activate.success": {
        "zh": "✓ SPEC「{spec}」已激活，立即进入调度（start_after manual → null）",
        "en": "✓ SPEC '{spec}' activated and entering dispatch now "
        "(start_after manual → null)",
    },
    "cli.activate.not_found": {
        "zh": "SPEC「{spec}」不存在于 STATE.md",
        "en": "SPEC '{spec}' does not exist in STATE.md",
    },
    "cli.activate.terminal": {
        "zh": "终态 SPEC「{spec}」不可激活",
        "en": "SPEC '{spec}' is in a terminal state and cannot be activated",
    },
    "cli.activate.unknown_reason": {
        "zh": "未知原因",
        "en": "Unknown reason",
    },
    "cli.activate.rejected": {
        "zh": "✗ 激活被拒绝：{reason}",
        "en": "✗ Activation rejected: {reason}",
    },
    "cli.reflow.success": {
        "zh": "✓ SPEC「{spec}」已回炉复位为 ready{gap_note}，"
        "daemon 将重新派发实现者承接剩余任务",
        "en": "✓ SPEC '{spec}' reset to ready{gap_note}; the daemon will "
        "re-dispatch an implementer for the remaining tasks",
    },
    "cli.reflow.gap_note": {
        "zh": "（缺口 {count} 项）",
        "en": " ({count} gap tasks)",
    },
    "cli.reflow.rejected": {
        "zh": "✗ 回炉被拒绝：{reason}",
        "en": "✗ Reflow rejected: {reason}",
    },
    "cli.exec.failed": {
        "zh": "✗ 命令执行失败：{exc_type}: {exc}",
        "en": "✗ Command failed: {exc_type}: {exc}",
    },
}


def t(key: str, locale: str = "zh", **kw: object) -> str:
    """查目录取展示文本（backend/cli 两车道共用单源）。

    - 未知键原样返回键名（backend-message-i18n「目录外未知键 SHALL 原样返回
      键本身以便暴露遗漏」）；
    - en 查询目录内仅存在 zh 文本的键时回退返回 zh 文本；
    - **kw 经 str.format 插值。
    """
    entry = CATALOG.get(key)
    if entry is None:
        return key
    if locale == "en":
        text = entry.get("en") or entry["zh"]
    else:
        text = entry["zh"]
    if kw:
        try:
            return text.format(**kw)
        except (KeyError, IndexError, ValueError):
            # 插值键不匹配：按缺参渲染降级（占位符原样保留），不炸调用链
            return text
    return text


def resolve_locale(accept_language: str | None) -> str:
    """按请求 Accept-Language 头解析展示语言（backend-message-i18n）。

    逗号分隔 q 值前缀匹配白名单 zh/en（``zh-CN``/``en-US`` 等带地区变体按
    前缀命中）；无头、无法解析或白名单外的值一律回退 ``zh``。
    """
    if not accept_language:
        return "zh"
    parsed: list[tuple[float, int, str]] = []
    for index, part in enumerate(accept_language.split(",")):
        seg = part.strip()
        if not seg:
            continue
        pieces = seg.split(";")
        tag = pieces[0].strip().lower()
        q = 1.0
        for param in pieces[1:]:
            param = param.strip()
            if param.startswith("q="):
                try:
                    q = float(param[2:])
                except ValueError:
                    q = 0.0
        if tag:
            parsed.append((q, index, tag))
    if not parsed:
        return "zh"
    # q 值降序、同 q 保持出现序（HTTP 偏好序）；取第一个白名单命中
    parsed.sort(key=lambda item: (-item[0], item[1]))
    for _q, _i, tag in parsed:
        if tag.startswith("zh"):
            return "zh"
        if tag.startswith("en"):
            return "en"
    return "zh"
