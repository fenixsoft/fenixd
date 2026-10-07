# Design: inflight-spec-amendment-watch

## 背景与痛点

2026-10-02 cimbar-airgap-transfer 实现在飞期间，框架外提交 803c688 改主树 tasks.md，与实现分支勾选更新在 merge-back 预演相撞，直通 repair 多耗 61 轮 / $0.427；修订落地到 merge 时刻近 4 小时零反馈，repair 靠自行考古定位根因。现行三道闸（core/worktree_manager/mergeback.py: _rehearse_merge_from_branch 调用点:143/定义:893、_wip_overlap_gate 调用点:166/定义:312、_check_spec_dir_inflight:253）均不覆盖「已提交修订」。

## 目标

- 在飞修订落地后一个扫描周期内告警（admin_monitor 入口）；merge-back 撞修订转 repair 时上下文自带根因（merge-back 入口）。
- 检测零副作用：不改 merge-back 返回值语义、不入熔断、分支不存在静默跳过。

## 非目标

- 不做修订改道/任务清单变更推送/强制拦截；不改预演与 repair 解决策略。

## 方案

1. core/worktree_manager/mergeback.py：新增已提交在飞修订检测（如 `_detect_spec_amended_inflight(branch, spec_dir)`）：`git merge-base <主树HEAD> <branch>` 求分叉点，`git log <merge-base>..<主树HEAD> -- spec/changes/<spec>/` 非空即命中；在 `merge_back_from_branch`（:107）闸门序列（_check_spec_dir_inflight :179 之后）调用；命中发 spec_amendment_inflight 告警并把提交短哈希列表挂到 MergeConflictInfo（如 `amended_inflight` 字段，参照既有 rehearsed/wip_gate_blocked 附加字段形态）。
2. core/pm_engine/dispatch/queue.py：rehearsed 直通 repair 分支（:1843-1844 `_direct_rehearsed_to_repair`）透传 `merge_info.amended_inflight`，repair 派发上下文与 prompt 增补「主树在飞修订根因」段（core/pm_engine/dispatch/repair_lane.py 消费）。
3. core/admin_monitor.py：周期扫描新增同条件检测——对有活跃实现 run 的 spec（分支名取自 run 记录），判定 spec 目录主树分叉；命中发同 kind 告警；以 spec+修订提交集合为告警指纹去重（沿用 admin_alerts 指纹/节流机制，orphaned_state 同款 _throttled 语义，core/admin_monitor.py:319 告警级别表处注册 kind）。

### 关键约束

- merge-base 依赖实现分支存活：两入口都 MUST 在分支存在时才执行（`git merge-base` 失败即静默跳过）；分支名以 run/spec 记录为准，不自行猜测命名规则。
- 检测命中 MUST NOT 改变 merge_back_from_branch 的布尔返回与 MergeConflictInfo.has_semantic_conflict 语义——相撞仍由预演检出并按既有 rehearsed 链路转 repair，避免与 merge 熔断记账（_merge_fp/_merge_streak）产生新交互。
- 告警 kind `spec_amendment_inflight` 注册进 admin_monitor 的 kind 级别/处方表（severity 建议 major，对照 orphaned_state: major），处置文案指向「等实现收尾后在分支上补修订或经 repair 合并」。
- 兼容旧 MergeConflictInfo 构造点：`amended_inflight` 必须带默认空值，MUST NOT 破坏既有测试对 MergeConflictInfo 的构造。

## 测试策略

- 扩展 tests/test_merge_back_spec_dir_guard.py：夹具仓库在 merge-base 之后于主树提交 spec 目录改动 → merge-back 发告警且 merge_info 携带 amended_inflight、repair 上下文含根因段；主树无新提交 → 行为与告警完全不变；分支不存在 → 静默跳过。
- 新增 tests/test_admin_monitor_spec_amendment.py：实现 run 在飞 + 主树 spec 修订 → 一个扫描周期内告警、同指纹不重复；run 不在飞 → 不检测。
- 回归：tests/test_worktree_merge_guard.py（含 _wip_overlap_gate 用例）、tests/test_merge_tree_rehearsal.py、tests/test_mergeback_repair_lane.py。