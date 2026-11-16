# 直派通道人类专属裁决越界拦截

## Why

`ADMIN_CHAIN_EXCLUDED_CHOICE_IDS`（core/dashboard/data/adjudication_choices.py:587-595，7 项人类拍板专属：abandon / force_advance / freeze_stop_loss / grant_env_exemption / raise_budget / revise_reproposal / skip_review_gate）目前只在升级链路径被复核（core/pm_engine/escalation_chain.py:1277-1301）。Administrator 的直派通道（admin_monitor 周期唤起）与自动执行通道（admin_auto_exec）不经过该复核，2026-11-12T14:08:51Z 已实际执行人类专属的 grant_env_exemption：落 disposition #eb0afd742714、写入 STATE `_env_exemptions`，并触发 2 次 Arbiter 升级（越界事实两源留痕：.fenix/admin_alerts.json #eb0afd742714 与 Arbiter 调查报告 b84d7f10daa1。注：STATE 内该豁免条目其后已被人工处置清理，2026-11-16 复核时 `_env_exemptions` 均已归 null、不在盘——历史越界事实仍由 alerts/narrative 留痕成立）。2026-10-26T05:07:32Z 有同效应先例。

三条 agent 驱动通道共用同一执行机器 `core/admin_choice_exec.execute_choice_for_disposition`（admin_monitor.py:9221 / admin_auto_exec.py:582 / escalation_chain.py:1405），而人工 Dashboard 路径（core/dashboard/routes/alert_routes.py:640）直接调用 `execute_adjudication_choice`、不经过该函数。因此在该函数入口加一道边界门，成本最低且不会误伤人类拍板。

## What Changes

- `core/dashboard/data/adjudication_choices.py`：新增 `is_human_exclusive_choice(choice_id)` 助手（对 `ADMIN_CHAIN_EXCLUDED_CHOICE_IDS` 做 strip 归一化成员判断），并把该常量的注释口径从「链上 Admin 拍板面排除集」扩为「全部 agent 驱动通道共用的执行排除集」。
- `core/admin_choice_exec.py`：`execute_choice_for_disposition` 在解析出 choice_id 后、调用 `execute_adjudication_choice` 之前统一复核；命中排除集即拒绝执行，返回 `{"ok": False, "skipped": True, "action": choice_id, "error": "choice 越界（人类拍板面专属）: <choice_id>，agent 通道拒绝执行"}` 并记 ERROR 日志。
- `core/admin_monitor.py`：直派消费侧识别该拒绝形态（skipped=True 且 error 含越界标记）时，为 disposition 记 `handoff_reason` 并跳过终态回写（信号保持 pending，交既有升级链/Arbiter 接管），与链路径 chain-handoff 同口径。
- 人工通道零改动：`core/dashboard/routes/alert_routes.py` 与 `execute_adjudication_choice` 默认行为不变。

## Capabilities

### New Capabilities

（无——本变更落在既有能力域）

### Modified Capabilities

- `adjudication-choices-registry`: 人类专属拍板面的执行边界从「仅升级链路径」收口为「全部 agent 驱动通道」；人工 Dashboard 裁决空间不变。

## Impact

- 代码：`core/dashboard/data/adjudication_choices.py`、`core/admin_choice_exec.py`、`core/admin_monitor.py` 三个文件；新增一个守卫测试文件。
- 行为：直派/自动执行遇到 7 项人类专属 choice 时不再执行、不再写 spec 状态，信号保持待处置并留 handoff 痕迹；链路径原有越界 handoff 先行，执行机器守卫作为第二层设防；人工 Dashboard 处置完全不变。
- 非目标：不改变排除集成员；不改提示词模板与 `{chain_choices}` 注入面；不追溯撤销历史遗留的 `_env_exemptions`（该条目已由人工处置清理、不在盘，无遗留需要本变更清理）。
