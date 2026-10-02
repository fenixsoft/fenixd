# ADR-205：车道终态自我收尾的取消键必须收敛到含 epoch 的完整 run 级 id，逐 run 归属复核禁裸前缀

date: 2026-10-02
status: accepted

## Context

SPEC 推送到终态时在飞 verify 车道不被回收（实证：42 分钟 LLM verifier 在 SPEC 推送后继续在飞 10 分钟白烧 tokens），收尾需复用既有取消原语、照搬 `_stop_parallel_planning` 的车道收尾范式。取证发现该既有范式的取消键并不收敛：`cancel_run` 的旗标登记键经归一化只剥 `-a<n>`/`-r<n>` 后缀、不剥 epoch，登记侧对活跃 attempt 按裸前缀 `startswith` 匹配即返回 `cancel_requested`；而消费点（attempt 循环/轮询环）以带 epoch 的 run 级 id 归一后做精确集合判定。传裸 `<lane>-<spec>` 键时旗标与消费键不收敛，取消静默失效且返回值与审计均显成功（`_stop_parallel_planning` 自身长期靠摘队列 + 消费侧校验兜底即是互证）。此外登记侧裸前缀匹配会误中同根后代 spec 的 run——`verify-fix-a-b-<epoch>` 命中 `verify-fix-a` 的前缀，而 family 派生谱系常见。

## Decision

- 车道对自家在飞 run 的终态自我收尾复用既有 `cancel_run` 原语（旗标登记 + 属主线程终止），不新建终止通道；但取消键 MUST 为完整 run 级 id（含 epoch），MUST NOT 传裸 `<lane>-<spec>`——键收敛由调用方保证，不是原语义务。
- 收尾须逐活跃 run 做归属复核（`run_spec_part(aid) == spec_name`），仅对本 spec 的 run 调 `cancel_run`；归属精确性不依赖登记侧的前缀匹配。
- 收尾挂在终态收敛点（多路结果采纳的唯一汇合处）终态转移成功之后，不在方法入口：逃生门回退续跑与保持态路径在入口判据后提前 return，入口收尾会拆掉刚被门禁要求续跑的在飞车道；按 epoch 键登记的旗标天然不波及回退后重派的新 epoch run 与人工重验 run。
- 收尾整体 try/except 记 WARNING 不抛，不阻塞终态主链；`cancel_run` 是协作式取消，长轮次退出有延迟，退出前写完的迟到结果由应用侧「非 testing 状态一律丢弃」复核兜底——取消与丢弃双腿缺一不可。
- 既有 `_stop_parallel_planning` 的裸键写法留档为反例，后续车道收尾 MUST NOT 照搬；测试断言取消生效必须查消费点视角 `_cancel_is_requested(<在飞 run id>)` 为真，禁只断言 `cancel_run` 返回值。

## Consequences

- 取消真正生效（属主轮询环退出、子进程终止、终态后白烧止损），代价是调用方须先解析活跃 run 的完整 run 级 id 并逐 run 归属复核，比裸键多一步。
- 协作式取消的退出延迟被有意保留而非改为跨线程 kill，因此本裁定与应用侧迟到结果丢弃守卫构成防御纵深，任一腿单独存在都不完整；后续任何车道收尾实现都必须同时具备两腿。
