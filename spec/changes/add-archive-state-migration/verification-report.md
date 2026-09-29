# 验证报告：add-archive-state-migration

> ⚠️ 本报告由框架于 2026-09-29T07:14:28Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-09-29T07:14:28.271763+00:00+run-result@mtime1790666068338217656

## 结论：✅ 通过（verified）

**状态：verified — 20/20 场景通过，0 失败，0 错误（全部场景通过）**

全绿快道: 20/20 场景通过、0 失败 0 警告——无分类对象，跳过 judge 机械 verified

| 指标 | 数量 |
| --- | --- |
| 通过 | 20 |
| 失败 | 0 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 15.79M |
| 本链增量 Token（输出） | 0.26M |


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| arc-fixture-provision | 夹具供给（幂等）：在 verify.yaml prepare 已 reset 的夹具项目 scheduling-showcase 上清跨轮残留（spec/archive 下 arc-mig-* 与 *-c-sched-done 归档目标、STATE.archive.md），再向 STATE.md 幂等追加本 spec 专用规格集——arc-mig-ui/ui2（pushed 终态、活跃目录+proposal.md）、arc-mig-auto-a/b/c（done、updated 依次 09-20/09-21/09-22、活跃目录）、arc-mig-nonterm（implementing、活跃目录）、arc-mig-backfill/backfill2（done、条目在目录缺失=历史归档遗留）、arc-mig-orphan（implementing、条目在目录缺失=非终态孤儿）；后续 api/web/cli 场景均消费此夹具（bin/fixture_scheduling_showcase.py 供给夹具项目并登记 dashboard，verify.yaml prepare 层每轮 reset） | pass | 0/4 | - |
| evict-primitive-relocates-idempotent-creates-list | 迁出原语正向路径+幂等+清单缺失首迁创建（archive-state-relocation「迁出条目落入清单并带溯源字段」「清单缺失视为空」「迁出后活跃条目消失且清单新增」「重复迁出幂等」）：scratch 项目上 StateMachine.evict_spec(name,'ui') 后 STATE.md 不含该条目、STATE.archive.md 出现同字段小节+archived_at(UTC ISO)+archived_by: ui，重复迁出返回未找到且清单不变（design D2/tasks 1.1） | pass | 0/4 | - |
| evict-primitive-oserror-keeps-entry | 迁出原语清单写入失败条目不丢（「清单写入失败条目不丢」）：把清单路径预置为同名目录迫使写入抛 OSError，evict_spec 返回失败且 STATE.md 条目原样保留、无半迁出态；另验证未注册名调用返回 found=False 幂等（design D2 顺序保证） | pass | 0/4 | - |
| archive-list-parse-shared-format-immutable-transition | 清单解析与活跃流转隔离（「活跃状态流转不重写清单」+tasks 1.2）：parse_archived_state 对缺失文件返回空 dict 不抛错；对含条目清单解析出与 STATE.md 同格式的小节字段；随后对活跃 STATE.md 做全量重写（write_all，状态流转的落盘通道），清单文件内容与 mtime_ns 均不变 | pass | 0/3 | - |
| cli-fenix-archive-evicts-entry | CLI 归档路径迁出收口（spec-archive「归档完成的 change」）：bin/fenix_archive.py <name> --project <scratch> 归档终态 change 成功——目录移入 spec/archive/、输出 JSON ok=true、STATE.md 条目迁出清单且 archived_by: cli、archived_at 存在（tasks 2.3） | pass | 0/8 | - |
| cli-fenix-archive-conflict-and-no-entry | CLI 归档异常路径（「目标已存在报错不覆盖」「STATE 无条目仍可归档」）：预先创建当日归档目标目录后归档 → 退出码 1、输出 Archive target already exists、原目录与 STATE.md 条目均不变、清单无新条目；对 STATE.md 无条目的 change 归档 → 成功不报错、目录正常移入归档（tasks 2.4） | pass | 0/8 | - |
| threshold-zero-disables-archive-backfill-still-runs | 阈值 0 禁用归档但回填不受开关约束（auto-spec-archive「阈值为 0 或缺失时禁用」+「回填 SHALL 与归档阈值无关」）：auto_archive_check(project, {archive:{auto_threshold:0}}) 返回 archived=0 且不动任何目录条目；同轮 backfill_archived_entries 仍把目录缺失终态条目 arc-mig-backfill2 迁出 archived_by: backfill（tasks 4.2） | pass | 0/3 | - |
| soft-delete-covers-archive-list | 软删除兼容清单（design D6/tasks 4.3）：scratch 项目——条目仅在清单+归档目录在 → soft_delete_spec 返回 found=True 且清单小节与归档目录一并清除；双源并存（活跃+清单）→ 两处都清、STATE.md 不再含条目 | pass | 0/5 | - |
| evo-candidate-name-avoids-evicted | evo 撞名检查双源口径（proposal「evo 撞名检查改为活跃+清单双源」tasks 3.3）：resolve_spec_name('foo',…) 在清单含 evo-foo 条目（活跃 STATE 无）时返回加后缀候选而非 evo-foo；对照组清单无条目时返回基名 evo-foo——防已迁出名被重复占用 | pass | 0/4 | - |
| statistics-active-only-projection | 统计口径只算活跃（archive-state-relocation「迁出后统计数字下降」）：scratch 项目 3 条目（其一终态），project_summary 报 spec_count=3；经 evict_spec 迁出该终态条目后再调 project_summary → spec_count=2、task_total 同步减少、且迁出名不再计入（BREAKING 数字下降属预期，proposal 已标注） | pass | 0/5 | - |
| unit-tests-archive-state-migration-pass | 新交付单测文件全绿（tasks 交付物 tests/test_archive_state_migration.py）：pytest -v 运行该文件，退出码 0 且输出含 passed 摘要（覆盖迁出原语原子性/回填/双源读侧/软删除的单测面）；-v 不带 -q 保证 PASSED 行输出形态与断言一致 | pass | 0/2 | - |
| auto-archive-threshold-evicts-oldest | daemon 自动归档迁出收口（auto-spec-archive「超阈值自动归档最久完成的」「归档成功条目同步迁出」「单条失败不阻塞」「非终态与已归档不计入阈值」）：直驱 auto_archive_check(project, {archive:{auto_threshold:2}})——4 条终态未归档（updated 升序 c-sched-done < auto-a < auto-b < auto-c）超阈值归档最久 2 条，其中最久的 auto-a 预置当日冲突目标被跳过、c-sched-done 归档成功迁出清单 archived_by: auto；implementing 与目录缺失条目不计入；archived=1/skipped=1（tasks 2.1） | pass | 0/6 | - |
| backfill-batch-idempotent-keeps-nonterminal | 存量回填（archive-state-relocation「存量已归档条目被批量迁出」「回填幂等可重复」「非终态孤儿条目保留」）：直驱 backfill_archived_entries(project, logger)——目录缺失的终态条目 arc-mig-backfill 批量迁出 archived_by: backfill；连续第二轮扫描集为空零迁出；非终态孤儿 arc-mig-orphan（implementing+目录缺失）保留在 STATE.md 不迁出（tasks 4.1） | pass | 0/5 | - |
| double-source-intermediate-fixture | 双源中间态夹具（dashboard-spec-table「双源同名单不重复行」前置）：向 scheduling-showcase 写入 arc-mig-ghost 双源条目——活跃 STATE.md 条目（done）+ STATE.archive.md 同名小节（archived_by: backfill）+ 活跃目录缺失，模拟迁出失败后回填未跑的中间态；整文件重写清单为仅含该小节避免跨场景串扰（design D4 活跃侧优先） | pass | 0/2 | - |
| ui-archive-api-evicts-and-list-merges | 界面归档 API 迁出收口+列表合并+详情可读（dashboard-spec-archive「归档终态 SPEC 成功」/dashboard-spec-table「列表合并归档清单条目」/archive-state-relocation「迁出后详情仍可读」）：POST /api/spec-archive?project=scheduling-showcase&spec=arc-mig-ui 返回 ok=true 与 spec/archive/ 目标路径（archived_by=ui）；GET /api/specs 合并后仍含 arc-mig-ui；GET /api/specs/arc-mig-ui 详情 200 且 name/status 透传迁出前字段（路由源码 core/dashboard/routes/spec_routes.py:561 _api_spec_archive、:37 _api_specs） | pass | 0/10 | - |
| web-ui-archive-evict-archived-view | 界面归档端到端+已归档视图合并可见（dashboard-spec-archive「归档终态 SPEC 成功」/dashboard-spec-table「已迁出 SPEC 仍在已归档视图可见」）：项目列表页（navigate 出处 config/routes.ts:21 /projects/:name）对 arc-mig-ui2 行经「更多→修改状态→归档 SPEC→确认」走真实归档 API，随后切「已归档」视图该行仍显示且状态「已推送」、无重复行（SpecStatusModal.tsx:578-591 归档区块、list.tsx:1360-1370 归档视图切换 Radio.Group） | pass | 0/6 | - |
| api-archive-rejections | 归档拒绝分支不迁出（dashboard-spec-archive「非终态 SPEC 被拒绝」「目标已存在不覆盖」+「归档被拒绝不迁出」）：POST /api/spec-archive 对 implementing 的 arc-mig-nonterm 返回 403；对已归档迁出的 arc-mig-ui 返回 409（archived_already）；对不存在 spec 返回 404；列表中 arc-mig-nonterm 仍在未归档态（路由 spec_routes.py:590-601 按数据层结构化标志分流 403/409/404） | pass | 0/6 | - |
| web-evicted-detail-docs-readable | 迁出后详情与文档归档回退可读（archive-state-relocation「迁出后详情仍可读」/dashboard-spec-table「可点击进入详情并查看文档」）：从已归档视图点击 arc-mig-ui2 行名进入详情页（routes.ts:20 /projects/:name/:spec；SpecNameCell list.tsx:239-242 history.push），详情加载后打开「文档」弹窗可见夹具 proposal.md 探针文本（文档读取经 /api/spec-doc 归档目录回退，spec_routes.py:70） | pass | 0/3 | - |
| web-double-source-single-row | 双源同名单不重复+未归档视图不含清单条目（dashboard-spec-table「双源同名单不重复」「未归档视图不含清单条目」）：默认「未归档」视图无 arc-mig-ghost 行；切「已归档」视图该行恰好一行（element_count=1）且状态透传渲染「完成」（STATUS_META done→完成，services/dashboard.ts:1064） | pass | 0/5 | - |
| web-unarchived-view-excludes-list-entries | 未归档视图不含清单条目（dashboard-spec-table「未归档视图不含清单条目」）：默认「未归档」视图仅含活跃 SPEC，双源中间态条目 arc-mig-ghost（活跃+清单同名、目录缺失）不得出现（routes.ts:21；list.tsx:847-852 archived 过滤） | pass | 0/4 | - |
