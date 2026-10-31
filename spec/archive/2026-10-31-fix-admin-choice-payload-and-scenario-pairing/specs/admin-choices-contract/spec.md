## ADDED Requirements

### Requirement: Administrator 处置记录 choice_payload 载荷通道

处置记录 MUST 支持结构化 `choice_payload` 键（字符串，内容为 JSON 载荷），作为 Administrator 向裁决执行器传递动作载荷的唯一直传通道：`AdminDisposition` MUST 携带 `choice_payload` 字段并随 final 记录透传落盘；`_apply_choice_execution` 调用 `execute_adjudication_choice` 时，`note` 参数 MUST 优先取 `choice_payload`（非空即整体直传，MUST NOT 经 `actions_taken` 文本拼接或长度截断）；仅当 `choice_payload` 为空且所选选项非 payload 必需时，`note` 维持现状传依据文本（`actions_taken` 截断 200 字）。

#### Scenario: 载荷经通道直达执行器
- **WHEN** Administrator 处置 `inconclusive_loop` 信号并选择 `revise_scenario_reverify`，处置记录写入 `choice_id` 与含完整场景集的 `choice_payload`
- **THEN** 框架自动执行以 `choice_payload` 原文作为 `note` 调用执行器，载荷解析成功、动作执行成功（成对写回场景文件并复位重验），告警闭环留痕

#### Scenario: 非载荷选项行为不变
- **WHEN** Administrator 选择无需载荷的选项（如 `manual_fixed_reverify`）且处置记录无 `choice_payload`
- **THEN** `note` 维持既有依据文本形态，动作执行与留痕行为与本变更前一致

#### Scenario: 人工路径不受影响
- **WHEN** 人工经 Dashboard alert-resolve 端点裁决同一信号（note 从请求体传入）
- **THEN** 端点行为不变（本变更不触碰 alert-resolve 通道）

### Requirement: 载荷必需选项缺载荷 fail-closed 硬门

处置产物硬门（对齐既有「admin 未写处置文件 / result 非法」fail-closed 先例，位于处置消费收口处）MUST 新增分支：处置记录 `choice_id` 指向注册表声明 `requires_payload` 的选项、且 `choice_payload` 缺失或为空时，该次处置 MUST 判失败（success 折算 False），错误信息 MUST 点名缺口（指出该选项需要 `choice_payload` JSON 载荷及契约形态），MUST NOT 折算为 resolved 类假收口；关联升级信号 MUST 保持未处理（可重试裁决）。`choice_payload` 存在但内容非法时，按执行器既有载荷解析失败路径拒绝（告警保持未处理），不新增第二道内容校验门。

#### Scenario: 缺载荷判失败不假收口
- **WHEN** 处置记录填 `choice_id=revise_scenario_reverify` 但无 `choice_payload` 键
- **THEN** 处置产物硬门判失败，错误信息点名「该选项需要 choice_payload JSON 载荷」，处置不记 resolved，escalation 告警保持未处理状态可重试

#### Scenario: 合法载荷正常放行
- **WHEN** 处置记录同时含 `choice_id=revise_scenario_reverify` 与合法 `choice_payload`
- **THEN** 硬门放行，自动执行照常进行

### Requirement: 场景修订必走载荷路径禁止越道手改

`agents/administrator.md` 处置契约 MUST 增补：需要修订场景定义或夹具供给层文件时，Administrator MUST 将修订后的完整场景集（及可选夹具文件）以 `choice_payload` JSON 载荷随 `choice_id=revise_scenario_reverify` 提交，由执行器白名单路径成对写回 `test_scenarios.json` 与 `_scenarios_full.json`；MUST NOT 绕开执行器直接编辑场景定义文件、全量备份或夹具供给层文件。契约 MUST 说明理由：单独手改单侧文件会破坏成对一致，旧定义可经「无理由缺场景补齐」分支回填复辟。

#### Scenario: 修订经载荷路径成对落盘
- **WHEN** Administrator 判定验证失败源于场景定义缺陷并需修订
- **THEN** 处置记录含 `choice_id=revise_scenario_reverify` 与完整场景集 `choice_payload`，执行器成对写回后 `test_scenarios.json` 与 `_scenarios_full.json` 定义一致，未产生直接编辑

#### Scenario: 契约明文禁止越道手改
- **WHEN** 审阅 `agents/administrator.md` 的裁决选项消费契约段
- **THEN** 含「场景/夹具修订 MUST 经 choice_payload 载荷路径、MUST NOT out-of-band 手改场景定义与夹具文件」的明文约束及配对一致理由说明
