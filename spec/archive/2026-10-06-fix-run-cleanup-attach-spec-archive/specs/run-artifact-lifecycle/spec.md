# run-artifact-lifecycle 能力规范

## ADDED Requirements

### Requirement: SPEC 归档时清理该 SPEC 的全部 run 产物

SPEC 归档执行时（`archive_spec_runs`，唯一入口，由 `bin/fenix_archive.py`
与 `spec_archive.py` 归档路径调用），该 SPEC 的 run 产物（`run_spec_part`
与 SPEC 名全等匹配的 `*.jsonl`）必须从**活跃目录与 `archive/` 归档副本两处
一并删除**（现行为仅顶层移入 archive/）。删除逐文件记日志（可审计），
单文件失败记 WARNING 继续其余文件，不阻断归档主流程。

#### Scenario: 归档 SPEC 后其产物两处均不存在
- **WHEN** `runs/` 顶层存在 `impl-foo-<ts>-a1.jsonl` 且 `runs/archive/` 存在
  同 SPEC 的 `verify-foo-<ts>-a1.jsonl`，对 SPEC `foo` 执行归档
- **THEN** 两处文件均被删除，`archive_spec_runs` 返回的清理计数为 2，
  日志含两条删除记录

#### Scenario: 归档对其他 SPEC 的产物零影响
- **WHEN** `runs/archive/` 存在 SPEC `bar` 的产物，对 SPEC `foo` 执行归档
- **THEN** SPEC `bar` 的产物保持原样

#### Scenario: 单文件删除失败不阻断
- **WHEN** 某*.jsonl 删除时抛 OSError（如权限），其余文件正常
- **THEN** 记 WARNING 后继续删除其余产物，归档流程不中断

### Requirement: 归档目录不再按 runs.keep 上限删除

保留清扫器（`runs_retention_check`）必须移除「归档目录按 `runs.keep`
上限最旧优先删除」的整段逻辑；归属活跃 SPEC 的归档产物在其 SPEC 归档前
**不被任何路径删除**。「终态 run 移入归档」（活跃目录有界性）保持不变。

#### Scenario: 未归档 SPEC 的归档产物跨周期存活
- **WHEN** `runs/archive/` 中存在活跃 SPEC `foo` 的产物，清扫器连续执行
  多个 300s 周期，归档条目数任意增长
- **THEN** SPEC `foo` 的产物始终存在，不被删除

#### Scenario: 活跃目录有界性不变
- **WHEN** `runs/` 顶层出现终态 run 产物
- **THEN** 清扫器仍将其移入 `archive/`（现行为零变化）

### Requirement: 取消 runs.keep 配置项

`runs.keep` 从配置体系移除：读侧无任何消费点；`config_admin` 的受管键
清单、缺省展示、回显与写入分支不再包含 `runs` 键。存量 `config.yaml`
中已写入的 `runs.keep` 值成为死键——读取无害、无迁移要求。

#### Scenario: 残留配置无害
- **WHEN** 项目 `config.yaml` 中仍写有 `runs: {keep: 120}`，守护进程加载
  配置并执行清扫器
- **THEN** 配置加载成功、清扫器正常执行，`keep` 值不产生任何行为影响

#### Scenario: 配置 API 不再接受 runs 键
- **WHEN** 经配置管理接口提交含 `runs: {keep: 120}` 的补丁
- **THEN** 该键被忽略（不落盘、不回显），其余键正常应用

### Requirement: 无主车道归档产物按天龄兜底清理

`runs/archive/` 中 `run_spec_part` 归属**不匹配任何活跃 SPEC**（`spec/changes/`
下无同名目录）且 mtime 距今超过保留天数（模块常量，14 天）的 `*.jsonl`
由清扫器删除，保证无显性 SPEC 的车道产物（code-fix / admin-global /
code-review 等）不无限堆积。归属活跃 SPEC 的产物不适用本条（归上一
Requirement 保护）；逐文件删除记日志。

#### Scenario: 超龄无主产物被清理
- **WHEN** `runs/archive/` 存在 mtime 15 天前、归属无任何活跃 SPEC 的
  `code-fix-<...>.jsonl`，清扫器执行
- **THEN** 该文件被删除且日志可查

#### Scenario: 未超龄无主产物保留
- **WHEN** 同类无主产物 mtime 距今 13 天
- **THEN** 该文件保留

#### Scenario: 活跃 SPEC 同名产物不受兜底影响
- **WHEN** `runs/archive/` 存在活跃 SPEC `foo` 的产物且 mtime 30 天前
- **THEN** 该文件保留（SPEC 归档时才清理，兜底只针对无主产物）
