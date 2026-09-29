<!-- knowledge: capability=verify-recovery-budget rev=1 sources=spec/archive/2026-09-12-fix-daemon-lifecycle-races -->

# 重启重验预算与超限冻结

daemon 重启恢复重验（testing 回退 implemented 并重派 verify）的持久化预算计数：堵死「毒 spec 借反复重启无限重验」的敞口。

## 现行规则

- STATE.md 维护内部字段 `_verify_redo_count`：重启恢复路径将 testing 状态 spec 回退为 implemented 并重派 verify 时递增该字段，并随 `update_spec` 持久化，跨重启保留。
- `_verify_redo_count` 与 `_verify_fail_rounds`（失败→fix 轮数）语义正交，互不读写对方字段。
- verify 自然通过（verified 或 done 落定）时 `_verify_redo_count` 清零，清零点与 `_verify_fail_rounds` 一致。
- daemon 启动恢复时若 spec 的 `_verify_redo_count` 达到 `agents.verify_redo_budget`（缺省 3），对该 spec 执行结构化冻结（status=blocked + frozen 字段），error 注明「重启重验超限，等待人工裁决」，本次启动不再自动重派 verify；人工 `unfreeze_spec` 后 spec 恢复指定状态且计数清零，可正常派发。

## 溯源

- [2026-09-12 fix-daemon-lifecycle-races](spec/archive/2026-09-12-fix-daemon-lifecycle-races/) — 新增重验计数持久化与超限结构化冻结：每次恢复重验递增 _verify_redo_count，达 agents.verify_redo_budget 冻结 blocked 等人工裁决
