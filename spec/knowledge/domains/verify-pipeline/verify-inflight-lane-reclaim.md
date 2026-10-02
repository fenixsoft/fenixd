# verified 终态在飞验证车道回收

<!-- knowledge: capability=verify-inflight-lane-reclaim rev=1
     sources=spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber -->

SPEC 达成 verified 终态时对在飞 verify 车道的自我收尾：摘除在队条目并按完整 run 级 id 取消在飞 verifier run，终态化之后不再白烧车道 tokens。

## 规则

- 收敛点单点收口：车道收尾挂在 `_on_spec_verified`（验证结果采纳的统一出口，legacy 与 pipeline 双路唯一汇合处）内 `transition(spec, "done")` 成功之后，与 `_evict_spec_serving` 终局驱逐同位置；收尾整体 try/except 记 WARNING 不抛，收尾失败不得影响 verified 主流程（done → push 链）。
- 两段结构：先 `_remove_queued_entry(spec, "verifier")` 摘除派发队列中的在队 verify 条目（daemon 不再据其派发新 verifier run）；再对归属复核通过的活跃 verify run 调既有取消原语 `cancel_run(..., by="verify-lane")`（旗标登记 + 属主线程终止）。
- 取消键 MUST 为完整 run 级 id（含 epoch，如 `verify-<spec>-<epoch>`），MUST NOT 传裸 `verify-<spec>`：旗标登记键与消费点（attempt 循环/轮询环按带 epoch 的 run 级 id 归一后精确集合判定）必须收敛；裸键登记与消费键不收敛，取消静默失效且 `cancel_run` 返回值仍显 `cancel_requested`。测试断言取消生效必须查轮询环视角 `_cancel_is_requested(<在飞 run id>)` 为真，不得只断言 `cancel_run` 返回值。
- 归属复核：仅对 `run_spec_part(aid) == spec_name` 解析为本 spec 的 run 调 `cancel_run`；不越权终止其它 spec 或其它 agent_type 的 run——同根后代 spec 的 run id 前缀相似但归属不同（`verify-fix-a-b-<epoch>` 不得被 `verify-fix-a` 的收尾波及）。
- 不回收路径：验证完成度闸门判定进度不完整、D7 逃生门回退 testing 断点续跑，以及「blocker 保持 verified」路径，不执行车道收尾——门禁要求续跑的在飞车道不得被拆。取消旗标按含 epoch 的完整 run id 登记，天然不波及门禁回退后重派的新 epoch verify run 与人工重验 run。
- 时机语义：回收发生在 verified 采纳之后（终态化起点）；testing 内机械车道与 LLM verifier 双车道并行是设计行为（机械车道先出结果即采信），不在 testing 内拆车道。
- 防御纵深：`cancel_run` 是协作式取消（旗标 + 轮询环退出），长轮次从收到旗标到实际退出有延迟；退出前写完的迟到结果由应用侧状态复核守卫（verify-late-result-terminal-guard）兜底丢弃，双腿缺一不可。

## 溯源

- 2026-10-02 fix-verify-late-result-terminal-clobber（spec/archive/2026-10-02-fix-verify-late-result-terminal-clobber） — 新增 verified 收敛点（done 转移成功后）的 verify 车道收尾：摘在队条目 + 按完整 run 级 id 取消在飞 run（2026-09-24 实证 SPEC 推送后在飞 LLM verifier 未被终止、继续白烧 10 分钟 LLM tokens）
