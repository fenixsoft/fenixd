# ADR-021：merge-back 主树冲突自愈保 merge 结果

date: 2026-09-04
status: accepted

## Context

merge-back 是实现链标准环节（ADR-023），其主树冲突面有两类反复复现的死锁变体：主树 untracked 文件与分支新增同路径文件冲突（merge 拒绝覆盖，连败触发熔断置 blocked）；stash pop 冲突使主树留在半合并状态，此后所有 git 写命令失败。每次都需人工「备份/移除→手动 merge→复位」救回。

## Decision

- stash pop 冲突自愈取舍：`checkout HEAD` 保留 merge 结果（已成功合并的实现，最不可丢失的核心产物），弃工作树中的 stash 版本（派发前散落改动，可从 stash 条目找回）；反向取舍（保 stash）会覆盖已合并实现，否决。冲突文件在 stash 条目中完整保留，框架不自动 drop。
- untracked 冲突按「分支新增路径集合 × 主树 untracked」交集防护：merge 前 `git diff --diff-filter=A HEAD...<branch>` 取分支新增路径，逐路径检出主树 untracked 者移入带时间戳的备份目录后再 merge；不做全仓库扫描，非冲突 untracked 留在原地。
- 备份清理前逐文件与 HEAD 同路径文件字节比对：全部一致才删；存在不一致保留备份目录并 WARNING 列出路径，不静默丢弃任何有价值主树改动。
- 冲突清单走既有 error 字段与 admin 告警通道，零新增持久化设施。

## Consequences

- merge-back 冲突自行止血，不瘫痪主树、不阻塞其它 spec 的合并；主树改动「可找回而不丢弃」成为取舍底线，宁可积压备份等人工决策。
- rename 目标路径等漏检场景退化为原有失败熔断路径，不劣于防护前；不自动解决内容冲突本身（谁对谁错只能人工判断），自愈只保证止血、留痕、可找回。
