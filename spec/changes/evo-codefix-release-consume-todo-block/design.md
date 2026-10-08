# design — codefix-release-consume-todo-block

## 实证与定位

- 现场链：fix-failed-release.jsonl 唯一行 released_at=2026-10-08T12:41:45Z、released_records=1、8 个 item_ids；fix-failed.json 现存 3 条已核销（consumed_at=2026-10-08T00:48:17Z）记录、1791442427 不在册；items.jsonl 8 条 resolved_at=2026-10-08T13:13:11.209627+00:00；登记块正文 00:15:34（review-2026-10-09.jsonl:90）尚在、55dabdfe（00:33:53）提交时只剩裸标题壳。
- release 路径：core/code_fix.py:1135-1194，`_do` 闭包剔除命中 ids、整批命中丢弃记录（:1182）、`_atomic_write` 整列表重写（:1184-1188）、`_with_lock`（:1191，伴生 .fix-failed.json.lock）；函数体零 todo 引用；留痕 `_append_release_trace`（:1214-1242）在 :1193 锁外追加。
- consume 路径：consume_resolved_failed_batches（:1349-1435）:1378-1379 按注册表记录过滤 pending（`not rec.get('consumed_at')`），记录已删即永远够不着 todo 块；核销动作=锁内置 consumed_at + 锁外 `_rewrite_todo_entry_consumed`（:1289-1346，持 .fenix/.todo.md.lock、needle=「被跳过的条目集合」ids 行、裸标题兜底 :1336-1337）；挂点 `_consume_failed_registrations`（:4317-4340）。

## 决策

1. **同调用序列而非同锁**：条目建议「同一锁内」字面不成立也不必要——fix-failed 锁与 todo 锁是两把锁，嵌套引入锁序风险；在删除成功后、同一函数调用序列内做 todo 重写（best-effort、OSError 容错）。崩溃窗口仅剩「已解除未核销」退回现状，不比今天更差，且留痕行的 todo 处理结果字段保证可审计。
2. **不采用「打 consumed 标记保留记录」**：字面不可行——:1379 pending 过滤跳过带 consumed_at 的记录，须另立 released_at 字段并改 pending 过滤，改动面更大，且与既有「解除=出册」语义冲突；仅当实现中发现 needle 定位失效率超预期时再评估该方向。
3. **自动释放路径一并接入**：release_retryable_failed_batches 是 release_failed_batch 的自动化等效路径，不接则缺口只修一半；留痕行增 released_by 字段区分人工/自动，released_records/item_ids 结构沿用。
4. **裸标题壳兜底复用既有逻辑**：:1336-1337 已有按标题移除残骸的实现（目前只在某条记录被核销时搭便车触发），本变更让 release 路径也能走到它，不新造。

## 权衡

- best-effort 核销可能因 todo.md 瞬时写冲突失败——后果仅是裸标题壳残留（比正文完整但无人核销的现状轻），留痕行 not_found/consumed 字段保证「解除未核销」可被事后审计。
- 自动释放补留痕会轻微增加 fix-failed-release.jsonl 行数——该文件本就是解除审计的唯一载体，可接受。