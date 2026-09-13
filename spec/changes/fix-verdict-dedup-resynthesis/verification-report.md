# 验证报告：fix-verdict-dedup-resynthesis

> ⚠️ 本报告由框架于 2026-09-11T04:20:13Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 11/11 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 11/11 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 11 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.92M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| dedup-normalization-cascade-exemption | 归一化细分与级联豁免用例组（8 用例全绿）：5 个场景共享根因但步骤序号/断言 label 各异 → 放行（单根因级联合法形态）；同步骤断言各异 → 放行（OR 语义）；同步骤同断言 → 仍拒（模板偷懒）；无步骤无断言同文 → 仍拒；2 场景边界放行 + 4 场景同文拒绝（threshold=3 不变）；豁免仅同 classification 生效；描述体前缀重合<80% 不豁免。覆盖 D3 归一化细分规格（core/verdict_check.py:662-860；tests/test_verdict_credibility_gate.py::TestDedupNormalizationCascadeExemption） | pass | 0/6 | - |
| dedup-threshold-three-boundary | 查重阈值边界与既有路径回归（5 用例全绿）：2 个场景同文不拒、3 个场景同文拒（≥3 阈值不变）、空白归一化后同文仍拒、不同归因放行、pass 场景排除不计。覆盖 D3 阈值不变约束（core/verdict_check.py:815-860；tests/test_verdict_credibility_gate.py::TestBatchAttributionDedup） | pass | 0/5 | - |
| resynthesis-rejection-artifacts-and-adopts | 重合成闭环正向（2 用例全绿）：查重拒绝 → verdict_violations.json + dedup_resynthesis_directive.json 落盘（派发瞬间取证，重合成 prompt 注入源在盘）→ 派发重合成 judge run 恰一次 → 差异化写回 → 回灌采纳 cause=pass → 采纳后清理 violations/directive → spec 保持 testing 由调用方推进。覆盖 D1/D2 闭环（core/pm_engine/verification.py:3349-3505；tests/test_verdict_dedup_resynthesis.py::TestRejectionWritesArtifacts + TestResynthesisAdopts） | pass | 0/3 | - |
| resynthesis-escalation-budget | 重合成预算与升级（2 用例全绿）：连续 2 轮重合成仍同文 → blocked + verdict_dedup_resynthesis_exhausted critical 告警 + error 含违规摘要 + run_planner.call_count==2（预算生效、MUST NOT 无限重试、不再派第 3 轮）；重合成 1 轮即修复 → 不升级、告警零调用（预算未触发）。覆盖 D2 升级语义（core/pm_engine/verification.py:3378-3396；tests/test_verdict_dedup_resynthesis.py::TestResynthesisEscalates） | pass | 0/3 | - |
| resynthesis-dispatch-branches | 重合成派发边界分支（5 用例全绿）：frozen 门拦截 → 让位（cause=dispatch_frozen、不写 blocked、不发告警）；取消旗标 → 让位（cause=dispatch_cancelled、保持 testing）；派发异常 → dispatch_exception 早退（不复读旧 report、不打假 ERROR、report 原样保留）；派发失败（非 frozen/取消）→ dispatch_failed 温和处置（保持 testing）；重合成成功但产物不可读 → report_missing（fail-closed 非违规）。覆盖 D1 复用 judge 通道防御语义（core/pm_engine/verification.py:3349-3505；tests/test_verdict_dedup_resynthesis.py::TestResynthesisDispatchBranches） | pass | 0/5 | - |
| resynthesis-incident-replay | 事故形态回放集成（2 用例全绿）：16:39 形态（5 场景模板归因被拒 → 重合成差异化 → 采纳推进、不自锁、只派发 1 轮、spec 保持 testing 由调用方推进、全程不触发全量验证重跑）；15:53 形态（23 连同文真偷懒 → 重合成仍同文 → blocked 升级 + error 含违规摘要、告警恰一次、MUST NOT 无限重试）。覆盖 5.1 事故回放集成链路（core/pm_engine/verification.py:3349-3505；tests/test_verdict_dedup_resynthesis.py::TestResynthesisIncidentReplay） | pass | 0/3 | - |
| prompt-directive-injection | 重合成 prompt 注入与 judge 契约（6 用例全绿）：directive 文件存在 → 注入段含被拒场景清单/失败步骤序号/断言 label 差异化素材/MUST NOT 套用共享模板串契约；directive 缺失 → 空串（普通裁决轮零注入）；directive 损坏 → 空串（fail-open）；rejection 段渲染查重违规条目（scenario_ids 列表 + 轻量重合成纪律）+ 单场景条目不回归；planner-judge.md 含归因文本契约段（共享根因合法、first_failed_step/triage evidence 引用本场景局部数据、禁 error[:120] 截断同文）。覆盖 Requirement: 重合成定向指令注入 + judge 归因文本契约（core/agent_runner/prompt_builder.py:1034-1095 + :967-1032；agents/planner-judge.md:106-108；tests/test_verdict_dedup_resynthesis.py::TestResynthesisPromptInjection） | pass | 0/5 | - |
| retry-status-recheck-matrix | in-place retry 派发前状态复查矩阵（8 用例全绿）：judge 预期 testing，spec blocked → 让位；spec 仍 testing → 照常重试；implementer 预期 implementing，testing（被移出）→ 让位；implementing → 照常重试；frozen → 让位（既有语义保持）；_cancelled_hold 取消保持态 → 让位（自动重派不得复活有意保持的 spec）；checker 自身异常 → fail-open 返回 False（保持既有重试语义）；未映射 agent_type（如 administrator）不判 status 保持现状。覆盖 D4 预期态映射（core/agent_runner/runner.py:120-127 EXPECTED_SPEC_STATUS_BY_AGENT + :3164-3235；tests/test_verdict_dedup_resynthesis.py::TestRetryStatusRecheck） | pass | 0/6 | - |
| retry-in-place-wiring | in-place retry 4.2 接线验证（2 用例全绿）：provider-transient 瞬断进入退避、期间 spec 被置 blocked → 退避结束后复查命中让位（只派发 1 次、不产生新的 transient_retry 轮、result.error 含 [retry-yielded] 与 已被接管——19:48 事故 $4.77 白烧根因消除）；provider-transient 瞬断退避、期间 spec 仍 testing → 照常原地重试（call_count>1、重试轮写合法产物后 result.success=True）。覆盖 D4 接线（core/agent_runner/runner.py provider-transient 通道退避重派前复查；tests/test_verdict_dedup_resynthesis.py::TestInPlaceRetryYields） | pass | 0/3 | - |
| log-wording-refused-adoption | 拒绝语义文案修正（D5）：源码中查重拒绝日志使用「拒绝采纳」而非「拒绝落盘」（report.json 已在盘上、拒绝的是状态机采纳）；「judge 下轮修文后自然通过」类不存在的回路描述已改写为 D1 真实重合成回路描述（注释与实际回路一致）。覆盖 Requirement: 拒绝语义文案修正（core/pm_engine/verification.py 查重拒绝分支日志 + core/verdict_check.py 注释；文案证据见 verification.py:1818/3320/3394/3408/3620 等「拒绝采纳」行） | pass | 0/6 | - |
| full-dedup-resynthesis-suite | 全量 test_verdict_dedup_resynthesis.py（27 用例全绿）：拒绝落盘+差异化采纳、冻结/取消/异常/产物缺失分支、连续拒绝升级预算、prompt 注入两态+rejection 双形态、16:39/15:53 事故回放集成、in-place retry 矩阵+接线。覆盖 5.2 任务组指定测试全绿（impl-result 216 passed 子集——本文件 27 用例整体通过） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 11 个（第 1 轮）。

- 首轮写入 11 个场景

