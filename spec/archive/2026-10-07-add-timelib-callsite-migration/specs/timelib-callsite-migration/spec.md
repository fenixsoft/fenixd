## ADDED Requirements

### Requirement: 守卫白名单清零

`add-timelib-consolidation-layer` 交付的 AST 守卫（`tests/test_timelib_guard.py`）白名单 SHALL 收缩为空集：全部生产文件（`core/**/*.py`、`fenixd.py`、`bin/*.py`）不再含任何禁用模式调用（零参 `datetime.now()`、`datetime.utcnow()`、零/单参 `fromtimestamp()`、`utcfromtimestamp()`、timelib 之外 `fromisoformat()`）。僵尸条目检测 MUST 全绿。

#### Scenario: 守卫零白名单通过
- **WHEN** 存量迁移完成且 `tests/test_timelib_guard.py` 白名单为空列表
- **THEN** 守卫测试通过，AST 扫描对禁用模式零命中

#### Scenario: 迁移完成后新违例仍被拦截
- **WHEN** 迁移合入后任一生产文件再次引入裸 `datetime.now()`
- **THEN** 守卫失败并报出文件与行号（棘轮不因白名单清空而失效）

### Requirement: self_review 本地 naive 气泡迁 aware UTC

`core/self_review.py` 的窗口计算 SHALL 整体迁 aware UTC：`_in_window` 两端、`window_start/window_end` 构造、mtime/run 起始时间戳（`from_epoch`）、run 记录解析统一 aware 比较。`HH:MM` 调度配置（`_parse_run_at`，单源 `SELF_REVIEW_DEFAULT_RUN_AT`）SHALL 保持人类时刻语义——按本地墙钟解析后立即转为 aware UTC 参与窗口计算，配置值本身不变。窗口判定结果 MUST 与迁移前一致（同一组 run 数据、同一调度配置下命中集合相同）。

#### Scenario: 窗口判定等价
- **WHEN** 以迁移前的同一组 run 时间戳数据与同一调度配置分别运行新旧窗口实现（机器时区 Asia/Shanghai）
- **THEN** 命中的 run 集合逐项相同

#### Scenario: 调度时刻语义保持本地墙钟
- **WHEN** 调度配置为 `23:00`（本地墙钟，UTC+8 机器）
- **THEN** 触发判定使用的 aware UTC 时刻为当日 `15:00Z`，配置文件中的 `23:00` 字面值不变

### Requirement: 写侧零 naive 产出

迁移完成后，任何持久化字段（jsonl、STATE.md、台账、dashboard API 响应）SHALL 不再新增 naive（无时区后缀）时间戳：写侧一律 `timelib.now_utc()` + `to_storage()`（aware UTC）。`HH:MM` 调度配置、knowledge 盖戳等人类可读形态不受此约束（它们是配置/渲染形态，非时间戳存储）。

#### Scenario: 新写时间戳带时区后缀
- **WHEN** 迁移后任一域写台账字段（如 `last_run_at`、`updated_at`）
- **THEN** 落盘串含 `Z` 或 `+HH:MM` 后缀，`parse_ts` 解析后 UTC 时刻与写入时刻一致

### Requirement: CLI 展示脚本统一 fmt_display

`bin/fenix_process.py` 与 `bin/fenix_dashboard.py` 的私有 `_local_ts` 助手 SHALL 退役，时间戳展示改走 `timelib.fmt_display`；展示输出格式保持与迁移前一致（`YYYY-MM-DD HH:MM:SS` 本地时区）。`bin/fenix_status.py`、`bin/fenix_dashboard.py` 的 `fromisoformat` 裸解析同步改走 `parse_ts`。

#### Scenario: CLI 展示输出不变
- **WHEN** 对同一 UTC 时间戳串（`Z` 后缀、`+00:00` 后缀、无后缀三形态）分别运行迁移前后 `bin/fenix_process.py` 的时间展示逻辑（机器时区 Asia/Shanghai）
- **THEN** 输出逐字一致；无后缀形态按本地解读（与 `parse_ts` 策略一致）

#### Scenario: 部署副本刷新已登记
- **WHEN** `bin/*.py` 真身修改合入主树
- **THEN** `.fenix/bin` 部署副本刷新的人工步骤已登记（`.fenix/todo.md` 或 docs help），注明「未跟踪文件不随 merge-back 落地，需主树手工同步或重启部署机制」

### Requirement: 域迁移不越界

各域迁移 MUST 限定在「等价替换」：不改窗口阈值、不改超时秒数、不改台账 schema 字段名、不改告警判定边界。凡迁移中发现必须的行为变化（如发现存量数据按旧解读已错 8 小时），MUST 在 `.fenix-run-result.json` 申报而非顺手修改，行为变化另行走 SPEC。

#### Scenario: 纯等价迁移无隐藏行为变化
- **WHEN** 单域迁移批次的 diff 审查
- **THEN** 除「naive 串 → aware UTC 串」与「时间原语换用 timelib」外，无任何数值/边界/字段名变化；发现的行为偏差已申报 unattainable 或另立项
