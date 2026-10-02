## ADDED Requirements

### Requirement: 契约模板态前置信号

框架周期巡检在 spec 尚未进入验证消费（状态为 ready 或 implementing）时，检测项目验证契约是否处于「文件存在但不可解析」的模板态；命中则前置写 `verify_contract_missing` 信号唤起 Administrator 起草，使契约起草与实现阶段并行而非在验证消费点串行阻塞。

#### Scenario: ready spec 撞上全注释模板

WHEN 项目存在状态为 ready 或 implementing 的 spec，且 `.fenix/verify.yaml` 文件存在、经 yaml 解析不产生顶层映射（全注释模板即此形态）
THEN 巡检写一条 `verify_contract_missing` 信号，spec 字段为该 spec 名，description 注明「前置预检：验证契约仍为未裁决模板态」，evidence 含项目根与契约路径

#### Scenario: 有效契约不触发

WHEN 项目存在状态为 ready 或 implementing 的 spec，且 `.fenix/verify.yaml` 可解析为顶层映射（含实质 prepare/regression 或 serve 段）
THEN 巡检不写任何契约信号

#### Scenario: 契约文件缺失不触发

WHEN 项目存在状态为 ready 或 implementing 的 spec，且 `.fenix/verify.yaml` 文件不存在
THEN 巡检不写契约信号（维持「无契约回退」既定语义，前置预检不扩大触发面）

#### Scenario: 已进入验证消费的 spec 不重复触发

WHEN 项目的 spec 状态为 testing 或之后状态且契约仍为模板态
THEN 前置检测器不写信号（该形态由验证消费期轻量自证 fail-fast 与其信号通道负责，两段互斥不双发）

#### Scenario: 信号在途期间契约被修正

WHEN 前置信号已写入但尚未唤起，且 `.fenix/verify.yaml` 已被修正为可解析契约
THEN 既有前置探测（PREPROBE）判定诉求已满足，免唤起 Administrator，信号闭环