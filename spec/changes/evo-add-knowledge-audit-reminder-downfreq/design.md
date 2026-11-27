# 设计：知识体检聚合提醒龄期降频

## D1. 状态键

.fenix/knowledge_audit_state.json 新增两键（经 _read_state/_write_state，写侧持 _state_write_lock 并回读合并，同 last_audit_date 的既有口径）：

- last_escalated_reminder_date: "YYYY-MM-DD"（上次实际 upsert 拍的本地日）
- last_escalated_set: 排序后的 escalated 完整指纹列表（条目数 ≤13 量级，直接存列表避免 hash 碰撞歧义）

## D2. 降频判定抽纯函数

core/knowledge_audit.py 新增纯函数便于单测：

```python
def _escalated_reminder_due(escalated: dict, state: dict, today: str) -> bool:
    """True = 本轮应拍（首次/集变化/距上次 ≥7 天）；False = 同集 7 天内跳过。"""
```

判定序：escalated 为空 → True（走清理旁路，调用点对空集本就是纯清理语义）；集与 state.last_escalated_set 不同 → True；同集且 (today - last_escalated_reminder_date) ≥ 7 天 → True；否则 False。本地日口径沿用 _today()。

## D3. 调用点接入

run_audit 收尾 upsert 调用点（约 :2245-2253）前置判定：

- 判定 False → 跳过 upsert（不写盘不提交），log.info 留痕一行（含下次提醒日）。
- 判定 True 且 escalated 非空 → 照常 upsert，行尾追加「（下次重复提醒不早于 YYYY-MM-DD）」，随后持 _state_write_lock 回读合并更新两状态键。
- escalated 为空 → 照常走纯清理语义摘除残留行，顺手重置两状态键（双保险：防陈旧集让恢复后首拍被误跳过——集变化本身已会触发拍）。

## D4. 行文案

_escalated_todo_line 增加可选参数 next_remind_date（None 时不追加尾注，既有调用兼容）。既有文案其余部分保持逐字节稳定约定不受影响——尾注只进 todo 聚合行，不进页面 disputed 注记。

## D5. 测试

tests/test_knowledge_audit_reminder_downfreq.py（新建）针对判定纯函数与行文案，必要时以桩 findings 台账驱动收尾段：

- 同集 7 天内跳过：state 记近日期 + 同集 → 判定 False，upsert 不发生。
- 集变化立即拍：新增一条 escalated → 判定 True，行含下次提醒尾注。
- 清零旁路：escalated 清空 → 判定 True 且清理语义执行。
- 到期恢复拍：last_escalated_reminder_date 为 8 天前 → 判定 True 且刷新两状态键。
- 回归：既有 knowledge audit 相关测试（tests/ 下 grep 定位）全绿，确认 upsert 既有幂等/清理语义与消费侧未被破坏。