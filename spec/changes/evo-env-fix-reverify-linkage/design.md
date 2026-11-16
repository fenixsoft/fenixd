## Context

2026-11-12 web-browser-client 实证：环境根治提交 0a30212 落地、处置链 17:09:02.637Z 以成功语义闭环（unfrozen=False），此后无任何组件触达 STATE，直到 60 分钟 blocked_stuck 阈值触发 admin run admin-web-browser-client-179419307（1038.43s/166 轮）才迁回 testing——修复后空等 56.74 分钟、blocked 总滞留 80.6 分钟。期间 manual_fixed_reverify 被拒（fenixd.log:10641，scoped-no-reverse）。同族形态 11-09 已在 single-app-realdevice-retest 两度出现（todo 11-09 节两条在案）。

## 关键代码事实（已回源核实）

- 动作体已存在：reset_verification（core/dashboard/data/admin_actions.py:1828）本身即「剥冻结 + 按 resolve_env_blocked_reset_path 推进（BLOCKED→TESTING 直通道重验，否则 BLOCKED→READY）」。
- 复位直通道已存在：_reset_env_blocked_after_disposition（core/admin_monitor.py:8868-8989，调用点 :8509-8516，仅处置终态触发一次）。
- 缺口一：链上闭环 _close_chain_success（core/pm_engine/escalation_chain.py:1502-1522）只对 frozen spec 解冻，对 blocked 无迁移且不挂直通道。
- 缺口二：17:04:04 复位尝试被处置在飞互斥跳过（fenixd.log:10571）后无重评机制。
- 缺口三：blocked_stuck 未注册选项桶（core/dashboard/data/adjudication_choices.py:338-340 仅 manual-intervention 与 verify_env_blocked 两桶）、resolve_choice 桶外拒绝（:741/:775）、VERIFY_CHAIN_SIGNAL_TYPES 白名单（core/dashboard/data/admin_actions.py:1703-1712）不含 blocked_stuck/verify_env_blocked。

## 方案

三处接线复用既有能力，不新建动作语义：①链上闭环命中「环境阻塞族 + spec=blocked + 处置已修复」三重前提时调用与直通道等价的复位；②互斥跳过写待重评标记（spec 维度），下一巡检周期消费；③桶与白名单同源补全，提示词词表按桶生成实现前置防越界。回执句柄挂处置终态回写与 chain-closed 两点，判定窗建议 10 分钟（覆盖巡检周期）。

## Risks

- daemon 常驻面改动需重启生效；判定窗过短会误报（与巡检周期耦合）。
- 词表收窄改变 admin 产出分布，须与解析面同源防新形态越界。
- 洗白门禁语义不变：env 失败场景仍不得判 verified，本联动只加快重验到达，不改变裁决标准。