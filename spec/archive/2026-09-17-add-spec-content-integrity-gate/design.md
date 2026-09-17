# 设计：派发前内容完整性闸门

## Context

fenixd 派发路径（`core/pm_engine/dispatch.py`）在 implementer / fast-track 派发前已有「次数」维度的闸门：`_check_impl_budget_exhausted`（core/pm_engine/budget.py:289），预算耗尽时置 blocked + human-escalation 告警。但没有「内容」维度的闸门——`_seed_spec`（core/worktree_manager.py:314）对空目录 `copytree` 后 git commit 报 "nothing to commit" 只记 WARNING 继续，实现 agent 拿到空目录只能拒绝产出，直到烧满预算才被拦。

scheduling-showcase 夹具实证该缺口：c-sched-set / c-sched-clear 两条空占位 spec 各盲跑 6 轮（共 12 个 implementer run）才被 `impl_budget_exhausted` 冻结。

## Goals / Non-Goals

- **Goals**：在任何真实项目里，空 spec 第一轮派发前即被拦下并冻结告警，不再烧预算；告警接入生命周期自动闭环。
- **Non-Goals**：不修改 `_seed_spec` 的 non-fatal 语义；不改 verifier 分支（verifier 跑在已有实现上）；不引入配置开关；不复用 verifier 的 tsc not found 缺依赖供给链（那是另一维度）。

## Decisions

### D1：闸门放在派发前，而非 seeding 层

**选择**：在 dispatch.py 的 implementer / fast-track 两分支，预算闸门检查处并列新增校验。

**理由**：seeding 失败是 non-fatal 设计，无法区分「合法空 spec」和「异常空 spec」，且 seeding 只在 worktree 内发生、不在派发资格把关链上。派发前是记忆验证过的「唯一可靠停靠点」（预算闸门正是如此）。校验离状态翻转最近，命中即得 blocked，不回落下一次派发。

### D2：实质内容四选一判定

**选择**：`proposal.md` / `design.md` / `tasks.md` / `specs/**/*.md` 任一存在即视为有内容。

**理由**：宽松到覆盖全部合法形态（早期 draft 可能只有 proposal，成熟 spec 有全套），同时拦得住「空目录 / 只有无关文件」的异常。fenixd 自身 54 个 spec 全部含 tasks.md+proposal.md，零误伤。

**备选**（否决）：仅拦空目录——「有文件但非 spec 内容」漏网；tasks.md 硬性要件——误伤 proposal 起步的早期 spec。

### D3：读目录异常保守放行

**选择**：IO 异常记 WARNING 并返回「有内容」放行。

**理由**：闸门的目标是拦空 spec，不是卡死派发。权限/临时不可达下宁可放行让预算闸门兜底，也不把健康 spec 挡住。

### D4：复用冻结范式 + 告警闭环

**选择**：命中即 `update_spec(status=blocked, error=...)` + `_send_human_escalation_alert(signal_type="spec_content_missing", severity="major")`；在 `alert_lifecycle._SIGNAL_CONDITIONS` 注册 `spec_content_missing → spec_terminal_or_unblocked`。

**理由**：与预算闸门完全同构，复用成熟代码路径；接入现有闭环枚举后，spec 补内容解冻离开 blocked 即自动 resolve，无需人工清告警。

### D5：模块落点

**选择**：新文件 `core/pm_engine/spec_integrity.py` 承载 `spec_has_content` 纯函数与闸门封装，engine.py 加薄转发（与 `_budget._check_impl_budget_exhausted` 同型）。

**理由**：同层并列、职责清晰，未来若需按项目白名单扩展判定不污染 budget.py。

## Risks / Trade-offs

- [误伤健康 spec] → 判定宽松（四选一）+ IO 异常放行 + lint/TDD 单测覆盖正常形态。
- [闸门与预算闸门重复告警] → 命中即 blocked，预算闸门随后因「已是 blocked」幂等返回 True 不重复告警。
- [空 spec 无设计文件场景漏网] → specs 目录扫描 `**/*.md` 兜底，覆盖只有 specs/ 无 proposal/design/tasks 的形态。

## Migration Plan

纯新增防护，无数据迁移、无配置迁移。存量已冻结的空 spec（如夹具 c-sched-*）不受影响——本闸门只作用派发前，不回溯清理既有 blocked 状态。

## Open Questions

无——判定口径与处置方式已与需求确认一致。