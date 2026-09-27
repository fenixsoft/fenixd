# ADR-131：repair 成功以 git 事实复核为准，提交先于测试为强制终点

date: 2026-09-21
status: accepted

## Context

repair agent 声明 success 与框架据以 re-merge 之间没有任何 git 事实校验：agent 把冲突解决并暂存、却因先跑全量套件从未 commit，在超时窗口内以 success 结束；框架对未前进的分支重新预演 → 检出同一冲突 → 熔断 → 全新重派。实证代价：尝试预算消耗过半、累计 $20.78，而冲突规模是单行 import。prompt 侧「解决冲突 → 跑测试 → commit」的顺序把测试放在提交之前，诱导 agent 用几十分钟的全量套件当提交前置，repair 窗口内几乎必然跑不完。

## Decision

- **agent 的 success 声明不进框架信任半径**：git 事实复核放在 dispatch worker 侧（判成功之后、re-merge 与预算对账之前），不依赖 prompt 措辞——agent 无论如何声明都无法绕过框架侧校验。
- 三项事实判定全部走只读 git 查询，不新增写操作：分支 tip 相对派发前基线前进（基线在派发点写入 STATE 侧车字段，成功后清零）；暂存区无未合并条目（`ls-files -u` 为空）；worktree 无 MERGE_HEAD（无未完成 merge）。判定以 repair 后实际 worktree 路径为准。
- 复核失败复用既有 fallback 路径，不新造回退分支；错误文本从笼统的「merge-back failed」升级为携带具体事实（基线值、当前值），注入下一轮重派上下文。基线缺失（存量状态）退化为仅查残留两项——保守放行，不引入新风险。
- prompt 契约确立「**提交先于测试且为强制终点**」：开场清理残留 merge 现场 → 合入 main → 解决冲突 → commit → 定向回归（触及文件子集 + 有界超时）；提交不可因测试未完而推迟。全量回归仍由后续 verifier 环节承担（repair 只解决冲突不改功能语义）。

## Consequences

- 真正提交过的 repair 逐字节不变（复核为纯增量校验）；tip 前进作为必要条件判据，不追求充分。
- 该裁定与 fast-track 死亡按分支提交分流、待合并活性按 git 未并入提交判据同族：**一切跨进程边界的成功/活性判定以 git 事实为准，不以声明为准**。
