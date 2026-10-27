# ADR-287：主树散件 untrack 根治执行器独立实现，复用守卫原语不扩既有门

date: 2026-10-27
status: accepted

## Context

主树复发型散件（被 track 的生成物日志等每次构建必复发的确定性敞口）需要「当场断根」的 untrack 路径：git rm --cached + .gitignore 追加 + 独立提交。仓库内已有 stash_guard 承载相近的出库自愈原语（staged 子集守卫、索引路径还原），但其入口挂着「check-ignore 全须忽略」前置门——目标生成物文件实测不被 ignore，走既有入口必须先拆门。

## Decision

untrack 执行器在裁决执行链内独立实现，不复用 stash_guard 入口、不打开（也不修改）其「check-ignore 全须忽略」前置门；仅复用其 staged 子集守卫与回滚子函数作为原语（staged 名单额外放行 .gitignore，回滚段还原出库与追加）。执行作用面收窄到告警 evidence 指认文件清单，与 commit_stray_wip 同款 signal_type 绑定守卫收口。

## Consequences

既有自愈路径的暴露面零扩大（拆门会连带放开原路径对所有场景的放行），新路径误伤面被限定在告警指认清单；代价是出现两条出库路径并存，stash_guard 原语演进时须同步核对独立执行器的复用点（口径漂移风险由共用子函数而非复制逻辑压住）。后续为同类「目标不满足既有门前提」的根治/清理诉求扩路径时，沿用「独立执行器 + 复用守卫原语 + 不扩既有门」形态，放宽须显式 supersede。
