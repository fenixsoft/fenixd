# judge 修复申报受理指纹门

<!-- knowledge: capability=judge-repair-claim-gate rev=1
     sources=spec/changes/evo-add-repair-claim-fingerprint-gate -->

bug-found 派发实现者修复后的申报受理门：随单附被修场景失败指纹、受理时比对新鲜侧指纹、实现者申报附真机探针义务——把「申报面全绿但真机无效」的零进展修复拦在白烧整轮重验之前。场景文件类修复的写回受理见 [judge 修复场景写回受理门](judge-repair-scenario-writeback-gate.md)。

## 规则

- **随单附派单指纹**：bug-found 路由派发实现者修复时，修复任务上下文附被修场景的失败指纹（场景 id + 失败断言签名摘要），并持久化到 spec STATE（`_repair_dispatch_fingerprint`）作受理点比对基线，注入两路派发分叉（fastlane 轻量修复与 fix SPEC 派生）；指纹口径读裁决面既有数据（verdict_cache 场景指纹 / verdict_stability 轮级 stamp），不新造指纹体系。无可附指纹（无基线的首轮修复）置 null 照常派发、受理门跳过比对，不因指纹缺失阻断。
- **受理指纹门（零进展拒收）**：框架受理 product 类修复申报时（fix SPEC 完成消费点 engine `_on_spec_done` fix-* 分支、fastlane 子集重验消费点），比对被修场景的新鲜侧指纹与派单指纹。新鲜侧指纹源优先级：实现者申报内探针标注（主）→ 盘面 post-fix 新鲜轮指纹（fastlane 子集重验 / fix SPEC 自验产出，仅当受理时点确有新鲜轮）；两者皆缺按「缺探针标注」拒收。指纹未变化（同一失败签名原样复现）即拒收本轮修复：不重入执行场景集、spec 保持当前验证态、`_record_repair_claim(rejected=True)` 记账、返回已消费信号不穿透守卫，拒收信息含「失败指纹未变化」与双方指纹值，经既有重派上下文回传下轮；指纹已变化、场景已转 pass 或无基线时照常受理。
- **受理时点缓存禁作新鲜侧**：MUST NOT 直接以 verdict_cache 最新条目作新鲜侧——受理时点重验回注未发生，缓存仍为派单同轮数据，以其比对恒等、必致无条件拒收死锁。
- **实现者探针义务**：product 类缺陷修复申报收尾 MUST 附被修场景的最小真机探针结果（针对修复后产物——重建/重载后实例或构建——的单场景执行或 API 级探针复跑）并标注探针失败签名与派单指纹是否一致；探针复现派单指纹不得申报修复成功，申报缺探针标注由受理门按指纹门同语义拒收。探针 MUST NOT 对未加载修复的旧运行实例取证（修复经 lib 重建部署+新启实例才可见，对旧实例探针会系统性误判「指纹未变化」错杀有效修复）。义务范围限被修场景，不引入全量回归义务（全量重验仍由验证链承担）。
- **预算与通道边界**：本门拒收按既有 rejected 口径记账，修复预算上限、预算记账口径与耗尽持久态语义不变；既有 test-defect 场景修复通道的三处 `_record_repair_claim` 调用点不在本门比对范围、行为零变化（场景文件类修复由 judge-repair-scenario-writeback-gate 与 revise 通道覆盖）。与路由面「失败集零进展」闸门（fix-verify-loop-convergence）互补：受理门在前（进入重验前拦单场景零进展），路由门兜底整轮失败集，两门均触管线须串行落地。

## 关键行为

受理分支顺序固定：读派单指纹（STATE 持久字段）→ 取新鲜侧（探针标注优先，其次盘面新鲜轮）→ 缺探针标注拒收 / 指纹未变化拒收（rejected 记账 + error 留痕 + 回传清单 + 不穿透守卫）/ 指纹变化或无基线照常受理进入既有后续流程。派单侧在 bug-found 派发时写指纹与上下文注入一次，受理侧每次申报消费一次。

## 代码锚点

- 主实现：`core/pm_engine/verification/repair_claim_gate.py`（`collect_failed_fingerprints` / `attach_dispatch_fingerprint` / `evaluate_fingerprint_gate` / `accept_repair_claim` / `reject_repair_claim`）
- 消费方：`core/pm_engine/verification/pipeline.py`（`_apply_bug_found` 派单侧附着、`_record_repair_claim` 指纹留痕扩展）；`core/pm_engine/engine.py` `_on_spec_done` fix-* 分支受理接线；`core/pm_engine/verification/fastlane.py` 子集重验消费点；`core/pm_engine/family.py` fix SPEC 派生上下文指纹段；`agents/implementer.md` 修复申报探针义务段

## 溯源

- 2026-11-16 evo-add-repair-claim-fingerprint-gate（spec/changes/evo-add-repair-claim-fingerprint-gate/） — 新增本能力：bug-found 随单附失败指纹（STATE 持久+两路派发注入）、product 修复申报受理指纹门（零进展拒收、受理时点缓存禁作新鲜侧）、实现者真机探针义务（限被修场景、须对修复后产物取证）。动因实测：add-session-advanced-search 申报面全绿而真机无效，白烧 impl+合入+部署+14 场景整轮重验并把 judge 重跑预算推至上限冻结，「申报受理不核效果」当日复发 6+ 次
