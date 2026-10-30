# 归档触发蒸馏管线

<!-- knowledge: capability=knowledge-distill-pipeline rev=3
     sources=spec/archive/2026-10-05-add-knowledge-atlas,spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction,spec/archive/2026-10-30-evo-knowledge-distill-resume-guard -->

SPEC 归档完成后自动派发蒸馏 run，把归档 delta 蒸馏进真相源能力页的增量车道：合并语义、确定性对账、自动提交一体完成；批次在飞全程落盘在册，daemon 重启可续跑。

## 规则

- 触发挂载：蒸馏派发单点挂在归档共同漏斗 `core/archive_commit.py::commit_archive_move` 移动成功分支，手工归档与 daemon 自动归档两条路径同等生效；软删除以归档移动收尾、经同一漏斗触发蒸馏属预期行为。派发 fail-open：失败只记日志并登记 `.fenix/todo.md` 重试台账（给人看的队列，不进任务门禁），不影响归档本身的返回与结果。
- 门控链：`knowledge.enabled=false` 时跳过派发（归档照旧）；配置解析失败按禁用处理（保守不派发）；归档目录缺失或归档名含路径成分时拒绝；回填期排队门——回填台账存在 pending 条目时不派发增量 run，把该归档登记进回填台账后返回（reason=backfill-queued），收敛后恢复即时派发，排队判定或登记故障 fail-open 按原派发继续；pytest 测试环境恒不派发（替身经 dispatcher 参数注入，既有单测直调漏斗不触发真实蒸馏）。门控拒绝与回填期排队的批次不写 pending 台账（未入队不算在途）。
- 单飞：同 project 同时至多一个蒸馏 run 写 `spec/knowledge/`——进程内 per-project 队列单 worker 串行消费 + 跨进程 flock（`.fenix/knowledge-distill.lock`）；并发归档事件排队串行，积压条目合并为一次批量 run（`dispatch_distill_batch` 同门控）。
- pending 台账：每次入队（单条与批量入口共用派发路径）同步把本批归档名持久化到 `<project>/.fenix/knowledge-distill-pending.json`——条目含归档名与入队时间戳、同批多归档合并为一条，写入为 tmp+os.replace 原子回写（与 flock 不同文件、互不阻塞）。台账是 best-effort 侧记而非事务队列：写点收在派发单咽喉（持进程内 guard 的单写者，整文件重读-改-回写），互斥范围仅进程内（dashboard --serve 与 daemon 并发派发时整文件覆盖可能丢对方条目，后果等同台账丢失、按同一口径接受）；读缺失/损坏/形态不合规按空表 fail-open——宁可丢台账退回内存态现状，不阻断派发主流程。
- 台账生命周期与批次收尾对账：成功收尾（提交落库或判定无变更可提交）后移除条目；放弃产出且工作区清理确认后移除；「校验通过但自动提交失败」「执行异常」「run 失败且回滚未确认」三条滞留路径必须保留条目，并照旧登记 todo 重试台账、注明由 daemon 重启续跑接管，不得静默清除。合并批次收尾按本批 names 并集一次清除全部对应条目（防漏清陈旧条目在重启后对已入库归档触发重蒸）；清除为整文件重读-过滤-原子回写，避免与并发入队互相覆盖丢条目。
- daemon 启动恢复：daemon 初始化末尾扫描 pending 台账，存在条目即先清空台账文件、再经恢复入口逐条走既有门控链重新入队——顺序必须先清空后入队（恢复重派会经写点立即重新落盘；若先入队后清空会把刚重写的条目一并抹掉，恢复期间台账裸奔）。门控放行的条目由写点立即重新落盘、收尾前始终在册（运行中再崩溃可再次恢复）；门控拒绝的条目随清空消失、不复活。恢复动作只重新入队、不执行蒸馏（实际 run 仍走既有 flock 单飞与 worker 串行消费）；恢复批次数落日志；恢复入口仅 daemon 启动路径接入，dashboard --serve 进程不做恢复（避免双进程竞争）；恢复异常降级 WARNING，不阻塞 daemon 启动。
- run 形态：daemon spawn `claude -p` 后台线程，cwd 主树直跑（真相源是 spec 元数据层非产品代码，无 merge-back），注入 `core/knowledge_prompts/distill.md` 提示词；写路径限定 `spec/knowledge/`（及 `.fenix/` 台账），run 前后 `git status` 对账越界写面——合法写面外的新增改动记 WARNING 留痕、不自动回滚（避免吞掉用户未提交改动）。
- 合并语义（后写覆盖前写）：读归档 `specs/<capability>/spec.md` delta 与 proposal 摘要处理每个 capability——真相源无该页则新建（rev=1）；已有则按本次 delta 整体重写受影响规则段（rev+1、溯源追加一行），旧规则从规则段消失；REMOVED 规则从规则段移除、溯源留「已随 <归档名> 废除」行，页面其余规则不动；主从分片按 capability 名聚合、整体重写全部分片。
- 收尾对账（确定性脚本，非 LLM）：`core/knowledge.py::validate_knowledge` 校验 marker 可解析、sources 指向真实归档目录、单页 ≤150 行、index/_domain/adr 链接可解析且不越界、ADR 三段式与 accepted 正文不可变、Superseded by 指向存在条目；违规清单回反馈给 run 修正（≤2 轮），仍违规则放弃产出——daemon 侧 `git restore` 真相源目录并清理未跟踪新增，不留半成品；放弃按批次级基线快照判别，不吞用户 run 前既有的未提交改动。
- 自动提交：校验全过后 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: distill <归档名>`；无变更（如重复蒸馏同批归档）跳过空提交、按 ok 处理；提交失败 fail-open 记 warning，pending 条目保留交重启续跑。
- 原料缺失降级（不判 run 失败）：归档无 `design.md` 跳过 ADR 抽取；无 `specs/` delta 按 proposal 摘要口径蒸馏能力页，或提不出任何当前规则时在能力页溯源段留一行「已审阅 <归档名>：无可蒸馏规则」，不虚构内容。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：双路径单点挂载、ADDED/MODIFIED/REMOVED 合并语义、fail-open 与重试台账、单飞约束、收尾校验与自动提交、原料缺失降级
- 2026-10-05 fix-knowledge-backfill-reconstruction（spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction/） — 门控链增回填期排队门：台账有 pending 时增量蒸馏登记回填台账不派发、收敛后放行、判定故障 fail-open
- 2026-10-30 evo-knowledge-distill-resume-guard（spec/archive/2026-10-30-evo-knowledge-distill-resume-guard/） — 批次从派发即内存态改为在飞全程在册：新增 pending 台账落盘与收尾对账（三条滞留路径保留、合并批并集清除）、daemon 启动先清空后入队恢复（dashboard 不接恢复）、门控拒绝路径不入账
