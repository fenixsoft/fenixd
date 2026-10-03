# ADR-229：worktree 锁让路退避归获取调用层，自动等待不可穿越人工接管

date: 2026-10-04
status: accepted

## Context

agent run 启动经 worktree_manager.create 取 worktree，同 spec:agent_type 锁被并行 run 持有时 create 返回 None，而全路径唯一的等待是 sleep 5 秒一次随即判定放弃——上游事件通道与派发队列同触发的同毫秒双派发窗口产生的单个瞬时锁碰撞，就足以把整条验证出题链炸进 legacy 降级（日志保留窗内同签名失败 9 次跨 7 个日期，一次降级拉起的旧版 verifier 白跑 966 秒后被回收）。等待机制的落点有三个候选，各有架构代价：单车道验证管线内重派只救一条车道、救不了主派发车道的同签名失败；worktree_manager.create 是多车道共用原语，内嵌等待拖长所有调用方的关键区，且该层拿不到 runner 层的冻结/取消上下文。

## Decision

- 等待归获取调用层：锁活跃导致的 create 失败由 runner 获取层（`_prepare_worktree`）内按短退避序列（当前 30s/60s/120s）等待重试，不消耗 attempt 重试额度、不写 STATE 退避字段；重试耗尽才交既有 gave up 终态。与 ADR-192 的分层裁定衔接：create 层只做「识别 + 一次性清理重试」，锁等待这一新重试形态同样不落入共用原语。
- 共用原语禁内嵌车道性等待；单车道管线内重派不作为通用解——跨车道共用的失败处置必须放在能同时看到全部车道与人工接管上下文的层。
- 自动等待不可穿越人工接管：frozen、`_cancelled_hold`、status 迁出预期态三种让路原因立即让位不进退避；退避循环每轮重探前复查三种接管态，等待期间出现任一（含并行 run 完成后的状态迁移）即立即让位，不得在锁释放后照常取得 worktree。此为对自动等待类机制的一般约束，先例为 provider-transient 退避的重派前复查。
- 锁释放后再 create 取得的是空闲 worktree，不构成并行 run，不违反双派发防护的安全语义。

## Consequences

- 瞬时锁碰撞由在位等待吸收，验证链不再因单个 create 冲突事件整体降级；代价是等待同步占用本 run 的 worker 线程，等待预算有界、耗尽即走既有放弃通道，持锁方长滞留的治理仍由锁残留恢复与孤儿清扫兜底。
- gave up 错误文案签名（parallel run or manual freeze）保持不变，依赖该签名做分流与统计的下游不受影响。
- 等待重试只针对锁活跃一类原因，非锁失败（git 命令失败等）不进退避，保持既有 attempt 层语义——退避不放大环境类失败的等待成本。
