# Design: worktree 创建重名换名重试

## 现状与关键事实

- core/worktree_manager/lifecycle.py G1LifecycleMixin.create（:132-263）：锁键 spec:agent_type（:144-152）；:173-184 一次性计算 timestamp/branch/wt_name（implementer/planner-plan 等走 fenix/{spec}-{timestamp}，verifier 走 fenix/verify-{spec}-{timestamp}）；:195-210 git worktree add -b（timeout 30）；:212-219 失败仅记 ERROR、discard 锁、return None。
- 解析契约：分支名末段纯数字时间戳被 queries.py:43-59 _spec_from_branch、:28-41 _spec_from_worktree_name、:392-460 find_branches_by_spec、:555/:683-697 等多处 rsplit("-", 1)+isdigit 依赖。
- 自愈兜底：core/agent_runner/runner.py:2502-2522 create 返回 None 时 sleep 5 秒进 attempt 2/3——本 SPEC 落地后该兜底保留为最后防线。
- 测试基建：tests/test_dual_dispatch_and_freeze.py 已有 create 锁语义测试与 subprocess mock 基建（:99-141）。

## 设计

1. 把「计算名字 → add -b」包成有界循环（上限 3 次）：失败且 "already exists" in stderr 时 timestamp = max(int(time.time()), timestamp + 1)，branch 与 wt_path 同步重建后重试；非 already exists 的失败不重试、直接走现状放弃路径。
2. 锁语义不变：重试全程持有 create 锁（锁在 create 入口获取、退出释放），对调用方透明。
3. 可观测：换名重试落 WARNING（含 spec、新旧分支名、尝试序号）。
4. 范围：仅动 lifecycle.create，runner/queue/queries 零改动。

## 风险与边界

- 时间戳单调性：max(now, old+1) 保证新后缀严格大于旧值，与既有「新纪元后缀成功」形态一致（如 …-1790135672 → …-1790135677）。
- verifier 车道（verify- 前缀）同样受益，无需分支处理。
- 撞名胜者不定（现有 5 组均为 planner 先到）：换名重试对任一方后到都生效，不依赖到达顺序。
