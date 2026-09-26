# 设计

## 改动点
1. core/agent_runner/runner.py _prepare_worktree（:2798-2825）：把「sleep(5) 一次 + 判定放弃」改为退避循环（30s/60s/120s）：每轮重探 create，锁活跃才继续等待；重试耗尽返回既有 gave up。
2. core/agent_runner/runner.py 让路原因区分（_should_give_up_before_retry :5083-5148）：单一 bool 拆分——锁活跃（has_active_lock 探针，core/worktree_manager/lifecycle.py:308-315）可退避等待；frozen（:5113-5120）、_cancelled_hold（:5123-5130）、status 迁出预期态（:5134-5145）必须立即让位。可在 _prepare_worktree 内分探针实现，不改公共判定函数的既有签名与语义。
3. core/pm_engine/engine.py 降级分支（:2418-2424）：加实例级/模块级计数器，WARNING 附「第 N 次降级」，约 5 行。

## 备选与否决
- verification/pipeline.py:2386-2436 阶段1 加退避重派（仿 ：2411-2435 provider circuit open 早退分支）：仅覆盖出题车道，救不了 09-06 主派发车道同签名死亡，作为次选不采用；
- 重试放 worktree_manager.create 内部：create 是多车道共用原语，内嵌等待拖长所有调用方关键区，且拿不到 runner 层的冻结/取消上下文，不做。

## 测试
新增 tests/test_worktree_acquire_backoff.py：锁释放后取得、耗尽放弃、frozen 立即让位、降级计数四类场景；回归既有 worktree 命名冲突与验证管线测试。