# 验证报告：evo-add-codefix-batch-wip-precheck

> ⚠️ 本报告由框架于 2026-09-24T10:06:21Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-24T10:06:21.639795+00:00

## 结论：✅ 通过（verified）

**状态：verified — 8/8 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 8/8 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 8 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 1.46M |
| 本链增量 Token（输出） | 0.03M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| wip-precheck-overlap-defers-batch | WIP 重叠整批推迟：主树脏 tracked 文件与候选批条目 file 重叠时，checkpoint 返回未触发（reason=wip_overlap_at_select）、不投递批任务、不置单飞、progress 写 blocked+交集文案、台账条目保持 open；含批内部分重叠变体（文案只列重叠文件）。出处 tests/test_code_fix_wip_precheck.py:86 TestWipOverlapDefersBatch，实现 core/code_fix.py:1462（checkpoint 预检推迟出口）、:1228（_wip_overlap_at_select） | pass | 0/3 | - |
| wip-precheck-no-overlap-dispatches | 无重叠正常选批：主树有 WIP 但与批无交集时选批投递流程与现状一致（同步链投递并核销 resolved）；非 git 根（git status 失败）按无重叠 fail-open 不阻塞选批。出处 tests/test_code_fix_wip_precheck.py:140 TestNoOverlapDispatches，实现 core/code_fix.py:1246（无脏文件返回空表） | pass | 0/3 | - |
| wip-precheck-artifact-exempt | 产物脏文件不误伤：交集仅含 dist 类产物路径且产物配置已裁决（has_build_artifacts=true + dist/ 前缀，与 merge-time 闸门同口径）时不推迟照常投递；产物配置未裁决时同路径按语义重叠推迟（同口径对照）；daemon 装配形态（config=None→runner 根配置）豁免同样生效。出处 tests/test_code_fix_wip_precheck.py:175 TestArtifactOverlapExempt，实现 core/code_fix.py:1252（ArtifactPathMatcher 同配置源构造） | pass | 0/4 | - |
| wip-precheck-probe-overlap-progress-observable | 推迟可观测探针：在验证树内以真实 CodeFixOrchestrator 驱动 checkpoint（git 临时项目根+主树 WIP 重叠台账条目），验证 progress 无条件落盘（running=false、phase=blocked、reason=wip_overlap_at_select、current 携带交集文件）且台账条目保持 open——无 live 链首查也写（MUST NOT 照抄选批为空出口的 live 链条件）。出处 core/code_fix.py:1461-1497（无条件 write_progress 推迟出口），探针经 tests/test_code_fix_wip_precheck.py 脚手架 | pass | 0/7 | - |
| wip-precheck-probe-no-overlap-dispatch | 无重叠正向探针：在验证树内以真实 CodeFixOrchestrator 驱动 checkpoint（git 临时项目根+主树 WIP 在批外 docs/notes.md），验证返回 triggered=true/reason=dispatched 且台账条目核销 resolved——预检未扰动既有投递路径。出处 core/code_fix.py:1466（预检插入点 select_batch 后契约守卫前） | pass | 0/5 | - |
| wip-precheck-new-suite-full-green | 新预检套件整体绿灯：tests/test_code_fix_wip_precheck.py 全部 7 例（两推迟+两无重叠+三产物豁免）单进程一次性通过，防跨类测试隔离问题。出处 tests/test_code_fix_wip_precheck.py:1 | pass | 0/3 | - |
| wip-precheck-existing-suite-regression | 既有 code-fix 套件回归：test_code_fix.py 110 例全过——本 SPEC 重构了 _get_config→_get_root_config（单源解析点）并在 checkpoint 选批热路径插入预检，回归锁既有选批/投递/defer 行为与现状一致。出处 core/code_fix.py:1203-1226（_get_root_config 重构）、tests/test_code_fix.py:1 | pass | 0/2 | - |
| wip-precheck-related-lanes-regression | 相关 code-fix 车道套件回归：manual_trigger/item_level_progress/startup_stage_visibility 三套件 57 例全过——三者均走 checkpoint 热路径（手动触发/条目级进度/启动期可见性），锁预检插入未扰动其进度写点与触发语义。出处 tests/test_code_fix_manual_trigger.py:1、tests/test_code_fix_item_level_progress.py:1、tests/test_code_fix_startup_stage_visibility.py:1 | pass | 0/2 | - |

## 本轮场景集变更

场景集与持久化集一致，无变更。

