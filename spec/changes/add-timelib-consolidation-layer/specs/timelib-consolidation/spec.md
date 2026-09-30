## ADDED Requirements

### Requirement: 唯一时间原语模块 core/timelib.py

系统 SHALL 提供 `core/timelib.py` 作为全框架唯一时间原语模块，零第三方依赖，导出以下 API：

- `now_utc() -> datetime`：返回 aware UTC 当前时间（等价 `datetime.now(timezone.utc)`）
- `now_local() -> datetime`：返回 aware 本地时区当前时间（等价 `datetime.now().astimezone()`）
- `parse_ts(value) -> Optional[datetime]`：唯一时间戳解析入口，接受 ISO 字符串（含 `Z` 后缀、`+00:00` 偏移、无偏移 naive、纯日期串）
- `from_epoch(ts: float) -> datetime`：epoch 秒 → aware UTC（替代裸 `fromtimestamp()`）
- `to_storage(dt: datetime) -> str`：写侧唯一序列化，输出 ISO UTC 且以 `Z` 后缀结尾
- `fmt_display(value, fmt="%Y-%m-%d %H:%M:%S") -> str`：渲染边界转换，接受 datetime 或 ISO 字符串，按本地时区输出人读串

模块外代码 MUST NOT 直接调用 `datetime.now()`（零参）、`datetime.utcnow()`、裸 `datetime.fromtimestamp()`、`datetime.fromisoformat()` 产生或解析时间戳。

#### Scenario: now_utc 返回 aware UTC
- **WHEN** 调用 `timelib.now_utc()`
- **THEN** 返回值的 `tzinfo` 等于 `timezone.utc`，`utcoffset()` 为零

#### Scenario: to_storage 输出 Z 后缀
- **WHEN** 对任一 aware datetime（UTC 或本地）调用 `to_storage`
- **THEN** 返回字符串以 `Z` 结尾且对应同一 UTC 时刻（本地 `2026-09-30 10:33 +08:00` 序列化为 `2026-09-30T02:33:00Z` 形态）

#### Scenario: fmt_display 按本地时区输出
- **WHEN** 对 UTC 时刻字符串 `2026-09-30T02:33:00Z` 调用 `fmt_display`（机器时区 Asia/Shanghai）
- **THEN** 输出 `2026-09-30 10:33:00`

### Requirement: naive 时间戳唯一解读策略为本地时区

`parse_ts` 对无时区后缀的输入 SHALL 按系统本地时区解读（定调 2026-09-30：存量 naive 数据实测多数产自本地 `now()`，机器时区固定 Asia/Shanghai）。该策略为全框架唯一 naive 解释，任何模块 MUST NOT 自行实现第二种 naive 解读。解析失败（非法串、非字符串类型）SHALL 返回 `None` 而非抛异常。

#### Scenario: naive 输入按本地解读
- **WHEN** 调用 `parse_ts("2026-09-30T10:33:00")`（机器时区 Asia/Shanghai）
- **THEN** 返回 aware datetime，UTC 时刻为 `2026-09-30T02:33:00+00:00`

#### Scenario: Z 后缀与 +00:00 等价
- **WHEN** 分别调用 `parse_ts("2026-09-30T02:33:00Z")` 与 `parse_ts("2026-09-30T02:33:00+00:00")`
- **THEN** 两次返回相等的 aware datetime（UTC 时刻不变，不叠加时区偏移）

#### Scenario: 非法输入返回 None 不抛异常
- **WHEN** 调用 `parse_ts("not-a-time")` 或 `parse_ts(None)` 或 `parse_ts("")`
- **THEN** 返回 `None`

### Requirement: 分层时区约定

时间值 SHALL 按层定性：存储与计算层一律 aware UTC；本地时区只允许出现在渲染边界（CLI 展示、knowledge 真相源盖戳、浏览器 dayjs 前端）与调度语义边界（`HH:MM` 人类时刻配置，进入计算前转为 aware UTC）。浏览器前端 dayjs 本地渲染与 `verify_engine/browser.py` 的 `timezone_id`（playwright 语义）不在本约定管辖范围。

#### Scenario: 知识真相源本地盖戳行为不变
- **WHEN** knowledge 蒸馏/回填管线盖戳（`knowledge.local_now_stamp` 与 `knowledge_backfill._now_local_parts` 两个同逻辑副本的时间源均改走 `timelib.now_local()` 后）
- **THEN** 输出格式与改造前逐字一致：`("2026-09-30 10:33", "UTC+8")`，行格式 `> 最后更新：YYYY-MM-DD HH:MM UTC+8`

