# 验证报告：add-archive-state-migration

> ⚠️ 本报告由框架于 2026-09-29T04:04:32Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-29T03:29:59.806317+00:00+run-result@mtime1790654642475493542

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 14/20 场景通过，6 失败，0 错误（1 个真实产品 Bug）**

重试裁决轮：仅按驳回清单补齐 auto-archive-threshold-evicts-oldest 的 assertion_triage（6 失败断言逐条归因 6/6，全部 test-defect），其余 5 个非 PASS 场景受理字段原样保留未动。20 场景：14 过 / 6 失败 → 1 个 product-bug（SummaryIndex 缓存签名 _spec_dep_sigs 漏活跃目录存在性 → archived 标记陈旧误标，阻塞界面归档主路径，派 implementer 修复）；5 个场景文件缺陷已于上一轮原地修复并本轮回读核验在场。静态情报核查：web-double-source-single-row assertions[2] text_contains「完成」判误报——选择器限 ghost 行（tr[data-row-key=arc-mig-ghost]），目标为状态单元格 STATUS_META（services/dashboard.ts）容器文本而非 antd Button，autoInsertSpace 不适用，且本轮执行该断言 pass=true（报告行 1429-1433），场景整体 pass，不改场景文件。判定规则适用记录：web-evicted-detail 的 no_click_interception 属弹窗遮挡时序特判（test-defect）；no_auth_error/no_console_error 豁免未触发（全部 no_console_error 断言本就通过）

| 指标 | 数量 |
| --- | --- |
| 通过 | 14 |
| 失败 | 6 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 12.88M |
| 本链增量 Token（输出） | 0.22M |


## 真实产品 Bug

### BUG-01（severity=major）· element_not_found（wait tr[data-row-key="arc-mig-ui2"] 5000ms 超时）

