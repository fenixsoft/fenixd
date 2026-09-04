# Tasks: fix-push-ref-lifecycle

## 1. 推送核心重构（design D1/D2）

- [x] 1.1 `_git_push_branch`/`_resolve_push_branch` 重构为 main 优先 + 分支尽力；实现 `_remote_branch_sha(branch)` 助手（ls-remote 查询）；补单测（正常 FF / 非 FF 拒绝 / 分支去重三分支 / 本地分支缺失跳过）
- [x] 1.2 approve_push 集成新判定：成功清 error 推进 pushed；失败写退避标记进 error 文本；补单测（成功清痕 / 失败留退避标记）

## 2. 退避收敛与重放去重（design D3/D5）

- [x] 2.1 实现 push 退避状态（next_retry_at 记于 error 文本约定格式）与 recovery 重放跳过；config `pm.push.*` 默认值；补单测（退避期内跳过 / 退避到期重试 / 连续 3 次升级 push_failed 信号且停止）
- [x] 2.2 config.yaml 增补 pm.push 注释与默认值；push_failed 信号在既有 activity view 可见（手动冒烟）

## 3. 残痕回填（design D4）

- [x] 3.1 实现幂等回填清理函数（pushed + git push failed 前缀 → SHA 验证 → 清 error；不可验证保留+清单日志）；补单测（可验证清除 / 不可验证保留）
- [x] 3.2 对现存 2 条残痕（improve-scheduling-noise-governance、fix-fix-dispatch-orphan）执行回填并记录结果

## 4. 回归与核验

- [x] 4.1 全量 pytest 通过（重点 tests/test_core.py pm_engine push 相关及新增用例），无既有用例回归
- [x] 4.2 对照 capability spec 全部 Scenario 逐条核对实现覆盖并记录结论
