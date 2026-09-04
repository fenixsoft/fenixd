## ADDED Requirements

### Requirement: 自动归档阈值配置

系统 SHALL 支持 `archive.auto_threshold` 配置键（用户级与项目级均可设置，项目级优先，参与既有配置热更新）：已完成（done/pushed）SPEC 数量超过该阈值时触发自动归档；默认值 50；设为 0 SHALL 表示禁用自动归档。设置页「其他」面板 SHALL 提供该阈值的输入控件（非负整数，0 = 禁用），与既有 runs.keep 字段并列，保存后经热更新生效。

#### Scenario: 设置界面展示并保存阈值

- **WHEN** 用户打开设置页「其他」面板
- **THEN** 可见「自动归档阈值」输入框（含 0 = 禁用说明），输入 30 保存后配置文件写入 archive.auto_threshold: 30

#### Scenario: 非法输入被拦截

- **WHEN** 用户输入负数或非整数并保存
- **THEN** 表单校验拦截提示，不写入配置

#### Scenario: 热更新生效

- **GIVEN** daemon 运行中
- **WHEN** 用户修改 auto_threshold 并保存（含直接编辑配置文件）
- **THEN** 无需重启 daemon，下一轮自动归档检查即采用新阈值

### Requirement: daemon 周期检查并执行自动归档

daemon 主循环 SHALL 周期性（独立低频计时，量级为分钟级）对每个项目执行自动归档检查：统计状态为 done/pushed 且未归档（`openspec/changes/<name>/` 目录仍存在）的 SPEC 数量；超过有效阈值时，按完成时间从最久到最新依次归档（调用与手动归档相同的移动逻辑：目录移入 `openspec/changes/archive/YYYY-MM-DD-<name>/`，STATE.md 条目保留），直到未归档终态数量降至阈值以内。阈值有效值为 0 或配置缺失时 SHALL 跳过检查。完成时间 SHALL 取 STATE.md 条目的 updated 字段（终态 SPEC 不再更新，updated 即完成时间）。单个 SPEC 归档失败（如目标目录已存在）SHALL 跳过该条并继续处理其余，且记录日志，不中断检查循环。

#### Scenario: 超阈值自动归档最久完成的

- **GIVEN** 某项目 auto_threshold=2，存在 4 个终态 SPEC，完成时间 A<B<C<D
- **WHEN** daemon 执行自动归档检查
- **THEN** A、B 被归档（目录移入 archive/），C、D 保留，数量降至阈值以内

#### Scenario: 未超阈值不动作

- **GIVEN** 某项目终态 SPEC 数量未超过阈值
- **WHEN** daemon 执行自动归档检查
- **THEN** 不移动任何目录，日志无归档动作

#### Scenario: 阈值为 0 或缺失时禁用

- **GIVEN** 某项目 archive.auto_threshold=0（或未配置且无默认值生效路径之外显式设 0）
- **WHEN** daemon 执行检查
- **THEN** 跳过该项目，不做任何归档

#### Scenario: 单条失败不阻塞

- **GIVEN** 待归档队列中最久一条的归档目标目录已存在
- **WHEN** daemon 执行自动归档
- **THEN** 该条被跳过并记录日志，其余符合条件的 SPEC 正常归档

#### Scenario: 非终态与已归档不计入阈值

- **GIVEN** 某项目有 3 个终态未归档 SPEC、2 个 implementing、1 个已归档终态
- **WHEN** 阈值为 3 时执行检查
- **THEN** 数量为 3 未超阈值，无归档动作（implementing 与已归档条目不计入）
