# 提案：worktree 锁让路的退避等待与降级计数

## 背景与问题
agent run 启动时 _prepare_worktree（core/agent_runner/runner.py:2729）经 worktree_manager.create 取 worktree；同 spec:agent_type 锁已被并行 run 持有时 create 返回 None（core/worktree_manager/lifecycle.py:144-153），runner 仅 time.sleep(5) 一次（runner.py:2805，全路径唯一等待）即经 _should_give_up_before_retry 判定放弃（:2822 错误文案「Failed to create worktree (gave up: parallel run or manual freeze)」）。对验证出题车道，这一个瞬间事件就把整条新验证流程炸进降级：pipeline.py:2436 raise 后 engine.py:2421-2424 无计数 WARNING 降级旧版 verifier。日志保留窗内同签名已发生 7 次（09-06/09-17/09-19/09-21/09-22/09-24/09-26），09-06 还波及主派发车道；09-26 降级拉起的旧版 verifier 白跑 966 秒 97 轮后被回收（fenixd.log:26872-26889）。

## 目标
1. 锁活跃（并行 run）导致的 worktree 创建失败改为短退避等待重试（等持锁方排空），重试耗尽才放弃；
2. 人工冻结/取消/状态迁出保持立即让位，不自动穿越；
3. 新验证流程降级分支的 WARNING 附累计计数，便于统计降级频率。

## 非目标
- 不改上游同毫秒双派发窗口成因（事件通道与派发队列同触发），可另立线索；
- 不动 worktree_manager 的「already exists」换名重试（evo-fix-worktree-name-collision-retry 已覆盖，签名不同）。

## 代价与风险
- 主改动在 runner 层挂点现成（sleep+判定已在该分支），约 20-30 行；
- 关键风险：退避不可穿越人工接管语义——frozen/_cancelled_hold/status 迁出必须立即让位，重试只针对锁活跃；
- 锁释放后再 create 不会形成并行 run，不违反双派发防护的安全语义。