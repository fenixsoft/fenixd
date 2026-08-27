# Design: improve-scheduling-noise-governance

## Context

三大循环的公共特征是"框架对失败信号的语义判错导致无效功重启"：
1. 验证器把**环境性失联**（mock 断流 → SSE 不推 → DOM 等待超时）与**产品缺陷**混为一谈，13/14 失败触发 bug-found 家族链；
2. 派发器把「比它重要」静态地当成「永远压制」，P6 在 P4/P5 家族持续占用下饿死；
3. 族谱自动繁衍把一次验证失败的修复成本乘上嵌套深度。

既有修补边界：fix-dispatch-orphan 已保证事件必达与扫描韧性；improve-run-lifecycle-governance 负责运行超时活性与锁一致性。本变更处理「判定语义 × 公平性 × 收敛性」，与其正交。

## Goals / Non-Goals

**Goals:**
- mock 环境下的 DOM/SSE 超时不再直接判 fail；整批环境性失联可整体重验且不烧 repeated_failures 信号
- 任何队列条目存在有限等待内的派发窗口上界
- 族谱自动繁衍有硬上限，越界转人工
- 今日两份真实失败 report 作为回归 fixture

**Non-Goals:**
- 不改动 verifier 提示词主结构 / 场景生成（planner）流程
- 不实现成本视图与 failover（独立后续 SPEC）
- 不放宽 approve 门禁

## Decisions

- **D1 探针判定归属 verify_engine 判定层而非 prompt。** 场景结算后统一后置分类：若步骤序列含 `mock_api` 且断言错误类型属于 `Locator.wait_for/Timeout` 纯等待类，触发环境探针（对 dashboard 实例 `/api/state` 或等价端点发起连通+时延检查）。探针失败 → blocked-env；探针成功 → 维持 fail（此时确属真缺陷或慢场景）。理由：prompt 层注入会让 LLM 判定不可测，后置分类纯函数可单测。
- **D2 blocked-env 的门禁换算规则。** summary 新增 `blocked_env` 计数；`failed = raw_failed - blocked_env`；当 `passed + warnings >= total - blocked_env` 且 raw_failed 全部为 blocked-env 时整体 `inconclusive`：状态机回 testing 重派新 attempt，重复上限沿用 attempts=3 但**不向 admin store 发 repeated_failures 信号**（新增信号抑制标记随 run 结果传递）。防误伤：同一场景第二重验仍探针通过则按真 fail 处理。
- **D3 队列条目携带 enqueued_at。** `_run_queue` 条目从 (priority, spec, type) 扩展为含 time.time()；`_process_queue` 比较时计算 `effective_prio = base + min(floor_levels, max(0, int((now-enqueued_at-initial_wait)/step_down)))`。内存态实现、不持久化——daemon 重启视为等待清零，代价可接受（重启本就罕见）。活动任务不计老化。
- **D4 族谱度量基于命名前缀 + 同父计数。** 深度 = 名字中连续 `fix-` 前缀层数（fix-fix-x = 2）；宽度 = read_all 中同父（strip 一层 fix- 后同名开头匹配）且未完成子代数量。超限路径在 `_on_spec_bug_found` 创建前拦截：不改父状态、不发 spec_bug_found 处理副作用，转而调用 admin_store.signal(kind=family_explosion, severity=major)；Administrator 放行动作执行后设置该父 SPEC 的豁免位 `_family_waiver=true` 允许下一轮继续一次。
- **D5 回归 fixture 直接入库真实样本。** `.fenix/tests/fixtures/report_0827_noise.json`（13/14 样本脱敏）驱动 D1 分类断言：预期 ≥12 个转为 blocked-env。

## Risks / Trade-offs

- [D1 探针把真·极慢页面误标] → 仅当「mock_api 存在 + 纯等待类超时 + 探针失联」三条件同时成立才降级
- [D3 老化使低优任务挤占高优窗口] → floor 默认 +4 级（P6 最低到 P10），高优家族仍天然先占
- [D4 宽度统计受同状态重置清理影响低估] → 统计口径用 STATE 全量 read_all（含 bug-found 父），不受 ready 清空字段影响
- [ Administrator 未部署时 family_explosion 无人处置] → 沿用现有 escalation_to_human 升级链

## Migration Plan

普通代码变更，daemon 重启生效；config 缺省行为下 aging 关闭键（enabled=false 时 effective==base）保持向后兼容。回滚 revert 即可。

## Open Questions

- 无
