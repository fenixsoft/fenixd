<!-- knowledge: capability=disposition-reverify-linkage rev=1 sources=spec/changes/evo-env-fix-reverify-linkage -->

# 处置闭环与重验直通道联动（环境阻塞族）

环境阻塞族信号的处置闭环自动接续既有复位直通道完成 blocked→testing 迁移与重验派发；处置回执以可核验落地为成功语义的唯一依据。

## 规则

- 环境阻塞族信号（`verify_env_blocked`、`verify_env_inconclusive`、`blocked_stuck`）的处置收尾与「处置成功链闭环」事件，复用 admin_monitor 既有复位直通道（transition_gate(testing) + 清 error + 入队 verifier）完成 blocked→testing 迁移与重验派发，不新建动作语义。
- 迁移三重前提：信号属环境阻塞族 ∧ spec 处于 blocked ∧ 处置结果为已修复语义——任一不满足即不迁移（既有行为不变），不得把产品缺陷误迁移回 testing；链上闭环回执的 unfrozen 语义对 frozen spec 保持既有行为不变。
- 复位因处置在飞互斥被跳过时，登记该 spec 维度的待重评标记，并在互斥解除后的下一巡检周期重评消费，标记消费后清除；环境修复后的重验恢复不依赖 blocked_stuck 超时阈值兜底。
- 「闭环 / 复位 / 入队 verifier」类处置动作写可核验回执句柄（预期 spec 终态、预期 run 类型、判定时间窗；处置终态回写与 chain-closed 两个写点），并在判定窗内核验 STATE 迁移或对应类型 run 派发落地；判定窗缺省 10 分钟（覆盖巡检周期）。
- 判定窗内落地则成功语义成立，回执记成功并携带句柄（预期终态与判定窗），供 dashboard 与处置链对账；窗内未落地则发升级告警（处置声称与落地不符）、处置记录标记无效、不闭环告警链、不记成功语义。
- blocked_stuck 注册单选项裁决桶（选项集 = manual_fixed_reverify，语义为解冻→testing→入队重验），并按注册桶同源纳入 VERIFY_CHAIN_SIGNAL_TYPES 白名单（verify_env_blocked 一并补全）；manual_fixed_reverify 经桶内精确匹配放行执行，桶外信号仍走既有解析拒绝面。
- admin 链提示词的 spec 作用域选项词表按信号桶收窄生成：未注册任何 spec 作用域选项桶的信号，其提示词不含该词表（前置防越界，替代事后拒绝）。

## 代码锚点

- 主实现：`core/pm_engine/escalation_chain.py`（链上闭环接续复位直通道与 chain-closed 回执句柄写点）
- 复位直通道与待重评标记/回执句柄状态文件 IO：`core/admin_monitor.py`（`_reset_env_blocked_after_disposition`、待重评标记单源写入口）
- 裁决选项桶注册：`core/dashboard/data/adjudication_choices.py`（blocked_stuck 桶）
- 白名单同源补全：`core/dashboard/data/admin_actions.py`（VERIFY_CHAIN_SIGNAL_TYPES）
- 守卫测试：`tests/test_env_fix_reverify_linkage.py`

## 溯源

- 2026-11-16 evo-env-fix-reverify-linkage（spec/changes/evo-env-fix-reverify-linkage/） — 新建本页：环境阻塞族处置闭环自动接续重验直通道、互斥跳过待重评周期消费、处置回执落地校验句柄、blocked_stuck 选项桶与白名单同源补全
