# 验证报告：evo-deliverable-declaration-drift-align

> ⚠️ 本报告由框架于 2026-09-19T00:41:50Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-19T00:41:50.630296+00:00

## 结论：✅ 通过（verified）

**状态：verified — 17/17 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 17/17 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 3.29M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| drift-locate-real-unpack-unique | 候选定位-真实拆包形态唯一命中：core/worktree_manager.py 与 core/pm_engine/dispatch.py 拆包后，分支改动集合内包目录唯一改动被定位为候选落点（_locate_drift_target，core/deliverables.py:1681；测试 tests/test_deliverable_drift_align.py:113/128 真实拆包取证） | pass | 0/3 | - |
| drift-locate-fail-open-zero-multi | 候选定位-fail-open：零候选（分支改动集合无包目录 .py）、多候选（包内改动模块≥2）、非 .py 声明路径均不产生可对齐候选（core/deliverables.py:1701-1717 规则 1/3，MUST NOT rglob 兜底；测试 :143/165/176） | pass | 0/4 | - |
| drift-detect-drift-feature-hit | 漂移特征判定-命中：kind=modify 且主树/分支 HEAD 均缺该路径且 git 历史命中 → drift=True 并附候选清单与历史命中数（is_drift_candidate，core/deliverables.py:1720；测试 :193） | pass | 0/2 | - |
| drift-detect-exclusion-cases | 漂移特征判定-排除：历史零命中（孤儿特征）、实现分支 HEAD 已落地、kind=new、分支缺失（无法判定）均判非漂移，保守 fail-open 不改写（core/deliverables.py:1744-1779 条件 1/2/3；测试 :210/218/237/249） | pass | 0/5 | - |
| drift-align-unique-rewrite-proceed | 对齐执行-唯一候选机械改写放行：_preclassify_drift 唯一候选且分支 HEAD 存在 → 生效声明改写为新落点（kind 保持、旧路径移除）、spec 置 implementing、error 清除（core/pm_engine/dispatch/adjudication.py:691；测试 :374） | pass | 0/2 | - |
| drift-align-audit-relocation-verdict | 对齐执行-审计留痕：dispute_audits.jsonl 落 type=relocation + verdict=drift-aligned + actual_path + 候选唯一性证据（history_hits/merge_base/candidates）+ 非单调 before/after diff（adjudication.py:691；测试 :411） | pass | 0/2 | - |
| drift-align-rewrite-committed | 对齐执行-改写后立即提交：生效声明 tasks.md 已提交（防 merge-back dirty 死锁）、无残留未提交改动（_commit_softened_declaration，adjudication.py:289；测试 :454） | pass | 0/2 | - |
| drift-align-fail-open-fallback | 对齐执行-fail-open 回人工：零候选/多候选/候选不在分支 HEAD/声明段无该条目均不机械改写，声明原文保留（adjudication.py:775-823；测试 :487/505/535/606） | pass | 0/5 | - |
| drift-align-branch-source-credential | 对齐执行-分支来源凭据登记：spec_dir=None（生效声明来源为分支版本、无落盘位置）→ 走 register_relocation_credential 凭据登记、MUST NOT 直写主树声明、审计落 relocation 记录（adjudication.py:731；测试 :559） | pass | 0/2 | - |
| drift-align-remaining-gate-continue | 对齐执行-余缺件续走：对齐后守卫重跑仍有缺件 → continue 携 remaining_missing/remaining_disputed 交调用方续走既有路径（adjudication.py:857-867；测试 :628） | pass | 0/2 | - |
| superseded-convergence-block-source-pass-target | 同源草案收敛-拦截面：本目录含 SUPERSEDED.md → blocked（error=同源草案收敛义务未满足，附 SUPERSEDED.md 路径）；被显式点名（inline code/路径形态）的生效落点 MUST NOT 被拦截，名字归一仅识别平级同名草案（core/pm_engine/engine.py:766 _check_superseded_convergence；测试 :698） | pass | 0/2 | - |
| superseded-on-spec-ready-blocks-source | 派发前拦截-主入口：_on_spec_ready 派发 implementer 前发现本目录含 SUPERSEDED.md → 置 blocked、不入队 _enqueue 未被调用（core/pm_engine/engine.py:623/715-746；测试 :737） | pass | 0/2 | - |
| superseded-on-spec-ready-dispatches-target | 派发前拦截-生效落点放行：_on_spec_ready 对 -575976（被点名生效落点、自身无 SUPERSEDED.md）正常派发 implementer、状态保持 ready（engine.py:747-767；测试 :753） | pass | 0/2 | - |
| superseded-process-queue-bypass-guard | 派发前拦截-旁路兜底：_process_queue 候选筛选对旁路直入队列（不经 _on_spec_ready）的收敛源条目同口径拦截——移除队列条目、置 blocked、不启动 worker（core/pm_engine/dispatch/queue.py:357-398；测试 :770） | pass | 0/2 | - |
| superseded-removal-restores-dispatch | 收敛完成恢复：SUPERSEDED.md 移除后 _check_superseded_convergence 不再拦截，派发恢复（engine.py:812-818 收敛完成信号；测试 :722） | pass | 0/2 | - |
| drift-align-full-suite | 全量回归：tests/test_deliverable_drift_align.py 24 用例全过（漂移判定/候选定位/对齐执行/同源收敛全链，tasks.md 3.1/3.2 测试交付物） | pass | 0/2 | - |
| drift-adjacent-declaration-suite-regression | 相邻通道回归：deliverables.py 改动未破坏既有孤儿预分类（test_deliverable_orphan_preclassify.py）与声明解析/重定位协议（test_declaration_relocation.py、test_declaration_resolution.py）共 60 用例（与 _preclassify_drift 互斥、单轮单通道） | pass | 0/2 | - |

## 本轮场景集变更

当前稳定场景集共 17 个（第 1 轮）。

- 首轮写入 17 个场景

