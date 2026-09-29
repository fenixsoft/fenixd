<!-- knowledge: capability=redispatch-artifact-succession rev=1 sources=spec/archive/2026-09-22-fix-relint-redispatch-legacy -->

# 打回重派的分支遗产登记

SPEC 因「run 层成功但 spec 层判失败」被打回重派时，保证已提交成果可被后继 run 认领继承，不因打回丢失。

## 现行规则

- 所有「status 回退到 `ready` 且分支含有效提交」的打回路径一致登记分支遗产（`worktree_manager.register_legacy`）：交付物守卫缺件打回（`_redispatch_for_missing`）、tasks.md 收口复检违规打回（`_redispatch_tasks_relint`）、merge-back 失败回退、repair fallback。不适用的路径以显式理由说明（如零变更哨：分支零提交，无遗产可登记）。
- 遗产认领：打回登记后，下一轮 `worktree_manager.create` 经 `_take_reusable_worktree` 认领同一分支，继承前轮已提交成果。
- 无分支时安全跳过：触发打回但 `result.branch` 为空或缺失时跳过遗产登记，重派照常进行（fail-open），不抛异常阻断处置。
- 一致性机械可验：存在测试或契约断言覆盖「每条适用打回路径都调用了 `register_legacy`」或「打回后 `_legacy` 在册可认领」，使新增打回路径漏登记遗产可被检出。
- 遗产登记不是成果继承的唯一手段：partial 收敛不成立的重派形态由 worktree 保留机制（见 redispatch-loop-governance）覆盖；分支遗产登记与 worktree 现场保留语义正交，同时满足时两条机制各自生效、互不覆盖。
- 任务与交付物以函数名锚定，不以绝对行号作为唯一锚点。

## 溯源

- [2026-09-22 fix-relint-redispatch-legacy](spec/archive/2026-09-22-fix-relint-redispatch-legacy/) — 补齐 relint 打回路径的分支遗产登记，固化四条打回路径的一致性断言与无分支 fail-open 边界
