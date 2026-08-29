# Design: add-inplace-bug-repair

## Context

现行 bug-found 处置：pm_engine 自动派生 `fix-*` 子 SPEC（`_ensure_fix_spec_files` 生成最小 proposal/tasks），implementer 在新 worktree 中凭两行引用重建上下文。已花费的配套治理：fix-repair-lane-dedup（pushed）三守卫治重复派发；fix-family-convergence-governor（随 improve-scheduling-noise-governance 已 pushed，pm_engine `_fix_prefix_depth`）治族谱深度；add-verify-report-gate（在途）治报告引用断裂。三者治理对象都是「派生」这一动作本身。

## Goals / Decisions

### D1: 原地打回替代派生，治理面整体消失
父 SPEC 目录天然携带 design/proposal/tasks/verification-report.md 全量上下文，重置 implementing 后走既有派发循环，信息零丢失、机制零新增。族谱不再增长 → 族谱收敛 governor 失去作用对象；每 SPEC 只有自身一条修复 lane → 派发级互斥失去作用对象；add-verify-report-gate 的「fix 派生输入校验」退化为 legacy 防御。两项已 pushed SPEC 无需回滚代码，随派生路径退役而失效。

### D2: 升级闸门用轮数计数器，不进 config
`_verify_fail_rounds` 为 `_` 前缀内部字段（state_machine 现有机制自动跨重启持久化，与 `_merge_fp` 等同构）。阈值 3 为模块常量——不新增配置键，即不触发「配置项必须带 Dashboard 界面」的约束；将来需要可调时再连同 UI 一起立项。

### D3: 修复任务注入走「追加段」而非重写
`tasks.md` 末尾追加/更新 `## 验证修复` 段（引用报告路径 + 轮数注记），既有任务与勾选状态 MUST NOT 改写——重验通过后该段残留无害，避免反向清理逻辑。报告存在性由 add-verify-report-gate 的裁决放行闸门保障（本变更依赖其先行落地）。

### D4: 过渡期兼容——存量链条自然耗尽
本 SPEC 排期在 v2 链与 add-verify-report-gate 之后，落地时存量 fix 链（如 fix-v2-shell-hash-router）应已收敛；「子 fix 完成 → 父 SPEC 自动重验」闭环保留为 legacy 路径直至链条清空，新裁决不再产生新派生。`_ensure_fix_spec_files` 与族谱 governor 代码在 legacy 闭环确认无残留可达后一并移除。

### D5: 范围边界——终态 SPEC 的回归不在本机制内
原地打回只作用于验证 lane 中的未终态 SPEC。done/pushed 后由其它 SPEC 的变更暴露的回归，属独立缺陷，按既有 SPEC 流程新建（不适用「打回」，因其工作已发布）。

## Risks / Trade-offs

- 失去 fix 族谱的「迭代台账」可见性 → 由 `_verify_fail_rounds` 计数 + tasks.md 轮数注记 + Dashboard 已有 error/status 展示补偿。
- 修复 agent 与原实现 agent 非同一会话，仍需读报告重建细节 → 报告与 spec 目录同处，读取成本远低于跨 SPEC 重建。
- 重置 implementing 时若该 SPEC 已有子 SPEC 在跑（依赖它）→ 子 SPEC 不受影响（依赖判定只看父状态是否终态），父回炉会自然暂停其下游推进，语义正确。

## Migration Plan

按 depends_on 顺序：add-verify-report-gate → 本变更。落地即对新裁决生效；存量 fix 链按 D4 自然耗尽；无数据迁移。

## Open Questions

无。
