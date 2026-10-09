# spec：todo-ledger-loss-guard

## 能力

daemon 对自省台账 .fenix/todo.md 的全部写入路径具备「工作树被清空而 HEAD 有内容」的检测与自愈能力，台账内容丢失可从 git 恢复且留痕可追。

## 需求

### R1 回写前 HEAD 自愈

- daemon 写 todo.md 前，若工作树文件为空/缺失而 HEAD 版本（git show HEAD:.fenix/todo.md）非空，则以 HEAD 内容为基线执行本次写操作，并落一条 WARNING（含恢复字节数与提示：如系有意清空请复核或用开关豁免）。
- git show 失败（非仓库、无 HEAD 版本、超时）时静默回退为现状行为（按空基线写），不得阻塞回写。
- 恢复动作在既有 with_file_lock 锁内完成，与追加/覆写原子提交。

### R2 豁免开关

- 自省配置新增 todo_head_restore（缺省 true）；为 false 时跳过恢复、按现状行为写，不落恢复 WARNING（保留普通写入日志）。

### R3 未留痕写者收敛

- dashboard 的 todo.md 写入端点（POST /api/todo 路径）写入时持与 daemon 相同的 with_file_lock；成功写入落 INFO 留痕（路径+字节数），覆写为空内容而 HEAD 非空时落 WARNING。

### R4 约束

- 不改动 read_todo 语义与缺省。
- git 依赖限于 subprocess 只读调用（git show），与 self_review 既有 _commit_todo 同口径。
- 恢复仅回放 HEAD 版本基线，不尝试合并工作树中并存的其他未提交内容。

## 验收

1. 工作树 todo.md 为空且 HEAD 版非空时触发回写：落盘内容为 HEAD 版+新节，WARNING 留痕在案。
2. 工作树有内容时行为与现状完全一致（增量追加，不引 HEAD）。
3. todo_head_restore=false 时第 1 场景按现状行为写，无恢复 WARNING。
4. dashboard 端点写入持锁成功且 INFO 留痕；写空触发 WARNING。
5. tests/test_daily_self_review.py 等既有用例回归通过。