- 关联场景：web-ui-archive-evict-archived-view
- 描述：SummaryIndex 摘要缓存把活跃条目 arc-mig-ui2 的 archived 标记永久缓存为 true，前端未归档视图按该标记过滤掉活跃 SPEC（归档入口无法触达），已归档视图反向错误显示它（web-evicted-detail-docs-readable 在已归档视图见到 ui2 行为同一误标旁证）
- 根因：spec_summary 经 is_spec_archived（core/dashboard/data/spec_archive.py:243）以活跃目录存在性为归档可见性单源，但 SummaryIndex 的 per-spec 缓存签名 _spec_dep_sigs（core/dashboard/data/summary.py:578，docstring 声称『对齐 spec_summary 实际读路径』）未收录 spec/changes/<name>/ 目录存在性，且签名只收 tasks.md/.spec.yaml/verification-report.md/specs/*.md 等特定文件——目录重建后若仅含不入签名的文件（如本例 proposal.md），签名零变化，陈旧 archived 标记永不重算。触发时序：夹具先写 STATE.md 后建目录的窗口被 watcher 首建 SummaryIndex 命中，ui2 以『目录缺失+条目在活跃』算出 archived=True 入缓存
- 证据（场景 web-ui-archive-evict-archived-view 结构化证据，引用）：
  - failed_assertions: [{"type": "step_error", "selector": "tr[data-row-key=\"arc-mig-ui2\"]", "expected": "未归档视图可见（ui2 为夹具活跃 pushed 条目，目录/探针在 spec/changes/arc-mig-ui2/proposal.md）", "actual": "Locator.wait_for Timeout 5000ms——读侧 /api/specs 误标 ui2 archived=true（实测响应 archived=True,archived_by=ui），前端未归档视图按 archived 过滤掉该行"}]
  - screenshots: []
  - first_failed_step: 步骤3: 等待 arc-mig-ui2 行超时（element_not_found_or_not_actionable）；实测 GET /api/specs 该条目 archived=True 且 archived_by=ui，但 ui2 在活跃 STATE.md:263、不在 STATE.archive.md（清单仅 ghost/ui）、目录存在——is_spec_archived 按磁盘代码现查应为 False，标记为 SummaryIndex 缓存陈旧值


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| arc-fixture-provision | 夹具供给（幂等）：在 verify.yaml prepare 已 reset 的夹具项目 scheduling-showcase 上清跨轮残留（spec/archive 下 arc-mig-* 与 *-c-sched-done 归档目标、STATE.archive.md），再向 STATE.md 幂等追加本 spec 专用规格集——arc-mig-ui/ui2（pushed 终态、活跃目录+proposal.md）、arc-mig-auto-a/b/c（done、updated 依次 09-20/09-21/09-22、活跃目录）、arc-mig-nonterm（implementing、活跃目录）、arc-mig-backfill/backfill2（done、条目在目录缺失=历史归档遗留）、arc-mig-orphan（implementing、条目在目录缺失=非终态孤儿）；后续 api/web/cli 场景均消费此夹具（bin/fixture_scheduling_showcase.py 供给夹具项目并登记 dashboard，verify.yaml prepare 层每轮 reset） | pass | 0/4 | - |
| evict-primitive-relocates-idempotent-creates-list | 迁出原语正向路径+幂等+清单缺失首迁创建（archive-state-relocation「迁出条目落入清单并带溯源字段」「清单缺失视为空」「迁出后活跃条目消失且清单新增」「重复迁出幂等」）：scratch 项目上 StateMachine.evict_spec(name,'ui') 后 STATE.md 不含该条目、STATE.archive.md 出现同字段小节+archived_at(UTC ISO)+archived_by: ui，重复迁出返回未找到且清单不变（design D2/tasks 1.1） | pass | 0/4 | - |
| evict-primitive-oserror-keeps-entry | 迁出原语清单写入失败条目不丢（「清单写入失败条目不丢」）：把清单路径预置为同名目录迫使写入抛 OSError，evict_spec 返回失败且 STATE.md 条目原样保留、无半迁出态；另验证未注册名调用返回 found=False 幂等（design D2 顺序保证） | pass | 0/4 | - |
| archive-list-parse-shared-format-immutable-transition | 清单解析与活跃流转隔离（「活跃状态流转不重写清单」+tasks 1.2）：parse_archived_state 对缺失文件返回空 dict 不抛错；对含条目清单解析出与 STATE.md 同格式的小节字段；随后对活跃 STATE.md 做全量重写（write_all，状态流转的落盘通道），清单文件内容与 mtime_ns 均不变 | pass | 0/3 | - |
| cli-fenix-archive-evicts-entry | CLI 归档路径迁出收口（spec-archive「归档完成的 change」）：bin/fenix_archive.py <name> --project <scratch> 归档终态 change 成功——目录移入 spec/archive/、输出 JSON ok=true、STATE.md 条目迁出清单且 archived_by: cli、archived_at 存在（tasks 2.3） | pass | 0/8 | - |
| cli-fenix-archive-conflict-and-no-entry | CLI 归档异常路径（「目标已存在报错不覆盖」「STATE 无条目仍可归档」）：预先创建当日归档目标目录后归档 → 退出码 1、输出 Archive target already exists、原目录与 STATE.md 条目均不变、清单无新条目；对 STATE.md 无条目的 change 归档 → 成功不报错、目录正常移入归档（tasks 2.4） | failed（已修正） | 1/8 | test-defect |
| threshold-zero-disables-archive-backfill-still-runs | 阈值 0 禁用归档但回填不受开关约束（auto-spec-archive「阈值为 0 或缺失时禁用」+「回填 SHALL 与归档阈值无关」）：auto_archive_check(project, {archive:{auto_threshold:0}}) 返回 archived=0 且不动任何目录条目；同轮 backfill_archived_entries 仍把目录缺失终态条目 arc-mig-backfill2 迁出 archived_by: backfill（tasks 4.2） | failed（已修正） | 3/3 | test-defect |
| soft-delete-covers-archive-list | 软删除兼容清单（design D6/tasks 4.3）：scratch 项目——条目仅在清单+归档目录在 → soft_delete_spec 返回 found=True 且清单小节与归档目录一并清除；双源并存（活跃+清单）→ 两处都清、STATE.md 不再含条目 | pass | 0/5 | - |
| evo-candidate-name-avoids-evicted | evo 撞名检查双源口径（proposal「evo 撞名检查改为活跃+清单双源」tasks 3.3）：resolve_spec_name('foo',…) 在清单含 evo-foo 条目（活跃 STATE 无）时返回加后缀候选而非 evo-foo；对照组清单无条目时返回基名 evo-foo——防已迁出名被重复占用 | pass | 0/4 | - |
| statistics-active-only-projection | 统计口径只算活跃（archive-state-relocation「迁出后统计数字下降」）：scratch 项目 3 条目（其一终态），project_summary 报 spec_count=3；经 evict_spec 迁出该终态条目后再调 project_summary → spec_count=2、task_total 同步减少、且迁出名不再计入（BREAKING 数字下降属预期，proposal 已标注） | pass | 0/5 | - |
| unit-tests-archive-state-migration-pass | 新交付单测文件全绿（tasks 交付物 tests/test_archive_state_migration.py）：pytest -v 运行该文件，退出码 0 且输出含 passed 摘要（覆盖迁出原语原子性/回填/双源读侧/软删除的单测面）；-v 不带 -q 保证 PASSED 行输出形态与断言一致 | pass | 0/2 | - |
| auto-archive-threshold-evicts-oldest | daemon 自动归档迁出收口（auto-spec-archive「超阈值自动归档最久完成的」「归档成功条目同步迁出」「单条失败不阻塞」「非终态与已归档不计入阈值」）：直驱 auto_archive_check(project, {archive:{auto_threshold:2}})——4 条终态未归档（updated 升序 c-sched-done < auto-a < auto-b < auto-c）超阈值归档最久 2 条，其中最久的 auto-a 预置当日冲突目标被跳过、c-sched-done 归档成功迁出清单 archived_by: auto；implementing 与目录缺失条目不计入；archived=1/skipped=1（tasks 2.1） | failed（已修正） | 6/6 | test-defect |
| backfill-batch-idempotent-keeps-nonterminal | 存量回填（archive-state-relocation「存量已归档条目被批量迁出」「回填幂等可重复」「非终态孤儿条目保留」）：直驱 backfill_archived_entries(project, logger)——目录缺失的终态条目 arc-mig-backfill 批量迁出 archived_by: backfill；连续第二轮扫描集为空零迁出；非终态孤儿 arc-mig-orphan（implementing+目录缺失）保留在 STATE.md 不迁出（tasks 4.1） | failed（已修正） | 4/5 | test-defect |
| double-source-intermediate-fixture | 双源中间态夹具（dashboard-spec-table「双源同名单不重复行」前置）：向 scheduling-showcase 写入 arc-mig-ghost 双源条目——活跃 STATE.md 条目（done）+ STATE.archive.md 同名小节（archived_by: backfill）+ 活跃目录缺失，模拟迁出失败后回填未跑的中间态；整文件重写清单为仅含该小节避免跨场景串扰（design D4 活跃侧优先） | pass | 0/2 | - |
| ui-archive-api-evicts-and-list-merges | 界面归档 API 迁出收口+列表合并+详情可读（dashboard-spec-archive「归档终态 SPEC 成功」/dashboard-spec-table「列表合并归档清单条目」/archive-state-relocation「迁出后详情仍可读」）：POST /api/spec-archive?project=scheduling-showcase&spec=arc-mig-ui 返回 ok=true 与 spec/archive/ 目标路径（archived_by=ui）；GET /api/specs 合并后仍含 arc-mig-ui；GET /api/specs/arc-mig-ui 详情 200 且 name/status 透传迁出前字段（路由源码 core/dashboard/routes/spec_routes.py:561 _api_spec_archive、:37 _api_specs） | pass | 0/10 | - |
| web-ui-archive-evict-archived-view | 界面归档端到端+已归档视图合并可见（dashboard-spec-archive「归档终态 SPEC 成功」/dashboard-spec-table「已迁出 SPEC 仍在已归档视图可见」）：项目列表页（navigate 出处 config/routes.ts:21 /projects/:name）对 arc-mig-ui2 行经「更多→修改状态→归档 SPEC→确认」走真实归档 API，随后切「已归档」视图该行仍显示且状态「已推送」、无重复行（SpecStatusModal.tsx:578-591 归档区块、list.tsx:1360-1370 归档视图切换 Radio.Group） | failed（已修正） | - | product-bug |
| api-archive-rejections | 归档拒绝分支不迁出（dashboard-spec-archive「非终态 SPEC 被拒绝」「目标已存在不覆盖」+「归档被拒绝不迁出」）：POST /api/spec-archive 对 implementing 的 arc-mig-nonterm 返回 403；对已归档迁出的 arc-mig-ui 返回 409（archived_already）；对不存在 spec 返回 404；列表中 arc-mig-nonterm 仍在未归档态（路由 spec_routes.py:590-601 按数据层结构化标志分流 403/409/404） | pass | 0/6 | - |
| web-evicted-detail-docs-readable | 迁出后详情与文档归档回退可读（archive-state-relocation「迁出后详情仍可读」/dashboard-spec-table「可点击进入详情并查看文档」）：从已归档视图点击 arc-mig-ui2 行名进入详情页（routes.ts:20 /projects/:name/:spec；SpecNameCell list.tsx:239-242 history.push），详情加载后打开「文档」弹窗可见夹具 proposal.md 探针文本（文档读取经 /api/spec-doc 归档目录回退，spec_routes.py:70） | failed（已修正） | 1/4 | test-defect |
| web-double-source-single-row | 双源同名单不重复+未归档视图不含清单条目（dashboard-spec-table「双源同名单不重复」「未归档视图不含清单条目」）：默认「未归档」视图无 arc-mig-ghost 行；切「已归档」视图该行恰好一行（element_count=1）且状态透传渲染「完成」（STATUS_META done→完成，services/dashboard.ts:1064） | pass | 0/5 | - |
| web-unarchived-view-excludes-list-entries | 未归档视图不含清单条目（dashboard-spec-table「未归档视图不含清单条目」）：默认「未归档」视图仅含活跃 SPEC，双源中间态条目 arc-mig-ghost（活跃+清单同名、目录缺失）不得出现（routes.ts:21；list.tsx:847-852 archived 过滤） | pass | 0/4 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| cli-fenix-archive-conflict-and-no-entry | file_exists .history/arc-mig-lab/c2/.fenix/STATE.archive.md（negate=true）冲突不得创建归档清单 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景文件缺陷：引擎 file_exists 断言不实现 negate（cli_assertions.py:208 raw=a.get('exists',True)，无 negate 分支）→ want 恒 true；引擎支持显式 exists:false 等价表达，属断言参数形态错误而非产品缺陷 |
| threshold-zero-disables-archive-backfill-still-runs | exit_code 步骤 t0 期望 0 实际 1 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景脚本缺陷：t9 场景 command 内 `root / 'spec' / 'changes' / 't9-live'.mkdir(...)` 属性引用优先于 / 运算，对 str 调 mkdir → AttributeError；对照 p1/c1 等通过场景均写 (root / ...).mkdir 括号形态 |
| threshold-zero-disables-archive-backfill-still-runs | json_output t0.ok 期望 true | test-defect | 测试用例自身缺陷（非产品缺陷） | stdout 空系夹具段 AttributeError 使脚本未运行到 print；被测 auto_archive_check/backfill_archived_entries 未被执行，非产品行为 |
| threshold-zero-disables-archive-backfill-still-runs | file_content t9/.fenix/STATE.archive.md 期望存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 清单不存在系夹具段中断导致回填未执行（.fenix 下仅 STATE.md 无 logs），非回填逻辑缺陷——t8 同款修复后直调复现 backfill 正常迁出（evicted=3） |
| auto-archive-threshold-evicts-oldest | exit_code 步骤 auto 期望 0 实际 1 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景脚本缺陷：t7 夹具 5 行 `root / 'spec' / 'changes' / 't7-<n>'.mkdir(...)` 全部漏括号，首行 AttributeError 中断；与 p1（(root/'.fenix').mkdir 括号形态、pass）对照成立 |
| auto-archive-threshold-evicts-oldest | json_output 步骤 auto path=ok 期望 true（stdout 非合法 JSON） | test-defect | 测试用例自身缺陷（非产品缺陷） | stdout 为空串系夹具段首行 AttributeError 中断、脚本未运行到 print(json.dumps(...))；引擎读空串判非 JSON，与 auto_archive_check 返回契约无关 |
| auto-archive-threshold-evicts-oldest | json_output 步骤 auto path=first.archived 期望 1（stdout 非合法 JSON） | test-defect | 测试用例自身缺陷（非产品缺陷） | first.archived 无输入可解析——auto_archive_check(threshold=2) 因夹具炸死从未执行；其返回结构含 archived 键（spec_archive.py:455-493），断言字段名与实现吻合 |
| auto-archive-threshold-evicts-oldest | json_output 步骤 auto path=first.skipped 期望 1（stdout 非合法 JSON） | test-defect | 测试用例自身缺陷（非产品缺陷） | first.skipped 同因无输出：t7-a 冲突跳过路径（预置当日归档目标）未被执行到，skipped 计数断言缺输入，非跳过逻辑缺陷 |
| auto-archive-threshold-evicts-oldest | json_output 步骤 auto path=second.archived 期望 0（stdout 非合法 JSON） | test-defect | 测试用例自身缺陷（非产品缺陷） | second.archived 幂等复验断言同样无输入可解析——二次 auto_archive_check 调用从未发生（脚本中断在夹具段） |
| auto-archive-threshold-evicts-oldest | file_content t7/.fenix/STATE.archive.md 期望存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 清单未创建系夹具中断致归档流程未执行；t7 lab .fenix 仅 STATE.md，非自动归档实现缺陷 |
| backfill-batch-idempotent-keeps-nonterminal | exit_code 步骤 bf 期望 0 实际 1 | test-defect | 测试用例自身缺陷（非产品缺陷） | 场景脚本缺陷：t8 夹具 `root / 'spec' / 'changes' / 't8-live'.mkdir(...)` 漏括号 AttributeError；同 lab 复现（目录缺失态）backfill_archived_entries 正常返回 {scanned:4, evicted:3, nonte... |
| backfill-batch-idempotent-keeps-nonterminal | json_output bf.ok 期望 true | test-defect | 测试用例自身缺陷（非产品缺陷） | stdout 空系夹具段 AttributeError 未运行到 print（引擎仅捕获 stdout），被测函数未执行 |
| backfill-batch-idempotent-keeps-nonterminal | file_content t8/.fenix/STATE.archive.md 期望存在 | test-defect | 测试用例自身缺陷（非产品缺陷） | 清单不存在系回填未执行（夹具中断在 import backfill 之前），非实现缺陷 |
| backfill-batch-idempotent-keeps-nonterminal | file_content t8/.fenix/STATE.md negate（### t8-bf1 不应存在） | test-defect | 测试用例自身缺陷（非产品缺陷） | actual_snippet 显示 t8-bf1 原样保留 = 回填未跑（夹具炸死），伴生失败；backfill 实现经复现验证迁出正常 |
| web-evicted-detail-docs-readable | no_click_interception a.touch-expand 文档入口可交互 | test-defect | 测试用例自身缺陷（非产品缺陷） | 断言时序设计缺陷：引擎断言统一在全部步骤后执行，步骤 7 点击入口已成功打开文档弹窗，断言再对同一入口重试点击必被 modal 遮罩拦截（判定规则明确的弹窗遮挡形态）；『入口可交互』意图已由步骤 7 click 成功覆盖，antd modal 遮罩全屏背景下弹窗开启期间不存在可断言的背景元素 |

## 本轮场景集变更

当前稳定场景集共 20 个（第 1 轮）。

- 首轮写入 20 个场景

