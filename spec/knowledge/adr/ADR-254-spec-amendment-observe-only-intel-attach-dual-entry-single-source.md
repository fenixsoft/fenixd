# ADR-254：主树在飞 spec 修订检测为只读情报附着，双入口共用单源判定

date: 2026-10-08
status: accepted

## Context

框架外的 spec 修订提交可能落在实现 run 在飞窗口内（2026-10-02 cimbar-airgap-transfer：修订提交落主树，与实现分支对同一 tasks.md 的勾选更新在 merge 预演相撞、直通 repair 多耗一次 run；修订落地到检出相撞相隔近 4 小时零反馈，repair 靠自行考古定位根因）。既有 merge-back 三道闸（合并预演、WIP 重叠、spec 目录在飞编辑卫检查）全部只覆盖「未提交」改动，已提交修订从落盘到 merge 时刻没有任何反馈面。做检测容易，但把检测挂进 merge-back 闸门序列有回归风险：一旦检测参与 merge 决策或熔断记账，会与既有预演/熔断语义产生新交互；而「修订自动改道实现分支」「向在飞 run 推送任务清单变更」类自动干预在无消息注入基础设施的现状下成本高、收益不明。

## Decision

主树已提交在飞 spec 修订检测一律为只读情报附着：命中只发 `spec_amendment_inflight` 告警并把修订提交列表附着 `MergeConflictInfo.amended_inflight`，MUST NOT 改变 merge-back 布尔返回与 has_semantic_conflict 语义、MUST NOT 计入 merge 熔断记账——冲突结局仍由预演确定性裁定并按既有 rehearsed 链路转 repair。检测插点固化在闸门序列头部（预演闸之前），其安全性由纯只读性保证（不触碰工作区、不写状态，前移不改变任何闸门判定）。判定与告警指纹收口单一模块级单源（`core.worktree_manager.mergeback.detect_spec_amended_inflight` / `spec_amendment_fingerprint`），merge-back 主链与 admin_monitor 周期扫描两入口共用，禁第二套同语义判定。分支不存在/git 失败一律静默跳过零副作用；告警是唯一反馈面——不做修订自动改道、不做在飞 run 任务清单变更推送、不做框架外提交者强制拦截。后续任何「修订自动改道/自动干预」类 SPEC 必须以显式裁定 supersede 本条，不得在检测函数内私自改写 merge 决策。

## Consequences

已提交修订从「merge 时刻才发现」提前到「落地后一个扫描周期内告警」，repair 相撞时上下文自带根因免考古。代价是检测只反馈不止损：相撞仍会发生、多耗一次 repair run 的成本被显式接受（结局确定性优先于省一次 run）。告警存在 merge-back 直写内联处方与 admin_monitor 处方表两处同文点，文案变更须双写同步；周期入口的去重备忘必须随信号送达结果回滚，否则出现「已告警假象」漏报。
