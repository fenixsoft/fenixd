# code-fix-item-level-progress 规格

## ADDED Requirements

### Requirement: 批上下文落盘

编排器（core/code_fix.py）在本批修复 run 启动前，把批上下文写入 `fix-progress.json`：

- `worktree`：本批 worktree 绝对路径（字符串）；
- `run_id`：本批 code-fix run 标识（字符串）。

批收尾（进度进入终态或切批）时清除这两个字段。缺失这两个键的进度文件按「批上下文不可用」处理——不得视为错误。

#### Scenario: 批启动写入批上下文
- **WHEN** 编排器启动一批修复（batch_no=N，run_id=R，worktree=W）并写 `phase="fixing"`
- **THEN** `fix-progress.json` 同时含 `"worktree": W` 与 `"run_id": R`

#### Scenario: 批收尾清除批上下文
- **WHEN** 本批进入收尾写进度（回归结果已定、`done` 更新或 `running` 置 false）
- **THEN** `fix-progress.json` 不再含 `worktree` / `run_id` 键（或值为 null）

### Requirement: 条级进度实时合成

`read_progress()` 在 `running=true` 且批上下文可用时，经既有 `read_fix_out(worktree, run_id)` 实时合成条级字段：

- `item_done`：out 文件中有效结果行数（整数，本批已处置条数）；
- `current_item`：最近一条有效结果行匹配注入清单所得的摘要对象 `{item_id, status, file, title}`；`file`/`title` 取自注入清单条目（out 行只含 `item_id/status/file` 时以清单补全 `title`）。

以下任一条件成立时 `item_done`/`current_item` 均为 null（MUST NOT 500、MUST NOT 回退为 0/空对象等可被误读的值）：

- `running != true`；
- 批上下文缺失；
- out 文件缺失或零有效行；
- `read_fix_out` 抛出任何异常（兜底捕获）。

#### Scenario: 批内进行中合成条级进度
- **WHEN** `phase="fixing"`、`worktree`/`run_id` 在场，且 out 文件已有 6 条有效行（最近一条 `item_id=X, status=fixed`，注入清单中 X 的 title 为 T、line 为 L）
- **THEN** `read_progress()` 返回 `item_done=6`、`current_item={"item_id": "X", "status": "fixed", "file": <X 的 file>, "title": "T"}`，批级字段（`done`/`total`/`phase`）与文件内容一致不受影响

#### Scenario: out 文件尚未产出第一行
- **WHEN** `phase="fixing"`、批上下文在场，但 out 文件尚不存在（agent 尚未处置完任何一条）
- **THEN** `item_done` 与 `current_item` 均为 null，其余字段正常返回

#### Scenario: 损坏行不干扰计数
- **WHEN** out 文件共 8 行，其中 2 行为空行或非法 JSON
- **THEN** `item_done=6`（只计有效行，`read_fix_out` 既有容错口径）

#### Scenario: 批收尾后条级字段让位
- **WHEN** 批收尾，进度文件已无 `worktree`/`run_id` 且 `done` 已更新为本批核销数
- **THEN** `item_done` 与 `current_item` 为 null，批级进度即唯一事实源

### Requirement: Dashboard 条级进度展示

Dashboard 读侧（core/dashboard/data/code_review.py）把 `item_done`/`current_item` 原样透传给前端；`CodeFixProgressCard` 在 `running=true` 时：

- `item_done` 非 null：卡片次级文案追加「本批已处置 N/M 条 · 刚完成：<status 中文>：<file> <title>」；
- `item_done` 为 null 且 `phase="fixing"`：次级文案追加「批内明细尚未产生（agent 处置中）」——替代用户无法解读的静默 0%；
- 非 fixing 阶段（验证/合并等）：不显示条级文案。

#### Scenario: 卡片显示条级进展
- **WHEN** 进度接口返回 `running=true, phase="fixing", item_done=6, total=270, current_item={...}`
- **THEN** 卡片渲染含「本批已处置 6/20 条」与刚完成条目的文件与标题文案

#### Scenario: 明细未产生时的可读提示
- **WHEN** 进度接口返回 `running=true, phase="fixing", item_done=null`
- **THEN** 卡片渲染「批内明细尚未产生（agent 处置中）」，不显示 0/N 之类的误导性计数

#### Scenario: 非 fixing 阶段无条级文案
- **WHEN** 进度接口返回 `running=true, phase="verifying"`（或 merging 等）
- **THEN** 卡片不渲染条级文案区块
