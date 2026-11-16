# 设计：直派通道人类专属裁决越界拦截

## 背景

人类专属拍板面已有单源名单，但复核只做在链的调用方。执行机器是三条 agent 通道的共同下游，把边界门下沉到执行机器可以让覆盖面从「链」扩到「全部 agent 通道」，且天然不影响人工 Dashboard。

## 决策

### D1 门放在 execute_choice_for_disposition，而不是 execute_adjudication_choice

`execute_adjudication_choice` 同时服务人工 alert-resolve（core/dashboard/routes/alert_routes.py:640），其默认语义必须保留人类拍板放行。把默认行为改掉会让「人类专属」变成「谁都不可执行」，直接与设计冲突。`execute_choice_for_disposition` 是 agent 侧专用入口，三个 agent 通道全部经过它，一处在位即全覆盖。

### D2 归因文案与链路径同源

拒绝文案沿用链路径的 `choice 越界（人类拍板面专属）: <choice_id>` 前缀，避免同一语义出现两套措辞，日志/告警检索可按同一 grep 命中。

### D3 复用既有 fail-closed 语义

返回 ok=false + skipped=true + error，与 fix-global-signal-choice-execution 建立的「执行失败不闭环」终态回写门天然兼容；不需要新增回写分支。

### D4 disposition 记 handoff_reason

直派路径没有链 item 可挂，故把越界原因写到 disposition 的 handoff_reason 字段（链路径已消费同名语义），让既有升级链/Arbiter 读侧能识别「该信号需人类拍板」而不是普通的执行失败。

## 风险与权衡

- 误伤风险：若未来出现「agent 应当可以执行某人类专属 choice」的新需求，必须显式从排除集移除并补测试，不能靠旁路绕过。
- 遗留豁免：本次修复不追溯撤销 2026-11-12 写入的 `_env_exemptions`，该项由人工确认（见 proposal 非目标）。
- 提示词层：模板缺 `{chain_choices}` 占位符是相邻独立问题，本变更不处理；执行机器守卫对「模型自行产出越界 choice」同样有效。
