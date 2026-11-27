## 设计

### 状态存储

复用 .fenix/knowledge_audit_state.json（已有 last_audit_date / last_scale 等键；该文件在 .fenix/* gitignore 内，不入库），新增三键，不新增文件：

- `last_escalated_reminded_date`：上次实际落库（upsert 写盘成功）聚合行的本地日 `YYYY-MM-DD`；
- `last_escalated_fingerprint_set`：上次落库/消费更新时的 escalated 指纹排序列表（用于识别集合新增/减少）；
- `last_escalated_consumed_date`：最近一次仲裁消费发生日 `YYYY-MM-DD`（从未消费时缺席）。

写侧持既有 `_state_write_lock`（core/knowledge_audit.py:188）并回读盘上状态合并（同 last_audit_date 口径，:960-970），只改本 SPEC 三键，不覆盖他人快照。键缺失/类型损坏一律按「无历史」处理并走向「本轮应拍」，MUST NOT 静默抑制提醒。

### 改动点与门控位置

在 core/knowledge_audit.py 的 run_audit 收尾 escalated 聚合行 upsert 调用点（当前 :2396-2416，即 `upsert_todo_line(project_root, TODO_ESCALATED_AGG_PREFIX, _escalated_todo_line(escalated), cleanup_prefixes=(TODO_ESCALATED_LEGACY_PREFIX,))`）**之前**做节拍判断。

- 跳过一拍 = 完全不调用 upsert（不写盘不提交，log.info 留痕下次提醒日）。
- MUST NOT 以「`_escalated_todo_line` 返回空串」实现跳过——upsert 对空串走纯清理语义（core/knowledge_backfill.py:278-341），会删除聚合行、丢失欠账信号。
- `_escalated_summary`（:391）被体检报告消费（:1934、:2544），MUST 保持原样；门控不得放进 `_escalated_summary` / `_escalated_todo_line` 内部，否则报告汇总会被节拍污染。

### 降频判定（纯函数）

新增纯函数便于单测：

```python
def _escalated_reminder_due(escalated: dict, state: dict, today: str) -> tuple[bool, bool]:
    """返回 (本轮是否应拍, 本拍是否为降频态)。"""
```

口径（`stale_days = cfg["escalated_stale_days"]`，config 单源白名单解析、缺省 7；MUST NOT 在本文件新增第二个 7 常量——:88-94 既有单源纪律）：

1. 集合变化旁路：当前指纹集 `sorted(escalated)` ≠ `last_escalated_fingerprint_set` → 应拍（新增疑点当日可见）。
2. escalated 为空 → 应拍（走既有纯清理语义摘除残留行），降频态 False，并复位三键。
3. 超龄判据：`_escalated_summary(escalated)["max_age_days"] > stale_days`（与 disputed 注记 :422-442 同口径，严格大于）。
4. 降频态 = 超龄 且（无 `last_escalated_consumed_date`，或今日距该日 > stale_days），即「持续零消费超阈值」。
5. 应拍 = 非降频态（每日一拍）或 距 `last_escalated_reminded_date` ≥ stale_days（降频后每 stale_days 天一拍，缺省 7 即每周）或 集合变化；否则跳过。降频态拍出时文案附注记，非降频态不附。
6. 集合减少（当前集是上次集的真子集，且非 consume_arbitration 已记账）视同消费活动：同时把 `last_escalated_consumed_date` 置 today，恢复每日节拍。

### 落库与状态刷新

- 应拍且 escalated 非空：`_escalated_todo_line` 增加可选参数 `decayed: bool = False`，True 时行尾追加「（已降频为每周一拍、欠账仍在）」，其余文案逐字节不变（兼容既有全前缀 `startswith` 断言）。
- 仅当 upsert 实际写盘（返回 True）时，持 `_state_write_lock` 回读合并刷新 `last_escalated_reminded_date = today` 与 `last_escalated_fingerprint_set = sorted(escalated)`；upsert 返回 False（幂等零写）或抛 OSError（既有 fail-open 降级 WARNING）时 **不刷新日期**，下一轮体检重试——避免写失败反被降频抑制 7 天。
- escalated 为空：照常调用 upsert 走纯清理（旁路降频），随后复位三键。

### 消费后恢复

`consume_arbitration`（:700）仅在 `consumed` 非空时，于既有 `_state_write_lock` 合并段追加记账：`last_escalated_consumed_date = today`、删除 `last_escalated_reminded_date`、更新 `last_escalated_fingerprint_set`；`consumed` 为空时零写（保持既有「零写零提交」轻量语义）。消费判定、台账删除、disputed 注记摘除与自提交行为不变。

恢复语义：`last_escalated_consumed_date` 重置后，降频态在随后 stale_days 天内不成立 → 每日一拍；超过阈值且集合不再变化后，重新回到每 stale_days 天一拍。

### 兼容性

- todo 聚合行前缀 `TODO_ESCALATED_AGG_PREFIX`（:112）与原位替换语义不变；跳过周期完全不触碰该行（保持旧行原文，不清空）。
- disputed 注记（:88-94、:422-442）与消费检查点（fenixd.py:1929-1931 → core/knowledge_audit.py:901-980）零改动。
- 状态文件在 .gitignore（.fenix/*，仅 todo.md/verify.yaml/config.template.yaml 等白名单入库），新增键不产生提交。

### 测试设计

tests/test_knowledge_audit_reminder_decay.py（新建）：

- 未超龄（max_age_days ≤ stale_days）：每日一拍。
- 超龄且持续零消费：首拍后间隔内跳过 upsert，todo.md 聚合行保持原样（不被清空），文案含降频注记。
- 降频期间新增 escalated 指纹：当日应拍（集合变化旁路）。
- 消费任一指纹后：零消费计时重置，随后每日一拍；超过 stale_days 后重新降频。
- escalated 全部消费：当日纯清理摘除残留行并复位三键。
- 状态键缺失/损坏、upsert 抛 OSError：本拍应拍，且写失败不刷新日期（下轮重试）。
- 回归：tests/test_knowledge_audit.py、tests/test_knowledge_audit_escalation_governance.py、tests/test_knowledge_backfill.py 保持全绿，upsert 幂等/清理语义与 consume_arbitration 行为不变。
