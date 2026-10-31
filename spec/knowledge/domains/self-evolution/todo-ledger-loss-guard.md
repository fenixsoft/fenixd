# 自省台账清空防护（todo.md 回写前 HEAD 自愈）

<!-- knowledge: capability=todo-ledger-loss-guard rev=1
     sources=spec/archive/2026-10-30-evo-self-review-todo-head-restore -->

daemon 对项目台账 `.fenix/todo.md` 全部内容损失型回写路径的空文件检测与自愈：工作树被清空而 HEAD 有内容时先从 HEAD 恢复基线再落写，未留痕写者收敛到持锁+留痕口径——台账内容丢失可从 git 恢复且留痕可追。

## 规则

- **回写前 HEAD 自愈**：daemon 写 todo.md 前，若工作树文件为空/缺失而 HEAD 版本（`git show HEAD:.fenix/todo.md`）非空，以 HEAD 内容为基线执行本次写操作，并落一条 WARNING（含恢复字节数与提示：如系有意清空请复核或用开关豁免）。恢复动作在既有 `with_file_lock` 锁内完成，与追加/覆写原子提交。
- **自愈失败静默回退**：`git show` 失败（项目非 git 仓库、无 HEAD 版本、30 秒超时）时静默回退为现状行为（按空基线写），不落恢复 WARNING、不阻塞回写——台账写入主路径永不因防护而失败。
- **豁免开关**：自省配置 `admin.self_review.todo_head_restore`（缺省 true）；false 时跳过恢复、按现状行为写，不落恢复 WARNING（保留普通写入日志），为有意清空台账留出通道，不与人工意图打架。
- **未留痕写者收敛**：dashboard 的 todo.md 覆写端点写入时持与 daemon 相同的 `with_file_lock`；成功写入落 INFO 留痕（路径+字节数），覆写为空内容而 HEAD 非空时落 WARNING；该侧 `git show` 失败时跳过 HEAD 对比、按现状写、不阻塞保存。
- **覆盖范围口径**：恢复接入「全部内容损失型回写路径」＝ self_review 三处回写（追加/跳过评审/清理已解决项）+ dashboard 覆写端点；evolution 的 `write_todo_marker` 不接入——其写入以当前文本中定位到条目为前置，空/缺文件上定位不到即跳过不写，天然非内容损失路径。
- **恢复语义边界**：恢复仅回放 HEAD 版本基线，不合并工作树中并存的其他未提交内容；git 依赖限于只读 subprocess 调用（`git show`），与既有 todo 提交助手同口径。read_todo 语义与缺省不受本能力影响（见 [daily-self-review](daily-self-review.md)）。

## 关键行为

- 工作树 todo.md 为空且 HEAD 版非空时回写：落盘内容为 HEAD 版+本次新节，WARNING 留痕在案；工作树有内容时行为与常规增量写完全一致（不引 HEAD）。
- 历史台账的一次性数据修复（历史完整版并入新节重提交）不走自动恢复，属人工运维操作；自动恢复只保「HEAD 基线不丢」。

## 溯源

- 2026-10-30 evo-self-review-todo-head-restore（spec/archive/2026-10-30-evo-self-review-todo-head-restore） — 新增本页：todo.md 回写前 HEAD 自愈（self_review 三处回写接入、锁内原子恢复、git show 失败静默回退）、`todo_head_restore` 豁免开关（缺省 true）、dashboard 覆写端点持锁+INFO/WARNING 留痕收敛；write_todo_marker 以「定位不到条目即跳过」豁免于恢复接入（动因：todo.md 曾被整文件清空后自省照常追加，119 行历史从工作树与 HEAD 双重缺席）
