# 裁决结果文件轮间卫生

<!-- knowledge: capability=judge-result-freshness-hygiene rev=1
     sources=spec/archive/2026-10-14-evo-add-judge-result-predispatch-rename -->

裁决（planner-judge）结果文件的轮间卫生：派发前把上轮遗留结果改名留档、硬门命中陈旧残留后重试前先行清理，使陈旧残留既不以「作废整轮」的高价兜底，也烧不光原地重试预算。

## 规则

- 派发前留档：裁决 run 派发前，编排层（run_planner 的 judge 派发分支，两条派发路径汇合处）检查 `.fenix/verify-progress/<spec>/.fenix-run-result.json`，存在即原子改名为 `prev-judge-result.json` 留档后再派发；本轮产物硬门因此不再命中上轮陈旧残留（仿 impl 侧 prev-impl-result.json 同型先例）。
- 改名失败非致命：改名抛 OSError 仅 WARNING 留痕、派发照常不阻断，原文件保留不删，由 agent 落盘时覆写原路径；此形态下不产生留档文件。
- 留档单文件限定：只处理该一个结果文件；`report.json`、`tokens.json`、`verdict_cache.json` 等跨轮累积产物一律不触碰。
- 留档仅挂 judge 分支：mode=plan 派发不触发留档；无遗留文件时行为零变化（不产生留档文件），verdict 稳定复用与全绿快道行为不受影响。
- 留档内容异质为设计内接受态：正常 plan→judge 流中，judge 派发时该路径现存文件可能是本轮 planready 产物（planner-plan 双产物门同读此路径），一并装入留档、judge 随后覆写同路径，功能无损，不做内容甄别；仅裁决重派路径（重派前上轮裁决产物仍在）留档的才是上轮裁决产物。
- 陈旧残留重试前清理：产物硬门新鲜度校验（结果文件 mtime 早于本轮启动减宽限即拒，fail-closed）命中陈旧残留进入原地重试前，须先清理该陈旧文件——改名留档，清理语义下改名失败退化为删除原文件；清理后再败归因退化为「结果文件缺失」，终态归因不再含「陈旧/早于本轮启动」，同一陈旧文件烧光全部原地重试预算的路径被切断。
- 清理范围限定：仅当 agent_type 为 planner-judge 且目标路径经 `planner_result_path(root, spec, "planner-judge")` 重建命中才清理（MUST NOT 从 error 归因文案解析路径取目标）；跨 spec 共享根文件 `.fenix/.fenix-run-result.json`（实现收尾契约唯一落点、快道争议读侧候选）与其他 agent_type 产物不得改名/删除。
- 下游语义不变：硬门 fail-closed 校验语义不变；resumed-worktree 豁免仅 implementer/fast-track 透传、planner-judge 不豁免；快道读侧先于 run_planner 执行，改名不引入读侧竞态。

## 溯源

- 2026-10-14 evo-add-judge-result-predispatch-rename（spec/archive/2026-10-14-evo-add-judge-result-predispatch-rename） — 新建本页：确立裁决派发前上轮结果改名 prev-judge-result.json 留档（改名失败仅 WARNING 不阻断）与硬门陈旧残留原地重试前清理（planner-judge 限定、共享根文件不触碰、终态归因退化为结果文件缺失）
