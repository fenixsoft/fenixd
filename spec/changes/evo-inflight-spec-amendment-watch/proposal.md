# Proposal: inflight-spec-amendment-watch

## Why

2026-10-02 cimbar-airgap-transfer 实现期间，框架外的 spec 修订提交 803c688（10:46:21，改写 tasks.md 四条任务并新增 5 项）落进主树，与实现分支对同一 tasks.md 的勾选更新自 merge-base 7ebb4db 分叉，14:28:55 merge 预演必然检出语义冲突、直通 repair 车道，多耗一次 run（61 轮 / $0.427，repair-cimbar-airgap-transfer-1790922535-a1）。现行 merge-back 三道闸门全部只覆盖「未提交」改动：_rehearse_merge_from_branch（core/worktree_manager/mergeback.py:143）只能事后检出冲突；_wip_overlap_gate（:166）显式排除 spec/changes/**；_check_spec_dir_inflight（:253）只查未提交——已提交修订从落盘到 merge 时刻的近 4 小时里零反馈，repair 车道还要自行考古根因。

## What Changes

- 新增「主树 spec 目录在飞修订」探测：merge-back 主链与 admin_monitor 周期扫描两个入口，检测 spec/changes/<spec>/ 相对 merge-base 在主树出现的新已提交修订；命中即发 spec_amendment_inflight 告警（含修订提交列表与相撞预警），把发现时刻从 merge 时刻提前到修订落地后的一个扫描周期。
- merge-back 侧命中时把修订提交列表附着到冲突转 repair 的派发上下文，repair prompt 直接带根因，消除考古成本。
- 不改变冲突的确定性结局：已提交修订与分支勾选相撞仍走既有预演→repair 链路，本 SPEC 只做早期探测、告警与根因透传。

## 非目标

- 不实现「修订自动改道实现分支」与「向在飞 run 推送任务清单变更通知」（现状无消息注入基础设施，成本高收益不明）。
- 不引入对框架外提交者的强制拦截（git 直提无法拦截），告警是唯一反馈面。
- 不改 _rehearse_merge_from_branch 预演语义、repair 车道解决策略与 merge 熔断记账语义。