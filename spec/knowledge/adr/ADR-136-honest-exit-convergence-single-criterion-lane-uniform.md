# ADR-136：诚实退出收敛以单一缺口判据闭环，两车道同源收口

date: 2026-09-22
status: accepted

## Context

实现 run 如实申报 `status: partial` + `unattainable`（部分任务客观不可由 agent 完成）时，缺口判定在结果文件缺 unfinished 字段时回退读主树 tasks.md 勾选，而主树勾选只在成功/merge-back 路径回写，partial 收敛走不到该路径——「未收敛 → 已完成项也算缺口 → 收敛永不成立」的自锁循环，每轮真实成功却被判失败重派。两条实现车道对同一形态各有用法，fast-track 的收敛路径被其硬校验（要求完整 verification 段）实质堵死为死路。

## Decision

- 收敛判据单点：`result.success ∧ impl_status=partial ∧ 缺口非空 ∧ 缺口 ⊆ unattainable`。缺口口径 MUST 单点取自结果文件（unfinished 优先，否则全量−完成），禁止任何回退读主树勾选的路径；缺口为空的 partial 属申报不自洽，MUST NOT 按收敛放过。
- 两车道同源：full 与 fast-track MUST 共用同一判据函数、同一收口语义（不重派 + 转成功）、同一留痕；允许的车道差异（收敛后去向）MUST 在契约测试中显式记录，防被误判为不对称。
- fast-track 收敛降级完整模式补验证：诚实退出收敛不可能同时产出完整验证裁决、过不了 fast-track 硬校验，改走 merge + 转 implemented + mode 改写 full + 入队三阶段独立验证——收敛形态识别点须在硬校验之前。单 run 自证的验证强度对这类 spec 不足，三阶段独立验证是正确收口。
- 收敛点对非法 `unattainable` 项 fail-closed：产物硬门「只卡第一次」降级放行后，含非法条目的申报不得在收敛点被部分采信（洗白窗口），不收敛、按失败通道处置。
- 收敛成立后走既有成功路径全链（零变更哨→交付物守卫→relint→merge→verifier），MUST NOT 短路。

## Consequences

- 诚实申报的 run 不再被无限重派，预算与既有提交得以保留，unattainable 申报通道获得机械闭环。
- 该判据同时是 dispatch 侧收敛判定与 runner 侧保留判定的唯一口径，任何第二套「缺口 ⊆ unattainable」推导都禁止（否则读源回退的洞在旁路重开）。
