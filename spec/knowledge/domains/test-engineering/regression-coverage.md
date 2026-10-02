<!-- knowledge: capability=regression-coverage rev=1 sources=spec/archive/2026-09-13-add-lost-semantics-regression-tests -->

# 语义回归覆盖

一组回归测试锚定的引擎不变量：replan 循环上限、熔断期 verifier 状态、验证失败归一计数与截图时机门禁。这些语义一旦被改动即在测试层立即暴露。

## 现行规则

- replan 循环上限：planner 连续产出不合格结果时，replan/重派循环有可验证的上限行为——达到上限后不再发起新一轮 planner run，最终状态为上限退回形态（blocked/人工升级/显式终止之一）且该转换有日志或状态记录可断言；某轮 replan 产出合格结果后循环计数归零，后续独立失败从零起算。
- provider 熔断隔离：ProviderCircuit 对当前 provider 处于 open 状态期间的 verifier run 失败归类为基础设施失败——spec 状态保持原状（testing/在跑态），不发生 →bug-found 迁移，`_verify_fail_rounds` 不递增，失败按基础设施口径记录（告警/日志可断言）。
- 验证失败形态归一：verifier run 异常、verdict bug-found、结果文件缺失或畸形三类失败形态统一归一到同一失败信号（bug-found 语义的打回/计数路径，打回注入的「验证修复」任务段语义一致），各自使 `_verify_fail_rounds` +1；任一失败后下一轮验证通过（verified）时 `_verify_fail_rounds` 归零。
- 截图时机门禁：verify_engine 的截图产物与断言执行绑定——断言未执行（浏览器未到达断言阶段/场景被跳过/前置失败）时不产生该场景的截图文件与截图事件，验证产物截图清单不含该场景；断言执行并失败时产生的截图能与该场景/断言关联（文件名或元数据含场景标识），供裁决证据链使用。

## 溯源

- 2026-09-13 add-lost-semantics-regression-tests（spec/archive/2026-09-13-add-lost-semantics-regression-tests） — 新增四组语义回归测试，锚定 replan 上限退回、熔断期状态保持、失败形态归一计数与断言绑定截图门禁
