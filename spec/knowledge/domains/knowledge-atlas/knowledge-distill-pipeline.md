# 归档触发蒸馏管线

<!-- knowledge: capability=knowledge-distill-pipeline rev=7
     sources=spec/archive/2026-10-05-add-knowledge-atlas,spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction,spec/archive/2026-10-30-evo-knowledge-distill-resume-guard,spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md,spec/knowledge/_inbox/done/distill-econnreset-misattrib-recover-sweep-race.md,spec/knowledge/_inbox/done/distill-batch-fold-tax-and-artifact-no-content-1106.md -->

SPEC 归档完成后自动派发蒸馏 run，把归档 delta 蒸馏进真相源能力页的增量车道：合并语义、确定性对账、自动提交一体完成；批次在飞全程落盘在册，daemon 重启可续跑。

## 规则

- 触发挂载：蒸馏派发单点挂在归档共同漏斗 `core/archive_commit.py::commit_archive_move` 移动成功分支，手工归档与 daemon 自动归档两条路径同等生效；软删除以归档移动收尾、经同一漏斗触发蒸馏属预期行为。派发 fail-open：失败只记日志并登记 `.fenix/todo.md` 重试台账（给人看的队列，不进任务门禁），不影响归档本身的返回与结果。
- 门控链：`knowledge.enabled=false` 时跳过派发（归档照旧）；配置解析失败按禁用处理（保守不派发）；归档目录缺失或归档名含路径成分时拒绝；回填期排队门——回填台账存在 pending 条目时不派发增量 run，把该归档登记进回填台账后返回（reason=backfill-queued），收敛后恢复即时派发，排队判定或登记故障 fail-open 按原派发继续；pytest 测试环境恒不派发（替身经 dispatcher 参数注入，既有单测直调漏斗不触发真实蒸馏）。门控拒绝与回填期排队的批次不写 pending 台账（未入队不算在途）。
- 单飞：同 project 同时至多一个蒸馏 run 写 `spec/knowledge/`——进程内 per-project 队列单 worker 串行消费 + 跨进程 flock（`.fenix/knowledge-distill.lock`）；并发归档事件排队串行，积压条目合并为一次批量 run（`dispatch_distill_batch` 同门控）。
- pending 台账：每次入队（单条与批量入口共用派发路径）同步把本批归档名持久化到 `<project>/.fenix/knowledge-distill-pending.json`——条目含归档名与入队时间戳、同批多归档合并为一条，写入为 tmp+os.replace 原子回写（与 flock 不同文件、互不阻塞）。台账是 best-effort 侧记而非事务队列：写点收在派发单咽喉（持进程内 guard 的单写者，整文件重读-改-回写），互斥范围仅进程内（dashboard --serve 与 daemon 并发派发时整文件覆盖可能丢对方条目，后果等同台账丢失、按同一口径接受）；读缺失/损坏/形态不合规按空表 fail-open——宁可丢台账退回内存态现状，不阻断派发主流程。
- 台账生命周期与批次收尾对账：成功收尾（提交落库或判定无变更可提交）后移除条目；放弃产出且工作区清理确认后移除；「校验通过但自动提交失败」「执行异常」「run 失败且回滚未确认」三条滞留路径必须保留条目，并照旧登记 todo 重试台账、注明由 daemon 重启续跑接管，不得静默清除。合并批次收尾按本批 names 并集一次清除全部对应条目（防漏清陈旧条目在重启后对已入库归档触发重蒸）；清除为整文件重读-过滤-原子回写，避免与并发入队互相覆盖丢条目。
- daemon 启动恢复：daemon 初始化末尾扫描 pending 台账，存在条目即先清空台账文件、再经恢复入口逐条走既有门控链重新入队——顺序必须先清空后入队（恢复重派会经写点立即重新落盘；若先入队后清空会把刚重写的条目一并抹掉，恢复期间台账裸奔）。门控放行的条目由写点立即重新落盘、收尾前始终在册（运行中再崩溃可再次恢复）；门控拒绝的条目随清空消失、不复活。恢复动作只重新入队、不执行蒸馏（实际 run 仍走既有 flock 单飞与 worker 串行消费）；恢复批次数落日志；恢复入口仅 daemon 启动路径接入，dashboard --serve 进程不做恢复（避免双进程竞争）；恢复异常降级 WARNING，不阻塞 daemon 启动。再驱动面现状：恢复入口只挂 daemon 初始化这一次，主循环维护检查点对台账仅做「登记超 24h」欠账提醒、不重派——主蒸馏 run 失败后欠账滞留至下次 daemon 重启才获续跑；折叠子项具备「失败条目滞留原地待下轮重试」的轮内自愈，主蒸馏没有等效物（运行期兜底重派缺位）。
- run 形态：daemon spawn `claude -p` 后台线程，cwd 主树直跑（真相源是 spec 元数据层非产品代码，无 merge-back），注入 `agents/knowledge-distill.md` 提示词；每轮先经折叠前置段逐条消化 `_inbox/` 存量（每条一个折叠子 run，语义见 knowledge-inbox-pipeline 页）再蒸当轮 SPEC；写路径限定 `spec/knowledge/`（及 `.fenix/` 台账），run 前后 `git status` 对账越界写面——合法写面外的新增改动记 WARNING 留痕、不自动回滚（避免吞掉用户未提交改动）。已知误报面：`_inbox/` 下长期 untracked 常驻的条目（如 README 声明的计数夹具）使每个折叠提交的对账环节各触发一次「改动含 run 前基线已有路径」WARNING——属常驻条目所致噪音、非越界写。
- 耗时口径：纯单 SPEC 蒸馏约 10 分钟量级；批次总耗时 = 折叠前置段逐条子 run + 当轮蒸馏，积压大时耗时由折叠税主导（语义见 knowledge-inbox-pipeline 页）——长批次不代表当轮 SPEC 的蒸馏成本。
- run 观测面形态（已知观测缺口）：蒸馏批产物是合成事件流，只记 started/heartbeat/round/result 四类事件；result 行仅含 commit hash 与 folded 计数，不含改动文件清单或内容摘要——dashboard 运行明细因此呈现不了「蒸馏了什么」，观感「什么都没输出」。蒸馏产出取证以 git log 为准（主提交 `distill <归档名>` + 各折叠条目独立提交），不以 run 事件流内容为准。
- spawn 失败分类的已知误归因面：蒸馏 spawn 失败的拒识重试分类按已失败 run 的全量 stderr 是否含 `unrecognized_model` 子串判「拒识形态」，显式传名分支更把「显式传名仍被拒」直接断言为确定性失败、不再重试。该 stderr 行是 CLI 启动期噪声、成功 run 同样恒在场（判读口径见 [cli-stderr-noise-filtering](../run-resilience/cli-stderr-noise-filtering.md)），据此网关瞬断失败（stdout 死因如 `API Error: Connection dropped (ECONNRESET)`）会被盖成拒识终态、重试被错误抑制。死因取证以 stdout 的 API Error 行为准，stderr 噪声行不作死因证据；「确定性失败」结论须用同车道窗口内同型失败后成功的事实排除（同条目稍后折叠成功即瞬断反证）。
- 产物心跳保活：蒸馏批产物在 spawn 等待期由批级心跳线程按 900 秒间隔追加非终态 heartbeat 事件行（读侧 stale 阈值 1800 秒，保证每个 stale 判定窗内至少一次写入；900s × 30min spawn 上限 ≈ 每批 ≤3 行，不污染产物）；心跳线程 fail-open（线程体内异常全吞、只留日志），批收尾先 join 心跳线程再写终态行，保证产物末行是终态。
- 合并语义（后写覆盖前写）：读归档 `specs/<capability>/spec.md` delta 与 proposal 摘要处理每个 capability——真相源无该页则新建（rev=1）；已有则按本次 delta 整体重写受影响规则段（rev+1、溯源追加一行），旧规则从规则段消失；REMOVED 规则从规则段移除、溯源留「已随 <归档名> 废除」行，页面其余规则不动；主从分片按 capability 名聚合、整体重写全部分片。
- 收尾对账（确定性脚本，非 LLM）：`core/knowledge.py::validate_knowledge` 校验 marker 可解析、sources 指向真实归档目录、单页 ≤150 行、index/_domain/adr 链接可解析且不越界、ADR 三段式与 accepted 正文不可变、Superseded by 指向存在条目；违规清单回反馈给 run 修正（≤2 轮），仍违规则放弃产出——daemon 侧 `git restore` 真相源目录并清理未跟踪新增，不留半成品；放弃按批次级基线快照判别，不吞用户 run 前既有的未提交改动。放弃清理的半径覆盖工作区全部未提交真相源内容：`git restore` + 清理未跟踪新增不只清 run 自身产出，恢复/核查会话刚写出的能力页、ADR 等 untracked 文件同样在半径内（脏工作区实证复发）——恢复工作完成后的第一动作是 commit 入库（已提交内容不在 restore/clean 半径），恢复与提交之间不留窗口。
- 自动提交：校验全过后 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: distill <归档名>`；无变更（如重复蒸馏同批归档）跳过空提交、按 ok 处理；提交失败 fail-open 记 warning，pending 条目保留交重启续跑。
- 原料缺失降级（不判 run 失败）：归档无 `design.md` 跳过 ADR 抽取；无 `specs/` delta 按 proposal 摘要口径蒸馏能力页，或提不出任何当前规则时在能力页溯源段留一行「已审阅 <归档名>：无可蒸馏规则」，不虚构内容。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：双路径单点挂载、ADDED/MODIFIED/REMOVED 合并语义、fail-open 与重试台账、单飞约束、收尾校验与自动提交、原料缺失降级
- 2026-10-05 fix-knowledge-backfill-reconstruction（spec/archive/2026-10-05-fix-knowledge-backfill-reconstruction/） — 门控链增回填期排队门：台账有 pending 时增量蒸馏登记回填台账不派发、收敛后放行、判定故障 fail-open
- 2026-10-30 evo-knowledge-distill-resume-guard（spec/archive/2026-10-30-evo-knowledge-distill-resume-guard/） — 批次从派发即内存态改为在飞全程在册：新增 pending 台账落盘与收尾对账（三条滞留路径保留、合并批并集清除）、daemon 启动先清空后入队恢复（dashboard 不接恢复）、门控拒绝路径不入账
- 2026-11-03 add-knowledge-inbox-pipeline（spec/changes/add-knowledge-inbox-pipeline/） — 修订 run 形态：知识车道 prompt 归位 `agents/knowledge-distill.md`（`core/knowledge_prompts/` 目录废除、路径变更须 daemon 重启生效），蒸馏轮入口前置折叠段逐条消化 `_inbox/` 存量
- 2026-11-04 memory-distill-open-gaps-hazards（spec/knowledge/_inbox/done/memory-distill-open-gaps-hazards.md） — 折叠批产物心跳保活（900s 心跳间隔快于 1800s stale 阈值、收尾先 join 再写终态）与放弃清理半径处方（恢复新建的 untracked 产物同在清理半径、恢复后第一动作 commit 入库不留窗口）
- 2026-11-04 distill-econnreset-misattrib-recover-sweep-race（spec/knowledge/_inbox/done/distill-econnreset-misattrib-recover-sweep-race.md） — 折叠 spawn 拒识分类误归因面（stderr 启动噪声行盖 stdout 瞬断死因、显式传名确定性断言误抑重试、死因取证以 stdout API Error 行为准）与台账恢复单点现状（重派只挂初始化、主循环检查点仅欠账提醒不重派、主蒸馏无轮内自愈等效物）
- 2026-11-06 distill-batch-fold-tax-and-artifact-no-content-1106（spec/knowledge/_inbox/done/distill-batch-fold-tax-and-artifact-no-content-1106.md） — 折叠批耗时口径（单 SPEC 基准约 10 分钟、长批由折叠积压税主导）与 run 观测面缺口登记（事件流只记四类事件、result 行无改动文件清单、产出取证走 git log），并登记 _inbox 常驻 untracked 条目触发基线 WARNING 的已知误报面
