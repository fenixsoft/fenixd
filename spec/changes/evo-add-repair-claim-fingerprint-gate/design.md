# design — add-repair-claim-fingerprint-gate

## 背景

2026-11-12 add-session-advanced-search 的 ctx.get 修复环实证：申报面（tsc/vitest/产物核验）全绿而真机无效，受理面无效果核验，无效修复环白烧整轮重验并把 judge 重跑预算推至上限冻结。核查确认：_apply_bug_found（pipeline.py:1214-1262）不随单附指纹、_record_repair_claim（pipeline.py:3971）仅 id 级摘要、implementer.md 无探针义务。

## D1 指纹数据源与口径

- 比对口径复用盘面既有数据，不新造指纹体系：verdict_cache.json 每场景 definition/build/verify_config 四元组指纹 + verdict_stability.json 轮级 stamp 已是裁决面权威（实测 dg=143de6fb3cc9cc7c，两轮 stamp ef83e42b→9769c8b2）。
- 随单附「派单指纹」= bug-found 裁决时被修场景的失败签名摘要（场景 id + 关键断言 actual/expected 截断），从裁决产物读取；缓存命中/无基线置 null，受理门跳过比对。
- 窗口语义：比对「被修场景」的单场景指纹，非整轮失败集——整轮失败集零进展的路由面治理由在途 SPEC fix-verify-loop-convergence 承担，两门互补不重叠。
- 新鲜侧指纹源优先级（D2 比对的新鲜侧数据源）：①实现者申报内的探针标注（主源，见 D3）；②盘面 post-fix 新鲜轮指纹（fastlane 子集重验 / fix SPEC 自验产出，仅当受理时点确有新鲜轮）；③两者皆缺 → 按「缺探针标注」拒收（与 D3 同语义）。MUST NOT 直接以 verdict_cache 最新条目作新鲜侧——受理时点重验回注未发生，缓存仍为派单同轮数据（save_verdict_cache 每轮采纳后整体重写，core/verdict_check.py:2158），以其比对恒等、必致无条件拒收死锁。

## D2 受理门接线

- 插入点：product 类修复申报受理点——fix SPEC 完成消费点 `engine.py _on_spec_done` fix-* 分支（父 SPEC 重验回注之前）与 fastlane 子集重验消费点，两处**新增** `_record_repair_claim` 调用并做记账前置比对（先读随单指纹与新鲜侧指纹源，见 D1 优先级；未变化即走拒收分支）。既有三处调用点（pipeline.py:1970/2007/2029，test-defect 场景修复通道）不在本门比对范围、行为零变化（与非目标一致）。
- 拒收分支复用 judge-repair-scenario-writeback-gate 已验证的接线形态：error 留痕（含「失败指纹未变化」+双方指纹值）、spec 保持当前态、`_record_repair_claim(rejected=True)`、返回消费信号不穿透守卫；拒收信息经既有重派上下文回传下轮。
- 指纹已变化/无基线/场景已 pass：照常受理，行为零变化；预算上限与耗尽态语义不动。

## D3 实现者申报义务

- agents/implementer.md 修复申报段追加：product 类修复申报前对被修场景做最小真机探针（单场景执行或 API 级探针），申报附探针签名与派单指纹的一致性标注（标注落 impl-result 申报约定字段，字段缺失即「缺探针标注」）；探针复现派单指纹不得申报 success。探针 MUST 针对修复后产物取证（worktree 重建/重载后的实例或构建），不得对未加载修复的旧运行实例复跑——本案事故中修复经 lib 重建部署+新启实例才可见（proposal Why），对旧实例探针会系统性误判「指纹未变化」错杀有效修复。
- 机械面：申报缺探针标注由受理门按指纹门同语义拒收（不新增 result_gate 硬门，避免与 code-review 车道共用面纠缠）；义务范围限被修场景，不引入全量回归义务。
- 成本边界：单场景/API 探针成本远低于整轮重验白烧（本案环代价=impl+合入+部署+14 场景执行+2 个 arbiter run）；探针失败本身即有效产出（受理门止损信号）。

## D4 与在途 SPEC 的协调

- fix-verify-loop-convergence（在途）：路由面「失败集零进展升闸门」，本门受理面「申报指纹门」——同一环两道闸，受理门在前（进入重验前），路由门兜底；两案均触 pipeline.py，实现须串行（本门后落地时以在途案合并后的管线为基线）。
- judge-repair-scenario-writeback-gate（已归档合入，spec/archive/2026-11-16-judge-repair-scenario-writeback-gate）：场景写回结构校验门，与本门同用拒收接线形态（rejected 记账、回传清单、不穿透守卫），分支样式已落地 pipeline.py:1988-2026 可直接参照。
- judge-rerun-budget（草稿队列）：预算豁免/计数面语义，与本门无文件级冲突（本门不改 judge_gate.py 计数）。

## 非目标

- 不改 judge 重跑预算计数与冻结语义（属 judge-rerun-budget 草稿主题）
- 不改 fail_history/verdict_cache 的产出侧结构（只读消费）
- 不处理场景文件类修复（test-defect）的指纹比对——该面由 judge-repair-scenario-writeback-gate 与 revise 通道覆盖；本门仅对 product 类缺陷修复生效
- 不要求实现者执行全量回归