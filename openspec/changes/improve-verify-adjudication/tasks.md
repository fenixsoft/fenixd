# Tasks: improve-verify-adjudication

## 1. report.json 质量闸门

- [ ] 1.1 在 core/dashboard/data.py 或 pm_engine 内新增 report.json 解析 helper：读取 `.fenix/verify-progress/<spec>/report.json`，返回 `{summary, scenarios}`；缺失/损坏返回明确标记（复用 dashboard data 现有容错风格）
- [ ] 1.2 实现 `_check_report_quality_gate(spec_name)`：全部 pass → 放行；存在 fail → 返回拦截文案（含失败场景数）；report 缺失但验证已启动 → 拦截（fail-closed）；无验证痕迹 → 放行不介入
- [ ] 1.3 失败分流：`assertion_results` 为空或 `step_results` 含 `success:false` → 工具噪音；有实败断言 → 产品缺陷。两种失败并存按产品缺陷从严
- [ ] 1.4 噪音路径：写 error 字段 + 触发 human-escalation-alerts 告警（附场景 id 与 step 中断详情），SPEC 滞留 verified；不触发 bug-found
- [ ] 1.5 缺陷路径：维持现行 bug-found 派生 fix SPEC 流程，派生材料携带实败断言证据
- [ ] 1.6 将新 blocker 并入 `_on_spec_verified` 的门禁合并逻辑（pm_engine.py:147-162），合并单条 error 不互相覆盖

## 2. verifier 结果文件 fail-closed

- [ ] 2.1 `_read_verifier_result` 三态化：有效 status / 结果缺失标记 / 异常标记；白名单不变，移除「未知状态视为 verified」语义及其 docstring 承诺
- [ ] 2.2 调用方（含 `_read_planner_result` 回退路径）适配三态：缺口时写 error 字段并升级 Administrator 告警，SPEC 保持原状态
- [ ] 2.3 项目根回退文件的「spec 残留护栏」逻辑保持不变，新增缺口分支不得绕过该护栏

## 3. fix 链回归继承

- [ ] 3.1 定义 `regression-inherit.json` 结构 `{parent_specs: [{spec, failed_ids, unexecuted_ids}], exempted: [{scenario_id, reason, by}]}` 与读写 helper
- [ ] 3.2 fix SPEC 派生时（`_ensure_fix_spec_files` / `_do_spec_bug_found`）：从父 report 计算 failed + unexecuted 场景集，多级 fix 取逐级并集，写入清单文件并在 proposal.md/tasks.md 标注必测项
- [ ] 3.3 fix SPEC 放行校验：验证本轮 report.json 覆盖且通过全部继承场景；缺口写入 error（格式「回归闭环缺口：<scenario_id>」）并拦截
- [ ] 3.4 豁免机制：读取清单文件中带理由的豁免记录视为闭环；豁免文件若与父 report 重算不一致则告警（防 agent 误改）

## 4. 测试与验收

- [ ] 4.1 单元测试：质量闸门三分支（全过放行 / 有 fail 拦截 / report 缺失 fail-closed）与噪音/缺陷判定规则（以本次事件真实样本形态构造 fixture：step 中断缺 target、assertion_results 为空、实败断言）
- [ ] 4.2 单元测试：result 文件缺失 / JSON 非法 / 白名单外 status 三态行为与告警触发
- [ ] 4.3 单元测试：回归清单注入（一级/多级 fix）、闭环校验拦截与放行、豁免留痕生效
- [ ] 4.4 验收实测：对一个带已知工具噪音失败的 SPEC 走通完整流程——滞留 verified、产生告警、admin 修正场景后重跑放行；确认无伪 fix 诞生
