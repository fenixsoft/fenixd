# test-regression-declaration

## ADDED Requirements

### Requirement: verify.yaml 的 regression 段声明全量回归执行方式

框架 MUST 支持在 `.fenix/verify.yaml` 顶层新增可选 `regression` 段，声明项目全量回归如何执行与如何解析结果。`regression` 段缺省不存在时，框架 MUST 按「未配置全量回归」处理（不报错、不派发），项目页「测试回归」分面显示引导态。

`regression` 段字段：

- `cmd`（必填，字符串或 argv 列表）：执行全量回归的命令；经 shell（字符串）或 argv 直接执行（列表），cwd 为项目根。命令 MUST 产出 JUnit XML 结果文件。
- `output`（必填，字符串）：命令产出的 JUnit XML 文件路径（相对项目根）。
- `timeout_seconds`（可选，正整数，缺省 1800）：硬超时；超过则中止进程并按超时归类。
- `format`（可选，固定 `junit`，缺省 `junit`）：结果格式；本次仅支持 JUnit XML（跨语言统一标准）。
- `long_test_threshold_seconds`（可选，正数，缺省 10）：长耗时用例阈值；单用例耗时超过该值即计入「长耗时用例」表。

框架 MUST 对 `regression` 段做结构校验：`cmd` 与 `output` 缺失时该段视为无效（按「未配置」回退处理并记 WARNING），MUST NOT 因无效段导致 daemon 启动失败。

#### Scenario: 有效 regression 段被解析

- **WHEN** `.fenix/verify.yaml` 含 `regression: {cmd: "pytest --junit-xml=.fenix/regression/junit.xml", output: ".fenix/regression/junit.xml", timeout_seconds: 900, long_test_threshold_seconds: 5}`
- **THEN** `load_verify_contract` 返回的契约对象携带解析后的 `regression` 规格（cmd、output、timeout=900、threshold=5）

#### Scenario: 缺省阈值取 10 秒

- **WHEN** `regression` 段只声明 `cmd` 与 `output`，未声明 `long_test_threshold_seconds`
- **THEN** 解析后的阈值 MUST 为 10

#### Scenario: 无 regression 段按未配置处理

- **WHEN** `.fenix/verify.yaml` 存在但无 `regression` 段
- **THEN** 契约对象的 `regression` 为 None，框架按「未配置全量回归」处理，不报错

#### Scenario: 无效 regression 段（缺 cmd 或 output）

- **WHEN** `regression` 段存在但缺 `cmd` 或缺 `output`
- **THEN** 该段视为无效，视同「未配置」，并记 WARNING 说明缺失字段

### Requirement: AI 自动起草 regression 段

框架 MUST 在既有验证契约自动起草流程（add-verify-contract-autodraft 通道）中，一并处理 `regression` 段：当 `verify.yaml` 无 `regression` 段（或文件整体缺失）时，administrator agent 起草的契约 MUST 包含探测到的 `regression` 段——即识别项目测试体系（语言、测试框架、测试目录、测试运行命令），生成能产出 JUnit XML 的 `cmd` 与对应 `output`，并据实测设定合理的 `timeout_seconds`。

起草产物 MUST 经 `bin/fenix_verify_contract.py <项目根>` 三段自证（prepare/serve/ready）后落位，全通才写盘。`regression` 段的自证为**独立可选校验**：`regression` 段存在时按 `cmd` 跑一次确认 `output` 产出可解析 JUnit XML，其失败 MUST 以省略该段收尾且 MUST NOT 改变三段自证的退出码与判定语义（prepare/serve/ready 三段未过即不落位，与现状一致——回归可跑 1800s，不得把既有自证门拖成小时级）。`regression` 段的探测失败（如项目无测试体系、命令产不出 JUnit XML）MUST 以省略该段收尾（`regression` 段为可选），不得臆造无效命令。

#### Scenario: 无 regression 段时起草补齐

- **WHEN** 项目 `verify.yaml` 的 prepare/serve/ready 齐全但无 `regression` 段，且触发了契约起草
- **THEN** 起草的契约 MUST 包含探测得出的 `regression` 段（cmd 产出 JUnit XML），且通过三段自证后落位

#### Scenario: 项目无测试体系时省略 regression 段

- **WHEN** 起草时探测不到任何测试体系
- **THEN** 起草的契约 MUST 省略 `regression` 段（而非写入无效命令），落位仍视为成功

### Requirement: 回归命令必须产出 JUnit XML 契约

框架 MUST 只按 JUnit XML 解析回归结果（`format: junit`）。声明 `regression.cmd` 的项目 MUST 保证该命令产出符合 JUnit XML 规范的 `output` 文件（含 `testsuites`/`testsuite`/`testcase` 结构，`testcase` 带 `time` 属性，失败带 `failure`/`error` 子元素，跳过带 `skipped`）。

框架 MUST NOT 假设被测项目用 Python/pytest；命令形态、测试目录、测试数量均由项目声明，框架仅消费 JUnit XML。

#### Scenario: 命令未产出 JUnit XML 文件

- **WHEN** `regression.cmd` 执行完毕但 `output` 路径不存在
- **THEN** 本次回归判为「结果不可解析」失败（结果快照 `status: "parse_error"` 并附原因），分面展示该错误而非空表
