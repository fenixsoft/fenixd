# 归档触发蒸馏管线

<!-- knowledge: capability=knowledge-distill-pipeline rev=1
     sources=spec/archive/2026-10-05-add-knowledge-atlas -->

SPEC 归档完成后自动派发蒸馏 run，把归档 delta 蒸馏进真相源能力页的增量车道：合并语义、确定性对账、自动提交一体完成。

## 规则

- 触发挂载：蒸馏派发单点挂在归档共同漏斗 `core/archive_commit.py::commit_archive_move` 移动成功分支，手工归档与 daemon 自动归档两条路径同等生效；软删除以归档移动收尾、经同一漏斗触发蒸馏属预期行为。派发 fail-open：失败只记日志并登记 `.fenix/todo.md` 重试台账（给人看的队列，不进任务门禁），不影响归档本身的返回与结果。
- 门控链：`knowledge.enabled=false` 时跳过派发（归档照旧）；配置解析失败按禁用处理（保守不派发）；归档目录缺失或归档名含路径成分时拒绝；pytest 测试环境恒不派发（替身经 dispatcher 参数注入，既有单测直调漏斗不触发真实蒸馏）。
- 单飞：同 project 同时至多一个蒸馏 run 写 `spec/knowledge/`——进程内 per-project 队列单 worker 串行消费 + 跨进程 flock（`.fenix/knowledge-distill.lock`）；并发归档事件排队串行，积压条目合并为一次批量 run（`dispatch_distill_batch` 同门控）。
- run 形态：daemon spawn `claude -p` 后台线程，cwd 主树直跑（真相源是 spec 元数据层非产品代码，无 merge-back），注入 `core/knowledge_prompts/distill.md` 提示词；写路径限定 `spec/knowledge/`（及 `.fenix/` 台账），run 前后 `git status` 对账越界写面——合法写面外的新增改动记 WARNING 留痕、不自动回滚（避免吞掉用户未提交改动）。
- 合并语义（后写覆盖前写）：读归档 `specs/<capability>/spec.md` delta 与 proposal 摘要处理每个 capability——真相源无该页则新建（rev=1）；已有则按本次 delta 整体重写受影响规则段（rev+1、溯源追加一行），旧规则从规则段消失；REMOVED 规则从规则段移除、溯源留「已随 <归档名> 废除」行，页面其余规则不动；主从分片按 capability 名聚合、整体重写全部分片。
- 收尾对账（确定性脚本，非 LLM）：`core/knowledge.py::validate_knowledge` 校验 marker 可解析、sources 指向真实归档目录、单页 ≤150 行、index/_domain/adr 链接可解析且不越界、ADR 三段式与 accepted 正文不可变、Superseded by 指向存在条目；违规清单回反馈给 run 修正（≤2 轮），仍违规则放弃产出——daemon 侧 `git restore` 真相源目录并清理未跟踪新增，不留半成品；放弃按批次级基线快照判别，不吞用户 run 前既有的未提交改动。
- 自动提交：校验全过后 pathspec 限定 `spec/knowledge/` 提交，commit 形如 `[fenix] knowledge: distill <归档名>`；无变更（如重复蒸馏同批归档）跳过空提交、按 ok 处理；提交失败 fail-open 记 warning。
- 原料缺失降级（不判 run 失败）：归档无 `design.md` 跳过 ADR 抽取；无 `specs/` delta 按 proposal 摘要口径蒸馏能力页，或提不出任何当前规则时在能力页溯源段留一行「已审阅 <归档名>：无可蒸馏规则」，不虚构内容。

## 溯源

- 2026-10-05 add-knowledge-atlas（spec/archive/2026-10-05-add-knowledge-atlas/） — 新增本能力页：双路径单点挂载、ADDED/MODIFIED/REMOVED 合并语义、fail-open 与重试台账、单飞约束、收尾校验与自动提交、原料缺失降级
