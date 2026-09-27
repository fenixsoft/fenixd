# ADR-113：fast-track 死活按分支提交分流，共享结果文件 fail-closed

date: 2026-09-18
status: accepted

## Context

fast-track 死活的唯一判据是结果文件读取，而共享结果文件是跨 spec 单例且被无条件覆盖：文件缺失时回退读到上个 spec 的残留、stamp 守卫忽略后返回 None → 一律判死亡重派——已提交 5 个 commit 的成果被整体丢弃。「结果文件缺失 = 死亡」的推定不查 git 事实。

## Decision

- 死亡路径按 git 事实分流：实现分支有提交（rev-list main..branch > 0，判定 helper 与零变更哨共用单一来源；branch 为空或 rev-list 失败一律按无提交——保守方向，绝不因判定器故障放行）→ 保留成果 merge，并升级完整模式由 verifier 补齐验证（既有契约 + 裁决证据双 fail-closed 门接管，较 fast-track 硬校验更严）；无提交 → 既有死亡路径（豁免 + 重置 + 重派）原样。
- 缺失的验证结论不合成、不架空门：verdict 由完整模式 verifier 补出，禁止合成 passed（架空验证门）；也不一律 blocked 交人工（成果已保全，补验证即可收敛）。
- 共享结果文件的 stamp 守卫收紧为 fail-closed：stamp 与当前 spec 不等（含缺失 / 空 / 非字符串）即拒绝采信；worktree 内文件同规则（worktree 复用也可能带旧残留）。
- 已消费的共享文件在 per-spec 快照落盘后单点删除（删除失败仅 WARNING，由严格 stamp 兜底拒绝）；不在读取函数内删——一读即删会误伤仍需读同一文件的 verifier / 门禁。

## Consequences

- 「分支有提交即成果」成立，不再因产物文件丢失丢弃已落地工作；补验证不损失校验强度。
- fail-closed 收紧会拒绝 legacy 无 stamp 文件（本就不该采信）；多读者竞态由「快照后单点删除 + 严格 stamp」双保险覆盖。
