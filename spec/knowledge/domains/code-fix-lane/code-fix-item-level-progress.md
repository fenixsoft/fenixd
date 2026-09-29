# 修复批内条级进度

<!-- knowledge: capability=code-fix-item-level-progress rev=1
     sources=spec/archive/2026-09-28-add-code-fix-item-level-progress -->

code-fix 车道在批内实时呈现条级处置明细：读侧经 agent 增量产物文件合成「本批已处置多少条、刚完成哪条」，填补批级进度长批恒 0% 的可观测空洞。批级快照结构与链级语义见 [code-fix-progress](code-fix-progress.md)，agent 逐条追加 out 文件的输出契约见 [code-fix-agent](code-fix-agent.md)。

## 规则

### 批上下文落盘

- 修复批启动时，编排器把批上下文写入 `.fenix/code-review/fix-progress.json` 三个键：`worktree`（本批 worktree 绝对路径）、`run_id`（本批 code-fix run 标识）、`batch_total`（本批条目数，条级文案分母）。
- 三个键必须在进度文件缺省键集内（缺省 null）：进度文件读侧为白名单合并语义，缺省集之外的键读侧不可见、且会被下一次合并写静默剥离。
- 写入时点在建树成功后、agent run 启动前（`phase="fixing"` 写点位于建树后）——更早的写点拿不到 worktree/run_id。run 在飞期间三键必须在场，读侧才能在 run 结束前解析增量产物。
- `run_id` 由编排器预生成并经既有 run 形参传入，run 内部不再自行生成：不预生成则编排器在 run 返回前无从得知 run_id，条级进度恰好在目标窗口（run 在飞期间）失效。预生成保持 `code-fix-` 前缀并按在飞判据同口径去重。
- 重试轮预生成 run_id 时，既往轮的 run_id 计入禁用集（重试产物落同一 worktree，主树在飞判据覆盖不到，须显式排除撞号）。
- 批收尾清除三键：全部失败收尾、checkpoint 各终态写、merging 完成写、保留现场收尾、切批 selecting 写均须落 null。切批写时三键必须已为 null，防上一批的陈旧索引（含保留 worktree 的失败批）被继续合成。
- 进度文件缺这三键按「批上下文不可用」处理，不视为错误。

### 条级字段实时合成

- 进度读取在 `running=true` 且批上下文可用时，经 out 文件（`<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl`）实时合成两个条级字段：
  - `item_done`：本批已处置条数，out 有效行按 `item_id` 去重计数（同条目重复追加只计一次，取末次）；
  - `current_item`：最近一条有效结果行对应的摘要对象 `{item_id, status, file, title}`；`title` 与可选 `line` 以 CR 台账按 `item_id` 回查补全（批内条目核销前保持 open，是唯一持久化且字段齐全的清单源）；台账不可达或匹配失败时降级为仅含 out 行自带的 `item_id/status/file`。
- 两个字段是**现算字段，不落盘**：不在持久化快照中留存（合并写剥离），避免陈旧快照被后续合并写冻结成误导性数字。
- 以下任一场景 `item_done`/`current_item` 均为 null——不得报错、不得回退为 0 或空对象等可被误读为「卡死」的值：`running != true`；批上下文缺失；out 文件缺失或零有效行；解析抛出任何异常。损坏行不计入（沿用 out 解析既有容错口径）。
- worktree 收尾清理后 out 随之不可达，条级字段让位属预期：彼时批级字段已承载终值，批级进度是唯一事实源。

### 转导与前端呈现

- Dashboard 读侧原样透传 `item_done`/`current_item`/`batch_total`；`worktree`/`run_id` 是内部定位索引，进度端点响应不得外泄这两个键。
- `running=true` 时进度卡片次级文案：
  - `item_done` 非 null：追加「本批已处置 N/M 条 · 刚完成：<status 中文>：<file> <title>」（M=`batch_total`，缺失时仅显示「本批已处置 N 条」）；
  - `item_done` 为 null 且 `phase="fixing"`：追加「批内明细尚未产生（agent 处置中）」，不显示 `0/N` 之类误导计数；
  - 非 fixing 阶段（验证/合并等）不渲染条级文案区块。

## 溯源

- [2026-09-28 2026-09-28-add-code-fix-item-level-progress](spec/archive/2026-09-28-add-code-fix-item-level-progress/) — 新建本页：批上下文三键落盘与清除纪律、读侧经 out 文件实时合成 item_done/current_item、null 三态容错、进度卡片条级文案。
