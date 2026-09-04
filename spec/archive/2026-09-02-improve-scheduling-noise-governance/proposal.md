# Proposal: improve-scheduling-noise-governance

## Why

2026-08-27 实证三大空转循环吞噬墙钟与 token：scene-based 验证器在 mock_api 斩断 SSE 的环境下产生整批假阴性（本轮 13/14、姊妹轮 4/5 场景失败），每次假阴性都派生 fix 子 SPEC 空转完整实现+验证周期；宽松优先级规则令 P6 条目被持续的更高优先级活跃任务无限压制（一个 verifier 入队数小时零派发窗口）；bug_found 自动派生无族谱收敛约束（add-dashboard-spec-doc-tabs 系四层、fix-dispatch-orphan 系三层嵌套）。用户反馈单个 SPEC 处理超 10 小时、token 成本不可承受，三者正是最大消耗源。

## What Changes

- **验证环境健全性门**：场景步骤含 mock_api 且最终断言为纯 DOM/SSE 等待超时时，先做环境健全性探针；证实环境性失联的场景记 `blocked-env` 计入 warning 不计入 fail；summary 新增 blocked_env 统计；全场景均 blocked-env 时整体判 inconclusive 并重新派发验证（不计入 repeated_failures 信号）。
- **派发队列老化**：队列条目记录入队时间，等待超过阈值后每隔 N 分钟等效降一级优先级直至下限，使被压制条目在持续高优任务占用下仍能获得窗口。
- **fix 族谱收敛治理**：自动创建 fix 子 SPEC 前计算族谱深度（fix- 前缀层数）与宽度（同父未完成子代数），超过 max_depth=3 / max_width=2 时停止自动繁衍，转发 family_explosion 困境信号交 Administrator 处置，人工放行后计数复位继续。

## Capabilities

### New Capabilities
- `verify-environment-sanity-gate`: mock 环境下 DOM/SSE 超时断言的健全性探针与 blocked-env 降级判定
- `dispatch-queue-aging`: 派发队列按等待时长的老化让位机制
- `fix-family-convergence-governor`: bug_found 派生的深度/宽度上限与人工处置升级

### Modified Capabilities

<!-- openspec/specs/ 为空；与 fix-dispatch-orphan 已合入的事件投递/隔离修补正交，
     与 improve-run-lifecycle-governance 的活性监督/巡检互补不重叠 -->

## Impact

- **代码**：`.fenix/core/verify_engine.py`（场景判定分类）、`.fenix/core/agent_runner.py`（verifier 提示词/环境探针步骤注入）、`.fenix/core/pm_engine.py`（_run_queue 结构与 _process_queue 判定、spec_bug_found 处理器接线、admin 信号扩展 family_explosion）
- **配置**：`pm.dispatch.aging.*`（initial_wait_minutes / step_down_minutes / floor_levels）与 `pm.family.max_depth / max_width`
- **测试**：tests/test_core.py 与 verify 相关用例扩展；今日真实 report.json 入库为回归 fixture
