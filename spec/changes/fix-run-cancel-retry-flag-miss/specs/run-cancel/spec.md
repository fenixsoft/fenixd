# run-cancel Delta: 瞬态重试轮取消覆盖

## ADDED Requirements

### Requirement: 取消旗标覆盖瞬态重试后缀 run

`AgentRunner` 的取消旗标登记键与消费键必须经同一归一化收敛：归一化需剥离 run_id 尾部**连续多组** `-a<N>`（attempt）与 `-r<N>`（瞬态重试）后缀。对带 `-r<N>` 后缀的在飞 run 登记取消（`cancel_run`）后，持有线程必须在轮询环内消费旗标并终止子进程（terminate→grace→kill→cancelled 终态），attempt 循环顶部旗标命中时不得派发后续 attempt。

#### Scenario: 轮询环消费 -r1 重试轮旗标
- **WHEN** run `planner-judge-x-<ts>-a1` 瞬态重试产生在飞子 run `planner-judge-x-<ts>-a1-r1`，对 base id `planner-judge-x-<ts>` 登记取消旗标
- **THEN** 子 run 的轮询环在下一轮询周期命中旗标，terminate 子进程并落 cancelled 终态，`run_planner` 返回 `cancelled=True`

#### Scenario: attempt 顶旗标命中阻断后续派发
- **WHEN** 取消旗标已按 base id 登记，run 的 attempt 循环准备派发下一 attempt（run_id 带或不带 `-r<N>`/`-a<N>` 后缀）
- **THEN** attempt 循环顶部归一化判定命中旗标，直接返回 `cancelled=True`，不派发 attempt、不创建 worktree

#### Scenario: 既有取消语义回归不变
- **WHEN** run_id 无后缀（如 `impl-x-<ts>`）或仅带 `-a<N>` 后缀，取消旗标登记与消费
- **THEN** 行为与修复前完全一致：无后缀输入归一化幂等，纯 `-a<N>` 轮照常命中
