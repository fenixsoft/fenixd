# proposal：fix-evolution-push-remote-probe-skip

## Why

自进化回写对受管项目仓就地 git push，而受管 6 项目中 dsh-plugins 与 potplayer-base 两仓零 remote，push 结构性必败：保留日志同文 WARNING 持续累积（2026-10-05 起逐日新增；2026-10-30 人工核查口径 49 条且逐日递增——替代早期冻结的 41/46/47 口径，评审实测 fenixd.log 8 条＋fenixd.log.3 45 条），stderr 逐条同文「fatal: No configured push destination.」且文案不含仓路径，持续稀释 WARNING 告警通道；daily self-review 车道（core/self_review.py 的 _commit_todo）同型裸 push 同病。两零 remote 仓的 todo 回写提交无任何远端备份。实测两仓裸 push 均 exit=128「fatal: No configured push destination.」与日志逐字同文。主仓 fenixd 自身含可用 origin（评审实测 `push --dry-run` exit=0），恒败刷屏集中于零 remote 两仓的回写链路；「有 remote 但临时失败」残余类由聚合告警收敛（同仓同日 WARNING 至多一条）。

## What Changes

- push 前以 git remote 探测，无 remote 记 DEBUG（含项目根路径）跳过 push——evolution.py 与 self_review.py 两车道同改、共用一个探测函数
- 恒失败（同仓连续失败）收敛为每日一条聚合告警，WARNING 与告警文案补项目根路径（当前不含仓路径导致 46 条失败无法逐条归仓）
- 零 remote 仓关闭 push 语义；需远端备份的仓由人工显式配置 remote（人工步骤记 .fenix/todo.md）

## Impact

- core/evolution.py：push 前探测＋聚合告警＋文案补路径
- core/self_review.py：_commit_todo 同型探测接入
- tests/test_evolution_push_remote_probe.py：新增契约测试
