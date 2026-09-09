# scenario-write-schema-gate 能力规范

## ADDED Requirements

### Requirement: 场景三文件写端结构校验门
系统对场景相关三文件的任何写入端 MUST 执行与读端 `load_scenarios` 同源的结构校验，非法条目 MUST 拒绝落盘。覆盖写入点包括：planner 产物收编写回（`_apply_scenario_freeze`）、无理由缺失补齐写回、`scenarios.json` 持久化写回（`save_scenario_set`）、`_scenarios_full.json` 备份更新。校验失败时 MUST 留痕（日志 + 验证报告场景集变更小节），且 MUST NOT 将非法条目写入任何一份文件。

#### Scenario: 补齐写回含非法条目被拦截
- **WHEN** 补齐逻辑准备将一个缺少 `kind` 或 `steps` 的条目写入 `test_scenarios.json`
- **THEN** 写入被拒绝，该条目不落盘，日志记录 ERROR 级留痕，验证流程不因拦截本身中断

#### Scenario: 合法写入正常放行
- **WHEN** 写入端收到的场景列表全部通过结构校验（每条含 `id`/`kind`/`steps` 等必填字段）
- **THEN** 写入正常执行，落盘内容与校验通过内容一致

#### Scenario: 三文件写入共用同一校验
- **WHEN** 任一写入端（收编写回 / 补齐写回 / `save_scenario_set` / 备份更新）收到场景数据
- **THEN** 全部经过同一个结构校验函数，不存在绕过校验的写入路径

### Requirement: 补齐占位改弃场景
无理由缺失场景补齐时，若备份 `_scenarios_full.json` 中不存在该场景的完整定义，系统 MUST NOT 写入仅含 `id`/`description` 的最小占位条目；MUST 改为将该场景登记为「定义不可恢复」，从本轮验证集剔除，并在日志与验证报告场景集变更小节留痕（剔除场景 id 清单）。若备份存在完整定义，MUST 照常补回。

#### Scenario: 备份缺定义时剔除而非写占位
- **WHEN** planner 无理由缺失场景 X，且 `_scenarios_full.json` 中无 X 的完整定义
- **THEN** X 不被写入 `test_scenarios.json`，验证以剩余场景继续，变更小节记录「场景 X 定义不可恢复已剔除」

#### Scenario: 备份有定义时正常补回
- **WHEN** planner 无理由缺失场景 X，且备份中存在 X 的完整合法定义
- **THEN** X 从备份补回 `test_scenarios.json`，验证集完整

### Requirement: 持久化集加载净化
`load_scenario_set` 读入 `scenarios.json` 时 MUST 剔除缺少 `kind` 的孤儿条目（无 kind 条目无法路由到任何 Runner），并输出 WARNING 级告警留痕（含剔除条目 id 清单）。净化结果 MUST NOT 静默。

#### Scenario: 加载含孤儿条目的持久化集
- **WHEN** `scenarios.json` 中存在 7 条仅有 `id`/`description` 无 `kind` 的条目
- **THEN** 加载返回的集合不含这 7 条，日志含 WARNING 告警列出被剔除的 id

#### Scenario: 净化不污染原文件
- **WHEN** 加载净化发生剔除
- **THEN** `scenarios.json` 原文件不被加载过程改写（净化只影响内存集合；文件修正由写端门与清理任务负责）