### Requirement: 读侧矛盾 naive 策略统一修复

以下 4 处读侧解析 MUST 改走 `timelib.parse_ts`（naive 统一按本地解读）：`core/regression.py`（现 naive→本地 `astimezone()`）、`core/dashboard/data/timeline.py` 的 `_parse_iso_ts`（现 naive 补 `tzinfo=utc`）、`core/dashboard/routes/code_review_routes.py`（现 naive 补 `tzinfo=utc`）、`core/evolution.py` 的 `_parse_iso`（现 naive 附本地 tzinfo 再转 UTC）。其中 `timeline.py` 的修改推翻 fix-deferred-findings D2 实现注释「naive 补 `tzinfo=utc`」；实现时 MUST 先以该域真实存量数据验读，列出行为差异点后再切换。

#### Scenario: 四处读侧对同一 naive 串解读一致
- **WHEN** 同一 naive 串 `2026-09-30T10:33:00` 分别经 regression 守卫、timeline `_parse_iso_ts`、code_review_routes 解析器、evolution `_parse_iso` 处理（机器时区 Asia/Shanghai）
- **THEN** 四处得到的 UTC 时刻一致，均为 `2026-09-30T02:33:00+00:00`

#### Scenario: timeline 域写手格式验读先于切换
- **WHEN** 实现修改 `timeline.py` naive 策略前
- **THEN** 从该域写手代码（含 `code_review.py` 剥时区写入链）提取实际序列化格式，构造覆盖全部已知写手形态的数据集（naive 本地、naive UTC、`Z` 后缀、`+00:00`），新旧两种解析逐条对照，差异清单落入测试注释或实现记录且差异可解释（worktree 内不可达 `.fenix` 运行时真实数据时，按写手实现构造等价 fixture 代替）

### Requirement: 重复转换轮子收拢

`core/code_review.py` 与 `core/self_review.py` 中逐字重复的 `_iso_to_local_dt` MUST 收拢为对 `timelib.parse_ts` 的转发（或直接改调用点删除副本）；`core/pm_engine/verification/escalation.py` 的 `_parse_ts`、`core/pm_engine/recovery.py` 的 `_parse_event_timestamp` 同批改走 `parse_ts`。本 requirement 仅限「解析收拢」，MUST NOT 改动 `self_review.py` 窗口比较的 naive 本地气泡语义（该迁移属后续全仓迁移 SPEC）。

#### Scenario: 重复副本删除后行为等价
- **WHEN** `_iso_to_local_dt` 的既有调用点传入同一组合法与非法输入（含 `Z` 后缀、`+00:00`、naive、垃圾串、`None`）
- **THEN** 收拢后返回值与收拢前逐项相等（aware 本地 / `None`）

### Requirement: AST 静态守卫棘轮

系统 SHALL 新增 `tests/test_timelib_guard.py`（复用 `tests/fenix_guards.py` 扫描基建，AST 扫描 `core/**/*.py` 与 `fenixd.py`，排除 vendored 目录），锁定以下禁用模式：

- `datetime.now()` 零参调用（naive 产出）
- `datetime.utcnow()` 调用（已废弃且产出 naive）
- `datetime.fromtimestamp()` 零/单参调用（未显式指定 tz）
- `datetime.fromisoformat()` 出现在 `core/timelib.py` 之外
- `datetime.utcfromtimestamp()` 调用

守卫 MUST 维护显式白名单（最小粒度键，不含行号），上线时白名单=当日全部存量违例；此后白名单条目只允许减少。`core/timelib.py` 本身 MUST 豁免于全部禁用模式。测试目录（`tests/`）不在扫描范围。`.astimezone()` 不列入首批禁用模式。

#### Scenario: 新增违例即时失败
- **WHEN** 任一生产文件新增裸 `datetime.now()` 调用且不在白名单
- **THEN** `tests/test_timelib_guard.py` 失败并报出文件与行号

#### Scenario: 白名单只许收缩
- **WHEN** 白名单中某条目对应的违例代码已被迁移消除
- **THEN** 从白名单删除该条目后守卫保持通过；守卫 MUST 对「白名单条目已无对应违例」（僵尸条目）给出警告或失败，防止名单虚胖

#### Scenario: timelib 自身豁免
- **WHEN** `core/timelib.py` 内部使用 `datetime.fromisoformat` 实现解析
- **THEN** 守卫通过，不产生违例
