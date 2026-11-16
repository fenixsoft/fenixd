# 设计：warning_stale_triage 裁决桶注册

## 背景

注册表是「信号 → 可执行选项」的单源，也是告警 choices 快照、人工下拉合法集、链上 Admin 拍板面的共同来源。缺桶会让三者同时为空，信号只能在链上被判越界后转 Arbiter，形成「一条信号烧两条 agent run」的空转。

## 决策

### D1 以「注册桶」为唯一结构性出口

不新增旁路，也不放宽 `_admin_choice_allowlist` 的拒绝语义——缺桶的正解是补桶。补桶后 `choices_for`、告警落盘、alert-resolve 校验、链上白名单四处同时生效，符合既有泛化实现。

### D2 ack_triage 复用 ack_self_heal 的 action

新增执行器分支的收益不足：`ack_triage` 的语义与既有 `ack_self_heal` 完全一致（留痕并关闭本条信号、不触碰状态机）。因此 choice id 独立（便于统计与文案）、action 复用 `ack_self_heal`（admin_actions.py:3239 已有分支），执行器零改动。triage 结论通过 note 留痕于处置记录。

### D3 revise_scenario_reverify 按引用复用单源常量

`_REVISE_SCENARIO_REVERIFY` 已是模块级常量（adjudication_choices.py:108-140），跨桶一致性由 import 期 `_assert_registry_consistency` 钉死。任何字段漂移会在启动时失败，不会静默分叉。

### D4 归因文案区分两种空集

未注册信号与「已注册但选项被人类专属集全部过滤」都会产生空白名单，但根因不同：前者是注册缺口，后者是权限边界。`_admin_choice_allowlist` 改为返回可区分形态，越界文案分别写「信号未注册裁决桶」与「人类拍板面专属」。拒绝行为保持不变，不扩权。

### D5 不接自动闭环

该信号指向「需要人工 triage 判断是否真缺陷」，验证翻绿不等于 triage 完成。`core/alert_lifecycle.py` 的自动闭环条件保持不含该信号。

## 风险与权衡

- 误收口风险：`ack_triage` 可在无载荷情况下收口信号，存在「随手确认」风险；缓解是 desc 明确要求处置记录附 triage 结论，且问题复发会再次发信号（自限语义与 ack_self_heal 一致）。
- 存量告警不做批量改写：本信号存量记录因发射时注册表为空而未写 choices 键（键缺失形态），alert-resolve 校验对「键缺失/None」本就回退读注册表（alert_routes.py 既有回退逻辑，「显式空快照 [] 不回退」约定不受影响），注册后存量告警在人工裁决面即时获得新选项，无需重发。
