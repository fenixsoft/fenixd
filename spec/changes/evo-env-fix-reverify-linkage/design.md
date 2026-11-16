## Context

2026-11-11（UTC）cloud-phone 实例 web-browser-client 实证：环境根治提交 0a30212 落地（+0800 11-12 01:07）、处置链 17:09:02.637Z 以成功语义闭环（unfrozen=False），此后无任何组件触达 STATE，直到 60 分钟 blocked_stuck 阈值触发 admin run admin-web-browser-client-1794419307（1038.43s/166 轮）才迁回 testing——修复后空等 56.74 分钟、blocked 总滞留 80.6 分钟。期间 manual_fixed_reverify 被拒（scoped-no-reverse）。以上均在 cloud-phone 实例日志 /root/cloud-phone/.fenix/logs/fenixd.log 逐条在案：处置链闭环 :10582、其前 17:04:04 复位互斥跳过 :10571、distress :10606、admin run 成本与 choice 拒绝 :10636-10641。同族形态 11-09 已在 single-app-realdevice-retest 两度出现（todo 11-09 节两条在案；同日志 10:16:16Z 复位互斥跳过在案）。

## 关键代码事实（已回源核实）

- 动作体已存在：reset_verification（core/dashboard/data/admin_actions.py:1848）本身即「剥冻结 + 按 resolve_env_blocked_reset_path 推进（BLOCKED→TESTING 直通道重验，否则 BLOCKED→READY）」。
- 复位直通道已存在：_reset_env_blocked_after_disposition（core/admin_monitor.py:9094 起，消费点 :8745，仅处置终态触发一次；处置在飞互斥跳过分支 :9157-9163）。
- 缺口一：链上闭环 _close_chain_success（core/pm_engine/escalation_chain.py:1736-1786，链驱动调用点 :1355）只对 frozen spec 解冻，对 blocked 无迁移且不挂直通道。
- 缺口二：17:04:04 复位尝试被处置在飞互斥跳过（cloud-phone 实例日志 :10571）后无重评机制。
- 缺口三：blocked_stuck 未注册选项桶（core/dashboard/data/adjudication_choices.py:332-345 区域仅 manual-intervention 与 verify_env_blocked 两桶，选项集均为单选项 _REVISE_SCENARIO_REVERIFY、不含 manual_fixed_reverify）、resolve_choice 桶外拒绝（:741/:775）、VERIFY_CHAIN_SIGNAL_TYPES 白名单（core/dashboard/data/admin_actions.py:1723-1733）不含 blocked_stuck/verify_env_blocked。
- 行号注：以上 core/ 行号以 2026-11-16 fenixd HEAD 复核；事件日志行号属 cloud-phone 实例（/root/cloud-phone/.fenix/logs/fenixd.log），与框架仓日志无涉，引用时须注明实例。

## 方案

三处接线复用既有能力，不新建动作语义：①链上闭环命中「环境阻塞族 + spec=blocked + 处置已修复」三重前提时调用与直通道等价的复位；②互斥跳过写待重评标记（spec 维度），下一巡检周期消费；③桶与白名单同源补全，提示词词表按桶生成实现前置防越界。回执句柄挂处置终态回写与 chain-closed 两点，判定窗建议 10 分钟（覆盖巡检周期）。

## Risks

- daemon 常驻面改动需重启生效；判定窗过短会误报（与巡检周期耦合）。
- 词表收窄改变 admin 产出分布，须与解析面同源防新形态越界。
- 洗白门禁语义不变：env 失败场景仍不得判 verified，本联动只加快重验到达，不改变裁决标准。