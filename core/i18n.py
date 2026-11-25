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
