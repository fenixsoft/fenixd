# ADR-102：tasks.md 损伤复检挂 merge 前、分支侧基准，显示层 lint fail-open

date: 2026-09-17
status: accepted

## Context

tasks.md 的既有 lint 只在 drafted→ready 晋升时跑且只拦「分组数为 0」；implementer 收尾期把任务行写坏（分组完好、任务行全灭）时晋升 lint 已过期跑不到，收口期无任何校验，损伤随 merge 进主树，dashboard 任务清单空白。

## Decision

- 写入端门禁：merge 前在两车道各设一次机械复检。full 车道以**实现分支上的 tasks.md** 为基准（`git show branch:path`）——merge 前主树版本=立项版本，恰好检不出分支上的中途损伤，写读必须同层；fast-track 车道直接读 worktree 文件（成功后 worktree 延迟清理仍在）。
- lint 规则并入同源函数：晋升 lint 与 merge 前复检共用「分组数 / 任务行数」纯函数计数，单一解析源防两处漂移；新增违规形态「分组在而任务行为 0」，违规文案携带修正处方，重派 run 可机械自修。
- fail 方向按损伤代价校准：tasks.md 损伤的代价是显示层空白（不烧钱、不阻塞推进），门禁误拦的代价是整轮重派烧钱——读取失败 / lint 异常一律放行，宁漏拦不误拦（与交付物硬校验的「宁误拦不漏放」方向相反，按各自损伤代价定）。
- 违规处置复用车道既有重派与熔断语义，不新增计数器；展示侧告警面不扩，只加写入端门禁。

## Consequences

- 损伤的 tasks.md 不进主树，dashboard 不再因中途损伤空白；全库存量扫描零误拦后方可收紧。
- 两车道读取路径（git show / worktree 文件）都须测试覆盖；解析正则保持单源。
