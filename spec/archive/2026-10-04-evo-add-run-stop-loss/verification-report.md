# 验证报告：evo-add-run-stop-loss

> ⚠️ 本报告由框架于 2026-09-25T21:16:39Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-25T21:16:39.361449+00:00

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 4.22M |
| 本链增量 Token（输出） | 0.07M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| stoploss-cancel-in-gap-registers-and-blocks-revival | CLI：attempt 间隙取消拦截复活 attempt——cancel_run 未命中活跃 attempt（not_running）时仍按 base_id 登记取消旗标（含 reason/by 元数据，带 -a1 后缀入参经归一化收敛），随后复活 attempt 经启动守卫 _attempt_top_guards 命中旗标以 cancelled 终态有序收尾、不再执行 provider 轮次，守卫收尾旗标清理无泄漏（SPEC「attempt 间隙取消拦截复活 attempt」；锚点 core/agent_runner/runner.py:717 cancel_run、:745 not_running 分支、:3200 _attempt_top_guards、:684 _normalize_run_id） | pass | 0/2 | - |
| stoploss-cancel-active-attempt-unchanged | CLI：活跃 attempt 取消行为不变（回归）——cancel_run 命中在飞 attempt 时保留 cancel_requested 语义（返回 attempts 列表与 base_run_id、登记旗标由属主线程终止），且 base 前缀不误伤同前缀更长 run_id（SPEC「活跃 attempt 取消行为不变」；锚点 runner.py:738 matched_attempts 边界匹配、:752 旗标登记、:791 返回结构） | pass | 0/2 | - |
| stoploss-cancel-flag-idempotent-and-no-leak | CLI：取消旗标幂等与跨 run 不泄漏（异常/回归路径）——同 base 多次 cancel（含 -a2-r1 复合后缀归一化形态）幂等收敛单键；另一 run 未登记不受影响；_cancel_clear 幂等清理且只清本 run，收尾无残留（SPEC 要求 1「MUST NOT 产生跨 run 旗标泄漏」；锚点 runner.py:684 _normalize_run_id、:711 _cancel_clear） | pass | 0/2 | - |
| stoploss-retry-yields-on-discarded-marker | CLI：已隔离的并行出题 run 不再重派——经 PMEngine 装配注入并行出题标记读取回调后，标记 status=discarded 时让位判据 _parallel_plan_marker_discarded 对 planner-plan 判定让位、在途（dispatched）与非枚举状态（quarantined；写侧实际枚举 dispatched/failed/discarded/completed，隔离伴生写入即 discarded）不误伤、gating 仅 planner-plan、未注入回调（缺省 None）行为不变（in-place retry 放弃重派、run 以 cancelled/failure 收尾的前提）（SPEC「已隔离的并行出题 run 不再重派」；2026-09-26 裁决原地修复：探针由误绑 _should_give_up_before_retry 改绑实现判据 _parallel_plan_marker_discarded，quarantined 幻觉枚举改为非枚举 fail-open 断言；锚点 core/agent_runner/runner.py:4923、:3095、:3325、core/pm_engine/engine.py:370 装配注入） | pass | 0/2 | - |
| stoploss-retry-proceeds-on-inflight-or-missing | CLI：正常重试不受影响（回归+异常路径）——并行出题标记在途（dispatched/completed）、缺失、损坏（非法 JSON 按无标记）时让位判据不命中；gating 仅对 planner-plan 生效（implementer 不受 discarded 影响）；未注入回调（缺省 None）时行为与现状一致（SPEC「正常重试不受影响」；design D2-B「缺省 None 时视为无标记、行为不变」；锚点同上） | pass | 0/2 | - |
| stoploss-stall-budget-config-default-off-and-coercion | CLI：停滞预算配置规范化（缺省关闭+非法回退）——agents.run_stall_budget_enabled/stalls/window_minutes 三键：缺省（无配置）解析为关闭；合法值透传（enabled=true、stalls=3、window_minutes=10）；非法值（banana/-5/abc）回退缺省且解析不抛异常；优先探测 ConfigLoader 专项访问器、缺访问器则经 resolve_config 全局规范化双路径兼容（SPEC 要求 3「缺省关闭」；tasks 2.2；锚点 core/config.py:2451 ConfigLoader.get、:366 resolve_config） | pass | 0/2 | - |
| stoploss-stall-budget-wiring-pinned-keys | CLI：停滞判停接线守卫（源级锚点）——runner.py 经 tasks 2.2 单点归一化访问器 ConfigLoader.get_run_stall_budget_config 消费停滞预算配置、判停挂在既有 latency_state 采样点旁；core/config.py 归一化三枚 agents.run_stall_budget_* 点号键（单源）；停滞预算路径不触碰 AdminStore/alert（SPEC 要求 3「复合判停+不新增 admin 告警」；2026-09-26 裁决原地修复：锚点由「runner.py 内嵌点号键字面量」改指 2.2 设计的正确层——单点归一供消费（runner.py:5037），点号键归一单源在 core/config.py:247-266，断言强度守恒（消费侧+归一化侧双锚点）；锚点 runner.py:5037、:4461 run_stall_budget_hit；tasks 2.1/2.2） | pass | 0/2 | - |
| stoploss-stall-criteria-implementer-suite-green | CLI：实现侧守卫套件全绿——tests/test_run_stop_loss.py 经 pytest 全量通过，覆盖 tasks 3.1-3.3 的细粒度单元：attempt 间隙取消路径、discarded/quarantined 让位与在途/缺失重试照常、活跃 attempt 取消不变、停滞判据复合命中/不命中/慢而健康不误杀/缺省关闭/非法配置回退（SPEC 三要求的判据级覆盖由实现侧套件承载；本场景以 exit_code 仲裁，规避 pytest 输出形态漂移） | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

