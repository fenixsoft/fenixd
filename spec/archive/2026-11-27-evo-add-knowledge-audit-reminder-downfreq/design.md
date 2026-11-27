# 设计：知识体检聚合提醒龄期降频

## D1. 状态键

.fenix/knowledge_audit_state.json 新增两键（经 _read_state/_write_state，写侧持 _state_write_lock 并回读合并，同 last_audit_date 的既有口径）：

- last_escalated_reminder_date: "YYYY-MM-DD"（上次实际 upsert 拍的本地日）
- last_escalated_set: 排序后的 escalated 完整指纹列表（当前 17 条量级、规模有界，直接存列表避免 hash 碰撞歧义）

## D2. 降频判定抽纯函数

core/knowledge_audit.py 新增纯函数便于单测：

```python
def _escalated_reminder_due(escalated: dict, state: dict, today: str) -> bool:
    """True = 本轮应拍（首次/集变化/距上次 ≥7 天）；False = 同集 7 天内跳过。"""
```

判定序：escalated 为空 → True（走清理旁路，调用点对空集本就是纯清理语义）；集与 state.last_escalated_set 不同 → True；同集且 (today - last_escalated_reminder_date) ≥ 7 天 → True；否则 False。本地日口径沿用 _today()。

集合比较前两侧均按 `sorted()` 归一化。fail-open：`last_escalated_set` 非列表、`last_escalated_reminder_date` 缺失/非法/晚于 today（时钟回拨或手编）一律返回 True（应拍），绝不抛异常——与 `_read_state` 的 fail-open 口径一致。日期差经 `core.timelib.parse_ts` 解析后按自然日相减。

## D3. 调用点接入

run_audit 收尾 upsert 调用点（约 :2407-2414）前置判定：

- 判定 False → 跳过 upsert（不写盘不提交），log.info 留痕一行（含下次提醒日）。跳过前先只读校验 todo.md 中以 TODO_ESCALATED_AGG_PREFIX 开头的聚合行仍在：行缺失（人工删除/外部清理）则强制拍，不等待 7 天窗口结束——降频不得换来「提醒缺席」。
- 判定 True 且 escalated 非空 → 照常 upsert，行尾追加「（下次重复提醒不早于 YYYY-MM-DD）」。**状态键只在 upsert 实际写盘成功（返回 True）后**持 _state_write_lock 回读合并更新：写路径抛 OSError 或 strict 解码失败（返回 False）时不更新状态键，下一轮重拍——写失败不得换来 7 天静默。
- escalated 为空 → 照常走纯清理语义摘除残留行，顺手持锁回读合并重置两状态键（双保险：防陈旧集让恢复后首拍被误跳过——集变化本身已会触发拍）。

## D4. 行文案

_escalated_todo_line 增加可选参数 next_remind_date（None 时不追加尾注，既有调用兼容）。既有文案其余部分保持逐字节稳定约定不受影响——尾注只进 todo 聚合行，不进页面 disputed 注记。

## D5. 测试

tests/test_knowledge_audit_reminder_downfreq.py（新建）针对判定纯函数与行文案，必要时以桩 findings 台账驱动收尾段：

- 同集 7 天内跳过：state 记近日期 + 同集 → 判定 False，upsert 不发生。
- 集变化立即拍：新增一条 escalated → 判定 True，行含下次提醒尾注。
- 清零旁路：escalated 清空 → 判定 True 且清理语义执行。
- 到期恢复拍：last_escalated_reminder_date 为 8 天前 → 判定 True 且刷新两状态键。
- fail-open：状态键缺失/损坏、日期晚于 today、last_escalated_set 形状不符 → 判定 True 不抛异常。
- 写失败不静默：upsert 抛 OSError 或 strict 解码失败 → 状态键不刷新，下一轮仍重拍。
- 在场性兜底：聚合行被外部删除而判定本应跳过 → 强制拍并重建行。
- 回归：既有 knowledge audit 相关测试（tests/ 下 grep 定位）全绿，确认 upsert 既有幂等/清理语义与消费侧未被破坏。

## D6. 既有测试与知识真相源同步

- `tests/test_knowledge_audit_escalation_governance.py::test_todo_aggregated_row_upsert_replaces_not_appends` 的「龄期推进 → 整行替换」段在同日连跑两次 run_audit 且指纹集不变：首跑落 last_escalated_reminder_date=today，次跑按降频跳过，现行「最长龄期 9 天」断言将失败。该用例 MUST 在第二次 run 前把状态键回拨 ≥7 天（或清空两键）模拟到期，并另增「同日第二跑零写盘」断言（新测试覆盖）。
- `spec/knowledge/domains/knowledge-atlas/knowledge-audit.md`「升级聚合与唯一人工入口」条现存文字「龄期推进时替换而非追加，聚合行不成为每日重述」与本 SPEC 的 7 天节拍相反；实施时 MUST 同步改写该条（含两状态键、集变化立即拍、清理旁路与 tail 文案），并更新页首 rev 与溯源段，避免知识真相源与代码行为相反。

## D7. 与在途草稿的关系（去重）

`spec/changes/evo-knowledge-audit-reminder-frequency-decay` 与本 SPEC 目标重叠，但判据与状态键不同：前者以「escalated 持续零消费超 stale_days」为降频条件、以消费事件重置为每日节拍，键名 `last_escalated_reminded_date` / `last_escalated_fingerprint_set`；本 SPEC 以「同指纹集 + 7 天窗口 + 集变化立即拍」为准，键名 `last_escalated_reminder_date` / `last_escalated_set`。两 SPEC MUST NOT 同时实施：对现网 58 天积压形态两者效果等价（首拍后即入 7 天窗口，消费使集变化立即拍），实施前由编排层择一；若前者先落地，本 SPEC 以其为基线合并，保留 7 天窗口判据并删除重复状态键与重复测试文件。