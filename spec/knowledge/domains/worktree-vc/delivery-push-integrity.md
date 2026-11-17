<!-- knowledge: capability=delivery-push-integrity rev=1 sources=spec/changes/evo-wrapup-push-branch-guard -->

# 推送交付完整性守护

done→pushed 收尾推送的交付完整性守护层：推送目标锁定实际检出分支（对既有解析单源做行为级回归守护）、推送成功以「远端 tip 前进」断言为准、daemon 启动时对账本地领先缺口兜住静默交付悬置。目标分支解析机制与推送环境预检见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)，推送引用生命周期（退避收敛、feature 分支 SHA 去重）见 [推送引用生命周期卫生](push-ref-hygiene.md)。

## 规则

- 推送目标为实际检出分支：收尾推送与归档收口推送的目标分支一律经解析单源 `_resolve_push_target_branch`（配置 `pm.push.target_branch` → 检出分支 → main，机制见 [推送 git 环境预检与 N/A 短路](push-git-env-precheck.md)）确定，不硬编码固定分支名——master 检出项目推送 master、main 检出项目行为不变。分支解析全系统只此一条路径，后续改动 MUST NOT 重写该解析或引入第二解析机制，本能力仅以行为级测试锁定其对外行为。
- 推送成功以远端 tip 前进为准：收尾主推在 git push 子进程 returncode==0 之上叠加 tip 前进断言——推送前经 ls-remote 取目标分支远端 tip 基线，推送后复取比对；tip 前进（含远端分支首次创建：基线缺席、推送后在位）才算推送成功，走现流程清 error、标记 pushed。returncode==0 单独不构成成功判据，`Everything up-to-date` 空转与真实 tip 前进可区分。
- up-to-date 空转不计成功、不进退避：推送后远端 tip 未前进（Everything up-to-date）不计成功——不标记 pushed、不写 error、不计退避、不发 push_failed，仅发单条 WARNING 级空转告警（含本地与远端 tip，说明推送目标无新内容）。空转是内容状态不是推送失败，刻意与指数退避机制解耦，避免误升级。
- 断言无法验证与推送命令失败走既有路径：推送后远端 tip 查询失败（ls-remote 取不到）按既有推送失败路径记账（进退避、超限升级），不新增语义；推送命令本身失败仍走既有分流——N/A 环境预检短路前置不变，非 fast-forward 失败走退避升级、禁止自动 force。
- daemon 启动领先对账：daemon 启动时对本地解析基分支跑 `git rev-list --count origin/<分支>..refs/heads/<分支>`（走本地 remote-tracking ref，不发网络请求）并上报日志；领先数>0 发 WARNING 暴露交付缺口（含分支名与领先数，交人工核查是否对齐远端）；一致（领先 0）记 info；远端引用缺失或 rev-list 异常记领先数不可知、fail-open 不阻塞启动；本地基分支不可解析（空仓/异常形态）跳过对账。对账结果同步进健康摘要聚合面（领先>0 追加「分支领先远端 N 提交」段，fail-open 不影响摘要主体；置于空 STATE 早退之前——缺口暴露不依赖 SPEC 在场），供人工与聚合面双路消费。
- 残痕回填清痕兜底按解析基分支：pushed 终态推送失败残痕的幂等回填清理，在 spec 自身分支与远端无从比对时，兜底比对「本地解析基分支 vs 远端同名分支」SHA（相等即清痕），基分支经解析单源获取而非硬编码 main——非 main 检出项目的残痕不因恒不相等而永不清理；取不到本地基分支时保守保留残留。

## 代码锚点

- 主实现：`core/pm_engine/engine.py`（`_assert_push_tip_advanced` tip 前进断言与空转告警、`reconcile_base_branch_ahead` 启动对账、approve_push 主推段断言接线、`backfill_push_residuals` 解析基分支兜底清痕、启动段对账日志上报、`get_health_summary` 领先段消费）
- 守卫测试：`tests/test_wrapup_push_branch_guard.py`（master 检出推送目标、tip 断言、空转告警、启动对账输出）

## 溯源

- 2026-11-17 evo-wrapup-push-branch-guard（spec/changes/evo-wrapup-push-branch-guard/） — 新增本能力：推送成功判据从 returncode==0 升级为远端 tip 前进断言（up-to-date 空转不再计成功、不进退避、单条告警）、daemon 启动基分支领先对账、残痕回填兜底清痕基分支去硬编码、遗留「main」表述清理；分支解析机制由 push-git-env-precheck 承载，本能力仅行为级守护。动因：cloud-phone 项目检出 master，7 次「Main push succeeded」中 5 次为 up-to-date 空转、STATE 全标 pushed 而 origin/main 缺 95 提交的静默交付悬置
